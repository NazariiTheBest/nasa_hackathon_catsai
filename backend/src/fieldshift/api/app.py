"""FastAPI application: location lookup, crop catalog, showcase areas and analysis."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fieldshift import __version__
from fieldshift.climate.power import ClimateUnavailable, PowerClient
from fieldshift.contracts import api
from fieldshift.contracts.bundle import CONTRACT_VERSION
from fieldshift.explain.templates import t
from fieldshift.ingest.registry import BundleRegistry
from fieldshift.kb import load_kb
from fieldshift.service import InvalidRequest, Services, analyze, locate
from fieldshift.settings import bundle_dirs, load_engine_config


def default_services() -> Services:
    """Load bundles, the knowledge base and the engine configuration from the project folders."""
    return Services(registry=BundleRegistry(bundle_dirs()), power=PowerClient(), kb=load_kb(), cfg=load_engine_config())


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.services is None:
            app.state.services = default_services()
        yield

    app = FastAPI(
        title="Field Shift API",
        version=__version__,
        description="Crop-rotation decision support that fuses NASA Earth observations with soil data, "
                    "crop traits and farmer priorities. It supports, and does not replace, farmer judgment.",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def svc(request: Request) -> Services:
        return request.app.state.services

    @app.exception_handler(InvalidRequest)
    async def invalid_request(_: Request, exc: InvalidRequest) -> JSONResponse:
        detail = [{"type": "value_error", "loc": list(e.loc), "msg": e.msg} for e in exc.errors]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/api/health", response_model=api.HealthResponse, tags=["system"])
    def health(request: Request) -> api.HealthResponse:
        s = svc(request)
        return api.HealthResponse(
            status="ok", engine_version=__version__, contract_version=CONTRACT_VERSION,
            bundles=[api.BundleInfo(**b) for b in s.registry.summary()],
            rejected_bundles=[f"{path}: {reason}" for path, reason in s.registry.rejected],
            crops=len(s.kb),
            crops_reviewed=sum(c.review_status == "reviewed" for c in s.kb.crops.values()),
            climate_cells_cached=s.power.cached_cells(),
        )

    @app.get("/api/locate", response_model=api.LocateResponse, tags=["site"])
    def locate_point(
        request: Request,
        lat: float = Query(..., ge=-90, le=90, description="Latitude in WGS84"),
        lon: float = Query(..., ge=-180, le=180, description="Longitude in WGS84"),
    ) -> api.LocateResponse:
        """Which data tier and unit a point falls in, without running an analysis."""
        return locate(lat, lon, svc(request))

    @app.get("/api/crops", response_model=api.CropCatalog, tags=["catalog"])
    def crops(request: Request, lang: api.Lang = "en") -> api.CropCatalog:
        return api.CropCatalog(lang=lang, crops=[api.CropEntry(**entry) for entry in svc(request).kb.catalog(lang)])

    @app.get("/api/showcase", response_model=api.ShowcaseResponse, tags=["site"])
    def showcase(request: Request) -> api.ShowcaseResponse:
        """Showcase fields as a GeoJSON FeatureCollection in WGS84."""
        return api.ShowcaseResponse(features=svc(request).registry.showcase_features())

    @app.post(
        "/api/analyze",
        response_model=api.AnalyzeResponse,
        responses={503: {"model": api.ErrorResponse, "description": "Climate data could not be obtained"}},
        tags=["analysis"],
    )
    def analyze_rotation(request: Request, body: api.AnalyzeRequest):
        """Diagnose the site and compare the baseline rotation with alternative strategies."""
        try:
            return analyze(body, svc(request))
        except ClimateUnavailable:
            error = api.ErrorResponse(code="climate_unavailable", message=t(body.lang, "error.climate_unavailable"))
            return JSONResponse(status_code=503, content=error.model_dump())

    return app


app = create_app()
