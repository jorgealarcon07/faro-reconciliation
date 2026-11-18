import json
import random

import pytest

from faro_reconciliation.contracts import ReconciliationError, event_error, minor_units
from faro_reconciliation.domain import project
from faro_reconciliation.fixtures import Bundle, bulk, event, manual, statement


def normalized(events):
    return [{"body": e, "event_collision": False, "cross_lot_effect": False} for e in events]


@pytest.mark.parametrize("amount,units", [("10", 1000), ("0.01", 1), ("100.10", 10010)])
def test_minor_units(amount, units):
    assert minor_units(amount) == units


@pytest.mark.parametrize("bad", ["0.001", "nan", "1e2", "-1", "12,00", 1.1])
def test_amount_rejects_rounding_and_ambiguous_inputs(bad):
    with pytest.raises(ReconciliationError):
        minor_units(bad)


@pytest.mark.parametrize(
    "fields",
    [
        {"amount_minor": True},
        {"amount_minor": -1},
        {"currency": "USD"},
        {"schema_version": "2.0"},
        {"occurred_at": "2026-01-01T00:00:00+00:00"},
        {"payout_id": None},
    ],
)
def test_contract_rejects_invalid_events(fields):
    assert event_error(event(1, "a", "capture", 6000, **fields))


def test_currency_units_and_duplicate_economic_effect_in_many_orders():
    capture = event(1, "a", "capture", 6000)
    second = event(1, "b", "capture", 4000)
    alias = {**capture, "event_id": "syn_alias"}
    refund = event(1, "r", "refund", 1000, ref="syn_e_1_b")
    initial = statement(1, 8600, members=("a", "b", "r", "fee"))
    revised = statement(
        1, 8700, role="revision", ref="syn_e_1_payout", members=("a", "b", "r", "fee")
    )
    fee = event(1, "fee", "fee", 300, invoice=False)
    events = [capture, alias, second, refund, fee, initial, revised]
    rng = random.Random(1)
    for _ in range(20):
        rng.shuffle(events)
        result = project("syn_p1", normalized(events), {"syn_i1"}, True)
        assert result.state == "reconciled"
        assert result.expected_minor == 8700
        assert sum(row["invoice_delta_minor"] for row in result.movements) == 9000
        assert len(result.movements) == 4


def test_statement_fork_never_arbitrarily_selects_a_winner():
    initial = statement(1, 6000)
    one = statement(1, 6000, role="new", ref="syn_e_1_payout")
    two = statement(1, 5600, role="fork", ref="syn_e_1_payout")
    lot = project(
        "syn_p1", normalized([event(1, "a", "capture", 6000), initial, one, two]), {"syn_i1"}, True
    )
    assert lot.state == "exception"
    assert lot.declared_minor is None


def test_reversal_of_refund_restores_the_original_capture():
    rows = [
        event(1, "a", "capture", 4000),
        event(1, "r", "refund", 3000, ref="syn_e_1_a"),
        event(1, "rev", "reversal", 3000, ref="syn_e_1_r"),
        statement(1, 4000, members=("a", "r", "rev")),
    ]
    lot = project("syn_p1", normalized(rows), {"syn_i1"}, True)
    assert lot.expected_minor == 4000 and lot.state == "reconciled"


def test_capture_reversal_with_active_refund_is_blocked():
    rows = [
        event(1, "a", "capture", 4000),
        event(1, "r", "refund", 1000, ref="syn_e_1_a"),
        event(1, "rev", "reversal", 4000, ref="syn_e_1_a"),
        statement(1, 0),
    ]
    lot = project("syn_p1", normalized(rows), {"syn_i1"}, True)
    assert "capture_has_active_refunds" in {issue["code"] for issue in lot.issues}
    assert lot.expected_minor == 3000 and lot.state == "exception"


def test_fixture_determinism_and_hash_gate(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    manual(first)
    manual(second)
    assert Bundle(first).manifest == Bundle(second).manifest
    path = first / "deliveries.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ReconciliationError, match="modified fixture"):
        Bundle(first)


def test_fixture_file_contains_no_personal_fields(tmp_path):
    bulk(tmp_path, 100, profile="mixed")
    bundle = Bundle(tmp_path)
    assert len(bundle.invoices) == 100
    assert all("card" not in json.dumps(row) for row in bundle.events)


def test_matching_zero_cannot_close_a_lot_missing_offsetting_movements():
    payout = statement(1, 0, members=("a", "rev"))
    lot = project("syn_p1", normalized([payout]), {"syn_i1"}, True)
    assert lot.difference_minor == 0 and lot.state == "exception"
    assert {issue["subject"] for issue in lot.issues} == {"syn_e_1_a", "syn_e_1_rev"}
