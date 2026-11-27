"""스타터 빌드 생존 검증: 빌드 구성 요소 ↔ 패치노트 항목 매칭."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import naming, patchnotes, pob

VERDICT_GREEN = "green"
VERDICT_YELLOW = "yellow"
VERDICT_RED = "red"

VERDICT_LABELS = {
    VERDICT_GREEN: "🟢 무사통과",
    VERDICT_YELLOW: "🟡 일부 조정",
    VERDICT_RED: "🔴 핵심 너프 주의",
}

_KIND_LABELS = {
    "main_skill": "주력 스킬",
    "secondary_skill": "보조 스킬",
    "support": "서포트 젬",
    "ascendancy": "전직",
    "keystone": "키스톤",
    "unique": "유니크",
}

# (가중치, 핵심 요소인가?)
_KIND_WEIGHTS = {
    "main_skill": (5.0, True),
    "ascendancy": (4.0, True),
    "unique": (3.0, True),
    "keystone": (3.0, True),
    "secondary_skill": (2.0, False),
    "support": (1.5, False),
}


@dataclass
class Hit:
    entity_kind: str
    entity_name: str
    entry: patchnotes.PatchEntry
    direction: str
    alias: str = ""
    weight: float = 1.0
    core: bool = False

    @property
    def kind_label(self) -> str:
        return _KIND_LABELS.get(self.entity_kind, self.entity_kind)

    @property
    def is_nerf(self) -> bool:
        return self.direction in ("nerf", "mixed")

    @property
    def severity(self) -> str:
        if self.is_nerf and self.core:
            return "critical"
        if self.is_nerf:
            return "minor"
        if self.direction == "buff":
            return "buff"
        return "neutral"

    def describe(self) -> str:
        parts = [f"{self.kind_label} '{self.entity_name}'"]
        if self.alias:
            parts.append(f"({self.alias})")
        label = {"buff": "상향", "nerf": "너프", "mixed": "혼합 조정", "neutral": "변경"}.get(
            self.direction, self.direction
        )
        if self.is_nerf:
            worst = self.entry.signal.worst_delta
            score = worst.benefit_pct if worst else 0.0
        else:
            score = self.entry.signal.score
        magnitude = f" {score:+.1f}%" if score else ""
        return f"{' '.join(parts)} — {label}{magnitude} ← {self.entry.name}"


@dataclass
class BuildVerdict:
    build_id: str
    build_name: str
    profile: pob.BuildProfile
    hits: list[Hit] = field(default_factory=list)
    error: str = ""
    kind_label: str = ""
    origin: str = ""

    @property
    def verdict(self) -> str:
        if self.error:
            return VERDICT_YELLOW
        if any(hit.severity == "critical" for hit in self.hits):
            return VERDICT_RED
        if any(hit.severity in ("minor", "neutral") for hit in self.hits):
            return VERDICT_YELLOW
        return VERDICT_GREEN

    @property
    def label(self) -> str:
        return VERDICT_LABELS[self.verdict]

    @property
    def nerf_hits(self) -> list[Hit]:
        return [h for h in self.hits if h.is_nerf]

    @property
    def buff_hits(self) -> list[Hit]:
        return [h for h in self.hits if h.direction == "buff"]

    def headline(self) -> str:
        if self.error:
            return f"빌드를 읽지 못했습니다: {self.error}"
        nerfs = self.nerf_hits
        if nerfs:
            core = [h for h in nerfs if h.core]
            target = core[0] if core else max(nerfs, key=lambda h: h.weight)
            extra = len(nerfs) - 1
            suffix = f" 외 {extra}건" if extra else ""
            return f"{target.entity_kind and _KIND_LABELS.get(target.entity_kind, '')} '{target.entity_name}' {('너프' if target.direction == 'nerf' else '혼합 조정')}{suffix}"
        changed = [h for h in self.hits if h.severity == "neutral"]
        if changed:
            return f"'{changed[0].entity_name}' 변경(수치 없음) 외 {max(0, len(changed) - 1)}건"
        buffs = self.buff_hits
        if buffs:
            return f"너프 없음 · 상향 {len(buffs)}건"
        return "패치노트에서 관련 변경 없음"

    def matched_lines(self) -> list[tuple[Hit, list[str]]]:
        out = []
        seen = set()
        for hit in sorted(self.hits, key=lambda h: (not h.core, -h.weight)):
            key = id(hit.entry)
            if key in seen:
                continue
            seen.add(key)
            out.append((hit, hit.entry.display_lines(limit=10)))
        return out


def _entry_keys(entry: patchnotes.PatchEntry) -> frozenset:
    gem = entry.kind in ("gem", "support") or naming.is_gem_name(entry.name)
    return naming.name_keys(entry.name, gem=gem)


def _match_entries(profile: pob.BuildProfile, notes: patchnotes.PatchNotes) -> list[Hit]:
    entities: list[tuple[str, str]] = []
    for gem in profile.main_skills:
        entities.append(("main_skill", gem.name))
    for gem in profile.secondary_skills:
        entities.append(("secondary_skill", gem.name))
    for gem in profile.supports:
        entities.append(("support", gem.name))
    if profile.ascendancy:
        entities.append(("ascendancy", profile.ascendancy))
    for keystone in profile.keystones:
        entities.append(("keystone", keystone))
    for unique in profile.uniques:
        entities.append(("unique", unique))

    entity_keys = []
    for kind, name in entities:
        gem = kind in ("main_skill", "secondary_skill", "support")
        entity_keys.append((kind, name, naming.name_keys(name, gem=gem)))

    hits: list[Hit] = []
    for entry in notes.entries:
        keys = _entry_keys(entry)
        if not keys:
            continue
        for kind, name, ekeys in entity_keys:
            if not (keys & ekeys):
                continue
            weight, core = _KIND_WEIGHTS.get(kind, (1.0, False))
            exact = naming.norm(name) in keys
            alias = "" if exact else "기본 이름 일치"
            hits.append(
                Hit(
                    entity_kind=kind,
                    entity_name=name,
                    entry=entry,
                    direction=entry.direction,
                    alias=alias,
                    weight=weight,
                    core=core,
                )
            )
    hits.sort(key=lambda h: (not h.core, -h.weight, h.direction != "nerf"))
    return hits


def check_build(entry, profile: pob.BuildProfile, notes: patchnotes.PatchNotes) -> BuildVerdict:
    verdict = BuildVerdict(
        build_id=getattr(entry, "id", ""),
        build_name=getattr(entry, "name", profile.name),
        profile=profile,
        kind_label=getattr(entry, "kind_label", ""),
        origin=getattr(entry, "origin", ""),
    )
    verdict.hits = _match_entries(profile, notes)
    return verdict


def check_library(library, notes: patchnotes.PatchNotes,
                  game: str | None = None) -> list[BuildVerdict]:
    results: list[BuildVerdict] = []
    for build, profile in library.profiles(game):
        results.append(check_build(build, profile, notes))
    for build_id, message in library.errors.items():
        build = library.get(build_id)
        if not build:
            continue
        results.append(
            BuildVerdict(
                build_id=build.id,
                build_name=build.name,
                profile=pob.BuildProfile(name=build.name, game=build.game),
                error=message,
                kind_label=build.kind_label,
                origin=build.origin,
            )
        )
    order = {VERDICT_RED: 0, VERDICT_YELLOW: 1, VERDICT_GREEN: 2}
    results.sort(key=lambda v: (order.get(v.verdict, 3), -len(v.nerf_hits), v.build_name))
    return results
