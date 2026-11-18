"""Measure the verified core on the 1k and optional 100k-delivery fixtures."""

import os
import platform
import threading
import time

import psutil

from faro_reconciliation import report, store
from faro_reconciliation.contracts import digest, write_json
from faro_reconciliation.fixtures import Bundle, bulk
from faro_reconciliation.transport import FileFeed, ingest


def sample_memory(stopped, readings):
    process = psutil.Process()
    while not stopped.wait(0.05):
        readings.append(process.memory_info().rss)


def query_plan(conn, case, payout, disable_indexes):
    with conn.transaction():
        if disable_indexes:
            conn.execute("SET LOCAL enable_indexscan=off")
            conn.execute("SET LOCAL enable_indexonlyscan=off")
            conn.execute("SET LOCAL enable_bitmapscan=off")
        return conn.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT effect_id,signed_minor "
            "FROM recon.movements WHERE case_id=%s AND payout_id=%s",
            (case, payout),
        ).fetchone()["QUERY PLAN"][0]


def run(conn, target, fixture_root, scale):
    results = []
    profiles = [(1000, "clean"), (1000, "duplicates"), (1000, "mixed")]
    if scale:
        profiles.append((32500, "mixed"))
    for count, profile in profiles:
        case = f"benchmark-{count}-{profile}"
        begin = time.perf_counter()
        path = fixture_root / case
        bulk(path, count, profile=profile)
        source = Bundle(path)
        prepare_seconds = time.perf_counter() - begin
        stopped = threading.Event()
        readings = [psutil.Process().memory_info().rss]
        thread = threading.Thread(target=sample_memory, args=(stopped, readings), daemon=True)
        thread.start()
        try:
            store.prepare(conn, case, source)
            stats = ingest(
                conn,
                case,
                FileFeed(source.manifest["dataset_sha256"], source.events),
                page_size=1000,
            )
            snapshot = report.snapshot(conn, case)
            queue = report.queue(conn, case, snapshot)
            counts = report.metrics(conn, case, snapshot, queue)
            expected = (
                {f"syn_p{n}" for n in range(100, count + 1, 100)} if profile == "mixed" else set()
            )
            observed = {
                row["payout_id"] for row in snapshot["payouts"] if row["state"] == "exception"
            }
            if (
                observed != expected
                or counts["movements"] != count * 2
                or stats["processed_n"] != len(source.events)
            ):
                raise AssertionError("Bulk oracle mismatch")
            for row in snapshot["payouts"]:
                difference = -100 if row["payout_id"] in expected else 0
                expected_state = "exception" if difference else "reconciled"
                if row["difference_minor"] != difference or row["state"] != expected_state:
                    raise AssertionError("Incorrect bulk payout state or amount")
            phases = {
                "case": case,
                "profile": profile,
                "invoices": count,
                "prepare_seconds": prepare_seconds,
                "input_sha256": source.manifest["dataset_sha256"],
                "data_sha256": digest(snapshot),
                "oracle": {
                    "expected_exception_lots": len(expected),
                    "correct_exception_lots": len(observed),
                    "false_closures": 0,
                    "false_exception_lots": 0,
                },
                "ingestion": stats,
                "metrics": counts,
            }
            if count == 32500:
                conn.execute("ANALYZE recon.movements")
                phases["explain"] = {
                    "indexed": query_plan(conn, case, "syn_p16000", False),
                    "forced_scan": query_plan(conn, case, "syn_p16000", True),
                }
        finally:
            stopped.set()
            thread.join()
        phases["peak_python_rss_bytes"] = max(readings)
        results.append(phases)
        write_json(
            target,
            {
                "system": platform.platform(),
                "python": platform.python_version(),
                "postgres": conn.execute("SHOW server_version").fetchone()["server_version"],
                "cpu_logical": os.cpu_count(),
                "ram_bytes": psutil.virtual_memory().total,
                "results": results,
            },
        )
        print(
            f"{case}: {stats['processed_n']} receipts, {stats['elapsed_seconds']:.2f}s, "
            f"{len(expected)} exceptions",
            flush=True,
        )
