"""3.30(PoE1) / 0.5(PoE2) 데이터·한국어 이름 생성 스크립트 (개발용, 배포물 아님)."""
from __future__ import annotations

import html
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DATA = Path("poe_checker/data")
WORK = Path("work")


def fetch(url: str, timeout: float = 120.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# PoE2 — PoB-PoE2 데이터
# ---------------------------------------------------------------------------

def parse_lua_gems(text: str) -> dict:
    """Gems.lua → {'actives': {name: [tags]}, 'supports': [name]}"""
    actives: dict[str, list[str]] = {}
    supports: list[str] = []
    # 항목 단위로 자른다: [ "Metadata/..." ] = { ... },
    chunks = re.split(r'\n\t\["Metadata/Items/Ge', text)
    for chunk in chunks[1:]:
        name_m = re.search(r'^\s*name = "([^"]+)"', chunk, re.M)
        if not name_m:
            continue
        name = name_m.group(1)
        gem_type = re.search(r'^\s*gemType = "([^"]+)"', chunk, re.M)
        tags_block = re.search(r"tags = \{(.*?)\}", chunk, re.S)
        tags = []
        if tags_block:
            tags = re.findall(r"^\s*(\w+) = true", tags_block.group(1), re.M)
        if gem_type and gem_type.group(1) == "Support":
            if name not in supports:
                supports.append(name)
            continue
        if "grants_active_skill" not in tags:
            # 패시브형(오라 등)도 스킬이다 — gemType 이 Support 가 아니면 액티브로 둔다
            pass
        prev = actives.get(name)
        merged = sorted(set(tags) | set(prev or []))
        actives[name] = merged
    return {"actives": actives, "supports": sorted(supports)}


def parse_lua_tree(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """tree.lua → (keystone {id: name}, class → [ascendancy])"""
    keystones: dict[str, str] = {}
    for m in re.finditer(r"\[(\d+)\]=\{(.*?)\n\t\t\},", text, re.S):
        body = m.group(2)
        if "isKeystone=true" not in body.replace(" ", ""):
            continue
        name_m = re.search(r'name="([^"]+)"', body)
        if name_m:
            keystones[m.group(1)] = name_m.group(1)
    classes: dict[str, list[str]] = {}
    class_blocks = re.split(r"\n\t\t\[\d+\]=\{\n\t\t\tascendancies=\{", text)
    for block in class_blocks[1:]:
        asc_section, _, rest = block.partition("\n\t\t\t},\n\t\t\tbackground")
        asc = re.findall(r'\n\t\t\t\t\t+id="([^"]+)"', asc_section)
        name_m = re.search(r'\n\t\t\tname="([^"]+)"', rest)
        if not name_m or not asc:
            continue
        uniq: list[str] = []
        for a in asc:
            if a not in uniq:
                uniq.append(a)
        classes[name_m.group(1)] = uniq
    return keystones, classes


# ---------------------------------------------------------------------------
# poedb / poe2db 한국어 이름
# ---------------------------------------------------------------------------

def parse_gem_pairs(text: str) -> dict[str, str]:
    """Gem 색인 페이지 → {영문 이름: 표시 이름} (slug 대신 링크 텍스트 사용)"""
    out: dict[str, str] = {}
    for m in re.finditer(r'<a class="gem_[a-z]+"[^>]*href="/[a-z]{2}/([A-Za-z0-9_]+)">([^<]{1,80})</a>', text):
        slug, label = m.group(1), html.unescape(m.group(2)).strip()
        out.setdefault(slug, label)
    return out


def parse_unique_pairs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(
        r'<a class="UniqueItem"[^>]*href="/[a-z]{2}/([^"]+)">\s*<span class="uniqueName">([^<]+)</span>',
        text,
    ):
        slug, label = m.group(1), html.unescape(m.group(2)).strip()
        out.setdefault(slug, label)
    return out


def parse_passive_pairs(text: str) -> dict[str, str]:
    """키스톤 색인 → {노드 slug: 이름}. 영문/한국어 페이지를 slug 로 맞춘다."""
    out: dict[str, str] = {}
    for m in re.finditer(
        r'<a[^>]*href="(?:https://[a-z0-9.]+/)?(?:/[a-z]{2}/)?([A-Za-z0-9_]+)"[^>]*>([^<]{1,60})</a>',
        text,
    ):
        slug, label = m.group(1), html.unescape(m.group(2)).strip()
        out.setdefault(slug, label)
    return out


def parse_ascendancy_pairs(text: str) -> dict[str, str]:
    """전직 클래스 페이지 → {전직 slug: 이름} (figcaption 안의 링크만)"""
    out: dict[str, str] = {}
    for m in re.finditer(
        r'<figcaption>\s*<a[^>]*href="(?:https://[a-z0-9.]+)?/[a-z]{2}/([A-Za-z0-9_]+)"[^>]*>([^<]{1,60})</a>',
        text,
    ):
        slug, label = m.group(1), html.unescape(m.group(2)).strip()
        out.setdefault(slug, label)
    return out


def join_maps(en: dict[str, str], kr: dict[str, str]) -> dict[str, str]:
    out = {}
    for slug, name in en.items():
        korean = kr.get(slug)
        if korean and korean != slug and re.search(r"[가-힣]", korean):
            out[name] = korean
    return out


def main() -> None:
    poe2_gems = parse_lua_gems(fetch(
        "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/Data/Gems.lua"))
    keystones2, classes2 = parse_lua_tree((WORK / "poe2_tree.lua").read_text(encoding="utf-8"))
    print("poe2 actives", len(poe2_gems["actives"]), "supports", len(poe2_gems["supports"]))
    print("poe2 keystones", len(keystones2), "classes", classes2)

    (DATA / "gems_poe2.json").write_text(json.dumps(
        {"schema": 1, "game": "poe2", "version": "0.5",
         "source": "PathOfBuilding-PoE2 dev src/Data/Gems.lua",
         **poe2_gems}, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "keystones_poe2.json").write_text(json.dumps(
        keystones2, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "ascendancies_poe2.json").write_text(json.dumps(
        classes2, ensure_ascii=False, indent=1), encoding="utf-8")

    urls = {
        "p1_gem_en": "https://poedb.tw/us/Gem",
        "p1_gem_kr": "https://poedb.tw/kr/Gem",
        "p1_uniq_en": "https://poedb.tw/us/Unique_item",
        "p1_uniq_kr": "https://poedb.tw/kr/Unique_item",
        "p1_key_en": "https://poedb.tw/us/Keystone",
        "p1_key_kr": "https://poedb.tw/kr/Keystone",
        "p1_asc_en": "https://poedb.tw/us/Ascendancy_class",
        "p1_asc_kr": "https://poedb.tw/kr/Ascendancy_class",
        "p2_gem_en": "https://poe2db.tw/us/Gem",
        "p2_gem_kr": "https://poe2db.tw/kr/Gem",
        "p2_uniq_en": "https://poe2db.tw/us/Unique_item",
        "p2_uniq_kr": "https://poe2db.tw/kr/Unique_item",
        "p2_key_en": "https://poe2db.tw/us/Keystone",
        "p2_key_kr": "https://poe2db.tw/kr/Keystone",
        "p2_asc_en": "https://poe2db.tw/us/Ascendancy_class",
        "p2_asc_kr": "https://poe2db.tw/kr/Ascendancy_class",
    }
    pages: dict[str, str] = {}
    todo = {}
    for key, url in urls.items():
        cached = WORK / f"page_{key}.html"
        if cached.exists():
            pages[key] = cached.read_text(encoding="utf-8")
        else:
            todo[key] = url
    with ThreadPoolExecutor(max_workers=6) as pool:
        for key, body in zip(todo, pool.map(fetch, todo.values())):
            pages[key] = body
            print("fetched", key, len(body))
            (WORK / f"page_{key}.html").write_text(body, encoding="utf-8")

    names = {}
    for game, prefix in (("poe1", "p1"), ("poe2", "p2")):
        names[game] = {
            "gems": join_maps(parse_gem_pairs(pages[f"{prefix}_gem_en"]),
                              parse_gem_pairs(pages[f"{prefix}_gem_kr"])),
            "uniques": join_maps(parse_unique_pairs(pages[f"{prefix}_uniq_en"]),
                                 parse_unique_pairs(pages[f"{prefix}_uniq_kr"])),
            "keystones": join_maps(parse_passive_pairs(pages[f"{prefix}_key_en"]),
                                   parse_passive_pairs(pages[f"{prefix}_key_kr"])),
            "ascendancies": join_maps(parse_ascendancy_pairs(pages[f"{prefix}_asc_en"]),
                                      parse_ascendancy_pairs(pages[f"{prefix}_asc_kr"])),
        }
        print(game, {k: len(v) for k, v in names[game].items()})
    (DATA / "names_kr.json").write_text(json.dumps(
        {"schema": 1, "note": "poedb.tw/kr · poe2db.tw/kr 색인에서 영문↔한국어 이름 대조",
         **names}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
