from __future__ import annotations

import pytest

from poe_checker import deltas


def test_range_midpoint_buff():
    result = deltas.compare_texts(
        "Linked target gains 219 to 329 Added Fire Damage",
        "Linked target gains 169 to 254 Added Fire Damage",
    )
    assert len(result) == 1
    assert result[0].metric == "damage"
    assert result[0].benefit_pct == pytest.approx(29.6, abs=0.2)
    assert result[0].direction == "buff"


def test_cost_reduction_is_buff():
    (delta,) = deltas.deltas_from_line("Mana Cost reduced from 12 to 9.")
    assert delta.metric == "cost"
    assert delta.benefit_pct > 20


def test_less_magnitude_inverts_damage():
    result = deltas.compare_texts(
        "Now has 35% less Damage",
        "previously 30% less Damage",
    )
    assert result and result[0].benefit_pct < 0  # 감소폭이 커짐 = 너프


def test_less_life_cost_is_buff():
    result = deltas.compare_texts(
        "Supported Skills now cost 20% less Life",
        "Supported Skills cost 15% less Life",
    )
    assert result and result[0].metric == "cost"
    assert result[0].benefit_pct > 0


def test_parenthetical_ignores_gem_level_numbers():
    result = deltas.deltas_from_line(
        "Now deals 39.7 base Fire Damage per second at gem level 1 (previously 49.4)."
    )
    assert len(result) == 1
    assert result[0].old == 49.4
    assert result[0].new == 39.7
    assert result[0].benefit_pct < 0


def test_per_100_ignored():
    result = deltas.deltas_from_line(
        "Now grants 6% increased Elemental Damage per 100 Intelligence (previously 10%)."
    )
    assert len(result) == 1
    assert result[0].old == 10 and result[0].new == 6


def test_keyword_signal_no_longer():
    score, hits = deltas.keyword_signal("No longer grants minion damage")
    assert score < 0 and "no longer" in hits


def test_summarize_nerf_entry():
    signal = deltas.summarize(
        [("Now grants 20% more Spell Damage", "previously 30%")],
        ["Now grants 20% more Spell Damage (previously 30%)."],
    )
    assert signal.direction == "nerf"
    assert signal.worst_delta is not None
