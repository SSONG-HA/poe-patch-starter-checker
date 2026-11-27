"""데스크톱 실행 진입점 — 내장 로컬 웹 대시보드.

v1.3.0 부터 tkinter 화면 대신 `poe_checker/webapp.py` 의 로컬 HTTP 서버가
`poe_checker/data/web/` 의 다크 골드 대시보드를 서비스하고, `pywebview`
전용 창으로 띄운다. pywebview/WebView2 런타임이 없으면 크래시하지 않고
기본 브라우저로 자동 폴백한다(서버는 유지).

CLI·pytest 는 pywebview 없이 이 모듈만 import 해도 동작한다(지연 import).
"""
from __future__ import annotations

import time
import traceback
import webbrowser
from pathlib import Path

from . import (
    APP_TITLE,
    __version__,
    analysis,
    buffs as buffs_mod,
    datafiles,
    matcher,
    patchnotes,
    recommend,
)
from . import webapp

WINDOW_TITLE = f"{APP_TITLE} v{__version__}"


# ---------------------------------------------------------------------------
# tkinter 없는 순수 로직 (테스트·내보내기용 — v1.2.0 과 호환)
# ---------------------------------------------------------------------------

def verdict_rows(result: analysis.AnalysisResult) -> list[tuple[str, ...]]:
    rows = []
    for index, verdict in enumerate(result.verdicts, start=1):
        profile = verdict.profile
        source = " · ".join(
            x for x in (verdict.kind_label, verdict.origin,
                        f"트리 {profile.tree_version}" if profile.tree_version else "") if x
        )
        rows.append(
            (
                str(index),
                verdict.label,
                verdict.build_name,
                source,
                " · ".join(x for x in (profile.ascendancy or profile.class_name,) if x),
                f"{profile.level}레벨" if profile.level else "",
                verdict.headline(),
            )
        )
    return rows


def korean(game: str, section: str, name: str) -> str:
    label = datafiles.korean_name(game, section, name)
    return f"{name}({label})" if label and label != name else name


def verdict_detail_text(verdict: matcher.BuildVerdict) -> str:
    profile = verdict.profile
    lines = [f"{verdict.label}  {verdict.build_name}"]
    info = " · ".join(
        str(x)
        for x in (
            profile.class_name,
            profile.ascendancy,
            f"{profile.level}레벨" if profile.level else "",
            f"트리 {profile.tree_version}" if profile.tree_version else "",
        )
        if x
    )
    if info:
        lines.append(info)
    source_bits = [verdict.kind_label, verdict.origin]
    if source_bits:
        lines.append("출처: " + " · ".join(x for x in source_bits if x))
    if profile.main_skill_names:
        lines.append(f"주력 스킬: {', '.join(korean(profile.game, 'gems', n) for n in profile.main_skill_names)}")
    if profile.support_names:
        lines.append(f"서포트: {', '.join(profile.support_names[:8])}")
    if profile.uniques:
        lines.append(f"유니크: {', '.join(korean(profile.game, 'uniques', n) for n in profile.uniques)}")
    if profile.keystones:
        lines.append(f"키스톤: {', '.join(korean(profile.game, 'keystones', n) for n in profile.keystones)}")
    lines.append("")
    lines.append(f"→ {verdict.headline()}")
    if verdict.error:
        lines.append(f"! {verdict.error}")
    if not verdict.hits:
        lines.append("패치노트에서 이 빌드의 구성 요소와 일치하는 항목을 찾지 못했습니다.")
    for hit, patch_lines in verdict.matched_lines():
        lines.append("")
        lines.append(f"· {hit.describe()}")
        for line in patch_lines:
            lines.append(f"    {line}")
    return "\n".join(lines)


def buff_rows(result: analysis.AnalysisResult) -> list[tuple[str, ...]]:
    rows = []
    for index, cand in enumerate(result.buffs, start=1):
        rows.append(
            (
                str(index),
                cand.name,
                cand.kind_label + (" · 혼합" if cand.entry.direction == "mixed" else ""),
                f"{cand.score:+.1f}%",
                str(cand.occurrences),
                ", ".join(cand.seeds) or "—",
            )
        )
    return rows


def recommend_detail_text(entry: recommend.Recommendation, category: str) -> str:
    fit = entry.fit
    lines = [f"{entry.build_name}   [{entry.score_for(category):.2f}]  {entry.verdict_label}"]
    lines.append(recommend.CATEGORY_LABELS.get(category, category))
    who = " · ".join(x for x in (entry.kind_label, entry.origin) if x)
    if who:
        lines.append(who)
    lines.append(f"→ {entry.headline}")
    lines.append("")
    lines.append("[콘텐츠 적합도]" + ("  (자동 추정)" if fit.auto else ""))
    for key, label in recommend.FIELDS:
        lines.append(f"  {label:6} {fit.stars(key)} {fit.score(key)}")
    if fit.tags:
        lines.append(f"  특화: {' · '.join(fit.tags)}")
    if fit.note:
        lines.append(f"  근거: {fit.note}")
    lines.append("")
    lines.append(f"[패치 보정] {entry.patch_delta:+.2f} (상향 {entry.buffs} · 너프 {entry.nerfs})")
    lines.append("")
    lines.append("[추천 사유]")
    lines.append(f"  {entry.reason_for(category)}")
    if entry.error:
        lines.append("")
        lines.append(f"! {entry.error}")
    return "\n".join(lines)


def buff_detail_text(cand: buffs_mod.BuffCandidate) -> str:
    lines = [f"{cand.name}  ({cand.kind_label})"]
    lines.append(f"최대 상향 {cand.score:+.1f}% · 합산 {cand.total:+.1f}% · {cand.occurrences}건")
    if cand.seeds:
        lines.append(f"시드 빌드: {', '.join(cand.seeds)}")
    lines.append("")
    lines.append("[근거 문장]")
    lines.extend(f"  {line}" for line in cand.evidence(limit=6))
    if cand.entry.lines:
        lines.append("")
        lines.append("[패치노트 원문]")
        lines.extend(f"  {line}" for line in cand.entry.display_lines(limit=12))
    lines.append("")
    lines.append("[바로가기]")
    lines.append(f"  {cand.poedb_url()}")
    ninja = cand.ninja_url()
    if ninja:
        lines.append(f"  {ninja}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# pywebview 네이티브 브리지 (파일 선택·저장 대화상자, 외부 링크)
# ---------------------------------------------------------------------------

class NativeApi:
    """JS `window.pywebview.api.*` 로 노출되는 로컬 기능 모음."""

    def __init__(self, state: webapp.AppState):
        self.state = state
        self.window = None

    # -- 파일 선택 ---------------------------------------------------------
    def pick_patch_file(self) -> dict:
        path = self._dialog(
            "open",
            file_types=("패치노트 텍스트 (*.txt;*.md)", "모든 파일 (*.*)"),
        )
        if not path:
            return {"cancelled": True}
        try:
            text = patchnotes.load_patch_file(path)
        except OSError as exc:
            return {"error": f"파일을 읽지 못했습니다: {exc}"}
        return {"path": path, "name": Path(path).name, "text": text, "chars": len(text)}

    def pick_build_file(self) -> dict:
        path = self._dialog(
            "open",
            file_types=("PoB XML (*.xml;*.txt)", "모든 파일 (*.*)"),
        )
        if not path:
            return {"cancelled": True}
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"error": f"파일을 읽지 못했습니다: {exc}"}
        return {"path": path, "name": Path(path).name, "text": text, "chars": len(text)}

    # -- 리포트 저장 -------------------------------------------------------
    def save_report(self, fmt: str = "md") -> dict:
        try:
            body, name = self.state.export_text(fmt)
        except webapp.ApiError as exc:
            return {"error": str(exc)}
        target = self._dialog(
            "save",
            save_filename=name,
            directory=str(self.state.default_export_dir()),
        )
        if not target:
            return {"cancelled": True}
        try:
            path = Path(target)
            if not path.suffix:
                path = path.with_suffix("." + (name.rsplit(".", 1)[-1]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except OSError as exc:
            return {"error": f"저장하지 못했습니다: {exc}"}
        return {"ok": True, "path": str(path), "bytes": len(body.encode("utf-8"))}

    # -- 외부 열기 ---------------------------------------------------------
    def open_url(self, url: str) -> dict:
        if not url:
            return {"error": "주소가 없습니다."}
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"브라우저를 열지 못했습니다: {exc}"}

    def open_guide(self, build_id: str) -> dict:
        try:
            path = self.state.export_guide_html(build_id)
        except webapp.ApiError as exc:
            return {"error": str(exc)}
        try:
            webbrowser.open(path.resolve().as_uri())
        except Exception as exc:  # noqa: BLE001
            return {"error": f"브라우저를 열지 못했습니다: {exc}", "path": str(path)}
        return {"ok": True, "path": str(path)}

    def copy_text(self, text: str) -> dict:
        return {"ok": webapp.copy_to_clipboard(text or "")}

    # -- 내부 -------------------------------------------------------------
    def _dialog(self, kind: str, **kwargs):
        window = self.window
        if window is None:
            return None
        try:
            import webview

            dialog_type = webview.SAVE_DIALOG if kind == "save" else webview.OPEN_DIALOG
            chosen = window.create_file_dialog(dialog_type, **kwargs)
        except Exception:  # noqa: BLE001 - 대화상자 실패는 치명적이지 않다
            traceback.print_exc()
            return None
        if not chosen:
            return None
        if isinstance(chosen, (list, tuple)):
            return str(chosen[0]) if chosen else None
        return str(chosen)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def _debug_enabled() -> bool:
    import os

    return os.environ.get("POE_CHECKER_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _run_native_window(url: str, state: webapp.AppState) -> bool:
    """pywebview 전용 창으로 연다. 실패하면 False(브라우저 폴백)."""
    try:
        import webview
    except Exception:
        return False
    api = NativeApi(state)
    try:
        window = webview.create_window(
            WINDOW_TITLE,
            url,
            width=1360,
            height=880,
            min_size=(1060, 700),
            background_color="#0b0a09",
            js_api=api,
            text_select=True,
            confirm_close=False,
        )
        api.window = window
        webview.start(debug=_debug_enabled(), private_mode=False)
        return True
    except Exception:  # noqa: BLE001 - WebView2 런타임 없음 등
        traceback.print_exc()
        return False


def _mini_window(url: str) -> bool:
    """브라우저 폴백용 최소 창 — 닫으면 서버도 끝난다."""
    try:
        import tkinter as tk
    except Exception:
        return False
    try:
        root = tk.Tk()
        root.title(WINDOW_TITLE)
        root.configure(bg="#0b0a09")
        root.geometry("440x190")
        root.resizable(False, False)
        frame = tk.Frame(root, bg="#0b0a09", padx=20, pady=18)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame, text="대시보드를 기본 브라우저로 열었습니다",
            bg="#0b0a09", fg="#dfba74", font=("Malgun Gothic", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame, text=url, bg="#0b0a09", fg="#948b7c", font=("Consolas", 9),
        ).pack(anchor="w", pady=(6, 10))
        row = tk.Frame(frame, bg="#0b0a09")
        row.pack(fill="x")
        tk.Button(
            row, text="브라우저 다시 열기", command=lambda: webbrowser.open(url),
            bg="#241e19", fg="#e9e3d7", relief="flat", padx=12, pady=4,
        ).pack(side="left")
        tk.Button(
            row, text="종료", command=root.destroy,
            bg="#2c251e", fg="#e9e3d7", relief="flat", padx=16, pady=4,
        ).pack(side="right")
        tk.Label(
            frame, text="이 창을 닫으면 프로그램이 종료됩니다.",
            bg="#0b0a09", fg="#6f675c", font=("Malgun Gothic", 9),
        ).pack(anchor="w", pady=(10, 0))
        root.mainloop()
        return True
    except Exception:  # noqa: BLE001
        return False


def launch(open_window: bool = True) -> int:
    """로컬 서버를 띄우고 pywebview 창(또는 브라우저)으로 대시보드를 연다."""
    try:
        state = webapp.AppState()
    except Exception as exc:  # noqa: BLE001
        print(f"라이브러리를 읽지 못했습니다: {exc}")
        return 1
    try:
        handle = webapp.start_server(state)
    except OSError as exc:
        print(f"로컬 서버를 시작하지 못했습니다: {exc}")
        return 1
    url = handle.url
    if not open_window:
        print(f"로컬 대시보드: {url}")
        return 0
    try:
        if _run_native_window(url, state):
            return 0
        webbrowser.open(url)
        if not _mini_window(url):
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        handle.shutdown()


def main() -> int:  # pragma: no cover - 수동/윈도우 실행
    try:
        return launch()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
