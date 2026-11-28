"""명령줄 모드 — 디스플레이 없이 검증할 때 쓴다."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (APP_TITLE, __version__, analysis, catalog, datafiles, guide,
               library as library_mod, live_sync, news, patchnotes, pob, report)


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
    source.add_argument("--patch-latest", action="store_true",
                        help="공식 홈페이지에서 가장 최신 패치노트를 찾아 바로 검사")
    source.add_argument("--list-patch-notes", action="store_true",
                        help="공식 홈페이지의 최신 패치노트 목록(PoE1/PoE2)을 출력")
    source.add_argument("--only-patch", action="store_true",
                        help="--list-patch-notes 에서 패치노트로 보이는 항목만")
    source.add_argument("--limit", type=int, default=25, help="--list-patch-notes 출력 개수(기본 25)")

    game = parser.add_argument_group("게임")
    game.add_argument("--game", choices=list(datafiles.GAMES), default=None,
                      help="검사할 게임(기본: 패치노트 출처에 맞춤, 없으면 poe1)")

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
    lib.add_argument("--sync-starters", action="store_true",
                     help="원격 카탈로그에서 스타터 목록·PoB 코드를 받아 최신화")
    lib.add_argument("--catalog-url", metavar="URL",
                     help="카탈로그 주소/파일 경로(기본: 공식 저장소 raw URL)")
    lib.add_argument("--dry-run", action="store_true", help="--sync-starters/--sync-live 미리보기(저장 안 함)")
    lib.add_argument("--live", action="store_true",
                     help="--sync-starters 뒤에 EXILEFILTER·유튜브 실시간 수집까지 실행")
    lib.add_argument("--sync-live", action="store_true",
                     help="원격 카탈로그 없이 실시간(EXILEFILTER·유튜브) 빌드만 수집")
    lib.add_argument("--live-games", metavar="poe1,poe2",
                     help="실시간 수집 대상 게임(기본: 둘 다)")
    lib.add_argument("--no-youtube", action="store_true", help="실시간 수집에서 유튜브 채널 건너뛰기")

    guides = parser.add_argument_group("빌드 가이드")
    guides.add_argument("--guide", metavar="BUILD_ID",
                        help="PoB XML 로 만든 빌드 가이드 & 빌드업을 텍스트로 출력")
    guides.add_argument("--export-guide", metavar="BUILD_ID",
                        help="빌드 가이드 HTML 을 생성(--out 으로 경로 지정, 없으면 기본 폴더)")
    guides.add_argument("--open", action="store_true", help="--export-guide HTML 을 기본 브라우저로 열기")

    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    parser.add_argument("--gui", action="store_true", help="GUI 로 실행")
    return parser


def _load_library(args) -> library_mod.BuildLibrary:
    return library_mod.BuildLibrary.load(args.library)


def _list_builds(lib: library_mod.BuildLibrary, game: str | None = None) -> None:
    rows = lib.rows(game)
    if not rows:
        _print("라이브러리가 비어 있습니다.")
        return
    _print(f"{'ID':36} {'게임':5} {'이름':30} {'종류':10} 전직/클래스  레벨  주력")
    _print("-" * 120)
    for row in rows:
        _print(
            f"{row['id'][:36]:36} {row['game'][:5]:5} {row['name'][:28]:30} {row['kind'][:10]:10} "
            f"{(row['class'] or '-')[:10]:10} {str(row['level']):4} {row['main'][:26]}"
            + (f"  ! {row['error']}" if row["error"] else "")
        )
    _print(f"\n총 {len(rows)}개 · 파일: {lib.path}")


def _print_news(feed: news.NewsFeed, *, game: str | None, limit: int, only_patch: bool) -> None:
    rows = feed.filtered(game=game, only_patch=only_patch)[: max(1, limit)]
    if not rows:
        _print("패치노트 목록이 비어 있습니다.")
        return
    for index, ref in enumerate(rows, start=1):
        mark = "" if ref.is_patch else "  (뉴스)"
        _print(f"{index:2d}. {ref.display()}{mark}")
        _print(f"    {ref.url}  · {ref.source}")
    for error in feed.errors:
        _print(f"! {error}")


def run(args) -> int:
    lib = _load_library(args)
    game = datafiles.normalize_game(args.game) if args.game else None

    if args.list_builds:
        _list_builds(lib, game)
        return 0

    if args.list_patch_notes:
        try:
            feed = news.fetch_news()
        except patchnotes.PatchNotesError as exc:
            _print(f"패치노트 목록 오류: {exc}")
            return 3
        _print_news(feed, game=game, limit=args.limit, only_patch=args.only_patch)
        if game is None:
            counts = feed.counts()
            _print(f"\n합계: PoE1 {counts.get('poe1', 0)}건 · PoE2 {counts.get('poe2', 0)}건")
        return 0

    if args.add_build:
        try:
            entry = lib.add(args.add_build, name=args.name or "", kind=args.kind,
                            note=args.note, game=game)
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

    def _live_targets():
        if not args.live_games:
            return None
        wanted = [part.strip() for part in args.live_games.split(",") if part.strip()]
        return [datafiles.normalize_game(game) for game in wanted] or None

    if args.sync_starters:
        try:
            result = catalog.sync_library(
                lib, url=args.catalog_url, dry_run=args.dry_run
            )
        except (catalog.CatalogError, OSError) as exc:
            _print(f"스타터 최신화 실패: {exc}")
            return 3
        for line in result.lines():
            _print(line)
        if not args.live:
            return 0

    if args.sync_starters or args.sync_live:
        try:
            live = live_sync.sync_live(
                lib,
                games=_live_targets(),
                dry_run=args.dry_run,
                include_youtube=not args.no_youtube,
            )
        except Exception as exc:  # noqa: BLE001 - 실패해도 카탈로그 결과는 남는다
            _print(f"실시간 수집 실패: {exc}")
            return 3
        for line in live.lines():
            _print(line)
        return 0

    if args.guide or args.export_guide:
        build_id = args.export_guide or args.guide
        build = lib.get(build_id)
        if build is None:
            _print(f"해당 ID 가 없습니다: {build_id}")
            return 2
        result = None
        if args.patch_url or args.patch_file or args.patch_text or args.patch_latest:
            url = args.patch_url
            try:
                if args.patch_latest and not (url or args.patch_file or args.patch_text):
                    feed = news.fetch_news()
                    latest = feed.latest(game=build.game)
                    if latest is None:
                        _print("최신 패치노트를 찾지 못했습니다.")
                        return 3
                    url = latest.url
                notes = patchnotes.patch_notes_from_source(
                    url=url, path=args.patch_file, text=args.patch_text, game=build.game
                )
                result = analysis.analyze(lib, notes, game=build.game)
            except (patchnotes.PatchNotesError, OSError) as exc:
                _print(f"패치노트 오류: {exc}")
                return 3
        try:
            made = guide.build_guide(build, result=result)
        except guide.GuideError as exc:
            _print(f"가이드 생성 실패: {exc}")
            return 3
        if args.export_guide:
            path = guide.export_html(made, args.out)
            if not args.quiet:
                _print(f"HTML 가이드: {path}")
                _print(f"  빌드: {made.name} · 스킬 세트 {len(made.skill_sets)} · 장비 세트 {len(made.item_sets)}")
                _print(f"  PoB 코드 {len(made.code)}자 · 패치 분석 {'포함' if made.patch else '없음'}")
            if args.open:
                guide.open_guide(path)
            return 0
        text = guide.render_text(made)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            if not args.quiet:
                _print(f"가이드 저장: {args.out}")
        if not args.quiet:
            _print(text)
        return 0

    if args.patch_latest and not (args.patch_url or args.patch_file or args.patch_text):
        try:
            feed = news.fetch_news()
        except patchnotes.PatchNotesError as exc:
            _print(f"패치노트 목록 오류: {exc}")
            return 3
        latest = feed.latest(game=game)
        if latest is None:
            _print("최신 패치노트를 찾지 못했습니다.")
            return 3
        args.patch_url = latest.url
        game = latest.game
        _print(f"최신 패치노트: {latest.display()}")

    if not (args.patch_url or args.patch_file or args.patch_text):
        _print("패치노트를 지정해 주세요: --patch-url, --patch-file, --patch-text, --patch-latest 중 하나.")
        return 2

    try:
        notes = patchnotes.patch_notes_from_source(
            url=args.patch_url, path=args.patch_file, text=args.patch_text,
            game=game or "",
        )
    except (patchnotes.PatchNotesError, OSError) as exc:
        _print(f"패치노트 오류: {exc}")
        return 3

    result = analysis.analyze(lib, notes, top=args.top, min_buff=args.min_buff, game=game)
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


def _ensure_streams() -> None:
    """windowed exe(pythonw) 처럼 stdout/stderr 가 None 이어도 죽지 않게 한다."""
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    _ensure_streams()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "gui", False):
        from .gui import launch

        return launch()
    return run(args)
