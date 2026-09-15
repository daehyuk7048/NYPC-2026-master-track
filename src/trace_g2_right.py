#!/usr/bin/env python3
"""RIGHT-side gate tracer for g2.txt: drive proto_v2_base.py as RIGHT through the replay,
capture _decide_impl frame locals per turn (sys.setprofile), verify per-turn fidelity.
Usage: python -X utf8 trace_g2_right.py <replay.txt> <t0> <t1>"""
import io, sys, importlib.util

from pathlib import Path
PROJ = str(Path(__file__).resolve().parent)  # this folder (was an absolute local path)
BOTPATH = PROJ + r"\proto_v2_base.py"

def load_bot(path):
    spec = importlib.util.spec_from_file_location("botmod", path)
    m = importlib.util.module_from_spec(spec)
    sys.modules["botmod"] = m
    spec.loader.exec_module(m)
    return m

def parse_replay(path):
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    i = 0
    while lines[i] != "MAP": i += 1
    i += 1
    N, K = map(int, lines[i].split()); i += 1
    xs = list(map(int, lines[i].split())); i += 1
    ys = list(map(int, lines[i].split())); i += 1
    sh = lines[i].split(); strongholds = sorted(map(int, sh[1:])); i += 1
    adj = []
    for r in range(N):
        toks = list(map(int, lines[i].split())); i += 1
        adj.append(sorted(toks[1:1+toks[0]]))
    assert lines[i] == "END MAP"; i += 1
    turns = {}
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("TURN ") and "RESULT" not in ln:
            tn = int(ln.split()[1]); i += 1
            cmd = {"LEFT": [], "RIGHT": []}
            for side in ("LEFT", "RIGHT"):
                assert lines[i] == f"COMMAND {side} START"; i += 1
                while lines[i] != f"COMMAND {side} END":
                    cmd[side].append(lines[i]); i += 1
                i += 1
            assert lines[i] == f"TURN {tn} RESULT"; i += 1
            res = []
            while lines[i] != f"END TURN {tn}":
                res.append(lines[i]); i += 1
            i += 1
            turns[tn] = {"cmd": cmd, "res": res}
        else:
            i += 1
    return N, K, xs, ys, strongholds, adj, turns

def res_to_wire(res):
    ups, trains, moves, dmgs, sieges = [], [], [], [], []
    for ln in res:
        t = ln.split()
        if t[0] == "TIME": continue
        if t[0] == "UPGRADE": ups.append(f"{t[1]} {t[2]}")
        elif t[0] == "TRAIN": trains.extend(t[1:])
        elif t[0] == "MOVE": moves.append(f"{t[1]} {t[2]}")
        elif t[0] == "DAMAGE": dmgs.append(f"{t[1]} {t[2]} {t[3]}")
        elif t[0] == "SIEGE": sieges.append(f"{t[1]} {t[2]} {t[3]}")
    out = ["TURN", "TIME X 5 5 5 5", f"UPGRADE {len(ups)}"] + ups
    out.append(f"TRAIN {len(trains)}")
    if trains: out.append(" ".join(trains))
    out += [f"MOVE {len(moves)}"] + moves + [f"DAMAGE {len(dmgs)}"] + dmgs + [f"SIEGE {len(sieges)}"] + sieges + ["END"]
    return "\n".join(out) + "\n"

def side_cmd(cmds):
    moves = set(); ups = set(); train = 0
    for ln in cmds:
        t = ln.split()
        if t[0] == "MOVE": moves.add((t[1], int(t[2])))
        elif t[0] == "UPGRADE": ups.add(int(t[1]))
        elif t[0] == "TRAIN": train = int(t[1])
    return moves, ups, train

KEYS = ["concentrate", "base_eating", "committed", "_advancing", "home_safe",
        "_behind_hq", "_hq_climb_window", "_bank_climb", "_rescue", "siege_recall",
        "_fortress", "counter_now"]
NUMS = ["threat", "on_hq", "enemy_stack_sz", "stack_reg", "stack_dist", "gate",
        "defenders_needed", "target_garrison", "target_army", "total_need",
        "worker_deficit", "deficit", "cap", "hq_reserve", "_res_amt", "_res_floor",
        "_train_reserve", "spent", "_fwd_ret_eta", "guard_floor", "want_spare"]

def run(replay, t0, t1):
    P = load_bot(BOTPATH)
    N, K, xs, ys, sh, adj, turns = parse_replay(replay)
    M = P.GameMap(); M.N, M.K = N, K; M.x, M.y = xs, ys; M.strongholds = sh; M.adj = adj
    M.my_side = P.Side.RIGHT; M.my_hq = N - 1; M.opp_hq = 0
    S = P.GameState(); S.gold = P.START_GOLD
    opp = M.my_side.opposite
    for sfx in range(1, P.START_WARRIORS + 1):
        S.warriors.append(P.Warrior(P.WarriorId(M.my_side, sfx), M.my_hq, P.HQ_LEVELS[1].warrior_hp))
        S.warriors.append(P.Warrior(P.WarriorId(opp, sfx), M.opp_hq, P.HQ_LEVELS[1].warrior_hp))
    S.buildings.append(P.Building(0, P.Side.LEFT, P.BType.HQ, 1, P.HQ_LEVELS[1].hp))
    S.buildings.append(P.Building(N - 1, P.Side.RIGHT, P.BType.HQ, 1, P.HQ_LEVELS[1].hp))
    nav = P.Nav(M); nav.warm()
    P.BOT = P.Bot()
    cap_locals = {}
    code = P._decide_impl.__code__
    def prof(frame, event, arg):
        if event == 'return' and frame.f_code is code:
            cap_locals.clear(); cap_locals.update(frame.f_locals)
    maxturn = max(turns)
    print(f"map N={N} K={K}  my=RIGHT HQ={N-1}  hq-hq hops={nav.hops(0, N-1)}")
    mm = 0
    for tn in range(1, maxturn + 1):
        if tn not in turns: break
        gold_pre = S.gold
        sys.setprofile(prof)
        a = P.decide(S, M, nav, tn)
        sys.setprofile(None)
        em = {(str(w), t) for w, t in a.moves}; eu = set(a.upgrades); et = a.train_n
        rm, ru, rt = side_cmd(turns[tn]["cmd"]["RIGHT"])
        fid = "OK " if (em == rm and eu == ru and et == rt) else "MM!"
        if fid == "MM!": mm += 1
        if t0 <= tn <= t1:
            g = cap_locals.get
            hq = S.find_building(M.my_hq)
            myW = sum(1 for w in S.warriors if w.id.side is M.my_side)
            eW = sum(1 for w in S.warriors if w.id.side is not M.my_side)
            flags = [k.lstrip('_') for k in KEYS if cap_locals.get(k)]
            nums = " ".join(f"{k.lstrip('_')}={g(k, '?')}" for k in NUMS)
            print(f"t{tn:>2} {fid} gold={gold_pre:>4} hqL{hq.level if hq else 0}/{hq.hp if hq else 0} "
                  f"myW={myW} eW={eW} thA={P.BOT.threat_army} | train={a.train_n} ups={a.upgrades} "
                  f"mv={[(str(w), t) for w, t in a.moves]}")
            print(f"     {nums}")
            print(f"     flags: {' '.join(flags) or '-'}")
        wire = res_to_wire(turns[tn]["res"])
        old = P.sys.stdin; P.sys.stdin = io.StringIO(wire)
        try: P.read_turn_result(S, M, a)
        finally: P.sys.stdin = old
    print(f"\nfidelity mismatches: {mm}")

if __name__ == "__main__":
    run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
