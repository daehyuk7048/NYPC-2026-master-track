#!/usr/bin/env python3
"""R100 EARLY_PUSH isolated A/B: proto-bot.py (EARLY_PUSH=1) vs proto_r100off.py (=0).
Narrow gate M.K<=12 => only K9/K11 can differ; K13/K19 must be byte-identical.
Focus: rush/wave K9/K11 (crack-0 hard gate) + grinder K9/K11 (narrow expander positive-test)
+ K13/K19 sanity (must show ON==OFF)."""
from __future__ import annotations
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
    return (m.group(1) if m else "ERR", m.group(2) if m else "")

def matrix(botL, opp, NP, KP, seeds, tag):
    w = l = d = 0; cr = 0
    for i, s in enumerate(seeds):
        a_left = (i % 2 == 0); L, R = (botL, opp) if a_left else (opp, botL)
        res, reason = run_game(L, R, s, NP, KP, HERE / f"_ab_{tag}.log")
        if res == "ERR": continue
        won = (res == "LEFT_WIN") == a_left and res != "DRAW"
        if res == "DRAW": d += 1
        elif won: w += 1
        else:
            l += 1
            if reason in ("HQ_DESTROYED", "RAZE"): cr += 1
    return w, l, d, cr

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    K = {9: (26, 4), 11: (33, 5), 13: (40, 6), 19: (52, 9)}
    s12 = list(range(2000, 2012))
    ON = "proto-bot.py"; OFF = "proto_r100off.py"
    # in-scope: crack-0 gates on narrow K9/K11 + narrow expander positive test
    plan = [("bot_rush.py", (9, 11, 13, 19)),
            ("bot_waverush.py", (9, 11, 13, 19)),
            ("bot_grinder.py", (9, 11)),
            ("my-bot.py", (13, 19))]  # K13/19 sanity: must be ON==OFF
    for opp, ks in plan:
        for kk in ks:
            NP, KP = K[kk]
            wN, lN, dN, cN = matrix(ON, opp, NP, KP, s12, "on")
            wF, lF, dF, cF = matrix(OFF, opp, NP, KP, s12, "off")
            tag = ""
            if cN > cF: tag = "  <-- CRACK REGRESSION"
            elif wN < wF or (wN == wF and lN > lF): tag = "  <-- WIN REGRESSION"
            elif wN > wF: tag = "  (better)"
            elif (wN, lN, dN, cN) == (wF, lF, dF, cF): tag = "  [identical]"
            print(f"  {opp:16s} K{kk:2d}: ON {wN}W{lN}L{dN}D cr{cN} | OFF {wF}W{lF}L{dF}D cr{cF}{tag}")
            sys.stdout.flush()
    print("AB_R100_DONE")

if __name__ == "__main__":
    main()
