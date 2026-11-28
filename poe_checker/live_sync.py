"""「스타터 최신화」 2단계 — 커뮤니티·유튜브 라이브 수집.

원격 카탈로그(`catalog.py`)에는 시즌 중에 새로 올라온 빌드가 없다. 이 모듈은
`스타터 최신화` 를 누를 때 **실제로 열려 있는 공개 소스**에서 현재 시즌
`Zero to Hero` / 리그 스타터를 찾아 PoB 를 받고 라이브러리에 병합한다.

    ① EXILEFILTER PRO (exilebuilds.com) 빌드 목록 → 상세 페이지 → `pobb.in/...`
    ② 주요 크리에이터 유튜브 채널 `/videos` → 영상 설명란의 `pobb.in/...`

- 새 빌드는 PoB XML 을 풀어 주력 스킬·전직·생명력·EHP·DPS·유니크를 뽑고,
  `data/names_kr.json`(poedb.tw/kr 색인)으로 한국어 표기를 붙여 이름/메모를 만든다.
- 같은 빌드는 URL 로 만든 결정적 id 로 중복을 걸러 내고, 이미 있는 빌드는 다시 받지 않는다.
- 어느 단계가 실패해도 예외를 밖으로 던지지 않고 `errors` 에 남긴다(전체 최신화는 계속).
- 네트워크·시간 예산(기본 90초)을 넘으면 남은 후보를 건너뛰고 지금까지를 반영한다.
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import datafiles, library as library_mod, pob
from .patchnotes import USER_AGENT

EXILEBUILDS_URL = "https://exilebuilds.com/builds/?lang=en"
EXILEBUILDS_SITE = "https://exilebuilds.com"
YOUTUBE_SITE = "https://www.youtube.com"

#: 게임별 현재 시즌 패치 표기(목록에 이 값이 붙은 빌드만 최신으로 본다).
CURRENT_PATCH: dict[str, tuple[str, ...]] = {
    datafiles.GAME_POE1: ("3.30",),
    datafiles.GAME_POE2: ("0.5",),
}

#: 제목에 이 말이 있어야 "스타터/제로 투 히어로" 로 본다.
STARTER_RE = re.compile(
    r"zero\s*to\s*hero|starter|league\s*-?\s*start|leaguestarter|leveling\s+guide|스타터",
    re.I,
)

#: 사용자가 콕 집어 언급한 크리에이터 — 후보 정렬에서 우선한다.
FOCUS_AUTHORS = (
    "bula", "exiled cat", "magefist", "kamisu", "pohx", "까까모리", "sanavixx",
    "palsteron", "zizaran", "jungroan",
)

MAX_PAGE_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
DEFAULT_DEADLINE = 90.0


class LiveSyncError(RuntimeError):
    """라이브 소스를 읽지 못했을 때(개별 단계는 errors 로 흡수된다)."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _ua_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def http_get(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    request = urllib.request.Request(url, headers=_ua_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_PAGE_BYTES)
    except urllib.error.HTTPError as exc:
        raise LiveSyncError(f"응답 {exc.code} — {url}") from exc
    except urllib.error.URLError as exc:
        raise LiveSyncError(f"연결하지 못했습니다({exc.reason}) — {url}") from exc
    except OSError as exc:  # pragma: no cover - 환경별 소켓 오류
        raise LiveSyncError(f"읽지 못했습니다({exc}) — {url}") from exc
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# EXILEFILTER 목록/상세 파싱
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"<h2>\s*([^<]+?)\s*</h2>(.*?)(?=<h2>|</section>|$)", re.S)
_ITEM_RE = re.compile(
    r'<li>\s*<a href="([^"]+)"[^>]*>\s*<b>(.*?)</b>\s*<span>(.*?)</span>\s*<small>(.*?)</small>',
    re.S,
)
_PATCH_RE = re.compile(r"(?:patch|parche)\s*([0-9][0-9.]*)", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_LEVEL_RE = re.compile(r"(?:nivel|level)\s*(\d{1,3})", re.I)


@dataclass
class ListingItem:
    """EXILEFILTER 목록 한 줄."""

    game: str
    title: str
    url: str
    classes: str = ""
    author: str = ""
    patch: str = ""

    @property
    def ascendancy(self) -> str:
        return self.classes.split("·")[0].strip() if self.classes else ""

    @property
    def main_skill(self) -> str:
        parts = [part.strip() for part in self.classes.split("·")]
        return parts[1] if len(parts) > 1 else ""


def _clean(text: str) -> str:
    return html_mod.unescape(_TAG_RE.sub("", text or "")).strip()


def _game_of(header: str) -> str:
    return datafiles.GAME_POE2 if "2" in header else datafiles.GAME_POE1


def parse_listing(text: str, *, base: str = EXILEBUILDS_SITE) -> list[ListingItem]:
    """빌드 목록 HTML → 목록 항목들(게임 섹션별)."""
    items: list[ListingItem] = []
    for section in _SECTION_RE.finditer(text or ""):
        header, body = _clean(section.group(1)), section.group(2)
        game = _game_of(header)
        for match in _ITEM_RE.finditer(body):
            href, title, classes, small = match.groups()
            url = urllib.parse.urljoin(base + "/", html_mod.unescape(href))
            small_text = _clean(small)
            patch_match = _PATCH_RE.search(small_text)
            author = small_text.split("·")[0].strip()
            items.append(
                ListingItem(
                    game=game,
                    title=_clean(title),
                    url=url.split("?")[0],
                    classes=_clean(classes),
                    author=author,
                    patch=patch_match.group(1).strip(".") if patch_match else "",
                )
            )
    return items


def is_starter(title: str) -> bool:
    return bool(STARTER_RE.search(title or ""))


_VERSION_TOKEN_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")


def title_patch_ok(title: str, game: str) -> bool:
    """제목에 다른 시즌 표기(3.29·2.0 등)만 있으면 지난 시즌 영상으로 본다."""
    tokens = _VERSION_TOKEN_RE.findall(title or "")
    if not tokens:
        return True
    wanted = CURRENT_PATCH.get(datafiles.normalize_game(game), ())
    return any(
        token == want or token.startswith(want + ".") for token in tokens for want in wanted
    )


def is_current_patch(patch: str, game: str) -> bool:
    """목록의 패치 표기가 현재 시즌(3.30 / 0.5, 0.5.5 …)인지."""
    value = (patch or "").strip()
    if not value:
        return False
    return any(value == want or value.startswith(want + ".") for want in
               CURRENT_PATCH.get(datafiles.normalize_game(game), ()))


def _number(text: str) -> float:
    """'6.241.771' · '5763' · '38.167' 같은 표기를 숫자로."""
    raw = (text or "").strip().replace("%", "").replace(" ", "")
    raw = re.sub(r"[^0-9.,\-]", "", raw)
    if not raw:
        return 0.0
    raw = raw.replace(",", "") if "," in raw and "." not in raw else raw
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


_STAT_RE = re.compile(r"<li>\s*<span>(.*?)</span>\s*<b>(.*?)</b>\s*</li>", re.S)
_KV_RE = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
_LEAD_RE = re.compile(r'<p class="pp-lead">(.*?)</p>', re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_POBB_RE = re.compile(r"(?:https?://)?pobb\.in/([A-Za-z0-9_\-]{4,})", re.I)
_YT_RE = re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_\-]{6,})", re.I)


@dataclass
class BuildDetail:
    """EXILEFILTER 상세 페이지에서 뽑은 빌드 정보."""

    url: str = ""
    title: str = ""
    game: str = datafiles.GAME_POE1
    author: str = ""
    class_name: str = ""
    ascendancy: str = ""
    main_skill: str = ""
    level: int | None = None
    patch: str = ""
    published: str = ""
    pobb_url: str = ""
    youtube_url: str = ""
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def life(self) -> float:
        return self.stats.get("life", 0.0)

    @property
    def ehp(self) -> float:
        return self.stats.get("ehp", 0.0)

    @property
    def dps(self) -> float:
        return self.stats.get("dps", 0.0)


def parse_detail(text: str, *, url: str = "") -> BuildDetail:
    """상세 페이지 HTML → BuildDetail(스페인어/영어 표기 모두)."""
    body = text or ""
    detail = BuildDetail(url=url)
    title_match = _TITLE_RE.search(body)
    if title_match:
        detail.title = _clean(title_match.group(1)).split(" · ")[0].strip()

    kv: dict[str, str] = {}
    for key, value in _KV_RE.findall(body):
        kv[_clean(key).lower()] = _clean(value)

    detail.author = kv.get("autor") or kv.get("author") or ""
    declared = kv.get("parche declarado") or kv.get("declared patch") or kv.get("patch") or ""
    patch_match = (
        _PATCH_RE.search(declared)
        or re.match(r"([0-9]+(?:\.[0-9]+)*)", declared.strip())
        or _PATCH_RE.search(kv.get("árbol del pob", "") or kv.get("pob tree", ""))
    )
    detail.patch = patch_match.group(1).strip(".") if patch_match else ""
    detail.published = kv.get("publicación") or kv.get("published") or ""

    juego = kv.get("juego") or kv.get("game") or ""
    if "2" in juego:
        detail.game = datafiles.GAME_POE2
    elif "poe2" in (url or "").lower() or "-poe2-" in (url or "").lower():
        detail.game = datafiles.GAME_POE2

    lead = _LEAD_RE.search(body)
    if lead:
        parts = [_clean(part) for part in re.split(r"·", _clean(lead.group(1)))]
        parts = [part for part in parts if part]
        if parts:
            names = [part.strip() for part in parts[0].split("/") if part.strip()]
            if len(names) > 1:
                detail.class_name, detail.ascendancy = names[0], names[-1]
            else:
                detail.ascendancy = names[0]
        for part in parts[1:]:
            level_match = _LEVEL_RE.search(part)
            if level_match:
                detail.level = int(level_match.group(1))
            elif not detail.main_skill:
                detail.main_skill = part
        if detail.ascendancy.strip().lower() in ("none", "null", "-"):
            detail.ascendancy = ""

    pobb = _POBB_RE.search(body)
    if pobb:
        detail.pobb_url = f"https://pobb.in/{pobb.group(1)}"
    youtube = _YT_RE.search(body)
    if youtube:
        detail.youtube_url = f"{YOUTUBE_SITE}/watch?v={youtube.group(1)}"

    for label, value in _STAT_RE.findall(body):
        key = _clean(label).lower()
        number = _number(_clean(value))
        if key.startswith("dps"):
            detail.stats["dps"] = number
        elif key.startswith("vida") or key.startswith("life"):
            detail.stats["life"] = number
        elif "escudo" in key or "energy shield" in key:
            detail.stats["es"] = number
        elif key.startswith("ehp"):
            detail.stats["ehp"] = number

    if not detail.ascendancy and detail.title:
        detail.ascendancy = ""
    return detail


# ---------------------------------------------------------------------------
# 유튜브 채널/영상 설명 파싱
# ---------------------------------------------------------------------------

_INIT_RE = re.compile(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", re.S)
_DESC_RE = re.compile('"attributedDescription"\\s*:\\s*\\{\\s*"content"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"', re.S)
_SHORT_DESC_RE = re.compile(r'"shortDescription"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)


@dataclass
class ChannelVideo:
    video_id: str
    title: str
    age: str = ""

    @property
    def url(self) -> str:
        return f"{YOUTUBE_SITE}/watch?v={self.video_id}"


def _json_walk(node):
    """ytInitialData 안에서 renderer/viewModel dict 를 문서 순서대로 꺼낸다."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _json_walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _json_walk(item)


def _lockup_title(renderer: dict) -> str:
    try:
        return renderer["metadata"]["lockupMetadataViewModel"]["title"]["content"]
    except (KeyError, TypeError):
        return ""


def _lockup_age(renderer: dict) -> str:
    try:
        rows = renderer["metadata"]["lockupMetadataViewModel"]["metadata"]["contentMetadataViewModel"]["metadataRows"]
        for row in rows:
            for part in row.get("metadataParts") or []:
                text = (part.get("text") or {}).get("content") or ""
                if re.search(r"ago|전", text):
                    return text
    except (KeyError, TypeError):
        pass
    return ""


def parse_channel(text: str) -> list[ChannelVideo]:
    """채널 `/videos` HTML → 최근 영상(신/구 렌더러 모두 지원)."""
    match = _INIT_RE.search(text or "")
    videos: list[ChannelVideo] = []
    if not match:
        return videos
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return videos
    seen: set[str] = set()
    for node in _json_walk(data):
        lockup = node.get("lockupViewModel")
        if isinstance(lockup, dict):
            video_id = str(lockup.get("contentId") or "")
            title = _lockup_title(lockup)
            if video_id and title and video_id not in seen:
                seen.add(video_id)
                videos.append(ChannelVideo(video_id, title, _lockup_age(lockup)))
            continue
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict):
            video_id = str(renderer.get("videoId") or "")
            runs = (renderer.get("title") or {}).get("runs") or [{}]
            title = (runs[0] or {}).get("text") or ""
            age = (renderer.get("publishedTimeText") or {}).get("simpleText") or ""
            if video_id and title and video_id not in seen:
                seen.add(video_id)
                videos.append(ChannelVideo(video_id, title, age))
    return videos


def parse_description(text: str) -> str:
    """영상 페이지 HTML → 설명란 본문(없으면 빈 문자열)."""
    for regex in (_DESC_RE, _SHORT_DESC_RE):
        match = regex.search(text or "")
        if not match:
            continue
        try:
            return json.loads('"' + match.group(1) + '"')
        except json.JSONDecodeError:
            return match.group(1)
    return ""


def pobb_in_text(text: str) -> str:
    """아무 텍스트에서 첫 pobb.in 링크를 정규화해 꺼낸다."""
    match = _POBB_RE.search(text or "")
    return f"https://pobb.in/{match.group(1)}" if match else ""


# ---------------------------------------------------------------------------
# 채널 목록
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Channel:
    name: str
    handles: tuple[str, ...]
    game: str = datafiles.GAME_POE1


DEFAULT_CHANNELS: tuple[Channel, ...] = (
    Channel("Pohx", ("PohxKappa",)),
    Channel("Palsteron", ("Palsteron",)),
    Channel("Bula", ("BulaPoE", "bulapoe")),
    Channel("MAGEFIST", ("MAGEFIST",)),
    Channel("Zizaran", ("Zizaran",)),
    Channel("Jungroan", ("jungroan",)),
    Channel("Sanavixx", ("Sanavixx",)),
    Channel("까까모리", ("까까모리",)),
)


def channel_url(handle: str) -> str:
    return f"{YOUTUBE_SITE}/@{urllib.parse.quote(handle)}/videos"


# ---------------------------------------------------------------------------
# 병합
# ---------------------------------------------------------------------------

def live_id(prefix: str, url: str) -> str:
    """같은 URL 이면 늘 같은 id(중복 제거용)."""
    parsed = urllib.parse.urlparse(url or "")
    video = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    if video:
        slug = re.sub(r"[^0-9A-Za-z_\-]+", "-", video).strip("-")[:38]
    else:
        tail = (url or "").rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"[^0-9a-z가-힣]+", "-", tail.lower()).strip("-")[:38].strip("-")
    return f"{prefix}-{slug or 'build'}-{hashlib.sha1((url or '').encode('utf-8')).hexdigest()[:6]}"


def _korean(game: str, section: str, name: str) -> str:
    """한국어 표기 — 해당 게임 사전에 없으면 다른 게임 사전까지 본다."""
    if not name:
        return ""
    target = datafiles.normalize_game(game)
    for key in (target, *[g for g in datafiles.GAMES if g != target]):
        try:
            label = datafiles.korean_name(key, section, name)
        except Exception:  # noqa: BLE001 - 번역 사전 누락 방어
            continue
        if label and label != name:
            return label
    return ""


def build_label(detail: BuildDetail, profile: pob.BuildProfile | None,
                game: str) -> str:
    """한국어 우선 이름: '격노의 소용돌이 버서커 (EXILED CAT)'.

    PoB 가 레벨링 초반본(60레벨 미만)이면 주력 스킬·전직이 실제 빌드와 다르므로,
    그때는 페이지/영상 제목 쪽 정보를 쓴다.
    """
    level = profile.level if profile is not None else None
    use_profile = bool(profile is not None and profile.main_skill_names and (level or 0) >= 60)
    main = profile.main_skill_names[0] if use_profile and profile is not None else ""
    ascendancy = (profile.ascendancy if use_profile and profile is not None else "") or detail.ascendancy
    main = main or detail.main_skill
    label = " ".join(
        part for part in (_korean(game, "gems", main) or main,
                          _korean(game, "ascendancies", ascendancy) or ascendancy)
        if part
    ).strip()
    if not label:
        label = (detail.title or "라이브 스타터").strip()[:70]
    if detail.author:
        label = f"{label} ({detail.author})"
    return label


def build_note(detail: BuildDetail, profile: pob.BuildProfile | None,
               origin: str) -> str:
    bits: list[str] = [origin]
    if detail.patch:
        bits.append(f"패치 {detail.patch}")
    if detail.published:
        bits.append(detail.published)
    level = detail.level or (profile.level if profile else None)
    if level:
        bits.append(f"{level}레벨")
    life = detail.life or (profile.stats.get("Life", 0.0) if profile else 0.0)
    if life and life < 50:  # 초반 레벨링 PoB 는 Life 가 비어 있다
        life = 0.0
    ehp = detail.ehp or (profile.ehp if profile else 0.0)
    dps = detail.dps or (profile.dps if profile else 0.0)
    if life:
        bits.append(f"생명력 {life:,.0f}")
    if ehp:
        bits.append(f"EHP {ehp:,.0f}")
    if dps:
        bits.append(f"DPS {dps:,.0f}")
    uniques = []
    if profile is not None:
        for name in profile.uniques[:3]:
            uniques.append(_korean(profile.game, "uniques", name) or name)
    if uniques:
        bits.append("유니크 " + ", ".join(uniques))
    note = " · ".join(bits)
    if detail.title:
        note += f" / 원제: {detail.title[:110]}"
    return note[:400]


@dataclass
class LiveSyncReport:
    games: tuple[str, ...] = ()
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    candidates: int = 0
    scanned: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {"exilebuilds": 0, "youtube": 0})
    errors: list[str] = field(default_factory=list)
    duration: float = 0.0
    dry_run: bool = False
    saved: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.updated)

    def summary(self) -> str:
        bits = [
            f"EXILEFILTER {self.counts.get('exilebuilds', 0)}",
            f"유튜브 {self.counts.get('youtube', 0)}",
        ]
        head = "실시간 수집" + ("(미리보기)" if self.dry_run else "")
        text = f"{head}: {' + '.join(bits)} = {self.total}건 반영"
        if self.unchanged:
            text += f" · 이미 있음 {len(self.unchanged)}"
        if self.skipped:
            text += f" · 건너뜀 {len(self.skipped)}"
        if self.errors:
            text += f" · 오류 {len(self.errors)}"
        return text

    def lines(self) -> list[str]:
        out = [self.summary()]
        if self.candidates:
            out.append(f"후보 {self.candidates}건 · 상세 확인 {self.scanned}건")
        for build_id in self.added:
            out.append(f"  + {build_id}")
        for build_id in self.updated:
            out.append(f"  ↻ {build_id}")
        for note in self.skipped:
            out.append(f"  - {note}")
        for message in self.errors:
            out.append(f"  ! {message}")
        return out

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "candidates": self.candidates,
            "scanned": self.scanned,
            "counts": dict(self.counts),
            "errors": self.errors,
            "duration": round(self.duration, 1),
            "dry_run": self.dry_run,
            "saved": self.saved,
            "changed": self.changed,
            "total": self.total,
            "summary": self.summary(),
            "lines": self.lines(),
        }


class _Merger:
    """라이브 수집 결과를 라이브러리에 안전하게 합친다."""

    def __init__(self, lib: library_mod.BuildLibrary, report: LiveSyncReport, *,
                 dry_run: bool = False):
        self.lib = lib
        self.report = report
        self.dry_run = dry_run
        self.sources = {
            (build.source or "").rstrip("/").lower()
            for build in lib.builds if build.source
        }
        self.signatures = {
            self.signature(build.name) for build in lib.builds if build.name
        }

    def has(self, build_id: str) -> bool:
        return self.lib.get(build_id) is not None

    @staticmethod
    def signature(name: str) -> tuple[str, str]:
        """'신성한 유물 네크로맨서 (Bula)' → (빌드 이름, 작성자) — 같은 빌드 판별용."""
        match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", name or "")
        if not match:
            return ((name or "").strip().lower(), "")
        return (match.group(1).strip().lower(), match.group(2).strip().lower())

    def similar_exists(self, name: str) -> bool:
        key = self.signature(name)
        return bool(key[1]) and key in self.signatures

    def duplicate_source(self, pobb_url: str) -> bool:
        return (pobb_url or "").rstrip("/").lower() in self.sources

    def add(self, *, build_id: str, name: str, game: str, kind: str,
            origin: str, source: str, note: str, code: str) -> bool:
        if not code:
            return False
        self.signatures.add(self.signature(name))
        if self.dry_run:
            self.report.added.append(build_id)
            self.sources.add((source or "").rstrip("/").lower())
            return True
        existing = self.lib.get(build_id)
        if existing is not None:
            if existing.code == code:
                self.report.unchanged.append(build_id)
                return False
            existing.name = name or existing.name
            existing.game = game
            existing.origin = origin or existing.origin
            existing.source = source or existing.source
            existing.note = note or existing.note
            existing.code = code
            existing.code_file = ""
            self.lib._profiles.pop(build_id, None)
            self.report.updated.append(build_id)
        else:
            self.lib.builds.append(
                library_mod.BuildEntry(
                    id=build_id,
                    name=name,
                    kind=kind if kind in library_mod.KINDS else "starter",
                    game=game,
                    origin=origin,
                    source=source,
                    note=note,
                    code=code,
                )
            )
            self.lib._profiles.pop(build_id, None)
            self.report.added.append(build_id)
        self.sources.add((source or "").rstrip("/").lower())
        return True


def _kind_for(game: str) -> str:
    return "poe2" if datafiles.normalize_game(game) == datafiles.GAME_POE2 else "starter"


def _profile_from_code(code: str, name: str = ""):
    """PoB 코드 → BuildProfile. 게임은 XML 루트(PathOfBuilding2)로 판별한다."""
    xml = pob.decode_pob_code(code)
    return pob.parse_pob_xml(xml, name=name)


# ---------------------------------------------------------------------------
# 수집기
# ---------------------------------------------------------------------------

def _rank_key(item: ListingItem) -> tuple[int, int]:
    """사용자가 언급한 크리에이터를 먼저, 그다음 목록 순서(최신)를 지킨다."""
    author = (item.author or "").lower()
    focus = 0 if any(key in author for key in FOCUS_AUTHORS) else 1
    return (focus, 0)


def collect_exilebuilds(
    report: LiveSyncReport,
    merger: _Merger,
    *,
    games: tuple[str, ...],
    max_per_game: int,
    max_total: int,
    fetcher,
    pobb_fetcher,
    workers: int,
    deadline: float | None,
) -> None:
    """EXILEFILTER 목록 → 상세 → pobb.in → 라이브러리."""
    try:
        listing_html = fetcher(EXILEBUILDS_URL)
    except Exception as exc:  # noqa: BLE001 - 사이트 변경/차단 모두 흡수
        report.errors.append(f"EXILEFILTER 목록: {exc}")
        return

    items = parse_listing(listing_html)
    pool: list[ListingItem] = []
    for game in games:
        rows = [
            item for item in items
            if item.game == game and is_starter(item.title) and is_current_patch(item.patch, game)
        ]
        rows.sort(key=_rank_key)
        pool.extend(rows[: max(4, max_per_game * 2)])
    report.candidates += len(pool)

    pending: list[ListingItem] = []
    for item in pool:
        if merger.has(live_id("eb", item.url)):
            report.unchanged.append(live_id("eb", item.url))
            continue
        pending.append(item)
    if not pending:
        return

    def fetch_detail(item: ListingItem) -> tuple[ListingItem, BuildDetail | None, str]:
        try:
            return item, parse_detail(fetcher(item.url), url=item.url), ""
        except Exception as exc:  # noqa: BLE001
            return item, None, f"{item.url}: {exc}"

    details: list[tuple[ListingItem, BuildDetail | None, str]] = []
    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool_exec:
        for result in pool_exec.map(fetch_detail, pending):
            details.append(result)
    report.scanned += len(details)

    per_game: dict[str, int] = {}
    chosen: list[tuple[ListingItem, BuildDetail]] = []
    for item, detail, error in details:
        if error:
            report.errors.append(f"상세 {error}")
            continue
        if detail is None:
            continue
        game = datafiles.normalize_game(detail.game or item.game)
        if game not in games:
            continue
        if not detail.pobb_url:
            report.skipped.append(f"PoB 링크 없음: {detail.title or item.title}")
            continue
        if merger.duplicate_source(detail.pobb_url):
            report.unchanged.append(live_id("eb", item.url))
            continue
        if per_game.get(game, 0) >= max_per_game:
            continue
        if len(chosen) >= max_total:
            break
        per_game[game] = per_game.get(game, 0) + 1
        chosen.append((item, detail))

    if not chosen:
        return

    def fetch_code(pair: tuple[ListingItem, BuildDetail]):
        item, detail = pair
        try:
            code = pobb_fetcher(detail.pobb_url)
            return item, detail, code, None
        except Exception as exc:  # noqa: BLE001
            return item, detail, "", str(exc)

    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool_exec:
        fetched = list(pool_exec.map(fetch_code, chosen))

    for item, detail, code, error in fetched:
        if error or not code:
            report.errors.append(f"PoB {detail.pobb_url}: {error or '빈 본문'}")
            continue
        try:
            profile = _profile_from_code(code, detail.title)
        except Exception as exc:  # noqa: BLE001 - PoB 해석 실패는 건너뛴다
            report.errors.append(f"PoB 해석 {detail.pobb_url}: {exc}")
            continue
        game = datafiles.normalize_game(profile.game or detail.game)
        if game not in games:
            continue
        origin = f"EXILEFILTER · {detail.author or item.author or '커뮤니티'}"
        if detail.patch:
            origin += f" · {detail.patch}"
        build_id = live_id("eb", item.url)
        label = build_label(detail, profile, game)
        if merger.similar_exists(label):
            report.unchanged.append(build_id)
            continue
        added = merger.add(
            build_id=build_id,
            name=label,
            game=game,
            kind=_kind_for(game),
            origin=origin,
            source=detail.pobb_url,
            note=build_note(detail, profile, "EXILEFILTER 라이브 수집"),
            code=code,
        )
        if added and build_id in report.added:
            report.counts["exilebuilds"] = report.counts.get("exilebuilds", 0) + 1
        elif build_id in report.updated:
            report.counts["exilebuilds"] = report.counts.get("exilebuilds", 0) + 1


def collect_youtube(
    report: LiveSyncReport,
    merger: _Merger,
    *,
    games: tuple[str, ...],
    max_per_channel: int,
    max_total: int,
    fetcher,
    pobb_fetcher,
    workers: int,
    channels: tuple[Channel, ...] = DEFAULT_CHANNELS,
) -> None:
    """유튜브 채널 → 스타터 영상 → 설명란 pobb.in → 라이브러리."""
    if max_total <= 0:
        return
    wanted = [channel for channel in channels if channel.game in games]
    if not wanted:
        return

    def fetch_channel(channel: Channel):
        last_error = ""
        for handle in channel.handles:
            try:
                return channel, fetcher(channel_url(handle)), ""
            except Exception as exc:  # noqa: BLE001 - 다음 후보 핸들로
                last_error = str(exc)
        return channel, "", last_error or "채널을 찾지 못했습니다"

    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool_exec:
        results = list(pool_exec.map(fetch_channel, wanted))

    picked: list[tuple[Channel, ChannelVideo]] = []
    for channel, page, error in results:
        if error:
            report.errors.append(f"유튜브 {channel.name}: {error}")
            continue
        videos = [
            video for video in parse_channel(page)
            if is_starter(video.title) and title_patch_ok(video.title, channel.game)
        ]
        report.candidates += len(videos)
        taken = 0
        for video in videos:
            if taken >= max_per_channel:
                break
            if merger.has(live_id("yt", video.url)):
                report.unchanged.append(live_id("yt", video.url))
                continue
            picked.append((channel, video))
            taken += 1

    if not picked:
        return

    def fetch_watch(pair: tuple[Channel, ChannelVideo]):
        channel, video = pair
        try:
            description = parse_description(fetcher(video.url))
            return channel, video, description, ""
        except Exception as exc:  # noqa: BLE001
            return channel, video, "", str(exc)

    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool_exec:
        watches = list(pool_exec.map(fetch_watch, picked))
    report.scanned += len(watches)

    chosen: list[tuple[Channel, ChannelVideo, str]] = []
    for channel, video, description, error in watches:
        if error:
            report.errors.append(f"유튜브 {channel.name} 설명: {error}")
            continue
        pobb_url = pobb_in_text(description)
        if not pobb_url:
            continue
        if merger.duplicate_source(pobb_url):
            report.unchanged.append(live_id("yt", video.url))
            continue
        if len(chosen) >= max_total:
            break
        chosen.append((channel, video, pobb_url))
    if not chosen:
        return

    def fetch_code(pair: tuple[Channel, ChannelVideo, str]):
        channel, video, pobb_url = pair
        try:
            return channel, video, pobb_url, pobb_fetcher(pobb_url), ""
        except Exception as exc:  # noqa: BLE001
            return channel, video, pobb_url, "", str(exc)

    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool_exec:
        fetched = list(pool_exec.map(fetch_code, chosen))

    for channel, video, pobb_url, code, error in fetched:
        if error or not code:
            report.errors.append(f"유튜브 PoB {pobb_url}: {error or '빈 본문'}")
            continue
        try:
            profile = _profile_from_code(code, video.title)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"유튜브 PoB 해석 {pobb_url}: {exc}")
            continue
        game = datafiles.normalize_game(profile.game or channel.game)
        if game not in games:
            continue
        detail = BuildDetail(
            url=video.url,
            title=video.title,
            game=game,
            author=channel.name,
            main_skill="",
            level=profile.level,
            patch=(CURRENT_PATCH.get(game, ("",))[0]),
            pobb_url=pobb_url,
        )
        build_id = live_id("yt", video.url)
        label = build_label(detail, profile, game)
        if merger.similar_exists(label):
            report.unchanged.append(build_id)
            continue
        added = merger.add(
            build_id=build_id,
            name=label,
            game=game,
            kind=_kind_for(game),
            origin=f"유튜브 · {channel.name}",
            source=pobb_url,
            note=build_note(detail, profile, "유튜브 라이브 수집"),
            code=code,
        )
        if added or build_id in report.updated:
            report.counts["youtube"] = report.counts.get("youtube", 0) + 1


def sync_live(
    lib: library_mod.BuildLibrary,
    *,
    games=None,
    max_per_game: int = 6,
    max_total: int = 12,
    max_per_channel: int = 2,
    dry_run: bool = False,
    fetcher=None,
    pobb_fetcher=None,
    channels: tuple[Channel, ...] | None = None,
    include_youtube: bool = True,
    workers: int = 6,
    deadline_seconds: float = DEFAULT_DEADLINE,
) -> LiveSyncReport:
    """실시간 커뮤니티/유튜브 빌드 수집 → 라이브러리 병합.

    어떤 실패도 예외로 올리지 않는다(수집 단계별 errors).
    """
    started = time.monotonic()
    target_games = tuple(
        datafiles.normalize_game(game) for game in (games or datafiles.GAMES)
    )
    report = LiveSyncReport(games=target_games, dry_run=dry_run)
    merger = _Merger(lib, report, dry_run=dry_run)
    fetcher = fetcher or http_get
    pobb_fetcher = pobb_fetcher or pob.fetch_pobb

    # 유튜브 몫을 남겨 둔다(EXILEFILTER 가 전부 가져가지 않게).
    exile_budget = max_total if not include_youtube else max(1, round(max_total * 0.65))
    try:
        collect_exilebuilds(
            report, merger,
            games=target_games,
            max_per_game=max_per_game,
            max_total=exile_budget,
            fetcher=fetcher,
            pobb_fetcher=pobb_fetcher,
            workers=workers,
            deadline=deadline_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - 수집기 자체 버그도 최신화를 깨지 않게
        report.errors.append(f"EXILEFILTER 수집: {exc}")

    remaining = max_total - report.total
    used = time.monotonic() - started
    if include_youtube and remaining > 0 and used < deadline_seconds:
        try:
            collect_youtube(
                report, merger,
                games=target_games,
                max_per_channel=max_per_channel,
                max_total=remaining,
                fetcher=fetcher,
                pobb_fetcher=pobb_fetcher,
                workers=workers,
                channels=channels or DEFAULT_CHANNELS,
            )
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"유튜브 수집: {exc}")

    report.duration = time.monotonic() - started
    if report.changed and not dry_run:
        try:
            lib.save()
            report.saved = True
        except OSError as exc:
            report.errors.append(f"라이브러리 저장: {exc}")
    return report
