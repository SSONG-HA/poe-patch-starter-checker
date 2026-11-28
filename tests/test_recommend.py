from __future__ import annotations

import json

from conftest import make_pob_code, make_pob_xml
from poe_checker import analysis, datafiles, guide, library, patchnotes, pob, recommend, report

DATA = datafiles.DATA_DIR


def _library_with(folder, *codes: str, names: list[str] | None = None) -> library.BuildLibrary:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "library.json"
    path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    lib = library.BuildLibrary.load(path)
    for index, code in enumerate(codes):
        name = (names or [])[index] if names and index < len(names) else f"빌드 {index + 1}"
        lib.add(code, name=name)
    return lib


def _stats_xml(*, ehp: int, dps: int, main: str = "Righteous Fire",
               supports: tuple[str, ...] = ("Elemental Focus", "Lifetap"),
               uniques: int = 1) -> str:
    """PlayerStat 을 넣은 최소 PoB XML(적합도 자동 추정 검증용)."""
    xml = make_pob_xml(main=main, supports=supports,
                       uniques=tuple(f"Unique {index}" for index in range(1, uniques + 1)))
    stats = (
        f'<PlayerStat stat="TotalEHP" value="{ehp}"/>'
        f'<PlayerStat stat="CombinedDPS" value="{dps}"/>'
    )
    return xml.replace('mainSocketGroup="1"/>', f'mainSocketGroup="1">{stats}</Build>', 1)


# ---------------------------------------------------------------------------
# 프로필 데이터
# ---------------------------------------------------------------------------

def test_profiles_cover_every_bundled_starter():
    starters = json.loads((DATA / "starters.json").read_text(encoding="utf-8"))
    profiles = recommend.load_profiles()
    ids = [row["id"] for row in starters["builds"]]
    assert len(ids) == 36
    for build_id in ids:
        fit = profiles[build_id]
        for key in recommend.FIELD_KEYS:
            assert 1 <= fit.score(key) <= 5, (build_id, key)
        assert fit.tags, build_id
        assert fit.note, build_id
        assert not fit.auto


def test_profile_json_matches_curated_ids():
    raw = json.loads((DATA / "starter_profiles.json").read_text(encoding="utf-8"))
    starters = json.loads((DATA / "starters.json").read_text(encoding="utf-8"))
    assert set(raw["builds"]) == {row["id"] for row in starters["builds"]}


# ---------------------------------------------------------------------------
# 커스텀 PoB 자동 추정
# ---------------------------------------------------------------------------

def test_estimate_fit_reads_pob_stats(tmp_path):
    lib = _library_with(tmp_path / "a", pob.encode_pob_code(
        _stats_xml(ehp=150_000, dps=6_000_000)
    ))
    fit = recommend.fit_for(lib.builds[0].id, lib.profile(lib.builds[0]))
    assert fit.auto
    assert fit.tankiness == 5
    assert fit.bossing == 5
    assert fit.mapping >= 4          # 화염 광역 주문
    assert fit.budget >= 4           # 유니크 1개
    assert "광역" in fit.tags
    assert "EHP" in fit.note


def test_estimate_fit_drops_for_fragile_low_dps(tmp_path):
    lib = _library_with(tmp_path / "b", pob.encode_pob_code(
        _stats_xml(ehp=12_000, dps=150_000, uniques=8)
    ))
    fit = recommend.fit_for(lib.builds[0].id, lib.profile(lib.builds[0]))
    assert fit.tankiness <= 2
    assert fit.bossing == 1
    assert fit.budget <= 2


def test_estimate_fit_neutral_without_stats(tmp_path):
    lib = _library_with(tmp_path / "c", make_pob_code(main="Righteous Fire"))
    fit = recommend.fit_for(lib.builds[0].id, lib.profile(lib.builds[0]))
    assert fit.tankiness == 3 and fit.bossing == 3
    assert fit.auto


def test_estimate_fit_minion_is_easier(tmp_path):
    minion = _library_with(tmp_path / "d", make_pob_code(
        main="Summon Raging Spirit", supports=("Minion Damage",)
    ))
    melee = _library_with(tmp_path / "e", make_pob_code(
        main="Dual Strike", supports=("Melee Physical Damage",)
    ))
    minion_fit = recommend.fit_for(minion.builds[0].id, minion.profile(minion.builds[0]))
    melee_fit = recommend.fit_for(melee.builds[0].id, melee.profile(melee.builds[0]))
    assert minion_fit.ease >= melee_fit.ease
    assert "소환수" in minion_fit.tags


# ---------------------------------------------------------------------------
# 추천 보드
# ---------------------------------------------------------------------------

NOTES = """
Skills
Righteous Fire
- Now deals 30% less Damage (previously 10%).

Skills
Scorching Ray
- Now deals 25% more Damage (previously 10%).

Unique Items
Mageblood
- Now grants 40% increased Flask Effect (previously 30%).
"""


def _board(tmp_path, text: str = NOTES):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    notes = patchnotes.parse_patch_notes(text, title="3.31 테스트")
    result = analysis.analyze(lib, notes, top=10, min_buff=1.0)
    return lib, result


def test_board_has_all_game_builds_and_scores(tmp_path):
    lib, result = _board(tmp_path)
    board = result.recommendations
    assert board is not None
    assert len(board.entries) == 24  # PoE1 스타터
    for entry in board.entries:
        fit = recommend.fit_for(entry.build_id, None)
        for category in recommend.CATEGORY_ORDER:
            expected = recommend.category_base(category, fit) + entry.patch_delta
            assert entry.score_for(category) == round(expected, 2)
        assert entry.reason_for("allrounder")


def test_top_is_sorted_desc_and_limited(tmp_path):
    lib, result = _board(tmp_path)
    board = result.recommendations
    for category in recommend.CATEGORY_ORDER:
        rows = board.top(category, 5)
        assert len(rows) == 5
        scores = [row.score_for(category) for row in rows]
        assert scores == sorted(scores, reverse=True)


def test_category_reasons_differ(tmp_path):
    lib, result = _board(tmp_path)
    entry = result.recommendations.entries[0]
    reasons = {category: entry.reason_for(category) for category in recommend.CATEGORY_ORDER}
    assert reasons["mapping"] != reasons["bossing"]
    assert "맵핑" in reasons["mapping"]
    assert "보스" in reasons["bossing"]
    assert "저자본" in reasons["budget"]


def test_nerfed_build_scores_lower_than_unaffected(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    notes = patchnotes.parse_patch_notes(
        "Skills\nRighteous Fire\n- Now deals 40% less Damage (previously 10%).\n",
        title="3.31 너프",
    )
    result = analysis.analyze(lib, notes, top=10, min_buff=1.0)
    board = result.recommendations
    rf = board.find("rf-chieftain-330")
    assert rf is not None and rf.verdict == "red"
    assert rf.patch_delta < 0
    others = [entry for entry in board.entries if entry.build_id != rf.build_id]
    assert others and max(entry.patch_delta for entry in others) > rf.patch_delta


def test_recommend_rows_shape(tmp_path):
    lib, result = _board(tmp_path)
    rows = recommend.recommend_rows(result.recommendations, "mapping", 3)
    assert len(rows) == 3
    assert len(rows[0]) == 10
    assert rows[0][0] == "1"


def test_error_builds_are_excluded(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    good = lib.get("rf-chieftain-330")
    lib.builds.append(
        type(good)(id="broken", name="깨진 빌드", kind="starter", game="poe1", code="broken-code")
    )
    notes = patchnotes.parse_patch_notes("Skills\nRighteous Fire\n- 10% more Damage.\n", title="t")
    result = analysis.analyze(lib, notes, top=5, min_buff=1.0)
    broken = result.recommendations.find("broken")
    assert broken is not None and broken.error
    assert all(row.build_id != "broken" for row in result.recommendations.top("allrounder", 50))


# ---------------------------------------------------------------------------
# 리포트·가이드 연결
# ---------------------------------------------------------------------------

def test_report_contains_recommendation_sections(tmp_path):
    lib, result = _board(tmp_path)
    text = report.render_text(result)
    assert "[3] 이번 패치 추천 스타터" in text
    assert recommend.CATEGORY_LABELS["budget"] in text
    markdown = report.render_markdown(result)
    assert "## 3. 이번 패치 추천 스타터" in markdown
    assert "적합도(맵·보·탱·저·편)" in markdown and "★" in markdown
    assert "적합도:" in text and "★" in text
    payload = json.loads(report.render_json(result))
    assert set(payload["recommendations"]["categories"]) == set(recommend.CATEGORY_ORDER)
    first = payload["recommendations"]["categories"]["allrounder"]["rows"][0]
    assert first["fit"]["mapping"] >= 1
    assert len(first["fit"]["stars"]["mapping"]) == 5
    assert first["reasons"]["allrounder"]


def test_guide_contains_fit_scores_and_reason(tmp_path):
    lib = library.BuildLibrary.load(tmp_path / "library.json")
    build = lib.get("rf-chieftain-pohx")
    made = guide.build_guide(build)
    assert made.fit is not None
    assert made.fit.mapping == 4 and made.fit.tankiness == 5
    text = guide.render_text(made)
    assert "[콘텐츠 적합도]" in text
    assert "추천 사유" in text
    assert "탱커" in text
    html = guide.render_html(made)
    assert "콘텐츠 적합도" in html
    assert "추천 사유" in html
    assert "탱킹" in html


def test_gui_recommend_detail_text(tmp_path):
    from poe_checker import gui

    lib, result = _board(tmp_path)
    entry = result.recommendations.entries[0]
    text = gui.recommend_detail_text(entry, "mapping")
    assert "[콘텐츠 적합도]" in text
    assert "[추천 사유]" in text
    assert "맵핑" in text
    assert gui.recommend_detail_text(entry, "bossing") != text


def test_custom_build_guide_marks_auto_fit(tmp_path):
    lib = _library_with(tmp_path / "g", make_pob_code(main="Righteous Fire"))
    made = guide.build_guide(lib.builds[0])
    assert made.fit is not None and made.fit.auto
    html = guide.render_html(made)
    assert "자동 추정" in html


# ---------------------------------------------------------------------------
# 고점·전환 추천(무재육성)
# ---------------------------------------------------------------------------

def test_ceiling_category_is_first_and_labeled():
    assert recommend.CATEGORY_ORDER[0] == "ceiling"
    assert "고점" in recommend.CATEGORY_LABELS["ceiling"]
    assert "무재육성" in recommend.CATEGORY_LABELS["ceiling"]


def test_profiles_have_ceiling_and_transition():
    profiles = recommend.load_profiles()
    assert len(profiles) == 36
    for build_id, fit in profiles.items():
        assert 1 <= fit.ceiling <= 5, build_id
        assert 1 <= fit.transition <= 5, build_id
    # 사용자가 든 전환 경로가 큐레이션에 들어 있다
    assert "CoC" in profiles["poison-holy-relic-necro"].path
    assert "칼날 낙하" in profiles["poison-concoction-pathfinder"].path
    assert "RF" in profiles["rf-chieftain-330"].path
    assert "쉐도우" in profiles["coc-forbidden-rite-assassin"].path


def test_ceiling_board_ranks_high_ceiling_no_reroll(tmp_path):
    lib, result = _board(tmp_path)
    board = result.recommendations
    rows = board.top("ceiling", 5)
    assert len(rows) == 5
    scores = [row.score_for("ceiling") for row in rows]
    assert scores == sorted(scores, reverse=True)
    # 같은 직업에서 갈아탈 수 있는 고점 빌드가 상위에 온다
    assert any(row.fit.transition >= 4 for row in rows)
    top = rows[0]
    assert "무재육성 전환" in top.reason_for("ceiling")
    assert top.fit.path


def test_ceiling_prefers_transition_over_cheap_low_ceiling(tmp_path):
    lib, result = _board(tmp_path)
    board = result.recommendations
    cheap = board.find("generals-cry-lacerate-champion")   # 저자본이지만 상한 낮음
    strong = board.find("coc-forbidden-rite-assassin")     # 재육성 없이 갈 수 있는 고점
    assert cheap is not None and strong is not None
    assert strong.score_for("ceiling") > cheap.score_for("ceiling")
    assert strong.score_for("budget") < cheap.score_for("budget")


def test_ceiling_payload_fields(tmp_path):
    lib, result = _board(tmp_path)
    entry = result.recommendations.find("tornado-inquisitor")
    payload = entry.to_dict()
    assert payload["ceiling"] == entry.fit.ceiling
    assert payload["transition"] == entry.fit.transition
    assert payload["path"]
    assert payload["fit"]["ceiling"] == entry.fit.ceiling
    assert payload["reasons"]["ceiling"].startswith("고점")


def test_custom_build_ceiling_estimated_from_pob(tmp_path):
    lib = _library_with(tmp_path / "ceil", pob.encode_pob_code(
        _stats_xml(ehp=90_000, dps=25_000_000, main="Forbidden Rite")
    ))
    build = lib.builds[0]
    # XML 기본 클래스는 머라우더/치프틴 → 같은 계열 고점 전환(4+)
    fit = recommend.fit_for(build.id, lib.profile(build))
    assert fit.auto
    assert fit.ceiling >= 4
    assert fit.transition >= 4
    assert fit.path


def test_low_dps_custom_build_has_low_ceiling(tmp_path):
    lib = _library_with(tmp_path / "low", pob.encode_pob_code(
        _stats_xml(ehp=12_000, dps=200_000)
    ))
    fit = recommend.fit_for(lib.builds[0].id, lib.profile(lib.builds[0]))
    assert fit.ceiling <= 2


def test_report_contains_ceiling_section(tmp_path):
    lib, result = _board(tmp_path)
    text = report.render_text(result)
    assert recommend.CATEGORY_LABELS["ceiling"] in text
    markdown = report.render_markdown(result)
    assert "고점·전환" in markdown
