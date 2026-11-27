"""명령줄 모드 — 디스플레이 없이 검증할 때 쓴다."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_TITLE, __version__, analysis, library as library_mod, patchnotes, pob, report


def _print(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="PoE-Patch-Starter-Checker",
        description=f"{APP_TITLE} v{__version__} — 패치노트로 스타터 생존·상향 스킬을 검사합니다.",
    )
    source = parser.add_argument_group("패치노트")
    source.add_argument("--patch-url", help="패치노트 주소(예: pathofexile.com/forum/view-thread/...)")
    source.add_argument("--patch-file", help="패치노트 .txt 파일 경로")
    source.add_argument("--patch-text", help="패치노트 본문을 직접 문자열로 전달(테스트용)")

    out = parser.add_argument_group("출력")
    out.add_argument("--out", help="텍스트 리포트를 저장할 경로")
    out.add_argument("--json", dest="json_path", help="JSON 결과를 저장할 경로")
    out.add_argument("--md", dest="md_path", help="Markdown 결과를 저장할 경로")
    out.add_argument("--top", type=int, default=15, help="버프 상위 표시 개수(기본 15)")
    out.add_argument("--min-buff", type=float, default=3.0, help="버프 최소 상향률 %% (기본 3.0)")
    out.add_argument("--brief", action="store_true", help="매칭 문장 전문을 생략")
    out.add_argument("--quiet", action="store_true", help="화면 출력 없이 파일만 저장")

    lib = parser.add_argument_group("라이브러리")
    lib.add_argument("--library", help="라이브러리 JSON 경로(기본: 사용자 데이터 폴더)")
    lib.add_argument("--list-builds", action="store_true", help="라이브러리 빌드 목록 출력")
    lib.add_argument("--add-build", metavar="SOURCE", help="pobb.in URL·PoB 코드·XML 파일 추가")
    lib.add_argument("--name", help="--add-build 시 표시 이름")
    lib.add_argument("--kind", default="custom", choices=sorted(library_mod.KINDS), help="추가할 빌드 종류")
    lib.add_argument("--note", default="", help="--add-build 시 메모")
    lib.add_argument("--remove-build", metavar="ID", help="라이브러리에서 빌드 제거")

    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    parser.add_argument("--gui", action="store_true", help="GUI 로 실행")
    return parser


def _load_library(args) -> library_mod.BuildLibrary:
    return library_mod.BuildLibrary.load(args.library)


def _list_builds(lib: library_mod.BuildLibrary) -> None:
    rows = lib.rows()
    if not rows:
        _print("라이브러리가 비어 있습니다.")
        return
    _print(f"{'ID':38} {'판정대상 이름':34} {'종류':8} 전직/클래스  레벨  주력")
    _print("-" * 110)
    for row in rows:
        _print(
            f"{row['id'][:38]:38} {row['name'][:32]:34} {row['kind'][:8]:8} "
            f"{(row['class'] or '-')[:10]:10} {str(row['level']):4} {row['main'][:30]}"
            + (f"  ! {row['error']}" if row["error"] else "")
        )
    _print(f"\n총 {len(rows)}개 · 파일: {lib.path}")


def run(args) -> int:
    lib = _load_library(args)

    if args.list_builds:
        _list_builds(lib)
        return 0

    if args.add_build:
        try:
            entry = lib.add(args.add_build, name=args.name or "", kind=args.kind, note=args.note)
        except (pob.PobError, library_mod.LibraryError) as exc:
            _print(f"추가 실패: {exc}")
            return 3
        _print(f"추가됨: {entry.name} ({entry.id})")
        return 0

    if args.remove_build:
        if lib.remove(args.remove_build):
            _print(f"제거됨: {args.remove_build}")
            return 0
        _print(f"해당 ID 가 없습니다: {args.remove_build}")
        return 2

    if not (args.patch_url or args.patch_file or args.patch_text):
        _print("패치노트를 지정해 주세요: --patch-url, --patch-file, --patch-text 중 하나.")
        return 2

    try:
        notes = patchnotes.patch_notes_from_source(
            url=args.patch_url, path=args.patch_file, text=args.patch_text
        )
    except (patchnotes.PatchNotesError, OSError) as exc:
        _print(f"패치노트 오류: {exc}")
        return 3

    result = analysis.analyze(lib, notes, top=args.top, min_buff=args.min_buff)
    text = report.render_text(result, show_details=not args.brief)
    if not args.quiet:
        _print(text)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        if not args.quiet:
            _print(f"\n텍스트 리포트 저장: {args.out}")
    if args.json_path:
        Path(args.json_path).write_text(report.render_json(result), encoding="utf-8")
        if not args.quiet:
            _print(f"JSON 저장: {args.json_path}")
    if args.md_path:
        Path(args.md_path).write_text(report.render_markdown(result), encoding="utf-8")
        if not args.quiet:
            _print(f"Markdown 저장: {args.md_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)
