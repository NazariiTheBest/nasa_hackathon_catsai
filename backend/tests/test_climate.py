import datetime as dt
import json

import httpx
import numpy as np
import pytest
from typer.testing import CliRunner

from fieldshift.climate.power import (
    COLUMNS,
    ClimateUnavailable,
    PowerClient,
    parse_payload,
    snap,
    year_matrix,
)

from .conftest import FIXTURES
from .helpers import FakePower, make_climate, power_payload

TODAY = dt.date(2026, 6, 15)


def _client(tmp_path, fake, **kw):
    return PowerClient(cache_dir=tmp_path / "cache", transport=fake.transport, today=TODAY, **kw)


# --- Retrieval ---

def test_recorded_power_response_parses_without_network():
    payload = json.loads((FIXTURES / "power_response_2024.json").read_text(encoding="utf-8"))
    frame, elevation = parse_payload(payload)
    assert list(frame.columns) == COLUMNS
    assert len(frame) == 366 and frame.index[0] == dt.datetime(2024, 1, 1)
    assert elevation is not None and 0 < elevation < 500
    july = frame.loc["2024-07"]
    assert 15 < july["t2m"].mean() < 30 and july["tmax"].mean() > july["tmin"].mean()
    assert 10 < july["srad"].mean() < 32  # MJ/m2/day
    assert frame["precip"].min() >= 0 and frame["gwetroot"].between(0, 1).all()


def test_series_covers_thirty_complete_years_and_excludes_the_partial_year(tmp_path):
    fake = FakePower()
    series = _client(tmp_path, fake).get_series(49.1, 32.1)

    assert fake.calls[0]["start"] == "19850101" and fake.calls[0]["end"] == "20251231"
    assert fake.calls[0]["community"] == "AG"
    assert series.data.index[-1] == dt.datetime(2025, 12, 31)
    assert series.data.index[0] == dt.datetime(1985, 1, 1)
    assert list(series.data.columns) == COLUMNS
    matrix, years = year_matrix(series.data)
    assert len(years) >= 30 and matrix["tmax"].shape == (len(years), 365)


def test_source_fill_value_becomes_missing():
    frame = make_climate(2024, 1)
    frame.iloc[10, frame.columns.get_loc("srad")] = np.nan  # encoded as -999 in the payload
    payload = power_payload(frame, 49.0, 32.5)
    assert payload["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]["20240111"] == -999.0

    parsed, _ = parse_payload(payload)
    assert np.isnan(parsed["srad"].iloc[10])
    assert parsed["srad"].notna().sum() == len(parsed) - 1
    assert (parsed.fillna(0) > -900).all().all()


def test_kwh_radiation_is_converted_to_megajoules():
    frame = make_climate(2024, 1)
    payload = power_payload(frame, 49.0, 32.5)
    payload["parameters"]["ALLSKY_SFC_SW_DWN"]["units"] = "kW-hr/m^2/day"
    parsed, _ = parse_payload(payload)
    assert parsed["srad"].iloc[0] == pytest.approx(frame["srad"].iloc[0] * 3.6)


# --- Cache ---

def test_repeated_request_makes_no_network_call(tmp_path):
    fake = FakePower()
    client = _client(tmp_path, fake)
    first = client.get_series(49.1, 32.1)
    second = client.get_series(49.1, 32.1)
    assert len(fake.calls) == 1
    assert first.data.equals(second.data)


def test_nearby_point_shares_the_cached_cell(tmp_path):
    fake = FakePower()
    client = _client(tmp_path, fake)
    assert snap(49.10, 32.10) == snap(49.20, 31.95) == (49.0, 31.875)
    client.get_series(49.10, 32.10)
    client.get_series(49.20, 31.95)
    assert len(fake.calls) == 1
    assert float(fake.calls[0]["latitude"]) == 49.0 and float(fake.calls[0]["longitude"]) == 31.875


def test_cache_survives_a_restart(tmp_path):
    fake = FakePower()
    _client(tmp_path, fake).get_series(49.1, 32.1)
    restarted = _client(tmp_path, fake)
    series = restarted.get_series(49.1, 32.1)
    assert len(fake.calls) == 1
    assert restarted.cached_cells() == 1
    assert series.provenance.cell_lat == 49.0


# --- Unreachable source ---

def test_source_down_with_stored_series(tmp_path):
    _client(tmp_path, FakePower()).get_series(49.1, 32.1)
    offline = _client(tmp_path, FakePower(down=True))
    assert len(offline.get_series(49.1, 32.1).data) > 365 * 30


def test_source_down_without_stored_series(tmp_path):
    offline = _client(tmp_path, FakePower(down=True))
    with pytest.raises(ClimateUnavailable):
        offline.get_series(49.1, 32.1)
    assert offline.cached_cells() == 0


def test_unreadable_response_is_climate_unavailable(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": True}))
    client = PowerClient(cache_dir=tmp_path / "cache", transport=transport, today=TODAY)
    with pytest.raises(ClimateUnavailable):
        client.get_series(49.1, 32.1)
    assert client.cached_cells() == 0


# --- Pre-warming ---

def _grid_points():
    return [(lat, lon) for lat in (48.0, 48.5, 49.0, 49.5) for lon in (31.25, 31.875, 32.5)]


def test_interrupted_prewarm_is_resumed(tmp_path):
    fake = FakePower()
    client = _client(tmp_path, fake)
    points = _grid_points()
    first = client.prewarm(points[:5], pause_s=0)
    assert len(first.fetched) == 5 and first.cells == 5

    second = client.prewarm(points, pause_s=0)
    assert second.cells == 12
    assert len(second.skipped) == 5 and len(second.fetched) == 7 and second.failed == []
    assert len(fake.calls) == 12


def test_individual_failure_does_not_stop_the_run(tmp_path):
    fake = FakePower(fail_cells={(48.5, 31.875)})
    client = _client(tmp_path, fake, retries=0)
    summary = client.prewarm(_grid_points(), pause_s=0)
    assert len(summary.fetched) == 11
    assert [cell for cell, _ in summary.failed] == [(48.5, 31.875)]
    assert client.cached_cells() == 11


def test_prewarm_command_reports_summary(tmp_path, monkeypatch, sample_root):
    import fieldshift.climate.power as power
    from fieldshift.cli import app
    from fieldshift.ingest.sample import FIELDS_ID

    fake = FakePower()
    original = power.PowerClient

    monkeypatch.setattr(
        power, "PowerClient",
        lambda *a, **k: original(cache_dir=tmp_path / "cache", transport=fake.transport, today=TODAY),
    )
    result = CliRunner().invoke(app, ["prewarm", "--bundle", str(sample_root / FIELDS_ID), "--pause", "0"])
    assert result.exit_code == 0, result.output
    assert "fetched: 2" in result.output and "failed: 0" in result.output


# --- Provenance ---

def test_provenance_accompanies_a_series(tmp_path):
    series = _client(tmp_path, FakePower()).get_series(49.1, 32.1)
    p = series.provenance
    assert "NASA POWER" in p.source and "0.5 x 0.625" in p.spatial_resolution
    assert p.period_start == dt.date(1985, 1, 1) and p.period_end == dt.date(2025, 12, 31)
    assert p.period_label == "1985-2025"
    assert p.retrieved_at.tzinfo is not None and p.elevation_m == 120.0


# --- Network guard ---

def test_real_network_requests_fail_the_suite():
    with pytest.raises(AssertionError, match="real network connection"):
        httpx.get("http://192.0.2.1/", timeout=2)
