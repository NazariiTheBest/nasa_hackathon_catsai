"""Evaluate rotation calendars at a site: per-slot water and stress, and the eight objectives."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fieldshift.contracts.api import OBJECTIVES
from fieldshift.diagnostics.et0 import PreparedClimate
from fieldshift.diagnostics.soil import SoilProps, terrain_factor
from fieldshift.engine.calendar import YEAR, Calendar, DailyArrays, Slot, daily_arrays, stage_bounds
from fieldshift.engine.simulate import Weather, build_weather, longest_run, run_water_balance
from fieldshift.ingest.registry import Unit
from fieldshift.kb import Crop, KnowledgeBase
from fieldshift.settings import EngineConfig


@dataclass
class SiteContext:
    """Everything known about one location, shared by diagnostics and the engine."""

    lat: float
    lon: float
    tier: str  # field | grid | climate_only
    unit: Unit | None
    soil: SoilProps
    climate: PreparedClimate
    kb: KnowledgeBase
    cfg: EngineConfig
    timeseries: pd.DataFrame | None = None
    suitability: dict[str, float] | None = None
    sources: dict[str, tuple[str, str]] = field(default_factory=dict)  # variable -> (product, resolution)
    _weather: dict[int, Weather] = field(default_factory=dict, repr=False)
    _heat_share: dict[str, float] = field(default_factory=dict, repr=False)

    def weather(self, cycle_years: int) -> Weather:
        if cycle_years not in self._weather:
            self._weather[cycle_years] = build_weather(self.climate.matrix, self.climate.years, cycle_years, self.cfg)
        return self._weather[cycle_years]

    @property
    def terrain(self) -> tuple[float, bool]:
        return terrain_factor(self.soil, self.cfg)

    def series(self, variable: str) -> pd.DataFrame | None:
        if self.timeseries is None or self.timeseries.empty:
            return None
        rows = self.timeseries[self.timeseries["variable"] == variable]
        return rows if not rows.empty else None

    def heat_units_share(self, crop_id: str) -> float:
        """Share of historical years that supply the crop's heat units between sowing and harvest."""
        if crop_id not in self._heat_share:
            crop = self.kb.get(crop_id)
            flat = self.climate.matrix["t2m"].reshape(-1)
            degree_days = np.clip(flat - crop.t_base_c, 0, None)
            cumulative = np.concatenate([[0.0], np.cumsum(degree_days)])
            sow = crop.default_sow_doy - 1
            starts = np.arange(len(self.climate.years)) * YEAR + sow
            ends = starts + crop.season_days
            ok = ends <= flat.size
            totals = cumulative[ends[ok]] - cumulative[starts[ok]]
            self._heat_share[crop_id] = float((totals >= crop.gdd_to_maturity).mean()) if totals.size else 0.0
        return self._heat_share[crop_id]


@dataclass
class SlotEval:
    slot: Slot
    crop: Crop
    demand: np.ndarray  # mm over the slot, per replay window
    actual: np.ndarray
    events: dict[str, np.ndarray]  # hazard -> occurred, per replay window
    stages: dict[str, tuple[int, int]]

    @property
    def deficit_ratio(self) -> np.ndarray:
        return 1 - np.divide(self.actual, self.demand, out=np.ones_like(self.actual), where=self.demand > 0)


@dataclass
class Evaluation:
    calendar: Calendar
    slots: list[SlotEval]
    windows: int
    water_demand: np.ndarray   # mm per year
    water_met: np.ndarray      # share of demand met
    erosive_bare: np.ndarray   # mm of erosive rain per year on bare soil, residue-weighted
    erosive_total: np.ndarray  # mm of erosive rain per year
    bare_days_per_year: float
    n_per_year: float
    families: int
    return_gaps: dict[str, int]
    objectives: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def mains(self) -> list[SlotEval]:
        return [s for s in self.slots if s.slot.role == "main"]

    @property
    def covers(self) -> list[SlotEval]:
        return [s for s in self.slots if s.slot.role == "cover"]

    def median(self, name: str) -> float:
        return float(np.median(self.objectives[name]))


def min_cyclic_gap(positions: list[int], cycle_years: int) -> int:
    """Shortest interval, in years, between occurrences on a repeating cycle."""
    pos = sorted(p % cycle_years for p in positions)
    if len(pos) <= 1:
        return cycle_years
    gaps = [b - a for a, b in zip(pos, pos[1:])] + [pos[0] + cycle_years - pos[-1]]
    return max(min(gaps), 0)


def crop_return_gaps(calendar: Calendar) -> dict[str, int]:
    """Main crop id -> shortest return interval in years."""
    return {crop_id: min_cyclic_gap(years, calendar.cycle_years) for crop_id, years in calendar.harvest_years().items()}


def family_return_gaps(calendar: Calendar, kb: KnowledgeBase) -> dict[str, int]:
    """Botanical family -> shortest interval in years between main crops of that family."""
    by_family: dict[str, list[int]] = {}
    for crop_id, years in calendar.harvest_years().items():
        by_family.setdefault(kb.get(crop_id).family, []).extend(years)
    return {family: min_cyclic_gap(years, calendar.cycle_years) for family, years in by_family.items()}


def _slot_events(slot: Slot, crop: Crop, stages: dict[str, tuple[int, int]], calendar: Calendar,
                 stressed: np.ndarray, weather: Weather, cfg: EngineConfig) -> dict[str, np.ndarray]:
    events: dict[str, np.ndarray] = {}
    none = np.zeros(weather.windows, dtype=bool)

    def days(stage: str) -> np.ndarray:
        return calendar.days_of(*stages[stage])

    if crop.stress.heat:
        d = days(crop.stress.heat.stage)
        events["heat"] = ((weather.tmax[:, d] >= crop.stress.heat.tmax_c).sum(axis=1) >= cfg.heat_event_min_days) if d.size else none
    if crop.stress.frost:
        d = days(crop.stress.frost.stage)
        events["frost"] = (weather.tmin[:, d] <= crop.stress.frost.tmin_c).any(axis=1) if d.size else none
    if crop.stress.winterkill:
        d = days(crop.stress.winterkill.stage)
        events["winterkill"] = (weather.tmin[:, d] <= crop.stress.winterkill.tmin_c).any(axis=1) if d.size else none
    d = days("mid")
    events["drought"] = (longest_run(stressed[:, d]) >= cfg.drought_run_days) if d.size else none
    return events


def _objectives(ev: Evaluation, arrays: DailyArrays, ctx: SiteContext) -> dict[str, np.ndarray]:
    cfg, cal = ctx.cfg, ev.calendar
    n, w = cal.cycle_years, ev.windows
    full = np.ones(w)

    water = np.clip(ev.water_met, 0, 1)
    nitrogen = full * min(1.0, ev.n_per_year / cfg.n_fixation_cap_kg_ha)

    bare_share = 1 - cal.covered_days() / cal.length
    ratio = np.divide(ev.erosive_bare, ev.erosive_total, out=np.full(w, bare_share), where=ev.erosive_total > 0)
    factor, _ = ctx.terrain
    erosion = 1 - np.clip(ratio, 0, 1) * factor

    residue = sum(s.crop.residue_cover * s.slot.growth_share for s in ev.slots)
    organic = full * float(np.clip(0.5 * (1 - bare_share) + 0.5 * min(1.0, residue / n), 0, 1))

    forage_sum = sum(s.crop.forage_value for s in ev.mains) + 0.5 * sum(s.crop.forage_value * s.slot.growth_share for s in ev.covers)
    forage = full * min(1.0, forage_sum / n)

    income_sum = np.zeros(w)
    stress_sum = np.zeros(w)
    for s in ev.mains:
        tolerance = 1 - 0.5 * s.crop.drought_tolerance
        loss = cfg.yield_loss.water * s.deficit_ratio * tolerance
        survive = np.ones(w)
        for hazard, occurred in s.events.items():
            weight = getattr(cfg.stress_weights, hazard) * (tolerance if hazard == "drought" else 1.0)
            survive *= 1 - weight * occurred
            if hazard != "drought":
                loss = loss + getattr(cfg.yield_loss, hazard) * occurred
        income_sum += s.crop.market_value * (1 - np.clip(loss, 0, 0.95))
        stress_sum += 1 - survive
    income = np.clip(income_sum / n - cfg.cover_cost_income * len(ev.covers) / n, 0, 1)
    resilience = 1 - stress_sum / max(len(ev.mains), 1)

    diversity = min(1.0, (ev.families - 1) / 3)
    compliance = float(np.mean([min(1.0, ev.return_gaps[s.crop.id] / s.crop.min_return_years) for s in ev.mains]))
    pest_break = full * (0.5 * diversity + 0.5 * compliance)

    values = dict(water=water, nitrogen=nitrogen, erosion=erosion, organic_matter=organic,
                  forage=forage, income=income, resilience=resilience, pest_break=pest_break)
    return {name: values[name] for name in OBJECTIVES}


def _evaluate_one(calendar: Calendar, arrays: DailyArrays, etc: np.ndarray, eta: np.ndarray,
                  stressed: np.ndarray, weather: Weather, ctx: SiteContext) -> Evaluation:
    slots: list[SlotEval] = []
    total_demand = np.zeros(weather.windows)
    total_actual = np.zeros(weather.windows)
    for slot in calendar.slots:
        crop = ctx.kb.get(slot.crop_id)
        days = calendar.days_of(slot.start, slot.end)
        demand = etc[:, days].sum(axis=1, dtype="float64")
        actual = eta[:, days].sum(axis=1, dtype="float64")
        stages = stage_bounds(slot, crop)
        events = _slot_events(slot, crop, stages, calendar, stressed, weather, ctx.cfg) if slot.role == "main" else {}
        slots.append(SlotEval(slot=slot, crop=crop, demand=demand, actual=actual, events=events, stages=stages))
        total_demand += demand
        total_actual += actual

    n = calendar.cycle_years
    ev = Evaluation(
        calendar=calendar,
        slots=slots,
        windows=weather.windows,
        water_demand=total_demand / n,
        water_met=np.divide(total_actual, total_demand, out=np.ones_like(total_actual), where=total_demand > 0),
        erosive_bare=(weather.erosive * arrays.bare_weight[None, :]).sum(axis=1) / n,
        erosive_total=weather.erosive.sum(axis=1) / n,
        bare_days_per_year=(calendar.length - calendar.covered_days()) / n,
        n_per_year=sum(s.crop.n_fixation_kg_ha * s.slot.growth_share for s in slots) / n,
        families=len({s.crop.family for s in slots if s.slot.role == "main"}),
        return_gaps=crop_return_gaps(calendar),
    )
    ev.objectives = _objectives(ev, arrays, ctx)
    return ev


def evaluate(calendars: list[Calendar], ctx: SiteContext) -> list[Evaluation]:
    """Evaluate calendars under historical weather, batched by cycle length."""
    out: list[Evaluation | None] = [None] * len(calendars)
    groups: dict[int, list[int]] = {}
    for i, calendar in enumerate(calendars):
        groups.setdefault(calendar.cycle_years, []).append(i)
    for cycle_years, indices in groups.items():
        weather = ctx.weather(cycle_years)
        arrays = [daily_arrays(calendars[i], ctx.kb, ctx.cfg) for i in indices]
        balance = run_water_balance(
            kc=np.stack([a.kc for a in arrays]),
            taw=np.stack([a.root_m for a in arrays]) * ctx.soil.awc_mm_per_m,
            depletion_fraction=np.stack([a.depletion for a in arrays]),
            winter=np.stack([a.winter for a in arrays]),
            weather=weather,
            cfg=ctx.cfg,
        )
        for j, i in enumerate(indices):
            out[i] = _evaluate_one(calendars[i], arrays[j], balance.etc[j], balance.eta[j], balance.stressed[j], weather, ctx)
    return out  # type: ignore[return-value]
