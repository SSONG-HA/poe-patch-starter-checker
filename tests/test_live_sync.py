"""실시간(EXILEFILTER·유튜브) 라이브 수집 테스트 — 네트워크 없이 HTML 파싱·병합만."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import make_pob_code, make_pob_xml
from poe_checker import library, live_sync


# ---------------------------------------------------------------------------
# 오프라인 HTML 픽스처(실제 페이지 구조를 축약)
# ---------------------------------------------------------------------------

LISTING = """
<section><h2>Path of Exile · 3 builds</h2>
<ul class="pp-cards">
<li><a href="/builds/zero-to-hero-holy-relic-poe1-bula/"><b>From Zero to Hero - POISON HOLY RELIC - Part 1 [PoE 3.30]</b><span>Necromancer · Summon Holy Relic of Conviction</span><small>Bula · patch 3.30</small></a></li>
<li><a href="/builds/old-starter-poe1-someone/"><b>Old League Starter</b><span>Slayer · Cyclone</span><small>Someone · patch 3.29</small></a></li>
<li><a href="/builds/not-a-starter-poe1-other/"><b>400M Damage Shrine Stacker</b><span>Hierophant · Rolling Magma</span><small>Phoenix &amp; co · patch 3.30</small></a></li>
</ul></section>
<section><h2>Path of Exile 2 · 1 build</h2>
<ul class="pp-cards">
<li><a href="/builds/zero-to-hero-grenade-poe2-jonno/"><b>Zero to Hero Grenade Amazon</b><span>Amazon · Explosive Grenade</span><small>jonno_poe · patch 0.5.5</small></a></li>
</ul></section>
"""

DETAIL = """
<html><head><title>From Zero to Hero - POISON HOLY RELIC - Part 1 [PoE 3.30] · PoE1 · EXILEFILTER PRO</title></head>
<body><p class="pp-lead">Witch / Necromancer · Summon Holy Relic of Conviction · level 92</p>
<dl class="pp-kv">
<div><dt>Author</dt><dd>Bula</dd></div>
<div><dt>Game</dt><dd>Path of Exile</dd></div>
<div><dt>Declared patch</dt><dd>3.30</dd></div>
<div><dt>PoB tree</dt><dd>3.30</dd></div>
<div><dt>Published</dt><dd>2026-11-17</dd></div>
</dl>
<h2>PoB numbers</h2>
<ul class="pp-stats">
<li><span>DPS (PoB)</span><b>6.241.771</b></li>
<li><span>Life</span><b>5076</b></li>
<li><span>Energy Shield</span><b>5</b></li>
<li><span>eHP (PoB)</span><b>63.763</b></li>
</ul>
<h2>Source</h2>
<ul class="pp-list">
<li><a href="https://www.youtube.com/watch?v=abc123DEF45">Author video</a></li>
<li><a href="https://pobb.in/4wjp33UBC-Ge">Path of Building</a></li>
</ul></body></html>
"""

DETAIL_NO_POB = DETAIL.replace("https://pobb.in/4wjp33UBC-Ge", "https://example.test/none")

def _lockup(video_id: str, title: str, age: str = "") -> dict:
    parts = [{"text": {"content": "4.8K"}}]
    if age:
        parts.append({"text": {"content": age}})
    return {
        "richItemRenderer": {
            "content": {
                "lockupViewModel": {
                    "contentId": video_id,
                    "metadata": {
                        "lockupMetadataViewModel": {
                            "title": {"content": title},
                            "metadata": {"contentMetadataViewModel": {"metadataRows": [
                                {"metadataParts": parts}
                            ]}},
                        }
                    },
                }
            }
        }
    }


CHANNEL_DATA = {
    "contents": {
        "twoColumnBrowseResultsRenderer": {
            "tabs": [
                {
                    "tabRenderer": {
                        "content": {
                            "richGridRenderer": {
                                "contents": [
                                    _lockup(
                                        "vidStarter01",
                                        "PoE 3.30 VERY Budget Holy Relic Showcase (Smooth league start viable)",
                                        "2 days ago",
                                    ),
                                    _lockup("vidOldEvent02", "OUR STARTER BUILD IN LEGACY OF PHRECIA 2.0", "1 month ago"),
                                    _lockup("vidNoPob03", "I'm Being Serious"),
                                ]
                            }
                        }
                    }
                }
            ]
        }
    }
}

CHANNEL_LOCKUP = "<script>var ytInitialData = " + json.dumps(CHANNEL_DATA) + ";</script>"

CHANNEL_LEGACY = """
<script>var ytInitialData = {"contents":[{"videoRenderer":{
 "videoId":"legacyVid01",
 "title":{"runs":[{"text":"My 3.30 League Start Guide"}]},
 "publishedTimeText":{"simpleText":"5 days ago"}}}]};</script>
"""

WATCH = """
<html><script>var ytInitialPlayerResponse = {"videoDetails":{
 "shortDescription":"Build guide\\nPOBB: https://pobb.in/NPkmGIlRh-JF\\nthanks"}};</script>
<script>var ytInitialData = {"engagementPanels":[{"attributedDescription":{
 "content":"Int stacker from zero should be fun\\nPOBB: https://pobb.in/NPkmGIlRh-JF\\n\\nMusic used"}}]};</script></html>
"""


class FakeWeb:
    """URL → HTML/코드 사전. 등록되지 않은 주소는 예외를 낸다(실패 경로 검증용)."""

    def __init__(self, pages: dict[str, str], codes: dict[str, str] | None = None):
        self.pages = pages
        self.codes = codes or {}
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url in self.pages:
            return self.pages[url]
        raise live_sync.LiveSyncError(f"가짜 응답 없음: {url}")

    def pobb(self, url: str) -> str:
        self.calls.append(url)
        if url in self.codes:
            return self.codes[url]
        raise live_sync.LiveSyncError(f"가짜 PoB 없음: {url}")


def _empty_library(tmp_path) -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"schema": 1, "builds": []}), encoding="utf-8")
    return library.BuildLibrary.load(path)


def _web(*, with_youtube: bool = True) -> FakeWeb:
    pages = {
        live_sync.EXILEBUILDS_URL: LISTING,
        "https://exilebuilds.com/builds/zero-to-hero-holy-relic-poe1-bula/": DETAIL,
        "https://exilebuilds.com/builds/old-starter-poe1-someone/": DETAIL.replace("3.30", "3.29"),
        "https://exilebuilds.com/builds/zero-to-hero-grenade-poe2-jonno/": DETAIL.replace(
            "Path of Exile<", "Path of Exile 2<"
        ),
    }
    codes = {
        "https://pobb.in/4wjp33UBC-Ge": make_pob_code(main="Summon Holy Relic of Conviction"),
        "https://pobb.in/NPkmGIlRh-JF": make_pob_code(main="Frost Blades", ascendancy="Raider"),
    }
    if with_youtube:
        pages[live_sync.channel_url("BulaPoE")] = CHANNEL_LOCKUP
        pages["https://www.youtube.com/watch?v=vidStarter01"] = WATCH
    return FakeWeb(pages, codes)


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

def test_parse_listing_sections_and_fields():
    items = live_sync.parse_listing(LISTING)
    assert len(items) == 4
    first = items[0]
    assert first.game == "poe1"
    assert "POISON HOLY RELIC" in first.title
    assert first.url == "https://exilebuilds.com/builds/zero-to-hero-holy-relic-poe1-bula/"
    assert first.author == "Bula"
    assert first.patch == "3.30"
    assert first.ascendancy == "Necromancer"
    assert first.main_skill == "Summon Holy Relic of Conviction"
    # 엔티티(&amp;)와 PoE2 섹션 구분
    assert items[2].author == "Phoenix & co"
    assert items[3].game == "poe2"
    assert items[3].patch == "0.5.5"


def test_starter_and_patch_filters():
    assert live_sync.is_starter("From Zero to Hero - Part 1")
    assert live_sync.is_starter("My League Starter")
    assert not live_sync.is_starter("400M Damage Shrine Stacker")
    assert live_sync.is_current_patch("3.30", "poe1")
    assert not live_sync.is_current_patch("3.29", "poe1")
    assert live_sync.is_current_patch("0.5.5", "poe2")
    # 유튜브 제목: 지난 시즌 표기만 있으면 제외
    assert live_sync.title_patch_ok("PoE 3.30 starter guide", "poe1")
    assert live_sync.title_patch_ok("My leaguestarter", "poe1")
    assert not live_sync.title_patch_ok("STARTER BUILD IN LEGACY OF PHRECIA 2.0", "poe1")


def test_parse_detail_extracts_pob_author_and_stats():
    detail = live_sync.parse_detail(DETAIL, url="https://exilebuilds.com/builds/x/")
    assert detail.author == "Bula"
    assert detail.game == "poe1"
    assert detail.class_name == "Witch"
    assert detail.ascendancy == "Necromancer"
    assert detail.main_skill == "Summon Holy Relic of Conviction"
    assert detail.level == 92
    assert detail.patch == "3.30"
    assert detail.published == "2026-11-17"
    assert detail.pobb_url == "https://pobb.in/4wjp33UBC-Ge"
    assert detail.youtube_url == "https://www.youtube.com/watch?v=abc123DEF45"
    assert detail.dps == 6_241_771
    assert detail.life == 5_076
    assert detail.ehp == 63_763
    assert detail.stats["es"] == 5


def test_parse_detail_without_pob_link():
    detail = live_sync.parse_detail(DETAIL_NO_POB)
    assert detail.pobb_url == ""


def test_parse_detail_spanish_labels():
    text = DETAIL.replace("Author", "Autor").replace("Published", "Publicación") \
        .replace("Declared patch", "Parche declarado").replace("Game", "Juego") \
        .replace("level 92", "nivel 92")
    detail = live_sync.parse_detail(text)
    assert detail.author == "Bula" and detail.level == 92 and detail.patch == "3.30"


def test_parse_channel_supports_lockup_and_legacy_renderers():
    videos = live_sync.parse_channel(CHANNEL_LOCKUP)
    assert [v.video_id for v in videos] == ["vidStarter01", "vidOldEvent02", "vidNoPob03"]
    assert videos[0].age == "2 days ago"  # 문서 순서 유지
    legacy = live_sync.parse_channel(CHANNEL_LEGACY)
    assert legacy[0].video_id == "legacyVid01"
    assert live_sync.parse_channel("no data here") == []


def test_parse_description_and_pobb_link():
    description = live_sync.parse_description(WATCH)
    assert "POBB" in description and "Music used" in description
    assert live_sync.pobb_in_text(description) == "https://pobb.in/NPkmGIlRh-JF"
    assert live_sync.pobb_in_text("pobb.in/abcDEF123") == "https://pobb.in/abcDEF123"
    assert live_sync.pobb_in_text("no link") == ""


def test_live_id_is_stable_and_readable():
    first = live_sync.live_id("eb", "https://exilebuilds.com/builds/some-build-poe1-x/")
    again = live_sync.live_id("eb", "https://exilebuilds.com/builds/some-build-poe1-x/")
    assert first == again and first.startswith("eb-some-build-poe1-x")
    video = live_sync.live_id("yt", "https://www.youtube.com/watch?v=vidStarter01")
    assert video.startswith("yt-vidStarter01")


# ---------------------------------------------------------------------------
# 병합
# ---------------------------------------------------------------------------

def test_sync_live_merges_exilebuilds_and_youtube(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web()
    report = live_sync.sync_live(
        lib, games=["poe1"], max_per_game=4, max_total=6, max_per_channel=1,
        fetcher=web, pobb_fetcher=web.pobb,
    )
    assert report.saved and report.changed
    assert report.counts["exilebuilds"] >= 1
    assert report.counts["youtube"] >= 1
    # 지난 시즌(3.29)·스타터 아닌 제목은 들어오지 않는다
    names = [build.name for build in lib.builds]
    assert not any("Cyclone" in name for name in names)
    assert not any("rolling" in name.lower() for name in names)
    entry = lib.get(report.added[0])
    assert entry is not None
    assert entry.game == "poe1"
    assert entry.kind == "starter"
    assert entry.source.startswith("https://pobb.in/")
    assert "Bula" in entry.origin
    # 한국어 이름·메모(번역 사전 + 생명력/EHP/DPS)
    assert "성결의 수호자" in entry.name or "신성한 유물" in entry.name
    assert "EXILEFILTER 라이브 수집" in entry.note
    assert "생명력" in entry.note
    assert lib.profile(entry).main_skill_names[0] == "Summon Holy Relic of Conviction"
    # 디스크에 저장
    again = library.BuildLibrary.load(lib.path)
    assert again.get(entry.id) is not None


def test_youtube_build_already_found_is_not_added_twice(tmp_path):
    """같은 크리에이터·같은 주력 스킬이 EXILEFILTER 로 이미 들어왔으면 유튜브 사본은 건너뛴다."""
    lib = _empty_library(tmp_path)
    web = _web()
    web.codes["https://pobb.in/NPkmGIlRh-JF"] = make_pob_code(main="Summon Holy Relic of Conviction")
    report = live_sync.sync_live(lib, games=["poe1"], max_per_game=4, max_total=6,
                                 max_per_channel=1, fetcher=web, pobb_fetcher=web.pobb)
    assert report.counts["exilebuilds"] >= 1
    assert report.counts["youtube"] == 0
    assert not any(build.origin.startswith("유튜브") for build in lib.builds)


def test_second_sync_does_not_duplicate(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web()
    first = live_sync.sync_live(lib, games=["poe1"], max_per_game=4, max_total=6,
                                max_per_channel=1, fetcher=web, pobb_fetcher=web.pobb)
    count = len(lib.builds)
    second = live_sync.sync_live(lib, games=["poe1"], max_per_game=4, max_total=6,
                                 max_per_channel=1, fetcher=web, pobb_fetcher=web.pobb)
    assert len(lib.builds) == count
    assert not second.added and not second.changed
    assert second.unchanged
    assert first.added


def test_sync_live_skips_detail_without_pob(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web(with_youtube=False)
    web.pages["https://exilebuilds.com/builds/zero-to-hero-holy-relic-poe1-bula/"] = DETAIL_NO_POB
    report = live_sync.sync_live(lib, games=["poe1"], max_total=4, include_youtube=False,
                                 fetcher=web, pobb_fetcher=web.pobb)
    assert report.skipped
    assert not report.added


def test_listing_failure_is_graceful(tmp_path):
    lib = _empty_library(tmp_path)

    def failing(url: str) -> str:
        raise live_sync.LiveSyncError("연결 실패(테스트)")

    report = live_sync.sync_live(lib, games=["poe1"], fetcher=failing,
                                 pobb_fetcher=lambda url: "", include_youtube=False)
    assert report.errors
    assert not report.changed
    assert not report.saved
    assert len(lib.builds) == 0


def test_pobb_failure_is_recorded_and_other_builds_continue(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web(with_youtube=False)
    good_code = web.codes["https://pobb.in/4wjp33UBC-Ge"]

    def pobb(url: str) -> str:
        if "4wjp" in url:
            raise live_sync.LiveSyncError("pobb 실패(테스트)")
        return good_code

    report = live_sync.sync_live(lib, games=["poe1"], max_total=4, include_youtube=False,
                                 fetcher=web, pobb_fetcher=pobb)
    assert any("pobb 실패" in message for message in report.errors)
    assert not report.added


def test_detail_failure_is_recorded(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web(with_youtube=False)
    target = "https://exilebuilds.com/builds/zero-to-hero-holy-relic-poe1-bula/"
    web.pages.pop(target)
    report = live_sync.sync_live(lib, games=["poe1"], max_total=4, include_youtube=False,
                                 fetcher=web, pobb_fetcher=web.pobb)
    assert any(target in message for message in report.errors)


def test_dry_run_does_not_save(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web(with_youtube=False)
    report = live_sync.sync_live(lib, games=["poe1"], max_total=4, include_youtube=False,
                                 dry_run=True, fetcher=web, pobb_fetcher=web.pobb)
    assert report.added and not report.saved
    assert lib.path.read_text(encoding="utf-8").strip().endswith("[]}") or "pobb" not in lib.path.read_text(encoding="utf-8")


def test_max_per_game_limits_additions(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web(with_youtube=False)
    web.pages["https://exilebuilds.com/builds/old-starter-poe1-someone/"] = DETAIL
    report = live_sync.sync_live(lib, games=["poe1"], max_per_game=1, max_total=5,
                                 include_youtube=False, fetcher=web, pobb_fetcher=web.pobb)
    assert len(report.added) == 1


def test_report_lines_and_payload():
    report = live_sync.LiveSyncReport(games=("poe1",), added=["a"], counts={"exilebuilds": 1, "youtube": 0})
    assert "EXILEFILTER 1" in report.summary()
    assert report.to_dict()["total"] == 1
    assert any(line.startswith("  + a") for line in report.lines())


def test_custom_builds_are_preserved(tmp_path):
    lib = _empty_library(tmp_path)
    custom = lib.add(make_pob_code(main="Winter Orb"), name="내 빌드")
    web = _web(with_youtube=False)
    live_sync.sync_live(lib, games=["poe1"], max_total=4, include_youtube=False,
                        fetcher=web, pobb_fetcher=web.pobb)
    assert lib.get(custom.id) is not None
    assert lib.get(custom.id).name == "내 빌드"


def test_deadline_budget_skips_remaining_work(tmp_path):
    lib = _empty_library(tmp_path)
    web = _web(with_youtube=False)

    def slow(url: str) -> str:
        time.sleep(0.02)  # 목록을 받는 사이 시간 예산이 끝난다
        return web(url)

    report = live_sync.sync_live(lib, games=["poe1"], include_youtube=False,
                                 fetcher=slow, pobb_fetcher=web.pobb, deadline_seconds=0.001)
    assert not report.changed
    assert any("시간 예산" in note for note in report.skipped)
    assert len(lib.builds) == 0
