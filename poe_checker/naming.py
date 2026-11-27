"""이름 정규화·별칭 처리.

PoB 는 젬 이름을 `nameSpec` 그대로 쓰고(예: `Scorching Ray of Immolation`,
`Greater Multiple Projectiles`), 패치노트는 기본 젬 이름이나 `... Support`
형태로 쓴다. 유니크도 3.30 의 `Foulborn ...` 변형 접두어가 붙는다.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from . import datafiles

_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "`": "'"})
_NON_WORD = re.compile(r"[^0-9a-z가-힣' ]+")

# PoB 안에서만 쓰이는 접두어(게임에는 없는 이름) 또는 3.30 변형 접두어
_STRIP_PREFIXES = ("foulborn ", "nerfed ")


def norm(text: str) -> str:
    """비교용 정규화: 소문자, 아포스트로피 통일, 구두점 제거, 공백 축약."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).lower()
    s = _NON_WORD.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def gem_key_set() -> frozenset:
    return datafiles.active_gem_keys() | datafiles.support_gem_keys()


@lru_cache(maxsize=8192)
def is_gem_name(name: str) -> bool:
    return norm(name) in gem_key_set()


@lru_cache(maxsize=8192)
def is_support_name(name: str) -> bool:
    return norm(name) in datafiles.support_gem_keys()


def name_keys(name: str, *, gem: bool | None = None) -> frozenset:
    """같은 대상을 가리킬 수 있는 이름 키 집합.

    - `Elemental Focus Support` → `elemental focus support`, `elemental focus`
    - `Scorching Ray of Immolation`(젬) → `..., scorching ray`
    - `Foulborn Doedre's Scorn` → `..., doedre's scorn`
    """
    base = norm(name)
    if not base:
        return frozenset()
    if gem is None:
        gem = is_gem_name(name)
    keys: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        if value:
            keys.add(value)

    add(base)
    for prefix in _STRIP_PREFIXES:
        if base.startswith(prefix):
            add(base[len(prefix):])
    # `... Support` 접미어 제거 (두 번까지: "Awakened X Support")
    for value in list(keys):
        if value.endswith(" support"):
            keys.add(value[: -len(" support")].strip())
    # 변형(transfigured) 젬: "X of Y" → 기본 젬 "X"
    # 단, 기본 이름 자체가 실제 젬일 때만 (예: Herald of Agony → Herald 는 젬이 아님)
    if gem:
        gem_keys = gem_key_set()
        for value in list(keys):
            if " of " in value:
                base = value.split(" of ", 1)[0]
                if base in gem_keys:
                    add(base)
    return frozenset(keys)


def keys_intersect(a: frozenset, b: frozenset) -> bool:
    return bool(a & b)


# ---------------------------------------------------------------------------
# 패치노트 한 줄에서 앞부분의 대상 이름을 찾기 위한 색인
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def known_entity_index() -> dict:
    """norm 이름 → (표시 이름, 종류). 긴 이름부터 매칭할 수 있게 정렬해서 쓴다."""
    index: dict[str, tuple[str, str]] = {}
    for name in datafiles.active_gems():
        index.setdefault(norm(name), (name, "gem"))
    for name in datafiles.support_gems():
        index.setdefault(norm(name), (name, "support"))
    for name in datafiles.keystone_names():
        index.setdefault(norm(name), (name, "keystone"))
    for name in datafiles.ascendancy_names():
        index.setdefault(norm(name), (name, "ascendancy"))
    return index


@lru_cache(maxsize=1)
def _known_keys_by_length() -> tuple[str, ...]:
    return tuple(sorted(known_entity_index(), key=len, reverse=True))


def find_leading_entity(line: str) -> tuple[str, str, str] | None:
    """줄 맨 앞에서 알려진 젬/키스톤/전직 이름을 찾는다.

    반환: (표시 이름, 남은 텍스트, 종류) 또는 None
    """
    text = line.strip().lstrip("-•*– \t")
    low = norm(text)
    if not low:
        return None
    for key in _known_keys_by_length():
        if low == key:
            display, kind = known_entity_index()[key]
            return display, "", kind
        if low.startswith(key + " "):
            remainder = text[len(key) + 1:] if len(text) > len(key) else ""
            display, kind = known_entity_index()[key]
            return display, remainder.strip(" :"), kind
    return None


def canonical_display(name: str) -> str:
    """가능하면 데이터에 있는 표기로 되돌린다."""
    key = norm(name)
    entry = known_entity_index().get(key)
    return entry[0] if entry else name.strip()
