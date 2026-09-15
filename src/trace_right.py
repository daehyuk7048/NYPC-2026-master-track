#!/usr/bin/env python3
"""RIGHT-side gate tracer + event timeline for proto_v2_base.py.
Usage: python -X utf8 trace_right.py <replay.txt> <t0> <t1>
Drives proto_v2_base as RIGHT (my_hq=N-1, opp_hq=0), verifies fidelity vs RIGHT commands,
dumps _decide_impl gate locals per turn in [t0,t1], attributes every planned UPGRADE to its
plan_upgrade caller line, and prints a full-game building event timeline for both sides."""
import io, sys, importlib.util
from collections import Counter

from pathlib import Path
PROJ = str(Path(__file__).resolve().parent)  # this folder (was an absolute local path)
BOTPATH = PROJ + r"\proto_v2_base.py"

UPG_SITE = {  # plan_upgrade caller lineno -> loop name
    1871: "1a_HQ_EMERG", 1889: "1b_BUILD", 1930: "1c_HQ_CLIMB",
    2008: "1d_BASE_WORK", 2050: "1e_STANDUP", 2069: "1f_FLYWHEEL", 2088: "1g_PRESS_L2",
}

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

def side_cmd(cmd):
    moves=set(); ups=set(); train=0
    for ln in cmd:
        t=ln.split()
        if t[0]=="MOVE": moves.add((t[1],int(t[2])))
        elif t[0]=="UPGRADE": ups.add(int(t[1]))
        elif t[0]=="TRAIN": train=int(t[1])
    return moves,ups,train

KEYS = ["concentrate","base_eating","counter_now","siege_recall","siege_climb","_relief","_fortress",
        "_overwhelmed","_decisive_pin","_behind_hq","_hq_climb_window",
        "_climb_rescue","_under_massed","home_safe","committed","_advancing","_stack_advancing",
        "_econ_lead","_harass_now","_attack_now","_winning","_wide_push","_outproduced",
        "_climb_pending","losing","behind","stuck_behind","_terr_deficit","_um_pressing",
        "_smallmap_econ","_econ_invest","_econ_invest_wide","_flywheel","_press_l2","is_wave"]

def run(replay, t0, t1):
    P = load_bot(BOTPATH)
    N,K,xs,ys,sh,adj,turns = parse_replay(replay)
    M = P.GameMap(); M.N,M.K=N,K; M.x,M.y=xs,ys; M.strongholds=sh; M.adj=adj
    M.my_side=P.Side.RIGHT; M.my_hq=N-1; M.opp_hq=0
    S = P.GameState(); S.gold=P.START_GOLD
    opp=M.my_side.opposite
    for sfx in range(1,P.START_WARRIORS+1):
        S.warriors.append(P.Warrior(P.WarriorId(M.my_side,sfx),M.my_hq,P.HQ_LEVELS[1].warrior_hp))
        S.warriors.append(P.Warrior(P.WarriorId(opp,sfx),M.opp_hq,P.HQ_LEVELS[1].warrior_hp))
    S.buildings.append(P.Building(0,P.Side.LEFT,P.BType.HQ,1,P.HQ_LEVELS[1].hp))
    S.buildings.append(P.Building(N-1,P.Side.RIGHT,P.BType.HQ,1,P.HQ_LEVELS[1].hp))
    nav=P.Nav(M); nav.warm()
    P.BOT = P.Bot()

    # upgrade attribution: TracingList records plan_upgrade's caller line
    upg_log = []   # (turn, region, caller_lineno)
    cur_turn = [0]
    class TracingList(list):
        def append(self, x):
            f = sys._getframe(2)   # 1=plan_upgrade, 2=caller loop
            upg_log.append((cur_turn[0], x, f.f_lineno))
            super().append(x)

    cap = {}
    code = P._decide_impl.__code__
    def prof(frame, event, arg):
        if event == 'return' and frame.f_code is code:
            cap.clear(); cap.update(frame.f_locals)

    mm = 0; first_mm = None
    maxturn = max(turns)
    hq_d = nav.hops(M.my_hq, M.opp_hq)
    print(f"map N={N} K={K}  LEFT_HQ=0 RIGHT_HQ(us)={N-1}  hq_dist={hq_d} gate=ceil(0.6*{hq_d})={-(-6*hq_d//10)}")
    events = []   # (turn, text)
    trace_lines = []
    prev_b = {}   # region -> (side,type,level,hp)

    def snap():
        return {b.region: (b.side.name, b.type.name, b.level, b.hp) for b in S.buildings}

    prev_b = snap()
    for tn in range(1, maxturn+1):
        if tn not in turns: break
        cur_turn[0] = tn
        a = P.Actions(); a.upgrades = TracingList()
        sys.setprofile(prof)
        try:
            P._decide_impl(S, M, nav, tn, a)
        except Exception as e:
            events.append((tn, f"DECIDE EXCEPTION {e!r}"))
        sys.setprofile(None)
        # fidelity vs RIGHT commands
        em={(str(w),t) for w,t in a.moves}; eu=set(a.upgrades); et=a.train_n
        rm,ru,rt=side_cmd(turns[tn]["cmd"]["RIGHT"])
        if not(em==rm and eu==ru and et==rt):
            mm+=1
            if first_mm is None: first_mm=tn
        if t0 <= tn <= t1:
            hqb = S.find_building(M.my_hq); ehq = S.find_building(M.opp_hq)
            myW = sum(1 for w in S.warriors if w.id.side is M.my_side)
            eW  = len(S.warriors) - myW
            g = cap.get
            stk = f"{g('enemy_stack_sz','?')}@{g('stack_reg','?')}/d{g('stack_dist','?')}"
            fw  = f"{g('fwd_sz','?')}@{g('fwd_reg','?')}/d{g('fwd_dist','?')}"
            flags = [k.lstrip('_') for k in KEYS if cap.get(k)]
            if getattr(P.BOT, 'deny_mode', False): flags.append('DENY')
            n_home = sum(1 for (w,t) in a.moves if t == M.my_hq)
            n_moves = len(a.moves)
            rf = cap.get('raid_force')
            rf = len(rf) if rf is not None else '?'
            tg = g('target_garrison','?'); dn = g('defenders_needed','?')
            trace_lines.append(
                f"{tn:>3} g{S.gold:>5} hq{hqb.level if hqb else 0}/e{ehq.level if ehq else 0} "
                f"W{myW:>2}v{eW:>2} thA{P.BOT.threat_army:>2} stk{stk:>9} fwd{fw:>9} "
                f"def{dn!s:>3} gar{tg!s:>3} rf{rf!s:>3} tgt{P.BOT.raid_tgt:>3}/L{P.BOT.raid_lock:<2} "
                f"tr{a.train_n} mv{n_moves:>2}(hq{n_home:>2}) {' '.join(flags)}")
        # feed result
        wire=res_to_wire(turns[tn]["res"])
        old=P.sys.stdin; P.sys.stdin=io.StringIO(wire)
        try: P.read_turn_result(S,M,a)
        finally: P.sys.stdin=old
        # building diff
        nb = snap()
        for r,(sd,ty,lv,hp) in nb.items():
            if r not in prev_b:
                events.append((tn, f"BUILD {sd} {ty} @{r} L{lv} (d_L={nav.hops(r,0)} d_R={nav.hops(r,N-1)})"))
            else:
                osd,oty,olv,ohp = prev_b[r]
                if lv != olv:
                    events.append((tn, f"UPGRADE {sd} {ty} @{r} L{olv}->L{lv}"))
                elif hp > ohp:
                    events.append((tn, f"HEAL {sd} {ty} @{r} hp{ohp}->{hp}"))
        for r,(sd,ty,lv,hp) in prev_b.items():
            if r not in nb:
                events.append((tn, f"RAZED {sd} {ty} @{r} (was L{lv}) (d_L={nav.hops(r,0)} d_R={nav.hops(r,N-1)})"))
        prev_b = nb

    print(f"fidelity_mm={mm} first@{first_mm}")
    print("\n=== GATE TRACE ===")
    for ln in trace_lines: print(ln)
    print("\n=== UPGRADE ATTRIBUTION (our planned upgrades) ===")
    for tn, reg, lineno in upg_log:
        print(f"t{tn:>3} UPG @{reg:>3} via line {lineno} {UPG_SITE.get(lineno,'?')} (d_L={nav.hops(reg,0)} d_R={nav.hops(reg,N-1)})")
    print("\n=== BUILDING EVENT TIMELINE (both sides) ===")
    for tn, txt in events:
        print(f"t{tn:>3} {txt}")

if __name__=="__main__":
    run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
