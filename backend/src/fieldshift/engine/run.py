"""The rotation engine: baseline, candidates, constraints, scores, selection."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from fieldshift.contracts.api import OBJECTIVES, PRIORITY_OBJECTIVES, Constraints, Priorities
from fieldshift.engine.calendar import Calendar, SequenceSpec, build_calendar
from fieldshift.engine.candidates import Candidate, OpRecord, generate_pairs, generate_singles
from fieldshift.engine.constraints import check, retained_violations
from fieldshift.engine.evaluate import Evaluation, SiteContext, evaluate

LEVELS = ("high", "medium", "low")
LABEL_MIN_GAIN = 0.01


@dataclass
class StrategyResult:
    id: str
    spec: SequenceSpec
    calendar: Calendar
    evaluation: Evaluation
    ops: list[OpRecord]
    is_baseline: bool
    overall: np.ndarray       # overall score per replay window
    retains: list[str]        # crops kept below their return interval
    introduced: list[str]     # crops absent from the baseline
    label_key: str = "balanced"
    confidence: str = "low"

    @property
    def median(self) -> float:
        return float(np.median(self.overall))

    @property
    def p10(self) -> float:
        return float(np.percentile(self.overall, 10))

    @property
    def p90(self) -> float:
        return float(np.percentile(self.overall, 90))

    def objective(self, name: str) -> float:
        return self.evaluation.median(name)


@dataclass
class EngineResult:
    baseline: StrategyResult
    alternatives: list[StrategyResult]
    weights: dict[str, float]
    notices: list[tuple[str, dict]] = field(default_factory=list)
    eliminated: dict[str, int] = field(default_factory=dict)
    candidates_generated: int = 0
    candidates_feasible: int = 0

    @property
    def strategies(self) -> list[StrategyResult]:
        return [self.baseline] + self.alternatives


def strategy_metrics(result: StrategyResult) -> dict[str, float]:
    """Physical quantities of a strategy; medians across replay windows where weather-dependent."""
    ev = result.evaluation
    return {
        "water_demand_mm_per_year": float(np.median(ev.water_demand)),
        "water_met_share": float(np.median(ev.water_met)),
        "bare_days_per_year": float(ev.bare_days_per_year),
        "n_kg_ha_per_year": float(ev.n_per_year),
        "erosive_rain_on_bare_mm_per_year": float(np.median(ev.erosive_bare)),
        "crop_families": float(ev.families),
    }


def baseline_deltas(alternative: StrategyResult, baseline: StrategyResult) -> dict:
    """Differences from the baseline: per objective, and in physical units."""
    alt, base = strategy_metrics(alternative), strategy_metrics(baseline)
    return {
        "objectives": {name: alternative.objective(name) - baseline.objective(name) for name in OBJECTIVES},
        **{key: alt[key] - base[key] for key in alt},
    }


def priority_weights(priorities: Priorities) -> tuple[dict[str, float], bool]:
    """Normalized weights of the six farmer priorities, and whether equal weights were substituted."""
    raw = {name: float(getattr(priorities, name)) for name in PRIORITY_OBJECTIVES}
    total = sum(raw.values())
    if total <= 0:
        return {name: 1 / len(raw) for name in raw}, True
    return {name: value / total for name, value in raw.items()}, False


def overall_score(ev: Evaluation, weights: dict[str, float], ctx: SiteContext) -> np.ndarray:
    """Priority-weighted score per replay window, with a fixed share for resilience and pest break."""
    w = ctx.cfg.weights
    weighted = sum(weights[name] * ev.objectives[name] for name in PRIORITY_OBJECTIVES)
    return w.priorities_share * weighted + w.resilience_share * ev.objectives["resilience"] + w.pest_break_share * ev.objectives["pest_break"]


def confidence_level(result: StrategyResult, ctx: SiteContext) -> str:
    level = {"field": 0, "grid": 1}.get(ctx.tier, 2)
    if result.p90 - result.p10 > ctx.cfg.confidence_interval_width:
        level += 1
    uses_draft = any(ctx.kb.get(c).review_status == "draft" for c in result.spec.crop_ids)
    if uses_draft or ctx.soil.derived_or_assumed >= 2:
        level += 1
    return LEVELS[min(level, 2)]


def _label_keys(baseline: StrategyResult, alternatives: list[StrategyResult]) -> None:
    """Label each alternative by the objective it improves most, avoiding repeats where possible."""
    used: set[str] = set()
    for alt in alternatives:
        gains = sorted(((alt.objective(n) - baseline.objective(n), n) for n in OBJECTIVES), key=lambda g: (-g[0], g[1]))
        improved = [name for gain, name in gains if gain > LABEL_MIN_GAIN]
        choice = next((name for name in improved if name not in used), improved[0] if improved else "balanced")
        alt.label_key = choice
        used.add(choice)


def _select(feasible: list[StrategyResult], count: int) -> list[StrategyResult]:
    """Best alternatives first, preferring ones produced by different operators."""
    ranked = sorted(feasible, key=lambda r: (-r.median, r.spec.mains, r.spec.covers))
    chosen: list[StrategyResult] = []
    signatures: set[tuple[str, ...]] = set()
    for result in ranked:
        signature = tuple(sorted(op.name for op in result.ops))
        if signature in signatures:
            continue
        chosen.append(result)
        signatures.add(signature)
        if len(chosen) == count:
            return chosen
    taken = {id(result) for result in chosen}
    for result in ranked:
        if len(chosen) == count:
            break
        if id(result) not in taken:
            chosen.append(result)
    return chosen


def run_engine(ctx: SiteContext, baseline_spec: SequenceSpec, priorities: Priorities, constraints: Constraints) -> EngineResult:
    cfg = ctx.cfg
    notices: list[tuple[str, dict]] = []
    weights, equal = priority_weights(priorities)
    if equal:
        notices.append(("equal_weights", {}))

    # --- Baseline: never rejected ---
    base_calendar = build_calendar(baseline_spec, ctx.kb, cfg, strict=False)
    notices += base_calendar.notices
    base_eval = evaluate([base_calendar], ctx)[0]
    max_cycle = constraints.max_cycle_years
    if base_calendar.cycle_years > max_cycle:
        max_cycle = base_calendar.cycle_years
        notices.append(("max_cycle_raised", {"years": max_cycle}))
    kept_excluded = sorted(set(constraints.excluded_crops) & baseline_spec.crop_ids)
    if kept_excluded:
        notices.append(("baseline_excluded_crop", {"crops": kept_excluded}))
    # The baseline as it could actually be placed: cover crops that did not fit are left out.
    effective_spec = SequenceSpec.of(baseline_spec.mains, [(s.index, s.crop_id) for s in base_calendar.covers])

    baseline = StrategyResult(
        id="s0", spec=effective_spec, calendar=base_calendar, evaluation=base_eval, ops=[], is_baseline=True,
        overall=overall_score(base_eval, weights, ctx), retains=retained_violations(base_calendar, ctx),
        introduced=[], label_key="baseline",
    )
    baseline.confidence = confidence_level(baseline, ctx)

    eliminated: dict[str, int] = {}
    generated = 0

    def assess(candidates: list[Candidate]) -> list[StrategyResult]:
        nonlocal generated
        generated += len(candidates)
        feasible: list[Candidate] = []
        for candidate in candidates:
            candidate.calendar = build_calendar(candidate.spec, ctx.kb, cfg, strict=True)
            verdict = check(candidate.calendar, base_calendar, ctx, constraints, max_cycle)
            if verdict.ok:
                candidate.retains = verdict.retains
                feasible.append(candidate)
            else:
                eliminated[verdict.reason] = eliminated.get(verdict.reason, 0) + 1
        evaluations = evaluate([c.calendar for c in feasible], ctx) if feasible else []
        results = []
        for candidate, ev in zip(feasible, evaluations):
            candidate.evaluation = ev
            results.append(StrategyResult(
                id="", spec=candidate.spec, calendar=candidate.calendar, evaluation=ev, ops=candidate.ops,
                is_baseline=False, overall=overall_score(ev, weights, ctx), retains=candidate.retains,
                introduced=sorted(candidate.spec.crop_ids - effective_spec.crop_ids),
            ))
        return results

    # --- Single operators, then pairs of the best ones ---
    singles = generate_singles(effective_spec, base_eval, ctx, max_cycle)[: cfg.max_candidates]
    single_results = assess(singles)
    ranked_singles = sorted(single_results, key=lambda r: (-r.median, r.spec.mains, r.spec.covers))
    ranked_candidates = [Candidate(r.spec, r.ops, r.calendar, r.evaluation, r.retains) for r in ranked_singles]
    pairs = generate_pairs(effective_spec, ranked_candidates, limit=max(cfg.max_candidates - len(singles), 0))
    feasible = single_results + assess(pairs)

    alternatives = _select(feasible, cfg.alternatives_returned)
    for i, alt in enumerate(alternatives, start=1):
        alt.id = f"s{i}"
        alt.confidence = confidence_level(alt, ctx)
    _label_keys(baseline, alternatives)

    if len(alternatives) < 2:
        reasons = [reason for reason, _ in sorted(eliminated.items(), key=lambda kv: (-kv[1], kv[0]))]
        notices.append(("few_alternatives", {"count": len(alternatives), "reasons": reasons}))

    return EngineResult(
        baseline=baseline, alternatives=alternatives, weights=weights, notices=notices,
        eliminated=eliminated, candidates_generated=generated, candidates_feasible=len(feasible),
    )
