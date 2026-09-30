"""Typed errors for the QS engine. Invalid inputs fail closed — never silent zero/NaN."""


class QSEngineError(Exception):
    """Base class for all QS engine errors."""


# --- Units ---------------------------------------------------------------

class UnitError(QSEngineError):
    """Base class for unit errors."""


class UnknownUnitError(UnitError):
    """Raised when a unit string is not in the supported registry."""


class IncompatibleUnitsError(UnitError):
    """Raised when a conversion is requested between incompatible dimensions."""


# --- Validation ----------------------------------------------------------

class ValidationError(QSEngineError):
    """Base class for input validation errors."""


class MissingFieldError(ValidationError):
    """Raised when a required field is absent."""


class NonPositiveDimensionError(ValidationError):
    """Raised when a dimension that must be > 0 is zero or negative."""


class NegativeQuantityError(ValidationError):
    """Raised when a quantity that must be >= 0 is negative."""


class NonPositiveDensityError(ValidationError):
    """Raised when a density that must be > 0 is zero or negative."""


class NegativeRateError(ValidationError):
    """Raised when a rate/cost that must be >= 0 is negative."""


class PercentageRangeError(ValidationError):
    """Raised when a percentage falls outside its declared valid range."""


class UnknownMasterDataDomainError(ValidationError):
    """Raised when a master-data domain name is not recognised."""


class UnknownMasterDataKeyError(ValidationError):
    """Raised when a master-data key does not exist in its domain table."""


class UnverifiedMasterDataError(ValidationError):
    """Raised when a calculation requires verified master data but the
    record is NEEDS_VERIFICATION (or its numerics are null) and no
    complete explicit overrides were supplied in the call context."""
