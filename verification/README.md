# 검증 기록 — v1.1.0 (2026-11-27)

모든 결과는 실제 실행 출력이다. 요약본은 `v1.1.0-live-verification.txt` / `.json` 에 있다.

## 1. 공식 패치노트 자동 수집 (실제 네트워크)

```bash
python3 main.py --list-patch-notes --limit 12
```

* 출처 3곳 모두 성공, 실패 없음.
  * PoE1 패치노트 포럼 `view-forum/patch-notes` → 30건
  * PoE1 뉴스 RSS `news/rss` → 29건
  * PoE2 얼리 액세스 패치노트 포럼 `view-forum/2212` → 30건
* 중복 스레드 제거 후 **PoE1 59건 · PoE2 30건**.
* 최신 5건: `3.30.0d Hotfix 3`(2026-11-23) · `3.30.0d Hotfix 2` · `3.30.0d Hotfix` ·
  `3.30.0d Patch Notes`(2026-11-20) · `3.30.0c Patch Notes`(2026-11-19), 그 사이에
  `[PoE2] 0.5.5h Patch Notes`(2026-11-18)가 날짜순으로 섞여 나온다.
* 포럼 표기(UTC-8)를 KST 로 옮겨 날짜를 계산한다(`Nov 22, 2026, 3:44:19 PM` → `2026-11-23`).

## 2. 게임별 검사 (최신 패치노트)

```bash
python3 main.py --patch-latest --game poe1 --out verification/poe1-latest-report.txt
python3 main.py --patch-latest --game poe2 --out verification/poe2-latest-report.txt
```

| 게임 | 패치노트 | 항목 | 검사 빌드 | 판정 |
| --- | --- | --- | --- | --- |
| PoE1 | 3.30.0d Hotfix 3 | 0 (핫픽스 문장) | 24 | 🔴0 🟡0 🟢24 |
| PoE2 | 0.5.5h Patch Notes | 1 | 12 | 🔴0 🟡0 🟢12 |

* PoE1 검사에는 PoE1 스타터 24개만, PoE2 검사에는 PoE2 스타터 12개만 들어간다(게임 탭 분리 확인).
* 항목 0건 문서는 ⚠ 경고를 함께 표시한다.

## 3. 젬 변경 스레드 매칭 (view-thread/4013898)

```bash
python3 main.py --patch-url "https://www.pathofexile.com/forum/view-thread/4013898" --game poe1 \
  --out verification/live-gem-thread-report.txt --json verification/live-gem-thread.json
```

* 항목 8개 (Flame Link, Summon Flame/Stone/Lightning Golem, Dark Bargain, Pact of Beidat,
  Winter Orb, Transfusion Support)
* 판정: 🔴 0 · 🟡 9 · 🟢 15 · 상향 TOP 1 **Flame Link +29.6%**
* 🟡 예: 냉기 도트 엘리(Summon Flame Golem 너프 외 2건), 루미너리 2종(Flame Link 혼합),
  연쇄 번개 렐리퀘리안(Summon Lightning Golem), 중독 신성한 유물(Summon Stone Golem).

## 4. 동봉 스타터 36종

* PoE1 24종(내 빌드 2 · 리그 스타터 19 · 시드 3), PoE2 12종 — 전부 파싱 성공(`rows()` 오류 0).
* 구성 요소 이름 929개 중 917개(98.7%)가 게임 데이터의 젬 목록과 일치. 나머지 12개는 전직·패시브·
  아이템이 부여하는 스킬(`Summon Elemental Relic`, `Doom Blast`, `Approaching Flames` 등)이다.
* 한국어 이름표: PoE1 젬 852 · 유니크 1,242, PoE2 젬 786 · 유니크 432, 키스톤·전직 포함.

## 5. 테스트

```bash
python3 -m pytest -q   # 82 passed
```

* 목록 파싱 픽스처: `tests/fixtures/news_rss_poe1.xml`, `forum_patch_notes_poe1.html`,
  `forum_patch_notes_poe2.html`
* PoE2 본문 픽스처: `tests/fixtures/patch_notes_poe2_055h.txt`
* 게임 분리 테스트: `tests/test_games.py` (PoE2 XML 감지, 라이브러리 game 필터, 게임별 분석)
* `sys.stdout=None` 스모크: `tests/test_cli.py` 의 `test_cli_survives_missing_stdout`
