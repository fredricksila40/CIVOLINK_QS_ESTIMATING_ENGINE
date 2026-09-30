"""Frozen-engine regression: proves the Corporate Document Engine is untouched.

1. SHA256 of every frozen file must match the Phase 0 baseline.
2. Frozen commercial totals must still compute (existing behaviour intact).
3. Frozen quotation_logic must contain no QS/engineering logic (no coupling).
"""

import hashlib
import os
from decimal import Decimal
from pathlib import Path

import pytest


def _edmolt_root() -> Path:
    """Locate the sibling EDMOLT checkout (override via CIVOLINK_EDMOLT_ROOT)."""
    override = os.environ.get("CIVOLINK_EDMOLT_ROOT")
    if override:
        return Path(override)
    return (Path(__file__).parent.parent.parent.parent / "EDMOLT"
            / "EDMOLT_CORPORATE_DOCUMENT_SYSTEM")


PROJECT_ROOT = _edmolt_root()

requires_edmolt_checkout = pytest.mark.skipif(
    not PROJECT_ROOT.is_dir(),
    reason=f"EDMOLT checkout not found at {PROJECT_ROOT} "
           f"(set CIVOLINK_EDMOLT_ROOT to override)",
)

# Baseline captured at Phase 0 start (Get-FileHash SHA256).
FROZEN_BASELINE = {
    "scripts/quotation_logic.py":
        "EDF0DEFF51ED939DFEF3F9E17FBC1D47516F146C16B766A1EDA3A3EDBACCCF64",
    "scripts/document_base.py":
        "22D05A3B0EA53F946B3AAC03FA86F6C5DF77C1B0D68BAC7EA594CACFBCBC4287",
    "scripts/quotation_word.py":
        "F930EB365F4213FD0E2980976E89F625C98CFB30839A27217CABCF7E5F641C4E",
    "scripts/invoice_word.py":
        "75796E4315B01E6E3DB5BB93809D23E9D82CB362406FF3160D53FE870921AA55",
    "scripts/purchase_order_word.py":
        "4A6AE875746D193C60341DEB0222B1CB8A94E6CD82F63C8D9CBD8C2F9D8C06FF",
    "scripts/branding.py":
        "662C99F478A079932C5F8F723E0B550E080537072AA82682BC6A5A7E0041FDC3",
    "config/brand_config.json":
        "F177733AB7008B26ADD02A8A22491CCBE58816D0933F7CEFCCE4FE43C5A09F18",
}


@requires_edmolt_checkout
def test_frozen_files_unmodified():
    for rel, expected in FROZEN_BASELINE.items():
        path = PROJECT_ROOT / rel
        assert path.exists(), f"Frozen file missing: {rel}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        assert actual == expected, f"Frozen file modified: {rel}"


@requires_edmolt_checkout
def test_frozen_commercial_totals_intact():
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.quotation_logic import (
        create_sample_invoice,
        create_sample_purchase_order,
        create_sample_quotation,
    )
    assert create_sample_quotation().grand_total == Decimal("4083200.00")
    assert create_sample_invoice().grand_total == Decimal("2592600.00")
    assert create_sample_purchase_order().grand_total == Decimal("3323400.00")


@requires_edmolt_checkout
def test_frozen_logic_has_no_qs_coupling():
    text = (PROJECT_ROOT / "scripts/quotation_logic.py").read_text(encoding="utf-8")
    for token in ("density", "wastage", "concrete class", "dry_volume",
                  "mortar", "rebar", "tonnage", "qs_engine"):
        assert token not in text.lower(), f"QS coupling in frozen logic: {token!r}"
