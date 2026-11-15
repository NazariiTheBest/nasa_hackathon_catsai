"""The analysis pipeline: request -> site context -> engine -> diagnosis -> explained strategies."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from shapely.errors import ShapelyError
from shapely.geometry import shape

from fieldshift import __version__
from fieldshift.climate.power import PowerClient
from fieldshift.contracts import api
from fieldshift.contracts.bundle import CONTRACT_VERSION
from fieldshift.diagnostics.site import build_context, diagnose, tier_of, unit_summary
from fieldshift.engine.calendar import SequenceSpec
from fieldshift.engine.run import run_engine
from fieldshift.explain.build import build_strategies, render_notices
from fieldshift.ingest.registry import BundleRegistry, Unit
from fieldshift.kb import KnowledgeBase
from fieldshift.settings import EngineConfig


@dataclass
class Services:
    registry: BundleRegistry
    power: PowerClient
    kb: KnowledgeBase
    cfg: EngineConfig


@dataclass
class FieldError:
    loc: tuple
    msg: str


class InvalidRequest(Exception):
    """The request is well-formed but refers to things that do not exist or do not fit."""

    def __init__(self, errors: list[FieldError]):
        super().__init__("; ".join(e.msg for e in errors))
        self.errors = errors


def _resolve_location(location, services: Services) -> tuple[float, float, Unit | None, list[tuple[str, dict]]]:
    if location.type == "point":
        return location.lat, location.lon, None, []
    if location.type == "unit":
        unit = services.registry.get_unit(location.unit_id)
        if unit is None:
            raise InvalidRequest([FieldError(("body", "location", "unit_id"), f"unknown unit identifier '{location.unit_id}'")])
        lat, lon = unit.centroid
        return lat, lon, unit, []
    try:
        geometry = shape(location.geometry)
        if geometry.is_empty or geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("geometry must be a non-empty Polygon or MultiPolygon")
        centroid = geometry.centroid
        lat, lon = float(centroid.y), float(centroid.x)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("geometry is not in WGS84 longitude, latitude order")
    except (ShapelyError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidRequest([FieldError(("body", "location", "geometry"), f"invalid polygon: {exc}")]) from exc
    return lat, lon, None, [("polygon_centroid", {"lat": lat, "lon": lon})]


def _validate_crops(request: api.AnalyzeRequest, kb: KnowledgeBase) -> None:
    errors: list[FieldError] = []
    for i, crop_id in enumerate(request.baseline.crops):
        if crop_id not in kb:
            errors.append(FieldError(("body", "baseline", "crops", i), f"unknown crop identifier '{crop_id}'"))
        elif kb.get(crop_id).role == "cover":
            errors.append(FieldError(("body", "baseline", "crops", i),
                                     f"'{crop_id}' is a cover crop; list it under baseline.covers"))
    seen: set[int] = set()
    for i, cover in enumerate(request.baseline.covers):
        if cover.crop_id not in kb:
            errors.append(FieldError(("body", "baseline", "covers", i, "crop_id"), f"unknown crop identifier '{cover.crop_id}'"))
        elif kb.get(cover.crop_id).role != "cover":
            errors.append(FieldError(("body", "baseline", "covers", i, "crop_id"), f"'{cover.crop_id}' is not a cover crop"))
        if cover.after_index >= len(request.baseline.crops):
            errors.append(FieldError(("body", "baseline", "covers", i, "after_index"),
                                     f"after_index {cover.after_index} is beyond the last main crop"))
        if cover.after_index in seen:
            errors.append(FieldError(("body", "baseline", "covers", i, "after_index"),
                                     f"more than one cover crop after main crop {cover.after_index}"))
        seen.add(cover.after_index)
    for i, crop_id in enumerate(request.constraints.excluded_crops):
        if crop_id not in kb:
            errors.append(FieldError(("body", "constraints", "excluded_crops", i), f"unknown crop identifier '{crop_id}'"))
    if errors:
        raise InvalidRequest(errors)


def locate(lat: float, lon: float, services: Services) -> api.LocateResponse:
    unit = services.registry.lookup(lat, lon)
    return api.LocateResponse(lat=lat, lon=lon, data_tier=tier_of(unit), unit=unit_summary(unit),
                              climate_cached=services.power.is_cached(lat, lon))


def analyze(request: api.AnalyzeRequest, services: Services) -> api.AnalyzeResponse:
    """Run one analysis. Raises InvalidRequest or ClimateUnavailable; never returns a partial result."""
    _validate_crops(request, services.kb)
    lat, lon, unit, notices = _resolve_location(request.location, services)

    ctx = build_context(lat, lon, services.registry, services.power, services.kb, services.cfg, unit=unit)
    spec = SequenceSpec.of(request.baseline.crops, [(c.after_index, c.crop_id) for c in request.baseline.covers])
    engine = run_engine(ctx, spec, request.priorities, request.constraints)
    site = diagnose(ctx, engine.baseline.evaluation, request.lang)
    strategies = build_strategies(engine, ctx, site, request.lang)

    return api.AnalyzeResponse(
        meta=api.Meta(
            contract_version=CONTRACT_VERSION, engine_version=__version__, data_tier=ctx.tier,
            generated_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0), lang=request.lang,
            notices=render_notices(notices + engine.notices, ctx, request.lang),
        ),
        site=site,
        strategies=strategies,
    )
