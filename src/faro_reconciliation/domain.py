"""Deterministic projections from immutable variants and explicit dependencies."""

from collections import defaultdict
from dataclasses import dataclass, field

from .contracts import digest, economic_body


@dataclass
class Lot:
    payout_id: str
    state: str = "provisional"
    expected_minor: int = 0
    declared_minor: int | None = None
    difference_minor: int | None = None
    statement_effect_id: str | None = None
    finalized: bool = False
    issues: list = field(default_factory=list)
    event_states: dict = field(default_factory=dict)
    movements: list = field(default_factory=list)

    def issue(self, code, subject, state="rejected", *, blocking=True):
        self.issues.append({"code": code, "subject": subject, "blocking": blocking})
        if subject in self.event_states:
            self.event_states[subject] = state


def movement(event, signed, invoice_delta):
    return {
        "effect_id": event["business_effect_id"],
        "payout_id": event["payout_id"],
        "invoice_id": event["invoice_id"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "signed_minor": signed,
        "invoice_delta_minor": invoice_delta,
        "reference_effect_id": event["reference_effect_id"],
    }


def choose_effects(result, variants):
    grouped = defaultdict(list)
    ambiguous = {v["body"]["business_effect_id"] for v in variants if v["event_collision"]}
    for variant in variants:
        event = variant["body"]
        key = event["event_id"]
        result.event_states[key] = "received"
        if variant["event_collision"]:
            if not any(i["subject"] == key for i in result.issues):
                result.issue("event_payload_conflict", key)
        else:
            grouped[event["business_effect_id"]].append(variant)

    selected = {}
    for effect_id, matches in grouped.items():
        signatures = {digest(economic_body(item["body"])) for item in matches}
        if (
            effect_id in ambiguous
            or len(signatures) != 1
            or any(item["cross_lot_effect"] for item in matches)
        ):
            for item in matches:
                result.issue("business_effect_conflict", item["body"]["event_id"])
            continue
        ordered = sorted((item["body"] for item in matches), key=lambda e: e["event_id"])
        selected[effect_id] = ordered[0]
        for duplicate in ordered[1:]:
            result.event_states[duplicate["event_id"]] = "duplicate_effect"
    return selected


def resolve_statement(result, declarations):
    if not declarations:
        return
    successors = defaultdict(list)
    for effect_id, event in declarations.items():
        parent = event["reference_effect_id"]
        if parent is not None and parent not in declarations:
            result.issue("missing_statement_predecessor", event["event_id"], "pending_dependency")
        successors[parent].append(effect_id)
    if any(i["code"] == "missing_statement_predecessor" for i in result.issues):
        return
    if len(successors[None]) != 1 or any(len(items) > 1 for items in successors.values()):
        result.issue("ambiguous_statement_chain", result.payout_id)
        return
    current = successors[None][0]
    visited = set()
    while current not in visited:
        visited.add(current)
        children = successors.get(current)
        if not children:
            break
        current = children[0]
    if len(visited) != len(declarations):
        result.issue("ambiguous_statement_chain", result.payout_id)
        return
    active = declarations[current]
    result.declared_minor = active["amount_minor"]
    result.statement_effect_id = current
    result.finalized = active["finalized"]
    for eid, event in declarations.items():
        result.event_states[event["event_id"]] = "applied" if eid == current else "superseded"


def apply_movements(result, effects, invoice_ids):
    originals = {}
    refunds = defaultdict(list)
    reversals = defaultdict(list)
    for effect_id, event in effects.items():
        key = event["event_id"]
        kind = event["event_type"]
        if event["invoice_id"] is not None and event["invoice_id"] not in invoice_ids:
            result.issue("missing_invoice", key, "pending_dependency")
        elif kind == "reversal":
            reversals[event["reference_effect_id"]].append(event)
        elif kind != "payout":
            originals[effect_id] = event
            if kind == "refund":
                refunds[event["reference_effect_id"]].append(event)

    pairs = {}
    for target_id, candidates in reversals.items():
        target = originals.get(target_id)
        for event in candidates:
            key = event["event_id"]
            if target is None:
                result.issue("missing_reversal_target", key, "pending_dependency")
            elif (
                event["amount_minor"] != target["amount_minor"]
                or event["invoice_id"] != target["invoice_id"]
            ):
                result.issue("inconsistent_reversal", key)
            else:
                pairs.setdefault(target_id, []).append(event)
    active_reversals = {}
    for target_id, candidates in pairs.items():
        if len(candidates) == 1:
            active_reversals[target_id] = candidates[0]
        else:
            for event in candidates:
                result.issue("multiple_reversals", event["event_id"])

    blocked_refunds = set()
    for capture_id, candidates in refunds.items():
        capture = originals.get(capture_id)
        valid = []
        for event in candidates:
            key = event["event_id"]
            if capture is None:
                result.issue("missing_capture", key, "pending_dependency")
                blocked_refunds.add(event["business_effect_id"])
            elif capture["event_type"] != "capture" or capture["invoice_id"] != event["invoice_id"]:
                result.issue("incompatible_capture", key)
                blocked_refunds.add(event["business_effect_id"])
            else:
                valid.append(event)
        active = [e for e in valid if e["business_effect_id"] not in active_reversals]
        if capture and active and capture_id in active_reversals:
            reversal = active_reversals.pop(capture_id)
            result.issue("capture_has_active_refunds", reversal["event_id"])
        if capture and sum(e["amount_minor"] for e in active) > capture["amount_minor"]:
            for event in active:
                result.issue("refunds_exceed_capture", event["event_id"])
                blocked_refunds.add(event["business_effect_id"])

    for effect_id, event in originals.items():
        if effect_id in blocked_refunds:
            reversal = active_reversals.get(effect_id)
            if reversal:
                result.issue(
                    "reversal_target_not_applied", reversal["event_id"], "pending_dependency"
                )
            continue
        kind = event["event_type"]
        signed = event["amount_minor"] * (1 if kind == "capture" else -1)
        invoice_delta = signed if kind != "fee" else 0
        result.movements.append(movement(event, signed, invoice_delta))
        result.event_states[event["event_id"]] = "applied"
        reversal = active_reversals.get(effect_id)
        if reversal:
            result.movements.append(movement(reversal, -signed, -invoice_delta))
            result.event_states[reversal["event_id"]] = "applied"


def project(payout_id, variants, invoice_ids, known, malformed=()):
    result = Lot(payout_id)
    selected = choose_effects(result, variants)
    for entry in malformed:
        result.issue(entry["validation_error"], entry["subject"])
    if not known:
        result.issue("unknown_payout", payout_id)
        for event_id, state in result.event_states.items():
            if state == "received":
                result.event_states[event_id] = "pending_dependency"
    else:
        declarations = {k: v for k, v in selected.items() if v["event_type"] == "payout"}
        resolve_statement(result, declarations)
        apply_movements(result, selected, invoice_ids)
    result.expected_minor = sum(m["signed_minor"] for m in result.movements)
    if result.declared_minor is not None:
        result.difference_minor = result.declared_minor - result.expected_minor
    for event_id, state in result.event_states.items():
        if state == "received":
            result.event_states[event_id] = "pending_dependency"
    if result.finalized and result.difference_minor != 0:
        result.issue("payout_mismatch", payout_id)
    if result.issues:
        result.state = (
            "exception"
            if result.finalized
            or any(
                result.event_states.get(i["subject"]) != "pending_dependency" for i in result.issues
            )
            else "provisional"
        )
    elif result.finalized:
        result.state = "reconciled"
    result.issues.sort(key=lambda i: (i["code"], i["subject"]))
    result.movements.sort(key=lambda m: m["effect_id"])
    return result
