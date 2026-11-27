"""패키지에 동봉된 게임 데이터 로더.

- gems_3_30.json / gems_poe2.json          : PoB Gems.lua 에서 뽑은 젬 이름·태그
- keystones_3_30.json / keystones_poe2.json: 트리 키스톤 노드 ID → 이름
- ascendancies_3_30.json / ascendancies_poe2.json : 직업 → 전직 이름
- names_kr.json                            : poedb/poe2db 색인에서 맞춘 영문↔한국어 이름
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
BUILD_DIR = DATA_DIR / "builds"

GAME_POE1 = "poe1"
GAME_POE2 = "poe2"
GAMES = (GAME_POE1, GAME_POE2)
GAME_LABELS = {GAME_POE1: "PoE1", GAME_POE2: "PoE2"}
GAME_VERSION_LABELS = {GAME_POE1: "PoE1 3.30", GAME_POE2: "PoE2 0.5"}

_GEM_FILES = {GAME_POE1: "gems_3_30.json", GAME_POE2: "gems_poe2.json"}
_KEYSTONE_FILES = {GAME_POE1: "keystones_3_30.json", GAME_POE2: "keystones_poe2.json"}
_ASC_FILES = {GAME_POE1: "ascendancies_3_30.json", GAME_POE2: "ascendancies_poe2.json"}


def normalize_game(game: str | None) -> str:
    value = (game or "").strip().lower()
    if value in ("poe2", "poe 2", "pathofexile2", "2"):
        return GAME_POE2
    return GAME_POE1


def _load(name: str) -> dict:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


@lru_cache(maxsize=4)
def gems(game: str = GAME_POE1) -> dict:
    """{'actives': {name: [tags]}, 'supports': [name, ...]}"""
    data = _load(_GEM_FILES[normalize_game(game)])
    data.setdefault("actives", {})
    data.setdefault("supports", [])
    return data


@lru_cache(maxsize=4)
def active_gems(game: str = GAME_POE1) -> dict:
    return gems(game)["actives"]


@lru_cache(maxsize=4)
def support_gems(game: str = GAME_POE1) -> frozenset:
    return frozenset(gems(game)["supports"])


@lru_cache(maxsize=4)
def keystones(game: str = GAME_POE1) -> dict:
    """node id(str) -> keystone name"""
    return _load(_KEYSTONE_FILES[normalize_game(game)])


@lru_cache(maxsize=4)
def keystone_names(game: str = GAME_POE1) -> frozenset:
    return frozenset(keystones(game).values())


@lru_cache(maxsize=4)
def ascendancies(game: str = GAME_POE1) -> dict:
    """class name -> [ascendancy names]"""
    return _load(_ASC_FILES[normalize_game(game)])


def _norm_keys(names) -> frozenset:
    from .naming import norm

    return frozenset(norm(name) for name in names)


@lru_cache(maxsize=4)
def active_gem_keys(game: str = GAME_POE1) -> frozenset:
    return _norm_keys(active_gems(game))


@lru_cache(maxsize=4)
def support_gem_keys(game: str = GAME_POE1) -> frozenset:
    return _norm_keys(support_gems(game))


@lru_cache(maxsize=4)
def ascendancy_keys(game: str = GAME_POE1) -> frozenset:
    return _norm_keys(ascendancy_names(game))


@lru_cache(maxsize=4)
def keystone_keys(game: str = GAME_POE1) -> frozenset:
    return _norm_keys(keystone_names(game))


@lru_cache(maxsize=4)
def ascendancy_names(game: str = GAME_POE1) -> frozenset:
    names = set()
    for values in ascendancies(game).values():
        names.update(values)
    return frozenset(names)


# -- 두 게임 합집합(패치노트 낱말이 젬·키스톤인지 판별할 때) ------------------

@lru_cache(maxsize=1)
def all_active_gem_keys() -> frozenset:
    return frozenset().union(*(active_gem_keys(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_support_gem_keys() -> frozenset:
    return frozenset().union(*(support_gem_keys(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_keystone_keys() -> frozenset:
    return frozenset().union(*(keystone_keys(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_ascendancy_keys() -> frozenset:
    return frozenset().union(*(ascendancy_keys(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_keystone_names() -> frozenset:
    return frozenset().union(*(keystone_names(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_ascendancy_names() -> frozenset:
    return frozenset().union(*(ascendancy_names(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_active_gems() -> dict:
    out: dict = {}
    for game in GAMES:
        for name, tags in active_gems(game).items():
            out.setdefault(name, tags)
    return out


@lru_cache(maxsize=1)
def all_support_gems() -> frozenset:
    return frozenset().union(*(support_gems(game) for game in GAMES))


@lru_cache(maxsize=1)
def all_keystones() -> dict:
    out: dict = {}
    for game in GAMES:
        for node, name in keystones(game).items():
            out.setdefault(node, name)
    return out


@lru_cache(maxsize=1)
def all_ascendancies() -> dict:
    out: dict = {}
    for game in GAMES:
        for cls, asc in ascendancies(game).items():
            out.setdefault(cls, list(asc))
    return out


# -- 한국어 이름 -------------------------------------------------------------

@lru_cache(maxsize=1)
def korean_names() -> dict:
    path = DATA_DIR / "names_kr.json"
    if not path.exists():
        return {GAME_POE1: {}, GAME_POE2: {}}
    return _load("names_kr.json")


@lru_cache(maxsize=1)
def all_unique_names() -> frozenset:
    """동봉 한국어 이름표에 있는 유니크 아이템 영문 이름(양 게임)."""
    names = set()
    for game in GAMES:
        table = korean_names().get(game, {}).get("uniques", {})
        names.update(table.keys())
    return frozenset(names)


@lru_cache(maxsize=1)
def all_unique_names_keys() -> frozenset:
    from .naming import norm

    return frozenset(norm(name) for name in all_unique_names())


def korean_name(game: str, section: str, name: str) -> str:
    """'정의의 화염' 처럼 한국어 표기를 돌려준다. 없으면 빈 문자열."""
    data = korean_names().get(normalize_game(game), {})
    table = data.get(section, {}) if isinstance(data, dict) else {}
    return table.get(name, "")
