# NYPC 2026 Master Track — Nation Providing 봇

넥슨 영 프로그래머스 컵(NYPC) 2026 **마스터 트랙 예선** 과제인 턴제 전략 게임 *Nation Providing*(아카이브명: NEXT NATION)의 AI 봇입니다.
약 10일 동안 실전 리플레이 117판을 분석하며 107회 이터레이션을 거쳐 만든 최종 제출본과, 그 과정에서 만든 상대 봇·검증 도구·분석 기록을 담았습니다.

> 문제 원문과 공식 테스팅 툴은 NYPC 아카이브에 있습니다: **https://nypc.github.io/2026**
> (넥슨 제공 파일은 저작권상 이 저장소에 포함하지 않습니다. 실행 시 아카이브에서 받아 `src/`에 두세요.)

## 1. 게임 요약

| 항목 | 값 |
|---|---|
| 형식 | 1:1 턴제, 200턴, 좌/우 진영 |
| 자원 | 시작 골드 500 · 전사 3기, 노동 수입 15/턴, 유지비 2/기, 이동 10g, 훈련 120g |
| 건물 | HQ L1~L5 (업그레이드 600/1200/2400/3600), 기지 L1~L3 (중립 거점 점령 후 건설) |
| 승리 | 상대 HQ 파괴, 또는 200턴 종료 시 `(HQ 생존, HQ 체력)` 타이브레이크 |
| 맵 | 시드 생성, 거점 수 K(9~19)에 따라 좁은 맵 / 넓은 맵 양상이 크게 다름 |

## 2. 봇 설계 (`src/proto-bot.py`, 8,094줄)

세 단계로 진화했습니다.

1. **v1 "Safe Economist"** (`my-bot.py`) — 심판 로그 분석 결과 "방어가 지배적이고 대부분 200턴 타이브레이크로 간다"는 전제에서, 경제 우위 → HQ 최대 체력 유지 → 잉여로 상대 HQ 치핑.
2. **proto "econ-capture"** (`docs/PROTO_NOTES.md`) — 빈 땅으로 병력을 흘리지 말고 **상대가 점유한 경제 거점을 뺏어서** 수입을 차단·플립하는 공격형. 로컬 스윕에서 무패였으나 실전 상대에게는 부족.
3. **v2 플래그 아키텍처** (R1~R107) — 실전 로그에서 발견한 패인마다 레버(플래그)를 하나씩 추가. 최종본에는 **0/1 플래그 233개**가 있고, 모든 레버는 `플래그 OFF = 이전 버전과 바이트 동일`을 만족하도록 격리했습니다.

핵심 개념 몇 가지:

- **가용병력(available army)** = 총 병력 − 노동 인원. 공격/방어 판단은 전부 이 값 기준 (`OPS_MATCH`, `READY_FLOOR`, `REACH_WIN`).
- **referee-exact 시뮬** — 심판 규칙(훈련→전투/공성→수입→유지비 순서, 터렛, 최저 HP 우선 처치)을 그대로 재현해 "이 기지를 이 병력으로 깰 수 있는가"를 계산 (`_can_crack`, `cf_g2.py`에서 리플레이 대조 검증).
- **HQ 공격 판정식** — 필요 주먹 = 수비 병력 + 터렛 + (2 × train_cap + 2) (`HQ_CRACK_MARGIN`, R95).
- **맵 크기 게이트** — 레버 대부분이 K 값으로 게이팅. 좁은 맵(K≤11)은 가까운 확장·초반 교전, 넓은 맵(K≥17)은 초반 압박·후반 피니시.
- **노동/운용 구분** — 적 웨이브 반응 시 노동 인원은 남기고 운용 병력만 동원 (`MASS_DEPART`, `GARRISON_STAND`, `CONC_KEEP_ECON`).

주요 레버 그룹은 `CHANGELOG.md`, 각 레버가 어떤 실전 로그에서 나왔는지는 `docs/analysis.md`에 있습니다.

## 3. 검증 방법론

"시뮬레이션에서 이기고 실전에서 지는 변경"을 여러 번 겪은 뒤 다음 순서를 고정했습니다.

```text
① flags0 바이트 동일성   새 레버 OFF 상태의 결과가 이전 버전과 byte-identical 인지
② 러시 하드 게이트       bot_rush / bot_waverush 상대 36판(시드 12 × 맵 3종) HQ 함락 0회
③ 매트릭스 무회귀        시드 12 × 맵 K9/11/13/19 × 상대 봇 14종, W/L/D + 공성량 비교
④ 미러전                 자기 자신과 좌/우 교대 대전으로 비결정성·좌우 편향 확인
⑤ 실전 관찰              온라인 래더 리플레이로 최종 판별 (자동 테스트가 못 잡는 손해가 있음)
```

검증에서 기각된 레버는 코드에 `FALSIFIED -- OFF`, 실전에서 역효과가 난 레버는 `ROLLED BACK`으로 남겨 두었습니다 (예: `L2_WATCH`, `REL_ARMY`, `WIN_PUSH`, `PULSE`, `DEF_CAP`, `FAST_EXPAND`).

## 4. 저장소 구조

```text
├─ README.md
├─ CHANGELOG.md            # R1~R107 이터레이션 이력
├─ docs/
│  ├─ analysis.md          # 실전 리플레이 117판 분석 → 문제 유형별 원인과 대응 레버
│  └─ PROTO_NOTES.md       # econ-capture 설계 노트
└─ src/                    # 모든 스크립트는 같은 폴더에서 서로를 참조합니다 (flat)
   ├─ proto-bot.py         # ★ 최종 제출 봇 (v2 R107)
   ├─ my-bot.py            # v1 베이스라인 (gen_attack / patch_proto 의 입력)
   ├─ bot_*.py             # 자체 제작 테스트 상대 봇 14종 (아래 표)
   ├─ arena.py / runval.py # A vs B 대전 (좌우 교대, 시드 범위, 맵 크기 고정)
   ├─ gen_attack.py, sweep_attack.py, sweep_expand.py, patch_proto.py, make_rival.py
   │                       # my-bot 에 공격/확장 노브를 주입해 proto 생성·스윕
   ├─ finval*.py, validate_even.py, cmp_noregress.py, cmp_rear.py, winendtest.py
   │                       # 검증 배터리 (러시 게이트, 매트릭스 무회귀, 미러)
   ├─ ab_r*.py, seedid_*.py, deployprobe.py, econ5probe.py
   │                       # 레버별 A/B 격리 실험, 시드별 승패 식별
   ├─ spend_ledger.py, cf_g2.py, trace_*.py, scratchpad_*.py
   │                       # 리플레이 골드 원장, referee-exact 반사실 시뮬, 턴별 게이트 추적
   └─ (testing-tool.py, sample-code.py)   ← 아카이브에서 받아 여기에 두세요
```

### 테스트 상대 봇

| 봇 | 재현 대상 |
|---|---|
| `bot_rush` | 경제 0, 개막 올인 HQ 러시 (t10~14 도착) — 러시 하드 게이트용 |
| `bot_waverush` | 주기적으로 커지는 웨이브를 보내는 러시 |
| `bot_allin` | 중반 전 병력 올인 |
| `bot_swarm` / `bot_rival` | 물량형 / 홈가드를 남기고 HQ를 L5까지 올리는 실전 상위권 근사 |
| `bot_grinder` | 경제를 유지하면서 2~3기 소규모 웨이브를 계속 보내는 소모전형 |
| `bot_pusher` | 점점 커지는 스택을 HQ로 행군시키는 요격 타이밍 테스트용 |
| `bot_turtle` / `bot_healer` | 수비·회복 위주, 200턴 타이브레이크를 노리는 형 |
| `bot_climber` / `bot_econ5` | HQ 등반 우선 / 기지 5개 경제 우선 |
| `bot_baseeater` / `bot_massup` / `bot_bait` | 기지 파괴 소부대 / 병력 집결 후 일격 / 유인 후 뒷치기 |

## 5. 실행

```bash
git clone https://github.com/daehyuk7048/NYPC-2026-master-track.git
cd NYPC-2026-master-track

# 1) 아카이브에서 testing-tool.py, sample-code.py 를 받아 src/ 에 둡니다.
cd src

# 2) 봇끼리 대전 (좌우 교대, 시드 20개)
python arena.py proto-bot.py bot_turtle.py 20 2000

# 3) 맵 크기를 고정한 대전 (NP=26 → N53 좁은 맵)
python runval.py proto-bot.py bot_rush.py 26 12 2000

# 4) 검증 배터리 (러시 게이트 + 매트릭스 무회귀 + 미러)
python finval4.py

# 5) 리플레이 골드 지출 원장
python -X utf8 spend_ledger.py replay.txt 10
```

`ab_r*.py`, `cmp_*.py`, `seedid_*.py`는 당시 특정 백업본(`proto_r104off.py` 등)과 비교하도록 작성돼 있습니다. 재현하려면 `proto-bot.py`를 복사해 해당 플래그를 0으로 바꾼 파일을 같은 이름으로 만들어 두면 됩니다.

## 6. 개발 방식

Claude Code(오케스트레이터 + 서브에이전트)로 개발했습니다. 코드 생성은 AI가 했고, 저는 실전 리플레이를 턴 단위로 읽으며 패인을 특정하고(`docs/analysis.md`), 레버의 판정 기준을 정하고, 위 검증 순서를 통과한 것만 채택했습니다. 각 레버 주석에 어느 로그의 몇 턴에서 나온 요구인지 남겨 두어 근거를 추적할 수 있게 했습니다.

## 7. 결과와 교훈

- 결과: **예선 탈락.** 온라인 래더에서 상위권 상대에게는 초반 중앙 거점 경쟁과 가용병력 판단에서 밀렸습니다.
- 자동 테스트가 못 잡는 손해가 있다 — 로컬 매트릭스에서 무패였던 변경이 실전에서 여러 번 롤백됐고, 실전 관찰을 최종 판별기로 두게 됐습니다.
- 기능은 항상 되돌릴 수 있게 — 플래그 격리 덕분에 107회 이터레이션 중 어떤 것도 이전 상태로 되돌리는 데 비용이 들지 않았습니다.
- 빈 땅 점령보다 **상대 경제 거점 탈취**가 승리 메커니즘이었고, 맵 크기에 따라 교리를 바꿔야 했습니다.
