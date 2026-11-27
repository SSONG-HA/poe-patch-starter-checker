from __future__ import annotations

import json

import pytest

from conftest import make_pob_code, make_pob_xml
from poe_checker import library, pob


def _empty_library(tmp_path) -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    return library.BuildLibrary.load(path)


def test_add_from_code_and_persist(tmp_path):
    lib = _empty_library(tmp_path)
    entry = lib.add(make_pob_code(main="Righteous Fire"), name="RF 빌드")
    assert entry.id == "rf-빌드"
    assert lib.path.exists()

    again = library.BuildLibrary.load(lib.path)
    assert [b.name for b in again.builds] == ["RF 빌드"]
    assert again.profile(again.builds[0]).main_skill_names[0] == "Righteous Fire"


def test_add_from_xml_file(tmp_path):
    lib = _empty_library(tmp_path)
    xml_path = tmp_path / "build.xml"
    xml_path.write_text(make_pob_xml(main="Winter Orb"), encoding="utf-8")
    entry = lib.add(str(xml_path), name="콜드 빌드")
    assert entry.code  # 코드 형태로 정규화되어 저장된다
    profile = lib.profile(entry)
    assert profile.main_skill_names[0] == "Winter Orb"


def test_duplicate_names_get_suffix(tmp_path):
    lib = _empty_library(tmp_path)
    first = lib.add(make_pob_code(main="Righteous Fire"), name="RF")
    second = lib.add(make_pob_code(main="Righteous Fire"), name="RF")
    assert first.id != second.id
    assert second.id == "rf-2"


def test_remove(tmp_path):
    lib = _empty_library(tmp_path)
    entry = lib.add(make_pob_code(), name="빌드")
    assert lib.remove(entry.id) is True
    assert lib.remove("없는-id") is False
    assert library.BuildLibrary.load(lib.path).builds == []


def test_add_invalid_source(tmp_path):
    lib = _empty_library(tmp_path)
    with pytest.raises(pob.PobError):
        lib.add("this-is-not-a-pob-code")


def test_rows_include_profile_summary(tmp_path):
    lib = _empty_library(tmp_path)
    lib.add(make_pob_code(main="Righteous Fire", ascendancy="Chieftain"), name="RF")
    (row,) = lib.rows()
    assert row["class"] == "Chieftain"
    assert row["main"].startswith("Righteous Fire")


def test_seed_from_bundled_library(tmp_path):
    target = tmp_path / "nested" / "library.json"
    lib = library.BuildLibrary.load(target)
    assert target.exists()
    assert len(lib.builds) >= 8
    assert any(b.id == "rf-chieftain-330" for b in lib.builds)
    # 동봉 빌드가 실제로 해석되는지
    profile = lib.profile(next(b for b in lib.builds if b.id == "rf-chieftain-330"))
    assert profile.ascendancy == "Chieftain"
    assert "Righteous Fire" in profile.main_skill_names
