"""Candidate rotations derived from the baseline by named operators."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from fieldshift.engine.calendar import Calendar, SequenceSpec
from fieldshift.engine.evaluate import Evaluation, SiteContext

OPERATORS = ("insert_cover", "swap_drought_tolerant", "add_legume", "diversify", "extend")
REPLACE_OPERATORS = ("swap_drought_tolerant", "add_legume", "diversify")


@dataclass(frozen=True)
class OpRecord:
    """One operator application, with what it changed, for the explanation."""

    name: str
    index: int            # position of the main crop replaced or followed
    old: str | None       # crop replaced, or the main crop a cover crop follows
    new: str              # crop introduced
    days: int = 0         # length of the bare window filled (insert_cover)
    years: int = 0        # resulting cycle length (extend)


@dataclass
class Candidate:
    spec: SequenceSpec
    ops: list[OpRecord]
    calendar: Calendar | None = None
    evaluation: Evaluation | None = None
    retains: list[str] = field(default_factory=list)

    @property
    def signature(self) -> tuple[str, ...]:
        return tuple(sorted(op.name for op in self.ops))


def _replace(spec: SequenceSpec, index: int, crop_id: str) -> SequenceSpec:
    mains = list(spec.mains)
    mains[index] = crop_id
    return SequenceSpec.of(mains, spec.covers)


def _main_crops(ctx: SiteContext) -> list:
    return ctx.kb.by_role("cash", "forage")


def insert_cover(spec: SequenceSpec, baseline: Evaluation, ctx: SiteContext) -> list[Candidate]:
    out = []
    occupied = spec.cover_map
    for gap in baseline.calendar.gaps(min_days=ctx.cfg.min_bare_window_days):
        if gap.after.role != "main" or gap.after.index in occupied:
            continue
        for cover in ctx.kb.by_role("cover"):
            new_spec = SequenceSpec.of(spec.mains, list(spec.covers) + [(gap.after.index, cover.id)])
            out.append(Candidate(new_spec, [OpRecord("insert_cover", gap.after.index, gap.after.crop_id, cover.id, days=gap.days)]))
    return out


def swap_drought_tolerant(spec: SequenceSpec, baseline: Evaluation, ctx: SiteContext) -> list[Candidate]:
    out = []
    mains = baseline.mains
    order = sorted(range(len(mains)), key=lambda i: -float(np.median(mains[i].deficit_ratio)))
    for i in order[:2]:
        target = mains[i]
        if float(np.median(target.deficit_ratio)) < 0.03:
            continue
        better = [c for c in _main_crops(ctx)
                  if c.season == target.crop.season and c.id not in spec.mains
                  and c.drought_tolerance >= target.crop.drought_tolerance + 0.1]
        better.sort(key=lambda c: (-c.drought_tolerance, c.id))
        for crop in better[:3]:
            out.append(Candidate(_replace(spec, target.slot.index, crop.id),
                                 [OpRecord("swap_drought_tolerant", target.slot.index, target.crop.id, crop.id)]))
    return out


def add_legume(spec: SequenceSpec, baseline: Evaluation, ctx: SiteContext) -> list[Candidate]:
    out = []
    legumes = sorted((c for c in _main_crops(ctx) if c.is_legume and c.id not in spec.mains), key=lambda c: c.id)
    targets = [s for s in baseline.mains if not s.crop.is_legume]
    targets.sort(key=lambda s: (s.crop.market_value, s.slot.index))
    for target in targets[:2]:
        for legume in legumes:
            out.append(Candidate(_replace(spec, target.slot.index, legume.id),
                                 [OpRecord("add_legume", target.slot.index, target.crop.id, legume.id)]))
    return out


def diversify(spec: SequenceSpec, baseline: Evaluation, ctx: SiteContext) -> list[Candidate]:
    out = []
    families = [s.crop.family for s in baseline.mains]
    present = set(families)
    targets = [s for s in baseline.mains
               if families.count(s.crop.family) > 1 or baseline.return_gaps[s.crop.id] < s.crop.min_return_years]
    targets.sort(key=lambda s: (s.crop.market_value, s.slot.index))
    for target in targets[:2]:
        fresh = [c for c in _main_crops(ctx) if c.family not in present and c.id not in spec.mains]
        fresh.sort(key=lambda c: (c.season != target.crop.season, -c.market_value, c.id))
        for crop in fresh[:3]:
            out.append(Candidate(_replace(spec, target.slot.index, crop.id),
                                 [OpRecord("diversify", target.slot.index, target.crop.id, crop.id)]))
    return out


def extend(spec: SequenceSpec, baseline: Evaluation, ctx: SiteContext, max_cycle_years: int) -> list[Candidate]:
    if baseline.calendar.cycle_years + 1 > max_cycle_years:
        return []
    present = {s.crop.family for s in baseline.mains}
    fresh = [c for c in _main_crops(ctx) if c.id not in spec.mains]
    fresh.sort(key=lambda c: (c.family in present, -c.market_value, c.id))
    out = []
    for crop in fresh[:6]:
        new_spec = SequenceSpec.of(list(spec.mains) + [crop.id], spec.covers)
        out.append(Candidate(new_spec, [OpRecord("extend", len(spec.mains), None, crop.id,
                                                  years=baseline.calendar.cycle_years + 1)]))
    return out


def generate_singles(spec: SequenceSpec, baseline: Evaluation, ctx: SiteContext, max_cycle_years: int) -> list[Candidate]:
    """Every single-operator candidate, deduplicated, in a stable order."""
    candidates = (
        insert_cover(spec, baseline, ctx)
        + swap_drought_tolerant(spec, baseline, ctx)
        + add_legume(spec, baseline, ctx)
        + diversify(spec, baseline, ctx)
        + extend(spec, baseline, ctx, max_cycle_years)
    )
    return dedupe(candidates, exclude={spec})


def generate_pairs(baseline_spec: SequenceSpec, ranked: list[Candidate], limit: int) -> list[Candidate]:
    """Combine the best single-operator candidates two at a time.

    `ranked` holds feasible single-operator candidates, best first. A change to
    the main crops is paired with a cover crop, and two replacements at
    different positions are paired with each other.
    """
    covers = [c for c in ranked if c.ops[0].name == "insert_cover"][:4]
    main_changes = [c for c in ranked if c.ops[0].name != "insert_cover"][:6]
    replacements = [c for c in ranked if c.ops[0].name in REPLACE_OPERATORS][:5]
    out: list[Candidate] = []

    for change in main_changes:
        for cover in covers:
            op = cover.ops[0]
            if op.index >= len(change.spec.mains) or change.spec.mains[op.index] != op.old:
                continue  # the cover crop's host crop was replaced
            spec = SequenceSpec.of(change.spec.mains, list(change.spec.covers) + [(op.index, op.new)])
            out.append(Candidate(spec, change.ops + [op]))

    for i, first in enumerate(replacements):
        for second in replacements[i + 1:]:
            a, b = first.ops[0], second.ops[0]
            if a.index == b.index or a.new == b.new:
                continue
            mains = list(baseline_spec.mains)
            mains[a.index], mains[b.index] = a.new, b.new
            out.append(Candidate(SequenceSpec.of(mains, baseline_spec.covers), [a, b]))

    return dedupe(out, exclude={baseline_spec} | {c.spec for c in ranked})[:limit]


def dedupe(candidates: list[Candidate], exclude: set[SequenceSpec]) -> list[Candidate]:
    seen = set(exclude)
    out = []
    for candidate in candidates:
        if candidate.spec in seen:
            continue
        seen.add(candidate.spec)
        out.append(candidate)
    return out
