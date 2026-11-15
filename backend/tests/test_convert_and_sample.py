import json

import numpy as np
import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from fieldshift.cli import app
from fieldshift.contracts.export import bundle_schema_texts
from fieldshift.ingest.convert import ConversionError, ConversionMapping, convert_table
from fieldshift.ingest.sample import FIELDS_ID, GRID_ID, generate_sample
from fieldshift.ingest.validator import validate_bundle
from fieldshift.settings import project_root

runner = CliRunner()

MAPPING = {
    "unit_id_column": "unit_id",
    "date_column": "date",
    "bands": {
        "NDVI": {"variable": "ndvi", "scale": 0.0001, "source": "MOD13Q1.061", "res_m": 250},
        "EVI": {"variable": "evi", "scale": 0.0001, "source": "MOD13Q1.061", "res_m": 250},
    },
}


def _wide(unit_ids):
    dates = pd.date_range("2024-01-01", periods=6, freq="16D")
    rows = []
    for unit_id in unit_ids:
        for i, date in enumerate(dates):
            rows.append({"system:index": f"{unit_id}_{i}", "unit_id": unit_id, "date": date.strftime("%Y-%m-%d"),
                         "NDVI": 2000 + 900 * i, "EVI": 1200 + 500 * i, ".geo": "{}"})
    return pd.DataFrame(rows)


def test_wide_table_is_converted_scaled_and_valid(grid_bundle):
    unit_ids = [f"g_{i:04d}" for i in range(20)]
    wide = _wide(unit_ids)
    wide.loc[0, "NDVI"] = -3000  # MODIS fill value becomes null
    long = convert_table(wide, ConversionMapping.model_validate(MAPPING))

    assert len(long) == len(wide) * 2
    assert not long.duplicated(["unit_id", "date", "variable"]).any()
    assert long["value"].dropna().between(-1, 1).all()
    assert long["value"].isna().sum() == 1
    assert set(long["variable"]) == {"ndvi", "evi"}

    long.to_parquet(grid_bundle / "timeseries.parquet", index=False)
    report = validate_bundle(grid_bundle)
    assert report.ok, report.render()


def test_unmapped_band_is_reported_not_dropped():
    wide = _wide(["g_0000"])
    wide["SummaryQA"] = 0
    with pytest.raises(ConversionError, match="SummaryQA"):
        convert_table(wide, ConversionMapping.model_validate(MAPPING))


def test_convert_command_exit_status(tmp_path):
    wide = _wide(["g_0000"])
    wide["SummaryQA"] = 0
    table, mapping, out = tmp_path / "export.csv", tmp_path / "mapping.yaml", tmp_path / "timeseries.parquet"
    wide.to_csv(table, index=False)
    mapping.write_text(yaml.safe_dump(MAPPING), encoding="utf-8")

    failed = runner.invoke(app, ["convert-gee", str(table), str(mapping), str(out)])
    assert failed.exit_code == 1 and not out.exists()

    wide.drop(columns="SummaryQA").to_csv(table, index=False)
    ok = runner.invoke(app, ["convert-gee", str(table), str(mapping), str(out)])
    assert ok.exit_code == 0, ok.output
    assert len(pd.read_parquet(out)) == 12


# --- Sample bundles ---

def _same(a, b):
    for bundle in (GRID_ID, FIELDS_ID):
        for name in ("manifest.json", "units.geojson"):
            assert json.loads((a / bundle / name).read_text("utf-8")) == json.loads((b / bundle / name).read_text("utf-8"))
        for name in ("timeseries.parquet", "static.parquet"):
            pd.testing.assert_frame_equal(pd.read_parquet(a / bundle / name), pd.read_parquet(b / bundle / name))
        pd.testing.assert_frame_equal(pd.read_csv(a / bundle / "suitability.csv"), pd.read_csv(b / bundle / "suitability.csv"))


def test_sample_bundles_are_valid_and_sized(sample_root):
    grid, fields = validate_bundle(sample_root / GRID_ID), validate_bundle(sample_root / FIELDS_ID)
    assert grid.ok, grid.render()
    assert fields.ok, fields.render()
    assert grid.stats["units"] >= 20 and fields.stats["units"] >= 3


def test_sample_regenerates_identically(sample_root, tmp_path):
    generate_sample(tmp_path)
    _same(sample_root, tmp_path)


def test_committed_sample_matches_the_generator(sample_root):
    committed = project_root() / "data" / "sample"
    assert (committed / GRID_ID).is_dir(), "run: uv run fieldshift make-sample"
    _same(sample_root, committed)


def test_sample_ndvi_has_a_winter_low_and_a_summer_peak(sample_root):
    ts = pd.read_parquet(sample_root / GRID_ID / "timeseries.parquet")
    ndvi = ts[(ts["variable"] == "ndvi") & (ts["unit_id"] == "g_0000")].dropna(subset=["value"])
    doy = pd.to_datetime(ndvi["date"]).dt.day_of_year
    assert ndvi.loc[doy < 40, "value"].median() < 0.30
    assert ndvi.loc[doy.between(140, 220), "value"].median() > 0.45
    assert np.isfinite(ndvi["value"]).all()


# --- Published schemas ---

def test_committed_bundle_schemas_are_current():
    target = project_root() / "contracts" / "bundle"
    for name, text in bundle_schema_texts().items():
        path = target / name
        assert path.exists(), f"{name} missing; run: uv run fieldshift export-schemas"
        assert path.read_text(encoding="utf-8") == text, f"{name} is stale; run: uv run fieldshift export-schemas"
