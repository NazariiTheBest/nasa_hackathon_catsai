"""Hard agronomic and user constraints on alternative rotations."""

from __future__ import annotations

from dataclasses import dataclass, field

from fieldshift.contracts.api import Constraints
from fieldshift.engine.calendar import Calendar
from fieldshift.engine.evaluate import SiteContext, crop_return_gaps, family_return_gaps

REASONS = ("calendar", "max_cycle_years", "excluded_crops", "irrigation", "heat_units", "suitability", "return_interval")


@dataclass
class Verdict:
    ok: bool
    reason: str | None = None
    detail: str = ""
    retains: list[str] = field(default_factory=list)  # baseline crops kept below their return interval


def retained_violations(calendar: Calendar, ctx: SiteContext) -> list[str]:
    """Main crops that return sooner than their minimum interval."""
    gaps = crop_return_gaps(calendar)
    return sorted(c for c, gap in gaps.items() if gap < ctx.kb.get(c).min_return_years)


def check(calendar: Calendar | None, baseline: Calendar, ctx: SiteContext, constraints: Constraints,
          max_cycle_years: int) -> Verdict:
    """Whether an alternative may be offered.

    Rules on what an alternative *adds* are hard. A return-interval violation
    the baseline already has may be kept, never worsened, and is reported.
    """
    kb, cfg = ctx.kb, ctx.cfg
    if calendar is None:
        return Verdict(False, "calendar", "a crop does not fit the sowing windows")
    if calendar.cycle_years > max_cycle_years:
        return Verdict(False, "max_cycle_years", f"{calendar.cycle_years} years")

    introduced = calendar.spec.crop_ids - baseline.spec.crop_ids
    excluded = set(constraints.excluded_crops)
    for crop_id in sorted(introduced):
        crop = kb.get(crop_id)
        if crop_id in excluded:
            return Verdict(False, "excluded_crops", crop_id)
        if crop.irrigation_required and not constraints.irrigation_available:
            return Verdict(False, "irrigation", crop_id)
        if crop.role != "cover" and ctx.heat_units_share(crop_id) < cfg.heat_units_min_share:
            return Verdict(False, "heat_units", crop_id)
        if ctx.suitability is not None and crop_id in ctx.suitability and ctx.suitability[crop_id] < cfg.suitability_floor:
            return Verdict(False, "suitability", crop_id)

    retains: list[str] = []
    base_gaps = crop_return_gaps(baseline)
    for crop_id, gap in crop_return_gaps(calendar).items():
        required = kb.get(crop_id).min_return_years
        if gap >= required:
            continue
        if crop_id in base_gaps and gap >= base_gaps[crop_id]:
            retains.append(crop_id)  # inherited from the baseline, not made worse
        else:
            return Verdict(False, "return_interval", crop_id)

    base_family = family_return_gaps(baseline, kb)
    for family, gap in family_return_gaps(calendar, kb).items():
        if gap >= cfg.family_interval(family):
            continue
        if family in base_family and gap >= base_family[family]:
            continue
        return Verdict(False, "return_interval", family)

    return Verdict(True, retains=sorted(retains))
