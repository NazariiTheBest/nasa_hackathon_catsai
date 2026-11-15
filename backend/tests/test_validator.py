import json

import pandas as pd
from typer.testing import CliRunner

from fieldshift.cli import app
from fieldshift.contracts.bundle import TIMESERIES_COLUMNS
from fieldshift.ingest.validator import validate_bundle

runner = CliRunner()


def _reasons(report, file=None):
    return [f"{v.where}: {v.reason}" for v in report.violations if file is None or v.file == file]


def _edit_ts(bundle, fn):
    path = bundle / "timeseries.parquet"
    df = pd.read_parquet(path)
    df = fn(df)
    df.to_parquet(path, index=False)


def _edit_json(path, fn):
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data), encoding="utf-8")


# --- Bundle structure ---

def test_complete_bundle_is_accepted(grid_bundle):
    report = validate_bundle(grid_bundle)
    assert report.ok, report.render()
    assert report.stats["units"] == 20
    assert "ndvi" in report.stats["variables"]
    assert report.stats["timeseries_rows"] > 0


def test_missing_required_file_is_named(grid_bundle):
    (grid_bundle / "static.parquet").unlink()
    report = validate_bundle(grid_bundle)
    assert not report.ok
    assert any(v.file == "static.parquet" and "missing" in v.reason for v in report.violations)


def test_unsupported_contract_version(grid_bundle):
    _edit_json(grid_bundle / "manifest.json", lambda d: d.update(contract_version="2.0"))
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "manifest.json"))
    assert "'2.0'" in reasons and "supported: 1.0" in reasons


# --- Unit identity and geometry ---

def test_duplicate_unit_identifiers(grid_bundle):
    def dup(d):
        d["features"][1]["properties"]["unit_id"] = d["features"][0]["properties"]["unit_id"]

    _edit_json(grid_bundle / "units.geojson", dup)
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "units.geojson"))
    assert "duplicate unit identifier" in reasons and "g_0000" in reasons


def test_coordinates_outside_wgs84(grid_bundle):
    def project(d):
        d["features"][0]["geometry"]["coordinates"] = [[[356600, 5430000], [357600, 5430000], [357600, 5431000], [356600, 5430000]]]

    _edit_json(grid_bundle / "units.geojson", project)
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "units.geojson"))
    assert "not in WGS84 longitude, latitude order" in reasons


# --- Time series ---

def test_unknown_variable_is_named_with_allowed_list(grid_bundle):
    def rename(df):
        df.loc[df.index[:3], "variable"] = "ndwi"
        return df

    _edit_ts(grid_bundle, rename)
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "timeseries.parquet"))
    assert "unknown variable(s): ndwi" in reasons and "allowed:" in reasons and "ndvi" in reasons


def test_additional_vocabulary_variable_needs_no_structural_change(grid_bundle):
    full = pd.read_parquet(grid_bundle / "timeseries.parquet")
    only_ndvi = full[full["variable"].isin(["ndvi", "evi"])]
    only_ndvi.to_parquet(grid_bundle / "timeseries.parquet", index=False)
    assert validate_bundle(grid_bundle).ok

    with_et = full[full["variable"].isin(["ndvi", "evi", "et"])]
    with_et.to_parquet(grid_bundle / "timeseries.parquet", index=False)
    assert validate_bundle(grid_bundle).ok
    assert tuple(only_ndvi.columns) == tuple(with_et.columns) == TIMESERIES_COLUMNS


def test_unscaled_satellite_integer_is_rejected(grid_bundle):
    def unscale(df):
        idx = df.index[(df["variable"] == "ndvi") & df["value"].notna()][0]
        df.loc[idx, "value"] = 4200.0
        return df

    _edit_ts(grid_bundle, unscale)
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "timeseries.parquet"))
    assert "outside valid range -1 to 1" in reasons and "scale factor" in reasons


def test_sentinel_fill_value_is_rejected(grid_bundle):
    def fill(df):
        df.loc[df.index[0], "value"] = -9999.0
        return df

    _edit_ts(grid_bundle, fill)
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "timeseries.parquet"))
    assert "missing data must be null" in reasons


# --- Referential integrity ---

def test_orphan_unit_identifier(grid_bundle):
    def ghost(df):
        df.loc[df.index[0], "unit_id"] = "ghost_unit"
        return df

    _edit_ts(grid_bundle, ghost)
    report = validate_bundle(grid_bundle)
    assert any(v.file == "timeseries.parquet" and "ghost_unit" in v.reason and "orphan" in v.reason
               for v in report.violations)


def test_unit_without_static_properties(grid_bundle):
    path = grid_bundle / "static.parquet"
    df = pd.read_parquet(path)
    df[df["unit_id"] != "g_0003"].to_parquet(path, index=False)
    reasons = " ".join(_reasons(validate_bundle(grid_bundle), "static.parquet"))
    assert "without static properties" in reasons and "g_0003" in reasons


# --- Validation report ---

def test_all_violations_are_reported_together_and_exit_status_fails(grid_bundle):
    def both(df):
        df.loc[df.index[0], "variable"] = "ndwi"
        df.loc[df.index[1], "unit_id"] = "ghost_unit"
        return df

    _edit_ts(grid_bundle, both)
    report = validate_bundle(grid_bundle)
    text = report.render()
    assert "unknown variable(s): ndwi" in text and "ghost_unit" in text

    result = runner.invoke(app, ["validate-bundle", str(grid_bundle)])
    assert result.exit_code == 1
    assert "INVALID" in result.output and "ndwi" in result.output and "ghost_unit" in result.output


def test_valid_bundle_exits_successfully(field_bundle):
    result = runner.invoke(app, ["validate-bundle", str(field_bundle)])
    assert result.exit_code == 0, result.output
    assert "VALID" in result.output


# --- Optional tables ---

def test_bundle_without_optional_tables(field_bundle):
    (field_bundle / "crop_history.csv").unlink()
    (field_bundle / "suitability.csv").unlink()
    assert validate_bundle(field_bundle).ok


def test_suitability_index_out_of_range(field_bundle):
    path = field_bundle / "suitability.csv"
    df = pd.read_csv(path)
    df.loc[0, "suitability_index"] = 140
    df.to_csv(path, index=False)
    reasons = " ".join(_reasons(validate_bundle(field_bundle), "suitability.csv"))
    assert "outside allowed range 0 to 100" in reasons


def test_optional_table_orphan_is_checked(field_bundle):
    path = field_bundle / "crop_history.csv"
    df = pd.read_csv(path)
    df.loc[0, "unit_id"] = "ghost_unit"
    df.to_csv(path, index=False)
    reasons = " ".join(_reasons(validate_bundle(field_bundle), "crop_history.csv"))
    assert "ghost_unit" in reasons
