"""공식 홈페이지에서 최신 패치노트 목록을 가져온다.

PoE1: 뉴스 RSS(`/news/rss`) + 패치노트 포럼(`/forum/view-forum/patch-notes`)
PoE2: 얼리 액세스 패치노트 포럼(`/forum/view-forum/2212`)

포럼·RSS 모두 GGG 가 서버에서 렌더링해 주는 HTML/XML 만 쓴다(외부 패키지 없음).
같은 스레드가 여러 출처에 나오면 한 번만 남기고, 한 출처가 실패해도 나머지 결과는 돌려준다.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .patchnotes import USER_AGENT, PatchNotesError

GAME_POE1 = "poe1"
GAME_POE2 = "poe2"
GAME_LABELS = {GAME_POE1: "PoE1", GAME_POE2: "PoE2"}
GAME_CHOICES = ("전체", "PoE1", "PoE2")

KST = timezone(timedelta(hours=9))
# GGG 포럼은 비로그인 상태에서 PST/PDT(UTC-8) 로 시각을 보여준다.
FORUM_TZ = timezone(timedelta(hours=-8))


@dataclass(frozen=True)
class NewsSource:
    key: str
    label: str
    url: str
    game: str
    kind: str  # "forum" | "rss"


SOURCES: tuple[NewsSource, ...] = (
    NewsSource(
        "poe1-patch-forum",
        "PoE1 패치노트 포럼",
        "https://www.pathofexile.com/forum/view-forum/patch-notes",
        GAME_POE1,
        "forum",
    ),
    NewsSource(
        "poe2-patch-forum",
        "PoE2 얼리 액세스 패치노트",
        "https://www.pathofexile.com/forum/view-forum/2212",
        GAME_POE2,
        "forum",
    ),
    NewsSource(
        "poe1-news-rss",
        "PoE1 뉴스",
        "https://www.pathofexile.com/news/rss",
        GAME_POE1,
        "rss",
    ),
)


@dataclass
class PatchNoteRef:
    title: str
    url: str
    game: str
    date: str = ""        # KST 기준 YYYY-MM-DD
    date_text: str = ""   # 원문 표기 그대로
    source: str = ""      # 출처 라벨
    is_patch: bool = True

    @property
    def game_label(self) -> str:
        return GAME_LABELS.get(self.game, self.game)

    @property
    def thread_id(self) -> str:
        match = re.search(r"/view-thread/(\d+)", self.url)
        return match.group(1) if match else self.url

    def display(self) -> str:
        bits = [f"[{self.game_label}]", self.title]
        if self.date:
            bits.append(f"({self.date})")
        return " ".join(bits)

    def sort_key(self) -> tuple:
        return (self.date or "0000-00-00", self.thread_id)


@dataclass
class NewsFeed:
    refs: list[PatchNoteRef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(KST))

    def filtered(self, *, game: str | None = None, only_patch: bool = False) -> list[PatchNoteRef]:
        rows = [r for r in self.refs if (not game or r.game == game) and (r.is_patch or not only_patch)]
        return sorted(rows, key=PatchNoteRef.sort_key, reverse=True)

    def latest(self, game: str | None = None) -> PatchNoteRef | None:
        rows = self.filtered(game=game)
        return rows[0] if rows else None

    def counts(self) -> dict[str, int]:
        out = {GAME_POE1: 0, GAME_POE2: 0}
        for ref in self.refs:
            out[ref.game] = out.get(ref.game, 0) + 1
        return out


# ---------------------------------------------------------------------------
# 날짜
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_forum_date(text: str) -> tuple[str, str]:
    """'Nov 22, 2026, 3:44:19 PM' → (KST 날짜 ISO, 원문)"""
    raw = text.strip().strip(",").strip()
    match = re.search(
        r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})(?:,\s*(\d{1,2}):(\d{2}):(\d{2})\s*([APap][Mm]))?",
        raw,
    )
    if not match:
        return "", raw
    month = _MONTHS.get(match.group(1).lower())
    if not month:
        return "", raw
    day = int(match.group(2))
    year = int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)
    if match.group(7):
        if match.group(7).lower() == "pm" and hour != 12:
            hour += 12
        if match.group(7).lower() == "am" and hour == 12:
            hour = 0
    moment = datetime(year, month, day, hour, minute, second, tzinfo=FORUM_TZ)
    return moment.astimezone(KST).date().isoformat(), raw


def parse_rss_date(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return "", raw
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).date().isoformat(), raw


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

_PATCH_HINTS = re.compile(
    r"(patch notes?|hotfix|hotfixes|restart|\b\d+\.\d+(?:\.\d+)?[a-z]?\b|new and changed gems|"
    r"지난\s*패치|패치\s*노트)",
    re.I,
)


def looks_like_patch(title: str) -> bool:
    return bool(_PATCH_HINTS.search(title or ""))


_FORUM_ROW_RE = re.compile(r'<td class="thread">(.*?)</td>', re.S)
_THREAD_LINK_RE = re.compile(r'href="(/forum/view-thread/(\d+))"')
_TITLE_RE = re.compile(r'<div class="title">\s*<a[^>]*>\s*(.*?)\s*</a>', re.S)
_POST_DATE_RE = re.compile(r'<span class="post_date">([^<]*)</span>')


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def parse_forum_listing(html: str, *, source: NewsSource, base: str = "https://www.pathofexile.com") -> list[PatchNoteRef]:
    refs: list[PatchNoteRef] = []
    for row in _FORUM_ROW_RE.findall(html):
        link = _THREAD_LINK_RE.search(row)
        if not link:
            continue
        title_match = _TITLE_RE.search(row)
        title = _clean(title_match.group(1)) if title_match else ""
        if not title:
            continue
        date_match = _POST_DATE_RE.search(row)
        date, date_text = parse_forum_date(date_match.group(1)) if date_match else ("", "")
        refs.append(
            PatchNoteRef(
                title=title,
                url=base + link.group(1),
                game=source.game,
                date=date,
                date_text=date_text,
                source=source.label,
                is_patch=looks_like_patch(title),
            )
        )
    return refs


def parse_rss(xml_text: str, *, source: NewsSource) -> list[PatchNoteRef]:
    refs: list[PatchNoteRef] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PatchNotesError(f"RSS 를 해석하지 못했습니다: {exc}") from exc
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        date, date_text = parse_rss_date(item.findtext("pubDate") or "")
        refs.append(
            PatchNoteRef(
                title=title,
                url=link,
                game=source.game,
                date=date,
                date_text=date_text,
                source=source.label,
                is_patch=looks_like_patch(title),
            )
        )
    return refs


# ---------------------------------------------------------------------------
# 가져오기
# ---------------------------------------------------------------------------

def fetch_source(source: NewsSource, *, timeout: float = 20.0) -> list[PatchNoteRef]:
    request = urllib.request.Request(
        source.url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise PatchNotesError(f"{source.label}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PatchNotesError(f"{source.label}: 연결 실패 ({exc.reason})") from exc
    if source.kind == "rss":
        return parse_rss(body, source=source)
    return parse_forum_listing(body, source=source)


def merge_refs(groups: list[list[PatchNoteRef]]) -> list[PatchNoteRef]:
    """스레드 단위로 합치고 최신순으로 정렬한다. 같은 스레드는 처음 나온 출처를 남긴다."""
    merged: dict[str, PatchNoteRef] = {}
    for group in groups:
        for ref in group:
            key = ref.thread_id
            if key in merged:
                current = merged[key]
                if not current.date and ref.date:
                    current.date = ref.date
                    current.date_text = ref.date_text
                continue
            merged[key] = ref
    return sorted(merged.values(), key=PatchNoteRef.sort_key, reverse=True)


def fetch_news(sources: tuple[NewsSource, ...] = SOURCES, *, timeout: float = 20.0) -> NewsFeed:
    """모든 출처를 시도하고, 실패한 출처는 errors 에 남긴다."""
    from concurrent.futures import ThreadPoolExecutor

    feed = NewsFeed()
    groups: list[list[PatchNoteRef]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(sources))) as pool:
        futures = {source.key: pool.submit(fetch_source, source, timeout=timeout) for source in sources}
        for key, future in futures.items():
            source = next(s for s in sources if s.key == key)
            try:
                groups.append(future.result())
            except Exception as exc:  # noqa: BLE001
                feed.errors.append(f"{source.label} 목록을 가져오지 못했습니다: {exc}")
    feed.refs = merge_refs(groups)
    if not feed.refs and feed.errors:
        raise PatchNotesError(" / ".join(feed.errors))
    return feed
