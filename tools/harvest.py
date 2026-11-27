"""pobb.in 코드 수집·해석 (개발용)."""
from __future__ import annotations

import base64
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CACHE = Path("work/codes")
CACHE.mkdir(parents=True, exist_ok=True)


def fetch_code(code: str, *, delay: float = 5.0) -> str:
    import time

    path = CACHE / f"{code}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    last: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"https://pobb.in/{code}/raw", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as response:
                body = response.read().decode("utf-8", "replace").strip()
            path.write_text(body, encoding="utf-8")
            time.sleep(delay)
            return body
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(delay * (attempt + 2))
    raise last  # type: ignore[misc]


def decode(code: str) -> str:
    token = fetch_code(code)
    return zlib.decompress(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))).decode(
        "utf-8", "replace")


def summarize(code: str) -> dict:
    xml = decode(code)
    root = ET.fromstring(xml)
    build = root.find("Build")
    out = {
        "code": code,
        "root": root.tag,
        "class": build.get("className"),
        "asc": build.get("ascendClassName"),
        "level": build.get("level"),
        "main_group": build.get("mainSocketGroup"),
    }
    spec = root.find("./Tree/Spec")
    out["tree"] = spec.get("treeVersion") if spec is not None else ""
    groups = []
    skills = root.find("Skills")
    active = skills.get("activeSkillSet") if skills is not None else None
    skill_set = None
    if skills is not None:
        for candidate in skills.findall("SkillSet"):
            if candidate.get("id") == active:
                skill_set = candidate
    if skill_set is not None:
        for skill in skill_set.findall("Skill"):
            if skill.get("enabled", "true") == "false":
                continue
            gems = [g.get("nameSpec") for g in skill.findall("Gem") if g.get("enabled", "true") != "false"]
            if gems:
                groups.append(gems)
    out["groups"] = groups[:14]
    uniques = []
    items = root.find("Items")
    if items is not None:
        for item in items.findall("Item"):
            rows = [r.strip() for r in (item.text or "").splitlines() if r.strip()]
            if rows and rows[0].upper().startswith("RARITY:") and "UNIQUE" in rows[0].upper():
                if len(rows) > 1:
                    uniques.append(rows[1])
    out["uniques"] = uniques
    return out


if __name__ == "__main__":
    for code in sys.argv[1:]:
        try:
            print(json.dumps(summarize(code), ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"code": code, "error": str(exc)}, ensure_ascii=False))
