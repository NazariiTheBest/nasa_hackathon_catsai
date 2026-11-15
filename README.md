# Field Shift

A farmer-centered decision-support tool that fuses NASA Earth observations with soil data, crop traits and farmer priorities to compare crop-rotation strategies. Built for the 2026 NASA Space Apps Challenge "Field Shift: Adapting Farms with NASA Data", Ukraine-first.

For a location and a current rotation it returns a site diagnosis (bare-soil windows, crop stress calendar, water balance, long-term trends) and at least three rotation strategies, each with why it was suggested, supporting evidence, expected benefits, information gaps, and risks that need local review. It supports, and does not replace, the judgment of the farmer and a local agronomist.

## Repository layout

| Path | Content |
|---|---|
| `backend/` | Python package `fieldshift`: data contract, NASA POWER client, diagnostics, rotation engine, explanations, HTTP API, tests |
| `frontend/` | Single-page web UI (Vite, React, TypeScript, Leaflet) |
| `kb/crops.yaml` | Crop knowledge base, editable by an agronomist |
| `config/engine.yaml` | Non-crop thresholds and score weights |
| `data/sample/` | Synthetic sample bundles used when no real bundle is present |
| `data/bundles/` | Real bundles from the geospatial scientists (not in git) |
| `contracts/` | Generated JSON Schemas for bundle files and the API |
| `docs/` | [Data contract](docs/data-contract.md) and [knowledge-base guide](docs/knowledge-base.md) |
| `openspec/` | Specifications, design and task list for the change that built this |

## Run the backend

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv if missing. Run from the `backend/` folder.

Install dependencies:

```bash
uv sync
```

Run the tests (offline; they use recorded NASA POWER responses):

```bash
uv run pytest
```

Start the API on http://127.0.0.1:8000:

```bash
uv run fieldshift serve
```

Check it is up:

```bash
curl http://127.0.0.1:8000/api/health
```

Interactive API documentation is at http://127.0.0.1:8000/api/docs.

The backend loads every bundle in `data/bundles/`; when that folder is empty it uses the synthetic sample in `data/sample/`. Climate series are fetched from NASA POWER on first use for a location and cached in `data/cache/power/`, so a location analyzed once works offline afterwards. Restart the backend after editing `kb/crops.yaml`, `config/engine.yaml` or adding a bundle.

## Run the UI

Requires Node 20 or newer. Start the backend first; the UI calls it through `/api`. Run from the `frontend/` folder.

Install dependencies:

```bash
npm install
```

Start the UI on http://localhost:5173:

```bash
npm run dev
```

Type-check and build for production (output in `frontend/dist/`):

```bash
npm run build
```

After changing an API model, regenerate the schema in `backend/` with `uv run fieldshift export-schemas`, then the UI's types:

```bash
npm run gen:api
```

Using it: click the map or pick a highlighted showcase field, list your current rotation, set your priorities, and press **Compare strategies**. The first analysis of a new area fetches about 40 years of daily climate from NASA POWER and takes several seconds; later ones use the stored series. The language switch (EN / УКР) is in the top right corner.

## Other backend commands

| Command | Purpose |
|---|---|
| `uv run fieldshift validate-bundle <dir>` | Check a bundle against the data contract |
| `uv run fieldshift convert-gee <table> <mapping> <out>` | Convert an Earth Engine export to the contract format |
| `uv run fieldshift prewarm --bundle <dir>` | Pre-fetch NASA POWER series for every unit of a bundle; resumable |
| `uv run fieldshift climate <lat> <lon>` | Fetch one location's climate series and print its provenance |
| `uv run fieldshift export-schemas` | Regenerate `contracts/` after changing a model |
| `uv run fieldshift make-sample` | Regenerate the synthetic sample bundles |
