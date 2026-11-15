"""HTTP API contract. TypeScript types for the UI are generated from these models."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Lang = Literal["en", "uk"]
DataTier = Literal["field", "grid", "climate_only"]
Hazard = Literal["heat", "frost", "winterkill", "drought"]
Confidence = Literal["high", "medium", "low"]
EvidenceScope = Literal["field", "grid_cell", "climate_cell", "rotation"]

OBJECTIVES = ("water", "nitrogen", "erosion", "organic_matter", "forage", "income", "resilience", "pest_break")
PRIORITY_OBJECTIVES = OBJECTIVES[:6]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------- Requests

class PointLocation(_Request):
    type: Literal["point"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class UnitLocation(_Request):
    type: Literal["unit"]
    unit_id: str = Field(min_length=1)


class PolygonLocation(_Request):
    type: Literal["polygon"]
    geometry: dict[str, Any] = Field(description="GeoJSON Polygon or MultiPolygon in WGS84")


Location = Annotated[Union[PointLocation, UnitLocation, PolygonLocation], Field(discriminator="type")]


class CoverCrop(_Request):
    after_index: int = Field(ge=0, description="Position in `crops` of the main crop the cover crop follows")
    crop_id: str = Field(min_length=1)


class Baseline(_Request):
    crops: list[str] = Field(min_length=1, max_length=8, description="Main crops in rotation order")
    covers: list[CoverCrop] = Field(default_factory=list)


class Priorities(_Request):
    water: float = Field(0.5, ge=0, le=1)
    nitrogen: float = Field(0.5, ge=0, le=1)
    erosion: float = Field(0.5, ge=0, le=1)
    organic_matter: float = Field(0.5, ge=0, le=1)
    forage: float = Field(0.0, ge=0, le=1)
    income: float = Field(0.5, ge=0, le=1)


class Constraints(_Request):
    irrigation_available: bool = False
    excluded_crops: list[str] = Field(default_factory=list)
    max_cycle_years: int = Field(5, ge=1, le=8)


class AnalyzeRequest(_Request):
    location: Location
    baseline: Baseline
    priorities: Priorities = Field(default_factory=Priorities)
    constraints: Constraints = Field(default_factory=Constraints)
    lang: Lang = "en"


# ---------------------------------------------------------------- Responses

class Notice(BaseModel):
    code: str
    text: str


class DayRef(BaseModel):
    year_index: int = Field(description="Cycle year, starting at 0")
    doy: int = Field(description="Day of year, 1-365")


class UnitSummary(BaseModel):
    unit_id: str
    unit_type: Literal["field", "grid_cell"]
    name: str | None = None
    bundle_id: str
    area_ha: float | None = None


class Slot(BaseModel):
    crop_id: str
    crop_name: str
    role: Literal["main", "cover"]
    sow: DayRef
    harvest: DayRef
    days: int
    clamped: bool = False


class BareWindow(BaseModel):
    start: DayRef
    end: DayRef
    days: int
    after_crop_id: str
    after_crop_name: str
    erosive_rain_mm: float = Field(description="Mean erosive rainfall falling inside the window")
    erosion_exposure: float = Field(ge=0, le=1)
    rain_only: bool = Field(description="True when slope and erodibility were unavailable")


class LowCoverPeriod(BaseModel):
    start_doy: int
    end_doy: int
    median_ndvi: float
    years: int
    source: str
    resolution: str


class StressEntry(BaseModel):
    crop_id: str
    crop_name: str
    hazard: Hazard
    hazard_label: str
    stage: str
    stage_label: str
    window_start_doy: int
    window_end_doy: int
    probability: float
    years_hit: int
    years_total: int


class WaterBalanceEntry(BaseModel):
    crop_id: str
    crop_name: str
    demand_mm: float
    supply_mm: float
    deficit_mm: float


class Trend(BaseModel):
    indicator: str
    label: str
    unit: str
    slope_per_decade: float
    p_value: float
    significant: bool
    period: str
    n_years: int
    source: str
    scope: EvidenceScope


class YearAnomaly(BaseModel):
    year: int
    anomaly: float


class Anomaly(BaseModel):
    variable: str
    label: str
    unit: str
    period: str
    n_years: int
    mean: float
    recent: list[YearAnomaly]
    source: str


class SoilInfo(BaseModel):
    awc_mm_per_m: float
    awc_status: Literal["supplied", "derived", "assumed"]
    k_factor: float | None = None
    k_status: Literal["supplied", "derived", "unavailable"]
    slope_pct: float | None = None
    clay_pct: float | None = None
    sand_pct: float | None = None
    soc_pct: float | None = None
    ph: float | None = None
    source: str | None = None


class ClimateInfo(BaseModel):
    source: str
    spatial_resolution: str
    period: str
    years: int
    cell_lat: float
    cell_lon: float
    retrieved_at: dt.datetime
    et0_fallback_days: int = Field(description="Days on which a temperature-based estimate replaced Penman-Monteith")
    filled_days: int = Field(description="Days with a missing input filled from the day-of-year mean")


class Site(BaseModel):
    data_tier: DataTier
    lat: float
    lon: float
    unit: UnitSummary | None = None
    bare_windows: list[BareWindow]
    observed_low_cover: list[LowCoverPeriod]
    stress: list[StressEntry]
    water_balance: list[WaterBalanceEntry]
    trends: list[Trend]
    anomalies: list[Anomaly]
    soil: SoilInfo
    climate: ClimateInfo
    information_gaps: list[Notice]


class ScoreSummary(BaseModel):
    median: float
    p10: float
    p90: float
    windows: int


class Scores(BaseModel):
    overall: ScoreSummary
    objectives: dict[str, float]


class Metrics(BaseModel):
    water_demand_mm_per_year: float
    water_met_share: float
    bare_days_per_year: float
    n_kg_ha_per_year: float
    erosive_rain_on_bare_mm_per_year: float
    crop_families: int


class VsBaseline(BaseModel):
    objectives: dict[str, float]
    water_demand_mm_per_year: float
    bare_days_per_year: float
    n_kg_ha_per_year: float


class Evidence(BaseModel):
    indicator: str
    label: str
    value: float
    unit: str
    source: str
    period: str
    resolution: str
    scope: EvidenceScope
    method: str


class Statement(BaseModel):
    """One explanation entry. `indicator` and `value` point at the evidence that backs a number."""

    code: str
    text: str
    indicator: str | None = None
    value: float | None = None
    unit: str | None = None


class Strategy(BaseModel):
    id: str
    label: str
    is_baseline: bool
    operators: list[str]
    cycle_years: int
    slots: list[Slot]
    scores: Scores
    metrics: Metrics
    vs_baseline: VsBaseline | None = None
    confidence: Confidence
    retains_return_violation: list[str] = Field(default_factory=list)
    why: list[Statement]
    evidence: list[Evidence]
    benefits: list[Statement]
    gaps: list[Statement]
    local_review: list[Statement]


class Meta(BaseModel):
    contract_version: str
    engine_version: str
    data_tier: DataTier
    generated_at: dt.datetime
    lang: Lang
    notices: list[Notice]


class AnalyzeResponse(BaseModel):
    meta: Meta
    site: Site
    strategies: list[Strategy]


class LocateResponse(BaseModel):
    lat: float
    lon: float
    data_tier: DataTier
    unit: UnitSummary | None = None
    climate_cached: bool


class CropEntry(BaseModel):
    id: str
    name: str
    role: Literal["cash", "cover", "forage"]
    family: str
    season: Literal["winter", "spring"]
    is_legume: bool
    drought_alternative: bool
    min_return_years: int
    review_status: Literal["draft", "reviewed"]


class CropCatalog(BaseModel):
    lang: Lang
    crops: list[CropEntry]


class ShowcaseResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]]


class BundleInfo(BaseModel):
    bundle_id: str
    unit_type: str
    units: int
    author: str
    notes: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    engine_version: str
    contract_version: str
    bundles: list[BundleInfo]
    rejected_bundles: list[str]
    crops: int
    crops_reviewed: int
    climate_cells_cached: int


class ErrorResponse(BaseModel):
    code: str
    message: str
