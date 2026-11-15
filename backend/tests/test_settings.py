import pytest
from pydantic import ValidationError

import fieldshift
from fieldshift.settings import EngineConfig, engine_config_path, load_engine_config


def test_package_imports():
    assert fieldshift.__version__


def test_engine_config_file_loads():
    cfg = load_engine_config(engine_config_path())
    assert isinstance(cfg, EngineConfig)
    assert 0 < cfg.bare_ndvi_threshold < 1
    assert cfg.weights.priorities_share + cfg.weights.resilience_share + cfg.weights.pest_break_share == pytest.approx(1.0)
    assert cfg.family_interval("poaceae") == 1
    assert cfg.family_interval("asteraceae") == 2


def test_engine_config_rejects_unknown_key(tmp_path):
    path = tmp_path / "engine.yaml"
    path.write_text("bare_ndvi_threshold: 0.3\nnot_a_real_key: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError) as err:
        load_engine_config(path)
    assert "not_a_real_key" in str(err.value)
