"""CIVOLINK licensing integration foundation.

Provider-neutral licensing boundary: the desktop application talks only
to LicensingProvider/LicensingService contracts. No provider SDK, no
network I/O, and no secrets live in this package — a future Keygen or
Cryptlex adapter implements LicensingProvider without touching callers.
See docs/LICENSING.md for the full architecture.
"""

from qs_engine.licensing.models import (
    LicenseInfo,
    LicenseState,
    ProviderResult,
    connection_display,
    expiration_display,
    license_display,
)
from qs_engine.licensing.provider import (
    FakeLicensingProvider,
    LicensingProvider,
    NullProvider,
)
from qs_engine.licensing.service import LicensingService
from qs_engine.licensing.storage import (
    LicenseStore,
    atomic_write_json,
    create_backup,
    default_license_dir,
    load_state,
    migrate_license_data,
    save_state,
    BACKUP_RETAIN_COUNT,
    CURRENT_SCHEMA_VERSION,
    FutureSchemaError,
    MIN_SUPPORTED_SCHEMA_VERSION,
)

__all__ = [
    "LicenseInfo",
    "LicenseState",
    "ProviderResult",
    "connection_display",
    "expiration_display",
    "license_display",
    "LicensingProvider",
    "FakeLicensingProvider",
    "NullProvider",
    "LicensingService",
    "LicenseStore",
    "atomic_write_json",
    "create_backup",
    "default_license_dir",
    "load_state",
    "migrate_license_data",
    "save_state",
    "BACKUP_RETAIN_COUNT",
    "CURRENT_SCHEMA_VERSION",
    "FutureSchemaError",
    "MIN_SUPPORTED_SCHEMA_VERSION",
]
