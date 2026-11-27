"""`data/starter_catalog.json` 생성기.

새 시즌 스타터를 추가했을 때:

    python tools/gen_catalog.py            # 카탈로그 다시 만들기
    git add poe_checker/data/starter_catalog.json poe_checker/data/starters.json poe_checker/data/builds
    git commit -m "..." && git push

앱의 「스타터 최신화」는 이 카탈로그(raw URL)를 받아 로컬 라이브러리에 병합한다.
`pob_code_url` 은 `base_url` 기준 상대 경로이고, `sha256` 은 본문(코드) 내용의 해시다
(같으면 다시 내려받지 않는다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "poe_checker" / "data"
STARTED = DATA / "starters.json"
TARGET = DATA / "starter_catalog.json"

DEFAULT_BASE = (
    "https://raw.githubusercontent.com/SSONG-HA/poe-patch-starter-checker/"
    "main/poe_checker/data/"
)


def build_catalog(starters: dict, *, updated: str, base_url: str) -> dict:
    builds = []
    for row in starters.get("builds", []):
        entry = {key: value for key, value in row.items() if key not in ("code_file", "code")}
        code_file = row.get("code_file") or ""
        if code_file:
            payload_path = DATA / code_file
            payload = payload_path.read_text(encoding="utf-8") if payload_path.exists() else ""
            entry["pob_code_url"] = code_file
            entry["sha256"] = hashlib.sha256(payload.strip().encode("utf-8")).hexdigest()
        elif row.get("code"):
            entry["pob_code"] = row["code"]
            entry["sha256"] = hashlib.sha256(row["code"].strip().encode("utf-8")).hexdigest()
        if (row.get("source") or "").startswith("http"):
            entry["pobb_in"] = row["source"]
        builds.append(entry)
    return {
        "schema": 1,
        "updated": updated,
        "note": (
            "PoE 스타터 카탈로그 — 앱의 「스타터 최신화」가 이 파일을 받아 라이브러리에 "
            "안전하게 병합합니다. 빌드 본문은 pob_code / pob_xml / pob_code_url / pobb_in 중 "
            "하나로 줄 수 있습니다."
        ),
        "base_url": base_url,
        "builds": builds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="스타터 카탈로그 생성")
    parser.add_argument("--starters", default=str(STARTED))
    parser.add_argument("--out", default=str(TARGET))
    parser.add_argument("--updated", default="", help="카탈로그 기준일(기본: starters.json 의 updated)")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()

    starters = json.loads(Path(args.starters).read_text(encoding="utf-8"))
    updated = args.updated or starters.get("updated") or ""
    catalog = build_catalog(starters, updated=updated, base_url=args.base_url)
    Path(args.out).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(catalog['builds'])}개 빌드 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
