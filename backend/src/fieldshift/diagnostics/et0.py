"""Reference evapotranspiration (FAO-56) and preparation of the climate series."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fieldshift.climate.power import ClimateSeries, Provenance, year_matrix


def saturation_vapour_pressure(t_c):
    """e0(T) in kPa (FAO-56 eq. 11)."""
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def extraterrestrial_radiation(lat_deg: float, doy):
    """Ra in MJ/m2/day (FAO-56 eq. 21)."""
    doy = np.asarray(doy, dtype="float64")
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    return (24 * 60 / np.pi) * 0.0820 * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def et0_penman_monteith(tmax, tmin, ea, u2, rs, lat_deg: float, elevation_m: float, doy):
    """Daily reference evapotranspiration in mm/day (FAO-56 eq. 6).

    tmax, tmin in deg C; ea (actual vapour pressure) in kPa; u2 (wind at 2 m) in
    m/s; rs (incoming solar radiation) in MJ/m2/day.
    """
    tmax, tmin, ea, u2, rs = (np.asarray(a, dtype="float64") for a in (tmax, tmin, ea, u2, rs))
    tmean = (tmax + tmin) / 2
    pressure = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26
    gamma = 0.000665 * pressure
    es = (saturation_vapour_pressure(tmax) + saturation_vapour_pressure(tmin)) / 2
    delta = 4098 * saturation_vapour_pressure(tmean) / (tmean + 237.3) ** 2
    ra = extraterrestrial_radiation(lat_deg, doy)
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = 0.77 * rs
    rel = np.clip(np.divide(rs, rso, out=np.ones_like(rs), where=rso > 0), 0.3, 1.0)
    sigma = 4.903e-9
    rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(np.clip(ea, 0, None))) * (1.35 * rel - 0.35)
    rn = rns - rnl
    numerator = 0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)
    return np.clip(numerator / (delta + gamma * (1 + 0.34 * u2)), 0, None)


def et0_hargreaves(tmax, tmin, lat_deg: float, doy):
    """Temperature-based estimate in mm/day (FAO-56 eq. 52), used when radiation is missing."""
    tmax, tmin = np.asarray(tmax, dtype="float64"), np.asarray(tmin, dtype="float64")
    tmean = (tmax + tmin) / 2
    ra = extraterrestrial_radiation(lat_deg, doy)
    return np.clip(0.0023 * (tmean + 17.8) * np.sqrt(np.clip(tmax - tmin, 0, None)) * 0.408 * ra, 0, None)


@dataclass
class PreparedClimate:
    matrix: dict[str, np.ndarray]  # each of shape (years, 365)
    years: list[int]
    provenance: Provenance
    et0_fallback_days: int
    filled_days: int

    @property
    def n_years(self) -> int:
        return len(self.years)

    @property
    def period(self) -> str:
        return f"{self.years[0]}-{self.years[-1]}" if self.years else ""


def _fill_from_day_of_year(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Replace missing values with the mean of the same calendar day across years."""
    missing_days = int(frame.isna().any(axis=1).sum())
    if missing_days == 0:
        return frame, 0
    doy = frame.index.day_of_year
    climatology = frame.groupby(doy).transform("mean")
    frame = frame.fillna(climatology).ffill().bfill()
    return frame, missing_days


def prepare_climate(series: ClimateSeries, lat: float, elevation_m: float | None = None) -> PreparedClimate:
    """Add reference evapotranspiration and reshape the series for historical replay."""
    frame = series.data.copy()
    elevation = elevation_m if elevation_m is not None else (series.provenance.elevation_m or 150.0)
    doy = frame.index.day_of_year.to_numpy()

    # Vapour pressure from dew point; from relative humidity where dew point is missing.
    ea = saturation_vapour_pressure(frame["tdew"])
    tmean = (frame["tmax"] + frame["tmin"]) / 2
    ea = ea.fillna(frame["rh"] / 100 * saturation_vapour_pressure(tmean))

    pm = et0_penman_monteith(frame["tmax"], frame["tmin"], ea, frame["ws2m"], frame["srad"], lat, elevation, doy)
    hargreaves = et0_hargreaves(frame["tmax"], frame["tmin"], lat, doy)
    use_fallback = np.isnan(pm) & ~np.isnan(hargreaves)
    frame["et0"] = np.where(np.isnan(pm), hargreaves, pm)

    core = frame[["t2m", "tmax", "tmin", "precip", "et0", "gwetroot", "gwettop"]]
    core, filled = _fill_from_day_of_year(core)
    core = core.assign(precip=core["precip"].clip(lower=0), et0=core["et0"].clip(lower=0))
    matrix, years = year_matrix(core)
    return PreparedClimate(
        matrix=matrix, years=years, provenance=series.provenance,
        et0_fallback_days=int(use_fallback.sum()), filled_days=filled,
    )
