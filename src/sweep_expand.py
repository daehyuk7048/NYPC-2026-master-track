#!/usr/bin/env python3
"""Sweep aggressive-EXPANSION proto configs and tally vs the opponent suite.

Strategy under test (user): take enemy-side land with many units (occupy their
strongholds -> permanent economy swing + denial), upgrade the HQ SLOWLY (economy
leads). Each preset = a set of knob overrides applied to my-bot.py source.

Knobs:
  CONTEST_REACH      how far into enemy ground we claim strongholds (2=base, 99=all)
  MAX_CLAIMERS       claimers dispatched per turn (3=base, higher=expand faster)
  WORKERS_PER_BASE   workers kept per base (2=base, 1=more bodies pushed forward)
  TERRITORY_SLACK    tolerate enemy lead before contesting (0=base)
  MUSTER             raid commit size when ahead (6=base, lower=commit sooner)
  EXPAND_FIRST_BASES NEW: keep HQ at L2 until we own this many bases (1=base = off,
                     higher = slow upgrade / expand first)

Run:  python sweep_expand.py [seeds]
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
SRC = (HERE / "my-bot.py").read_text(encoding="utf-8")

# Discriminating opponents only (swarm/rival are always 8-0 -> no signal).
OPPONENTS = ["my-bot", "bot_turtle"]
SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
START = 1234

# Single-knob perturbations around control to map the gradient and find the optimum.
PRESETS: dict[str, dict] = {
    "control":   {},
    "reach1":    {"CONTEST_REACH": 1},
    "reach3":    {"CONTEST_REACH": 3},
    "claim4":    {"MAX_CLAIMERS": 4},
    "claim5":    {"MAX_CLAIMERS": 5},
    "workers1":  {"WORKERS_PER_BASE": 1},
    "muster4":   {"MUSTER": 4},
    "slack1":    {"TERRITORY_SLACK": 1},
    "efb3":      {"EXPAND_FIRST_BASES": 3},
}


def make_bot(cfg: dict, out: Path) -> None:
    code = SRC
    # Always inject EXPAND_FIRST_BASES (default 1 = baseline behaviour) + gate the
    # HQ L2->L5 climb behind owning that many bases.
    efb = cfg.get("EXPAND_FIRST_BASES", 1)
    if "CONTEST_REACH = " not in code:
        raise SystemExit("anchor CONTEST_REACH missing")
    code = code.replace(
        "CONTEST_REACH = ",
        f"EXPAND_FIRST_BASES = {efb}  # proto: keep HQ at L2 until this many bases\nCONTEST_REACH = ",
        1,
    )
    if "        elif len(my_bases) >= 1:" not in code:
        raise SystemExit("anchor 'elif len(my_bases) >= 1' missing")
    code = code.replace(
        "        elif len(my_bases) >= 1:",
        "        elif len(my_bases) >= EXPAND_FIRST_BASES:",
        1,
    )
    # Apply the remaining scalar knob overrides by rewriting the top-level constant.
    for name, val in cfg.items():
        if name == "EXPAND_FIRST_BASES":
            continue
        code, n = re.subn(rf"(?m)^{re.escape(name)}\s*=.*$", f"{name} = {val}", code, count=1)
        if n != 1:
            raise SystemExit(f"knob not found/unique: {name}")
    out.write_text(code, encoding="utf-8")


def one_game(left: str, right: str, seed: int) -> str | None:
    cmd = [PY, TOOL, "--seed", str(seed),
           "--exec1", f'{PY} "{left}"', "--exec2", f'{PY} "{right}"',
           "--log", str(HERE / "_sweep_tmp.log")]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    m = RESULT_RE.search(out.stdout) or RESULT_RE.search(out.stderr)
    return m.group(1) if m else None


def score(bot: str, opp: str) -> tuple[int, int, int]:
    w = l = d = 0
    botp = str(HERE / bot)
    oppp = str(HERE / f"{opp}.py")
    for i in range(SEEDS):
        seed = START + i
        if i % 2 == 0:
            res = one_game(botp, oppp, seed); a_left = True
        else:
            res = one_game(oppp, botp, seed); a_left = False
        if res is None:
            continue
        if res == "DRAW":
            d += 1
        elif (res == "LEFT_WIN") == a_left:
            w += 1
        else:
            l += 1
    return w, l, d


def main() -> None:
    bots = {}
    for name, cfg in PRESETS.items():
        path = HERE / f"_proto_{name}.py"
        make_bot(cfg, path)
        bots[name] = f"_proto_{name}.py"
    print(f"seeds/opp = {SEEDS} (both orientations)\n")
    header = f"{'preset':14s} " + " ".join(f"{o:>14s}" for o in OPPONENTS)
    print(header)
    print("-" * len(header))
    for name in PRESETS:
        cells = []
        for opp in OPPONENTS:
            w, l, d = score(bots[name], opp)
            cells.append(f"{w}W-{l}L-{d}D")
        print(f"{name:14s} " + " ".join(f"{c:>14s}" for c in cells))


if __name__ == "__main__":
    main()
