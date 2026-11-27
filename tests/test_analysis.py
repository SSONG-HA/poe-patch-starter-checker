from __future__ import annotations

import json

from conftest import make_pob_code
from poe_checker import analysis, library, patchnotes, report


def _library(tmp_path) -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "builds": [
                    {"id": "rf", "name": "RF 빌드", "kind": "custom", "code": make_pob_code()}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return library.BuildLibrary.load(path)


def test_empty_patch_notes_warns(tmp_path):
    notes = patchnotes.parse_patch_notes(
        "Since the league launched, we have been reading feedback. Monsters are too tough now.",
        title="mechanics",
    )
    result = analysis.analyze(_library(tmp_path), notes, top=5)
    assert result.entry_count == 0
    assert result.warnings
    text = report.render_text(result)
    assert "⚠" in text
    payload = json.loads(report.render_json(result))
    assert payload["patch"]["entry_count"] == 0


def test_filtered_buffs_respects_threshold(tmp_path):
    notes = patchnotes.parse_patch_notes(
        "Skills\nRighteous Fire\n- Now deals 40% more Damage (previously 20%).\n"
        "Winter Orb\n- Now deals 10% more Damage (previously 5%).\n"
    )
    result = analysis.analyze(_library(tmp_path), notes, top=1, min_buff=30.0)
    assert len(result.buffs) >= 2          # 전체 후보는 모두 보관
    shown = result.filtered_buffs()
    assert len(shown) == 1
    assert shown[0].name == "Righteous Fire"
