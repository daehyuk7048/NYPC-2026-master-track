#!/usr/bin/env python3
"""Final REACH_WIN (widened windows) confirmation: rush gate + my-bot K13 + mirrors."""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
from finval3 import matrix

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    s12 = list(range(2000, 2012))
    print("=== RUSH HARD GATE ===", flush=True)
    for kk, (NP, KP) in {9: (26, 4), 13: (40, 6), 19: (52, 9)}.items():
        w, l, d, cr = matrix("proto-bot.py", "bot_rush.py", NP, KP, s12, f"f5r{kk}")
        print(f"  rush K{kk}: {w}W {l}L {d}D cracks={cr}", flush=True)
    print("=== my-bot K13 (NEW vs OFF) ===", flush=True)
    for bot, tag in (("proto-bot.py", "NEW"), ("_rw_off.py", "OFF")):
        w, l, d, _ = matrix(bot, "my-bot.py", 40, 6, s12, f"f5m{tag}")
        print(f"  {tag}: {w}W {l}L {d}D", flush=True)
    print("=== MIRRORS ===", flush=True)
    for kk, (NP, KP) in {13: (40, 6), 19: (52, 9)}.items():
        w, l, d, _ = matrix("proto-bot.py", "proto-bot.py", NP, KP, s12, f"f5mirN{kk}")
        wB, lB, dB, _ = matrix("_rw_off.py", "_rw_off.py", NP, KP, s12, f"f5mirB{kk}")
        print(f"  mirror K{kk}: NEW {w}W{l}L{d}D | OFF {wB}W{lB}L{dB}D", flush=True)
    print("FINVAL5 DONE")

if __name__ == "__main__":
    main()
