"""Synthetic sample bundles for development and tests.

The data is invented. It has the shape and seasonal behavior of the real
exports so that the backend, the UI and the tests run before real data lands.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fieldshift.contracts.bundle import CONTRACT_VERSION

GRID_ID = "ua-sample-grid"
FIELDS_ID = "ua-sample-fields"
CREATED_AT = "2026-11-14T00:00:00Z"
NOTE = "SYNTHETIC data for development and tests. Not real observations."

# South-west corner and size of the sample grid (Cherkasy oblast, central Ukraine).
LON0, LAT0, CELL = 32.0, 49.0, 0.1
COLS, ROWS = 5, 4
YEARS = range(2001, 2026)

# (name, lon, lat, width_deg, height_deg) of the showcase fields' south-west corners.
FIELDS = [
    ("f_demo_01", "Demo field 1", 32.130, 49.140, 0.012, 0.008),
    ("f_demo_02", "Demo field 2", 32.245, 49.165, 0.014, 0.007),
    ("f_demo_03", "Demo field 3", 32.260, 49.230, 0.010, 0.009),
]

SUITABILITY = {
    "winter_wheat": 82, "winter_barley": 78, "spring_barley": 70, "maize": 66, "sunflower": 74,
    "soybean": 61, "winter_rapeseed": 64, "sugar_beet": 18, "sorghum": 52, "millet": 58,
    "chickpea": 49, "buckwheat": 55, "peas": 67, "alfalfa": 63, "sainfoin": 60,
}


def _rect(lon: float, lat: float, w: float, h: float) -> list[list[list[float]]]:
    return [[[lon, lat], [lon + w, lat], [lon + w, lat + h], [lon, lat + h], [lon, lat]]]


def _winter_curve(doy: np.ndarray) -> np.ndarray:
    spring = 0.55 * np.exp(-0.5 * ((doy - 150) / 28.0) ** 2)
    autumn = 0.12 * np.exp(-0.5 * ((doy - 300) / 18.0) ** 2)
    return 0.20 + spring + autumn


def _summer_curve(doy: np.ndarray) -> np.ndarray:
    return 0.17 + 0.62 * np.exp(-0.5 * ((doy - 205) / 30.0) ** 2)


def _timeseries(unit_ids: list[str], winter_share: dict[str, float], rng: np.random.Generator, by_parity: bool) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    composite_doys = np.arange(1, 366, 16)
    year_effect = {year: rng.normal(0, 0.04) for year in YEARS}
    for unit_id in unit_ids:
        # Vegetation indices and evapotranspiration, 16-day composites.
        dates, ndvi = [], []
        for year in YEARS:
            share = winter_share[unit_id]
            if by_parity:  # a single field alternates winter and summer crops
                share = 1.0 if year % 2 == 0 else 0.0
            curve = share * _winter_curve(composite_doys) + (1 - share) * _summer_curve(composite_doys)
            peak_scale = 1 + year_effect[year]
            values = 0.18 + (curve - 0.18) * peak_scale + rng.normal(0, 0.015, composite_doys.size)
            ndvi.append(np.clip(values, 0.05, 0.92))
            dates += [dt.date(year, 1, 1) + dt.timedelta(days=int(d) - 1) for d in composite_doys]
        ndvi_all = np.concatenate(ndvi)
        doy_all = np.tile(composite_doys, len(YEARS))
        missing = rng.random(ndvi_all.size) < 0.01
        valid = np.where(missing, 0.0, np.round(rng.uniform(0.6, 1.0, ndvi_all.size), 2))
        std = np.where(missing, np.nan, np.round(rng.uniform(0.03, 0.08, ndvi_all.size), 3))
        ndvi_out = np.where(missing, np.nan, np.round(ndvi_all, 4))
        evi_out = np.where(missing, np.nan, np.round(ndvi_all * 0.62, 4))
        for variable, values in (("ndvi", ndvi_out), ("evi", evi_out)):
            rows.append(pd.DataFrame({
                "unit_id": unit_id, "date": dates, "variable": variable, "value": values,
                "std": std, "valid_frac": valid, "source": "MOD13Q1.061", "res_m": 250,
            }))
        et = 0.3 + 3.9 * np.clip(np.sin((doy_all - 80) / 365 * 2 * np.pi), 0, None) * (ndvi_all / 0.8)
        rows.append(pd.DataFrame({
            "unit_id": unit_id, "date": dates, "variable": "et", "value": np.round(et, 3),
            "std": np.nan, "valid_frac": 1.0, "source": "MOD16A2GF.061", "res_m": 500,
        }))

        # Precipitation (2001+) and soil moisture (SMAP era, 2015+), monthly means.
        months = pd.date_range("2001-01-01", "2025-12-01", freq="MS")
        precip = np.clip(1.6 + 0.7 * np.sin((months.month - 4) / 12 * 2 * np.pi) + rng.normal(0, 0.5, months.size), 0, None)
        rows.append(pd.DataFrame({
            "unit_id": unit_id, "date": months.date, "variable": "precip", "value": np.round(precip, 3),
            "std": np.nan, "valid_frac": 1.0, "source": "IMERG.V07", "res_m": 11000,
        }))
        smap = months[months.year >= 2015]
        seasonal = 0.07 * np.cos((smap.month - 2) / 12 * 2 * np.pi)
        for variable, base in (("sm_surface", 0.24), ("sm_rootzone", 0.27)):
            values = np.clip(base + seasonal + rng.normal(0, 0.015, smap.size), 0.05, 0.5)
            rows.append(pd.DataFrame({
                "unit_id": unit_id, "date": smap.date, "variable": variable, "value": np.round(values, 4),
                "std": np.nan, "valid_frac": 1.0, "source": "SPL4SMGP.007", "res_m": 9000,
            }))
    out = pd.concat(rows, ignore_index=True)
    out["res_m"] = out["res_m"].astype("int32")
    out["std"] = out["std"].astype("float64")
    return out


def _static(unit_ids: list[str], rng: np.random.Generator, supplied: set[str]) -> pd.DataFrame:
    n = len(unit_ids)
    clay = rng.uniform(24, 36, n)
    sand = rng.uniform(18, 34, n)
    frame = pd.DataFrame({
        "unit_id": unit_ids,
        "clay_pct": np.round(clay, 1),
        "sand_pct": np.round(sand, 1),
        "soc_pct": np.round(rng.uniform(1.6, 2.6, n), 2),
        "ph": np.round(rng.uniform(6.4, 7.3, n), 1),
        "slope_pct": np.round(rng.uniform(0.8, 4.5, n), 1),
        "elevation_m": np.round(rng.uniform(95, 210, n), 0),
        "awc_mm_per_m": [165.0 if u in supplied else np.nan for u in unit_ids],
        "k_factor": [0.032 if u in supplied else np.nan for u in unit_ids],
        "drainage_class": ["well drained" if u in supplied else None for u in unit_ids],
    })
    return frame


def _suitability(unit_ids: list[str], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for unit_id in unit_ids:
        for crop_id, base in SUITABILITY.items():
            rows.append({
                "unit_id": unit_id, "crop_id": crop_id,
                "suitability_index": int(np.clip(base + rng.integers(-4, 5), 0, 100)),
                "scenario": "historical_1981_2010", "water_supply": "rainfed",
                "source": "GAEZ v4 (synthetic sample)",
            })
    return pd.DataFrame(rows)


def _manifest(bundle_id: str, unit_type: str) -> dict:
    def src(variable, product, version, res, start="2001-01-01", end="2025-12-31"):
        return {"variable": variable, "product": product, "version": version, "native_res_m": res,
                "date_start": start, "date_end": end}

    return {
        "contract_version": CONTRACT_VERSION,
        "bundle_id": bundle_id,
        "unit_type": unit_type,
        "created_at": CREATED_AT,
        "author": "fieldshift sample generator",
        "sources": [
            src("ndvi", "MOD13Q1", "061", 250),
            src("evi", "MOD13Q1", "061", 250),
            src("et", "MOD16A2GF", "061", 500),
            src("precip", "GPM IMERG monthly", "V07", 11000),
            src("sm_surface", "SMAP SPL4SMGP", "007", 9000, "2015-04-01"),
            src("sm_rootzone", "SMAP SPL4SMGP", "007", 9000, "2015-04-01"),
            src("soil", "SoilGrids", "2.0", 250, None, None),
            src("terrain", "SRTMGL1", "003", 30, None, None),
            src("suitability", "FAO GAEZ", "v4", 9000, None, None),
        ],
        "notes": NOTE,
    }


def _write(bundle_dir: Path, manifest: dict, features: list[dict], ts: pd.DataFrame, static: pd.DataFrame,
           suitability: pd.DataFrame, crop_history: pd.DataFrame | None) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    collection = {"type": "FeatureCollection", "features": features}
    (bundle_dir / "units.geojson").write_text(json.dumps(collection) + "\n", encoding="utf-8")
    ts.to_parquet(bundle_dir / "timeseries.parquet", index=False)
    static.to_parquet(bundle_dir / "static.parquet", index=False)
    suitability.to_csv(bundle_dir / "suitability.csv", index=False, lineterminator="\n")
    if crop_history is not None:
        crop_history.to_csv(bundle_dir / "crop_history.csv", index=False, lineterminator="\n")


def generate_sample(out_dir: str | Path, seed: int = 42) -> list[Path]:
    """Write the sample grid and field bundles under out_dir; return their paths."""
    out_dir = Path(out_dir)
    rng = np.random.default_rng(seed)

    # --- Grid bundle ---
    grid_ids, grid_features, grid_share = [], [], {}
    for row in range(ROWS):
        for col in range(COLS):
            unit_id = f"g_{row * COLS + col:04d}"
            lon, lat = LON0 + col * CELL, LAT0 + row * CELL
            grid_ids.append(unit_id)
            grid_share[unit_id] = float(rng.uniform(0.45, 0.6))
            grid_features.append({
                "type": "Feature",
                "properties": {"unit_id": unit_id, "unit_type": "grid_cell", "name": None,
                               "area_ha": 8100.0, "cropland_frac": round(float(rng.uniform(0.5, 0.85)), 2)},
                "geometry": {"type": "Polygon", "coordinates": _rect(round(lon, 4), round(lat, 4), CELL, CELL)},
            })
    _write(
        out_dir / GRID_ID,
        _manifest(GRID_ID, "grid_cell"),
        grid_features,
        _timeseries(grid_ids, grid_share, rng, by_parity=False),
        _static(grid_ids, rng, supplied=set()),
        _suitability(grid_ids, rng),
        None,
    )

    # --- Field bundle ---
    field_ids = [f[0] for f in FIELDS]
    field_features = [{
        "type": "Feature",
        "properties": {"unit_id": uid, "unit_type": "field", "name": name,
                       "area_ha": round(w * 73.0 * h * 111.0 * 100, 1), "cropland_frac": None},
        "geometry": {"type": "Polygon", "coordinates": _rect(lon, lat, w, h)},
    } for uid, name, lon, lat, w, h in FIELDS]
    history = pd.DataFrame([
        {"unit_id": uid, "year": year,
         "crop_id": "winter_wheat" if year % 2 == 0 else "sunflower",
         "cover_frac": 1.0, "method": "declared", "confidence": 1.0}
        for uid in field_ids for year in range(2021, 2026)
    ])
    _write(
        out_dir / FIELDS_ID,
        _manifest(FIELDS_ID, "field"),
        field_features,
        _timeseries(field_ids, {u: 0.5 for u in field_ids}, rng, by_parity=True),
        _static(field_ids, rng, supplied={"f_demo_01"}),
        _suitability(field_ids, rng),
        history,
    )
    return [out_dir / GRID_ID, out_dir / FIELDS_ID]
