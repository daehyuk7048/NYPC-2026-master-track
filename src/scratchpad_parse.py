import re, sys, os
def parse(log):
    rows=[]; sa=0
    for ln in open(log, encoding='utf-8', errors='ignore'):
        m=re.search(r'Debug LEFT: HIDBG (.*)', ln)
        if m:
            d={}
            for kv in m.group(1).split():
                k,v=kv.split('=')
                d[k]=v
            rows.append(d)
        if re.search(r'\bSIEGE A\b', ln):
            mm=re.search(r'SIEGE A \S+ (\d+)', ln)
            if mm: sa+=int(mm.group(1))
    return rows, sa

for tag in ['hion','hioff']:
    for s in [2000,2001,2002]:
        log=f"{tag}_{s}.log"
        rows,sa=parse(log)
        # events
        hi_fires=[r['t'] for r in rows if r.get('hi_go')=='1']
        wout=[r for r in rows if r.get('workers_out')=='1']
        wout_turns=[int(r['t']) for r in rows]
        # first workers_out turn
        first_wout=next((r['t'] for r in rows if r.get('workers_out')=='1'),None)
        # eligible-window turns: 3<=E<10, d<=6, adv=1, veto='-'
        elig=[r for r in rows if r.get('E','0').isdigit() and 3<=int(r['E'])<10 and int(r['d'])<=6 and r['adv']=='1' and r['veto']=='-']
        # any sub-wave (3-9) advancing within reach that reached on_hq later
        onhq=[r for r in rows if int(r.get('on_hq','0'))>0]
        print(f"\n##### {tag} seed {s}: SIEGE_A_total={sa}")
        print(f"  hi_go fired turns: {hi_fires if hi_fires else 'NEVER'}")
        print(f"  workers_out turns (on_hq>0): {[r['t'] for r in wout] if wout else 'NONE'}")
        print(f"  HI-eligible-window turns (3<=E<10,d<=6,adv=1,veto=-): {[(r['t'],r['E'],r['d'],r['rf']) for r in elig] if elig else 'NONE'}")
        # min stack dist reached with E in 3-9
        sub=[r for r in rows if r.get('E','0').isdigit() and 3<=int(r['E'])<10]
        if sub:
            md=min(int(r['d']) for r in sub)
            print(f"  min d reached by a 3-9 stack: {md}")
