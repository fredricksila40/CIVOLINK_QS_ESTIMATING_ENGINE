# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['qs_engine/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[('qs_engine/master_data/tables/*.json', 'qs_engine/master_data/tables'), ('config/company_profile.json', 'config'), ('scripts/*.py', 'scripts')],
    hiddenimports=['fastapi', 'starlette', 'pydantic', 'anyio', 'uvicorn', 'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'multipart', 'httpx', 'reportlab', 'reportlab.lib', 'reportlab.pdfbase', 'reportlab.pdfgen', 'reportlab.platypus', 'sqlite3', 'docx', 'lxml', 'qs_engine.valuation', 'qs_engine.valuation.calculator', 'qs_engine.valuation.exporter', 'qs_engine.valuation.models', 'qs_engine.mixes', 'qs_engine.mixes.calculator'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CIVOLINK-QS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest='civolink.manifest',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CIVOLINK-QS',
)
