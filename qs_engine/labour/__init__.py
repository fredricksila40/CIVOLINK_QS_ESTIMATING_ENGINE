"""Labour calculation engine (Phase 7).

Activity-based gang durations and costs with skilled:unskilled splits.
Hourly rates require an explicit hours_per_day; daily rates reject it.
Fail-closed on unverified master data unless complete overrides supplied.
"""

from .engine import (
    LABOUR_FIELDS,
    RECORD_KEYS,
    RATE_UNIT_DAY,
    RATE_UNIT_HOUR,
    LabourTradeOverride,
    calculate_labour_requirement,
    gang_cost_per_rate_unit,
    labour_duration_days,
    resolve_labour_trade,
)
from .results import LabourRequirement, ResolvedLabourTrade

__all__ = [
    "LABOUR_FIELDS", "RECORD_KEYS", "RATE_UNIT_DAY", "RATE_UNIT_HOUR",
    "LabourTradeOverride", "calculate_labour_requirement",
    "gang_cost_per_rate_unit", "labour_duration_days", "resolve_labour_trade",
    "LabourRequirement", "ResolvedLabourTrade",
]
