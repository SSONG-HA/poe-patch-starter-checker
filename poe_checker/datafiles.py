"""패키지에 동봉된 3.30 게임 데이터 로더.

- gems_3_30.json          : PoB 3.30 Gems.lua 에서 추출한 젬 이름/태그(액티브·서포트)
- keystones_3_30.json     : PoB 3.30 tree.lua 에서 추출한 키스톤 노드 ID → 이름
- ascendancies_3_30.json  : 직업(클래스) → 전직(어센던시) 이름
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
BUILD_DIR = DATA_DIR / "builds"


def _load(name: str) -> dict:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


@lru_cache(maxsize=1)
def gems() -> dict:
    """{'actives': {name: [tags]}, 'supports': [name, ...]}"""
    data = _load("gems_3_30.json")
    data.setdefault("actives", {})
    data.setdefault("supports", [])
    return data


@lru_cache(maxsize=1)
def active_gems() -> dict:
    return gems()["actives"]


@lru_cache(maxsize=1)
def support_gems() -> frozenset:
    return frozenset(gems()["supports"])


@lru_cache(maxsize=1)
def keystones() -> dict:
    """node id(str) -> keystone name"""
    return _load("keystones_3_30.json")


@lru_cache(maxsize=1)
def keystone_names() -> frozenset:
    return frozenset(keystones().values())


@lru_cache(maxsize=1)
def ascendancies() -> dict:
    """class name -> [ascendancy names]"""
    return _load("ascendancies_3_30.json")


@lru_cache(maxsize=1)
def active_gem_keys() -> frozenset:
    from .naming import norm

    return frozenset(norm(name) for name in active_gems())


@lru_cache(maxsize=1)
def support_gem_keys() -> frozenset:
    from .naming import norm

    return frozenset(norm(name) for name in support_gems())


@lru_cache(maxsize=1)
def ascendancy_keys() -> frozenset:
    from .naming import norm

    return frozenset(norm(name) for name in ascendancy_names())


@lru_cache(maxsize=1)
def keystone_keys() -> frozenset:
    from .naming import norm

    return frozenset(norm(name) for name in keystone_names())


@lru_cache(maxsize=1)
def ascendancy_names() -> frozenset:
    names = set()
    for values in ascendancies().values():
        names.update(values)
    return frozenset(names)
