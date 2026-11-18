"""Deterministic synthetic input. Expected outcomes exist separately in tests/oracles."""

import csv
import hashlib
import json
import random
from pathlib import Path

from .contracts import (
    NAMESPACE,
    VERSION,
    ReconciliationError,
    digest,
    encode,
    identifier,
    validate,
    write_json,
)

DATE = "2026-01-01T10:00:00Z"
FILES = ("invoices.jsonl", "lots.json", "payouts.csv", "deliveries.jsonl")


def event(number, role, kind, amount, invoice=True, ref=None, finalized=None, **overrides):
    return {
        "namespace": NAMESPACE,
        "schema_version": VERSION,
        "event_type": kind,
        "event_id": f"syn_{number}_{role}",
        "business_effect_id": f"syn_e_{number}_{role}",
        "invoice_id": f"syn_i{number}" if invoice else None,
        "payout_id": f"syn_p{number}",
        "amount_minor": amount,
        "currency": "COP",
        "occurred_at": DATE,
        "received_at": DATE,
        "reference_effect_id": ref,
        "finalized": finalized,
        "expected_effect_ids": None,
        **overrides,
    }


def statement(number, amount, *, final=True, role="payout", ref=None, members=("a",)):
    return event(
        number,
        role,
        "payout",
        amount,
        invoice=False,
        finalized=final,
        ref=ref,
        expected_effect_ids=sorted(f"syn_e_{number}_{member}" for member in members),
    )


def write_bundle(directory, invoices, lots, deliveries, seed, scenario):
    directory.mkdir(parents=True, exist_ok=True)
    for name, records in (("invoices.jsonl", invoices), ("deliveries.jsonl", deliveries)):
        with (directory / name).open("w", encoding="utf-8", newline="\n") as stream:
            for item in records:
                stream.write(encode(item) + "\n")
    write_json(directory / "lots.json", lots)
    with (directory / "payouts.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "delivery_position",
                "payout_id",
                "statement_effect_id",
                "declared_minor",
                "finalized",
                "supersedes_effect_id",
                "expected_effect_ids",
            ]
        )
        for position, item in enumerate(deliveries):
            if isinstance(item, dict) and item.get("event_type") == "payout":
                writer.writerow(
                    [
                        position,
                        item["payout_id"],
                        item["business_effect_id"],
                        item["amount_minor"],
                        str(item["finalized"]).lower(),
                        item["reference_effect_id"] or "",
                        encode(item["expected_effect_ids"]),
                    ]
                )
    checksums = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in FILES
    }
    manifest = {
        "seed": seed,
        "scenario": scenario,
        "source_namespace": NAMESPACE,
        "data_kind": "synthetic",
        "license": "CC0-1.0",
        "sha256": checksums,
        "dataset_sha256": digest(checksums),
    }
    write_json(directory / "source.json", manifest)
    return manifest


def invoices_for(count):
    return [
        {
            "namespace": NAMESPACE,
            "invoice_id": f"syn_i{n}",
            "currency": "COP",
            "original_minor": 10_000,
        }
        for n in range(1, count + 1)
    ]


def manual(directory):
    cap_a = event(1, "a", "capture", 6000)
    cap_b = event(1, "b", "capture", 4000)
    early = [
        event(1, "refund", "refund", 1000, ref="syn_e_1_b"),
        cap_a,
        cap_a,
        event(1, "alias", "capture", 6000, business_effect_id="syn_e_1_a"),
        event(1, "fee", "fee", 300, invoice=False),
        statement(1, 8600, members=("a", "b", "refund", "fee")),
    ]
    late = [cap_b]
    corrected = [
        statement(
            1, 8700, role="revision", ref="syn_e_1_payout", members=("a", "b", "refund", "fee")
        )
    ]
    conflict = event(6, "a", "capture", 9000)
    controls = [
        event(2, "a", "capture", 4000),
        statement(2, 4000),
        event(3, "a", "capture", 12000),
        statement(3, 12000),
        event(4, "a", "capture", 10000),
        statement(4, 10000, final=False),
        event(5, "a", "capture", 5000, invoice_id="syn_missing"),
        statement(5, 5000),
        conflict,
        {**conflict, "amount_minor": 8000},
        statement(6, 0),
        event(7, "a", "capture", 4000),
        event(7, "r", "refund", 5000, ref="syn_e_7_a"),
        statement(7, 4000, members=("a", "r")),
        event(8, "rev", "reversal", 5000, ref="syn_e_8_a"),
        event(8, "a", "capture", 5000),
        statement(8, 0, members=("a", "rev")),
        event(9, "a", "capture", 10000),
        event(10, "a", "capture", 10000),
        event(10, "fee", "fee", 300, invoice=False),
        event(10, "rev", "reversal", 300, invoice=False, ref="syn_e_10_fee"),
        statement(10, 10000, members=("a", "fee", "rev")),
    ]
    write_bundle(
        directory,
        invoices_for(10),
        [f"syn_p{n}" for n in range(1, 11)],
        early + late + corrected + controls,
        2026,
        "manual",
    )
    return {"pending": len(early), "mismatch": len(early) + len(late)}


def bulk(directory, count, seed=2026, duplicate_every=13, profile="mixed"):
    if not 1 <= count <= 40_000:
        raise ReconciliationError("Supported synthetic size: 1–40000 invoices")
    if profile not in ("clean", "duplicates", "mixed"):
        raise ReconciliationError("Profile must be clean, duplicates or mixed")
    rng = random.Random(seed)
    deliveries = []
    for number in range(1, count + 1):
        amount = rng.randrange(7500, 10501)
        fee = rng.randrange(25, 300)
        discrepancy = 100 if profile == "mixed" and number % 100 == 0 else 0
        capture = event(number, "a", "capture", amount)
        group = [
            capture,
            event(number, "fee", "fee", fee, invoice=False),
            statement(number, amount - fee - discrepancy, members=("a", "fee")),
        ]
        if profile != "clean":
            if duplicate_every and number % duplicate_every == 0:
                group.append(capture)
            rng.shuffle(group)
        deliveries.extend(group)
    return write_bundle(
        directory,
        invoices_for(count),
        [f"syn_p{n}" for n in range(1, count + 1)],
        deliveries,
        seed,
        profile,
    )


class Bundle:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / "source.json").read_text())
        for key, expected in self.manifest["sha256"].items():
            if (
                key not in FILES
                or hashlib.sha256((self.directory / key).read_bytes()).hexdigest() != expected
            ):
                raise ReconciliationError("Unapproved or modified fixture: " + key)
        if (
            set(self.manifest["sha256"]) != set(FILES)
            or digest(self.manifest["sha256"]) != self.manifest["dataset_sha256"]
            or self.manifest.get("data_kind") != "synthetic"
            or self.manifest.get("source_namespace") != NAMESPACE
            or self.manifest.get("license") != "CC0-1.0"
            or type(self.manifest.get("seed")) is not int
        ):
            raise ReconciliationError("Invalid synthetic source manifest")
        self.invoices = self.read_lines("invoices.jsonl")
        for invoice in self.invoices:
            validate("invoice", invoice)
        self.lots = json.loads((self.directory / "lots.json").read_text())
        if not self.lots or not all(identifier(value) for value in self.lots):
            raise ReconciliationError("Invalid payout catalog")
        self.events = self.read_lines("deliveries.jsonl")
        self.check_statements()

    def read_lines(self, name):
        items = []
        with (self.directory / name).open(encoding="utf-8") as stream:
            for line in stream:
                if len(line) > 8192:
                    raise ReconciliationError("Fixture record exceeds 8 KiB")
                items.append(json.loads(line))
        return items

    def check_statements(self):
        expected = {}
        for position, item in enumerate(self.events):
            if isinstance(item, dict) and item.get("event_type") == "payout":
                validate("payout_statement", item)
                expected[position] = (
                    item["payout_id"],
                    item["business_effect_id"],
                    str(item["amount_minor"]),
                    str(item["finalized"]).lower(),
                    item["reference_effect_id"] or "",
                    encode(item["expected_effect_ids"]),
                )
        with (self.directory / "payouts.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        actual = {
            int(r["delivery_position"]): (
                r["payout_id"],
                r["statement_effect_id"],
                r["declared_minor"],
                r["finalized"],
                r["supersedes_effect_id"],
                r["expected_effect_ids"],
            )
            for r in rows
        }
        if actual != expected or len(actual) != len(rows):
            raise ReconciliationError("Statement CSV and receipts disagree")
