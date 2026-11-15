# Design

## Context

See `proposal.md` for motivation and scope. Constraints that shape the approach:

- **Greenfield.** The repository holds only OpenSpec scaffolding and `CLAUDE.md`. It is not yet a git repository.
- **One development laptop.** Intel i5-9300H (4 cores / 8 threads), 24 GB RAM with about 8 GB free in normal use, GTX 1660 Ti with 6 GB VRAM, Windows 11. Drive C: has 32 GB free; the project lives on D: with 441 GB free. Python 3.10.8, uv, Node 22, Docker and git are installed; GDAL is not.
- **Three people, 48 hours.** One person owns backend, engine and UI. Geospatial Scientist #1 (GS#1) extracts satellite data in Google Earth Engine, which the team has confirmed access to. Geospatial Scientist #2 (GS#2) owns agronomic indices and scientific validation.
- **Ukraine-first.** US-only sources (Cropland Data Layer, SSURGO, OpenET, PRISM, NASS) are not used. Every remaining input is global, so the whole country can be extracted in one pass.
- **No rotation-outcome labels exist.** There is no dataset that maps a rotation to a measured outcome for Ukrainian fields.

The stack, the scoring approach, the national grid, bilingual output and knowledge-base ownership were proposed as defaults during exploration and accepted when this proposal was requested.

## Goals / Non-Goals

**Goals:**

- Three people can work in parallel from hour 3 against contracts that do not change shape when a new variable or crop is added.
- Any click inside Ukraine returns an analysis backed by satellite and soil data, not only climate.
- Every number shown to the farmer is traceable to a named source, period and spatial resolution.
- The demo runs with the network unplugged once the cache is warm.
- An analysis with warm cache returns within 10 seconds on the development laptop.

**Non-Goals:**

- Field-scale accuracy from 50 km climate cells. The tool states the resolution of each input instead.
- Yield prediction in physical units. Income is a relative index.
- Raster handling, tile serving or a spatial database in the backend.
- A trained model anywhere in the path that produces a recommendation.

## Decisions

### D1. Raster work stays in Earth Engine; the backend sees only tables

GS#1 reduces rasters to per-unit statistics in Earth Engine and exports tables. The backend reads Parquet, CSV and GeoJSON only.

- *Why:* no GDAL on the laptop, 4 cores, one backend developer. Tabular inputs keep the backend dependency set to pure wheels (pandas, pyarrow, DuckDB, shapely).
- *Alternative considered:* rasterio/rioxarray in the backend with Cloud-Optimized GeoTIFFs. Rejected: installation risk on Windows, slow zonal statistics on 4 cores, and it moves GS#1's work onto the backend developer.

### D2. Three data tiers resolved by location

```
 point (lat, lon)
      |
      v
 inside a showcase field? --yes--> tier "field"
      | no                          (per-field MODIS, soil, terrain)
      v
 inside a national grid cell? --yes--> tier "grid"
      | no                              (cropland-masked 10 km cell)
      v
 tier "climate_only"  (NASA POWER only; soil assumed, flagged)

 NASA POWER daily climate is used in every tier.
```

- *Why:* the national grid makes any Ukrainian location demonstrable, while the showcase fields show the finer story. Degrading tiers give the "information gaps and uncertainty" output real content.
- *Alternative considered:* showcase areas only. Rejected: a judge clicking elsewhere would get climate-only output. *Alternative considered:* live Earth Engine extraction per request. Deferred to a follow-up: it adds service-account setup, quota and latency risk on the demo path.

### D3. One bundle contract for both grid cells and fields, in long format

A bundle is a directory `data/bundles/<bundle_id>/`:

| File | Required | Content |
|---|---|---|
| `manifest.json` | yes | `contract_version`, `bundle_id`, `unit_type`, `created_at`, `author`, `sources[]` (`variable`, `product`, `version`, `native_res_m`, `date_start`, `date_end`), `notes` |
| `units.geojson` | yes | FeatureCollection in WGS84 (longitude, latitude order). Properties: `unit_id` (string, unique), `unit_type` (`field` or `grid_cell`), `name` (optional), `area_ha`, `cropland_frac` (grid cells) |
| `timeseries.parquet` | yes | Long format, one row per unit, date and variable (columns below) |
| `static.parquet` | yes | One row per unit: `clay_pct`, `sand_pct`, `soc_pct`, `ph`, `slope_pct`, `elevation_m`; optional `awc_mm_per_m`, `k_factor`, `drainage_class` |
| `crop_history.csv` | no | `unit_id, year, crop_id, cover_frac, method, confidence`; `method` is `declared`, `worldcereal` or `ndvi_phenology` |
| `suitability.csv` | no | `unit_id, crop_id, suitability_index` (0-100), `scenario`, `water_supply`, `source` |

`timeseries.parquet` columns:

| Column | Type | Rule |
|---|---|---|
| `unit_id` | string | Must exist in `units.geojson` |
| `date` | date | Start of the composite period, UTC |
| `variable` | string | From the controlled vocabulary below |
| `value` | float64 | Unit-level mean after QA masking, scale factor applied; null when no valid data |
| `std` | float64, nullable | Spatial standard deviation within the unit |
| `valid_frac` | float64 | Fraction of unmasked pixels, 0 to 1 |
| `source` | string | Product and version, for example `MOD13Q1.061` |
| `res_m` | int32 | Native resolution in meters |

Controlled vocabulary, version 1.0:

| `variable` | Unit | Valid range | Expected source |
|---|---|---|---|
| `ndvi`, `evi` | unitless | -1 to 1 | MODIS MOD13Q1 |
| `et` | mm/day | 0 to 20 | MODIS MOD16A2GF |
| `sm_surface`, `sm_rootzone` | m3/m3 | 0 to 1 | SMAP L4 |
| `precip` | mm/day | 0 to 500 | GPM IMERG |
| `t2m_mean` | deg C | -60 to 60 | ERA5-Land (optional) |
| `lst_day` | deg C | -60 to 80 | optional |

Sentinel fill values (for example -9999, -3000, 32767) are rejected by the validator, as are values outside the valid range, so an unscaled MODIS integer is caught at hand-off.

- *Why long format:* a new variable is a new value in one column. Neither side changes a schema, which matters when three people move in parallel.
- *Why one schema for both unit types:* one validator, one ingest path, one lookup.
- *Alternative considered:* wide tables with one column per variable. Rejected: every added variable becomes a coordinated schema change. Wide input is still accepted at the edge (D4).

### D4. GS#1 delivers Earth Engine's native shape; ingest converts it

Earth Engine exports one row per unit and image with one column per band. A converter takes that table plus a small mapping (`band`, `variable`, `scale`, `source`, `res_m`) and writes contract-conformant `timeseries.parquet`.

- *Why:* reshaping in Earth Engine scripts is awkward and error-prone; in pandas it is one `melt`.
- *Alternative considered:* require long format from GS#1. Rejected as avoidable friction.

### D5. Time series are queried from Parquet with DuckDB, not loaded into memory

The national grid is about 10 million rows. DuckDB reads only the rows for one `unit_id` per request.

- *Why:* a full pandas load costs several hundred MB against 8 GB of free RAM and slows start-up. DuckDB is a single wheel with no server.
- *Alternative considered:* SQLite import. Rejected: an extra import step and slower analytical scans. *Alternative considered:* PostGIS. Rejected: Docker's disk lives on C:, which has 32 GB free, and it is another moving part.

Unit lookup uses shapely geometries held in memory with a spatial index: showcase fields first, then grid cells.

### D6. NASA POWER daily point API, cached per source grid cell

- Parameters: `T2M`, `T2M_MAX`, `T2M_MIN`, `T2MDEW`, `RH2M`, `WS2M`, `PRECTOTCORR`, `ALLSKY_SFC_SW_DWN`, `GWETTOP`, `GWETROOT`, community `AG`.
- Period: 1 January 1985 through the last complete calendar year. Partial current-year data is not used in statistics.
- POWER's fill value (-999) becomes null.
- Cache key: the request coordinates snapped to POWER's meteorological grid (0.5 degree latitude, 0.625 degree longitude). One Parquet file per cell under `data/cache/power/`.
- A pre-warm command walks a list of points (showcase fields or every grid cell), skips cells already cached and can be re-run after interruption. Full national coverage is about 300 cells.
- When POWER is unreachable: serve the cache if the cell is present, otherwise fail with an explicit "climate data unavailable" error. Never return partial or synthetic climate.

- *Why snap to the source grid:* nearby clicks share one cache entry, and the cache can be completed for the whole country in advance.
- *Alternative considered:* ERA5-Land from the bundle as the climate source. Rejected as the primary source: POWER is the challenge's flagship API and works for any point without a bundle. ERA5-Land remains an optional bundle variable.

### D7. Rotations are ordered crop slots with dates, not one crop per calendar year

Winter wheat, winter barley and winter rapeseed are sown in autumn and harvested the following July, so a `{year, crop}` model cannot represent them.

- Farmer input stays simple: an ordered list of crop ids and optional cover crops.
- The engine builds a calendar of slots `{crop_id, role, sow: {year_index, doy}, harvest: {year_index, doy}}` from knowledge-base sowing windows, stage lengths and a 7-day turnaround.
- The gap between one slot's harvest and the next slot's sowing is a bare window.
- The baseline is never rejected for agronomic infeasibility. If declared crops cannot fit the knowledge-base windows, dates are clamped and a notice is attached, because the farmer's real practice outranks the knowledge base.

- *Alternative considered:* asking the farmer for sowing and harvest dates. Rejected for the MVP: more input friction than a hackathon demo can afford.

### D8. Crop knowledge base as a reviewed YAML file

`kb/crops.yaml`, validated on load. One record per crop (values below are illustrative, not final):

```yaml
- id: sunflower
  name: {en: Sunflower, uk: Соняшник}
  family: asteraceae
  role: cash                    # cash | cover | forage
  season: spring                # winter | spring
  sowing_window_doy: [100, 135]
  default_sow_doy: 115
  t_base_c: 6
  gdd_to_maturity: 1600
  stages_days: [25, 35, 45, 25] # initial, development, mid, late (FAO-56)
  kc: {ini: 0.35, mid: 1.05, end: 0.35}
  root_depth_m: 1.5
  depletion_fraction: 0.45
  stress:
    heat:  {stage: mid, tmax_c: 35}
    frost: {stage: ini, tmin_c: -4}
  drought_tolerance: 0.7        # 0 to 1
  n_fixation_kg_ha: 0
  residue_cover: 0.3            # 0 to 1
  forage_value: 0.1             # 0 to 1
  market_value: 0.9             # 0 to 1
  min_return_years: 7
  irrigation_required: false
  sources: ["FAO-56 Tables 11, 12, 22"]
  review_status: draft          # draft | reviewed
```

- Initial values are drafted from FAO-56, FAO ECOCROP and cover-crop guides and marked `draft`. GS#2 reviews and flips them to `reviewed`. A strategy that uses a draft crop carries an information-gap note, so development is never blocked on review and the output stays honest about it.
- Engine thresholds that are not crop-specific (bare NDVI threshold, hot-day temperature, erosive-rain threshold, suitability floor, objective weights reserved for resilience and pest break) live in `config/engine.yaml` so GS#2 can tune them without touching code.
- Planned crop list: winter wheat, winter barley, spring barley, maize, sunflower, soybean, winter rapeseed, sugar beet, sorghum, millet, chickpea, buckwheat, peas, alfalfa, sainfoin, winter rye, white mustard, oilseed radish, phacelia, hairy vetch.

- *Alternative considered:* a database table. Rejected: a text file is reviewable in a diff and editable by a non-developer.

### D9. Site diagnostics use established agronomic methods

| Output | Method |
|---|---|
| Reference evapotranspiration | FAO-56 Penman-Monteith, daily, from POWER inputs; temperature-based (Hargreaves) estimate on days without radiation |
| Crop water balance | FAO-56 single crop coefficient with a daily root-zone bucket: capacity is water-holding capacity times rooting depth; actual use is reduced by the FAO-56 stress coefficient once depletion passes the crop's depletion fraction. Winter crops use a dormancy coefficient while 10-day mean temperature is below base temperature |
| Stress calendar | For each crop and hazard, the share of replay years in which the knowledge-base threshold is crossed inside the sensitive stage. Drought is a run of consecutive days of severe water stress (FAO-56 stress coefficient below 0.5); counting any day beyond readily available water flagged rainfed maize in almost every year and told the farmer nothing |
| Trends | Theil-Sen slope and Mann-Kendall p-value on annual series: growing-season (April-September) mean temperature, precipitation, precipitation minus reference evapotranspiration, hot-day count and summer root-zone wetness. Significant at p < 0.05 |
| Short records | Series under 15 years (SMAP begins in 2015) are reported as anomalies against their own mean, never as trends |
| Bare-soil windows | Derived from the rotation calendar in every tier; cross-checked against periods where the multi-year median NDVI is below the bare threshold when a time series exists |
| Erosion exposure | Mean total of daily rainfall on erosive-rain days inside each bare window, multiplied by slope and erodibility factors when available. A relative index, not tonnes per hectare |
| Derived soil properties | Water-holding capacity by the Saxton-Rawls pedotransfer functions and erodibility by the EPIC equation, from texture and organic carbon, marked as derived |

- *Why:* these are standard, citable and cheap to compute, and each yields a number with a clear meaning for the evidence list.
- *Alternative considered:* a learned stress model. Deferred to the follow-up change; thresholds from the knowledge base are sufficient and reviewable.

### D10. Recommendation by constrained generation and multi-objective scoring, not a trained model

Pipeline: baseline calendar -> candidates -> hard constraints -> objective scores per replay window -> overall score -> selection.

**Candidates.** Operators applied to the baseline singly and in pairs, deduplicated, capped at 100:

| Operator | Effect |
|---|---|
| `insert_cover` | Put a cover crop into a bare window of at least 60 days that fits its sowing window |
| `swap_drought_tolerant` | Replace the main crop with the largest water deficit by a more tolerant crop of the same season |
| `add_legume` | Replace a main crop with a legume, or insert a legume cover |
| `diversify` | Replace a crop that repeats a family or sits at its return-interval limit |
| `extend` | Lengthen the cycle by one year with a new crop, within the user's maximum |

**Hard constraints.** Sowing windows and turnaround; enough accumulated heat units in at least 80% of replay years; user-excluded crops; maximum cycle length; no irrigation-dependent crop when irrigation is unavailable; suitability index above the configured floor when a suitability table exists.

Return intervals are a hard constraint only on what an alternative adds: it may not introduce a crop, or grow a baseline crop more often, in a way that breaks the crop's or family's minimum return interval. A violation inherited from the baseline (sunflower every second year is common practice) is kept as allowed, penalized through `pest_break`, marked on the strategy and raised as a local-review reminder. Forbidding it outright would make every alternative drop the farmer's main cash crop, which no farmer would accept.

**Objectives**, each normalized to 0-1, higher is better:

| Objective | Basis | Weather-dependent |
|---|---|---|
| `water` | Share of crop water demand met, with cover-crop water use charged to the strategy | yes |
| `nitrogen` | Mean nitrogen-fixation credit per year | no |
| `erosion` | One minus the relative erosion-exposure index over the cycle | yes |
| `organic_matter` | Residue cover class and share of days with living cover | no |
| `forage` | Mean forage value | no |
| `income` | Market value index reduced by stress-driven yield risk | yes |
| `resilience` | One minus stage-weighted stress probability | yes |
| `pest_break` | Family diversity and margin above return intervals | no |

**Overall score** for strategy `s` in replay window `r`:

```
overall(s, r) = 0.8 * sum_k( w_k * u_k(s, r) ) + 0.1 * u_resilience(s, r) + 0.1 * u_pest_break(s)
```

`w_k` are the six farmer priorities (water, nitrogen, erosion, organic matter, forage, income) normalized to sum to 1. If all are zero, equal weights are used and a notice is returned.

**Replay.** An N-year cycle is replayed from every historical start year that has N years of data. The response reports the median and the P10-P90 interval of `overall` across windows, plus the window count. The daily simulation is vectorized across replay windows with numpy to meet the response-time goal.

**Selection.** The baseline is always returned and flagged. Alternatives are taken in descending median score, skipping any whose crop sequence and operator set duplicate one already selected, until three are chosen. Each is labeled by the objective it improves most against the baseline.

**Confidence.** Start at `high`. Drop one level for tier `grid` and two for `climate_only`; one if the P10-P90 width exceeds 0.15; one if the strategy uses a draft crop or two or more derived or assumed inputs. The floor is `low`.

- *Why not a trained model:* no rotation-outcome labels exist. Training on invented labels would produce a result no judge or agronomist could audit. Every score here decomposes into contributions that the explanation can cite.
- *Alternative considered:* gradient boosting on synthetic outcomes. Rejected for the reason above. *Alternative considered:* exhaustive search over all sequences. Rejected: operators on the baseline keep alternatives recognizable to the farmer and the candidate count small.

### D11. Explanations are templates over structured evidence

Each strategy carries `why[]`, `evidence[]`, `benefits[]`, `gaps[]` and `local_review[]`. An evidence record is `{indicator, value, unit, source, period, resolution, scope, method}` where `scope` is `field`, `grid_cell` or `climate_cell`. Text is rendered from templates in English and Ukrainian with the same parameters.

- *Why:* identical requests give identical wording, every claim is traceable, and the demo has no dependency on a model service.
- *Alternative considered:* a language model that rewrites the evidence into prose. Deferred: it adds a network dependency and a hallucination risk on the one output judges will read most closely.

### D12. API shape

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Loaded bundles, crop count, cache size |
| `GET /api/locate?lat=&lon=` | Data tier and unit summary for a point |
| `GET /api/crops?lang=` | Crop catalog with localized names, role, family, review status |
| `GET /api/showcase` | Showcase areas and field geometries as GeoJSON |
| `POST /api/analyze` | Site diagnosis and strategies |

Analyze request:

```json
{
  "location": {"type": "point", "lat": 47.1, "lon": 32.0},
  "baseline": {"crops": ["winter_wheat", "sunflower", "spring_barley"], "covers": []},
  "priorities": {"water": 0.8, "nitrogen": 0.3, "erosion": 0.6,
                 "organic_matter": 0.5, "forage": 0.0, "income": 0.7},
  "constraints": {"irrigation_available": false, "excluded_crops": [], "max_cycle_years": 5},
  "lang": "uk"
}
```

`location` may also be `{"type": "unit", "unit_id": "..."}` or `{"type": "polygon", "geometry": <GeoJSON>}`; a polygon is reduced to its centroid and a notice says so.

Analyze response (abridged, values illustrative):

```json
{
  "meta": {"contract_version": "1.0", "engine_version": "0.1.0", "data_tier": "grid",
           "generated_at": "2026-11-14T10:00:00Z", "notices": []},
  "site": {
    "unit": {"unit_id": "g_04512", "unit_type": "grid_cell"},
    "bare_windows": [{"start": {"year_index": 0, "doy": 196}, "end": {"year_index": 1, "doy": 105},
                      "days": 274, "erosion_exposure": 0.62}],
    "observed_low_cover": [{"start_doy": 305, "end_doy": 80, "median_ndvi": 0.21, "years": 24}],
    "stress": [{"crop_id": "sunflower", "hazard": "heat", "stage": "mid",
                "probability": 0.33, "years_hit": 12, "years_total": 36}],
    "water_balance": [{"crop_id": "sunflower", "demand_mm": 520, "supply_mm": 310, "deficit_mm": 210}],
    "trends": [{"indicator": "water_balance_apr_sep_mm", "slope_per_decade": -18.2,
                "p_value": 0.03, "significant": true, "period": "1985-2025"}]
  },
  "strategies": [{
    "id": "s1", "label": "Soil builder", "is_baseline": false, "operators": ["insert_cover"],
    "slots": [{"crop_id": "winter_wheat", "role": "main",
               "sow": {"year_index": 0, "doy": 265}, "harvest": {"year_index": 1, "doy": 195}}],
    "scores": {"overall": {"median": 0.71, "p10": 0.64, "p90": 0.77, "windows": 36},
               "objectives": {"water": 0.62, "nitrogen": 0.40, "erosion": 0.81, "organic_matter": 0.70,
                              "forage": 0.10, "income": 0.66, "resilience": 0.58, "pest_break": 0.75}},
    "vs_baseline": {"water_demand_mm_per_year": 35, "bare_days_per_year": -120, "n_kg_ha_per_year": 0},
    "confidence": "medium",
    "why": ["..."], "evidence": [{"indicator": "bare_days_per_year", "value": 150, "unit": "days",
            "source": "MOD13Q1.061", "period": "2001-2025", "resolution": "250 m", "scope": "grid_cell",
            "method": "rotation calendar, cross-checked with NDVI"}],
    "benefits": ["..."], "gaps": ["..."], "local_review": ["..."]
  }]
}
```

Errors: 422 with field-level messages for invalid input; 503 with code `climate_unavailable` when climate data cannot be obtained.

The API models are the single source of truth: JSON Schemas for the team and TypeScript types for the frontend are generated from them, not written by hand.

### D13. Stack and layout

- **Backend:** Python 3.12 pinned with uv (the system default is 3.10.8), FastAPI, Pydantic v2, httpx, pandas, numpy, scipy, pyarrow, DuckDB, shapely, PyYAML, a small CLI. Tests with pytest.
- **Frontend:** Vite, React, TypeScript, Leaflet through react-leaflet. Charts (calendar strip, score range, goal bars, meters) are hand-built HTML and CSS; a chart library was planned and dropped because every chart here is a thin bar or a timeline, which plain markup draws with less code than configuring a library. Types generated from the OpenAPI schema. Vite proxies `/api` to the backend in development.
- **No Docker in the development loop.** Its virtual disk sits on C:.

```
backend/
  pyproject.toml
  src/fieldshift/
    contracts/     bundle, knowledge-base and API models
    ingest/        validator, Earth Engine converter, unit lookup
    climate/       POWER client, cache, pre-warm
    kb/            loader
    diagnostics/   ET0, water balance, stress, trends, bare soil
    engine/        calendar, operators, constraints, objectives, selection
    explain/       evidence, templates (en, uk)
    api/           FastAPI application
  tests/
frontend/          Vite + React + TypeScript
kb/crops.yaml
config/engine.yaml
contracts/         generated JSON Schemas
data/
  sample/          synthetic bundle (committed)
  bundles/         real bundles (ignored)
  cache/           POWER cache (ignored)
docs/data-contract.md
```

- *Alternative considered:* Streamlit for the UI. Rejected: map interaction and a side-by-side comparison layout are clumsy there, and the UI is what judges see. *Alternative considered:* MapLibre GL. Rejected: Leaflet is simpler for point picking and a GeoJSON overlay, which is all the map needs.

### D14. Mock-first sequencing

A synthetic sample bundle and a recorded POWER response are produced before any engine code, so the backend, UI and tests run with no external data. Real bundles replace the sample by configuration.

Checkpoints: hour 3, contracts, sample bundle and validator published to the team; hour 14, first real bundle passes the validator; hour 26, end-to-end analysis on real data; hour 40, feature freeze; hours 40-48, cache pre-warm, demo script and submission material.

## Risks / Trade-offs

- [One person owns backend, engine and UI] -> The UI stays a single page; GS#2 owns knowledge-base values; contracts are frozen at hour 3 so nobody waits on anybody.
- [Knowledge-base quality decides credibility] -> Draft values from published tables on day one, a visible draft/reviewed status, and a gap note on any strategy that uses a draft crop.
- [The national grid export may queue for hours in Earth Engine] -> Start by hour 3, split exports by year, and develop against the sample bundle. If the grid slips, showcase fields plus the climate-only tier still satisfy every requirement.
- [NASA POWER is slow or unreachable during the demo] -> Per-cell persistent cache and a resumable pre-warm for showcase areas first, then the whole country.
- [POWER cells are about 50 km] -> Field-specific signal comes from the bundle; every climate-based evidence record carries its resolution and a standing gap note.
- [Soil properties are modeled, not surveyed] -> SoilGrids values and derived water capacity and erodibility are marked as modeled or derived in evidence.
- [A grid cell is not the farmer's field] -> Tier `grid` caps confidence at `medium` and adds a gap note; bare windows come from the declared rotation, with the cell's NDVI only as a cross-check.
- [Cover crops can dry the soil in the steppe] -> Cover-crop water use is charged to the water objective and surfaced as a disclosed trade-off, not hidden.
- [Winterkill depends on snow cover, which is not modeled] -> Winterkill is reported from minimum temperature alone with a gap note.
- [Income is the weakest objective] -> A relative index only, labeled low-confidence, with a local-review flag about prices and logistics.
- [The tool cannot see mine contamination, war damage or current irrigation status] -> Standing local-review reminders on every strategy.
- [Scores look more precise than they are] -> The interval and confidence level are shown wherever the overall score is shown.
- [Response time with 100 candidates and about 36 replay windows] -> Vectorize across windows, cap candidates, and measure against the 10-second target in a test.
- [uv's package cache defaults to C:, which has 32 GB free] -> Point the cache at D: if space becomes tight.

## Open Questions

None of these change the specs, the approach or the task breakdown.

- Does GS#1 work in the Earth Engine Python API or the JavaScript editor? Python would make live per-polygon extraction a feasible follow-up.
- Which oblasts and which specific fields form the showcase areas? Current intent: one southern-steppe area (Mykolaiv or Odesa oblast) and one forest-steppe area (Poltava, Cherkasy or Vinnytsia oblast), in government-controlled territory away from the front line.
- What is the fastest route to FAO GAEZ v4 rasters? The suitability table is optional, so the answer only affects whether suitability screening has data.
- Which NASA GIBS vegetation layer id and tile matrix set should the map overlay use? To be confirmed against the GIBS capabilities document when the layer is wired in.
- Are the SMAP and IMERG Earth Engine asset versions current? GS#1 confirms in the catalog.
