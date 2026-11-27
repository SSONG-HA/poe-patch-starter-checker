from __future__ import annotations

import json

import pytest

from conftest import make_pob_code, make_pob_xml
from poe_checker import buffs, library, patchnotes

NOTES = """
Skills
Righteous Fire
- Now deals 40% more Damage (previously 20%).

Winter Orb
- Now deals 10% more Damage (previously 5%).

Scorching Ray
- Now deals 5% more Damage (previously 4%).

Support Gems
Elemental Focus Support
- Supported Skills now deal 25% more Elemental Damage (previously 20%).

Unique Items
Nebulis
- Now grants 12% increased Elemental Damage per 100 Intelligence (previously 10%).
"""


def _library(tmp_path) -> library.BuildLibrary:
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
    return library.BuildLibrary.load(path)


def test_ranking_order_and_seed_link(tmp_path):
    lib = _library(tmp_path)
    notes = patchnotes.parse_patch_notes(NOTES)
    ranked = buffs.rank_buffs(notes, lib.profiles(), top=10, min_score=1.0)
    names = [c.name for c in ranked]
    assert names[0] == "Righteous Fire"
    assert "Nebulis" in names
    rf = ranked[0]
    assert rf.kind_label == "스킬"
    assert rf.seeds == ["RF 빌드"]
    assert rf.poedb_url().endswith("/Righteous_Fire")


def test_min_score_filters_small_buffs():
    notes = patchnotes.parse_patch_notes(NOTES)
    ranked = buffs.rank_buffs(notes, [], top=10, min_score=30.0)
    names = [c.name for c in ranked]
    assert "Righteous Fire" in names
    assert "Scorching Ray" not in names  # +25% 는 기준 미만
    assert all(c.score >= 30.0 for c in ranked)


def test_kind_filter():
    notes = patchnotes.parse_patch_notes(NOTES)
    ranked = buffs.rank_buffs(notes, [], top=10, min_score=1.0, kinds={"유니크"})
    assert [c.name for c in ranked] == ["Nebulis"]
