"""pytest 공통 도우미."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poe_checker import pob  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_pob_xml(
    *,
    class_name: str = "Marauder",
    ascendancy: str = "Chieftain",
    level: int = 95,
    main: str = "Righteous Fire",
    supports: tuple[str, ...] = ("Swift Affliction", "Elemental Focus", "Lifetap"),
    utility: tuple[str, ...] = ("Malevolence", "Purity of Fire"),
    uniques: tuple[str, ...] = ("Nebulis",),
    keystone_nodes: tuple[int, ...] = (11455,),
    tree_version: str = "3_30",
) -> str:
    """테스트용 최소 PoB XML."""
    support_xml = "".join(
        f'<Gem nameSpec="{name}" enabled="true" level="20" quality="20" '
        f'gemId="Metadata/Items/Gems/SupportGemX"/>'
        for name in supports
    )
    utility_xml = "".join(
        f'<Gem nameSpec="{name}" enabled="true" level="20" quality="0" '
        f'gemId="Metadata/Items/Gems/SkillGemX"/>'
        for name in utility
    )
    items = "".join(
        f'<Item id="{index}">\nRarity: UNIQUE\n{name}\nTest Base\n</Item>'
        for index, name in enumerate(uniques, start=1)
    )
    nodes = ",".join(str(node) for node in keystone_nodes)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding>
  <Build level="{level}" targetVersion="3_0" className="{class_name}" ascendClassName="{ascendancy}" mainSocketGroup="1"/>
  <Tree activeSpec="1"><Spec nodes="{nodes}" treeVersion="{tree_version}"/></Tree>
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true" label="" mainActiveSkill="1">
        <Gem nameSpec="{main}" enabled="true" level="20" quality="20" gemId="Metadata/Items/Gems/SkillGemMain"/>
        {support_xml}
      </Skill>
      <Skill enabled="true" label="auras">
        <Gem nameSpec="{utility[0] if utility else 'Clarity'}" enabled="true" level="20" quality="0" gemId="Metadata/Items/Gems/SkillGemAura"/>
      </Skill>
    </SkillSet>
  </Skills>
  <Items activeItemSet="1">{items}</Items>
</PathOfBuilding>"""


def make_pob_code(**kwargs) -> str:
    return pob.encode_pob_code(make_pob_xml(**kwargs))


@pytest.fixture
def make_pob():
    """테스트용 최소 PoB XML 생성기."""
    return make_pob_xml


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURES


@pytest.fixture
def synthetic_notes_text() -> str:
    return (FIXTURES / "patch_notes_synthetic_full.txt").read_text(encoding="utf-8")


@pytest.fixture
def real_notes_text() -> str:
    return (FIXTURES / "patch_notes_330_new_gems.txt").read_text(encoding="utf-8")
