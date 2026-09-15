#!/usr/bin/env python3
"""Sweep staging-burst attack configs (gen_attack.gen) vs the opponent suite.

Signals:
  bot_turtle  -> can the burst convert the structural draw into WINS?
  bot_swarm/bot_rival -> does an offense-heavy proto still beat them (or collapse)?
  my-bot      -> head-to-head vs the strong baseline.

Run:  python sweep_attack.py [seeds]
"""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path
from gen_attack import gen

HERE = Path(__file__).resolve().parent
PY = sys.executable or "python"
TOOL = str(HERE / "testing-tool.py")
RESULT_RE = re.compile(r"RESULT\s+(LEFT_WIN|RIGHT_WIN|DRAW)\s+(\w+)")

OPPONENTS = ["my-bot", "bot_turtle", "bot_rival"]
SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
START = 5000   # fresh seed range to check robustness of the always+earlyHQ finding

CONFIGS: dict[str, dict] = {
    "hq_rush":   {"ATTACK_WHEN": "always", "ATTACK_TGT": "hq",   "ATTACK_MIN_HQ": 2},
    "econ_hq2":  {"ATTACK_WHEN": "always", "ATTACK_TGT": "econ", "ATTACK_MIN_HQ": 2},
    "econ_hq3":  {"ATTACK_WHEN": "always", "ATTACK_TGT": "econ", "ATTACK_MIN_HQ": 3},
    "econ_hq4":  {"ATTACK_WHEN": "always", "ATTACK_TGT": "econ", "ATTACK_MIN_HQ": 4},
    "econ_b8":   {"ATTACK_WHEN": "always", "ATTACK_TGT": "econ", "ATTACK_MIN_HQ": 2, "BURST_MIN": 8},
    "econ_b16":  {"ATTACK_WHEN": "always", "ATTACK_TGT": "econ", "ATTACK_MIN_HQ": 2, "BURST_MIN": 16},
    "econ_lose": {"ATTACK_WHEN": "losing", "ATTACK_TGT": "econ", "ATTACK_MIN_HQ": 2},
}


def one_game(left: str, right: str, seed: int) -> str | None:
    cmd = [PY, TOOL, "--seed", str(seed),
           "--exec1", f'{PY} "{left}"', "--exec2", f'{PY} "{right}"',
           "--log", str(HERE / "_atk_tmp.log")]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    m = RESULT_RE.search(out.stdout) or RESULT_RE.search(out.stderr)
    return m.group(1) if m else None


def score(bot: str, opp: str) -> tuple[int, int, int]:
    w = l = d = 0
    botp, oppp = str(HERE / bot), str(HERE / f"{opp}.py")
    for i in range(SEEDS):
        seed = START + i
        if i % 2 == 0:
            res, a_left = one_game(botp, oppp, seed), True
        else:
            res, a_left = one_game(oppp, botp, seed), False
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
    for name, cfg in CONFIGS.items():
        p = HERE / f"_atk_{name}.py"
        gen(cfg, p)
        bots[name] = f"_atk_{name}.py"
    print(f"seeds/opp = {SEEDS} (both orientations)\n")
    header = f"{'config':16s} " + " ".join(f"{o:>13s}" for o in OPPONENTS)
    print(header); print("-" * len(header))
    for name in CONFIGS:
        cells = [f"{w}W-{l}L-{d}D" for w, l, d in (score(bots[name], o) for o in OPPONENTS)]
        print(f"{name:16s} " + " ".join(f"{c:>13s}" for c in cells))


if __name__ == "__main__":
    main()
