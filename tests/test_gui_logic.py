from __future__ import annotations

import json

from conftest import make_pob_code
from poe_checker import analysis, gui, library, patchnotes


def _result(tmp_path, notes_text: str) -> analysis.AnalysisResult:
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "builds": [
                    {
                        "id": "rf",
                        "name": "RF 빌드",
                        "kind": "custom",
                        "code": make_pob_code(main="Righteous Fire", uniques=("Nebulis",)),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lib = library.BuildLibrary.load(path)
    notes = patchnotes.parse_patch_notes(notes_text, title="test")
    return analysis.analyze(lib, notes, top=5, min_buff=1.0)


NOTES = """
Skills
Righteous Fire
- Now deals 40% more Damage (previously 20%).

Unique Items
Nebulis
- Now grants 12% increased Elemental Damage per 100 Intelligence (previously 10%).
"""


def test_verdict_rows_shape(tmp_path):
    result = _result(tmp_path, NOTES)
    rows = gui.verdict_rows(result)
    assert len(rows) == 1
    assert rows[0][1] == "🟢 무사통과"
    assert rows[0][2] == "RF 빌드"
    assert rows[0][5]


def test_verdict_detail_text_contains_evidence(tmp_path):
    notes = "Skills\nRighteous Fire\n- Now deals 20% less Damage (previously 10%).\n"
    result = _result(tmp_path, notes)
    verdict = result.verdicts[0]
    text = gui.verdict_detail_text(verdict)
    assert "🔴" in text
    assert "주력 스킬" in text
    assert "Righteous Fire" in text
    assert "Now deals 20% less Damage" in text


def test_buff_rows_and_detail(tmp_path):
    result = _result(tmp_path, NOTES)
    rows = gui.buff_rows(result)
    assert rows and rows[0][1] == "Righteous Fire"
    detail = gui.buff_detail_text(result.buffs[0])
    assert "시드 빌드" in detail
    assert "poedb.tw" in detail
