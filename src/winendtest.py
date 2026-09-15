#!/usr/bin/env python3
"""Isolate WIN_ENDGAME_COMMIT: new (WEC=1) vs _wec_off (WEC=0) vs bot_econ5, per seed.
Reports result, final HQ levels, SIEGE-B (proto razing econ5) split pre/post t150."""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
PY=sys.executable or "python"
TOOL=str(HERE/"testing-tool.py")
RE=re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")

def run(bot,opp,seed,NP,KP,lp):
    cmd=[PY,TOOL,"--seed",str(seed),"--NP",str(NP),"--KP",str(KP),
         "--exec1",f'{PY} "{HERE/bot}"',"--exec2",f'{PY} "{HERE/opp}"',"--log",str(lp)]
    o=subprocess.run(cmd,capture_output=True,text=True,timeout=400)
    m=RE.search(o.stdout) or RE.search(o.stderr)
    res=m.group(1) if m else "ERR"
    lines=Path(lp).read_text(encoding="utf-8",errors="replace").splitlines()
    N=int(lines[3].split()[0]); AH,BH=0,N-1
    turn=0; al=bl=1; spre=spost=0
    for t in lines:
        t=t.strip()
        if t.startswith("TURN ") and "RESULT" not in t:
            try: turn=int(t.split()[1])
            except: pass
        elif t.startswith("UPGRADE A ") and int(t.split()[2])==AH: al+=1
        elif t.startswith("UPGRADE B ") and int(t.split()[2])==BH: bl+=1
        elif t.startswith("SIEGE B "):
            d=int(t.split()[3])
            if turn>150: spost+=d
            else: spre+=d
    return res,al,bl,spre,spost

def main():
    NP,KP,N=52,9,105
    opp="bot_econ5.py"
    seeds=list(range(2000,2010))
    print(f"{'seed':5s} | {'build':7s} | result     | A_HQ B_HQ | siegeB_pre siegeB_POST")
    for s in seeds:
        row=[]
        for bot,tag in [("proto-bot.py","WEC=1"),("_wec_off.py","WEC=0")]:
            res,al,bl,spre,spost=run(bot,opp,s,NP,KP,HERE/f"_we_{tag}.log")
            # from A(proto=LEFT) perspective
            win = "WIN " if res=="LEFT_WIN" else ("DRAW" if res=="DRAW" else "LOSS")
            row.append((tag,win,res,al,bl,spre,spost))
        for tag,win,res,al,bl,spre,spost in row:
            print(f"{s:<5d} | {tag:7s} | {win} {res:10s}| {al:>4d} {bl:>4d} | {spre:>10d} {spost:>11d}")
        print()
    print("WINENDTEST DONE")

if __name__=="__main__":
    main()
