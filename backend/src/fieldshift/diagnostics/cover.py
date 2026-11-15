"""Observed low-cover periods from a vegetation-index time series."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

BIN_DAYS = 16  # MODIS 16-day composites: 23 bins per year
N_BINS = 23


@dataclass
class LowCover:
    start_doy: int
    end_doy: int
    median_ndvi: float
    years: int

    @property
    def days(self) -> int:
        if self.end_doy >= self.start_doy:
            return self.end_doy - self.start_doy + 1
        return (365 - self.start_doy + 1) + self.end_doy


def observed_low_cover(ndvi: pd.DataFrame | None, threshold: float) -> list[LowCover]:
    """Day-of-year periods whose multi-year median index is below the threshold.

    Periods are found on the circular year, so a winter period that runs from
    November to March is reported once, with start_doy greater than end_doy.
    """
    if ndvi is None or ndvi.empty:
        return []
    frame = ndvi.dropna(subset=["value"])
    if frame.empty:
        return []
    doy = frame["date"].dt.day_of_year.to_numpy()
    bins = np.minimum((doy - 1) // BIN_DAYS, N_BINS - 1)
    medians = frame.groupby(bins)["value"].median().reindex(range(N_BINS))
    years = int(frame["date"].dt.year.nunique())
    low = (medians < threshold).fillna(False).to_numpy()
    if not low.any():
        return []

    def period(first_bin: int, last_bin: int, members: list[int]) -> LowCover:
        end = 365 if last_bin == N_BINS - 1 else (last_bin + 1) * BIN_DAYS
        return LowCover(start_doy=first_bin * BIN_DAYS + 1, end_doy=end,
                        median_ndvi=round(float(medians.iloc[members].median()), 3), years=years)

    if low.all():
        return [period(0, N_BINS - 1, list(range(N_BINS)))]

    # Rotate so the scan starts on a covered bin; runs then never straddle the scan's end.
    offset = int(np.flatnonzero(~low)[0])
    order = [(offset + i) % N_BINS for i in range(N_BINS)]
    periods, run = [], []
    for b in order + [None]:
        if b is not None and low[b]:
            run.append(b)
        elif run:
            periods.append(period(run[0], run[-1], run))
            run = []
    return sorted(periods, key=lambda p: p.start_doy)
