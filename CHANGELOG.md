# 이터레이션 이력 (2026-06-26 ~ 07-08)

백업 파일명(`proto_v2r<N><tag>.py`), 코드 내 플래그 주석, 분석 노트에서 복원한 기록입니다.
각 R은 하나의 레버(플래그) 추가 또는 조정이며, 기본적으로 `플래그 OFF = 직전 버전과 바이트 동일`을 검증한 뒤 채택했습니다.
"근거"의 `1(N)`은 `docs/analysis.md`의 실전 로그 번호, `g1`/`5(12)` 등은 자체 대전·AI 상대 로그 번호입니다.

## Phase 0 — v1 "Safe Economist" (06-26 ~ 06-30)

- 심판 로그 분석: 방어 우위, 대부분 200턴 HQ 체력 타이브레이크로 결정.
- `my-bot.py`: 경제 우선 → HQ 최대 체력 유지 → 진짜 잉여만 상대 HQ 치핑. 불법 명령 0, 파산 0을 최우선.
- 상대 봇 제작 시작: `bot_swarm`, `bot_turtle`, `bot_rival`(make_rival), `bot_grinder`, `bot_rush`.

## Phase 1 — proto "econ-capture" (06-29 ~ 07-01)

- `gen_attack.py` + `sweep_attack.py`: 빈 HQ 러시(hq_rush) 대신 **적 점유 경제 거점 점령**(`ATTACK_TGT=econ`), 열세일 때만 공격(`ATTACK_WHEN=losing`), 스테이징 버스트(`BURST_MIN`). 로컬 스윕 무패.
- `proto_pre_*` 시리즈(07-01): campaign → standup → flywheel(L2 턴골드 재투자) → etareact → press → widel2 → l2loosen → relarmy → rally → econfirst → relief → unitlead → velocity → consolidate → climbfix → latchfix → deny_gamble → unfreeze → boommatch.
- 실전 래더 투입 결과 초반 러시·과확장·노동자 이탈 문제가 드러남 → v2로 재구성.

## Phase 2 — v2 R1~R24: 격리 플래그 아키텍처 (07-02 ~ 07-03)

| R | 태그 | 내용 |
|---|---|---|
| v2 base | `proto_v2_base`, `v2_flags0` | 모든 개선을 플래그로 격리, flags0 기준선 도입 |
| R2~R5 | — | 리플레이 추적 도구(`trace_*`, `dump_*`)로 명령 소유권 분석, 골드 원장(`spend_ledger`) |
| R6 | `safe6`, `r6_no_*` 절제 실험 | CLAIM_PARK_RELEASE / GARRISON_HOLD / OUTMASSED_DROP / RELIEF_ETA_BODY 를 하나씩 끄며 효과 분리 → GARRISON_HOLD·RELIEF_ETA_BODY는 기본 OFF |
| R7 | — | RAID_MIN_COMMIT(2~3기 트리클 커밋 금지), GRIND_RESCUE |
| R8 | — | 노동/운용 구분(`need = enemy_total − workcap`), 이동 재과금 제거 |
| R9~R10 | — | 소규모 찔러보기에 전체 원정대가 귀환하던 문제(RELIEF_SIZED) |
| R12~R13 | — | 매트릭스 무회귀 검증 체계 정착(`v2r12_flags0` 등 기준선 파일 유지) |
| R14 | `DOMINATE_PUSH` | 턴골드 우위인데 상대가 기지 업그레이드에 집중할 때 병력으로 응징 (g4/g6 무승부 수정) |
| R15 | `HARASS_WHEN_PASSIVE` | 수동적 상대에게 잉여 전량 방출 |
| R16 | `CONTEST_CLAIM` | 초반 중앙 거점을 상대가 "예약"만 한 경우 뺏기 (game 6 근본 원인) |
| R17 | `RACE_TIE` | 8패 포렌식: 6/8이 초반 영토 경쟁 열세 → 중앙 거점 선점 레이스 (ETA 기반 게이트) |
| R18 | `cc` | CONSOLIDATE(집결 후 진입) |
| R19 | `sb` | 스테이징 버스트 재도입 |
| R20 | `pivot` | SNOWBALL_UNTIL: 경제 단계 종료 시점 고정 |
| R21 | `final` | 종반 정리 |
| R22 | `flee` | FLEE_FIX / FLEE_TURRET: 피할 필요 없는 싸움에서 도망치던 회피 판정 수정 |
| R23 | `finisher` | ENDGAME_FINISHER: 지배적인 게임을 무승부로 끝내던 문제 (finval 배터리 도입) |
| R24 | `deny` | 종반 상대 기지 거부(deny) 주먹 |

## Phase 3 — R25~R41: 방어·요격 (07-04)

| R | 태그 | 내용 |
|---|---|---|
| R25 | `hi` | HOME_INTERCEPT: HQ로 오는 스택을 미리 요격 (`bot_pusher`로 메커니즘 검증) |
| R26 | `relsiege` | RELIEF_UNDER_SIEGE: HQ 방어 중에도 전방 기지 구원 허용 |
| R27 | `expand` | EXPAND_AHEAD: 병력 우위일 때 공격적 확장 (FAST_EXPAND는 절제 OFF) |
| R28 | `prestage` | PRESTAGE: 적 최단경로 예측 → 도착 전에 병력 사전 배치 |
| R29 | `counterpush` | COUNTER_PUSH: 큰 웨이브를 막고 병력 차가 생기면 즉시 러시 |
| R30 | `matchavail` | 가용병력 매칭 |
| R31 | `availgate` | 가용병력 기준 게이트 |
| R32 | `pwhcp` | POST_WAVE_HOLD + COUNTER_PUSH 연계 |
| R33 | `subdef` | PRESTAGE_SUBWAVE: 웨이브 인식 하한 10→6 (SUBWAVE_MIN) |
| R34 | `reachwin` | REACH_WIN: 창 안에 도달 가능한 병력만 세는 승리 판정 |
| R35 | `bracket` | 브래킷(실전 대진) 손실 모드 반영 |
| R36 | `wavefix` | 웨이브 판정 수정 |
| R37 | `fg0` | FWD_GARRISON 기본 OFF |
| R38 | `milgambit` | MIL_GAMBIT: 상대가 경제를 포기하고 군사에 올인하는지 감지 → 패리티 유지 |
| R39 | `trivsiege` | TRIVIAL_SIEGE: 1~2기 찔러보기에 전체가 반응하지 않도록 |
| R40~R41 | `dripfix`, `dripguard` | DRIP_GUARD: 반복되는 소규모 유입(drip war)에 상시 경비 |

## Phase 4 — R42~R55: 경제·타이밍 (07-05)

| R | 레버 | 근거 / 내용 |
|---|---|---|
| R42 | PARITY_CLIMB, PREDICT_STAGE, RAID_PHANTOM | 1(44)(45)(46)(49) 지갑 포렌식 / 1(49)(50) "상대 여분 병력이 3칸 움직이면 목적지가 특정된다" / 1(47) 후반 지원군 예측 |
| R43 | CHIP_LEAN_FINAL | 5(4): 종반 치핑 시 잉여 계산 정밀화 |
| R44 | chiplean | 치핑 주먹 슬림화 |
| R45 | CHIP_SETTLED_EARLY, PC_REARM | 6(2): L5 달성 후 185턴까지 기다리던 창을 160턴으로 |
| R46 | L2_WATCH | HQ L2 구매를 상대 타이밍에 맞춰 지연 |
| R47 | L2_WATCH **롤백** | 래더 7(3)/8(10)에서 기각 → OFF |
| R48 | OPEN_CLAIM | 8번 시리즈 근본 원인: 개막 클레임이 훈련 지갑 경쟁에서 짐 |
| R49 | HP_FIGHT_BAR | 적대적 감사에서 확인된 갭: 야전 판정에 전사 HP 가중치 반영 |
| R50 | NEIGHBOR_RELIEF, MG_DEEP_OPS | 1(53)(55) "주변 기지 인원이 막으면 충분했는데" / FILL_REACH_SURPLUS는 기각 OFF |
| R51 | INCOME_PRESS, L2_FIRST_GUARD, L2_LATE_PUNISH | 1(51) "인원 차이가 심하고 턴골드가 앞서면 시원하게 박자", HQ 타이밍 창(TEMPO 교리) |
| R52 | L4_WINDOW, GARRISON_STAND | 5(6) L3→L4 창 / 1(56) "오는 병력에 노동자가 전부 튀어나옴" |
| R53 | MAX_SWEEP | 5(7) "HQ 5를 찍었으면 병력 뽑아 던져라" |
| R54 | CONC_KEEP_ECON | 1(59) "최단거리로 오는 병력에 HQ도 안 거치는데 왜 반응하냐" — 노동자 이탈 근본 수정 |
| R55 | CK_PARK | 1(60) "노동자가 모든 작업장에서 튀어나와 골드 누수" |

## Phase 5 — R56~R76: 실전 패배 로그 1:1 대응 (07-06)

| R | 레버 | 근거 |
|---|---|---|
| R56 | OVEREXPAND_PUNISH | 1(62) 기지 2개 앞서가는 t65에 응징했어야 |
| R57 | RELIEF_TRIAGE | 1(63) 늦은 방어 대신 상대 기지 공격, "보내기 전에 계산" |
| R58 | PS_TTL | 1(64) t32에 이미 오는 걸 알아야 — 가까운 기지 인원으로 요격 |
| R59 | RAZE_CAMP | 1(65) 기지를 부쉈는데 상대가 재건 → 용인 시간 단축 |
| R60 | CLAIM_WALLET | 1(67) t46에 5곳 동시 확장 → 턴골드 기준 클레임 지갑 |
| R61 | TRIV_HOLD | 1(69) t167 4기에 노동자 전원 이탈 |
| R62 | ROUTE_AVOID | 1(70) 이동 경로에 적 기지 |
| R63 | oxpthin3 | OXP_THIN=3 조정 |
| R64 | RALLY_HOLD | 7(6) 11기 러시에 소극적 대응 |
| R65 | NARROW_NEAR | 1(72) 좁은 맵은 가까운 곳부터 확장 |
| R66 | EXPAND_ESCORT | 1(73) 확장 시 기지 1개당 병력 1기 확보 |
| R67 | MASS_STAGE | 8(13), 1(73) 파킹된 대군 대비 사전 배치 |
| R68 | PRESS_HOLD | 1(74) 압도적 병력이 주변만 서성임 |
| R69 | msreach | 1(75) 좁은 맵 MASS_STAGE 검증 |
| R70 | CHIP_REACH_DEF | 1(76) 큰 맵 피니시: 상대 HQ 인원 계산 후 한방 |
| R71 / R71b | COMMIT_STRIKE (+cslatch) | 1(77) 상대 주력이 멀리 갔을 때 HQ 강타 |
| R72 / R72b | OVEREXTEND_HOLD (+parity) | 5(8) 과신장 억제 |
| R73 | CONSOLIDATE_ARMY | 5(9) HQ L3 직후 대량 훈련 |
| R74 | RALLY_FALLBACK | 5(11) 못 막는 기지는 포기하고 다음 집결지로 |
| R75 | CS_FINISH | 5(12) 종반 must-win 클로저 |
| R76 | MIDEXPAND_ARM | 1(82) 기지 수 같으면 군사로 이득, 확장은 기지=인원 |

## Phase 6 — R77~R97: 피니시·확장 억제 (07-07)

| R | 레버 | 근거 |
|---|---|---|
| R77 | CS_FIN_AHEAD | 1(84) 레벨 앞서도 열린 HQ는 끝내기 |
| R78 | CS_FIN_EARLY | 1(85) 좁은 맵에서 상대가 기지를 연달아 노리면 HQ가 빈다 |
| R79 | SPENT_RAZE | 1(86) 잘 막고 치고 나가는 타이밍 |
| R81 | STRAND_RECALL | 1(88)(89) 과확장으로 방치된 클레이머 회수 |
| R82 | CS_FIN_LVLGATE | 5(13) 유리했던 게임을 토해내는 조기 피니시 방지 |
| R83 | SPENT_FINISH | 4(2) 후반 HQ에 소모하지 말고 한방에 |
| R84 | MXA_PRESSED | 1(91) 초반 과확장 치명타 — 확정 레버 |
| R85 | AVAIL_DENY | 1(92) 기지 수 밀려도 가용병력 우위면 거부 — 확정 레버 |
| R86b | CONC_WAVE_GATE | 웨이브 집결 게이트 |
| R87 | MG_RELIEF_LEAN | 1(94) 후방 배치 인원이 지원을 안 옴 — 확정 레버 |
| R88 / R88b | CONC_CLAIM_HOLD, openfix | 집결 중 클레임 보류 |
| R89 | FWD_STAGE | **NO-GO** (검증 실패, 미채택) |
| R90 | CONC_ECON_SPARE (MARGIN=2) | 확정 레버 |
| R91 | bsplit | 분할 대응 |
| R93 | climb | 등반 타이밍 |
| R94 | train | 훈련 정책 |
| R95 | HQ_CRACK_MARGIN | 1(101)~(104) HQ 공격 판정식: 주먹 = 수비 + 터렛 + (2·train_cap + 2) |
| R96 | climbcap | 등반 상한 |
| R97 | expand | 확장 조정 |

## Phase 7 — R98~R107: 최종 제출 (07-08)

| R | 레버 | 근거 |
|---|---|---|
| R98 | raid | 레이드 조정 |
| R99 | pushfar | 원거리 푸시 |
| R100 | push | A/B `ab_r100*.py` |
| R101 | recall | A/B `ab_r101.py` |
| R102 / R102b | distraid, deadlock | 분산 레이드 / 교착 해소 |
| R103 | deadlock | 교착 상태 스타트 레버 |
| R104 | RECALL_HOLD | 핵심 생존 변경 — 전 맵 러시 crack-0 하드 게이트 (`ab_r104.py`) |
| R105 | EXPAND_CAP | "확장 전부 한꺼번에 하면 안 될 것 같아" — 오프닝 이후 확장 상한 |
| R106 | CS_FIN_REACH | 1(102) 소수가 상대 HQ에 박혀 죽는 유닛 방지 |
| R107 | SMALLWAVE | 1(106)(107)(116)(117) 주기적 5기 웨이브 식별 (6기 이상은 진짜 웨이브) |

최종 `proto-bot.py`: 2026-07-08 11:39, 8,094줄, 0/1 플래그 233개.

## 롤백 / 기각 목록 (코드에 그대로 남김)

| 레버 | 사유 |
|---|---|
| L2_WATCH (R47) | 래더 7(3)/8(10) 기각 |
| FILL_REACH_SURPLUS (R50), RAIDPH_LEAN (R52) | 가설 기각(FALSIFIED) |
| REL_ARMY | 10-에이전트 검증에서 army→L2 전환이 손해 |
| WIN_PUSH | 재제출에서 7·8번 게임 회귀 |
| CLUSTER_TGT | 타겟 재정렬이 다른 매치업으로 파급 |
| PULSE, DEF_CAP | 실전 브래킷에서 역효과 (HQ 대량 펌프 러시에 훈련 매칭 실패) |
| FAST_EXPAND, EARLY_L2, ETA_CRACK, CRACK_HORIZON | 단일 플래그 절제에서 손실 |
| PROACTIVE_CLIMB, HQ_CRUSH, FINAL_RUSH | 상위 레버로 대체(decommissioned) |
| FWD_STAGE (R89) | NO-GO |
