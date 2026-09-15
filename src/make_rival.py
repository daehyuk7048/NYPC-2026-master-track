#!/usr/bin/env python3
"""Build bot_rival.py from bot_swarm.py — approximates the REAL log-7/8 opponent.

Difference from the toy bot_swarm (which my-bot beats 20-0 by backdooring its
undefended HQ): the rival KEEPS A HOME GUARD at its HQ (so the backdoor can't crack
it) and reliably climbs its HQ toward L5. This reproduces the 7/8 failure mode
(opponent wins the day-200 hp tiebreak) for local testing.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / "bot_swarm.py").read_text(encoding="utf-8")

DELTAS: list[tuple[str, str, str]] = []

DELTAS.append((
    'MIN_RAID = 6          # never advance the stack below this\n'
    'HQ_TARGET_EARLY = 3   # rush HQ to lvl3 (train_cap 2) early',
    'MIN_RAID = 6          # never advance the stack below this\n'
    'HQ_TARGET_EARLY = 3   # rush HQ to lvl3 (train_cap 2) early\n'
    'HOME_GUARD = 5        # warriors kept on the HQ so a backdoor cannot crack it',
    "const HOME_GUARD",
))

# Split off a HOME_GUARD (lowest-id army warriors) — these never raid.
DELTAS.append((
    '    army = [w for w in stat if w.id not in workers]\n',
    '    army_all = [w for w in stat if w.id not in workers]\n'
    '    army_sorted = sorted(army_all, key=lambda w: w.id.num)\n'
    '    guard = army_sorted[:min(len(army_sorted), HOME_GUARD)]\n'
    '    army = army_sorted[min(len(army_sorted), HOME_GUARD):]\n',
    "split guard",
))

# After mv() exists, pin the guard onto the HQ (reinforce every turn).
DELTAS.append((
    '    # ---- raid state machine ----\n',
    '    # ---- home guard holds the HQ (defends the backdoor) ----\n'
    '    for w in guard:\n'
    '        if w.region != M.my_hq:\n'
    '            mv(w, M.my_hq)\n\n'
    '    # ---- raid state machine ----\n',
    "guard-home moves",
))

out = src
for find, repl, label in DELTAS:
    if find not in out:
        raise SystemExit(f"rival delta MISS: {label}")
    if out.count(find) != 1:
        raise SystemExit(f"rival delta NON-UNIQUE: {label}")
    out = out.replace(find, repl)
    print(f"applied: {label}")

(HERE / "bot_rival.py").write_text(out, encoding="utf-8")
print(f"wrote bot_rival.py ({len(out.splitlines())} lines)")
