#!/usr/bin/env python3
"""Probe proto vs bot_econ5: does the ENDGAME_FINISHER window occur AND does proto deploy?
Parses per-turn HQ levels, opp live-base count at t150/t190, proto SIEGE-B pre/post t150,
and MOVE A dest==enemy building post-t150 (deployment proof)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")

def run(bot, opp, seed, NP, KP, logp):
    cmd=[PY,TOOL,"--seed",str(seed),"--NP",str(NP),"--KP",str(KP),
         "--exec1",f'{PY} "{HERE/bot}"',"--exec2",f'{PY} "{HERE/opp}"',"--log",str(logp)]
    subprocess.run(cmd,capture_output=True,text=True,timeout=400)
    return Path(logp).read_text(encoding="utf-8",errors="replace").splitlines()

def probe(bot, opp, seed, NP, KP, N):
    lines=run(bot,opp,seed,NP,KP,HERE/"_e5.log")
    A_HQ,B_HQ=0,N-1
    turn=0; a_lvl=b_lvl=1
    siege_pre=siege_post=0
    a_l5_turn=None
    a_lvl_150=b_lvl_150=None; a_lvl_190=b_lvl_190=None
    moves_enemy_post=0
    on_proto_hq_late=0     # enemy warriors on proto HQ (region 0) post-t150? (home_safe check proxy)
    # track enemy building ownership over time; count live at snapshots
    enemy_regs=set(); my_regs=set()
    for t in lines:
        if t.startswith("UPGRADE B "): enemy_regs.add(int(t.split()[2]))
        if t.startswith("UPGRADE A "): my_regs.add(int(t.split()[2]))
    # We approximate opp live-base count at t150/t190 by replaying SIEGE/UPGRADE.
    # Simpler: count distinct enemy base regions that still receive UPGRADE or are
    # never razed to 0. We do a lightweight per-turn ownership sim below.
    opp_bases_150=opp_bases_190=None
    # Build set of enemy base regions (exclude HQ). Razing tracked via SIEGE A (dmg to B).
    # We can't perfectly track hp; use "distinct enemy base regions seen" minus "regions
    # with heavy siege". Good enough: report distinct enemy base regions + siege split.
    for t in lines:
        t=t.strip()
        if t.startswith("TURN ") and "RESULT" not in t:
            try: turn=int(t.split()[1])
            except: pass
            if turn==150:
                a_lvl_150,b_lvl_150=a_lvl,b_lvl
            if turn==190:
                a_lvl_190,b_lvl_190=a_lvl,b_lvl
        elif t.startswith("UPGRADE A ") and int(t.split()[2])==A_HQ:
            a_lvl+=1
            if a_lvl==5 and a_l5_turn is None: a_l5_turn=turn
        elif t.startswith("UPGRADE B ") and int(t.split()[2])==B_HQ:
            b_lvl+=1
        elif t.startswith("SIEGE B "):
            dmg=int(t.split()[3])
            if turn>150: siege_post+=dmg
            else: siege_pre+=dmg
        elif t.startswith("MOVE A ") and turn>150:
            try:
                dest=int(t.split()[-1])
                if dest in enemy_regs: moves_enemy_post+=1
            except: pass
        elif t.startswith("MOVE B ") and turn>150:
            try:
                dest=int(t.split()[-1])
                if dest==A_HQ: on_proto_hq_late+=1
            except: pass
    enemy_base_regs = enemy_regs - {B_HQ}
    return dict(a_final=a_lvl,b_final=b_lvl,a_l5_turn=a_l5_turn,
                a150=a_lvl_150,b150=b_lvl_150,a190=a_lvl_190,b190=b_lvl_190,
                siege_pre=siege_pre,siege_post=siege_post,moves_enemy_post=moves_enemy_post,
                n_enemy_bases=len(enemy_base_regs),opp_hq_march_late=on_proto_hq_late)

def main():
    NP,KP,N=52,9,105
    opp=sys.argv[1] if len(sys.argv)>1 else "bot_econ5.py"
    seeds=[int(x) for x in sys.argv[2:]] or [2000,2001,2002,2003]
    print(f"proto vs {opp}  (K19/N105)")
    print(f"{'seed':4s} {'build':6s} | Afin Bfin  A_L5@ | A@150 B@150  A@190 B@190 | enBase | siege_pre siege_POST mv_en_POST Bmarch_HQ")
    for s in seeds:
        for bot,tag in [("proto-bot.py","fin=1"),("proto_pre_finisher.py","fin=0")]:
            r=probe(bot,opp,s,NP,KP,N)
            win = (r['a_final']>=5 and (r['b150'] or 1)<5 and r['n_enemy_bases']>=2)
            mark = "  <== WINDOW" if (bot=="proto-bot.py" and win) else ""
            print(f"{s:<4d} {tag:6s} | {r['a_final']:>3d} {r['b_final']:>4d}  {str(r['a_l5_turn']):>5s} | "
                  f"{str(r['a150']):>4s} {str(r['b150']):>4s}  {str(r['a190']):>4s} {str(r['b190']):>4s} | "
                  f"{r['n_enemy_bases']:>6d} | {r['siege_pre']:>9d} {r['siege_post']:>10d} "
                  f"{r['moves_enemy_post']:>10d} {r['opp_hq_march_late']:>9d}{mark}")
        print()
    print("ECON5PROBE DONE")

if __name__=="__main__":
    main()
