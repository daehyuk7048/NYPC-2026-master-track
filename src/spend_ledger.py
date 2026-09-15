#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spend_ledger.py -- 리플레이에서 양측(A=LEFT, B=RIGHT)의 골드 지출을 카테고리별 분류/누적.

사용법:  python -X utf8 spend_ledger.py <replay.txt> [interval=10]

카테고리:
  expand  = 스트롱홀드 첫 UPGRADE (기지건설 300)          [RESULT 이벤트 기준=집행 확정분]
  base_up = 기존 기지 UPGRADE (L2 600 / L3 1000)          [RESULT 기준]
  hq_up   = HQ UPGRADE (L2 600 / L3 1200 / L4 2400 / L5 3600) [RESULT 기준]
  heal    = 만렙 건물 UPGRADE = 힐 (HQ 1000 / 기지 500)    [RESULT 기준]
  train   = RESULT TRAIN 수 x 120                          [RESULT 기준=실제 생산분]
  moves   = 제출 명령(COMMAND 블록) 기준 MOVE x 10; 목적지에 자기 건물이 있으면 0
            (referee/봇 모델과 동일: 명령 1건당 1회 과금, 멀티홉 무관)
  upkeep  = 매턴 생존 워리어 x 2 (잔고 0 밑으로 못 내려감: max(0, bal-upk) 클램프 재현)
  income  = 매턴 15 x min(그 건물 위 자기 워리어 수, work_cap) 합

근사/가정 (proto_v2_base.py read_turn_result와 동일한 모델, fidelity 0 검증됨):
  * 건물 소유/레벨/HP는 RESULT의 UPGRADE/SIEGE 이벤트로 추적한 스냅샷. 파괴된 스트롱홀드를
    상대가 재건하면 expand(300)로 재분류됨(referee와 동일).
  * MOVE 과금 판정은 그 턴 RESULT 처리 전 스냅샷(=명령 제출 시점) 기준. 죽은/미존재
    워리어에 대한 MOVE 명령은 무과금 처리(referee가 거부한다고 가정) -- 근사.
  * 워리어 HP는 훈련 시점 HQ 레벨의 warrior_hp에서 DAMAGE 누적으로만 감소(힐 없음 --
    proto_v2_base 모델과 동일). 사망=HP<=0.
  * 잔고는 지출 -> income -> upkeep(0 클램프) 순으로 갱신(봇 모델과 동일 순서).
"""
import sys

# ---- 게임 상수 (proto_v2_base.py에서 하드코딩 복사; import 불필요) ----
START_GOLD = 500
START_WARRIORS = 3
MOVE_COST = 10
TRAIN_COST = 120
WORK_INCOME = 15
UPKEEP = 2
HQ_HEAL_COST = 1000
BASE_HEAL_COST = 500
HQ_MAX_LEVEL = 5
BASE_MAX_LEVEL = 3
# level -> (upgrade_cost_to_this_level, warrior_hp, building_hp, work_cap)
HQ_LV = {1: (0, 4, 10, 1), 2: (600, 5, 15, 2), 3: (1200, 6, 20, 3),
         4: (2400, 7, 25, 4), 5: (3600, 8, 30, 5)}
# level -> (cost_to_this_level, building_hp, work_cap)
BASE_LV = {1: (300, 6, 1), 2: (600, 12, 2), 3: (1000, 18, 3)}

CATS = ["expand", "base_up", "hq_up", "heal", "train", "moves", "upkeep"]


def parse_replay(path):
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    i = 0
    while lines[i] != "MAP":
        i += 1
    i += 1
    N, K = map(int, lines[i].split()); i += 1
    i += 2  # xs, ys (좌표는 레저에 불필요)
    i += 1  # STRONGHOLDS
    for _ in range(N):
        i += 1  # 인접 리스트
    assert lines[i] == "END MAP"; i += 1
    turns = {}
    result_line = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("TURN ") and "RESULT" not in ln:
            tn = int(ln.split()[1]); i += 1
            cmd = {"A": [], "B": []}
            for side, key in (("LEFT", "A"), ("RIGHT", "B")):
                assert lines[i] == f"COMMAND {side} START"; i += 1
                while lines[i] != f"COMMAND {side} END":
                    cmd[key].append(lines[i]); i += 1
                i += 1
            assert lines[i] == f"TURN {tn} RESULT"; i += 1
            res = []
            while lines[i] != f"END TURN {tn}":
                res.append(lines[i]); i += 1
            i += 1
            turns[tn] = (cmd, res)
        elif ln.startswith("RESULT "):
            result_line = ln; i += 1
        else:
            i += 1
    return N, K, turns, result_line


class Bld:
    __slots__ = ("side", "typ", "level", "hp")  # typ: "HQ" | "BASE"

    def __init__(self, side, typ, level, hp):
        self.side, self.typ, self.level, self.hp = side, typ, level, hp

    def full_hp(self):
        return HQ_LV[self.level][2] if self.typ == "HQ" else BASE_LV[self.level][1]

    def work_cap(self):
        return HQ_LV[self.level][3] if self.typ == "HQ" else BASE_LV[self.level][2]


def run(path, interval):
    N, K, turns, result_line = parse_replay(path)
    hq_of = {"A": 0, "B": N - 1}

    blds = {0: Bld("A", "HQ", 1, HQ_LV[1][2]), N - 1: Bld("B", "HQ", 1, HQ_LV[1][2])}
    # wid("A3") -> [side, region, hp]
    wars = {}
    for s in ("A", "B"):
        for k in range(1, START_WARRIORS + 1):
            wars[f"{s}{k}"] = [s, hq_of[s], HQ_LV[1][1]]

    tot = {s: {c: 0 for c in CATS} for s in "AB"}
    tot_inc = {"A": 0, "B": 0}
    unpaid = {"A": 0, "B": 0}  # upkeep 클램프로 실제 못 걷힌 몫
    bal = {"A": START_GOLD, "B": START_GOLD}

    maxturn = max(turns)
    rows = []
    win_start = 1
    snap = {s: dict(tot[s]) for s in "AB"}
    snap_inc = dict(tot_inc)

    def emit_window(t_end):
        nonlocal win_start, snap, snap_inc
        for s in "AB":
            d = {c: tot[s][c] - snap[s][c] for c in CATS}
            inc = tot_inc[s] - snap_inc[s]
            w = sum(1 for v in wars.values() if v[0] == s)
            nb = sum(1 for b in blds.values() if b.side == s and b.typ == "BASE")
            hb = blds.get(hq_of[s])
            hql = hb.level if hb is not None and hb.side == s else 0
            rows.append((win_start, t_end, s, d, inc, bal[s], w, nb, hql))
        win_start = t_end + 1
        snap = {s: dict(tot[s]) for s in "AB"}
        snap_inc = dict(tot_inc)

    for tn in range(1, maxturn + 1):
        if tn not in turns:
            break
        cmd, res = turns[tn]

        # 1) MOVE 과금: 제출 명령 기준, 그 턴 이벤트 처리 전 스냅샷으로 소유 판정
        for s in "AB":
            for ln in cmd[s]:
                t = ln.split()
                if t[0] != "MOVE":
                    continue
                wid, target = t[1], int(t[2])
                if wid not in wars or wars[wid][0] != s:
                    continue  # 죽은/타측 워리어 명령은 referee 거부로 간주(무과금) -- 근사
                b = blds.get(target)
                cost = 0 if (b is not None and b.side == s) else MOVE_COST
                tot[s]["moves"] += cost
                bal[s] -= cost

        # 2) RESULT 이벤트 순차 처리 (UPGRADE/TRAIN/MOVE/DAMAGE/SIEGE)
        for ln in res:
            t = ln.split()
            if t[0] == "TIME":
                continue
            if t[0] == "UPGRADE":
                s, region = t[1], int(t[2])
                b = blds.get(region)
                if b is None:
                    tot[s]["expand"] += BASE_LV[1][0]
                    bal[s] -= BASE_LV[1][0]
                    blds[region] = Bld(s, "BASE", 1, BASE_LV[1][1])
                else:
                    mx = HQ_MAX_LEVEL if b.typ == "HQ" else BASE_MAX_LEVEL
                    if b.level >= mx:
                        c = HQ_HEAL_COST if b.typ == "HQ" else BASE_HEAL_COST
                        tot[s]["heal"] += c
                        bal[s] -= c
                        b.hp = b.full_hp()
                    else:
                        b.level += 1
                        c = HQ_LV[b.level][0] if b.typ == "HQ" else BASE_LV[b.level][0]
                        cat = "hq_up" if b.typ == "HQ" else "base_up"
                        tot[s][cat] += c
                        bal[s] -= c
                        b.hp = b.full_hp()
            elif t[0] == "TRAIN":
                for wid in t[1:]:
                    s = wid[0]
                    hb = blds.get(hq_of[s])
                    lvl = hb.level if hb is not None else 1
                    wars[wid] = [s, hq_of[s], HQ_LV[lvl][1]]
                    tot[s]["train"] += TRAIN_COST
                    bal[s] -= TRAIN_COST
            elif t[0] == "MOVE":
                wid, region = t[1], int(t[2])
                if wid in wars:
                    wars[wid][1] = region
            elif t[0] == "DAMAGE":
                wid, dmg = t[2], int(t[3])
                if wid in wars:
                    wars[wid][2] -= dmg
                    if wars[wid][2] <= 0:
                        del wars[wid]
            elif t[0] == "SIEGE":
                region, dmg = int(t[2]), int(t[3])
                b = blds.get(region)
                if b is not None:
                    b.hp -= dmg
                    if b.hp <= 0:
                        del blds[region]

        # 3) income
        for s in "AB":
            inc = 0
            for region, b in blds.items():
                if b.side != s:
                    continue
                cnt = sum(1 for v in wars.values() if v[0] == s and v[1] == region)
                inc += WORK_INCOME * min(cnt, b.work_cap())
            tot_inc[s] += inc
            bal[s] += inc

        # 4) upkeep (referee와 동일: 잔고 0 클램프)
        for s in "AB":
            alive = sum(1 for v in wars.values() if v[0] == s)
            upk = UPKEEP * alive
            paid = min(bal[s], upk) if bal[s] > 0 else 0
            unpaid[s] += upk - paid
            tot[s]["upkeep"] += upk
            bal[s] = max(0, bal[s] - upk)

        if tn % interval == 0:
            emit_window(tn)

    if win_start <= maxturn:
        emit_window(maxturn)

    # ---- 출력 ----
    hdr = (f"{'turns':>9} | s | {'expand':>6} {'base_up':>7} {'hq_up':>6} {'heal':>5} "
           f"{'train':>6} {'moves':>5} {'upkeep':>6} | {'income':>6} | {'bal_end':>7} | "
           f"{'W':>3} {'bases':>5} {'HQ':>2}")
    print(f"== SPEND LEDGER: {path}")
    print(f"== N={N} K={K} turns={maxturn} interval={interval}"
          + (f"  |  {result_line}" if result_line else ""))
    print(hdr)
    print("-" * len(hdr))
    for (t0, t1, s, d, inc, b_end, w, nb, hql) in rows:
        print(f"t{t0:03d}-{t1:03d} | {s} | {d['expand']:>6} {d['base_up']:>7} "
              f"{d['hq_up']:>6} {d['heal']:>5} {d['train']:>6} {d['moves']:>5} "
              f"{d['upkeep']:>6} | {inc:>6} | {b_end:>7} | {w:>3} {nb:>5} {hql:>2}")
        if s == "B":
            print("-" * len(hdr))

    print()
    print("== FINAL CUMULATIVE SUMMARY")
    for s in "AB":
        spend = sum(tot[s].values())
        parts = "  ".join(
            f"{c}={tot[s][c]}({(100.0 * tot[s][c] / spend if spend else 0):.1f}%)"
            for c in CATS)
        print(f"  {s}: total_spend={spend}  income={tot_inc[s]}  "
              f"bal_end={bal[s]}  upkeep_unpaid(클램프)={unpaid[s]}")
        print(f"     {parts}")


if __name__ == "__main__":
    replay = sys.argv[1]
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    run(replay, interval)
