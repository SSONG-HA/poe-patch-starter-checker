"""콘텐츠 적합도와 「이번 패치 추천 스타터」.

- 내장 36종 스타터는 `data/starter_profiles.json` 의 큐레이션 점수(1~5)를 쓴다.
- 사용자가 직접 추가한 PoB 는 PoB 스탯(EHP·DPS)과 주력 스킬 태그로 적합도를 추정한다.
- 추천 점수 = 콘텐츠 적합도 + 이번 패치의 버프/너프·생존 판정 보정.
- 「고점·전환 추천 (무재육성)」은 맨땅 가성비 대신 **새 캐릭터를 다시 키우지 않고**
  같은 직업/전직으로 상위 빌드로 갈아탈 수 있는지(transition)와 투자 대비 상한선(ceiling)을
  함께 본다. 예: 마녀 → 신성한 유물·CoC 금단의 의식, 레인저 → 독성 혼합물 → 칼날 낙하,
  쉐도우 → 트릭스터/어쌔신 CoC, 머라우더 → RF 치프틴 → 고점 빌드.
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
    "ceiling": "고점·전환 추천 (무재육성)",
    "allrounder": "올라운더 추천 TOP",
    "mapping": "맵핑 특화",
    "bossing": "보스 특화",
    "budget": "저자본·편한 손맛",
}
CATEGORY_ORDER = ("ceiling", "allrounder", "mapping", "bossing", "budget")


# ---------------------------------------------------------------------------
# 고점·전환(무재육성) 큐레이션
# ---------------------------------------------------------------------------
# ceiling   : 투자 대비 도달 가능한 상한(보스·엔드게임 화력) 1~5
# transition: 그 상한까지 **새 캐릭터를 키우지 않고** 같은 직업/전직에서 갈아탈 수 있는가 1~5
# path      : 실제 전환 경로(한국어)

CEILING_BUILDS: dict[str, tuple[int, int, str]] = {
    # -- PoE1 -------------------------------------------------------------
    "rf-chieftain-current": (4, 5, "머라우더 → RF 치프틴 → 제물의 작열 광선 토템 고점"),
    "rf-chieftain-330": (4, 5, "머라우더 → RF 치프틴 → 제물의 작열 광선 토템 고점"),
    "rf-chieftain-pohx": (4, 5, "머라우더 → RF 치프틴 → 제물의 작열 광선 토템 고점"),
    "poison-holy-relic-necro": (4, 5, "마녀 → 성결의 수호자 → CoC 금단의 의식 전환"),
    "dominating-blow-guardian": (5, 4, "템플러 → 가디언 지배의 일격 → 정전기 타격 고점"),
    "tornado-inquisitor": (5, 4, "템플러 → 인퀴지터 회오리바람 완성형"),
    "eviscerate-elementalist": (4, 4, "마녀 → 절개 점화 → 소각·독조 엘리멘탈리스트 전환"),
    "static-strike-guardian": (5, 4, "템플러 → 가디언 정전기 타격 고점"),
    "poison-concoction-pathfinder": (3, 5, "레인저 → 독성 혼합물 → 칼날 낙하(관통) 전환"),
    "bladefall-impaling-pathfinder": (5, 4, "레인저 → 칼날 낙하 관통 패스파인더 고점"),
    "cold-dot-spellslinger-elementalist": (3, 4, "마녀 → 냉기 도트 → 독조·CoC 전환"),
    "stormburst-totem-hierophant": (5, 3, "템플러 → 히에로판트 폭풍 파열 토템 고점"),
    "incinerate-venting-elementalist": (3, 3, "마녀 → 소각 분출 → 독조 엘리멘탈리스트 상위"),
    "animate-weapon-ranged-necromancer": (4, 4, "마녀 → 무기 소환 → 신성한 유물·소환수 고점"),
    "generals-cry-lacerate-champion": (3, 2, "듀얼리스트 → 챔피언 절단 (상한 낮음)"),
    "static-strike-slayer": (4, 3, "듀얼리스트 → 슬레이어 정전기 타격 고점"),
    "smite-armor-stacker-luminary": (4, 3, "스키온 → 루미너리 방어구 중첩 고점"),
    "arc-crab-totems-reliquarian": (3, 3, "스키온 → 렐리퀘리안 게 토템 안정형"),
    "explosive-arrow-ballista-hierophant": (4, 3, "템플러 → 히에로판트 발리스타 고점"),
    "boneshatter-juggernaut": (3, 3, "머라우더 → 저거너트 뼈 분쇄 → 치프틴 RF 전환(전직 리셋)"),
    "luminary-merc-aurabit": (3, 2, "스키온 → 루미너리 오라봇 (파티 시너지형)"),
    "coc-forbidden-rite-assassin": (5, 5, "쉐도우 → 어쌔신·트릭스터 CoC 금단의 의식"),
    "impending-doom-elementalist": (5, 3, "마녀 → 독조 엘리멘탈리스트 고점"),
    "dual-strike-gladiator": (5, 3, "듀얼리스트 → 글래디에이터 쌍수 타격 고점"),
    # -- PoE2 -------------------------------------------------------------
    "poe2-spark-stormweaver": (4, 4, "소서리스 → 스톰위버 전기불꽃 고점"),
    "poe2-permafrost-witchhunter": (4, 3, "용병 → 위치헌터 영구 동토 상위"),
    "poe2-explosive-grenade-witchhunter": (4, 4, "용병 → 위치헌터 수류탄 → 영구 동토·폭발 화살 전환"),
    "poe2-martial-artist-monk": (3, 5, "몽크 레벨링 → 낙뢰 무술가 그대로 전환"),
    "poe2-falling-thunder-monk": (4, 4, "몽크 → 무술가 낙뢰 고점"),
    "poe2-ice-strike-amazon": (4, 3, "헌트리스 → 아마존 얼음 타격 고점"),
    "poe2-chaos-flicker-chayula": (4, 3, "몽크 → 차율라 아콜라이트 혼돈 섬광 고점"),
    "poe2-pathfinder-spark": (3, 4, "레인저 → 패스파인더 전기불꽃 전환"),
    "poe2-twister-gemling": (4, 3, "용병 → 보석병 회오리 고점"),
    "poe2-gemling-twister": (4, 3, "용병 → 보석병 회오리 고점"),
    "poe2-minion-infernalist": (3, 4, "마녀 → 인퍼널리스트 소환수 상위"),
    "poe2-lightning-spear-tactician": (5, 3, "용병 → 택티션 번개 창 고점"),
}

# 큐레이션에 없는 빌드(직접 추가·라이브 수집)의 전환 잠재력 — 직업 계열 기준.
CLASS_TRANSITION: dict[str, tuple[int, int, str]] = {
    "witch": (4, 5, "마녀 계열 → 신성한 유물·CoC 금단의 의식 등 상위 전환"),
    "shadow": (5, 5, "쉐도우 계열 → 트릭스터·어쌔신 CoC 상위 전환"),
    "ranger": (4, 5, "레인저 계열 → 칼날 낙하·독성 혼합물 상위 전환"),
    "marauder": (4, 5, "머라우더 계열 → RF 치프틴 등 상위 전환"),
    "templar": (4, 4, "템플러 계열 → 히에로판트·인퀴지터 상위 전환"),
    "duelist": (4, 3, "듀얼리스트 계열 → 슬레이어·글래디에이터 상위 전환"),
    "scion": (4, 4, "스키온 계열 → 루미너리·렐리퀘리안 상위 전환"),
    "sorceress": (4, 4, "소서리스 계열 → 스톰위버 상위 전환"),
    "mercenary": (4, 4, "용병 계열 → 위치헌터·보석병·택티션 상위 전환"),
    "monk": (4, 4, "몽크 계열 → 무술가·차율라 상위 전환"),
    "huntress": (3, 4, "헌트리스 계열 → 아마존 상위 전환"),
    "warrior": (4, 4, "전사 계열 → 타이탄 상위 전환"),
}


def _ceiling_for_build(build_id: str) -> tuple[int, int, str] | None:
    return CEILING_BUILDS.get(build_id)


def _transition_for_profile(profile: pob.BuildProfile) -> tuple[int, int, str]:
    """직업명으로 전환 잠재력을 찾는다(없으면 중립 3/3)."""
    for key in (profile.class_name, profile.ascendancy):
        row = CLASS_TRANSITION.get((key or "").strip().lower())
        if row:
            return row
    return (3, 3, "")

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
    ceiling: int = 3
    transition: int = 3
    path: str = ""
    tags: tuple[str, ...] = ()
    note: str = ""
    auto: bool = False

    def score(self, key: str) -> int:
        return int(getattr(self, key, 3))

    def as_dict(self) -> dict:
        out = {key: self.score(key) for key in FIELD_KEYS}
        out.update(
            {
                "stars": {key: self.stars(key) for key in FIELD_KEYS},
                "ceiling": self.ceiling,
                "transition": self.transition,
                "path": self.path,
                "tags": list(self.tags),
                "note": self.note,
                "auto": self.auto,
            }
        )
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
        ceiling, transition, path = CEILING_BUILDS.get(build_id, (3, 3, ""))
        out[build_id] = ContentFit(
            **values,
            ceiling=_clamp(ceiling),
            transition=_clamp(transition),
            path=path,
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


def _estimate_ceiling(*, dps: float, ehp: float, tags: set[str]) -> int:
    """PoB 스탯으로 도달 상한(엔드게임 화력)을 어림한다."""
    if dps and math.isinf(dps):
        return 5
    if dps >= 20_000_000:
        return 5
    if dps >= 6_000_000:
        return 4
    if dps >= 1_500_000:
        return 3
    if dps >= 400_000:
        return 2
    if dps > 0:
        return 1
    # DPS 미기재(소환수·오라 등)는 생존력과 태그로 대신 본다.
    if ehp and (math.isinf(ehp) or ehp >= 100_000):
        return 4
    if tags & {"minion", "aura", "totem"}:
        return 3
    return 2


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
    ceiling = _estimate_ceiling(dps=dps, ehp=ehp, tags=tags)
    _class_ceiling, trans_floor, path = _transition_for_profile(profile)
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
        ceiling=_clamp(ceiling),
        transition=_clamp(trans_floor),
        path=path,
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
    if category == "ceiling":
        # 무재육성 전환 가능성 + 도달 상한(보스 화력)을 가장 크게 본다.
        return 0.45 * fit.ceiling + 0.35 * fit.transition + 0.20 * b
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
        if category == "ceiling":
            basis = f"고점 {fit.ceiling} · 무재육성 전환 {fit.transition}"
            if fit.path:
                basis += f" · {fit.path}"
        elif category == "mapping":
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
            "ceiling": self.fit.ceiling,
            "transition": self.fit.transition,
            "path": self.fit.path,
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
