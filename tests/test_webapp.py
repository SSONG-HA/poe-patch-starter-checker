"""내장 웹 대시보드(HTTP 서버·JSON API) 테스트."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from conftest import make_pob_code
from poe_checker import __version__, catalog, datafiles, library, news, recommend, webapp

NOTES = """Skills
Righteous Fire
- Now deals 20% less Damage (previously 10%).
Arc
- Now deals 25% more Damage (previously 10%).

Support Gems
Swift Affliction
- Now has 10% increased Damage over Time (previously 5%).

Unique Items
Nebulis
- Now grants 12% increased Elemental Damage per 100 Intelligence (previously 10%).
"""


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------

def _library(tmp_path) -> library.BuildLibrary:
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "builds": [
                    {
                        "id": "rf",
                        "name": "RF 빌드",
                        "kind": "custom",
                        "code": make_pob_code(main="Righteous Fire", uniques=("Nebulis",)),
                    },
                    {
                        "id": "arc",
                        "name": "Arc 빌드",
                        "kind": "starter",
                        "code": make_pob_code(
                            main="Arc",
                            ascendancy="Elementalist",
                            supports=("Added Lightning Damage",),
                            uniques=(),
                            keystone_nodes=(),
                        ),
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return library.BuildLibrary.load(path)


@pytest.fixture
def handle(tmp_path):
    server = webapp.make_server(webapp.AppState(_library(tmp_path)), port=0)
    thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _request(server, path, body=None, *, token=True, raw: bytes | None = None,
             headers: dict | None = None) -> tuple[int, object, dict]:
    hdrs = dict(headers or {})
    if token:
        hdrs.setdefault("X-App-Token", server.token)
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(
        server.url.rstrip("/") + path, data=data, headers=hdrs,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            payload = response.read()
            ctype = response.headers.get("Content-Type", "")
            if "json" in ctype:
                return response.status, json.loads(payload), dict(response.headers)
            return response.status, payload.decode("utf-8"), dict(response.headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload), dict(exc.headers)
        except json.JSONDecodeError:
            return exc.code, payload.decode("utf-8", "replace"), dict(exc.headers)


def _analyze(server) -> dict:
    status, data, _ = _request(server, "/api/analyze", {"game": "poe1", "text": NOTES})
    assert status == 200, data
    return data


# ---------------------------------------------------------------------------
# 정적 파일·토큰
# ---------------------------------------------------------------------------

def test_index_injects_token_and_version(handle):
    status, html, headers = _request(handle, "/", token=False)
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert handle.token in html
    assert "__APP_TOKEN__" not in html
    assert f"v{__version__}" in html
    assert "styles.css" in html and "app.js" in html


def test_static_assets_are_served(handle):
    for name, needle in (("/styles.css", "--gold"), ("/app.js", "window.APP_TOKEN")):
        status, body, headers = _request(handle, name, token=False)
        assert status == 200, name
        assert needle in body
        assert "no-store" in headers.get("Cache-Control", "")


def test_api_requires_token(handle):
    status, data, _ = _request(handle, "/api/state", token=False)
    assert status == 403
    assert data["ok"] is False
    status, _, _ = _request(handle, "/api/state", headers={"X-App-Token": "nope"})
    assert status == 403


def test_query_token_is_accepted(handle):
    status, data, _ = _request(handle, f"/api/health?token={handle.token}", token=False)
    assert status == 200
    assert data["version"] == __version__


def test_unknown_paths(handle):
    assert _request(handle, "/nope.css", token=False)[0] == 404
    assert _request(handle, "/api/nope")[0] == 404
    assert _request(handle, "/api/guide?build_id=missing")[0] == 404


def test_static_whitelist_blocks_traversal(handle):
    for path in ("/../poe_checker/webapp.py", "/..%2fwebapp.py", "/poe_checker/webapp.py"):
        status, _, _ = _request(handle, path, token=False)
        assert status == 404, path


# ---------------------------------------------------------------------------
# 상태·빌드
# ---------------------------------------------------------------------------

def test_state_payload(handle):
    status, data, _ = _request(handle, "/api/state")
    assert status == 200
    assert data["app"]["version"] == __version__
    assert [g["key"] for g in data["games"]] == ["poe1", "poe2"]
    assert data["game"] == "poe1"
    assert data["library"]["counts"] == {"total": 2, "poe1": 2, "poe2": 0, "custom": 1}
    assert data["result"] is None
    assert "catalog" in data["sync"]


def test_builds_endpoint(handle):
    status, data, _ = _request(handle, "/api/builds?game=poe1")
    assert status == 200
    assert data["count"] == 2
    assert [row["id"] for row in data["builds"]] == ["rf", "arc"]
    assert data["builds"][0]["custom"] is True
    assert data["builds"][0]["mine"] is True
    assert data["builds"][1]["custom"] is False
    assert data["builds"][1]["mine"] is False
    assert data["builds"][0]["class"] == "Chieftain"
    assert data["builds"][0]["main"] == "Righteous Fire"


def test_game_switch(handle):
    status, data, _ = _request(handle, "/api/game", {"game": "poe2"})
    assert status == 200
    assert data["game"] == "poe2"
    assert data["state"]["game"] == "poe2"
    status, data, _ = _request(handle, "/api/builds?game=poe2")
    assert data["count"] == 0


# ---------------------------------------------------------------------------
# 분석
# ---------------------------------------------------------------------------

def test_analyze_returns_full_dashboard_payload(handle):
    data = _analyze(handle)
    result = data["result"]
    assert result["game"] == "poe1"
    assert result["kpi"] == {"green": 1, "yellow": 0, "red": 1, "buffs": 3, "total": 2}
    assert result["entry_count"] == 4
    assert {v["id"] for v in result["verdicts"]} == {"rf", "arc"}

    rf = next(v for v in result["verdicts"] if v["id"] == "rf")
    assert rf["verdict"] == "red"
    assert rf["label"].startswith("🔴")
    assert rf["custom"] is True
    assert rf["tags"] and any(t["korean"] == "정의의 화염" for t in rf["tags"])
    assert any(t["affected"] == "nerf" for t in rf["tags"])
    hit = rf["hits"][0]
    assert hit["kind"] == "주력 스킬"
    assert hit["direction"] == "nerf"
    assert hit["core"] is True
    assert hit["lines"] and "less Damage" in hit["lines"][0]

    names = [b["name"] for b in result["buffs"]]
    assert "Arc" in names and "Nebulis" in names
    arc_buff = next(b for b in result["buffs"] if b["name"] == "Arc")
    assert arc_buff["kind"] == "스킬"
    assert arc_buff["poedb"].startswith("https://poedb.tw/kr/")

    rec = result["recommend"]
    assert set(result["recommend"]["categories"]) == set(recommend.CATEGORY_ORDER)
    assert len(rec["entries"]) == 2
    top = rec["categories"]["allrounder"]["rows"][0]
    assert top["verdict"] == "green"
    assert set(top["scores"]) == set(recommend.CATEGORY_ORDER)
    assert top["reasons"]["bossing"]


def test_analyze_requires_source(handle):
    status, data, _ = _request(handle, "/api/analyze", {"game": "poe1"})
    assert status == 400
    assert "붙여넣" in data["error"]


def test_analyze_rejects_bad_numbers(handle):
    status, data, _ = _request(handle, "/api/analyze", {"text": NOTES, "top": "abc"})
    assert status == 400
    assert data["ok"] is False


def test_verdicts_filters_and_search(handle):
    _analyze(handle)
    status, data, _ = _request(handle, "/api/verdicts?filter=red")
    assert status == 200
    assert [v["id"] for v in data["verdicts"]] == ["rf"]
    status, data, _ = _request(handle, "/api/verdicts?filter=custom")
    assert [v["id"] for v in data["verdicts"]] == ["rf"]
    assert data["verdicts"][0]["mine"] is True
    status, data, _ = _request(handle, "/api/verdicts?q=arc")
    assert [v["id"] for v in data["verdicts"]] == ["arc"]
    status, data, _ = _request(handle, "/api/verdicts?q=" + urllib.parse.quote("정의"))
    assert [v["id"] for v in data["verdicts"]] == ["rf"]


def test_buffs_endpoint_filters(handle):
    _analyze(handle)
    status, data, _ = _request(handle, "/api/buffs?min=0&top=10")
    assert status == 200
    assert len(data["buffs"]) == 3
    assert set(data["kinds"]) == {"스킬", "서포트", "유니크"}
    status, data, _ = _request(handle, "/api/buffs?min=0&top=10&kind=" + urllib.parse.quote("스킬"))
    assert [b["name"] for b in data["buffs"]] == ["Arc"]
    status, data, _ = _request(handle, "/api/buffs?min=120&top=10")
    assert [b["name"] for b in data["buffs"]] == ["Arc"]


def test_recommend_endpoint(handle):
    _analyze(handle)
    status, data, _ = _request(handle, "/api/recommend?category=bossing&limit=1")
    assert status == 200
    assert len(data["rows"]) == 1
    assert data["label"] == "보스 특화"
    status, data, _ = _request(handle, "/api/recommend?category=nope")
    assert status == 200 and data["category"] == "allrounder"


# ---------------------------------------------------------------------------
# 가이드
# ---------------------------------------------------------------------------

def test_guide_payload_has_socket_colors(handle):
    status, data, _ = _request(handle, "/api/guide?build_id=rf")
    assert status == 200
    guide = data["guide"]
    assert guide["name"] == "RF 빌드"
    assert guide["stages"] and guide["stages"][0]["key"] == "basic"
    gems = [gem for link in guide["skill_sets"][0]["links"] for gem in link["gems"]]
    assert gems
    assert all(gem["color"] in {"red", "green", "blue", "white"} for gem in gems)
    assert any(gem["color"] == "blue" for gem in gems)      # Righteous Fire = intelligence
    assert guide["pob_code_length"] > 100
    assert guide["code"]


def test_guide_code_endpoint(handle):
    status, data, _ = _request(handle, "/api/guide/code?build_id=rf")
    assert status == 200
    assert len(data["code"]) > 100


def test_guide_payload_from_bundled_catalog(tmp_path):
    bundled = datafiles.DATA_DIR / "starters.json"
    lib = library.BuildLibrary.load(bundled, seed=False)
    server = webapp.make_server(webapp.AppState(lib), port=0)
    thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, data, _ = _request(server, "/api/guide?build_id=rf-chieftain-pohx")
        assert status == 200, data
        guide = data["guide"]
        keys = [stage["key"] for stage in guide["stages"]]
        assert keys and set(keys) <= {"act", "mapping", "endgame", "basic"}
        assert guide["item_sets"], "장비 세트가 있어야 한다"
        slots = [item["slot"] for item in guide["item_sets"][0]["items"]]
        assert "Body Armour" in slots or "Helmet" in slots
        item = next(i for i in guide["item_sets"][0]["items"] if i["slot"] == "Body Armour")
        assert item["kind"] in ("unique", "rare", "magic", "normal", "relic")
        assert guide["specs"] and "keystones" in guide["specs"][0]
        assert guide["notes_blocks"] or guide["notes_length"]
        assert guide["notes"] and len(guide["notes"]) > 100
        assert guide["code_length"] == len(guide["code"]) > 1000
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "title,index,total,expected",
    [
        ("Act 1 Leveling", 0, 3, "act"),
        ("초반 스타터", 0, 3, "act"),
        ("Lvl 60 Budget", 0, 3, "act"),
        ("Lvl 90 Block Based", 0, 3, "mapping"),
        ("Lvl 98 Endgame", 0, 3, "endgame"),
        ("Endgame min-max", 0, 2, "endgame"),
        ("", 0, 1, "basic"),
        ("", 0, 2, "mapping"),
        ("", 1, 2, "endgame"),
    ],
)
def test_stage_for(title, index, total, expected):
    assert webapp.stage_for(title, index=index, total=total) == expected


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------

def test_export_requires_result(handle):
    status, data, _ = _request(handle, "/api/export", {"format": "md"})
    assert status == 409
    assert "검사" in data["error"]


def test_export_formats(handle, tmp_path):
    _analyze(handle)
    status, data, _ = _request(handle, "/api/export", {"format": "md"})
    assert status == 200
    assert data["filename"].endswith(".md")
    assert data["content"].startswith("#")
    status, data, _ = _request(handle, "/api/export", {"format": "json"})
    assert json.loads(data["content"])["game"] in ("poe1", "PoE1")
    status, data, _ = _request(handle, "/api/export", {"format": "txt"})
    assert "RIGHTEOUS" in data["content"].upper() or "RF 빌드" in data["content"]

    target = tmp_path / "report.md"
    status, data, _ = _request(handle, "/api/export", {"format": "md", "save": True, "path": str(target)})
    assert status == 200
    assert target.exists() and target.read_text(encoding="utf-8").startswith("#")


# ---------------------------------------------------------------------------
# 라이브러리·동기화·뉴스
# ---------------------------------------------------------------------------

def test_library_add_and_remove(handle):
    code = make_pob_code(main="Arc", ascendancy="Elementalist")
    status, data, _ = _request(handle, "/api/library/add", {"source": code, "name": "추가 빌드"})
    assert status == 200, data
    assert data["name"] == "추가 빌드"
    status, data, _ = _request(handle, "/api/builds?game=poe1")
    assert data["count"] == 3
    assert data["custom"] == 2

    status, data, _ = _request(handle, "/api/library/remove", {"id": "arc"})
    assert status == 200 and data["removed"] is True
    status, data, _ = _request(handle, "/api/builds?game=poe1")
    assert data["count"] == 2
    assert "arc" not in [b["id"] for b in data["builds"]]


def test_library_add_errors(handle):
    status, data, _ = _request(handle, "/api/library/add", {"source": ""})
    assert status == 400
    status, data, _ = _request(handle, "/api/library/add", {"source": "완전히 잘못된 코드"})
    assert status == 400
    assert data["ok"] is False
    assert _request(handle, "/api/library/remove", {"id": "nope"})[0] == 404


def test_analysis_resets_after_library_change(handle):
    _analyze(handle)
    assert _request(handle, "/api/result")[1]["result"]["kpi"]["total"] == 2
    _request(handle, "/api/library/add",
             {"source": make_pob_code(main="Arc"), "name": "새 빌드"})
    status, data, _ = _request(handle, "/api/result")
    assert status == 200
    assert data["result"] is None


def test_news_endpoint_uses_fetcher(handle, monkeypatch):
    ref = news.PatchNoteRef("3.30 패치노트", "https://example.test/1", "poe1", "2026-11-27")
    feed = news.NewsFeed(refs=[ref])
    monkeypatch.setattr(news, "fetch_news", lambda *a, **k: feed)
    status, data, _ = _request(handle, "/api/news?game=poe1")
    assert status == 200
    assert data["refs"][0]["title"] == "3.30 패치노트"
    assert data["refs"][0]["display"].startswith("[PoE1]")


def test_sync_endpoint_reports(handle, monkeypatch):
    report = catalog.SyncReport(location="https://example.test/catalog.json",
                                updated_label="2026-11-27", added=["new-build"], saved=True)
    monkeypatch.setattr(catalog, "sync_library", lambda lib, dry_run=False: report)
    status, data, _ = _request(handle, "/api/sync", {})
    assert status == 200
    assert data["added"] == ["new-build"]
    assert data["summary"].startswith("스타터 최신화")
    assert data["saved"] is True
    assert data["changed"] is True
    status, state, _ = _request(handle, "/api/state")
    assert state["sync"]["updated"] == "2026-11-27"


# ---------------------------------------------------------------------------
# 오류 처리
# ---------------------------------------------------------------------------

def test_non_finite_numbers_are_sanitized(handle):
    assert webapp._rounded(float("inf")) == 0
    assert webapp._rounded(None) == 0
    payload = json.loads(webapp._json_bytes({"x": float("inf"), "y": [float("nan")]}))
    assert payload == {"x": 0.0, "y": [0.0]}


def test_bad_json_body(handle):
    status, data, _ = _request(handle, "/api/analyze", raw=b"{bad json")
    assert status == 400
    assert data["ok"] is False


def test_non_object_json_rejected(handle):
    status, data, _ = _request(handle, "/api/analyze", raw=b"[1,2,3]")
    assert status == 400


def test_patch_file_endpoint(handle, tmp_path):
    patch = tmp_path / "notes.txt"
    patch.write_text(NOTES, encoding="utf-8")
    status, data, _ = _request(handle, "/api/patch/file", {"path": str(patch)})
    assert status == 200
    assert data["chars"] == len(data["text"])
    assert "Righteous Fire" in data["text"]
    assert data["title"] == "notes.txt"
    status, data, _ = _request(handle, "/api/patch/file", {"path": str(tmp_path / "missing.txt")})
    assert status == 400


# ---------------------------------------------------------------------------
# 실시간 스타터 수집(EXILEFILTER·유튜브)
# ---------------------------------------------------------------------------

def test_sync_live_endpoint_reports(handle, monkeypatch):
    from poe_checker import live_sync

    report = live_sync.LiveSyncReport(
        games=("poe1", "poe2"),
        added=["eb-zero-to-hero-bula"],
        counts={"exilebuilds": 2, "youtube": 1},
        saved=True,
        duration=3.4,
    )
    seen = {}

    def fake(lib, **kwargs):
        seen.update(kwargs)
        return report

    monkeypatch.setattr(live_sync, "sync_live", fake)
    status, data, _ = _request(handle, "/api/sync/live", {})
    assert status == 200
    assert data["added"] == ["eb-zero-to-hero-bula"]
    assert data["counts"]["youtube"] == 1
    assert data["summary"].startswith("실시간 수집")
    assert data["saved"] is True
    assert data["changed"] is True
    assert seen["games"] == ["poe1", "poe2"]
    status, state, _ = _request(handle, "/api/state")
    assert state["sync"]["live"]["summary"].startswith("실시간 수집")
    assert state["sync"]["live"]["at"]


def test_sync_live_endpoint_accepts_game_filter(handle, monkeypatch):
    from poe_checker import live_sync

    seen = {}

    def fake(lib, **kwargs):
        seen.update(kwargs)
        return live_sync.LiveSyncReport(games=("poe2",))

    monkeypatch.setattr(live_sync, "sync_live", fake)
    status, _, _ = _request(handle, "/api/sync/live", {"games": "poe2"})
    assert status == 200
    assert seen["games"] == ["poe2"]


def test_sync_live_resets_analysis_result(handle, monkeypatch):
    from poe_checker import live_sync

    assert _analyze(handle)["result"] is not None
    report = live_sync.LiveSyncReport(games=("poe1",), added=["new-live-build"], saved=True)
    monkeypatch.setattr(live_sync, "sync_live", lambda lib, **kwargs: report)
    _request(handle, "/api/sync/live", {})
    status, data, _ = _request(handle, "/api/result")
    assert status == 200 and data["result"] is None
