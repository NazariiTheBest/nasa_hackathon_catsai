import copy

import pytest
import yaml

from fieldshift.kb import KnowledgeBaseError, load_kb
from fieldshift.kb.loader import parse_kb
from fieldshift.settings import kb_path


@pytest.fixture(scope="module")
def records():
    with open(kb_path(), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _with(records, crop_id, mutate):
    out = copy.deepcopy(records)
    mutate(next(r for r in out if r["id"] == crop_id))
    return out


# --- Crop trait record ---

def test_complete_record_loads():
    kb = load_kb()
    wheat = kb.get("winter_wheat")
    assert wheat.name.uk == "Пшениця озима" and wheat.family == "poaceae"
    assert wheat.season_days == 290 and wheat.stress.winterkill.tmin_c == -20


def test_missing_trait_blocks_loading(records):
    broken = _with(records, "sunflower", lambda r: r.pop("root_depth_m"))
    with pytest.raises(KnowledgeBaseError) as err:
        parse_kb(broken)
    message = str(err.value)
    assert "crop 'sunflower'" in message and "'root_depth_m' is missing" in message


# --- Trait value validation ---

def test_out_of_range_coefficient_is_rejected(records):
    broken = _with(records, "maize", lambda r: r["kc"].update(mid=3.0))
    with pytest.raises(KnowledgeBaseError) as err:
        parse_kb(broken)
    message = str(err.value)
    assert "crop 'maize'" in message and "kc.mid" in message and "1.5" in message


def test_duplicate_crop_identifier_is_rejected(records):
    broken = copy.deepcopy(records) + [copy.deepcopy(records[0])]
    with pytest.raises(KnowledgeBaseError, match="crop 'winter_wheat': duplicate crop identifier"):
        parse_kb(broken)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda r: r.update(sowing_window_doy=[140, 120]), "must precede"),
        (lambda r: r.update(sowing_window_doy=[100, 400]), "1 to 366"),
        (lambda r: r.update(drought_tolerance=1.4), "drought_tolerance"),
        (lambda r: r.update(min_return_years=0), "min_return_years"),
    ],
)
def test_other_range_rules(records, mutate, expected):
    with pytest.raises(KnowledgeBaseError, match=expected):
        parse_kb(_with(records, "sunflower", mutate))


def test_all_problems_are_reported_together(records):
    broken = _with(records, "maize", lambda r: r["kc"].update(mid=3.0))
    broken = _with(broken, "sunflower", lambda r: r.pop("root_depth_m"))
    with pytest.raises(KnowledgeBaseError) as err:
        parse_kb(broken)
    assert "maize" in str(err.value) and "sunflower" in str(err.value)


# --- Provenance and review status ---

def test_crop_without_a_source_is_rejected(records):
    broken = _with(records, "peas", lambda r: r.update(sources=[]))
    with pytest.raises(KnowledgeBaseError, match="crop 'peas'"):
        parse_kb(broken)


def test_review_status_is_exposed_in_the_catalog():
    catalog = load_kb().catalog("en")
    assert all(entry["review_status"] in ("draft", "reviewed") for entry in catalog)


# --- Editable without code changes ---

def test_edited_file_takes_effect_on_load(records, tmp_path):
    edited = _with(records, "sunflower", lambda r: r["stress"]["heat"].update(tmax_c=31))
    path = tmp_path / "crops.yaml"
    path.write_text(yaml.safe_dump(edited, allow_unicode=True), encoding="utf-8")
    assert load_kb(path).get("sunflower").stress.heat.tmax_c == 31
    assert load_kb().get("sunflower").stress.heat.tmax_c == 35


# --- Coverage ---

def test_catalog_meets_coverage_minimums():
    crops = list(load_kb().crops.values())
    assert len(crops) >= 15
    assert sum(c.role == "cover" for c in crops) >= 3
    assert sum(c.is_legume for c in crops) >= 3
    assert sum(c.role == "cash" and c.season == "winter" for c in crops) >= 2
    assert sum(c.role == "cash" and c.season == "spring" for c in crops) >= 2
    assert sum(c.drought_alternative for c in crops) >= 2


def test_every_default_sowing_date_is_inside_its_window():
    for crop in load_kb().crops.values():
        start, end = crop.sowing_window_doy
        assert start <= crop.default_sow_doy <= end, crop.id


# --- Localized names ---

def test_ukrainian_and_english_catalogs():
    kb = load_kb()
    uk = {e["id"]: e["name"] for e in kb.catalog("uk")}
    en = {e["id"]: e["name"] for e in kb.catalog("en")}
    assert uk["sunflower"] == "Соняшник" and en["sunflower"] == "Sunflower"
    assert uk["peas"] == "Горох" and en["peas"] == "Field peas"
    assert all(any("а" <= ch.lower() <= "я" or ch in "іїєґІЇЄҐ" for ch in name) for name in uk.values())
    assert all(name.isascii() for name in en.values())
