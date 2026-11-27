from __future__ import annotations

from datetime import datetime

import pytest

from poe_checker import news, patchnotes


@pytest.fixture
def forum_poe1(fixture_dir):
    return (fixture_dir / "forum_patch_notes_poe1.html").read_text(encoding="utf-8")


@pytest.fixture
def forum_poe2(fixture_dir):
    return (fixture_dir / "forum_patch_notes_poe2.html").read_text(encoding="utf-8")


@pytest.fixture
def rss_text(fixture_dir):
    return (fixture_dir / "news_rss_poe1.xml").read_text(encoding="utf-8")


def test_forum_listing_poe1(forum_poe1):
    source = news.SOURCES[0]
    refs = news.parse_forum_listing(forum_poe1, source=source)
    assert len(refs) == 3
    first = refs[0]
    assert first.game == "poe1"
    assert first.title == "3.30.0d Hotfix 3"
    assert first.url == "https://www.pathofexile.com/forum/view-thread/4019056"
    assert first.is_patch
    # 포럼 시각은 PST(UTC-8) → KST 로 옮긴 날짜
    assert first.date == "2026-11-23"


def test_forum_listing_poe2(forum_poe2):
    source = news.SOURCES[1]
    refs = news.parse_forum_listing(forum_poe2, source=source)
    assert len(refs) == 3
    assert {ref.game for ref in refs} == {"poe2"}
    assert refs[0].title == "0.5.5h Patch Notes"
    assert refs[0].display().startswith("[PoE2] 0.5.5h Patch Notes")


def test_rss_parse(rss_text):
    source = news.SOURCES[2]
    refs = news.parse_rss(rss_text, source=source)
    assert len(refs) == 3
    titles = [ref.title for ref in refs]
    assert "Improvements to Core Item Drops" in titles
    # RSS 는 UTC 시각 → KST 날짜로 변환한다
    assert refs[0].date == "2026-11-18"


def test_looks_like_patch():
    assert news.looks_like_patch("3.30.0d Hotfix 3")
    assert news.looks_like_patch("0.5.5f Patch Notes")
    assert news.looks_like_patch("New and Changed Gems in Path of Exile 1: Covens of Umbra")
    assert not news.looks_like_patch("Covens of Umbra - Live Updates")


def test_merge_and_sort_dedupes_threads(forum_poe1, rss_text):
    poe1_forum = news.parse_forum_listing(forum_poe1, source=news.SOURCES[0])
    rss = news.parse_rss(rss_text, source=news.SOURCES[2])
    # 같은 스레드가 두 출처에 있어도 한 번만 남는다
    duplicated = poe1_forum + rss + rss
    merged = news.merge_refs([poe1_forum, rss, duplicated])
    ids = [ref.thread_id for ref in merged]
    assert len(ids) == len(set(ids))
    dates = [ref.date for ref in merged]
    assert dates == sorted(dates, reverse=True)


def test_feed_filters_and_latest(forum_poe1, forum_poe2):
    feed = news.NewsFeed(refs=news.parse_forum_listing(forum_poe1, source=news.SOURCES[0])
                         + news.parse_forum_listing(forum_poe2, source=news.SOURCES[1]))
    assert feed.counts() == {"poe1": 3, "poe2": 3}
    assert all(ref.game == "poe1" for ref in feed.filtered(game="poe1"))
    assert feed.latest(game="poe2").game == "poe2"
    assert feed.latest(game="poe1").title.startswith("3.30.0d")


def test_fetch_news_tolerates_one_failing_source(monkeypatch, forum_poe1, forum_poe2, rss_text):
    def fake_fetch(source, *, timeout=20.0):
        if source.key == "poe2-patch-forum":
            raise patchnotes.PatchNotesError("HTTP 503")
        if source.kind == "rss":
            return news.parse_rss(rss_text, source=source)
        return news.parse_forum_listing(forum_poe1 if source.game == "poe1" else forum_poe2,
                                        source=source)

    monkeypatch.setattr(news, "fetch_source", fake_fetch)
    feed = news.fetch_news()
    assert feed.refs
    assert any("PoE2" in error for error in feed.errors)
    assert feed.counts()["poe1"] > 0


def test_all_sources_failing_raises(monkeypatch):
    def boom(source, *, timeout=20.0):
        raise patchnotes.PatchNotesError("offline")

    monkeypatch.setattr(news, "fetch_source", boom)
    with pytest.raises(patchnotes.PatchNotesError):
        news.fetch_news()


def test_forum_date_formats():
    assert news.parse_forum_date("Nov 22, 2026, 3:44:19 PM")[0] == "2026-11-23"
    assert news.parse_forum_date("Jan 3, 2026, 12:05:00 AM")[0] == "2026-01-03"
    assert news.parse_forum_date("") == ("", "")


def test_patch_notes_carry_game(fixture_dir):
    body = (fixture_dir / "patch_notes_poe2_055h.txt").read_text(encoding="utf-8")
    notes = patchnotes.parse_patch_notes(body, title="0.5.5h", game="poe2")
    assert notes.game == "poe2"
    assert "Cinder Spider" in notes.text
