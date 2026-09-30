"""CIVOLINK QS CLI: command-line interface for the Estimating Engine.

Provides a read-only dashboard summary and session commands without
requiring a display. Uses master-data tables for verification status
aggregation; never invents unverified figures.
"""

from __future__ import annotations

import sys
from pathlib import Path

from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.ui.session import TakeoffSession


def _aggregate_verification(repo: MasterDataRepository) -> dict[str, int]:
    """Count verification_status across EVERY master-data domain.

    Returns a dict with keys: VERIFIED, NEEDS_VERIFICATION, PROVISIONAL.
    Domains come from repository.domains() so new tables are counted
    automatically — the dashboard never under-reports unverified data.
    """
    counts: dict[str, int] = {
        "VERIFIED": 0,
        "NEEDS_VERIFICATION": 0,
        "PROVISIONAL": 0,
    }
    for domain in repo.domains():
        records = repo.list(domain)
        for rec in records:
            vs = rec.get("verification_status", "NEEDS_VERIFICATION")
            if vs in counts:
                counts[vs] += 1
    return counts


def _format_dashboard(session: TakeoffSession, repo: MasterDataRepository) -> str:
    """Build a read-only dashboard summary string."""
    verification = _aggregate_verification(repo)
    total_records = verification["VERIFIED"] + verification["NEEDS_VERIFICATION"] + verification["PROVISIONAL"]
    lines = [
        "=" * 50,
        "CIVOLINK QS Estimating Engine — Dashboard",
        "=" * 50,
        f"Take-off lines: {session.summary_counts()['lines']}",
        "",
        "Master-data verification status:",
        f"  VERIFIED:   {verification['VERIFIED']}",
        f"  NEEDS_VERIFICATION: {verification['NEEDS_VERIFICATION']}",
        f"  PROVISIONAL: {verification['PROVISIONAL']}",
        f"  Total records: {total_records}",
        "",
        "Status: read-only; no unverified figures invented.",
        "=" * 50,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CIVOLINK QS CLI.

    Usage:
        python -m qs_engine.cli       # print dashboard to stdout
    """
    if argv is None:
        argv = sys.argv[1:]
    repo = MasterDataRepository()
    session = TakeoffSession()
    if not argv or argv[0] in ("--help", "-h", "--dashboard", "-d"):
        print(_format_dashboard(session, repo))
        return 0
    print("Unknown argument; use --help or --dashboard/-d.")
    return 2


if __name__ == "__main__":
    sys.exit(main())