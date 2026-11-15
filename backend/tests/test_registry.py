import json

from fieldshift.ingest.registry import BundleRegistry
from fieldshift.ingest.sample import FIELDS_ID, GRID_ID


def test_registry_loads_sample_bundles(sample_root):
    registry = BundleRegistry([sample_root])
    summary = {s["bundle_id"]: s for s in registry.summary()}
    assert summary[GRID_ID]["units"] == 20 and summary[GRID_ID]["unit_type"] == "grid_cell"
    assert summary[FIELDS_ID]["units"] == 3 and summary[FIELDS_ID]["unit_type"] == "field"
    assert registry.rejected == []


def test_unsupported_contract_version_is_refused(grid_bundle):
    manifest = grid_bundle / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["contract_version"] = "2.0"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    registry = BundleRegistry([grid_bundle.parent])
    assert registry.bundles == {}
    assert len(registry.rejected) == 1
    assert "'2.0' is not supported" in registry.rejected[0][1]


def test_timeseries_query_returns_only_the_units_rows(sample_root):
    registry = BundleRegistry([sample_root])
    frame = registry.timeseries("g_0007")
    assert set(frame["variable"]) == {"ndvi", "evi", "et", "precip", "sm_surface", "sm_rootzone"}
    ndvi = registry.timeseries("g_0007", "ndvi")
    assert len(ndvi) == 25 * 23
    assert ndvi["date"].is_monotonic_increasing
    assert ndvi["source"].iloc[0] == "MOD13Q1.061" and ndvi["res_m"].iloc[0] == 250
    assert registry.timeseries("no_such_unit").empty


def test_static_and_optional_tables(sample_root, field_bundle):
    registry = BundleRegistry([sample_root])
    supplied = registry.static("f_demo_01")
    assert supplied["awc_mm_per_m"] == 165.0 and supplied["k_factor"] == 0.032
    assert registry.static("f_demo_02")["awc_mm_per_m"] is None
    assert registry.suitability("f_demo_01")["winter_wheat"] > 50
    assert list(registry.crop_history("f_demo_01")["year"]) == [2021, 2022, 2023, 2024, 2025]
    assert registry.source_label("g_0000", "ndvi") == ("MOD13Q1 061", "250 m")

    (field_bundle / "crop_history.csv").unlink()
    (field_bundle / "suitability.csv").unlink()
    bare = BundleRegistry([field_bundle.parent])
    assert bare.suitability("f_demo_01") is None
    assert bare.crop_history("f_demo_01").empty


def test_lookup_prefers_field_then_grid_then_none(sample_root):
    registry = BundleRegistry([sample_root])

    inside_field = registry.lookup(lat=49.144, lon=32.136)
    assert inside_field.unit_id == "f_demo_01" and inside_field.unit_type == "field"

    grid_only = registry.lookup(lat=49.05, lon=32.05)
    assert grid_only.unit_id == "g_0000" and grid_only.unit_type == "grid_cell"

    assert registry.lookup(lat=10.0, lon=10.0) is None


def test_showcase_features_are_map_ready(sample_root):
    features = BundleRegistry([sample_root]).showcase_features()
    assert len(features) == 3
    assert features[0]["geometry"]["type"] == "Polygon"
    assert {"unit_id", "name"} <= set(features[0]["properties"])
