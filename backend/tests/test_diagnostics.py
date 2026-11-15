import numpy as np
import pandas as pd
import pytest

from fieldshift.climate.power import PowerClient
from fieldshift.diagnostics.cover import observed_low_cover
from fieldshift.diagnostics.et0 import et0_hargreaves, et0_penman_monteith
from fieldshift.diagnostics.site import bare_windows, build_context, diagnose
from fieldshift.diagnostics.soil import derive_awc_mm_per_m, derive_k_factor, resolve_soil, saxton_rawls, terrain_factor
from fieldshift.diagnostics.trends import ShortRecord, TrendResult, summarize_record, theil_sen_trend
from fieldshift.engine.calendar import SequenceSpec, build_calendar, daily_arrays
from fieldshift.engine.evaluate import evaluate
from fieldshift.engine.simulate import build_weather, longest_run, run_water_balance
from fieldshift.ingest.registry import BundleRegistry

from .helpers import FakePower, kb_variant, make_climate, make_context, ndvi_frame

LOAM = dict(clay_pct=20.0, sand_pct=40.0, soc_pct=1.45, ph=6.8, slope_pct=3.0, elevation_m=150.0)


def _baseline(ctx, mains, covers=()):
    calendar = build_calendar(SequenceSpec.of(mains, covers), ctx.kb, ctx.cfg, strict=False)
    return evaluate([calendar], ctx)[0]


# ------------------------------------------------- Reference evapotranspiration

def test_fao56_daily_worked_example_is_reproduced():
    # FAO-56 Example 18: Uccle (Brussels), 6 July. Published result: 3.9 mm/day (3.88).
    et0 = et0_penman_monteith(tmax=21.5, tmin=12.3, ea=1.409, u2=2.078, rs=22.07,
                              lat_deg=50.8, elevation_m=100.0, doy=187)
    assert float(et0) == pytest.approx(3.88, abs=0.1)


def test_days_without_radiation_use_the_temperature_estimate(kb, cfg):
    frame = make_climate(2000, 3, seed=1)
    frame.loc["2001-06-01":"2001-06-10", "srad"] = np.nan
    ctx = make_context(frame, kb, cfg)
    assert ctx.climate.et0_fallback_days == 10
    assert np.isfinite(ctx.climate.matrix["et0"]).all()
    assert float(et0_hargreaves(28.0, 14.0, 49.0, 180)) == pytest.approx(5.2, abs=1.0)


def test_et0_has_a_plausible_seasonal_cycle(kb, cfg, climate40):
    et0 = make_context(climate40, kb, cfg).climate.matrix["et0"]
    assert 0.1 < et0[:, :31].mean() < 1.5       # January
    assert 3.5 < et0[:, 181:212].mean() < 7.0   # July
    assert 550 < et0.sum(axis=1).mean() < 1100  # annual total, mm


# ---------------------------------------------------------------------- Soil

def test_saxton_rawls_reproduces_the_published_loam():
    # Saxton & Rawls 2006, Table 3: loam (40% sand, 20% clay, 2.5% organic matter):
    # wilting point 14%, field capacity 28%, available water 0.14 cm/cm.
    wilting, capacity = saxton_rawls(40, 20, 2.5)
    assert wilting == pytest.approx(0.14, abs=0.01)
    assert capacity == pytest.approx(0.28, abs=0.01)
    assert derive_awc_mm_per_m(40, 20, 2.5 / 1.724) == pytest.approx(140, abs=10)


def test_erodibility_is_in_the_published_range_and_orders_textures():
    loam = derive_k_factor(40, 20, 1.45)
    assert 0.02 < loam < 0.05                                # typical loam in SI units
    assert derive_k_factor(15, 15, 1.0) > loam               # silt-rich soil erodes more easily
    assert derive_k_factor(40, 20, 4.0) < loam               # organic carbon protects


def test_soil_properties_carry_their_provenance(cfg):
    derived = resolve_soil(LOAM, cfg)
    assert derived.awc_status == "derived" and derived.k_status == "derived"
    assert 120 < derived.awc_mm_per_m < 170

    supplied = resolve_soil({**LOAM, "awc_mm_per_m": 165.0, "k_factor": 0.032}, cfg)
    assert (supplied.awc_mm_per_m, supplied.awc_status, supplied.k_status) == (165.0, "supplied", "supplied")

    assumed = resolve_soil(None, cfg)
    assert assumed.awc_status == "assumed" and assumed.awc_mm_per_m == cfg.default_awc_mm_per_m
    assert assumed.k_status == "unavailable"
    assert terrain_factor(assumed, cfg) == (cfg.neutral_terrain_factor, True)
    factor, rain_only = terrain_factor(derived, cfg)
    assert 0.4 <= factor <= 1.0 and not rain_only


# ----------------------------------------------------------- Bare-soil windows

def test_long_gap_after_a_winter_cereal(kb, cfg, climate40):
    ctx = make_context(climate40, kb, cfg)
    windows = bare_windows(ctx, _baseline(ctx, ["winter_wheat", "sunflower"]), "en")
    longest = max(windows, key=lambda w: w.days)
    assert longest.after_crop_id == "winter_wheat"
    assert 250 <= longest.days <= 300, "about nine months"
    assert 180 <= longest.start.doy <= 215      # from the July harvest
    assert 90 <= longest.end.doy <= 140         # to the April sowing


def test_winter_crop_is_not_reported_as_bare(kb, cfg, climate40):
    ctx = make_context(climate40, kb, cfg)
    ev = _baseline(ctx, ["winter_wheat", "sunflower"])
    wheat = next(s.slot for s in ev.slots if s.slot.crop_id == "winter_wheat")
    cal = ev.calendar
    growing = cal.days_of(wheat.start, wheat.end)
    assert (daily_arrays(cal, kb, cfg).bare_weight[growing] == 0).all()
    for gap in cal.gaps():
        assert not np.intersect1d(cal.days_of(gap.start, gap.end), growing).size


# ------------------------------------------------------ Observed low-cover periods

def test_low_cover_period_wrapping_the_year_end():
    winter_low = ndvi_frame(lambda doy: 0.2 if (doy >= 305 or doy <= 75) else 0.65)
    periods = observed_low_cover(winter_low, threshold=0.30)
    assert len(periods) == 1
    period = periods[0]
    assert period.start_doy == 305 and period.end_doy == 80   # early November to mid March
    assert period.start_doy > period.end_doy and period.days == 141
    assert period.years == 25 and period.median_ndvi == pytest.approx(0.2)


def test_low_cover_period_inside_the_year():
    summer_low = ndvi_frame(lambda doy: 0.15 if 190 <= doy <= 240 else 0.6)
    periods = observed_low_cover(summer_low, threshold=0.30)
    assert [(p.start_doy, p.end_doy) for p in periods] == [(193, 240)]
    assert observed_low_cover(ndvi_frame(lambda doy: 0.6), 0.30) == []
    assert observed_low_cover(None, 0.30) == []


def test_no_time_series_is_recorded_as_a_gap(kb, cfg, climate40):
    ctx = make_context(climate40, kb, cfg, tier="climate_only")
    site = diagnose(ctx, _baseline(ctx, ["winter_wheat", "sunflower"]))
    assert site.observed_low_cover == []
    assert "gap.no_timeseries" in {g.code for g in site.information_gaps}


# -------------------------------------------------------------- Water balance

def _bucket(frame, kb, cfg, taw_mm=120.0, kc=1.0):
    ctx = make_context(frame, kb, cfg)
    weather = build_weather(ctx.climate.matrix, ctx.climate.years, 1, cfg)
    shape = (1, 365)
    balance = run_water_balance(np.full(shape, kc), np.full(shape, taw_mm), np.full(shape, 0.5),
                                np.zeros(shape, dtype=bool), weather, cfg, detail=True, spin_up=False)
    return weather, balance


def test_water_balance_closes(kb, cfg, climate40):
    weather, b = _bucket(climate40, kb, cfg)
    inflow = weather.precip.sum(axis=1)
    used = b.eta[0].sum(axis=1)
    drained = b.drainage[0].sum(axis=1)
    storage_change = -(b.depletion[0][:, -1] - b.initial_depletion[0])
    np.testing.assert_allclose(inflow - used - drained, storage_change, atol=1e-6)
    assert (b.eta <= b.etc + 1e-9).all() and (b.depletion >= 0).all() and (b.depletion <= 120.0 + 1e-9).all()


def test_no_deficit_under_abundant_rain(kb, cfg, climate40):
    wet = climate40.copy()
    wet["precip"] = 25.0
    _, b = _bucket(wet, kb, cfg)
    np.testing.assert_allclose(b.eta, b.etc)
    assert not b.stressed.any()

    dry = climate40.copy()
    dry["precip"] = 0.0
    _, d = _bucket(dry, kb, cfg)
    assert d.eta.sum() < 0.5 * d.etc.sum() and d.stressed.any()


def test_larger_capacity_lowers_the_deficit(kb, cfg, climate40):
    def deficit(awc):
        ctx = make_context(climate40, kb, cfg, static={**LOAM, "awc_mm_per_m": awc})
        return float(np.median(_baseline(ctx, ["maize"]).mains[0].demand - _baseline(ctx, ["maize"]).mains[0].actual))

    assert deficit(220.0) < deficit(70.0)


def test_water_balance_entries_are_consistent(kb, cfg, climate40):
    ctx = make_context(climate40, kb, cfg)
    site = diagnose(ctx, _baseline(ctx, ["winter_wheat", "sunflower", "spring_barley"]))
    assert [w.crop_id for w in site.water_balance] == ["winter_wheat", "sunflower", "spring_barley"]
    for entry in site.water_balance:
        assert 150 < entry.demand_mm < 900
        assert 0 <= entry.supply_mm <= entry.demand_mm
        assert entry.deficit_mm == pytest.approx(entry.demand_mm - entry.supply_mm, abs=1.01)


def test_longest_run():
    flags = np.array([[1, 1, 0, 1, 1, 1, 0], [0, 0, 0, 0, 0, 0, 0], [1, 1, 1, 1, 1, 1, 1]], dtype=bool)
    assert longest_run(flags).tolist() == [3, 0, 7]


# ------------------------------------------------------------- Stress calendar

def _heat_climate(hot_years):
    """Thirty-six years in which only the listed years have a hot spell in early July."""
    frame = make_climate(1985, 36, seed=3)
    frame["tmax"] = np.minimum(frame["tmax"], 29.0)
    for year in hot_years:
        frame.loc[f"{year}-07-01":f"{year}-07-05", "tmax"] = 41.0
    return frame


def test_heat_during_the_sensitive_stage_twelve_of_thirty_six_years(kb, cfg):
    hot_years = list(range(1985, 2021, 3))
    assert len(hot_years) == 12
    ctx = make_context(_heat_climate(hot_years), kb, cfg)
    site = diagnose(ctx, _baseline(ctx, ["sunflower"]))
    heat = next(s for s in site.stress if s.crop_id == "sunflower" and s.hazard == "heat")
    assert (heat.years_hit, heat.years_total) == (12, 36)
    assert heat.probability == pytest.approx(0.333, abs=0.001)
    assert heat.stage == "mid" and heat.window_start_doy < 183 < heat.window_end_doy


def test_hazards_that_do_not_apply_are_omitted(kb, cfg, climate40):
    ctx = make_context(climate40, kb, cfg)
    site = diagnose(ctx, _baseline(ctx, ["winter_wheat", "sunflower"]))
    by_crop = {}
    for entry in site.stress:
        by_crop.setdefault(entry.crop_id, set()).add(entry.hazard)
    assert "winterkill" not in by_crop["sunflower"]
    assert {"heat", "frost", "drought"} <= by_crop["sunflower"]
    assert "winterkill" in by_crop["winter_wheat"]


def test_edited_threshold_changes_the_probability(cfg, climate40):
    def heat_probability(tmax_c):
        kb = kb_variant("sunflower", lambda r: r["stress"]["heat"].update(tmax_c=tmax_c))
        ctx = make_context(climate40, kb, cfg)
        site = diagnose(ctx, _baseline(ctx, ["sunflower"]))
        return next(s.probability for s in site.stress if s.hazard == "heat")

    assert heat_probability(26) > heat_probability(35)


def test_drought_follows_rainfall(kb, cfg, climate40):
    def drought(precip_scale):
        frame = climate40.copy()
        frame["precip"] = frame["precip"] * precip_scale
        ctx = make_context(frame, kb, cfg)
        site = diagnose(ctx, _baseline(ctx, ["maize"]))
        return next(s.probability for s in site.stress if s.hazard == "drought")

    assert drought(0.3) > drought(3.0)


# ----------------------------------------------------------- Erosion exposure

def test_wetter_window_scores_higher(kb, cfg, climate40):
    def exposure(frame):
        ctx = make_context(frame, kb, cfg, static=LOAM)
        windows = bare_windows(ctx, _baseline(ctx, ["winter_wheat", "sunflower"]), "en")
        return max(windows, key=lambda w: w.days)

    wetter = climate40.copy()
    autumn = (wetter.index.month >= 9) & (wetter.index.month <= 11) & (wetter.index.day % 6 == 0)
    wetter.loc[autumn, "precip"] = wetter.loc[autumn, "precip"] + 18.0
    base, wet = exposure(climate40), exposure(wetter)
    assert wet.days == base.days
    assert wet.erosive_rain_mm > base.erosive_rain_mm and wet.erosion_exposure > base.erosion_exposure
    assert 0 <= base.erosion_exposure <= 1 and not base.rain_only


def test_rainfall_only_index_is_marked(kb, cfg, climate40):
    ctx = make_context(climate40, kb, cfg, tier="climate_only")
    windows = bare_windows(ctx, _baseline(ctx, ["winter_wheat", "sunflower"]), "en")
    assert all(w.rain_only for w in windows)
    with_terrain = make_context(climate40, kb, cfg, static={**LOAM, "slope_pct": 9.0})
    steep = bare_windows(with_terrain, _baseline(with_terrain, ["winter_wheat", "sunflower"]), "en")
    flat_ctx = make_context(climate40, kb, cfg, static={**LOAM, "slope_pct": 0.5})
    flat = bare_windows(flat_ctx, _baseline(flat_ctx, ["winter_wheat", "sunflower"]), "en")
    assert max(w.erosion_exposure for w in steep) > max(w.erosion_exposure for w in flat)


# --------------------------------------------------------------------- Trends

def test_known_trend_is_recovered():
    rng = np.random.default_rng(11)
    years = np.arange(1985, 2025)
    values = 10 + 0.04 * (years - years[0]) + rng.normal(0, 0.25, years.size)  # 0.4 per decade
    result = theil_sen_trend("tmean_apr_sep", "c", years, values)
    assert result.slope_per_decade == pytest.approx(0.4, abs=0.1)
    assert result.significant and result.p_value < 0.05
    assert result.period == "1985-2024" and result.n_years == 40


def test_trendless_series_is_not_significant():
    rng = np.random.default_rng(5)
    years = np.arange(1985, 2025)
    result = theil_sen_trend("precip_apr_sep", "mm", years, rng.normal(300, 40, years.size))
    assert not result.significant and result.p_value >= 0.05


def test_climate_trends_cover_the_five_indicators(kb, cfg, climate40):
    warming = climate40.copy()
    drift = (warming.index.year - 1985) * 0.06
    for column in ("t2m", "tmax", "tmin"):
        warming[column] = warming[column] + drift
    ctx = make_context(warming, kb, cfg)
    site = diagnose(ctx, _baseline(ctx, ["maize"]))
    trends = {tr.indicator: tr for tr in site.trends}
    assert set(trends) == {"tmean_apr_sep", "precip_apr_sep", "water_balance_apr_sep", "hot_days", "rootzone_wetness_jja"}
    warm = trends["tmean_apr_sep"]
    assert warm.significant and warm.slope_per_decade == pytest.approx(0.6, abs=0.2)
    assert warm.period == "1985-2024" and warm.scope == "climate_cell" and warm.source == "NASA POWER"


def test_short_records_are_anomalies_not_trends(cfg):
    months = pd.date_range("2015-04-01", "2025-12-01", freq="MS")
    frame = pd.DataFrame({"date": months, "value": 0.25 + 0.002 * np.arange(months.size)})
    short = summarize_record("sm_rootzone", frame, cfg, unit="m3m3")
    assert isinstance(short, ShortRecord)
    assert short.n_years == 11 and len(short.recent) == 3
    assert not hasattr(short, "slope_per_decade") and not hasattr(short, "significant")

    long_months = pd.date_range("2001-01-01", "2025-12-01", freq="MS")
    long = summarize_record("ndvi_peak", pd.DataFrame({"date": long_months, "value": 0.5}), cfg, unit="ndvi", reducer="max")
    assert isinstance(long, TrendResult) and long.n_years == 25


# ------------------------------------------------------------------ Data tiers

@pytest.fixture
def offline(sample_root, recorded_climate_cache, kb, cfg):
    registry = BundleRegistry([sample_root])
    power = PowerClient(cache_dir=recorded_climate_cache, transport=FakePower(down=True).transport)
    return registry, power, kb, cfg


@pytest.mark.parametrize(
    "lat, lon, tier, unit_id",
    [(49.144, 32.136, "field", "f_demo_01"), (49.05, 32.05, "grid", "g_0000"), (48.9, 31.7, "climate_only", None)],
)
def test_diagnosis_in_every_tier(offline, lat, lon, tier, unit_id):
    registry, power, kb, cfg = offline
    ctx = build_context(lat, lon, registry, power, kb, cfg)
    site = diagnose(ctx, _baseline(ctx, ["winter_wheat", "sunflower", "spring_barley"]), "en")

    assert site.data_tier == tier
    assert (site.unit.unit_id if site.unit else None) == unit_id
    assert site.climate.years >= 30 and "NASA POWER" in site.climate.source
    assert len(site.bare_windows) >= 2 and len(site.stress) >= 6 and len(site.water_balance) == 3
    assert len([tr for tr in site.trends if tr.scope == "climate_cell"]) == 5
    codes = {g.code for g in site.information_gaps}

    if tier == "climate_only":
        assert site.observed_low_cover == [] and site.anomalies == []
        assert site.soil.awc_status == "assumed"
        assert {"gap.no_timeseries", "gap.no_satellite_or_soil", "gap.soil_assumed"} <= codes
        assert all(w.rain_only for w in site.bare_windows)
    else:
        assert site.observed_low_cover and site.observed_low_cover[0].source == "MOD13Q1 061"
        assert {a.variable for a in site.anomalies} == {"sm_surface", "sm_rootzone"}
        assert any(tr.indicator == "ndvi_peak" for tr in site.trends)
        assert "gap.no_timeseries" not in codes

    if tier == "field":
        assert site.soil.awc_status == "supplied" and "gap.soil_derived" not in codes
    if tier == "grid":
        assert site.soil.awc_status == "derived" and "gap.soil_derived" in codes


def test_real_climate_gives_plausible_central_ukraine_values(offline):
    registry, power, kb, cfg = offline
    ctx = build_context(49.05, 32.05, registry, power, kb, cfg)
    matrix = ctx.climate.matrix
    assert 550 < matrix["et0"].sum(axis=1).mean() < 1000      # mm per year
    assert 400 < matrix["precip"].sum(axis=1).mean() < 800    # mm per year
    assert 16 < matrix["t2m"][:, 181:212].mean() < 26         # July mean, deg C
    assert ctx.heat_units_share("maize") > 0.8
    assert 0 <= ctx.heat_units_share("sorghum") <= 1
