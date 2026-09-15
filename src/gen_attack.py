#!/usr/bin/env python3
"""Generate an OFFENSE-maximal proto from my-bot.py (defense handled elsewhere).

Two ideas, both knob-controlled:
  (1) staging-burst: gather the true surplus on a node ADJACENT to the target, then
      once BURST_MIN are staged move them ALL on the same turn -> one day's siege can
      crack/chip before reinforcement (3/turn) or a 1000g heal responds.
  (2) target selection ATTACK_TGT:
        'hq'   -> rush the enemy HQ (chip its hp -> tiebreak)
        'econ' -> EAT the enemy's OCCUPIED strongholds (their BASES) first: capturing
                  them denies their income AND (via the build logic) flips it to us,
                  so we out-economy them. Fall back to the HQ only when they have no
                  bases left. This fixes the "stream onto bare land / HQ-front path
                  node" behaviour the user flagged in the real logs.

Knobs (overridable): PROTO_ATTACK, ATTACK_WHEN, ATTACK_TGT, BURST_MIN, ATTACK_MIN_HQ,
STAGE_BURST. The home garrison (2a) is still filled first, so only the TRUE surplus
assaults.
"""
from __future__ import annotations
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = (HERE / "my-bot.py").read_text(encoding="utf-8")

HELPERS = '''
def _staging_node(M, nav, target):
    """Neighbor of `target` closest to OUR HQ -- gather here, one hop away, then burst."""
    best, bestd = target, 1 << 30
    for nb in M.adj[target]:
        d = nav.hops(nb, M.my_hq)
        if d < bestd:
            bestd, best = d, nb
    return best


def _assault_target(S, M, nav, me):
    """Pick what to assault. 'econ': eat the enemy's nearest OCCUPIED stronghold (their
    base) to flip economy; fall back to the HQ only when no enemy base remains."""
    if ATTACK_TGT != 'hq':
        ebases = [b.region for b in S.buildings
                  if b.side is not me and b.type is BType.BASE]
        if ebases:
            return min(ebases, key=lambda r: nav.hops(M.my_hq, r))
    return M.opp_hq


def _assault(force, target, stage, nav, order_move):
    """Staging-burst assault on `target` (an enemy base or the HQ)."""
    if not STAGE_BURST:
        for w in force:
            if w.region != target:
                order_move(w, target)
        return
    staged = sum(1 for w in force if w.region == stage or w.region == target)
    if staged >= BURST_MIN:
        for w in force:                       # BURST: staged -> target same turn
            if w.region == stage or w.region == target:
                order_move(w, target)         # (no-op if already on target -> hold & siege)
            else:
                order_move(w, stage)          # latecomers keep gathering for next wave
    else:
        for w in force:                       # GATHER on the staging node, hold
            if w.region != stage and w.region != target:
                order_move(w, stage)


def _sim_crack(atk_hps, base_hp, turret, def_hps, max_turns):
    """REFEREE-EXACT siege simulation (validated 1:1 against apply_day_combat/apply_day_siege).
    Attackers (list of hp) vs a building (base_hp, turret) defended by def_hps. Each turn BOTH
    sides' attack COUNTS are fixed at the start; our overflow beyond defender HP sieges the base;
    their (defenders + turret) attacks kill our lowest-HP units. Returns (cracked, turns, survivors)."""
    ours = sorted(atk_hps)
    theirs = sorted(def_hps)
    bh = base_hp
    for t in range(1, max_turns + 1):
        if not ours:
            return (False, t - 1, 0)
        our_cap = len(ours)
        their_cap = len(theirs) + (turret if bh > 0 else 0)
        siege = our_cap - sum(theirs)             # overflow past the defenders sieges the building
        if siege > 0:
            bh -= siege
        dmg = our_cap                             # our attacks also kill their lowest units
        nt = []
        for h in theirs:
            if dmg <= 0:
                nt.append(h)
            elif dmg >= h:
                dmg -= h
            else:
                nt.append(h - dmg); dmg = 0
        theirs = sorted(nt)
        cracked = bh <= 0
        dmg = their_cap                           # their counterattack (count fixed at turn start)
        no = []
        for h in ours:
            if dmg <= 0:
                no.append(h)
            elif dmg >= h:
                dmg -= h
            else:
                no.append(h - dmg); dmg = 0
        ours = sorted(no)
        if cracked:
            return (True, t, len(ours))
    return (False, max_turns, len(ours))


def _can_crack(S, M, grp, target, max_turns):
    """Can `grp` (our warriors) actually DESTROY the building at `target` before being wiped?
    Referee-exact. True if there is no building there (nothing to crack)."""
    b = S.find_building(target)
    if b is None:
        return True
    turret = (HQ_LEVELS if b.type is BType.HQ else BASE_LEVELS)[b.level].turret
    me = M.my_side
    defs = [w.hp for w in S.warriors if w.region == target and w.id.side is not me and w.hp > 0]
    return _sim_crack([w.hp for w in grp], b.hp, turret, defs, max_turns)[0]


def _nearest_crackable(S, M, nav, force, live, max_turns):
    """The nearest LIVE enemy base this force can ACTUALLY destroy (referee-exact); -1 if none."""
    for r in sorted(live, key=lambda r: nav.hops(M.my_hq, r)):
        if _can_crack(S, M, force, r, max_turns):
            return r
    return -1


def _raid_advance(M, nav, force, target, order_move):
    """MONOTONIC march: every unit steps exactly one hop toward `target`, so its distance to the
    target strictly DECREASES each turn -> it can NEVER oscillate (the game-6 0<->5 ping-pong bug
    came from a 'regroup onto the most-common node' rule that let the front and stragglers swap).
    Units already on the target hold & siege it; the fist starts bunched at the HQ so it stays
    together and arrives. A razed base drops out of `live` next turn -> the caller retargets."""
    for w in force:
        if w.region == target:
            continue
        nh = nav.next_hop(w.region, target)
        order_move(w, nh if nh >= 0 else target)


def _withdraw(M, nav, force, ctx, order_move):
    fr = ctx['friendlies']
    home = M.my_hq
    for w in force:
        d = min(fr, key=lambda f: nav.hops(w.region, f)) if fr else home
        if w.region != d:
            order_move(w, d)


def _raid_commit(S, M, nav, force, live, order_move, ctx):
    """COMMIT to ONE crackable base and march the whole fist there (monotonic) until it falls or the
    lock expires -- target commitment is what kills the per-turn re-pick oscillation. If nothing is
    crackable, WITHDRAW to the nearest friendly base and watch for a fixed spell before re-checking.
    STALLED-SIEGE GUARD: a base we stay locked on for the FULL spell WITHOUT razing it (the enemy
    reinforces/heals faster than we chip -- the game-7/8 'park 6 units on the centre base dealing
    1 dmg/turn for 100 turns' waste) is abandoned: blacklist it for a watch and pull the fist back
    to a friendly base so it stops bleeding on a turret it cannot break, instead of re-locking it."""
    BOT = ctx['BOT']
    live_set = set(live)
    tgt = getattr(BOT, 'raid_tgt', -2)
    lock = getattr(BOT, 'raid_lock', 0)
    if lock > 0 and tgt in live_set:               # committed to a live base -> keep marching
        BOT.raid_lock = lock - 1
        _raid_advance(M, nav, force, tgt, order_move)
        return
    if lock > 0 and tgt == -1:                      # committed WITHDRAW -> sit at a friendly base & watch
        BOT.raid_lock = lock - 1
        _withdraw(M, nav, force, ctx, order_move)
        return
    if tgt in live_set:                            # lock expired but base STILL ALIVE -> STALLED siege
        BOT.raid_skip = tgt                        # blacklist it so we don't instantly re-lock the wall
        BOT.raid_skip_lock = ctx['raid_lock']
        BOT.raid_tgt = -1
        BOT.raid_lock = ctx['watch_lock']
        _withdraw(M, nav, force, ctx, order_move)
        return
    skip = getattr(BOT, 'raid_skip', -2) if getattr(BOT, 'raid_skip_lock', 0) > 0 else -2
    BOT.raid_skip_lock = max(0, getattr(BOT, 'raid_skip_lock', 0) - 1)
    cand = [r for r in live if r != skip]
    tgt = _nearest_crackable(S, M, nav, force, cand, ctx['max_turns'])
    if tgt < 0:                                     # crack nothing -> commit to a short WATCH at home
        BOT.raid_tgt = -1
        BOT.raid_lock = ctx['watch_lock']
        _withdraw(M, nav, force, ctx, order_move)
        return
    BOT.raid_tgt = tgt
    BOT.raid_lock = ctx['raid_lock']
    _raid_advance(M, nav, force, tgt, order_move)


def _raid2(S, M, nav, raid_force, enemy_base_regs, order_move, ctx):
    """ONE coherent raid decision with COMMITMENT (anti-oscillation). Priority: defend HQ > intercept
    a beatable forward stack > recall vs a wave we cannot hold (hysteretic) > raze a committed crackable
    base (monotonic march) > hold home. Every unit always gets a live order; nothing oscillates."""
    if not raid_force:
        return
    BOT = ctx['BOT']
    home = M.my_hq

    def send(units, dst):
        for w in units:
            if w.region != dst:
                order_move(w, dst)

    live = [r for r in enemy_base_regs if S.find_building(r) is not None]
    live_set = set(live)

    if ctx['on_hq']:                               # 1) enemy on our HQ -> all home
        BOT.raid_lock = 0
        send(raid_force, home)
        return
    if ctx['intercept'] >= 0:                      # 2) mass on a beatable forward stack
        BOT.raid_lock = 0
        send(raid_force, ctx['intercept'])
        return
    # 3) RECALL vs a wave we cannot hold -- HYSTERETIC so a 1-turn can_hold flicker can't bounce us.
    #    FORTRESS (must_hold) forces the recall REGARDLESS of can_hold: late-game, out-armied, with a
    #    doomstack inbound, we do NOT gamble the surplus on an optimistic hold estimate and march it
    #    into enemy land (the game-4/5 loss: army deep in their half while a 50-stack walks into our
    #    empty HQ). Pull everyone home, defend, and climb. can_hold still governs the mid-wave case.
    if ctx['turtle'] and (ctx.get('must_hold') or not ctx['can_hold']):
        BOT.recall_lock = ctx['recall_hold']
    else:
        BOT.recall_lock = max(0, getattr(BOT, 'recall_lock', 0) - 1)
    if getattr(BOT, 'recall_lock', 0) > 0:
        BOT.raid_lock = 0
        cut = ctx['cut_force']
        if cut > 0 and live and len(raid_force) >= ctx['cut_min']:
            cutters = sorted(raid_force, key=lambda w: w.id.num)[:cut]
            cut_ids = {w.id for w in cutters}
            send([w for w in raid_force if w.id not in cut_ids], home)
            _raid_commit(S, M, nav, cutters, live, order_move, ctx)
        else:
            send(raid_force, home)
        return
    # 4) RAZE: an ACTIVE commitment (overrides offense flicker), or offense on, or turtle-but-can-hold.
    committed = getattr(BOT, 'raid_lock', 0) > 0 and getattr(BOT, 'raid_tgt', -2) in live_set
    if live and (committed or ctx['offense'] or ctx['turtle']):
        _raid_commit(S, M, nav, raid_force, live, order_move, ctx)
        return
    # 5) nothing to attack -> hold home (a few must never chip the turreted HQ).
    BOT.raid_lock = 0
    if ctx['offense'] and not live and not ctx['bank'] and len(raid_force) >= ctx['hq_min']:
        send(raid_force, M.opp_hq)
    else:
        send(raid_force, home)


'''


def gen(cfg: dict, out: Path) -> None:
    code = SRC

    # 1) constants block
    anchor = "COUNTER_DROP = 1    # when losing, drop the climb reserve -> army (econ=army)"
    if anchor not in code:
        raise SystemExit("anchor COUNTER_DROP missing")
    # Defaults = swept-best ATTACKER: capture the enemy's OCCUPIED economy (their bases)
    # when we are LOSING, with a staging burst, starting from HQ L2.
    #   vs my-bot 11-13W/0L, vs turtle 10-13W/0L (converts the structural draw via
    #   economy swing -> tiebreak), vs swarm/rival 12-14W/0L (HQ_DESTROYED). No losses.
    #   ATTACK_TGT 'econ' >> 'hq' (removes the hq-rush losses); 'losing' trigger >>
    #   'always' (don't over-commit even games); ATTACK_MIN_HQ 2 >> 3 >> 4.
    consts = (anchor + "\n"
              "PROTO_ATTACK = 1\n"
              "ATTACK_WHEN = 'losing'\n"
              "ATTACK_TGT = 'econ'\n"
              "BURST_MIN = 5\n"
              "ATTACK_MIN_HQ = 2\n"
              "STAGE_BURST = 1\n"
              "FUND_GATE = 1\n"      # 0: aggressive (always); 1: only when attacking; 2: HYBRID. REVERT: 1 so gold flows to the L5 climb, not an idle standing army
              "LATE_CLIMB = 130\n"        # from this turn, reserve the next HQ-upgrade cost
              "LATE_BACKSTOP = 150\n"     # from here: force the L5 climb regardless of enemy tempo (insurance)
              "TEMPO_DECAY = 0.6\n"       # decay for the enemy army-growth accumulator
              "TEMPO_BURST = 4.0\n"       # accumulated enemy growth above this = enemy is BURSTING units
              "TEMPO_DEV_WIN = 8\n"       # turns after an enemy upgrade we treat the enemy as DEVELOPING
              "RELIEF = 0\n"              # REVERT: off (was 1). Intercept is now the clean chain's base_eating branch; RELIEF only reduced the HQ garrison without inj4
              "RELIEF_MIN = 4\n"          # enemy stack this big sitting on our land = a grinding column (sensitive)
              "RELIEF_SLACK = 6\n"        # fire even when our army is up to this many UNDER the stack (turret covers it)
              "RELIEF_FORCE = 2\n"        # need at least guard + this many bodies to bother relieving
              "PRESTAFF = 1\n"            # staff a base's NEW work slot the same turn we upgrade it (no idle capacity)
              "MATCH_EAGER = 0\n"         # REVERT: off (was 1). Eager-matching a spread econ-swarmer built the idle 65-unit stack that starved the L5 climb (game 5)
              "THREAT_MIN = 4\n"          # ignore <=THREAT_MIN-1 isolated enemy pokers (don't pull workers off bases for 1-3 scouts)
              "HARASS_HQLEVEL = 4\n"      # PROACTIVE late-game roam: once the HQ is healthy (>=L4), send the surplus to crack/raze enemy bases (crack-aware backdoor roams; sacrosanct climb can't be starved) -- the user's 'late-game destroy-enemy-bases role'
              "FORTRESS = 0\n"            # REVERT: off (was 1). Its force-recall was the oscillation engine; defense = my-bot concentrate/garrison + the climb (each upgrade heals the HQ)
              "FORTRESS_TURN = 120\n"     # earliest turn the fortress mode may engage (the 'late game' boundary)
              "FORTRESS_ARMY = 14\n"      # an enemy TOTAL army this big late = a doomstack we should not race -> turtle the tiebreak
              "FORTRESS_SLACK = 4\n"      # engage even when the enemy army is up to this many UNDER ours (don't raid out & lose the HQ)
              "FORTRESS_RANGE = 8\n"      # enemy units within this many hops of our HQ (on our half) count as INBOUND (ETA proxy)
              "FORTRESS_MIN = 6\n"        # this many inbound enemies also trips the fortress even below FORTRESS_ARMY
              "FORTRESS_HOLD = 1\n"       # in fortress mode, HOLD the army home (suppress harass/counter, recall raiders)
              "PRESSURE = 0\n"            # REVERT: off (was 1). PRESSURE funded a standing raid army from HQ-L3 that never got used coherently and starved the climb
              "PRESSURE_TURN = 60\n"      # from this turn, proactively pressure the enemy's economy (the user: 'attack happens too late' -> start the mid-game economy-denial earlier, surplus-only so the HQ guard is untouched)
              "PRESSURE_HQLEVEL = 3\n"    # ...once the HQ is a working economy at this level
              "PRESSURE_FORCE = 6\n"      # target raiding-force size committed to economy-denial (a real two-front stack, not a lone picked-off scout)
              "SUPPLY_CUT = 0\n"          # REVERT: off (was 1). Consumed only by the removed _raid2 dispatcher
              "SUPPLY_CUT_WAVE = 10\n"    # ...only against a genuine wave this big (their whole army is forward, rear open)
              "SUPPLY_CUT_FORCE = 4\n"    # squad size sent to cut supply (enough to crack a base: turret + lone worker)
              "SUPPLY_CUT_MIN = 4\n"      # only peel when we have at least this much TRUE surplus beyond the HQ garrison (defense never shorted)
              "KEEP_ECON = 0\n"           # REVERT: off (was 1). Use the stock my-bot recall-on-concentrate; fewer interacting knobs
              "RAID_HOLD = 6\n"           # raid COMMITMENT: once raiders go out, keep them committed this many turns through trigger flicker (anti-oscillation)
              "RAID_ADVANCE_RADIUS = 4\n"  # the raid front advances once the LOCAL fist is assembled (don't stall on bare land waiting for far recruits)
              "BANK_HQ = 1\n"             # the user's late-game doctrine: once mid-late & not behind on bases, do NOT rebuild razed enemy strongholds (no gold sink) and stop funding new claimers -> the surplus gold banks into the HQ climb (close the HP gap) + military, while raiders just RAZE enemy bases and leave the land empty
              "BANK_HQ_TURN = 110\n"      # ...from this turn onward (the user's 'mid-late game'); raze enemy bases but don't rebuild -> our richer economy maxes the HQ while theirs can't
              "CRACK = 1\n"               # referee-exact siege calc: a backdoor party only commits to a base it can ACTUALLY destroy; otherwise it withdraws to the nearest friendly base and watches
              "CRACK_TURNS = 30\n"        # must be able to crack the base within this many turns (else treat as uncrackable -> don't waste the party)
              "CRACK_DEFENSE = 1\n"       # when the enemy comes to finish us, judge if the home garrison can HOLD; if yes keep razing, if no recall to help
              "HOLD_MARGIN = 2\n"         # require holding the incoming wave even with this many EXTRA attackers (safety buffer vs reinforcement)
              "RAID_LOCK = 10\n"          # COMMIT to one crackable base for this many turns (monotonic march, no per-turn re-pick oscillation)
              "WATCH_LOCK = 4\n"          # when nothing is crackable, sit & watch at a friendly base this long before re-checking (no withdraw<->advance flicker)
              "RECALL_HOLD = 3\n"         # once we judge we cannot hold a wave, keep recalling this many turns (no recall<->raze flicker)
              "GAMBLE = 1\n")             # when LOSING the HQ-level tiebreak (our HQ level < enemy's), let backdoor raiders target the enemy HQ IF crackable (the user's 모험수). Safe-by-construction: fires ONLY when behind on HQ level -> inert in games we win or draw, active only in a losing game (e.g. game 7 L3<L4)
    code = code.replace(anchor, consts, 1)

    # 2) helper functions before _two_front_raid
    a2 = "def _two_front_raid(S, M, nav, raid_force, enemy_base_regs, order_move):"
    if a2 not in code:
        raise SystemExit("anchor _two_front_raid missing")
    code = code.replace(a2, HELPERS + a2, 1)

    # 3) compute attack-mode flag before the garrison-need section
    a3 = ("    # --- per-building garrison need -----------------------------------------\n"
          "    # Keep economy LEAN")
    if a3 not in code:
        raise SystemExit("anchor garrison-need missing")
    inj3 = (
        "    # --- PROTO attack mode --------------------------------------------------\n"
        "    if ATTACK_WHEN == 'always':\n"
        "        _attack_now = (on_hq == 0)\n"
        "    elif ATTACK_WHEN == 'losing':\n"
        "        # RETALIATE on ECONOMY, not on HQ-level: the moment the enemy out-bases us\n"
        "        # (it raided/took our land), send the surplus to smash ITS bases so our\n"
        "        # compounding does not fall behind -- the user's rule: never let a base-trade\n"
        "        # just 'flow' into a passive economic loss (games 4/5). The old gate also\n"
        "        # required hq.level < enemy (usually false mid-game), so we never retaliated\n"
        "        # and the army sat idle while our economy bled (logs 7/8).\n"
        "        _attack_now = (_terr_deficit and on_hq == 0)\n"
        "    else:\n"
        "        _attack_now = counter_now\n"
        "    _attack_now = bool(PROTO_ATTACK) and _attack_now\n"
        "    # PROACTIVE HARASS (the user's 양동작전): once our economy is healthy (HQ >= HARASS_HQLEVEL)\n"
        "    # OR we are already behind, send the TRUE surplus to grind the enemy's bases as TWO evasive\n"
        "    # squads (_two_front_raid: two prongs on opposite flanks; a prong that meets a bigger force\n"
        "    # DISENGAGES and hits where they ain't). This denies the enemy economy so it cannot out-climb\n"
        "    # us in a quiet game (real log 5: we did zero damage and lost the HQ race by one level).\n"
        "    # RAID COMMITMENT / HYSTERESIS (the user's 'tangled / wasted units / idle after\n"
        "    # cracking a base'): the per-turn triggers FLICKER on compact maps (terr_deficit and\n"
        "    # concentrate toggle as the enemy stack jitters at the midline), so marginal units\n"
        "    # bounced home<->out every turn and never progressed. Decide the harass ONCE and HOLD\n"
        "    # it for RAID_HOLD turns: once raiders commit, _two_front_raid keeps advancing them and\n"
        "    # RETARGETS to the next enemy base when one falls (no idling). Cleanly separated from\n"
        "    # the turtle regime: a committed wave (concentrate) or enemy-on-HQ clears the hold so\n"
        "    # defense takes over without a tug-of-war.\n"
        "    _harass_raw = (bool(PROTO_ATTACK) and on_hq == 0 and not concentrate and hq is not None\n"
        "                   and (_terr_deficit or hq.level >= HARASS_HQLEVEL))\n"
        "    if _harass_raw:\n"
        "        BOT.harass_hold = RAID_HOLD\n"
        "    elif on_hq > 0 or concentrate:\n"
        "        BOT.harass_hold = 0\n"
        "    else:\n"
        "        BOT.harass_hold = max(0, getattr(BOT, 'harass_hold', 0) - 1)\n"
        "    _harass_now = (bool(PROTO_ATTACK) and on_hq == 0 and not concentrate\n"
        "                   and (_harass_raw or BOT.harass_hold > 0))\n\n"
        "    # --- enemy TEMPO (reactive; never schedule the HQ climb by turn alone) ---\n"
        "    # The real opponents flip modes by STATE, not clock: when their development\n"
        "    # stalls they convert spare gold into a UNIT BURST and strike all at once;\n"
        "    # once it lands they resume upgrading. So (a) climb the HQ only in a SAFE\n"
        "    # window (enemy is upgrading / not massing) -- a fixed-turn stall just hands\n"
        "    # them the burst trigger -- and (b) ride out their burst on defense.\n"
        "    _e_tot = len(enemy_warriors)\n"
        "    _e_lvl = 0\n"
        "    for _b in S.buildings:\n"
        "        if _b.side is not me:\n"
        "            _e_lvl += _b.level\n"
        "    _grow = _e_tot - getattr(BOT, 'e_tot_prev', _e_tot)\n"
        "    if _grow < 0:\n"
        "        _grow = 0\n"
        "    BOT.e_growth = getattr(BOT, 'e_growth', 0.0) * TEMPO_DECAY + _grow\n"
        "    if _e_lvl > getattr(BOT, 'e_lvl_prev', _e_lvl):\n"
        "        BOT.e_dev_turn = turn\n"
        "    BOT.e_tot_prev = _e_tot\n"
        "    BOT.e_lvl_prev = _e_lvl\n"
        "    _since_dev = turn - getattr(BOT, 'e_dev_turn', -99)\n"
        "    _enemy_burst = (BOT.e_growth >= TEMPO_BURST) and (_since_dev > TEMPO_DEV_WIN)\n"
        "    _enemy_dev = (_since_dev <= TEMPO_DEV_WIN) and not _enemy_burst\n"
        "    # Climb the HQ hard only to CATCH UP (we are strictly behind the enemy's HQ\n"
        "    # level -- a tiebreak gap we must close) or as a late-game L5 backstop; never\n"
        "    # while the enemy is BURSTING onto us (ride that out on defense), and never\n"
        "    # greedily ahead (that starves the economy that funds the expensive top steps).\n"
        "    _behind_hq = (hq is not None and hq.level < _ehl0)\n"
        "    # --- LATE-GAME FORTRESS / TIEBREAK-MAX (the user's rule) -----------------\n"
        "    # Real losses 4/5: the enemy out-develops us, masses a 23-25 doomstack and STORMS\n"
        "    # our HQ while our army is OFF raiding (game 4), or we trade armies in a race we\n"
        "    # cannot win and the HQ stalls at L3 (games 5/7 -- the climb was disabled exactly\n"
        "    # during the enemy's mass-train because _hq_climb_window forbade _enemy_burst).\n"
        "    # The user's call: late-game, estimate when the enemy army can REACH our HQ; if we\n"
        "    # cannot out-field it, STOP attacking, hold everyone home, and pour gold into the HQ\n"
        "    # so it MAXES (L5/30hp). A turreted L5 + full garrison HOLDS the siege, and if it\n"
        "    # still reaches turn 200 the maxed HQ wins the tiebreak (game 8 won exactly so).\n"
        "    _inbound = sum(1 for _w in enemy_warriors\n"
        "                   if nav.hops(_w.region, M.my_hq) <= FORTRESS_RANGE\n"
        "                   and nav.hops(_w.region, M.my_hq) <= nav.hops(_w.region, M.opp_hq))\n"
        "    _fortress = (bool(FORTRESS) and turn >= FORTRESS_TURN and hq is not None\n"
        "                 and enemy_total >= len(my_warriors) - FORTRESS_SLACK\n"
        "                 and (enemy_total >= FORTRESS_ARMY or _inbound >= FORTRESS_MIN))\n"
        "    if _fortress and FORTRESS_HOLD:\n"
        "        # hold the army home (don't raid out into a lost-HQ trade) and don't race out --\n"
        "        # the recall itself is in section 2c via home_safe (and _harass/counter off here)\n"
        "        _harass_now = False\n"
        "        counter_now = False\n"
        "    # Climb the HQ to L5 to CATCH UP (strictly behind the enemy HQ level), as a late\n"
        "    # backstop, OR all through the fortress buildup -- ignoring the enemy unit BURST in\n"
        "    # that case (we have committed to the tiebreak; each upgrade heals the HQ + adds\n"
        "    # siege-soak). The climb still pauses the instant a stack COMMITS (not concentrate),\n"
        "    # where surviving the imminent hit via training outranks one more level.\n"
        "    # BANK-HQ (the user's tiebreak plan): mid-late, when we are NOT behind in territory,\n"
        "    # stop REBUILDING razed enemy bases and bank our income LEAD into the HQ climb. We\n"
        "    # out-earn the enemy, so we reach L5 (30hp) fast while razing keeps theirs from doing\n"
        "    # the same -> we win the day-200 HP tiebreak (real game 7: we rebuilt bases instead of\n"
        "    # upgrading and stalled at L3). Self-correcting: the instant the enemy out-bases us\n"
        "    # (_e_bases > my_bases) this turns off and we contest territory again.\n"
        "    _e_bases = sum(1 for _b in S.buildings if _b.side is not me and _b.type is BType.BASE)\n"
        "    _bank_hq = (bool(BANK_HQ) and hq is not None and not _is_max(hq)\n"
        "                and turn >= BANK_HQ_TURN and len(my_bases) >= _e_bases)\n"
        "    _climb_safe = (on_hq == 0 and not concentrate and hq is not None and not _is_max(hq))\n"
        "    _climb_pressed = (on_hq == 0 and hq is not None and not _is_max(hq))\n"
        "    # L5-SACROSANCT (regression fix): in every lost game the HQ stalled at L2/L3/L4 below the\n"
        "    # enemy and we lost the day-200 HP tiebreak -- the ONLY thing that decides a no-kill game.\n"
        "    # The old window locked the climb OFF during an enemy unit-burst and outside a behind/late\n"
        "    # window, so vs a continuously-training econ-swarmer (games 5/6) we never climbed. Make the\n"
        "    # climb the unconditional first claim on surplus gold: climb WHENEVER home is safe (no enemy\n"
        "    # on the HQ, no committed wave) and we are below L5. Each upgrade also heals the HQ to full,\n"
        "    # so climbing IS defense; it only pauses for a genuine committed assault (not concentrate).\n"
        "    _hq_climb_window = _climb_safe\n"
        "    # KEEP-ECON (the user's point 2): turtling must not needlessly STARVE income. The\n"
        "    # siege math says a turreted HQ + a right-sized garrison HOLDS, so once we have the\n"
        "    # bodies to fully garrison the HQ we keep WORKERS_PER_BASE earning on each base rather\n"
        "    # than idling them home -- early over-recall bleeds income that compounds into the gap.\n"
        "    # Guarded so the garrison is NEVER shorted: only keep base staffing when, after it, we\n"
        "    # still have >= defenders_needed bodies for the HQ. Late game (fortress) full-turtles.\n"
        "    _keep_econ = (bool(KEEP_ECON) and on_hq == 0 and turn < FORTRESS_TURN\n"
        "                  and len(my_warriors) - len(my_bases) * WORKERS_PER_BASE >= defenders_needed)\n"
        "    # --- RELIEF: intercept an enemy column grinding our forward bases --------\n"
        "    # The real econ-swarmers (logs 7/8) never beeline our HQ -- they park a stack\n"
        "    # ON our forward strongholds and grind them one by one, far enough from HQ that\n"
        "    # the HQ-turtle never triggers, so our army oscillates idle while our economy\n"
        "    # (and the L5 climb it funds) collapses. Detect a stack SITTING ON/next to one\n"
        "    # of OUR buildings and march the surplus onto it to FIGHT -- on our own turreted\n"
        "    # ground we hold even slightly outnumbered (siege/turn = stack - our defender HP,\n"
        "    # and the turret adds attacks). The 'on our land' test keeps this from diverting\n"
        "    # the HQ-rush vs a stack merely TRANSITING toward our HQ (the beeline proxies).\n"
        "    _relief = (bool(RELIEF) and on_hq == 0 and stack_reg >= 0\n"
        "               and enemy_stack_sz >= RELIEF_MIN\n"
        "               and stack_dist > CONCENTRATE_DIST\n"
        "               and stack_dist < nav.hops(stack_reg, M.opp_hq)\n"
        "               and (stack_reg in my_building_regions\n"
        "                    or any(nb in my_building_regions for nb in M.adj[stack_reg]))\n"
        "               and len(my_warriors) >= enemy_stack_sz - RELIEF_SLACK\n"
        "               and len(my_warriors) >= guard_floor + RELIEF_FORCE)\n"
        "    # When relieving, the ONLY threat is that forward stack (it is sitting on our\n"
        "    # base, not our HQ -- on_hq==0). Don't let `threat` pin the whole army home; hold\n"
        "    # just the guard and send the rest as a real relief force to fight the column.\n"
        "    if _relief:\n"
        "        defenders_needed = min(len(my_warriors), guard_floor)\n\n"
        + a3)
    code = code.replace(a3, inj3, 1)

    # 3b) KEEP-ECON: don't zero base income when turtling if the HQ garrison is already covered.
    a3b = ("        elif concentrate:\n"
           "            need[b.region] = 0                                     # wave committed: everyone home to node 0")
    if code.count(a3b) != 1:
        raise SystemExit("anchor concentrate need[base]=0 not unique")
    inj3b = ("        elif concentrate:\n"
             "            need[b.region] = WORKERS_PER_BASE if _keep_econ else 0  # KEEP_ECON: garrison the HQ but keep bases earning (turret + right-sized garrison holds)")
    code = code.replace(a3b, inj3b, 1)

    # 3c) RAID TARGETING: a small raid must hit the nearest enemy ECONOMY base, NEVER beeline the
    # enemy HQ. flank_target() fell back to opp_hq whenever a flank had no enemy base, so a prong
    # repeatedly threw a few units at the turreted 30hp HQ for zero siege (real game 6: 80 move-cmds
    # onto the enemy HQ, 0 siege). The user's rule: hit the bases on the surrounding gold-land. So
    # fall back to the nearest enemy base on ANY flank; the HQ is the target ONLY once no base remains.
    a3c = ("        for r in ebases:\n"
           "            if flank(r) == fl and S.find_building(r) is not None:\n"
           "                return r\n"
           "        return M.opp_hq")
    if code.count(a3c) != 1:
        raise SystemExit("anchor flank_target not unique")
    inj3c = ("        for r in ebases:\n"
             "            if flank(r) == fl and S.find_building(r) is not None:\n"
             "                return r\n"
             "        for r in ebases:                       # no base on this flank -> nearest enemy base ANY flank\n"
             "            if S.find_building(r) is not None:  # (deny income; never chip the turreted HQ with a few units)\n"
             "                return r\n"
             "        return M.opp_hq                         # only when the enemy has NO bases left")
    code = code.replace(a3c, inj3c, 1)

    # 3d) RAID ADVANCE: the front advanced only with >=60% of the WHOLE group on it, so continuous
    # late-game training kept inflating the group and the front NEVER reached 60% -> a chunk of units
    # sat idle on a bare transit node forever (the user's game-4 "units just on bare land"). Gate on
    # 60% of the LOCAL units (within RAID_ADVANCE_RADIUS hops) instead: the front advances once the
    # nearby fist is together; distant recruits regroup and form the trailing wave, never stranded.
    a3d = "        if stack != target and len(at_stack) >= max(MIN_RAID, int(0.6 * len(grp))):"
    if code.count(a3d) != 1:
        raise SystemExit("anchor raid-advance gate not unique")
    inj3d = ("        _near = [w for w in grp if nav.hops(w.region, stack) <= RAID_ADVANCE_RADIUS]\n"
             "        if stack != target and len(at_stack) >= max(MIN_RAID, int(0.6 * len(_near))):")
    code = code.replace(a3d, inj3d, 1)

    # 3d2) CRACK-AWARE BACKDOOR (the user's repeated doctrine), added as a CONTAINED upgrade to the
    # SINGLE _two_front_raid owner -- NOT a competing dispatcher (that is exactly what tangled the
    # bot before). A prong commits ONLY to an enemy base it can ACTUALLY destroy (referee-exact
    # _can_crack); if its assigned base is too tough it retargets to the nearest base it CAN crack;
    # if it can crack NOTHING it WITHDRAWS to the nearest friendly base to watch and re-engage on an
    # opening -- never bleeding on a turret it cannot break (the game-7 stuck-siege on bases 26/31
    # that wasted the army and stalled our HQ at L3). GAMBLE: when we are LOSING the HQ-level
    # tiebreak, the enemy HQ becomes a legal crack target too (go for the kill rather than lose on
    # level -- the user's 모험수). Self-contained: reads only S/M/nav + module knobs.
    a3d2 = ("    for grp, target in prongs:\n"
            "        if not grp:\n"
            "            continue\n")
    if code.count(a3d2) != 1:
        raise SystemExit("anchor prong-loop not unique")
    inj3d2 = ("    for grp, target in prongs:\n"
              "        if not grp:\n"
              "            continue\n"
              "        if bool(CRACK) and S.find_building(target) is not None and target != M.opp_hq \\\n"
              "                and not _can_crack(S, M, grp, target, CRACK_TURNS):\n"
              "            _newt = -1\n"
              "            _mh = S.find_building(M.my_hq)\n"
              "            _eh = S.find_building(M.opp_hq)\n"
              "            _losing = (_mh is not None and _eh is not None and _mh.level < _eh.level)\n"
              "            _cands = list(ebases) + ([M.opp_hq] if (bool(GAMBLE) and _losing) else [])\n"
              "            for _r in _cands:\n"
              "                if S.find_building(_r) is not None and _can_crack(S, M, grp, _r, CRACK_TURNS):\n"
              "                    _newt = _r\n"
              "                    break\n"
              "            if _newt >= 0:\n"
              "                target = _newt\n"
              "            else:\n"
              "                _myb = [b.region for b in S.buildings if b.side is M.my_side]\n"
              "                _stk = Counter(w.region for w in grp).most_common(1)[0][0]\n"
              "                target = min(_myb, key=lambda _f: nav.hops(_stk, _f)) if _myb else M.my_hq\n")
    code = code.replace(a3d2, inj3d2, 1)

    # 3e) BANK-HQ: don't REBUILD a razed enemy base (1b) while banking for the HQ -- that build
    # cost is exactly what stalled our HQ at L3 (real game 7). Raze and move on; the gold climbs HQ.
    a3e = "                and r not in enemy_at and turn < ECON_PAYBACK_CUTOFF):"
    if code.count(a3e) != 1:
        raise SystemExit("anchor 1b base-build gate not unique")
    inj3e = "                and r not in enemy_at and turn < ECON_PAYBACK_CUTOFF and not _bank_hq):"
    code = code.replace(a3e, inj3e, 1)

    # 3f) BANK-HQ: don't fund CLAIMER bodies to expand while banking (they would just walk out and
    # sit on a razed stronghold we won't rebuild = idle upkeep). Keep them home as army / HQ income.
    a3f = ("        if unclaimed_now > 0 and on_hq == 0:\n"
           "            want_spare = max(want_spare, min(2 if behind else 1, unclaimed_now))")
    if code.count(a3f) != 1:
        raise SystemExit("anchor unclaimed want_spare not unique")
    inj3f = ("        if unclaimed_now > 0 and on_hq == 0 and not _bank_hq:\n"
             "            want_spare = max(want_spare, min(2 if behind else 1, unclaimed_now))")
    code = code.replace(a3f, inj3f, 1)

    # 3g) BANK-HQ: also drop the standing +1 expansion spare while banking.
    a3g = ("        want_spare = 1 if (turn < ECON_PAYBACK_CUTOFF and\n"
           "                           any(s not in handled_targets for s in BOT.claim_order)) else 0")
    if code.count(a3g) != 1:
        raise SystemExit("anchor early want_spare not unique")
    inj3g = ("        want_spare = 1 if (not _bank_hq and turn < ECON_PAYBACK_CUTOFF and\n"
             "                           any(s not in handled_targets for s in BOT.claim_order)) else 0")
    code = code.replace(a3g, inj3g, 1)

    # 4) attack branch at the top of the raid chain
    a4 = "    if counter_now and raid_force:"
    if code.count(a4) != 1:
        raise SystemExit("anchor raid-chain not unique")
    inj4 = (
        "    # CONSOLIDATED RAID (refactor): one coherent decision replaces the stacked, overlapping\n"
        "    # raid branches that flip-flopped units each turn and stranded them on bare land after a\n"
        "    # base fell. Build the context and dispatch to _raid2, which GUARANTEES every surplus\n"
        "    # unit gets a live order. The original elif-chain below is now unreachable (raid_force is\n"
        "    # fully handled here) but kept intact. intercept = a beatable forward stack (relief or\n"
        "    # base_eating) we should mass on; turtle = a committed wave we can't beat in the field.\n"
        "    # HOLD judgment: can the HOME GARRISON (units AT the HQ) + turret hold the incoming wave?\n"
        "    # If yes, the surplus keeps razing instead of piling idle at home; if no, it is recalled.\n"
        "    # The garrison is held home by defenders_needed regardless -- this only governs the SURPLUS.\n"
        "    _friendlies = sorted(my_building_regions)\n"
        "    _garr = [w.hp for w in my_warriors if w.region == M.my_hq]\n"
        "    _inc = [w.hp for w in enemy_warriors\n"
        "            if nav.hops(w.region, M.my_hq) <= FORTRESS_RANGE\n"
        "            and nav.hops(w.region, M.my_hq) <= nav.hops(w.region, M.opp_hq)]\n"
        "    _inc = _inc + [max((w.hp for w in enemy_warriors), default=8)] * HOLD_MARGIN\n"
        "    _can_hold = (bool(CRACK) and bool(CRACK_DEFENSE) and hq is not None\n"
        "                 and not _sim_crack(_inc, hq.hp, HQ_LEVELS[hq.level].turret, _garr, CRACK_TURNS)[0])\n"
        "    _raid_ctx = {\n"
        "        'on_hq': on_hq > 0,\n"
        "        'must_hold': bool(_fortress and FORTRESS_HOLD),\n"
        "        'intercept': stack_reg if ((_relief or base_eating) and stack_reg >= 0) else -1,\n"
        "        'turtle': bool(concentrate) or bool(_fortress and FORTRESS_HOLD),\n"
        "        'can_hold': bool(_can_hold),\n"
        "        'offense': bool(_harass_now),\n"
        "        'bank': bool(_bank_hq),\n"
        "        'cut_force': SUPPLY_CUT_FORCE if (SUPPLY_CUT and enemy_stack_sz >= SUPPLY_CUT_WAVE) else 0,\n"
        "        'cut_min': SUPPLY_CUT_MIN,\n"
        "        'hq_min': PRONG_MIN,\n"
        "        'friendlies': _friendlies,\n"
        "        'max_turns': CRACK_TURNS,\n"
        "        'BOT': BOT,\n"
        "        'raid_lock': RAID_LOCK,\n"
        "        'watch_lock': WATCH_LOCK,\n"
        "        'recall_hold': RECALL_HOLD,\n"
        "    }\n"
        "    if raid_force:\n"
        "        BOT.raiding = bool(_harass_now)\n"
        "        _raid2(S, M, nav, raid_force, enemy_base_regs, order_move, _raid_ctx)\n"
        "    elif counter_now and raid_force:")
    # REVERT (regression fix): the _raid2 dispatcher (inj4) made `if raid_force:` the FIRST
    # branch and so DEAD-CODED the validated my-bot.py raid chain (counter / base_eating /
    # BOT.raiding->_two_front_raid / muster-home). Routing every warrior through the 7-branch
    # _raid2 tangle produced the real-game 0<->adjacent ping-pong (game6 A12-A15 0<->5 for ~80
    # turns), the 22/27/31 orbit (game7), idle 65-unit stacks, and ZERO enemy-HQ sieges, while
    # its competing fortress-recall vs target-lock starved the HQ-L5 climb -> every loss was a
    # pure tiebreak (our HQ L2/L3/L4 below the enemy). SKIP the injection: the single contained
    # _two_front_raid chain (one owner per branch, monotone advance, no per-turn re-arbitration)
    # is restored -- the coherent movement behind the only repeatable real result (10W/5D/5L).
    if cfg.get('USE_RAID2', False):
        code = code.replace(a4, inj4, 1)

    # 5) fund the burst force in the train section
    a5 = "        target_army = total_need + want_spare"
    if code.count(a5) != 1:
        raise SystemExit("anchor target_army not unique")
    # Fund the burst army ONLY while actually attacking (_attack_now = losing). Funding
    # it unconditionally from HQ L2 built an idle 12-stack even when NOT losing; its
    # upkeep (2g each) drained income so the HQ never banked the L4->L5 cost and stalled
    # at L2/L3 -> day-200 tiebreak LOSS with our HQ never even sieged (real logs 5/7/8).
    # When not attacking we now climb to L5. When losing we still mass + crack (vs the
    # doomstacker proxies this still wins 12-0 by HQ_DESTROYED).
    inj5 = (
        "        if FUND_GATE == 2:\n"
        "            _fund_ok = (on_hq == 0) and (_attack_now or (hq is not None and _is_max(hq)))\n"
        "        elif FUND_GATE == 1:\n"
        "            _fund_ok = _attack_now\n"
        "        else:\n"
        "            _fund_ok = bool(PROTO_ATTACK) and on_hq == 0\n"
        "        if _fund_ok and hq is not None and hq.level >= ATTACK_MIN_HQ:\n"
        "            want_spare = max(want_spare, BURST_MIN)\n"
        "        # PROACTIVE MID-GAME PRESSURE (the user's rule: widen the gap BEFORE the\n"
        "        # last-resort doomstack). From PRESSURE_TURN, once the HQ is a working economy,\n"
        "        # fund a real raiding force so the surplus actively DENIES the enemy's bases\n"
        "        # (capturing them swings income both ways = the gap widens) instead of sitting\n"
        "        # home banking for L5. _harass_now routes it through the evasive two-front raid;\n"
        "        # fortress (late) recalls it to turtle the tiebreak, so this is the MID game only.\n"
        "        if (bool(PRESSURE) and _harass_now and turn >= PRESSURE_TURN and not _fortress\n"
        "                and hq is not None and hq.level >= PRESSURE_HQLEVEL):\n"
        "            want_spare = max(want_spare, PRESSURE_FORCE)\n"
        "        target_army = total_need + want_spare")
    code = code.replace(a5, inj5, 1)

    # 5a2) REACTIVE L5 CLIMB GATE: in section 1c the HQ climb is gated behind a lean that
    # SCALES WITH ARMY SIZE -- so matching the enemy doomstack inflates it and the HQ stays
    # frozen below L5 into the day-200 tiebreak (real logs 7/8: ours L2/L3 vs theirs L5).
    # During a SAFE window (enemy developing, or late-game backstop, no stack on our HQ),
    # drop the army-scaled lean and keep only a flat float -- the upgrade heals the HQ to
    # full, so climbing is itself defensive.
    a5a2 = ("            lean = GOLD_FLOOR + UPKEEP_PER_WARRIOR * (len(my_warriors) + 1)\n"
            "            want = (S.gold - spent) >= (cost + lean)")
    if code.count(a5a2) != 1:
        raise SystemExit("anchor 1c lean/want not unique")
    inj5a2 = (a5a2 + "\n"
              "            if _hq_climb_window and (S.gold - spent) >= (cost + GOLD_FLOOR):\n"
              "                want = True")
    code = code.replace(a5a2, inj5a2, 1)

    # 5c) PRE-STAFF base upgrades: a fresh work slot earns nothing while empty. In lean mode
    # bases hold only WORKERS_PER_BASE worker(s), so upgrading a base's work_cap adds capacity
    # we never fill -> the gold (and the turns) are wasted (the user's point). When we DO upgrade
    # a base, raise its staffing target to the post-upgrade work_cap so 2a sends a worker to fill
    # it THIS turn -- the income the upgrade paid for starts immediately, not several idle turns later.
    a5c = ("            if can(cost):\n"
           "                plan_upgrade(b.region, cost)")
    if code.count(a5c) != 1:
        raise SystemExit("anchor 1d base-upgrade not unique")
    inj5c = ("            if can(cost):\n"
             "                if plan_upgrade(b.region, cost) and PRESTAFF:\n"
             "                    need[b.region] = max(need.get(b.region, 0), BASE_LEVELS[b.level + 1].work_cap)")
    code = code.replace(a5c, inj5c, 1)

    # 5b) LATE-GAME L5 GUARANTEE: keep full aggression early, but from turn LATE_CLIMB
    # force-bank the next HQ-upgrade cost so the army's upkeep can't keep the HQ frozen
    # at L2/L3 into the day-200 tiebreak (real logs 7/8: HQ stuck L2 while the enemy
    # reached L4). Early game is untouched, so the winning aggression (AIs 1-4) stays.
    a5b = "        deficit = target_army - len(my_warriors)"
    if code.count(a5b) != 1:
        raise SystemExit("anchor deficit not unique")
    inj5b = (
        "        if ((turn >= LATE_CLIMB or _hq_climb_window) and hq is not None\n"
        "                and not _is_max(hq) and not concentrate):\n"
        "            hq_reserve = max(hq_reserve, _next_cost(hq))\n"
        "        deficit = target_army - len(my_warriors)")
    code = code.replace(a5b, inj5b, 1)

    # 5e) DON'T OVER-REACT TO SMALL POKES: a couple of enemy scouts past the midline (threat 1-3)
    # must NOT pull workers off our bases into the HQ -- doing so every time the enemy poke-cycles
    # a single unit starves our compounding (the user: "we react to <=3 enemy units, leave the gold
    # land and go home -> our economy/HQ falls behind -> can't even draw", real log 5). The standing
    # home guard + base turrets handle a scout; only a real group (>= THREAT_MIN) musters defenders.
    a5e = ("    if threat > 0:\n"
           "        defenders_needed = min(len(my_warriors), max(defenders_needed, threat + 1))")
    if code.count(a5e) != 1:
        raise SystemExit("anchor threat-bump not unique")
    inj5e = ("    if threat >= THREAT_MIN:\n"
             "        defenders_needed = min(len(my_warriors), max(defenders_needed, threat + 1))")
    code = code.replace(a5e, inj5e, 1)

    # 5d) MATCH-EAGER: unfreeze training when the enemy is OUT-PRODUCING us with a SPREAD army.
    # The stock wave-response drops the L5-reserve to train only when a concentrated stack is
    # APPROACHING (stack_dist <= gate). The real econ-swarmers (logs 7/8) keep their army spread
    # as workers -- no stack ever "approaches" -- so the reserve froze our training while we banked
    # for upgrades and we never matched their churn (the user: "they crank units, we're stuck
    # upgrading, no response"). Also fire on threat_total (out-produced by margin), stack or not.
    a5d = ("        if (n == 0 and hq_reserve > 0 and BOT.threat_army > 0\n"
           "                and len(my_warriors) < target_garrison\n"
           "                and stack_dist <= gate):")
    if code.count(a5d) != 1:
        raise SystemExit("anchor wave-response not unique")
    inj5d = ("        if (n == 0 and hq_reserve > 0\n"
             "                and len(my_warriors) < target_garrison\n"
             "                and ((BOT.threat_army > 0 and stack_dist <= gate)\n"
             "                     or (MATCH_EAGER and BOT.threat_total > 0))):")
    code = code.replace(a5d, inj5d, 1)

    # 5f) FORTRESS RECALL: in late-game fortress mode keep the army HOME. `home_safe` gates the
    # offensive raid (2c); making it False while fortressing recalls the raiders to the HQ (the
    # else-branch musters everyone home) so we never send the army out into a lost-HQ trade
    # (real game 4: our stack went raiding at t159 while the enemy's 23-stack stormed our open
    # HQ). Beatable forward stacks are still intercepted (base_eating ignores home_safe).
    a5f = "    home_safe = (on_hq == 0 and not concentrate)"
    if code.count(a5f) != 1:
        raise SystemExit("anchor home_safe not unique")
    inj5f = "    home_safe = (on_hq == 0 and not concentrate and not (_fortress and FORTRESS_HOLD))"
    code = code.replace(a5f, inj5f, 1)

    # 6) apply config overrides
    # Proto-specific tuning: react to the enemy's unit production at a SMALL margin (the stock
    # MATCH_TOTAL_MARGIN=14 only triggers once they are 14 ahead -- far too late on the compact
    # maps where the econ-swarmer out-churns us by turn ~50). cfg can still override further.
    proto_over = {"MATCH_TOTAL_MARGIN": 4}
    for name, val in proto_over.items():
        if name in cfg:
            continue
        v = f"'{val}'" if isinstance(val, str) else str(val)
        code, n = re.subn(rf"(?m)^{re.escape(name)}\s*=.*$", f"{name} = {v}", code, count=1)
        if n != 1:
            raise SystemExit(f"proto override not found/unique: {name}")
    for name, val in cfg.items():
        v = f"'{val}'" if isinstance(val, str) else str(val)
        code, n = re.subn(rf"(?m)^{re.escape(name)}\s*=.*$", f"{name} = {v}", code, count=1)
        if n != 1:
            raise SystemExit(f"override not found/unique: {name}")

    out.write_text(code, encoding="utf-8")


if __name__ == "__main__":
    import ast
    gen({}, HERE / "proto-bot.py")
    ast.parse((HERE / "proto-bot.py").read_text(encoding="utf-8"))
    print("wrote proto-bot.py (econ-capture attack): syntax OK")
