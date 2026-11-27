from __future__ import annotations

import json
import sys
from html import escape as xml_escape

import pytest

from conftest import make_pob_code
from poe_checker import analysis, cli, datafiles, guide, library, patchnotes, pob

DATA = datafiles.DATA_DIR


# ---------------------------------------------------------------------------
# 합성 PoB XML — 실제 시즌에 없는 새 젬/유니크까지 포함
# ---------------------------------------------------------------------------

def make_rich_xml(*, notes: str = "", unknown: bool = False,
                  main: str | None = None) -> str:
    main_name = main or ("Comet of the New Season" if unknown else "Righteous Fire")
    support = "Support of the New Season" if unknown else "Elemental Focus"
    unique = "Brand New Unique" if unknown else "Mageblood"
    notes_xml = f"<Notes>{xml_escape(notes)}</Notes>" if notes else "<Notes/>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding>
  <Build level="92" className="Marauder" ascendClassName="Chieftain" mainSocketGroup="1">
    <PlayerStat stat="TotalEHP" value="150000"/>
    <PlayerStat stat="CombinedDPS" value="6000000"/>
  </Build>
  <Tree activeSpec="1">
    <Spec title="Lvl 90 Block Based {{1}}" treeVersion="3_30" nodes="11455,2311,2550"/>
    <Spec title="Lvl 100 Endgame {{2}}" treeVersion="3_30" nodes="11455,3533"/>
  </Tree>
  <Skills activeSkillSet="1">
    <SkillSet id="1" title="^2Act 1-3 Leveling {{1}}">
      <Skill enabled="true" label="" slot="Body Armour">
        <Gem nameSpec="{main_name}" enabled="true" level="20" quality="20" gemId="Metadata/Items/Gems/SkillGemMain"/>
        <Gem nameSpec="{support}" enabled="true" level="20" quality="10" gemId="Metadata/Items/Gems/SupportGemX"/>
        <Gem nameSpec="Lifetap" enabled="true" level="18" quality="0" gemId="Metadata/Items/Gems/SupportGemY"/>
      </Skill>
      <Skill enabled="true" label="auras" slot="Helmet">
        <Gem nameSpec="Malevolence" enabled="true" level="20" quality="0" gemId="Metadata/Items/Gems/SkillGemAura"/>
      </Skill>
    </SkillSet>
    <SkillSet id="2" title="^4Endgame {{2}}">
      <Skill enabled="true" label="" slot="Body Armour">
        <Gem nameSpec="{main_name}" enabled="true" level="21" quality="20" gemId="Metadata/Items/Gems/SkillGemMain"/>
        <Gem nameSpec="{support}" enabled="true" level="20" quality="20" gemId="Metadata/Items/Gems/SupportGemX"/>
      </Skill>
      <Skill enabled="false" label="off" slot="Gloves">
        <Gem nameSpec="Clarity" enabled="true" level="1" quality="0" gemId="Metadata/Items/Gems/SkillGemAura"/>
      </Skill>
    </SkillSet>
  </Skills>
  <Items activeItemSet="1">
    <Item id="1">
Rarity: UNIQUE
{unique}
Heavy Belt
Unique ID: abc
Item Level: 85
Implicits: 0
+30 to all Attributes
</Item>
    <Item id="2">
Rarity: RARE
Dragon Solace
Crimson Jewel
Unique ID: def
Item Level: 85
Implicits: 0
+3% Chance to Block Attack Damage while Dual Wielding
10% increased Melee Damage
6% increased maximum Life
</Item>
    <Item id="3">
Rarity: MAGIC
Seething Divine Life Flask of Warding
Unique ID: ghi
Item Level: 64
Implicits: 0
66% reduced Amount Recovered
Instant Recovery
</Item>
    <Item id="4">
Rarity: MAGIC
Notable Small Cluster Jewel of the Pupil
Unique ID: jkl
Cluster Jewel Node Count: 2
Item Level: 69
Implicits: 1
{{crafted}}Adds 2 Passive Skills
1 Added Passive Skill is Enduring Composure
</Item>
    <ItemSet id="1" title="^4Early Game {{1}}" useSecondWeaponSet="false">
      <Slot name="Body Armour" itemId="1"/>
      <Slot name="Weapon 1" itemId="0"/>
      <Slot name="Flask 1" itemId="3"/>
    </ItemSet>
    <ItemSet id="2" title="^4Endgame {{2}}" useSecondWeaponSet="false">
      <Slot name="Body Armour" itemId="1"/>
      <Slot name="Ring 1" itemId="2"/>
      <Slot name="Flask 1" itemId="3"/>
      <Slot name="Belt Abyssal Socket 1" itemId="4"/>
    </ItemSet>
  </Items>
  {notes_xml}
</PathOfBuilding>"""


def _library_with(tmp_path, xml: str, *, name: str = "합성 빌드") -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    lib = library.BuildLibrary.load(path)
    lib.add(pob.encode_pob_code(xml), name=name)
    return lib


# ---------------------------------------------------------------------------
# 내장 36종 전수 검증
# ---------------------------------------------------------------------------

def test_bundled_codes_are_all_embedded_and_restorable():
    data = json.loads((DATA / "starters.json").read_text(encoding="utf-8"))
    assert len(data["builds"]) == 36
    for row in data["builds"]:
        assert row.get("code_file") or row.get("code"), row["id"]
        path = DATA / row["code_file"]
        assert path.exists(), row["code_file"]
        raw = path.read_text(encoding="utf-8")
        code = pob.encode_pob_code(raw) if pob.looks_like_xml(raw) else raw.strip()
        assert code, row["id"]
        xml = pob.decode_pob_code(code)
        assert "<PathOfBuilding" in xml, row["id"]
        # 코드 → XML → 코드 왕복에서도 XML 이 그대로 복원된다
        assert "<PathOfBuilding" in pob.decode_pob_code(pob.encode_pob_code(xml))


def test_guide_for_every_bundled_build_parses_fully(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    assert len(lib.builds) == 36
    for build in lib.builds:
        made = guide.build_guide(build)
        assert made.code, build.id
        assert "<PathOfBuilding" in pob.decode_pob_code(made.code), build.id
        assert made.skill_sets, build.id
        assert made.item_sets, build.id
        assert made.name == build.name
        text = guide.render_text(made)
        assert "[스킬 세트]" in text and "[장비 세트]" in text and "[PoB 코드]" in text


def test_pohx_guide_has_all_sets_notes_and_korean(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    build = lib.get("rf-chieftain-pohx")
    made = guide.build_guide(build)
    assert len(made.skill_sets) == 4
    assert len(made.item_sets) == 4
    assert made.skill_sets[0].title.startswith("Lvl 90")
    assert all(skill.title for skill in made.skill_sets)
    assert len(made.specs) == 4
    assert made.specs[0].set_ids == ["1"]
    assert "SRI Totem Math" in made.notes
    assert "^" not in made.notes
    # 젬 레벨/퀄리티·슬롯·한국어 병기
    link = made.skill_sets[0].links[0]
    assert link.slot == "Body Armour"
    assert link.is_main
    assert link.gems[0].name == "Scorching Ray of Immolation"
    assert link.gems[0].level == 20
    assert link.gems[0].korean == "제물의 작열 광선"
    assert any(gem.level == 20 and gem.quality == 20 for gem in link.gems)
    # 유니크 한국어 이름
    uniques = [item for item_set in made.item_sets for item in item_set.items
               if item.kind == "unique"]
    assert uniques
    assert any(item.korean for item in uniques)
    text = guide.render_text(made)
    assert "정의의 화염" in text or "제물의 작열 광선" in text
    assert "Glancing Blows" in text


def test_item_kinds_rare_mods_flasks_and_jewels(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    build = lib.get("rf-chieftain-current")
    made = guide.build_guide(build)
    items = [item for item_set in made.item_sets for item in item_set.items]
    kinds = {item.kind for item in items}
    assert "flask" in kinds
    assert "unique" in kinds
    rare = next(item for item in items if item.kind == "rare")
    assert rare.key_mods
    assert any("Life" in mod or "Resist" in mod for mod in rare.key_mods)


# ---------------------------------------------------------------------------
# 새 시즌 PoB(모르는 이름) 안전 표시
# ---------------------------------------------------------------------------

def test_unknown_gem_and_unique_fall_back_to_english(tmp_path):
    lib = _library_with(tmp_path, make_rich_xml(unknown=True))
    made = guide.build_guide(lib.builds[0])
    assert made.skill_sets[0].links[0].gems[0].name == "Comet of the New Season"
    assert made.skill_sets[0].links[0].gems[0].korean == ""
    unique = next(item for item in made.item_sets[0].items if item.kind == "unique")
    assert unique.display_name == "Brand New Unique"
    assert unique.korean == ""
    text = guide.render_text(made)
    assert "Comet of the New Season" in text
    assert "Brand New Unique" in text


def test_skill_and_item_set_titles_are_cleaned(tmp_path):
    lib = _library_with(tmp_path, make_rich_xml())
    made = guide.build_guide(lib.builds[0])
    assert made.skill_sets[0].title == "Act 1-3 Leveling"
    assert made.skill_sets[0].linked_ids == ["1"]
    assert made.skill_sets[1].title == "Endgame"
    assert made.item_sets[1].title == "Endgame"
    # 메인 젬이 링크 맨 앞에 온다
    assert made.skill_sets[0].links[0].gems[0].name == "Righteous Fire"
    # 비활성 링크도 보존
    assert any(not link.enabled for link in made.skill_sets[1].links)


def test_notes_are_cleaned_and_split_into_headings(tmp_path):
    notes = (
        "\n\t\t^7~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
        "                    Totem Math\n"
        "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^xC8C8C8\n"
        "First paragraph line 1\nline 2\n\n^7Second paragraph^xFFFFFF\n\t\t"
    )
    lib = _library_with(tmp_path, make_rich_xml(notes=notes))
    made = guide.build_guide(lib.builds[0])
    assert ("heading", "Totem Math") in made.notes_blocks
    assert "^" not in made.notes
    assert "First paragraph line 1\nline 2" in made.notes
    assert "Second paragraph" in made.notes


# ---------------------------------------------------------------------------
# 패치노트 연결
# ---------------------------------------------------------------------------

def test_guide_shows_patch_impact_when_analysis_is_connected(tmp_path):
    lib = _library_with(tmp_path, make_rich_xml())
    notes = patchnotes.parse_patch_notes(
        "Skills\nRighteous Fire\n- Now deals 20% less Damage (previously 10%).\n",
        title="3.30 테스트 패치노트",
    )
    result = analysis.analyze(lib, notes, top=5, min_buff=1.0)
    build = lib.builds[0]
    made = guide.build_guide(build, result=result)
    assert made.patch is not None
    assert made.patch.verdict == "red"
    assert made.patch.nerf_count >= 1
    assert made.patch.advice
    text = guide.render_text(made)
    assert "[이번 패치노트 영향]" in text
    assert "너프" in text
    html = guide.render_html(made)
    assert "이번 패치노트 영향" in html
    assert "보완 포인트" in html
    assert "Righteous Fire" in html


# ---------------------------------------------------------------------------
# HTML 내보내기
# ---------------------------------------------------------------------------

def test_html_guide_is_self_contained_and_escaped(tmp_path):
    notes = "<script>alert('x')</script> & <b>굵게</b>"
    lib = _library_with(tmp_path, make_rich_xml(notes=notes))
    made = guide.build_guide(lib.builds[0])
    html = guide.render_html(made)
    assert html.startswith("<!doctype html>")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert 'id="pob-code"' in html
    assert "PoB 코드 복사" in html
    assert "navigator.clipboard" in html
    assert "<details" in html and "<summary" in html
    assert "<style>" in html
    assert "http://" not in html.replace(made.source_url, "")
    assert "콘텐츠 적합도" in html
    assert made.name in html
    # 코드가 HTML 안에 그대로 들어 있다
    assert made.code in html


def test_export_html_writes_file(tmp_path):
    lib = _library_with(tmp_path, make_rich_xml())
    made = guide.build_guide(lib.builds[0])
    target = guide.export_html(made, tmp_path / "out" / "guide.html")
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert made.name in body
    assert guide.safe_filename("빌드/이름:테스트") == "빌드-이름-테스트"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_export_and_text_guide(tmp_path, capsys):
    lib_path = tmp_path / "library.json"
    lib_path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    lib = library.BuildLibrary.load(lib_path)
    entry = lib.add(pob.encode_pob_code(make_rich_xml()), name="합성 빌드")
    out = tmp_path / "guide.html"
    assert cli.main(["--library", str(lib_path), "--export-guide", entry.id,
                     "--out", str(out)]) == 0
    assert out.exists()
    assert "합성 빌드" in out.read_text(encoding="utf-8")
    capsys.readouterr()

    assert cli.main(["--library", str(lib_path), "--guide", entry.id]) == 0
    captured = capsys.readouterr().out
    assert "[스킬 세트]" in captured
    assert "[PoB 코드]" in captured

    assert cli.main(["--library", str(lib_path), "--guide", "없는-빌드"]) == 2


def test_cli_guide_survives_missing_stdout(tmp_path, monkeypatch):
    lib_path = tmp_path / "library.json"
    lib_path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    lib = library.BuildLibrary.load(lib_path)
    entry = lib.add(pob.encode_pob_code(make_rich_xml()), name="합성 빌드")
    out = tmp_path / "guide.html"
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert cli.main(["--library", str(lib_path), "--export-guide", entry.id,
                     "--out", str(out)]) == 0
    assert out.exists()
