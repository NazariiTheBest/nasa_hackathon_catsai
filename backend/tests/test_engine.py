import time

import numpy as np
import pytest

from fieldshift.climate.power import PowerClient
from fieldshift.contracts.api import OBJECTIVES, Constraints, Priorities
from fieldshift.diagnostics.site import build_context
from fieldshift.engine.calendar import SequenceSpec, build_calendar
from fieldshift.engine.candidates import OPERATORS, generate_singles
from fieldshift.engine.constraints import check
from fieldshift.engine.evaluate import crop_return_gaps, evaluate, min_cyclic_gap
from fieldshift.engine.run import priority_weights, run_engine
from fieldshift.ingest.registry import BundleRegistry

from .helpers import FakePower, kb_variant, make_climate, make_context

WHEAT_SUNFLOWER = SequenceSpec.of(["winter_wheat", "sunflower"])
THREE_CROPS = SequenceSpec.of(["winter_wheat", "sunflower", "spring_barley"])


@pytest.fixture(scope="module")
def ctx(kb, cfg, climate40):
    return make_context(climate40, kb, cfg)


def _run(ctx, spec=WHEAT_SUNFLOWER, priorities=None, **constraints):
    return run_engine(ctx, spec, priorities or Priorities(), Constraints(**constraints))


def _calendar(ctx, mains, covers=(), strict=True):
    return build_calendar(SequenceSpec.of(mains, covers), ctx.kb, ctx.cfg, strict=strict)


def _check(ctx, mains, covers=(), baseline=WHEAT_SUNFLOWER, max_cycle=5, **constraints):
    base = build_calendar(baseline, ctx.kb, ctx.cfg, strict=False)
    return check(_calendar(ctx, mains, covers), base, ctx, Constraints(**constraints), max_cycle)


# ----------------------------------------------------------------- Operators

def test_cover_crop_fills_a_long_bare_window(ctx):
    base = evaluate([build_calendar(WHEAT_SUNFLOWER, ctx.kb, ctx.cfg, strict=False)], ctx)[0]
    singles = generate_singles(WHEAT_SUNFLOWER, base, ctx, max_cycle_years=5)
    covers = [c for c in singles if c.ops[0].name == "insert_cover"]
    assert covers, "a qualifying bare window must produce cover-crop candidates"
    assert all(c.ops[0].old == "winter_wheat" and c.ops[0].days >= ctx.cfg.min_bare_window_days for c in covers)
    placed = [build_calendar(c.spec, ctx.kb, ctx.cfg) for c in covers]
    assert any(cal is not None and cal.covers for cal in placed)
    assert {c.ops[0].name for c in singles} >= {"insert_cover", "add_legume", "extend"}


def test_operators_are_recorded_on_every_alternative(ctx):
    result = _run(ctx)
    assert result.baseline.ops == []
    for alt in result.alternatives:
        assert alt.ops and all(op.name in OPERATORS for op in alt.ops)
        assert alt.spec != result.baseline.spec


def test_candidate_cap_holds(kb, climate40, cfg):
    small = cfg.model_copy(update={"max_candidates": 12})
    result = _run(make_context(climate40, kb, small))
    assert 0 < result.candidates_generated <= 12


# --------------------------------------------------------------- Constraints

def test_min_cyclic_gap():
    assert min_cyclic_gap([0], 3) == 3
    assert min_cyclic_gap([0, 1], 4) == 1
    assert min_cyclic_gap([0, 2], 4) == 2
    assert min_cyclic_gap([1, 3], 4) == 2


def test_introduced_crop_respects_its_return_interval(ctx):
    base = SequenceSpec.of(["winter_wheat", "maize", "spring_barley"])
    # peas need 4 years between crops; once in a 3-year cycle is every 3 years
    verdict = _check(ctx, ["winter_wheat", "maize", "peas"], baseline=base)
    assert not verdict.ok and verdict.reason == "return_interval" and verdict.detail == "peas"
    # in a 4-year cycle the same crop is acceptable
    assert _check(ctx, ["winter_wheat", "maize", "spring_barley", "peas"], baseline=base).ok

    for alt in _run(ctx, base).alternatives:
        gaps = crop_return_gaps(alt.calendar)
        for crop_id in alt.introduced:
            crop = ctx.kb.get(crop_id)
            if crop.role != "cover":
                assert gaps[crop_id] >= crop.min_return_years, (crop_id, gaps)


def test_baseline_frequency_is_kept_but_never_increased(ctx):
    kept = _check(ctx, ["winter_wheat", "sunflower"], covers=[(0, "white_mustard")])
    assert kept.ok and kept.retains == ["sunflower"]

    worse = _check(ctx, ["sunflower"])  # every year instead of every second year
    assert not worse.ok and worse.reason == "return_interval"

    result = _run(ctx)
    assert result.baseline.retains == ["sunflower"]
    for alt in result.alternatives:
        gap = crop_return_gaps(alt.calendar).get("sunflower")
        if gap is not None:
            assert gap >= 2
            assert ("sunflower" in alt.retains) == (gap < ctx.kb.get("sunflower").min_return_years)


def test_family_repeat_is_not_introduced(ctx):
    base = SequenceSpec.of(["winter_wheat", "sunflower", "maize"])
    # chickpea directly after soybean would put two legumes in consecutive years
    verdict = _check(ctx, ["soybean", "chickpea", "maize", "winter_wheat"], baseline=base)
    assert not verdict.ok and verdict.reason == "return_interval" and verdict.detail == "fabaceae"


def test_excluded_crop_never_appears(ctx):
    assert _check(ctx, ["winter_wheat", "soybean"], excluded_crops=["soybean"]).reason == "excluded_crops"
    banned = ["soybean", "peas", "chickpea"]
    result = _run(ctx, excluded_crops=banned)
    for alt in result.alternatives:
        assert not set(banned) & alt.spec.crop_ids
    assert result.eliminated.get("excluded_crops", 0) > 0


def test_irrigation_dependent_crop_needs_irrigation(cfg, climate40):
    thirsty = kb_variant("soybean", lambda r: r.update(irrigation_required=True))
    ctx = make_context(climate40, thirsty, cfg)
    base = SequenceSpec.of(["winter_wheat", "maize", "spring_barley"])
    spec = ["winter_wheat", "maize", "soybean"]
    assert _check(ctx, spec, baseline=base, irrigation_available=False).reason == "irrigation"
    assert _check(ctx, spec, baseline=base, irrigation_available=True).ok
    for alt in _run(ctx, base, irrigation_available=False).alternatives:
        assert "soybean" not in alt.introduced


def test_heat_units_and_cycle_length(kb, cfg):
    cold = make_context(make_climate(1985, 40, seed=7, t_mean=5.0, t_amp=11.0), kb, cfg)
    assert cold.heat_units_share("maize") < 0.8
    base = SequenceSpec.of(["winter_wheat", "spring_barley"])
    assert _check(cold, ["winter_wheat", "maize"], baseline=base).reason == "heat_units"

    warm = make_context(make_climate(1985, 40, seed=7), kb, cfg)
    assert warm.heat_units_share("maize") >= 0.8
    long = ["winter_wheat", "maize", "spring_barley", "soybean"]
    assert _check(warm, long, baseline=base, max_cycle=3).reason == "max_cycle_years"
    assert _check(warm, long, baseline=base, max_cycle=4).ok


def test_suitability_screening(kb, cfg, climate40):
    base = SequenceSpec.of(["winter_wheat", "maize", "spring_barley"])
    spec = ["winter_wheat", "sorghum", "spring_barley"]

    screened = make_context(climate40, kb, cfg, suitability={"sorghum": 10.0, "millet": 80.0})
    assert _check(screened, spec, baseline=base).reason == "suitability"
    assert _check(screened, ["winter_wheat", "millet", "spring_barley"], baseline=base).ok
    for alt in _run(screened, base).alternatives:
        assert "sorghum" not in alt.introduced

    unscreened = make_context(climate40, kb, cfg, suitability=None)
    assert _check(unscreened, spec, baseline=base).ok


# ---------------------------------------------------------------- Objectives

def test_scores_are_reproducible(ctx):
    first, second = _run(ctx, THREE_CROPS), _run(ctx, THREE_CROPS)
    assert [s.spec for s in first.strategies] == [s.spec for s in second.strategies]
    for a, b in zip(first.strategies, second.strategies):
        np.testing.assert_array_equal(a.overall, b.overall)
        for name in OBJECTIVES:
            np.testing.assert_array_equal(a.evaluation.objectives[name], b.evaluation.objectives[name])
            assert 0 <= a.objective(name) <= 1


def test_legume_raises_the_nitrogen_score(ctx):
    base, legume = evaluate([_calendar(ctx, ["winter_wheat", "maize", "spring_barley"], strict=False),
                             _calendar(ctx, ["winter_wheat", "soybean", "spring_barley"])], ctx)
    assert legume.median("nitrogen") > base.median("nitrogen")
    assert base.n_per_year == 0 and legume.n_per_year == pytest.approx(20.0)


def test_cover_crop_does_not_lower_the_erosion_score(ctx):
    for cover in ("white_mustard", "winter_rye", "hairy_vetch", "phacelia", "oilseed_radish"):
        base, covered = evaluate([_calendar(ctx, ["winter_wheat", "sunflower"]),
                                  _calendar(ctx, ["winter_wheat", "sunflower"], covers=[(0, cover)])], ctx)
        assert (covered.objectives["erosion"] >= base.objectives["erosion"] - 1e-12).all(), cover
        assert covered.bare_days_per_year < base.bare_days_per_year
        assert covered.median("organic_matter") > base.median("organic_matter")


def test_cover_crop_water_use_is_counted(ctx):
    base, covered = evaluate([_calendar(ctx, ["winter_wheat", "sunflower"]),
                              _calendar(ctx, ["winter_wheat", "sunflower"], covers=[(0, "winter_rye")])], ctx)
    cover = covered.covers[0]
    years = covered.calendar.cycle_years
    np.testing.assert_allclose(covered.water_demand - base.water_demand, cover.demand / years, rtol=1e-4)
    assert np.median(covered.water_demand) > np.median(base.water_demand)
    # the cover crop draws down soil water, so the following crop is not better supplied
    after = next(s for s in covered.mains if s.crop.id == "sunflower")
    before = next(s for s in base.mains if s.crop.id == "sunflower")
    assert np.median(after.actual) <= np.median(before.actual) + 1e-6


def test_drought_tolerant_crop_meets_more_of_its_demand(kb, cfg, climate40):
    dry = climate40.copy()
    dry["precip"] = dry["precip"] * 0.55
    ctx = make_context(dry, kb, cfg)
    maize, sorghum = evaluate([_calendar(ctx, ["winter_wheat", "maize"]), _calendar(ctx, ["winter_wheat", "sorghum"])], ctx)
    maize_slot = next(s for s in maize.mains if s.crop.id == "maize")
    sorghum_slot = next(s for s in sorghum.mains if s.crop.id == "sorghum")
    # lower crop coefficient: less water demanded, and a smaller share of it unmet
    assert np.median(sorghum_slot.demand) < np.median(maize_slot.demand)
    assert np.median(sorghum_slot.deficit_ratio) <= np.median(maize_slot.deficit_ratio) + 1e-9
    assert np.median(maize_slot.deficit_ratio) > 0.05, "the dry climate must actually stress maize"

    base = evaluate([build_calendar(SequenceSpec.of(["winter_wheat", "maize"]), kb, cfg, strict=False)], ctx)[0]
    swaps = [c for c in generate_singles(SequenceSpec.of(["winter_wheat", "maize"]), base, ctx, 5)
             if c.ops[0].name == "swap_drought_tolerant"]
    assert swaps and all(ctx.kb.get(c.ops[0].new).drought_tolerance > ctx.kb.get(c.ops[0].old).drought_tolerance for c in swaps)
    assert "sorghum" in {c.ops[0].new for c in swaps}


# ------------------------------------------------------ Overall score, replay

def test_priorities_change_only_the_overall_score(ctx):
    water_first = _run(ctx, THREE_CROPS, Priorities(water=1, nitrogen=0, erosion=0, organic_matter=0, forage=0, income=0))
    income_first = _run(ctx, THREE_CROPS, Priorities(water=0, nitrogen=0, erosion=0, organic_matter=0, forage=0, income=1))
    a, b = water_first.baseline, income_first.baseline
    for name in OBJECTIVES:
        np.testing.assert_array_equal(a.evaluation.objectives[name], b.evaluation.objectives[name])
    assert a.median != b.median
    share = ctx.cfg.weights
    expected = share.priorities_share * a.evaluation.objectives["water"] + share.resilience_share * a.evaluation.objectives[
        "resilience"] + share.pest_break_share * a.evaluation.objectives["pest_break"]
    np.testing.assert_allclose(a.overall, expected)


def test_all_zero_priorities_use_equal_weights(ctx):
    zero = Priorities(water=0, nitrogen=0, erosion=0, organic_matter=0, forage=0, income=0)
    weights, equal = priority_weights(zero)
    assert equal and all(w == pytest.approx(1 / 6) for w in weights.values())
    result = _run(ctx, priorities=zero)
    assert ("equal_weights", {}) in result.notices
    assert not priority_weights(Priorities())[1]


def test_replay_windows_and_interval(ctx):
    result = _run(ctx, THREE_CROPS)
    base = result.baseline
    assert base.calendar.cycle_years == 3
    assert ctx.climate.n_years == 40 and base.overall.size == 38
    for s in result.strategies:
        assert s.overall.size == 40 - s.calendar.cycle_years + 1
        assert 0 <= s.p10 <= s.median <= s.p90 <= 1


# ----------------------------------------------------------------- Selection

def test_baseline_plus_distinct_alternatives(ctx):
    result = _run(ctx, THREE_CROPS)
    assert result.baseline.is_baseline and result.baseline.id == "s0"
    assert len(result.alternatives) >= 2
    assert not any(alt.is_baseline for alt in result.alternatives)
    specs = [s.spec for s in result.strategies]
    assert len(set(specs)) == len(specs)
    assert [alt.id for alt in result.alternatives] == [f"s{i + 1}" for i in range(len(result.alternatives))]
    assert not any(code == "few_alternatives" for code, _ in result.notices)
    assert all(alt.label_key in OBJECTIVES + ("balanced",) for alt in result.alternatives)


def test_physical_deltas_against_the_baseline(ctx):
    from fieldshift.engine.run import baseline_deltas, strategy_metrics

    result = _run(ctx)
    base = strategy_metrics(result.baseline)
    assert 200 < base["water_demand_mm_per_year"] < 900 and 0 < base["bare_days_per_year"] < 365
    for alt in result.alternatives:
        delta, metrics = baseline_deltas(alt, result.baseline), strategy_metrics(alt)
        assert set(delta["objectives"]) == set(OBJECTIVES)
        for key in ("water_demand_mm_per_year", "bare_days_per_year", "n_kg_ha_per_year"):
            assert delta[key] == pytest.approx(metrics[key] - base[key])
        if alt.spec.cover_map and alt.spec.mains == result.baseline.spec.mains:
            assert delta["bare_days_per_year"] < 0 and delta["water_demand_mm_per_year"] > 0


def test_selection_prefers_different_operators(ctx):
    result = _run(ctx, THREE_CROPS)
    signatures = [tuple(sorted(op.name for op in alt.ops)) for alt in result.alternatives]
    assert len(set(signatures)) == len(signatures)


def test_over_constrained_request_returns_what_exists_with_a_notice(ctx):
    allowed = {"winter_wheat", "sunflower", "white_mustard"}
    excluded = [c for c in ctx.kb.crops if c not in allowed]
    result = _run(ctx, excluded_crops=excluded, max_cycle_years=2)
    assert len(result.alternatives) == 1
    assert result.alternatives[0].spec.cover_map == {0: "white_mustard"}
    code, params = next(n for n in result.notices if n[0] == "few_alternatives")
    assert params["count"] == 1 and "excluded_crops" in params["reasons"]


def test_baseline_longer_than_the_maximum_is_still_evaluated(ctx):
    result = _run(ctx, THREE_CROPS, max_cycle_years=2)
    assert ("max_cycle_raised", {"years": 3}) in result.notices
    assert all(alt.calendar.cycle_years <= 3 for alt in result.alternatives)


def test_baseline_with_timing_conflict_is_evaluated_with_a_notice(ctx):
    result = _run(ctx, SequenceSpec.of(["maize", "winter_rapeseed"]))
    assert any(code == "timing_conflict" for code, _ in result.notices)
    assert result.baseline.overall.size > 0
    for alt in result.alternatives:
        assert not any(slot.clamped for slot in alt.calendar.slots)


# ---------------------------------------------------------------- Confidence

@pytest.mark.parametrize("tier, allowed", [("climate_only", {"low"}), ("grid", {"medium", "low"}),
                                           ("field", {"high", "medium", "low"})])
def test_confidence_by_tier(kb, cfg, climate40, tier, allowed):
    result = _run(make_context(climate40, kb, cfg, tier=tier))
    assert {s.confidence for s in result.strategies} <= allowed


def test_reviewed_crops_and_supplied_soil_allow_high_confidence(cfg, climate40):
    import copy

    import yaml

    from fieldshift.kb.loader import parse_kb
    from fieldshift.settings import kb_path

    with open(kb_path(), encoding="utf-8") as fh:
        records = copy.deepcopy(yaml.safe_load(fh))
    for record in records:
        record["review_status"] = "reviewed"
    static = dict(clay_pct=30.0, sand_pct=25.0, soc_pct=2.0, ph=6.8, slope_pct=2.0, elevation_m=150.0,
                  awc_mm_per_m=165.0, k_factor=0.032)
    steady = make_climate(1985, 40, seed=7)
    ctx = make_context(steady, parse_kb(records), cfg.model_copy(update={"confidence_interval_width": 1.0}),
                       static=static, tier="field")
    result = _run(ctx)
    assert result.baseline.confidence == "high"


# -------------------------------------------------------------------- Timing

def test_full_engine_run_is_fast_enough(sample_root, recorded_climate_cache, kb, cfg):
    registry = BundleRegistry([sample_root])
    power = PowerClient(cache_dir=recorded_climate_cache, transport=FakePower(down=True).transport)
    started = time.perf_counter()
    ctx = build_context(49.144, 32.136, registry, power, kb, cfg)
    result = run_engine(ctx, THREE_CROPS, Priorities(), Constraints())
    elapsed = time.perf_counter() - started
    print(f"\nengine run: {elapsed:.2f} s, {result.candidates_generated} candidates, "
          f"{result.candidates_feasible} feasible, {len(result.alternatives)} alternatives")
    assert len(result.alternatives) >= 2
    assert elapsed < 8.0
