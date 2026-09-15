import re
def rows(log):
    out=[]
    for ln in open(log, encoding='utf-8', errors='ignore'):
        m=re.search(r'Debug LEFT: HIDBG (.*)', ln)
        if m:
            d=dict(kv.split('=') for kv in m.group(1).split())
            out.append(d)
    return out
# For a given log, show every turn where on_hq>0 plus the 3 turns before it
for log in ['hion_2000.log','hion_2002.log','hioff_2001.log']:
    R=rows(log); print(f"\n===== {log} : on_hq events with lead-in =====")
    idx={int(r['t']):i for i,r in enumerate(R)}
    shown=set()
    for i,r in enumerate(R):
        if int(r['on_hq'])>0:
            for j in range(max(0,i-2),i+1):
                t=int(R[j]['t'])
                if t in shown: continue
                shown.add(t)
                rr=R[j]
                print(f"  t={rr['t']} E={rr['E']} d={rr['d']} on_hq={rr['on_hq']} adv={rr['adv']} rf={rr['rf']} veto={rr['veto']} conc={rr['conc']} mil={rr['mil']} workers_out={rr['workers_out']}")
