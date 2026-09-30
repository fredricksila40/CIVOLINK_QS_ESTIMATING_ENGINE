# CIVOLINK QS Estimating Engine — Architecture & Phase History

## 1. Project Overview

CIVOLINK QS Estimating Engine is a quantity-surveying workbench for
construction cost estimation: domain take-offs, composite rate
build-ups, bill-of-quantities (BOQ) compilation, tender
reconciliation, interim valuations, and branded document export —
exposed through both a native desktop UI and a REST API backed by the
same controller contracts.

## 2. Architecture

| Layer | Location | Notes |
|---|---|---|
| UI Layer | `qs_engine/ui` | Native Tkinter desktop shell (`views.py`), toolkit-free controllers (`controllers.py`), session store (`session.py`), render-ready view-models (`viewmodels.py`). Calculation never lives in widgets. |
| REST API Layer | `qs_engine/web` | FastAPI app (`api.py`) plus uvicorn launcher (`server.py`); interactive OpenAPI documentation at `/docs`. Thin HTTP facade — every endpoint delegates to the existing controllers. |
| Reporting Engine | `qs_engine/export` | ReportLab PDF exporter (`pdf_exporter.py`): formal BOQ summary and Interim Payment Certificate statements as print-ready bytes. |
| Valuation Engine | `qs_engine/valuation` | IPC engine (`ipc_engine.py`): work-to-date, gross certification, capped retention, advance recovery, and net payable. |
| Persistence Layer | `qs_engine/persistence` | `.clk` project files (compressed-JSON session snapshots, `project_file.py`) and the Master SQLite Rate Library (`rate_library.py`) for shared enterprise rates. |
| Material Override Layer | `qs_engine/resources` | Writable user material catalogue (`material_store.py`) and custom categories (`category_registry.py`) persisted to `data/user_materials.json` / `data/user_categories.json`, merged over the read-only seed by `MaterialResolver` (`material_resolver.py`) — a drop-in for `MasterDataRepository`. User records are identifiers only (`density` / `default_wastage_pct` NULL, `NEEDS_VERIFICATION`). |
| Excel Adapter | `qs_engine/adapters/excel` | Tender-schedule exporter with live formulas plus the tender reconciliation and variance engine. |
| Document Adapter | `qs_engine/adapters/document` | BOQ/rate payload DTOs, company-profile store, and the branded Word/PDF export bridge. |

### Precision Policy

Strict `Decimal` arithmetic across all currency, variance, and
take-off calculations. Binary floating point (`float` literals and
`float()` calls) is banned by an architecture-invariant test that
scans the entire `qs_engine/` tree. Monetary values travel as
exact strings through every DTO; rounding happens only at
presentation boundaries (half-up, 2dp) and unresolved amounts stay
explicit instead of being zero-filled.

### Dependency Boundaries

- `qs_engine` core never imports UI toolkits, office libraries, or the
  frozen document engine (AST-enforced by `test_import_boundary.py`).
- `openpyxl` is permitted only under `qs_engine/adapters/`;
  `tkinter` only inside `qs_engine/ui/views.py`.
- The calculation core stays independent of FastAPI, reportlab, and
  SQLite drivers, which live strictly in the web/export/persistence
  edge layers.

## 3. Milestone History Summary

- **Phase 1–16 — Core QS engines & desktop workbench.** Measurement,
  take-off (concrete, masonry, rebar, earthworks, finishes, labour,
  plant, haulage), composite rates, BOQ compilation, master-data
  governance, and the Tkinter workbench with project setup, rate
  builder, materials catalogue, and estimate dashboard.
- **Phase 17 — Excel Tender Exporter & Reconciliation Engine**
  (504 passing tests). Single-sheet tender schedules with live Amount
  formulas and honest `UNRESOLVED` totals, plus a row-by-row tender
  variance engine (quantity/rate/cost deltas, provisional-lump
  carryover, withheld-line policy) behind a dual-panel
  Export/Reconciliation page.
- **Phase 18 — FastAPI REST API & OpenAPI docs at `/docs`**
  (519 passing tests). Take-off, rate-build, BOQ-compile, and
  tender-reconcile endpoints over the unchanged controllers, plus a
  uvicorn launcher with foreground and desktop-background modes.
- **Phase 19 — PDF Exporter & IPC Valuation Engine**
  (536 passing tests). Exact-Decimal interim valuations (retention
  capped, advance recovery guarded) and formal BOQ-summary / IPC
  statement PDFs, with matching API streams and a Valuations & IPC
  page.
- **UI Polish & Navigation Fix** (555 passing tests). Project Setup
  grid realignment and a single-owner sidebar active-route sync
  (`active_route_key`), verified live across every route.
- **Phase 20 — Project File Persistence & Master SQLite Rate
  Library.** Compressed-JSON session snapshots with schema-version
  guard and recompiling hydration, alongside a transactional
  (all-or-nothing CSV sync) enterprise rate store with matching API
  and File-menu/desktop integrations.
- **File Extension Update** — Primary project extension shortened to
  `.clk` (CIVOLINK Project File) with full backward compatibility:
  legacy `.civolink` files carry the identical payload and remain
  readable everywhere (desktop dialogs, API uploads, adapter loads).
- **Phase 21 — Standalone Executable Packaging & High-DPI
  Integration** (568 passing tests). One-file windowed build
  (`pyinstaller civolink.spec --clean --noconfirm` →
  `dist/CIVOLINK-QS.exe`, `--help` smoke-tested at exit 0)
  with Per-Monitor V2 DPI awareness from both the embedded
  `civolink.manifest` (`dpiAware true/pm`) and a process-level
  `SetProcessDpiAwareness` call in `QSApp.__init__`; `sys.frozen`-aware
  path resolution so output, company-profile, and `scripts/`
  generator lookups target the executable directory (or bundled
  `_MEIPASS/scripts`) instead of the vanishing temp bundle; data
  bundling extended to `scripts/*.py` with `docx`/`lxml` hidden
  imports; pinned `requirements.txt`; Rate Builder fold optimization
  (actions in the meta row, side-by-side result grids, bounded table
  heights); window title aligned to `v1.4.2`; UI compaction grid
  system (`QSPanel` 2-column forms, paired admin/commercial grids,
  2-column readout cards) plus the PopoverGuide migration (static
  instruction banners replaced by `ℹ  Panel Guide` header popovers,
  reclaiming 101–151px per view across all 16 pages, with a `Help →
  Show Panel Instructions` global toggle); universal scrolling
  (recursive hover wheel binding with child-transition guard,
  trackpad deltas, Shift-horizontal, keyboard page nav, middle-drag
  pan); Help menu with setup/verification guide, standards
  reference, and About dialogs; resizable PanedWindow sidebar
  (230px initial width with 210px snap-back floor clamp, Tk 9 ttk
  panedwindow exposes no per-pane minsize); thematic category and
  page-header icons across all 16 views (display-only maps, routing
  keys unchanged); touchpad precision delta scaling (sub-120 deltas
  collapse to signed unit steps) and `-topmost` popover z-order
  fixes with explicit `command=` wiring.
- **Phase 22 — Licensing Integration Foundation** (593 passing
  tests: 568 baseline preserved, 25 new). Provider-neutral
  `qs_engine/licensing/` package (`models`, `provider`, `service`,
  `storage`): 11-state license machine, `LicensingProvider` ABC with
  `NullProvider` shipped default and scripted `FakeLicensingProvider`
  test double, per-user JSON artifact store (`%APPDATA%/CIVOLINK`,
  no custom crypto, no secrets), offline-grace semantics (cached
  `ACTIVE` + retryable outage yields `OFFLINE_GRACE`, never a
  downgrade; no invented grace duration), Help-menu License Status /
  Activate License modeless dialogs, and `docs/LICENSING.md`
  developer guide. No provider integrated, no server/portal/crypto/
  payment built; QS engines, corpdoc, and frozen files untouched.
  Executable recompiled under Phase 22.1 below (current
  `dist/CIVOLINK-QS.exe` matches present source).
- **Phase 22.1 — Warning Wrap Fix + Executable Rebuild.** Project
  Setup density provenance badges gained `wraplength=220` so long
  override values wrap instead of overflowing; `dist/CIVOLINK-QS.exe`
  recompiled from current source and GUI smoke-tested (single window
  at startup, all 16 pages navigate highlight-verified, Help →
  License Status and Help → Activate License open, no startup
  network activity). 593 passing tests, 0 failures.
- **Phase 23 — Keygen Provider Adapter** (616 passing tests: 593
  baseline preserved, 23 new, 0 failures). `KeygenProvider` in
  `qs_engine/licensing/provider.py` (stdlib `urllib` transport,
  runtime-supplied account ID/public key only — no embedded
  secrets): validate-key + license-key-authenticated machine
  activation/deactivation, verdict mapping (expired/suspended/
  revoked/limit/unknown-fail-closed), Ed25519 offline artifact
  verification (`cryptography` pinned), network-failure grace
  escalation, and machine-taken limit handling. Export entitlement
  gate (`ACTIVE`/`OFFLINE_GRACE` only) wired into the Excel,
  Corporate Document, and IPC/BOQ PDF export handlers in
  `qs_engine/ui/views.py`; take-off, rating, save/load, and
  read-only review stay ungated. `tests/test_keygen_provider.py`
  (mocked HTTP, runtime-generated keys, secret scan) plus
  `docs/LICENSING.md` Keygen configuration. No account integrated
  yet — production still needs real Keygen account materials.
  Executable not recompiled in this phase (`dist/CIVOLINK-QS.exe`
  remains the Phase 22.1 build).
- **Phase 23.1 — Standalone Executable Rebuild & Frozen Smoke Test.**
  PyInstaller rebuild of `dist/CIVOLINK-QS.exe` (v1.4.2) with hidden-import
  hardening for the Phase 23 Keygen adapter: `cryptography` (and submodules
  `cryptography.exceptions`, `cryptography.hazmat.primitives.asymmetric.ed25519`,
  `cryptography.hazmat.primitives.serialization`, `cryptography.hazmat.primitives`),
  `cffi`, `pycparser`, and `qs_engine.licensing` (`models`, `provider`,
  `service`, `storage`) added to `HIDDEN_IMPORTS` in `civolink.spec` — the
  `verify_signature()` function lazily imports `cryptography` inside its body,
  invisible to static Analysis, so the full Ed25519 verification chain is now
  guaranteed bundled at build time. Build completed with zero missing-DLL
  errors (Error 126); `pyi_rth_cryptography_openssl.py` and
  `pyi_rth__tkinter.py` runtime hooks both execute cleanly in the frozen
  binary. Frozen smoke-test results (19-point checklist, all green):
  (a) Runtime & Startup — single window opens titled "CIVOLINK QS Estimating
  Engine v1.4.2", no DLL/crash errors, zero startup network I/O (NullProvider
  active, no HTTP/TCP during idle), no unsolicited licensing popups;
  (b) Unlicensed Engine Usability — all QS calculation panels (Concrete,
  Masonry, Reinforcement, Structural Steel, etc.) remain accessible, `.clk`
  save/load functional, Excel Reconciliation read-only mode operates without
  entitlement errors; (c) Licensing UI & Export Boundary — Help → License
  Status and Help → Activate License dialogs open and close cleanly, and
  Export actions (Excel Export, Corporate Document Generator, PDF BOQ Exporter)
  cleanly trigger the entitlement guard notice while leaving the main window
  responsive. **618 tests pass, 0 failures**; executable size ~40.2 MB at
  `dist/CIVOLINK-QS.exe`.

- **Phase 23.2 — ScrollableFrame Mouse-Wheel Event Lifecycle Fix.**
  Diagnosed and resolved touchpad/mouse-wheel scrolling failure over
  `ScrollableFrame` content area in `qs_engine/ui/views.py`. Root cause:
  `QSApp.show()` created new page children via `PAGES[key]()` but never
  called `refresh_wheel_bindings()`, so dynamically added widgets (labels,
  entries, panels) had no `<Enter>` binding. Since Tk `<Enter>` events fire
  only on the topmost widget under the cursor (not parent ancestors),
  entering over a child without a binding meant `_on_sub_enter` →
  `_bind_wheel` never fired, so `bind_all("<MouseWheel>")` was never
  registered. Fix: added `self.workspace.refresh_wheel_bindings()` call
  in `QSApp.show()` after `PAGES[key]()` renders new content, ensuring
  `_bind_tree` rebinds all children on every page load. Added 2 regression
  tests (source-inspection + display-guarded widget test) to
  tests/test_ui_phase14_1b.py. 621 tests pass, 0 failures.

- **Phase 23.3 — ScrollableFrame MouseWheel Delegation & Resize Debouncing.**
  Two deeper ScrollableFrame hardening fixes in `qs_engine/ui/views.py`:
  (1) Sub-widget mousewheel delegation: added `_bind_mousewheel_tree()` /
  `_unbind_mousewheel_tree()` methods that recursively bind `<MouseWheel>`,
  `<Button-4>`, and `<Button-5>` directly on non-Combobox child widgets (labels,
  entries, panels, frames), ensuring wheel gestures are captured even when ttk
  widgets consume the event before it reaches `bind_all`. Comboboxes are spared
  to preserve dropdown option-cycling. A 50ms time-based guard in
  `_on_mousewheel` deduplicates concurrent widget-level + `bind_all` dispatch to
  prevent scroll-doubling. (2) Resize debouncing: replaced direct
  `<Configure>` lambdas with an `after_idle`-based debounce
  (`_schedule_layout_update` / `_do_layout_update`) that coalesces rapid-fire
  resize events into a single deferred layout pass, suppressing CPU/GPU redraw
  storms and audible coil whine during live panel resizing. 621 tests pass,
  0 failures.

- **Phase 23.3.1 — Production Binary Rebuild** (`dist/CIVOLINK-QS.exe`).
  Rebuilt from current source via `pyinstaller --clean civolink.spec` (v6.22.3,
  Python 3.14.7). Onefile windowed EXE (bootloader `runw.exe`, `console=False`,
  `debug=False`, `upx=True` in spec — UPX not available in build environment,
  binary shipped uncompressed at 40.2 MB). `pyi_rth_cryptography_openssl.py`
  and `pyi_rth__tkinter.py` runtime hooks execute cleanly (Error 126 resolved,
  zero DLL init errors). Binary launches as a single responding process;
  `GUIDE_BUTTON_TEXT` change and new `_bind_mousewheel_tree` / `_do_layout_update`
  methods are compiled into the bundle. Engine files and master-data JSON tables
  verified unmodified (timestamps 2026-09-22).

- **Phase 23.6–11 — License State Schema Migration, Atomic Write & AppData
  Hardening** (`qs_engine/licensing/storage.py`). Persisted license records now
  carry an explicit `schema_version`; `CURRENT_SCHEMA_VERSION = 2` with
  `MIN_SUPPORTED_SCHEMA_VERSION = 1`. `migrate_license_data()` is a pure,
  strictly idempotent v1→v2 transform: it copies the record, sets
  `schema_version: 2`, stamps integer epoch `updated_at` only when absent, and
  never rewrites provider values (integer timestamps keep this package inside
  the qs_engine float ban). v2 input returns an identical copy with no
  timestamp churn. `load_state()` reports `ok` / `migrated` / `missing` /
  `corrupt` / `future_schema` and never persists — callers commit explicitly
  through `save_state()`. Writes are atomic (staged `.tmp` in the target
  directory → `flush` → `os.fsync` → `os.replace`), so a failed write leaves
  the prior valid state untouched and cleans up its temp file. Every
  `save_state()` over an existing parseable file first copies it to
  `%APPDATA%/CIVOLINK/licensing/backups/license-<nanoseconds>.json`, pruned to
  the newest 5 (`BACKUP_RETAIN_COUNT`). Future-schema fail-safe: any payload or
  on-disk record above v2 raises `FutureSchemaError`, `load_state()` returns
  `(None, "future_schema")`, and `save_state()` inspects the disk copy first
  and refuses to overwrite — an older build can never downgrade a newer
  build's license. State stays per-user in `%APPDATA%/CIVOLINK` (overridable
  via `CIVOLINK_LICENSE_DIR`), never in the install tree, and the pre-existing
  `load()` / `save()` / `clear()` API is unchanged, so `LicensingService` and
  the License dialog are unaffected. See `docs/LICENSING_MIGRATION.md`.
  21 new tests in `tests/test_licensing_migration.py` cover v2 load, v1→v2
  migration, idempotency, corrupt/missing handling, atomic-failure
  preservation, rolling backup retention, v99 refusal, AppData isolation, and
  absence of socket activation. 703 tests pass, 0 failures.

- **Phase 23.6–11 deferred — Code Signing & Installer Compilation.** Executable
  signing (`signtool.exe`) and installer compilation (`iscc.exe` /
  `makensis.exe`) remain deferred: no such toolchain exists in this build
  environment, so neither a signature nor an installer could be produced or
  verified here. `scripts/sign_artifacts.py`, `scripts/build_release.py` and
  `civolink_setup.iss` are orchestration/configuration only and fail closed
  (`find_signtool()` / `find_iscc()` return `None` when the tool is absent). No
  certificate, password, private key, or signing credential is hard-coded
  anywhere; secrets come from the environment only.

- **Phase 25 — Writable Material Overrides & Custom Categories** (817 passing
  tests: 783 pre-existing + 34 new). Adds the `qs_engine/resources` layer so a QS
  can create and edit their own materials and categories without ever touching
  read-only master data. `UserMaterialStore` persists to
  `data/user_materials.json` (atomic staged-temp → `os.replace`) beside the
  writable `rate_library.db`, never inside `qs_engine/master_data/tables/`;
  `CategoryRegistry` persists custom categories to `data/user_categories.json`
  under the `user:<slug>` namespace, with seed categories read-only and always
  winning so user entries cannot shadow master data. Records are identifiers
  only — `density` and `default_wastage_pct` have no create/update parameter,
  are written `NULL`, and still pass `validate_record(MATERIALS, …)` with
  `NEEDS_VERIFICATION`, so the calculation core keeps failing closed instead of
  fabricating engineering values. `generate_material_code()` suggests the next
  free sequence code and `validate_material_code()` rejects malformed,
  duplicate, or reserved seed identifiers/codes; each material's canonical key
  (`user:<12-hex>`) is minted once and a code change keeps the previous code as
  an alias resolving to the *same* material. `MaterialResolver` is a drop-in for
  `MasterDataRepository` (`domains` / `table_version` / `list` / `get`), so
  rates, resolution, exports and the CLI consume the merged catalogue with zero
  call-site changes; `QSApp` builds the stack by default while an injected
  repository is still honoured verbatim. The Materials page gains Add/Edit plus
  a custom-category dialog, seed rows stay read-only, and an unreadable or
  future-schema override file fails closed back to the seed catalogue with the
  reason surfaced. The `.clk` schema is unchanged (no material definitions are
  stored in project files) and the seed tables are byte-identical (SHA-256)
  after a full create → rename → restart → resolve lifecycle.

## 4. Verification

The suite is executable from the repository root:

```console
python -m pytest tests -q
```

Headless CI runs everything except display-guarded widget tests
(they skip cleanly without a display and run where one exists).
See `docs/QS_ASSUMPTION_REGISTER.md` for engineering assumptions and
verification statuses governing the calculation core.
