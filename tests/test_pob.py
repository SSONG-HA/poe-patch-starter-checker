from __future__ import annotations

import pytest

from conftest import make_pob_code, make_pob_xml
from poe_checker import pob


def test_code_roundtrip():
    xml = make_pob_xml()
    code = pob.encode_pob_code(xml)
    assert pob.decode_pob_code(code) == xml
    # padding 이 붙은 입력도 받아야 한다
    assert pob.decode_pob_code(code + "==") == xml


def test_parse_profile_basics():
    profile = pob.load_build(make_pob_code())
    assert profile.class_name == "Marauder"
    assert profile.ascendancy == "Chieftain"
    assert profile.level == 95
    assert profile.tree_version == "3_30"


def test_main_skill_beats_utility_aura():
    profile = pob.load_build(
        make_pob_code(main="Righteous Fire", utility=("Malevolence",), supports=("Swift Affliction",))
    )
    assert profile.main_skill_names[0] == "Righteous Fire"
    assert "Malevolence" in [g.name for g in profile.secondary_skills]


def test_supports_and_uniques_and_keystones():
    profile = pob.load_build(make_pob_code(uniques=("Nebulis", "Cloak of Flame")))
    assert set(profile.support_names) >= {"Swift Affliction", "Elemental Focus", "Lifetap"}
    assert profile.uniques == ["Nebulis", "Cloak of Flame"]
    assert profile.keystones == ["Chaos Inoculation"]


def test_xml_passthrough():
    xml = make_pob_xml(main="Tornado of Elemental Turbulence", class_name="Templar", ascendancy="Inquisitor")
    profile = pob.load_build(xml)
    assert profile.main_skill_names[0] == "Tornado of Elemental Turbulence"
    assert profile.ascendancy == "Inquisitor"


def test_bad_code_raises():
    with pytest.raises(pob.PobError):
        pob.load_build("not-a-pob-code")
