#!/usr/bin/env python3
"""ENDGAME_FINISHER validation: byte-equiv (flag-off), rush safety, matrix no-regression, mirror."""
from __future__ import annotations
import re, subprocess, sys, hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RESULT_RE = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")

def run_game(left, right, seed, NP, KP, logpath):
    cmd = [PY, TOOL, "--seed", str(seed), "--NP", str(NP), "--KP", str(KP),
           "--exec1", f'{PY} "{HERE/left}"', "--exec2", f'{PY} "{HERE/right}"',
           "--log", str(logpath)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=400)
    m = RESULT_RE.search(out.stdout) or RESULT_RE.search(out.stderr)
    if not m: return ("ERR", (out.stdout+" "+out.stderr).strip()[:120])
    return (m.group(1), m.group(2))

def parse_log(logpath, N):
    A_HQ, B_HQ = 0, N-1
    a_lvl=b_lvl=1; sA=sB=0; a_hq_alive=b_hq_alive=True
    for t in Path(logpath).read_text(encoding="utf-8",errors="replace").splitlines():
        t=t.strip()
        if t.startswith("UPGRADE A ") and int(t.split()[2])==A_HQ: a_lvl+=1
        elif t.startswith("UPGRADE B ") and int(t.split()[2])==B_HQ: b_lvl+=1
        elif t.startswith("SIEGE A "): sA+=int(t.split()[3])
        elif t.startswith("SIEGE B "): sB+=int(t.split()[3])
    return (a_lvl,b_lvl,sA,sB)

def _cmdstream(logpath):
    """Filter the referee log to the DETERMINISTIC command stream (drop wall-clock TIME
    telemetry + exec-path echoes, which vary run-to-run and don't affect the game)."""
    return [ln for ln in Path(logpath).read_text(encoding="utf-8",errors="replace").splitlines()
            if not ln.startswith('[LEFT "COMMAND') and not ln.startswith('[RIGHT "COMMAND')
            and not ln.startswith('TIME LEFT') and not ln.startswith('TIME RIGHT')]

def byte_equiv(botA, botB, opp, NP, KP, seeds, N):
    """proto=LEFT vs opp=RIGHT each seed; filtered command stream must match A vs B."""
    same=diff=0; difflist=[]
    for s in seeds:
        run_game(botA, opp, s, NP, KP, HERE/"_be_A.log"); ca=_cmdstream(HERE/"_be_A.log")
        run_game(botB, opp, s, NP, KP, HERE/"_be_B.log"); cb=_cmdstream(HERE/"_be_B.log")
        if ca==cb: same+=1
        else: diff+=1; difflist.append(s)
    return same,diff,difflist

def matrix(botL, opp, NP, KP, seeds, N):
    """W/L/D + HQ-crack count from botL's perspective, alternating orientation."""
    w=l=d=0; cracks=0; sieges=[]
    for i,s in enumerate(seeds):
        a_left=(i%2==0)
        L,R=(botL,opp) if a_left else (opp,botL)
        lp=HERE/"_mx.log"
        res,reason=run_game(L,R,s,NP,KP,lp)
        if res=="ERR": print(f"    seed {s} ERR {reason}"); continue
        al,bl,sA,sB=parse_log(lp,N)
        won=(res=="LEFT_WIN")==a_left and res!="DRAW"
        # botL HQ level, siege received (razing on botL's HQ side)
        if a_left: myHQ,opHQ,sToMe = al,bl,sB
        else:      myHQ,opHQ,sToMe = bl,al,sA
        if res=="DRAW": d+=1
        elif won: w+=1
        else: l+=1
        if reason in ("HQ_DESTROYED","RAZE") and not won: cracks+=1
    return w,l,d,cracks

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    SKIP_BE = "--skip-be" in sys.argv
    # NP,KP,N triples
    K = {9:(26,4,53), 13:(40,6,81), 19:(52,9,105)}
    seeds12=list(range(2000,2012))
    be_seeds=list(range(2000,2006))

    if not SKIP_BE:
        print("===== BYTE-EQUIV (flag-off inertness) -- filtered command stream ====="); sys.stdout.flush()
        for kk,opp in [(19,"bot_turtle.py"),(19,"my-bot.py")]:
            NP,KP,N=K[kk]
            s,df,dl=byte_equiv("_fin_f0.py","_pre_fr0.py",opp,NP,KP,be_seeds,N)
            print(f"  [new OFF vs old-lever OFF] K{kk} vs {opp:14s}: {s} identical / {df} diff {dl if dl else ''}"); sys.stdout.flush()
        for kk,opp in [(19,"bot_turtle.py"),(19,"my-bot.py")]:
            NP,KP,N=K[kk]
            s,df,dl=byte_equiv("proto_pre_finisher.py","_pre_fr0.py",opp,NP,KP,be_seeds,N)
            print(f"  [old FR=1 vs FR=0 decommission] K{kk} vs {opp:14s}: {s} identical / {df} diff {dl if dl else ''}"); sys.stdout.flush()

    print("\n===== RUSH SAFETY (proto-bot vs bot_rush, want 12W/0 crack) ====="); sys.stdout.flush()
    for kk in (9,13,19):
        NP,KP,N=K[kk]
        w,l,d,cr=matrix("proto-bot.py","bot_rush.py",NP,KP,seeds12,N)
        print(f"  rush K{kk}: {w}W {l}L {d}D   HQ-cracks={cr}"); sys.stdout.flush()

    print("\n===== MATRIX no-regression: LIVE (fin=1) vs BASELINE (proto_pre_finisher) ====="); sys.stdout.flush()
    for opp in ("bot_turtle.py","bot_climber.py","bot_grinder.py","bot_swarm.py","my-bot.py"):
        for kk in (13,19):
            NP,KP,N=K[kk]
            wL,lL,dL,_=matrix("proto-bot.py",opp,NP,KP,seeds12,N)
            wB,lB,dB,_=matrix("proto_pre_finisher.py",opp,NP,KP,seeds12,N)
            flag="  <-- REGRESSION" if (wL<wB or (wL==wB and lL>lB)) else ("  (improved)" if wL>wB else "")
            print(f"  {opp:16s} K{kk}: LIVE {wL}W{lL}L{dL}D | BASE {wB}W{lB}L{dB}D{flag}"); sys.stdout.flush()

    print("\n===== MIRROR canary (proto-bot vs proto-bot) K19 ====="); sys.stdout.flush()
    NP,KP,N=K[19]
    w,l,d,_=matrix("proto-bot.py","proto-bot.py",NP,KP,seeds12,N)
    print(f"  mirror K19: {w}W {l}L {d}D (expect near-symmetric, no death-spiral)")
    print("\nFINVAL DONE")

if __name__=="__main__":
    main()
