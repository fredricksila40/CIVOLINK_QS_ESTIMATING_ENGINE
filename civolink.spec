# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification (Phase 21): CIVOLINK QS desktop app.

Build with:  pyinstaller civolink.spec
(no binary is committed; tests validate this spec statically and never
compile it).

Bundling notes (all paths below are relative to this file):
- Entry point is qs_engine/__main__.py (mode launcher; existing
  run_app.py / qs_engine.cli launchers stay untouched).
- Master-data JSON tables ship as data files (runtime reads them from
  the bundle); the default company profile ships likewise.
- reportlab needs no external font files (built-in Helvetica family);
  its subpackages travel via hidden imports below.
- The SQLite rate library needs no template file: RateLibrary creates
  its schema on first connect, so an empty template would be
  byte-identical to a fresh database.
- Reference PDFs under standards/ are documentation, not runtime
  assets, and are deliberately excluded to keep the bundle lean.
- Windows High-DPI: civolink.manifest (dpiAware true/pm,
  PerMonitorV2) is embedded via the EXE manifest argument below so
  the frozen exe renders natively crisp; live runs rely on the
  SetProcessDpiAwareness call in QSApp.__init__ instead.
"""

import os

# NOTE: SPECPATH is predefined by PyInstaller as this file's directory
# (do not reassign it); the test suite substitutes the engine root
# when validating bundled paths statically.

HIDDEN_IMPORTS = [
    # Web stack (background API serving from the desktop app).
    "fastapi",
    "starlette",
    "pydantic",
    "anyio",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "multipart",
    "httpx",
    # PDF generation (reportlab platypus document pipeline).
    "reportlab",
    "reportlab.lib",
    "reportlab.pdfbase",
    "reportlab.pdfgen",
    "reportlab.platypus",
    # Local persistence backend (stdlib, listed for explicitness).
    "sqlite3",
    # Offline license verification (Ed25519 via lazy import in the
    # Keygen adapter; listed so the frozen bundle carries it).
    "cryptography",
    # Branded Word export: scripts/ generators are loaded at runtime
    # via importlib (import boundary forbids static imports), so both
    # the office stack and its loader path stay invisible to Analysis.
    "docx",
    "lxml",
    # Phase 23 — Keygen licensing adapter: verify_signature() lazily
    # imports cryptography inside the function body (not visible to static
    # Analysis), so the full lazy-import chain must be declared here.
    "cryptography",
    "cryptography.exceptions",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.serialization",
    "cryptography.hazmat.primitives",
    "cffi",
    "pycparser",
    "qs_engine.licensing",
    "qs_engine.licensing.models",
    "qs_engine.licensing.provider",
    "qs_engine.licensing.service",
    "qs_engine.licensing.storage",
]

BUNDLED_DATA = [
    (os.path.join(SPECPATH, "qs_engine", "master_data", "tables",
                  "*.json"),
     os.path.join("qs_engine", "master_data", "tables")),
    (os.path.join(SPECPATH, "config", "company_profile.json"),
     "config"),
    (os.path.join(SPECPATH, "scripts", "*.py"), "scripts"),
]

block_cipher = None

#: Windows application manifest declaring native High-DPI awareness
#: (dpiAware true/pm + PerMonitorV2); embedded into CIVOLINK-QS.exe.
APP_MANIFEST = os.path.join(SPECPATH, "civolink.manifest")

a = Analysis(
    [os.path.join(SPECPATH, "qs_engine", "__main__.py")],
    pathex=[SPECPATH],
    binaries=[],
    datas=BUNDLED_DATA,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
                name="CIVOLINK-QS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest=APP_MANIFEST,
)
