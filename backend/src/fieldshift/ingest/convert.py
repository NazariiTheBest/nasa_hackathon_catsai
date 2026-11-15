"""Convert an Earth Engine export table into the contract's long format.

Earth Engine's natural export has one row per unit and image with one column
per band. A small mapping declares, for each band, the contract variable, the
scale factor, the source product and its native resolution.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from fieldshift.contracts.bundle import SENTINELS, TIMESERIES_COLUMNS, VOCABULARY


class BandMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable: str
    scale: float = 1.0
    offset: float = 0.0
    source: str = Field(min_length=1)
    res_m: int = Field(gt=0)
    std_column: str | None = None


class ConversionMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id_column: str = "unit_id"
    date_column: str = "date"
    valid_frac_column: str | None = None
    bands: dict[str, BandMapping]
    ignore_columns: list[str] = Field(default_factory=lambda: ["system:index", ".geo"])


class ConversionError(ValueError):
    pass


def load_mapping(path: str | Path) -> ConversionMapping:
    with open(path, encoding="utf-8") as fh:
        return ConversionMapping.model_validate(yaml.safe_load(fh))


def convert_table(wide: pd.DataFrame, mapping: ConversionMapping) -> pd.DataFrame:
    """Return a long-format frame with the contract's time-series columns."""
    for column in (mapping.unit_id_column, mapping.date_column):
        if column not in wide.columns:
            raise ConversionError(f"input table has no '{column}' column")
    for band, spec in mapping.bands.items():
        if band not in wide.columns:
            raise ConversionError(f"mapped band column '{band}' is not in the input table")
        if spec.variable not in VOCABULARY:
            raise ConversionError(
                f"band '{band}' maps to unknown variable '{spec.variable}'; allowed: {', '.join(sorted(VOCABULARY))}"
            )

    known = {mapping.unit_id_column, mapping.date_column, *mapping.bands, *mapping.ignore_columns}
    if mapping.valid_frac_column:
        known.add(mapping.valid_frac_column)
    known.update(s.std_column for s in mapping.bands.values() if s.std_column)
    unmapped = [c for c in wide.columns if c not in known]
    if unmapped:
        raise ConversionError(
            "unmapped column(s) in the input table: "
            + ", ".join(unmapped)
            + ". Map each one under 'bands' or list it under 'ignore_columns'."
        )

    dates = wide[mapping.date_column]
    if pd.api.types.is_numeric_dtype(dates):
        dates = pd.to_datetime(dates, unit="ms")  # Earth Engine system:time_start
    else:
        dates = pd.to_datetime(dates)
    unit_ids = wide[mapping.unit_id_column].astype(str)
    if mapping.valid_frac_column:
        valid_frac = pd.to_numeric(wide[mapping.valid_frac_column], errors="coerce")
    else:
        valid_frac = None

    frames = []
    for band, spec in mapping.bands.items():
        raw = pd.to_numeric(wide[band], errors="coerce")
        raw = raw.mask(raw.isin(SENTINELS))
        value = raw * spec.scale + spec.offset
        std = None
        if spec.std_column:
            std = pd.to_numeric(wide[spec.std_column], errors="coerce") * abs(spec.scale)
        frame = pd.DataFrame(
            {
                "unit_id": unit_ids,
                "date": dates.dt.date,
                "variable": spec.variable,
                "value": value,
                "std": std if std is not None else float("nan"),
                "valid_frac": valid_frac if valid_frac is not None else value.notna().astype(float),
                "source": spec.source,
                "res_m": spec.res_m,
            }
        )
        frame.loc[frame["value"].isna(), "valid_frac"] = 0.0
        frames.append(frame)

    long = pd.concat(frames, ignore_index=True)
    long["res_m"] = long["res_m"].astype("int32")
    long["std"] = long["std"].astype("float64")
    return long[list(TIMESERIES_COLUMNS)].sort_values(["unit_id", "variable", "date"], ignore_index=True)


def convert_file(input_path: str | Path, mapping_path: str | Path, output_path: str | Path) -> pd.DataFrame:
    input_path = Path(input_path)
    if input_path.suffix.lower() == ".parquet":
        wide = pd.read_parquet(input_path)
    else:
        wide = pd.read_csv(input_path)
    long = convert_table(wide, load_mapping(mapping_path))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    long.to_parquet(output_path, index=False)
    return long
