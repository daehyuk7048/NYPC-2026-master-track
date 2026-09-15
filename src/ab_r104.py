#!/usr/bin/env python3
"""R104 RECALL_HOLD isolated A/B: proto-bot.py(RECALL_HOLD=1) vs proto_r104off.py(=0).
CORE SURVIVAL CHANGE -> rush/wave crack-0 across ALL K is THE hard gate."""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RE = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")
def run_game(left, right, seed, NP, KP, lp):
    cmd = [PY, TOOL, "--seed", str(seed), "--NP", str(NP), "--KP", str(KP),
           "--exec1", f'{PY} "{HERE/left}"', "--exec2", f'{PY} "{HERE/right}"', "--log", str(lp)]
    o = subprocess.run(cmd, capture_output=True, text=True, timeout=400)
    m = RE.search(o.stdout) or RE.search(o.stderr)
    return (m.group(1) if m else "ERR", m.group(2) if m else "")
def matrix(botL, opp, NP, KP, seeds, tag):
    w=l=d=cr=0
    for i,s in enumerate(seeds):
        a_left=(i%2==0); L,R=(botL,opp) if a_left else (opp,botL)
        res,reason=run_game(L,R,s,NP,KP,HERE/f"_ab101_{tag}.log")
        if res=="ERR": continue
        won=(res=="LEFT_WIN")==a_left and res!="DRAW"
        if res=="DRAW": d+=1
        elif won: w+=1
        else:
            l+=1
            if reason in ("HQ_DESTROYED","RAZE"): cr+=1
    return w,l,d,cr
def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    K={9:(26,4),11:(33,5),13:(40,6),19:(52,9)}; s12=list(range(2000,2012))
    ON="proto-bot.py"; OFF="proto_r104off.py"
    print("=== HARD GATE: rush + waverush crack-0 (ALL K) ===")
    for opp in ("bot_rush.py","bot_waverush.py"):
        for kk in (9,11,13,19):
            NP,KP=K[kk]
            wN,lN,dN,cN=matrix(ON,opp,NP,KP,s12,"on")
            wF,lF,dF,cF=matrix(OFF,opp,NP,KP,s12,"off")
            tag="  <-- CRACK REGRESSION" if cN>cF else ("  <-- WIN REG" if (wN<wF or (wN==wF and lN>lF)) else ("  (better)" if wN>wF else "  [id]"))
            print(f"  {opp:16s} K{kk:2d}: ON {wN}W{lN}L{dN}D cr{cN} | OFF {wF}W{lF}L{dF}D cr{cF}{tag}"); sys.stdout.flush()
    print("=== MATRIX: econ + my-bot (K13/19) ===")
    for opp in ("bot_turtle.py","bot_climber.py","bot_grinder.py","bot_swarm.py","bot_pusher.py","my-bot.py"):
        for kk in (13,19):
            NP,KP=K[kk]
            wN,lN,dN,cN=matrix(ON,opp,NP,KP,s12,"on")
            wF,lF,dF,cF=matrix(OFF,opp,NP,KP,s12,"off")
            tag="  <-- CRACK REG" if cN>cF else ("  <-- WIN REG" if (wN<wF or (wN==wF and lN>lF)) else ("  (better)" if wN>wF else "  [id]"))
            print(f"  {opp:16s} K{kk:2d}: ON {wN}W{lN}L{dN}D cr{cN} | OFF {wF}W{lF}L{dF}D cr{cF}{tag}"); sys.stdout.flush()
    print("AB_R104_DONE")
main()
