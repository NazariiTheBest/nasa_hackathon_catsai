"""Loaded bundles: unit geometries, per-unit queries and location lookup."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import ValidationError
from shapely import STRtree
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from fieldshift.contracts.bundle import SUPPORTED_CONTRACT_VERSIONS, Manifest, UnitProperties


@dataclass
class Unit:
    unit_id: str
    unit_type: str
    name: str | None
    area_ha: float | None
    cropland_frac: float | None
    geometry: BaseGeometry
    bundle_id: str

    @property
    def centroid(self) -> tuple[float, float]:
        """(lat, lon) of the unit's centroid."""
        c = self.geometry.centroid
        return (c.y, c.x)


@dataclass
class Bundle:
    path: Path
    manifest: Manifest
    units: dict[str, Unit]
    static: dict[str, dict]
    crop_history: pd.DataFrame | None
    suitability: pd.DataFrame | None
    features: list[dict] = field(default_factory=list)

    @property
    def bundle_id(self) -> str:
        return self.manifest.bundle_id


class BundleRegistry:
    """Discovers bundles under the given directories and answers per-unit queries.

    Time series stay in Parquet and are queried per unit with DuckDB, so a
    national grid of about ten million rows costs no start-up time or memory.
    """

    def __init__(self, dirs: list[Path] | None = None):
        self.bundles: dict[str, Bundle] = {}
        self.rejected: list[tuple[str, str]] = []
        self._unit_bundle: dict[str, str] = {}
        self._trees: dict[str, tuple[STRtree, list[Unit]]] = {}
        self._con = duckdb.connect(":memory:")
        for directory in dirs or []:
            self.discover(Path(directory))

    # --- Loading ---

    def discover(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for sub in sorted(directory.iterdir()):
            if sub.is_dir() and (sub / "manifest.json").exists():
                self.load(sub)
        self._build_index()

    def load(self, path: Path) -> Bundle | None:
        try:
            manifest = Manifest.model_validate(json.loads((path / "manifest.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            self.rejected.append((str(path), f"manifest cannot be read: {exc}"))
            return None
        if manifest.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            self.rejected.append((
                str(path),
                f"contract version '{manifest.contract_version}' is not supported "
                f"(supported: {', '.join(SUPPORTED_CONTRACT_VERSIONS)})",
            ))
            return None
        try:
            collection = json.loads((path / "units.geojson").read_text(encoding="utf-8"))
            units: dict[str, Unit] = {}
            for feature in collection["features"]:
                props = UnitProperties.model_validate(feature["properties"])
                units[props.unit_id] = Unit(
                    unit_id=props.unit_id, unit_type=props.unit_type, name=props.name,
                    area_ha=props.area_ha, cropland_frac=props.cropland_frac,
                    geometry=shape(feature["geometry"]), bundle_id=manifest.bundle_id,
                )
            static_df = pd.read_parquet(path / "static.parquet")
            static = {
                str(row["unit_id"]): {k: (None if pd.isna(v) else v) for k, v in row.items() if k != "unit_id"}
                for row in static_df.to_dict("records")
            }
            if not (path / "timeseries.parquet").exists():
                raise FileNotFoundError("timeseries.parquet")
        except (OSError, KeyError, ValueError, ValidationError) as exc:
            self.rejected.append((str(path), f"bundle cannot be loaded: {exc}"))
            return None

        def _csv(name: str) -> pd.DataFrame | None:
            file = path / name
            if not file.exists():
                return None
            return pd.read_csv(file, dtype={"unit_id": str, "crop_id": str})

        bundle = Bundle(
            path=path, manifest=manifest, units=units, static=static,
            crop_history=_csv("crop_history.csv"), suitability=_csv("suitability.csv"),
            features=collection["features"],
        )
        self.bundles[manifest.bundle_id] = bundle
        for unit_id in units:
            self._unit_bundle[unit_id] = manifest.bundle_id
        return bundle

    def _build_index(self) -> None:
        self._trees = {}
        for unit_type in ("field", "grid_cell"):
            members = [u for b in self.bundles.values() for u in b.units.values() if u.unit_type == unit_type]
            if members:
                self._trees[unit_type] = (STRtree([u.geometry for u in members]), members)

    # --- Lookup ---

    def lookup(self, lat: float, lon: float) -> Unit | None:
        """The showcase field containing the point, else the grid cell, else None."""
        point = Point(lon, lat)
        for unit_type in ("field", "grid_cell"):
            entry = self._trees.get(unit_type)
            if entry is None:
                continue
            tree, members = entry
            hits = tree.query(point, predicate="intersects")
            if len(hits):
                return members[int(min(hits))]
        return None

    def get_unit(self, unit_id: str) -> Unit | None:
        bundle_id = self._unit_bundle.get(unit_id)
        return self.bundles[bundle_id].units[unit_id] if bundle_id else None

    def bundle_of(self, unit_id: str) -> Bundle | None:
        bundle_id = self._unit_bundle.get(unit_id)
        return self.bundles[bundle_id] if bundle_id else None

    # --- Per-unit queries ---

    def timeseries(self, unit_id: str, variable: str | None = None) -> pd.DataFrame:
        """Rows for one unit, ordered by variable and date. Empty when the unit is unknown."""
        bundle = self.bundle_of(unit_id)
        columns = ["date", "variable", "value", "std", "valid_frac", "source", "res_m"]
        if bundle is None:
            return pd.DataFrame(columns=columns)
        sql = (
            f"SELECT {', '.join(columns)} FROM read_parquet(?) WHERE unit_id = ?"
            + (" AND variable = ?" if variable else "")
            + " ORDER BY variable, date"
        )
        params = [str(bundle.path / "timeseries.parquet"), unit_id] + ([variable] if variable else [])
        frame = self._con.cursor().execute(sql, params).df()
        frame["date"] = pd.to_datetime(frame["date"])
        frame["variable"] = frame["variable"].astype(str)
        frame["source"] = frame["source"].astype(str)
        return frame

    def static(self, unit_id: str) -> dict | None:
        bundle = self.bundle_of(unit_id)
        return dict(bundle.static[unit_id]) if bundle and unit_id in bundle.static else None

    def crop_history(self, unit_id: str) -> pd.DataFrame:
        bundle = self.bundle_of(unit_id)
        if bundle is None or bundle.crop_history is None:
            return pd.DataFrame(columns=["unit_id", "year", "crop_id", "cover_frac", "method", "confidence"])
        frame = bundle.crop_history
        return frame[frame["unit_id"] == unit_id].sort_values("year", ignore_index=True)

    def suitability(self, unit_id: str) -> dict[str, float] | None:
        """crop_id -> suitability index, or None when the unit has no suitability table."""
        bundle = self.bundle_of(unit_id)
        if bundle is None or bundle.suitability is None:
            return None
        frame = bundle.suitability
        rows = frame[frame["unit_id"] == unit_id]
        if rows.empty:
            return None
        return {str(c): float(v) for c, v in zip(rows["crop_id"], rows["suitability_index"])}

    def source_label(self, unit_id: str, variable: str) -> tuple[str, str] | None:
        """(product and version, native resolution) declared in the unit's bundle manifest."""
        bundle = self.bundle_of(unit_id)
        entry = bundle.manifest.source_for(variable) if bundle else None
        if entry is None:
            return None
        res = entry.native_res_m
        resolution = f"{res / 1000:g} km" if res >= 1000 else f"{res:g} m"
        return (f"{entry.product} {entry.version}".strip(), resolution)

    # --- Summaries ---

    def summary(self) -> list[dict]:
        return [
            {"bundle_id": b.bundle_id, "unit_type": b.manifest.unit_type, "units": len(b.units),
             "author": b.manifest.author, "notes": b.manifest.notes}
            for b in self.bundles.values()
        ]

    def showcase_features(self) -> list[dict]:
        """GeoJSON features of every showcase field, ready for a map client."""
        features = []
        for bundle in self.bundles.values():
            if bundle.manifest.unit_type != "field":
                continue
            for feature in bundle.features:
                props = feature["properties"]
                features.append({
                    "type": "Feature",
                    "properties": {"unit_id": props["unit_id"], "name": props.get("name"),
                                   "area_ha": props.get("area_ha"), "bundle_id": bundle.bundle_id},
                    "geometry": feature["geometry"],
                })
        return features
