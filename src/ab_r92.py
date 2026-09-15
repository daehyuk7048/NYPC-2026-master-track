#!/usr/bin/env python3
"""Surgical A/B: proto-bot.py (MG_HOLD_BASE=1) vs _r92_off.py (flag off), per-seed, per-cell.
Confirms the flag ONLY changes the intended cells (waverush losing regime) and leaves every
other cell result-identical. Usage: python _ab_r92.py <opp.py> <NP> <KP>"""
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
    return (f"{m.group(1)}/{m.group(2)}" if m else "ERR")

def cell(bot, opp, NP, KP, seeds, tag):
    res = {}
    for i, s in enumerate(seeds):
        a_left = (i % 2 == 0); L, R = (bot, opp) if a_left else (opp, bot)
        res[s] = (run_game(L, R, s, NP, KP, HERE / f"_ab92_{tag}.log"), a_left)
    return res

def main():
    opp = sys.argv[1] if len(sys.argv) > 1 else "bot_waverush.py"
    NP = int(sys.argv[2]) if len(sys.argv) > 2 else 33
    KP = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    seeds = list(range(2000, 2012))
    on = cell("proto-bot.py", opp, NP, KP, seeds, "on")
    off = cell("_r92_off.py", opp, NP, KP, seeds, "off")
    diffs = 0
    for s in seeds:
        ro, _ = on[s]; rf, side = off[s]
        mark = "" if ro == rf else "  <<< CHANGED"
        if ro != rf: diffs += 1
        print(f"  seed {s} side={'L' if side else 'R'}  ON={ro:22s} OFF={rf:22s}{mark}")
    print(f"{opp} K(NP{NP}/KP{KP}): {diffs} cell(s) changed by MG_HOLD_BASE")

if __name__ == "__main__":
    main()
