import datetime as dt

import pytest
from pydantic import ValidationError

from fieldshift.contracts.bundle import (
    CropHistoryRow,
    Manifest,
    StaticRow,
    SuitabilityRow,
    TimeseriesRow,
    UnitProperties,
    numeric_bounds,
)

TS = dict(unit_id="u1", date=dt.date(2020, 1, 1), variable="ndvi", value=0.4, std=0.05,
          valid_frac=0.9, source="MOD13Q1.061", res_m=250)
STATIC = dict(unit_id="u1", clay_pct=30, sand_pct=25, soc_pct=2.0, ph=6.8, slope_pct=2.0, elevation_m=150)
HISTORY = dict(unit_id="u1", year=2024, crop_id="maize", cover_frac=1.0, method="declared", confidence=1.0)
SUIT = dict(unit_id="u1", crop_id="maize", suitability_index=70, scenario="historical",
            water_supply="rainfed", source="GAEZ v4")
MANIFEST = dict(contract_version="1.0", bundle_id="b", unit_type="field", created_at="2026-11-14T00:00:00Z",
                author="me", sources=[dict(variable="ndvi", product="MOD13Q1", version="061", native_res_m=250)])
UNIT = dict(unit_id="u1", unit_type="field", area_ha=80.0)


@pytest.mark.parametrize(
    "model, valid, bad",
    [
        (TimeseriesRow, TS, {"value": 4200}),
        (TimeseriesRow, TS, {"valid_frac": 1.4}),
        (StaticRow, STATIC, {"clay_pct": 140}),
        (CropHistoryRow, HISTORY, {"cover_frac": 2.0}),
        (SuitabilityRow, SUIT, {"suitability_index": 140}),
        (Manifest, MANIFEST, {"sources": [dict(variable="ndvi", product="p", version="1", native_res_m=-5)]}),
        (UnitProperties, UNIT, {"cropland_frac": 1.7}),
    ],
)
def test_models_accept_valid_and_reject_out_of_range(model, valid, bad):
    assert model.model_validate(valid)
    with pytest.raises(ValidationError):
        model.model_validate({**valid, **bad})


def test_timeseries_row_rejects_unknown_variable_and_sentinel():
    with pytest.raises(ValidationError, match="unknown variable"):
        TimeseriesRow.model_validate({**TS, "variable": "ndwi"})
    with pytest.raises(ValidationError, match="must be null"):
        TimeseriesRow.model_validate({**TS, "value": -9999})
    assert TimeseriesRow.model_validate({**TS, "value": None}).value is None


def test_numeric_bounds_are_read_from_the_model():
    bounds = numeric_bounds(StaticRow)
    assert bounds["clay_pct"] == (0, 100)
    assert bounds["ph"] == (2, 11)
