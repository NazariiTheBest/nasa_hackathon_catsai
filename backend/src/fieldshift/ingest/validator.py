"""Standalone bundle validator.

Reports every violation it finds, each with the file, the affected field or
rows and the reason. Table checks are vectorized so a national grid bundle of
about ten million rows validates in seconds.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pydantic import BaseModel, ValidationError

from fieldshift.contracts.bundle import (
    REQUIRED_FILES,
    SENTINELS,
    STATIC_OPTIONAL_COLUMNS,
    STATIC_REQUIRED_COLUMNS,
    SUPPORTED_CONTRACT_VERSIONS,
    TIMESERIES_COLUMNS,
    VOCABULARY,
    CropHistoryRow,
    Manifest,
    StaticRow,
    SuitabilityRow,
    UnitProperties,
    numeric_bounds,
)

MAX_EXAMPLES = 5


@dataclass
class Violation:
    file: str
    where: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.file}] {self.where}: {self.reason}"


@dataclass
class ValidationReport:
    bundle: str
    violations: list[Violation] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations

    def add(self, file: str, where: str, reason: str) -> None:
        self.violations.append(Violation(file, where, reason))

    def render(self) -> str:
        lines = [f"Bundle: {self.bundle}"]
        if self.ok:
            lines.append("Result: VALID")
        else:
            lines.append(f"Result: INVALID ({len(self.violations)} violation(s))")
            lines += [f"  - {v}" for v in self.violations]
        for key, value in self.stats.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)


def _rows(mask: pd.Series | np.ndarray) -> str:
    """Describe the rows selected by a boolean mask."""
    idx = np.flatnonzero(np.asarray(mask))
    shown = ", ".join(str(i) for i in idx[:MAX_EXAMPLES])
    more = f" (+{len(idx) - MAX_EXAMPLES} more)" if len(idx) > MAX_EXAMPLES else ""
    return f"{len(idx)} row(s), e.g. row {shown}{more}"


def _pydantic_violations(report: ValidationReport, file: str, prefix: str, err: ValidationError) -> None:
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        report.add(file, f"{prefix}{loc}", e["msg"])


def _check_manifest(path: Path, report: ValidationReport) -> Manifest | None:
    name = "manifest.json"
    try:
        data = json.loads((path / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.add(name, "file", f"cannot be read as JSON: {exc}")
        return None
    try:
        manifest = Manifest.model_validate(data)
    except ValidationError as err:
        _pydantic_violations(report, name, "", err)
        return None
    if manifest.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        report.add(
            name,
            "contract_version",
            f"declared contract version '{manifest.contract_version}' is not supported; "
            f"supported: {', '.join(SUPPORTED_CONTRACT_VERSIONS)}",
        )
    return manifest


def _iter_positions(coords):
    if coords and isinstance(coords[0], (int, float)):
        yield coords
    else:
        for part in coords or []:
            yield from _iter_positions(part)


def _check_units(path: Path, report: ValidationReport, manifest: Manifest | None) -> set[str] | None:
    name = "units.geojson"
    try:
        data = json.loads((path / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.add(name, "file", f"cannot be read as JSON: {exc}")
        return None
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        report.add(name, "type", "must be a GeoJSON FeatureCollection")
        return None

    ids: list[str] = []
    for i, feature in enumerate(data["features"]):
        where = f"features[{i}]"
        try:
            props = UnitProperties.model_validate(feature.get("properties") or {})
        except ValidationError as err:
            _pydantic_violations(report, name, f"{where}.properties.", err)
            continue
        ids.append(props.unit_id)
        where = f"unit '{props.unit_id}'"
        if manifest is not None and props.unit_type != manifest.unit_type:
            report.add(name, where, f"unit_type '{props.unit_type}' differs from manifest unit_type '{manifest.unit_type}'")
        geom = feature.get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            report.add(name, where, f"geometry type must be Polygon or MultiPolygon, found {geom.get('type')!r}")
            continue
        for pos in _iter_positions(geom.get("coordinates")):
            if len(pos) < 2 or not (-180 <= pos[0] <= 180 and -90 <= pos[1] <= 90):
                report.add(
                    name,
                    where,
                    f"geometry is not in WGS84 longitude, latitude order (found x={pos[0]}, y={pos[1] if len(pos) > 1 else None})",
                )
                break

    for unit_id, count in Counter(ids).items():
        if count > 1:
            report.add(name, f"unit '{unit_id}'", f"duplicate unit identifier (appears {count} times)")
    report.stats["units"] = len(set(ids))
    return set(ids)


def _check_orphans(report: ValidationReport, file: str, table_ids: pd.Series, unit_ids: set[str] | None) -> None:
    if unit_ids is None:
        return
    orphans = sorted(set(map(str, pd.unique(table_ids.dropna()))) - unit_ids)
    if orphans:
        shown = ", ".join(orphans[:MAX_EXAMPLES])
        more = f" (+{len(orphans) - MAX_EXAMPLES} more)" if len(orphans) > MAX_EXAMPLES else ""
        report.add(file, "unit_id", f"orphan unit identifier(s) not present in units.geojson: {shown}{more}")


def _check_bounds(report: ValidationReport, file: str, df: pd.DataFrame, model: type[BaseModel]) -> None:
    for column, (lo, hi) in numeric_bounds(model).items():
        if column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        sentinel = values.isin(SENTINELS)
        if sentinel.any():
            report.add(file, f"{column}: {_rows(sentinel)}", "sentinel fill value found; missing data must be null")
        bad = values.notna() & ~sentinel
        if lo is not None:
            bad_lo = bad & (values < lo)
        else:
            bad_lo = bad & False
        bad_hi = bad & (values > hi) if hi is not None else bad & False
        out = bad_lo | bad_hi
        if out.any():
            report.add(file, f"{column}: {_rows(out)}", f"value outside allowed range {lo} to {hi}")


def _check_timeseries(path: Path, report: ValidationReport, unit_ids: set[str] | None) -> None:
    name = "timeseries.parquet"
    try:
        df = pq.read_table(path / name).to_pandas(strings_to_categorical=True)
    except Exception as exc:  # pyarrow raises several unrelated types
        report.add(name, "file", f"cannot be read as Parquet: {exc}")
        return
    missing = [c for c in TIMESERIES_COLUMNS if c not in df.columns]
    extra = [c for c in df.columns if c not in TIMESERIES_COLUMNS]
    if extra:
        report.add(name, "columns", f"unexpected column(s): {', '.join(extra)}")
    if missing:
        report.add(name, "columns", f"missing required column(s): {', '.join(missing)}")
        return

    report.stats["timeseries_rows"] = len(df)
    if not (isinstance(df["unit_id"].dtype, pd.CategoricalDtype) or df["unit_id"].dtype == object):
        report.add(name, "unit_id", f"must be a string column, found {df['unit_id'].dtype}")
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        dates = pd.to_datetime(df["date"], errors="coerce")
        if dates.isna().any():
            report.add(name, f"date: {_rows(dates.isna())}", "not a valid date")

    variables = df["variable"].astype(str)
    present = sorted(variables.unique())
    report.stats["variables"] = ", ".join(present)
    unknown = [v for v in present if v not in VOCABULARY]
    if unknown:
        report.add(
            name,
            "variable",
            f"unknown variable(s): {', '.join(unknown)}; allowed: {', '.join(sorted(VOCABULARY))}",
        )

    values = pd.to_numeric(df["value"], errors="coerce")
    sentinel = values.isin(SENTINELS)
    if sentinel.any():
        report.add(name, f"value: {_rows(sentinel)}", "sentinel fill value found; missing data must be null")
    for var in present:
        spec = VOCABULARY.get(var)
        if spec is None:
            continue
        out = (variables == var) & values.notna() & ~sentinel & ((values < spec.lo) | (values > spec.hi))
        if out.any():
            hint = ""
            if var in ("ndvi", "evi"):
                hint = "; a scale factor was probably not applied (MODIS indices are stored multiplied by 10000)"
            report.add(
                name,
                f"value ({var}): {_rows(out)}",
                f"outside valid range {spec.lo:g} to {spec.hi:g} {spec.unit}{hint}",
            )

    valid = pd.to_numeric(df["valid_frac"], errors="coerce")
    bad_valid = valid.isna() | (valid < 0) | (valid > 1)
    if bad_valid.any():
        report.add(name, f"valid_frac: {_rows(bad_valid)}", "must be between 0 and 1")
    std = pd.to_numeric(df["std"], errors="coerce")
    if (std < 0).any():
        report.add(name, f"std: {_rows(std < 0)}", "must not be negative")
    res = pd.to_numeric(df["res_m"], errors="coerce")
    if (res.isna() | (res <= 0)).any():
        report.add(name, f"res_m: {_rows(res.isna() | (res <= 0))}", "must be a positive number of meters")
    source = df["source"].astype(str)
    empty_source = df["source"].isna() | (source.str.len() == 0)
    if empty_source.any():
        report.add(name, f"source: {_rows(empty_source)}", "must name the source product")

    dup = df.duplicated(["unit_id", "date", "variable"])
    if dup.any():
        report.add(name, f"{_rows(dup)}", "duplicate row for the same unit, date and variable")
    _check_orphans(report, name, df["unit_id"], unit_ids)


def _check_static(path: Path, report: ValidationReport, unit_ids: set[str] | None) -> None:
    name = "static.parquet"
    try:
        df = pq.read_table(path / name).to_pandas()
    except Exception as exc:
        report.add(name, "file", f"cannot be read as Parquet: {exc}")
        return
    missing = [c for c in STATIC_REQUIRED_COLUMNS if c not in df.columns]
    extra = [c for c in df.columns if c not in STATIC_REQUIRED_COLUMNS + STATIC_OPTIONAL_COLUMNS]
    if extra:
        report.add(name, "columns", f"unexpected column(s): {', '.join(extra)}")
    if missing:
        report.add(name, "columns", f"missing required column(s): {', '.join(missing)}")
        return
    for column in STATIC_REQUIRED_COLUMNS:
        if column != "unit_id" and df[column].isna().any():
            report.add(name, f"{column}: {_rows(df[column].isna())}", "required value is missing")
    _check_bounds(report, name, df, StaticRow)
    ids = df["unit_id"].astype(str)
    for unit_id, count in Counter(ids).items():
        if count > 1:
            report.add(name, f"unit '{unit_id}'", f"has {count} rows; exactly one is required")
    _check_orphans(report, name, df["unit_id"], unit_ids)
    if unit_ids is not None:
        absent = sorted(unit_ids - set(ids))
        if absent:
            shown = ", ".join(absent[:MAX_EXAMPLES])
            more = f" (+{len(absent) - MAX_EXAMPLES} more)" if len(absent) > MAX_EXAMPLES else ""
            report.add(name, "unit_id", f"unit(s) without static properties: {shown}{more}")


def _literal_choices(model: type[BaseModel]) -> dict[str, tuple[str, ...]]:
    choices = {}
    for field_name, info in model.model_fields.items():
        args = get_args(info.annotation)
        if args and all(isinstance(a, str) for a in args):
            choices[field_name] = args
    return choices


def _check_csv(path: Path, name: str, model: type[BaseModel], report: ValidationReport, unit_ids: set[str] | None) -> None:
    if not (path / name).exists():
        return
    try:
        df = pd.read_csv(path / name, dtype={"unit_id": str, "crop_id": str})
    except Exception as exc:
        report.add(name, "file", f"cannot be read as CSV: {exc}")
        return
    required = list(model.model_fields)
    missing = [c for c in required if c not in df.columns]
    if missing:
        report.add(name, "columns", f"missing required column(s): {', '.join(missing)}")
        return
    for column in required:
        if df[column].isna().any():
            report.add(name, f"{column}: {_rows(df[column].isna())}", "required value is missing")
    _check_bounds(report, name, df, model)
    for column, allowed in _literal_choices(model).items():
        bad = ~df[column].astype(str).isin(allowed) & df[column].notna()
        if bad.any():
            report.add(name, f"{column}: {_rows(bad)}", f"must be one of: {', '.join(allowed)}")
    _check_orphans(report, name, df["unit_id"], unit_ids)
    report.stats[f"{name}_rows"] = len(df)


def validate_bundle(path: str | Path) -> ValidationReport:
    path = Path(path)
    report = ValidationReport(bundle=str(path))
    if not path.is_dir():
        report.add("(bundle)", "directory", "bundle path is not a directory")
        return report
    present = {name: (path / name).exists() for name in REQUIRED_FILES}
    for name, exists in present.items():
        if not exists:
            report.add(name, "file", "required file is missing")

    manifest = _check_manifest(path, report) if present["manifest.json"] else None
    unit_ids = _check_units(path, report, manifest) if present["units.geojson"] else None
    if present["timeseries.parquet"]:
        _check_timeseries(path, report, unit_ids)
    if present["static.parquet"]:
        _check_static(path, report, unit_ids)
    _check_csv(path, "crop_history.csv", CropHistoryRow, report, unit_ids)
    _check_csv(path, "suitability.csv", SuitabilityRow, report, unit_ids)
    return report
