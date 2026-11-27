"""분석 결과를 콘솔 텍스트·JSON·Markdown 으로 출력."""
from __future__ import annotations

import json
from datetime import datetime

from . import APP_TITLE, __version__, datafiles, matcher
from .analysis import AnalysisResult

WIDTH = 78


def _rule(char: str = "=") -> str:
    return char * WIDTH


def _wrap(text: str, indent: str = "   ", width: int = WIDTH) -> list[str]:
    lines = []
    current = indent
    for word in text.split():
        if len(current) + len(word) + 1 > width:
            lines.append(current.rstrip())
            current = indent + "  " + word + " "
        else:
            current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _time_label(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _korean(game: str, section: str, name: str) -> str:
    korean = datafiles.korean_name(game, section, name)
    return f"{name}({korean})" if korean and korean != name else name


def _source_line(game: str, kind_label: str, origin: str, tree: str) -> str:
    bits = [datafiles.GAME_VERSION_LABELS.get(datafiles.normalize_game(game), ""), kind_label]
    if origin:
        bits.append(origin)
    if tree:
        bits.append(f"트리 {tree}")
    seen: list[str] = []
    for bit in bits:
        for token in [part.strip() for part in bit.split("·")]:
            if token and token not in seen:
                seen.append(token)
    return " · ".join(seen)


def render_text(result: AnalysisResult, *, show_details: bool = True) -> str:
    notes = result.notes
    out: list[str] = []
    out.append(_rule())
    out.append(f" {APP_TITLE} v{__version__}")
    out.append(_rule())
    title = notes.title or "(제목 없음)"
    version = f" · 패치 {result.version_hint}" if result.version_hint else ""
    out.append(f"게임     : {result.game_label}")
    out.append(f"패치노트 : {title}{version}")
    if result.source_label:
        out.append(f"출처     : {result.source_label}")
    out.append(f"분석 시각: {_time_label(result.generated_at)}")
    out.append(f"항목 수  : {result.entry_count}개 (빌드 {len(result.verdicts)}개 검사)")
    counts = (
        f"🔴 {len(result.red)} · 🟡 {len(result.yellow)} · 🟢 {len(result.green)}"
    )
    out.append(f"판정 요약: {counts}")
    for warning in result.warnings:
        for wrapped in _wrap(f"⚠ {warning}"):
            out.append(wrapped)
    out.append("")

    out.append("[1] 스타터 생존 검증")
    out.append(_rule("-"))
    if not result.verdicts:
        out.append("   검사할 빌드가 없습니다. 라이브러리에 PoB 코드를 추가해 주세요.")
    for verdict in result.verdicts:
        profile = verdict.profile
        who = " · ".join(
            x for x in (profile.ascendancy or profile.class_name, f"{profile.level}레벨" if profile.level else "") if x
        )
        out.append(f"{verdict.label}  {verdict.build_name}" + (f"  ({who})" if who else ""))
        source = _source_line(
            profile.game,
            getattr(verdict, "kind_label", ""),
            getattr(verdict, "origin", ""),
            profile.tree_version,
        )
        if source:
            out.append(f"   출처: {source}")
        if profile.main_skill_names:
            mains = ", ".join(_korean(profile.game, "gems", n) for n in profile.main_skill_names[:2])
            out.append(f"   주력: {mains}")
        out.append(f"   → {verdict.headline()}")
        if verdict.error:
            out.append(f"   ! {verdict.error}")
        if show_details:
            for hit, lines in verdict.matched_lines():
                out.append(f"   · {hit.describe()}")
                for line in lines[:6]:
                    for wrapped in _wrap(line, indent="       "):
                        out.append(wrapped)
        out.append("")

    shown_buffs = result.filtered_buffs()
    out.append(f"[2] 대폭 상향(버프) TOP {len(shown_buffs)}")
    out.append(_rule("-"))
    if not shown_buffs:
        out.append("   기준치를 넘는 상향 항목이 없습니다.")
    for index, cand in enumerate(shown_buffs, start=1):
        seeds = f"  ↔ 시드: {', '.join(cand.seeds)}" if cand.seeds else ""
        out.append(f"{index:2d}. {cand.describe()}{seeds}")
        if show_details:
            for line in cand.evidence(limit=3):
                for wrapped in _wrap(line, indent="     "):
                    out.append(wrapped)
            links = [cand.poedb_url()]
            ninja = cand.ninja_url()
            if ninja:
                links.append(ninja)
            out.append(f"     링크: {' | '.join(links)}")
    out.append("")
    out.append(_rule())
    out.append("주의: 판정은 패치노트 문장과 빌드 구성 요소의 이름 매칭·수치 비교로 계산됩니다.")
    out.append("      실제 체감은 젬 레벨·장비·플레이 방식에 따라 다를 수 있습니다.")
    return "\n".join(out)


def render_json(result: AnalysisResult) -> str:
    payload = {
        "tool": APP_TITLE,
        "version": __version__,
        "generated_at": result.generated_at.isoformat(timespec="seconds"),
        "game": result.game,
        "game_label": result.game_label,
        "patch": {
            "title": result.notes.title,
            "source": result.source_label,
            "version_hint": result.version_hint,
            "entry_count": result.entry_count,
        },
        "summary": {
            "red": len(result.red),
            "yellow": len(result.yellow),
            "green": len(result.green),
        },
        "builds": [],
        "buffs": [],
    }
    for verdict in result.verdicts:
        profile = verdict.profile
        payload["builds"].append(
            {
                "id": verdict.build_id,
                "name": verdict.build_name,
                "game": profile.game,
                "kind": getattr(verdict, "kind_label", ""),
                "origin": getattr(verdict, "origin", ""),
                "verdict": verdict.verdict,
                "label": verdict.label,
                "headline": verdict.headline(),
                "class": profile.class_name,
                "ascendancy": profile.ascendancy,
                "level": profile.level,
                "tree_version": profile.tree_version,
                "main_skills": profile.main_skill_names,
                "supports": profile.support_names,
                "uniques": profile.uniques,
                "keystones": profile.keystones,
                "error": verdict.error,
                "hits": [
                    {
                        "entity": hit.entity_name,
                        "entity_kind": hit.entity_kind,
                        "entry": hit.entry.name,
                        "entry_kind": hit.entry.kind,
                        "direction": hit.direction,
                        "severity": hit.severity,
                        "alias": hit.alias,
                        "score": round(hit.entry.signal.score, 2),
                        "lines": hit.entry.display_lines(limit=12),
                    }
                    for hit in verdict.hits
                ],
            }
        )
    for cand in result.filtered_buffs():
        payload["buffs"].append(
            {
                "name": cand.name,
                "kind": cand.kind_label,
                "score": round(cand.score, 2),
                "total": round(cand.total, 2),
                "occurrences": cand.occurrences,
                "seeds": cand.seeds,
                "poedb": cand.poedb_url(),
                "poe_ninja": cand.ninja_url(),
                "evidence": cand.evidence(limit=6),
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_markdown(result: AnalysisResult) -> str:
    notes = result.notes
    out = [f"# {APP_TITLE} 결과", ""]
    out.append(f"- 게임: {result.game_label}")
    out.append(f"- 패치노트: {notes.title or '(제목 없음)'}")
    if result.source_label:
        out.append(f"- 출처: {result.source_label}")
    if result.version_hint:
        out.append(f"- 패치 버전: {result.version_hint}")
    out.append(f"- 분석 시각: {_time_label(result.generated_at)}")
    out.append(
        f"- 요약: 🔴 {len(result.red)} · 🟡 {len(result.yellow)} · 🟢 {len(result.green)}"
    )
    for warning in result.warnings:
        out.append(f"- ⚠ {warning}")
    out.append("")
    out.append("## 1. 스타터 생존 검증")
    out.append("")
    out.append("| 판정 | 빌드 | 전직/레벨 | 요약 |")
    out.append("| --- | --- | --- | --- |")
    for verdict in result.verdicts:
        profile = verdict.profile
        who = " ".join(
            str(x) for x in (profile.ascendancy or profile.class_name, profile.level or "") if x
        )
        out.append(f"| {verdict.label} | {verdict.build_name} | {who} | {verdict.headline()} |")
    out.append("")
    for verdict in result.verdicts:
        out.append(f"### {verdict.label} {verdict.build_name}")
        if verdict.profile.main_skill_names:
            out.append(f"- 주력: {', '.join(verdict.profile.main_skill_names)}")
        if verdict.error:
            out.append(f"- 오류: {verdict.error}")
        for hit, lines in verdict.matched_lines():
            out.append(f"- **{hit.entity_name}** ({hit.kind_label}) ← {hit.entry.name}")
            for line in lines[:8]:
                out.append(f"  - {line}")
        out.append("")
    out.append("## 2. 대폭 상향(버프) TOP")
    out.append("")
    for index, cand in enumerate(result.filtered_buffs(), start=1):
        seeds = f" (시드: {', '.join(cand.seeds)})" if cand.seeds else ""
        out.append(f"{index}. **{cand.name}** — {cand.kind_label} {cand.score:+.1f}%{seeds}")
        for line in cand.evidence(limit=3):
            out.append(f"   - {line}")
    out.append("")
    return "\n".join(out)
