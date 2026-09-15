#!/usr/bin/env python3
"""bot_grinder: mimics the real 7/8 econ-swarmer.

Unlike bot_swarm (all-in HQ/base rush), the grinder:
  - keeps a real ECONOMY (claims bases, climbs HQ toward L5), so games go long and
    the day-200 HQ tiebreak decides them; and
  - once it has a wave, parks a big STACK on the opponent's nearest FORWARD stronghold
    and grinds it (sieges it, holds), one base at a time -- it does NOT beeline the HQ.
This is exactly the pattern proto's RELIEF logic must intercept. Reuses bot_swarm's
verified I/O framework (imported), overriding only decide().
"""
from __future__ import annotations
import sys
from collections import Counter, defaultdict
import bot_swarm as B
from bot_swarm import (WState, BType, Actions, GameState, GameMap, Nav, BOT,
                       BASE_LEVELS, HQ_LEVELS, HQ_MAX_LEVEL, WORK_INCOME, TRAIN_COST,
                       GOLD_FLOOR, UPKEEP_PER_WARRIOR, _is_max, _next_cost, _train_cap)

MUSTER = 12
MIN_RAID = 6
ECON_BASES = 5        # a REAL economy (more bases than bot_swarm)
GRIND_HOLD = 5        # keep grinding the same target for at least this many turns before retargeting


def _decide_impl(S, M, nav, turn, a):
    if not BOT.inited:
        B._init_bot(M, nav)
    me = M.my_side
    my = [w for w in S.warriors if w.id.side is me]
    enemy = [w for w in S.warriors if w.id.side is not me]
    my_b = [b for b in S.buildings if b.side is me]
    my_bases = [b for b in my_b if b.type is BType.BASE]
    hq = S.find_building(M.my_hq)
    enemy_at = {w.region for w in enemy}
    my_present = {w.region for w in my}

    reserve = GOLD_FLOOR + UPKEEP_PER_WARRIOR * (len(my) + 1)
    spent = 0

    def can(c):
        return S.gold - spent - c >= reserve

    def ulegal(r):
        return r in my_present and r not in enemy_at

    ups = set()

    def up(r, c):
        nonlocal spent
        if r in ups:
            return
        spent += c; a.upgrades.append(r); ups.add(r)

    # economy: claim our strongholds as bases, climb HQ all the way to L5
    for w in my:
        if (w.state is WState.STATIONARY and w.region in BOT.claim_set
                and S.find_building(w.region) is None and w.region not in ups
                and w.region not in enemy_at and len(my_bases) < ECON_BASES and turn < 150):
            if can(BASE_LEVELS[1].cost):
                up(w.region, BASE_LEVELS[1].cost)
    if hq and not _is_max(hq) and ulegal(hq.region) and hq.region not in ups:
        c = _next_cost(hq)
        if S.gold - spent >= c + reserve + 150 and can(c):
            up(hq.region, c)
    if hq and hq.hp < hq.current_hp() and ulegal(hq.region) and hq.region not in ups:
        c = _next_cost(hq)
        if can(c):
            up(hq.region, c)

    # GRIND TARGET: the opponent's nearest FORWARD building to THEIR hq (so we sit deep
    # in their half on their stronghold), sticky for GRIND_HOLD turns. Fall back to opp HQ.
    opp_blds = [b.region for b in S.buildings
                if b.side is not me and b.type is BType.BASE]
    sticky = getattr(BOT, "grind_tgt", -1)
    sticky_t = getattr(BOT, "grind_set", -999)
    if opp_blds and (sticky not in opp_blds or turn - sticky_t >= GRIND_HOLD):
        sticky = min(opp_blds, key=lambda r: nav.hops(M.opp_hq, r))
        BOT.grind_tgt = sticky
        BOT.grind_set = turn
    target = sticky if (opp_blds and sticky in opp_blds) else M.opp_hq

    # split workers vs army
    stat = [w for w in my if w.state is WState.STATIONARY]
    at = defaultdict(list)
    for w in stat:
        at[w.region].append(w)
    need = {b.region: b.work_cap() for b in my_b}
    if hq:
        need[M.my_hq] = max(need.get(M.my_hq, 0), 1)
    workers = set()
    for r, c in need.items():
        for w in at.get(r, [])[:c]:
            workers.add(w.id)
    army = [w for w in stat if w.id not in workers]

    assigned = set()

    def mv(w, t):
        nonlocal spent
        if w.id in assigned or w.state is not WState.STATIONARY or t == w.region:
            return
        if not nav.reachable(w.region, t):
            return
        b = S.find_building(t)
        c = 0 if (b and b.side is me) else B.MOVE_COST
        if c and not can(c):
            return
        spent += c; a.moves.append((w.id, t)); assigned.add(w.id)

    if len(army) >= MUSTER:
        BOT.raiding = True
    if len(army) < MIN_RAID:
        BOT.raiding = False

    if BOT.raiding and army:
        cnt = Counter(w.region for w in army)
        stack = cnt.most_common(1)[0][0]
        at_stack = [w for w in army if w.region == stack]
        together = len(at_stack) >= max(MIN_RAID, int(0.7 * len(army)))
        if stack == target:
            for w in army:
                if w.region != stack:
                    mv(w, stack)
        elif together:
            nh = nav.next_hop(stack, target)
            if nh >= 0:
                for w in at_stack:
                    mv(w, nh)
            for w in army:
                if w.region != stack:
                    mv(w, stack)
        else:
            for w in army:
                if w.region != stack:
                    mv(w, stack)
    else:
        for w in army:
            if w.region != M.my_hq:
                mv(w, M.my_hq)

    if hq:
        cap = _train_cap(hq)
        n = cap
        while n > 0 and not can(TRAIN_COST * n):
            n -= 1
        a.train_n = n


B._decide_impl = _decide_impl   # not strictly needed; we call our own below


def decide(S, M, nav, turn):
    a = Actions()
    try:
        _decide_impl(S, M, nav, turn, a)
    except Exception as e:
        if B.DEBUG:
            print(f"# grinder err t{turn}: {e}", file=sys.stderr, flush=True)
    return a


def main():
    M, S = B.parse_init()
    nav = Nav(M)
    nav.warm()
    while (turn := B.read_turn_start()) is not None:
        a = decide(S, M, nav, turn)
        B.emit(a)
        B.read_turn_result(S, M, a)


if __name__ == "__main__":
    main()
