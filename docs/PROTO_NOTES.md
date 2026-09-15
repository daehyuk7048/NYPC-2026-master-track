# proto-bot = 최강 공격 (적 경제 점령형) — 방어는 별도 작업

## 핵심 (사용자 통찰 = 정답)
적 땅을 빈 노드/HQ 앞 경로로 가서 소모하지 말고, **적이 점유한 경제 거점(베이스)을
먹어라.** 그러면 적 수입 차단 + 우리 것으로 플립 → **경제를 더 크게 굴려** HQ 등반/치핑에서
앞서 이긴다. (실전 로그 4·5: 우리가 node 77/101 같은 빈 노드로 한 줄 트리클하며 소모만 한 게 패인.)

## 승리 메커니즘
승패 = 턴200 `(HQ_생존, HQ_체력)`. 적 경제를 뺏으면:
- vs 방어봇(turtle/my-bot): 우리가 out-economy → HQ 더 높이/적 HQ 칩 → **TURN_LIMIT 틱브레이크 승**
- vs 공격봇(swarm/rival): 적이 HQ 비움 → **HQ_DESTROYED 승**

## 채택 설정 (`gen_attack.py` 기본값 = 스윕 우승)
| 노브 | 값 | 의미 |
|---|---|---|
| `ATTACK_TGT` | **econ** | 가장 가까운 적 **점유 거점(베이스)** 점령. 없으면 HQ. (hq러시의 4패 제거) |
| `ATTACK_WHEN` | **losing** | 영토+HQ레벨 열세일 때만 공격 (대등할 때 과공격 금지 = "공세는 질 때만 +EV") |
| `ATTACK_MIN_HQ` | **2** | HQ L2부터 일찍 (2≫3≫4) |
| 버스트 | staging | 잉여를 적 거점 인접에 모았다가 `BURST_MIN(12)` 쌓이면 한 턴 동시투입(트리클 제거) |

## 성적 (`arena.py`, 양진영 교대, 2개 시드범위)
| proto vs | 결과 |
|---|---|
| **bot_turtle** | **10~13승 0패** (구조적 무승부 → 승 전환) |
| **my-bot 베이스라인** | **11~13승 0패** |
| bot_swarm | 12~14승 0패 (HQ파괴) |
| bot_rival | 12~14승 0패 (HQ파괴) |
| **전체** | **무패** |

비교: hq_rush(빈 HQ 러시)=my-bot 5승4패·turtle 9승. **econ targeting이 패배 제거+승수 증가.**

## 도구
- `gen_attack.py` — my-bot + 공격 주입 → proto-bot (기본=우승). 노브 override.
- `sweep_attack.py [seeds]` — ATTACK_TGT/WHEN/MIN_HQ/BURST 스윕표.
- `arena.py A.py B.py [n] [seed]` — 양진영 교대, 승리 사유 표시.

## 다음
- 점령 후 **거점 사수/플립 완성**(현재는 빌드 로직이 기회적으로 플립; 수비대 남기면 영구화).
- 실제 대회 상대로 스윕(로컬 무패지만 강한 공격형 상대엔 미검증).
- 이 econ-capture 패턴을 방어 워크스트림에 조건부 접목.
