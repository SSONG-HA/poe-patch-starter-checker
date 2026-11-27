"""PoB XML → 빌드 가이드 & 빌드업 자동 생성.

설계 원칙
---------
- **시즌 번호에 묶이지 않는다.** 3.30 / 0.5 같은 값은 표시용일 뿐이고, 가이드의 모든
  내용은 넘겨받은 PoB XML 한 개만으로 만들어진다. 다음 시즌 새 PoB(pobb.in URL·PoB
  코드·XML)를 넣어도 같은 코드가 그대로 동작한다.
- 하드코딩 금지. 스킬 세트·장비 세트·트리 단계·메모는 XML 에 있는 것을 순서대로 읽는다.
- 이름을 모르면 영문 그대로 안전하게 표시한다(`names_kr.json` 미등재 신규 젬·유니크).
"""
from __future__ import annotations

import html
import os
import re
import tempfile
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import APP_TITLE, __version__, datafiles, naming, pob

# 보조 스킬(오라·저주·이동기 등) 판별 태그 — pob 와 같은 어휘를 쓴다.
UTILITY_TAGS = frozenset(
    {
        "aura", "herald", "curse", "hex", "golem", "movement", "travel", "blink",
        "warcry", "trigger", "banner", "guard", "link", "stance", "offering", "persistent",
    }
)

SLOT_ORDER = [
    "Weapon 1", "Weapon 2", "Offhand 1", "Offhand 2",
    "Helmet", "Head", "Body Armour", "Body", "Gloves", "Arm 1", "Arm 2",
    "Boots", "Leg 1", "Leg 2", "Amulet", "Ring 1", "Ring 2", "Ring 3",
    "Belt", "Charm 1", "Charm 2", "Charm 3", "Graft 1", "Graft 2",
    "Flask 1", "Flask 2", "Flask 3", "Flask 4", "Flask 5",
    "Weapon 1 Swap", "Weapon 2 Swap", "Offhand 1 Swap", "Offhand 2 Swap",
]

_COLOR_RE = re.compile(r"\^(?:x[0-9A-Fa-f]{6}|.)")
_AFFIX_TAG_RE = re.compile(r"\{[^}]*\}")
_PLACEHOLDER_NAMES = {"new item", "new item (copy)", "new item (copy 2)"}
_RULE_RE = re.compile(r"^[\s~=*_\-]{3,}$")
_META_PREFIXES = (
    "unique id:", "item level:", "levelreq:", "quality:", "sockets:", "implicits:",
    "radius:", "limited to:", "cluster jewel skill:", "cluster jewel node count:",
    "item class:", "stack size:", "catalyst:", "talisman tier:", "map tier:",
    "area level:", "prefix:", "suffix:", "enchant:", "requirements:", "level:",
    "gem level:", "corrupted:", "mirrored:",
)
_FLAGS = {
    "corrupted", "mirrored", "split", "synthesised", "unscalable value", "foil unique",
    "identified", "unidentified",
}
_KEY_MOD_PATTERNS = (
    (r"to maximum life", 12),
    (r"to maximum mana", 6),
    (r"resist", 10),
    (r"\+[0-9]+ to level of", 10),
    (r"added passive skill is", 9),
    (r"increased .*damage|more .*damage", 6),
    (r"attack speed|cast speed", 6),
    (r"critical", 5),
    (r"suppress", 5),
    (r"increased armour|increased evasion|energy shield", 4),
    (r"\+[0-9]+ to (strength|dexterity|intelligence)", 4),
    (r"movement speed", 3),
)


class GuideError(RuntimeError):
    """가이드를 만들 수 없을 때."""


# ---------------------------------------------------------------------------
# 이름 표기
# ---------------------------------------------------------------------------

def strip_pob_colors(text: str) -> str:
    """PoB 색상 코드(`^7`, `^xC8C8C8`) 제거."""
    return _COLOR_RE.sub("", text or "")


def clean_text(text: str) -> str:
    return strip_pob_colors(text).replace("\t", "    ").replace("\r\n", "\n").strip()


def clean_title(text: str) -> tuple[str, list[str]]:
    """세트 제목 정리: 색상 코드·장식 기호·`{id}` 참조 제거.

    PoB 가이드는 제목에 `{1}` 처럼 같은 번호의 장비/스킬 세트를 가리키는 표시를 넣는다.
    """
    text = clean_text(text)
    ids: list[str] = []
    for group in re.findall(r"\{([0-9,\s]+)\}", text):
        for token in re.split(r"[,\s]+", group):
            if token and token not in ids:
                ids.append(token)
    text = re.sub(r"\{[0-9,\s]+\}", "", text)
    text = re.sub(r"^[\s\-=~_*]+|[\s\-=~_*]+$", "", text)
    return re.sub(r"\s{2,}", " ", text).strip(), ids


def _name_candidates(name: str, section: str) -> Iterable[str]:
    name = (name or "").strip()
    if not name:
        return
    yield name
    if section == "gems" and not name.lower().endswith("support"):
        yield f"{name} Support"
    for prefix in ("Foulborn ", "Nerfed "):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            yield rest
            if section == "gems":
                yield f"{rest} Support"
    # "Brutal Restraint 6965; 3; Eternal Youth" 처럼 PoB 가 씨앗을 붙인 이름
    variant = re.split(r"\s+\d+;", name, maxsplit=1)[0]
    if variant != name:
        yield variant.strip()
    # "Bathed in the Blood of X" 처럼 대소문자만 다른 표기
    yield name.replace("’", "'")


_KOREAN_INDEX: dict[tuple[str, str], dict[str, str]] = {}


def _korean_index(game: str, section: str) -> dict[str, str]:
    key = (datafiles.normalize_game(game), section)
    if key not in _KOREAN_INDEX:
        table = datafiles.korean_names().get(key[0], {})
        rows = table.get(section, {}) if isinstance(table, dict) else {}
        _KOREAN_INDEX[key] = {naming.norm(en): ko for en, ko in rows.items() if en and ko}
    return _KOREAN_INDEX[key]


def korean(game: str, section: str, name: str) -> str:
    """영문 이름 → 한국어 표기. 없으면 빈 문자열(영문 그대로 표시)."""
    table = datafiles.korean_names().get(datafiles.normalize_game(game), {})
    rows = table.get(section, {}) if isinstance(table, dict) else {}
    for candidate in _name_candidates(name, section):
        if candidate in rows and rows[candidate]:
            return rows[candidate]
    index = _korean_index(game, section)
    for candidate in _name_candidates(name, section):
        hit = index.get(naming.norm(candidate))
        if hit:
            return hit
    return ""


def ko_label(game: str, section: str, name: str) -> str:
    label = korean(game, section, name)
    return f"{name} ({label})" if label and label != name else name


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------

@dataclass
class GemInfo:
    name: str
    level: int | None = None
    quality: int | None = None
    enabled: bool = True
    support: bool = False
    corrupted: bool = False
    count: int = 1
    tags: tuple[str, ...] = ()
    korean: str = ""

    @property
    def level_label(self) -> str:
        if self.level and self.quality:
            return f"{self.level}/{self.quality}"
        if self.level:
            return str(self.level)
        if self.quality:
            return f"q{self.quality}"
        return ""

    @property
    def label(self) -> str:
        bits = [self.name]
        if self.korean and self.korean != self.name:
            bits.append(f"({self.korean})")
        if self.level_label:
            bits.append(self.level_label)
        if self.count > 1:
            bits.append(f"x{self.count}")
        if self.corrupted:
            bits.append("타락")
        return " ".join(bits)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "korean": self.korean,
            "level": self.level,
            "quality": self.quality,
            "level_label": self.level_label,
            "support": self.support,
            "enabled": self.enabled,
            "corrupted": self.corrupted,
            "count": self.count,
            "tags": list(self.tags),
        }


@dataclass
class SkillLink:
    index: int
    label: str = ""
    slot: str = ""
    source: str = ""
    enabled: bool = True
    gems: list[GemInfo] = field(default_factory=list)
    is_main: bool = False

    @property
    def actives(self) -> list[GemInfo]:
        return [g for g in self.gems if not g.support]

    @property
    def main_gem(self) -> GemInfo | None:
        for gem in self.gems:
            if not gem.support and gem.enabled:
                return gem
        return self.gems[0] if self.gems else None

    @property
    def supports(self) -> list[GemInfo]:
        return [g for g in self.gems if g.support]

    @property
    def title(self) -> str:
        if self.label:
            return self.label
        gem = self.main_gem
        return gem.name if gem else "(빈 스킬)"

    @property
    def kind_label(self) -> str:
        if not self.enabled:
            return "비활성"
        return "메인 링크" if self.is_main else "보조 링크"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "label": self.label,
            "slot": self.slot,
            "source": self.source,
            "enabled": self.enabled,
            "main": self.is_main,
            "gems": [g.to_dict() for g in self.gems],
        }


@dataclass
class SkillSetInfo:
    id: str
    title: str
    active: bool = False
    links: list[SkillLink] = field(default_factory=list)
    linked_ids: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.title or f"스킬 세트 {self.id}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "name": self.name,
            "active": self.active,
            "links": [link.to_dict() for link in self.links],
        }


@dataclass
class ItemInfo:
    slot: str
    rarity: str = ""
    name: str = ""
    base: str = ""
    mods: list[str] = field(default_factory=list)
    implicits: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    kind: str = "normal"
    korean: str = ""
    item_id: str = ""

    @property
    def display_name(self) -> str:
        if self.name and self.name.strip().lower() not in _PLACEHOLDER_NAMES:
            return self.name
        return self.base or self.name or "(빈 아이템)"

    @property
    def label(self) -> str:
        bits = [self.display_name]
        if self.korean and self.korean != self.display_name:
            bits.append(f"({self.korean})")
        return " ".join(bits)

    @property
    def kind_label(self) -> str:
        return {
            "unique": "고유",
            "relic": "유물",
            "rare": "레어",
            "magic": "매직",
            "normal": "노멀",
            "flask": "플라스크",
            "cluster": "클러스터 주얼",
            "jewel": "주얼",
        }.get(self.kind, self.kind)

    @property
    def key_mods(self) -> list[str]:
        if not self.mods:
            return []
        scored: list[tuple[int, int, str]] = []
        for index, mod in enumerate(self.mods):
            low = mod.lower()
            weight = 0
            for pattern, value in _KEY_MOD_PATTERNS:
                if re.search(pattern, low):
                    weight = max(weight, value)
            if weight:
                scored.append((-weight, index, mod))
        scored.sort()
        picked = [mod for _, _, mod in scored]
        if self.kind == "unique" or self.kind == "relic":
            return picked[:2] or self.mods[:2]
        return picked[:4] or self.mods[:4]

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "rarity": self.rarity,
            "name": self.name,
            "base": self.base,
            "korean": self.korean,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "flags": self.flags,
            "key_mods": self.key_mods,
            "mods": self.mods,
        }


@dataclass
class ItemSetInfo:
    id: str
    title: str
    active: bool = False
    items: list[ItemInfo] = field(default_factory=list)
    linked_ids: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.title or f"장비 세트 {self.id}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "name": self.name,
            "active": self.active,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class SpecInfo:
    index: int
    title: str
    tree_version: str = ""
    nodes: int = 0
    keystones: list[str] = field(default_factory=list)
    set_ids: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.title or f"트리 {self.index}"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "name": self.name,
            "tree_version": self.tree_version,
            "nodes": self.nodes,
            "keystones": self.keystones,
            "set_ids": self.set_ids,
        }


@dataclass
class FitInfo:
    """콘텐츠 적합도(1~5). recommend 모듈이 채운다(없으면 표시 생략)."""

    mapping: int = 3
    bossing: int = 3
    tankiness: int = 3
    budget: int = 3
    ease: int = 3
    tags: tuple[str, ...] = ()
    note: str = ""
    auto: bool = False

    def to_dict(self) -> dict:
        return {
            "mapping": self.mapping,
            "bossing": self.bossing,
            "tankiness": self.tankiness,
            "budget": self.budget,
            "ease": self.ease,
            "tags": list(self.tags),
            "note": self.note,
            "auto": self.auto,
        }


@dataclass
class PatchHitInfo:
    kind_label: str
    name: str
    direction: str
    summary: str
    lines: list[str] = field(default_factory=list)


@dataclass
class PatchImpact:
    verdict: str
    label: str
    headline: str
    source: str = ""
    error: str = ""
    hits: list[PatchHitInfo] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)

    @property
    def nerf_count(self) -> int:
        return len([h for h in self.hits if h.direction in ("nerf", "mixed")])

    @property
    def buff_count(self) -> int:
        return len([h for h in self.hits if h.direction == "buff"])

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "label": self.label,
            "headline": self.headline,
            "source": self.source,
            "error": self.error,
            "buff_count": self.buff_count,
            "nerf_count": self.nerf_count,
            "hits": [
                {
                    "kind": h.kind_label,
                    "name": h.name,
                    "direction": h.direction,
                    "summary": h.summary,
                    "lines": h.lines,
                }
                for h in self.hits
            ],
            "advice": self.advice,
        }


@dataclass
class Guide:
    build_id: str
    name: str
    game: str
    game_label: str
    kind_label: str = ""
    origin: str = ""
    note: str = ""
    class_name: str = ""
    ascendancy: str = ""
    level: int | None = None
    tree_version: str = ""
    code: str = ""
    source_url: str = ""
    skill_sets: list[SkillSetInfo] = field(default_factory=list)
    item_sets: list[ItemSetInfo] = field(default_factory=list)
    specs: list[SpecInfo] = field(default_factory=list)
    keystones: list[str] = field(default_factory=list)
    notes: str = ""
    notes_blocks: list[tuple[str, str]] = field(default_factory=list)
    patch: PatchImpact | None = None
    fit: FitInfo | None = None
    fit_reason: str = ""
    stats: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def ascendancy_label(self) -> str:
        ko = korean(self.game, "ascendancies", self.ascendancy)
        return f"{self.ascendancy} ({ko})" if ko and ko != self.ascendancy else self.ascendancy

    @property
    def class_label(self) -> str:
        ko = korean(self.game, "ascendancies", self.class_name)
        return f"{self.class_name} ({ko})" if ko and ko != self.class_name else self.class_name

    @property
    def has_code(self) -> bool:
        return bool(self.code)

    @property
    def skill_set_count(self) -> int:
        return len(self.skill_sets)

    def headline(self) -> str:
        bits = [x for x in (self.ascendancy_label or self.class_label,
                            f"{self.level}레벨" if self.level else "",
                            f"트리 {self.tree_version}" if self.tree_version else "") if x]
        return " · ".join(bits)

    def to_dict(self) -> dict:
        return {
            "build_id": self.build_id,
            "name": self.name,
            "game": self.game,
            "game_label": self.game_label,
            "kind": self.kind_label,
            "origin": self.origin,
            "note": self.note,
            "class": self.class_name,
            "ascendancy": self.ascendancy,
            "level": self.level,
            "tree_version": self.tree_version,
            "source": self.source_url,
            "has_pob_code": self.has_code,
            "pob_code_length": len(self.code),
            "keystones": self.keystones,
            "skill_sets": [s.to_dict() for s in self.skill_sets],
            "item_sets": [s.to_dict() for s in self.item_sets],
            "specs": [s.to_dict() for s in self.specs],
            "notes_length": len(self.notes),
            "patch": self.patch.to_dict() if self.patch else None,
            "fit": self.fit.to_dict() if self.fit else None,
            "fit_reason": self.fit_reason,
            "warnings": self.warnings,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
        }


# ---------------------------------------------------------------------------
# XML → 가이드
# ---------------------------------------------------------------------------

def _tags_for(name: str, game: str) -> tuple[str, ...]:
    for key, tags in datafiles.active_gems(game).items():
        if naming.norm(key) == naming.norm(name):
            return tuple(tags)
    return ()


def _is_support(name: str, gem_id: str) -> bool:
    if name and naming.is_support_name(name):
        return True
    gem_id = gem_id or ""
    return "SupportGem" in gem_id or gem_id.endswith("Support")


def _gem_from_element(element: Any, game: str) -> GemInfo | None:
    name = (element.get("nameSpec") or "").strip()
    if not name:
        return None
    level = element.get("level") or ""
    quality = element.get("quality") or ""
    count = element.get("count") or ""
    return GemInfo(
        name=name,
        level=int(level) if level.isdigit() else None,
        quality=int(quality) if quality.isdigit() else None,
        enabled=(element.get("enabled", "true").lower() != "false"),
        support=_is_support(name, element.get("gemId") or ""),
        corrupted=(element.get("corrupted", "false").lower() == "true"),
        count=int(count) if count.isdigit() and int(count) > 0 else 1,
        tags=_tags_for(name, game),
        korean=korean(game, "gems", name),
    )


def _ordered_gems(gems: list[GemInfo]) -> list[GemInfo]:
    """메인 젬을 맨 앞으로. 나머지는 PoB 소켓 순서를 유지한다."""
    main = next((gem for gem in gems if not gem.support and gem.enabled), None)
    if main is None:
        return gems
    return [main] + [gem for gem in gems if gem is not main]


def _link_score(link: SkillLink) -> float:
    """링크 세트 중 '메인 링크'를 고르는 점수(서포트 수·젬 레벨·보조 스킬 감점)."""
    if not link.enabled:
        return -50.0
    supports = len([g for g in link.gems if g.support and g.enabled])
    actives = [g for g in link.gems if not g.support and g.enabled]
    score = supports * 2.0
    if actives:
        best = max(actives, key=lambda g: (g.level or 0) + (g.quality or 0) / 100)
        score += min(best.level or 0, 21) / 10.0
        if set(best.tags) & UTILITY_TAGS:
            score -= 6.0
    else:
        score -= 4.0
    return score


def _parse_skill_sets(root: Any, game: str) -> list[SkillSetInfo]:
    skills = root.find("Skills")
    if skills is None:
        return []
    active_id = skills.get("activeSkillSet") or ""
    sets: list[SkillSetInfo] = []
    for order, skill_set in enumerate(skills.findall("SkillSet")):
        set_id = skill_set.get("id") or str(order + 1)
        links: list[SkillLink] = []
        for index, skill in enumerate(skill_set.findall("Skill")):
            gems = [g for g in (_gem_from_element(el, game) for el in skill.findall("Gem")) if g]
            if not gems:
                continue
            links.append(
                SkillLink(
                    index=index,
                    label=clean_text(skill.get("label") or ""),
                    slot=(skill.get("slot") or "").strip(),
                    source=(skill.get("source") or "").strip(),
                    enabled=(skill.get("enabled", "true").lower() != "false"),
                    gems=_ordered_gems(gems),
                )
            )
        if links:
            best = max(links, key=lambda link: (_link_score(link), -link.index))
            if _link_score(best) > 0:
                best.is_main = True
        links.sort(key=lambda link: (not link.is_main, link.index))
        title, linked = clean_title(skill_set.get("title") or "")
        sets.append(
            SkillSetInfo(
                id=set_id,
                title=title,
                active=(set_id == active_id),
                links=links,
                linked_ids=linked,
            )
        )
    return sets


def _is_meta(line: str) -> bool:
    low = line.strip().lower()
    return any(low.startswith(prefix) for prefix in _META_PREFIXES)


def _is_flag(line: str) -> bool:
    low = line.strip().lower()
    return low in _FLAGS or low.startswith("foil unique")


def _classify(rarity: str, name: str, base: str) -> str:
    probe = f"{name} {base}".lower()
    if "flask" in probe:
        return "flask"
    if "cluster jewel" in probe:
        return "cluster"
    if "jewel" in probe:
        return "jewel"
    return {
        "UNIQUE": "unique",
        "RELIC": "relic",
        "RARE": "rare",
        "MAGIC": "magic",
        "NORMAL": "normal",
    }.get(rarity, "normal")


def parse_item_text(text: str, *, slot: str = "", item_id: str = "",
                    game: str = datafiles.GAME_POE1) -> ItemInfo | None:
    """PoB `<Item>` 본문(아이템 복사 텍스트)을 구조화한다."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return None
    rarity = ""
    if lines[0].lower().startswith("rarity:"):
        rarity = lines[0].split(":", 1)[1].strip().upper()
        lines = lines[1:]
    if not lines:
        return None

    name = lines[0]
    index = 1
    base = name if rarity == "NORMAL" else ""
    if rarity in ("UNIQUE", "RELIC", "RARE") and index < len(lines) and not _is_meta(lines[index]):
        base = lines[index]
        index += 1

    implicit_count = 0
    mods_raw: list[str] = []
    flags: list[str] = []
    for line in lines[index:]:
        low = line.lower()
        if low.startswith("implicits:"):
            value = line.split(":", 1)[1].strip()
            implicit_count = int(value) if value.isdigit() else 0
            continue
        if _is_meta(line):
            continue
        if _is_flag(line):
            flags.append(line)
            continue
        mods_raw.append(_AFFIX_TAG_RE.sub("", line).strip())
    implicits = mods_raw[:implicit_count] if implicit_count else []
    mods = mods_raw[implicit_count:] if implicit_count else mods_raw
    kind = _classify(rarity, name, base)
    section = "uniques" if kind in ("unique", "relic") else "uniques"
    return ItemInfo(
        slot=slot,
        rarity=rarity,
        name=name,
        base=base,
        mods=mods,
        implicits=implicits,
        flags=flags,
        kind=kind,
        korean=korean(game, section, name) if kind in ("unique", "relic") else "",
        item_id=item_id,
    )


def _slot_key(slot: str, fallback: int) -> tuple[int, int]:
    base = slot
    nested = 0
    match = re.match(r"^(.*?)\s+(Abyssal Socket|Jewel Socket)\s+(\d+)$", slot)
    if match:
        base = match.group(1)
        nested = 1
    try:
        order = SLOT_ORDER.index(base)
    except ValueError:
        order = len(SLOT_ORDER) + fallback
    return (order, nested)


def _parse_item_sets(root: Any, game: str) -> list[ItemSetInfo]:
    items_el = root.find("Items")
    if items_el is None:
        return []
    by_id: dict[str, ItemInfo] = {}
    for element in items_el.findall("Item"):
        info = parse_item_text(
            element.text or "", item_id=element.get("id") or "", game=game
        )
        if info is not None and info.item_id:
            by_id[info.item_id] = info

    active_id = items_el.get("activeItemSet") or ""
    sets: list[ItemSetInfo] = []
    for order, item_set in enumerate(items_el.findall("ItemSet")):
        set_id = item_set.get("id") or str(order + 1)
        rows: list[tuple[tuple[int, int], ItemInfo]] = []
        for position, slot_el in enumerate(item_set.findall("Slot")):
            item_id = (slot_el.get("itemId") or "0").strip()
            if item_id in ("", "0"):
                continue
            info = by_id.get(item_id)
            if info is None:
                continue
            slot_name = (slot_el.get("name") or "").strip()
            clone = ItemInfo(**{**info.__dict__, "slot": slot_name})
            rows.append((_slot_key(slot_name, position), clone))
        rows.sort(key=lambda pair: pair[0])
        title, linked = clean_title(item_set.get("title") or "")
        sets.append(
            ItemSetInfo(
                id=set_id,
                title=title,
                active=(set_id == active_id),
                items=[item for _, item in rows],
                linked_ids=linked,
            )
        )
    return sets


def _parse_specs(root: Any, game: str) -> list[SpecInfo]:
    tree = root.find("Tree")
    if tree is None:
        return []
    keystone_map = datafiles.keystones(game)
    specs: list[SpecInfo] = []
    for index, spec in enumerate(tree.findall("Spec"), start=1):
        nodes = [n.strip() for n in (spec.get("nodes") or "").split(",") if n.strip()]
        title = clean_text(spec.get("title") or "")
        set_ids = re.findall(r"\{([0-9,\s]+)\}", title)
        ids: list[str] = []
        for group in set_ids:
            for token in re.split(r"[,\s]+", group):
                if token and token not in ids:
                    ids.append(token)
        specs.append(
            SpecInfo(
                index=index,
                title=re.sub(r"\{[0-9,\s]+\}", "", title).strip(),
                tree_version=(spec.get("treeVersion") or "").strip(),
                nodes=len(nodes),
                keystones=sorted({keystone_map[n] for n in nodes if n in keystone_map}),
                set_ids=ids,
            )
        )
    return specs


def notes_blocks(text: str) -> list[tuple[str, str]]:
    """PoB `<Notes>` 를 (종류, 본문) 목록으로 정리한다. 종류: heading | text."""
    lines = [clean_text(line).rstrip() for line in (text or "").splitlines()]
    blocks: list[tuple[str, str]] = []
    total = len(lines)
    i = 0
    while i < total:
        line = lines[i]
        if _RULE_RE.match(line) and i + 2 < total and _RULE_RE.match(lines[i + 2]) and lines[i + 1].strip():
            blocks.append(("heading", lines[i + 1].strip()))
            i += 3
            continue
        if _RULE_RE.match(line) or not line.strip():
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < total and lines[i].strip() and not _RULE_RE.match(lines[i]):
            paragraph.append(lines[i])
            i += 1
        blocks.append(("text", "\n".join(paragraph)))
    return blocks


def notes_text(blocks: list[tuple[str, str]]) -> str:
    out: list[str] = []
    for kind, body in blocks:
        out.append(f"■ {body}" if kind == "heading" else body)
    return "\n\n".join(out)


def _patch_impact(entry: Any, result: Any) -> PatchImpact | None:
    if result is None:
        return None
    verdict = None
    for candidate in getattr(result, "verdicts", []):
        if candidate.build_id == getattr(entry, "id", ""):
            verdict = candidate
            break
    if verdict is None:
        return None
    hits: list[PatchHitInfo] = []
    for hit, lines in verdict.matched_lines():
        hits.append(
            PatchHitInfo(
                kind_label=hit.kind_label,
                name=hit.entity_name,
                direction=hit.direction,
                summary=hit.describe(),
                lines=list(lines)[:6],
            )
        )
    advice: list[str] = []
    for hit in hits:
        if hit.direction in ("nerf", "mixed"):
            advice.append(
                f"‘{hit.name}’({hit.kind_label}) 너프 — PoB에서 이 요소를 유지·교체했을 때의 "
                "DPS·생존을 비교하고, 젬 레벨·퀄리티와 패시브 투자로 보완하세요."
            )
        elif hit.direction == "buff":
            advice.append(
                f"‘{hit.name}’({hit.kind_label}) 상향 — 새 수치를 PoB에 반영해 더 강해졌는지 확인하세요."
            )
        else:
            advice.append(
                f"‘{hit.name}’({hit.kind_label}) 변경 — 발동 조건·지속시간·수치가 바뀌었는지 원문을 확인하세요."
            )
    if not advice:
        advice.append(
            "이 패치노트에는 이 빌드의 구성 요소(주력 스킬·서포트·전직·키스톤·유니크)와 "
            "겹치는 변경이 없습니다."
        )
    title = getattr(getattr(result, "notes", None), "title", "") or ""
    return PatchImpact(
        verdict=verdict.verdict,
        label=verdict.label,
        headline=verdict.headline(),
        source=getattr(result, "source_label", "") or title,
        error=verdict.error,
        hits=hits,
        advice=advice,
    )


def _fit_for(entry: Any, profile: pob.BuildProfile) -> FitInfo | None:
    try:
        from . import recommend  # 순환 import 방지(지연 로딩)

        return recommend.fit_for(getattr(entry, "id", ""), profile).as_guide_fit()
    except Exception:  # noqa: BLE001 - 적합도는 없어도 가이드는 만들어진다
        return None


def _fit_reason(fit: FitInfo | None, patch: PatchImpact | None) -> str:
    """추천 사유 — 적합도 수치 + 이번 패치 영향 + 특화 태그."""
    if fit is None:
        return ""
    bits = [
        f"맵핑 {fit.mapping}", f"보스 {fit.bossing}", f"탱킹 {fit.tankiness}",
        f"저자본 {fit.budget}", f"편한 조작 {fit.ease}",
    ]
    if patch is not None:
        bits.append(f"패치 {patch.label} (상향 {patch.buff_count}·너프 {patch.nerf_count})")
    if fit.tags:
        bits.append(" · ".join(fit.tags[:3]))
    if fit.auto:
        bits.append("적합도 자동 추정")
    return " · ".join(bits)


def build_guide(entry: Any, *, result: Any = None, xml: str | None = None,
                code: str | None = None) -> Guide:
    """라이브러리 빌드(또는 PoB 소스) 하나로 가이드 전체를 만든다."""
    import xml.etree.ElementTree as ET

    payload = ""
    if xml is None:
        try:
            payload = entry.payload()
        except Exception as exc:  # noqa: BLE001
            raise GuideError(f"PoB 코드를 읽지 못했습니다: {exc}") from exc
        xml = payload if pob.looks_like_xml(payload) else pob.decode_pob_code(payload)
    if code is None:
        code = pob.encode_pob_code(xml) if not payload or pob.looks_like_xml(payload) else pob.code_for(payload)
    code = (code or "").strip()
    if not code:
        raise GuideError("PoB 코드를 만들지 못했습니다.")

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise GuideError(f"PoB XML 을 해석하지 못했습니다: {exc}") from exc

    build = root.find("Build")
    game = datafiles.normalize_game(getattr(entry, "game", "") or pob.detect_game(xml))
    profile = pob.parse_pob_xml(xml, name=getattr(entry, "name", ""), game=game)
    ascendancy = (build.get("ascendClassName") or "") if build is not None else ""
    class_name = (build.get("className") or "") if build is not None else ""
    tree_version = profile.tree_version
    specs = _parse_specs(root, game)
    if not tree_version:
        tree_version = next((s.tree_version for s in specs if s.tree_version), "")

    raw_notes = root.find("Notes")
    raw_notes_text = (raw_notes.text or "") if raw_notes is not None else ""
    blocks = notes_blocks(raw_notes_text)

    source = (getattr(entry, "source", "") or "").strip()
    source_url = source if source.startswith("http") else ""

    guide = Guide(
        build_id=getattr(entry, "id", ""),
        name=getattr(entry, "name", "") or profile.name or "빌드",
        game=game,
        game_label=datafiles.GAME_VERSION_LABELS.get(game, game),
        kind_label=getattr(entry, "kind_label", ""),
        origin=getattr(entry, "origin", ""),
        note=getattr(entry, "note", ""),
        class_name=class_name or profile.class_name,
        ascendancy=ascendancy or profile.ascendancy,
        level=profile.level,
        tree_version=tree_version,
        code=code,
        source_url=source_url,
        skill_sets=_parse_skill_sets(root, game),
        item_sets=_parse_item_sets(root, game),
        specs=specs,
        keystones=profile.keystones,
        notes=notes_text(blocks),
        notes_blocks=blocks,
        patch=_patch_impact(entry, result),
        fit=_fit_for(entry, profile),
        stats=dict(profile.stats),
    )
    guide.fit_reason = _fit_reason(guide.fit, guide.patch)
    if not guide.skill_sets:
        guide.warnings.append("PoB XML 에 스킬 세트가 없습니다.")
    if not guide.item_sets:
        guide.warnings.append("PoB XML 에 장비 세트가 없습니다.")
    if not guide.notes:
        guide.warnings.append("제작자 메모(<Notes>)가 비어 있습니다.")
    if not guide.source_url:
        guide.warnings.append("pobb.in 원본 링크가 없는 빌드입니다(PoB 코드는 내장되어 있습니다).")
    return guide


# ---------------------------------------------------------------------------
# 텍스트 렌더링 (GUI·CLI 공용)
# ---------------------------------------------------------------------------

def _stars(value: int) -> str:
    value = max(0, min(5, int(value)))
    return "★" * value + "☆" * (5 - value)


def _gem_line(gem: GemInfo, *, bullet: str = "    ") -> str:
    bits = [f"{bullet}{gem.name}"]
    if gem.korean and gem.korean != gem.name:
        bits.append(f"({gem.korean})")
    if gem.level_label:
        bits.append(gem.level_label)
    if gem.count > 1:
        bits.append(f"x{gem.count}")
    if gem.corrupted:
        bits.append("타락")
    if not gem.enabled:
        bits.append("[비활성]")
    return " ".join(bits)


def render_text(guide: Guide, *, limit_sets: int | None = None) -> str:
    out: list[str] = []
    out.append("=" * 88)
    out.append(f" {guide.name}")
    out.append("=" * 88)
    bits = [guide.game_label, guide.kind_label, guide.headline()]
    out.append(" · ".join(x for x in bits if x))
    source_bits = [x for x in (guide.origin, guide.source_url) if x]
    if source_bits:
        out.append("출처: " + " · ".join(source_bits))
    if guide.note:
        out.append(f"메모: {guide.note}")
    if guide.has_code:
        out.append(f"PoB 가져오기 코드: {len(guide.code)}자 (아래 [PoB 코드] 또는 'PoB 코드 복사')")
    else:
        out.append("PoB 가져오기 코드: 없음 — 이 빌드는 코드 없이 저장되어 있습니다.")
    for warning in guide.warnings:
        out.append(f"⚠ {warning}")

    # -- 패치노트 영향 -----------------------------------------------------
    out.append("")
    out.append("[이번 패치노트 영향]")
    out.append("-" * 88)
    if guide.patch is None:
        out.append("   패치노트를 불러와 '검사 실행'을 하면 이 빌드에 걸린 버프·너프가 여기에 표시됩니다.")
    else:
        patch = guide.patch
        out.append(f"   {patch.label}  {patch.headline}")
        if patch.source:
            out.append(f"   패치노트: {patch.source}")
        if patch.error:
            out.append(f"   ! {patch.error}")
        if not patch.hits:
            out.append("   이 패치노트에서 이 빌드 구성 요소와 일치하는 항목이 없습니다.")
        for hit in patch.hits:
            out.append(f"   · {hit.summary}")
            for line in hit.lines[:3]:
                out.append(f"       {line}")
    out.append("")
    out.append("[보완 포인트]")
    if guide.patch is None:
        out.append("   · 패치 분석을 연결하면 자동으로 채워집니다.")
    else:
        for item in guide.patch.advice:
            out.append(f"   · {item}")

    # -- 적합도 -----------------------------------------------------------
    if guide.fit is not None:
        fit = guide.fit
        out.append("")
        out.append("[콘텐츠 적합도]" + ("  (자동 추정)" if fit.auto else ""))
        out.append(
            f"   맵핑 {_stars(fit.mapping)} {fit.mapping} · 보스 {_stars(fit.bossing)} {fit.bossing}"
            f" · 탱킹 {_stars(fit.tankiness)} {fit.tankiness}"
        )
        out.append(f"   저자본 {_stars(fit.budget)} {fit.budget} · 편한 조작 {_stars(fit.ease)} {fit.ease}")
        if fit.tags:
            out.append(f"   특화: {' · '.join(fit.tags)}")
        if fit.note:
            out.append(f"   근거: {fit.note}")
        if guide.fit_reason:
            out.append(f"   추천 사유: {guide.fit_reason}")

    # -- 기본 정보 --------------------------------------------------------
    out.append("")
    out.append("[전직 · 키스톤]")
    out.append("-" * 88)
    who = " / ".join(x for x in (guide.class_label, guide.ascendancy_label) if x)
    out.append(f"   직업·전직: {who or '-'}")
    if guide.level:
        out.append(f"   레벨: {guide.level}")
    if guide.tree_version:
        out.append(f"   트리 버전: {guide.tree_version}")
    if guide.keystones:
        out.append("   키스톤: " + ", ".join(ko_label(guide.game, "keystones", k) for k in guide.keystones))
    else:
        out.append("   키스톤: 없음")

    # -- 스킬 세트 --------------------------------------------------------
    out.append("")
    out.append(f"[스킬 세트] {len(guide.skill_sets)}개")
    out.append("-" * 88)
    if not guide.skill_sets:
        out.append("   스킬 세트가 없습니다.")
    shown = guide.skill_sets if limit_sets is None else guide.skill_sets[:limit_sets]
    for number, skill_set in enumerate(shown, start=1):
        mark = "  ← 사용 중(active)" if skill_set.active else ""
        out.append(f"   {number}. {skill_set.name}{mark}")
        if not skill_set.links:
            out.append("      (링크 없음 — 메모나 다른 세트를 참고)")
        for link in skill_set.links:
            slot = f"[{link.slot}] " if link.slot else ""
            out.append(f"      · {link.kind_label} {slot}{link.title}")
            for gem in link.gems:
                out.append(_gem_line(gem, bullet="          "))
    if limit_sets is not None and len(guide.skill_sets) > limit_sets:
        out.append(f"   … 외 {len(guide.skill_sets) - limit_sets}개 세트")

    # -- 장비 세트 --------------------------------------------------------
    out.append("")
    out.append(f"[장비 세트] {len(guide.item_sets)}개")
    out.append("-" * 88)
    if not guide.item_sets:
        out.append("   장비 세트가 없습니다.")
    shown_items = guide.item_sets if limit_sets is None else guide.item_sets[:limit_sets]
    for number, item_set in enumerate(shown_items, start=1):
        mark = "  ← 사용 중(active)" if item_set.active else ""
        out.append(f"   {number}. {item_set.name}{mark}")
        for item in item_set.items:
            flags = f" [{', '.join(item.flags)}]" if item.flags else ""
            base = f" — {item.base}" if item.base and item.base != item.display_name else ""
            out.append(f"      {item.slot:22} {item.label}{base} ({item.kind_label}){flags}")
            for mod in item.key_mods[:3]:
                out.append(f"          - {mod}")
    if limit_sets is not None and len(guide.item_sets) > limit_sets:
        out.append(f"   … 외 {len(guide.item_sets) - limit_sets}개 세트")

    # -- 트리 단계 --------------------------------------------------------
    if guide.specs:
        out.append("")
        out.append(f"[트리 단계] {len(guide.specs)}개")
        out.append("-" * 88)
        for spec in guide.specs:
            sets = f"  ↔ 세트 {', '.join(spec.set_ids)}" if spec.set_ids else ""
            out.append(f"   {spec.index}. {spec.name} — 노드 {spec.nodes}개{sets}")
            if spec.keystones:
                out.append("      키스톤: " + ", ".join(ko_label(guide.game, "keystones", k) for k in spec.keystones))

    # -- 메모 ------------------------------------------------------------
    out.append("")
    out.append("[제작자 메모]")
    out.append("-" * 88)
    if not guide.notes:
        out.append("   (메모 없음)")
    else:
        for line in guide.notes.splitlines():
            out.append(f"   {line}" if line.strip() else "")

    # -- PoB 코드 --------------------------------------------------------
    out.append("")
    out.append("[PoB 코드]")
    out.append("-" * 88)
    out.append("   PoB → Import → 'Import Code' 에 붙여넣으면 이 빌드가 그대로 열립니다.")
    out.append(guide.code)
    out.append("")
    out.append(f"※ {APP_TITLE} v{__version__} · {guide.generated_at:%Y-%m-%d %H:%M} 생성")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML 렌더링
# ---------------------------------------------------------------------------

_CSS = """
:root{--bg:#0b0f14;--panel:#121821;--panel2:#0f151d;--line:#243040;--text:#e6edf6;
--muted:#93a4b8;--accent:#7cc4ff;--gold:#f0c96b;--red:#ff7b72;--green:#53d18b;
--yellow:#f2cc60;--chip:#1b2534}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:linear-gradient(180deg,#0b0f14,#0d1218 40%,#0b0f14);
color:var(--text);font:15px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 72px}
.hero{background:radial-gradient(1200px 320px at 20% -40%,rgba(124,196,255,.22),transparent 60%),
radial-gradient(900px 300px at 85% -60%,rgba(240,201,107,.15),transparent 60%),var(--panel);
border:1px solid var(--line);border-radius:20px;padding:26px 28px;margin-bottom:18px;
box-shadow:0 18px 50px rgba(0,0,0,.35)}
.kicker{color:var(--muted);font-size:12.5px;letter-spacing:.14em;text-transform:uppercase}
h1{margin:6px 0 10px;font-size:31px;line-height:1.25}
h2{margin:0 0 12px;font-size:20px}
h3{margin:18px 0 8px;font-size:16px;color:#cfe2f7}
h4{margin:18px 0 6px;font-size:14.5px;color:var(--gold);letter-spacing:.02em}
.badges{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px}
.chip{background:var(--chip);border:1px solid var(--line);color:#cfe2f7;border-radius:999px;
padding:4px 11px;font-size:12.5px}
.chip.gold{color:var(--gold);border-color:#4a3d1c}
.chip.green{color:var(--green);border-color:#1d4a33}
.chip.red{color:var(--red);border-color:#4d211d}
.chip.yellow{color:var(--yellow);border-color:#4a3d1c}
.actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
button,.btn{background:linear-gradient(180deg,#2b3d54,#1d2a3a);border:1px solid #38526f;color:#eaf3ff;
border-radius:10px;padding:9px 15px;font:inherit;font-size:13.5px;cursor:pointer}
button:hover,.btn:hover{border-color:var(--accent);text-decoration:none}
button.primary{background:linear-gradient(180deg,#1d6fa8,#12466c);border-color:#2c8fd0}
nav.toc{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:6px;padding:10px 0;
background:rgba(11,15,20,.92);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);margin-bottom:18px}
nav.toc a{font-size:13px;color:var(--muted);padding:5px 10px;border-radius:8px;border:1px solid transparent}
nav.toc a:hover{color:var(--text);border-color:var(--line);background:var(--panel);text-decoration:none}
section.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.stat{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stat .label{color:var(--muted);font-size:12px}
.stat .value{font-size:19px;font-weight:700;margin-top:2px}
.bar{height:7px;background:#1a2431;border-radius:99px;overflow:hidden;margin-top:8px}
.bar>span{display:block;height:100%;background:linear-gradient(90deg,#3f8fd4,#7cc4ff);border-radius:99px}
.stars{color:var(--gold);letter-spacing:2px}
table{width:100%;border-collapse:collapse;margin:6px 0 4px;font-size:13.5px}
th,td{border-bottom:1px solid #1c2634;padding:8px 9px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;letter-spacing:.04em}
tr:hover td{background:#131b26}
td.slot{color:#b9cbe0;white-space:nowrap;font-size:12.5px}
.rarity{font-size:11.5px;border-radius:6px;padding:2px 7px;border:1px solid var(--line);color:var(--muted)}
.rarity.unique{color:#d7a75a;border-color:#54401a}
.rarity.rare{color:#f2cc60;border-color:#4a3d1c}
.rarity.flask,.rarity.jewel,.rarity.cluster{color:#8fd3c7;border-color:#204a44}
.mods{margin:4px 0 0;padding-left:16px;color:#a9bcd0;font-size:12.5px}
.mods li{margin:1px 0}
details.set{background:var(--panel2);border:1px solid var(--line);border-radius:13px;margin:10px 0;padding:2px 14px}
details.set[open]{padding-bottom:12px}
details.set>summary{cursor:pointer;list-style:none;padding:11px 2px;font-weight:700;color:#dce9f8}
details.set>summary::-webkit-details-marker{display:none}
details.set>summary:before{content:"▸";color:var(--accent);display:inline-block;width:18px}
details.set[open]>summary:before{content:"▾"}
.set-meta{color:var(--muted);font-weight:400;font-size:12.5px;margin-left:6px}
.link{background:#101823;border:1px solid #1d2a3a;border-radius:11px;padding:10px 12px;margin:9px 0}
.link .head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:4px}
.link .title{font-weight:700}
.gemlist{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.gem{background:#17202c;border:1px solid #22314a;border-radius:8px;padding:3px 8px;font-size:12.5px}
.gem.support{border-color:#2a3b2f;color:#bfe3c8}
.gem .lv{color:var(--gold);margin-left:6px;font-size:12px}
.note{white-space:pre-wrap;background:var(--panel2);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;color:#c2d2e4;font-size:13.5px;margin:8px 0}
.patch-hit{border-left:3px solid var(--line);padding:6px 0 6px 12px;margin:10px 0}
.patch-hit.buff{border-color:var(--green)}
.patch-hit.nerf{border-color:var(--red)}
.patch-hit.neutral{border-color:var(--yellow)}
.patch-hit .quote{color:#9fb3c8;font-size:12.5px;white-space:pre-wrap;margin-top:4px}
.advice li{margin:5px 0}
textarea#pob-code{width:100%;min-height:180px;background:#080c11;color:#9fd0ff;border:1px solid var(--line);
border-radius:12px;padding:12px;font:12px/1.5 ui-monospace,Consolas,Menlo,monospace;word-break:break-all;resize:vertical}
footer{color:#6f8299;font-size:12px;text-align:center;margin-top:30px}
.warn{color:var(--yellow);font-size:13px}
@media print{body{background:#fff;color:#111}nav.toc,button,.btn{display:none}
section.card,details.set,details.set[open]{border-color:#ccc;background:#fff;color:#111}
.note,textarea#pob-code{background:#f6f6f6;color:#111}}
"""

_COPY_JS = """
function flash(msg){var el=document.getElementById('toast');if(!el)return;el.textContent=msg;
el.classList.add('show');setTimeout(function(){el.classList.remove('show')},1800);}
function copyPob(){var t=document.getElementById('pob-code');if(!t){return;}
t.focus();t.select();t.setSelectionRange(0,t.value.length);
if(navigator.clipboard&&navigator.clipboard.writeText){
 navigator.clipboard.writeText(t.value).then(function(){flash('PoB 코드를 복사했습니다')})
 .catch(function(){legacyCopy(t)});}else{legacyCopy(t);}}
function legacyCopy(t){try{document.execCommand('copy');flash('PoB 코드를 복사했습니다');}
catch(e){flash('복사하지 못했습니다. 코드를 직접 선택해 주세요.');}}
function toggleAll(open){document.querySelectorAll('details.set').forEach(function(d){d.open=open;});}
"""


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _star_html(value: int) -> str:
    value = max(0, min(5, int(value)))
    return f'<span class="stars" title="{value}/5">{"★" * value}{"☆" * (5 - value)}</span>'


def _fit_html(fit: FitInfo, reason: str = "") -> str:
    rows = [
        ("맵핑", fit.mapping), ("보스", fit.bossing), ("탱킹", fit.tankiness),
        ("저자본", fit.budget), ("편한 조작", fit.ease),
    ]
    cells = "".join(
        f'<div class="stat"><div class="label">{_e(name)}</div>'
        f'<div class="value">{value} <span style="font-size:13px;color:var(--gold)">{_star_html(value)}</span></div>'
        f'<div class="bar"><span style="width:{value * 20}%"></span></div></div>'
        for name, value in rows
    )
    extra = ""
    if fit.tags:
        extra += '<div class="badges" style="margin-top:12px">' + "".join(
            f'<span class="chip">{_e(tag)}</span>' for tag in fit.tags
        ) + "</div>"
    if fit.note:
        extra += f'<p style="color:#a9bcd0;margin:8px 0 0">{_e(fit.note)}</p>'
    if reason:
        extra += f'<p style="margin:10px 0 0"><strong>추천 사유</strong> — {_e(reason)}</p>'
    if fit.auto:
        extra += '<p class="warn" style="margin:6px 0 0">이 빌드는 직접 추가한 PoB라 적합도를 자동 추정했습니다.</p>'
    return f'<div class="grid">{cells}</div>{extra}'


def _patch_html(patch: PatchImpact | None) -> str:
    if patch is None:
        return (
            '<p style="color:#93a4b8">패치노트를 불러와 검사를 실행하면 이 빌드에 걸린 '
            "버프·너프가 여기에 표시됩니다.</p>"
        )
    cls = {"green": "green", "yellow": "yellow", "red": "red"}.get(patch.verdict, "yellow")
    out = [f'<div class="badges"><span class="chip {cls}">{_e(patch.label)}</span>'
           f'<span class="chip">{_e(patch.headline)}</span></div>']
    if patch.source:
        out.append(f'<p style="color:#93a4b8;margin:2px 0 10px">패치노트: {_e(patch.source)}</p>')
    if patch.error:
        out.append(f'<p class="warn">! {_e(patch.error)}</p>')
    if not patch.hits:
        out.append('<p style="color:#93a4b8">이 패치노트에서 이 빌드 구성 요소와 일치하는 항목이 없습니다.</p>')
    for hit in patch.hits:
        css = hit.direction if hit.direction in ("buff", "nerf") else "neutral"
        quote = "".join(f"<div class=\"quote\">{_e(line)}</div>" for line in hit.lines[:3])
        out.append(
            f'<div class="patch-hit {css}"><strong>{_e(hit.summary)}</strong>{quote}</div>'
        )
    out.append("<h4>보완 포인트</h4><ul class=\"advice\">")
    out.extend(f"<li>{_e(item)}</li>" for item in patch.advice)
    out.append("</ul>")
    return "".join(out)


def _gems_html(link: SkillLink) -> str:
    chips = []
    for gem in link.gems:
        ko = f" ({gem.korean})" if gem.korean and gem.korean != gem.name else ""
        lv = f'<span class="lv">{_e(gem.level_label)}</span>' if gem.level_label else ""
        extra = []
        if gem.count > 1:
            extra.append(f"x{gem.count}")
        if gem.corrupted:
            extra.append("타락")
        if not gem.enabled:
            extra.append("비활성")
        tail = f'<span class="lv">{_e(" ".join(extra))}</span>' if extra else ""
        css = "gem support" if gem.support else "gem"
        chips.append(f'<span class="{css}">{_e(gem.name)}{_e(ko)}{lv}{tail}</span>')
    return '<div class="gemlist">' + "".join(chips) + "</div>"


def _skills_html(guide: Guide) -> str:
    if not guide.skill_sets:
        return '<p style="color:#93a4b8">스킬 세트가 없습니다.</p>'
    out = []
    for number, skill_set in enumerate(guide.skill_sets, start=1):
        meta = [f"세트 {_e(skill_set.id)}"]
        if skill_set.active:
            meta.append("사용 중(active)")
        meta.append(f"링크 {len(skill_set.links)}개")
        out.append(
            f'<details class="set" {"open" if number == 1 else ""}>'
            f'<summary>{number}. {_e(skill_set.name)}'
            f'<span class="set-meta">{" · ".join(meta)}</span></summary>'
        )
        for link in skill_set.links:
            slot = f'<span class="chip">{_e(link.slot)}</span>' if link.slot else ""
            badge = "메인 링크" if link.is_main else link.kind_label
            out.append(
                f'<div class="link"><div class="head">{slot}'
                f'<span class="title">{_e(link.title)}</span>'
                f'<span class="chip">{_e(badge)}</span>'
                + (f'<span class="chip">출처: {_e(link.source)}</span>' if link.source else "")
                + f"</div>{_gems_html(link)}</div>"
            )
        if not skill_set.links:
            out.append('<p style="color:#93a4b8">링크 없음 — 메모나 다른 세트를 참고하세요.</p>')
        out.append("</details>")
    return "".join(out)


def _items_html(guide: Guide) -> str:
    if not guide.item_sets:
        return '<p style="color:#93a4b8">장비 세트가 없습니다.</p>'
    out = []
    for number, item_set in enumerate(guide.item_sets, start=1):
        meta = [f"세트 {_e(item_set.id)}", f"{len(item_set.items)}칸"]
        if item_set.active:
            meta.append("사용 중(active)")
        out.append(
            f'<details class="set" {"open" if number == 1 else ""}>'
            f'<summary>{number}. {_e(item_set.name)}'
            f'<span class="set-meta">{" · ".join(meta)}</span></summary>'
            '<table><thead><tr><th style="width:150px">슬롯</th><th>아이템</th>'
            '<th style="width:96px">분류</th><th>핵심 옵션</th></tr></thead><tbody>'
        )
        for item in item_set.items:
            base = f'<div style="color:#93a4b8;font-size:12.5px">{_e(item.base)}</div>' \
                if item.base and item.base != item.display_name else ""
            flags = "".join(f'<span class="chip">{_e(flag)}</span> ' for flag in item.flags)
            mods = "".join(f"<li>{_e(mod)}</li>" for mod in item.key_mods)
            mods_html = f'<ul class="mods">{mods}</ul>' if mods else ""
            out.append(
                f'<tr><td class="slot">{_e(item.slot)}</td>'
                f'<td><strong>{_e(item.display_name)}</strong>'
                + (f' <span style="color:#9fd0ff">({_e(item.korean)})</span>' if item.korean and item.korean != item.display_name else "")
                + f"{base}{flags}</td>"
                f'<td><span class="rarity {_e(item.kind)}">{_e(item.kind_label)}</span></td>'
                f"<td>{mods_html}</td></tr>"
            )
        out.append("</tbody></table></details>")
    return "".join(out)


def _specs_html(guide: Guide) -> str:
    if not guide.specs:
        return ""
    rows = []
    for spec in guide.specs:
        sets = ", ".join(spec.set_ids)
        keystones = ", ".join(ko_label(guide.game, "keystones", k) for k in spec.keystones)
        rows.append(
            f'<tr><td>{spec.index}</td><td><strong>{_e(spec.name)}</strong></td>'
            f"<td>{spec.nodes}개</td><td>{_e(spec.tree_version)}</td>"
            f"<td>{_e(sets) or '—'}</td><td>{_e(keystones) or '—'}</td></tr>"
        )
    return (
        '<table><thead><tr><th style="width:42px">#</th><th>단계</th><th style="width:90px">노드</th>'
        '<th style="width:90px">트리</th><th style="width:90px">연결 세트</th><th>키스톤</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table>"
    )


def _notes_html(guide: Guide) -> str:
    if not guide.notes_blocks:
        return '<p style="color:#93a4b8">제작자 메모가 없습니다.</p>'
    out = []
    for kind, body in guide.notes_blocks:
        if kind == "heading":
            out.append(f"<h4>{_e(body)}</h4>")
        else:
            out.append(f'<div class="note">{_e(body)}</div>')
    return "".join(out)


def render_html(guide: Guide) -> str:
    """단일 HTML 문서(외부 리소스 없음). PoB 코드 복사 버튼 포함."""
    fit_block = ""
    if guide.fit is not None:
        fit_block = f"""
<section class="card" id="fit">
  <h2>콘텐츠 적합도{' <span class="chip">자동 추정</span>' if guide.fit.auto else ''}</h2>
  {_fit_html(guide.fit, guide.fit_reason)}
</section>"""
    stat_cells = []
    if guide.level:
        stat_cells.append(("레벨", str(guide.level)))
    if guide.tree_version:
        stat_cells.append(("트리", guide.tree_version))
    stat_cells.append(("스킬 세트", str(len(guide.skill_sets))))
    stat_cells.append(("장비 세트", str(len(guide.item_sets))))
    if guide.stats.get("TotalEHP"):
        stat_cells.append(("EHP", f"{guide.stats['TotalEHP']:,.0f}"))
    dps = max((guide.stats.get(k, 0.0) for k in ("CombinedDPS", "FullDPS", "TotalDotDPS", "TotalDPS")), default=0.0)
    if dps:
        stat_cells.append(("PoB DPS", f"{dps:,.0f}"))
    stats_html = "".join(
        f'<div class="stat"><div class="label">{_e(name)}</div><div class="value">{_e(value)}</div></div>'
        for name, value in stat_cells
    )
    keystones = ", ".join(ko_label(guide.game, "keystones", k) for k in guide.keystones) or "없음"
    warnings = "".join(f'<p class="warn">⚠ {_e(w)}</p>' for w in guide.warnings)
    badges = [
        f'<span class="chip">{_e(guide.game_label)}</span>',
        f'<span class="chip">{_e(guide.kind_label)}</span>' if guide.kind_label else "",
        f'<span class="chip">{_e(guide.ascendancy_label)}</span>' if guide.ascendancy_label else "",
        f'<span class="chip">{guide.level}레벨</span>' if guide.level else "",
        f'<span class="chip">트리 {_e(guide.tree_version)}</span>' if guide.tree_version else "",
    ]
    source_link = (
        f'<a class="btn" href="{_e(guide.source_url)}" target="_blank" rel="noopener">pobb.in 원본 열기</a>'
        if guide.source_url else '<span class="chip">pobb.in 링크 없음</span>'
    )
    code_section = ""
    if guide.has_code:
        code_section = f"""
<section class="card" id="code">
  <h2>PoB 가져오기 코드 <span class="chip">{len(guide.code):,}자</span></h2>
  <p style="color:#a9bcd0;margin-top:0">PoB → <strong>Import</strong> → <strong>Import Code</strong> 에 붙여넣으면 이 빌드가 그대로 열립니다.</p>
  <div class="actions" style="margin-bottom:10px">
    <button class="primary" onclick="copyPob()">PoB 코드 복사</button>
    <span id="toast" style="color:var(--green)"></span>
  </div>
  <textarea id="pob-code" readonly spellcheck="false">{_e(guide.code)}</textarea>
</section>"""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(guide.name)} — PoB 빌드 가이드</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<header class="hero">
  <div class="kicker">{APP_TITLE} v{__version__} · PoB 빌드 가이드</div>
  <h1>{_e(guide.name)}</h1>
  <div class="badges">{''.join(badges)}</div>
  <div class="actions">
    <button class="primary" onclick="copyPob()">PoB 코드 복사</button>
    {source_link}
    <button onclick="toggleAll(true)">전체 펼치기</button>
    <button onclick="toggleAll(false)">전체 접기</button>
    <button onclick="window.print()">인쇄 / PDF</button>
  </div>
  {warnings}
</header>
<nav class="toc">
  <a href="#overview">개요</a><a href="#patch">패치 영향</a><a href="#fit">적합도</a>
  <a href="#skills">스킬 세트</a><a href="#items">장비 세트</a><a href="#tree">트리</a>
  <a href="#notes">메모</a><a href="#code">PoB 코드</a>
</nav>
<main>
<section class="card" id="overview">
  <h2>개요</h2>
  <div class="grid">{stats_html}</div>
  <h3>직업 · 전직</h3>
  <p>{_e(guide.class_label)} / <strong>{_e(guide.ascendancy_label)}</strong></p>
  <h3>키스톤</h3><p>{_e(keystones)}</p>
  <h3>출처</h3>
  <p>{_e(guide.origin) or '—'}{(' · <a href="' + _e(guide.source_url) + '" target="_blank" rel="noopener">' + _e(guide.source_url) + '</a>') if guide.source_url else ''}</p>
  {f'<h3>메모</h3><p>{_e(guide.note)}</p>' if guide.note else ''}
</section>
<section class="card" id="patch">
  <h2>이번 패치노트 영향</h2>
  {_patch_html(guide.patch)}
</section>
{fit_block}
<section class="card" id="skills">
  <h2>스킬 세트 <span class="chip">{len(guide.skill_sets)}개</span></h2>
  {_skills_html(guide)}
</section>
<section class="card" id="items">
  <h2>장비 세트 <span class="chip">{len(guide.item_sets)}개</span></h2>
  {_items_html(guide)}
</section>
<section class="card" id="tree">
  <h2>패시브 트리 단계 <span class="chip">{len(guide.specs)}개</span></h2>
  {_specs_html(guide) or '<p style="color:#93a4b8">트리 단계 정보가 없습니다.</p>'}
</section>
<section class="card" id="notes">
  <h2>제작자 메모</h2>
  {_notes_html(guide)}
</section>
{code_section}
</main>
<footer>{APP_TITLE} v{__version__} · {guide.generated_at:%Y-%m-%d %H:%M} 생성 · 이 문서는 오프라인에서도 열립니다.</footer>
</div>
<script>{_COPY_JS}</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------

def default_guide_dir() -> Path:
    base = os.environ.get("POE_CHECKER_HOME")
    if base:
        return Path(base) / "guides"
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
        return root / "PoE-Patch-Starter-Checker" / "guides"
    return Path.home() / ".poe-patch-starter-checker" / "guides"


def safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", (text or "").strip()).strip("-")
    return cleaned[:80] or "guide"


def export_html(guide: Guide, path: str | Path | None = None) -> Path:
    """HTML 가이드를 저장하고 경로를 돌려준다."""
    target = Path(path) if path else default_guide_dir() / f"{safe_filename(guide.build_id or guide.name)}-guide.html"
    if target.is_dir():
        target = target / f"{safe_filename(guide.build_id or guide.name)}-guide.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(guide), encoding="utf-8")
    return target


def temp_guide_path(guide: Guide) -> Path:
    return Path(tempfile.gettempdir()) / f"PoE-Guide-{safe_filename(guide.build_id or guide.name)}.html"


def open_guide(path: str | Path) -> bool:
    target = Path(path)
    try:
        return bool(webbrowser.open(target.resolve().as_uri()))
    except Exception:  # noqa: BLE001
        return False
