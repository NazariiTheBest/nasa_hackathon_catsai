"""Historical weather replay and the daily root-zone water balance.

An N-year rotation is replayed from every historical start year that has N
years of data. The water balance is vectorized across both the candidate
rotations and the replay windows, so one pass over the cycle's days evaluates
every candidate under every window.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fieldshift.settings import EngineConfig

DORMANCY_TEMP_C = 5.0
DORMANCY_RUN_DAYS = 10


@dataclass
class Weather:
    """Replay windows for one cycle length: arrays of shape (windows, cycle days)."""

    cycle_years: int
    start_years: list[int]
    et0: np.ndarray
    precip: np.ndarray
    tmax: np.ndarray
    tmin: np.ndarray
    cold: np.ndarray     # 10-day mean temperature below the dormancy threshold
    erosive: np.ndarray  # daily rainfall on erosive-rain days, else 0

    @property
    def windows(self) -> int:
        return self.et0.shape[0]

    @property
    def length(self) -> int:
        return self.et0.shape[1]


def _windows(values: np.ndarray, cycle_years: int) -> np.ndarray:
    """Stack every run of `cycle_years` consecutive years into one row."""
    n = values.shape[0] - cycle_years + 1
    return np.stack([values[s:s + cycle_years].reshape(-1) for s in range(n)])


def build_weather(matrix: dict[str, np.ndarray], years: list[int], cycle_years: int, cfg: EngineConfig) -> Weather:
    n_windows = len(years) - cycle_years + 1
    if n_windows < 1:
        raise ValueError(f"a {cycle_years}-year rotation needs at least {cycle_years} years of climate data")
    t2m = _windows(matrix["t2m"], cycle_years)
    kernel = np.ones(DORMANCY_RUN_DAYS) / DORMANCY_RUN_DAYS
    padded = np.concatenate([t2m[:, -DORMANCY_RUN_DAYS + 1:], t2m], axis=1)  # the cycle repeats
    running = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), 1, padded)
    precip = _windows(matrix["precip"], cycle_years)
    return Weather(
        cycle_years=cycle_years,
        start_years=list(years[:n_windows]),
        et0=_windows(matrix["et0"], cycle_years),
        precip=precip,
        tmax=_windows(matrix["tmax"], cycle_years),
        tmin=_windows(matrix["tmin"], cycle_years),
        cold=running < DORMANCY_TEMP_C,
        erosive=np.where(precip >= cfg.erosive_rain_mm, precip, 0.0),
    )


@dataclass
class WaterBalance:
    """Results of shape (candidates, windows, cycle days)."""

    etc: np.ndarray       # crop water demand, mm/day
    eta: np.ndarray       # water actually used, mm/day
    stressed: np.ndarray  # severe water stress: the crop can take up less than a set share of its demand
    drainage: np.ndarray | None = None   # only with detail=True
    depletion: np.ndarray | None = None  # root-zone depletion at the end of each day, mm; only with detail=True
    initial_depletion: np.ndarray | None = None


def run_water_balance(
    kc: np.ndarray,
    taw: np.ndarray,
    depletion_fraction: np.ndarray,
    winter: np.ndarray,
    weather: Weather,
    cfg: EngineConfig,
    detail: bool = False,
    spin_up: bool = True,
) -> WaterBalance:
    """FAO-56 single-coefficient water balance on a daily root-zone bucket.

    kc, taw (total available water, mm), depletion_fraction and winter have
    shape (candidates, cycle days). State is the depleted share of the current
    root zone; it carries across crop changes. With spin_up the cycle is run
    once to reach a soil-moisture state consistent with the repeating rotation
    before results are recorded.
    """
    n_cand, length = kc.shape
    n_win = weather.windows
    dtype = "float64" if detail else "float32"
    etc_out = np.empty((n_cand, n_win, length), dtype=dtype)
    eta_out = np.empty((n_cand, n_win, length), dtype=dtype)
    stressed = np.empty((n_cand, n_win, length), dtype=bool)
    drainage = np.empty((n_cand, n_win, length)) if detail else None
    depletion_out = np.empty((n_cand, n_win, length)) if detail else None
    initial = None

    any_winter = bool(winter.any())
    share = np.full((n_cand, n_win), 0.3)  # depleted share of the root zone
    for record in ([False, True] if spin_up else [True]):
        if record and detail:
            initial = share * taw[:, 0][:, None]
        for d in range(length):
            kc_d = kc[:, d][:, None]
            if any_winter and winter[:, d].any():
                dormant = winter[:, d][:, None] & weather.cold[None, :, d]
                kc_d = np.where(dormant, np.minimum(kc_d, cfg.dormancy_kc), kc_d)
            etc_d = kc_d * weather.et0[None, :, d]
            taw_d = taw[:, d][:, None]
            raw_d = depletion_fraction[:, d][:, None] * taw_d
            dr = share * taw_d
            over = dr > raw_d
            ks = np.where(over, (taw_d - dr) / np.maximum(taw_d - raw_d, 1e-9), 1.0)
            eta_d = ks * etc_d
            unbounded = dr - weather.precip[None, :, d] + eta_d
            eta_d = eta_d - np.clip(unbounded - taw_d, 0.0, None)  # cannot use more than is stored
            dr = np.clip(unbounded, 0.0, taw_d)
            share = dr / taw_d
            if record:
                etc_out[:, :, d] = etc_d
                eta_out[:, :, d] = eta_d
                stressed[:, :, d] = ks < cfg.drought_stress_ks
                if detail:
                    drainage[:, :, d] = np.clip(-unbounded, 0.0, None)
                    depletion_out[:, :, d] = dr
    return WaterBalance(etc=etc_out, eta=eta_out, stressed=stressed, drainage=drainage,
                        depletion=depletion_out, initial_depletion=initial)


def longest_run(flags: np.ndarray) -> np.ndarray:
    """Longest run of True along the last axis."""
    current = np.zeros(flags.shape[:-1], dtype="int32")
    best = np.zeros(flags.shape[:-1], dtype="int32")
    for d in range(flags.shape[-1]):
        current = (current + 1) * flags[..., d]
        np.maximum(best, current, out=best)
    return best
