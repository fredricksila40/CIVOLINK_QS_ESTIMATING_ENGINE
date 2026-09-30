# QS Engine — Phase 0 Foundation

Independent Construction QS / Estimating calculation foundation.
No trade calculators exist yet — this phase establishes only the kernel,
schemas, contracts, and tests every later phase must build on.

## Architecture

```
CIVOLINK_QS_ESTIMATING_ENGINE/      (run pytest from here)
├── qs_engine/
│   ├── core/          # Kernel: units, decimal policy, errors, validation,
│   │                  #          rounding (ceiling), wastage, assumptions.
│   │                  #          Pure stdlib + Decimal. No other dependencies.
│   ├── master_data/
│   │   ├── schemas.py     # Record schemas (structure + provenance rules).
│   │   ├── repository.py  # JSON-table loader with typed lookup errors.
│   │   └── tables/*.json  # Values only after verification.
│   ├── contracts/
│   │   └── models.py  # MasterRecord, Quantity, TakeoffResult,
│   │                  # MaterialRequirement, CostLine, BOQItem.
│   ├── concrete/ | masonry/ | reinforcement/ | formwork/ | earthworks/ | finishes/
│   └── README.md      # (this file, Phase 0–6 build notes)
├── tests/             # pytest suite, extracted sibling layout (see below).
├── standards/measurement/{SMM,CESMM}/  # reserved for measurement references.
├── standards/{specifications,codes,references}/  # reserved.
├── docs/              # QS_ASSUMPTION_REGISTER.md (verification ledger).
├── data/              # writable runtime data (created on demand):
│                      # user_config.json, user_materials.json,
│                      # user_categories.json, rate_library.db,
│                      # sessions/*.clk. Never seed master data.
└── output/            # generated artefacts (none checked in).
```

Future phases add sibling packages (`takeoff/`, `resolution/`, `costing/`,
`boq/`) that consume `core` + `master_data` and expose results via
`contracts`. They never bypass the kernel.

## Dependency boundary (enforced by test_import_boundary.py)

`qs_engine` MUST NOT import: `docx`, `openpyxl`, `scripts.*`
(`quotation_logic`, `document_base`), `branding`, SOCS, or any UI
framework. Core code is standard library + `Decimal` only. Tests may use
`pytest` (and `tmp_path` fixtures).

## Decimal policy (`core/decimal_policy.py`)

- `Decimal` for quantities, densities, rates, costs, percentages,
  conversion factors, monetary amounts.
- `float` is **rejected** (`to_decimal` raises `TypeError`) so binary
  floating-point can never enter a chain silently.
- `quantize` / `quantize_money` exist for **output boundaries only**.
  Intermediate results stay unrounded.

## Units policy (`core/units.py`)

- Explicit registry only: mm/cm/m, mm²/m², mm³/m³/L, kg/tonne,
  bag/piece/pair/set/sheet, hour/day.
- `convert(value, from_unit, to_unit)`: exact Decimal factors, identity
  always allowed, unknown units → `UnknownUnitError`, cross-dimension or
  undefined pairs → `IncompatibleUnitsError`. No guessing (e.g. mm→cm
  has no entry and fails closed by design).

## Validation policy (`core/validation.py`, `core/errors.py`)

Typed errors for every rule: dimensions > 0, quantities ≥ 0,
densities > 0, rates ≥ 0, percentages within declared range (default
0–100), required fields present, master-data keys exist. Invalid input
fails closed — never silent zero, substitution, NaN, or invented default.

## Rounding policy (`core/rounding.py`)

- Ceiling is **explicit and opt-in** via `apply_ceiling()` for
  bag/piece/pair/set/sheet (and tonne where appropriate).
- Fractional units (m, m³, kg, L) **cannot** be ceiled — raises.
- `RoundingResult` keeps `calculated_quantity` beside
  `ordering_quantity`; the engineered figure is never destroyed.

## Wastage pipeline (`core/wastage.py`)

`apply_wastage(base, pct)` returns `WastageResult` exposing base,
wastage %, waste quantity, and after-wastage quantity. No hidden
multipliers. `rounding_applied` is always `False` here — rounding is a
separate, later, explicit stage. Wastage percentages themselves come
from master data in later phases, never from code.

## Master-data philosophy (`master_data/`)

- Schemas define structure; JSON tables carry values with
  `schema_version` + per-record `source/version/effective_date/
  verification_status`.
- Tables ship **empty**. Missing table file = empty table (domains fill
  incrementally); missing key = `UnknownMasterDataKeyError`.
- No engineering constant (density, mix, wastage %, output, rate, truck
  dimension) may ever live in calculator code.

## Assumption-register philosophy (`core/assumptions.py`)

Every future constant is an `AssumptionRecord` (key/name/value/unit/
description/source/source_type/standard/version/effective_date/
verification_status/notes). Statuses: `NEEDS_VERIFICATION`
→ `PROVISIONAL` → `VERIFIED` (which additionally requires value +
source). Unverified values stay `None`.

## Future phase boundaries (not built yet)

- Phase 1: materials master data (values, verified).
- Phases 2+: trade calculators → costing → BOQ → Excel export →
  document-engine adapter → UI → validation QA.
- QS → Corporate Document Engine: one-way handoff DTO via a future
  adapter; frozen files are never touched.
- QS → SOCS: planned-quantities snapshot DTO; no shared modules.

## Running tests

```
C:\Python314\python.exe -m pytest tests -q
```

## Phase 1 — Materials catalog (v1.0-catalog)

`master_data/tables/materials.json` holds 22 material records: identifiers
(key/name/category/unit) plus full provenance. `density` and
`default_wastage_pct` are **NULL on every record** pending engineering
verification — no record is usable for calculation yet, by design.

Supporting rule (`master_data/schemas.py`, `NULLABLE_NUMERIC_FIELDS`):
numeric fields may be null **only** while a record is
`NEEDS_VERIFICATION`; `PROVISIONAL`/`VERIFIED` records must be complete.
`contracts.master_record_from()` wraps a repository record as a typed
`MasterRecord` for future calculators.

## Phase 2 — Concrete engine (`concrete/`)

Ratio-based pipeline in `concrete/engine.py`: `wet_concrete_volume()` →
`dry_constituent_volume()` (K_dry ≥ 1) → `split_constituents()` (parts sum
exactly to dry volume) → `constituent_masses()` → `cement_bags()`
(explicit `round_up` option; bag mass always supplied, never defaulted) →
`water_requirement()` (water density explicit, never a hidden 1.0).

`resolve_mix()` enforces fail-closed: `NEEDS_VERIFICATION` classes
(`class_c15/c20/c25/c30` skeletons, v2.0-skeleton, all numerics NULL)
require a complete `ConcreteMixOverride`; anything less raises
`UnverifiedMasterDataError`. Verified/provisional records resolve from the
table with per-field overrides recorded on `ResolvedMix`. Results live in
`concrete/results.py` (`ConcreteRequirement` bundle).

## Phase 3 — Masonry engine (`masonry/`)

Take-off and mortar pipeline in `masonry/engine.py`: `wall_areas()`
(gross − openings = net; excess openings fail closed) → `unit_takeoff()`
(joint-inclusive face → exact → +waste → always-ceiled ordering) →
conservative wet mortar (`gross_wall_volume − net_unit_volume`, net from
waste-inclusive ceiled units, floored at 0 with both inputs exposed) →
dry expansion → `split_mortar()` (cement:sand) → `mortar_constituents()`
(cement kg, sand kg + m³) → `cement_bags()` (reused from concrete).

`resolve_masonry_unit()` enforces fail-closed: `NEEDS_VERIFICATION`
units (`machine_cut_stone_200mm`, `concrete_block_200mm`,
`concrete_block_150mm` skeletons, v3.0-skeleton, all numerics NULL)
require a complete `MasonryUnitOverride`. Dry-factor scaling and bagging
reuse the tested concrete services rather than duplicating them. Results
live in `masonry/results.py` (`MasonryRequirement` bundle).

## Phase 4 — Reinforcement (`reinforcement/`) and formwork (`formwork/`)

Rebar (`reinforcement/engine.py`): designation lookup (Y8–Y32 skeletons,
v4.0-skeleton, nominal diameters present, mass/wastage NULL) → unit mass
from the verified table value or the nominal-mass formula
(pi·(d/1000)²/4·density, exact decimal pi, caller-supplied density — the
d²/162.2 shortcut is deliberately unused as it hides a 7850 density) →
`BarLineInput` expansion (count × (length + laps × lap_len + hooks)) →
schedule totals in kg + tonnes with REQUIRED explicit wastage and optional
tying-wire ratio. `resolve_rebar_bar()` fails closed without a usable mass.

Formwork (`formwork/engine.py`): two-step API — element take-off
(slab soffit/edge, beam 2-sides+soffit, rectangular column, footing
sides, wall 1|2 faces) + `apply_deductions()` (itemised, excess fails
closed) → scheduling from explicit rates (`schedule_boarding()` with
reuse factor, `schedule_props()` in unrounded linear metres,
`release_agent_litres()`). No rates in the module; release-agent
coverage skeleton added for a later phase. Circular columns deferred.

## Phase 5 — Earthworks (`earthworks/`)

`earthworks/engine.py`: `clearance_area()` / `topsoil_strip_volume()` →
`excavation_volume()` (bank, working-space allowance added to EACH side;
serves bulk and trench work, identical geometry) → `swell_volume()`
(bank × K_swell) → `backfill_volume()` (bank − displaced substructure;
excess displaces fails closed) → `backfill_loose_requirement()` (bank ×
K_compact, or bank uncompacted) → `cartaway_volume()` (loose dug −
backfill loose; negative exposed as net import, never floored).
`compacted_yield()` inverts compaction. Factors < 1 fail closed.

Beds share `layer_volume()` (`hardcore_bed_volume()`,
`blinding_volume()`); loose supply reuses the compaction math.
`membrane_area_with_laps()` covers DPM/anti-termite (lap % validated
0–100). `resolve_soil()` fails closed on the new `soils` domain
(topsoil/clay/gravel/rock skeletons, v5.0-skeleton, all numerics NULL)
without complete `SoilOverride`s. Bank mass uses bank density only —
loose mass is deferred to the truck/tonnage phase with verified loose
densities, never derived silently. Hardcore/blinding materials already
exist as Phase 1 catalog keys.

## Phase 6 — Finishes (`finishes/`)

Two layers with a hard boundary. `takeoff.py` is pure geometry — no
master data, no rates: `plaster_takeoff()` (per-face areas, itemised
openings, volume; thickness REQUIRED), `screed_takeoff()` (area,
volume; thickness REQUIRED), `tile_takeoff()` (joint-inclusive tile
area, theoretical count; wastage OPTIONAL), `paint_takeoff()` (net area
per coat, total coated; coats REQUIRED). Openings accept `Opening`
objects (width/height/count) or tuples; takeoffs embed a
contracts `TakeoffResult` for the primary quantity.

`resolution.py` maps geometry to materials and returns computed bundles
or an explicit `UnresolvedRequirement` — never a typical value:
`MortarOverride` (shared plaster/screed; no mortar-mix domain exists
yet, so resolution is overrides-only), `PaintOverride` (coverage from
override or verified coverages record; wastage override-only),
`TileConsumablesOverride` (adhesive/grout rates likewise). Bundles carry
`MaterialRequirement` objects (post-waste kg/L) plus `WastageResult`
trails; tile order ceilings pieces only when wastage is explicit.
Coverages skeletons added (v6.0-skeleton): emulsion/gloss per-coat,
tile adhesive bedding, tile grout jointing — all rates NULL.

## Phase 7 — Labour (`labour/`) and plant (`plant/`)

Labour (`labour/engine.py`): trade lookup (6 skeletons, v7.0-skeleton,
names/units/bases structural, all outputs/gangs/rates NULL) → gang cost
(skilled×rate + unskilled×rate) → duration (quantity ÷ gang output/day)
→ person-day split → cost. Hourly rates REQUIRE explicit `hours_per_day`
(no working day assumed anywhere); `hours_per_day` with daily rates
fails closed as contradictory. Gang-days stay fractional; whole-day
hiring is procurement, not calculation. `resolve_labour_trade()` fails
closed without complete `LabourTradeOverride`s.

Plant (`plant/engine.py`): equipment lookup (5 skeletons, v7.0-skeleton,
all outputs/rates/operating NULL) → duty duration in the output basis →
hire cost, converting hour↔day through explicit `hours_per_day` only when
rate and output bases differ (contradictory supply otherwise fails
closed) → operating cost from explicit operating hours × rate, or
explicitly absent (`None`, never zero) when no rate exists. Hire basis
(dry/wet) carried as provenance. Results in phase `results.py` bundles.

## Phase 8 — Logistics (`logistics/`)

`logistics/engine.py`: `bin_volume()` (struck, or explicitly heaped %) →
`load_tonnage()` (loose-state density only — bank densities never reused)
→ `limiting_load()` (bin fill vs rated payload, binding constraint named;
rated payload above legal limit fails closed) → `cycle_time_minutes()`
(loaded + empty legs + load + unload) → `trips_per_day()` (exact) →
`fleet_size()` (ceiled against a tonne-or-m³ daily target) →
`price_haulage()` (per-trip/tonne/m³ with hire and fuel kept distinct;
fuel needs burn AND price together). Loose volumes arrive from earthworks
take-off (documented handoff, no code coupling). `resolve_truck()`
fails closed on the `trucks` domain (tipper/flatbed/dumper skeletons,
v8.0-skeleton, all numerics NULL) without complete `TruckOverride`s;
hire/fuel stay optional extras (absent = unavailable, never zero).
Two-step API: `plan_haulage()` (trips/fleet) then `price_haulage()`
(costing with explicit hire params).

## Phase 9 — Unit-rate build-up (`rates/`)

`rates/engine.py`: explicit component builders — `material_component()`
(key validated, price + wastage explicit), `labour_component_from_requirement()`
and `plant_component_from_requirement()` (consume Phase 7 results;
per-unit = total ÷ quantity), `labour_component_direct()`,
`logistics_component()` (haulage total ÷ work quantity),
`subcontract_component()` (description required; provisional flagged) —
feed `composite_rate()`, which sums direct cost and applies an ordered
markup stack under a recorded policy: SEQUENTIAL compounds onto the
running total, PARALLEL applies each to direct cost. Net vs gross always
separated, with per-markup amounts and running totals. No price library
exists yet: prices arrive per call. Structural `rate_templates` domain
added (v9.0-skeleton, 2 templates, all values NULL) for the BOQ phase to
bind prices to; `template_is_priced()` gates that step.

## Phase 10 — BOQ compilation (`boq/`)

`boq/models.py`: validated inputs (`Boq` → `BoqSection` → `BoqSubsection`
→ `BoqItem`, all ordered lists, all refs non-empty) with pricing as
`priced` (Phase 9 gross), `explicit` (rate + ref), `provisional` (lump
sum, the only legal use of unit `sum`), or `unpriced` (amount None, never
zero). `boq/measurement.py`: `MeasurementStandard` (SMM/CESMM known,
future names allowed visibly), `MeasurementRule` (citation-only
provenance, zero encoded rules), `Rulebook` (duplicate registration and
unknown lookups fail closed). `boq/compiler.py`: deterministic
section.subsection.item numbering (explicit overrides checked unique),
exact Decimal amounts, honest totals (`total` None whenever any line is
unpriced/unresolved; `resolved_subtotal` always reports what IS priced),
and full traceability (take-off object + refs, rate result, rule
citation) on every compiled line. No new master-data domain: rules
arrive per item; calculation lives in Phases 0–9.

## Phase 11 — Excel export adapter (`adapters/excel/`)

`boq_workbook.py` renders a `CompiledBoq` to `.xlsx` as a read-only
presentation sink — the compiled BOQ stays the truth, nothing feeds
back. Per sheet (Cover, Summary, one bill per section): 8 columns
(Item No, Description, Quantity, Unit, Rate, Amount, Compiled Amount,
Check). Priced rows carry `=C*E` formulas (F), compiled Decimals (G),
and `=F-G` checks (H); provisional lumps render as values with a
description suffix; unpriced renders as UNPRICED text (never zero).
Section/summary/cover totals render compiled values or UNRESOLVED text
— never partial formula sums. Cover carries audit metadata and the
governance banner. PRECISION NOTE: xlsx numerics are IEEE doubles, so
openpyxl stores floats; display stays exact via `#,##0.00`/`#,##0.000`
formats while Decimal truth lives in-engine. Styling is neutral grey —
no frozen brand assets leak in. openpyxl is permitted ONLY under
`adapters/` (boundary test enforces this).

## Phase 12 — Corporate document adapter (`adapters/document/`)

`payload.py` synthesizes JSON-serializable DTOs from compiled QS
results — no rendering, no docx, no frozen-engine contact:
`synthesize_boq_payload()` maps `CompiledBoq` trees (numbers, exact
Decimal-as-string amounts, verbatim statuses, refs, measurement
citations) with header/governance metadata (title, purpose, refs,
compilation ID, date, unresolved flags); `synthesize_rate_payload()`
maps Phase 9 `CompositeRate` results. Decimals serialize as strings
(exact, round-trippable — JSON has no Decimal); unresolved totals are
explicit nulls plus flags so generators cannot misrepresent incomplete
estimates. Data flows one way: engine → DTO → future generators.

## Phase 14 — System integration & audit (`tests/test_integration_e2e.py`)

End-to-end proof across all layers, no new product code: Scenario A
(concrete + masonry + rebar take-offs → composite rates → BOQ →
Excel + DTO) conserves every number layer to layer; Scenario B proves
fail-closed (unverified master data → `UnverifiedMasterDataError`,
UI → `ErrorView`, unpriced → honest null totals); Scenario C pins
CESMM lineage (take-off ref + rate ref + rule citation on every line,
in compiled output, DTO, and workbook cover). Plus a product-wide AST
audit pinning zero binary floats in `qs_engine/`.

## Phase 13 — Desktop UI adapter (`ui/`)

MVP over the engine: `controllers.py` is framework-agnostic (string in,
view-model out, engine decides — fully headless-testable); `views.py`
binds those controllers to stdlib tkinter widgets (the conservative,
zero-dependency toolkit choice; swap seam documented for CustomTkinter/
Qt later). Controllers NEVER raise engine errors — every failure becomes
an `ErrorView` (fail-closed feedback). Strict string→Decimal parsing
(empty/float/comma inputs rejected with field attribution); no float
arithmetic anywhere. Panels: project setup (SMM/CESMM selector),
concrete/masonry/rebar/earthworks/finishes/labour/plant/logistics
take-offs, string-driven rate builder (plant lines need resolved
requirement objects — stated, not guessed), BOQ view, Excel and document
DTO export triggers. `test_import_boundary.py` scopes GUI toolkits to
`ui/` only (openpyxl stays `adapters/`-scoped).

## Security & RBAC

Two-tier administrative access control:

* **Tier 1 — Operational PIN**: Daily access to rate library editing,
  GL mapping, and system configuration. Stored as a salted PBKDF2-HMAC-SHA256
  hash in `data/user_config.json`. Possessing the PIN grants administrative
  tools but denies PIN overwrites.
* **Tier 2 — Super-Admin Recovery**: PIN rotation requires the current
  operational PIN AND the Master Recovery Key. On startup, the engine scans
  `%APPDATA%\CIVOLINK\licensing\` for a signed `master_admin.lic` file.
  Lockout throttles the PIN dialog for 5 minutes after 5 consecutive failed
  attempts. Role-based route guarding blocks unauthorized navigation to
  `admin_setup` and `global_policy_editor` views.

## Session Archiving

Working sessions are persisted as `.clk` archive files (zip-compressed JSON)
in `%APPDATA%\CIVOLINK\sessions\`. The archive contains the project profile,
take-off lines, and session metadata. Sessions are loaded back via
`TakeoffSession.load_archive()` or imported via `TakeoffSession.import_clk()`.

## Material Persistence

* **User Materials**: Writable JSON store at `data/user_materials.json`.
  User-created materials carry `verification_status = NEEDS_VERIFICATION`
  and never acquire density, mix ratios, or engineering factors.
* **Rate Library**: SQLite store at `data/rate_library.db` for assembly
  rates and rate cards managed on the Rate Builder page.
* **Category Registry**: Seed categories derived from the materials table
  plus user-created categories persisted in `data/user_categories.json`.
