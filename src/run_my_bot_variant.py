#!/usr/bin/env python3
"""Run my-bot.py with small source-level experiment switches.

This helper is for local analysis only. It leaves the submission bot unchanged.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--relaxed-home-safe", action="store_true")
    ap.add_argument("--hq-direct-raid", action="store_true")
    ap.add_argument("--hq-deny-raid", action="store_true")
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Replace a top-level constant assignment in my-bot.py.",
    )
    args = ap.parse_args()

    path = Path(__file__).with_name("my-bot.py")
    code = path.read_text(encoding="utf-8")

    if args.relaxed_home_safe:
        code = code.replace(
            "home_safe = (on_hq == 0 and threat == 0)",
            "home_safe = (on_hq == 0 and not concentrate)",
        )
        code = re.sub(
            r"\n    if BOT\.threat_army > 0:\n"
            r"        # MOBILIZING:[\s\S]*?"
            r"        BOT\.raiding = False\n",
            "\n    if BOT.threat_army > 0 and concentrate:\n"
            "        BOT.raiding = False\n",
            code,
            count=1,
        )

    if args.hq_direct_raid:
        code = code.replace(
            "        ebases = sorted(enemy_base_regs, key=lambda r: nav.hops(M.my_hq, r))\n"
            "        hitlist = ebases + [M.opp_hq]\n"
            "        target = next((r for r in hitlist if S.find_building(r) is not None), M.opp_hq)",
            "        target = M.opp_hq",
        )

    if args.hq_deny_raid:
        code = code.replace(
            "        ebases = sorted(enemy_base_regs, key=lambda r: nav.hops(M.my_hq, r))\n"
            "        hitlist = ebases + [M.opp_hq]\n"
            "        target = next((r for r in hitlist if S.find_building(r) is not None), M.opp_hq)",
            "        enemy_hq = S.find_building(M.opp_hq)\n"
            "        if enemy_hq is not None and not _is_max(enemy_hq):\n"
            "            target = M.opp_hq\n"
            "        else:\n"
            "            ebases = sorted(enemy_base_regs, key=lambda r: nav.hops(M.my_hq, r))\n"
            "            hitlist = ebases + [M.opp_hq]\n"
            "            target = next((r for r in hitlist if S.find_building(r) is not None), M.opp_hq)",
        )

    for assignment in args.set:
        if "=" not in assignment:
            raise SystemExit(f"--set must be NAME=VALUE, got {assignment!r}")
        name, value = assignment.split("=", 1)
        name = name.strip()
        value = value.strip()
        code, n = re.subn(
            rf"(?m)^{re.escape(name)}\s*=.*$",
            f"{name} = {value}",
            code,
            count=1,
        )
        if n != 1:
            raise SystemExit(f"constant not found or not unique: {name}")

    ns = {"__name__": "__main__", "__file__": str(path)}
    exec(compile(code, str(path), "exec"), ns)


if __name__ == "__main__":
    main()
