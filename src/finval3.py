#!/usr/bin/env python3
"""Sub-wave defense 3-fix validation: rush hard gate, matrix no-regression vs flags-off
baseline (_swd_off.py == pre-fix behavior), mirror canary. Filtered-cmdstream byte-equiv
for containment is already proven via 1(36) fidelity 0/200."""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
PY=sys.executable or "python"
TOOL=str(HERE/"testing-tool.py")
RE=re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")

def run_game(left,right,seed,NP,KP,lp):
    cmd=[PY,TOOL,"--seed",str(seed),"--NP",str(NP),"--KP",str(KP),
         "--exec1",f'{PY} "{HERE/left}"',"--exec2",f'{PY} "{HERE/right}"',"--log",str(lp)]
    o=subprocess.run(cmd,capture_output=True,text=True,timeout=400)
    m=RE.search(o.stdout) or RE.search(o.stderr)
    return (m.group(1) if m else "ERR", m.group(2) if m else "")

def matrix(botL,opp,NP,KP,seeds,tag):
    w=l=d=0; cr=0
    for i,s in enumerate(seeds):
        a_left=(i%2==0); L,R=(botL,opp) if a_left else (opp,botL)
        res,reason=run_game(L,R,s,NP,KP,HERE/f"_v3_{tag}.log")
        if res=="ERR": print(f"    seed {s} ERR"); continue
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
    K={9:(26,4),13:(40,6),19:(52,9)}
    s12=list(range(2000,2012))
    NEW="proto-bot.py"; BASE="_fg_off.py"

    print("===== RUSH HARD GATE (NEW vs bot_rush, want 12W/0 crack) ====="); sys.stdout.flush()
    for kk in (9,13,19):
        NP,KP=K[kk]; w,l,d,cr=matrix(NEW,"bot_rush.py",NP,KP,s12,f"r{kk}")
        print(f"  rush K{kk}: {w}W {l}L {d}D  HQ-cracks={cr}"); sys.stdout.flush()

    print("\n===== MATRIX: NEW vs BASE(flags-off) ====="); sys.stdout.flush()
    for opp in ("bot_turtle.py","bot_climber.py","bot_grinder.py","bot_swarm.py","my-bot.py","bot_pusher.py"):
        for kk in (13,19):
            NP,KP=K[kk]
            wN,lN,dN,_=matrix(NEW,opp,NP,KP,s12,"mN")
            wB,lB,dB,_=matrix(BASE,opp,NP,KP,s12,"mB")
            flag="  <-- REGRESSION" if (wN<wB or (wN==wB and lN>lB)) else ("  (better)" if wN>wB else "")
            print(f"  {opp:16s} K{kk}: NEW {wN}W{lN}L{dN}D | BASE {wB}W{lB}L{dB}D{flag}"); sys.stdout.flush()

    print("\n===== MIRROR canary ====="); sys.stdout.flush()
    for kk in (13,19):
        NP,KP=K[kk]
        w,l,d,_=matrix(NEW,NEW,NP,KP,s12,"mirN")
        wB,lB,dB,_=matrix(BASE,BASE,NP,KP,s12,"mirB")
        print(f"  mirror K{kk}: NEW {w}W{l}L{d}D | BASE {wB}W{lB}L{dB}D"); sys.stdout.flush()
    print("\nFINVAL3 DONE")

if __name__=="__main__":
    main()
