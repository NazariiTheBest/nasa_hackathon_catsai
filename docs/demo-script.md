# Demo script

**Status: draft, walked on the synthetic sample bundles on 15 November 2026.** Re-walk it on the real bundles before the demo and replace the field names and the numbers quoted below. Climate figures already come from live NASA POWER and are real.

## Before the demo

Run from `backend/`. Pre-fetch climate for the showcase fields and the grid so nothing depends on the venue network:

```bash
uv run fieldshift prewarm --bundle ../data/sample/ua-sample-fields
```

```bash
uv run fieldshift prewarm --bundle ../data/sample/ua-sample-grid
```

Start the backend (`uv run fieldshift serve`) and the UI (`npm run dev` in `frontend/`), then open http://localhost:5173. Check http://127.0.0.1:8000/api/health lists the bundles you expect.

## Walkthrough (about three minutes)

| Step | Do | What it shows |
|---|---|---|
| 1 | Press **Go to showcase fields**, click a highlighted field | "Field-level data": satellite, soil and terrain for this field |
| 2 | Leave winter wheat and sunflower, add maize | The farmer's own rotation is the baseline; nothing is entered about dates |
| 3 | Raise **Water conservation** to the top, leave **Forage value** off | Priorities drive the ranking; forage is never given as a reason |
| 4 | Press **Compare strategies** | First run fetches about 40 years of NASA POWER; later runs take two to three seconds |
| 5 | In **Site diagnosis**, point at the calendar strip and the first bare window | Nine to ten months of bare soil after winter wheat, with its erosion exposure |
| 6 | Point at **Long-term trends** | Significant trends are marked; insignificant ones are greyed and labeled |
| 7 | In **Rotation strategies**, compare the cards | Baseline plus three alternatives, each with score, P10-P90 range and confidence |
| 8 | Open an alternative with a cover crop | Benefit in bare-soil days, and the water cost stated as a trade-off |
| 9 | Scroll to **Supporting evidence** | Every number has a source, period, resolution and what it describes |
| 10 | Point at **Information gaps** and **Risks requiring local review** | The tool says what it does not know and what an agronomist must check |
| 11 | Click a point outside the fields, run again | "Regional data (grid cell)": the gaps now say the values describe a 10 km cell |
| 12 | Switch to **УКР** | Same numbers, Ukrainian wording |
| 13 | Tick **NASA vegetation index** on the map | MODIS NDVI from NASA GIBS as context |

## What was observed on the sample walk

Rotation winter wheat, maize, sunflower; water conservation at maximum.

| Location | Tier | Strategies | Confidence | Notes |
|---|---|---|---|---|
| Demo field 1 (49.144, 32.136) | field | baseline + 3 | medium | Alternatives: sorghum for maize with a hairy vetch cover; cover crop only; four-year rotation with chickpea |
| Point 49.130, 32.348 | grid | baseline + 3 | low | Gaps add "grid cell, not your field" and "soil derived from texture" |
| Point 49.233, 33.774 | climate only | baseline + 3 | low | No satellite or soil data; default water capacity stated as assumed |

Real climate findings at the field's NASA POWER cell (1985-2025): growing-season temperature rising 0.54 deg C per decade and hot days rising 5.7 per decade, both significant; growing-season precipitation and water balance show no significant trend.

Confidence is capped at medium everywhere until the agronomist marks crops as reviewed in `kb/crops.yaml`; every strategy says so in its gaps.

## If something goes wrong

- **"Climate data could not be reached"**: the location's climate cell is not stored and NASA POWER did not answer. Use a pre-warmed showcase field, or press **Try again**.
- **"The analysis server could not be reached"**: the backend is not running on port 8000.
- **The NASA vegetation layer shows a warning**: the GIBS tiles did not load. The rest of the tool is unaffected.
