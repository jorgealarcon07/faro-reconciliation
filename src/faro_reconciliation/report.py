"""Repeatable operational metrics, exports and offline review."""

import csv
import html
import json
from collections import Counter
from pathlib import Path

from . import store
from .contracts import NAMESPACE, ROOT, ReconciliationError, digest, now, write_json


def snapshot(conn, case_id):
    rows = store.payout_rows(conn, case_id)
    case_issues = store.global_issues(conn, case_id)
    if case_issues:
        for lot in rows:
            lot["state"] = "exception"
    return {
        "payouts": [{k: v for k, v in item.items() if k != "case_id"} for item in rows],
        "invoices": conn.execute(
            "SELECT invoice_id,original_minor,net_collected_minor,"
            "coverage_difference_minor,coverage_state FROM recon.invoice_coverage WHERE case_id=%s ORDER BY invoice_id",
            (case_id,),
        ).fetchall(),
        "movements": conn.execute(
            "SELECT effect_id,payout_id,invoice_id,event_id,event_type,signed_minor,"
            "invoice_delta_minor,reference_effect_id FROM recon.movements WHERE case_id=%s ORDER BY effect_id",
            (case_id,),
        ).fetchall(),
        "unassigned_issues": [
            {k: v for k, v in item.items() if k != "opened_at"} for item in case_issues
        ],
    }


def detail(conn, case_id, payout_id):
    lot = next(
        (row for row in store.payout_rows(conn, case_id) if row["payout_id"] == payout_id), None
    )
    if not lot:
        raise ReconciliationError("Payout not found")
    lot["unassigned_issues"] = store.global_issues(conn, case_id)
    if lot["unassigned_issues"]:
        lot["state"] = "exception"
    lot["movements"] = conn.execute(
        "SELECT * FROM recon.movements WHERE case_id=%s AND payout_id=%s ORDER BY effect_id",
        (case_id, payout_id),
    ).fetchall()
    lot["receipts"] = conn.execute(
        "SELECT receipt_id,position,checksum,event_id,feed_id,received_at,"
        "validation_error FROM recon.raw_delivery WHERE case_id=%s AND payout_id=%s ORDER BY receipt_id",
        (case_id, payout_id),
    ).fetchall()
    lot["audit"] = conn.execute(
        "SELECT * FROM recon.audit WHERE case_id=%s AND payout_id=%s ORDER BY audit_id",
        (case_id, payout_id),
    ).fetchall()
    return lot


def queue(conn, case_id, state):
    first_seen = {}
    for row in conn.execute(
        "SELECT payout_id,evidence,recorded_at FROM recon.audit "
        "WHERE case_id=%s AND action='projection' ORDER BY audit_id",
        (case_id,),
    ):
        for issue in row["evidence"]["issues"]:
            key = store.issue_key(row["payout_id"], issue)
            first_seen.setdefault(key, row["recorded_at"].isoformat())
    issues = []
    for lot in state["payouts"]:
        for issue in lot["issues"]:
            key = store.issue_key(lot["payout_id"], issue)
            issues.append(
                {
                    **issue,
                    "issue_id": key,
                    "payout_id": lot["payout_id"],
                    "currency": "COP",
                    "opened_at": first_seen.get(key, ""),
                    "difference_minor": lot["difference_minor"],
                }
            )
    for issue in store.global_issues(conn, case_id):
        issues.append(
            {
                **issue,
                "opened_at": issue["opened_at"].isoformat(),
                "issue_id": store.issue_key(None, issue),
                "payout_id": None,
                "currency": "COP",
                "difference_minor": None,
                "blocking": True,
            }
        )
    return sorted(
        issues, key=lambda i: (i["opened_at"], -abs(i["difference_minor"] or 0), i["issue_id"])
    )


def metrics(conn, case_id, state, issues):
    delivery = conn.execute(
        """
        SELECT count(*) AS receipts, count(*) FILTER(WHERE validation_error IS NOT NULL) AS invalid,
               count(DISTINCT checksum) AS unique_payloads
        FROM recon.raw_delivery WHERE case_id=%s
        """,
        (case_id,),
    ).fetchone()
    statuses = Counter(lot["state"] for lot in state["payouts"])
    event_states = Counter(
        label for lot in state["payouts"] for label in lot["event_states"].values()
    )
    ages = [
        max(0, (_utc(now()) - _utc(item["opened_at"])).total_seconds())
        for item in issues
        if item["opened_at"]
    ]
    return {
        **delivery,
        "identical_payload_repeats": delivery["receipts"] - delivery["unique_payloads"],
        "lot_states": dict(statuses),
        "lots": len(state["payouts"]),
        "event_states": dict(event_states),
        "open_issues": len(issues),
        "oldest_issue_seconds": max(ages, default=0),
        "absolute_unexplained_minor": sum(
            abs(lot["difference_minor"] or 0)
            for lot in state["payouts"]
            if lot["state"] == "exception"
        ),
        "movements": len(state["movements"]),
    }


def _utc(text):
    from datetime import datetime

    return datetime.fromisoformat(text)


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export(conn, case_id, folder, focus="syn_p1"):
    # Readers see one snapshot even if another client commits a page while generating the report.
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        state = snapshot(conn, case_id)
        issues = queue(conn, case_id, state)
        counts = metrics(conn, case_id, state, issues)
        focus_exists = any(lot["payout_id"] == focus for lot in state["payouts"])
        payload = {
            "case": case_id,
            "source_namespace": NAMESPACE,
            "data_kind": "synthetic",
            "currency": "COP",
            "exponent": 2,
            "generated_at": now(),
            "data_sha256": digest(state),
            "metrics": counts,
            "exceptions": issues,
            "snapshot": state,
            "detail": detail(conn, case_id, focus) if focus_exists else None,
        }
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "reconciliation.json", payload)
    write_csv(
        folder / "payouts.csv",
        state["payouts"],
        [
            "payout_id",
            "state",
            "expected_minor",
            "declared_minor",
            "difference_minor",
            "finalized",
            "statement_effect_id",
        ],
    )
    write_csv(
        folder / "exceptions.csv",
        issues,
        [
            "issue_id",
            "payout_id",
            "code",
            "subject",
            "blocking",
            "currency",
            "opened_at",
            "difference_minor",
        ],
    )
    write_csv(
        folder / "invoices.csv",
        state["invoices"],
        [
            "invoice_id",
            "original_minor",
            "net_collected_minor",
            "coverage_difference_minor",
            "coverage_state",
        ],
    )
    template = (ROOT / "assets/report.html").read_text(encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=False, default=str).replace("<", "\\u003c")
    (folder / "index.html").write_text(
        template.replace("@@CASE@@", html.escape(case_id)).replace("@@PAYLOAD@@", encoded),
        encoding="utf-8",
    )
    return payload


def baseline_naive(events, payout_id):
    matching = [e for e in events if e["payout_id"] == payout_id]
    signed = {"capture": 1, "refund": -1, "fee": -1}
    expected = sum(e["amount_minor"] * signed.get(e["event_type"], 0) for e in matching)
    declared = next(
        (e["amount_minor"] for e in reversed(matching) if e["event_type"] == "payout"), None
    )
    return {
        "expected_minor": expected,
        "declared_minor": declared,
        "difference_minor": None if declared is None else declared - expected,
    }
