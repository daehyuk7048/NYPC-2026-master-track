#!/usr/bin/env python3
"""Replay-drive proto-bot and dump _decide_impl internal gates per turn.
Usage: python trace_gates.py <replay.txt> <t0> <t1>"""
import io, sys, importlib.util

from pathlib import Path
PROJ = str(Path(__file__).resolve().parent)  # this folder (was an absolute local path)
BOTPATH = PROJ + r"\proto-bot.py"

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
    while lines[i] != "MAP":
        i += 1
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

KEYS = ["concentrate","base_eating","counter_now","siege_recall","_relief",
        "_behind_hq","home_safe","_harass_now","_eg_gate","_eg_lock","_finisher","_finisher_all",
        "_hq_assault","_siege_latch"]
NUMS = ["threat","on_hq","fwd_reg","fwd_sz","fwd_dist","stack_reg","enemy_stack_sz","stack_dist",
        "defenders_needed","target_garrison","want_spare","_climb_keep","reserve","spent",
        "total_need","guard_floor","_ehl0"]

def run(replay, t0, t1):
    P = load_bot(BOTPATH)
    N,K,xs,ys,sh,adj,turns = parse_replay(replay)
    M = P.GameMap(); M.N,M.K=N,K; M.x,M.y=xs,ys; M.strongholds=sh; M.adj=adj
    M.my_side=P.Side.LEFT; M.my_hq=0; M.opp_hq=N-1
    S = P.GameState(); S.gold=P.START_GOLD
    opp=M.my_side.opposite
    for sfx in range(1,P.START_WARRIORS+1):
        S.warriors.append(P.Warrior(P.WarriorId(M.my_side,sfx),M.my_hq,P.HQ_LEVELS[1].warrior_hp))
        S.warriors.append(P.Warrior(P.WarriorId(opp,sfx),M.opp_hq,P.HQ_LEVELS[1].warrior_hp))
    S.buildings.append(P.Building(0,P.Side.LEFT,P.BType.HQ,1,P.HQ_LEVELS[1].hp))
    S.buildings.append(P.Building(N-1,P.Side.RIGHT,P.BType.HQ,1,P.HQ_LEVELS[1].hp))
    nav=P.Nav(M); nav.warm()
    P.BOT = P.Bot()
    cap = {}
    code = P._decide_impl.__code__
    def prof(frame, event, arg):
        if event == 'return' and frame.f_code is code:
            cap.clear(); cap.update(frame.f_locals)
    maxturn=max(turns)
    print(f"map N={N} K={K}  A_HQ=0 B_HQ={N-1}")
    hdr = f"{'t':>3} {'gold':>5} {'hq':>2} {'eh':>2} {'myW':>3} {'eW':>3} {'thA':>3} {'thT':>3} {'stk':>7} {'fwd':>7} {'def':>3} {'gar':>3} {'spare':>5} {'ckeep':>5} tr flags"
    print(hdr)
    for tn in range(1,maxturn+1):
        if tn not in turns: break
        sys.setprofile(prof)
        a=P.decide(S,M,nav,tn)
        sys.setprofile(None)
        if t0 <= tn <= t1:
            hq = S.find_building(M.my_hq); ehq = S.find_building(M.opp_hq)
            myW = sum(1 for w in S.warriors if w.id.side is M.my_side)
            eW  = len(S.warriors) - myW
            g = cap.get
            stk = f"{g('enemy_stack_sz','?')}@{g('stack_reg','?')}/d{g('stack_dist','?')}"
            fw  = f"{g('fwd_sz','?')}@{g('fwd_reg','?')}/d{g('fwd_dist','?')}"
            flags = [k.lstrip('_') for k in KEYS if cap.get(k)]
            if getattr(P.BOT, 'deny_mode', False): flags.append('DENY')
            n_home = sum(1 for (w,t) in a.moves if t == M.my_hq)
            n_opp = sum(1 for (w,t) in a.moves if t == M.opp_hq)
            n_moves = len(a.moves)
            inc = 0
            for b in S.buildings:
                if b.side is M.my_side:
                    cnt = sum(1 for w in S.warriors if w.id.side is M.my_side and w.region == b.region)
                    inc += 15 * min(cnt, b.work_cap())
            rf = cap.get('raid_force')
            rf = len(rf) if rf is not None else '?'
            print(f"{tn:>3} {S.gold:>5} {hq.level if hq else 0:>2} {ehq.level if ehq else 0:>2} "
                  f"{myW:>3} {eW:>3} {P.BOT.threat_army:>3} {P.BOT.threat_total:>3} {stk:>7} {fw:>7} "
                  f"{g('defenders_needed','?'):>3} {g('target_garrison','?'):>3} {g('want_spare','?'):>5} "
                  f"{g('_climb_keep','?'):>5} rf{rf:>3} tgt{P.BOT.raid_tgt:>3}/L{P.BOT.raid_lock:<3} "
                  f"nts{P.BOT.no_target_streak:>3} {a.train_n:>2} mv{n_moves}(hm{n_home}/opq{n_opp}) tn{g('total_need','?')} inc{inc} {' '.join(flags)}")
        wire=res_to_wire(turns[tn]["res"])
        old=P.sys.stdin; P.sys.stdin=io.StringIO(wire)
        try: P.read_turn_result(S,M,a)
        finally: P.sys.stdin=old

if __name__=="__main__":
    run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
