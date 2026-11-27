from __future__ import annotations

from poe_checker import patchnotes


def test_synthetic_sections_and_entries(synthetic_notes_text):
    notes = patchnotes.parse_patch_notes(synthetic_notes_text, title="3.30.0")
    names = [entry.name for entry in notes.entries]
    assert "Righteous Fire" in names
    assert "Nebulis" in names
    assert "Mind Over Matter" in names
    # `New Gems` 목록에 한 번 더 나온 젬은 하나로 합쳐진다
    assert names.count("Summon Holy Relic of Conviction") == 1
    rf = next(e for e in notes.entries if e.name == "Righteous Fire")
    assert rf.section.lower().startswith("skills")
    assert rf.direction == "nerf"
    assert rf.lines


def test_kinds_classified(synthetic_notes_text):
    notes = patchnotes.parse_patch_notes(synthetic_notes_text)
    kinds = {entry.name: entry.kind for entry in notes.entries}
    assert kinds["Elemental Focus Support"] == "support"
    assert kinds["Nebulis"] == "unique"
    assert kinds["Chieftain"] == "ascendancy"
    assert kinds["Mind Over Matter"] == "keystone"


def test_inline_bullet_creates_entry(synthetic_notes_text):
    notes = patchnotes.parse_patch_notes(synthetic_notes_text)
    assert any(e.name == "Shield Charge" for e in notes.entries)


def test_no_longer_marks_nerf(synthetic_notes_text):
    notes = patchnotes.parse_patch_notes(synthetic_notes_text)
    malevolence = next(e for e in notes.entries if e.name == "Malevolence")
    assert malevolence.direction in ("mixed", "nerf")
    assert "no longer" in malevolence.signal.keyword_hits


def test_real_gem_thread(real_notes_text):
    notes = patchnotes.parse_patch_notes(real_notes_text, title="New and Changed Gems")
    names = [entry.name for entry in notes.entries]
    assert "Flame Link" in names
    assert "Winter Orb" in names
    assert "Transfusion Support" in names
    winter = next(e for e in notes.entries if e.name == "Winter Orb")
    assert winter.direction == "nerf"
    flame = next(e for e in notes.entries if e.name == "Flame Link")
    assert flame.direction == "mixed"
    # 피해 범위(+29.6%)와 최대 생명력 비례 추가 피해(-40%) 두 가지가 잡힌다
    assert len(flame.signal.deltas) == 2
    assert any(d.benefit_pct > 25 for d in flame.signal.deltas)
    assert any(d.benefit_pct < -30 for d in flame.signal.deltas)


def test_html_to_text_strips_scripts_and_keeps_lists():
    html = """
    <html><head><style>body{color:red}</style><script>var x=1;</script></head>
    <body><div class="content"><div class="box-content m-pad">
    <p>Intro line</p>
    <h4>Flame Link</h4>
    <ul><li>New: 10% more Damage</li><li>Old: 5% more Damage</li></ul>
    <br><span class="show-text">Show Differences</span>
    </div></div></body></html>
    """
    text = patchnotes.html_to_text(html)
    assert "Intro line" in text
    assert "Flame Link" in text
    assert "New: 10% more Damage" in text
    assert "color:red" not in text
    assert "var x" not in text
    assert "Show Differences" not in text


def test_merge_duplicate_names():
    text = "Skills\nRighteous Fire\n- Now deals 10% more Damage (previously 5%).\n\nUnique Items\nRighteous Fire\n- Now grants 2% more Damage\n"
    notes = patchnotes.parse_patch_notes(text)
    assert [e.name for e in notes.entries].count("Righteous Fire") == 1
    entry = notes.entries[0]
    assert len(entry.lines) >= 2


def test_bullet_with_other_skill_starts_new_entry():
    text = """Skills
Righteous Fire
- Now deals 20% more Damage (previously 10%).
- Scorching Ray now deals 15% more Damage (previously 10%).
"""
    notes = patchnotes.parse_patch_notes(text)
    names = [e.name for e in notes.entries]
    assert names == ["Righteous Fire", "Scorching Ray"]
    assert notes.entries[1].direction == "buff"
