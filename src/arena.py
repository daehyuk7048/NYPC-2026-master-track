#!/usr/bin/env python3
"""Tiny arena: run BOT_A vs BOT_B over many seeds (both orientations) and tally.

Usage:
  python arena.py <botA.py> <botB.py> [num_seeds] [start_seed]

Reports wins from BOT_A's perspective, swapping sides each seed so neither bot
gets a fixed LEFT/RIGHT advantage. Prints W/L/D and the HQ-tiebreak detail.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RESULT_RE = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")


def one_game(left: str, right: str, seed: int) -> tuple[str, str]:
    cmd = [PY, TOOL, "--seed", str(seed),
           "--exec1", f'{PY} "{left}"',
           "--exec2", f'{PY} "{right}"',
           "--log", str(HERE / "_arena_tmp.log")]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    m = RESULT_RE.search(out.stdout) or RESULT_RE.search(out.stderr)
    if not m:
        return ("ERR", out.stdout.strip()[:80] + " " + out.stderr.strip()[:80])
    return (m.group(1), m.group(2))


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    botA = str((HERE / sys.argv[1]).resolve())
    botB = str((HERE / sys.argv[2]).resolve())
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    start = int(sys.argv[4]) if len(sys.argv) > 4 else 1000

    nameA, nameB = Path(botA).stem, Path(botB).stem
    wins = losses = draws = errs = 0
    by_reason: dict[str, int] = {}
    for i in range(n):
        seed = start + i
        # alternate orientation so A plays LEFT on even, RIGHT on odd seeds
        if i % 2 == 0:
            res, reason = one_game(botA, botB, seed)
            a_is_left = True
        else:
            res, reason = one_game(botB, botA, seed)
            a_is_left = False
        if res == "ERR":
            errs += 1
            print(f"seed {seed}: ERR {reason}")
            continue
        a_won = (res == "LEFT_WIN" and a_is_left) or (res == "RIGHT_WIN" and not a_is_left)
        b_won = (res == "RIGHT_WIN" and a_is_left) or (res == "LEFT_WIN" and not a_is_left)
        if res == "DRAW":
            draws += 1
            tag = "DRAW"
        elif a_won:
            wins += 1
            tag = f"{nameA} WIN"
        else:
            losses += 1
            tag = f"{nameB} WIN"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        print(f"seed {seed}: {res:10s} {reason:13s} -> {tag}")

    total = wins + losses + draws
    print("-" * 50)
    print(f"{nameA} vs {nameB}  ({n} games)")
    print(f"  {nameA}: {wins}W  {losses}L  {draws}D"
          + (f"  ({errs} ERR)" if errs else ""))
    if total:
        print(f"  winrate(excl draws): {wins}/{wins+losses}"
              + (f" = {100*wins/(wins+losses):.0f}%" if wins + losses else ""))
    print(f"  reasons: {by_reason}")


if __name__ == "__main__":
    main()
