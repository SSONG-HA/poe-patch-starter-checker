"""패치노트 문장에서 수치 변화(델타)를 뽑아 방향(버프/너프)과 크기를 계산한다.

지원하는 문장 형태
  - `New: 219 to 329 Added Fire Damage` / `Old: 169 to 254 ...`   (GGG 젬 diff 게시물)
  - `Now deals 2447.9 base Fire Damage per second (previously 2142.6).`
  - `Mana Cost reduced from 12 to 10.`  / `increased from 10% to 15%`
  - `No longer grants ...`, `Now also ...` 같은 정성적 문장
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NUM = r"[-+]?\d+(?:[.,]\d+)?"
# `gem level 20`, `per 100 Intelligence` 같은 수치는 비교 대상이 아니다.
_IGNORE_CTX = re.compile(r"(?:gem level|item level|character level|level|quality|per)\s*$", re.I)
# 수치 뒤에 붙는 `% less` / `% reduced` 는 '감소폭' 비교다.
_REDUCTION_AFTER_RE = re.compile(r"%\s*(?:less|reduced|fewer)\b", re.I)
_RANGE_RE = re.compile(rf"({NUM})\s*(?:%|)\s*(?:to|–|—|-)\s*({NUM})\s*(%?)", re.I)
_PAIR_RE = re.compile(
    rf"\bfrom\s+({NUM})\s*(%?)\s*(?:to|→|->)\s*({NUM})\s*(%?)", re.I
)
_TOKEN_RE = re.compile(rf"({NUM})\s*(%?)")
_PAREN_OLD_RE = re.compile(r"\(\s*previously\s+([^)]*)\)", re.I)

# (지표 이름, 키워드들, 낮을수록 좋은가?)
_METRICS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("mana cost", ("mana cost", "mana costs"), True),
    ("life cost", ("life cost", "life costs"), True),
    ("reservation", ("reservation", "reserves", "reserve "), True),
    ("cooldown recovery", ("cooldown recovery",), False),
    ("cooldown", ("cooldown", "cooldowns"), True),
    ("cast time", ("cast time",), True),
    ("attack time", ("attack time",), True),
    ("interval", ("every", "interval"), True),
    ("attribute requirements", ("attribute requirements", "requirements"), True),
    ("level requirement", ("level requirement",), True),
    ("damage taken", ("damage taken",), True),
    ("cost", ("cost", "costs"), True),
    ("chain", ("chain", "chains", "additional times"), False),
    ("projectile", ("projectile", "projectiles"), False),
    ("area of effect", ("area of effect", "area", "radius"), False),
    ("duration", ("duration",), False),
    ("speed", ("speed", "frequency", "rate"), False),
    ("damage", ("damage", "dps", "damage over time"), False),
    ("life", ("life",), False),
    ("armour", ("armour", "armor"), False),
    ("evasion", ("evasion",), False),
    ("energy shield", ("energy shield",), False),
    ("block", ("block",), False),
    ("resistance", ("resistance", "resistances"), False),
    ("critical", ("critical", "crit"), False),
    ("chance", ("chance",), False),
    ("quality", ("quality",), False),
    ("charges", ("charge", "charges"), False),
    ("regeneration", ("regeneration", "regenerate"), False),
    ("leech", ("leech",), False),
    ("ailment", ("ailment", "ignite", "poison", "bleed"), False),
    ("defences", ("defences", "defense", "defences"), False),
)

_LOWER_IS_BETTER = {m[0] for m in _METRICS if m[2]}


def metric_for(text: str, pos: int | None = None) -> str:
    """문장(또는 pos 주변)에서 수치에 해당하는 지표를 고른다.

    pos 를 주면 그 위치에서 가장 가까운 키워드를 쓴다(앞쪽 우선).
    (예: `60% chance to Block Attack Damage` → damage 가 아니라 block)
    """
    low = text.lower()
    if pos is None:
        pos = len(low)
    best = None
    for name, keywords, _ in _METRICS:
        for kw in keywords:
            start = 0
            while True:
                index = low.find(kw, start)
                if index < 0:
                    break
                distance = (pos - index) if index <= pos else (index - pos) + 150
                if best is None or distance < best[0]:
                    best = (distance, name)
                start = index + 1
    if best is None:
        return "value"
    if best[0] > 260:  # 너무 멀리 있는 키워드는 무시
        return "value"
    return best[1]


@dataclass(frozen=True)
class Delta:
    metric: str
    old: float
    new: float
    unit: str
    benefit_pct: float  # 양수 = 사용자에게 이득(버프), 음수 = 너프
    note: str = ""

    @property
    def direction(self) -> str:
        if self.benefit_pct > 0.5:
            return "buff"
        if self.benefit_pct < -0.5:
            return "nerf"
        return "neutral"

    def describe(self) -> str:
        unit = "%" if self.unit in ("%", "%p") else ""
        return (
            f"{self.metric}: {_fmt(self.old)}{unit} → {_fmt(self.new)}{unit} "
            f"({self.benefit_pct:+.1f}%)"
        )


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def _to_float(text: str) -> float:
    return float(text.replace(",", ""))


@dataclass
class _Num:
    value: float
    unit: str
    is_range: bool = False
    pos: int = 0


def _numbers(text: str) -> list[_Num]:
    found: list[tuple[int, _Num]] = []
    ranges = []
    for m in _RANGE_RE.finditer(text):
        if _IGNORE_CTX.search(text[max(0, m.start() - 18): m.start()]):
            continue
        a, b = _to_float(m.group(1)), _to_float(m.group(2))
        num = _Num((a + b) / 2, m.group(3) or "", True, m.start())
        ranges.append((m.start(), m.end()))
        found.append((m.start(), num))
    for m in _TOKEN_RE.finditer(text):
        if any(s <= m.start() < e for s, e in ranges):
            continue
        if _IGNORE_CTX.search(text[max(0, m.start() - 18): m.start()]):
            continue
        found.append((m.start(), _Num(_to_float(m.group(1)), m.group(2), False, m.start())))
    found.sort(key=lambda pair: pair[0])
    return [num for _, num in found]


def _benefit(metric: str, old: float, new: float, *, reduction: bool = False) -> float:
    """사용자 이득 기준 변화율(%).

    reduction=True 는 `20% less Life` 처럼 '감소폭' 자체를 비교하는 경우다.
    감소폭이 커지면 실효값은 그만큼 줄어든다.
    """
    lower_better = metric in _LOWER_IS_BETTER
    if old == 0:
        if new == 0:
            return 0.0
        sign = 1.0 if new > 0 else -1.0
        return sign if not lower_better else -sign
    raw = (new - old) / abs(old) * 100.0
    if reduction:
        raw = -raw
    return -raw if lower_better else raw


def compare_texts(new_text: str, old_text: str) -> list[Delta]:
    """`New: ...` / `Old: ...` (또는 문장과 `(previously ...)`) 두 문장 비교."""
    new_nums = _numbers(new_text)
    old_nums = _numbers(old_text)
    if not new_nums or not old_nums:
        return []
    deltas = []
    for n, o in zip(new_nums, old_nums):
        if n.is_range != o.is_range:
            continue
        metric = metric_for(new_text, n.pos)
        if metric == "value":
            metric = metric_for(old_text, o.pos)
        unit = n.unit or o.unit
        reduction = bool(_REDUCTION_AFTER_RE.search(new_text[n.pos: n.pos + 26]))
        benefit = _benefit(metric, o.value, n.value, reduction=reduction)
        deltas.append(
            Delta(
                metric=metric,
                old=o.value,
                new=n.value,
                unit=unit,
                benefit_pct=benefit,
                note=new_text.strip(),
            )
        )
    return deltas


def deltas_from_line(line: str) -> list[Delta]:
    """한 줄짜리 문장에서 `from X to Y`, `(previously X)` 형태를 뽑는다."""
    out: list[Delta] = []
    for m in _PAIR_RE.finditer(line):
        old, new = _to_float(m.group(1)), _to_float(m.group(3))
        unit = m.group(2) or m.group(4)
        metric = metric_for(line, m.start())
        reduction = bool(_REDUCTION_AFTER_RE.search(line[m.end(): m.end() + 26]))
        benefit = _benefit(metric, old, new, reduction=reduction)
        out.append(Delta(metric, old, new, unit, benefit, line.strip()))
    if out:
        return out
    m = _PAREN_OLD_RE.search(line)
    if m:
        head = line[: m.start()]
        # "(previously 20%)" 는 앞 수치와 짝을 맞춘다
        new_nums = _numbers(head)
        old_nums = _numbers(m.group(1))
        if new_nums and old_nums:
            metric = metric_for(head, new_nums[-1].pos)
            n, o = new_nums[-1], old_nums[-1]
            unit = n.unit or o.unit
            reduction = bool(_REDUCTION_AFTER_RE.search(head[n.pos: n.pos + 26]))
            benefit = _benefit(metric, o.value, n.value, reduction=reduction)
            out.append(Delta(metric, o.value, n.value, unit, benefit, line.strip()))
    return out


# ---------------------------------------------------------------------------
# 정성적 신호
# ---------------------------------------------------------------------------

KEYWORD_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("no longer", -18.0),
    ("has been removed", -20.0),
    ("have been removed", -20.0),
    ("removed", -16.0),
    ("now also", 12.0),
    ("now additionally", 12.0),
)

UNPAIRED_NEW_WEIGHT = 10.0
UNPAIRED_OLD_WEIGHT = -12.0


def keyword_signal(text: str) -> tuple[float, list[str]]:
    low = text.lower()
    score = 0.0
    hits: list[str] = []
    for phrase, weight in KEYWORD_WEIGHTS:
        if phrase in low:
            score += weight
            hits.append(phrase)
    return score, hits


@dataclass
class EntrySignal:
    """패치노트 항목 하나의 종합 판정."""

    direction: str = "neutral"  # buff / nerf / mixed / neutral / new / removed
    deltas: list[Delta] = field(default_factory=list)
    keyword_hits: list[str] = field(default_factory=list)
    score: float = 0.0  # 최대 이득 % (버프 랭킹용)
    net: float = 0.0  # 합산 이득 % (방향 판정용)

    @property
    def best_delta(self) -> Delta | None:
        if not self.deltas:
            return None
        return max(self.deltas, key=lambda d: d.benefit_pct)

    @property
    def worst_delta(self) -> Delta | None:
        if not self.deltas:
            return None
        return min(self.deltas, key=lambda d: d.benefit_pct)


def summarize(pairs: list[tuple[str, str]], lines: list[str], *, is_new: bool = False,
              removed_block: bool = False, added_block: bool = False,
              unpaired_new: list[str] | None = None,
              unpaired_old: list[str] | None = None) -> EntrySignal:
    signal = EntrySignal()
    for new_text, old_text in pairs:
        signal.deltas.extend(compare_texts(new_text, old_text))
    for line in lines:
        signal.deltas.extend(deltas_from_line(line))
    # 중복 제거(같은 지표·같은 수치)
    seen = set()
    uniq: list[Delta] = []
    for d in signal.deltas:
        key = (d.metric, round(d.old, 4), round(d.new, 4), d.unit)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)
    signal.deltas = uniq

    prose = [line for line in lines if line.strip().lower() not in ("added", "removed", "modified")]
    text = " ".join(prose + [t for pair in pairs for t in pair])
    kw_score, hits = keyword_signal(text)
    if removed_block:
        kw_score -= 18.0
        hits.append("removed block")
    if added_block:
        kw_score += 10.0
        hits.append("added block")
    unpaired_new = unpaired_new or []
    unpaired_old = unpaired_old or []
    if unpaired_new:
        kw_score += UNPAIRED_NEW_WEIGHT * len(unpaired_new)
        hits.append("added line")
    if unpaired_old:
        kw_score += UNPAIRED_OLD_WEIGHT * len(unpaired_old)
        hits.append("removed line")
    signal.keyword_hits = hits

    positives = [d.benefit_pct for d in signal.deltas if d.benefit_pct > 0]
    negatives = [d.benefit_pct for d in signal.deltas if d.benefit_pct < 0]
    signal.score = max(positives) if positives else 0.0
    signal.net = sum(d.benefit_pct for d in signal.deltas) + kw_score

    strong_buff = (max(positives) if positives else 0) >= 8 or (
        not positives and kw_score >= 8
    )
    strong_nerf = (min(negatives) if negatives else 0) <= -8 or "no longer" in hits or (
        not negatives and kw_score <= -8
    )
    if added_block and removed_block and not signal.deltas:
        signal.direction = "mixed"
    elif added_block and removed_block and not (strong_buff or strong_nerf):
        signal.direction = "mixed"
    elif strong_buff and strong_nerf:
        signal.direction = "mixed"
    elif strong_nerf:
        signal.direction = "nerf"
    elif strong_buff:
        signal.direction = "buff"
    elif is_new:
        signal.direction = "new"
    elif removed_block and not added_block:
        signal.direction = "nerf"
    elif added_block and not removed_block:
        signal.direction = "buff"
    elif signal.net > 1:
        signal.direction = "buff"
    elif signal.net < -1:
        signal.direction = "nerf"
    else:
        signal.direction = "neutral"
    return signal
