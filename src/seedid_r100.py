#!/usr/bin/env python3
"""Per-seed flip finder: swarm K11 + my-bot K9, ON vs OFF, with reasons."""
import re, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RX = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")
def run_game(left, right, seed, NP, KP, tag):
    cmd = [PY, TOOL, "--seed", str(seed), "--NP", str(NP), "--KP", str(KP),
           "--exec1", f'{PY} "{HERE/left}"', "--exec2", f'{PY} "{HERE/right}"',
           "--log", str(HERE / f"_seed_{tag}.log")]
    o = subprocess.run(cmd, capture_output=True, text=True, timeout=400)
    m = RX.search(o.stdout) or RX.search(o.stderr)
    return (m.group(1) if m else "ERR", m.group(2) if m else "")
def sweep(opp, NP, KP, label):
    print(f"--- {label} ---"); sys.stdout.flush()
    for i, s in enumerate(range(2000, 2012)):
        a_left = (i % 2 == 0)
        for bot, nm in (("proto-bot.py", "ON "), ("proto_r100off.py", "OFF")):
            L, R = (bot, opp) if a_left else (opp, bot)
            res, reason = run_game(L, R, s, NP, KP, f"{label}_{s}_{nm.strip()}")
            we = "L" if a_left else "R"
            won = (res == "LEFT_WIN") == a_left and res != "DRAW"
            out = "WIN" if won else ("DRAW" if res == "DRAW" else "LOSS")
            print(f"  s{s} we={we} {nm}: {out} ({res} {reason})"); sys.stdout.flush()
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
sweep("bot_swarm.py", 33, 5, "swarmK11")
sweep("my-bot.py", 26, 4, "mybotK9")
print("SEEDID_DONE")
