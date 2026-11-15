"""Long-term trends and short-record anomalies."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from fieldshift.settings import EngineConfig

# Slices on a 365-day (no leap day) year.
APR_SEP = slice(90, 273)   # 1 April - 30 September
JUN_AUG = slice(151, 243)  # 1 June - 31 August


@dataclass
class TrendResult:
    indicator: str
    unit: str
    slope_per_decade: float
    p_value: float
    significant: bool
    n_years: int
    first_year: int
    last_year: int

    @property
    def period(self) -> str:
        return f"{self.first_year}-{self.last_year}"


def theil_sen_trend(indicator: str, unit: str, years, values, alpha: float = 0.05) -> TrendResult | None:
    """Theil-Sen slope per decade with a Mann-Kendall (Kendall tau) p-value."""
    years = np.asarray(years, dtype="float64")
    values = np.asarray(values, dtype="float64")
    keep = np.isfinite(values)
    years, values = years[keep], values[keep]
    if years.size < 3:
        return None
    if np.allclose(values, values[0]):
        slope, p_value = 0.0, 1.0
    else:
        slope = float(stats.theilslopes(values, years)[0])
        p_value = float(stats.kendalltau(years, values).pvalue)
        if not np.isfinite(p_value):
            p_value = 1.0
    return TrendResult(
        indicator=indicator, unit=unit, slope_per_decade=slope * 10, p_value=p_value,
        significant=bool(p_value < alpha), n_years=int(years.size),
        first_year=int(years[0]), last_year=int(years[-1]),
    )


def annual_indicators(matrix: dict[str, np.ndarray], cfg: EngineConfig) -> dict[str, tuple[str, np.ndarray]]:
    """Annual series (unit, values per year) of the climate trend indicators."""
    return {
        "tmean_apr_sep": ("c", matrix["t2m"][:, APR_SEP].mean(axis=1)),
        "precip_apr_sep": ("mm", matrix["precip"][:, APR_SEP].sum(axis=1)),
        "water_balance_apr_sep": ("mm", (matrix["precip"][:, APR_SEP] - matrix["et0"][:, APR_SEP]).sum(axis=1)),
        "hot_days": ("days", (matrix["tmax"] >= cfg.hot_day_tmax_c).sum(axis=1).astype("float64")),
        "rootzone_wetness_jja": ("fraction", matrix["gwetroot"][:, JUN_AUG].mean(axis=1)),
    }


def climate_trends(matrix: dict[str, np.ndarray], years: list[int], cfg: EngineConfig) -> list[TrendResult]:
    out = []
    for indicator, (unit, values) in annual_indicators(matrix, cfg).items():
        result = theil_sen_trend(indicator, unit, years, values)
        if result is not None:
            out.append(result)
    return out


@dataclass
class ShortRecord:
    variable: str
    n_years: int
    first_year: int
    last_year: int
    mean: float
    recent: list[tuple[int, float]]  # (year, anomaly against the record mean)


def annual_series(frame: pd.DataFrame) -> pd.Series:
    """Annual mean of a per-unit time series, keeping only reasonably complete years."""
    frame = frame.dropna(subset=["value"])
    if frame.empty:
        return pd.Series(dtype="float64")
    by_year = frame.groupby(frame["date"].dt.year)["value"]
    counts = by_year.count()
    keep = counts[counts >= 0.6 * counts.max()].index
    return by_year.mean().loc[keep]


def summarize_record(variable: str, frame: pd.DataFrame, cfg: EngineConfig, unit: str = "fraction",
                     reducer: str = "mean") -> TrendResult | ShortRecord | None:
    """A trend for a long record; anomalies against its own mean for a short one.

    Series shorter than `short_record_years` are never given a slope or a
    significance: a decade of data cannot separate a trend from variability.
    """
    if reducer == "max":
        clean = frame.dropna(subset=["value"])
        annual = clean.groupby(clean["date"].dt.year)["value"].max() if not clean.empty else pd.Series(dtype="float64")
    else:
        annual = annual_series(frame)
    if annual.size < 2:
        return None
    years = annual.index.to_numpy()
    if annual.size < cfg.short_record_years:
        mean = float(annual.mean())
        recent = [(int(y), float(v - mean)) for y, v in annual.tail(3).items()]
        return ShortRecord(variable=variable, n_years=int(annual.size), first_year=int(years[0]),
                           last_year=int(years[-1]), mean=mean, recent=recent)
    return theil_sen_trend(variable, unit, years, annual.to_numpy())
