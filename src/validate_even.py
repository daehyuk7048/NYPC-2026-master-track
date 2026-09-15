import sys
sys.path.insert(0, ".")
from finval3 import matrix
NEW = "proto_r91c.py"; OFF = "proto_r91c_off.py"
s12 = list(range(2000, 2012))
# label = M.K = 2*KP+1 ;  (NP, KP)
K = {9:(26,4), 11:(33,5), 13:(40,6), 19:(52,9)}
def line(m): print(m, flush=True)

line("=== crack-0 add M.K=11 (KP5) ===")
cf=False
for opp in ("bot_rush.py","bot_waverush.py"):
    NP,KP=K[11]; w,l,d,cr=matrix(NEW,opp,NP,KP,s12,f"c{opp[4]}11")
    if cr>0: cf=True
    line(f"  {opp:14s} MK11: {w}W {l}L {d}D cracks={cr} {'*FAIL*' if cr>0 else 'ok'}")
line(f"  crack MK11: {'FAIL' if cf else 'ok'}")

line("=== EVEN-MATCHUP NO-REGRESS: NEW vs OFF (M.K 9/11/13/19) ===")
regs=[]
for opp in ("bot_turtle.py","bot_climber.py","bot_grinder.py","bot_swarm.py","my-bot.py","bot_pusher.py"):
    for mk in (9,11,13,19):
        NP,KP=K[mk]
        wN,lN,dN,_=matrix(NEW,opp,NP,KP,s12,"eN")
        wB,lB,dB,_=matrix(OFF,opp,NP,KP,s12,"eB")
        reg=(wN<wB) or (wN==wB and lN>lB)
        if reg: regs.append(f"{opp} MK{mk}")
        tag="  <-- REGRESSION" if reg else ("  (better)" if wN>wB else "")
        line(f"  {opp:14s} MK{mk}: NEW {wN}W{lN}L{dN}D | OFF {wB}W{lB}L{dB}D{tag}")
line("=== MIRROR ===")
for mk in (9,11,13,19):
    NP,KP=K[mk]
    wN,lN,dN,_=matrix(NEW,NEW,NP,KP,s12,"mN")
    wB,lB,dB,_=matrix(OFF,OFF,NP,KP,s12,"mB")
    line(f"  mirror MK{mk}: NEW {wN}W{lN}L{dN}D | OFF {wB}W{lB}L{dB}D")
line(f"=== VERDICT: {'*** REGRESSIONS: '+', '.join(regs)+' ***' if regs else 'PASS no draw->loss'} ===")
line("EVEN_DONE")
