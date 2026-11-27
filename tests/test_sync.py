from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_pob_code, make_pob_xml
from poe_checker import catalog, cli, datafiles, library, pob

DATA = datafiles.DATA_DIR


def _empty_library(tmp_path) -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    return library.BuildLibrary.load(path)


def _write_catalog(tmp_path, builds, *, updated="2026-12-01", base_url=None) -> Path:
    base = base_url if base_url is not None else f"{tmp_path}/"
    path = tmp_path / "starter_catalog.json"
    path.write_text(
        json.dumps(
            {"schema": 1, "updated": updated, "base_url": base, "builds": builds},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_build_file(tmp_path, name: str, xml: str) -> str:
    folder = tmp_path / "builds"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(pob.encode_pob_code(xml), encoding="utf-8")
    return f"builds/{name}"


def test_catalog_file_in_repo_covers_bundled_builds():
    starters = json.loads((DATA / "starters.json").read_text(encoding="utf-8"))
    catalog_data = json.loads((DATA / "starter_catalog.json").read_text(encoding="utf-8"))
    ids = [row["id"] for row in starters["builds"]]
    cat_ids = [row["id"] for row in catalog_data["builds"]]
    assert ids == cat_ids
    assert len(cat_ids) == 36
    for row in catalog_data["builds"]:
        assert row["pob_code_url"] and row["sha256"]
        payload = (DATA / row["pob_code_url"]).read_text(encoding="utf-8")
        assert catalog.digest(payload) == row["sha256"]
        code = payload if not pob.looks_like_xml(payload) else pob.encode_pob_code(payload)
        assert "<PathOfBuilding" in pob.decode_pob_code(code)


def test_sync_adds_new_build_and_keeps_custom(tmp_path):
    lib = _empty_library(tmp_path)
    custom = lib.add(make_pob_code(main="Winter Orb"), name="내 커스텀 빌드")
    custom_code = custom.code

    code_path = _write_build_file(tmp_path, "new.txt", make_pob_xml(main="Comet"))
    catalog_path = _write_catalog(
        tmp_path,
        [
            {
                "id": "remote-new",
                "name": "원격 신규 빌드",
                "kind": "starter",
                "game": "poe1",
                "origin": "카탈로그 · 3.31",
                "note": "새 시즌 스타터",
                "source": "https://pobb.in/example",
                "pob_code_url": code_path,
                "sha256": catalog.digest((tmp_path / code_path).read_text(encoding="utf-8")),
            }
        ],
    )
    report = catalog.sync_library(lib, url=str(catalog_path))
    assert report.added == ["remote-new"]
    assert report.saved
    entry = lib.get("remote-new")
    assert entry is not None and entry.name == "원격 신규 빌드"
    assert lib.profile(entry).main_skill_names == ["Comet"]
    # 커스텀 빌드는 그대로
    kept = lib.get(custom.id)
    assert kept is not None and kept.code == custom_code
    assert kept.name == "내 커스텀 빌드"
    assert custom.id not in report.updated and custom.id not in report.added
    # 디스크에도 저장됨
    again = library.BuildLibrary.load(lib.path)
    assert again.get("remote-new") is not None
    assert again.get(custom.id) is not None


def test_sync_updates_existing_build_and_clears_profile_cache(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    build = lib.get("rf-chieftain-330")
    assert lib.profile(build).main_skill_names[0] == "Scorching Ray of Immolation"

    code_path = _write_build_file(tmp_path, "changed.txt", make_pob_xml(main="Comet", ascendancy="Inquisitor"))
    catalog_path = _write_catalog(
        tmp_path,
        [
            {
                "id": "rf-chieftain-330",
                "name": "RF 치프틴 (갱신 이름)",
                "kind": "character",
                "game": "poe1",
                "origin": "카탈로그 갱신",
                "note": "새 본문",
                "pob_code_url": code_path,
            }
        ],
    )
    report = catalog.sync_library(lib, url=str(catalog_path))
    assert report.updated == ["rf-chieftain-330"]
    entry = lib.get("rf-chieftain-330")
    assert entry.name == "RF 치프틴 (갱신 이름)"
    assert entry.note == "새 본문"
    assert not entry.code_file  # 내려받은 코드를 직접 보관
    assert lib.profile(entry).main_skill_names == ["Comet"]
    # 카탈로그에 없는 나머지 빌드는 보존
    assert len(report.preserved) == 35


def test_sync_skips_download_when_sha_matches(tmp_path):
    lib = _empty_library(tmp_path)
    entry = lib.add(make_pob_code(main="Righteous Fire"), name="같은 빌드")
    calls: list[str] = []

    def fetcher(location: str) -> str:
        calls.append(location)
        raise AssertionError("다운로드하면 안 된다")

    catalog_path = _write_catalog(
        tmp_path,
        [
            {
                "id": entry.id,
                "name": "같은 빌드",
                "kind": "custom",
                "origin": "",
                "pob_code_url": "builds/never.txt",
                "sha256": catalog.digest(entry.code),
            }
        ],
    )
    report = catalog.sync_library(lib, url=str(catalog_path), fetcher=fetcher)
    assert calls == []
    assert report.custom_kept == [entry.id]  # 커스텀은 해시와 무관하게 보존
    assert entry.code


def test_sync_uses_pobb_in_and_inline_code(tmp_path):
    lib = _empty_library(tmp_path)
    code = make_pob_code(main="Comet")
    catalog_path = _write_catalog(
        tmp_path,
        [
            {"id": "from-pobb", "name": "pobb 빌드", "pobb_in": "https://pobb.in/abc"},
            {"id": "inline", "name": "내장 코드", "pob_code": code},
            {"id": "xml", "name": "내장 XML", "pob_xml": make_pob_xml(main="Frostbolt")},
        ],
    )
    report = catalog.sync_library(
        lib, url=str(catalog_path), pobb_fetcher=lambda url: code
    )
    assert sorted(report.added) == ["from-pobb", "inline", "xml"]
    assert lib.profile(lib.get("from-pobb")).main_skill_names == ["Comet"]
    assert lib.profile(lib.get("inline")).main_skill_names == ["Comet"]
    assert lib.profile(lib.get("xml")).main_skill_names == ["Frostbolt"]
    assert lib.get("xml").code  # XML 도 PoB 코드로 저장


def test_sync_keeps_existing_build_when_payload_is_broken(tmp_path):
    lib = _empty_library(tmp_path)
    entry = lib.add(make_pob_code(main="Righteous Fire"), name="정상 빌드", kind="starter")
    original = entry.code
    catalog_path = _write_catalog(
        tmp_path,
        [{"id": entry.id, "name": "깨진 빌드", "kind": "starter", "pob_code": "not-a-pob-code"}],
    )
    report = catalog.sync_library(lib, url=str(catalog_path))
    assert report.errors and entry.id in report.errors[0]
    assert lib.get(entry.id).code == original
    assert lib.get(entry.id).name == "정상 빌드"
    assert not report.saved


def test_sync_dry_run_does_not_write(tmp_path):
    lib = _empty_library(tmp_path)
    code_path = _write_build_file(tmp_path, "dry.txt", make_pob_xml(main="Comet"))
    catalog_path = _write_catalog(
        tmp_path,
        [{"id": "dry-build", "name": "미리보기", "pob_code_url": code_path}],
    )
    before = lib.path.read_text(encoding="utf-8")
    report = catalog.sync_library(lib, url=str(catalog_path), dry_run=True)
    assert report.added == ["dry-build"]
    assert not report.saved
    assert lib.path.read_text(encoding="utf-8") == before
    assert lib.get("dry-build") is not None  # 메모리에는 반영(저장만 안 함)


def test_catalog_network_error_is_reported(tmp_path):
    def failing_fetcher(location: str) -> str:
        raise catalog.CatalogError("연결 실패(테스트)")

    with pytest.raises(catalog.CatalogError):
        catalog.load_catalog("https://example.invalid/catalog.json", fetcher=failing_fetcher)
    with pytest.raises(catalog.CatalogError):
        catalog.read_source(str(tmp_path / "missing.json"))


def test_parse_catalog_accepts_dict_and_relative_base(tmp_path):
    text = json.dumps(
        {
            "schema": 1,
            "base_url": f"{tmp_path}/data/",
            "builds": {
                "a": {"name": "A", "pob_code_url": "builds/a.txt"},
                "b": {"name": "B", "pob_xml": "<PathOfBuilding/>"},
            },
        }
    )
    parsed = catalog.parse_catalog(text, location=str(tmp_path / "starter_catalog.json"))
    assert [b.id for b in parsed.builds] == ["a", "b"]
    assert parsed.base_url == f"{tmp_path}/data/"
    resolved = catalog.resolve_location("builds/a.txt", base=parsed.base_url)
    assert resolved == f"{tmp_path}/data/builds/a.txt"


def test_cli_sync_starters_offline(tmp_path, capsys):
    lib_path = tmp_path / "library.json"
    lib_path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    lib = library.BuildLibrary.load(lib_path)
    custom = lib.add(make_pob_code(main="Winter Orb"), name="내 빌드")

    code_path = _write_build_file(tmp_path, "cli.txt", make_pob_xml(main="Comet"))
    catalog_path = _write_catalog(
        tmp_path, [{"id": "cli-build", "name": "CLI 빌드", "pob_code_url": code_path}]
    )
    assert cli.main(["--library", str(lib_path), "--sync-starters",
                     "--catalog-url", str(catalog_path)]) == 0
    out = capsys.readouterr().out
    assert "스타터 최신화" in out and "추가 1" in out
    payload = json.loads(lib_path.read_text(encoding="utf-8"))
    ids = [row["id"] for row in payload["builds"]]
    assert "cli-build" in ids and custom.id in ids


def test_cli_sync_starters_bad_catalog(tmp_path, capsys):
    lib_path = tmp_path / "library.json"
    lib_path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    assert cli.main(["--library", str(lib_path), "--sync-starters",
                     "--catalog-url", str(tmp_path / "nope.json")]) == 3
    assert "실패" in capsys.readouterr().out


def test_remote_sync_is_not_reverted_by_bundled_copy(tmp_path, monkeypatch):
    """기본 라이브러리 경로: 최신화 뒤 앱을 다시 열어도 동봉본이 되돌리지 않는다."""
    monkeypatch.setenv("POE_CHECKER_HOME", str(tmp_path))
    lib = library.BuildLibrary.load()
    assert lib.get("rf-chieftain-330") is not None

    code_path = _write_build_file(tmp_path, "remote.txt", make_pob_xml(main="Comet"))
    catalog_path = _write_catalog(
        tmp_path,
        [{"id": "rf-chieftain-330", "name": "원격 갱신 빌드", "kind": "character",
          "pob_code_url": code_path}],
    )
    report = catalog.sync_library(lib, url=str(catalog_path))
    assert report.updated == ["rf-chieftain-330"]

    again = library.BuildLibrary.load()  # 앱 재시작과 같은 경로
    entry = again.get("rf-chieftain-330")
    assert entry.name == "원격 갱신 빌드"
    assert again.profile(entry).main_skill_names == ["Comet"]
