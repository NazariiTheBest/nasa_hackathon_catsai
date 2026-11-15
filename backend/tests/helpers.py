"""Synthetic climate and NASA POWER-shaped payloads for tests."""

from __future__ import annotations

import httpx
import numpy as np
import pandas as pd

from fieldshift.climate.power import COLUMNS, PARAMETERS


def make_climate(start_year: int = 1985, n_years: int = 40, seed: int = 0, t_mean: float = 9.0,
                 t_amp: float = 13.0, wet_prob: float = 0.3, rain_per_wet_day: float = 5.5) -> pd.DataFrame:
    """A daily climate frame with a temperate seasonal cycle, shaped like the POWER series."""
    dates = pd.date_range(f"{start_year}-01-01", f"{start_year + n_years - 1}-12-31", freq="D")
    doy = dates.day_of_year.to_numpy()
    n = dates.size
    rng = np.random.default_rng(seed)
    season = np.sin((doy - 105) / 365 * 2 * np.pi)  # peaks in mid-July
    t2m = t_mean + t_amp * season + rng.normal(0, 2.5, n)
    tmax = t2m + 5.5 + np.abs(rng.normal(0, 1.0, n))
    tmin = t2m - 5.5 - np.abs(rng.normal(0, 1.0, n))
    wet = rng.random(n) < wet_prob
    precip = np.where(wet, rng.gamma(0.9, rain_per_wet_day / 0.9, n), 0.0)
    srad = np.clip(11 + 9.5 * np.sin((doy - 80) / 365 * 2 * np.pi) + rng.normal(0, 1.5, n), 1.5, None)
    frame = pd.DataFrame(
        {
            "t2m": t2m, "tmax": tmax, "tmin": tmin, "tdew": tmin - 1.0,
            "rh": np.clip(70 - 15 * season + rng.normal(0, 5, n), 20, 100),
            "ws2m": np.clip(3.0 + rng.normal(0, 0.6, n), 0.3, None),
            "precip": precip, "srad": srad,
            "gwettop": np.clip(0.5 - 0.15 * season + rng.normal(0, 0.03, n), 0.05, 0.95),
            "gwetroot": np.clip(0.55 - 0.12 * season + rng.normal(0, 0.02, n), 0.05, 0.95),
        },
        index=dates,
    )
    frame.index.name = "date"
    return frame[COLUMNS].round(2)


def power_payload(frame: pd.DataFrame, lat: float, lon: float, elevation: float = 120.0) -> dict:
    keys = frame.index.strftime("%Y%m%d")
    column_to_param = {v: k for k, v in PARAMETERS.items()}
    parameter = {
        column_to_param[column]: dict(zip(keys, frame[column].fillna(-999.0).tolist()))
        for column in frame.columns
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat, elevation]},
        "header": {"title": "NASA/POWER Source Native Resolution Daily Data", "fill_value": -999.0},
        "parameters": {"ALLSKY_SFC_SW_DWN": {"units": "MJ/m^2/day"}},
        "properties": {"parameter": parameter},
    }


def make_context(frame: pd.DataFrame, kb, cfg, static: dict | None = None, tier: str = "climate_only",
                 lat: float = 49.0, lon: float = 32.0, timeseries=None, suitability=None, sources=None):
    """A SiteContext built from a climate frame, without bundles or a network."""
    import datetime as dt

    from fieldshift.climate.power import ClimateSeries, Provenance
    from fieldshift.diagnostics.et0 import prepare_climate
    from fieldshift.diagnostics.soil import resolve_soil
    from fieldshift.engine.evaluate import SiteContext

    provenance = Provenance(
        cell_lat=lat, cell_lon=lon, elevation_m=150.0,
        period_start=frame.index[0].date(), period_end=frame.index[-1].date(),
        retrieved_at=dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc),
    )
    soil = resolve_soil(static, cfg)
    climate = prepare_climate(ClimateSeries(frame, provenance), lat, soil.elevation_m)
    return SiteContext(lat=lat, lon=lon, tier=tier, unit=None, soil=soil, climate=climate, kb=kb, cfg=cfg,
                       timeseries=timeseries, suitability=suitability, sources=sources or {})


def kb_variant(crop_id: str, mutate):
    """The shipped knowledge base with one crop record edited."""
    import copy

    import yaml

    from fieldshift.kb.loader import parse_kb
    from fieldshift.settings import kb_path

    with open(kb_path(), encoding="utf-8") as fh:
        records = copy.deepcopy(yaml.safe_load(fh))
    mutate(next(r for r in records if r["id"] == crop_id))
    return parse_kb(records)


def ndvi_frame(curve, years=range(2001, 2026)) -> pd.DataFrame:
    """A 16-day vegetation-index series; `curve` maps day of year to a value."""
    rows = []
    for year in years:
        for doy in range(1, 366, 16):
            rows.append({"date": pd.Timestamp(year, 1, 1) + pd.Timedelta(days=doy - 1), "variable": "ndvi",
                         "value": float(curve(doy)), "std": 0.05, "valid_frac": 1.0, "source": "MOD13Q1.061", "res_m": 250})
    return pd.DataFrame(rows)


class FakePower:
    """An httpx transport that answers like NASA POWER and counts requests."""

    def __init__(self, fail_cells: set[tuple[float, float]] | None = None, down: bool = False):
        self.calls: list[dict] = []
        self.fail_cells = fail_cells or set()
        self.down = down

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        if self.down:
            raise httpx.ConnectError("simulated outage", request=request)
        lat, lon = float(params["latitude"]), float(params["longitude"])
        if (lat, lon) in self.fail_cells:
            return httpx.Response(503, text="Service Unavailable")
        start, end = int(params["start"][:4]), int(params["end"][:4])
        frame = make_climate(start, end - start + 1, seed=int(abs(lat * 10) + abs(lon * 10)))
        return httpx.Response(200, json=power_payload(frame, lat, lon))

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
