from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fieldshift.ingest.sample import FIELDS_ID, GRID_ID, generate_sample

FIXTURES = Path(__file__).parent / "fixtures"
POWER_CACHE_FIXTURE = FIXTURES / "power_cache"

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fail any test that opens a connection to a non-local host.

    Tests use recorded or synthetic NASA POWER responses, so a real request is a
    bug: it would make the suite slow, flaky and dependent on the network.
    """
    import socket

    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise AssertionError(f"test attempted a real network connection to {address!r}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def recorded_climate_cache(tmp_path) -> Path:
    """A private copy of the recorded NASA POWER cache for the sample bundle's cells."""
    dst = tmp_path / "power_cache"
    shutil.copytree(POWER_CACHE_FIXTURE, dst)
    return dst


@pytest.fixture(scope="session")
def kb():
    from fieldshift.kb import load_kb

    return load_kb()


@pytest.fixture(scope="session")
def cfg():
    from fieldshift.settings import load_engine_config

    return load_engine_config()


@pytest.fixture(scope="session")
def climate40():
    """Forty years of synthetic daily climate (1985-2024)."""
    from .helpers import make_climate

    return make_climate(1985, 40, seed=7)


@pytest.fixture(scope="session")
def sample_root(tmp_path_factory) -> Path:
    """Freshly generated sample bundles, shared read-only by the session."""
    out = tmp_path_factory.mktemp("sample")
    generate_sample(out)
    return out


@pytest.fixture
def grid_bundle(sample_root, tmp_path) -> Path:
    """A private, editable copy of the sample grid bundle."""
    dst = tmp_path / GRID_ID
    shutil.copytree(sample_root / GRID_ID, dst)
    return dst


@pytest.fixture
def field_bundle(sample_root, tmp_path) -> Path:
    """A private, editable copy of the sample field bundle."""
    dst = tmp_path / FIELDS_ID
    shutil.copytree(sample_root / FIELDS_ID, dst)
    return dst
