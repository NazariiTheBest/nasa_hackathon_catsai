"""Assemble the site context and the site diagnosis."""

from __future__ import annotations

import numpy as np

from fieldshift.climate.power import PowerClient
from fieldshift.contracts import api
from fieldshift.diagnostics.cover import observed_low_cover
from fieldshift.diagnostics.et0 import prepare_climate
from fieldshift.diagnostics.soil import resolve_soil
from fieldshift.diagnostics.trends import ShortRecord, TrendResult, climate_trends, summarize_record
from fieldshift.engine.evaluate import Evaluation, SiteContext
from fieldshift.explain.templates import t
from fieldshift.ingest.registry import BundleRegistry, Unit
from fieldshift.kb import KnowledgeBase
from fieldshift.settings import EngineConfig

SOURCE_VARIABLES = ("ndvi", "evi", "et", "sm_surface", "sm_rootzone", "precip", "soil", "terrain", "suitability")
MIN_REPORTED_GAP_DAYS = 15
CLIMATE_SOURCE = "NASA POWER"


def tier_of(unit: Unit | None) -> str:
    if unit is None:
        return "climate_only"
    return "field" if unit.unit_type == "field" else "grid"


def scope_of(tier: str) -> str:
    return {"field": "field", "grid": "grid_cell"}.get(tier, "climate_cell")


def build_context(lat: float, lon: float, registry: BundleRegistry, power: PowerClient, kb: KnowledgeBase,
                  cfg: EngineConfig, unit: Unit | None = None) -> SiteContext:
    """Gather climate, satellite and soil inputs for a location.

    Raises ClimateUnavailable when the climate series cannot be obtained; the
    other inputs degrade to a coarser data tier instead.
    """
    unit = unit or registry.lookup(lat, lon)
    static = registry.static(unit.unit_id) if unit else None
    soil = resolve_soil(static, cfg)
    climate = prepare_climate(power.get_series(lat, lon), lat, soil.elevation_m)
    sources = {}
    if unit:
        for variable in SOURCE_VARIABLES:
            label = registry.source_label(unit.unit_id, variable)
            if label:
                sources[variable] = label
    return SiteContext(
        lat=lat, lon=lon, tier=tier_of(unit), unit=unit, soil=soil, climate=climate, kb=kb, cfg=cfg,
        timeseries=registry.timeseries(unit.unit_id) if unit else None,
        suitability=registry.suitability(unit.unit_id) if unit else None,
        sources=sources,
    )


def unit_summary(unit: Unit | None) -> api.UnitSummary | None:
    if unit is None:
        return None
    return api.UnitSummary(unit_id=unit.unit_id, unit_type=unit.unit_type, name=unit.name,
                           bundle_id=unit.bundle_id, area_ha=unit.area_ha)


def _day_ref(calendar, absolute_day: int) -> api.DayRef:
    year_index, doy = calendar.day_ref(absolute_day)
    return api.DayRef(year_index=year_index, doy=doy)


def bare_windows(ctx: SiteContext, baseline: Evaluation, lang: str) -> list[api.BareWindow]:
    calendar = baseline.calendar
    weather = ctx.weather(calendar.cycle_years)
    factor, rain_only = ctx.terrain
    out = []
    for gap in calendar.gaps(min_days=MIN_REPORTED_GAP_DAYS):
        days = calendar.days_of(gap.start, gap.end)
        rain = float(weather.erosive[:, days].sum(axis=1).mean())
        out.append(api.BareWindow(
            start=_day_ref(calendar, gap.start), end=_day_ref(calendar, gap.end - 1), days=gap.days,
            after_crop_id=gap.after.crop_id, after_crop_name=ctx.kb.name(gap.after.crop_id, lang),
            erosive_rain_mm=round(rain, 1),
            erosion_exposure=round(min(1.0, rain / ctx.cfg.erosive_rain_ref_mm) * factor, 3),
            rain_only=rain_only,
        ))
    return out


def low_cover_periods(ctx: SiteContext) -> list[api.LowCoverPeriod]:
    source, resolution = ctx.sources.get("ndvi", ("bundle time series", "unknown"))
    return [
        api.LowCoverPeriod(start_doy=p.start_doy, end_doy=p.end_doy, median_ndvi=p.median_ndvi, years=p.years,
                           source=source, resolution=resolution)
        for p in observed_low_cover(ctx.series("ndvi"), ctx.cfg.bare_ndvi_threshold)
    ]


def stress_calendar(ctx: SiteContext, baseline: Evaluation, lang: str) -> list[api.StressEntry]:
    calendar = baseline.calendar
    out = []
    for s in baseline.mains:
        for hazard, occurred in s.events.items():
            stage = "mid" if hazard == "drought" else getattr(s.crop.stress, hazard).stage
            start, end = s.stages[stage]
            if end <= start:
                continue
            out.append(api.StressEntry(
                crop_id=s.crop.id, crop_name=ctx.kb.name(s.crop.id, lang),
                hazard=hazard, hazard_label=t(lang, f"hazard.{hazard}"),
                stage=stage, stage_label=t(lang, f"stage.{stage}"),
                window_start_doy=calendar.day_ref(start)[1], window_end_doy=calendar.day_ref(end - 1)[1],
                probability=round(float(occurred.mean()), 3),
                years_hit=int(occurred.sum()), years_total=int(occurred.size),
            ))
    return out


def water_balance(ctx: SiteContext, baseline: Evaluation, lang: str) -> list[api.WaterBalanceEntry]:
    out = []
    for s in baseline.mains:
        demand, supply = float(np.median(s.demand)), float(np.median(s.actual))
        out.append(api.WaterBalanceEntry(
            crop_id=s.crop.id, crop_name=ctx.kb.name(s.crop.id, lang),
            demand_mm=round(demand, 0), supply_mm=round(supply, 0), deficit_mm=round(max(demand - supply, 0), 0),
        ))
    return out


def _trend_out(result: TrendResult, lang: str, source: str, scope: str, cfg: EngineConfig) -> api.Trend:
    return api.Trend(
        indicator=result.indicator,
        label=t(lang, f"trend.{result.indicator}", threshold=cfg.hot_day_tmax_c),
        unit=t(lang, f"unit.{result.unit}"),
        slope_per_decade=round(result.slope_per_decade, 4), p_value=round(result.p_value, 4),
        significant=result.significant, period=result.period, n_years=result.n_years,
        source=source, scope=scope,
    )


def trends_and_anomalies(ctx: SiteContext, lang: str) -> tuple[list[api.Trend], list[api.Anomaly]]:
    cfg = ctx.cfg
    trends = [_trend_out(r, lang, CLIMATE_SOURCE, "climate_cell", cfg)
              for r in climate_trends(ctx.climate.matrix, ctx.climate.years, cfg)]
    anomalies: list[api.Anomaly] = []
    records = (("ndvi", "ndvi_peak", "ndvi", "max"), ("sm_surface", "sm_surface", "m3m3", "mean"),
               ("sm_rootzone", "sm_rootzone", "m3m3", "mean"))
    for variable, indicator, unit, reducer in records:
        frame = ctx.series(variable)
        if frame is None:
            continue
        source = ctx.sources.get(variable, ("bundle time series", ""))[0]
        summary = summarize_record(indicator, frame, cfg, unit=unit, reducer=reducer)
        if isinstance(summary, TrendResult):
            trends.append(_trend_out(summary, lang, source, scope_of(ctx.tier), cfg))
        elif isinstance(summary, ShortRecord):
            key = f"trend.{indicator}" if indicator == "ndvi_peak" else f"anomaly.{indicator}"
            anomalies.append(api.Anomaly(
                variable=variable, label=t(lang, key), unit=t(lang, f"unit.{unit}"),
                period=f"{summary.first_year}-{summary.last_year}", n_years=summary.n_years,
                mean=round(summary.mean, 4),
                recent=[api.YearAnomaly(year=y, anomaly=round(a, 4)) for y, a in summary.recent],
                source=source,
            ))
    return trends, anomalies


def soil_info(ctx: SiteContext) -> api.SoilInfo:
    soil = ctx.soil
    source = ctx.sources.get("soil", (None, None))[0]
    return api.SoilInfo(
        awc_mm_per_m=soil.awc_mm_per_m, awc_status=soil.awc_status, k_factor=soil.k_factor, k_status=soil.k_status,
        slope_pct=soil.slope_pct, clay_pct=soil.clay_pct, sand_pct=soil.sand_pct, soc_pct=soil.soc_pct,
        ph=soil.ph, source=source,
    )


def climate_info(ctx: SiteContext) -> api.ClimateInfo:
    p = ctx.climate.provenance
    return api.ClimateInfo(
        source=p.source, spatial_resolution=p.spatial_resolution, period=ctx.climate.period,
        years=ctx.climate.n_years, cell_lat=p.cell_lat, cell_lon=p.cell_lon, retrieved_at=p.retrieved_at,
        et0_fallback_days=ctx.climate.et0_fallback_days, filled_days=ctx.climate.filled_days,
    )


def diagnose(ctx: SiteContext, baseline: Evaluation, lang: str = "en") -> api.Site:
    """The site diagnosis for a location and its baseline rotation."""
    trends, anomalies = trends_and_anomalies(ctx, lang)
    gaps: list[api.Notice] = []
    if ctx.series("ndvi") is None:
        gaps.append(api.Notice(code="gap.no_timeseries", text=t(lang, "gap.no_timeseries")))
    if ctx.tier == "climate_only":
        gaps.append(api.Notice(code="gap.no_satellite_or_soil", text=t(lang, "gap.no_satellite_or_soil")))
    if ctx.soil.awc_status == "assumed":
        gaps.append(api.Notice(code="gap.soil_assumed", text=t(lang, "gap.soil_assumed", awc=ctx.soil.awc_mm_per_m)))
    elif ctx.soil.derived_or_assumed:
        gaps.append(api.Notice(code="gap.soil_derived", text=t(lang, "gap.soil_derived")))
    return api.Site(
        data_tier=ctx.tier, lat=ctx.lat, lon=ctx.lon, unit=unit_summary(ctx.unit),
        bare_windows=bare_windows(ctx, baseline, lang),
        observed_low_cover=low_cover_periods(ctx),
        stress=stress_calendar(ctx, baseline, lang),
        water_balance=water_balance(ctx, baseline, lang),
        trends=trends, anomalies=anomalies,
        soil=soil_info(ctx), climate=climate_info(ctx),
        information_gaps=gaps,
    )
