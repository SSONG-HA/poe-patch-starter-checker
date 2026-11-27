# PoE 패치노트 스타터 생존·버프 검증기 (PoE-Patch-Starter-Checker) v1.1.0

리그 시작일(Day 1)에는 `poe.ninja` 에 새 시즌 데이터가 없다. 이 도구는 **패치노트 원문만으로**

1. 내 스타터 빌드가 새 패치에서 살아남는지 (🟢 무사통과 / 🟡 일부 조정 / 🔴 핵심 너프 주의)
2. 이번 패치에서 **크게 상향된 스킬·서포트·유니크·전직**이 무엇인지 (순위 + 시드 빌드 + 바로가기 링크)

를 한 화면에서 보여준다. **PoE1 3.30(Covens of Umbra)과 PoE2 0.5(Runes of Aldur)를 게임 탭으로 나눠**
각 게임의 패치노트를 그 게임의 스타터로만 검증한다. 외부 패키지 없이 표준 라이브러리만 쓰는 가벼운
`tkinter` 앱이며 PyInstaller 단일 `.exe` 로 빌드된다.

---

## 1. 실행

```bash
# GUI (Windows: 콘솔 없이 실행하려면 pythonw main.py)
python main.py

# 최신 패치노트 목록 보기 (PoE1 + PoE2)
python main.py --list-patch-notes --limit 20
python main.py --list-patch-notes --game poe2 --only-patch

# 최신 패치노트를 자동으로 찾아 검사
python main.py --patch-latest --game poe1 --out report.txt --json report.json --md report.md

# 주소·파일·붙여넣기 (기존 방식 그대로)
python main.py --patch-url "https://www.pathofexile.com/forum/view-thread/4019056" --game poe1
python main.py --patch-file patch_notes.txt --game poe2

# 빌드 라이브러리 관리
python main.py --list-builds --game poe2
python main.py --add-build "https://pobb.in/xxxxxxxx" --name "내 새 빌드" --game poe1
python main.py --remove-build rf-chieftain-330
```

* Python 3.10+ (tkinter 포함). 실행에 필요한 외부 패키지 없음.
* 라이브러리 파일은 기본적으로 `%APPDATA%\PoE-Patch-Starter-Checker\library.json`
  (macOS/Linux 는 `~/.poe-patch-starter-checker/library.json`)에 있고, 처음 실행할 때 동봉된
  36개 빌드로 자동 생성된다. `--library` 로 다른 파일을 쓰면 동봉분 자동 병합은 하지 않는다
  (테스트·별도 라이브러리용). `POE_CHECKER_HOME` 로 위치를 바꿀 수 있다.
* 앱을 새 버전으로 덮어쓰면 **동봉 스타터 갱신분이 기존 라이브러리에 자동 반영**된다
  (`starters.json` 의 `updated`/`schema` 가 바뀐 경우). 사용자가 직접 추가한 빌드는 그대로 남는다.

### exe 빌드

```bash
pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean --onefile --windowed --name PoE-Patch-Starter-Checker \
  --add-data "poe_checker/data;poe_checker/data" main.py
```

`.github/workflows/build.yml` 이 Windows 러너에서 pytest → PyInstaller 빌드 → `--version` 스모크 테스트
→ 아티팩트 업로드(태그 푸시 시 릴리스)를 수행한다. (이 워크플로는 앱 권한상 수정하지 않는다.)

---

## 2. 게임 탭 — PoE1 / PoE2 분리 (v1.1.0 신규)

* 헤더의 **게임** 라디오 버튼으로 `PoE1 3.30` / `PoE2 0.5` 를 고른다.
* 선택한 게임의 **스타터만** 라이브러리·검사 결과에 나오고, 패치노트 목록도 그 게임 것만 표시된다.
* 패치노트 목록에서 PoE2 글을 불러오면 게임 탭도 자동으로 PoE2 로 바뀐다.
* 게임별 데이터: `gems_3_30.json` / `gems_poe2.json`, `keystones_3_30.json` / `keystones_poe2.json`,
  `ascendancies_3_30.json` / `ascendancies_poe2.json` (PoE2 는 PoB-PoE2 `0_5` 트리·`Gems.lua` 에서 추출).

## 3. 최신 패치노트 자동 수집 (v1.1.0 신규)

GUI 의 **최신 패치노트** 드롭다운에서 `[PoE1] 3.30.0d Patch Notes (2026-11-20)` 같은 항목을 고르고
**선택 불러오기** 를 누르면 본문을 바로 가져온다. 기존의 주소 입력·본문 붙여넣기·파일 열기도 그대로다.

| 게임 | 출처 | 엔드포인트 |
| --- | --- | --- |
| PoE1 | 패치노트 포럼 | `https://www.pathofexile.com/forum/view-forum/patch-notes` |
| PoE1 | 뉴스 RSS | `https://www.pathofexile.com/news/rss` |
| PoE2 | 얼리 액세스 패치노트 포럼 | `https://www.pathofexile.com/forum/view-forum/2212` |

* 포럼 목록 HTML 은 서버에서 렌더링되어 오므로 `제목 · 날짜 · 게임 · URL` 을 그대로 파싱한다.
  같은 스레드가 RSS 와 포럼에 모두 있으면 한 번만 남기고, 한 출처가 막혀도 나머지 결과를 돌려준다.
* 포럼 시각은 사이트 표기(UTC-8)를 KST 로 옮겨 날짜를 표시한다. 패치노트로 보이는 제목
  (`N.N.N`, Patch Notes, Hotfix, Restart, New and Changed Gems …)은 `--only-patch` 로 걸러진다.
* PoE2 공식 사이트(`pathofexile2.com`)는 자바스크립트 앱이라 RSS·목록 HTML 을 주지 않는다(2026-11-27 확인).
  그래서 PoE2 는 같은 사이트의 **얼리 액세스 패치노트 포럼**을 쓴다.
* 오프라인·CI 테스트용 실제 캡처 픽스처: `tests/fixtures/news_rss_poe1.xml`,
  `forum_patch_notes_poe1.html`, `forum_patch_notes_poe2.html`.

## 4. 탭 1 — 스타터 생존 검증

* **빌드 라이브러리**: PoB 코드(pobb.in 코드)와 XML 을 그대로 읽어 `base64 + zlib` 로 풀고, 활성 스킬
  세트의 `mainSocketGroup`·서포트 수·젬 레벨을 기준으로 **주력 스킬 / 보조 스킬 / 서포트**를 나눈다.
  전직, 키스톤(트리 노드 ID), 유니크 아이템도 함께 뽑는다. PoB XML 루트가 `PathOfBuilding2` 면 PoE2 로 읽는다.
* **패치노트 입력**: 최신 목록에서 고르거나, 주소(`pathofexile.com/forum/view-thread/...`)를 불러오거나,
  본문을 붙여넣거나 `.txt` 파일을 열 수 있다. 포럼 HTML 은 본문(`box-content` / `content-container`)만
  골라 텍스트로 바꾸고 `script/style`·`Show Differences` 같은 UI 문자열은 버린다.
* **매칭**: 각 빌드의 스킬·서포트·전직·키스톤·유니크 이름을 패치노트 항목과 비교한다. 변형 젬은 기본 젬
  이름으로도 매칭하고(`Dominating Blow of Inspiring` ↔ `Dominating Blow`), PoE2 등급 보조 젬은 등급을 뗀
  이름으로도 매칭한다(`Rapid Casting II` ↔ `Rapid Casting`).
* **판정**

  | 판정 | 조건 |
  | --- | --- |
  | 🔴 핵심 너프 주의 | 주력 스킬·전직·핵심 유니크·키스톤에 너프/혼합 조정/삭제 |
  | 🟡 일부 조정 | 서포트·보조 스킬 너프, 수치 없는 문장 변경 |
  | 🟢 무사통과 | 너프성 변경 없음 (상향만 있으면 🟢 + "상향 N건") |

* 결과 표에는 **출처/버전**(예: `리그 스타터 · Pohx · 3.30`, `내 캐릭터 · 내 빌드 · 2026-11-27`,
  `PoE2 스타터 · Chem · PoE2 0.5`, `트리 3_29`)이 함께 나온다. 상세 창은 주력 스킬·유니크·키스톤의
  한국어 명칭을 병기한다(예: `Righteous Fire(정의의 화염)`).

## 5. 탭 2 — 대폭 상향(버프) 탐지

* 패치노트 전체에서 `New:`/`Old:` 쌍, `(previously ...)`, `from X to Y`, `X% less ...` 같은 수치 변화를 뽑아
  **사용자 이득 기준 상대 변화율** `(새 값 − 옛 값) / 옛 값` 을 계산한다.
  * 비용·마나·재사용 대기시간처럼 **낮을수록 좋은 지표**는 부호를 뒤집는다.
  * `35% less Damage` 처럼 **감소폭 자체**를 비교하는 문장은 실효값이 반대로 움직이므로 따로 처리한다.
  * `gem level 1`, `per 100 Intelligence` 처럼 비교 대상이 아닌 수치는 제외한다.
* 숫자 없이 `now also`, `Added` 블록만 있는 **정성 상향**도 목록에 넣는다(표기: `정성 상향`).
* 각 항목은 유형(스킬/서포트/유니크/전직/키스톤)과 **연결된 시드 빌드**를 보여주고, `poedb.tw/kr` ·
  `poe.ninja` 바로가기를 만든다. (더블클릭 = poedb 열기)

---

## 6. 동봉 스타터 36종

### PoE1 3.30 — 내 빌드 2 + 리그 스타터 19 + 시드/엔드게임 3

| ID | 빌드 | 종류 · 출처 | 코드 |
| --- | --- | --- | --- |
| rf-chieftain-current | 작열 광선 RF 치프틴 (내 캐릭터 · 최신) | 내 캐릭터 · 2026-11-27 | `OWo-55L1tWbA` |
| rf-chieftain-330 | 작열 광선 RF 치프틴 (내 캐릭터 · 11-24) | 내 캐릭터 · 2026-11-24 | `5VPv477qQmkr` |
| rf-chieftain-pohx | RF 치프틴 (Pohx SRI) | Pohx · 3.30 | `Y6jHZomP3qPi` |
| poison-holy-relic-necro | 중독 신성한 유물 네크로맨서 | Bula · 3.30 | `Na035hGPLxLx` |
| dominating-blow-guardian | 지배의 일격 가디언 | ArminYou · 3.30 | `1oDia2RSD4ku` |
| tornado-inquisitor | 회오리바람 인퀴지터 | BalorMage · 3.30 | `GtWMZtty-7o2` |
| eviscerate-elementalist | 절개 점화 엘리멘탈리스트 | Desmo Saze · 3.30 | `EaARfgbK7QYl` |
| static-strike-guardian | 정전기 타격 가디언 | Alohaa · 3.30 | `0rKXrao_8pGM` |
| poison-concoction-pathfinder | 독성 혼합물 패스파인더 | DapperDD · 3.30 | `Pb1QziUGW5SQ` |
| bladefall-impaling-pathfinder | 칼날 낙하 관통 패스파인더 | DapperDD · 3.30 | `Vt2dSIJuurwn` |
| cold-dot-spellslinger-elementalist | 냉기 도트 스펠슬링어 엘리멘탈리스트 | Jungroan · 3.30 | `AadCGMhml9fa` |
| stormburst-totem-hierophant | 폭풍 파열 토템 히에로판트 | aer0 / Palsteron · 3.30 | `4SpZG4IzZogq` |
| incinerate-venting-elementalist | 소각 분출 엘리멘탈리스트 | smokie_777 · 3.30 | `WBamNpUW03yL` |
| animate-weapon-ranged-necromancer | 무기 소환 원거리 네크로맨서 | 3.30 인기 스타터 | `rtTLjTEh1ky0` |
| generals-cry-lacerate-champion | 장군의 함성 절단 챔피언 | 3.30 검증 스타터 | `1TONbRrNbM-w` |
| static-strike-slayer | 정전기 타격 슬레이어 | 3.30 가이드 | `OJJy1ScEuDhH` |
| smite-armor-stacker-luminary | 강타 방어구 중첩 루미너리 | 3.30 검증 스타터 | `dx239avt6A-O` |
| arc-crab-totems-reliquarian | 연쇄 번개 게 토템 렐리퀘리안 | 3.30 신 전직 | `ZBb8nQQsiT7O` |
| explosive-arrow-ballista-hierophant | 폭발 화살 발리스타 히에로판트 | POEGuy · 3.30 | `zY5__MKcIUfb` |
| boneshatter-juggernaut | 뼈 분쇄 저거너트 | Zizaran · 3.30 | `qRFk_VlQJyRx` |
| luminary-merc-aurabit | 루미너리 오라봇 | 3.30 검증 스타터 | `ebkcWV8iQUgW` |
| coc-forbidden-rite-assassin | CoC 금단의 의식 어쌔신 (저예산) | MrJim · 3.30 | `ijdNRePRfWU8` |
| impending-doom-elementalist | 독조 엘리멘탈리스트 (Doom Blast) | 직접 제작 PoB | — |
| dual-strike-gladiator | 쌍수 타격 글래디에이터 (Ephemeral Edge) | 직접 제작 PoB | — |

### PoE2 0.5 — 스타터 12

| ID | 빌드 | 전직 | 출처 |
| --- | --- | --- | --- |
| poe2-spark-stormweaver | 전기불꽃 스톰위버 | Stormweaver | animeprincess · `lvfQVOByE12P` |
| poe2-permafrost-witchhunter | 영구 동토 탄환 위치헌터 | Witchhunter | Chem · `0jY6QStgCiF7` |
| poe2-explosive-grenade-witchhunter | 폭발 수류탄 위치헌터 | Witchhunter | Hayura · `_ZU_HFdera9X` |
| poe2-martial-artist-monk | 무술가 몽크 레벨링 | Martial Artist | Ghost Activity · `ttCJAV3WX9bn` |
| poe2-falling-thunder-monk | 낙뢰 무술가 몽크 | Martial Artist | Spraahz · `pKT6y4260FdA` |
| poe2-ice-strike-amazon | 얼음 타격 아마존 | Amazon | Taaki · `OKQOruaZYWcX` |
| poe2-chaos-flicker-chayula | 혼돈 섬광 아콜라이트 | Acolyte of Chayula | `atwLUF9Q_GEo` |
| poe2-pathfinder-spark | 전기불꽃 패스파인더 | Pathfinder | `k1_vEjHL-zZO` |
| poe2-twister-gemling | 회오리 보석병 | Gemling Legionnaire | snoobae85 · `e-WNTOnCq5EC` |
| poe2-gemling-twister | 회오리 보석병 | Gemling Legionnaire | mwExile · `rPuAWBzQfEgX` |
| poe2-minion-infernalist | 소환수 인퍼널리스트 (SSF) | Infernalist | Thyworm · `_hUlac12nFNX` |
| poe2-lightning-spear-tactician | 번개 창 택티션 | Tactician | Snap · `PbvuVbm_kQdL` |

* "트리"는 코드에 저장된 `treeVersion` 값 그대로다. 3.30 가이드로 공개된 빌드라도 PoB 저장 시점이
  3.29/3.28 트리면 그대로 표기했다(수치를 꾸미지 않는다). PoE2 도 `0_4`/`0_5` 를 그대로 쓴다.
* 동봉 빌드의 젬·키스톤·전직 이름은 게임 데이터와 자동 대조한다(`tests/test_games.py`).
  전직·패시브·아이템이 부여하는 스킬(예: `Summon Elemental Relic`, `Doom Blast`)은 젬 목록에 없어 예외로 둔다.
* 한국어 이름: `names_kr.json` 은 `poedb.tw/kr`(PoE1)·`poe2db.tw/kr`(PoE2) 색인에서 영문↔한국어를
  맞춘 표다(젬 850+/786+, 유니크 1,242/432, 키스톤, 전직). 한국어 표기가 없는 이름은 영문 그대로 보인다.

## 7. 검증

```bash
python -m pytest -q      # 84 tests
```

* `tests/fixtures/patch_notes_synthetic_full.txt` — GGG 문체를 따른 합성 패치노트.
* `tests/fixtures/patch_notes_330_new_gems.txt` — 실제 GGG 스레드(`view-thread/4013898`) 본문 픽스처.
* `tests/fixtures/patch_notes_poe2_055h.txt` — 실제 PoE2 `0.5.5h Patch Notes` 본문 픽스처.
* `tests/fixtures/news_rss_poe1.xml`, `forum_patch_notes_poe1.html`, `forum_patch_notes_poe2.html` —
  실제 응답을 3건으로 줄인 목록 픽스처(오프라인/CI 테스트).
* 실제 네트워크 실행 결과는 `verification/v1.1.0-live-verification.txt`(와 `.json`)에 있다.
  * 2026-11-27 16:45 KST 기준 목록: **PoE1 59건 · PoE2 30건**, 실패한 출처 없음.
  * PoE1 최신 `3.30.0d Hotfix 3`: 항목 0개(핫픽스 문장) → ⚠ 경고와 함께 빌드 24개 전부 🟢.
  * PoE2 최신 `0.5.5h Patch Notes`: 빌드 12개 검사, 전부 🟢.
  * `New and Changed Gems`(4013898): 항목 8개 · 🟡 9 / 🟢 15 · 상향 TOP 1 `Flame Link +29.6%`.
* `sys.stdout=None`(windowed exe) 상태에서도 `--version`·`--list-patch-notes`·`--list-builds` 가
  종료코드 0 으로 동작한다(`_ensure_streams()`).

## 8. 한계

* 판정은 어디까지나 **문장 매칭 + 수치 비교**다. "젬이 재작업되어 문장만 바뀐" 경우는 🟡 로만 표시된다.
* 패치노트가 전직 노티컬 이름만 언급하면(예: `Master Surgeon`) 전직명(`Pathfinder`)만으로는 잡지 못할 수 있다.
* 수치는 젬 20레벨/20% 품질 기준이 아닐 수 있고, 실제 체감은 장비·플레이 방식에 따라 다르다.
* Cloudflare 가 막으면 주소 불러오기가 403 으로 실패한다 → 본문을 복사해 붙여넣으면 된다.
  (패치노트 목록 HTML/RSS 는 현재 차단 없이 열린다.)
* **한국어 번역 패치노트**는 젬·유니크 이름이 영어로 남아 있을 때만 매칭된다(이름 기반 매칭이므로).
* 항목을 하나도 분해하지 못한 문서는 결과 맨 위에 ⚠ 경고를 띄운다 — 🟢 이 "안전"이 아니라
  "판단 불가"일 수 있다. 특히 PoE2 핫픽스는 `Fixed a bug ...` 문장뿐이라 항목 0개가 흔하다.
* PoE2 데이터는 PoB-PoE2 `0_5` 트리 기준이다. 0.6 등 새 시즌이 나오면 그 트리 파일로 다시 뽑아야 한다
  (`tools/gen_game_data.py` 참고, 배포물에는 포함되지 않는 개발 스크립트).
