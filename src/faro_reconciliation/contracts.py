"""Versioned interface and canonical serialization shared by both transports."""

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "payments_cop_synthetic"
VERSION = "1.0.0"


class ReconciliationError(Exception):
    """An input or operation requires review."""


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(obj):
    return hashlib.sha256(encode(obj).encode("utf-8")).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def schema(name):
    return json.loads((ROOT / "contracts/v1" / (name + ".schema.json")).read_text())


def validate(name, data):
    Draft202012Validator(schema(name), format_checker=FormatChecker()).validate(data)


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"syn_[A-Za-z0-9_-]{1,60}", value) is not None


def case_name(value):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value or ""):
        raise ReconciliationError(
            "Case ID must contain 1–80 letters, digits, underscores or hyphens"
        )
    return value


def minor_units(text):
    """Import a decimal string without rounding fractional minor units."""
    if not isinstance(text, str) or not re.fullmatch(r"\d{1,14}(\.\d{1,2})?", text):
        raise ReconciliationError("Expected a nonnegative COP amount with at most two decimals")
    return int(Decimal(text) * 100)


PAYMENT = Draft202012Validator(schema("payment_event"), format_checker=FormatChecker())


def event_error(event):
    error = next(PAYMENT.iter_errors(event), None)
    if error is not None:
        return "invalid_" + (str(error.path[0]) if error.path else "contract")
    if any(not event[key].endswith("Z") for key in ("occurred_at", "received_at")):
        return "invalid_utc_timestamp"
    kind = event["event_type"]
    if kind in ("capture", "refund") and not event["invoice_id"]:
        return "invoice_required"
    if kind in ("fee", "payout") and event["invoice_id"] is not None:
        return "unexpected_invoice"
    if kind in ("refund", "reversal") and not event["reference_effect_id"]:
        return "reference_required"
    if kind in ("capture", "fee") and event["reference_effect_id"]:
        return "unexpected_reference"
    if kind != "payout" and event["finalized"] is not None:
        return "unexpected_finality"
    if kind == "payout" and not isinstance(event["finalized"], bool):
        return "finality_required"
    if kind != "payout" and event["amount_minor"] == 0:
        return "zero_movement"
    return None


def event_body(event):
    return {key: value for key, value in event.items() if key != "received_at"}


def economic_body(event):
    return {
        key: value
        for key, value in event_body(event).items()
        if key not in ("event_id", "occurred_at")
    }
