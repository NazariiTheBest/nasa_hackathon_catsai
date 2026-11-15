"""Project paths and the non-crop engine configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


def project_root() -> Path:
    """Repository root. Override with the FIELDSHIFT_ROOT environment variable."""
    env = os.environ.get("FIELDSHIFT_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


def kb_path() -> Path:
    return project_root() / "kb" / "crops.yaml"


def engine_config_path() -> Path:
    return project_root() / "config" / "engine.yaml"


def cache_dir() -> Path:
    return Path(os.environ.get("FIELDSHIFT_CACHE", project_root() / "data" / "cache" / "power"))


def bundle_dirs() -> list[Path]:
    """Directories whose sub-directories are bundles.

    Real bundles in data/bundles take precedence; the committed sample is used
    when no real bundle is present. FIELDSHIFT_BUNDLES overrides both.
    """
    env = os.environ.get("FIELDSHIFT_BUNDLES")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]
    real = project_root() / "data" / "bundles"
    if real.is_dir() and any(p.is_dir() for p in real.iterdir()):
        return [real]
    return [project_root() / "data" / "sample"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoreWeights(_Strict):
    priorities_share: float = Field(0.8, ge=0, le=1)
    resilience_share: float = Field(0.1, ge=0, le=1)
    pest_break_share: float = Field(0.1, ge=0, le=1)


class YieldLoss(_Strict):
    water: float = Field(1.0, ge=0)
    heat: float = Field(0.15, ge=0, le=1)
    frost: float = Field(0.20, ge=0, le=1)
    winterkill: float = Field(0.40, ge=0, le=1)


class StressWeights(_Strict):
    heat: float = Field(0.5, ge=0, le=1)
    frost: float = Field(0.5, ge=0, le=1)
    winterkill: float = Field(0.7, ge=0, le=1)
    drought: float = Field(0.6, ge=0, le=1)


class EngineConfig(_Strict):
    """Thresholds that are not crop-specific. Unknown keys are rejected."""

    bare_ndvi_threshold: float = Field(0.30, ge=-1, le=1)
    hot_day_tmax_c: float = 30.0
    erosive_rain_mm: float = Field(10.0, gt=0)
    erosive_rain_ref_mm: float = Field(300.0, gt=0)
    min_bare_window_days: int = Field(60, ge=1)
    min_cover_growth_days: int = Field(45, ge=1)
    turnaround_days: int = Field(7, ge=0)
    cover_termination_lead_days: int = Field(14, ge=0)
    baseline_clamp_tolerance_days: int = Field(45, ge=0)
    heat_units_min_share: float = Field(0.8, ge=0, le=1)
    suitability_floor: float = Field(25.0, ge=0, le=100)
    drought_run_days: int = Field(10, ge=1)
    drought_stress_ks: float = Field(0.5, gt=0, le=1)
    heat_event_min_days: int = Field(3, ge=1)
    default_awc_mm_per_m: float = Field(140.0, gt=0)
    bare_soil_kc: float = Field(0.20, ge=0, le=1.5)
    bare_soil_depth_m: float = Field(0.4, gt=0)
    dormancy_kc: float = Field(0.4, ge=0, le=1.5)
    max_candidates: int = Field(100, ge=1)
    alternatives_returned: int = Field(3, ge=2)
    n_fixation_cap_kg_ha: float = Field(100.0, gt=0)
    confidence_interval_width: float = Field(0.15, gt=0)
    neutral_terrain_factor: float = Field(0.7, gt=0, le=1)
    cover_cost_income: float = Field(0.03, ge=0, le=1)
    short_record_years: int = Field(15, ge=2)
    weights: ScoreWeights = ScoreWeights()
    yield_loss: YieldLoss = YieldLoss()
    stress_weights: StressWeights = StressWeights()
    family_min_return_years: dict[str, int] = Field(default_factory=lambda: {"default": 2, "poaceae": 1})

    def family_interval(self, family: str) -> int:
        return self.family_min_return_years.get(family, self.family_min_return_years.get("default", 2))


def load_engine_config(path: Path | None = None) -> EngineConfig:
    path = path or engine_config_path()
    if not path.exists():
        return EngineConfig()
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return EngineConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_engine_config() -> EngineConfig:
    return load_engine_config()
