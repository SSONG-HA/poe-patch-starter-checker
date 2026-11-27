"""대폭 상향(버프) 탐지 & 빌드 시드 연결."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from . import datafiles, naming, patchnotes

_KIND_LABELS = {
    "gem": "스킬",
    "support": "서포트",
    "ascendancy": "전직",
    "keystone": "키스톤",
    "unique": "유니크",
    "passive": "패시브",
    "generic": "기타",
}


@dataclass
class BuffCandidate:
    entry: patchnotes.PatchEntry
    score: float
    total: float
    occurrences: int
    kind_label: str = "기타"
    seeds: list[str] = field(default_factory=list)
    qualitative: bool = False

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def direction_label(self) -> str:
        return "상향" if self.entry.direction == "buff" else "혼합(상향 우세)"

    def poedb_url(self) -> str:
        slug = self.entry.name.replace(" ", "_").replace("'", "%27")
        return f"https://poedb.tw/kr/{quote(slug, safe='_%')}"

    def ninja_url(self) -> str | None:
        if self.entry.kind not in ("gem", "support"):
            return None
        skill = self.entry.name.removesuffix(" Support").replace(" ", "_")
        return f"https://poe.ninja/poe1/builds?skill={quote(skill, safe='_')}"

    def describe(self) -> str:
        occ = f" ({self.occurrences}건)" if self.occurrences > 1 else ""
        magnitude = "정성 상향" if self.qualitative else f"{self.score:+.1f}%"
        mixed = " · 혼합" if self.entry.direction == "mixed" else ""
        return f"{self.name} — {self.kind_label} {magnitude}{occ}{mixed}"

    def evidence(self, limit: int = 4) -> list[str]:
        if self.qualitative:
            added = self.entry.unpaired_new or [
                line
                for line in self.entry.lines
                if line.strip().lower() not in ("added", "removed", "modified")
            ]
            if added:
                return added[:limit]
        lines = []
        best = sorted(self.entry.signal.deltas, key=lambda d: -d.benefit_pct)[:limit]
        for delta in best:
            if delta.benefit_pct > 0:
                lines.append(f"{delta.describe()} · {delta.note[:110]}")
        if not lines:
            lines = self.entry.display_lines(limit=limit)
        return lines


def _kind_label(entry: patchnotes.PatchEntry, library_uniques: set[str]) -> str:
    key = naming.norm(entry.name)
    if key in datafiles.support_gem_keys():
        return "서포트"
    if key in datafiles.active_gem_keys():
        return "스킬"
    if key in datafiles.ascendancy_keys():
        return "전직"
    if key in datafiles.keystone_keys():
        return "키스톤"
    if entry.kind == "unique" or key in library_uniques:
        return "유니크"
    return _KIND_LABELS.get(entry.kind, "기타")


def _seed_builds(entry: patchnotes.PatchEntry, profiles) -> list[str]:
    gem = entry.kind in ("gem", "support") or naming.is_gem_name(entry.name)
    keys = naming.name_keys(entry.name, gem=gem)
    seeds = []
    for build, profile in profiles:
        names = (
            profile.main_skill_names
            + [g.name for g in profile.secondary_skills]
            + profile.support_names
            + profile.uniques
            + ([profile.ascendancy] if profile.ascendancy else [])
            + profile.keystones
        )
        for name in names:
            if keys & naming.name_keys(name, gem=naming.is_gem_name(name)):
                seeds.append(build.name)
                break
    return seeds


def rank_buffs(
    notes: patchnotes.PatchNotes,
    profiles: list | None = None,
    *,
    top: int | None = None,
    min_score: float = 0.0,
    kinds: set[str] | None = None,
) -> list[BuffCandidate]:
    profiles = profiles or []
    library_uniques = {
        naming.norm(name) for _, profile in profiles for name in profile.uniques
    }
    rows: list[BuffCandidate] = []
    qualitative_hits = {"now also", "now additionally", "added block", "added line"}
    for entry in notes.entries:
        signal = entry.signal
        if signal.direction not in ("buff", "mixed"):
            continue
        positive = [d for d in signal.deltas if d.benefit_pct > 0]
        qualitative = (
            entry.direction == "buff"
            and not positive
            and bool(qualitative_hits & set(signal.keyword_hits))
        )
        if signal.score < min_score and not qualitative:
            continue
        kind_label = _kind_label(entry, library_uniques)
        if kinds and kind_label not in kinds:
            continue
        rows.append(
            BuffCandidate(
                entry=entry,
                score=signal.score,
                total=sum(d.benefit_pct for d in positive),
                occurrences=max(1, len(positive)),
                kind_label=kind_label,
                seeds=_seed_builds(entry, profiles),
                qualitative=qualitative,
            )
        )
    rows.sort(key=lambda row: (row.score if not row.qualitative else 0.0, row.total), reverse=True)
    return rows[:top] if top else rows
