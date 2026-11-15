# Field Shift data contract (version 1.0)

For the geospatial scientists. This is everything needed to deliver data the backend can ingest without anyone editing code.

**The short version:** export per-unit statistics from Earth Engine, convert them with one command, run the validator, hand over the folder.

## 1. What a bundle is

A bundle is one folder of pre-processed features for a set of *units*. A unit is either a showcase **field** or a national **grid cell** (about 10 km, cropland-masked). Both kinds use the same files and the same rules.

```
data/bundles/<bundle_id>/
  manifest.json        required  who made it, from which products
  units.geojson        required  one polygon per unit
  timeseries.parquet   required  one row per unit, date and variable
  static.parquet       required  one row per unit: soil and terrain
  crop_history.csv     optional  what grew where, by year
  suitability.csv      optional  crop suitability per unit (GAEZ)
```

Deliver the grid and the fields as two separate bundles. JSON Schemas for every file are in [`contracts/bundle/`](../contracts/bundle). A complete synthetic example is in [`data/sample/`](../data/sample).

## 2. Files

### manifest.json

```json
{
  "contract_version": "1.0",
  "bundle_id": "ua-grid",
  "unit_type": "grid_cell",
  "created_at": "2026-11-14T09:00:00Z",
  "author": "your name",
  "sources": [
    {"variable": "ndvi", "product": "MOD13Q1", "version": "061", "native_res_m": 250,
     "date_start": "2001-01-01", "date_end": "2025-12-31"},
    {"variable": "soil", "product": "SoilGrids", "version": "2.0", "native_res_m": 250},
    {"variable": "terrain", "product": "SRTMGL1", "version": "003", "native_res_m": 30}
  ],
  "notes": "QA: SummaryQA <= 1; cropland mask: WorldCover class 40, >= 50% of the MODIS pixel"
}
```

`unit_type` is `grid_cell` or `field`. List one `sources` entry per variable you deliver, plus `soil`, `terrain` and `suitability` when present. These entries are what the tool cites as evidence to the farmer, so product and version must be exact.

### units.geojson

A GeoJSON FeatureCollection of polygons in **WGS84, longitude first, then latitude**.

| Property | Type | Rule |
|---|---|---|
| `unit_id` | string | Unique within the bundle. Use strings even if they look like numbers |
| `unit_type` | string | `field` or `grid_cell`, same as the manifest |
| `name` | string, optional | Shown on the map for fields |
| `area_ha` | number, optional | |
| `cropland_frac` | number 0-1, optional | Grid cells: share of the cell that is cropland |

### timeseries.parquet

Long format: one row per unit, date and variable. Adding a new variable never changes the columns.

| Column | Type | Rule |
|---|---|---|
| `unit_id` | string | Must exist in `units.geojson` |
| `date` | date | Start of the composite period |
| `variable` | string | One of the names in the vocabulary below |
| `value` | float | Unit mean after QA masking, **scale factor applied**; null when there is no valid data |
| `std` | float or null | Spread of pixel values inside the unit |
| `valid_frac` | float 0-1 | Share of the unit's pixels that passed masking |
| `source` | string | Product and version, for example `MOD13Q1.061` |
| `res_m` | integer | Native resolution in meters |

Vocabulary and units:

| `variable` | Unit | Valid range | Expected source |
|---|---|---|---|
| `ndvi`, `evi` | unitless | -1 to 1 | MODIS MOD13Q1 |
| `et` | mm/day | 0 to 20 | MODIS MOD16A2GF |
| `sm_surface`, `sm_rootzone` | m3/m3 | 0 to 1 | SMAP L4 |
| `precip` | mm/day | 0 to 500 | GPM IMERG |
| `t2m_mean` | deg C | -60 to 60 | ERA5-Land (optional) |
| `lst_day` | deg C | -60 to 80 | optional |

Need a variable that is not listed? Ask for it to be added to the vocabulary; it is a one-line change.

### static.parquet

Exactly one row per unit.

| Column | Unit | Required |
|---|---|---|
| `unit_id` | | yes |
| `clay_pct`, `sand_pct` | % by weight, topsoil (0-30 cm) | yes |
| `soc_pct` | % soil organic carbon | yes |
| `ph` | pH in water | yes |
| `slope_pct` | % | yes |
| `elevation_m` | m | yes |
| `awc_mm_per_m` | mm of plant-available water per m of soil | no |
| `k_factor` | t ha h / (ha MJ mm) | no |
| `drainage_class` | text | no |

If `awc_mm_per_m` or `k_factor` is missing, the backend derives it from texture and organic carbon and tells the farmer it is derived. SoilGrids stores some properties as scaled integers (for example clay in g/kg, organic carbon in dg/kg): convert to percent before delivery.

### crop_history.csv (optional)

`unit_id, year, crop_id, cover_frac, method, confidence`

`method` is `declared`, `worldcereal` or `ndvi_phenology`. `cover_frac` and `confidence` are 0-1. Class-level identifiers such as `winter_cereal` are fine.

### suitability.csv (optional)

`unit_id, crop_id, suitability_index, scenario, water_supply, source`

`suitability_index` is 0-100. `water_supply` is `rainfed` or `irrigated`. `crop_id` should match the knowledge base identifiers in [`kb/crops.yaml`](../kb/crops.yaml) so the engine can screen crops with it.

## 3. The five mistakes the validator catches most

1. **Scale factor not applied.** MODIS NDVI of `4200` must be delivered as `0.42`.
2. **Fill values left in.** `-9999`, `-3000`, `32767` must be null.
3. **Projected coordinates or latitude first.** Geometry must be WGS84 longitude, latitude.
4. **Unit identifiers that do not match** between the tables and `units.geojson`.
5. **Kelvin.** Temperatures are in degrees Celsius.

## 4. Earth Engine sources

Asset identifiers were written from memory. Confirm each one, and especially the version suffix, in the Earth Engine catalog before a long export.

| Layer | Earth Engine asset | Contract target |
|---|---|---|
| NDVI, EVI | `MODIS/061/MOD13Q1` | `ndvi`, `evi` (scale 0.0001) |
| Evapotranspiration | `MODIS/061/MOD16A2GF` | `et` (band `ET` is kg/m2 per 8 days, scale 0.1; divide by 8 for mm/day) |
| Soil moisture | `NASA/SMAP/SPL4SMGP/007` | `sm_surface`, `sm_rootzone` (already m3/m3) |
| Precipitation | `NASA/GPM_L3/IMERG_MONTHLY_V07` | `precip` (mm/hr; multiply by 24 for mm/day) |
| Monthly weather | `ECMWF/ERA5_LAND/MONTHLY_AGGR` | `t2m_mean` (Kelvin; subtract 273.15) |
| Elevation, slope | `USGS/SRTMGL1_003` | `elevation_m`, `slope_pct` |
| Soil | `projects/soilgrids-isric/clay_mean`, `sand_mean`, `soc_mean`, `phh2o_mean` | `clay_pct`, `sand_pct`, `soc_pct`, `ph` |
| Cropland mask | `ESA/WorldCover/v200` | mask only |
| Crop class | `ESA/WorldCereal/2021/MODELS/v100` | `crop_history.csv` |
| Suitability | FAO GAEZ v4 (download from the FAO portal, upload as an asset) | `suitability.csv` |

CHIRPS is not used because it stops at 50 degrees north, which excludes Kyiv and northern Ukraine.

### Cropland mask recipe (grid cells)

A starting point for the Earth Engine code editor; adjust to your scripts.

```js
// 10 m cropland (WorldCover class 40) aggregated to the MODIS 250 m grid.
var modisProj = ee.ImageCollection('MODIS/061/MOD13Q1').first().select('NDVI').projection();
var cropFrac = ee.ImageCollection('ESA/WorldCover/v200').first().eq(40)
  .reduceResolution({reducer: ee.Reducer.mean(), maxPixels: 1024})
  .reproject({crs: modisProj});
var cropMask = cropFrac.gte(0.5);

// One row per grid cell and image. `grid` is a FeatureCollection with a `unit_id` property.
var year = 2001;
var modis = ee.ImageCollection('MODIS/061/MOD13Q1').filterDate(year + '-01-01', (year + 1) + '-01-01');
var rows = modis.map(function (img) {
  var good = img.select('SummaryQA').lte(1);
  var masked = img.select(['NDVI', 'EVI']).updateMask(good).updateMask(cropMask);
  return masked.reduceRegions({collection: grid, reducer: ee.Reducer.mean(), scale: 250, tileScale: 4})
    .map(function (f) { return f.set('date', img.date().format('YYYY-MM-dd')).setGeometry(null); });
}).flatten();

Export.table.toDrive({
  collection: rows, description: 'ua_grid_mod13q1_' + year, fileFormat: 'CSV',
  selectors: ['unit_id', 'date', 'NDVI', 'EVI']
});
```

Export one year per task: thousands of cells times a year of images finishes far sooner than one 25-year task, and a failed year can be re-run alone. Concatenate the yearly CSV files before converting.

## 5. Convert, validate, hand over

All commands run from the `backend/` folder.

**Convert** an Earth Engine export (one row per unit and date, one column per band) into `timeseries.parquet`. The mapping file says which band is which variable:

```yaml
# docs/examples/modis_mapping.yaml
unit_id_column: unit_id
date_column: date
bands:
  NDVI: {variable: ndvi, scale: 0.0001, source: MOD13Q1.061, res_m: 250}
  EVI:  {variable: evi,  scale: 0.0001, source: MOD13Q1.061, res_m: 250}
ignore_columns: ["system:index", ".geo"]
```

```bash
uv run fieldshift convert-gee ../docs/examples/gee_export_example.csv ../docs/examples/modis_mapping.yaml ../data/cache/example_timeseries.parquet
```

A band column that the mapping does not mention stops the conversion with a message naming it, so nothing is silently dropped. Optional keys per band: `offset`, `std_column`. Optional top-level key: `valid_frac_column`. Without it, `valid_frac` is 1 where a value exists and 0 where it is null. Convert each product separately and concatenate the outputs, or put all bands in one table.

**Validate** a bundle. Every problem is listed with the file, the rows and the reason; the exit status is non-zero when anything is wrong.

```bash
uv run fieldshift validate-bundle ../data/sample/ua-sample-grid
```

```bash
uv run fieldshift validate-bundle ../data/sample/ua-sample-fields
```

**Hand over** the validated folder by placing it in `data/bundles/`. That folder is ignored by git; share large bundles through the team drive. The backend loads every bundle it finds there at start-up and falls back to the synthetic sample when the folder is empty.

**Regenerate the synthetic sample** (only needed if the generator changes):

```bash
uv run fieldshift make-sample
```
