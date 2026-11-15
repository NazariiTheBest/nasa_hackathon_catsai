import json
import time

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from fieldshift.api.app import create_app
from fieldshift.climate.power import PowerClient
from fieldshift.contracts.export import openapi_text
from fieldshift.ingest.registry import BundleRegistry
from fieldshift.ingest.sample import GRID_ID
from fieldshift.service import Services
from fieldshift.settings import project_root

from .helpers import FakePower

FIELD_POINT = {"type": "point", "lat": 49.144, "lon": 32.136}
GRID_POINT = {"type": "point", "lat": 49.05, "lon": 32.05}
OUTSIDE_POINT = {"type": "point", "lat": 48.9, "lon": 31.7}   # no bundle, climate cell cached
UNCACHED_POINT = {"type": "point", "lat": 46.5, "lon": 30.7}  # no bundle, no cached climate


def body(location=None, **overrides):
    request = {
        "location": location or GRID_POINT,
        "baseline": {"crops": ["winter_wheat", "sunflower", "spring_barley"], "covers": []},
        "priorities": {"water": 0.8, "nitrogen": 0.3, "erosion": 0.6, "organic_matter": 0.5, "forage": 0.0, "income": 0.7},
        "constraints": {"irrigation_available": False, "excluded_crops": [], "max_cycle_years": 5},
        "lang": "en",
    }
    request.update(overrides)
    return request


@pytest.fixture
def client(sample_root, recorded_climate_cache, kb, cfg):
    services = Services(
        registry=BundleRegistry([sample_root]),
        power=PowerClient(cache_dir=recorded_climate_cache, transport=FakePower(down=True).transport, retries=0),
        kb=kb, cfg=cfg,
    )
    with TestClient(create_app(services)) as test_client:
        yield test_client


def messages(response):
    return " | ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in response.json()["detail"])


# ----------------------------------------------------------------- Health

def test_health_reports_bundles_crops_and_cache(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    units = {b["bundle_id"]: b["units"] for b in data["bundles"]}
    assert units == {"ua-sample-fields": 3, "ua-sample-grid": 20}
    assert data["crops"] == 20 and data["climate_cells_cached"] == 4 and data["rejected_bundles"] == []


# ----------------------------------------------- Lookup, catalog, showcase

def test_locate_point_in_a_grid_cell(client):
    data = client.get("/api/locate", params={"lat": 49.05, "lon": 32.05}).json()
    assert data["data_tier"] == "grid" and data["unit"]["unit_id"] == "g_0000" and data["climate_cached"] is True


def test_locate_point_in_a_field_and_outside(client):
    field = client.get("/api/locate", params={"lat": 49.144, "lon": 32.136}).json()
    assert field["data_tier"] == "field" and field["unit"]["unit_id"] == "f_demo_01"
    outside = client.get("/api/locate", params={"lat": 10.0, "lon": 10.0}).json()
    assert outside["data_tier"] == "climate_only" and outside["unit"] is None and outside["climate_cached"] is False
    assert client.get("/api/locate", params={"lat": 120, "lon": 10}).status_code == 422


def test_crop_catalog_in_ukrainian(client):
    data = client.get("/api/crops", params={"lang": "uk"}).json()
    assert data["lang"] == "uk" and len(data["crops"]) == 20
    sunflower = next(c for c in data["crops"] if c["id"] == "sunflower")
    assert sunflower == {"id": "sunflower", "name": "Соняшник", "role": "cash", "family": "asteraceae", "season": "spring",
                         "is_legume": False, "drought_alternative": False, "min_return_years": 7, "review_status": "draft"}
    assert client.get("/api/crops").json()["crops"][0]["name"] == "Winter wheat"
    assert client.get("/api/crops", params={"lang": "de"}).status_code == 422


def test_showcase_fields_are_listed(client):
    data = client.get("/api/showcase").json()
    assert data["type"] == "FeatureCollection" and len(data["features"]) == 3
    feature = data["features"][0]
    assert feature["properties"]["unit_id"] == "f_demo_01" and feature["properties"]["name"] == "Demo field 1"
    lon, lat = feature["geometry"]["coordinates"][0][0]
    assert 22 < lon < 41 and 44 < lat < 53, "WGS84 longitude, latitude inside Ukraine"


def test_showcase_is_empty_without_a_field_bundle(sample_root, recorded_climate_cache, kb, cfg):
    registry = BundleRegistry()
    registry.load(sample_root / GRID_ID)
    registry._build_index()
    services = Services(registry, PowerClient(cache_dir=recorded_climate_cache, transport=FakePower(down=True).transport), kb, cfg)
    with TestClient(create_app(services)) as grid_only:
        response = grid_only.get("/api/showcase")
    assert response.status_code == 200 and response.json()["features"] == []


# ------------------------------------------------------------------ Analysis

def test_point_request(client):
    response = client.post("/api/analyze", json=body(GRID_POINT))
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["strategies"]) >= 3
    assert [s["is_baseline"] for s in data["strategies"]].count(True) == 1 and data["strategies"][0]["is_baseline"]
    assert data["site"]["data_tier"] == "grid" and data["site"]["unit"]["unit_id"] == "g_0000"
    assert data["site"]["bare_windows"] and data["site"]["stress"] and data["site"]["trends"]
    for strategy in data["strategies"]:
        assert all(strategy[element] for element in ("why", "evidence", "benefits", "gaps", "local_review"))
        assert strategy["scores"]["overall"]["p10"] <= strategy["scores"]["overall"]["median"] <= strategy["scores"]["overall"]["p90"]


def test_unit_request(client):
    data = client.post("/api/analyze", json=body({"type": "unit", "unit_id": "f_demo_02"})).json()
    assert data["meta"]["data_tier"] == "field" and data["site"]["unit"]["unit_id"] == "f_demo_02"
    assert data["site"]["observed_low_cover"]


def test_polygon_request_uses_the_centroid(client):
    polygon = {"type": "Polygon", "coordinates": [[[32.04, 49.04], [32.06, 49.04], [32.06, 49.06], [32.04, 49.06], [32.04, 49.04]]]}
    data = client.post("/api/analyze", json=body({"type": "polygon", "geometry": polygon})).json()
    notice = next(n for n in data["meta"]["notices"] if n["code"] == "notice.polygon_centroid")
    assert "centroid" in notice["text"] and "49.0500" in notice["text"] and "32.0500" in notice["text"]
    assert data["site"]["lat"] == pytest.approx(49.05) and data["site"]["unit"]["unit_id"] == "g_0000"


def test_climate_only_point(client):
    data = client.post("/api/analyze", json=body(OUTSIDE_POINT)).json()
    assert data["meta"]["data_tier"] == "climate_only" and data["site"]["unit"] is None
    assert all(s["confidence"] == "low" for s in data["strategies"])


def test_response_metadata(client):
    meta = client.post("/api/analyze", json=body()).json()["meta"]
    assert meta["contract_version"] == "1.0" and meta["engine_version"] == "0.1.0"
    assert meta["data_tier"] == "grid" and meta["lang"] == "en" and isinstance(meta["notices"], list)
    assert meta["generated_at"].endswith("Z") or "+00:00" in meta["generated_at"]


def test_ukrainian_response_has_the_same_numbers(client):
    en = client.post("/api/analyze", json=body()).json()
    uk = client.post("/api/analyze", json=body(lang="uk")).json()
    assert [s["scores"] for s in en["strategies"]] == [s["scores"] for s in uk["strategies"]]
    assert uk["strategies"][0]["label"] == "Поточна сівозміна"
    assert uk["site"]["stress"][0]["hazard_label"] != en["site"]["stress"][0]["hazard_label"]


# ------------------------------------------------------------- Validation

def test_unknown_crop_identifier(client):
    response = client.post("/api/analyze", json=body(baseline={"crops": ["winter_wheat", "quinoa"], "covers": []}))
    assert response.status_code == 422
    assert "baseline.crops.1" in messages(response) and "unknown crop identifier 'quinoa'" in messages(response)


def test_several_invalid_fields_are_all_reported(client):
    response = client.post("/api/analyze", json=body({"type": "point", "lat": 120, "lon": 32}, baseline={"crops": [], "covers": []}))
    assert response.status_code == 422
    text = messages(response)
    assert "lat" in text and "less than or equal to 90" in text
    assert "baseline.crops" in text and "at least 1 item" in text


def test_unsupported_language_lists_the_supported_ones(client):
    response = client.post("/api/analyze", json=body(lang="de"))
    assert response.status_code == 422
    assert "lang" in messages(response) and "'en'" in messages(response) and "'uk'" in messages(response)


def test_other_invalid_inputs(client):
    out_of_range = client.post("/api/analyze", json=body(priorities={"water": 1.5}))
    assert out_of_range.status_code == 422 and "priorities.water" in messages(out_of_range)

    unknown_unit = client.post("/api/analyze", json=body({"type": "unit", "unit_id": "nope"}))
    assert unknown_unit.status_code == 422 and "unknown unit identifier 'nope'" in messages(unknown_unit)

    cover_as_main = client.post("/api/analyze", json=body(baseline={"crops": ["winter_rye"], "covers": []}))
    assert cover_as_main.status_code == 422 and "is a cover crop" in messages(cover_as_main)

    bad_cover = client.post("/api/analyze", json=body(
        baseline={"crops": ["winter_wheat"], "covers": [{"after_index": 3, "crop_id": "maize"}]}))
    assert bad_cover.status_code == 422
    assert "not a cover crop" in messages(bad_cover) and "beyond the last main crop" in messages(bad_cover)

    bad_polygon = client.post("/api/analyze", json=body({"type": "polygon", "geometry": {"type": "Point", "coordinates": [32, 49]}}))
    assert bad_polygon.status_code == 422 and "invalid polygon" in messages(bad_polygon)


# ------------------------------------------------------- Upstream failure

def test_climate_source_unreachable_and_nothing_cached(client):
    response = client.post("/api/analyze", json=body(UNCACHED_POINT))
    assert response.status_code == 503
    data = response.json()
    assert data["code"] == "climate_unavailable" and "NASA POWER" in data["message"]
    assert "strategies" not in data and "site" not in data

    ukrainian = client.post("/api/analyze", json=body(UNCACHED_POINT, lang="uk")).json()
    assert ukrainian["code"] == "climate_unavailable" and ukrainian["message"] != data["message"]


# ------------------------------------------------------ Published schema

def test_response_conforms_to_the_published_schema(client):
    schema = client.get("/api/openapi.json").json()
    assert {"/api/health", "/api/locate", "/api/crops", "/api/showcase", "/api/analyze"} <= set(schema["paths"])

    def validator(name):
        return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": schema["components"]})

    for location in (FIELD_POINT, GRID_POINT, OUTSIDE_POINT):
        analysis = client.post("/api/analyze", json=body(location)).json()
        errors = sorted(validator("AnalyzeResponse").iter_errors(analysis), key=str)
        assert errors == [], errors[:3]
    assert list(validator("LocateResponse").iter_errors(client.get("/api/locate", params={"lat": 49.05, "lon": 32.05}).json())) == []
    assert list(validator("CropCatalog").iter_errors(client.get("/api/crops").json())) == []
    assert list(validator("HealthResponse").iter_errors(client.get("/api/health").json())) == []
    assert list(validator("ErrorResponse").iter_errors(client.post("/api/analyze", json=body(UNCACHED_POINT)).json())) == []


def test_committed_openapi_schema_is_current():
    path = project_root() / "contracts" / "openapi.json"
    assert path.exists(), "run: uv run fieldshift export-schemas"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(openapi_text()), "run: uv run fieldshift export-schemas"


# ---------------------------------------------------------- Response time

def test_warm_analysis_returns_within_ten_seconds(client):
    started = time.perf_counter()
    response = client.post("/api/analyze", json=body(FIELD_POINT))
    elapsed = time.perf_counter() - started
    print(f"\nwarm analysis: {elapsed:.2f} s")
    assert response.status_code == 200
    assert elapsed < 10.0
