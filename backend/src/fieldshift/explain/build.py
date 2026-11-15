"""Turn engine results into strategies with the five explanation elements.

Every number that appears in a reason or a benefit is first recorded as an
evidence entry and then quoted from it, so a claim can never drift from its
evidence.
"""

from __future__ import annotations

from fieldshift.contracts import api
from fieldshift.contracts.api import OBJECTIVES, PRIORITY_OBJECTIVES
from fieldshift.diagnostics.site import scope_of
from fieldshift.engine.calendar import Calendar
from fieldshift.engine.evaluate import SiteContext
from fieldshift.engine.run import EngineResult, StrategyResult, baseline_deltas, strategy_metrics
from fieldshift.explain.templates import t

MATERIAL_SCORE = 0.005      # smallest score change worth stating
STRESS_REPORTED = 0.2       # stress probabilities at or above this become evidence
MAX_STRESS_EVIDENCE = 4
PRIORITIES_CITED = 3


class Book:
    """The evidence entries of one strategy, keyed by indicator."""

    def __init__(self, ctx: SiteContext, lang: str):
        self.ctx, self.lang = ctx, lang
        self.items: dict[str, api.Evidence] = {}
        p = ctx.climate.provenance
        self._climate = dict(source=p.source, period=ctx.climate.period, resolution=p.spatial_resolution, scope="climate_cell")
        self._rotation = dict(source=t(lang, "source.rotation"), period=t(lang, "period.none"),
                              resolution=t(lang, "resolution.none"), scope="rotation")
        self._kb = {**self._rotation, "source": t(lang, "source.kb")}

    def add(self, indicator: str, label: str, value: float, unit: str, method: str, digits: int, where: dict) -> float:
        value = round(float(value), digits)
        value = 0.0 if value == 0 else value  # no negative zero
        label = label[:1].upper() + label[1:]
        self.items[indicator] = api.Evidence(indicator=indicator, label=label, value=value, unit=unit, method=method, **where)
        return value

    def climate(self, indicator, label, value, unit_key, method_key, digits=1, **method_params) -> float:
        return self.add(indicator, label, value, t(self.lang, f"unit.{unit_key}"),
                        t(self.lang, f"method.{method_key}", **method_params), digits, self._climate)

    def rotation(self, indicator, label, value, unit_key, method_key="calendar", digits=1) -> float:
        return self.add(indicator, label, value, t(self.lang, f"unit.{unit_key}"), t(self.lang, f"method.{method_key}"),
                        digits, self._rotation)

    def kb(self, indicator, label, value, unit_key, digits=1) -> float:
        return self.add(indicator, label, value, t(self.lang, f"unit.{unit_key}"), t(self.lang, "method.kb"), digits, self._kb)

    def unit(self, indicator, label, value, unit_key, method_key, variable, period, digits=1) -> float:
        source, resolution = self.ctx.sources.get(variable, ("bundle", t(self.lang, "resolution.none")))
        where = dict(source=source, period=period, resolution=resolution, scope=scope_of(self.ctx.tier))
        return self.add(indicator, label, value, t(self.lang, f"unit.{unit_key}"), t(self.lang, f"method.{method_key}"), digits, where)

    def statement(self, code: str, indicator: str | None = None, **params) -> api.Statement:
        """A statement whose number, when it has one, is quoted from the named evidence entry."""
        if indicator is None:
            return api.Statement(code=code, text=t(self.lang, code, **params))
        entry = self.items[indicator]
        return api.Statement(code=code, text=t(self.lang, code, **params), indicator=indicator, value=entry.value, unit=entry.unit)


def _names(ctx: SiteContext, lang: str, crop_ids) -> str:
    return ", ".join(ctx.kb.name(c, lang) for c in crop_ids)


def _slots(calendar: Calendar, ctx: SiteContext, lang: str) -> list[api.Slot]:
    out = []
    for slot in calendar.slots:
        sow_year, sow_doy = calendar.day_ref(slot.start)
        harvest_year, harvest_doy = calendar.day_ref(slot.end - 1)
        out.append(api.Slot(
            crop_id=slot.crop_id, crop_name=ctx.kb.name(slot.crop_id, lang), role=slot.role,
            sow=api.DayRef(year_index=sow_year, doy=sow_doy),
            harvest=api.DayRef(year_index=harvest_year, doy=harvest_doy),
            days=slot.days, clamped=slot.clamped,
        ))
    return out


def _ndvi_period(ctx: SiteContext) -> str | None:
    frame = ctx.series("ndvi")
    if frame is None:
        return None
    years = frame["date"].dt.year
    return f"{int(years.min())}-{int(years.max())}"


def _core_evidence(book: Book, result: StrategyResult, site: api.Site) -> dict[str, float]:
    """Evidence every strategy carries. Returns the rounded values for reuse in statements."""
    ctx, lang, ev = book.ctx, book.lang, result.evaluation
    metrics = strategy_metrics(result)
    values = {
        "overall_score": book.climate("overall_score", t(lang, "ev.overall_score"), result.median, "score", "replay", 3),
        "bare_days_per_year": book.rotation("bare_days_per_year", t(lang, "ev.bare_days_per_year"),
                                            metrics["bare_days_per_year"], "days_per_year", digits=0),
        "water_demand_mm_per_year": book.climate("water_demand_mm_per_year", t(lang, "ev.water_demand_mm_per_year"),
                                                 metrics["water_demand_mm_per_year"], "mm_per_year", "fao56", 0),
        "water_met_share": book.climate("water_met_share", t(lang, "ev.water_met_share"),
                                        metrics["water_met_share"] * 100, "percent", "bucket", 0),
        "erosive_rain_on_bare_mm_per_year": book.climate(
            "erosive_rain_on_bare_mm_per_year", t(lang, "ev.erosive_rain_on_bare_mm_per_year"),
            metrics["erosive_rain_on_bare_mm_per_year"], "mm_per_year", "erosive", 0, threshold=ctx.cfg.erosive_rain_mm),
        "n_kg_ha_per_year": book.kb("n_kg_ha_per_year", t(lang, "ev.n_kg_ha_per_year"), metrics["n_kg_ha_per_year"], "kg_ha_per_year", 0),
        "crop_families": book.kb("crop_families", t(lang, "ev.crop_families"), metrics["crop_families"], "count", 0),
        "cycle_years": book.rotation("cycle_years", t(lang, "ev.cycle_years"), result.calendar.cycle_years, "years", digits=0),
    }

    # The most likely stresses of this strategy's main crops.
    stresses = []
    for s in ev.mains:
        for hazard, occurred in s.events.items():
            probability = float(occurred.mean())
            if probability >= STRESS_REPORTED:
                stage = "mid" if hazard == "drought" else getattr(s.crop.stress, hazard).stage
                stresses.append((probability, s.crop.id, hazard, stage))
    for probability, crop_id, hazard, stage in sorted(stresses, key=lambda x: (-x[0], x[1], x[2]))[:MAX_STRESS_EVIDENCE]:
        label = t(lang, "ev.stress_probability", hazard=t(lang, f"hazard.{hazard}"),
                  crop=ctx.kb.name(crop_id, lang), stage=t(lang, f"stage.{stage}"))
        book.climate(f"stress.{crop_id}.{hazard}", label, probability, "probability", "threshold", 2)

    # Satellite cross-check of bare soil, where a time series exists.
    period = _ndvi_period(ctx)
    if period and site.observed_low_cover:
        days = sum((p.end_doy - p.start_doy + 1) if p.end_doy >= p.start_doy else (365 - p.start_doy + 1 + p.end_doy)
                   for p in site.observed_low_cover)
        book.unit("observed_low_cover_days", t(lang, "ev.observed_low_cover_days"), days, "days_per_year",
                  "ndvi_median", "ndvi", period, digits=0)

    if ctx.soil.awc_status != "assumed":
        book.unit("awc_mm_per_m", t(lang, "ev.awc_mm_per_m"), ctx.soil.awc_mm_per_m, "mm_per_m",
                  f"soil_{ctx.soil.awc_status}", "soil", t(lang, "period.none"), digits=0)

    if ctx.suitability:
        for crop_id in result.introduced:
            if crop_id in ctx.suitability:
                book.unit(f"suitability.{crop_id}", t(lang, "ev.suitability_index", crop=ctx.kb.name(crop_id, lang)),
                          ctx.suitability[crop_id], "index", "suitability", "suitability", t(lang, "period.none"), digits=0)

    for crop_id in result.retains:
        book.rotation(f"return_interval.{crop_id}", t(lang, "ev.return_interval_years", crop=ctx.kb.name(crop_id, lang)),
                      ev.return_gaps[crop_id], "years", digits=0)
    return values


def _trend(site: api.Site, indicator: str) -> api.Trend | None:
    return next((tr for tr in site.trends if tr.indicator == indicator and tr.significant), None)


def _trend_evidence(book: Book, trend: api.Trend) -> str:
    key = f"trend.{trend.indicator}"
    unit = t(book.lang, "unit.per_decade", unit=trend.unit)
    book.add(key, t(book.lang, "ev.trend", label=trend.label), trend.slope_per_decade, unit,
             t(book.lang, "method.theil_sen"), 2,
             dict(source=book._climate["source"], period=trend.period, resolution=book._climate["resolution"], scope="climate_cell"))
    return key


def _baseline_text(book: Book, values: dict[str, float]):
    why = [book.statement("why.baseline_reference")]
    benefits = [
        book.statement("benefit.baseline_known"),
        book.statement("benefit.baseline_metrics", "bare_days_per_year", bare=values["bare_days_per_year"],
                       water=values["water_met_share"], n=values["n_kg_ha_per_year"]),
    ]
    return why, benefits


def _alternative_text(book: Book, alt: StrategyResult, base: StrategyResult, engine: EngineResult,
                      site: api.Site, values: dict[str, float], base_values: dict[str, float]):
    ctx, lang = book.ctx, book.lang
    delta = baseline_deltas(alt, base)

    def objective_change(name: str) -> tuple[str, float]:
        key = f"objective_change.{name}"
        label = t(lang, "ev.objective_change", objective=t(lang, f"objective.{name}"))
        return key, book.climate(key, label, delta["objectives"][name], "score", "difference", 3)

    # ---- Why: what changed, which priorities it serves, which trends it answers ----
    why: list[api.Statement] = []
    for op in alt.ops:
        params = dict(new=ctx.kb.name(op.new, lang), old=ctx.kb.name(op.old, lang) if op.old else "")
        if op.name == "insert_cover":
            key = f"bare_window_days.{op.index}"
            book.rotation(key, t(lang, "ev.bare_window_days", crop=params["old"]), op.days, "days", digits=0)
            why.append(book.statement("why.op.insert_cover", key, days=op.days, **params))
        elif op.name == "extend":
            why.append(book.statement("why.op.extend", "cycle_years", years=alt.calendar.cycle_years, new=params["new"]))
        else:
            why.append(book.statement(f"why.op.{op.name}", **params))

    ranked = sorted((n for n in PRIORITY_OBJECTIVES if engine.weights[n] > 0), key=lambda n: (-engine.weights[n], OBJECTIVES.index(n)))
    for rank, name in enumerate(ranked[:PRIORITIES_CITED], start=1):
        if delta["objectives"][name] > MATERIAL_SCORE:
            key = f"objective.{name}"
            book.climate(key, t(lang, "ev.objective", objective=t(lang, f"objective.{name}")), alt.objective(name), "score", "replay", 3)
            objective_change(name)
            why.append(book.statement("why.priority_improved", key, objective=t(lang, f"objective.{name}"),
                                      rank=rank, base=base.objective(name), alt=alt.objective(name)))

    uses_less_water = delta["water_demand_mm_per_year"] < -1 or delta["objectives"]["water"] > MATERIAL_SCORE
    more_resilient = delta["objectives"]["resilience"] > MATERIAL_SCORE
    water_trend = _trend(site, "water_balance_apr_sep")
    if water_trend and water_trend.slope_per_decade < 0 and uses_less_water and engine.weights["water"] > 0:
        key = _trend_evidence(book, water_trend)
        why.append(book.statement("why.trend_water", key, slope=water_trend.slope_per_decade, period=water_trend.period))
    heat_trend = _trend(site, "hot_days")
    warming = _trend(site, "tmean_apr_sep")
    if heat_trend and heat_trend.slope_per_decade > 0 and more_resilient:
        key = _trend_evidence(book, heat_trend)
        why.append(book.statement("why.trend_heat", key, slope=heat_trend.slope_per_decade, period=heat_trend.period))
    elif warming and warming.slope_per_decade > 0 and more_resilient:
        key = _trend_evidence(book, warming)
        why.append(book.statement("why.trend_warming", key, slope=warming.slope_per_decade, period=warming.period))

    why.append(book.statement("why.best_overall", "overall_score", score=values["overall_score"], base=base_values["overall_score"]))

    # ---- Benefits and trade-offs against the baseline ----
    benefits: list[api.Statement] = []
    tradeoffs: list[api.Statement] = []

    water = book.climate("water_demand_change_mm_per_year", t(lang, "ev.water_demand_change_mm_per_year"),
                         delta["water_demand_mm_per_year"], "mm_per_year", "difference", 0)
    if water <= -1:
        benefits.append(book.statement("benefit.water_saved", "water_demand_change_mm_per_year", value=-water))
    elif water >= 1:
        tradeoffs.append(book.statement("tradeoff.water_demand", "water_demand_change_mm_per_year", value=water))
    met = values["water_met_share"] - base_values["water_met_share"]
    if met >= 1:
        key = "water_met_change"
        book.climate(key, t(lang, "ev.objective_change", objective=t(lang, "objective.water")), met, "percent", "difference", 0)
        benefits.append(book.statement("benefit.water_met", key, value=met))

    if delta["objectives"]["pest_break"] > MATERIAL_SCORE:
        key, change = objective_change("pest_break")
        benefits.append(book.statement("benefit.pest", key, value=change, families=int(values["crop_families"]),
                                       base_families=int(base_values["crop_families"])))

    bare = book.rotation("bare_days_change_per_year", t(lang, "ev.bare_days_change_per_year"),
                         delta["bare_days_per_year"], "days_per_year", "calendar", digits=0)
    if bare <= -1:
        benefits.append(book.statement("benefit.erosion_days", "bare_days_change_per_year", value=-bare))
    rain = book.climate("erosive_rain_change_mm_per_year", t(lang, "ev.erosive_rain_change_mm_per_year"),
                        delta["erosive_rain_on_bare_mm_per_year"], "mm_per_year", "difference", 0)
    if rain <= -1:
        benefits.append(book.statement("benefit.erosion_rain", "erosive_rain_change_mm_per_year", value=-rain))

    nitrogen = book.kb("n_change_kg_ha_per_year", t(lang, "ev.n_change_kg_ha_per_year"), delta["n_kg_ha_per_year"], "kg_ha_per_year", 0)
    if nitrogen >= 1:
        benefits.append(book.statement("benefit.nitrogen", "n_change_kg_ha_per_year", value=nitrogen))
    if delta["objectives"]["organic_matter"] > MATERIAL_SCORE:
        key, change = objective_change("organic_matter")
        benefits.append(book.statement("benefit.soil", key, value=change))
    if more_resilient:
        key, change = objective_change("resilience")
        benefits.append(book.statement("benefit.resilience", key, value=change))

    for name in OBJECTIVES:
        if delta["objectives"][name] < -MATERIAL_SCORE:
            key, change = objective_change(name)
            tradeoffs.append(book.statement("tradeoff.objective", key, objective=t(lang, f"objective.{name}"), value=-change))

    if not benefits:
        benefits.append(book.statement("benefit.none"))
    return why, benefits + tradeoffs


def _gaps(book: Book, result: StrategyResult) -> list[api.Statement]:
    ctx, lang = book.ctx, book.lang
    gaps = [
        book.statement("gap.score_uncertainty", p10=result.p10, p90=result.p90, median=result.median, windows=int(result.overall.size)),
        book.statement("gap.climate_resolution", resolution=ctx.climate.provenance.spatial_resolution),
    ]
    if ctx.tier == "grid":
        gaps.append(book.statement("gap.grid_cell_not_field"))
    elif ctx.tier == "climate_only":
        gaps.append(book.statement("gap.no_satellite_or_soil"))
    if ctx.soil.awc_status == "assumed":
        gaps.append(book.statement("gap.soil_assumed", awc=ctx.soil.awc_mm_per_m))
    elif ctx.soil.derived_or_assumed:
        gaps.append(book.statement("gap.soil_derived"))
    drafts = sorted(c for c in result.spec.crop_ids if ctx.kb.get(c).review_status == "draft")
    if drafts:
        gaps.append(book.statement("gap.draft_crop", crops=_names(ctx, lang, drafts)))
    if ctx.suitability is None:
        gaps.append(book.statement("gap.no_suitability"))
    if any(ctx.kb.get(c).season == "winter" for c in result.spec.mains):
        gaps.append(book.statement("gap.winterkill_no_snow"))
    gaps.append(book.statement("gap.income_relative"))
    return gaps


def _local_review(book: Book, result: StrategyResult) -> list[api.Statement]:
    ctx, lang = book.ctx, book.lang
    review = [book.statement("review.supports_not_replaces"), book.statement("review.unseen_conditions")]
    new_mains = [c for c in result.introduced if ctx.kb.get(c).role != "cover"]
    new_covers = [c for c in result.introduced if ctx.kb.get(c).role == "cover"]
    if new_mains:
        review.append(book.statement("review.new_crop", crops=_names(ctx, lang, new_mains)))
    if new_covers:
        review.append(book.statement("review.cover_crop", crops=_names(ctx, lang, new_covers)))
    winter = sorted({c for c in result.spec.mains if ctx.kb.get(c).season == "winter"})
    if winter:
        review.append(book.statement("review.winter_crop", crops=_names(ctx, lang, winter)))
    for crop_id in result.retains:
        review.append(book.statement(
            "review.return_interval", f"return_interval.{crop_id}", crop=ctx.kb.name(crop_id, lang),
            actual=result.evaluation.return_gaps[crop_id], recommended=ctx.kb.get(crop_id).min_return_years,
        ))
    if new_mains:
        review.append(book.statement("review.market"))
    return review


def build_strategies(engine: EngineResult, ctx: SiteContext, site: api.Site, lang: str = "en") -> list[api.Strategy]:
    """API strategies, baseline first, each with its five explanation elements."""
    base = engine.baseline
    base_book = Book(ctx, lang)
    base_values = _core_evidence(base_book, base, site)
    out = []
    for result in engine.strategies:
        book = base_book if result.is_baseline else Book(ctx, lang)
        values = base_values if result.is_baseline else _core_evidence(book, result, site)
        if result.is_baseline:
            why, benefits = _baseline_text(book, values)
            vs_baseline = None
        else:
            why, benefits = _alternative_text(book, result, base, engine, site, values, base_values)
            delta = baseline_deltas(result, base)
            vs_baseline = api.VsBaseline(
                objectives={name: round(delta["objectives"][name], 3) for name in OBJECTIVES},
                water_demand_mm_per_year=round(delta["water_demand_mm_per_year"], 0),
                bare_days_per_year=round(delta["bare_days_per_year"], 0),
                n_kg_ha_per_year=round(delta["n_kg_ha_per_year"], 0),
            )
        gaps = _gaps(book, result)
        review = _local_review(book, result)
        metrics = strategy_metrics(result)
        out.append(api.Strategy(
            id=result.id,
            label=t(lang, f"label.{result.label_key}"),
            is_baseline=result.is_baseline,
            operators=[op.name for op in result.ops],
            cycle_years=result.calendar.cycle_years,
            slots=_slots(result.calendar, ctx, lang),
            scores=api.Scores(
                overall=api.ScoreSummary(median=round(result.median, 3), p10=round(result.p10, 3),
                                         p90=round(result.p90, 3), windows=int(result.overall.size)),
                objectives={name: round(result.objective(name), 3) for name in OBJECTIVES},
            ),
            metrics=api.Metrics(
                water_demand_mm_per_year=round(metrics["water_demand_mm_per_year"], 0),
                water_met_share=round(metrics["water_met_share"], 3),
                bare_days_per_year=round(metrics["bare_days_per_year"], 0),
                n_kg_ha_per_year=round(metrics["n_kg_ha_per_year"], 0),
                erosive_rain_on_bare_mm_per_year=round(metrics["erosive_rain_on_bare_mm_per_year"], 0),
                crop_families=int(metrics["crop_families"]),
            ),
            vs_baseline=vs_baseline,
            confidence=result.confidence,
            retains_return_violation=result.retains,
            why=why,
            evidence=list(book.items.values()),
            benefits=benefits,
            gaps=gaps,
            local_review=review,
        ))
    return out


def render_notices(notices: list[tuple[str, dict]], ctx: SiteContext, lang: str) -> list[api.Notice]:
    """Engine and request notices as localized text."""
    out = []
    for code, params in notices:
        params = dict(params)
        for key in ("crop", "prev", "cover", "main"):
            if key in params and params[key] in ctx.kb:
                params[key] = ctx.kb.name(params[key], lang)
        if "crops" in params:
            params["crops"] = _names(ctx, lang, params["crops"])
        if "reasons" in params:
            params["reasons"] = ", ".join(t(lang, f"reason.{r}") for r in params["reasons"]) or "-"
        out.append(api.Notice(code=f"notice.{code}", text=t(lang, f"notice.{code}", **params)))
    return out
