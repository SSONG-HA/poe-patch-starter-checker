from __future__ import annotations

import json

import pytest

from conftest import make_pob_code
from poe_checker import analysis, library, matcher, patchnotes

BUILD_TEXT = "Skills\n{gem}\n- Now deals 20% less Damage (previously it dealt more).\n- Now grants 10% more Damage (previously 20%).\n"


def _library(tmp_path, builds) -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "builds": [
                    {"id": build_id, "name": name, "kind": "custom", "code": make_pob_code(**kwargs)}
                    for build_id, name, kwargs in builds
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return library.BuildLibrary.load(path)


def test_red_when_main_skill_nerfed(tmp_path):
    lib = _library(tmp_path, [("rf", "RF 빌드", {"main": "Righteous Fire"})])
    notes = patchnotes.parse_patch_notes(
        BUILD_TEXT.format(gem="Righteous Fire"), title="test"
    )
    (verdict,) = matcher.check_library(lib, notes)
    assert verdict.verdict == matcher.VERDICT_RED
    assert verdict.nerf_hits


def test_yellow_when_only_support_nerfed(tmp_path):
    lib = _library(
        tmp_path,
        [("rf", "RF 빌드", {"main": "Righteous Fire", "supports": ("Swift Affliction",)})],
    )
    notes = patchnotes.parse_patch_notes(
        "Support Gems\nSwift Affliction Support\n- Supported Skills now deal 25% less Damage (previously 20% less Damage).\n",
        title="test",
    )
    (verdict,) = matcher.check_library(lib, notes)
    assert verdict.verdict == matcher.VERDICT_YELLOW
    assert verdict.hits[0].entity_kind == "support"


def test_green_when_no_hits(tmp_path):
    lib = _library(tmp_path, [("rf", "RF 빌드", {"main": "Righteous Fire"})])
    notes = patchnotes.parse_patch_notes(
        "Skills\nWinter Orb\n- Now deals 10% more Damage (previously 5%).\n", title="test"
    )
    (verdict,) = matcher.check_library(lib, notes)
    assert verdict.verdict == matcher.VERDICT_GREEN


def test_buff_on_main_skill_stays_green(tmp_path):
    lib = _library(tmp_path, [("rf", "RF 빌드", {"main": "Righteous Fire"})])
    notes = patchnotes.parse_patch_notes(
        "Skills\nRighteous Fire\n- Now deals 30% more Damage (previously 10%).\n", title="test"
    )
    (verdict,) = matcher.check_library(lib, notes)
    assert verdict.verdict == matcher.VERDICT_GREEN
    assert verdict.buff_hits


def test_transfigured_name_matches_base_gem(tmp_path):
    lib = _library(
        tmp_path, [("db", "지배의 일격", {"main": "Dominating Blow of Inspiring"})]
    )
    notes = patchnotes.parse_patch_notes(
        "Skills\nDominating Blow\n- Now deals 20% less Damage (previously 10% less Damage).\n",
        title="test",
    )
    (verdict,) = matcher.check_library(lib, notes)
    hit = verdict.hits[0]
    assert hit.alias == "기본 이름 일치"
    assert verdict.verdict == matcher.VERDICT_RED


def test_unique_nerf_is_red(tmp_path):
    lib = _library(
        tmp_path,
        [("rf", "RF 빌드", {"main": "Righteous Fire", "uniques": ("Nebulis",)})],
    )
    notes = patchnotes.parse_patch_notes(
        "Unique Items\nNebulis\n- Now grants 6% increased Elemental Damage per 100 Intelligence (previously 10%).\n",
        title="test",
    )
    (verdict,) = matcher.check_library(lib, notes)
    assert verdict.verdict == matcher.VERDICT_RED
    assert verdict.hits[0].entity_kind == "unique"


def test_analysis_json_roundtrip(tmp_path):
    lib = _library(tmp_path, [("rf", "RF 빌드", {"main": "Righteous Fire"})])
    notes = patchnotes.parse_patch_notes(
        BUILD_TEXT.format(gem="Righteous Fire"), title="test"
    )
    result = analysis.analyze(lib, notes, top=5)
    from poe_checker import report

    payload = json.loads(report.render_json(result))
    assert payload["summary"]["red"] == 1
    assert payload["builds"][0]["name"] == "RF 빌드"
    assert payload["builds"][0]["hits"][0]["entry"] == "Righteous Fire"
    text = report.render_text(result)
    assert "RF 빌드" in text
    assert "대폭 상향" in text
