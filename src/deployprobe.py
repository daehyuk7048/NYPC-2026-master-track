#!/usr/bin/env python3
"""Live-game deployment proof: does the endgame army RAZE past t150 (finisher ON) vs
sit home (OFF)? Runs proto=LEFT vs opp at K19, parses SIEGE B (proto razing enemy) by
turn + HQ-level trajectories. The finisher only fires when proto reaches L5 with enemy
still sub-L5, so we scan several opponents."""
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
    lines=run(bot,opp,seed,NP,KP,HERE/"_dp.log")
    A_HQ,B_HQ=0,N-1
    turn=0; a_lvl=b_lvl=1
    siege_pre=siege_post=0           # proto razing enemy (SIEGE B), split at t150
    a_l5_turn=None; b_lvl_at150=None
    moves_enemy_post=0               # proto MOVE dest == an enemy building region, post-t150
    # first pass: enemy building regions (from UPGRADE B lines = enemy owns them)
    enemy_regs=set()
    for t in lines:
        if t.startswith("UPGRADE B "): enemy_regs.add(int(t.split()[2]))
    for t in lines:
        t=t.strip()
        if t.startswith("TURN ") and "RESULT" not in t:
            try: turn=int(t.split()[1])
            except: pass
            if turn==150: b_lvl_at150=b_lvl
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
            # MOVE A <wid> <from> <to>  (dest is last int)
            try:
                dest=int(t.split()[-1])
                if dest in enemy_regs: moves_enemy_post+=1
            except: pass
    return dict(a_final=a_lvl,b_final=b_lvl,a_l5_turn=a_l5_turn,b_at150=b_lvl_at150,
                siege_pre=siege_pre,siege_post=siege_post,moves_enemy_post=moves_enemy_post)

def main():
    NP,KP,N=52,9,105
    opps=["bot_turtle.py","bot_climber.py","bot_grinder.py","bot_swarm.py","bot_healer.py","my-bot.py"]
    seeds=[2000,2001,2002]
    print(f"{'opp':14s} {'seed':4s} | {'build':6s} | Afin Bfin  A_L5@ B@150 | siege_pre siege_POST moves_en_POST")
    for opp in opps:
        for s in seeds:
            for bot,tag in [("proto-bot.py","fin=1"),("proto_pre_finisher.py","fin=0")]:
                r=probe(bot,opp,s,NP,KP,N)
                fires = (r['a_final']>=5 and (r['b_at150'] or 1)<5)
                mark = "  <-- FINISHER WINDOW" if (bot=="proto-bot.py" and r['a_final']>=5 and r['b_final']<5) else ""
                print(f"{opp:14s} {s:<4d} | {tag:6s} | {r['a_final']:>3d} {r['b_final']:>4d}  "
                      f"{str(r['a_l5_turn']):>5s} {str(r['b_at150']):>5s} | "
                      f"{r['siege_pre']:>9d} {r['siege_post']:>10d} {r['moves_enemy_post']:>12d}{mark}")
        print()
    print("DEPLOYPROBE DONE")

if __name__=="__main__":
    main()
