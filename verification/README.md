# 검증 기록 (2026-11-27)

모든 결과는 `python3 main.py ...` 실행으로 생성된 실제 출력이다.

## 1. 실제 GGG 스레드 — New and Changed Gems (view-thread/4013898)

```bash
python3 main.py --patch-url "https://www.pathofexile.com/forum/view-thread/4013898" \
  --top 10 --out verification/live-gem-thread-report.txt --json verification/live-gem-thread.json
```

* 항목 9개 파싱 (Flame Link, Summon Flame/Stone/Lightning Golem, Dark Bargain, Pact of Beidat, Winter Orb, Transfusion Support, Vaal Sacrifice Support)
* 판정: 🔴 0 · 🟡 3 · 🟢 6
  * 🟡 독조 엘리멘탈리스트 — Summon Flame/Stone/Lightning Golem 너프(-25%/-20%/-20%)
  * 🟡 절개 점화 엘리멘탈리스트 — 같은 골렘 너프
  * 🟡 중독 신성한 유물 네크로맨서 — Summon Stone Golem 너프
  * 나머지 6개(RF 2종, CoC 금단의 의식, 회오리바람, 지배의 일격, 쌍수 타격)는 관련 항목 없음
* 상향 TOP 1: Flame Link +29.6% (추가 화염 피해 169–254 → 219–329, 혼합)

## 2. 실제 GGG 스레드 — Thread Difficulty and League Mechanic Changes (view-thread/4016267)

```bash
python3 main.py --patch-url "https://www.pathofexile.com/forum/view-thread/4016267" --top 5 \
  --out verification/live-league-mechanics-report.txt
```

* 젬·유니크 이름이 붙은 항목이 없는 안내문 → 항목 0개
* 결과 상단에 ⚠ 경고 출력(0건을 "변경 없음" 근거로 쓰지 말라는 안내)

## 3. 합성 패치노트(Skills / Support Gems / Unique Items / Passive Tree)

```bash
python3 main.py --patch-file tests/fixtures/patch_notes_synthetic_full.txt --top 8 \
  --out verification/synthetic-full-report.txt --json verification/synthetic-full.json
```

* 항목 23개 · 🔴 5 · 🟡 3 · 🟢 1
  * 🔴 RF 치프틴 2종 — 주력 Righteous Fire 너프 + Nebulis 너프
  * 🔴 독조 엘리 — 키스톤 Mind Over Matter 너프
  * 🔴 회오리바람 — 주력 혼합 조정(피해 -66.7% / 범위 +60%)
  * 🔴 지배의 일격 — 주력 혼합 조정(공격 속도 +50% / "No longer grants ...")
  * 🟡 CoC, 신성한 유물, 절개 — 서포트/보조 스킬 너프
  * 🟢 쌍수 타격 — 관련 변경 없음
* 상향 TOP 17: Forbidden Rite of Soul Sacrifice +100%, Chieftain +100%, Tornado +60%, Dominating Blow +50% …

## 4. 라이브러리

* 동봉 9개 빌드 전부 파싱 성공(`library.errors == {}`), 전직/레벨/주력 스킬/유니크/키스톤 추출 확인
* `--add-build https://pobb.in/EaARfgbK7QYl` 로 네트워크 추가 성공 → `--list-builds` 에 반영

## 5. 테스트

```bash
python3 -m pytest -q   # 57 passed
```
