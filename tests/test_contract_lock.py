import hashlib
import json

from faro_reconciliation.contracts import ROOT
from faro_reconciliation.fixtures import Bundle


def test_contract_lock_matches_versioned_json_schemas():
    lock = json.loads((ROOT / "contracts.lock.json").read_text())
    paths = sorted((ROOT / "contracts/v1").glob("*.json"))
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == lock[
        "sha256"
    ]
    assert lock["version"] == "1.0.0"


def test_checked_in_input_hashes_survive_a_clean_checkout():
    bundle = Bundle(ROOT / "data/fixtures")
    assert len(bundle.invoices) == 10
