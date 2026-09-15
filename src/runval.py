#!/usr/bin/env python3
"""NP-controlled arena: A vs B over seeds at a FIXED map size, alternating orientation.

Usage:
  python runval.py <botA.py> <botB.py> <NP> [num_seeds] [start_seed]

N = 2*NP + 1.  NP=26 -> N53, NP=28 -> N57 (compact 7/8), NP=41 -> N83 (game-4).
Reports W/L/D from A's perspective + per-game final HQ levels and total siege A->B / B->A
(parsed from the referee log) so we can see HOW games are decided, not just the result.
"""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RESULT_RE = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")


def parse_log(logpath: str):
    """Return (A_hq_lvl, B_hq_lvl, siege_to_A, siege_to_B) from a finished log.
    LEFT=A, RIGHT=B in the log. A HQ region=0, B HQ region=N-1."""
    try:
        lines = Path(logpath).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return (None, None, 0, 0)
    N = int(lines[3].split()[0]); A_HQ, B_HQ = 0, N - 1
    a_lvl = b_lvl = 1; sA = sB = 0
    for t in lines:
        t = t.strip()
        if t.startswith("UPGRADE A ") and int(t.split()[2]) == A_HQ: a_lvl += 1
        elif t.startswith("UPGRADE B ") and int(t.split()[2]) == B_HQ: b_lvl += 1
        elif t.startswith("SIEGE A "): sA += int(t.split()[3])
        elif t.startswith("SIEGE B "): sB += int(t.split()[3])
    return (a_lvl, b_lvl, sA, sB)


def one_game(left, right, seed, NP, KP, logpath):
    cmd = [PY, TOOL, "--seed", str(seed), "--NP", str(NP), "--KP", str(KP),
           "--exec1", f'{PY} "{left}"', "--exec2", f'{PY} "{right}"',
           "--log", logpath]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=400)
    m = RESULT_RE.search(out.stdout) or RESULT_RE.search(out.stderr)
    if not m:
        return ("ERR", (out.stdout + " " + out.stderr).strip()[:120], (None, None, 0, 0))
    return (m.group(1), m.group(2), parse_log(logpath))


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    botA = str((HERE / sys.argv[1]).resolve())
    botB = str((HERE / sys.argv[2]).resolve())
    NP = int(sys.argv[3])
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    start = int(sys.argv[5]) if len(sys.argv) > 5 else 2000
    KP = int(sys.argv[6]) if len(sys.argv) > 6 else 4   # K=2*KP+1 (4->9, 6->13)
    nameA, nameB = Path(botA).stem, Path(botB).stem
    logp = str(HERE / f"_runval_{nameA}_{nameB}_{NP}.log")

    wins = losses = draws = errs = 0
    by_reason = {}
    for i in range(n):
        seed = start + i
        a_left = (i % 2 == 0)
        L, R = (botA, botB) if a_left else (botB, botA)
        res, reason, (la, lb, sA, sB) = one_game(L, R, seed, NP, KP, logp)
        if res == "ERR":
            errs += 1; print(f"seed {seed}: ERR {reason}"); continue
        a_won = (res == "LEFT_WIN") == a_left and res != "DRAW"
        # HQ levels / siege from A's perspective
        if a_left: aHQ, bHQ, sToA, sToB = la, lb, sA, sB
        else:      aHQ, bHQ, sToA, sToB = lb, la, sB, sA
        if res == "DRAW": draws += 1; tag = "DRAW"
        elif a_won:       wins += 1;  tag = f"{nameA} WIN"
        else:             losses += 1; tag = f"{nameB} WIN"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        print(f"seed {seed}: {res:10s} {reason:11s} HQ A{aHQ}/B{bHQ}  siege A>{sToB} B>{sToA}  -> {tag}")

    print("-" * 64)
    print(f"{nameA} vs {nameB}  (NP={NP}, N={2*NP+1}, {n} games)")
    print(f"  {nameA}: {wins}W  {losses}L  {draws}D" + (f"  ({errs} ERR)" if errs else ""))
    if wins + losses:
        print(f"  winrate(excl draws): {wins}/{wins+losses} = {100*wins/(wins+losses):.0f}%")
    print(f"  reasons: {by_reason}")


if __name__ == "__main__":
    main()
