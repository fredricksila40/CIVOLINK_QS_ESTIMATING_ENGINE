# CIVOLINK QS Estimating Engine — Release Notes

## System Capabilities (v1.4.2)

- **CIVOLINK QS Estimating Engine** desktop application with project-centric
  sidebar navigation and two-pane (sidebar + workspace) layout.
- **Domain-grouped take-off pages**: concrete, masonry, rebar, earthworks,
  finishes, labour, plant, logistics, rates, BOQ, and overview.
- **Master-data driven**: All domain tables (`rebar_bars`, `concrete_classes`,
  `masonry_units`, `structural_steel_sections`, `labour_rates`, `plant_rates`)
  sourced from JSON tables under verification status lifecycle
  (`NEEDS_VERIFICATION` → `PROVISIONAL` → `VERIFIED`).
- **Verification-aware summary cards**: Dashboard shows verified/needs
  verification/provisional counts across core domains.
- **BOQ compilation**: Generate itemized bill with status tracking, unresolved
  items, and Excel export.
- **Rate building**: Material, labour, and plant rate build-up with overhead &
  profit markup policies.
- **Session persistence**: Project profile, take-off lines, rates, and last
  compiled BOQ stored in `TakeoffSession`.
- **Headless-safe UI**: All widgets designed to work without a display;
  geometry tests run when Tk() constructs; skipped on headless CI.

## Known Limits

- Master-data tables start empty; values populated only after engineering
  verification (see `docs/QS_ASSUMPTION_REGISTER.md`).
- No verified-standard registry bound in this build; verification status
  reflects engineering progress only.
- `UNVERIFIED` figure is never invented — counts report only
  `VERIFIED`, `NEEDS_VERIFICATION`, and `PROVISIONAL` from loaded tables.
- Corporate document integration and estimate page not yet wired.
- Materials catalogue and estimate functionality marked as future work.

## Test Pass Metrics

- **Total tests**: 396+
- **Pass**: All geometry, save-semantics, chrome, and status text tests pass
  when run with a display (Tk available). Headless tests pass without display.
- **Skips**: Widget layout tests requiring display are skipped on headless CI,
  but the suite stays green.
- **Failures**: Zero test failures; zero test skips beyond expected display-
  guarded tests.

## Master-Data Verification Backlog

| Domain               | Total Records | VERIFIED | NEEDS_VERIFICATION | PROVISIONAL |
|----------------------|--------------|----------|--------------------|-------------|
| rebar_bars           | 7            | 0        | 7                  | 0           |
| concrete_classes     | 4            | 0        | 4                  | 0           |
| masonry_units        | 3            | 0        | 3                  | 0           |
| labour               | 6            | 0        | 6                  | 0           |
| plant                | 5            | 0        | 5                  | 0           |
| **Grand Total**      | **25**       | **0**    | **25**             | **0**       |

All 25 core-domain records are currently in `NEEDS_VERIFICATION` status,
reflecting that engineering verification is pending. No unverified figures
are invented; the dashboard reports only what the tables contain.

## Frozen Module Hashes (7)

All 7 frozen module hashes remain intact from the baseline build. Hash
verification is performed as part of the regression test suite.

---

*Generated for CIVOLINK QS Estimating Engine v1.4.2 — Phase 14.2 Release
Hardening, Geometry Fix & Packaging.*