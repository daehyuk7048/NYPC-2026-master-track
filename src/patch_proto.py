#!/usr/bin/env python3
"""Regenerate proto-bot.py from my-bot.py — a MORE AGGRESSIVE counter-doomstack tune.

my-bot.py already implements the user's counter-doomstack (race the enemy's open HQ
when we are LOSING the land+HQ-level race and its stack has committed forward). On all
local proxies that machinery is a verified NO-OP (no proxy reproduces the
losing-while-enemy-stack-forward scenario), so it cannot be tuned by local play -- only
vs the real opponent. This proto exposes a strictly-more-aggressive tune of the SAME
gated machinery (fire at a smaller deficit, with a bigger counter stack) for that
real-opponent sweep, while staying a no-op / no-regression on the local suite.

Sweep these against the real opponent with arena.py; keep whatever wins, since the
"even => offense is -EV" rule means only a genuinely-losing matchup can benefit.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / "my-bot.py").read_text(encoding="utf-8")

DELTAS: list[tuple[str, str, str]] = []

DELTAS.append((
'''#!/usr/bin/env python3
"""
nation-providing bot — v1: "Safe Economist + Tiebreak Insurance + Opportunistic Chip"''',
'''#!/usr/bin/env python3
"""
nation-providing PROTO — my-bot.py + a bigger counter-stack (COUNTER_QUOTA 8->12).
Same hard gate as my-bot -- the counter fires ONLY when losing (2+ base deficit AND
not ahead on HQ level) & the enemy stack is forward -- so it is a strict no-op in
mirrors/even games (verified). NOTE: LOSE_MARGIN 1->0 was tried and REVERTED: firing
the econ->army reserve drop at a 1-base deficit threw a near-mirror game vs my-bot
(the "even => offense is -EV" rule again). Original baseline header follows:

bot — v1: "Safe Economist + Tiebreak Insurance + Opportunistic Chip"''',
    "docstring",
))

# Build a bigger race stack so it can actually crack the (briefly) open enemy HQ.
# Only spends when ALREADY losing (the gated `losing` flag), so it is a no-op locally.
DELTAS.append((
    'COUNTER_QUOTA = 8   # counter-stack size to accumulate when losing',
    'COUNTER_QUOTA = 12  # PROTO: bigger race stack to crack the open enemy HQ in-window',
    "COUNTER_QUOTA 12",
))

out = src
for find, repl, label in DELTAS:
    if find not in out:
        raise SystemExit(f"delta MISS: {label}")
    if out.count(find) != 1:
        raise SystemExit(f"delta NON-UNIQUE ({out.count(find)}x): {label}")
    out = out.replace(find, repl)
    print(f"applied: {label}")

(HERE / "proto-bot.py").write_text(out, encoding="utf-8")
print(f"wrote proto-bot.py ({len(out.splitlines())} lines)")
