#!/usr/bin/env python3
"""g2 counterfactuals: referee-exact HQ-fight sim (verified against replay t15-21)
+ full gold model per scenario.
Referee rules (verified): trained/arriving units fight the turn they appear;
atk_cap/def_cap fixed at turn start; siege = max(0, atk_count - sum(def HP));
turret adds attacks while HQ hp>0; damage kills lowest-HP first.
Turn order: train(spend) -> combat/siege -> income -> upkeep."""

HQ_HP0 = 10
TURRET = 1
WHP = 4          # L1 warrior hp both sides
TRAIN = 120
INC = 15
UPK = 2

def dmg_assign(units, dmg):
    out = []
    for h in sorted(units):
        if dmg <= 0: out.append(h)
        elif dmg >= h: dmg -= h
        else: out.append(h - dmg); dmg = 0
    return sorted(out)

def fight(name, t0, def0, atk_arr, def_arr, gold0, income_fn, train_policy, floor_fn, tmax=40, verbose=True):
    """def0: defender hps at t0 start. atk_arr/def_arr: {turn: [hp,...]} joining that turn.
    gold0: our gold at decide(t0). income_fn(t, ndef_alive): our income at end of turn t.
    train_policy: 'floor' (respect can(): gold >= 120+floor), 'bypass' (gold>=120), 'none'.
    floor_fn(nwar): reserve amount."""
    hq = HQ_HP0
    defs = sorted(def0)
    atks = []
    gold = gold0
    trained = 0
    log = []
    for t in range(t0, t0 + tmax):
        atks = sorted(atks + atk_arr.get(t, []))
        defs = sorted(defs + def_arr.get(t, []))
        # 1) train (cap 1/turn, L1 HQ)
        tr = 0
        if train_policy != 'none' and atks:  # only during/around fight; pre-fight trains are in def_arr
            need = TRAIN + (floor_fn(len(defs) + 1) if train_policy == 'floor' else 0)
            if gold >= need:
                gold -= TRAIN; defs = sorted(defs + [WHP]); tr = 1; trained += 1
        if not atks:
            log.append(f"  t{t}: attackers wiped. HQ={hq}/10, defenders left={len(defs)} gold={gold}")
            break
        # 2) combat
        atk_cap = len(atks)
        def_cap = len(defs) + (TURRET if hq > 0 else 0)
        siege = max(0, atk_cap - sum(defs))
        hq -= siege
        defs2 = dmg_assign(defs, atk_cap)
        atks2 = dmg_assign(atks, def_cap)
        cracked = hq <= 0
        log.append(f"  t{t}: atk {len(atks)}({sum(atks)}hp) vs def {len(defs)}({sum(defs)}hp)+turret"
                   f"{' +train' if tr else ''} | siege={siege} HQ={max(hq,0)}/10 -> atk {len(atks2)} def {len(defs2)} gold={gold}")
        defs, atks = defs2, atks2
        if cracked:
            log.append(f"  t{t}: *** HQ DESTROYED ***")
            break
        # 3) income / upkeep
        gold += income_fn(t, len(defs)) - UPK * len(defs)
        gold = max(0, gold)
    else:
        log.append(f"  (horizon) HQ={hq}/10 def={len(defs)} atk={len(atks)}")
    result = "HQ DESTROYED" if hq <= 0 else ("HELD (attackers dead)" if not atks else "HELD (horizon)")
    print(f"[{name}] -> {result} | trained_during_fight={trained}")
    if verbose:
        for ln in log: print(ln)
    print()
    return hq > 0

ATK = {15: [WHP]*4, 16: [WHP]*2}   # A3-A6 land t15, A2/A7 land t16

floor = lambda nw: 60 + UPK * (nw + 1)

print("=" * 100)
print("S0 BASELINE VERIFY (actual game): def B1,B2,B3 at t15; bot trained B4 at t16; income 15/turn")
# actual: gold at decide t15 = 186 -> bot could NOT train (needs 188). t16: reserve drops (B1 died) -> trains.
# emulate exactly: 'floor' policy reproduces it.
fight("S0 actual", 15, [WHP]*3, ATK, {}, 186, lambda t, nd: INC if nd else 0, 'floor', floor)

print("=" * 100)
print("S1 SKIP BASE-68 @t11, everything else = bot's own logic (rescue latch t12, floor respected)")
print("gold check: decide t12 = 414 (390 - 0 + inc30 - upk6, no 300g spend, B3 idle on 68)")
# trains: t12 (414>=188), t13 (294+30-8=316>=188), t14 (316-120=196 +15-10=201>=188 -> B6)
# B4@t12, B5@t13, B6@t14 all home; B2,B3 recalled t13 arrive t14 (as actual).
# So def at t15 = B1,B2,B3,B4,B5,B6 = 6. gold at decide t15 = 201-120=81 +15-12 = 84.
fight("S1 skip-base68", 15, [WHP]*6, ATK, {}, 84, lambda t, nd: INC if nd else 0, 'floor', floor)

print("=" * 100)
print("S2 KEEP base-68, but rescue BYPASSES GOLD_FLOOR -> train B4 @t12 (129>=120); then broke")
# t12 train -> gold 9; end +45-8=46; t13 recall, 46+15-8=53; t14 60; t15 67 (4 def)
fight("S2 t12-train-only", 15, [WHP]*4, ATK, {}, 67, lambda t, nd: INC if nd else 0, 'bypass', floor)

print("=" * 100)
print("S3 GARRISON SWEEP: m defenders standing at t15, NO trains, no gold")
for m in range(3, 8):
    fight(f"m={m}", 15, [WHP]*m, ATK, {}, 0, lambda t, nd: 0, 'none', floor, verbose=(m in (4, 5)))

print("=" * 100)
print("S4 DETECT @t8 (rush-calculator): freeze economy, train t8,t9,t10; skip base-68; recall t13")
# t8: gold 342-120=222 end +30-8=244 ; t9: 244-120=124 +30-10=144 ; t10: 144-120=24 +30-12=42
# t11: 42+30-12=60 ; t12: 60+30-12=78 ; t13 recall: 78+15-12=81 ; t14: 84 -> def 6 at t15, gold 84
fight("S4 detect-t8", 15, [WHP]*6, ATK, {}, 84, lambda t, nd: INC if nd else 0, 'floor', floor)

print("=" * 100)
print("S5 LATE-BY-ONE: skip base-68 but claimers recalled only t14 (arrive t15 mid-fight)")
# B2,B3 arrive during t15 -> still count at t15 start? They arrive in t15's MOVE results = fight t15.
fight("S5 recall-t14", 15, [WHP]*4, ATK, {15: [], 16: []}, 84,
      lambda t, nd: INC if nd else 0, 'floor', floor)
print("(S5: def0 counts B1+B4+B5+B6; B2,B3 modeled as arriving t15 below)")
fight("S5b recall-t14 arrivals@t15", 15, [WHP]*4, ATK, {15: [WHP]*2}, 84,
      lambda t, nd: INC if nd else 0, 'floor', floor)
