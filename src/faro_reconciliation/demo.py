"""Run the portfolio scenario through HTTP, faults, review and file replay."""

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

from . import report, store
from .contracts import (
    NAMESPACE,
    ROOT,
    VERSION,
    ReconciliationError,
    digest,
    now,
    validate,
    write_json,
)
from .fixtures import Bundle, manual
from .transport import FileFeed, HttpFeed, ingest, simulator


def decision():
    return {
        "payout_id": "syn_p1",
        "issue_id": store.issue_key("syn_p1", {"code": "payout_mismatch", "subject": "syn_p1"}),
        "actor": "analista_faro",
        "reason": "La declaración revisada coincide con captura, devolución y comisión.",
        "evidence_effect_id": "syn_e_1_revision",
    }


def verify_oracle(snapshot, path=None):
    oracle = json.loads((path or ROOT / "tests/oracles/manual.json").read_text(encoding="utf-8"))
    actual = {
        r["payout_id"]: [
            r["state"],
            r["expected_minor"],
            r["declared_minor"],
            r["difference_minor"],
            sorted({i["code"] for i in r["issues"]}),
        ]
        for r in snapshot["payouts"]
    }
    if actual != oracle["payouts"]:
        raise ReconciliationError("Manual payout oracle differs from persisted projections")
    invoices = {r["invoice_id"]: r["coverage_difference_minor"] for r in snapshot["invoices"]}
    if any(invoices[k] != v for k, v in oracle["coverage"].items()):
        raise ReconciliationError("Manual invoice oracle differs from persisted coverage")
    return {
        "payouts_checked": len(actual),
        "invoices_checked": len(oracle["coverage"]),
        "oracle_exception_lots": sum(r[0] == "exception" for r in actual.values()),
        "false_closures": 0,
    }


def run(conn, case_id, output):
    start = time.perf_counter()
    output = Path(output)
    bundle_dir = output / "fixture"
    limits = manual(bundle_dir)
    bundle = Bundle(bundle_dir)
    feed = FileFeed(bundle.manifest["dataset_sha256"], bundle.events)
    store.initialize(conn)
    store.prepare(conn, case_id, bundle)
    stages = {}
    with simulator(feed, faults=True) as url:
        client = HttpFeed(url, feed.feed_id)
        stages["pending"] = ingest(conn, case_id, client, page_size=2, until=limits["pending"])
        stages["pending"]["payout"] = report.detail(conn, case_id, "syn_p1")
        stages["mismatch"] = ingest(conn, case_id, client, page_size=2, until=limits["mismatch"])
        stages["mismatch"]["payout"] = report.detail(conn, case_id, "syn_p1")
        try:
            store.resolution(conn, case_id, decision())
        except ReconciliationError:
            stages["forced_close_blocked"] = True
        else:
            raise ReconciliationError("Resolution unexpectedly accepted before reconciliation")
        recoveries = []
        for fault in ("before_commit", "after_commit"):
            before = store.cursor(conn, case_id, feed.feed_id)
            try:
                ingest(conn, case_id, client, page_size=1, failpoint=fault)
            except store.Interrupted:
                after = store.cursor(conn, case_id, feed.feed_id)
                if after != before + int(fault == "after_commit"):
                    raise ReconciliationError(
                        "Fault injection checkpoint did not match transaction"
                    ) from None
                recoveries.append({"fault": fault, "before": before, "after": after})
            else:
                raise ReconciliationError("Expected interruption missing")
        stages["recovery"] = recoveries
        stages["completed"] = ingest(conn, case_id, client, page_size=4)
    if not store.resolution(conn, case_id, decision()):
        raise ReconciliationError("Demo requires a fresh case ID")
    payload = report.export(conn, case_id, output)
    fresh_case = case_id + "-rebuild"
    store.prepare(conn, fresh_case, bundle)
    ingest(conn, fresh_case, feed, page_size=40)
    fresh = report.snapshot(conn, fresh_case)
    if digest(fresh) != payload["data_sha256"]:
        raise ReconciliationError("File rebuild differs from incremental HTTP ingestion")
    stage_oracle = json.loads((ROOT / "tests/oracles/manual.json").read_text())["stages"]
    for name, expected in stage_oracle.items():
        actual = stages[name]["payout"]
        for key, value in expected.items():
            if key == "issue":
                if value not in {i["code"] for i in actual["issues"]}:
                    raise ReconciliationError("Interim exception was not detected")
            elif value != actual[key]:
                raise ReconciliationError(f"Interim oracle mismatch for {name}/{key}")
    oracle = verify_oracle(payload["snapshot"])
    git_executable = shutil.which("git")
    git = (
        subprocess.run(
            [git_executable, "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if git_executable
        else None
    )
    run_manifest = {
        "run_id": case_id,
        "source_namespace": NAMESPACE,
        "data_kind": "synthetic",
        "dataset_sha256": feed.feed_id,
        "git_sha": (git.stdout.strip() if git and git.returncode == 0 else "unversioned"),
        "contract_version": VERSION,
        "contract_lock_sha256": digest(json.loads((ROOT / "contracts.lock.json").read_text())),
        "seed": bundle.manifest["seed"],
        "as_of": now(),
        "rows": payload["metrics"]["receipts"],
        "data_sha256": payload["data_sha256"],
        "platform": platform.platform(),
        "postgres": conn.execute("SHOW server_version").fetchone()["server_version"],
        "elapsed_seconds": time.perf_counter() - start,
        "metrics": payload["metrics"],
        "oracle": oracle,
        "naive_baseline": report.baseline_naive(bundle.events, "syn_p1"),
        "stages": stages,
        "file_rebuild_sha256": digest(fresh),
    }
    validate("run_manifest", run_manifest)
    write_json(output / "manifest.json", run_manifest)
    return run_manifest
