"""Bundle contract, version 1.0.

A bundle is a directory of pre-processed Earth-observation features for a set
of units (showcase fields or national grid cells). These models are the single
source of truth for the contract: the validator reads its bounds from them and
the JSON Schemas handed to the geospatial scientists are generated from them.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0"
SUPPORTED_CONTRACT_VERSIONS = ("1.0",)

REQUIRED_FILES = ("manifest.json", "units.geojson", "timeseries.parquet", "static.parquet")
OPTIONAL_FILES = ("crop_history.csv", "suitability.csv")

# Values that satellite products use for "no data". They must never reach the
# contract tables: missing data is null.
SENTINELS = (-9999.0, -3000.0, -999.0, 32767.0, -32768.0, 65535.0)

UnitType = Literal["field", "grid_cell"]


class VariableSpec(BaseModel):
    unit: str
    lo: float
    hi: float
    expected_source: str


# Controlled vocabulary: variable name -> canonical unit and valid range.
VOCABULARY: dict[str, VariableSpec] = {
    "ndvi": VariableSpec(unit="unitless", lo=-1, hi=1, expected_source="MODIS MOD13Q1"),
    "evi": VariableSpec(unit="unitless", lo=-1, hi=1, expected_source="MODIS MOD13Q1"),
    "et": VariableSpec(unit="mm/day", lo=0, hi=20, expected_source="MODIS MOD16A2GF"),
    "sm_surface": VariableSpec(unit="m3/m3", lo=0, hi=1, expected_source="SMAP L4"),
    "sm_rootzone": VariableSpec(unit="m3/m3", lo=0, hi=1, expected_source="SMAP L4"),
    "precip": VariableSpec(unit="mm/day", lo=0, hi=500, expected_source="GPM IMERG"),
    "t2m_mean": VariableSpec(unit="degC", lo=-60, hi=60, expected_source="ERA5-Land"),
    "lst_day": VariableSpec(unit="degC", lo=-60, hi=80, expected_source="MODIS MOD11 / ECOSTRESS"),
}


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceEntry(_Row):
    variable: str
    product: str
    version: str
    native_res_m: float = Field(gt=0)
    date_start: dt.date | None = None
    date_end: dt.date | None = None


class Manifest(_Row):
    contract_version: str
    bundle_id: str = Field(min_length=1)
    unit_type: UnitType
    created_at: dt.datetime
    author: str = Field(min_length=1)
    sources: list[SourceEntry]
    notes: str = ""

    def source_for(self, variable: str) -> SourceEntry | None:
        for entry in self.sources:
            if entry.variable == variable:
                return entry
        return None


class UnitProperties(BaseModel):
    """Properties of one feature in units.geojson. Extra properties are allowed."""

    model_config = ConfigDict(extra="allow")

    unit_id: str = Field(min_length=1)
    unit_type: UnitType
    name: str | None = None
    area_ha: float | None = Field(default=None, ge=0)
    cropland_frac: float | None = Field(default=None, ge=0, le=1)


class TimeseriesRow(_Row):
    unit_id: str = Field(min_length=1)
    date: dt.date
    variable: str
    value: float | None
    std: float | None = Field(default=None, ge=0)
    valid_frac: float = Field(ge=0, le=1)
    source: str = Field(min_length=1)
    res_m: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_variable_and_range(self) -> "TimeseriesRow":
        spec = VOCABULARY.get(self.variable)
        if spec is None:
            raise ValueError(f"unknown variable '{self.variable}'; allowed: {sorted(VOCABULARY)}")
        if self.value is not None:
            if self.value in SENTINELS:
                raise ValueError(f"sentinel fill value {self.value}; missing data must be null")
            if not (spec.lo <= self.value <= spec.hi):
                raise ValueError(
                    f"{self.variable} value {self.value} outside valid range {spec.lo} to {spec.hi} {spec.unit}"
                )
        return self


class StaticRow(_Row):
    unit_id: str = Field(min_length=1)
    clay_pct: float = Field(ge=0, le=100)
    sand_pct: float = Field(ge=0, le=100)
    soc_pct: float = Field(ge=0, le=60)
    ph: float = Field(ge=2, le=11)
    slope_pct: float = Field(ge=0, le=500)
    elevation_m: float = Field(ge=-500, le=9000)
    awc_mm_per_m: float | None = Field(default=None, ge=0, le=400)
    k_factor: float | None = Field(default=None, ge=0, le=0.2)
    drainage_class: str | None = None


class CropHistoryRow(_Row):
    unit_id: str = Field(min_length=1)
    year: int = Field(ge=1980, le=2100)
    crop_id: str = Field(min_length=1)
    cover_frac: float = Field(ge=0, le=1)
    method: Literal["declared", "worldcereal", "ndvi_phenology"]
    confidence: float = Field(ge=0, le=1)


class SuitabilityRow(_Row):
    unit_id: str = Field(min_length=1)
    crop_id: str = Field(min_length=1)
    suitability_index: float = Field(ge=0, le=100)
    scenario: str = Field(min_length=1)
    water_supply: Literal["rainfed", "irrigated"]
    source: str = Field(min_length=1)


TIMESERIES_COLUMNS = tuple(TimeseriesRow.model_fields)
STATIC_REQUIRED_COLUMNS = tuple(
    name for name, f in StaticRow.model_fields.items() if f.is_required()
)
STATIC_OPTIONAL_COLUMNS = tuple(
    name for name, f in StaticRow.model_fields.items() if not f.is_required()
)


def numeric_bounds(model: type[BaseModel]) -> dict[str, tuple[float | None, float | None]]:
    """Inclusive (low, high) bounds declared on a model's numeric fields."""
    bounds: dict[str, tuple[float | None, float | None]] = {}
    for name, field in model.model_fields.items():
        lo = hi = None
        for meta in field.metadata:
            if getattr(meta, "ge", None) is not None:
                lo = meta.ge
            if getattr(meta, "gt", None) is not None:
                lo = meta.gt
            if getattr(meta, "le", None) is not None:
                hi = meta.le
            if getattr(meta, "lt", None) is not None:
                hi = meta.lt
        if lo is not None or hi is not None:
            bounds[name] = (lo, hi)
    return bounds


def schema_documents() -> dict[str, dict]:
    """JSON Schema documents published to the team, keyed by file name."""
    docs = {
        "manifest.schema.json": Manifest.model_json_schema(),
        "unit_properties.schema.json": UnitProperties.model_json_schema(),
        "timeseries_row.schema.json": TimeseriesRow.model_json_schema(),
        "static_row.schema.json": StaticRow.model_json_schema(),
        "crop_history_row.schema.json": CropHistoryRow.model_json_schema(),
        "suitability_row.schema.json": SuitabilityRow.model_json_schema(),
        "vocabulary.json": {
            "contract_version": CONTRACT_VERSION,
            "variables": {name: spec.model_dump() for name, spec in VOCABULARY.items()},
            "sentinels_rejected": list(SENTINELS),
        },
    }
    return docs
