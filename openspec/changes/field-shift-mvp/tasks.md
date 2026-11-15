# Tasks

Groups 1-10 run entirely on the synthetic sample bundle and a recorded climate fixture. Tasks 11.1-11.3 and 11.6 need deliveries from the geospatial scientists (GS#1, GS#2).

## 1. Repository and tooling

- [x] 1.1 Initialize git in the project root with a `.gitignore` covering `.venv/`, `node_modules/`, `data/bundles/`, `data/cache/` and build output; verify `git status` lists only intended files
- [x] 1.2 Create `backend/` as a uv project pinned to Python 3.12 with package `fieldshift`, the dependencies in design D13 and one import smoke test; verify `uv run pytest` passes
- [x] 1.3 Create `frontend/` as a Vite + React + TypeScript project with Leaflet, react-leaflet and Recharts and a dev proxy from `/api` to the backend; verify `npm run build` succeeds
- [x] 1.4 Add `config/engine.yaml` with the non-crop thresholds named in design D8 and a typed loader; verify tests load it and reject an unknown key

## 2. Bundle contract, validator and hand-off pack

- [x] 2.1 Implement the bundle contract models (manifest, units, time-series row, static row, crop history, suitability) with the controlled vocabulary and valid ranges from design D3; verify tests accept a valid instance and reject an out-of-range value for each model
- [x] 2.2 Implement the standalone validator command that reports every violation with file, field or row and reason, and sets the exit status; verify tests cover each rejection scenario in the `geodata-bundles` spec and the all-violations-together scenario
- [x] 2.3 Implement a seeded sample-bundle generator that writes a synthetic grid bundle (at least 20 cells) and a field bundle (at least 3 fields inside the grid) with plausible seasonal NDVI to `data/sample/`; verify both generated bundles pass the validator and regenerate identically
- [x] 2.4 Implement the Earth Engine wide-to-long converter command with a band mapping file; verify tests cover the scaled conversion and the unmapped-band report, and that converted output passes the validator
- [x] 2.5 Export the bundle JSON Schemas to `contracts/`; verify a test fails when committed schemas differ from freshly generated ones
- [x] 2.6 Write `docs/data-contract.md` for the geospatial scientists (bundle layout, vocabulary and units, Earth Engine asset list, cropland-mask recipe, mapping-file example, validator and converter commands); verify every command in the document runs as written against `data/sample/`

## 3. Bundle loading and location lookup

- [x] 3.1 Implement the bundle registry that discovers bundles at start-up, checks manifests and exposes unit counts; verify tests load the sample bundles and refuse an unsupported contract version
- [x] 3.2 Implement per-unit queries of time series, static properties, crop history and suitability from Parquet and CSV without loading whole tables; verify tests return the expected rows for a sample unit and empty results when optional tables are absent
- [x] 3.3 Implement location lookup (showcase field first, then grid cell, else none) with a spatial index; verify tests cover the three lookup scenarios in the `geodata-bundles` spec

## 4. Climate data

- [x] 4.1 Implement the NASA POWER client for the parameters and period in design D6, mapping fill values to missing and attaching provenance; verify a recorded-response test with no network, and a live smoke command for one Ukrainian point that prints the period and row count
- [x] 4.2 Implement source-grid snapping and the persistent per-cell cache; verify tests show no second network call, a shared cell for a nearby point, and reuse by a fresh client instance
- [x] 4.3 Implement unreachable-source behavior; verify tests return the stored series when present and raise the climate-unavailable error when absent
- [x] 4.4 Implement the resumable pre-warm command over a bundle's units or a point list with a fetched/skipped/failed summary; verify tests cover a resumed run and a failing cell
- [x] 4.5 Commit a recorded POWER fixture covering the sample bundle's cells and make the test suite fail on any real network request; verify the full suite passes with the network guard active

## 5. Crop knowledge base

- [x] 5.1 Implement the knowledge-base models, loader and validation (required traits, ranges, duplicate identifiers, sources, review status); verify tests cover each rejection scenario in the `crop-knowledge-base` spec
- [x] 5.2 Author `kb/crops.yaml` with the 20 crops listed in design D8, each with Ukrainian and English names, cited sources and `draft` status; verify it loads and a test asserts the coverage minimums in the spec
- [x] 5.3 Implement the localized catalog listing; verify tests return Ukrainian and English names with review status
- [x] 5.4 Write `docs/knowledge-base.md` for GS#2 (trait meanings and units, how to edit values, how to mark a crop reviewed, how to tune `config/engine.yaml`); verify the document's example edit loads without error

## 6. Rotation calendar and site diagnostics

- [x] 6.1 Implement the rotation calendar builder (dated slots, winter crops spanning cycle years, turnaround, date clamping with a notice); verify tests cover both calendar scenarios in the `rotation-recommendation` spec
- [x] 6.2 Implement reference evapotranspiration by FAO-56 Penman-Monteith with the temperature-based fallback and a count of fallback days; verify a test reproduces the FAO-56 daily worked example within 0.1 mm per day
- [x] 6.3 Implement derived soil properties (Saxton-Rawls water-holding capacity, EPIC erodibility) and the default assumption, each marked derived or assumed; verify tests against published reference values for one texture class and check the markers
- [x] 6.4 Implement bare-soil windows from the calendar; verify tests cover the long-gap and winter-crop scenarios
- [x] 6.5 Implement observed low-cover periods from the multi-year median vegetation index, including periods that wrap the year end; verify tests cover detection, year-end wrap and absence in tier `climate_only`
- [x] 6.6 Implement the daily root-zone water balance vectorized across replay windows (crop coefficient curve, dormancy, stress coefficient) with per-crop demand, supply and deficit; verify tests show the mass balance closes, the deficit is zero under abundant rain and a larger capacity lowers the deficit
- [x] 6.7 Implement the stress calendar (heat, frost, winterkill, drought by stage) with years hit and years examined; verify tests cover the 12-of-36 scenario, omission of winterkill for spring crops and a changed probability after a threshold edit
- [x] 6.8 Implement the erosion-exposure index for bare-soil windows; verify tests cover the wetter-window and rainfall-only scenarios
- [x] 6.9 Implement trends (Theil-Sen slope, Mann-Kendall p-value) for the five indicators and anomaly summaries for short records; verify tests recover a known slope, leave a trendless series not significant and report no trend for a series under 15 years
- [x] 6.10 Assemble the site diagnosis with data tier and provenance; verify an integration test on the sample bundles and climate fixture produces a diagnosis for tiers `field`, `grid` and `climate_only`

## 7. Rotation engine

- [x] 7.1 Implement the five candidate operators applied singly and in pairs, with recorded operator lists, deduplication and the cap of 100; verify tests show a cover crop fills a qualifying bare window, operators are recorded and the cap holds
- [x] 7.2 Implement the hard constraints, including the return-interval rule that distinguishes introduced crops from inherited baseline frequency; verify tests cover every scenario under "Hard agronomic and user constraints" and "Suitability screening"
- [x] 7.3 Implement the eight objective functions normalized to 0-1, with cover-crop water use charged to the water objective; verify tests cover reproducibility, the legume, cover-crop erosion and cover-crop water-demand scenarios
- [x] 7.4 Implement the priority-weighted overall score, the all-zero-priorities rule and replay aggregation (median, 10th and 90th percentile, window count); verify tests show priorities change only the overall score and a 3-year cycle on 40 years yields 38 windows
- [x] 7.5 Implement selection (flagged baseline, distinct alternatives, labels, over-constrained notice) and baseline deltas in physical units; verify tests cover both selection scenarios and the physical-delta scenario
- [x] 7.6 Implement the confidence level rule from design D10; verify tests give `low` for tier `climate_only` and never `high` for tier `grid`
- [x] 7.7 Add a timing test for a full engine run on a three-crop baseline with stored climate; verify it completes in under 8 seconds on the development laptop and prints the measured time

## 8. Explanations

- [x] 8.1 Implement evidence records built from diagnostics and scores; verify a test finds every required field on every evidence entry of a sample analysis
- [x] 8.2 Implement the English and Ukrainian template catalogs over shared parameters; verify a test finds every template key in both languages with identical placeholders
- [x] 8.3 Implement reasons, benefits and trade-offs; verify tests cover the top-priority, zero-weight, significant-trend, quantified-benefit, trade-off and numeric-claims-backed scenarios
- [x] 8.4 Implement information gaps and local-review reminders driven by actual conditions; verify tests cover every scenario under "Gaps reflect actual data conditions" and "Local-review reminders"
- [x] 8.5 Implement the baseline explanation; verify tests cover the baseline-as-reference, language-parity and reproducible-wording scenarios

## 9. HTTP API

- [x] 9.1 Implement the application with start-up loading of bundles, knowledge base and configuration, and the health endpoint; verify a test reads bundle unit counts, crop count and stored climate cells from it
- [x] 9.2 Implement the location lookup, crop catalog and showcase endpoints; verify tests cover every scenario for those three requirements in the `analysis-api` spec
- [x] 9.3 Implement the analysis endpoint wiring diagnostics, engine and explanations for point, unit and polygon locations with notices and response metadata; verify tests cover the three location scenarios on sample data and the metadata scenario
- [x] 9.4 Implement field-level validation errors and the `climate_unavailable` failure response; verify tests cover every scenario under "Input validation" and "Upstream failure reporting"
- [x] 9.5 Publish the machine-readable schema and export it to `contracts/openapi.json`; verify tests validate a real analysis response against it and confirm a warm analysis returns within 10 seconds
- [x] 9.6 Document how to run the backend in `README.md`; verify the documented commands run as written and the health endpoint responds

## 10. Web UI

- [x] 10.1 Generate TypeScript types from the exported schema and add a typed API client; verify the type check passes and regenerating produces no diff
- [x] 10.2 Build the page layout with the Ukrainian and English label dictionaries and the language switch; verify in the browser that switching changes every visible label
- [x] 10.3 Build the map with a base layer, click-to-place marker, selectable showcase fields and a data-tier badge from the lookup endpoint; verify in the browser against the backend with sample data for a field, a grid cell and a point outside both
- [x] 10.4 Add the NASA vegetation layer toggle with attribution; verify the layer id against the GIBS capabilities document, that tiles render, and that the workflow still works with the layer URL deliberately broken
- [x] 10.5 Build the rotation builder (add, remove, reorder, cover crops) from the crop catalog, with analysis disabled while empty; verify both scenarios in the browser
- [x] 10.6 Build the priority controls and constraints form; verify the submitted request body in the browser's network panel matches the entered values
- [x] 10.7 Build the site diagnosis view (bare-window timeline, stress calendar, trends with significance styling); verify against a sample analysis that all three appear and an insignificant trend is labeled
- [x] 10.8 Build the strategy comparison (calendar strip, overall score with interval, confidence, objective bars against the baseline); verify at least three strategies are visible together with the baseline labeled
- [x] 10.9 Build the strategy detail with the five explanation elements and an evidence table; verify gaps and local-review items are reachable in one interaction and each evidence entry shows source, period and resolution
- [x] 10.10 Build loading and error states (progress, disabled submit, climate-unavailable message with retry, cleared stale results); verify by forcing a failure response and by submitting twice quickly
- [x] 10.11 Document how to run the UI in `README.md`; verify the documented commands run as written and the page loads

## 11. Real data integration and demo readiness

- [ ] 11.1 Convert and validate GS#1's national grid export into `data/bundles/`; verify the validator passes and the lookup endpoint returns tier `grid` for points in Kyiv, Poltava and Mykolaiv oblasts
- [ ] 11.2 Validate and load GS#1's showcase field bundle; verify the showcase endpoint lists the fields and an analysis for one field reports tier `field`
- [ ] 11.3 Apply GS#2's knowledge-base review and threshold tuning; verify the knowledge base loads and a showcase analysis no longer reports draft-crop gaps for reviewed crops
- [ ] 11.4 Pre-warm the climate cache for the showcase areas and then for every grid cell; verify the summary lists no unexplained failures and an analysis succeeds with the network disconnected
- [ ] 11.5 Run one analysis per data tier in both languages in the browser and record the walkthrough in `docs/demo-script.md`; verify each returns at least three strategies with all five explanation elements
- [ ] 11.6 Review showcase results with GS#2 for agronomic plausibility in one southern-steppe and one forest-steppe field; verify by recording accepted results and applied adjustments in `docs/validation-notes.md`
- [ ] 11.7 Run the full backend test suite and the frontend build as the final gate; verify both pass

## Workflow follow-up

- Archive this change after the hackathon submission.
- Candidate follow-up change: a gradient-boosted model of seasonal NDVI anomaly trained on the national grid, used as additional stress evidence.
- Candidate follow-up change: live Earth Engine extraction for a user-drawn polygon, if GS#1's extraction is available as a Python function.
