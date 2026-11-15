# Crop knowledge base: review guide

For the agronomist reviewing the tool's assumptions. Two plain text files hold every agronomic number the tool uses. Editing them changes the tool's behavior the next time the backend starts; no code changes are needed.

| File | Holds |
|---|---|
| [`kb/crops.yaml`](../kb/crops.yaml) | One record per crop: calendar, water use, stress thresholds, soil and market traits |
| [`config/engine.yaml`](../config/engine.yaml) | Thresholds that are not crop-specific: what counts as bare soil, a hot day, erosive rain, and how scores are weighted |

All crop values start as `review_status: draft`. A strategy that uses a draft crop tells the farmer that its trait values are not yet reviewed. When you have checked a crop, set `review_status: reviewed` and the note disappears.

## Crop traits

| Trait | Unit | Meaning and effect |
|---|---|---|
| `id` | | Stable identifier. Do not rename: bundles and requests refer to it |
| `name.en`, `name.uk` | | Display names |
| `family` | | Botanical family in lower case. Drives the pest-cycle and family-repeat rules |
| `role` | `cash`, `cover`, `forage` | Cover crops are inserted into bare-soil windows; the others are main crops |
| `season` | `winter`, `spring` | Winter crops are sown in autumn and harvested the next summer |
| `drought_alternative` | true/false | Marks crops offered as drought-tolerant replacements |
| `sowing_window_doy` | day of year | Earliest and latest acceptable sowing day. Alternatives never sow outside it |
| `default_sow_doy` | day of year | Sowing day used when nothing forces another |
| `t_base_c`, `gdd_to_maturity` | deg C, degree-days | A crop is only introduced where the site supplies these heat units in at least 80% of years |
| `stages_days` | days | Lengths of the initial, development, mid-season and late-season stages (FAO-56 Table 11). Their sum sets the harvest date |
| `kc.ini`, `kc.mid`, `kc.end` | | Crop coefficients (FAO-56 Table 12). Scale water demand |
| `root_depth_m` | m | Maximum rooting depth (FAO-56 Table 22). Deeper roots buffer dry spells |
| `depletion_fraction` | 0-1 | Share of available water the crop uses before stress begins (FAO-56 Table 22, `p`) |
| `stress.heat` | stage, `tmax_c` | Heat event: daily maximum at or above `tmax_c` during the stage |
| `stress.frost` | stage, `tmin_c` | Frost event: daily minimum at or below `tmin_c` during the stage |
| `stress.winterkill` | stage, `tmin_c` | Winterkill event for winter crops. Snow cover is not modeled |
| `drought_tolerance` | 0-1 | Reduces the yield penalty from water deficit |
| `n_fixation_kg_ha` | kg N/ha | Net nitrogen credit left for the following crop |
| `residue_cover` | 0-1 | Ground cover left by residues. Reduces erosion exposure after harvest and raises the organic-matter score |
| `forage_value`, `market_value` | 0-1 | Relative indices. Market value is the weakest input; say so if it looks wrong |
| `min_return_years` | years | Shortest interval before the crop returns to the same field |
| `irrigation_required` | true/false | Never introduced where the farmer reports no irrigation |
| `sources` | | Where the values came from. At least one is required |
| `review_status` | `draft`, `reviewed` | See above |

Stages are named `ini`, `dev`, `mid` and `late`. For most grain crops flowering and grain fill fall in `mid`, which is why heat thresholds point there.

## How to edit

1. Open `kb/crops.yaml` in any text editor and change the value.
2. Add the source of the new value to that crop's `sources` list.
3. Set `review_status: reviewed` once every value of the crop has been checked.
4. Check the file loads. Run from the `backend/` folder:

```bash
uv run python -c "from fieldshift.kb import load_kb; kb = load_kb(); print(len(kb), 'crops loaded;', sum(c.review_status == 'reviewed' for c in kb.crops.values()), 'reviewed')"
```

If a value is out of range or a trait is missing, the message names the crop, the trait and the allowed range, and nothing is loaded until it is fixed.

Example edit: to make sunflower heat-sensitive from 33 deg C instead of 35, change

```yaml
  stress:
    heat: {stage: mid, tmax_c: 35}
```

to

```yaml
  stress:
    heat: {stage: mid, tmax_c: 33}
```

Sunflower's heat-stress probability, its resilience and income scores, and every strategy containing sunflower are recomputed with the new threshold after the backend restarts.

## Engine thresholds

`config/engine.yaml` is commented line by line. The entries most worth an agronomist's attention:

| Key | Default | Why it matters |
|---|---|---|
| `bare_ndvi_threshold` | 0.30 | Median NDVI below this is reported as low cover. Regional soils and residues shift the right value |
| `hot_day_tmax_c` | 30 | Defines the hot-day trend shown to the farmer |
| `erosive_rain_mm` | 10 | Daily rainfall counted as erosive |
| `min_bare_window_days` | 60 | Shortest gap a cover crop is proposed for |
| `min_cover_growth_days` | 45 | A cover crop that cannot grow this long is not proposed |
| `heat_units_min_share` | 0.8 | How reliable the season must be before a crop is introduced |
| `suitability_floor` | 25 | Suitability index below which a crop is not introduced |
| `family_min_return_years` | 2 (cereals 1) | Same-family repeat rule for main crops |
| `yield_loss.*`, `stress_weights.*` | | How strongly each hazard reduces the income and resilience scores |

An unknown key in this file stops the backend at start-up with a message naming it, so a typo cannot silently fall back to a default.
