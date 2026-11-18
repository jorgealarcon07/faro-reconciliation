"""Regenerate the small input and contract checksums after a reviewed interface change."""

import hashlib

from faro_reconciliation.contracts import ROOT, write_json
from faro_reconciliation.fixtures import manual


def main():
    contracts = ROOT / "contracts/v1"
    document = {
        "version": "1.0.0",
        "sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(contracts.glob("*.json"))
        },
    }
    write_json(ROOT / "contracts.lock.json", document)
    manual(ROOT / "data/fixtures")


if __name__ == "__main__":
    main()
