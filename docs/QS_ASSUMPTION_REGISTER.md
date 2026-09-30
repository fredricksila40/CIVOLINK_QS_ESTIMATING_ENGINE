# QS Assumption Register — Phase 0

Every engineering input the QS engine will need, with verification status.
**No values are populated here.** A value enters master data only with a
cited source, standard/document, version, and effective date, reviewed by
the engineer/QS lead. `NULL` = not yet verified = must not be used.

Status key: `NEEDS_VERIFICATION` → `PROVISIONAL` → `VERIFIED`.
Schema: see `qs_engine/core/assumptions.py` (`AssumptionRecord`).

## 1. Materials & densities

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `cement_bag_mass` | kg/bag | NEEDS_VERIFICATION | NULL. Confirm bag mass with supplier/standard. |
| `cement_density` | kg/m³ | NEEDS_VERIFICATION | NULL. Loose bulk density for volume/tonnage conversions. |
| `sand_density` | kg/m³ | NEEDS_VERIFICATION | NULL. State loose vs compacted basis on verification. |
| `coarse_aggregate_density` | kg/m³ | NEEDS_VERIFICATION | NULL. Ballast/crushed stone basis to be stated. |
| `water_density` | kg/L | NEEDS_VERIFICATION | NULL. |
| `steel_density` | kg/m³ | NEEDS_VERIFICATION | NULL. Underpins rebar mass tables. |
| `soil_bulking_factor` | ratio | NEEDS_VERIFICATION | NULL. Excavation cut-to-spoil expansion. |
| `hardcore_compaction_allowance` | % | NEEDS_VERIFICATION | NULL. |

Phase 5 skeleton keys exist in `qs_engine/master_data/tables/soils.json`
(v5.0-skeleton, all `NEEDS_VERIFICATION`, all numerics NULL):
topsoil_vegetable, clay_soil, gravel_soil, rock_hard. Engine fails closed
on these without complete explicit overrides. Hardcore, murram,
quarry dust, and river sand keys already exist in the Phase 1 materials
catalog for bed/blinding scheduling.

### User-created materials (Phase 25)

Materials created or edited in the desktop catalogue are identity records
only: `data/user_materials.json` stores name, code, category, unit, and
`verification_status: NEEDS_VERIFICATION`, with `density` and
`default_wastage_pct` written as `NULL`. The create/update API accepts no
parameter for either numeric, so an engineering input cannot be populated by
catalogue editing. `density` remains the register key governed by this
section: it can only become non-NULL through the reviewed
`PROVISIONAL` → `VERIFIED` promotion path, never by user override, and any
calculation that requires it keeps reporting unresolved.

## 2. Concrete

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `concrete_class_mix_<CLASS>` | kg/m³ + m³/m³ + L/m³ | NEEDS_VERIFICATION | NULL per class. Keyed by CLASS (C15…), never by mix ID. Cement, sand, aggregate, water per m³ of placed concrete. |
| `dry_volume_factor_<CLASS>` | ratio | NEEDS_VERIFICATION | NULL per class. Wet-to-dry volume factor with derivation cited. |
| `concrete_wastage_default` | % | NEEDS_VERIFICATION | NULL. Placement/pump/spillage allowance. |

Phase 2 skeleton keys exist in `qs_engine/master_data/tables/concrete_classes.json`
(v2.0-skeleton, all `NEEDS_VERIFICATION`, all numerics NULL): class_c15, class_c20,
class_c25, class_c30. Engine fails closed on these without complete explicit overrides.

## 3. Masonry & mortar

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `block_nominal_size_<TYPE>` | mm | NEEDS_VERIFICATION | NULL per stone/block type (L×H×T, nominal vs actual stated). |
| `masonry_joint_default` | mm | NEEDS_VERIFICATION | NULL. Bed/joint thickness assumption. |
| `mortar_mix_masonry` | ratio | NEEDS_VERIFICATION | NULL. Cement:sand for block/stone laying. |
| `mortar_mix_plaster` | ratio | NEEDS_VERIFICATION | NULL. Per plaster type/coat. |
| `mortar_mix_screed` | ratio | NEEDS_VERIFICATION | NULL. |
| `masonry_wastage_default` | % | NEEDS_VERIFICATION | NULL. Cutting/breakage. |
| `wet_mortar_identity` | method | NEEDS_VERIFICATION | Conservative identity (wet = gross − net of waste-inclusive units) to be confirmed with QS lead — it intentionally over-orders mortar. |

Phase 3 skeleton keys exist in `qs_engine/master_data/tables/masonry_units.json`
(v3.0-skeleton, all `NEEDS_VERIFICATION`, all numerics NULL):
machine_cut_stone_200mm, concrete_block_200mm, concrete_block_150mm.
Engine fails closed on these without complete explicit overrides. Gross wall
volume basis used: net (post-deduction) area × unit thickness.

## 4. Reinforcement & formwork

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `rebar_mass_<DIA>` | kg/m | NEEDS_VERIFICATION | NULL per diameter. Derived from steel density + cross-section; cite table/standard. |
| `rebar_lap_allowance_<DIA>` | mm or ×dia | NEEDS_VERIFICATION | NULL per diameter. |
| `rebar_hook_bend_allowance` | mm or ×dia | NEEDS_VERIFICATION | NULL. |
| `rebar_wastage_default` | % | NEEDS_VERIFICATION | NULL. Offcuts. |
| `formwork_reuse_factor` | uses | NEEDS_VERIFICATION | NULL. Timber/steel panel reuses assumed in rate build-up. Per-calculation explicit parameter until verified. |

Phase 4 skeleton keys: `rebar_bars.json` (v4.0-skeleton: Y8–Y32, nominal
diameters present as designations, mass/wastage NULL); `coverages.json`
(v4.0-skeleton: formwork_release_agent, rate NULL) + `materials.json`
release_agent key. Steel density for the nominal-mass formula is always an
explicit caller input — no 7850/162.2 constant exists anywhere in the engine.

## 5. Coverages (finishes)

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `coverage_<ACTIVITY>` | mixed | NEEDS_VERIFICATION | NULL per activity (plaster thickness→mortar/m², screed, tile adhesive, paint coats/L, etc.). Manufacturer data to be cited per line. |
| `tile_breakage_allowance` | % | NEEDS_VERIFICATION | NULL. |
| `tile_size_<TYPE>` | mm | NEEDS_VERIFICATION | NULL per tile type. |

Phase 6 skeleton keys exist in `qs_engine/master_data/tables/coverages.json`
(v6.0-skeleton, all `NEEDS_VERIFICATION`, all rates NULL):
emulsion_paint_per_coat, gloss_paint_per_coat, tile_adhesive_bedding,
tile_grout_jointing (release_agent key from Phase 4 retained). Plaster and
screed mortar mixes have NO master-data domain yet by design — resolution
is overrides-only until a mixes phase unifies them with masonry mortar.
Thickness, joints, tile sizes, and coats have no defaults anywhere.

## 6. Labour & plant

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `labour_output_<TRADE>` | unit/day | NEEDS_VERIFICATION | NULL per trade/activity. Gang composition to be stated. |
| `labour_rate_<TRADE>` | KES/unit-time | NEEDS_VERIFICATION | NULL. Basis (day/hour) and effective date required. |
| `plant_output_<EQUIP>` | unit/unit-time | NEEDS_VERIFICATION | NULL per equipment/activity. |
| `plant_rate_<EQUIP>` | KES/unit-time | NEEDS_VERIFICATION | NULL. Hire vs operating, mobilisation treatment, effective date required. |

Phase 7 skeleton keys: `labour.json` (v7.0-skeleton: mason, carpenter,
steel_fixer, painter, excavator_operator, general_labourer — names, work
units, and day-rate bases structural; outputs, gangs, rates NULL);
`plant.json` (v7.0-skeleton: concrete_mixer, backhoe_excavator,
poker_vibrator, road_roller, mobile_crane — names, work units, bases
structural; outputs, rates, operating costs NULL). No working-hours-per-day
constant exists: hourly rates require an explicit call parameter.

## 7. Trucks & tonnage

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `truck_body_<SIZE>` | m (L×W×H) | NEEDS_VERIFICATION | NULL per reference size. Struck vs heaped policy to be stated. |
| `payload_limit_<SIZE>` | tonnes | NEEDS_VERIFICATION | NULL. Legal/operational limit per size. |
| `loose_density_<MATERIAL>` | kg/m³ or t/m³ | NEEDS_VERIFICATION | NULL per hauled material (loose basis for tonnage calc). |

Phase 8 skeleton keys exist in `qs_engine/master_data/tables/trucks.json`
(v8.0-skeleton, all `NEEDS_VERIFICATION`, all numerics NULL): tipper_truck,
flatbed_trailer, site_dumper. Struck vs heaped loading is an explicit
per-call policy (default struck). Hire rates/fuel burn resolve when verified
or overridden; costing functions always take explicit rate parameters.

## 8. Commercial boundary (QS-side)

| Key | Unit | Status | Notes |
|-----|------|--------|-------|
| `default_wastage_<MATERIAL>` | % | NEEDS_VERIFICATION | NULL per material (also stored per master-data record). |
| `overhead_basis` | method | NEEDS_VERIFICATION | On direct cost vs on rate; per-item vs project-level — decision required. |
| `profit_basis` | method | NEEDS_VERIFICATION | As above. |

Phase 9 notes: the rates engine supports both compounding policies
(SEQUENTIAL cumulative, PARALLEL on-direct) with the policy recorded per
rate — but the commercial decision of which basis applies stays open (see
rows above). No verified material price library exists: build-up prices
arrive per call. Structural skeletons in `rate_templates.json`
(v9.0-skeleton): concrete_placed_per_m3, blockwork_per_m2 — all
quantities/prices/percentages NULL; BOQ phase binds prices.

Phase 10 notes: no new master-data domain — measurement rules arrive
per BOQ item as citations (standard/edition/ref/source/status) and no
SMM/CESMM rule content is encoded anywhere. `standards/measurement/`
(SMM, CESMM) awaits source material; the pipeline remains source →
extracted rule → verification → structured rule → test → implementation.
BOQ amounts are exact Decimal with no compilation rounding.

Phase 11 notes: the Excel adapter introduces no engineering assumptions —
it renders compiled values only. xlsx numerics are IEEE-754 doubles, so
reviewers must read money through the `#,##0.00` display formats; the
Check (H) column reconciles native formulas against compiled values
in-Excel. No currency symbol is applied (amounts carry no currency).

Phase 12 notes: the document adapter introduces no engineering
assumptions — it serializes compiled values only (Decimals as exact
strings, unresolved totals as explicit nulls with flags). No prices,
rules, or statuses are created or defaulted in the DTO layer.

Phase 14 notes: integration scenarios use arbitrary test figures only
(concrete 5×4×0.15 slab, 4×2 block wall, 20×12 m Y12 bars, test prices);
no new assumptions. A repo-wide AST audit pins zero `float` usage in
`qs_engine/` product code — the sole float contact in the system remains
openpyxl's documented double coercion at the Excel export boundary.

Phase 13 notes: the UI layer introduces no engineering assumptions — it
collects strings and renders engine results. Panel field defaults that
look like practice (unit m, faces, struck heap, struck bins) are the
underlying engines' documented explicit defaults, unchanged here.
| `vat_boundary` | method | NEEDS_VERIFICATION | Working assumption: estimates ex-VAT; tax applied in the commercial/document layer per existing company config. To be confirmed. |

## Phase 1 catalog keys (materials)

Identifiers now exist in `qs_engine/master_data/tables/materials.json`
(v1.0-catalog, all `NEEDS_VERIFICATION`, numerics NULL): portland_cement_42_5,
hydrated_lime, river_sand, quarry_dust, ballast_20mm, hardcore, murram,
building_stone, concrete_block_200mm, concrete_block_150mm, binding_wire,
wire_nails, formwork_timber, plywood_18mm, emulsion_paint, gloss_paint,
tile_adhesive, tile_grout, gypsum_plaster, ceiling_board, water,
polythene_sheeting. Verification of each key's density and wastage promotes
the corresponding row above; nothing below is superseded until then.

## Promotion rule

`NEEDS_VERIFICATION` → `PROVISIONAL` (figure supplied, source pending) →
`VERIFIED` (value + source + standard + version + effective date all
present). The loader accepts any of the three states; calculators must
refuse `NEEDS_VERIFICATION`-with-`NULL` values at use time (fail closed).
