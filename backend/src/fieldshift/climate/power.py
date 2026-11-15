"""NASA POWER daily point client with a persistent per-cell cache.

POWER's meteorology comes from MERRA-2 on a 0.5 x 0.625 degree grid. Requests
are snapped to that grid so that nearby points share one cached series and the
cache can be completed for a whole country in advance.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import httpx
import numpy as np
import pandas as pd
from pydantic import BaseModel

from fieldshift.settings import cache_dir as default_cache_dir

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
START_YEAR = 1985
LAT_STEP, LON_STEP = 0.5, 0.625

# POWER parameter -> column name used throughout the backend.
PARAMETERS = {
    "T2M": "t2m",                    # mean air temperature at 2 m, deg C
    "T2M_MAX": "tmax",               # deg C
    "T2M_MIN": "tmin",               # deg C
    "T2MDEW": "tdew",                # dew point, deg C
    "RH2M": "rh",                    # relative humidity, %
    "WS2M": "ws2m",                  # wind speed at 2 m, m/s
    "PRECTOTCORR": "precip",         # mm/day
    "ALLSKY_SFC_SW_DWN": "srad",     # incoming solar radiation, MJ/m2/day
    "GWETTOP": "gwettop",            # surface soil wetness, 0-1
    "GWETROOT": "gwetroot",          # root-zone soil wetness, 0-1
}
COLUMNS = list(PARAMETERS.values())


class ClimateUnavailable(Exception):
    """NASA POWER could not be reached and the cell is not in the cache."""


class Provenance(BaseModel):
    source: str = "NASA POWER daily (MERRA-2 meteorology, CERES radiation)"
    spatial_resolution: str = "0.5 x 0.625 degree (about 50 km)"
    cell_lat: float
    cell_lon: float
    elevation_m: float | None = None
    period_start: dt.date
    period_end: dt.date
    retrieved_at: dt.datetime

    @property
    def period_label(self) -> str:
        return f"{self.period_start.year}-{self.period_end.year}"


@dataclass
class ClimateSeries:
    data: pd.DataFrame  # indexed by date, columns as in COLUMNS
    provenance: Provenance


@dataclass
class PrewarmSummary:
    cells: int = 0
    fetched: list[tuple[float, float]] = field(default_factory=list)
    skipped: list[tuple[float, float]] = field(default_factory=list)
    failed: list[tuple[tuple[float, float], str]] = field(default_factory=list)


def snap(lat: float, lon: float) -> tuple[float, float]:
    """Centre of the POWER meteorological grid cell that contains the point."""
    return (round(round(lat / LAT_STEP) * LAT_STEP, 3), round(round(lon / LON_STEP) * LON_STEP, 4))


def last_complete_year(today: dt.date | None = None) -> int:
    return (today or dt.date.today()).year - 1


def parse_payload(payload: dict) -> tuple[pd.DataFrame, float | None]:
    """Turn a POWER JSON response into a daily frame; fill values become missing."""
    params = payload["properties"]["parameter"]
    fill = float(payload.get("header", {}).get("fill_value", -999.0))
    frame = pd.DataFrame({PARAMETERS[name]: pd.Series(values, dtype="float64")
                          for name, values in params.items() if name in PARAMETERS})
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise KeyError(f"POWER response lacks parameter(s): {', '.join(missing)}")
    frame.index = pd.to_datetime(frame.index, format="%Y%m%d")
    frame.index.name = "date"
    frame = frame.sort_index()[COLUMNS]
    frame = frame.mask(np.isclose(frame, fill) | (frame <= -900))

    units = payload.get("parameters", {}).get("ALLSKY_SFC_SW_DWN", {}).get("units", "")
    if "kW" in units:  # kWh/m2/day -> MJ/m2/day
        frame["srad"] = frame["srad"] * 3.6
    coords = payload.get("geometry", {}).get("coordinates", [])
    elevation = float(coords[2]) if len(coords) > 2 else None
    return frame, elevation


class PowerClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 120.0,
        today: dt.date | None = None,
        retries: int = 2,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self._transport = transport
        self._timeout = timeout_s
        self._today = today
        self._retries = retries

    # --- Cache ---

    def _paths(self, cell: tuple[float, float]) -> tuple[Path, Path]:
        stem = f"power_{cell[0]:+08.3f}_{cell[1]:+09.4f}"
        return self.cache_dir / f"{stem}.parquet", self.cache_dir / f"{stem}.json"

    def is_cached(self, lat: float, lon: float) -> bool:
        data_path, meta_path = self._paths(snap(lat, lon))
        return data_path.exists() and meta_path.exists()

    def cached_cells(self) -> int:
        return len(list(self.cache_dir.glob("power_*.parquet"))) if self.cache_dir.is_dir() else 0

    def _load(self, cell: tuple[float, float]) -> ClimateSeries:
        data_path, meta_path = self._paths(cell)
        frame = pd.read_parquet(data_path)
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.set_index("date").astype("float64")
        provenance = Provenance.model_validate_json(meta_path.read_text(encoding="utf-8"))
        return ClimateSeries(frame, provenance)

    def _store(self, cell: tuple[float, float], frame: pd.DataFrame, provenance: Provenance) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data_path, meta_path = self._paths(cell)
        frame.astype("float32").reset_index().to_parquet(data_path, index=False)
        meta_path.write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")

    # --- Retrieval ---

    def _fetch(self, cell: tuple[float, float]) -> dict:
        end_year = last_complete_year(self._today)
        params = {
            "parameters": ",".join(PARAMETERS),
            "community": "AG",
            "latitude": cell[0],
            "longitude": cell[1],
            "start": f"{START_YEAR}0101",
            "end": f"{end_year}1231",
            "format": "JSON",
        }
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                    response = client.get(POWER_URL, params=params)
                    response.raise_for_status()
                    return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self._retries:
                    time.sleep(0.5 * (attempt + 1) if self._transport is None else 0)
        raise ClimateUnavailable(f"NASA POWER request failed for cell {cell}: {last_error}")

    def get_series(self, lat: float, lon: float) -> ClimateSeries:
        """Daily series for the POWER cell containing the point. Uses the cache when present."""
        cell = snap(lat, lon)
        if self.is_cached(lat, lon):
            return self._load(cell)
        payload = self._fetch(cell)
        try:
            frame, elevation = parse_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise ClimateUnavailable(f"NASA POWER response for cell {cell} could not be read: {exc}") from exc
        if frame.empty:
            raise ClimateUnavailable(f"NASA POWER returned no data for cell {cell}")
        provenance = Provenance(
            cell_lat=cell[0], cell_lon=cell[1], elevation_m=elevation,
            period_start=frame.index[0].date(), period_end=frame.index[-1].date(),
            retrieved_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0),
        )
        self._store(cell, frame, provenance)
        return self._load(cell)

    # --- Pre-warming ---

    def prewarm(
        self,
        points: Iterable[tuple[float, float]],
        pause_s: float = 1.0,
        progress: Callable[[str], None] | None = None,
    ) -> PrewarmSummary:
        """Fetch every distinct cell among the points; skip cached cells, continue past failures."""
        cells = sorted({snap(lat, lon) for lat, lon in points})
        summary = PrewarmSummary(cells=len(cells))
        for i, cell in enumerate(cells, start=1):
            if self.is_cached(*cell):
                summary.skipped.append(cell)
                continue
            try:
                self.get_series(*cell)
                summary.fetched.append(cell)
                status = "fetched"
            except ClimateUnavailable as exc:
                summary.failed.append((cell, str(exc)))
                status = "FAILED"
            if progress:
                progress(f"[{i}/{len(cells)}] {cell} {status}")
            if pause_s and i < len(cells):
                time.sleep(pause_s)
        return summary


def points_from_bundle(bundle_dir: Path) -> list[tuple[float, float]]:
    """(lat, lon) centroid of every unit in a bundle."""
    from shapely.geometry import shape

    collection = json.loads((Path(bundle_dir) / "units.geojson").read_text(encoding="utf-8"))
    points = []
    for feature in collection["features"]:
        centroid = shape(feature["geometry"]).centroid
        points.append((centroid.y, centroid.x))
    return points


def points_from_csv(path: Path) -> list[tuple[float, float]]:
    frame = pd.read_csv(path)
    return list(zip(frame["lat"].astype(float), frame["lon"].astype(float)))


def year_matrix(frame: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[int]]:
    """Reshape a daily series into arrays of shape (years, 365).

    29 February is dropped and incomplete years are skipped, so that every year
    has the same length and historical replay can be vectorized.
    """
    index = frame.index
    keep = ~((index.month == 2) & (index.day == 29))
    frame = frame[keep]
    counts = frame.groupby(frame.index.year).size()
    years = [int(y) for y, n in counts.items() if n == 365]
    frame = frame[frame.index.year.isin(years)]
    out = {column: frame[column].to_numpy(dtype="float64").reshape(len(years), 365) for column in frame.columns}
    return out, years
