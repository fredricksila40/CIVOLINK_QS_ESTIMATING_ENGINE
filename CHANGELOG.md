# CIVOLINK QS Estimating Engine Changelog

## 24.0.0 - Phase 24 Release Packaging & Audit

### Release artifacts
- **Distribution archive**: `dist/CIVOLINK-QS-v24.0.0.zip` (39.9 MB)
  containing the full `dist/CIVOLINK-QS/` tree (12.7 MB core
  executable, ~76 MB unpacked).
- **Checksum manifest**: `dist/RELEASE_MANIFEST.json` (SHA-256 of
  executable and archive, 738-test baseline, bundled assemblies).
- **Portable smoke test**: extracted archive runs `--help` and `--cli`
  with exit code 0 and no missing-module/asset errors.

### Verification
- **738 passed, 0 failed** across the full pytest suite.
- Frozen GUI smoke: single window at startup, all 16 pages navigate,
  Help → License Status / Activate License dialogs open.

## 25.0.0 - Phase 25 Milestone Initiation

### Baseline established
- Phase 24 release packaged and verified: `dist/CIVOLINK-QS-v24.0.0.zip`
  contains the full `dist/CIVOLINK-QS/` tree (184 entries); the SHA-256
  digests in `dist/RELEASE_MANIFEST.json` were re-hashed and validated
  against the on-disk archive and executable.
- Portable smoke test passes: `CIVOLINK-QS.exe --cli --help` exits 0 with
  no missing-module/asset exceptions; the `--cli` dashboard likewise runs
  headless (exit 0) and aggregates 25 master-data records.
- Audit metrics locked: 12.7 MB core executable, ~76 MB distribution tree,
  738 passing tests / 0 failures (full suite re-run: 738 passed, 1
  deprecation warning, 0 failures in 73.71s).

### Readiness
- The Phase 24 release artifact is reproducible and portable-deployed
  smoke-tested. Codebase is green at the Phase 24 baseline.
- Phase 25 feature backlog scoping is unblocked.

## 25.1.0 - Phase 25 Writable Material Overrides & Custom Categories

### Added
- **User material catalogue** (`qs_engine/resources/`): `UserMaterialStore`
  persists QS-created materials to `data/user_materials.json`, beside the
  writable `rate_library.db` — never inside the read-only seed tree
  (`qs_engine/master_data/tables/`). Entries are identifiers only: `density`
  and `default_wastage_pct` have no create/update parameter, are written
  `NULL`, and are stamped `NEEDS_VERIFICATION`, exactly like the seed
  catalogue. Every record still passes the existing
  `validate_record(MATERIALS, …)` gate.
- **Generated codes**: `generate_material_code()` suggests the next free
  sequence code; the code stays a user-editable suggestion validated by
  `validate_material_code()`. Malformed codes, duplicates, and reserved seed
  identifiers/codes are rejected.
- **Stable identity**: each user material is minted a canonical key
  (`user:<12-hex>`) once at creation. Changing a material code keeps the
  previous code as an alias, so earlier references resolve to the *same*
  material — a code edit is never a silent re-point.
- **Custom categories** (`CategoryRegistry`): user categories persist to
  `data/user_categories.json` under the `user:<slug>` namespace. Seed
  categories are read-only and always win, so user data can never shadow
  master data.
- **Drop-in resolver** (`MaterialResolver`): exposes the same `domains` /
  `table_version` / `list` / `get` surface as `MasterDataRepository`, so
  rates, material resolution, exports and the CLI consume the merged
  seed + user catalogue with zero call-site changes.
- **UI**: the Materials page gains "Add Material…" / "Edit Selected" plus a
  material dialog (name, generated code, category including
  "+ Add Custom Category…", unit) and a custom-category dialog. Seed rows
  remain read-only.
- **Fail-closed behaviour**: unknown units, duplicate/reserved codes, and
  malformed or future-schema override files raise typed errors surfaced in
  the dialog (`Not saved: …`) — never a partial or silent save. Because user
  materials carry no engineering properties, any calculation that needs
  density or wastage allowance still reports unresolved
  (`NEEDS_VERIFICATION`) instead of fabricating a value.

### Verification
- **817 passed, 0 failed** across the full suite (783 pre-existing + 34 new;
  817 collected, 0 skipped, no `conftest.py`/ini collection filters).
- 34 new tests in `tests/test_material_overrides.py` cover the seed-hash
  invariant, creation, code generation/validation, custom categories,
  identity stability across renames, resolver drop-in behaviour,
  reserved/shadowed identifiers, fail-closed engineering inputs, restart
  reload, malformed-store rejection, unchanged `.clk` schema, dialog write
  isolation, and the end-to-end acceptance workflow.
- Seed tables are byte-identical (SHA-256) after a full
  create → rename → restart → resolve lifecycle.

## 1.4.2 - Phase 14.2 Release Hardening, Geometry Fix & Packaging

### Added
- **Master-Data Health Dashboard**: Aggregated `verification_status` counts
  (`VERIFIED`, `NEEDS_VERIFICATION`, `PROVISIONAL`) across core domain tables
  (`rebar_bars`, `concrete_classes`, `masonry_units`, `labour`, `plant`) in the
  Overview pane and CLI view (`qs_engine/cli.py`).
- **Workspace Canvas Geometry Fix**: Updated `ScrollableFrame` in
  `qs_engine/ui/views.py` to use `self.canvas_window_id` for the `<Configure>`
  event binding, ensuring canvas content width resizes correctly with the
  parent workspace.
- **Scrollbar Docking**: Confirmed `vbar` packed strictly to `side="right",
  fill="y"` on the outermost edge of the workspace frame.
- **Geometry Assertion**: Added `test_canvas_content_width_matches_parent` in
  `tests/test_ui_phase14_1.py` verifying that canvas content width expands to
  match full workspace width (`child.winfo_width() == parent.winfo_width()`).

### Changed
- **Namespace Cleanup**: Updated docstring in `qs_engine/__init__.py` from
  "EDMOLT Construction QS / Estimating Engine" to "CIVOLINK Construction QS /
  Estimating Engine".
- **Version Bump**: `__version__` advanced from `0.1.0` to `1.4.2`.

### Fixed
- **Panel Guide Button Text Cleanup**: Changed `GUIDE_BUTTON_TEXT` from `"[ℹ️ Panel Guide]"` to `"ℹ  Panel Guide"` in `qs_engine/ui/views.py`, removing raw ASCII brackets for a cleaner header button appearance.
- **Sub-Widget MouseWheel Delegation**: Added `_bind_mousewheel_tree()` / `_unbind_mousewheel_tree()` methods to `ScrollableFrame` in `qs_engine/ui/views.py`, recursively binding `<MouseWheel>`, `<Button-4>`, and `<Button-5>` directly on non-Combobox child widgets so that wheel gestures over labels, entries, and panels are captured even when ttk widgets swallow the event before it reaches `bind_all`. Comboboxes are spared to preserve dropdown option-cycling. A 50ms time-based guard in `_on_mousewheel` deduplicates concurrent widget-level + `bind_all` dispatch to prevent scroll-doubling.
- **Resize Event Debouncing**: Replaced direct `<Configure>` handlers on `self.interior` and `self.canvas` with an `after_idle`-based debounce (`_schedule_layout_update` / `_do_layout_update`), coalescing rapid-fire resize events into a single deferred layout pass to prevent CPU/GPU redraw storms and audible coil whine during live panel resizing.
- **Save-Semantics Corrections** (Phase 14.1B): Resolved session save
  state issues ensuring `session.project_saved` accurately reflects save
  outcomes; fixed chrome panel header suppression when `chrome=False` is set
  on `QSPanel`.
- **ScrollableFrame Mouse-Wheel Binding Fix**: `QSApp.show()` now calls
  `self.workspace.refresh_wheel_bindings()` after `PAGES[key]()` creates
  new page content. Dynamically generated children (labels, entries, panels)
  previously had no `<Enter>` binding, so `_on_sub_enter` → `_bind_wheel`
  never fired and the global `bind_all("<MouseWheel>")` handler was never
  registered — resulting in silently non-functional scrolling over fresh
  page content. The fix ensures `_bind_tree` rebinds all children on every
  page load, restoring event reception on first mouse-over.

## 1.4.1 - Phase 14.1B Save-Semantics/Chrome Fixes

### Fixed
- Session save-state now correctly marks `project_saved` flag after
  `save_project()` calls.
- `QSPanel` with `chrome=False` properly suppresses instruction banners
  and headers in panel headers.