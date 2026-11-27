"""PoB(Path of Building) 코드·XML 해석.

pobb.in 코드는 `base64url(zlib(xml))` 이다. 이 모듈은
  - 코드/URL/XML 파일 → XML
  - XML → BuildProfile(주력 스킬, 서포트 젬, 전직, 키스톤, 유니크)
까지 담당한다.
"""
from __future__ import annotations

import base64
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import datafiles, naming
from .patchnotes import USER_AGENT

MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024

# 보조 스킬(오라·저주·이동기 등) 판별 태그
_UTILITY_TAGS = {
    "aura", "herald", "curse", "hex", "golem", "movement", "travel", "blink",
    "warcry", "trigger", "banner", "guard", "link", "stance", "offering",
}


class PobError(RuntimeError):
    """PoB 코드/XML 을 해석하지 못했을 때."""


@dataclass
class Gem:
    name: str
    enabled: bool = True
    support: bool = False
    level: int | None = None
    quality: int | None = None
    tags: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        bits = [self.name]
        if self.level:
            bits.append(f"{self.level}")
        if self.quality:
            bits[-1] = f"{self.level}/{self.quality}" if self.level else f"q{self.quality}"
        return " ".join(bits)


@dataclass
class BuildProfile:
    name: str = ""
    game: str = datafiles.GAME_POE1
    class_name: str = ""
    ascendancy: str = ""
    level: int | None = None
    tree_version: str = ""
    main_skills: list[Gem] = field(default_factory=list)
    secondary_skills: list[Gem] = field(default_factory=list)
    supports: list[Gem] = field(default_factory=list)
    uniques: list[str] = field(default_factory=list)
    keystones: list[str] = field(default_factory=list)
    source: str = ""
    notes: str = ""
    stats: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def dps(self) -> float:
        """PoB 가 계산해 둔 최대 피해량(직접타격·지속·총합 중 큰 값)."""
        keys = ("CombinedDPS", "FullDPS", "TotalDotDPS", "WithDotDPS", "TotalDPS")
        return max((self.stats.get(key, 0.0) for key in keys), default=0.0)

    @property
    def dot_dps(self) -> float:
        return max(self.stats.get("TotalDotDPS", 0.0), self.stats.get("WithDotDPS", 0.0))

    @property
    def ehp(self) -> float:
        """유효 생명력(TotalEHP). 없으면 생명력+에너지 보호막."""
        total = self.stats.get("TotalEHP", 0.0)
        if total:
            return total
        return self.stats.get("Life", 0.0) + self.stats.get("EnergyShield", 0.0)

    @property
    def main_skill_names(self) -> list[str]:
        return [g.name for g in self.main_skills]

    @property
    def support_names(self) -> list[str]:
        return [g.name for g in self.supports]

    def summary(self) -> str:
        cls = " ".join(x for x in (self.ascendancy or self.class_name, ) if x)
        lvl = f"{self.level}레벨" if self.level else ""
        return " · ".join(x for x in (cls, lvl) if x)


# ---------------------------------------------------------------------------
# 디코딩
# ---------------------------------------------------------------------------

def looks_like_xml(text: str) -> bool:
    head = text.lstrip()[:200]
    return head.startswith("<?xml") or head.startswith("<PathOfBuilding")


def decode_pob_code(code: str) -> str:
    """base64url + zlib PoB 코드를 XML 문자열로."""
    token = re.sub(r"\s+", "", code).strip()
    if not token:
        raise PobError("빈 PoB 코드입니다.")
    raw = token.replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise PobError(f"PoB 코드(base64)를 풀지 못했습니다: {exc}") from exc
    try:
        xml_bytes = zlib.decompress(data)
    except zlib.error as exc:
        raise PobError(f"PoB 코드(zlib)를 풀지 못했습니다: {exc}") from exc
    xml = xml_bytes.decode("utf-8", errors="replace")
    if "<PathOfBuilding" not in xml:
        raise PobError("PoB XML 이 아닙니다.")
    return xml


def extract_code_from_html(html: str) -> str | None:
    """pobb.in 같은 페이지 본문에 박혀 있는 PoB 코드를 찾는다."""
    for match in re.finditer(r"[A-Za-z0-9_\-]{200,}", html):
        token = match.group(0)
        raw = token.replace("-", "+").replace("_", "/")
        raw += "=" * (-len(raw) % 4)
        try:
            text = zlib.decompress(base64.b64decode(raw, validate=False)).decode(
                "utf-8", errors="replace"
            )
        except Exception:  # noqa: BLE001
            continue
        if "<PathOfBuilding" in text:
            return token
    return None


def fetch_pobb(url: str, timeout: float = 30.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_DOWNLOAD_BYTES)
    except urllib.error.HTTPError as exc:
        raise PobError(f"pobb.in 응답 {exc.code} — 링크를 확인해 주세요.") from exc
    except urllib.error.URLError as exc:
        raise PobError(f"pobb.in 에 연결하지 못했습니다: {exc.reason}") from exc
    body = raw.decode("utf-8", errors="replace")
    code = extract_code_from_html(body)
    if not code:
        raise PobError("페이지에서 PoB 코드를 찾지 못했습니다.")
    return code


def resolve_source(source: str) -> str:
    """코드 / pobb.in URL / XML 파일 경로 / 코드 파일 → XML 문자열."""
    text = source.strip()
    if not text:
        raise PobError("PoB 코드가 비어 있습니다.")
    if looks_like_xml(text):
        return text
    path = Path(text)
    if "\n" not in text and len(text) < 500:
        # 짧은 PoB 코드도 파일 경로로 오인해 OSError(파일명 초과)가 나지 않게 한다.
        try:
            is_file = path.exists()
        except OSError:
            is_file = False
        if is_file:
            body = path.read_text(encoding="utf-8", errors="replace")
            if looks_like_xml(body):
                return body
            return decode_pob_code(body)
    if text.startswith("http://") or text.startswith("https://"):
        return decode_pob_code(fetch_pobb(text))
    return decode_pob_code(text)


# ---------------------------------------------------------------------------
# XML 해석
# ---------------------------------------------------------------------------

def _gem_tags(name: str, game: str = datafiles.GAME_POE1) -> tuple[str, ...]:
    for key, tags in datafiles.active_gems(game).items():
        if naming.norm(key) == naming.norm(name):
            return tuple(tags)
    return ()


def _is_support_gem(name: str, gem_id: str = "") -> bool:
    if name and naming.is_support_name(name):
        return True
    return "SupportGem" in (gem_id or "") or (gem_id or "").endswith("Support")


def _build_gem(element: ET.Element, game: str = datafiles.GAME_POE1) -> Gem:
    name = (element.get("nameSpec") or "").strip()
    levels = element.get("level")
    qualities = element.get("quality")
    return Gem(
        name=name,
        enabled=(element.get("enabled", "true").lower() != "false"),
        support=_is_support_gem(name, element.get("gemId", "")),
        level=int(levels) if levels and levels.isdigit() else None,
        quality=int(qualities) if qualities and qualities.isdigit() else None,
        tags=_gem_tags(name, game),
    )


def _active_skill_set(root: ET.Element) -> ET.Element | None:
    skills = root.find("Skills")
    if skills is None:
        return None
    sets = skills.findall("SkillSet")
    if not sets:
        return None
    active_id = skills.get("activeSkillSet")
    for skill_set in sets:
        if skill_set.get("id") == active_id:
            return skill_set
    return sets[0]


def _score_group(gems: list[Gem], is_main_group: bool) -> float:
    supports = [g for g in gems if g.support and g.enabled]
    actives = [g for g in gems if not g.support and g.enabled]
    if not actives:
        return -1.0
    score = len(supports) * 2.0
    if is_main_group:
        score += 3.0
    best = max(actives, key=lambda g: (g.level or 0) + (g.quality or 0) / 100)
    score += min(best.level or 0, 21) / 10.0
    if set(best.tags) & _UTILITY_TAGS:
        score -= 8.0
    return score


def detect_game(xml: str) -> str:
    """PoB XML 루트 태그로 게임을 판별한다(PathOfBuilding2 = PoE2)."""
    head = xml.lstrip()[:400].lower()
    if "pathofbuilding2" in head:
        return datafiles.GAME_POE2
    return datafiles.GAME_POE1


def parse_pob_xml(xml: str, *, name: str = "", source: str = "", notes: str = "",
                  game: str | None = None) -> BuildProfile:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise PobError(f"PoB XML 을 해석하지 못했습니다: {exc}") from exc

    build = root.find("Build")
    if build is None:
        raise PobError("PoB XML 에 <Build> 가 없습니다.")

    resolved_game = datafiles.normalize_game(game) if game else detect_game(xml)
    profile = BuildProfile(
        name=name,
        game=resolved_game,
        class_name=build.get("className", ""),
        ascendancy=build.get("ascendClassName", ""),
        level=int(build.get("level")) if (build.get("level") or "").isdigit() else None,
        source=source,
        notes=notes,
    )

    for stat in build.findall("PlayerStat"):
        key = stat.get("stat") or ""
        value = stat.get("value") or ""
        try:
            profile.stats[key] = float(value)
        except ValueError:
            continue

    spec = root.find("Tree")
    if spec is not None:
        active_spec = spec.get("activeSpec")
        chosen = None
        for candidate in spec.findall("Spec"):
            if candidate.get("activeSpec") == active_spec:
                chosen = candidate
                break
        chosen = chosen if chosen is not None else (spec.findall("Spec") or [None])[0]
        if chosen is not None:
            profile.tree_version = chosen.get("treeVersion", "")
            nodes = [n for n in (chosen.get("nodes") or "").split(",") if n.strip()]
            keymap = datafiles.keystones(resolved_game)
            profile.keystones = sorted({keymap[n.strip()] for n in nodes if n.strip() in keymap})

    skill_set = _active_skill_set(root)
    main_group = build.get("mainSocketGroup")
    main_index = int(main_group) - 1 if (main_group or "").isdigit() else 0

    if skill_set is not None:
        groups: list[tuple[int, list[Gem]]] = []
        for index, skill in enumerate(skill_set.findall("Skill")):
            if skill.get("enabled", "true").lower() == "false":
                continue
            gems = [_build_gem(g, resolved_game) for g in skill.findall("Gem")]
            if gems:
                groups.append((index, gems))

        scored = [
            (_score_group(gems, index == main_index), index, gems) for index, gems in groups
        ]
        scored.sort(key=lambda item: item[0], reverse=True)

        def actives(gems: list[Gem], *, skip_utility: bool) -> list[Gem]:
            out = []
            for gem in gems:
                if gem.support or not gem.enabled or not gem.name:
                    continue
                if skip_utility and set(gem.tags) & _UTILITY_TAGS:
                    continue
                out.append(gem)
            return out

        top_score = scored[0][0] if scored else 0.0
        threshold = max(top_score * 0.45, 0.0)
        main: list[Gem] = []
        for score, _, gems in scored:
            if score < threshold:
                continue
            main.extend(actives(gems, skip_utility=True))
        if not main and scored:
            main = actives(scored[0][2], skip_utility=False)

        def dedupe(gems: list[Gem], limit: int | None = None) -> list[Gem]:
            seen: set[str] = set()
            out: list[Gem] = []
            for gem in gems:
                key = naming.norm(gem.name)
                if key in seen:
                    continue
                seen.add(key)
                out.append(gem)
            return out[:limit] if limit else out

        profile.main_skills = dedupe(main, limit=3)
        main_keys = {naming.norm(g.name) for g in profile.main_skills}
        others: list[Gem] = []
        for _, _, gems in scored:
            others.extend(actives(gems, skip_utility=False))
        profile.secondary_skills = [
            gem for gem in dedupe(others) if naming.norm(gem.name) not in main_keys
        ]
        support_seen: set[str] = set()
        supports: list[Gem] = []
        for _, _, gems in scored:
            for gem in gems:
                if gem.support and gem.enabled and gem.name:
                    key = naming.norm(gem.name)
                    if key in support_seen:
                        continue
                    support_seen.add(key)
                    supports.append(gem)
        profile.supports = supports

    items = root.find("Items")
    if items is not None:
        uniques: list[str] = []
        for item in items.findall("Item"):
            text = (item.text or "").strip()
            if not text:
                continue
            rows = [row.strip() for row in text.splitlines() if row.strip()]
            if not rows or not rows[0].upper().startswith("RARITY:"):
                continue
            if rows[0].split(":", 1)[1].strip().upper() != "UNIQUE":
                continue
            if len(rows) < 2:
                continue
            item_name = rows[1]
            if item_name not in uniques:
                uniques.append(item_name)
        profile.uniques = uniques

    if not profile.main_skills:
        profile.warnings.append("주력 스킬을 찾지 못했습니다(젬 정보 없음).")
    return profile


def load_build(source: str, *, name: str = "", notes: str = "",
               game: str | None = None) -> BuildProfile:
    """코드/URL/파일 → BuildProfile."""
    xml = resolve_source(source)
    return parse_pob_xml(xml, name=name, source=source if "\n" not in source else "붙여넣은 코드",
                         notes=notes, game=game)


def encode_pob_code(xml: str) -> str:
    """XML → PoB 코드(base64url, 패딩 없음). 테스트·내보내기용."""
    compressed = zlib.compress(xml.encode("utf-8"), 9)
    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def code_for(source: str) -> str:
    """코드/XML/PoB 파일 → 가져오기용 PoB 코드.

    이미 코드 형태면 원문을 그대로 돌려준다(내장 빌드의 pobb.in 코드 보존).
    XML 이면 base64+zlib 코드로 되돌린다. 어느 경우에도 빈 문자열은 돌려주지 않는다.
    """
    text = (source or "").strip()
    if not text:
        raise PobError("PoB 코드가 비어 있습니다.")
    xml = resolve_source(text)
    if looks_like_xml(text):
        return encode_pob_code(xml)
    return re.sub(r"\s+", "", text)
