# Proposal

## Why

Ukrainian farmers are changing rotations under hotter summers, less reliable rain and, in the south, lost irrigation, yet a crop that helps the soil can cost too much water, miss the growing season or fail to sell. The 2026 NASA Space Apps "Field Shift" challenge asks for a farmer-centered decision-support tool that fuses NASA Earth observations with soil data, crop traits and farmer priorities. This repository is empty and a three-person team has 48 hours, so the first change must deliver one complete, demonstrable slice built on fixed data contracts that let all three people work in parallel.

## What Changes

Everything below is new; there is no existing behavior to modify.

- Add a file contract ("bundle") for pre-processed Earth-observation features delivered by the geospatial scientists, with a standalone validator, a converter from Earth Engine's native export shape, and point-to-unit lookup. Two bundle kinds share one schema: a national grid of about 10 km cropland-masked cells covering Ukraine, and hand-digitized showcase fields.
- Add live retrieval of multi-decade daily climate series from NASA POWER for any point, persistently cached per source grid cell and pre-warmable so the demo survives network loss.
- Add a crop knowledge base of about 20 Ukraine-relevant crops (cash, drought-tolerant, legume, forage, cover) with cited trait values, a draft/reviewed status and Ukrainian and English names, editable without code changes.
- Add site diagnostics that fuse climate, satellite and soil inputs: bare-soil windows and their erosion exposure, a per-crop stress calendar (heat, frost, winterkill, drought), crop water balance, and long-term trends with significance.
- Add a rotation engine that derives alternative rotations from the farmer's baseline through named operators, filters them with hard agronomic and user constraints, scores them on eight objectives weighted by farmer priorities, replays them across historical weather for an uncertainty interval, and returns the baseline plus at least two distinct alternatives.
- Add explanation output for every strategy with the five elements the challenge requires: why it was suggested, supporting evidence, expected benefits, information gaps and uncertainty, and risks requiring local review. Text is template-based, traceable to evidence records, and available in Ukrainian and English.
- Add an HTTP API exposing location lookup, the crop catalog, showcase areas, and analysis, with a published machine-readable schema.
- Add a single-page map-based web UI for selecting a location, entering the baseline rotation, priorities and constraints, and comparing strategies with their explanations.

Out of scope for this change:

- Any trained model in the recommendation core. A gradient-boosted model of seasonal NDVI anomaly from the national grid is a candidate follow-up change.
- Live Earth Engine extraction for user-drawn polygons, and polygon drawing in the UI. The API accepts a polygon and uses its centroid.
- Raster processing in the backend. All raster work happens in Earth Engine on the geospatial scientists' side.
- Generative-model wording, user accounts, persistence of user sessions, deployment to a hosting provider, and mobile-specific layouts.
- Regions outside Ukraine as a first-class target. Any point where NASA POWER has data still gets a climate-only analysis.

## Capabilities

### New Capabilities

- `geodata-bundles`: The file contract for pre-processed Earth-observation features (grid cells and fields), its validation, conversion from Earth Engine exports, and lookup of the unit that contains a point.
- `climate-data`: Multi-decade daily climate series from NASA POWER for any point, with persistent caching, pre-warming and defined behavior when the source is unreachable.
- `crop-knowledge-base`: The catalog of crop traits with provenance, review status and bilingual names that all agronomic reasoning reads from.
- `site-diagnostics`: Fusion of climate, satellite and soil inputs into bare-soil windows, erosion exposure, crop stress calendar, water balance and long-term trends, with an explicit data tier.
- `rotation-recommendation`: Generation, constraint filtering, multi-objective scoring, historical replay and selection of rotation strategies relative to a baseline.
- `strategy-explanation`: The five explanation elements per strategy, evidence records, and Ukrainian/English rendering.
- `analysis-api`: The HTTP interface for location lookup, crop catalog, showcase areas and analysis, including validation, error reporting and the published schema.
- `decision-support-ui`: The single-page map-based workflow for inputs, site diagnosis, strategy comparison and explanation detail.

### Modified Capabilities

None. The project has no existing specs.

## Impact

- **Repository**: becomes a git repository with `backend/` (Python package and tests), `frontend/` (web UI), `kb/` (crop knowledge base), `config/` (engine thresholds), `data/` (sample bundle committed; real bundles and cache ignored), `contracts/` (exported schemas) and `docs/` (data contract for the team).
- **Team hand-offs**: Geospatial Scientist #1 delivers bundles that pass the validator; Geospatial Scientist #2 reviews knowledge-base values and engine thresholds. Both are unblocked from hour 3 by the published schemas, a synthetic sample bundle and the validator.
- **External services**: NASA POWER daily point API (climate), NASA GIBS and a public base-map tile service (map display). No credentials are required by any of them.
- **Runtime**: Python 3.12 managed by uv and Node 22 on the development laptop (4 cores, 24 GB RAM). No GPU, GDAL or Docker dependency.
- **Data volume**: the national grid bundle is about 10 million rows and under 100 MB of Parquet; the climate cache is about 300 cells for full national coverage.
