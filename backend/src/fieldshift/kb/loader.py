"""Crop knowledge base: trait model, validation and loading from kb/crops.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fieldshift.settings import kb_path

Stage = Literal["ini", "dev", "mid", "late"]
STAGES: tuple[str, ...] = ("ini", "dev", "mid", "late")
Lang = Literal["en", "uk"]


class KnowledgeBaseError(ValueError):
    """The knowledge base file is missing, malformed or holds invalid values."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CropName(_Strict):
    en: str = Field(min_length=1)
    uk: str = Field(min_length=1)


class CropCoefficients(_Strict):
    ini: float = Field(ge=0, le=1.5)
    mid: float = Field(ge=0, le=1.5)
    end: float = Field(ge=0, le=1.5)


class HeatThreshold(_Strict):
    stage: Stage
    tmax_c: float = Field(ge=15, le=50)


class ColdThreshold(_Strict):
    stage: Stage
    tmin_c: float = Field(ge=-45, le=10)


class CropStress(_Strict):
    heat: HeatThreshold | None = None
    frost: ColdThreshold | None = None
    winterkill: ColdThreshold | None = None


class Crop(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: CropName
    family: str = Field(min_length=1)
    role: Literal["cash", "cover", "forage"]
    season: Literal["winter", "spring"]
    drought_alternative: bool = False
    sowing_window_doy: tuple[int, int]
    default_sow_doy: int = Field(ge=1, le=366)
    t_base_c: float = Field(ge=-5, le=20)
    gdd_to_maturity: float = Field(gt=0, le=6000)
    stages_days: tuple[int, int, int, int]
    kc: CropCoefficients
    root_depth_m: float = Field(ge=0.1, le=3.0)
    depletion_fraction: float = Field(ge=0.1, le=0.9)
    stress: CropStress
    drought_tolerance: float = Field(ge=0, le=1)
    n_fixation_kg_ha: float = Field(ge=0, le=400)
    residue_cover: float = Field(ge=0, le=1)
    forage_value: float = Field(ge=0, le=1)
    market_value: float = Field(ge=0, le=1)
    min_return_years: int = Field(ge=1, le=12)
    irrigation_required: bool
    sources: list[str] = Field(min_length=1)
    review_status: Literal["draft", "reviewed"]
    notes: str = ""

    @model_validator(mode="after")
    def _check_calendar(self) -> "Crop":
        start, end = self.sowing_window_doy
        for doy in (start, end):
            if not 1 <= doy <= 366:
                raise ValueError(f"sowing_window_doy value {doy} is outside the allowed range 1 to 366")
        if start >= end:
            raise ValueError(f"sowing_window_doy start {start} must precede its end {end}")
        if not start <= self.default_sow_doy <= end:
            raise ValueError(f"default_sow_doy {self.default_sow_doy} is outside the sowing window {start} to {end}")
        if any(d <= 0 for d in self.stages_days):
            raise ValueError("stages_days must be four positive day counts")
        if self.season == "winter" and self.role != "cover" and self.stress.winterkill is None:
            raise ValueError("a winter crop must define a winterkill threshold")
        return self

    @property
    def is_legume(self) -> bool:
        return self.family == "fabaceae"

    @property
    def season_days(self) -> int:
        return sum(self.stages_days)


class KnowledgeBase:
    def __init__(self, crops: list[Crop]):
        self.crops: dict[str, Crop] = {c.id: c for c in crops}

    def __contains__(self, crop_id: str) -> bool:
        return crop_id in self.crops

    def __len__(self) -> int:
        return len(self.crops)

    def get(self, crop_id: str) -> Crop:
        return self.crops[crop_id]

    def name(self, crop_id: str, lang: str = "en") -> str:
        crop = self.crops.get(crop_id)
        if crop is None:
            return crop_id
        return crop.name.uk if lang == "uk" else crop.name.en

    def by_role(self, *roles: str) -> list[Crop]:
        return [c for c in self.crops.values() if c.role in roles]

    def catalog(self, lang: str = "en") -> list[dict]:
        """The crop list as exposed to clients, with names in the requested language."""
        return [
            {
                "id": c.id,
                "name": self.name(c.id, lang),
                "role": c.role,
                "family": c.family,
                "season": c.season,
                "is_legume": c.is_legume,
                "drought_alternative": c.drought_alternative,
                "min_return_years": c.min_return_years,
                "review_status": c.review_status,
            }
            for c in self.crops.values()
        ]


def _describe(crop_id: str, err: ValidationError) -> list[str]:
    lines = []
    for e in err.errors():
        trait = ".".join(str(p) for p in e["loc"]) or "(record)"
        if e["type"] == "missing":
            lines.append(f"crop '{crop_id}': required trait '{trait}' is missing")
        else:
            lines.append(f"crop '{crop_id}': trait '{trait}': {e['msg']}")
    return lines


def parse_kb(records: object) -> KnowledgeBase:
    if not isinstance(records, list) or not records:
        raise KnowledgeBaseError("the knowledge base must be a non-empty list of crop records")
    crops: list[Crop] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, record in enumerate(records):
        crop_id = record.get("id", f"#{i + 1}") if isinstance(record, dict) else f"#{i + 1}"
        try:
            crop = Crop.model_validate(record)
        except ValidationError as err:
            problems += _describe(str(crop_id), err)
            continue
        if crop.id in seen:
            problems.append(f"crop '{crop.id}': duplicate crop identifier")
        seen.add(crop.id)
        crops.append(crop)
    if problems:
        raise KnowledgeBaseError("invalid knowledge base:\n  " + "\n  ".join(problems))
    return KnowledgeBase(crops)


def load_kb(path: Path | None = None) -> KnowledgeBase:
    path = Path(path) if path else kb_path()
    try:
        with open(path, encoding="utf-8") as fh:
            records = yaml.safe_load(fh)
    except OSError as exc:
        raise KnowledgeBaseError(f"knowledge base file cannot be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise KnowledgeBaseError(f"knowledge base file is not valid YAML: {exc}") from exc
    return parse_kb(records)
