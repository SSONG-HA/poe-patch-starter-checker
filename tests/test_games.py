from __future__ import annotations

import json
from pathlib import Path

import pytest

from poe_checker import analysis, datafiles, library as library_mod, matcher, naming, patchnotes, pob


def make_poe2_xml(*, ascendancy="Stormweaver", main="Spark", supports=("Unleash", "Rapid Casting II"),
                  keystone_nodes=(56349,), uniques=("Headhunter",), level=98) -> str:
    support_xml = "".join(
        f'<Gem nameSpec="{name}" enabled="true" level="1" quality="0" '
        f'gemId="Metadata/Items/Gems/SupportGemX"/>'
        for name in supports
    )
    items = "".join(
        f'<Item id="{index}">\nRarity: UNIQUE\n{name}\nTest Base\n</Item>'
        for index, name in enumerate(uniques, start=1)
    )
    nodes = ",".join(str(node) for node in keystone_nodes)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build className="Sorceress" ascendClassName="{ascendancy}" level="{level}" mainSocketGroup="1"/>
  <Tree activeSpec="1"><Spec nodes="{nodes}" treeVersion="0_5"/></Tree>
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true" mainActiveSkill="1">
        <Gem nameSpec="{main}" enabled="true" level="20" quality="20" gemId="Metadata/Items/Gems/SkillGemSpark"/>
        {support_xml}
      </Skill>
    </SkillSet>
  </Skills>
  <Items activeItemSet="1">{items}</Items>
</PathOfBuilding2>"""


def test_poe2_root_detected_as_poe2():
    profile = pob.parse_pob_xml(make_poe2_xml(), name="PoE2 test")
    assert profile.game == "poe2"
    assert profile.ascendancy == "Stormweaver"
    assert profile.main_skill_names == ["Spark"]
    assert "Unleash" in profile.support_names
    # PoE2 키스톤은 0_5 트리 데이터에서 이름을 찾는다
    assert profile.keystones == ["Chaos Inoculation"]
    assert profile.uniques == ["Headhunter"]


def test_poe1_root_detected_as_poe1(make_pob):
    profile = pob.parse_pob_xml(make_pob(), name="PoE1 test")
    assert profile.game == "poe1"
    assert profile.ascendancy == "Chieftain"
    assert "Righteous Fire" in profile.main_skill_names


def test_poe2_support_tier_name_keys():
    keys = naming.name_keys("Rapid Casting II", gem=True)
    assert "rapid casting" in keys
    assert "rapid casting ii" in keys


def test_both_games_have_gem_and_keystone_data():
    for game in datafiles.GAMES:
        assert len(datafiles.active_gems(game)) > 100
        assert len(datafiles.support_gems(game)) > 50
        assert len(datafiles.keystones(game)) >= 30
        assert len(datafiles.ascendancy_names(game)) >= 10


def test_korean_names_available_for_both_games():
    assert datafiles.korean_name("poe1", "gems", "Righteous Fire") == "정의의 화염"
    assert datafiles.korean_name("poe2", "gems", "Spark")
    assert datafiles.korean_name("poe2", "ascendancies", "Stormweaver")
    assert datafiles.korean_name("poe1", "uniques", "Nebulis") == "성운"


@pytest.fixture
def two_game_library(tmp_path, make_pob):
    path = tmp_path / "library.json"
    payload = {
        "schema": 2,
        "builds": [
            {
                "id": "poe1-rf",
                "name": "PoE1 RF",
                "kind": "starter",
                "game": "poe1",
                "code": pob.encode_pob_code(make_pob()),
            },
            {
                "id": "poe2-spark",
                "name": "PoE2 Spark",
                "kind": "poe2",
                "game": "poe2",
                "code": pob.encode_pob_code(make_poe2_xml()),
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return library_mod.BuildLibrary.load(path)


def test_library_filters_by_game(two_game_library):
    assert [b.id for b in two_game_library.builds_for("poe1")] == ["poe1-rf"]
    assert [b.id for b in two_game_library.builds_for("poe2")] == ["poe2-spark"]
    rows = two_game_library.rows("poe2")
    assert rows[0]["game"] == "PoE2"
    assert rows[0]["kind"] == "PoE2 스타터"


def test_analysis_only_checks_selected_game(two_game_library):
    text = "- Spark: Now deals 20% more Damage.\n- Righteous Fire: Now deals 10% less Damage."
    notes = patchnotes.parse_patch_notes(text, game="poe2")
    result = analysis.analyze(two_game_library, notes, game="poe2")
    assert [v.build_id for v in result.verdicts] == ["poe2-spark"]
    assert result.game == "poe2"
    assert result.game_label == "PoE2 0.5"

    result1 = analysis.analyze(two_game_library, notes, game="poe1")
    assert [v.build_id for v in result1.verdicts] == ["poe1-rf"]


def test_notes_game_used_when_no_explicit_game(two_game_library):
    notes = patchnotes.parse_patch_notes("- Spark: Now deals 20% more Damage.", game="poe2")
    result = analysis.analyze(two_game_library, notes)
    assert result.game == "poe2"


@pytest.fixture
def bundled_library():
    return library_mod.BuildLibrary.load(datafiles.DATA_DIR / "starters.json")


def test_bundled_starters_size_and_split(bundled_library):
    poe1 = [b for b in bundled_library.builds if b.game == "poe1"]
    poe2 = [b for b in bundled_library.builds if b.game == "poe2"]
    assert len(bundled_library.builds) >= 25
    assert len(poe1) >= 15
    assert len(poe2) >= 10
    assert len({b.id for b in bundled_library.builds}) == len(bundled_library.builds)


def test_bundled_starters_all_parse(bundled_library):
    rows = bundled_library.rows()
    broken = [row for row in rows if row["error"]]
    assert not broken, broken
    for row in rows:
        assert row["class"], row
        assert row["main"], row


def test_bundled_starters_names_exist_in_game_data(bundled_library):
    """동봉 스타터의 이름이 게임 데이터와 맞는지 검사한다.

    전직·패시브·아이템이 부여하는 스킬(예: Summon Elemental Relic, Doom Blast)은
    젬 목록에 없으므로 소수의 예외를 허용하고 비율로 확인한다.
    """
    gem_problems = []
    hard_problems = []
    total_gems = 0
    for build in bundled_library.builds:
        profile = bundled_library.profile(build)
        game = profile.game
        gem_keys = datafiles.active_gem_keys(game) | datafiles.support_gem_keys(game)
        keystone_keys = datafiles.keystone_keys(game)
        asc_keys = datafiles.ascendancy_keys(game)
        for gem in profile.main_skills + profile.secondary_skills + profile.supports:
            total_gems += 1
            if naming.norm(gem.name) not in gem_keys:
                gem_problems.append((build.id, gem.name))
        for keystone in profile.keystones:
            if naming.norm(keystone) not in keystone_keys:
                hard_problems.append((build.id, "keystone", keystone))
        if profile.ascendancy and naming.norm(profile.ascendancy) not in asc_keys:
            hard_problems.append((build.id, "ascendancy", profile.ascendancy))
    assert not hard_problems, hard_problems
    assert total_gems > 400
    assert len(gem_problems) / total_gems <= 0.05, gem_problems[:10]


def test_bundled_starters_have_korean_titles(bundled_library):
    for build in bundled_library.builds:
        assert any("\uac00" <= ch <= "\ud7a3" for ch in build.name), build.name


def test_starters_korean_coverage_for_main_skills(bundled_library):
    total = 0
    covered = 0
    for build in bundled_library.builds:
        profile = bundled_library.profile(build)
        for name in profile.main_skill_names[:2]:
            total += 1
            if datafiles.korean_name(profile.game, "gems", name):
                covered += 1
    assert total > 0
    assert covered / total >= 0.7, f"{covered}/{total}"


def test_game_scoped_patch_notes_produce_verdicts(bundled_library, fixture_dir):
    poe2_text = (fixture_dir / "patch_notes_poe2_055h.txt").read_text(encoding="utf-8")
    notes = patchnotes.parse_patch_notes(poe2_text, title="0.5.5h", game="poe2")
    result = analysis.analyze(bundled_library, notes, game="poe2")
    assert len(result.verdicts) >= 10
    assert all(v.profile.game == "poe2" for v in result.verdicts)


def test_library_syncs_new_bundled_starters(tmp_path, bundled_library):
    """앱에 동봉된 스타터가 늘면 기존 사용자 라이브러리에도 반영된다."""
    path = tmp_path / "library.json"
    path.write_text(json.dumps({
        "schema": 1,
        "bundled_updated": "2026-01-01",
        "builds": [{"id": "old", "name": "옛 빌드", "kind": "starter", "game": "poe1",
                    "code_file": "builds/rf-chieftain-330.txt"}],
    }), encoding="utf-8")
    merged = library_mod.BuildLibrary.load(path, sync=True)
    ids = {b.id for b in merged.builds}
    assert "rf-chieftain-current" in ids
    assert "poe2-spark-stormweaver" in ids
    assert "old" in ids
    # 두 번째 로드는 다시 합치지 않는다
    again = library_mod.BuildLibrary.load(path, sync=True)
    assert len(again.builds) == len(merged.builds)
