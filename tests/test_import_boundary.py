"""Dependency-boundary test: qs_engine product code must stay independent.

Uses AST analysis, so docstrings/comments never count — only real import
statements in non-test modules. Forbidden: office libraries, the frozen
document engine, SOCS, UI frameworks.
"""

import ast
from pathlib import Path

FORBIDDEN_MODULES = (
    "docx",
    "openpyxl",
    "scripts",
    "branding",
    "tkinter",
    "pyqt",
    "pyside",
    "socs",
)

# Phase 11: openpyxl is permitted ONLY inside qs_engine/adapters/
# (presentation sinks). Everywhere else it stays forbidden.
OPENPYXL_ALLOWED_UNDER = ("adapters",)
# Phase 13: GUI toolkits permitted ONLY inside qs_engine/ui/ (views).
# Controllers stay toolkit-free so the suite runs headless.
GUI_MODULES = ("tkinter", "pyqt", "pyside", "customtkinter")
GUI_ALLOWED_UNDER = ("ui",)

# Product package lives beside this tests/ directory (extracted layout).
QS_ROOT = Path(__file__).parent.parent / "qs_engine"


def _imported_modules(path: Path):
    """Yield top-level module names from real AST import nodes."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module.split(".")[0]


def test_no_forbidden_imports():
    violations = []
    for path in sorted(QS_ROOT.rglob("*.py")):
        if "tests" in path.relative_to(QS_ROOT).parts:
            continue  # the suite itself may reference frozen code for regression
        rel_parts = path.relative_to(QS_ROOT).parts
        for module in _imported_modules(path):
            lowered = module.lower()
            if (lowered == "openpyxl"
                    and OPENPYXL_ALLOWED_UNDER[0] in rel_parts):
                continue  # adapter-scoped presentation dependency
            if (lowered in GUI_MODULES
                    and GUI_ALLOWED_UNDER[0] in rel_parts):
                continue  # UI-layer view toolkit
            if lowered in FORBIDDEN_MODULES:
                violations.append(f"{path.name}: imports {module!r}")
    assert violations == [], f"Forbidden imports in qs_engine: {violations}"


def test_openpyxl_stays_out_of_core():
    """openpyxl must not leak beyond adapters/: core, master_data,
    contracts, trade engines, rates, and boq stay dependency-free."""
    outside = []
    for path in sorted(QS_ROOT.rglob("*.py")):
        rel_parts = path.relative_to(QS_ROOT).parts
        if "adapters" in rel_parts:
            continue
        for module in _imported_modules(path):
            if module.lower() == "openpyxl":
                outside.append(path.name)
    assert outside == [], f"openpyxl leaked outside adapters/: {outside}"


def test_gui_toolkit_stays_in_views():
    """GUI toolkits must not leak beyond qs_engine/ui/views.py:
    controllers stay toolkit-free so the suite runs headless.

    The sanctioned overlay-widget companion (qs_engine/ui/widgets.py,
    imported by views.py) shares the views.py toolkit allowance.
    """
    outside = []
    for path in sorted(QS_ROOT.rglob("*.py")):
        rel_parts = path.relative_to(QS_ROOT).parts
        if ("ui" in rel_parts
                and path.name in ("views.py", "widgets.py")):
            continue
        for module in _imported_modules(path):
            if module.lower() in GUI_MODULES:
                outside.append(path.name)
    assert outside == [], f"GUI toolkit leaked outside views.py: {outside}"


def test_controllers_import_no_toolkit():
    """Controllers module AST must contain zero GUI imports."""
    import ast as _ast
    path = QS_ROOT / "ui" / "controllers.py"
    tree = _ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    toolkits = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            toolkits.update(a.name.split(".")[0].lower()
                            for a in node.names)
        elif isinstance(node, _ast.ImportFrom) and node.module:
            toolkits.add(node.module.split(".")[0].lower())
    assert not (toolkits & set(GUI_MODULES)), (
        f"controllers.py imports GUI toolkit: {toolkits & set(GUI_MODULES)}")
