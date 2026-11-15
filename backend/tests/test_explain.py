import copy
import re

import pytest
import yaml

from fieldshift.contracts.api import Constraints, Priorities
from fieldshift.diagnostics.site import diagnose
from fieldshift.engine.calendar import SequenceSpec
from fieldshift.engine.run import run_engine
from fieldshift.explain.build import build_strategies
from fieldshift.explain.templates import EN, UK, placeholders, t
from fieldshift.kb.loader import parse_kb
from fieldshift.settings import kb_path

from .helpers import make_climate, make_context

SUPPLIED_SOIL = dict(clay_pct=30.0, sand_pct=25.0, soc_pct=2.0, ph=6.8, slope_pct=2.0, elevation_m=150.0,
                     awc_mm_per_m=165.0, k_factor=0.032)
DERIVED_SOIL = dict(clay_pct=30.0, sand_pct=25.0, soc_pct=2.0, ph=6.8, slope_pct=2.0, elevation_m=150.0)
ELEMENTS = ("why", "evidence", "benefits", "gaps", "local_review")


def explain(ctx, mains, priorities=None, lang="en", covers=(), **constraints):
    engine = run_engine(ctx, SequenceSpec.of(mains, covers), priorities or Priorities(), Constraints(**constraints))
    site = diagnose(ctx, engine.baseline.evaluation, lang)
    return build_strategies(engine, ctx, site, lang), site, engine


def codes(statements):
    return [s.code for s in statements]


@pytest.fixture(scope="module")
def ctx(kb, cfg, climate40):
    return make_context(climate40, kb, cfg, static=DERIVED_SOIL, tier="grid",
                        sources={"soil": ("SoilGrids 2.0", "250 m")})


@pytest.fixture(scope="module")
def reviewed_kb():
    with open(kb_path(), encoding="utf-8") as fh:
        records = copy.deepcopy(yaml.safe_load(fh))
    for record in records:
        record["review_status"] = "reviewed"
    return parse_kb(records)


@pytest.fixture(scope="module")
def drying_ctx(kb, cfg):
    """A site whose growing-season water balance declines significantly."""
    frame = make_climate(1985, 40, seed=7)
    years = frame.index.year - 1985
    frame["precip"] = frame["precip"] * (1.25 - 0.02 * years)
    return make_context(frame, kb, cfg)


WATER_FIRST = Priorities(water=1.0, nitrogen=0.2, erosion=0.2, organic_matter=0.2, forage=0.0, income=0.3)
SOIL_FIRST = Priorities(water=0.1, nitrogen=0.4, erosion=1.0, organic_matter=1.0, forage=0.0, income=0.2)


# ------------------------------------------------------------------ Templates

def test_both_languages_define_the_same_templates():
    assert set(EN) == set(UK)
    for key in EN:
        assert placeholders(EN[key]) == placeholders(UK[key]), key
        assert EN[key].strip() and UK[key].strip()


def test_ukrainian_templates_are_ukrainian():
    cyrillic = re.compile("[а-яіїєґ]", re.IGNORECASE)
    untranslated = [k for k, v in UK.items() if not cyrillic.search(v) and not k.startswith("unit.")]
    assert untranslated == []


# ------------------------------------------------------- Five elements, evidence

def test_every_strategy_has_all_five_elements(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower", "spring_barley"])
    assert len(strategies) >= 3 and strategies[0].is_baseline
    for s in strategies:
        for element in ELEMENTS:
            assert getattr(s, element), f"{s.id} has an empty '{element}'"


def test_baseline_is_explained_as_the_reference(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower"])
    base = strategies[0]
    assert base.why[0].code == "why.baseline_reference" and "current rotation" in base.why[0].text
    assert base.label == "Current rotation" and base.vs_baseline is None and base.operators == []
    assert "benefit.baseline_metrics" in codes(base.benefits)


def test_evidence_entries_are_complete(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower", "spring_barley"])
    for s in strategies:
        indicators = [e.indicator for e in s.evidence]
        assert len(indicators) == len(set(indicators))
        assert {"overall_score", "bare_days_per_year", "water_demand_mm_per_year", "n_kg_ha_per_year"} <= set(indicators)
        for e in s.evidence:
            for name in ("indicator", "label", "unit", "source", "period", "resolution", "scope", "method"):
                assert str(getattr(e, name)).strip(), (e.indicator, name)
            assert e.scope in ("field", "grid_cell", "climate_cell", "rotation")


def test_evidence_states_source_period_and_resolution(kb, cfg, climate40, sample_root):
    from fieldshift.ingest.registry import BundleRegistry

    registry = BundleRegistry([sample_root])
    ctx = make_context(climate40, kb, cfg, static=DERIVED_SOIL, tier="grid", timeseries=registry.timeseries("g_0000"),
                       sources={"ndvi": registry.source_label("g_0000", "ndvi"), "soil": registry.source_label("g_0000", "soil")})
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower"])
    satellite = next(e for e in strategies[0].evidence if e.indicator == "observed_low_cover_days")
    assert satellite.source == "MOD13Q1 061" and satellite.period == "2001-2025"
    assert satellite.resolution == "250 m" and satellite.scope == "grid_cell"
    climate = next(e for e in strategies[0].evidence if e.indicator == "water_demand_mm_per_year")
    assert "NASA POWER" in climate.source and climate.period == "1985-2024" and climate.scope == "climate_cell"
    assert "0.5 x 0.625" in climate.resolution


def test_numeric_claims_are_backed_by_evidence(ctx, drying_ctx):
    for context, priorities in ((ctx, SOIL_FIRST), (drying_ctx, WATER_FIRST)):
        strategies, _, _ = explain(context, ["winter_wheat", "maize", "sunflower"], priorities)
        for s in strategies:
            evidence = {e.indicator: e for e in s.evidence}
            for statement in s.why + s.benefits:
                if re.search(r"\d", statement.text):
                    assert statement.indicator, f"number without evidence: {statement.text}"
                if statement.indicator:
                    assert statement.indicator in evidence, statement.code
                    assert evidence[statement.indicator].value == statement.value, statement.code


# ------------------------------------------------------------------------ Why

def test_top_priority_is_cited_with_the_size_of_the_improvement(drying_ctx):
    strategies, _, _ = explain(drying_ctx, ["winter_wheat", "maize", "sunflower"], WATER_FIRST)
    improved = [s for s in strategies[1:] if s.vs_baseline.objectives["water"] > 0.005]
    assert improved, "the scenario must contain an alternative that improves the water score"
    for s in improved:
        cited = next(w for w in s.why if w.code == "why.priority_improved" and w.indicator == "objective.water")
        assert "water conservation" in cited.text and "priority no. 1" in cited.text
        assert f"{s.scores.objectives['water']:.2f}" in cited.text
        assert f"{strategies[0].scores.objectives['water']:.2f}" in cited.text


def test_zero_weight_priority_is_never_a_reason(ctx):
    priorities = Priorities(water=0.5, nitrogen=0.5, erosion=0.5, organic_matter=0.5, forage=0.0, income=0.5)
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower", "spring_barley"], priorities)
    for s in strategies:
        for statement in s.why:
            assert statement.indicator != "objective.forage"
            assert "forage" not in statement.text.lower()


def test_significant_trend_is_cited(drying_ctx):
    strategies, site, _ = explain(drying_ctx, ["winter_wheat", "maize", "sunflower"], WATER_FIRST)
    trend = next(tr for tr in site.trends if tr.indicator == "water_balance_apr_sep")
    assert trend.significant and trend.slope_per_decade < 0
    responders = [s for s in strategies[1:]
                  if s.vs_baseline.water_demand_mm_per_year < -1 or s.vs_baseline.objectives["water"] > 0.005]
    assert responders
    for s in responders:
        cited = next(w for w in s.why if w.code == "why.trend_water")
        assert trend.period in cited.text
        assert any(e.indicator == "trend.water_balance_apr_sep" for e in s.evidence)


def test_insignificant_trend_is_not_cited(ctx):
    strategies, site, _ = explain(ctx, ["winter_wheat", "maize", "sunflower"], WATER_FIRST)
    assert not next(tr for tr in site.trends if tr.indicator == "water_balance_apr_sep").significant
    assert all("why.trend_water" not in codes(s.why) for s in strategies)


# --------------------------------------------------------- Benefits, trade-offs

def test_cover_crop_benefit_is_quantified_and_its_water_cost_disclosed(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower"], SOIL_FIRST)
    covered = [s for s in strategies[1:] if "insert_cover" in s.operators and len(s.operators) == 1]
    assert covered, "soil-first priorities must surface a cover-crop alternative"
    s = covered[0]
    days = next(b for b in s.benefits if b.code == "benefit.erosion_days")
    assert days.value < 0 and f"{-days.value:.0f} fewer bare-soil days" in days.text
    assert s.vs_baseline.bare_days_per_year == days.value

    cost = next(b for b in s.benefits if b.code == "tradeoff.water_demand")
    assert cost.value > 0 and cost.text.startswith("Trade-off") and f"{cost.value:.0f} mm" in cost.text
    assert s.vs_baseline.water_demand_mm_per_year == cost.value


def test_lower_objectives_are_stated_as_trade_offs(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "maize", "sunflower"], SOIL_FIRST)
    for s in strategies[1:]:
        worse = {name for name, change in s.vs_baseline.objectives.items() if change < -0.005}
        stated = {b.indicator.split(".", 1)[1] for b in s.benefits if b.code == "tradeoff.objective"}
        assert worse == stated


# ----------------------------------------------------------------------- Gaps

def test_gaps_in_the_grid_tier_with_draft_crops(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower"])
    for s in strategies:
        gap_codes = codes(s.gaps)
        assert {"gap.climate_resolution", "gap.score_uncertainty", "gap.grid_cell_not_field", "gap.soil_derived",
                "gap.draft_crop", "gap.no_suitability", "gap.winterkill_no_snow"} <= set(gap_codes)
        grid = next(g for g in s.gaps if g.code == "gap.grid_cell_not_field")
        assert "10 km" in grid.text and "not your specific field" in grid.text
        draft = next(g for g in s.gaps if g.code == "gap.draft_crop")
        assert all(slot.crop_name in draft.text for slot in s.slots), "every draft crop in the strategy is named"
        assert "50 km" in next(g for g in s.gaps if g.code == "gap.climate_resolution").text
    baseline_draft = next(g for g in strategies[0].gaps if g.code == "gap.draft_crop")
    assert "Winter wheat" in baseline_draft.text and "Sunflower" in baseline_draft.text


def test_gaps_that_do_not_apply_are_absent(reviewed_kb, cfg, climate40):
    ctx = make_context(climate40, reviewed_kb, cfg, static=SUPPLIED_SOIL, tier="field",
                       suitability={"winter_wheat": 80.0, "sunflower": 75.0})
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower"])
    for s in strategies:
        gap_codes = set(codes(s.gaps))
        assert not gap_codes & {"gap.grid_cell_not_field", "gap.soil_derived", "gap.soil_assumed", "gap.draft_crop",
                                "gap.no_satellite_or_soil", "gap.no_suitability"}
        assert "gap.climate_resolution" in gap_codes


def test_gaps_in_the_climate_only_tier(kb, cfg, climate40):
    strategies, _, _ = explain(make_context(climate40, kb, cfg), ["maize", "soybean"])
    for s in strategies:
        gap_codes = set(codes(s.gaps))
        assert {"gap.no_satellite_or_soil", "gap.soil_assumed"} <= gap_codes
        assert "gap.grid_cell_not_field" not in gap_codes
        has_winter_crop = any(kb.get(slot.crop_id).season == "winter" for slot in s.slots if slot.role == "main")
        assert ("gap.winterkill_no_snow" in gap_codes) == has_winter_crop
        assert s.confidence == "low"
    assert "gap.winterkill_no_snow" not in set(codes(strategies[0].gaps))


# --------------------------------------------------------------- Local review

def test_standing_reminders_are_always_present(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower", "spring_barley"])
    for s in strategies:
        review = codes(s.local_review)
        assert review[0] == "review.supports_not_replaces" and "review.unseen_conditions" in review
        assert "does not replace" in s.local_review[0].text and "agronomist" in s.local_review[0].text


def test_condition_specific_reminders(ctx):
    strategies, _, engine = explain(ctx, ["winter_wheat", "sunflower"], SOIL_FIRST)
    by_id = {r.id: r for r in engine.strategies}
    for s in strategies:
        review = {r.code: r for r in s.local_review}
        result = by_id[s.id]
        new_mains = [c for c in result.introduced if ctx.kb.get(c).role != "cover"]
        new_covers = [c for c in result.introduced if ctx.kb.get(c).role == "cover"]
        assert ("review.new_crop" in review) == bool(new_mains)
        assert ("review.cover_crop" in review) == bool(new_covers)
        for crop_id in new_mains:
            assert ctx.kb.name(crop_id) in review["review.new_crop"].text
        if new_covers:
            assert "termination timing" in review["review.cover_crop"].text
        if any(ctx.kb.get(c).season == "winter" for c in result.spec.mains):
            assert "review.winter_crop" in review
    assert any("review.cover_crop" in codes(s.local_review) for s in strategies)
    assert "review.new_crop" not in codes(strategies[0].local_review)


def test_return_interval_reminder_names_the_crop_and_interval(ctx):
    strategies, _, _ = explain(ctx, ["winter_wheat", "sunflower"])
    base = strategies[0]
    assert base.retains_return_violation == ["sunflower"]
    reminder = next(r for r in base.local_review if r.code == "review.return_interval")
    assert "Sunflower" in reminder.text and "every 2 years" in reminder.text and "7 years" in reminder.text
    assert reminder.indicator == "return_interval.sunflower" and reminder.value == 2


# ------------------------------------------------------- Language, determinism

def test_language_parity(ctx):
    en, _, _ = explain(ctx, ["winter_wheat", "sunflower", "spring_barley"], lang="en")
    uk, _, _ = explain(ctx, ["winter_wheat", "sunflower", "spring_barley"], lang="uk")
    assert [s.id for s in en] == [s.id for s in uk]
    cyrillic = re.compile("[а-яіїєґ]", re.IGNORECASE)
    for a, b in zip(en, uk):
        assert a.scores == b.scores and a.metrics == b.metrics and a.vs_baseline == b.vs_baseline
        assert [(e.indicator, e.value) for e in a.evidence] == [(e.indicator, e.value) for e in b.evidence]
        for element in ("why", "benefits", "gaps", "local_review"):
            left, right = getattr(a, element), getattr(b, element)
            assert [(s.code, s.indicator, s.value) for s in left] == [(s.code, s.indicator, s.value) for s in right]
            assert all(cyrillic.search(s.text) for s in right)
            assert all(re.findall(r"\d+(?:\.\d+)?", x.text) == re.findall(r"\d+(?:\.\d+)?", y.text) or x.code.startswith("gap.climate")
                       for x, y in zip(left, right)), element
        assert b.label != a.label and cyrillic.search(b.label)
        assert all(cyrillic.search(slot.crop_name) for slot in b.slots)


def test_wording_is_reproducible(ctx):
    first, _, _ = explain(ctx, ["winter_wheat", "maize", "sunflower"], WATER_FIRST)
    second, _, _ = explain(ctx, ["winter_wheat", "maize", "sunflower"], WATER_FIRST)
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_template_rendering_ignores_unknown_language():
    assert t("xx", "label.baseline") == t("en", "label.baseline")
