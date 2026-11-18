import json
import os
import random
import subprocess
import sys
import uuid

import pytest

from faro_reconciliation import demo, report, store
from faro_reconciliation.contracts import ROOT, ReconciliationError, digest
from faro_reconciliation.fixtures import (
    Bundle,
    event,
    invoices_for,
    manual,
    statement,
    write_bundle,
)
from faro_reconciliation.transport import FileFeed, HttpFeed, ingest, simulator

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    if not os.getenv("FARO2_DB_PASSWORD"):
        pytest.fail("Set FARO2_DB_PASSWORD for integration tests or use the native runner")
    with store.connect() as connection:
        store.initialize(connection)
        yield connection


@pytest.fixture
def setup(conn, tmp_path):
    case = "test-" + uuid.uuid4().hex[:12]
    limits = manual(tmp_path / "inputs")
    bundle = Bundle(tmp_path / "inputs")
    feed = FileFeed(bundle.manifest["dataset_sha256"], bundle.events)
    store.prepare(conn, case, bundle)
    return case, bundle, feed, limits


def test_http_retries_and_complete_file_oracle(conn, setup):
    case, _, feed, _ = setup
    with simulator(feed, faults=True) as url:
        result = ingest(conn, case, HttpFeed(url, feed.feed_id), page_size=5)
    assert result["retries"] == {"429": 1, "500": 1}
    assert result["processed_n"] == len(feed.events)
    snapshot = report.snapshot(conn, case)
    assert demo.verify_oracle(snapshot)["false_closures"] == 0
    invoice_states = {r["invoice_id"]: r["coverage_state"] for r in snapshot["invoices"]}
    assert [invoice_states[key] for key in ("syn_i2", "syn_i3", "syn_i8", "syn_i10")] == [
        "partially_covered",
        "overpaid",
        "uncovered",
        "covered",
    ]
    first = report.detail(conn, case, "syn_p1")["receipts"][0]
    assert first["received_at"].utcoffset().total_seconds() == 0


def test_page_effect_and_checkpoint_rollback_together(conn, setup):
    case, _, feed, _ = setup
    with pytest.raises(store.Interrupted):
        ingest(conn, case, feed, page_size=3, failpoint="before_commit")
    assert store.cursor(conn, case, feed.feed_id) == 0
    assert (
        conn.execute(
            "SELECT count(*) n FROM recon.raw_delivery WHERE case_id=%s", (case,)
        ).fetchone()["n"]
        == 0
    )
    assert not report.snapshot(conn, case)["movements"]
    with pytest.raises(store.Interrupted):
        ingest(conn, case, feed, page_size=3, failpoint="after_commit")
    assert store.cursor(conn, case, feed.feed_id) == 3
    assert report.snapshot(conn, case)["movements"]
    ingest(conn, case, feed, page_size=5)
    assert ingest(conn, case, feed)["processed_n"] == 0
    assert demo.verify_oracle(report.snapshot(conn, case))["false_closures"] == 0


def test_repeated_partial_retries_and_conflict_rollback_of_provisional_effect(conn, setup):
    case, _, feed, limits = setup
    ingest(conn, case, feed, page_size=2, until=limits["pending"])
    pending = report.detail(conn, case, "syn_p1")
    assert pending["event_states"]["syn_1_refund"] == "pending_dependency"
    assert pending["event_states"]["syn_1_alias"] == "duplicate_effect"
    assert sum(row["event_id"] == "syn_1_a" for row in pending["receipts"]) == 2
    positions = [index for index, row in enumerate(feed.events) if row["event_id"] == "syn_6_a"]
    ingest(conn, case, feed, page_size=3, until=positions[0] + 1)
    assert report.detail(conn, case, "syn_p6")["expected_minor"] == 9000
    ingest(conn, case, feed, page_size=3, until=positions[1] + 1)
    assert report.detail(conn, case, "syn_p6")["expected_minor"] == 0
    assert (
        len(
            [
                row
                for row in report.detail(conn, case, "syn_p6")["receipts"]
                if row["event_id"] == "syn_6_a"
            ]
        )
        == 2
    )


def test_final_projection_is_equal_in_many_arrival_orders(conn, setup):
    case, bundle, feed, _ = setup
    ingest(conn, case, feed, page_size=3)
    expected = digest(report.snapshot(conn, case))
    for seed in (3, 7, 11):
        events = bundle.events.copy()
        random.Random(seed).shuffle(events)
        alt = case + str(seed)
        store.prepare(conn, alt, bundle)
        ingest(conn, alt, FileFeed(digest(events), events), page_size=4)
        assert digest(report.snapshot(conn, alt)) == expected


def test_resolution_requires_evidence_and_records_role(conn, setup):
    case, _, feed, limits = setup
    ingest(conn, case, feed, until=limits["mismatch"])
    with pytest.raises(ReconciliationError, match="reconciled"):
        store.resolution(conn, case, demo.decision())
    ingest(conn, case, feed)
    with pytest.raises(ReconciliationError, match="Evidence"):
        store.resolution(conn, case, {**demo.decision(), "evidence_effect_id": "syn_e_3_a"})
    assert store.resolution(conn, case, demo.decision())
    assert not store.resolution(conn, case, demo.decision())
    final = report.detail(conn, case, "syn_p1")
    assert final["difference_minor"] == 0 and final["audit"][-1]["actor"] == "analista_faro"


def test_duplicate_effect_in_different_lots_blocks_both(conn, setup):
    case, _, feed, _ = setup
    ingest(conn, case, feed)
    old = report.detail(conn, case, "syn_p2")
    assert old["state"] == "reconciled"
    cross = event(3, "cross", "capture", 4000, business_effect_id="syn_e_2_a")
    ingest(conn, case, FileFeed("append", [cross]))
    for lot in ("syn_p2", "syn_p3"):
        current = report.detail(conn, case, lot)
        assert current["state"] == "exception"
        assert "business_effect_conflict" in {i["code"] for i in current["issues"]}


def test_invalid_unassigned_input_is_retained_and_blocks_case(conn, setup):
    case, _, feed, _ = setup
    ingest(conn, case, feed)
    ingest(conn, case, FileFeed("bad", [["malformed"]]))
    assert report.snapshot(conn, case)["unassigned_issues"]
    assert {r["state"] for r in report.snapshot(conn, case)["payouts"]} == {"exception"}
    with pytest.raises(ReconciliationError, match="unassigned"):
        store.resolution(conn, case, demo.decision())


def test_malformed_event_cannot_hide_prior_identity(conn, setup):
    case, _, feed, _ = setup
    ingest(conn, case, feed)
    malformed = {**event(2, "a", "capture", 4000), "currency": "USD"}
    ingest(conn, case, FileFeed("bad", [malformed]))
    payout = report.detail(conn, case, "syn_p2")
    assert payout["state"] == "exception" and payout["expected_minor"] == 0
    assert {"event_payload_conflict", "invalid_currency"} <= {
        issue["code"] for issue in payout["issues"]
    }


def test_separate_revision_feed_preserves_original_statement(conn, tmp_path):
    case = "revision-" + uuid.uuid4().hex[:8]
    write_bundle(
        tmp_path,
        invoices_for(1),
        ["syn_p1"],
        [event(1, "a", "capture", 6000), statement(1, 5900)],
        2026,
        "revision",
    )
    bundle = Bundle(tmp_path)
    store.prepare(conn, case, bundle)
    ingest(conn, case, FileFeed(bundle.manifest["dataset_sha256"], bundle.events))
    issue = report.queue(conn, case, report.snapshot(conn, case))[0]
    late = statement(1, 6000, role="revised", ref="syn_e_1_payout")
    ingest(conn, case, FileFeed("revision", [late]))
    assert store.resolution(
        conn,
        case,
        {
            "payout_id": "syn_p1",
            "issue_id": issue["issue_id"],
            "actor": "tester",
            "reason": "Valid revision from processor",
            "evidence_effect_id": "syn_e_1_revised",
        },
    )
    payout = report.detail(conn, case, "syn_p1")
    assert payout["event_states"]["syn_1_payout"] == "superseded"
    assert len(payout["receipts"]) == 3


def test_cli_demo_generates_auditable_static_consumer(conn, tmp_path):
    case = "cli-" + uuid.uuid4().hex[:8]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "faro_reconciliation.cli",
            "demo",
            "--case",
            case,
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_sha256"] == manifest["file_rebuild_sha256"]
    for name in ("index.html", "payouts.csv", "exceptions.csv", "invoices.csv"):
        assert (tmp_path / name).exists()


def test_late_catalog_reference_replays_pending_events(conn, setup):
    case, _, feed, _ = setup
    ingest(conn, case, feed)
    invoice = {**invoices_for(1)[0], "invoice_id": "syn_missing"}
    assert report.detail(conn, case, "syn_p5")["event_states"]["syn_5_a"] == "pending_dependency"
    assert store.register_catalog(conn, case, invoice=invoice)
    assert not store.register_catalog(conn, case, invoice=invoice)
    assert report.detail(conn, case, "syn_p5")["state"] == "reconciled"
    new_lot = FileFeed(
        "late-lot", [event(11, "a", "capture", 1000, invoice_id="syn_i1"), statement(11, 1000)]
    )
    ingest(conn, case, new_lot)
    assert report.detail(conn, case, "syn_p11")["event_states"]["syn_11_a"] == "pending_dependency"
    assert store.register_catalog(conn, case, payout_id="syn_p11")
    assert report.detail(conn, case, "syn_p11")["state"] == "reconciled"
