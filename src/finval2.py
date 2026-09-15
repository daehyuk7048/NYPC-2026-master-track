#!/usr/bin/env python3
"""WIN_ENDGAME_COMMIT + ENDGAME DENY ALL-IN validation: byte-equiv(flag-off vs v2r23),
rush safety, matrix no-regression vs v2r23 baseline, mirror."""
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

def cmdstream(lp):
    return [ln for ln in Path(lp).read_text(encoding="utf-8",errors="replace").splitlines()
            if not ln.startswith('[LEFT "COMMAND') and not ln.startswith('[RIGHT "COMMAND')
            and not ln.startswith('TIME LEFT') and not ln.startswith('TIME RIGHT')]

def parse(lp,N):
    A,B=0,N-1; al=bl=1; sA=sB=0
    for t in Path(lp).read_text(encoding="utf-8",errors="replace").splitlines():
        t=t.strip()
        if t.startswith("UPGRADE A ") and int(t.split()[2])==A: al+=1
        elif t.startswith("UPGRADE B ") and int(t.split()[2])==B: bl+=1
        elif t.startswith("SIEGE A "): sA+=int(t.split()[3])
        elif t.startswith("SIEGE B "): sB+=int(t.split()[3])
    return al,bl,sA,sB

def byte_equiv(a,b,opp,NP,KP,seeds):
    same=diff=0; dl=[]
    for s in seeds:
        run_game(a,opp,s,NP,KP,HERE/"_v2a.log"); run_game(b,opp,s,NP,KP,HERE/"_v2b.log")
        if cmdstream(HERE/"_v2a.log")==cmdstream(HERE/"_v2b.log"): same+=1
        else: diff+=1; dl.append(s)
    return same,diff,dl

def matrix(botL,opp,NP,KP,N,seeds):
    w=l=d=0; cr=0
    for i,s in enumerate(seeds):
        a_left=(i%2==0); L,R=(botL,opp) if a_left else (opp,botL)
        res,reason=run_game(L,R,s,NP,KP,HERE/"_v2m.log")
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
    K={9:(26,4,53),13:(40,6,81),19:(52,9,105)}
    s12=list(range(2000,2012)); be=list(range(2000,2006))
    NEW="proto-bot.py"; OFF="_wec_off.py"; BASE="proto_v2r23finisher.py"

    print("===== BYTE-EQUIV: _wec_off (WEC=0) vs proto_v2r23finisher (must be identical) ====="); sys.stdout.flush()
    for kk,opp in [(19,"bot_turtle.py"),(19,"my-bot.py"),(13,"bot_turtle.py"),(9,"bot_rush.py")]:
        NP,KP,N=K[kk]
        sm,df,dl=byte_equiv(OFF,BASE,opp,NP,KP,be)
        print(f"  K{kk} vs {opp:14s}: {sm} identical / {df} diff {dl if dl else ''}"); sys.stdout.flush()

    print("\n===== RUSH SAFETY (proto-bot vs bot_rush, want 12W/0 crack) ====="); sys.stdout.flush()
    for kk in (9,13,19):
        NP,KP,N=K[kk]; w,l,d,cr=matrix(NEW,"bot_rush.py",NP,KP,N,s12)
        print(f"  rush K{kk}: {w}W {l}L {d}D  cracks={cr}"); sys.stdout.flush()

    print("\n===== MATRIX no-regression: NEW vs BASELINE(v2r23) ====="); sys.stdout.flush()
    for opp in ("bot_turtle.py","bot_climber.py","bot_grinder.py","bot_swarm.py","my-bot.py"):
        for kk in (13,19):
            NP,KP,N=K[kk]
            wN,lN,dN,_=matrix(NEW,opp,NP,KP,N,s12)
            wB,lB,dB,_=matrix(BASE,opp,NP,KP,N,s12)
            flag="  <-- REGRESSION" if (wN<wB or (wN==wB and lN>lB)) else ("  (better)" if wN>wB else "")
            print(f"  {opp:16s} K{kk}: NEW {wN}W{lN}L{dN}D | BASE {wB}W{lB}L{dB}D{flag}"); sys.stdout.flush()

    print("\n===== MIRROR K19 canary ====="); sys.stdout.flush()
    NP,KP,N=K[19]; w,l,d,_=matrix(NEW,NEW,NP,KP,N,s12)
    wB,lB,dB,_=matrix(BASE,BASE,NP,KP,N,s12)
    print(f"  mirror K19: NEW {w}W{l}L{d}D | BASE {wB}W{lB}L{dB}D")
    print("\nFINVAL2 DONE")

if __name__=="__main__":
    main()
