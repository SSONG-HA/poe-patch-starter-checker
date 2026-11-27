"""패치노트 텍스트 가져오기·HTML 정리·항목(entry) 분해."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import datafiles, deltas, naming

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_BULLET_RE = re.compile(r"^\s*[-•*–]\s*")
_NEW_OLD_RE = re.compile(r"^\s*(new|old)\s*:\s*(.*)$", re.I)
_HEADER_NOTES = {
    "modified": "Modified",
    "added": "Added",
    "removed": "Removed",
    "reworked": "Reworked",
    "new": "New",
    "unchanged": "Unchanged",
}
_SECTION_HINTS = (
    "general",
    "new content and features",
    "content and features",
    "endgame changes",
    "skills",
    "skill gems",
    "support gems",
    "active skill gems",
    "items",
    "unique items",
    "flasks",
    "passive tree",
    "ascendancy changes",
    "ascendancies",
    "ascendancy",
    "monsters",
    "map devices",
    "atlas",
    "league",
    "challenge league",
    "bug fixes",
    "changes",
    "new gems",
    "updated gems",
)


class PatchNotesError(RuntimeError):
    """패치노트를 가져오지 못했을 때."""


# ---------------------------------------------------------------------------
# HTML → 텍스트
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {
    "p", "div", "ul", "ol", "li", "br", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "section", "article", "hr", "pre",
}


class _ForumTextExtractor(HTMLParser):
    """GGG 포럼 뉴스 글의 본문(box-content)을 줄 단위 텍스트로 바꾼다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._capture_depth = 0
        self._skip_depth = 0
        self._found_post = False

    # -- helpers
    def _is_post_div(self, attrs) -> bool:
        classes = (dict(attrs).get("class") or "").lower().split()
        if "content-container" in classes:
            return False
        # 2025년 이전 포럼: div.box-content.m-pad / 현재 포럼: td.content-container > div.content
        return ("box-content" in classes and "m-pad" in classes) or "content" in classes

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if self._capture_depth:
            if tag == "div":
                self._capture_depth += 1
            if tag == "li":
                self.chunks.append("\n- ")
            elif tag in _BLOCK_TAGS:
                self.chunks.append("\n")
            if tag in ("td", "th"):
                self.chunks.append(" | ")
            return
        if self._is_post_div(attrs):
            self._found_post = True
            self._capture_depth = 1
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._capture_depth:
            if tag == "div":
                self._capture_depth -= 1
            if tag in _BLOCK_TAGS:
                self.chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth or not self._capture_depth:
            return
        self.chunks.append(data)

    def text(self) -> str:
        return "".join(self.chunks)


def _strip_tags(html: str) -> str:
    class _All(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out: list[str] = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "nav", "header", "footer"):
                self.skip += 1
            elif tag in _BLOCK_TAGS:
                self.out.append("\n")
            elif tag in ("td", "th"):
                self.out.append(" | ")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "nav", "header", "footer"):
                self.skip = max(0, self.skip - 1)
            elif tag in _BLOCK_TAGS:
                self.out.append("\n")

        def handle_data(self, data):
            if not self.skip:
                self.out.append(data)

    parser = _All()
    parser.feed(html)
    return "".join(parser.out)


_POST_TD_RE = re.compile(r'<td[^>]*class="[^"]*content-container[^"]*"[^>]*>(.*?)</td>', re.S)
_POST_BOX_RE = re.compile(r'<div[^>]*class="[^"]*box-content[^"]*"[^>]*>(.*)', re.S)


def _post_fragment(html: str) -> str | None:
    """본문 부분만 잘라낸다. 포럼에는 content-container td 가 여러 개(서명 등) 있으므로 가장 긴 것을 쓴다."""
    candidates = _POST_TD_RE.findall(html)
    if candidates:
        return max(candidates, key=lambda chunk: len(_strip_tags(chunk).strip()))
    match = _POST_BOX_RE.search(html)
    if match:
        return match.group(0)
    return None


class _AllTextExtractor(HTMLParser):
    """본문 조각 전체를 텍스트로. 불릿(li)은 '- ' 로 살려 패치노트 항목 분해가 되게 한다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


class _BoxContentExtractor(HTMLParser):
    """뉴스형 글의 box-content 블록 여러 개를 이어 붙인다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.depth = 0
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
            return
        classes = (dict(attrs).get("class") or "").lower().split()
        if "box-content" in classes and self.depth == 0:
            self.depth = 1
            self.out.append("\n")
            return
        if self.depth:
            if tag == "div":
                self.depth += 1
            if tag == "li":
                self.out.append("\n- ")
            elif tag in _BLOCK_TAGS:
                self.out.append("\n")
            elif tag in ("td", "th"):
                self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if self.depth:
            if tag == "div":
                self.depth -= 1
            elif tag in _BLOCK_TAGS:
                self.out.append("\n")

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    if "box-content" in html:
        parser = _BoxContentExtractor()
        try:
            parser.feed(html)
            text = "".join(parser.out)
        except Exception:  # pragma: no cover - 방어적
            text = ""
        if len(text.strip()) >= 40:
            return normalize_text(text)
    fragment = _post_fragment(html)
    if fragment is not None:
        parser = _AllTextExtractor()
        try:
            parser.feed(fragment)
            text = "".join(parser.out)
        except Exception:  # pragma: no cover - 방어적
            text = _strip_tags(fragment)
        if len(text.strip()) >= 20:
            return normalize_text(text)
    text = _strip_tags(html)
    return normalize_text(text)


_UI_NOISE_RE = re.compile(r"(?:Show|Hide)\s+(?:All\s+)?Differences", re.I)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _UI_NOISE_RE.sub(" ", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(line)
    return "\n".join(out).strip()


def fetch_patch_text(url: str, timeout: float = 30.0) -> tuple[str, str]:
    """URL 에서 패치노트를 가져온다. (텍스트, 제목) 반환."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            charset = "utf-8"
            match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
            if match:
                charset = match.group(1)
            body = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code in (403, 503):
            hint = (
                " (Cloudflare 차단일 수 있습니다. 브라우저로 열어 본문을 복사해 "
                "'텍스트 붙여넣기'로 붙여 주세요.)"
            )
        raise PatchNotesError(f"HTTP {exc.code} — 패치노트를 가져오지 못했습니다.{hint}") from exc
    except urllib.error.URLError as exc:
        raise PatchNotesError(f"주소에 연결하지 못했습니다: {exc.reason}") from exc

    title = ""
    match = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    if match:
        title = re.sub(r"\s+-\s+Forum.*$", "", re.sub(r"\s+", " ", match.group(1))).strip()

    if "html" in content_type.lower() or body.lstrip().startswith("<"):
        text = html_to_text(body)
    else:
        text = normalize_text(body)
    if len(text) < 40:
        raise PatchNotesError("패치노트 본문을 찾지 못했습니다. 텍스트를 직접 붙여넣어 주세요.")
    return text, title


def load_patch_file(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fp:
        return normalize_text(fp.read())


# ---------------------------------------------------------------------------
# 항목 분해
# ---------------------------------------------------------------------------

@dataclass
class PatchEntry:
    name: str
    section: str = ""
    kind: str = "generic"
    header_note: str = ""
    lines: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    unpaired_new: list[str] = field(default_factory=list)
    unpaired_old: list[str] = field(default_factory=list)
    added_block: bool = False
    removed_block: bool = False
    signal: deltas.EntrySignal = field(default_factory=deltas.EntrySignal)

    @property
    def direction(self) -> str:
        return self.signal.direction

    @property
    def score(self) -> float:
        return self.signal.score

    def display_lines(self, limit: int = 8) -> list[str]:
        noise = {"modified", "added", "removed", "reworked", "unchanged"}
        lines = [line for line in self.lines if line.strip().lower() not in noise]
        return (lines or self.lines)[:limit]

    def __post_init__(self) -> None:
        self.kind = self.kind or "generic"


@dataclass
class PatchNotes:
    text: str
    entries: list[PatchEntry] = field(default_factory=list)
    title: str = ""
    source: str = ""
    game: str = ""

    @property
    def gem_entries(self) -> list[PatchEntry]:
        return [e for e in self.entries if e.kind in ("gem", "support")]

    def by_name(self) -> dict[str, PatchEntry]:
        return {naming.norm(e.name): e for e in self.entries}


_CHANGE_WORDS = (
    "now",
    "no longer",
    "has ",
    "have ",
    "deals",
    "grants",
    "gains",
    "fires",
    "increased",
    "reduced",
    "added",
    "removed",
    "can ",
)


def _looks_like_change(rest: str) -> bool:
    low = rest.lower().strip()
    if not low:
        return False
    if any(word in low for word in _CHANGE_WORDS):
        return True
    return any(char.isdigit() for char in low)


_CLAUSE_SPLIT_RE = re.compile(
    r"\s(?:now|no longer|has been|have been|will now|can now|is now|are now|"
    r"has |have |grants |deals |added |removed |reduced |increased )",
    re.I,
)


_CLAUSE_STOPWORDS = {
    "now", "no", "not", "this", "it", "they", "there", "when", "while", "if", "we",
    "you", "the", "a", "an", "and", "or", "but", "also", "additionally", "monsters",
}


def _leading_clause(text: str) -> str:
    """알려진 이름이 없는 불릿에서 대상 이름으로 쓸 앞부분을 뽑는다."""
    body = _BULLET_RE.sub("", text).strip()
    if not body or body.startswith(("For ", "Fixed ", "We ", "This ", "If ")):
        return ""
    match = _CLAUSE_SPLIT_RE.search(body)
    if not match or match.start() < 6:
        return ""
    clause = body[: match.start()].strip(" ,.:;")
    if not (4 <= len(clause) <= 70):
        return ""
    words = clause.split()
    if len(words) > 9:
        return ""
    if clause.lower() in _CLAUSE_STOPWORDS:
        return ""
    if not (clause[0].isupper() or clause[0].isdigit()):
        return ""
    if words[-1].lower() in {"and", "or", "will", "would", "can", "have", "has", "is", "are", "be"}:
        return ""
    return clause


def _is_section_header(line: str) -> bool:
    low = line.lower().strip(" :")
    if low in _SECTION_HINTS:
        return True
    if len(line) <= 40 and line.isupper() and len(line.split()) <= 4:
        return True
    for hint in _SECTION_HINTS:
        if low.endswith(" " + hint) and len(line.split()) <= 4:
            return True
    return False


def _kind_for(name: str, section: str) -> str:
    key = naming.norm(name)
    if key in datafiles.all_unique_names_keys():
        return "unique"
    if key in datafiles.support_gem_keys():
        return "support"
    if key in datafiles.active_gem_keys():
        return "gem"
    if key in datafiles.ascendancy_keys():
        return "ascendancy"
    if key in datafiles.keystone_keys():
        return "keystone"
    if "unique" in section.lower():
        return "unique"
    if "passive" in section.lower() or "keystone" in section.lower():
        return "passive"
    if "ascend" in section.lower():
        return "ascendancy"
    if key.endswith(" support"):
        return "support"
    return "generic"


def _flush_signal(entry: PatchEntry) -> None:
    entry.signal = deltas.summarize(
        entry.pairs,
        entry.lines,
        is_new=entry.header_note.lower() in ("new", "added") and not entry.removed_block,
        removed_block=entry.removed_block,
        added_block=entry.added_block,
        unpaired_new=entry.unpaired_new,
        unpaired_old=entry.unpaired_old,
    )


def parse_patch_notes(text: str, *, title: str = "", source: str = "",
                      game: str = "") -> PatchNotes:
    lines = [line for line in normalize_text(text).split("\n")]
    notes = PatchNotes(text=text, title=title, source=source, game=game)
    section = ""
    entry: PatchEntry | None = None
    pending_new: str | None = None
    block: str | None = None  # 'added' / 'removed'

    def start(name: str, note: str = "") -> PatchEntry:
        nonlocal entry, pending_new, block
        entry = PatchEntry(name=name, section=section, header_note=note)
        entry.kind = _kind_for(name, section)
        notes.entries.append(entry)
        pending_new = None
        block = None
        return entry

    def next_content(index: int) -> str:
        for j in range(index + 1, len(lines)):
            s = lines[j].strip()
            if s:
                return s
        return ""

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        if _is_section_header(line):
            if entry is not None:
                _flush_signal(entry)
            entry = None
            section = line.strip(" :")
            block = None
            continue

        note = _HEADER_NOTES.get(line.lower())
        if note in ("Modified", "Added", "Removed", "Reworked", "New", "Unchanged"):
            if entry is not None and line.lower() in ("added", "removed"):
                block = line.lower()
                entry.lines.append(line)
                entry.header_note = entry.header_note or note
                if block == "added":
                    entry.added_block = True
                else:
                    entry.removed_block = True
                continue
            if entry is not None:
                entry.lines.append(line)
                continue
            continue

        new_old = _NEW_OLD_RE.match(line)
        if new_old and entry is not None:
            prefix, body = new_old.group(1).lower(), new_old.group(2).strip()
            entry.lines.append(line)
            if prefix == "new":
                pending_new = body
            else:
                if pending_new is not None:
                    entry.pairs.append((pending_new, body))
                    pending_new = None
                else:
                    entry.unpaired_old.append(body)
            continue

        if block and not _BULLET_RE.match(line) and not _NEW_OLD_RE.match(line):
            entry.lines.append(line)
            if block == "added":
                entry.unpaired_new.append(line)
            else:
                entry.unpaired_old.append(line)
            block = None
            continue

        if _BULLET_RE.match(line):
            body = _BULLET_RE.sub("", line).strip()
            bullet_new_old = _NEW_OLD_RE.match(body)
            if bullet_new_old and entry is not None:
                prefix, value = bullet_new_old.group(1).lower(), bullet_new_old.group(2).strip()
                entry.lines.append(body)
                if prefix == "new":
                    pending_new = value
                elif pending_new is not None:
                    entry.pairs.append((pending_new, value))
                    pending_new = None
                else:
                    entry.unpaired_old.append(value)
                continue
            found = naming.find_leading_entity(body)
            if entry is None:
                if found:
                    name, rest, _kind = found
                    entry = start(name)
                    if rest:
                        entry.lines.append(rest)
                else:
                    clause = _leading_clause(body)
                    if clause:
                        entry = start(clause)
                        entry.lines.append(body)
                continue
            # 다른 대상의 변경 문장이 한 불릿으로 들어오면 항목을 나눈다
            if (
                found
                and naming.norm(found[0]) != naming.norm(entry.name)
                and _looks_like_change(found[1])
            ):
                _flush_signal(entry)
                entry = start(found[0])
                entry.lines.append(found[1])
                continue
            if not found and entry.lines:
                clause = _leading_clause(body)
                if clause and naming.norm(clause) != naming.norm(entry.name):
                    _flush_signal(entry)
                    entry = start(clause)
                    entry.lines.append(body)
                    continue
            entry.lines.append(body)
            continue

        # 이름만 있는 헤더 (다음 줄이 불릿 또는 New:/Old: 또는 Modified 등)
        following = next_content(i)
        is_header = False
        if len(line) <= 90 and not line.endswith("."):
            if following and (
                _BULLET_RE.match(following)
                or _NEW_OLD_RE.match(following)
                or following.lower() in _HEADER_NOTES
            ):
                is_header = True
            leading = naming.find_leading_entity(line)
            if leading and not leading[1]:
                is_header = True
        if is_header:
            if entry is not None:
                _flush_signal(entry)
            start(line.strip(" :"))
            continue

        # "Righteous Fire: Now deals ..." 한 줄 형식
        if ":" in line and len(line.split(":")[0]) <= 60:
            head, rest = line.split(":", 1)
            found = naming.find_leading_entity(head.strip())
            if found and not found[1]:
                entry = start(head.strip())
                entry.lines.append(rest.strip())
                continue

        if entry is not None:
            entry.lines.append(line)
        # 첫 항목 이전의 머리말은 무시

    _merge_duplicate_entries(notes)
    for e in notes.entries:
        _flush_signal(e)
    return notes


def _merge_duplicate_entries(notes: PatchNotes) -> None:
    """같은 이름이 여러 번(예: 목록 + 상세) 나오면 한 항목으로 합친다."""
    merged: dict[str, PatchEntry] = {}
    unique: list[PatchEntry] = []
    for entry in notes.entries:
        key = naming.norm(entry.name)
        if key in merged:
            first = merged[key]
            first.lines.extend(entry.lines)
            first.pairs.extend(entry.pairs)
            first.unpaired_new.extend(entry.unpaired_new)
            first.unpaired_old.extend(entry.unpaired_old)
            first.added_block = first.added_block or entry.added_block
            first.removed_block = first.removed_block or entry.removed_block
            if not first.header_note:
                first.header_note = entry.header_note
            continue
        merged[key] = entry
        unique.append(entry)
    notes.entries = unique


def patch_notes_from_source(*, url: str | None = None, text: str | None = None,
                            path: str | None = None, game: str = "") -> PatchNotes:
    if text:
        return parse_patch_notes(text, source="붙여넣은 텍스트", game=game)
    if path:
        body = load_patch_file(path)
        return parse_patch_notes(body, title=path.rsplit("/", 1)[-1], source=path, game=game)
    if url:
        body, title = fetch_patch_text(url)
        return parse_patch_notes(body, title=title, source=url, game=game)
    raise PatchNotesError("패치노트 URL·파일·텍스트 중 하나가 필요합니다.")
