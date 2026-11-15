"""Rotation calendar: dated crop slots on a repeating cycle.

A rotation is entered as an ordered list of main crops plus optional cover
crops. The calendar gives every crop a sowing and a harvest day on a cycle of
N years of 365 days. Winter crops are sown in autumn and harvested the next
summer, so slots may cross a year boundary and the last slot may wrap around
the end of the cycle.

Days are counted from 1 January of cycle year 0 ("absolute days"). A slot
occupies the half-open range [start, end).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from fieldshift.kb import Crop, KnowledgeBase
from fieldshift.kb.loader import STAGES
from fieldshift.settings import EngineConfig

YEAR = 365


@dataclass(frozen=True)
class SequenceSpec:
    """What the farmer (or an operator) states: main crops in order, and cover crops by position."""

    mains: tuple[str, ...]
    covers: tuple[tuple[int, str], ...] = ()  # (index of the main crop it follows, cover crop id)

    @staticmethod
    def of(mains, covers=()) -> "SequenceSpec":
        return SequenceSpec(tuple(mains), tuple(sorted((int(i), str(c)) for i, c in covers)))

    @property
    def cover_map(self) -> dict[int, str]:
        return dict(self.covers)

    @property
    def crop_ids(self) -> set[str]:
        return set(self.mains) | {c for _, c in self.covers}


@dataclass
class Slot:
    crop_id: str
    role: str  # "main" | "cover"
    start: int
    end: int
    index: int  # position among mains; for a cover crop, the main crop it follows
    clamped: bool = False
    growth_share: float = 1.0

    @property
    def days(self) -> int:
        return self.end - self.start


@dataclass
class BareGap:
    start: int
    end: int
    after: Slot

    @property
    def days(self) -> int:
        return self.end - self.start


@dataclass
class Calendar:
    spec: SequenceSpec
    slots: list[Slot]
    cycle_years: int
    notices: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def length(self) -> int:
        return self.cycle_years * YEAR

    @property
    def mains(self) -> list[Slot]:
        return [s for s in self.slots if s.role == "main"]

    @property
    def covers(self) -> list[Slot]:
        return [s for s in self.slots if s.role == "cover"]

    def day_ref(self, absolute_day: int) -> tuple[int, int]:
        """(cycle year index, day of year 1-365) of an absolute day."""
        day = absolute_day % self.length
        return day // YEAR, day % YEAR + 1

    def days_of(self, start: int, end: int) -> np.ndarray:
        """Cycle-day indices of the absolute range [start, end), wrapped onto the cycle."""
        return np.arange(start, end) % self.length

    def gaps(self, min_days: int = 1) -> list[BareGap]:
        """Bare periods between consecutive slots on the repeating cycle."""
        ordered = sorted(self.slots, key=lambda s: s.start)
        gaps = []
        for i, slot in enumerate(ordered):
            nxt = ordered[(i + 1) % len(ordered)]
            next_start = nxt.start + (self.length if i == len(ordered) - 1 else 0)
            if next_start - slot.end >= min_days:
                gaps.append(BareGap(slot.end, next_start, slot))
        return gaps

    def covered_days(self) -> int:
        return sum(s.days for s in self.slots)

    def harvest_years(self) -> dict[str, list[int]]:
        """Crop id -> cycle years (0-based, unwrapped order) in which a main crop is harvested."""
        out: dict[str, list[int]] = {}
        for slot in self.mains:
            out.setdefault(slot.crop_id, []).append((slot.end - 1) // YEAR)
        return out


def stage_bounds(slot: Slot, crop: Crop) -> dict[str, tuple[int, int]]:
    """Absolute [start, end) of each growth stage, truncated at the slot's end."""
    bounds, cursor = {}, slot.start
    for stage, length in zip(STAGES, crop.stages_days):
        end = min(cursor + length, slot.end)
        bounds[stage] = (cursor, max(end, cursor))
        cursor = end
    return bounds


def _place_main(crop: Crop, earliest: int | None, cfg: EngineConfig, strict: bool) -> tuple[int, bool, int]:
    """Sowing day for a main crop that may not be sown before `earliest`.

    Returns (sowing day, clamped, days late). In strict mode a crop whose window
    has passed waits for the next year. Otherwise a crop that is only a little
    late is sown anyway and flagged, because the farmer's declared order wins.
    """
    w_start, w_end = crop.sowing_window_doy[0] - 1, crop.sowing_window_doy[1] - 1
    default = crop.default_sow_doy - 1
    if earliest is None:
        return default, False, 0
    year, day = divmod(earliest, YEAR)
    if day <= default:
        return year * YEAR + default, False, 0
    if day <= w_end:
        return earliest, False, 0
    late = day - w_end
    if not strict and late <= cfg.baseline_clamp_tolerance_days:
        return earliest, True, late
    return (year + 1) * YEAR + default, False, 0


def _place_cover(cover: Crop, gap_start: int, gap_end: int, cfg: EngineConfig) -> tuple[int, int] | None:
    """Sowing and termination day of a cover crop inside [gap_start, gap_end), or None if it does not fit."""
    w_start, w_end = cover.sowing_window_doy[0] - 1, cover.sowing_window_doy[1] - 1
    earliest = gap_start + cfg.turnaround_days
    latest_end = gap_end - cfg.cover_termination_lead_days
    year, day = divmod(earliest, YEAR)
    for candidate_year in (year, year + 1):
        if candidate_year == year:
            if day > w_end:
                continue
            sow = max(earliest, year * YEAR + w_start)
        else:
            sow = candidate_year * YEAR + w_start
        end = min(sow + cover.season_days, latest_end)
        if end - sow >= cfg.min_cover_growth_days:
            return sow, end
    return None


def build_calendar(spec: SequenceSpec, kb: KnowledgeBase, cfg: EngineConfig, strict: bool = True) -> Calendar | None:
    """Build the dated calendar for a crop sequence.

    strict=True is used for generated alternatives: every crop is sown inside its
    window and a cover crop that does not fit makes the sequence infeasible
    (None). strict=False is used for the farmer's baseline, which is never
    rejected: late sowings are clamped and cover crops that do not fit are
    dropped, each with a notice.
    """
    notices: list[tuple[str, dict]] = []

    def place_mains(first_sow: int | None) -> list[Slot]:
        notices.clear()
        placed: list[Slot] = []
        earliest: int | None = None
        for i, crop_id in enumerate(spec.mains):
            crop = kb.get(crop_id)
            if i == 0 and first_sow is not None:
                sow, clamped, late = first_sow, False, 0
            else:
                sow, clamped, late = _place_main(crop, earliest, cfg, strict)
            if clamped:
                notices.append(("timing_conflict", {"crop": crop_id, "prev": spec.mains[i - 1], "days": late}))
            placed.append(Slot(crop_id, "main", sow, sow + crop.season_days, i, clamped=clamped))
            earliest = placed[-1].end + cfg.turnaround_days
        return placed

    # The cycle is the shortest whole number of years after which the first crop can be sown
    # again. If its default sowing day comes a few days too early for that, it is sown later
    # inside its window instead of leaving the field fallow for a year.
    mains = place_mains(None)
    first_window_end = kb.get(spec.mains[0]).sowing_window_doy[1] - 1
    cycle_years = 1
    for _ in range(4):
        first, last = mains[0], mains[-1]
        needed = last.end + cfg.turnaround_days
        cycle_years = 1
        while first_window_end + cycle_years * YEAR < needed:
            cycle_years += 1
        if first.start + cycle_years * YEAR >= needed:
            break
        mains = place_mains(needed - cycle_years * YEAR)
    else:
        first, last = mains[0], mains[-1]
        while first.start + cycle_years * YEAR < last.end + cfg.turnaround_days:
            cycle_years += 1
    length = cycle_years * YEAR

    slots = list(mains)
    for after_index, cover_id in spec.covers:
        if not 0 <= after_index < len(mains):
            notices.append(("cover_dropped", {"cover": cover_id, "main": "?"}))
            if strict:
                return None
            continue
        gap_start = mains[after_index].end
        nxt = mains[(after_index + 1) % len(mains)]
        gap_end = nxt.start + (length if after_index == len(mains) - 1 else 0)
        cover = kb.get(cover_id)
        placed = _place_cover(cover, gap_start, gap_end, cfg)
        if placed is None:
            if strict:
                return None
            notices.append(("cover_dropped", {"cover": cover_id, "main": mains[after_index].crop_id}))
            continue
        sow, end = placed
        slots.append(Slot(cover_id, "cover", sow, end, after_index, growth_share=min(1.0, (end - sow) / cover.season_days)))

    slots.sort(key=lambda s: s.start)
    return Calendar(spec=spec, slots=slots, cycle_years=cycle_years, notices=notices)


@dataclass
class DailyArrays:
    """Per-cycle-day inputs of the water balance and the erosion index, each of length `calendar.length`."""

    kc: np.ndarray
    root_m: np.ndarray
    depletion: np.ndarray
    winter: np.ndarray       # day belongs to a winter-season crop (dormancy applies)
    bare_weight: np.ndarray  # 0 under a crop; on bare days, 1 reduced by the previous crop's residue


def daily_arrays(calendar: Calendar, kb: KnowledgeBase, cfg: EngineConfig) -> DailyArrays:
    length = calendar.length
    kc = np.full(length, cfg.bare_soil_kc)
    root = np.full(length, cfg.bare_soil_depth_m)
    depletion = np.full(length, 0.4)
    winter = np.zeros(length, dtype=bool)
    bare_weight = np.ones(length)

    mains = calendar.mains
    for gap in calendar.gaps():
        prev = kb.get(gap.after.crop_id)
        residue = prev.residue_cover * gap.after.growth_share
        if gap.after.role == "cover":
            # A cover crop's residue lies on top of the stubble of the main crop it followed.
            residue = min(1.0, residue + kb.get(mains[gap.after.index].crop_id).residue_cover)
        bare_weight[calendar.days_of(gap.start, gap.end)] = 1 - 0.5 * residue

    for slot in calendar.slots:
        crop = kb.get(slot.crop_id)
        days = calendar.days_of(slot.start, slot.end)
        t = np.arange(slot.days, dtype="float64")
        l_ini, l_dev, l_mid, l_late = crop.stages_days
        ini, mid, end = crop.kc.ini, crop.kc.mid, crop.kc.end
        curve = np.where(
            t < l_ini, ini,
            np.where(
                t < l_ini + l_dev, ini + (t - l_ini) / l_dev * (mid - ini),
                np.where(t < l_ini + l_dev + l_mid, mid, mid + (t - l_ini - l_dev - l_mid) / l_late * (end - mid)),
            ),
        )
        kc[days] = curve
        grow = np.clip(t / (l_ini + l_dev), 0, 1)
        root[days] = np.maximum(cfg.bare_soil_depth_m * 0.75, 0.3) + (crop.root_depth_m - 0.3) * grow
        depletion[days] = crop.depletion_fraction
        winter[days] = crop.season == "winter"
        bare_weight[days] = 0.0
    return DailyArrays(kc=kc, root_m=np.maximum(root, 0.1), depletion=depletion, winter=winter, bare_weight=bare_weight)
