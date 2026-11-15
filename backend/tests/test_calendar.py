import numpy as np

from fieldshift.engine.calendar import SequenceSpec, build_calendar, daily_arrays, stage_bounds


def _cal(kb, cfg, mains, covers=(), strict=True):
    return build_calendar(SequenceSpec.of(mains, covers), kb, cfg, strict=strict)


def test_winter_crop_spans_two_cycle_years(kb, cfg):
    cal = _cal(kb, cfg, ["winter_wheat", "sunflower"])
    wheat = next(s for s in cal.slots if s.crop_id == "winter_wheat")
    sow_year, sow_doy = cal.day_ref(wheat.start)
    harvest_year, harvest_doy = cal.day_ref(wheat.end - 1)
    assert 244 <= sow_doy <= 304, "sown in autumn"
    assert 160 <= harvest_doy <= 215, "harvested in summer"
    assert harvest_year == (sow_year + 1) % cal.cycle_years
    assert cal.cycle_years == 2


def test_cycle_lengths(kb, cfg):
    assert _cal(kb, cfg, ["maize"]).cycle_years == 1
    assert _cal(kb, cfg, ["winter_wheat"]).cycle_years == 1  # wraps around the year end
    assert _cal(kb, cfg, ["sunflower", "winter_wheat"]).cycle_years == 2
    assert _cal(kb, cfg, ["winter_wheat", "sunflower", "spring_barley"]).cycle_years == 3


def test_slots_never_overlap_on_the_repeating_cycle(kb, cfg):
    for mains in (["winter_wheat"], ["winter_wheat", "sunflower"], ["maize", "soybean", "winter_wheat"],
                  ["sunflower", "spring_barley", "winter_rapeseed", "winter_wheat"]):
        cal = _cal(kb, cfg, mains)
        occupancy = np.zeros(cal.length, dtype=int)
        for slot in cal.slots:
            occupancy[cal.days_of(slot.start, slot.end)] += 1
        assert occupancy.max() == 1, mains
        assert all(g.days >= cfg.turnaround_days for g in cal.gaps()), mains


def test_alternatives_always_sow_inside_the_window(kb, cfg):
    cal = _cal(kb, cfg, ["maize", "winter_rapeseed"], strict=True)
    for slot in cal.mains:
        crop = kb.get(slot.crop_id)
        assert crop.sowing_window_doy[0] <= cal.day_ref(slot.start)[1] <= crop.sowing_window_doy[1]
        assert not slot.clamped
    assert cal.notices == []


def test_tight_baseline_timing_produces_a_notice_not_a_rejection(kb, cfg):
    cal = _cal(kb, cfg, ["maize", "winter_rapeseed"], strict=False)
    assert cal is not None
    rapeseed = next(s for s in cal.slots if s.crop_id == "winter_rapeseed")
    assert rapeseed.clamped
    code, params = cal.notices[0]
    assert code == "timing_conflict"
    assert params["crop"] == "winter_rapeseed" and params["prev"] == "maize" and params["days"] > 0


def test_cover_crop_is_placed_inside_the_gap(kb, cfg):
    cal = _cal(kb, cfg, ["winter_wheat", "sunflower"], covers=[(0, "white_mustard")])
    wheat = next(s for s in cal.slots if s.crop_id == "winter_wheat")
    sunflower = next(s for s in cal.slots if s.crop_id == "sunflower")
    cover = cal.covers[0]
    assert cover.start >= wheat.end + cfg.turnaround_days
    assert cover.end <= sunflower.start - cfg.cover_termination_lead_days
    assert cover.days >= cfg.min_cover_growth_days
    mustard = kb.get("white_mustard")
    assert mustard.sowing_window_doy[0] <= cal.day_ref(cover.start)[1] <= mustard.sowing_window_doy[1]


def test_winter_cover_is_terminated_before_the_next_sowing(kb, cfg):
    cal = _cal(kb, cfg, ["winter_wheat", "sunflower"], covers=[(0, "winter_rye")])
    cover, sunflower = cal.covers[0], next(s for s in cal.slots if s.crop_id == "sunflower")
    assert cover.end == sunflower.start - cfg.cover_termination_lead_days
    assert 0.9 < cover.growth_share <= 1.0


def test_cover_that_does_not_fit(kb, cfg):
    spec = dict(mains=["winter_wheat", "sunflower"], covers=[(1, "white_mustard")])  # 23-day gap after sunflower
    assert _cal(kb, cfg, strict=True, **spec) is None
    baseline = _cal(kb, cfg, strict=False, **spec)
    assert baseline.covers == []
    assert baseline.notices[0][0] == "cover_dropped"


def test_stage_bounds_partition_the_slot(kb, cfg):
    cal = _cal(kb, cfg, ["sunflower"])
    slot = cal.slots[0]
    bounds = stage_bounds(slot, kb.get("sunflower"))
    assert bounds["ini"][0] == slot.start and bounds["late"][1] == slot.end
    assert bounds["ini"][1] == bounds["dev"][0] and bounds["dev"][1] == bounds["mid"][0]
    assert bounds["mid"][1] - bounds["mid"][0] == 45


def test_daily_arrays_follow_the_crop_coefficient_curve(kb, cfg):
    cal = _cal(kb, cfg, ["sunflower"])
    arrays = daily_arrays(cal, kb, cfg)
    slot, crop = cal.slots[0], kb.get("sunflower")
    assert arrays.kc[slot.start] == crop.kc.ini
    assert arrays.kc[slot.start + 70] == crop.kc.mid
    assert arrays.kc[slot.start - 5] == cfg.bare_soil_kc
    assert arrays.root_m[slot.start + 70] == crop.root_depth_m
    assert arrays.bare_weight[slot.start + 10] == 0
    assert 0 < arrays.bare_weight[slot.end + 5] <= 1
