"""패치노트 1건에 대한 전체 분석 실행."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from . import buffs, library as library_mod, matcher, patchnotes


@dataclass
class AnalysisResult:
    notes: patchnotes.PatchNotes
    verdicts: list[matcher.BuildVerdict] = field(default_factory=list)
    buffs: list[buffs.BuffCandidate] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)
    source_label: str = ""
    version_hint: str = ""
    warnings: list[str] = field(default_factory=list)
    top: int = 15
    min_buff: float = 3.0

    def filtered_buffs(self, *, top: int | None = None, min_buff: float | None = None,
                       kinds: set[str] | None = None) -> list:
        limit = self.top if top is None else top
        floor = self.min_buff if min_buff is None else min_buff
        rows = [
            cand
            for cand in self.buffs
            if (cand.score >= floor or cand.qualitative) and (not kinds or cand.kind_label in kinds)
        ]
        return rows[:limit]

    @property
    def entry_count(self) -> int:
        return len(self.notes.entries)

    @property
    def red(self) -> list[matcher.BuildVerdict]:
        return [v for v in self.verdicts if v.verdict == matcher.VERDICT_RED]

    @property
    def yellow(self) -> list[matcher.BuildVerdict]:
        return [v for v in self.verdicts if v.verdict == matcher.VERDICT_YELLOW]

    @property
    def green(self) -> list[matcher.BuildVerdict]:
        return [v for v in self.verdicts if v.verdict == matcher.VERDICT_GREEN]


_VERSION_RE = re.compile(r"\b3\.\d{1,2}(?:\.\d{1,2})?\b")


def _version_hint(notes: patchnotes.PatchNotes) -> str:
    haystack = " ".join([notes.title, notes.text[:4000]])
    match = _VERSION_RE.search(haystack)
    if match:
        return match.group(0)
    if "Covens of Umbra" in haystack:
        return "3.30"
    return ""


def analyze(
    lib: library_mod.BuildLibrary,
    notes: patchnotes.PatchNotes,
    *,
    top: int = 15,
    min_buff: float = 3.0,
) -> AnalysisResult:
    profiles = lib.profiles()
    result = AnalysisResult(
        notes=notes,
        verdicts=matcher.check_library(lib, notes),
        buffs=buffs.rank_buffs(notes, profiles),
        source_label=notes.source or "",
        version_hint=_version_hint(notes),
        top=top,
        min_buff=min_buff,
    )
    if not notes.entries:
        result.warnings.append(
            "패치노트에서 젬·유니크·전직 이름이 붙은 항목을 하나도 찾지 못했습니다. "
            "일반 안내문이거나 형식이 다른 문서일 수 있으니, 0건을 '변경 없음'의 근거로 쓰지 마세요."
        )
    failed = [v for v in result.verdicts if v.error]
    if failed:
        result.warnings.append(
            "읽지 못한 빌드가 있습니다: " + ", ".join(v.build_name for v in failed)
        )
    return result
