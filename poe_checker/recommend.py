"""콘텐츠 적합도와 「이번 패치 추천 스타터」.

- 내장 36종 스타터는 `data/starter_profiles.json` 의 큐레이션 점수(1~5)를 쓴다.
- 사용자가 직접 추가한 PoB 는 PoB 스탯(EHP·DPS)과 주력 스킬 태그로 적합도를 추정한다.
- 추천 점수 = 콘텐츠 적합도 + 이번 패치의 버프/너프·생존 판정 보정.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache

from . import datafiles, pob

FIELDS = (
    ("mapping", "맵핑"),
    ("bossing", "보스"),
    ("tankiness", "탱킹"),
    ("budget", "저자본"),
    ("ease", "편한 조작"),
)
FIELD_KEYS = tuple(key for key, _ in FIELDS)

CATEGORY_LABELS = {
    "allrounder": "올라운더 추천 TOP",
    "mapping": "맵핑 특화",
    "bossing": "보스 특화",
    "budget": "저자본·편한 손맛",
}
CATEGORY_ORDER = ("allrounder", "mapping", "bossing", "budget")

VERDICT_RANK = {"green": 0, "yellow": 1, "red": 2}

_TAG_LABELS = {
    "minion": "소환수", "totem": "토템", "aura": "오라", "herald": "전령",
    "curse": "저주", "hex": "사술", "golem": "골렘", "movement": "이동기",
    "warcry": "함성", "trigger": "트리거", "banner": "깃발", "guard": "수호",
    "link": "연결", "stance": "태세", "offering": "제물", "trap": "함정",
    "mine": "지뢰", "melee": "근접", "bow": "활", "projectile": "투사체",
    "spell": "주문", "attack": "공격", "area": "광역", "channelling": "채널링",
    "duration": "지속시간", "strike": "타격", "slam": "강타", "nova": "폭발",
    "chaining": "연쇄", "vaal": "바알", "critical": "치명타",
}

_TAG_PRIORITY = (
    "minion", "totem", "aura", "trigger", "trap", "mine", "warcry", "curse",
    "melee", "bow", "projectile", "spell", "area", "channelling", "slam",
    "strike", "duration", "chaining", "nova", "movement",
)


def _clamp(value: float, low: int = 1, high: int = 5) -> int:
    return max(low, min(high, int(round(value))))


@dataclass
class ContentFit:
    mapping: int = 3
    bossing: int = 3
    tankiness: int = 3
    budget: int = 3
    ease: int = 3
    tags: tuple[str, ...] = ()
    note: str = ""
    auto: bool = False

    def score(self, key: str) -> int:
        return int(getattr(self, key, 3))

    def as_dict(self) -> dict:
        out = {key: self.score(key) for key in FIELD_KEYS}
        out.update({"tags": list(self.tags), "note": self.note, "auto": self.auto})
        return out

    def as_guide_fit(self):
        from .guide import FitInfo  # 순환 import 방지

        return FitInfo(
            mapping=self.mapping,
            bossing=self.bossing,
            tankiness=self.tankiness,
            budget=self.budget,
            ease=self.ease,
            tags=self.tags,
            note=self.note,
            auto=self.auto,
        )

    def stars(self, key: str) -> str:
        value = self.score(key)
        return "★" * value + "☆" * (5 - value)


# ---------------------------------------------------------------------------
# 큐레이션 프로필
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_profiles() -> dict[str, ContentFit]:
    path = datafiles.DATA_DIR / "starter_profiles.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, ContentFit] = {}
    for build_id, row in (data.get("builds") or {}).items():
        values = {key: _clamp(row.get(key, 3)) for key in FIELD_KEYS}
        out[build_id] = ContentFit(
            **values,
            tags=tuple(row.get("tags") or ()),
            note=row.get("note", ""),
            auto=False,
        )
    return out


def clear_cache() -> None:
    load_profiles.cache_clear()


# ---------------------------------------------------------------------------
# 커스텀 PoB 자동 추정
# ---------------------------------------------------------------------------

def _skill_tags(profile: pob.BuildProfile) -> set[str]:
    tags: set[str] = set()
    gems = list(profile.main_skills) or list(profile.secondary_skills)
    for gem in gems:
        tags.update(gem.tags)
    return tags


def _tag_labels(tags: set[str], *, dot_share: float, dps: float, dot: float) -> tuple[str, ...]:
    labels: list[str] = []
    for key in _TAG_PRIORITY:
        if key in tags and _TAG_LABELS[key] not in labels:
            labels.append(_TAG_LABELS[key])
        if len(labels) >= 4:
            break
    if dot > 0 and dot_share >= 0.6 and "지속 피해" not in labels:
        labels.insert(0, "지속 피해")
    elif dps > 0 and dot_share < 0.4 and "직접 타격" not in labels:
        labels.append("직접 타격")
    return tuple(labels[:4])


def estimate_fit(profile: pob.BuildProfile) -> ContentFit:
    """PoB 스탯·스킬 태그로 커스텀 빌드의 콘텐츠 적합도를 추정한다."""
    tags = _skill_tags(profile)
    ehp = profile.ehp
    dps = profile.dps
    dot = profile.dot_dps
    dot_share = dot / dps if dps > 0 else 0.0

    if ehp and math.isinf(ehp):
        tankiness = 5
    elif ehp >= 120_000:
        tankiness = 5
    elif ehp >= 70_000:
        tankiness = 4
    elif ehp >= 40_000:
        tankiness = 3
    elif ehp >= 20_000:
        tankiness = 2
    elif ehp > 0:
        tankiness = 1
    else:
        tankiness = 3

    if dps >= 5_000_000:
        bossing = 5
    elif dps >= 2_000_000:
        bossing = 4
    elif dps >= 800_000:
        bossing = 3
    elif dps >= 300_000:
        bossing = 2
    elif dps > 0:
        bossing = 1
    else:
        bossing = 3

    mapping = 3.0
    if tags & {"area", "projectile", "chaining", "nova"}:
        mapping += 1.0
    if tags & {"minion", "totem", "aura"}:
        mapping += 0.5
    if dot_share >= 0.6:
        mapping += 0.5
    if dps >= 5_000_000:
        mapping += 0.5

    budget = 5.0
    uniques = len(profile.uniques)
    budget -= 0.5 * max(0, uniques - 2)
    if uniques >= 6:
        budget -= 0.5
    if (profile.level or 0) >= 95:
        budget -= 0.5

    ease = 3.0
    if tags & {"minion", "totem", "aura", "trigger"}:
        ease += 1.0
    if "melee" in tags and not (tags & {"minion", "totem"}):
        ease -= 0.5
    if "channelling" in tags:
        ease -= 0.5
    if tankiness >= 4:
        ease += 0.5

    labels = _tag_labels(tags, dot_share=dot_share, dps=dps, dot=dot)
    note_bits = []
    if ehp:
        note_bits.append(f"EHP {ehp:,.0f}")
    if dps:
        note_bits.append(f"PoB DPS {dps:,.0f}")
    if uniques:
        note_bits.append(f"유니크 {uniques}개")
    note = "PoB 스탯·스킬 태그로 자동 추정"
    if note_bits:
        note += " (" + ", ".join(note_bits) + ")"
    return ContentFit(
        mapping=_clamp(mapping),
        bossing=_clamp(bossing),
        tankiness=_clamp(tankiness),
        budget=_clamp(budget),
        ease=_clamp(ease),
        tags=labels,
        note=note,
        auto=True,
    )


def fit_for(build_id: str, profile: pob.BuildProfile | None = None) -> ContentFit:
    curated = load_profiles().get(build_id)
    if curated is not None:
        return curated
    if profile is not None:
        return estimate_fit(profile)
    return ContentFit(note="적합도 정보 없음", auto=True)


# ---------------------------------------------------------------------------
# 패치 보정 · 추천
# ---------------------------------------------------------------------------

def _hit_magnitude(hit) -> float:
    if hit.is_nerf:
        worst = hit.entry.signal.worst_delta
        return abs(worst.benefit_pct) if worst else 0.0
    return abs(getattr(hit.entry.signal, "score", 0.0) or 0.0)


def patch_delta(verdict) -> float:
    """패치 생존 + 버프/너프 크기를 -4~+4 점으로 환산한다."""
    if getattr(verdict, "error", ""):
        return -3.0
    gain = loss = 0.0
    for hit in verdict.hits:
        magnitude = min(_hit_magnitude(hit), 60.0)
        weight = 1.0 + (hit.weight / 5.0)
        if hit.direction == "buff":
            gain += magnitude / 25.0 * weight
        elif hit.direction in ("nerf", "mixed"):
            loss += magnitude / 25.0 * weight
    base = {"green": 1.2, "yellow": 0.0, "red": -2.5}.get(verdict.verdict, 0.0)
    return round(max(-4.0, min(4.0, base + gain - loss)), 2)


def category_base(category: str, fit: ContentFit) -> float:
    m, b, t = fit.mapping, fit.bossing, fit.tankiness
    e, u = fit.ease, fit.budget
    if category == "mapping":
        return 0.55 * m + 0.20 * e + 0.15 * t + 0.10 * b
    if category == "bossing":
        return 0.55 * b + 0.20 * t + 0.15 * m + 0.10 * e
    if category == "budget":
        return 0.45 * u + 0.35 * e + 0.20 * t
    return 0.40 * m + 0.30 * b + 0.20 * t + 0.10 * e


@dataclass
class Recommendation:
    build_id: str
    build_name: str
    game: str
    kind_label: str
    origin: str
    verdict: str
    verdict_label: str
    headline: str
    fit: ContentFit
    patch_delta: float
    buffs: int = 0
    nerfs: int = 0
    error: str = ""
    scores: dict[str, float] = field(default_factory=dict)

    def score_for(self, category: str) -> float:
        return self.scores.get(category, 0.0)

    def reason_for(self, category: str) -> str:
        fit = self.fit
        if category == "mapping":
            basis = f"맵핑 {fit.mapping} · 편한 조작 {fit.ease} · 탱킹 {fit.tankiness}"
        elif category == "bossing":
            basis = f"보스 {fit.bossing} · 탱킹 {fit.tankiness} · 맵핑 {fit.mapping}"
        elif category == "budget":
            basis = f"저자본 {fit.budget} · 편한 조작 {fit.ease} · 탱킹 {fit.tankiness}"
        else:
            basis = f"맵핑 {fit.mapping} · 보스 {fit.bossing} · 탱킹 {fit.tankiness}"
        patch_bits = []
        if self.buffs:
            patch_bits.append(f"상향 {self.buffs}건")
        if self.nerfs:
            patch_bits.append(f"너프 {self.nerfs}건")
        patch_text = f"패치 {self.verdict_label.split(' ', 1)[-1]}"
        if patch_bits:
            patch_text += f"({', '.join(patch_bits)})"
        tags = " · ".join(fit.tags[:3])
        reason = f"{basis} · {patch_text}"
        if self.error:
            reason += f" · ! {self.error}"
        elif tags:
            reason += f" · {tags}"
        return reason

    def to_dict(self) -> dict:
        return {
            "id": self.build_id,
            "name": self.build_name,
            "game": self.game,
            "kind": self.kind_label,
            "origin": self.origin,
            "verdict": self.verdict,
            "label": self.verdict_label,
            "headline": self.headline,
            "fit": self.fit.as_dict(),
            "patch_delta": self.patch_delta,
            "buffs": self.buffs,
            "nerfs": self.nerfs,
            "error": self.error,
            "scores": {key: round(value, 2) for key, value in self.scores.items()},
            "reasons": {key: self.reason_for(key) for key in CATEGORY_ORDER},
        }


@dataclass
class RecommendationBoard:
    game: str
    entries: list[Recommendation] = field(default_factory=list)

    def top(self, category: str, limit: int = 5) -> list[Recommendation]:
        if category not in CATEGORY_ORDER:
            category = "allrounder"
        rows = [entry for entry in self.entries if not entry.error]
        rows.sort(
            key=lambda entry: (
                -entry.score_for(category),
                VERDICT_RANK.get(entry.verdict, 3),
                entry.build_name,
            )
        )
        return rows[:limit]

    def find(self, build_id: str) -> Recommendation | None:
        for entry in self.entries:
            if entry.build_id == build_id:
                return entry
        return None

    def to_dict(self, limit: int = 5) -> dict:
        return {
            "game": self.game,
            "categories": {
                category: {
                    "label": CATEGORY_LABELS[category],
                    "rows": [entry.to_dict() for entry in self.top(category, limit)],
                }
                for category in CATEGORY_ORDER
            },
        }


def build_board(result, lib) -> RecommendationBoard:
    """분석 결과 + 라이브러리 → 추천 보드(게임별)."""
    game = datafiles.normalize_game(getattr(result, "game", datafiles.GAME_POE1))
    verdicts = {verdict.build_id: verdict for verdict in getattr(result, "verdicts", [])}
    board = RecommendationBoard(game=game)
    for build in lib.builds_for(game):
        verdict = verdicts.get(build.id)
        if verdict is None:
            continue
        fit = fit_for(build.id, verdict.profile)
        delta = patch_delta(verdict)
        scores = {
            category: round(category_base(category, fit) + delta, 2)
            for category in CATEGORY_ORDER
        }
        board.entries.append(
            Recommendation(
                build_id=build.id,
                build_name=build.name,
                game=game,
                kind_label=build.kind_label,
                origin=build.origin,
                verdict=verdict.verdict,
                verdict_label=verdict.label,
                headline=verdict.headline(),
                fit=fit,
                patch_delta=delta,
                buffs=len(verdict.buff_hits),
                nerfs=len(verdict.nerf_hits),
                error=verdict.error,
                scores=scores,
            )
        )
    return board


def recommend_rows(board: RecommendationBoard, category: str, limit: int = 10) -> list[tuple[str, ...]]:
    """GUI·CLI 표시용 행(순위, 빌드, 판정, 점수, 적합도 5종, 이유)."""
    rows = []
    for index, entry in enumerate(board.top(category, limit), start=1):
        fit = entry.fit
        rows.append(
            (
                str(index),
                entry.build_name,
                entry.verdict_label,
                f"{entry.score_for(category):.2f}",
                str(fit.mapping),
                str(fit.bossing),
                str(fit.tankiness),
                str(fit.budget),
                str(fit.ease),
                entry.reason_for(category),
            )
        )
    return rows
