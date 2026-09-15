#!/usr/bin/env python3
"""Compare NEW proto-bot.py vs BASELINE proto_478win.py against fixed opponents
across K9/K11/K15/K19. Prints W/L/D and mean siege A->B for each, side by side.

K-identical maps (K9=games7/8, K15=game4) must match the baseline exactly.
K11 (game6) and K19 (game5) should show MORE siege (deny fires / bigger fist),
with home-defense vs rush staying crack-free (siege B->A on our HQ irrelevant;
we check we don't LOSE to rush)."""
import re, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RES = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")

def parse_log(logpath, N):
    A_HQ, B_HQ = 0, N-1
    a=b=1; sA=sB=0
    for t in Path(logpath).read_text(encoding="utf-8",errors="replace").splitlines():
        t=t.strip()
        if t.startswith("UPGRADE A ") and int(t.split()[2])==A_HQ: a+=1
        elif t.startswith("UPGRADE B ") and int(t.split()[2])==B_HQ: b+=1
        elif t.startswith("SIEGE A "): sA+=int(t.split()[3])
        elif t.startswith("SIEGE B "): sB+=int(t.split()[3])
    return a,b,sA,sB

def one(left,right,seed,NP,KP,logp):
    cmd=[PY,TOOL,"--seed",str(seed),"--NP",str(NP),"--KP",str(KP),
         "--exec1",f'{PY} "{left}"',"--exec2",f'{PY} "{right}"',"--log",logp]
    out=subprocess.run(cmd,capture_output=True,text=True,timeout=400)
    m=RES.search(out.stdout) or RES.search(out.stderr)
    if not m: return None
    return m.group(1),m.group(2),parse_log(logp,2*NP+1)

def run(botA,botB,NP,KP,n,start):
    w=l=d=0; sgB=0; logp=str(HERE/f"_cmp_{NP}_{KP}.log")
    for i in range(n):
        seed=start+i; a_left=(i%2==0)
        L,R=(botA,botB) if a_left else (botB,botA)
        r=one(L,R,seed,NP,KP,logp)
        if not r: continue
        res,reason,(la,lb,sA,sB)=r
        if a_left: sToB=sB
        else: sToB=sA
        sgB+=sToB
        a_won=(res=="LEFT_WIN")==a_left and res!="DRAW"
        if res=="DRAW": d+=1
        elif a_won: w+=1
        else: l+=1
    return w,l,d,sgB/max(1,n)

CONFIGS=[("K9-turtle","bot_turtle.py",26,4),
         ("K9-rush","bot_rush.py",26,4),
         ("K11-turtle","bot_turtle.py",31,5),
         ("K11-rush","bot_rush.py",31,5),
         ("K15-turtle","bot_turtle.py",41,7),
         ("K19-turtle","bot_turtle.py",52,9)]
N=int(sys.argv[1]) if len(sys.argv)>1 else 6
START=int(sys.argv[2]) if len(sys.argv)>2 else 3000
print(f"{'config':14s} {'NEW (W/L/D  sgB)':24s} {'BASE (W/L/D  sgB)':24s} verdict")
for name,opp,NP,KP in CONFIGS:
    nw,nl,nd,nsg=run(str(HERE/"proto-bot.py"),str(HERE/opp),NP,KP,N,START)
    bw,bl,bd,bsg=run(str(HERE/"proto_478win.py"),str(HERE/opp),NP,KP,N,START)
    same=(nw,nl,nd)==(bw,bl,bd) and abs(nsg-bsg)<0.5
    v="IDENTICAL" if same else ("siege+" if nsg>bsg+0.5 else "CHANGED")
    print(f"{name:14s} {nw}W{nl}L{nd}D  sg{nsg:5.1f}        {bw}W{bl}L{bd}D  sg{bsg:5.1f}        {v}")
