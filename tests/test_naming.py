from __future__ import annotations

from poe_checker import naming


def test_support_suffix_removed():
    keys = naming.name_keys("Elemental Focus Support")
    assert "elemental focus" in keys
    assert "elemental focus support" in keys


def test_transfigured_gem_has_base_key():
    keys = naming.name_keys("Scorching Ray of Immolation", gem=True)
    assert "scorching ray" in keys
    assert "scorching ray of immolation" in keys


def test_base_key_only_when_base_is_real_gem():
    # Herald of Agony 의 기본 'herald' 는 젬 이름이 아니므로 만들지 않는다
    keys = naming.name_keys("Herald of Agony", gem=True)
    assert "herald" not in keys


def test_foulborn_unique_strips_prefix():
    keys = naming.name_keys("Foulborn Doedre's Scorn", gem=False)
    assert "doedre's scorn" in keys


def test_unique_apostrophe_variants():
    assert naming.norm("Doedre’s Scorn") == naming.norm("Doedre's Scorn")


def test_find_leading_entity_exact_and_inline():
    exact = naming.find_leading_entity("Righteous Fire")
    assert exact is not None and exact[0] == "Righteous Fire"
    inline = naming.find_leading_entity("- Scorching Ray now deals 5% more Damage")
    assert inline is not None
    assert inline[0] == "Scorching Ray"
    assert inline[1].startswith("now deals")


def test_find_leading_entity_unknown():
    assert naming.find_leading_entity("This is not a gem name") is None
