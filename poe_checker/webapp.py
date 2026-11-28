"""내장 로컬 웹 대시보드 — HTTP 서버 + JSON API.

tkinter 대신 브라우저(또는 pywebview 창)에서 그리는 UI 를 위해,
127.0.0.1 의 임시 포트에 스레드 HTTP 서버를 띄우고 `poe_checker` 의
핵심 모듈(news·patchnotes·analysis·buffs·recommend·guide·library·catalog·
pob·report·datafiles)을 그대로 API 로 노출한다.

pywebview 는 여기서 import 하지 않는다(gui.py 가 담당). CLI·pytest 는
pywebview 없이 이 모듈만으로 동작한다.
"""
from __future__ import annotations

import json
import math
import re
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (
    APP_NAME,
    APP_TITLE,
    __version__,
    analysis,
    catalog,
    datafiles,
    guide as guide_mod,
    library as library_mod,
    live_sync,
    news,
    patchnotes,
    pob,
    recommend,
    report,
)

WEB_DIR = datafiles.DATA_DIR / "web"
_TOKEN_PLACEHOLDER = "__APP_TOKEN__"
_VERSION_PLACEHOLDER = "__APP_VERSION__"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "favicon.svg": "image/svg+xml",
}
MAX_BODY = 32 * 1024 * 1024
NEWS_TTL = 600.0

# 스킬 젬 소켓 도트 색
_SOCKET_COLORS = {"strength": "red", "dexterity": "green", "intelligence": "blue"}

# 가이드 스킬/장비 세트 → 단계(액트·초반 / 맵핑 / 엔드게임)
_STAGE_ORDER = ("act", "mapping", "endgame", "basic")
_STAGE_LABELS = {
    "act": "액트·초반",
    "mapping": "맵핑",
    "endgame": "엔드게임",
    "basic": "기본 구성",
}
_LEVEL_RE = re.compile(r"(?:lvl|level|레벨)\s*(\d{1,3})", re.I)
_ACT_WORDS = ("act ", "leveling", "levelling", "early", "starter", "스타터", "초반", "액트")
_END_WORDS = ("endgame", "end game", "min-max", "minmax", "cluster", "엔드", "최종")


class ApiError(RuntimeError):
    """API 400 응답으로 돌려줄 사용자 오류."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# 표시용 페이로드
# ---------------------------------------------------------------------------

def _korean(game: str, section: str, name: str) -> str:
    try:
        label = datafiles.korean_name(game, section, name)
    except Exception:  # pragma: no cover - 데이터 누락 방어
        return ""
    return label if label and label != name else ""


_TAG_SECTIONS = (
    ("skill", "주력 스킬", "gems"),
    ("support", "서포트 젬", "gems"),
    ("unique", "유니크", "uniques"),
    ("ascendancy", "전직", "ascendancies"),
    ("keystone", "키스톤", "keystones"),
)


def _socket_color(tags) -> str:
    for key, color in _SOCKET_COLORS.items():
        if key in tags:
            return color
    return "white"


def stage_for(title: str, *, index: int = 0, total: int = 1) -> str:
    """스킬/장비 세트 제목으로 진행 단계를 추정한다."""
    low = (title or "").lower()
    if any(word in low for word in _ACT_WORDS):
        return "act"
    level = _LEVEL_RE.search(low)
    if level:
        value = int(level.group(1))
        if value < 70:
            return "act"
        if value < 95:
            return "mapping"
        return "endgame"
    if any(word in low for word in _END_WORDS):
        return "endgame"
    if total <= 1:
        return "basic"
    if index == 0:
        return "mapping"
    return "endgame"


def _hit_score(hit) -> float:
    if hit.is_nerf:
        worst = hit.entry.signal.worst_delta
        return float(worst.benefit_pct) if worst else 0.0
    return float(hit.entry.signal.score or 0.0)


def _hit_payload(hit, game: str = datafiles.GAME_POE1) -> dict:
    section = {
        "main_skill": "gems",
        "secondary_skill": "gems",
        "support": "gems",
        "unique": "uniques",
        "ascendancy": "ascendancies",
        "keystone": "keystones",
    }.get(hit.entity_kind, "gems")
    direction_label = {
        "buff": "상향",
        "nerf": "너프",
        "mixed": "혼합 조정",
        "neutral": "변경",
    }.get(hit.direction, hit.direction)
    return {
        "kind": hit.kind_label,
        "entity_kind": hit.entity_kind,
        "name": hit.entity_name,
        "korean": _korean(game, section, hit.entity_name),
        "alias": hit.alias,
        "direction": hit.direction,
        "direction_label": direction_label,
        "severity": hit.severity,
        "core": hit.core,
        "weight": hit.weight,
        "score": round(_finite(_hit_score(hit)), 2),
        "entry": hit.entry.name,
        "entry_kind": hit.entry.kind,
        "describe": hit.describe(),
        "lines": hit.entry.display_lines(limit=10),
    }


def _verdict_tags(verdict) -> list[dict]:
    profile = verdict.profile
    game = profile.game
    affected: dict[str, str] = {}
    for hit in verdict.hits:
        for key in (hit.entity_name, hit.alias):
            if key:
                affected[key.strip().lower()] = hit.direction
    tags: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, label: str, name: str) -> None:
        if not name:
            return
        key = (kind, name.strip().lower())
        if key in seen:
            return
        seen.add(key)
        tags.append(
            {
                "type": kind,
                "label": label,
                "name": name,
                "korean": _korean(game, "gems" if kind in ("skill", "support") else
                                 "uniques" if kind == "unique" else
                                 "ascendancies" if kind == "ascendancy" else "keystones", name),
                "affected": affected.get(name.strip().lower(), ""),
            }
        )

    for name in profile.main_skill_names:
        add("skill", "주력 스킬", name)
    for name in profile.support_names:
        add("support", "서포트 젬", name)
    for name in profile.uniques:
        add("unique", "유니크", name)
    if profile.ascendancy:
        add("ascendancy", "전직", profile.ascendancy)
    for name in profile.keystones:
        add("keystone", "키스톤", name)
    return tags


def _source_label(verdict) -> str:
    bits = [x for x in (verdict.kind_label, verdict.origin) if x]
    if verdict.profile.tree_version:
        bits.append(f"트리 {verdict.profile.tree_version}")
    return " · ".join(bits)


def verdict_payload(verdict) -> dict:
    profile = verdict.profile
    return {
        "id": verdict.build_id,
        "name": verdict.build_name,
        "verdict": verdict.verdict,
        "label": verdict.label,
        "headline": verdict.headline(),
        "kind": verdict.kind_label,
        "origin": verdict.origin,
        "source_label": _source_label(verdict),
        "class": profile.class_name,
        "ascendancy": profile.ascendancy,
        "level": profile.level,
        "tree": profile.tree_version,
        "game": profile.game,
        "error": verdict.error,
        "stats": {
            "dps": _rounded(profile.dps),
            "dot_dps": _rounded(profile.dot_dps),
            "ehp": _rounded(profile.ehp),
            "life": _rounded(profile.stats.get("Life", 0.0)),
            "es": _rounded(profile.stats.get("EnergyShield", 0.0)),
            "armour": _rounded(profile.stats.get("Armour", 0.0)),
        },
        "tags": _verdict_tags(verdict),
        "hits": [_hit_payload(hit, profile.game) for hit in verdict.hits],
        "nerfs": len(verdict.nerf_hits),
        "buffs": len(verdict.buff_hits),
        "custom": False,
    }


def buff_payload(cand) -> dict:
    game = datafiles.GAME_POE1
    try:
        game = datafiles.normalize_game(getattr(cand.entry, "game", "") or datafiles.GAME_POE1)
    except Exception:
        game = datafiles.GAME_POE1
    return {
        "name": cand.name,
        "korean": _korean(game, "gems", cand.name) or _korean(game, "uniques", cand.name),
        "kind": cand.kind_label,
        "direction": cand.entry.direction,
        "direction_label": cand.direction_label,
        "score": round(_finite(cand.score), 2),
        "total": round(_finite(cand.total), 2),
        "occurrences": cand.occurrences,
        "seeds": list(cand.seeds),
        "qualitative": cand.qualitative,
        "poedb": cand.poedb_url(),
        "ninja": cand.ninja_url(),
        "evidence": cand.evidence(limit=6),
        "lines": cand.entry.display_lines(limit=12),
        "mixed": cand.entry.direction == "mixed",
        "describe": cand.describe(),
    }


def _stage_sets(sets) -> list[dict]:
    out = []
    total = len(sets)
    for index, item in enumerate(sets):
        data = item.to_dict()
        data["stage"] = stage_for(getattr(item, "title", ""), index=index, total=total)
        data["linked_ids"] = list(getattr(item, "linked_ids", []))
        out.append(data)
    return out


def _stage_groups(stage_sets: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in stage_sets:
        groups.setdefault(row["stage"], []).append(row)
    out = []
    for key in _STAGE_ORDER:
        if key not in groups:
            continue
        out.append({"key": key, "label": _STAGE_LABELS[key], "sets": groups.pop(key)})
    for key, rows in groups.items():
        out.append({"key": key, "label": _STAGE_LABELS.get(key, key), "sets": rows})
    return out


def guide_payload(made: guide_mod.Guide) -> dict:
    data = made.to_dict()
    data["code"] = made.code
    data["code_length"] = len(made.code)
    data["headline"] = made.headline()
    data["notes"] = made.notes[:8000]
    data["notes_blocks"] = [{"kind": kind, "text": text} for kind, text in made.notes_blocks]
    skill_sets = _stage_sets(made.skill_sets)
    item_sets = _stage_sets(made.item_sets)
    item_by_id = {row["id"]: row for row in item_sets}
    for row in skill_sets:
        # 색상별 소켓 도트 + 한국어 병기
        for link in row.get("links", []):
            for gem in link.get("gems", []):
                gem["color"] = _socket_color(gem.get("tags") or ())
        source = next((item_by_id[sid] for sid in row.get("linked_ids", []) if sid in item_by_id), None)
        row["linked_items"] = source["id"] if source else (item_sets[0]["id"] if len(item_sets) == 1 and item_sets else "")
    data["skill_sets"] = skill_sets
    data["item_sets"] = item_sets
    data["stages"] = _stage_groups(skill_sets)
    data["stats"] = {
        "dps": _rounded(made.stats.get("FullDPS") or made.stats.get("CombinedDPS") or made.stats.get("TotalDPS", 0.0)),
        "dot_dps": _rounded(made.stats.get("TotalDotDPS", 0.0)),
        "ehp": _rounded(made.stats.get("TotalEHP", 0.0)),
        "life": _rounded(made.stats.get("Life", 0.0)),
        "armour": _rounded(made.stats.get("Armour", 0.0)),
    }
    return data


# ---------------------------------------------------------------------------
# 앱 상태
# ---------------------------------------------------------------------------

def _load_library_safely() -> library_mod.BuildLibrary:
    """라이브러리 JSON 이 깨졌어도 앱이 죽지 않게 한다(원본은 .bak 로 보존)."""
    try:
        return library_mod.BuildLibrary.load()
    except library_mod.LibraryError:
        path = library_mod.default_library_path()
        try:
            if path.exists():
                path.replace(path.with_suffix(".json.corrupt"))
        except OSError:
            pass
        return library_mod.BuildLibrary.load()


@dataclass
class ServerHandle:
    httpd: ThreadingHTTPServer
    url: str
    state: "AppState"
    token: str
    thread: threading.Thread | None = None

    def shutdown(self) -> None:
        try:
            self.httpd.shutdown()
        finally:
            self.httpd.server_close()


class AppState:
    """UI 가 쓰는 단일 상태(라이브러리·현재 결과·패치노트 피드)."""

    def __init__(self, library: library_mod.BuildLibrary | None = None):
        self.library = library if library is not None else _load_library_safely()
        self.game = datafiles.GAME_POE1
        self.result: analysis.AnalysisResult | None = None
        self.feed: news.NewsFeed | None = None
        self.feed_at: float = 0.0
        self.feed_error = ""
        self.sync_info: dict = {
            "catalog": catalog.CATALOG_URL,
            "updated": (getattr(self.library, "_sync_meta", None) or {}).get("updated", ""),
            "last_sync": "",
            "saved": False,
            "live": {},
        }
        self.lock = threading.RLock()

    # -- 공통 -------------------------------------------------------------
    def set_game(self, game: str) -> str:
        self.game = datafiles.normalize_game(game)
        return self.game

    def _library_counts(self) -> dict:
        rows = self.library.builds
        return {
            "total": len(rows),
            "poe1": len(self.library.builds_for(datafiles.GAME_POE1)),
            "poe2": len(self.library.builds_for(datafiles.GAME_POE2)),
            "custom": len([b for b in rows if b.kind == "custom"]),
        }

    def _result_summary(self) -> dict | None:
        result = self.result
        if result is None:
            return None
        return {
            "game": result.game,
            "game_label": result.game_label,
            "title": result.notes.title,
            "source": result.source_label,
            "version_hint": result.version_hint,
            "generated_at": result.generated_at.isoformat(timespec="seconds"),
            "entry_count": result.entry_count,
            "warnings": list(result.warnings),
            "kpi": {
                "green": len(result.green),
                "yellow": len(result.yellow),
                "red": len(result.red),
                "buffs": len(result.filtered_buffs(top=999, min_buff=0.0)),
                "total": len(result.verdicts),
            },
        }

    def state(self) -> dict:
        with self.lock:
            return {
                "app": {
                    "name": APP_NAME,
                    "title": APP_TITLE,
                    "version": __version__,
                },
                "games": [
                    {
                        "key": game,
                        "label": datafiles.GAME_VERSION_LABELS[game],
                        "short": "PoE 1" if game == datafiles.GAME_POE1 else "PoE 2",
                        "name": datafiles.GAME_LABELS[game],
                    }
                    for game in datafiles.GAMES
                ],
                "game": self.game,
                "library": {
                    "path": str(self.library.path),
                    "counts": self._library_counts(),
                },
                "sync": dict(self.sync_info),
                "result": self._result_summary(),
            }

    # -- 빌드 -------------------------------------------------------------
    def builds(self, game: str | None = None) -> dict:
        target = datafiles.normalize_game(game) if game else self.game
        custom_ids = {b.id for b in self.library.builds if b.kind == "custom"}
        mine_ids = {b.id for b in self.library.builds if b.kind in ("custom", "character")}
        rows = []
        for row in self.library.rows(target):
            row = dict(row)
            row["custom"] = row["id"] in custom_ids
            row["mine"] = row["id"] in mine_ids
            entry = self.library.get(row["id"])
            row["origin"] = entry.origin if entry else ""
            row["note"] = entry.note if entry else ""
            row["source"] = entry.source if entry else ""
            row["has_code"] = bool(entry and entry.code)
            rows.append(row)
        builtin = 0
        bundled = self.library._read_bundled() if hasattr(self.library, "_read_bundled") else None
        if bundled:
            builtin = len([b for b in bundled.get("builds", []) if datafiles.normalize_game(b.get("game")) == target])
        return {
            "game": target,
            "builds": rows,
            "count": len(rows),
            "builtin": builtin,
            "custom": len([r for r in rows if r["custom"]]),
            "library_path": str(self.library.path),
        }

    def add_build(self, source: str, *, name: str = "", game: str | None = None,
                  kind: str = "custom") -> dict:
        source = (source or "").strip()
        if not source:
            raise ApiError("PoB 코드나 pobb.in 주소를 입력해 주세요.")
        with self.lock:
            try:
                entry = self.library.add(source, name=name, kind=kind, game=game)
            except (pob.PobError, library_mod.LibraryError) as exc:
                raise ApiError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - 네트워크·디코딩 오류
                raise ApiError(f"빌드를 추가하지 못했습니다: {exc}") from exc
            self.game = datafiles.normalize_game(entry.game)
            # 추가한 빌드가 바로 분석 결과에 반영되도록 캐시를 비운다.
            self.result = None
        return {
            "id": entry.id,
            "name": entry.name,
            "game": entry.game,
            "kind": entry.kind_label,
        }

    def remove_build(self, build_id: str) -> dict:
        build_id = (build_id or "").strip()
        if not build_id:
            raise ApiError("삭제할 빌드를 지정해 주세요.")
        with self.lock:
            build = self.library.get(build_id)
            if build is None:
                raise ApiError("라이브러리에 없는 빌드입니다.", status=404)
            name = build.name
            self.library.remove(build_id)
            if self.result is not None:
                self.result.verdicts = [v for v in self.result.verdicts if v.build_id != build_id]
                if self.result.recommendations is not None:
                    self.result.recommendations = recommend.build_board(self.result, self.library)
        return {"id": build_id, "name": name, "removed": True}

    # -- 패치노트 ----------------------------------------------------------
    def news(self, *, game: str | None = None, refresh: bool = False) -> dict:
        target = datafiles.normalize_game(game) if game else self.game
        with self.lock:
            stale = (time.time() - self.feed_at) > NEWS_TTL
            if refresh or self.feed is None or stale:
                try:
                    self.feed = news.fetch_news()
                    self.feed_error = ""
                except Exception as exc:  # noqa: BLE001
                    self.feed_error = str(exc)
                    if self.feed is None:
                        raise ApiError(f"패치노트 목록을 가져오지 못했습니다: {exc}", status=502) from exc
                self.feed_at = time.time()
            feed = self.feed
        assert feed is not None
        refs = feed.filtered(game=target)
        return {
            "game": target,
            "refs": [
                {
                    "title": ref.title,
                    "url": ref.url,
                    "game": ref.game,
                    "game_label": ref.game_label,
                    "date": ref.date,
                    "display": ref.display(),
                    "is_patch": ref.is_patch,
                    "source": ref.source,
                }
                for ref in refs
            ],
            "counts": feed.counts(),
            "errors": list(feed.errors),
            "error": self.feed_error,
        }

    def load_patch_text(self, url: str) -> dict:
        url = (url or "").strip()
        if not url:
            raise ApiError("패치노트 주소를 입력해 주세요.")
        try:
            text, title = patchnotes.fetch_patch_text(url)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"패치노트를 불러오지 못했습니다: {exc}", status=502) from exc
        return {"url": url, "title": title, "text": text, "chars": len(text)}

    def load_patch_file(self, path: str) -> dict:
        raw = (path or "").strip()
        if not raw:
            raise ApiError("패치노트 파일 경로가 없습니다.")
        try:
            text = patchnotes.load_patch_file(raw)
        except OSError as exc:
            raise ApiError(f"파일을 읽지 못했습니다: {exc}") from exc
        return {"path": raw, "title": Path(raw).name, "text": text, "chars": len(text)}

    # -- 분석 -------------------------------------------------------------
    def analyze(self, payload: dict) -> dict:
        game = datafiles.normalize_game(payload.get("game") or self.game)
        text = (payload.get("text") or "").strip()
        url = (payload.get("url") or "").strip()
        try:
            top = max(1, min(100, int(payload.get("top") or 15)))
            min_buff = max(0.0, min(100.0, float(payload.get("min_buff") or 3.0)))
        except (TypeError, ValueError) as exc:
            raise ApiError("표시 개수·최소 상향률 값이 올바르지 않습니다.") from exc
        if not text and not url:
            raise ApiError("패치노트를 선택하거나 본문을 붙여넣어 주세요.")
        # 내려받기·파싱은 락 밖에서(분석 중 다른 API 응답이 막히지 않게).
        try:
            if text:
                notes = patchnotes.parse_patch_notes(text, source="붙여넣은 텍스트", game=game)
            else:
                body, title = patchnotes.fetch_patch_text(url)
                notes = patchnotes.parse_patch_notes(body, title=title, source=url, game=game)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"패치노트를 읽지 못했습니다: {exc}", status=502) from exc
        with self.lock:
            try:
                result = analysis.analyze(
                    self.library, notes, top=top, min_buff=min_buff, game=game
                )
            except Exception as exc:  # noqa: BLE001
                raise ApiError(f"검사 중 오류: {exc}", status=500) from exc
            self.result = result
            self.game = game
            return self.result_payload()

    def result_payload(self) -> dict:
        with self.lock:
            result = self.result
            if result is None:
                return {"result": None, "summary": None}
            custom_ids = {b.id for b in self.library.builds if b.kind == "custom"}
            mine_ids = {b.id for b in self.library.builds if b.kind in ("custom", "character")}
            verdicts = [verdict_payload(v) for v in result.verdicts]
            for row in verdicts:
                row["custom"] = row["id"] in custom_ids
                row["mine"] = row["id"] in mine_ids
            buffs = [buff_payload(c) for c in result.filtered_buffs(top=999, min_buff=0.0)]
            board = result.recommendations
            rec_entries = [entry.to_dict() for entry in board.entries] if board else []
            categories = {}
            if board is not None:
                for key in recommend.CATEGORY_ORDER:
                    categories[key] = {
                        "label": recommend.CATEGORY_LABELS[key],
                        "rows": [entry.to_dict() for entry in board.top(key, 12)],
                    }
            return {
                "result": {
                    "game": result.game,
                    "game_label": result.game_label,
                    "title": result.notes.title,
                    "source": result.source_label,
                    "version_hint": result.version_hint,
                    "generated_at": result.generated_at.isoformat(timespec="seconds"),
                    "entry_count": result.entry_count,
                    "warnings": list(result.warnings),
                    "top": result.top,
                    "min_buff": result.min_buff,
                    "kpi": self._result_summary()["kpi"],  # type: ignore[index]
                    "verdicts": verdicts,
                    "buffs": buffs,
                    "recommend": {"categories": categories, "entries": rec_entries},
                },
                "summary": self._result_summary(),
            }

    def verdicts(self, *, game: str | None = None, filter_: str = "all", q: str = "") -> dict:
        with self.lock:
            result = self.result
            if result is None:
                return {"verdicts": [], "game": None, "updated": ""}
            game = result.game
            rows = [verdict_payload(v) for v in result.verdicts]
        custom = {b.id for b in self.library.builds if b.kind == "custom"}
        mine = {b.id for b in self.library.builds if b.kind in ("custom", "character")}
        for row in rows:
            row["custom"] = row["id"] in custom
            row["mine"] = row["id"] in mine
        needle = (q or "").strip().lower()
        if needle:
            rows = [
                row
                for row in rows
                if needle in row["name"].lower()
                or needle in (row["class"] or "").lower()
                or needle in (row["ascendancy"] or "").lower()
                or any(needle in tag["name"].lower() for tag in row["tags"])
                or any(needle in (tag.get("korean") or "").lower() for tag in row["tags"])
                or any(needle in (hit.get("korean") or "").lower() for hit in row["hits"])
            ]
        if filter_ in ("green", "yellow", "red"):
            rows = [row for row in rows if row["verdict"] == filter_]
        elif filter_ == "custom":
            rows = [row for row in rows if row.get("mine")]
        return {"verdicts": rows, "game": game, "updated": result.generated_at.isoformat(timespec="seconds")}

    def buffs(self, *, top: int = 15, min_buff: float = 3.0, kind: str = "") -> dict:
        with self.lock:
            result = self.result
            if result is None:
                return {"buffs": [], "kinds": []}
            kinds = {kind} if kind and kind != "전체" else None
            rows = [buff_payload(c) for c in result.filtered_buffs(top=top, min_buff=min_buff, kinds=kinds)]
            all_kinds = sorted({c.kind_label for c in result.buffs})
        return {"buffs": rows, "kinds": all_kinds}

    def recommend(self, category: str, limit: int = 10) -> dict:
        with self.lock:
            board = self.result.recommendations if self.result else None
            if board is None:
                return {"categories": {}, "rows": []}
            if category not in recommend.CATEGORY_ORDER:
                category = "allrounder"
            rows = [entry.to_dict() for entry in board.top(category, limit)]
            return {
                "category": category,
                "label": recommend.CATEGORY_LABELS[category],
                "rows": rows,
                "categories": {
                    key: {"label": recommend.CATEGORY_LABELS[key],
                          "rows": [entry.to_dict() for entry in board.top(key, limit)]}
                    for key in recommend.CATEGORY_ORDER
                },
            }

    # -- 가이드 -----------------------------------------------------------
    def _guide(self, build_id: str) -> guide_mod.Guide:
        build_id = (build_id or "").strip()
        if not build_id:
            raise ApiError("빌드를 골라 주세요.")
        build = self.library.get(build_id)
        if build is None:
            raise ApiError("라이브러리에 없는 빌드입니다.", status=404)
        try:
            return guide_mod.build_guide(build, result=self.result)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"가이드를 만들지 못했습니다: {exc}", status=500) from exc

    def guide(self, build_id: str) -> dict:
        with self.lock:
            return guide_payload(self._guide(build_id))

    def guide_code(self, build_id: str) -> str:
        with self.lock:
            made = self._guide(build_id)
        if not made.code:
            raise ApiError("이 빌드에는 PoB 코드가 없습니다.", status=404)
        return made.code

    def guide_source(self, build_id: str) -> str:
        build = self.library.get((build_id or "").strip())
        if build is None:
            raise ApiError("라이브러리에 없는 빌드입니다.", status=404)
        return build.source or ""

    def export_guide_html(self, build_id: str) -> Path:
        with self.lock:
            made = self._guide(build_id)
        return guide_mod.export_html(made)

    # -- 내보내기 ----------------------------------------------------------
    def export_text(self, fmt: str = "md") -> tuple[str, str]:
        with self.lock:
            result = self.result
            if result is None:
                raise ApiError("먼저 검사를 실행해 주세요.", status=409)
            fmt = (fmt or "md").lower()
            if fmt in ("json",):
                body = report.render_json(result)
                ext = "json"
            elif fmt in ("txt", "text"):
                body = report.render_text(result)
                ext = "txt"
            else:
                body = report.render_markdown(result)
                ext = "md"
            stamp = result.generated_at.strftime("%Y%m%d-%H%M")
        name = f"poe-starter-report-{stamp}.{ext}"
        return body, name

    def write_export(self, fmt: str, path: str) -> Path:
        body, _ = self.export_text(fmt)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target

    # -- 카탈로그 ----------------------------------------------------------
    def sync_catalog(self, *, dry_run: bool = False) -> dict:
        with self.lock:
            try:
                rep = catalog.sync_library(self.library, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                raise ApiError(f"스타터 최신화 실패: {exc}", status=502) from exc
            if rep.changed and not dry_run:
                self.result = None  # 새 스타터가 다음 검사에 반영되도록
            self.sync_info = {
                "catalog": rep.location or catalog.CATALOG_URL,
                "updated": rep.updated_label,
                "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
                "saved": rep.saved,
                "live": self.sync_info.get("live", {}),
            }
            data = rep.to_dict()
            data["summary"] = rep.summary()
            data["lines"] = rep.lines()
            data["changed"] = rep.changed
            data["counts"] = self._library_counts()
            return data

    def sync_live(self, *, dry_run: bool = False, games: list[str] | None = None) -> dict:
        """실시간(EXILEFILTER·유튜브) 빌드 수집 — ① 원격 카탈로그 뒤에 이어서 실행한다."""
        target = [
            datafiles.normalize_game(game) for game in (games or list(datafiles.GAMES))
        ]
        with self.lock:
            try:
                rep = live_sync.sync_live(self.library, games=target, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001 - 수집기는 원칙적으로 예외를 올리지 않는다
                raise ApiError(f"실시간 빌드 수집 실패: {exc}", status=502) from exc
            if rep.changed and not dry_run:
                self.result = None  # 새 스타터가 다음 검사·추천에 반영되도록
            live = rep.to_dict()
            live["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.sync_info["live"] = live
            live["counts_all"] = self._library_counts()
            return live

    # -- 로컬 파일 도우미 ---------------------------------------------------
    def default_export_dir(self) -> Path:
        home = Path.home()
        downloads = home / "Downloads"
        return downloads if downloads.exists() else home


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _finite(value, default: float = 0.0) -> float:
    """NaN·무한대는 JSON/JS 로 넘기면 깨지므로 유한값으로 바꾼다."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _rounded(value) -> int:
    return int(round(min(abs(_finite(value)), 1e15)))


def _clean_numbers(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if isinstance(value, dict):
        return {key: _clean_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_numbers(item) for item in value]
    return value


def _json_bytes(data) -> bytes:
    return json.dumps(_clean_numbers(data), ensure_ascii=False, allow_nan=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = f"PoE-Starter-Checker/{__version__}"
    protocol_version = "HTTP/1.1"

    # -- 응답 ------------------------------------------------------------
    def log_message(self, fmt, *args):  # pragma: no cover - 조용히
        return

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            pass

    def _json(self, data, status: int = 200) -> None:
        self._send(status, _json_bytes(data), "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    # -- 공통 ------------------------------------------------------------
    @property
    def state_obj(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    @property
    def token(self) -> str:
        return self.server.token  # type: ignore[attr-defined]

    def _check_token(self) -> bool:
        supplied = self.headers.get("X-App-Token") or ""
        if not supplied:
            supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return secrets.compare_digest(supplied, self.token)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError("요청 본문이 너무 큽니다.", status=413)
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(f"JSON 본문을 읽지 못했습니다: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError("JSON 객체를 보내 주세요.")
        return data

    # -- GET -------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        if path.startswith("/api/"):
            if not self._check_token():
                return self._error("접근 토큰이 없습니다.", 403)
            try:
                return self._api_get(path, query)
            except ApiError as exc:
                return self._error(str(exc), exc.status)
            except Exception as exc:  # noqa: BLE001
                return self._error(f"처리 중 오류: {exc}", 500)
        return self._static(path)

    def _api_get(self, path: str, query: dict) -> None:
        state = self.state_obj
        if path == "/api/state":
            return self._json({"ok": True, **state.state()})
        if path == "/api/builds":
            return self._json({"ok": True, **state.builds(query.get("game"))})
        if path == "/api/news":
            refresh = str(query.get("refresh", "")).lower() in ("1", "true", "yes")
            return self._json({"ok": True, **state.news(game=query.get("game"), refresh=refresh)})
        if path == "/api/result":
            return self._json({"ok": True, **state.result_payload()})
        if path == "/api/verdicts":
            return self._json(
                {"ok": True, **state.verdicts(
                    filter_=query.get("filter", "all"), q=query.get("q", ""))}
            )
        if path == "/api/buffs":
            try:
                top = int(query.get("top", 15))
                min_buff = float(query.get("min", 3))
            except ValueError:
                raise ApiError("표시 개수·최소 상향률 값이 올바르지 않습니다.")
            return self._json({"ok": True, **state.buffs(top=top, min_buff=min_buff,
                                                        kind=query.get("kind", ""))})
        if path == "/api/recommend":
            try:
                limit = int(query.get("limit", 10))
            except ValueError:
                raise ApiError("표시 개수가 올바르지 않습니다.")
            return self._json({"ok": True, **state.recommend(query.get("category", "allrounder"), limit)})
        if path == "/api/guide":
            return self._json({"ok": True, "guide": state.guide(query.get("build_id", ""))})
        if path == "/api/guide/code":
            return self._json({"ok": True, "code": state.guide_code(query.get("build_id", ""))})
        if path == "/api/guide/html":
            made = state.guide(query.get("build_id", ""))
            return self._json({"ok": True, "html": made})
        if path == "/api/health":
            return self._json({"ok": True, "version": __version__, "pid": __import__("os").getpid()})
        raise ApiError("없는 API 주소입니다.", status=404)

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        if name not in STATIC_FILES:
            return self._send(404, b"Not found", "text/plain; charset=utf-8")
        target = WEB_DIR / name
        if not target.is_file():
            return self._send(404, b"Not found", "text/plain; charset=utf-8")
        try:
            body = target.read_bytes()
        except OSError:
            return self._send(500, b"Cannot read asset", "text/plain; charset=utf-8")
        if name == "index.html":
            body = body.replace(_TOKEN_PLACEHOLDER.encode(), self.token.encode())
            body = body.replace(_VERSION_PLACEHOLDER.encode(), __version__.encode())
        self._send(200, body, STATIC_FILES[name])

    # -- POST ------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            return self._error("없는 주소입니다.", 404)
        if not self._check_token():
            return self._error("접근 토큰이 없습니다.", 403)
        try:
            payload = self._read_json()
        except ApiError as exc:
            return self._error(str(exc), exc.status)
        try:
            return self._api_post(path, payload)
        except ApiError as exc:
            return self._error(str(exc), exc.status)
        except Exception as exc:  # noqa: BLE001
            return self._error(f"처리 중 오류: {exc}", 500)

    def _api_post(self, path: str, payload: dict) -> None:
        state = self.state_obj
        if path == "/api/game":
            game = state.set_game(payload.get("game") or datafiles.GAME_POE1)
            return self._json({"ok": True, "game": game, "state": state.state()})
        if path == "/api/analyze":
            return self._json({"ok": True, **state.analyze(payload)})
        if path == "/api/patch/text":
            return self._json({"ok": True, **state.load_patch_text(payload.get("url", ""))})
        if path == "/api/patch/file":
            return self._json({"ok": True, **state.load_patch_file(payload.get("path", ""))})
        if path == "/api/library/add":
            return self._json({"ok": True, **state.add_build(
                payload.get("source", ""),
                name=payload.get("name", ""),
                game=payload.get("game") or None,
                kind=payload.get("kind") or "custom",
            )})
        if path == "/api/library/remove":
            return self._json({"ok": True, **state.remove_build(payload.get("id", ""))})
        if path == "/api/sync":
            return self._json({"ok": True, **state.sync_catalog(dry_run=bool(payload.get("dry_run")))})
        if path == "/api/sync/live":
            games = payload.get("games") or None
            if isinstance(games, str):
                games = [games]
            return self._json({"ok": True, **state.sync_live(
                dry_run=bool(payload.get("dry_run")), games=games)})
        if path == "/api/export":
            fmt = payload.get("format", "md")
            body, name = state.export_text(fmt)
            out = {"format": fmt, "filename": name, "content": body, "bytes": len(body.encode())}
            if payload.get("save"):
                target = state.write_export(fmt, payload.get("path") or (state.default_export_dir() / name))
                out["path"] = str(target)
            return self._json({"ok": True, **out})
        if path == "/api/guide/open":
            made = state.export_guide_html(payload.get("build_id", ""))
            opened = False
            try:
                import webbrowser

                opened = webbrowser.open(made.resolve().as_uri())
            except Exception:  # noqa: BLE001
                opened = False
            return self._json({"ok": True, "path": str(made), "opened": bool(opened)})
        if path == "/api/clipboard":
            text = payload.get("text", "")
            return self._json({"ok": True, "copied": copy_to_clipboard(text)})
        raise ApiError("없는 API 주소입니다.", status=404)


def copy_to_clipboard(text: str) -> bool:
    """백엔드 폴백 클립보드 복사(프론트 navigator.clipboard 실패 시)."""
    if not text:
        return False
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            proc = subprocess.run(["clip"], input=text.encode("utf-16le"), timeout=10)
            return proc.returncode == 0
        if sys.platform == "darwin":
            proc = subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=10)
            return proc.returncode == 0
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                proc = subprocess.run(cmd, input=text.encode("utf-8"), timeout=10)
                if proc.returncode == 0:
                    return True
            except FileNotFoundError:
                continue
    except Exception:  # noqa: BLE001
        return False
    return False


def make_server(state: AppState | None = None, *, host: str = "127.0.0.1", port: int = 0,
                web_dir: Path | None = None) -> ServerHandle:
    state = state or AppState()
    token = secrets.token_urlsafe(18)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.app_state = state  # type: ignore[attr-defined]
    httpd.token = token  # type: ignore[attr-defined]
    url = f"http://{host}:{httpd.server_address[1]}/"
    return ServerHandle(httpd=httpd, url=url, state=state, token=token)


def start_server(state: AppState | None = None, *, host: str = "127.0.0.1",
                 port: int = 0) -> ServerHandle:
    handle = make_server(state, host=host, port=port)
    thread = threading.Thread(target=handle.httpd.serve_forever, name="poe-web", daemon=True)
    thread.start()
    handle.thread = thread
    return handle
