"""Persistence package (Phase 20): project files + rate library.

Single-file `.clk` project snapshots (compressed JSON) and the
SQLite master rate library. Pure stdlib plus engine DTOs — no widgets,
no web framework, no third-party office libraries.
"""

from .project_file import (
    SCHEMA_VERSION,
    ProjectFileAdapter,
    SessionState,
    load_session,
    save_session,
    state_from_dict,
    state_from_session,
)
from .rate_library import (
    CATEGORIES,
    CATEGORY_LABELS,
    CSV_COLUMNS,
    RateLibrary,
    default_library_path,
)

__all__ = [
    "SCHEMA_VERSION", "ProjectFileAdapter", "SessionState",
    "load_session", "save_session", "state_from_dict",
    "state_from_session", "CATEGORIES", "CATEGORY_LABELS",
    "CSV_COLUMNS", "RateLibrary", "default_library_path",
]
