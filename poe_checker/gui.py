"""tkinter GUI — 탭 2개: 스타터 생존 검증 / 대폭 상향 탐지.

tkinter 는 여기서만 쓴다(CLI·테스트는 tkinter 없이 동작).
"""
from __future__ import annotations

import threading
import traceback
import webbrowser
from pathlib import Path

from . import APP_TITLE, __version__, analysis, buffs, library as library_mod, matcher
from . import patchnotes, pob, report

FONT_CANDIDATES = ("Malgun Gothic", "맑은 고딕", "AppleGothic", "NanumGothic", "Segoe UI")
MONO_CANDIDATES = ("Consolas", "D2Coding", "Menlo", "DejaVu Sans Mono", "Courier New")

VERDICT_COLORS = {
    matcher.VERDICT_RED: "#c0392b",
    matcher.VERDICT_YELLOW: "#b8860b",
    matcher.VERDICT_GREEN: "#1e824c",
}


def _pick_font(root, candidates, size=10):
    try:
        from tkinter import font as tkfont

        available = set(tkfont.families(root))
    except Exception:  # pragma: no cover
        available = set()
    for name in candidates:
        if name in available:
            return (name, size)
    return ("TkDefaultFont", size)


# ---------------------------------------------------------------------------
# tkinter 없는 순수 로직 (테스트 대상)
# ---------------------------------------------------------------------------

def verdict_rows(result: analysis.AnalysisResult) -> list[tuple[str, ...]]:
    rows = []
    for index, verdict in enumerate(result.verdicts, start=1):
        profile = verdict.profile
        rows.append(
            (
                str(index),
                verdict.label,
                verdict.build_name,
                " · ".join(x for x in (profile.ascendancy or profile.class_name,) if x),
                f"{profile.level}레벨" if profile.level else "",
                verdict.headline(),
            )
        )
    return rows


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
    if profile.main_skill_names:
        lines.append(f"주력 스킬: {', '.join(profile.main_skill_names)}")
    if profile.support_names:
        lines.append(f"서포트: {', '.join(profile.support_names[:8])}")
    if profile.uniques:
        lines.append(f"유니크: {', '.join(profile.uniques)}")
    if profile.keystones:
        lines.append(f"키스톤: {', '.join(profile.keystones)}")
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


def buff_detail_text(cand: buffs.BuffCandidate) -> str:
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
# GUI
# ---------------------------------------------------------------------------

def launch() -> int:  # pragma: no cover - GUI 는 수동/윈도우 실행
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{APP_TITLE} v{__version__}")
    root.geometry("1240x820")
    root.minsize(980, 640)
    try:  # Windows 고해상도 대응
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App(root)
    root.mainloop()
    return 0


class App:  # pragma: no cover - GUI
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.library = library_mod.BuildLibrary.load()
        self.result: analysis.AnalysisResult | None = None
        self.notes: patchnotes.PatchNotes | None = None
        self._busy = False
        self._pending: dict | None = None

        self.font = _pick_font(root, FONT_CANDIDATES, 10)
        self.mono = _pick_font(root, MONO_CANDIDATES, 10)
        self._style()
        self._build_header()
        self._build_tabs()
        self._build_statusbar()
        self.refresh_builds()
        self.root.after(120, self._poll)

    # -- 구성 -----------------------------------------------------------
    def _style(self):
        style = self.ttk.Style(self.root)
        for theme in ("vista", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure(".", font=self.font)
        style.configure("Head.TLabel", font=(self.font[0], 15, "bold"))
        style.configure("Sub.TLabel", foreground="#555555")
        style.configure("Treeview", rowheight=24, font=self.font)
        style.configure("Treeview.Heading", font=(self.font[0], 10, "bold"))
        style.configure("Run.TButton", font=(self.font[0], 11, "bold"), padding=(14, 8))

    def _build_header(self):
        tk, ttk = self.tk, self.ttk
        header = ttk.Frame(self.root, padding=(14, 10, 14, 4))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Head.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Day 1, poe.ninja 없이 패치노트만으로 스타터 생존·상향 스킬 확인",
            style="Sub.TLabel",
        ).pack(side="left", padx=(12, 0), pady=(6, 0))
        ttk.Label(header, text=f"v{__version__}", style="Sub.TLabel").pack(side="right")

    def _build_tabs(self):
        ttk = self.ttk
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.tab_survival = ttk.Frame(self.tabs, padding=8)
        self.tab_buffs = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.tab_survival, text=" 1. 스타터 생존 검증 ")
        self.tabs.add(self.tab_buffs, text=" 2. 대폭 상향(버프) 탐지 ")

        self._build_survival_tab()
        self._build_buff_tab()

    def _build_statusbar(self):
        ttk = self.ttk
        bar = ttk.Frame(self.root, padding=(14, 4, 14, 8))
        bar.pack(fill="x")
        self.status_var = self.tk.StringVar(value=f"라이브러리: {self.library.path}")
        ttk.Label(bar, textvariable=self.status_var, style="Sub.TLabel").pack(side="left")
        self.count_var = self.tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.count_var, style="Sub.TLabel").pack(side="right")

    # -- 탭 1 -----------------------------------------------------------
    def _build_survival_tab(self):
        tk, ttk = self.tk, self.ttk
        paned = ttk.Panedwindow(self.tab_survival, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=2)
        paned.add(right, weight=3)

        ttk.Label(left, text="빌드 라이브러리").pack(anchor="w")
        columns = ("name", "class", "main", "tree")
        self.lib_tree = ttk.Treeview(left, columns=columns, show="headings", height=10)
        for column, title, width in (
            ("name", "이름", 190),
            ("class", "전직", 90),
            ("main", "주력 스킬", 170),
            ("tree", "트리", 50),
        ):
            self.lib_tree.heading(column, text=title)
            self.lib_tree.column(column, width=width, anchor="w")
        self.lib_tree.pack(fill="both", expand=True, pady=(4, 6))

        buttons = ttk.Frame(left)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="빌드 추가", command=self.add_build).pack(side="left")
        ttk.Button(buttons, text="선택 삭제", command=self.remove_build).pack(side="left", padx=4)
        ttk.Button(buttons, text="새로고침", command=self.refresh_builds).pack(side="left")
        ttk.Label(
            left,
            text="pobb.in 주소, PoB 코드, .xml 파일을 추가할 수 있습니다.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        # -- 패치노트 입력
        source = ttk.LabelFrame(right, text=" 패치노트 ", padding=8)
        source.pack(fill="x")
        row = ttk.Frame(source)
        row.pack(fill="x")
        ttk.Label(row, text="주소").pack(side="left")
        self.url_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.url_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="불러오기", command=self.fetch_url).pack(side="left")
        ttk.Button(row, text="파일…", command=self.pick_file).pack(side="left", padx=4)

        paste_row = ttk.Frame(source)
        paste_row.pack(fill="x", pady=(8, 0))
        ttk.Label(paste_row, text="또는 본문 붙여넣기").pack(anchor="w")
        self.patch_text = tk.Text(paste_row, height=7, wrap="word", font=self.font, undo=True)
        self.patch_text.pack(fill="both", expand=True, pady=(4, 6))

        action = ttk.Frame(source)
        action.pack(fill="x")
        self.run_button = ttk.Button(
            action, text="검사 실행", style="Run.TButton", command=self.run_check
        )
        self.run_button.pack(side="left")
        self.progress = ttk.Progressbar(action, mode="indeterminate", length=180)
        self.progress.pack(side="left", padx=10)
        ttk.Button(action, text="리포트 저장", command=self.save_report).pack(side="right")

        # -- 결과
        result_frame = ttk.Frame(right)
        result_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.result_paned = ttk.Panedwindow(result_frame, orient="vertical")
        self.result_paned.pack(fill="both", expand=True)

        top = ttk.Frame(self.result_paned)
        bottom = ttk.Frame(self.result_paned)
        self.result_paned.add(top, weight=3)
        self.result_paned.add(bottom, weight=2)

        columns = ("no", "verdict", "name", "class", "level", "summary")
        self.result_tree = ttk.Treeview(top, columns=columns, show="headings", height=8)
        for column, title, width in (
            ("no", "#", 36),
            ("verdict", "판정", 120),
            ("name", "빌드", 240),
            ("class", "전직", 90),
            ("level", "레벨", 60),
            ("summary", "요약", 320),
        ):
            self.result_tree.heading(column, text=title)
            self.result_tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scroll.set)
        self.result_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.result_tree.bind("<<TreeviewSelect>>", self.show_verdict_detail)

        self.detail = tk.Text(bottom, wrap="word", font=self.mono, height=12)
        detail_scroll = ttk.Scrollbar(bottom, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self._configure_tags(self.detail)

    # -- 탭 2 -----------------------------------------------------------
    def _build_buff_tab(self):
        tk, ttk = self.tk, self.ttk
        top = ttk.Frame(self.tab_buffs)
        top.pack(fill="x")
        ttk.Label(top, text="최소 상향률(%)").pack(side="left")
        self.min_buff_var = tk.StringVar(value="3")
        ttk.Spinbox(top, from_=0, to=100, increment=1, width=6, textvariable=self.min_buff_var).pack(
            side="left", padx=(4, 12)
        )
        ttk.Label(top, text="표시 개수").pack(side="left")
        self.top_var = tk.StringVar(value="15")
        ttk.Spinbox(top, from_=5, to=100, increment=1, width=6, textvariable=self.top_var).pack(
            side="left", padx=(4, 12)
        )
        ttk.Label(top, text="유형").pack(side="left")
        self.kind_var = tk.StringVar(value="전체")
        ttk.Combobox(
            top,
            textvariable=self.kind_var,
            values=("전체", "스킬", "서포트", "유니크", "전직", "키스톤"),
            state="readonly",
            width=8,
        ).pack(side="left", padx=(4, 12))
        ttk.Button(top, text="다시 계산", command=lambda: self.show_buffs()).pack(side="left")
        ttk.Label(
            top,
            text="패치노트는 1번 탭에서 불러옵니다.",
            style="Sub.TLabel",
        ).pack(side="left", padx=12)

        paned = ttk.Panedwindow(self.tab_buffs, orient="vertical")
        paned.pack(fill="both", expand=True, pady=(8, 0))
        table = ttk.Frame(paned)
        detail = ttk.Frame(paned)
        paned.add(table, weight=3)
        paned.add(detail, weight=2)

        columns = ("no", "name", "kind", "score", "count", "seeds")
        self.buff_tree = ttk.Treeview(table, columns=columns, show="headings", height=10)
        for column, title, width in (
            ("no", "#", 40),
            ("name", "대상", 260),
            ("kind", "유형", 110),
            ("score", "상향", 90),
            ("count", "건수", 60),
            ("seeds", "연결된 빌드", 380),
        ):
            self.buff_tree.heading(column, text=title)
            self.buff_tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.buff_tree.yview)
        self.buff_tree.configure(yscrollcommand=scroll.set)
        self.buff_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.buff_tree.bind("<<TreeviewSelect>>", self.show_buff_detail)
        self.buff_tree.bind("<Double-1>", self.open_buff_link)

        self.buff_detail = tk.Text(detail, wrap="word", font=self.mono, height=12)
        buff_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.buff_detail.yview)
        self.buff_detail.configure(yscrollcommand=buff_scroll.set)
        self.buff_detail.pack(side="left", fill="both", expand=True)
        buff_scroll.pack(side="right", fill="y")
        self._configure_tags(self.buff_detail)

    def _configure_tags(self, widget):
        widget.tag_configure("red", foreground=VERDICT_COLORS[matcher.VERDICT_RED])
        widget.tag_configure("yellow", foreground=VERDICT_COLORS[matcher.VERDICT_YELLOW])
        widget.tag_configure("green", foreground=VERDICT_COLORS[matcher.VERDICT_GREEN])
        widget.tag_configure("dim", foreground="#666666")
        widget.tag_configure("bold", font=(self.mono[0], 11, "bold"))
        widget.configure(state="disabled")

    # -- 라이브러리 ------------------------------------------------------
    def refresh_builds(self):
        tree = self.lib_tree
        tree.delete(*tree.get_children())
        for row in self.library.rows():
            label = row["name"] if not row["error"] else f"{row['name']} (오류)"
            tree.insert("", "end", iid=row["id"], values=(label, row["class"], row["main"], row["tree"]))
        self.status_var.set(f"라이브러리: {self.library.path} · 빌드 {len(self.library.builds)}개")

    def _selected_build_id(self) -> str | None:
        selection = self.lib_tree.selection()
        return selection[0] if selection else None

    def add_build(self):
        tk, ttk = self.tk, self.ttk
        dialog = tk.Toplevel(self.root)
        dialog.title("빌드 추가")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("620x300")

        ttk.Label(
            dialog,
            text="pobb.in 주소, PoB 코드, PoB .xml 파일 경로 중 하나를 넣어 주세요.",
        ).pack(anchor="w", padx=12, pady=(12, 4))
        text = tk.Text(dialog, height=8, wrap="word", font=self.mono)
        text.pack(fill="both", expand=True, padx=12, pady=4)

        name_row = ttk.Frame(dialog)
        name_row.pack(fill="x", padx=12)
        ttk.Label(name_row, text="이름(선택)").pack(side="left")
        name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=name_var).pack(side="left", fill="x", expand=True, padx=6)

        status = ttk.Label(dialog, text="", style="Sub.TLabel")
        status.pack(anchor="w", padx=12)

        def submit():
            source = text.get("1.0", "end").strip()
            if not source:
                status.configure(text="코드나 주소를 입력해 주세요.")
                return
            status.configure(text="확인 중…")
            dialog.update_idletasks()
            try:
                entry = self.library.add(source, name=name_var.get().strip(), kind="custom")
            except (pob.PobError, library_mod.LibraryError) as exc:
                status.configure(text=f"추가 실패: {exc}")
                return
            self.refresh_builds()
            self.status_var.set(f"추가됨: {entry.name}")
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=10)
        ttk.Button(buttons, text="추가", command=submit).pack(side="right")
        ttk.Button(buttons, text="취소", command=dialog.destroy).pack(side="right", padx=6)

    def remove_build(self):
        from tkinter import messagebox

        build_id = self._selected_build_id()
        if not build_id:
            messagebox.showinfo(APP_TITLE, "삭제할 빌드를 선택해 주세요.")
            return
        build = self.library.get(build_id)
        if not build:
            return
        if not messagebox.askyesno(APP_TITLE, f"'{build.name}' 을(를) 라이브러리에서 삭제할까요?"):
            return
        self.library.remove(build_id)
        self.refresh_builds()

    # -- 패치노트 --------------------------------------------------------
    def fetch_url(self):
        from tkinter import messagebox

        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo(APP_TITLE, "패치노트 주소를 입력해 주세요.")
            return
        self._set_busy(True, "패치노트를 불러오는 중…")

        def work():
            try:
                text, title = patchnotes.fetch_patch_text(url)
                self._pending = {"kind": "text", "text": text, "title": title, "url": url}
            except Exception as exc:  # noqa: BLE001
                self._pending = {"kind": "error", "message": str(exc)}

        threading.Thread(target=work, daemon=True).start()

    def pick_file(self):
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            title="패치노트 텍스트 선택",
            filetypes=[("텍스트", "*.txt *.md"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            text = patchnotes.load_patch_file(path)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"파일을 읽지 못했습니다: {exc}")
            return
        self.patch_text.configure(state="normal")
        self.patch_text.delete("1.0", "end")
        self.patch_text.insert("1.0", text)
        self.status_var.set(f"패치노트 파일: {path}")

    def run_check(self):
        from tkinter import messagebox

        if self._busy:
            return
        url = self.url_var.get().strip()
        pasted = self.patch_text.get("1.0", "end").strip()
        if not pasted and not url:
            messagebox.showinfo(
                APP_TITLE, "패치노트 주소를 입력하거나 본문을 붙여넣어 주세요."
            )
            return

        self._set_busy(True, "검사 중…")

        def work():
            try:
                if pasted:
                    notes = patchnotes.parse_patch_notes(pasted, source="붙여넣은 텍스트")
                else:
                    body, title = patchnotes.fetch_patch_text(url)
                    notes = patchnotes.parse_patch_notes(body, title=title, source=url)
                result = analysis.analyze(
                    self.library, notes, top=self._top_n(), min_buff=self._min_buff()
                )
                self._pending = {"kind": "result", "result": result}
            except Exception as exc:  # noqa: BLE001
                self._pending = {"kind": "error", "message": str(exc)}

        threading.Thread(target=work, daemon=True).start()

    def _top_n(self) -> int:
        try:
            return max(1, int(self.top_var.get()))
        except ValueError:
            return 15

    def _min_buff(self) -> float:
        try:
            return max(0.0, float(self.min_buff_var.get()))
        except ValueError:
            return 3.0

    # -- 결과 표시 -------------------------------------------------------
    def _poll(self):
        if self._pending:
            pending, self._pending = self._pending, None
            self._handle_pending(pending)
        self.root.after(150, self._poll)

    def _handle_pending(self, pending: dict):
        from tkinter import messagebox

        kind = pending.get("kind")
        if kind == "text":
            self.patch_text.configure(state="normal")
            self.patch_text.delete("1.0", "end")
            self.patch_text.insert("1.0", pending["text"])
            self.status_var.set(f"불러옴: {pending.get('title') or pending.get('url')}")
            self._set_busy(False, "패치노트를 불러왔습니다. '검사 실행'을 눌러 주세요.")
            return
        if kind == "result":
            self.result = pending["result"]
            self.notes = self.result.notes
            self.show_results()
            self._set_busy(False, "검사 완료")
            return
        if kind == "error":
            self._set_busy(False, "오류")
            messagebox.showerror(APP_TITLE, pending.get("message", "알 수 없는 오류"))

    def show_results(self):
        result = self.result
        if result is None:
            return
        tree = self.result_tree
        tree.delete(*tree.get_children())
        rows = verdict_rows(result)
        for row in rows:
            iid = tree.insert("", "end", values=row)
            verdict = result.verdicts[int(row[0]) - 1]
            tree.item(iid, tags=(verdict.verdict,))
        for verdict, color in VERDICT_COLORS.items():
            tree.tag_configure(verdict, foreground=color)
        self.count_var.set(
            f"🔴 {len(result.red)} · 🟡 {len(result.yellow)} · 🟢 {len(result.green)} "
            f"· 상향 TOP {len(result.filtered_buffs())}"
        )
        if result.warnings:
            self.status_var.set("⚠ " + " / ".join(result.warnings))
        self.show_buffs()
        if rows:
            children = tree.get_children()
            tree.selection_set(children[0])
            tree.focus(children[0])
            self.show_verdict_detail()

    def show_verdict_detail(self, _event=None):
        selection = self.result_tree.selection()
        if not selection or self.result is None:
            return
        index = int(self.result_tree.item(selection[0], "values")[0]) - 1
        verdict = self.result.verdicts[index]
        text = verdict_detail_text(verdict)
        self._set_text(self.detail, text, verdict.verdict)

    def _set_text(self, widget, text: str, tag: str | None = None):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        first, _, rest = text.partition("\n")
        widget.insert("end", first + "\n", ("bold", tag) if tag else ("bold",))
        widget.insert("end", rest)
        widget.configure(state="disabled")

    # -- 버프 탭 ---------------------------------------------------------
    def show_buffs(self):
        if self.result is None:
            return
        kind = self.kind_var.get()
        kinds = None if kind == "전체" else {kind}
        filtered = self.result.filtered_buffs(
            top=self._top_n(), min_buff=self._min_buff(), kinds=kinds
        )
        tree = self.buff_tree
        tree.delete(*tree.get_children())
        for index, cand in enumerate(filtered, start=1):
            tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    str(index),
                    cand.name,
                    cand.kind_label + (" · 혼합" if cand.entry.direction == "mixed" else ""),
                    f"{cand.score:+.1f}%",
                    str(cand.occurrences),
                    ", ".join(cand.seeds) or "—",
                ),
            )
        self._buff_view = filtered
        if filtered:
            tree.selection_set("1")
            self.show_buff_detail()

    def show_buff_detail(self, _event=None):
        selection = self.buff_tree.selection()
        if not selection:
            return
        index = int(selection[0]) - 1
        view = getattr(self, "_buff_view", [])
        if index >= len(view):
            return
        self._set_text(self.buff_detail, buff_detail_text(view[index]))

    def open_buff_link(self, _event=None):
        selection = self.buff_tree.selection()
        if not selection:
            return
        index = int(selection[0]) - 1
        view = getattr(self, "_buff_view", [])
        if index < len(view):
            webbrowser.open(view[index].poedb_url())

    # -- 저장/상태 -------------------------------------------------------
    def save_report(self):
        from tkinter import filedialog, messagebox

        if self.result is None:
            messagebox.showinfo(APP_TITLE, "먼저 검사를 실행해 주세요.")
            return
        path = filedialog.asksaveasfilename(
            title="리포트 저장",
            defaultextension=".txt",
            filetypes=[("텍스트", "*.txt"), ("Markdown", "*.md"), ("JSON", "*.json")],
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix == ".json":
            body = report.render_json(self.result)
        elif suffix == ".md":
            body = report.render_markdown(self.result)
        else:
            body = report.render_text(self.result)
        Path(path).write_text(body, encoding="utf-8")
        self.status_var.set(f"저장됨: {path}")

    def _set_busy(self, busy: bool, message: str = ""):
        self._busy = busy
        state = "disabled" if busy else "normal"
        try:
            self.run_button.configure(state=state)
        except Exception:
            pass
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        if message:
            self.status_var.set(message)


def main() -> int:  # pragma: no cover
    try:
        return launch()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
