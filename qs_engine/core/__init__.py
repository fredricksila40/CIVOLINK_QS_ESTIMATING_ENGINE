"""QS core kernel: units, decimal policy, errors, validation, rounding, wastage, assumptions."""

from .errors import (
    QSEngineError,
    UnitError,
    UnknownUnitError,
    IncompatibleUnitsError,
    ValidationError,
    MissingFieldError,
    NonPositiveDimensionError,
    NegativeQuantityError,
    NonPositiveDensityError,
    NegativeRateError,
    PercentageRangeError,
    UnknownMasterDataDomainError,
    UnknownMasterDataKeyError,
    UnverifiedMasterDataError,
)
from .decimal_policy import MONEY_PLACES, to_decimal, quantize, quantize_money, apply_percentage
from .units import (
    MM, CM, M, MM2, M2, MM3, M3, LITRE,
    KG, TONNE, BAG, PIECE, PAIR, SET, SHEET, HOUR, DAY,
    SUPPORTED_UNITS, dimension_of, convert,
)
from .validation import (
    require_present,
    validate_dimension,
    validate_quantity,
    validate_density,
    validate_rate,
    validate_percentage,
    require_master_key,
)
from .rounding import ceiling_units, RoundingResult
from .wastage import apply_wastage, WastageResult
from .assumptions import VerificationStatus, AssumptionRecord, validate_assumption

__all__ = [
    "QSEngineError", "UnitError", "UnknownUnitError", "IncompatibleUnitsError",
    "ValidationError", "MissingFieldError", "NonPositiveDimensionError",
    "NegativeQuantityError", "NonPositiveDensityError", "NegativeRateError",
    "PercentageRangeError", "UnknownMasterDataDomainError", "UnknownMasterDataKeyError",
    "UnverifiedMasterDataError",
    "MONEY_PLACES", "to_decimal", "quantize", "quantize_money", "apply_percentage",
    "MM", "CM", "M", "MM2", "M2", "MM3", "M3", "LITRE",
    "KG", "TONNE", "BAG", "PIECE", "PAIR", "SET", "SHEET", "HOUR", "DAY",
    "SUPPORTED_UNITS", "dimension_of", "convert",
    "require_present", "validate_dimension", "validate_quantity",
    "validate_density", "validate_rate", "validate_percentage", "require_master_key",
    "ceiling_units", "RoundingResult",
    "apply_wastage", "WastageResult",
    "VerificationStatus", "AssumptionRecord", "validate_assumption",
]
