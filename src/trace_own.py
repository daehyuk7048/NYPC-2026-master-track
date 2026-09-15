#!/usr/bin/env python3
"""Ownership trace: which branch owned the raid moves each turn, what MULTI_PRONG picked,
and what a value-key would have picked instead. Usage: python trace_own.py <replay> <t0> <t1>"""
import io, sys, importlib.util
from collections import Counter

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

    cap = {}                 # _decide_impl locals
    tfr_cap = {}             # _two_front_raid locals
    rc_calls = []            # _raid_commit locals (each call)
    pt_rets = []             # _pick_target return values
    code_d  = P._decide_impl.__code__
    code_t  = P._two_front_raid.__code__
    code_rc = P._raid_commit.__code__
    code_pt = P._pick_target.__code__
    busy = [False]
    def prof(frame, event, arg):
        if busy[0] or event != 'return':
            return
        c = frame.f_code
        if c is code_d:
            busy[0]=True; cap.clear(); cap.update(frame.f_locals); busy[0]=False
        elif c is code_t:
            busy[0]=True; tfr_cap.clear(); tfr_cap.update(frame.f_locals); busy[0]=False
        elif c is code_rc:
            busy[0]=True; rc_calls.append(dict(frame.f_locals)); busy[0]=False
        elif c is code_pt:
            pt_rets.append(arg)

    maxturn=max(turns)
    print(f"map N={N} K={K}  A_HQ=0 B_HQ={N-1}")
    for tn in range(1,maxturn+1):
        if tn not in turns: break
        cap.clear(); tfr_cap.clear(); rc_calls.clear(); pt_rets.clear()
        sys.setprofile(prof)
        a=P.decide(S,M,nav,tn)
        sys.setprofile(None)
        if t0 <= tn <= t1:
            g = cap.get
            rf = cap.get('raid_force'); rf_n = len(rf) if rf is not None else 0
            # branch label
            if g('_relief') and rf_n: br='RELIEF'
            elif g('counter_now') and rf_n: br='COUNTER'
            elif g('base_eating') and rf_n: br='BASE_EAT'
            elif tfr_cap: br='MPRONG'
            elif g('_finisher_all'): br='ALLIN'
            elif g('_finisher') and rf_n: br='FINISHER'
            elif rc_calls:
                if g('_harass_now') and g('concentrate'): br='PINBRK>RC'
                elif P.BOT.threat_army>0 and g('_harass_now') and g('home_safe'): br='FIST>RC'
                else: br='RC'
            elif g('_hq_assault'): br='HQ_ASSLT'
            elif rf_n: br='MUSTER'
            else: br='-'
            # enemy bases snapshot (region:lvl@hp)
            ebs = {}
            for b in S.buildings:
                if b.side is not M.my_side and b.type is P.BType.BASE:
                    ebs[b.region] = (b.level, b.hp)
            eb_str = " ".join(f"{r}:L{l}@{h}" for r,(l,h) in sorted(ebs.items()))
            # our sieges THIS turn (from replay result)
            sg = [f"{t[2]}-{t[3]}" for ln in turns[tn]["res"] for t in [ln.split()]
                  if t[0]=="SIEGE" and t[1]=="B"]
            line = (f"t{tn:>3} {br:<9} rf{rf_n:>2} tgt{P.BOT.raid_tgt:>3}/L{P.BOT.raid_lock:<2}"
                    f" latch{int(bool(g('_siege_latch')))} thA{P.BOT.threat_army:>2}"
                    f" chip{int(P.BOT.chip_mode)} deny{int(P.BOT.deny_mode)}")
            if pt_rets:
                line += f" pick={pt_rets}"
            if tfr_cap:
                prongs = tfr_cap.get('prongs') or []
                pr = [(len(gp), tg) for gp, tg in prongs if gp]
                lb = tfr_cap.get('live_bases') or []
                ov = tfr_cap.get('_overwhelm')
                # counterfactual: value-key order from the fist's stack region
                force = tfr_cap.get('raid_force') or []
                frm = Counter(w.region for w in force).most_common(1)[0][0] if force else M.my_hq
                def valkey(r):
                    k = nav.hops(frm, r) - nav.hops(r, M.opp_hq)
                    b = S.find_building(r)
                    if b is not None:
                        k -= P.TGT_LVL_W * b.level
                        if b.hp < b.current_hp():
                            k -= P.TGT_DMG_BONUS
                    k += P.TGT_REBUILD_W * min(P.BOT.raze_count.get(r,0), 3)
                    if bool(P.CLUSTER_TGT):
                        k -= P.CLUSTER_W * sum(1 for o in lb if o != r and nav.hops(r,o) <= P.CLUSTER_R)
                    return k
                vlb = sorted(lb, key=valkey)
                nK = max(1, len(pr))
                line += (f" MP ovw{int(bool(ov))} prongs={pr} hops_order={lb[:5]}"
                         f" VALUE_order={vlb[:5]} diff={int(set(t for _,t in pr)!=set(vlb[:nK]))}")
            if sg:
                line += f" SIEGE:{sg}"
            line += f" | EB {eb_str}"
            print(line)
        wire=res_to_wire(turns[tn]["res"])
        old=P.sys.stdin; P.sys.stdin=io.StringIO(wire)
        try: P.read_turn_result(S,M,a)
        finally: P.sys.stdin=old
    print("raze_count final:", dict(P.BOT.raze_count))

if __name__=="__main__":
    run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
