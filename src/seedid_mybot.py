import re, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; PY=sys.executable or "python"; TOOL=str(HERE/"testing-tool.py")
RX=re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")
def run(l,r,s,NP,KP):
    o=subprocess.run([PY,TOOL,"--seed",str(s),"--NP",str(NP),"--KP",str(KP),"--exec1",f'{PY} "{HERE/l}"',"--exec2",f'{PY} "{HERE/r}"',"--log",str(HERE/"_sm.log")],capture_output=True,text=True,timeout=400)
    m=RX.search(o.stdout) or RX.search(o.stderr); return (m.group(1),m.group(2)) if m else ("ERR","")
def sweep(NP,KP,label):
    print(f"--- {label} ---"); sys.stdout.flush()
    for i,s in enumerate(range(2000,2012)):
        aL=(i%2==0)
        for bot,nm in (("proto-bot.py","ON "),("proto_r104off.py","OFF")):
            L,R=(bot,"my-bot.py") if aL else ("my-bot.py",bot)
            res,rs=run(L,R,s,NP,KP); we="L" if aL else "R"
            won=(res=="LEFT_WIN")==aL and res!="DRAW"; out="WIN" if won else("DRAW" if res=="DRAW" else "LOSS")
            print(f"  s{s} we={we} {nm}: {out} ({res} {rs})"); sys.stdout.flush()
try: sys.stdout.reconfigure(encoding="utf-8")
except: pass
sweep(40,6,"mybotK13"); print("SEEDID_MB_DONE")
