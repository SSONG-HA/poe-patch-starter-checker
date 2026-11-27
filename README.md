# PoE 패치노트 스타터 생존·버프 검증기 (PoE-Patch-Starter-Checker) v1.0.0

리그 시작일(Day 1)에는 `poe.ninja` 에 새 시즌 데이터가 없다. 이 도구는 **패치노트 원문만으로**

1. 내 스타터 빌드(6~8개)가 3.30 에서 살아남는지 (🟢 무사통과 / 🟡 일부 조정 / 🔴 핵심 너프 주의)
2. 이번 패치에서 **크게 상향된 스킬·서포트·유니크·전직**이 무엇인지 (순위 + 시드 빌드 + 바로가기 링크)

를 한 화면에서 보여준다. 외부 패키지 없이 표준 라이브러리만 쓰는 가벼운 `tkinter` 앱이며 PyInstaller 단일 `.exe` 로 빌드된다.

---

## 1. 실행

```bash
# GUI (Windows: 콘솔 없이 실행하려면 pythonw main.py)
python main.py

# CLI — 패치노트 주소로 검사
python main.py --patch-url "https://www.pathofexile.com/forum/view-thread/4013898"

# CLI — 텍스트 파일 + 결과 저장
python main.py --patch-file patch_notes.txt --out report.txt --json report.json --md report.md

# 빌드 라이브러리 관리
python main.py --list-builds
python main.py --add-build "https://pobb.in/xxxxxxxx" --name "내 새 빌드"
python main.py --remove-build rf-chieftain-330
```

* Python 3.10+ (tkinter 포함). 실행에 필요한 외부 패키지 없음.
* 라이브러리 파일은 기본적으로 `%APPDATA%\PoE-Patch-Starter-Checker\library.json` (macOS/Linux 는 `~/.poe-patch-starter-checker/library.json`)에 있고, 처음 실행할 때 동봉된 9개 빌드로 자동 생성된다. `POE_CHECKER_HOME` 환경변수나 `--library` 로 위치를 바꿀 수 있다.

### exe 빌드

```bash
pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean --onefile --windowed --name PoE-Patch-Starter-Checker \
  --add-data "poe_checker/data;poe_checker/data" main.py
```

`.github/workflows/build.yml` 이 Windows 러너에서 pytest → PyInstaller 빌드 → `--version` 스모크 테스트 → 아티팩트 업로드(태그 푸시 시 릴리스)를 수행한다.

---

## 2. 탭 1 — 스타터 생존 검증

* **빌드 라이브러리**: PoB 코드(pobb.in 코드)와 XML 을 그대로 읽어 `base64 + zlib` 로 풀고, 활성 스킬 세트의 `mainSocketGroup`·서포트 수·젬 레벨을 기준으로 **주력 스킬 / 보조 스킬 / 서포트**를 나눈다. 전직(`ascendClassName`), 키스톤(3.30 트리 노드 ID), 유니크 아이템도 함께 뽑는다.
* **패치노트 입력**: 주소(`pathofexile.com/forum/view-thread/...`)를 불러오거나, 본문을 붙여넣거나, `.txt` 파일을 열 수 있다. 포럼 HTML 은 본문(`box-content`)만 골라 텍스트로 바꾸고 `script/style`·`Show Differences` 같은 UI 문자열은 버린다.
* **매칭**: 각 빌드의 스킬·서포트·전직·키스톤·유니크 이름을 패치노트 항목과 비교한다. 변형 젬은 기본 젬 이름으로도 매칭한다(`Dominating Blow of Inspiring` ↔ `Dominating Blow`). 기본 이름 자체가 실제 젬일 때만 별칭을 만들기 때문에 `Herald of Agony ↔ Herald of Purity` 같은 오탐은 없다.
* **판정**

  | 판정 | 조건 |
  | --- | --- |
  | 🔴 핵심 너프 주의 | 주력 스킬·전직·핵심 유니크·키스톤에 너프/혼합 조정/삭제 |
  | 🟡 일부 조정 | 서포트·보조 스킬 너프, 수치 없는 문장 변경 |
  | 🟢 무사통과 | 너프성 변경 없음 (상향만 있으면 🟢 + "상향 N건") |

* 결과 표에서 빌드를 고르면 **패치노트 원문 문장**이 그대로 표시된다.

## 3. 탭 2 — 대폭 상향(버프) 탐지

* 패치노트 전체에서 `New:`/`Old:` 쌍, `(previously ...)`, `from X to Y`, `X% less ...` 같은 수치 변화를 뽑아 **사용자 이득 기준 상대 변화율** `(새 값 − 옛 값) / 옛 값` 을 계산한다.
  * 비용·마나·재사용 대기시간처럼 **낮을수록 좋은 지표**는 부호를 뒤집는다.
  * `35% less Damage` 처럼 **감소폭 자체**를 비교하는 문장은 실효값이 반대로 움직이므로 따로 처리한다.
  * `gem level 1`, `per 100 Intelligence` 처럼 비교 대상이 아닌 수치는 제외한다.
* 숫자 없이 `now also`, `Added` 블록만 있는 **정성 상향**도 목록에 넣는다(표기: `정성 상향`).
* 각 항목은 유형(스킬/서포트/유니크/전직/키스톤)과 **연결된 시드 빌드**를 보여주고, `poedb.tw/kr` · `poe.ninja` 바로가기를 만든다. (더블클릭 = poedb 열기)

---

## 4. 동봉 빌드 라이브러리 (PoE 1 3.30 · Covens of Umbra)

| ID | 빌드 | 전직/레벨 | 트리 | 출처 |
| --- | --- | --- | --- | --- |
| rf-chieftain-330 | 작열 광선 RF 치프틴 (내 캐릭터) | Chieftain 95 | 3_30 | https://pobb.in/5VPv477qQmkr |
| rf-chieftain-pohx | RF 치프틴 (Pohx SRI) | Chieftain 90 | 3_29 | https://pobb.in/Y6jHZomP3qPi |
| poison-holy-relic-necro | 중독 신성한 유물 네크로맨서 (Bula) | Necromancer 98 | 3_29 | https://pobb.in/Na035hGPLxLx |
| dominating-blow-guardian | 지배의 일격 가디언 (ArminYou) | Guardian 95 | 3_29 | https://pobb.in/1oDia2RSD4ku |
| tornado-inquisitor | 회오리바람 인퀴지터 (BalorMage) | Inquisitor 94 | 3_29 | https://pobb.in/GtWMZtty-7o2 |
| eviscerate-elementalist | 절개 점화 엘리멘탈리스트 (Desmo Saze) | Elementalist 100 | 3_29 | https://pobb.in/EaARfgbK7QYl |
| coc-forbidden-rite-assassin | CoC 금단의 의식 어쌔신 (MrJim 저예산) | Assassin 93 | 3_30 | https://pobb.in/u/mrjimo%232244/ijdNRePRfWU8 |
| impending-doom-elementalist | 독조 엘리멘탈리스트 (Doom Blast) | Elementalist 97 | 3_30 | 직접 제작 PoB |
| dual-strike-gladiator | 쌍수 타격 글래디에이터 (Ephemeral Edge) | Gladiator 98 | 3_30 | 직접 제작 PoB |

* "트리"는 코드에 저장된 `treeVersion` 값 그대로다. 3.30 리그 스타터 가이드로 공개된 빌드라도 PoB 저장 시점이 3.29 트리면 그대로 표기했다(수치를 꾸미지 않는다).
* 3.30 PoB 데이터에서 뽑은 보조 데이터: `gems_3_30.json`(젬 태그/서포트 275종), `keystones_3_30.json`(키스톤 57종), `ascendancies_3_30.json`(직업→전직).

## 5. 검증

```bash
python -m pytest -q      # 57 tests
```

* `tests/fixtures/patch_notes_synthetic_full.txt` — GGG 문체를 따른 합성 패치노트(Skills/Support Gems/Unique Items/Passive Tree, `no longer`, `from X to Y`, `less` 등).
* `tests/fixtures/patch_notes_330_new_gems.txt` — 실제 GGG 스레드(`view-thread/4013898`) 본문을 그대로 저장한 픽스처.
* 실제 네트워크 실행 결과는 `verification/live-gem-thread-report.txt`, `verification/live-gem-thread.json` 에 있다.
  * `view-thread/4013898`(New and Changed Gems, 실시간 조회): 항목 9개 · 🔴0 / 🟡3 / 🟢6 · 상향 TOP 1(Flame Link +29.6%).
  * `view-thread/4016267`(Thread Difficulty and League Mechanic Changes): 젬/유니크 이름이 없는 안내문이라 항목 0개 → 경고를 표시하고 "변경 없음"의 근거로 쓰지 말라고 알린다.

## 6. 한계

* 판정은 어디까지나 **문장 매칭 + 수치 비교**다. "젬이 재작업되어 문장만 바뀐" 경우는 🟡 로만 표시된다.
* 패치노트가 전직 노티컬 이름만 언급하면(예: `Master Surgeon`) 전직명(`Pathfinder`)만으로는 잡지 못할 수 있다 — 이때는 해당 항목이 목록에 남는다.
* 수치는 젬 20레벨/20% 품질 기준이 아닐 수 있고, 실제 체감은 장비·플레이 방식에 따라 다르다.
* Cloudflare 가 막으면 주소 불러오기가 403 으로 실패한다 → 본문을 복사해 붙여넣으면 된다.
* **한국어 번역 패치노트**는 젬·유니크 이름이 영어로 남아 있을 때만 매칭된다(이름 기반 매칭이므로).
* 항목을 하나도 분해하지 못한 문서는 결과 맨 위에 ⚠ 경고를 띄운다 — 🟢 9개가 "안전"이 아니라 "판단 불가"일 수 있다.
