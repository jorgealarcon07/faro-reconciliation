"""PostgreSQL persistence. A page and its cursor are one transaction."""

import os
from collections import defaultdict
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import (
    ROOT,
    ReconciliationError,
    case_name,
    digest,
    event_body,
    event_error,
    identifier,
    validate,
)
from .domain import project


def connect():
    config = {}
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("FARO2_DB_") and "=" in line:
                name, value = line.split("=", 1)
                config[name] = value

    def setting(key, default):
        key = "FARO2_DB_" + key
        return os.getenv(key, config.get(key, default))

    password = setting("PASSWORD", "")
    if not password:
        raise ReconciliationError("Set FARO2_DB_PASSWORD for the project database")
    return psycopg.connect(
        host=setting("HOST", "127.0.0.1"),
        port=setting("PORT", "55433"),
        dbname=setting("NAME", "faro_reconcile"),
        user=setting("USER", "faro_reconcile"),
        password=password,
        connect_timeout=8,
        row_factory=dict_row,
        application_name="faro-reconciliation",
        autocommit=True,
    )


class Interrupted(ReconciliationError):
    """Fault injection for demo and recovery tests."""


def initialize(conn):
    with conn.transaction():
        conn.execute((ROOT / "sql/001_reconciliation.sql").read_text())


@contextmanager
def locked(conn, case_id):
    case_name(case_id)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 42002))", (case_id,))
        yield


def prepare(conn, case_id, bundle):
    with locked(conn, case_id):
        existing = conn.execute(
            "SELECT source_hash FROM recon.cases WHERE case_id=%s", (case_id,)
        ).fetchone()
        source_hash = bundle.manifest["dataset_sha256"]
        if existing:
            if existing["source_hash"] != source_hash:
                raise ReconciliationError("Case is bound to a different source manifest")
            return
        conn.execute(
            "INSERT INTO recon.cases(case_id,source_hash,seed) VALUES (%s,%s,%s)",
            (case_id, source_hash, bundle.manifest["seed"]),
        )
        conn.cursor().executemany(
            "INSERT INTO recon.invoices VALUES (%s,%s,%s)",
            [(case_id, row["invoice_id"], row["original_minor"]) for row in bundle.invoices],
        )
        conn.cursor().executemany(
            "INSERT INTO recon.lots VALUES (%s,%s)", [(case_id, lot) for lot in bundle.lots]
        )


def cursor(conn, case_id, feed_id):
    row = conn.execute(
        "SELECT next_cursor FROM recon.checkpoints WHERE case_id=%s AND feed_id=%s",
        (case_id, feed_id),
    ).fetchone()
    return row["next_cursor"] if row else 0


def audit(conn, case_id, payout_id, action, actor, reason, evidence):
    conn.execute(
        "INSERT INTO recon.audit(case_id,payout_id,action,actor,reason,evidence) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (case_id, payout_id, action, actor, reason, Jsonb(evidence)),
    )


def _store_receipts(conn, case_id, feed_id, current, events):
    receipts, variants = [], []
    event_ids, effect_ids, lot_ids = set(), set(), set()
    for position, payload in enumerate(events, current):
        payload_dict = payload if isinstance(payload, dict) else {}
        event_id = payload_dict.get("event_id")
        payout_id = payload_dict.get("payout_id")
        event_id = event_id if identifier(event_id) else None
        payout_id = payout_id if identifier(payout_id) else None
        reason = event_error(payload)
        receipts.append(
            (
                case_id,
                feed_id,
                position,
                Jsonb(payload),
                digest(payload),
                event_id,
                payout_id,
                reason,
            )
        )
        if payout_id:
            lot_ids.add(payout_id)
        if event_id:
            event_ids.add(event_id)
        if reason is None:
            body = event_body(payload)
            effect_id = body["business_effect_id"]
            effect_ids.add(effect_id)
            variants.append((case_id, event_id, digest(body), effect_id, payout_id, Jsonb(body)))
    with conn.cursor().copy(
        "COPY recon.raw_delivery(case_id,feed_id,position,payload,checksum,"
        "event_id,payout_id,validation_error) FROM STDIN"
    ) as copy:
        for receipt in receipts:
            copy.write_row(receipt)
    conn.cursor().executemany(
        "INSERT INTO recon.inbox_event VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", variants
    )
    connected = conn.execute(
        "SELECT DISTINCT payout_id FROM recon.inbox_event WHERE case_id=%s AND "
        "(event_id=ANY(%s) OR effect_id=ANY(%s))",
        (case_id, sorted(event_ids), sorted(effect_ids)),
    ).fetchall()
    return sorted(lot_ids | {row["payout_id"] for row in connected})


def _projection_inputs(conn, case_id, lots):
    candidates = conn.execute(
        """
        SELECT v.payout_id,v.body,
          (EXISTS(SELECT 1 FROM recon.inbox_event x WHERE x.case_id=v.case_id
             AND x.event_id=v.event_id AND x.variant_hash<>v.variant_hash)
           OR EXISTS(SELECT 1 FROM recon.raw_delivery r WHERE r.case_id=v.case_id
             AND r.event_id=v.event_id AND r.validation_error IS NOT NULL)) AS event_collision,
          EXISTS(SELECT 1 FROM recon.inbox_event x WHERE x.case_id=v.case_id
             AND x.effect_id=v.effect_id AND x.payout_id<>v.payout_id) AS cross_lot_effect
        FROM recon.inbox_event v WHERE v.case_id=%s AND v.payout_id=ANY(%s)
        ORDER BY v.payout_id,v.event_id,v.variant_hash
        """,
        (case_id, lots),
    ).fetchall()
    by_lot = defaultdict(list)
    for row in candidates:
        by_lot[row["payout_id"]].append(row)
    known = {
        r["payout_id"]
        for r in conn.execute(
            "SELECT payout_id FROM recon.lots WHERE case_id=%s AND payout_id=ANY(%s)",
            (case_id, lots),
        )
    }
    invoice_ids = {v["body"]["invoice_id"] for v in candidates if v["body"]["invoice_id"]}
    invoices = {
        r["invoice_id"]
        for r in conn.execute(
            "SELECT invoice_id FROM recon.invoices WHERE case_id=%s AND invoice_id=ANY(%s)",
            (case_id, sorted(invoice_ids)),
        )
    }
    malformed = defaultdict(list)
    for row in conn.execute(
        "SELECT DISTINCT payout_id,validation_error,coalesce(event_id,checksum) AS subject "
        "FROM recon.raw_delivery WHERE case_id=%s AND payout_id=ANY(%s) AND validation_error IS NOT NULL",
        (case_id, lots),
    ):
        malformed[row["payout_id"]].append(row)
    return [project(lot, by_lot[lot], invoices, lot in known, malformed[lot]) for lot in lots]


def _replace_projections(conn, case_id, results):
    lots = [result.payout_id for result in results]
    old = {
        row["payout_id"]: row
        for row in conn.execute(
            "SELECT payout_id,state,issues,event_states FROM recon.projections WHERE case_id=%s AND payout_id=ANY(%s)",
            (case_id, lots),
        )
    }
    conn.execute(
        "DELETE FROM recon.movements WHERE case_id=%s AND payout_id=ANY(%s)", (case_id, lots)
    )
    with conn.cursor().copy("COPY recon.movements FROM STDIN") as copy:
        for result in results:
            for movement in result.movements:
                copy.write_row((case_id, *movement.values()))
    conn.cursor().executemany(
        """
        INSERT INTO recon.projections VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(case_id,payout_id) DO UPDATE SET
          state=excluded.state, expected_minor=excluded.expected_minor,
          declared_minor=excluded.declared_minor, difference_minor=excluded.difference_minor,
          statement_effect_id=excluded.statement_effect_id, finalized=excluded.finalized,
          issues=excluded.issues, event_states=excluded.event_states
        """,
        [
            (
                case_id,
                r.payout_id,
                r.state,
                r.expected_minor,
                r.declared_minor,
                r.difference_minor,
                r.statement_effect_id,
                r.finalized,
                Jsonb(r.issues),
                Jsonb(r.event_states),
            )
            for r in results
        ],
    )
    entries = []
    for r in results:
        before = old.get(r.payout_id, {})
        if any(before.get(key) != getattr(r, key) for key in ("state", "issues", "event_states")):
            transitions = {
                key: [before.get("event_states", {}).get(key, "received"), state]
                for key, state in r.event_states.items()
                if before.get("event_states", {}).get(key) != state
            }
            entries.append(
                (
                    case_id,
                    r.payout_id,
                    "projection",
                    "processor",
                    "Recomputed from immutable receipts",
                    Jsonb(
                        {
                            "from_state": before.get("state"),
                            "state": r.state,
                            "previous_issues": before.get("issues", []),
                            "issues": r.issues,
                            "transitions": transitions,
                            "difference_minor": r.difference_minor,
                            "statement_effect_id": r.statement_effect_id,
                        }
                    ),
                )
            )
    conn.cursor().executemany(
        "INSERT INTO recon.audit(case_id,payout_id,action,actor,reason,evidence) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        entries,
    )


def commit_page(conn, case_id, feed_id, current, events, failpoint=None):
    with locked(conn, case_id):
        latest = cursor(conn, case_id, feed_id)
        if latest > current:
            return latest
        if latest != current:
            raise ReconciliationError("Page cursor does not match the committed checkpoint")
        lots = _store_receipts(conn, case_id, feed_id, current, events)
        if lots:
            _replace_projections(conn, case_id, _projection_inputs(conn, case_id, lots))
        if failpoint == "before_commit":
            raise Interrupted("Injected interruption before transaction commit")
        end = current + len(events)
        conn.execute(
            "INSERT INTO recon.checkpoints VALUES (%s,%s,%s) "
            "ON CONFLICT(case_id,feed_id) DO UPDATE SET next_cursor=excluded.next_cursor",
            (case_id, feed_id, end),
        )
    if failpoint == "after_commit":
        raise Interrupted("Injected interruption after commit and before caller acknowledgement")
    return end


def payout_rows(conn, case_id):
    return conn.execute(
        """
        SELECT * FROM recon.projections WHERE case_id=%s
        UNION ALL
        SELECT l.case_id,l.payout_id,'provisional',0,NULL,NULL,NULL,false,'[]'::jsonb,'{}'::jsonb
        FROM recon.lots l LEFT JOIN recon.projections p USING(case_id,payout_id)
        WHERE l.case_id=%s AND p.payout_id IS NULL
        ORDER BY payout_id
        """,
        (case_id, case_id),
    ).fetchall()


def global_issues(conn, case_id):
    return conn.execute(
        """
        SELECT validation_error AS code,checksum AS subject,min(received_at) AS opened_at
        FROM recon.raw_delivery WHERE case_id=%s AND payout_id IS NULL
        AND validation_error IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
        """,
        (case_id,),
    ).fetchall()


def resolution(conn, case_id, decision):
    validate("decision_record", decision)
    payout_id = decision["payout_id"]
    with locked(conn, case_id):
        if global_issues(conn, case_id):
            raise ReconciliationError("Case has unassigned invalid receipts")
        row = conn.execute(
            "SELECT * FROM recon.projections WHERE case_id=%s AND payout_id=%s",
            (case_id, payout_id),
        ).fetchone()
        if not row or row["state"] != "reconciled" or row["issues"]:
            raise ReconciliationError(
                "Resolution requires a reconciled payout with no active issues"
            )
        history = conn.execute(
            "SELECT audit_id,evidence FROM recon.audit WHERE case_id=%s AND payout_id=%s "
            "AND action='projection' ORDER BY audit_id DESC",
            (case_id, payout_id),
        ).fetchall()
        issue = next(
            (
                a["audit_id"]
                for a in history
                if any(
                    issue_key(payout_id, i) == decision["issue_id"] for i in a["evidence"]["issues"]
                )
            ),
            None,
        )
        if issue is None:
            raise ReconciliationError("This payout has no matching historical issue")
        evidence = decision["evidence_effect_id"]
        if (
            evidence != row["statement_effect_id"]
            and not conn.execute(
                "SELECT 1 FROM recon.movements WHERE case_id=%s AND payout_id=%s AND effect_id=%s",
                (case_id, payout_id, evidence),
            ).fetchone()
        ):
            raise ReconciliationError(
                "Evidence must be an applied effect or current statement for the payout"
            )
        if conn.execute(
            "SELECT 1 FROM recon.audit WHERE case_id=%s AND payout_id=%s AND action='resolution' "
            "AND evidence->>'issue_id'=%s AND evidence->>'issue_audit_id'=%s",
            (case_id, payout_id, decision["issue_id"], str(issue)),
        ).fetchone():
            return False
        audit(
            conn,
            case_id,
            payout_id,
            "resolution",
            decision["actor"],
            decision["reason"],
            {
                **decision,
                "issue_audit_id": issue,
                "state": row["state"],
                "difference_minor": row["difference_minor"],
            },
        )
    return True


def issue_key(payout_id, issue):
    return digest([payout_id, issue["code"], issue["subject"]])[:20]
