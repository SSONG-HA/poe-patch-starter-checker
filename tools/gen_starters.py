"""starters.json v2 생성 (개발용). pobb.in 코드를 data/builds 로 복사하고 목록을 만든다."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

BUILDS = Path("poe_checker/data/builds")
CODES = Path("work/codes")

# (id, 표시 이름, 종류, 게임, 출처(크리에이터/리그), pobb.in 코드, 설명)
ENTRIES = [
    # ---- 내 캐릭터 ----
    ("rf-chieftain-current", "작열 광선 RF 치프틴 (내 캐릭터 · 최신)", "character", "poe1",
     "내 빌드 · 2026-11-27", "OWo-55L1tWbA",
     "정우 님 95레벨 치프틴 최신 PoB(2026-11-27 15:27 점검본). 제물의 작열 광선 토템 + RF."),
    ("rf-chieftain-330", "작열 광선 RF 치프틴 (내 캐릭터 · 11-24)", "character", "poe1",
     "내 빌드 · 2026-11-24", "5VPv477qQmkr",
     "2026-11-24 갱신본. 제웅 4부위, 방패 Hate Ward, 3.30 트리."),
    # ---- PoE1 3.30 리그 스타터 ----
    ("rf-chieftain-pohx", "RF 치프틴 (Pohx SRI)", "starter", "poe1",
     "Pohx · 3.30", "Y6jHZomP3qPi",
     "Pohx의 3.30 RF 로드아웃. 코드 저장 시점 트리 표기는 3_29."),
    ("poison-holy-relic-necro", "중독 신성한 유물 네크로맨서 (Bula)", "starter", "poe1",
     "Bula · 3.30", "Na035hGPLxLx",
     "중독 신성한 유물 + 강철의 창. 트리 표기 3_29."),
    ("dominating-blow-guardian", "지배의 일격 가디언 (ArminYou)", "starter", "poe1",
     "ArminYou · 3.30", "1oDia2RSD4ku",
     "Dominating Blow of Inspiring + 소환수. 트리 표기 3_29."),
    ("tornado-inquisitor", "회오리바람 인퀴지터 (BalorMage)", "starter", "poe1",
     "BalorMage · 3.30", "GtWMZtty-7o2",
     "Tornado of Elemental Turbulence + Rathpith. 트리 표기 3_29."),
    ("eviscerate-elementalist", "절개 점화 엘리멘탈리스트 (Desmo Saze)", "starter", "poe1",
     "Desmo Saze · 3.30", "EaARfgbK7QYl",
     "Eviscerate 점화, Ephemeral Edge. 트리 표기 3_29."),
    ("static-strike-guardian", "정전기 타격 가디언 (Alohaa)", "starter", "poe1",
     "Alohaa · 3.30", "0rKXrao_8pGM",
     "Static Strike + Shockwave 가디언. 3.29 트리로 저장된 3.30 가이드 PoB."),
    ("poison-concoction-pathfinder", "독성 혼합물 패스파인더 (DapperDD)", "starter", "poe1",
     "DapperDD · 3.30", "Pb1QziUGW5SQ",
     "Poisonous Concoction of Bouncing 리그 스타터."),
    ("bladefall-impaling-pathfinder", "칼날 낙하 관통 패스파인더 (DapperDD 교체)", "starter", "poe1",
     "DapperDD · 3.30", "Vt2dSIJuurwn",
     "Bladefall of Impaling 우버 보스용 교체 로드아웃."),
    ("cold-dot-spellslinger-elementalist", "냉기 도트 스펠슬링어 엘리멘탈리스트 (Jungroan)", "starter", "poe1",
     "Jungroan · 3.30", "AadCGMhml9fa",
     "Creeping Frost of Floes + Vortex 냉기 도트. 트리 표기 3_28."),
    ("stormburst-totem-hierophant", "폭풍 파열 토템 히에로판트 (aer0)", "starter", "poe1",
     "aer0 / Palsteron · 3.30", "4SpZG4IzZogq",
     "Storm Burst 토템 + Singularity. 트리 표기 3_29."),
    ("incinerate-venting-elementalist", "소각 분출 엘리멘탈리스트 (smokie_777)", "starter", "poe1",
     "smokie_777 · 3.30", "WBamNpUW03yL",
     "Incinerate of Venting SSF 우버 대응 빌드. 트리 표기 3_29."),
    ("animate-weapon-ranged-necromancer", "무기 소환 원거리 네크로맨서 (3.30)", "starter", "poe1",
     "3.30 인기 스타터 · poe.ninja 5위", "rtTLjTEh1ky0",
     "Animate Weapon of Ranged Arms + Feeding Frenzy."),
    ("generals-cry-lacerate-champion", "장군의 함성 절단 챔피언 (3.30)", "starter", "poe1",
     "3.30 검증 스타터", "1TONbRrNbM-w",
     "General's Cry + Lacerate of Butchering 챔피언."),
    ("static-strike-slayer", "정전기 타격 슬레이어 (3.30)", "starter", "poe1",
     "3.30 가이드 (트리 3_28)", "OJJy1ScEuDhH",
     "Static Strike 슬레이어 리그 스타터."),
    ("smite-armor-stacker-luminary", "강타 방어구 중첩 루미너리 (3.30)", "starter", "poe1",
     "3.30 검증 스타터", "dx239avt6A-O",
     "Smite + 방어구 중첩 루미너리(Scion)."),
    ("arc-crab-totems-reliquarian", "연쇄 번개 게 토템 렐리퀘리안 (3.30)", "starter", "poe1",
     "3.30 신 전직 스타터", "ZBb8nQQsiT7O",
     "Reliquarian + Arc 토템(3.30 신규 전직)."),
    ("explosive-arrow-ballista-hierophant", "폭발 화살 발리스타 히에로판트 (3.30)", "starter", "poe1",
     "POEGuy · 3.30", "zY5__MKcIUfb",
     "Explosive Arrow + Ballista Totem."),
    ("boneshatter-juggernaut", "뼈 분쇄 저거너트 (Zizaran)", "starter", "poe1",
     "Zizaran · 3.30", "qRFk_VlQJyRx",
     "Boneshatter of Complex Trauma 저거너트. 트리 표기 3_29."),
    ("luminary-merc-aurabit", "루미너리 오라봇 (3.30)", "starter", "poe1",
     "3.30 검증 스타터", "ebkcWV8iQUgW",
     "Luminary(Scion) 오라봇 + Flame Link."),
    # ---- 시드/엔드게임 (직접 제작 PoB) ----
    ("coc-forbidden-rite-assassin", "CoC 금단의 의식 어쌔신 (MrJim 저예산)", "seed", "poe1",
     "MrJim · 3.30", None, "CoC Forbidden Rite of Soul Sacrifice CHEAP. 트리 3_30."),
    ("impending-doom-elementalist", "독조 엘리멘탈리스트 (Doom Blast)", "seed", "poe1",
     "직접 제작 PoB", None, "Foulborn Doedre's Scorn + Impending Doom 30레벨."),
    ("dual-strike-gladiator", "쌍수 타격 글래디에이터 (Ephemeral Edge)", "seed", "poe1",
     "직접 제작 PoB", None, "Dual Strike of Ambidexterity + Ephemeral Edge."),
    # ---- PoE2 0.5 스타터 ----
    ("poe2-spark-stormweaver", "전기불꽃 스톰위버 (animeprincess)", "poe2", "poe2",
     "animeprincess · PoE2 0.5", "lvfQVOByE12P",
     "Spark + Orb of Storms + CoC Comet 스톰위버 리그 스타터."),
    ("poe2-permafrost-witchhunter", "영구 동토 탄환 위치헌터 (Chem)", "poe2", "poe2",
     "Chem · PoE2 0.5", "0jY6QStgCiF7",
     "Permafrost Bolts + Fragmentation Rounds 위치헌터(석궁)."),
    ("poe2-explosive-grenade-witchhunter", "폭발 수류탄 위치헌터 (0.5)", "poe2", "poe2",
     "Hayura / 0.5 수류탄 스타터", "_ZU_HFdera9X",
     "Explosive Grenade + Explosive Shot 수류탄 위치헌터."),
    ("poe2-martial-artist-monk", "무술가 몽크 레벨링 (Ghost Activity)", "poe2", "poe2",
     "Ghost Activity · PoE2 0.5", "ttCJAV3WX9bn",
     "Whirling Assault → Falling Thunder 무술가 몽크 레벨링 플랜."),
    ("poe2-falling-thunder-monk", "낙뢰 무술가 몽크 (Spraahz)", "poe2", "poe2",
     "Spraahz · PoE2 0.5", "pKT6y4260FdA",
     "Ice Strike + Falling Thunder 하이브리드 크리 무술가."),
    ("poe2-ice-strike-amazon", "얼음 타격 아마존 (Taaki)", "poe2", "poe2",
     "Taaki · PoE2 0.5", "OKQOruaZYWcX",
     "Ice Strike + Shattering Palm 아마존 리그 스타터."),
    ("poe2-chaos-flicker-chayula", "혼돈 섬광 아콜라이트 (0.5)", "poe2", "poe2",
     "PoE2 0.5 차율라 몽크", "atwLUF9Q_GEo",
     "Flicker Strike + Tempest Bell 혼돈 전환 아콜라이트 오브 차율라."),
    ("poe2-pathfinder-spark", "전기불꽃 패스파인더 (0.5)", "poe2", "poe2",
     "PoE2 0.5 패스파인더 스파크", "k1_vEjHL-zZO",
     "Spark + CoC Comet + Spellslinger 패스파인더."),
    ("poe2-twister-gemling", "회오리 보석병 (snoobae85)", "poe2", "poe2",
     "snoobae85 · PoE2 0.5", "e-WNTOnCq5EC",
     "Twister + Whirling Slash 보석병 군단병."),
    ("poe2-gemling-twister", "회오리 보석병 (mwExile)", "poe2", "poe2",
     "mwExile · PoE2 0.5", "rPuAWBzQfEgX",
     "Twister 보석병 군단병 두 번째 로드아웃."),
    ("poe2-minion-infernalist", "소환수 인퍼널리스트 (Thyworm SSF)", "poe2", "poe2",
     "Thyworm · PoE2 0.5", "_hUlac12nFNX",
     "Summon Infernal Hound + Skeletal Warrior 소환수 SSF 스타터."),
    ("poe2-lightning-spear-tactician", "번개 창 택티션 (Snap)", "poe2", "poe2",
     "Snap · PoE2 0.5", "PbvuVbm_kQdL",
     "Lightning Spear + Armour Break 택티션."),
]

LOCAL = {
    "coc-forbidden-rite-assassin": "builds/coc-forbidden-rite-assassin.txt",
    "impending-doom-elementalist": "builds/impending-doom-elementalist.xml",
    "dual-strike-gladiator": "builds/dual-strike-gladiator.xml",
}


def main() -> None:
    rows = []
    for build_id, name, kind, game, origin, code, note in ENTRIES:
        row = {"id": build_id, "name": name, "kind": kind, "game": game,
               "origin": origin, "note": note}
        if code:
            src = CODES / f"{code}.txt"
            target = BUILDS / f"{build_id}.txt"
            if src.exists():
                shutil.copyfile(src, target)
            elif not target.exists():
                raise SystemExit(f"missing code {code}")
            row["source"] = f"https://pobb.in/{code}"
            row["code_file"] = f"builds/{build_id}.txt"
        else:
            row["source"] = LOCAL[build_id]
            row["code_file"] = LOCAL[build_id]
        rows.append(row)
    payload = {
        "schema": 2,
        "updated": "2026-11-27",
        "note": ("PoE1 3.30(Covens of Umbra) 리그 스타터·내 빌드 + PoE2 0.5(Runes of Aldur) 스타터. "
                 "code_file 은 poe_checker/data 기준 상대경로이며 pobb.in 코드/직접 만든 PoB XML 이다. "
                 "'origin' 은 만든 사람·리그, 'note' 는 구성 요약."),
        "builds": rows,
    }
    Path("poe_checker/data/starters.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", len(rows), "builds")


if __name__ == "__main__":
    main()
