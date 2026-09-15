#!/usr/bin/env python3
"""
nation-providing bot — v1: "Safe Economist + Tiebreak Insurance + Opportunistic Chip"

Strategy (derived from referee analysis):
  - Defense dominates; most games go to the day-200 HQ-hp tiebreak.
  - Plan: out-economy (base-first), keep HQ maxed (30hp) and defended so it can't be
    chipped, then spend TRUE surplus on chipping the enemy HQ for the tiebreak.
  - Hard priority: never emit an illegal command (instant WA) and never starve.

Only decide() / Nav / Bot below are bot logic. The I/O framework (parse_init,
read_turn_start, read_turn_result, emit) is the verified sample-code.py framework.
"""
from __future__ import annotations

import heapq
import math
import sys
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

MAX_TURN = 200
START_GOLD = 500
START_WARRIORS = 3
MOVE_COST = 10
TRAIN_COST = 120
WORK_INCOME = 15
UPKEEP_PER_WARRIOR = 2
HQ_MAX_LEVEL = 5
BASE_MAX_LEVEL = 3
HQ_HEAL_COST = 1000
BASE_HEAL_COST = 500


class HqLevelEntry(NamedTuple):
    upgrade_cost: int
    warrior_hp: int
    hp: int
    turret: int
    train_cap: int
    work_cap: int


class BaseLevelEntry(NamedTuple):
    cost: int
    hp: int
    turret: int
    work_cap: int


HQ_LEVELS: tuple[HqLevelEntry, ...] = (
    HqLevelEntry(0,     0, 0,  0, 0, 0),
    HqLevelEntry(0,     4, 10, 1, 1, 1),
    HqLevelEntry(600,   5, 15, 2, 1, 2),
    HqLevelEntry(1200,  6, 20, 2, 2, 3),
    HqLevelEntry(2400,  7, 25, 3, 2, 4),
    HqLevelEntry(3600,  8, 30, 3, 3, 5),
)
BASE_LEVELS: tuple[BaseLevelEntry, ...] = (
    BaseLevelEntry(0,    0,  0, 0),
    BaseLevelEntry(300,  6, 1, 1),
    BaseLevelEntry(600,  12, 1, 2),
    BaseLevelEntry(1000, 18, 2, 3),
)


class Side(Enum):
    LEFT = "A"
    RIGHT = "B"

    @property
    def opposite(self) -> "Side":
        return Side.RIGHT if self is Side.LEFT else Side.LEFT

    @classmethod
    def from_word(cls, w: str) -> "Side":
        return cls.LEFT if w == "LEFT" else cls.RIGHT

    @classmethod
    def from_char(cls, c: str) -> "Side":
        return cls.LEFT if c == "A" else cls.RIGHT


class BType(Enum):
    HQ = "HQ"
    BASE = "BASE"


class WState(Enum):
    STATIONARY = 0
    MOVING = 1


@dataclass(frozen=True)
class WarriorId:
    side: Side
    num: int

    def __str__(self) -> str:
        return f"{self.side.value}{self.num}"

    @classmethod
    def parse(cls, tok: str) -> "WarriorId":
        assert tok and tok[0] in ("A", "B")
        return cls(Side.from_char(tok[0]), int(tok[1:]))


@dataclass
class Warrior:
    id: WarriorId
    region: int
    hp: int
    state: WState = WState.STATIONARY
    target: int = 0


@dataclass
class Building:
    region: int
    side: Side
    type: BType
    level: int = 1
    hp: int = 10

    def current_hp(self) -> int:
        return HQ_LEVELS[self.level].hp if self.type is BType.HQ else BASE_LEVELS[self.level].hp

    def work_cap(self) -> int:
        return HQ_LEVELS[self.level].work_cap if self.type is BType.HQ else BASE_LEVELS[self.level].work_cap

    def apply_upgrade(self) -> None:
        self.level += 1
        self.hp = self.current_hp()

    def upgrade_cost(self) -> int:
        if self.type is BType.HQ:
            return HQ_LEVELS[self.level + 1].upgrade_cost
        else:
            return BASE_LEVELS[self.level + 1].cost


@dataclass
class GameMap:
    N: int = 0
    K: int = 0
    x: list[int] = field(default_factory=list)
    y: list[int] = field(default_factory=list)
    strongholds: list[int] = field(default_factory=list)
    adj: list[list[int]] = field(default_factory=list)
    my_side: Side = Side.LEFT
    my_hq: int = 0
    opp_hq: int = 0

    def hq_of(self, s: Side) -> int:
        return 0 if s is Side.LEFT else self.N - 1


@dataclass
class GameState:
    gold: int = START_GOLD
    my_countdown: int = 5
    opp_countdown: int = 5
    warriors: list[Warrior] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)

    def find_building(self, region: int) -> Building | None:
        return next((b for b in self.buildings if b.region == region), None)

    def find_warrior(self, wid: WarriorId) -> Warrior | None:
        return next((w for w in self.warriors if w.id == wid), None)


@dataclass
class Actions:
    train_n: int = 0
    moves: list[tuple[WarriorId, int]] = field(default_factory=list)
    upgrades: list[int] = field(default_factory=list)


def make_base(region: int, s: Side) -> Building:
    return Building(region, s, BType.BASE, 1, BASE_LEVELS[1].hp)


def readln() -> str:
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return line.rstrip("\n")


def read_tokens() -> list[str]:
    return readln().split()


def parse_init() -> tuple[GameMap, GameState]:
    M = GameMap()

    t = read_tokens()
    assert len(t) >= 2 and t[0] == "READY"
    M.my_side = Side.from_word(t[1])

    t = read_tokens()
    M.N, M.K = int(t[0]), int(t[1])

    M.x = [int(v) for v in read_tokens()]
    M.y = [int(v) for v in read_tokens()]

    M.strongholds = sorted(int(v) for v in read_tokens())

    M.adj = [[] for _ in range(M.N)]
    for r in range(M.N):
        t = read_tokens()
        deg = int(t[0])
        M.adj[r] = sorted(int(v) for v in t[1:1 + deg])

    M.my_hq = M.hq_of(M.my_side)
    M.opp_hq = M.hq_of(M.my_side.opposite)

    S = GameState()
    opp = M.my_side.opposite
    for sfx in range(1, START_WARRIORS + 1):
        S.warriors.append(Warrior(WarriorId(M.my_side, sfx), M.my_hq, HQ_LEVELS[1].warrior_hp))
        S.warriors.append(Warrior(WarriorId(opp, sfx), M.opp_hq, HQ_LEVELS[1].warrior_hp))
    S.buildings.append(Building(0, Side.LEFT, BType.HQ, 1, HQ_LEVELS[1].hp))
    S.buildings.append(Building(M.N - 1, Side.RIGHT, BType.HQ, 1, HQ_LEVELS[1].hp))

    print("OK", flush=True)
    return M, S


def read_turn_start() -> int | None:
    line = readln()
    if line == "FINISH":
        return None
    t = line.split()
    assert t and t[0] == "START"
    return int(t[2])


def read_turn_result(S: GameState, M: GameMap, submitted: Actions) -> None:
    for region in submitted.upgrades:
        b = S.find_building(region)
        if b is None:
            S.gold -= BASE_LEVELS[1].cost
            S.buildings.append(make_base(region, M.my_side))
        else:
            max_level = HQ_MAX_LEVEL if b.type is BType.HQ else BASE_MAX_LEVEL
            if b.level >= max_level:
                cost = HQ_HEAL_COST if b.type is BType.HQ else BASE_HEAL_COST
                S.gold -= cost
                b.hp = b.current_hp()
            else:
                S.gold -= b.upgrade_cost()
                b.apply_upgrade()

    for wid, target in submitted.moves:
        b = S.find_building(target)
        cost = 0 if (b is not None and b.side is M.my_side) else MOVE_COST
        S.gold -= cost
        w = S.find_warrior(wid)
        if w is not None:
            w.state = WState.MOVING
            w.target = target

    S.gold -= TRAIN_COST * submitted.train_n

    line = readln()
    if line == "FINISH":
        sys.exit(0)
    t = line.split()
    assert t and t[0] == "TURN"

    t = read_tokens()
    S.my_countdown = int(t[2])
    S.opp_countdown = int(t[4])

    t = read_tokens()  # "UPGRADE N"
    n = int(t[1])
    for _ in range(n):
        r = read_tokens()
        s = Side.from_char(r[0][0])
        region = int(r[1])
        b = S.find_building(region)
        if b is None:
            S.buildings.append(make_base(region, s))
        elif b.side is not M.my_side:
            max_level = HQ_MAX_LEVEL if b.type is BType.HQ else BASE_MAX_LEVEL
            if b.level >= max_level:
                b.hp = b.current_hp()
            else:
                b.apply_upgrade()

    t = read_tokens()  # "TRAIN N"
    n = int(t[1])
    if n > 0:
        ids = read_tokens()
        for i in range(n):
            wid = WarriorId.parse(ids[i])
            hq_region = M.hq_of(wid.side)
            hq_b = S.find_building(hq_region)
            hq_level = hq_b.level if hq_b is not None else 1
            S.warriors.append(Warrior(wid, hq_region, HQ_LEVELS[hq_level].warrior_hp))

    t = read_tokens()  # "MOVE N"
    n = int(t[1])
    for _ in range(n):
        r = read_tokens()
        wid = WarriorId.parse(r[0])
        region = int(r[1])
        w = S.find_warrior(wid)
        if w is not None:
            w.region = region
            if (wid.side is M.my_side
                    and w.state is WState.MOVING
                    and w.region == w.target):
                w.state = WState.STATIONARY

    t = read_tokens()  # "DAMAGE N"
    n = int(t[1])
    for _ in range(n):
        r = read_tokens()
        wid = WarriorId.parse(r[1])
        damage = int(r[2])
        w = S.find_warrior(wid)
        if w is not None:
            w.hp -= damage
    S.warriors = [w for w in S.warriors if w.hp > 0]

    t = read_tokens()  # "SIEGE N"
    n = int(t[1])
    for _ in range(n):
        r = read_tokens()
        region = int(r[1])
        dmg = int(r[2])
        b = S.find_building(region)
        if b is not None:
            b.hp -= dmg
    S.buildings = [b for b in S.buildings if b.hp > 0]

    readln()  # "END"

    income = 0
    for b in S.buildings:
        if b.side is not M.my_side:
            continue
        count = sum(
            1 for w in S.warriors
            if w.id.side is M.my_side and w.region == b.region
        )
        income += WORK_INCOME * min(count, b.work_cap())
    S.gold += income

    alive = sum(1 for w in S.warriors if w.id.side is M.my_side)
    S.gold = max(0, S.gold - UPKEEP_PER_WARRIOR * alive)


# ----------------------------------------------------------------------------
# Fast pathfinding (lazy weighted Dijkstra) — replaces O(N^3) Floyd-Warshall.
# Movement in the referee follows the minimum ceil-euclidean-weight path, one
# hop/day; Nav reproduces that exactly (same tie-break: lowest-numbered neighbor
# attaining the minimal edge+dist score, adj is sorted ascending).
# ----------------------------------------------------------------------------
class Nav:
    def __init__(self, M: GameMap):
        self.M = M
        self.N = M.N
        self._dist: dict[int, list[float]] = {}
        self._next: dict[tuple[int, int], int] = {}
        self._hops: dict[tuple[int, int], int] = {}

    def _w(self, u: int, v: int) -> int:
        return math.ceil(math.hypot(self.M.x[u] - self.M.x[v], self.M.y[u] - self.M.y[v]))

    def dist(self, target: int) -> list[float]:
        d = self._dist.get(target)
        if d is None:
            d = self._dijkstra(target)
            self._dist[target] = d
        return d

    def _dijkstra(self, target: int) -> list[float]:
        INF = math.inf
        dist = [INF] * self.N
        dist[target] = 0.0
        pq = [(0.0, target)]
        while pq:
            du, u = heapq.heappop(pq)
            if du > dist[u]:
                continue
            for v in self.M.adj[u]:
                nd = du + self._w(u, v)
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return dist

    def next_hop(self, u: int, target: int) -> int:
        if u == target:
            return target
        key = (u, target)
        nh = self._next.get(key)
        if nh is None:
            d = self.dist(target)
            best = -1
            best_score = math.inf
            for nb in self.M.adj[u]:
                if d[nb] == math.inf:
                    continue
                score = self._w(u, nb) + d[nb]
                if score < best_score:
                    best_score = score
                    best = nb
            nh = best
            self._next[key] = nh
        return nh

    def hops(self, u: int, target: int) -> int:
        if u == target:
            return 0
        key = (u, target)
        h = self._hops.get(key)
        if h is None:
            cur = u
            cnt = 0
            guard = self.N + 5
            while cur != target and cnt < guard:
                nh = self.next_hop(cur, target)
                if nh < 0:
                    cnt = self.N + 99
                    break
                cur = nh
                cnt += 1
            h = cnt
            self._hops[key] = h
        return h

    def reachable(self, u: int, target: int) -> bool:
        return self.dist(target)[u] != math.inf

    def warm(self) -> None:
        # Precompute Dijkstra for the targets we query constantly, before turn 1.
        self.dist(self.M.my_hq)
        self.dist(self.M.opp_hq)
        for s in self.M.strongholds:
            self.dist(s)


# ----------------------------------------------------------------------------
# Strategy
# ----------------------------------------------------------------------------
DEBUG = False

# Tunable parameters
THREAT_RANGE = 6          # enemy within this many hops of my HQ counts as a threat
GOLD_FLOOR = 60           # never let planned spend leave us below upkeep cushion + this
HEAL_RESERVE = 1000       # bank this once HQ is strong, for emergency heal/upgrade
ASSAULT_START = 70        # earliest turn to consider committing surplus to offense
ASSAULT_MIN_SURPLUS = 4   # true-surplus warriors required before we send any to attack
ECON_PAYBACK_CUTOFF = 175 # stop opening new work slots after this turn (won't pay back)
GUARD_MIN = 3             # standing home-guard floor (kept at HQ, never raids)
MUSTER = 6                # raid stack size to commit when we are AHEAD in territory
MIN_RAID = 4              # commit size when BEHIND in territory (and stack floor)
WORKERS_PER_BASE = 2      # workers kept per base; the REST feed the raid army (lower = attack readier)
TERRITORY_SLACK = 0       # tolerate enemy leading by this many bases before contesting (0 = stay >= even)
CONTEST_REACH = 2         # also claim strongholds the enemy is closer to by <= this (race the middle).
#                           Raised 1->2 per the user's "don't yield the center" directive: contest a
#                           wider central band so we don't cede our fair share of the midline economy
#                           (no regression on the test maps; may claim a central stronghold on others).
LOSE_MARGIN  = 1    # enemy out-bases us by > this = LOSING the land war
COUNTER_QUOTA = 8   # counter-stack size to accumulate when losing
COUNTER_TGT  = 'base'  # race the enemy's nearest BASE, not its turreted HQ (an HQ race is a turret-suicide:
#                        the whole army marches 10+ hops and is ground to 0 by the turret + converging
#                        defenders). 'base' keeps the open-rear punish without feeding the army to the turret.
COUNTER_MODE = 'le'  # 'lt'=fire when HQ strictly behind (slow), 'le'=at parity (fast)
COUNTER_ARMY = 0    # only counter when we CAN'T win the defensive fight (army<stack)
COUNTER_DROP = 1    # when losing, drop the climb reserve -> army (econ=army)
PROTO_ATTACK = 1
ATTACK_WHEN = 'losing'
ATTACK_TGT = 'econ'
BURST_MIN = 5
ATTACK_MIN_HQ = 2
STAGE_BURST = 1
FUND_GATE = 2
LATE_CLIMB = 130
LATE_BACKSTOP = 150
# --- PROACTIVE CLIMB (the user's "AHEAD/EVEN coast" fix, g6/g8 root cause) -------------------
# The climb window used to OPEN only when strictly BEHIND on HQ level, or at LATE_BACKSTOP(150),
# or in the fortress buildup. So whenever we were AHEAD or EVEN and turn<150 the window was CLOSED
# and the HQ COASTED (g8: L2 from t46->t181 while the enemy sprinted L1->L4 and won the tiebreak;
# g6: reached L5 first at t159 but never out-climbed the enemy's t186 L5 -> draw). This gate OPENS
# the climb the moment the economy is established (multi-base) and NO wave is committing, regardless
# of ahead/even/turn -- so on compact maps the HQ chains L2->L5 by ~t120-140 instead of banking idle.
# It is SELF-LIMITING and breaks no invariant: it only flips `want` to True in section 1c (the upgrade
# still passes can()/upgrade_legal/_is_max), and the training-phase reserve (1c-mirror at 1560) only
# gates OFFENSIVE surplus -- workers and the closing-wave force-train are funded first, untouched.
PROACTIVE_CLIMB = 0         # DISABLED: a blanket "climb to L5 whenever ahead/even" COASTS to L5 instead of
#                            razing the enemy's economy, so a turtle/mirror ALSO reaches L5 -> the proven
#                            raze-denial WINS (turtle 7W/mirror 4W locally) collapse to DRAWS (0W). And it
#                            did NOT even fix the g8 coast (heavy futile raiding drained the gold before the
#                            climb could fire). Replaced by the narrow CLIMB-RESCUE below: climb only when
#                            razing is GENUINELY futile (stuck low + nothing crackable for FUTILE_STREAK
#                            turns) -- the h6/h8 case -- which never trips vs a turtle (we crack its bases).
PROACTIVE_CLIMB_BASES = 2   # economy "established" = at least this many BASES (HQ excluded) standing
PROACTIVE_CLIMB_TURN = 30   # don't pre-empt the opening claim/economy race before this
# --- LATE-GAME HQ-LEAD DOCTRINE (the user's rule), tiered, from HQ_CRUSH_TURN:
#   * ANY HQ lead (>= HQ_CRUSH_GAP): do NOT coast to the day-200 tiebreak (the enemy still has ~70 turns
#     to upgrade and close the gap). Pour the free gold into a LARGE army and raze the enemy's bases
#     FREQUENTLY (continuous 견제) so it can never accumulate the gold to upgrade its HQ -- denying its
#     growth keeps our tiebreak lead safe.
#   * OVERWHELMING army (our committing force cracks the enemy HQ even if its WHOLE army converges to
#     defend -- the honest worst-case siege sim, so never a suicide): go destroy the enemy HQ outright.
HQ_CRUSH = 0             # DISABLED (was the t130 _hq_assault): it threw the whole army at the turreted
#                          enemy HQ on a STALE turn-130 snapshot -- the ~10-turn march let the enemy
#                          reinforce/heal so the "crackable" read was false on arrival, the per-unit
#                          (non-monotonic) order scattered the fist, it dealt ~0 siege, and abandoning
#                          home let the enemy counter-wave. It fired ONLY in the two real LOSSES (g7/g8);
#                          g6 drew BECAUSE it never fired. Base-razing (the proven path) is the safe
#                          aggression; a deliberate open-rear HQ race stays counter_now's job (base-targeted).
HQ_CRUSH_TURN = 130
HQ_CRUSH_GAP = 1          # even a SLIGHT lead -> keep harassing so the enemy can't keep growing
TEMPO_DECAY = 0.6
TEMPO_BURST = 4.0
TEMPO_DEV_WIN = 8
RELIEF = 1
RELIEF_MIN = 4
RELIEF_SLACK = 6
RELIEF_FORCE = 2
PRESTAFF = 1
MATCH_EAGER = 1
THREAT_MIN = 4
HARASS_HQLEVEL = 3
FORTRESS = 1
FORTRESS_TURN = 140
FORTRESS_ARMY = 14
FORTRESS_SLACK = 4
FORTRESS_RANGE = 8
FORTRESS_MIN = 6
FORTRESS_HOLD = 1
# --- MID-GAME FORTIFY (the user's game-3 fix): the _fortress trigger above only opens at turn>=140,
#     but game 3 was LOST at t92 -- the enemy massed an 11-stack ON ITS OWN HQ (detected: threat_army
#     fired at t51 when it hit 10), then launched an all-in. Our HQ sat at L2 (15hp) because we were
#     nominally "ahead" on HQ level (L2 vs their L1 -> _behind_hq=False) and pre-FORTRESS_TURN, so
#     _hq_climb_window stayed CLOSED and gold went to BASE upgrades while the deathball formed (the
#     user's "기지를 짓느라 돈을 너무 써버린"). A paper L2 HQ then got cracked. FIX: the instant a real
#     massed enemy army is detected (threat_army/threat_total >= this floor), FORTIFY -- open the HQ
#     climb regardless of relative HQ level/turn, and stop pouring gold into bases. Climbing heals the
#     HQ + adds hp + a turret + raises train_cap (faster matching) -- the single best survival spend.
#     Gated on a genuine mass (>= floor): a turtle never stacks this many, so the raze-denial draws/wins
#     are untouched (mil_switch stays 0 vs a dispersed economy). on_hq==0/not-concentrate (inherited via
#     _climb_safe) keep it to the FORMING phase; the committed phase is handled by siege_climb.
FORTIFY = 1
FORTIFY_MASS_MIN = 8      # a detected enemy stack/out-production this big = fortify the HQ now
PRESSURE = 1
PRESSURE_TURN = 60
PRESSURE_HQLEVEL = 3
PRESSURE_FORCE = 8
# --- EARLY RAID (the user's "초반 공격을 더 빠르게"): the old offense path only opened at HQ>=L3 or a
#     territory deficit, AND the raid fist was only funded from PRESSURE_TURN(60). So an EVEN opening
#     funded ZERO raiders -- we sat compounding + climbing until ~t70 and the game was already locked
#     (real log 8: we never sieged an enemy base once). This window opens a SMALL fist far earlier so we
#     grab the enemy's exposed FORWARD bases while they are cheap (L1 base = 6hp) and keep continuous
#     pressure. It is SELF-LIMITING and breaks none of the invariants: the bodies are TRUE surplus
#     (want_spare on top of full work_cap -> never pulls a worker, compounding intact) and are trimmed
#     by the L5-climb reserve in the affordability loop (so the tiebreak climb still comes first). When
#     there is no genuine free gold the quota trims to 0 and we just keep compounding. The backdoor
#     stays the single monotonic owner (_raid_commit only commits to a base _can_crack says we RAZE, and
#     flees a stopping force) -- so timing VARIES by map/opponent: it fires the moment a forward base is
#     actually crackable, not on a fixed clock.
EARLY_RAID = 1
EARLY_RAID_TURN = 25      # open the offense gate + fund a small fist from here (was effectively ~60-70)
EARLY_RAID_FORCE = 6      # small surplus to fund early (razes an undefended L1/L2 forward base)

MAX_CLAIMERS = 3          # claimers we may dispatch in a single turn (faster expansion)
ASSAULT_CAP = 80          # cap extra warriors funded from the late-game gold hoard
RAID_FUND_HQLEVEL = 3     # economy floor (HQ level) before funding the land-taking raid army
RAID_AGGRESSION = 0.5     # DEPRECATED: superseded by the hard fortress-first rule (offensive
#                           chip-army funds ONLY after the HQ is maxed to L5). Kept for reference.
# --- Counter-mobilization: detect the enemy massing an army and MATCH it as a home
#     garrison. Siege math (verified vs referee): siege/turn to my HQ =
#     max(0, enemy_stack_on_HQ - my_defender_HP_present); the turret only adds turret
#     attacks (3 at L5), it does NOT soak siege. So to survive a wave of W warriors we
#     must keep ~W of our own standing ON node 0, reinforced every turn. We react to the
#     enemy's ARMY SIZE (early) and pre-mass + concentrate, not to its arrival (too late).
MOBILIZE_ARM_TURN = 35    # detector silent before this (opening-economy noise: armies 1-4)
WAVE_STACK_MIN = 10       # an enemy stack this big ANYWHERE = a wave forming (turtle-safe:
#                           a distributed economy never concentrates 10+ on one region)
MOBILIZE_NEAR = 6         # a smaller stack already this close counts as a rush (compact maps)
MOBILIZE_APPROACH_F = 0.6 # "close" = within ceil(F*diameter) hops of my HQ
MOBILIZE_MATCH = 1.0      # at L5, match the enemy stack 1:1 (turret+30hp covers the small edge)
MOBILIZE_MATCH_SUBL5 = 1.15  # below L5, need > parity (no full turret/30hp yet)
MOBILIZE_CAP = 80         # ceiling on the matched home garrison
BEHIND_GARRISON_SLACK = 2 # when our HQ TRAILS the enemy's level, cap the FORMING-phase garrison ramp at
#                           ~parity (enemy standing army + this slack) instead of the full target, freeing
#                           the gold to CATCH UP the HQ level (losing the tiebreak by level is the worst
#                           outcome; g7/g8 over-trained 35/31 vs 24/28 yet stalled at L3<L4 and lost). The
#                           concentrate-driven defenders_needed is untouched, so a COMMITTED wave still fills.
# --- TOTAL-ARMY MATCHING (the core fix for the real losses) -------------------
# Every real loss had the SAME shape: near-equal territory and HQ level, but the enemy's
# army was 2-3x ours (e.g. 99 vs 43, 90 vs 60, 57 vs 20). The enemy keeps its army SPREAD as
# workers (small stacks) so the stack detector under-counts -> we stop training at ~20-40 while
# its TOTAL army grows and finally concentrates into a siege we can't answer in time. But a
# WORKING army nets +13/turn and break-even is ~7.5x work-capacity (~190 warriors), so at
# parity we can AFFORD to match their total. So: track the enemy's TOTAL army and MATCH it
# (reserve-protected for the L5 climb), holding the matched force at home as workers/garrison
# (income-positive) -- ready to meet the sweep the instant it commits. Turtle-safe: engage only
# once the enemy genuinely OUT-PRODUCES us in army by a clear MARGIN (a passive/moderate-army
# opponent we already beat never trips it, so it never makes us go passive and trade a win).
MATCH_TOTAL = False       # CRITICAL FIX (the user's call): do NOT react to the enemy's TOTAL warrior count.
#                           The enemy keeps most of its army as WORKERS on its bases -- counting them as a
#                           threat made us pull OUR base workers into a matched home garrison, which
#                           collapsed our economic compounding (복리). Defense now keys ONLY on the enemy's
#                           CONCENTRATED attacking army (threat_army: a real massed/advancing stack) and on
#                           forward invaders -- judge the enemy's ATTACKERS, not its head-count.
MATCH_TOTAL_F = 1.0       # match the enemy total 1:1 (L5 turret + 30hp covers the small edge)
MATCH_TOTAL_MARGIN = 4
MATCH_TOTAL_CAP = 130     # hard ceiling, well under the break-even army -- never starve the economy
# --- OUT-PRODUCTION detector (g3 STILL-LOST fix): MATCH_TOTAL above is off because counting the enemy's
#     WORKERS as a threat pulls our own workers and collapses 복리. But g3 keeps losing on exactly the shape
#     it can't see: the enemy out-produces us 2:1 (B=12 vs A=6 by t60) while keeping its army DISPERSED
#     (1-per-node, looks like economy -> threat_army stays 0), then converges an 11-stack at t65 and cracks
#     our paper L1 HQ. The tell we DO have without touching workers: the enemy fields far more warriors than
#     it can possibly WORK. enemy_idle = enemy_total - enemy_work_capacity is its real surplus (deathball-in-
#     waiting). When that idle army out-numbers us, FORTIFY now (feeds threat_total -> _under_massed climb +
#     target_garrison match-train), regardless of whether it has concentrated yet. Turtle-safe: a turtle keeps
#     its army ON its bases working (idle ~0) and never out-numbers us by the margin, so it never trips.
OUTPRODUCE = 1
OUTPRODUCE_MARGIN = 4     # enemy must out-number our whole army by this much (absolute)
OUTPRODUCE_RATIO = 1.6    # AND by this factor (a real ~2:1 deathball build, not a mirror's transient +4 lead --
#                           the ratio gate keeps the symmetric mirror/turtle from tripping it and coasting)
OUTPRODUCE_IDLE_MIN = 3   # AND field >= this many warriors beyond its total work capacity (a real idle army)
CONCENTRATE_DIST = 3      # pull EVERYONE home (abandon base income) only once the wave's stack
#                           is this close OR has advanced strictly past the midline toward us
HQ_NEAR = 2               # a forward enemy wave only forces a full HQ-turtle when its nearest target is
#                           the HQ itself (within this many hops). Farther out it is grinding a forward
#                           BASE -> contest it there (base_eating) instead of abandoning the base to
#                           turtle node 0 (the user's "기지로 오는지 HQ로 오는지 명확히 판단"; log7/8 loss).
# --- EARLY HQ-RUSH defense (the user's "아군 기지에서 방어하는 이점을 못 살리는 버그"): the wave detector is
#     turn-gated (MOBILIZE_ARM_TURN=35) so an OPENING all-in -- the enemy trains a few warriors and
#     beelines our L1 HQ by turn ~11 -- is invisible, and THREAT_MIN=4 means a 3-unit rush raises no
#     defenders at all. So we keep dispersing to claim and the rush walks in and razes the HQ (real user
#     losses: HQ destroyed t18, t70). This trigger arms the home-turtle at ANY turn for a stack that has
#     CROSSED into our half and is CLOSING on our HQ -- existential, and distinct from the opening economic
#     NOISE the turn gate guards against (that noise sits on the ENEMY side, never near ours).
RUSH_DEFENSE = 1
RUSH_MIN = 3              # an invading stack this big = a committed assault (below THREAT_MIN=4)
RUSH_DIST = 4             # CLOSE assault: within this many hops of our HQ (catches even a detachment)
RUSH_COMMIT_F = 0.55      # ALL-IN: a stack that is >= this fraction of the enemy's WHOLE army, anywhere in
#                           our half, is a committed all-in -> arm the turtle EARLY (before THREAT_RANGE=6),
#                           even across a big map, while still ignoring a small forward harass detachment.
#                           Lowered 0.6->0.55 (g3): the t65 11-stack was ~11/13 of their army -- already
#                           caught -- but a slightly looser bar arms the turtle the instant the bulk
#                           commits forward, buying recall + climb time. Still well above a harass
#                           detachment (a few units = a small fraction), so no over-turtle regression.
# --- SIEGE-EMERGENCY (FORTRESS-AND-RECALL, the g3 loss fix) ----------------------------------------
# g3 root cause (confirmed forensics): the enemy massed an 11-stack (>= RUSH_COMMIT_F of its army) at
# t65 and marched it at our HQ; our raid fist was deep (regions 24-54), recalled only t75, and our HQ
# was a weak L2 (15hp) that a 14-turn siege cracked at t92. Three failures compounded: late all-in
# read, fist too deep to recall, HQ too weak to survive. SIEGE-EMERGENCY ties them together: when a
# BIG committed enemy stack is forming/closing on our HQ AND our HQ hp-pool cannot survive its siege,
# we (a) RECALL the raid fist home regardless of depth and (b) FORCE the HQ climb as the top survival
# priority (each upgrade heals to full + adds hp/turret-soak). It is existential-only and self-limiting:
# it needs a genuine committed all-in (SIEGE_EMERG_STACK units that have CROSSED into our half), so a
# turtle/mirror that never concentrates an all-in never trips it -> the raze-denial draws/wins are kept.
SIEGE_EMERGENCY = 1
SIEGE_EMERG_STACK = 8    # a committed enemy stack this big, in our half, beelining our HQ = an existential
#                          all-in (g3 was 11). Below this is a harass detachment -> handled by RUSH/relief.
SIEGE_EMERG_RANGE = 9    # only an all-in within this many hops of our HQ is "incoming" (it can reach us
#                          while a low HQ is still weak); a stack still deep in the enemy half is not yet
#                          a siege emergency (we have time -- the normal climb window handles it).
SIEGE_EMERG_HP_SLACK = 5 # survival margin: treat the HQ as UNSAFE vs a wave of W when our present
#                          defender-HP pool (HQ hp + standing garrison hp) < W + this slack. Forces the
#                          climb/recall while there is still a cushion, not after the siege has begun.

# --- Two-front "backdoor" offense: split the raid army into a TOP and a BOTTOM prong along
#     the my_hq->opp_hq axis and strike the enemy's land on both flanks. A prong that meets a
#     LARGER enemy force at its target DISENGAGES and reroutes to reinforce the other (open)
#     flank -- "hit where they ain't". This only changes HOW the raid moves (it never touches
#     the home guard, the L5 climb, or the wave mobilization), so defense is unchanged.
TWO_FRONT_MIN = 8         # only split into two prongs when the raid force is at least this big
PRONG_MIN = 4             # a prong below this folds into the other (a half-stack cracks nothing)
DEF_RADIUS = 3            # enemy warriors within this many hops of a flank target = its defenders
# --- 승기 PUSH (the user's "승기를 잡으면 계속 병사를 찍어서 밀어붙이자"): the three draws all share a MID-GAME
#     PRODUCTION HALT -- once nominally ahead we bank for the L5 climb and stop training, so the army
#     dwindles and we coast to a turn-200 tiebreak draw (g5 trained NOTHING t110-155; g6 t77-160; g4
#     t125-157). When we hold a DECISIVE economy lead (>= WIN_BASE_LEAD more bases) with home safe and not
#     trailing the HQ tiebreak, we have SEIZED the advantage -> pour the free gold into ARMY (reserve-
#     protected, so the L5 climb still maxes in parallel) and keep PUSHING with the single fist, converting
#     the lead into a win instead of banking idle. The DECISIVE-lead bar keeps the SYMMETRIC mirror (which
#     never sustains a multi-base lead) from tripping it, so the proven mirror draw is preserved.
WINNING = 1
WIN_BASE_LEAD = 3        # >= this many MORE bases than the enemy = 승기 (a decisive, mirror-proof lead)
WIN_ENEMY_BASES = 2      # ...AND the enemy must still hold >= this many bases (real economy to BREAK by
#                          pushing). vs a minimal-economy rusher there is nothing to raze, so pushing army
#                          just slows our own clean climb-to-tiebreak win -- against those we keep climbing.
# --- CRACK-AWARE COMMITTED BACKDOOR (the user's long-requested strategy, finally realized) -------
# In an EVEN or slightly-behind game the day-200 tiebreak is at best a DRAW, so we must break parity
# BEFORE the endgame by ATTACKING. The backdoor commits a real fist to ONE enemy building it can
# ACTUALLY destroy (referee-exact crack sim), marches there as a monotonic stack (distance strictly
# decreases -> cannot ping-pong), razes it, then ROAMS to the next crackable building. If nothing is
# crackable it WITHDRAWS to the nearest friendly base and watches; a base it locks the whole spell
# without razing is BLACKLISTED so it never bleeds on a wall. Commitment (a lock) is the anti-
# oscillation guard; the fire gate (crack_arm, even/behind only) keeps the games we already win.
CRACK_FORCE = 12           # surplus to fund for the backdoor fist (sized to out-DPS an L5 base/turret; 6-unit chips fizzled)
CRACK_LOCK = 18           # turns we stay committed to a target (travel + siege) before re-evaluating
WATCH_LOCK = 4            # turns we sit at a friendly base watching when nothing is crackable (tried 2 to
#                           re-engage faster, but it sent the fist back out into a forming rush -> HQ chipped)
SKIP_WATCH = 12           # turns a base stays blacklisted after a stalled siege (then eligible again)
MAX_CRACK_TURNS = 12      # crack sim horizon: can this fist raze the target within this many siege turns
FLEE_RADIUS = 3           # backdoor EVASION: only flee when a beating enemy stack is THIS close (was 4 --
#                           fleeing from 4 hops away abandoned bases we could have razed first; the user's
#                           "멀리서부터 반응 말고 다가오면 그때 빠져라 -- 상대도 1턴씩 움직인다"). 2 razed far more but
#                           left the raiding fist too deep to recall vs an all-in rush (HQ chipped); 3 keeps
#                           most of the extra razing while staying one hop safer for the home recall.
#                           If that count reaches our fist size the enemy can STOP us -> flee & watch.
REINFORCE_DIST = 1        # _can_crack counts not just on-tile defenders but enemy units within this many
#                           hops of the target (they CONVERGE during the multi-turn siege). A base hugging
#                           a DEFENDED HQ then reads uncrackable (no suicide -- the 4/5 miscalc fix), while
#                           a base near a PASSIVE/empty HQ stays crackable -> we keep pressing an enemy that
#                           does not intercept (the user's game-5 rule), instead of a blanket HQ-distance ban.
HQ_CLUSTER_DIST = 2       # CONVERGENCE-AWARE CRACK (games 6/7/8 fix): a base within this many hops of the
#                           ENEMY HQ is a "cluster" base -- the HQ garrison standing ON the HQ is up to this
#                           many hops away, so REINFORCE_DIST=1 does NOT count it and _can_crack mis-reads the
#                           cluster base as crackable. We then commit, the HQ garrison converges over the
#                           multi-turn siege, siege drops to ~0, and the fist grinds for zero progress (k7
#                           region 47 @2hops: 9 dmg taken / 0 dealt; k8 regions 45/54/55/56: 28 taken / 0
#                           dealt). For a cluster target we WIDEN the convergence radius to reach the HQ body
#                           (local_rd = max(REINFORCE_DIST, hops(target->opp_hq))) so the cluster reads
#                           UNCRACKABLE and the backdoor skips it -> raze forward bases + climb instead.
#                           FORWARD bases (hops(target->opp_hq) > this) keep REINFORCE_DIST=1, so the proven
#                           FLEE_RADIUS=3 aggressive forward razing (turtle/mirror raze-denial wins) is intact.
CLUSTER_KEEP_F = 0.70     # PRECISE-COMBAT gate for cluster bases (games 6/7/8): the siege is COUNT-based, so
#                           even with the converging garrison counted a base near the enemy HQ can still read
#                           "crackable" -- we outnumber the snapshot defenders -- yet the turret + steady
#                           reinforcement bleed the fist while we grind (k6/7/8: we WIN the exchange but lose
#                           the army and the initiative -> draw). For a CLUSTER target we additionally require
#                           the sim to leave at least this fraction of the fist ALIVE: only commit when the
#                           crack is a FAVORABLE trade (we keep the army), else skip and raze forward + climb.
#                           Forward bases have NO survivor gate -- aggressive forward razing stays untouched.
NO_REBUILD_TURN = 130     # before this turn, razing an enemy base and BUILDING ours there is GOOD -- there is
#                           still time for that captured base to compound. From this turn on there is no time
#                           to compound, so we RAZE and LEAVE THE LAND EMPTY and bank the gold into the army/HQ.
HARASS_QUOTA = 5          # STUCK-BEHIND (enemy out-bases us & no stronghold left to claim): train
#                           this many raiders EARLY (pre-L5) to take enemy land before the gap
#                           compounds -- late territory-taking is meaningless
CLIMB_STUCK_LEVEL = 3     # the climb-rescue fires only when our HQ is stuck this low (<= L3)...
CLIMB_STUCK_TURN = 100    # ...this late -- a clear sign our own L2->L5 climb has STALLED (g8). vs a turtle
#                           we are L3+ well before t100, so this never trips and razing-denial is preserved.
FUTILE_STREAK = 9999      # rescue/recall DISABLED (set high): the futile-recall machinery introduced
#                           and (if the HQ is still climbing) recall home to bank for the climb instead of
#                           roaming a fully-defended enemy at 10g/unit/turn (the g8 coast). vs a turtle we
#                           crack a base every few turns -> the streak resets -> we keep razing (wins kept).
HARASS_STAGE_TURN = 100   # from this turn, when the backdoor finds NOTHING crackable it stages at our
#                           FRONTIER base (nearest the enemy) instead of drifting home to watch -- so a
#                           both-turtle stalemate keeps continuous pressure (the enemy must keep its army
#                           home, can't grow) and the fist pounces the instant a base becomes crackable.
#                           The user's game-6 rule: "고착화로 무승부 나지 말고 계속 견제해 성장을 방해해라". The
#                           per-call evasion still flees a real relief column, so this never feeds the army.
HARASS_CAP = 3            # while a wave is FORMING we hold a home garrison that MATCHES the wave
#                           (target_garrison) and harass with the EXCESS beyond it; this small
#                           distraction-probe FLOOR still goes out even at/below parity (losing a
#                           couple of raiders is survivable and it keeps the enemy reacting), but
#                           is kept SMALL so a razor-close game is never thrown by being short at
#                           the HQ during the recall window. Army control vs the enemy's army:
#                           never commit the whole force deep while the enemy masses (or the wave
#                           cracks our underdefended HQ and a winnable game collapses).
# NOTE: an "income-focus raid" (pillage an enemy that goes economy-heavy with a small army) was
# designed, implemented, and exhaustively swept here -- and REJECTED by the data. Every active
# variant (threshold-only, small/large quota, any stack cap) lost 12/12 vs a competent economist
# on the day-200 HQ tiebreak: continuously raiding pulls our warriors off our own economy and burns
# move-gold, stalling OUR L5 climb, while destroying enemy bases barely dents them (workers
# redistribute, bases rebuild for 300). Post-L5-gated pillaging was a pure no-op. The exploitable
# (non-L5) economist is already beaten just by out-climbing to L5; the solid one is a structural
# draw. So there is deliberately NO income-raid here -- it can only regress.


def _max_level(b: Building) -> int:
    return HQ_MAX_LEVEL if b.type is BType.HQ else BASE_MAX_LEVEL


def _is_max(b: Building) -> bool:
    return b.level >= _max_level(b)


def _home_turret(S, M, me, reg):
    """HOME-DEFENSE BONUS (referee-exact, the user's log-3 point: '아군기지에서 방어할 때는 보너스가
    있잖아'). In apply_day_combat the building owner's attacks = own_warriors + own turret, so when we
    fight an enemy stack standing ON (or next to) one of OUR buildings the turret swings FOR us -- our
    effective force is warriors + that turret. We were comparing RAW counts (army >= stack) and so
    abandoned base defenses we could actually win. Returns the turret of OUR building AT reg (the unit
    is fighting on it), else the largest turret among OUR adjacent buildings, else 0."""
    on = S.find_building(reg)
    if on is not None and on.side is me:
        return (HQ_LEVELS if on.type is BType.HQ else BASE_LEVELS)[on.level].turret
    best = 0
    for nb in M.adj[reg]:
        b = S.find_building(nb)
        if b is not None and b.side is me:
            best = max(best, (HQ_LEVELS if b.type is BType.HQ else BASE_LEVELS)[b.level].turret)
    return best


def _next_cost(b: Building) -> int:
    if _is_max(b):
        return HQ_HEAL_COST if b.type is BType.HQ else BASE_HEAL_COST
    if b.type is BType.HQ:
        return HQ_LEVELS[b.level + 1].upgrade_cost
    return BASE_LEVELS[b.level + 1].cost


def _train_cap(b: Building) -> int:
    return HQ_LEVELS[b.level].train_cap


@dataclass
class Bot:
    inited: bool = False
    claim_order: list[int] = field(default_factory=list)   # my-half strongholds, nearest first
    claim_set: set[int] = field(default_factory=set)
    raiding: bool = False                                   # concentrated raid stack committed?
    threat_army: int = 0                                  # sticky running-max enemy WAVE we must match
    threat_total: int = 0                                 # sticky running-max enemy TOTAL army we must match
    raid_tgt: int = -1                                    # crack-backdoor: the ONE enemy building we are committed to (-1 = none / watching)
    raid_lock: int = 0                                    # crack-backdoor: turns left on the current commit/watch spell (commitment = anti-oscillation)
    raid_skip: dict = field(default_factory=dict)         # crack-backdoor: region -> watch-expiry turn (stalled-siege blacklist)
    no_target_streak: int = 0                             # consecutive backdoor turns with NOTHING crackable (razing futile -> climb-priority recall)
    seen_enemy: set = field(default_factory=set)          # every region that EVER held an enemy building -> we raze & LEAVE EMPTY, never rebuild our own base on razed enemy land


BOT = Bot()


def _init_bot(M: GameMap, nav: Nav) -> None:
    # Strongholds to claim: NOT just our strict half — also the CENTER and the
    # contested band (enemy closer by at most CONTEST_REACH). Conceding the middle
    # is how you fall behind in territory: the enemy grabs every neutral stronghold
    # and out-bases you. Order by distance from our HQ so we race the nearest first.
    scored = []
    for s in M.strongholds:
        dm = nav.hops(s, M.my_hq)
        do = nav.hops(s, M.opp_hq)
        if dm <= do + CONTEST_REACH:      # ours + center + contested band
            scored.append((dm, s))
    scored.sort()
    BOT.claim_order = [s for _, s in scored]
    # claim_set = ONLY our own planned strongholds (our half + contested band), NOT every stronghold
    # on the map. Otherwise a backdoor raider standing on a RAZED enemy stronghold is mistaken for "a
    # claimer waiting to build", so 1b builds our base on razed enemy land and the unit stops roaming
    # (the user's "상대 기지 부수며 돌아다니는데 아군기지를 세워버려"). Now razed enemy land stays empty and the
    # raider is treated as surplus -> it roams on to the next crackable base; spare gold banks to HQ/army.
    BOT.claim_set = set(BOT.claim_order)
    BOT.inited = True
    if DEBUG:
        print(f"# claim_order={BOT.claim_order}", file=sys.stderr, flush=True)


def decide(S: GameState, M: GameMap, nav: Nav, turn: int) -> Actions:
    a = Actions()
    try:
        _decide_impl(S, M, nav, turn, a)
    except Exception as e:  # never crash -> never WA by timeout
        if DEBUG:
            print(f"# decide error turn {turn}: {e}", file=sys.stderr, flush=True)
    return a


def _decide_impl(S: GameState, M: GameMap, nav: Nav, turn: int, a: Actions) -> None:
    if not BOT.inited:
        _init_bot(M, nav)

    me = M.my_side
    my_warriors = [w for w in S.warriors if w.id.side is me]
    enemy_warriors = [w for w in S.warriors if w.id.side is not me]
    my_buildings = [b for b in S.buildings if b.side is me]
    my_bases = [b for b in my_buildings if b.type is BType.BASE]
    hq = S.find_building(M.my_hq)
    my_building_regions = {b.region for b in my_buildings}
    # remember every stronghold that has EVER held an enemy building, so once the backdoor razes it
    # we leave the land EMPTY (never rebuild our own base on razed enemy land) and bank the gold.
    BOT.seen_enemy.update(b.region for b in S.buildings if b.side is not me)
    # Razed enemy land is OFF-LIMITS for our own bases ONLY from NO_REBUILD_TURN onward (leave it empty,
    # bank the gold). BEFORE that turn this set is empty, so we freely capture & rebuild razed enemy
    # strongholds and let them compound. One gate, used everywhere a build/claim is decided -> no tangle.
    _skip_build = BOT.seen_enemy if turn >= NO_REBUILD_TURN else frozenset()

    enemy_at: set[int] = {w.region for w in enemy_warriors}
    my_present: set[int] = {w.region for w in my_warriors}  # regions with a live friendly

    # --- threat & defender requirement -------------------------------------
    # Count an enemy as a threat only if it is within THREAT_RANGE hops of our HQ AND
    # has ADVANCED toward us (no farther from our HQ than from its own). An enemy's
    # idle home/border garrison parked on its own side is NOT an assault -- and on a
    # compact map (the two HQs within THREAT_RANGE hops) the old, position-blind count
    # tagged that entire garrison as a threat every turn, pinning our whole army at the
    # HQ forever: we dispatched no claimers, built nothing, and sat at HQ L1 to a draw/
    # loss. A real push crosses the midline well before reaching us, so this still
    # musters defenders in time; `on_hq` keeps max defense once they actually arrive.
    threat = sum(
        1 for w in enemy_warriors
        if nav.hops(w.region, M.my_hq) <= THREAT_RANGE
        and nav.hops(w.region, M.my_hq) <= nav.hops(w.region, M.opp_hq)
    )
    on_hq = sum(1 for w in enemy_warriors if w.region == M.my_hq)
    # FORWARD INVADERS (direct): enemy units that crossed into OUR half. The global most-common
    # stack misses a detachment the enemy pushes forward while keeping its mass at the rear, so our
    # army sits idle (log7/8). Detect them and CONSOLIDATE to defend (safe -- never leaves the HQ).
    _fwd = [w for w in enemy_warriors if nav.hops(w.region, M.my_hq) < nav.hops(w.region, M.opp_hq)]
    fwd_reg, fwd_sz, fwd_dist = -1, 0, 1 << 30
    if _fwd:
        fwd_reg, fwd_sz = Counter(w.region for w in _fwd).most_common(1)[0]
        fwd_dist = nav.hops(fwd_reg, M.my_hq)
    # Standing home guard ONLY once the HQ is maxed (i.e. once raids can start):
    # keeps GUARD_MIN at the HQ so committing a raid never opens it to a trickle.
    # Before that, floor is 1 (identical to the proven economic baseline -> no
    # economy regression while the HQ is still climbing to 30).
    guard_floor = GUARD_MIN if (hq is not None and hq.level >= RAID_FUND_HQLEVEL) else 1
    defenders_needed = min(len(my_warriors), guard_floor)
    if threat >= THREAT_MIN:
        defenders_needed = min(len(my_warriors), max(defenders_needed, threat + 1))
    if on_hq > 0:
        defenders_needed = min(len(my_warriors), max(defenders_needed, on_hq + 2))

    # --- counter-mobilization detector --------------------------------------
    # The enemy wins by massing one big stack and waving it into our HQ. Siege only
    # starts once our node-0 defender HP hits 0 (siege/turn = enemy_stack - our present
    # defender HP; the turret only adds turret_val attacks, it does NOT soak siege), so
    # the defense is to hold ~stack-many warriors ON node 0 and start massing EARLY
    # (train cap 3/turn at L5 -> a 60-wave needs ~20 turns' lead).
    #   We key off the enemy's largest CONCENTRATED stack -- a real wave is concentrated,
    #   a distributed economy (turtle) is not. A 10+ stack ANYWHERE is a forming wave
    #   (gives early warning as it builds at their base); a smaller stack already CLOSE is
    #   a compact-map rush. This is turtle-safe: a passive economy never stacks 10+.
    enemy_stack_sz = 0
    stack_dist = 1 << 30
    stack_reg = -1
    gate = math.ceil(MOBILIZE_APPROACH_F * max(nav.hops(M.my_hq, M.opp_hq), 1))
    if enemy_warriors:
        stack_reg, enemy_stack_sz = Counter(w.region for w in enemy_warriors).most_common(1)[0]
        stack_dist = nav.hops(stack_reg, M.my_hq)
        is_wave = turn >= MOBILIZE_ARM_TURN and (
            enemy_stack_sz >= WAVE_STACK_MIN or (enemy_stack_sz >= MOBILIZE_NEAR and stack_dist <= gate))
        if is_wave:
            BOT.threat_army = max(BOT.threat_army, enemy_stack_sz)   # sticky running-max
    if BOT.threat_army > 0 and enemy_stack_sz < MOBILIZE_NEAR and on_hq == 0 and threat == 0:
        BOT.threat_army = 0                       # wave dissolved & home clear -> baseline
    # EARLY HQ-RUSH (ungated by turn): arm the home-turtle the instant a real stack invades our half, even
    # pre-MOBILIZE_ARM_TURN. This makes `concentrate` engage (stop claiming, free base workers, muster every
    # body onto node 0) so the turret + a few defenders zero out the siege -- the home-defense advantage we
    # were throwing away by dispersing. Two ways to qualify, both requiring the stack to have CROSSED into
    # our half (closer to us than to its own HQ): (a) CLOSE -- within RUSH_DIST of our HQ, catches even a
    # detachment about to hit us; (b) ALL-IN COMMIT -- the stack is >= RUSH_COMMIT_F of the enemy's WHOLE
    # army, so we react the moment they commit the bulk forward, even far out on a big map (where the
    # real losses happened -- THREAT_RANGE=6 saw it only after our turn-1 claimers were already lost).
    # A small forward harass (few units, a fraction of their army, not close) does NOT qualify -> no
    # over-turtle regression. on_hq>0 (already standing on our HQ) is the unambiguous case. Dissolves via
    # the check above once the rush is repelled (small stack & home clear).
    if bool(RUSH_DEFENSE) and enemy_warriors and (
            on_hq > 0 or (stack_reg >= 0 and enemy_stack_sz >= RUSH_MIN
                          and stack_dist < nav.hops(stack_reg, M.opp_hq)
                          and (stack_dist <= RUSH_DIST
                               or enemy_stack_sz >= math.ceil(RUSH_COMMIT_F * max(len(enemy_warriors), 1))))):
        BOT.threat_army = max(BOT.threat_army, max(enemy_stack_sz, on_hq))
    # TOTAL-ARMY MATCHING: the enemy that wins keeps its army SPREAD (workers) so it never
    # forms a 10-stack until the final commit -- threat_army stays 0 and we under-train. Track
    # its TOTAL army whenever it OUT-PRODUCES us by MARGIN (turtle-safe: a passive economy's
    # army stays ~equal to ours, never exceeding by MARGIN). Sticky running-max; relax toward
    # parity when the enemy is no longer ahead (never disband, never chase a spent army).
    enemy_total = len(enemy_warriors)
    # OUT-PRODUCTION (g3): the enemy out-numbers our whole army by MARGIN AND fields more warriors than it can
    # WORK (idle = total - work_capacity >= IDLE_MIN) = a real dispersed surplus army, not just a big economy.
    # NOTE: this feeds ONLY the HQ-fortify (_under_massed) below -- it deliberately does NOT raise threat_total/
    # target_garrison. Routing it through total-army MATCHING over-trains and stalls the economy in the mirror
    # (verified: 13W7D -> 9W8D3L). The safe response to "enemy is massing" is to FORTIFY the HQ, not to match
    # head-count (the 50차 복리 collapse). Training stays driven by threat_army (concentrated stacks) as before.
    _enemy_workcap = sum((HQ_LEVELS if b.type is BType.HQ else BASE_LEVELS)[b.level].work_cap
                         for b in S.buildings if b.side is not M.my_side)
    _outproduced = (bool(OUTPRODUCE) and turn >= MOBILIZE_ARM_TURN
                    and enemy_total >= len(my_warriors) + OUTPRODUCE_MARGIN
                    and enemy_total >= OUTPRODUCE_RATIO * max(len(my_warriors), 1)
                    and (enemy_total - _enemy_workcap) >= OUTPRODUCE_IDLE_MIN)
    if MATCH_TOTAL and turn >= MOBILIZE_ARM_TURN and enemy_total >= len(my_warriors) + MATCH_TOTAL_MARGIN:
        BOT.threat_total = max(BOT.threat_total, min(MATCH_TOTAL_CAP, math.ceil(MATCH_TOTAL_F * enemy_total)))
    elif BOT.threat_total > 0:
        BOT.threat_total = min(BOT.threat_total, max(enemy_total, len(my_warriors)))
    mil_switch = BOT.threat_army > 0 or BOT.threat_total > 0
    target_garrison = 0
    concentrate = False
    base_eating = False
    counter_now = False
    _ehqb0 = S.find_building(M.opp_hq); _ehl0 = _ehqb0.level if _ehqb0 is not None else 1
    _terr_deficit = (sum(1 for b in S.buildings if b.side is not M.my_side and b.type is BType.BASE)
                     > len(my_bases) + LOSE_MARGIN)
    losing = (_terr_deficit and hq is not None and hq.level < _ehl0)  # economy/CDROP: only when strictly behind
    if BOT.threat_total > 0:                       # match the enemy's TOTAL army (workers + garrison)
        target_garrison = min(MATCH_TOTAL_CAP, BOT.threat_total)
    if BOT.threat_army > 0:
        mf = MOBILIZE_MATCH if (hq is not None and _is_max(hq)) else MOBILIZE_MATCH_SUBL5
        target_garrison = max(target_garrison, min(MOBILIZE_CAP, math.ceil(mf * BOT.threat_army)))
        # CONCENTRATE everyone on node 0 only once the wave is genuinely CLOSING -- right on
        # top of us (<= CONCENTRATE_DIST) or having advanced strictly past the midline toward
        # us. We give up base income here on purpose (surviving outranks economy -- the user's
        # "don't be greedy" rule). The bar is tight: a stack merely PARKED at the gate boundary
        # is not committing, and concentrating on it for 70 turns starved our economy + L5 climb
        # and then the real wave killed us (log6). The wide gate is for DETECTION only.
        committed = stack_reg >= 0 and (
            stack_dist <= CONCENTRATE_DIST or stack_dist < nav.hops(stack_reg, M.opp_hq))
        # NOTE: do NOT concentrate merely because `threat > 0`. A couple of advanced enemy
        # scouts (threat 2-6) parked past the midline must not make us abandon our whole
        # economy for 100+ turns (that stalled HQ at L2 and the real late wave then killed us,
        # log6). `threat` still raises defenders_needed (pull surplus home); full concentration
        # waits for the stack to actually CLOSE, or the enemy to stand ON our HQ.
        concentrate = (on_hq > 0 or committed)
        # FORWARD BASE-EATING: a sizable wave has pushed into OUR half (past the midline) but is NOT
        # on our HQ -- it is grinding our forward bases one by one. The default `concentrate` here
        # would turtle our whole army at node 0 and just watch the economy die while the enemy never
        # even comes to the HQ -- the EXACT log7/8 tiebreak loss (bases eaten -> income collapses ->
        # our HQ stalls at L3 while theirs reaches L5). Instead, when we can actually contest the
        # stack (our army >= its size), keep the economy lean and march our matched surplus out to
        # FIGHT the eaters where they stand (handled in 2c). Transitions back to a real HQ-turtle the
        # instant the stack actually closes on us (stack_dist <= CONCENTRATE_DIST -> base_eating off).
        base_eating = (on_hq == 0 and stack_reg >= 0
                       and stack_dist > CONCENTRATE_DIST
                       and stack_dist < nav.hops(stack_reg, M.opp_hq)
                       and enemy_stack_sz >= MOBILIZE_NEAR
                       and len(my_warriors) + _home_turret(S, M, me, stack_reg) >= enemy_stack_sz)
        if base_eating:
            concentrate = False
        # COUNTER-DOOMSTACK (user: hit the all-in's weakness -- their rear is empty): when we are
        # LOSING the land war AND the enemy committed its stack forward into our half, its HQ is
        # open. We lose the tiebreak anyway (economy collapsing), so RACE a counter-stack at the
        # enemy HQ to crack it outright instead of dying slowly. Overrides turtle/defend.
        _ehqb = S.find_building(M.opp_hq)
        _ehl = _ehqb.level if _ehqb is not None else 1
        _hq_ok = (hq is not None and (hq.level < _ehl if COUNTER_MODE == 'lt' else hq.level <= _ehl))
        if (_terr_deficit and _hq_ok and stack_reg >= 0 and on_hq == 0 and enemy_stack_sz >= MOBILIZE_NEAR
                and stack_dist < nav.hops(stack_reg, M.opp_hq)
                and (not COUNTER_ARMY or len(my_warriors) < enemy_stack_sz)):
            counter_now = True
            concentrate = False
            base_eating = False
        # Force the FULL matched garrison into node 0 ONLY when the wave commits. While it is
        # merely FORMING, do NOT inflate defenders_needed to target_garrison: that pulls every
        # warrior to the HQ and STRIPS the base workers, collapsing income so the HQ never
        # finishes its L5 climb -- and we then lose the tiebreak to a wave that never even
        # reaches our HQ (the enemy ate a forward base instead; exact map3/log7-8 failure).
        # Forming-phase defense comes for free: the trained surplus musters home (2c) and TRAIN
        # grows the army toward target_garrison, all while base workers keep funding the fortress.
        if concentrate:
            defenders_needed = min(len(my_warriors), max(defenders_needed, target_garrison))
    # FORWARD PUSH: a real enemy detachment is deep in our half. Decide its TARGET (the user's "기지로
    # 오는지 HQ로 오는지 명확히 판단"): the closest of OUR buildings to the stack. If that is the HQ (or the
    # stack is right on top of it), turtle node 0. If it is a forward BASE, the wave is a base-raid --
    # CONTEST it forward with our matched army (base_eating) and KEEP the HQ climb + economy alive,
    # instead of abandoning the base to pull everyone to the HQ (the log7/8 loss: the enemy razed our
    # forward base while we turtled node 0 and stalled at L3 -> lost the tiebreak). The HQ heals to full
    # on its next upgrade, so eating some HQ chip to save a base is the right trade. Still turtle if we
    # are outnumbered (can't win the field fight) or the stack is genuinely closing on the HQ.
    if on_hq == 0 and fwd_reg >= 0 and fwd_sz >= WAVE_STACK_MIN and fwd_dist <= CONCENTRATE_DIST + 2:
        _wtgt = min(my_building_regions, key=lambda r: nav.hops(fwd_reg, r)) if my_building_regions else M.my_hq
        _hq_bound = (nav.hops(fwd_reg, M.my_hq) <= HQ_NEAR) or (_wtgt == M.my_hq)
        if _hq_bound or len(my_warriors) < fwd_sz:
            concentrate = True
            base_eating = False
            defenders_needed = min(len(my_warriors), max(defenders_needed, fwd_sz + 1))
        else:
            base_eating = True          # base-raid we can contest -> fight it forward, do not abandon it
            concentrate = False
            if fwd_reg != stack_reg:     # ensure 2c marches at the FORWARD stack, not the enemy's rear mass
                stack_reg, enemy_stack_sz, stack_dist = fwd_reg, fwd_sz, fwd_dist
    # CONTEST FREES THE ARMY: when base_eating (the wave is on our BASE, not our HQ), do NOT let `threat`
    # pin everyone home -- that left only a trickle to contest while the base fell (the log7/8 failure:
    # "병력이 갖춰졌는데 너무 늦게/적게 보냈다"). Hold just the guard and send the rest to FIGHT the wave at the
    # base, exactly like _relief. The HQ heals to full on its next upgrade, so trading a little HQ chip to
    # win the field fight and save the base income (which funds the L5 climb) is the right call.
    if base_eating:
        defenders_needed = min(len(my_warriors), guard_floor)

    # --- SIEGE-EMERGENCY (FORTRESS-AND-RECALL): the g3 all-in fix ------------
    # g3: an 11-stack (a committed all-in) marched our HQ while our fist raided deep (regions 24-54)
    # and our HQ was a weak L2 (15hp). It cracked at t92. Detect THIS shape -- a BIG committed enemy
    # stack that has CROSSED into our half and is BEELINING our HQ, close enough to reach us soon --
    # and react existentially: (a) FORCE-RECALL the raid fist home regardless of depth (siege_recall,
    # consumed in 2c so the fist defends in time, not 5 turns late), and (b) PRIORITIZE the HQ climb to
    # a survivable fortress (siege_climb) when our present defender-HP pool cannot outlast the wave.
    #   The defender pool = HQ hp + every warrior we own (each warrior = 1 body that can muster onto
    # node 0 and soak siege). vs a wave of W, siege/turn = max(0, W - present_defender_hp); an upgrade
    # heals the HQ to full AND adds hp + a turret attack (thins the stack), so climbing is the highest-
    # value survival spend. We gate on a genuine all-in (SIEGE_EMERG_STACK, beelining, within
    # SIEGE_EMERG_RANGE) so a turtle/mirror -- which never concentrates such a stack at our gate --
    # never trips it, preserving the raze-denial draws/wins. on_hq>0 (already under siege) always counts.
    siege_recall = False
    siege_climb = False
    if bool(SIEGE_EMERGENCY) and hq is not None and enemy_warriors:
        # the worst incoming all-in: either already on our HQ, or a big stack beelining it in our half
        _incoming_all_in = 0
        if on_hq > 0:
            _incoming_all_in = on_hq
        if (stack_reg >= 0 and enemy_stack_sz >= SIEGE_EMERG_STACK
                and stack_dist <= SIEGE_EMERG_RANGE
                and stack_dist < nav.hops(stack_reg, M.opp_hq)):   # has crossed toward us (beelining)
            _incoming_all_in = max(_incoming_all_in, enemy_stack_sz)
        if _incoming_all_in > 0:
            # RECALL the fist home the moment a real all-in is incoming -- depth-independent, so a deep
            # raider (g3 region 49) starts the long walk home NOW instead of after the breach. The home
            # garrison is still filled first (2a); this only redirects the OFFENSIVE surplus.
            siege_recall = True
            # A confirmed all-in on our own HQ overrides ALL offense: racing the enemy HQ while ours is
            # stormed is the g3 death. Suppress counter_now (rear race) AND base_eating -- the latter peels
            # the EXCESS out to RAZE enemy bases (away from home) during the siege, the exact "fist too deep,
            # came home late" loss. _relief STAYS (a stack standing ON our own base is the real forward
            # defense); everything else falls through to the 2c recall else-branch and marches to node 0.
            counter_now = False
            base_eating = False
            # present defender-HP pool we can ACTUALLY put on node 0 in time = HQ hp + only the bodies that
            # can reach home before the stack arrives (within stack_dist hops). Counting ALL bodies (incl.
            # deep raiders that cannot get back) was the g3 trap: 13 scattered warriors read as "survivable"
            # so the climb never fired and the L2 HQ was cracked. The honest reachable pool fires the climb
            # when home is genuinely thin -> the HQ upgrades (heals to full + more hp/turret) and survives.
            _reach = max(1, stack_dist)
            _def_pool = hq.hp + sum(max(1, w.hp) for w in my_warriors
                                    if nav.hops(w.region, M.my_hq) <= _reach)
            if not _is_max(hq) and _def_pool < _incoming_all_in + SIEGE_EMERG_HP_SLACK:
                siege_climb = True

    # --- PROTO attack mode --------------------------------------------------
    if ATTACK_WHEN == 'always':
        _attack_now = (on_hq == 0)
    elif ATTACK_WHEN == 'losing':
        # RETALIATE on ECONOMY, not on HQ-level: the moment the enemy out-bases us
        # (it raided/took our land), send the surplus to smash ITS bases so our
        # compounding does not fall behind -- the user's rule: never let a base-trade
        # just 'flow' into a passive economic loss (games 4/5). The old gate also
        # required hq.level < enemy (usually false mid-game), so we never retaliated
        # and the army sat idle while our economy bled (logs 7/8).
        _attack_now = (_terr_deficit and on_hq == 0)
    else:
        _attack_now = counter_now
    _attack_now = bool(PROTO_ATTACK) and _attack_now
    # PROACTIVE HARASS (the user's 양동작전): once our economy is healthy (HQ >= HARASS_HQLEVEL)
    # OR we are already behind, send the TRUE surplus to grind the enemy's bases as TWO evasive
    # squads (_two_front_raid: two prongs on opposite flanks; a prong that meets a bigger force
    # DISENGAGES and hits where they ain't). This denies the enemy economy so it cannot out-climb
    # us in a quiet game (real log 5: we did zero damage and lost the HQ race by one level).
    _harass_now = (bool(PROTO_ATTACK) and on_hq == 0 and hq is not None
                   and (_terr_deficit or hq.level >= HARASS_HQLEVEL
                        or (bool(EARLY_RAID) and turn >= EARLY_RAID_TURN)))

    # --- enemy TEMPO (reactive; never schedule the HQ climb by turn alone) ---
    # The real opponents flip modes by STATE, not clock: when their development
    # stalls they convert spare gold into a UNIT BURST and strike all at once;
    # once it lands they resume upgrading. So (a) climb the HQ only in a SAFE
    # window (enemy is upgrading / not massing) -- a fixed-turn stall just hands
    # them the burst trigger -- and (b) ride out their burst on defense.
    _e_tot = len(enemy_warriors)
    _e_lvl = 0
    for _b in S.buildings:
        if _b.side is not me:
            _e_lvl += _b.level
    _grow = _e_tot - getattr(BOT, 'e_tot_prev', _e_tot)
    if _grow < 0:
        _grow = 0
    BOT.e_growth = getattr(BOT, 'e_growth', 0.0) * TEMPO_DECAY + _grow
    if _e_lvl > getattr(BOT, 'e_lvl_prev', _e_lvl):
        BOT.e_dev_turn = turn
    BOT.e_tot_prev = _e_tot
    BOT.e_lvl_prev = _e_lvl
    _since_dev = turn - getattr(BOT, 'e_dev_turn', -99)
    _enemy_burst = (BOT.e_growth >= TEMPO_BURST) and (_since_dev > TEMPO_DEV_WIN)
    _enemy_dev = (_since_dev <= TEMPO_DEV_WIN) and not _enemy_burst
    # Climb the HQ hard only to CATCH UP (we are strictly behind the enemy's HQ
    # level -- a tiebreak gap we must close) or as a late-game L5 backstop; never
    # while the enemy is BURSTING onto us (ride that out on defense), and never
    # greedily ahead (that starves the economy that funds the expensive top steps).
    _behind_hq = (hq is not None and hq.level < _ehl0)
    # --- LATE-GAME FORTRESS / TIEBREAK-MAX (the user's rule) -----------------
    # Real losses 4/5: the enemy out-develops us, masses a 23-25 doomstack and STORMS
    # our HQ while our army is OFF raiding (game 4), or we trade armies in a race we
    # cannot win and the HQ stalls at L3 (games 5/7 -- the climb was disabled exactly
    # during the enemy's mass-train because _hq_climb_window forbade _enemy_burst).
    # The user's call: late-game, estimate when the enemy army can REACH our HQ; if we
    # cannot out-field it, STOP attacking, hold everyone home, and pour gold into the HQ
    # so it MAXES (L5/30hp). A turreted L5 + full garrison HOLDS the siege, and if it
    # still reaches turn 200 the maxed HQ wins the tiebreak (game 8 won exactly so).
    _inbound = sum(1 for _w in enemy_warriors
                   if nav.hops(_w.region, M.my_hq) <= FORTRESS_RANGE
                   and nav.hops(_w.region, M.my_hq) <= nav.hops(_w.region, M.opp_hq))
    _fortress = (bool(FORTRESS) and turn >= FORTRESS_TURN and hq is not None
                 and enemy_total >= len(my_warriors) - FORTRESS_SLACK
                 and (enemy_total >= FORTRESS_ARMY or _inbound >= FORTRESS_MIN))
    if _fortress and FORTRESS_HOLD:
        # hold the army home (don't raid out into a lost-HQ trade) and don't race out --
        # the recall itself is in section 2c via home_safe (and _harass/counter off here)
        _harass_now = False
        counter_now = False
    # Climb the HQ to L5 to CATCH UP (strictly behind the enemy HQ level), as a late
    # backstop, OR all through the fortress buildup -- ignoring the enemy unit BURST in
    # that case (we have committed to the tiebreak; each upgrade heals the HQ + adds
    # siege-soak). The climb still pauses the instant a stack COMMITS (not concentrate),
    # where surviving the imminent hit via training outranks one more level.
    # ...and late-game, KEEP climbing through a non-on_hq concentrate when we TRAIL the enemy's HQ level:
    # the catch-up upgrade (each level = +hp +turret + heal-to-full) is what wins the tiebreak, and a stack
    # merely PARKED (not standing on node 0) must not freeze the climb for 100 turns (g8 sat at L3 from t46
    # to t181 because concentrate was continuously set). on_hq>0 (enemy ON our HQ) still stops the climb.
    _climb_safe = (on_hq == 0 and (not concentrate or (_behind_hq and turn >= LATE_BACKSTOP))
                   and hq is not None and not _is_max(hq))
    # PROACTIVE CLIMB: open the window when the economy is ESTABLISHED (>= PROACTIVE_CLIMB_BASES
    # bases standing) and NO wave commits -- on_hq==0 (inherited via _climb_safe), not concentrate,
    # and the nearest enemy stack is beyond CONCENTRATE_DIST -- regardless of ahead/even/turn. This is
    # what lets us chain L2->L5 by ~t120-140 when AHEAD/EVEN instead of coasting at L2 (g6/g8). It does
    # NOT bypass _enemy_burst (ride a burst out on defense) nor the committed-wave freeze (concentrate
    # closes _climb_safe), and the affordability + worker-first guards downstream still apply.
    _econ_established = (bool(PROACTIVE_CLIMB) and turn >= PROACTIVE_CLIMB_TURN
                        and len(my_bases) >= PROACTIVE_CLIMB_BASES)
    _proactive_climb = (_econ_established and not concentrate
                        and stack_dist > CONCENTRATE_DIST and not _enemy_burst)
    # CLIMB-RESCUE: the only proactive climb opener. Fires ONLY when razing is GENUINELY futile -- our HQ
    # is STUCK low (<= CLIMB_STUCK_LEVEL) late (turn >= CLIMB_STUCK_TURN) AND the backdoor has found NOTHING
    # crackable for FUTILE_STREAK consecutive turns (a fully-defended enemy we cannot deny). Then we climb
    # the HQ with the gold we would otherwise bleed roaming (the g8 coast: L2 from t46 to t200). vs a turtle
    # this NEVER trips -- we crack its bases every few turns so the streak resets and we are L3+ by ~t84 --
    # so the proven raze-denial that WINS turtle/mirror is fully preserved.
    _climb_rescue = (hq is not None and not _is_max(hq) and hq.level <= CLIMB_STUCK_LEVEL
                     and turn >= CLIMB_STUCK_TURN and BOT.no_target_streak >= FUTILE_STREAK)
    # SIEGE-CLIMB opener (g3): when an all-in is incoming and our HQ is too weak to survive it,
    # FORCE the climb even though `concentrate` is set (a committed wave normally closes _climb_safe).
    # Each upgrade heals the HQ to full + adds hp + a turret attack -- it is the single best survival
    # spend. We still require on_hq==0 (an enemy STANDING on the HQ makes the upgrade referee-illegal,
    # and we cannot afford to lose a defender turn then -- we just hold/train); upgrade_legal in 1a/1c
    # re-checks "no enemy on node 0", so this never emits an illegal UPGRADE. Distinct from _climb_safe
    # so it survives the concentrate freeze; bounded by siege_climb (a genuine weak-HQ all-in only).
    _siege_climb_ok = (bool(SIEGE_EMERGENCY) and siege_climb and on_hq == 0
                       and hq is not None and not _is_max(hq))
    # MID-GAME FORTIFY (g3): a real massed enemy army is forming (threat_army/threat_total fired at >=
    # FORTIFY_MASS_MIN) and our HQ is not yet a fortress. Climb NOW, regardless of relative HQ level or
    # turn -- the paper L2 HQ that loses to the all-in is the exact g3 death. Rides _climb_safe so it is
    # FORMING-phase only (on_hq==0, not concentrate); the committed wave is handled by siege_climb. Does
    # NOT fire vs a turtle (never stacks FORTIFY_MASS_MIN), so the raze-denial draws/wins are untouched.
    _under_massed = (bool(FORTIFY) and hq is not None and not _is_max(hq)
                     and (max(BOT.threat_army, BOT.threat_total) >= FORTIFY_MASS_MIN or _outproduced))
    _hq_climb_window = ((_climb_safe and (_fortress
                        or _under_massed
                        or ((_behind_hq or turn >= LATE_BACKSTOP) and not _enemy_burst)
                        or _proactive_climb
                        or _climb_rescue))
                        or _siege_climb_ok)
    # Recall the idle fist HOME (bank for the rescue climb) exactly while the rescue is active and safe.
    _climb_pending = (_climb_safe and _climb_rescue)
    # --- RELIEF: intercept an enemy column grinding our forward bases --------
    # The real econ-swarmers (logs 7/8) never beeline our HQ -- they park a stack
    # ON our forward strongholds and grind them one by one, far enough from HQ that
    # the HQ-turtle never triggers, so our army oscillates idle while our economy
    # (and the L5 climb it funds) collapses. Detect a stack SITTING ON/next to one
    # of OUR buildings and march the surplus onto it to FIGHT -- on our own turreted
    # ground we hold even slightly outnumbered (siege/turn = stack - our defender HP,
    # and the turret adds attacks). The 'on our land' test keeps this from diverting
    # the HQ-rush vs a stack merely TRANSITING toward our HQ (the beeline proxies).
    _relief = (bool(RELIEF) and on_hq == 0 and stack_reg >= 0
               and enemy_stack_sz >= RELIEF_MIN
               and stack_dist > CONCENTRATE_DIST
               and stack_dist < nav.hops(stack_reg, M.opp_hq)
               and (stack_reg in my_building_regions
                    or any(nb in my_building_regions for nb in M.adj[stack_reg]))
               and len(my_warriors) + _home_turret(S, M, me, stack_reg) >= enemy_stack_sz - RELIEF_SLACK
               and len(my_warriors) >= guard_floor + RELIEF_FORCE)
    # When relieving, the ONLY threat is that forward stack (it is sitting on our
    # base, not our HQ -- on_hq==0). Don't let `threat` pin the whole army home; hold
    # just the guard and send the rest as a real relief force to fight the column.
    if _relief:
        defenders_needed = min(len(my_warriors), guard_floor)

    # --- per-building garrison need -----------------------------------------
    # Keep economy LEAN so a raid army actually forms: each base holds only
    # WORKERS_PER_BASE worker(s) (still earns income); the HQ holds just the guard
    # (the mustering raid army parked at the HQ supplies its work income anyway).
    # Everyone beyond this becomes the raid force -> attacking is possible from far
    # lower thresholds, on far more maps.
    need: dict[int, int] = {}
    for b in my_buildings:
        if b.region == M.my_hq:
            need[b.region] = max(b.work_cap(), defenders_needed)   # HQ: full income (safe at home)
        elif concentrate:
            need[b.region] = 0                                     # ONLY a committed wave empties a base: survival outranks income
        else:
            # KEEP EVERY BASE WORKER (the user's compounding rule): each base earns its FULL work_cap
            # so the economy compounds. We NEVER pull a working soldier into the army -- raiders come
            # ONLY from the TRUE surplus trained on top of total_need (want_spare). Pulling workers to
            # "match the enemy's total" was the critical error that collapsed the compounding.
            need[b.region] = b.work_cap()
    total_need = sum(need.values())

    # --- gold budget --------------------------------------------------------
    reserve = GOLD_FLOOR + UPKEEP_PER_WARRIOR * (len(my_warriors) + 1)
    if hq is not None and hq.level >= 4:
        reserve += HEAL_RESERVE  # bank for repairs once we have a fortress
    spent = 0

    def can(cost: int, ignore_heal_reserve: bool = False) -> bool:
        r = reserve - (HEAL_RESERVE if (ignore_heal_reserve and reserve >= HEAL_RESERVE) else 0)
        return (S.gold - spent - cost) >= r

    def upgrade_legal(region: int) -> bool:
        # referee requires a friendly warrior present AND no enemy warrior present
        return region in my_present and region not in enemy_at

    # ======================================================================
    # 1) UPGRADES / BUILD / HEAL  (referee processes these first each morning)
    # ======================================================================
    upgraded_regions: set[int] = set()

    def plan_upgrade(region: int, cost: int) -> bool:
        nonlocal spent
        if region in upgraded_regions:
            return False
        spent += cost
        a.upgrades.append(region)
        upgraded_regions.add(region)
        return True

    # 1a) Emergency: keep HQ alive. If HQ damaged & no enemy standing on it,
    #     upgrade (also heals + adds turret/hp) or heal at max level.
    if hq is not None and hq.hp < hq.current_hp() and upgrade_legal(hq.region):
        cost = _next_cost(hq)
        # under real pressure, spend even the heal reserve to survive
        if can(cost, ignore_heal_reserve=True):
            plan_upgrade(hq.region, cost)

    # 1b) Build bases on claimers that have arrived on an unclaimed stronghold.
    for w in my_warriors:
        if w.state is not WState.STATIONARY:
            continue
        r = w.region
        if (r in BOT.claim_set and S.find_building(r) is None
                and r not in upgraded_regions and r not in _skip_build
                and r not in enemy_at and turn < ECON_PAYBACK_CUTOFF):
            # NB: build only when NO building of ANY side exists at r — emitting
            # UPGRADE on an enemy-owned building is an instant-WA loss (referee
            # treats it as build-on-existing -> enemy-owned -> WaError).
            if can(BASE_LEVELS[1].cost):
                plan_upgrade(r, BASE_LEVELS[1].cost)
                my_building_regions.add(r)  # treat as ours for the rest of this turn

    # 1c) HQ economic / defensive upgrades.
    if (hq is not None and hq.region not in upgraded_regions and not _is_max(hq)
            and upgrade_legal(hq.region)):
        cost = _next_cost(hq)
        nxt_workcap_gain = HQ_LEVELS[hq.level + 1].work_cap - hq.work_cap()
        payback = (cost / WORK_INCOME) if nxt_workcap_gain > 0 else 1e9
        econ_ok = (nxt_workcap_gain > 0) and (turn + payback <= MAX_TURN)
        # The HQ MUST climb to L5 (30hp): it is the day-200 tiebreak insurance, and an
        # HQ stuck below L5 loses the tiebreak to any maxed turtle. Reach the fortress
        # whenever we have a working economy and can afford it without dipping below
        # the operating reserve.
        #   The old logic gated the fortress climb on level>=3 with a +400 slack bar;
        #   on tight maps the HQ would reach L2, never accumulate enough before the
        #   econ-payback window closed (turn 120), and then be PERMANENTLY stuck at L2
        #   (15hp) -- an automatic tiebreak loss. Reachable from L2, modest bar, fixes it.
        want = False
        if hq.level < 2:
            want = econ_ok                                   # L1->L2: cheap, economic
        elif len(my_bases) >= 1:
            # L2->L5 fortress insurance. Reaching L5 (30hp) outranks holding the 1000 heal
            # cushion -- the upgrade itself heals the HQ to full -- so the climb may dip into
            # that reserve, holding back only a lean operating float. This stops the expensive
            # L4->L5 step (3600g) from stalling forever behind the cushion and losing the
            # tiebreak by a single upgrade (HQ L4=25 < their L5=30).
            lean = GOLD_FLOOR + UPKEEP_PER_WARRIOR * (len(my_warriors) + 1)
            want = (S.gold - spent) >= (cost + lean)
            if _hq_climb_window and (S.gold - spent) >= (cost + GOLD_FLOOR):
                want = True
        if want and can(cost, ignore_heal_reserve=True):
            plan_upgrade(hq.region, cost)

    # 1d) Base work-slot upgrades when economy supports and payback is positive.
    #     SUPPRESSED while fortifying (g3): when a real massed army is forming, every gold goes to the HQ
    #     climb + army, NOT into deepening base work-slots -- spending on bases here is exactly what left
    #     the HQ at a paper L2 while the deathball grew (the user's "기지를 짓느라 돈을 너무 써버린").
    for b in sorted(my_bases, key=lambda bb: bb.region):
        if b.region in upgraded_regions or _is_max(b) or not upgrade_legal(b.region) or _under_massed:
            continue
        cost = _next_cost(b)
        payback = cost / WORK_INCOME
        if turn + payback <= MAX_TURN and (S.gold - spent) >= (cost + reserve + 200):
            if can(cost):
                if plan_upgrade(b.region, cost) and PRESTAFF:
                    need[b.region] = max(need.get(b.region, 0), BASE_LEVELS[b.level + 1].work_cap)

    # ======================================================================
    # 2) MOVES  (only STATIONARY warriors; free to friendly buildings, 10 else)
    # ======================================================================
    stationary = [w for w in my_warriors if w.state is WState.STATIONARY]
    moving = [w for w in my_warriors if w.state is WState.MOVING]

    stationary_at: dict[int, list[Warrior]] = defaultdict(list)
    for w in stationary:
        stationary_at[w.region].append(w)
    incoming: dict[int, int] = defaultdict(int)
    for w in moving:
        incoming[w.target] += 1

    assigned: set[WarriorId] = set()

    def order_move(w: Warrior, target: int) -> bool:
        nonlocal spent
        if w.id in assigned or w.state is not WState.STATIONARY:
            return False
        if target == w.region:                       # avoid wasted 10g + stuck-MOVING bug
            return False
        if not nav.reachable(w.region, target):
            return False
        dest_b = S.find_building(target)
        cost = 0 if (dest_b is not None and dest_b.side is me) else MOVE_COST
        if cost > 0 and not can(cost):
            return False
        spent += cost
        a.moves.append((w.id, target))
        assigned.add(w.id)
        return True

    # Identify surplus stationary warriors (not currently needed where they sit).
    # Under an active HQ siege, abandon base income and free base workers so they
    # can rush home to defend (the only same-day refill is training, capped at
    # train_cap, so we also need the standing-worker pool).
    hq_pressure = on_hq > 0
    surplus: list[Warrior] = []
    for r, ws in stationary_at.items():
        if r in need:
            keep = 0 if (hq_pressure and r != M.my_hq) else need[r]
            for i, w in enumerate(ws):
                if i >= keep:
                    surplus.append(w)
        elif (r in BOT.claim_set and S.find_building(r) is None
                and r not in _skip_build and r not in enemy_at):
            pass  # a claimer waiting to build (kept; building handled above / next turns)
        else:
            surplus.extend(ws)   # stranded warriors -> reassignable

    def nearest_surplus(target: int) -> Warrior | None:
        best = None
        best_h = 1 << 30
        for w in surplus:
            if w.id in assigned:
                continue
            h = nav.hops(w.region, target)
            if h < best_h:
                best_h = h
                best = w
        return best

    # 2a) Fill garrison deficits (these moves are free — destinations are ours).
    #     HQ first so defenders are prioritized under pressure.
    for r in sorted(need.keys(), key=lambda rr: (rr != M.my_hq, rr)):
        settled = len(stationary_at.get(r, []))
        eff = settled + incoming.get(r, 0)
        deficit = need[r] - eff
        while deficit > 0:
            w = nearest_surplus(r)
            if w is None:
                break
            if order_move(w, r):
                incoming[r] += 1
                deficit -= 1
            else:
                break

    # 2b) Claim the next unclaimed my-half stronghold with a spare surplus warrior.
    handled_targets = set(my_building_regions)
    for w in my_warriors:
        if w.state is WState.MOVING and w.target in BOT.claim_set:
            handled_targets.add(w.target)
        if w.region in BOT.claim_set:
            handled_targets.add(w.region)
    # Dispatch up to MAX_CLAIMERS claimers per turn to the NEAREST unclaimed
    # strongholds -> expand fast and don't let the enemy grab the contested middle.
    # Keep expanding while a wave merely FORMS (we still want economy + L5), but STOP being
    # greedy once it COMMITS (concentrate): then every spare body and gold piece goes to the
    # matched home army, not new economy. Chasing bases while the wave lands is how we lost.
    #   NOTE: do NOT also halt on _under_massed here -- braking claimers in the forming phase
    #   stalls the economy and converts mirror/turtle WINS into draws (the 50차 death-spiral:
    #   in a mirror BOTH sides mass, so _under_massed fires and stopping expansion just coasts).
    #   The fortress redirect is funded by the HQ-climb priority + the 1d base-upgrade suppression
    #   above, which keep income flowing while still pouring surplus gold into the HQ.
    if turn < ECON_PAYBACK_CUTOFF and not concentrate:
        dispatched = 0
        for s in BOT.claim_order:
            if dispatched >= MAX_CLAIMERS:
                break
            if s in handled_targets or s in enemy_at or s in _skip_build:   # ours/incoming, contested, or (late) razed-enemy land to leave empty
                continue
            if S.gold - spent < BASE_LEVELS[1].cost + reserve - 100:
                break                                   # can't foreseeably afford more bases yet
            w = nearest_surplus(s)
            if w is None:
                break                                   # no spare warrior to send
            if order_move(w, s):
                handled_targets.add(s)
                dispatched += 1

    # 2c) RAID (two-front backdoor): move the TRUE surplus as concentrated stacks to deny the
    #     enemy's economy — siege their bases, then the enemy HQ. Moving as a stack is the whole
    #     point: a lone attacker is picked off and deals 0; a stack of N cracks a base (turret +
    #     lone worker) and accumulates real siege. The GUARD_MIN guard stays home, so committing
    #     the raid never opens our own HQ.
    raid_force = [w for w in surplus if w.id not in assigned]
    # Home is "raid-safe" as long as the HQ is not under direct siege and no wave has COMMITTED.
    # A few enemy scouts past the midline (threat>0) must NOT freeze all offense -- they only
    # raise defenders_needed (filled FIRST in 2a), so the raid uses TRUE surplus beyond the
    # garrison. This is what lets us HARASS the enemy's economy during its buildup (the user's
    # distraction tactic) instead of sitting passive while it masses an unbeatable wave.
    # siege_recall (g3): an all-in is incoming -> the offense is OVER, the fist comes home to defend.
    # Closing home_safe routes the WHOLE raid_force through 2c's else-branch (recall every body to node 0)
    # even when the wave has not yet CLOSED enough to set `concentrate` -- the exact g3 gap where the fist
    # lingered deep (region 49) while the 11-stack approached. We also drop any raid lock so a committed
    # fist breaks off its target and walks home immediately instead of finishing a now-irrelevant siege.
    if siege_recall and (BOT.raid_lock > 0 or BOT.raid_tgt >= 0):
        BOT.raid_tgt = -1
        BOT.raid_lock = 0
    home_safe = (on_hq == 0 and not concentrate and not siege_recall
                 and not (_fortress and FORTRESS_HOLD))
    # TERRITORY PRINCIPLE: never let the enemy out-base us, or the economy gap
    # compounds beyond recovery. Whenever we are NOT ahead in bases, go take enemy
    # land (their nearest base) -- accepting that we may lose some of our own. When
    # behind we commit a small force (MIN_RAID); when already ahead we only raid
    # with a real surplus (MUSTER).
    enemy_base_regs = [b.region for b in S.buildings
                       if b.side is not M.my_side and b.type is BType.BASE]
    # Contest only when STRICTLY falling behind (enemy has more land than us).
    # When even/ahead we keep our economy and play the tiebreak (so a mirror/turtle
    # stays a draw); only a genuine territory deficit makes us go take their land.
    behind = len(enemy_base_regs) > len(my_bases) + TERRITORY_SLACK
    # Can we still EXPAND our own economy (an unclaimed claimable stronghold remains)?
    can_expand = any(s not in handled_targets and s not in enemy_at and s not in _skip_build for s in BOT.claim_order)
    # STUCK-BEHIND: the enemy out-bases us AND we have no stronghold left to claim, so we cannot
    # close the gap by BUILDING. Then we must TAKE their land -- commit a SMALL stack EARLY to
    # raid enemy bases and deny their economy before the gap compounds (the user's rule: attacking
    # only after the gap has fully widened is meaningless). Otherwise keep the safe MUSTER bar.
    stuck_behind = behind and not can_expand
    # ECONOMIC CUSHION for early raids: only raid early while we hold a BASE LEAD. A raid costs gold/units
    # that would otherwise feed the L5 climb; in a SYMMETRIC game (mirror) that diversion makes US climb
    # slower and lose the tiebreak (verified: early-raiding a mirror stalled our HQ at L4 -> loss, vs an
    # L5 draw without it). A base lead means the raid spends a TRUE surplus the climb does not need -- so
    # we press an advantage we already hold (vs a weaker/passive opponent we out-base it by mid-opening)
    # and stay passive when even (keep the safe draw). This is the discriminator that converts winnable
    # draws to wins WITHOUT regressing even matchups into losses.
    _econ_lead = len(my_bases) > len(enemy_base_regs)
    # Early window: commit eagerly at the MIN_RAID floor (continuous pressure) instead of waiting for the
    # safe MUSTER stack -- _can_crack + the evasion keep a small fist from throwing itself away.
    _early_window = bool(EARLY_RAID) and turn < PRESSURE_TURN and _econ_lead
    commit_threshold = MIN_RAID if (stuck_behind or _early_window) else MUSTER
    # LIVE enemy BASES the backdoor may target (regions, so the crack toolkit reads turret/level/
    # defenders via S.find_building). The enemy HQ is DELIBERATELY EXCLUDED: _can_crack snapshots the
    # defenders standing ON the target, so a far-off fist sees the HQ momentarily undefended and the
    # sim says "crackable" -- but by the time the fist arrives the enemy's whole army converges on its
    # own HQ, siege drops to 0, and the turret-3 wipes the fist for ZERO damage (the user's "상대 HQ까지
    # 가서 병사들을 다 죽음으로 몰아 데미지를 못준다"). The backdoor RAZES BASES and roams; it never throws the
    # fist at the turreted HQ. A deliberate HQ assault stays the job of counter_now (open-rear race).
    # Near-HQ bases are NOT blanket-excluded anymore: _can_crack now counts the HQ garrison that would
    # converge (REINFORCE_DIST), so a base by a DEFENDED HQ reads uncrackable (no suicide -- the 4/5
    # miscalc fix) while one by a PASSIVE HQ is taken (keep pressing an enemy that does not intercept --
    # the user's game-5 rule: razed the forward bases, then stalled on the lightly-held near-HQ ones).
    live = [b.region for b in S.buildings if b.side is not M.my_side and b.type is BType.BASE]
    # OVERWHELMING-ARMY HQ ASSAULT (the user's rule): late-game, if our committing force can DESTROY the
    # enemy HQ even when its ENTIRE army converges to defend it (honest worst-case siege sim -> never the
    # suicide the user hated), throw everything at the HQ to win outright instead of just razing bases.
    _hq_assault = (bool(HQ_CRUSH) and turn >= HQ_CRUSH_TURN and on_hq == 0 and _ehqb0 is not None
                   and len(raid_force) >= MIN_RAID and len(my_warriors) > len(enemy_warriors)
                   and _sim_crack([w.hp for w in raid_force], _ehqb0.hp,
                                  HQ_LEVELS[_ehl0].turret,
                                  [w.hp for w in enemy_warriors], MAX_CRACK_TURNS)[0])
    if len(raid_force) >= commit_threshold:
        BOT.raiding = True
    if len(raid_force) < MIN_RAID or not home_safe:
        BOT.raiding = False
    if BOT.threat_army > 0 and concentrate:
        # Once the wave has COMMITTED, the matched army garrisons node 0 and never raids out
        # (2c's else-branch recalls every body to the HQ). But while the wave is only FORMING,
        # keep HARASSING with the surplus: pressuring the enemy's bases forces it to peel
        # defenders off its wave (shrinking the wave) and denies the economy that fuels it --
        # exactly the disruption that turns an unbeatable late mega-wave into a survivable one.
        BOT.raiding = False
    if _relief and raid_force:
        BOT.raid_tgt = -1; BOT.raid_lock = 0     # real enemy stack on our base -> release the commit & defend
        BOT.raiding = False
        for _w in raid_force:
            if _w.region != stack_reg:
                order_move(_w, stack_reg)
    elif counter_now and raid_force:
        # RACE the enemy's open rear with our whole counter-force -- but at its nearest BASE, NEVER its
        # turreted HQ (an HQ march is a suicide). If the enemy has no live base to punish, fall through to
        # the crack-aware backdoor (which is base-only and withdraws when nothing is crackable) rather
        # than throwing the fist at the HQ turret.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        BOT.raiding = False
        if COUNTER_TGT == 'base' and not enemy_base_regs:
            _raid_commit(S, M, nav, raid_force, live, order_move, my_building_regions, turn, climb_pending=_climb_pending)
        else:
            _ct = (min(enemy_base_regs, key=lambda r: nav.hops(stack_reg, r))
                   if (COUNTER_TGT == 'base' and enemy_base_regs) else M.opp_hq)
            for w in raid_force:
                if w.region != _ct:
                    order_move(w, _ct)
    elif base_eating and raid_force:
        # DEFEND/INTERCEPT: the enemy wave is grinding our forward bases. March our matched surplus
        # straight onto the enemy stack to FIGHT it where it stands -- combat resolves when we
        # co-locate, and army >= stack (the base_eating gate) means we win the exchange and STOP the
        # bleed, preserving the economy that funds our HQ climb. The HQ guard (filled in 2a) holds.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        BOT.raiding = False
        # COMMIT-BACKDOOR (the user's rule: "상대가 하나에 응집해 공격하면 소수로 다른 기지를 친다"). The enemy
        # committed its army forward, so its REAR is open. Send just enough to WIN the field fight at
        # the stack (matched + 1); peel the EXCESS to raze the enemy's now-undefended bases instead of
        # piling everyone onto the same fight -- otherwise we only trade ("안그럼 손해밖에 안나"). The
        # backdoor squad uses the crack toolkit (commits only to bases it can actually raze).
        need_fight = min(len(raid_force), enemy_stack_sz + 1)
        fight = sorted(raid_force, key=lambda w: nav.hops(w.region, stack_reg))[:need_fight]
        fight_ids = {w.id for w in fight}
        extra = [w for w in raid_force if w.id not in fight_ids]
        for w in fight:
            if w.region != stack_reg:
                order_move(w, stack_reg)
        if len(extra) >= MIN_RAID and live:
            _raid_commit(S, M, nav, extra, live, order_move, my_building_regions, turn, climb_pending=_climb_pending)
        else:
            for w in extra:
                if w.region != stack_reg:
                    order_move(w, stack_reg)
    elif (_harass_now and on_hq == 0 and concentrate and stack_dist > CONCENTRATE_DIST
            and len(raid_force) >= MIN_RAID):
        # PARKED-STACK PIN BREAK (the g6 draw): a far enemy stack parked past its own midline trips
        # `concentrate` -> home_safe=False -> the whole offense branch closes and our big army sits idle to
        # a draw (g6: 36 units, only 6 total siege ALL game). But the MATCHED garrison is already held home
        # (2a inflated defenders_needed to target_garrison under concentrate), so `raid_force` here is the
        # TRUE EXCESS above it. Commit that excess to RAZE the enemy's economy via the proven crack-aware
        # backdoor (base-only, never opp_hq, evasion-guarded) -> deny growth, reach L5 first, break the
        # stalemate. Excess-only + matched garrison home = the home HQ is never stripped. Gated on the stack
        # NOT closing (stack_dist > CONCENTRATE_DIST); a genuinely closing wave still recalls everyone below.
        BOT.raiding = False
        _raid_commit(S, M, nav, raid_force, live, order_move, my_building_regions, turn, climb_pending=_climb_pending)
    elif _harass_now and home_safe and raid_force:
        # ACTIVE crack-aware committed BACKDOOR (single owner of the offense branch). Fires from
        # mid-game (HQ >= HARASS_HQLEVEL) as BROADLY as the proven v1 -- so the attack stays vigorous
        # -- but it now ROAMS razing only enemy bases it can ACTUALLY crack (monotonic march -> never
        # ping-pongs) and withdraws-to-watch otherwise, instead of v1's chip-and-retreat. During a
        # FORMING wave (mil_switch) it holds the matched garrison home and commits only the EXCESS, so
        # going on offense never under-defends our HQ; with no wave it commits the whole surplus.
        # home_safe-gated so it never marches out into a committed wave (that loses winnable games).
        BOT.raiding = False
        if BOT.threat_army > 0:
            # a CONCENTRATED wave is forming -> hold the matched garrison home and commit only the
            # EXCESS to the backdoor (so attacking never under-defends our HQ vs the building wave).
            # Keyed on threat_army (a real massed stack), NOT mil_switch: a turtle that merely
            # out-PRODUCES us with spread units (threat_total) is no imminent threat -- against that we
            # commit a FULL fist and raze, instead of cowering behind a huge idle garrison.
            harass_budget = max(0, len(my_warriors) - target_garrison)
            harass_budget = min(len(raid_force), max(harass_budget, min(HARASS_CAP, len(raid_force))))
            fist = sorted(raid_force, key=lambda w: w.id.num)[:harass_budget]
            fist_ids = {w.id for w in fist}
            for w in raid_force:
                if w.id not in fist_ids and w.region != M.my_hq:
                    order_move(w, M.my_hq)
            if fist:
                _raid_commit(S, M, nav, fist, live, order_move, my_building_regions, turn, climb_pending=_climb_pending)
            else:
                BOT.raid_tgt = -1; BOT.raid_lock = 0
        elif _hq_assault:
            # OVERWHELMING: throw the whole surplus at the enemy HQ to end it (guaranteed crackable above).
            BOT.raid_tgt = -1; BOT.raid_lock = 0
            for w in raid_force:
                if w.region != M.opp_hq:
                    order_move(w, M.opp_hq)
        else:
            _raid_commit(S, M, nav, raid_force, live, order_move, my_building_regions, turn, climb_pending=_climb_pending)
    else:
        BOT.raid_tgt = -1; BOT.raid_lock = 0     # wave committed / nothing to attack -> muster & defend
        for w in raid_force:                     # muster at home / recall to defend
            if w.region != M.my_hq:
                order_move(w, M.my_hq)

    # ======================================================================
    # 3) TRAIN  (referee processes last; <= HQ train_cap, buffered)
    # ======================================================================
    if hq is not None:
        cap = _train_cap(hq)
        # target army = economy+defense need (+1 spare to fund expansion / chip)
        want_spare = 1 if (turn < ECON_PAYBACK_CUTOFF and
                           any(s not in handled_targets and s not in _skip_build for s in BOT.claim_order)) else 0
        if turn >= ASSAULT_START:
            want_spare = max(want_spare, 2)
        # Land-taking army funding (conditional): once the economy is ESTABLISHED
        # (HQ >= lvl3 and >= 2 bases) and home is safe, convert gold ABOVE the
        # reserve + the next HQ-upgrade cost into the raid army. Reserving the next
        # HQ upgrade means the HQ keeps climbing to 30 (no tiebreak regression),
        # while the EXCESS funds proactive enemy-base denial much earlier than
        # waiting for a fully-maxed HQ.
        # TERRITORY (build, don't hoard): when the enemy out-BUILDS us, the answer is
        # to BUILD more bases ourselves -- NOT to stockpile a home army. Fund extra
        # claimer bodies (capped at MAX_CLAIMERS) so several strongholds are claimed in
        # parallel; each claimer becomes a base + work slot, which is how the territory
        # gap actually closes.
        #   The previous version trained a static raid army here whenever `behind`.
        #   Against an early expander that made us "behind" by ~turn 7, so every worker
        #   we trained piled idle at the HQ (HQ work_cap is 1 -> the extras earn nothing
        #   but cost 2 upkeep each), the gold never recovered to the 300 needed for a
        #   2nd base, and we stayed locked at ONE base for the whole game while the enemy
        #   built 6-10. Expansion -- not a home army -- is the principle-aligned response
        #   to a territory deficit (the user's "net land" rule: keep BUILDING).
        unclaimed_now = sum(1 for s in BOT.claim_order if s not in handled_targets and s not in _skip_build)
        if unclaimed_now > 0 and on_hq == 0:
            want_spare = max(want_spare, min(2 if behind else 1, unclaimed_now))
        # STUCK-BEHIND early offense: the enemy out-bases us and we have NO stronghold left to
        # claim, so banking only for the L5 climb just watches the gap snowball into an
        # unbeatable wave. Train a small raid quota NOW (pre-L5) and send it to take enemy land
        # -- early denial is the only counter (the user: late territory-taking is meaningless).
        # These bodies do NOT pile idle (the old death-spiral): the raid commit threshold is
        # MIN_RAID when stuck_behind, so they march out and siege the enemy's nearest bases.
        if stuck_behind and on_hq == 0 and hq.level >= 2:
            want_spare = max(want_spare, HARASS_QUOTA)
        if losing and on_hq == 0 and hq.level >= 2:
            want_spare = max(want_spare, COUNTER_QUOTA)   # accumulate a real counter-stack
        # Otherwise (ahead in territory): only spend surplus on raiding ONCE THE HQ IS A
        # MAXED FORTRESS (L5 / 30hp). Reaching L5 is the day-200 tiebreak: a strong
        # opponent ALWAYS maxes its HQ, so an HQ stuck at L4 (25hp) auto-loses the
        # tiebreak even when we survive the wave -- this was the exact loss in logs 7/8
        # (we held to turn 200 but our HQ stalled one upgrade short while theirs maxed).
        # So before L5 we bank EVERY surplus piece toward the climb (the 1c upgrade) and
        # fund ZERO offensive chip-raiders; only the TRUE post-L5 surplus arms for offense.
        econ_ready = (_is_max(hq) and len(my_bases) >= 2)
        if econ_ready and on_hq == 0:
            free_gold = (S.gold - spent) - reserve
            if free_gold > 0:
                want_spare = max(want_spare, min(ASSAULT_CAP, free_gold // TRAIN_COST))
        # HQ-LEAD CRUSH: ahead by >= HQ_CRUSH_GAP levels from HQ_CRUSH_TURN -> pour the free gold into a
        # big army (same burst as post-L5 econ_ready, but unlocked by the LEAD even before our own L5) so
        # the surplus routes through the backdoor and grinds the enemy's bases -- starving the gold it
        # needs to upgrade its HQ and close the tiebreak gap. The climb reserve (hq_reserve below) is still
        # honoured first, so our own HQ keeps maxing in parallel; not while fortressing (survival first).
        hq_crush = (bool(HQ_CRUSH) and turn >= HQ_CRUSH_TURN and hq is not None
                    and (hq.level - _ehl0) >= HQ_CRUSH_GAP and on_hq == 0 and not _fortress)
        if hq_crush:
            free_gold = (S.gold - spent) - reserve
            if free_gold > 0:
                want_spare = max(want_spare, min(ASSAULT_CAP, free_gold // TRAIN_COST))
        # 승기 PUSH (the user's "승기를 잡으면 계속 병사를 찍어서 밀어붙이자"): once we hold a DECISIVE economy
        # lead (>= WIN_BASE_LEAD more bases) with home safe, mid-game, and NOT trailing the HQ tiebreak, we
        # have seized the advantage -- so do NOT coast to a draw banking for the climb. Pour the free gold
        # into ARMY (same burst as the post-L5 econ_ready, unlocked early by the LEAD) so the single fist
        # keeps razing the enemy's economy and we convert the lead. Reserve-protected: the hq_reserve below
        # still funds the next L5 step first, so the HQ maxes in parallel (no tiebreak regression). The
        # decisive-lead bar keeps the SYMMETRIC mirror -- never a multi-base lead -- from tripping it.
        _winning = (bool(WINNING) and home_safe and turn >= PRESSURE_TURN
                    and hq is not None and not _behind_hq and not _fortress
                    and len(enemy_base_regs) >= WIN_ENEMY_BASES
                    and (len(my_bases) - len(enemy_base_regs)) >= WIN_BASE_LEAD)
        if _winning:
            free_gold = (S.gold - spent) - reserve
            if free_gold > 0:
                want_spare = max(want_spare, min(ASSAULT_CAP, free_gold // TRAIN_COST))
        if FUND_GATE == 2:
            _fund_ok = (on_hq == 0) and (_attack_now or (hq is not None and _is_max(hq)))
        elif FUND_GATE == 1:
            _fund_ok = _attack_now
        else:
            _fund_ok = bool(PROTO_ATTACK) and on_hq == 0
        if _fund_ok and hq is not None and hq.level >= ATTACK_MIN_HQ:
            want_spare = max(want_spare, BURST_MIN)
        # PROACTIVE MID-GAME PRESSURE (the user's rule: widen the gap BEFORE the
        # last-resort doomstack). From PRESSURE_TURN, once the HQ is a working economy,
        # fund a real raiding force so the surplus actively DENIES the enemy's bases
        # (capturing them swings income both ways = the gap widens) instead of sitting
        # home banking for L5. _harass_now routes it through the evasive two-front raid;
        # fortress (late) recalls it to turtle the tiebreak, so this is the MID game only.
        # ...and NOT while our HQ trails the enemy's level (_behind_hq): losing the day-200 tiebreak by HQ
        # LEVEL is the worst outcome (real game-8 loss: we over-trained raiders, razed almost nothing, and
        # stalled at L3 while the enemy reached L4). When behind, bank every surplus piece into CATCHING UP
        # the HQ climb instead of funding raiders that achieve little.
        if (bool(PRESSURE) and _harass_now and turn >= PRESSURE_TURN and not _fortress and not _behind_hq
                and hq is not None and hq.level >= PRESSURE_HQLEVEL):
            want_spare = max(want_spare, PRESSURE_FORCE)
        # CRACK BACKDOOR funding: fund a real fist (>= CRACK_FORCE) so the backdoor commits a force
        # that can actually RAZE, not a 6-unit chip squad that fizzles. A PRE-COMMIT ramp (while the
        # active gate is open) reaches commit size before the first commit; a lock-keyed COMMIT-
        # DURATION floor stops the trained surplus evaporating mid-march when the econ/attack flags
        # flicker. Both ride want_spare (TRUE surplus on top of total_need) and are still trimmed by
        # the affordability loop below, so they never starve the inviolable L5-climb reserve.
        # EARLY-RAID funding (continuous from EARLY_RAID_TURN, BEFORE the mid-game PRESSURE/CRACK ramps):
        # a small fist so the opening is aggressive -- but ONLY while we hold a base lead (_econ_lead), so
        # the gold spent is a true surplus the L5 climb does not need. Without that cushion the diversion
        # costs us the climb and the tiebreak (a symmetric mirror must stay a draw, not become a loss).
        # No HQ-level gate (we WANT to raid pre-L3); rides want_spare so it's TRUE surplus (never a worker).
        if (bool(EARLY_RAID) and _econ_lead and _harass_now and not _fortress
                and EARLY_RAID_TURN <= turn < PRESSURE_TURN):
            want_spare = max(want_spare, EARLY_RAID_FORCE)
        if _harass_now and turn >= PRESSURE_TURN and not _fortress and not _behind_hq:
            want_spare = max(want_spare, CRACK_FORCE)
        if BOT.raid_lock > 0 and on_hq == 0 and hq.level >= HARASS_HQLEVEL and not _behind_hq:
            want_spare = max(want_spare, CRACK_FORCE)
        target_army = total_need + want_spare
        hq_reserve = 0
        if mil_switch:
            # MASS TO MATCH the wave/total: train up to the garrison target + base workers,
            # UNCAPPED by our current count so we grow toward it (cap/turn). target_garrison
            # already reflects max(matched-total, matched-stack).
            base_need = total_need - need[M.my_hq]
            _mcap = max(MOBILIZE_CAP, MATCH_TOTAL_CAP)
            # When we TRAIL the enemy's HQ level, cap the FORMING-phase ramp at ~parity so the freed gold
            # banks the catch-up upgrade instead of an over-built garrison (g7/g8 root cause). A COMMITTED
            # wave still fills via the concentrate-driven defenders_needed (total_need), which is untouched.
            _gtgt = (target_garrison if not _behind_hq
                     else min(target_garrison, len(enemy_warriors) + BEHIND_GARRISON_SLACK))
            target_army = max(target_army, min(_mcap + base_need,
                                               _gtgt + base_need))
            # FORTRESS-FIRST while the wave is only FORMING (not yet committed): reserve the
            # next HQ upgrade so we keep climbing to L5 (the tiebreak + best defense) AND match
            # in army -- this is what keeps the parked-army / turtle cases reaching L5. Once the
            # wave COMMITS (concentrate), drop the reserve and pour everything into bodies:
            # surviving the imminent hit is all that matters, and reserving it then just
            # PARALYSES training on a poor map (army stuck while the wave lands -> HQ cracked).
            # Keep banking the next upgrade through a non-on_hq concentrate when BEHIND on HQ level (catch
            # up the tiebreak); only an enemy standing ON node 0 (on_hq>0) drops it for raw survival.
            if (hq is not None and not _is_max(hq)
                    and (not concentrate or (_behind_hq and on_hq == 0))
                    and not (losing and COUNTER_DROP)):
                hq_reserve = _next_cost(hq)
        if ((turn >= LATE_CLIMB or _hq_climb_window) and hq is not None
                and not _is_max(hq) and (not concentrate or (_behind_hq and on_hq == 0))):
            hq_reserve = max(hq_reserve, _next_cost(hq))
        deficit = target_army - len(my_warriors)
        n = max(0, min(cap, deficit))
        # WORKERS FIRST: the warriors filling the economy/garrison need WORK and pay for
        # themselves (+13/turn net), so the HQ-climb reserve must NEVER freeze them -- starving
        # workers starves the income that funds the climb itself, the exact self-defeating stall
        # that froze a poor compact map at 6 warriors (banked 3600g for L5 while income stayed
        # ~90g/turn -> never climbed, never massed). The reserve only gates the OFFENSIVE surplus
        # BEYOND the worker/garrison need; workers are funded down to the base reserve.
        worker_deficit = max(0, min(cap, total_need - len(my_warriors)))
        # 승기 PUSH (the user's "승기를 잡으면 계속 병사를 찍어서 밀어붙이자"): the decisive-lead draws stall here --
        # while ahead we bank the next HQ upgrade (hq_reserve) and that FREEZES army training to ZERO for
        # 40+ turns (verified trace: win=True, deficit=10+, yet n=0 t80-120 banking L3->L5), so the army
        # never grows to break the enemy and we coast to a tiebreak draw. When we hold the decisive lead,
        # the climb reserve must NOT freeze the army: drop it so the surplus pours into bodies, and let the
        # HQ keep climbing OPPORTUNISTICALLY (the 1c upgrade still fires whenever gold allows). This is safe
        # by construction -- _winning requires NOT _behind_hq (our HQ already >= the enemy's) and NOT
        # _fortress, so if the enemy ever out-climbs us _winning drops and the reserve is restored; the L5
        # tiebreak backstop (LATE_BACKSTOP / fortress) is untouched. Workers are always funded first.
        # ...but only MID-game: from LATE_BACKSTOP on, restore the reserve and SECURE the L5 climb (the
        # endgame tiebreak insurance). The mid-game army push (60..150) is what breaks the enemy; if it
        # has not won by then, the last 50 turns bank L5 so the worst case is a tiebreak DRAW, never a loss
        # (the symmetric mirror finishing a hair behind on the climb was the only downside of the drop).
        _train_reserve = 0 if (_winning and turn < LATE_BACKSTOP) else hq_reserve
        while n > 0 and not can(TRAIN_COST * n + (_train_reserve if n > worker_deficit else 0)):
            n -= 1
        # WAVE RESPONSE -- match the enemy's churn. The fortress-first reserve above banks the
        # next HQ upgrade, but on a POOR COMPACT map gold can't cover both that reserve AND a
        # 120g warrior, so training freezes to ZERO while the enemy keeps massing -> we detect
        # the wave but produce no defenders and our HQ is cracked (AI#3 / log3: we sat at 7
        # warriors from turn 48 while the enemy churned 13). So: if a wave is forming and we are
        # UNDER-MASSED (army below the matched garrison), never let the reserve freeze training --
        # drop it and train every body we can afford. The user's rule: when the enemy keeps
        # churning out soldiers, we churn ours out to match. (We resume banking for the climb
        # once the wave is repelled and the threat clears -> threat_army resets.)
        # ...but when we TRAIL the enemy's HQ level, only a CLOSING stack (within CONCENTRATE_DIST, or
        # already on node 0) may steal the catch-up gold; a stack still massing FAR must not re-route the
        # banked upgrade into a forming-phase garrison (that is exactly what kept g7/g8 stalled at L3).
        if (n == 0 and hq_reserve > 0
                and len(my_warriors) < target_garrison
                and (not _behind_hq or on_hq > 0 or stack_dist <= CONCENTRATE_DIST)
                and ((BOT.threat_army > 0 and stack_dist <= gate)
                     or (MATCH_EAGER and BOT.threat_total > 0))):
            # ...but ONLY once the wave's stack is actually APPROACHING our HQ (within the
            # detection gate). While the enemy is still massing FAR at its own HQ (stack_dist =
            # ~diameter) we have time, so we keep banking for the L5 climb. The instant the wave
            # starts marching in (stack_dist drops into the gate), survival outranks the climb ->
            # train. This fires for AI#3's early rush (it marches in ~turn 66) but NOT for a
            # late econ-swarmer whose army masses far and arrives only after we have reached L5.
            n = max(0, min(cap, deficit))
            while n > 0 and not can(TRAIN_COST * n):
                n -= 1
        a.train_n = n

    if DEBUG and turn % 25 == 0:
        print(f"# t{turn} gold={S.gold} spent={spent} w={len(my_warriors)} "
              f"bld={len(my_buildings)} need={total_need} hqL={hq.level if hq else 0} "
              f"thr={threat} up={a.upgrades} tr={a.train_n} mv={len(a.moves)}",
              file=sys.stderr, flush=True)



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


def _two_front_raid(S, M, nav, raid_force, enemy_base_regs, order_move):
    """Two-front "backdoor" offense: split the raid army into a TOP and BOTTOM prong along the
    my_hq->opp_hq axis and strike the enemy's land on both flanks. A prong that meets a LARGER
    enemy force at its target DISENGAGES and reroutes to reinforce the other (open) flank --
    "hit where they ain't". Each prong advances as a CONCENTRATED stack (the verified combat
    math rewards concentration); per-warrior moves give the organic split/regroup control.
    This only chooses MOVE targets for the already-committed raid_force; it never touches the
    home guard, the L5 climb, or the wave mobilization, so defense is unchanged."""
    enemy_warriors = [w for w in S.warriors if w.id.side is not M.my_side]

    # Flank of a region = which side of the my_hq->opp_hq axis it lies on (signed cross product).
    ax = M.x[M.opp_hq] - M.x[M.my_hq]
    ay = M.y[M.opp_hq] - M.y[M.my_hq]

    def flank(r: int) -> int:
        cross = ax * (M.y[r] - M.y[M.my_hq]) - ay * (M.x[r] - M.x[M.my_hq])
        return 1 if cross >= 0 else -1

    # Per-flank target = the enemy BASE on that flank nearest our HQ (land denial first), else
    # the enemy HQ. Both prongs converge on the enemy HQ once its flank's bases are gone.
    ebases = sorted(enemy_base_regs, key=lambda r: nav.hops(M.my_hq, r))

    def flank_target(fl: int) -> int:
        for r in ebases:
            if flank(r) == fl and S.find_building(r) is not None:
                return r
        return M.opp_hq

    t_pos = flank_target(1)
    t_neg = flank_target(-1)

    def enemy_def_near(tgt: int) -> int:
        return sum(1 for w in enemy_warriors if nav.hops(w.region, tgt) <= DEF_RADIUS)

    d_pos = enemy_def_near(t_pos)
    d_neg = enemy_def_near(t_neg)

    n = len(raid_force)
    # Stable id-ordered split: the raiders all START on node 0 (same flank), so we cannot
    # assign by current position -- we split the force itself in half by warrior id (stable
    # across turns as they advance toward their separate flank targets).
    rf = sorted(raid_force, key=lambda w: w.id.num)
    # Default: half the force to each flank (two simultaneous prongs force the enemy to divide
    # their defenders). Small force OR a single shared target -> one concentrated stack.
    if n >= TWO_FRONT_MIN and t_pos != t_neg:
        half = n // 2
        pos_grp = rf[:half]
        neg_grp = rf[half:]
        # BACKDOOR: a prong OUTNUMBERED at its target disengages and folds into the other flank
        # (concentrate on the open side). Also fold a prong below PRONG_MIN (a half-stack cracks
        # nothing -- better one real stack than two impotent ones).
        pos_out = d_pos >= len(pos_grp) or len(pos_grp) < PRONG_MIN
        neg_out = d_neg >= len(neg_grp) or len(neg_grp) < PRONG_MIN
        if pos_out and not neg_out:
            neg_grp = rf; pos_grp = []
        elif neg_out and not pos_out:
            pos_grp = rf; neg_grp = []
        elif pos_out and neg_out:
            # both contested -> mass the WHOLE force on the LESS-defended flank (true backdoor)
            if d_pos <= d_neg:
                pos_grp = rf; neg_grp = []
            else:
                neg_grp = rf; pos_grp = []
        prongs = [(pos_grp, t_pos), (neg_grp, t_neg)]
    else:
        # one concentrated stack at the LESS-defended flank target (backdoor)
        tgt = t_pos if d_pos <= d_neg else t_neg
        prongs = [(rf, tgt)]

    for grp, target in prongs:
        if not grp:
            continue
        # advance the prong as a stack: gather on its most-advanced node, then step toward target
        stack = Counter(w.region for w in grp).most_common(1)[0][0]
        at_stack = [w for w in grp if w.region == stack]
        if stack != target and len(at_stack) >= max(MIN_RAID, int(0.6 * len(grp))):
            nh = nav.next_hop(stack, target)
            if nh >= 0:
                for w in at_stack:
                    order_move(w, nh)            # the massed front advances one hop together
        for w in grp:                            # stragglers regroup onto the front
            if w.region != stack:
                order_move(w, stack)


# ----------------------------------------------------------------------------
# Crack-aware committed backdoor — referee-exact toolkit (validated 1:1 vs the
# referee's apply_day_combat / apply_day_siege). These are pure helpers; all the
# offense control flow lives in _raid_commit, the SINGLE owner of the raid branch.
# ----------------------------------------------------------------------------
def _sim_crack(atk_hps, base_hp, turret, def_hps, max_turns):
    """REFEREE-EXACT siege simulation. Attackers (list of hp) vs a building (base_hp, turret)
    defended by def_hps. Each turn the attack COUNTS are fixed at the start; our overflow beyond
    the defenders' HP sieges the building; their (defenders + turret) attacks kill our lowest-HP
    units. Returns (cracked, turns, survivors)."""
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


def _can_crack(S, M, nav, grp, target, max_turns):
    """Can `grp` (our warriors) actually DESTROY the building at `target` before being wiped?
    Referee-exact. True if there is no building there (nothing to crack). Counts as defenders not only
    the units STANDING ON the target but every enemy within REINFORCE_DIST hops -- they converge during
    the multi-turn siege, so a base next to a defended HQ reads uncrackable (no suicide) while one next
    to a passive/empty HQ stays crackable (keep pressing an enemy that does not intercept)."""
    b = S.find_building(target)
    if b is None:
        return True
    turret = (HQ_LEVELS if b.type is BType.HQ else BASE_LEVELS)[b.level].turret
    me = M.my_side
    # CONVERGENCE-AWARE local reinforce distance. For a base inside the enemy HQ cluster (within
    # HQ_CLUSTER_DIST hops of opp_hq), the HQ garrison that converges during the siege stands UP TO that
    # many hops from the target -- REINFORCE_DIST=1 would miss it and mis-read the base as crackable. Widen
    # the radius to reach the HQ body (local_rd = max(REINFORCE_DIST, hops(target->opp_hq))) so every body
    # that can converge is counted -> the cluster reads UNCRACKABLE and we stop grinding the HQ's doorstep.
    # FORWARD bases keep REINFORCE_DIST=1: aggressive forward razing (the turtle/mirror wins) is untouched.
    hq_hops = nav.hops(target, M.opp_hq)
    is_cluster = hq_hops <= HQ_CLUSTER_DIST
    local_rd = max(REINFORCE_DIST, hq_hops) if is_cluster else REINFORCE_DIST
    defs = [w.hp for w in S.warriors
            if w.id.side is not me and w.hp > 0 and nav.hops(w.region, target) <= local_rd]
    cracked, _t, survivors = _sim_crack([w.hp for w in grp], b.hp, turret, defs, max_turns)
    if cracked and is_cluster and b.type is not BType.HQ:
        # PRECISE-COMBAT gate: near the enemy HQ the count-based siege can still read crackable, but the
        # turret + steady reinforcement bleed the fist. Only commit if the crack is a FAVORABLE trade --
        # we keep at least CLUSTER_KEEP_F of the fist alive. Otherwise skip (raze forward + climb), so we
        # stop trading the whole army for one doorstep base (the g6/7/8 "무리하게 HQ 공격하다 병력 잃음").
        return survivors >= max(1, int(CLUSTER_KEEP_F * len(grp) + 0.999))
    return cracked


def _pick_target(S, M, nav, force, live, max_turns, frm):
    """Best LIVE enemy base for this fist to raze next, and actually crackable; else -1. Ordered by a
    single balanced key = hops(fist -> base) - hops(base -> enemy HQ): LOW = both NEAR our fist (short,
    safe march) and FAR from the enemy HQ (the enemy's exposed FORWARD bases, which it cannot quickly
    relieve from its home core -- and which keeps the fist away from the turreted HQ). So the roam
    picks off the enemy's forward economy first and works the edge, instead of diving at the HQ."""
    for r in sorted(live, key=lambda r: nav.hops(frm, r) - nav.hops(r, M.opp_hq)):
        if _can_crack(S, M, nav, force, r, max_turns):
            return r
    return -1


def _raid_advance(M, nav, force, target, order_move):
    """MONOTONIC march: every unit steps exactly one hop toward `target`, so its distance to the
    target strictly DECREASES each turn -> it can NEVER oscillate (the documented 0<->adjacent
    ping-pong came from a 'regroup onto the most-common node' rule). Units on the target hold & siege."""
    for w in force:
        if w.region == target:
            continue
        nh = nav.next_hop(w.region, target)
        order_move(w, nh if nh >= 0 else target)


def _withdraw(M, nav, force, friendly_regions, order_move, forward=False, home_recall=False):
    """Disengage: each unit makes a one-way march to a friendly building, to watch and re-engage on
    opportunity. Monotone -> the disengage path itself cannot oscillate. home_recall=True drives the whole
    fist back to NODE 0 (and it then sits at 0g) so a pending HQ climb is not bled by per-turn roam moves
    (the g8 coast: ineffective roaming at 10g/unit/turn starved the L2->L5 climb). forward=True stages the
    fist at our FRONTIER base to keep pressure on a turtle; forward=False sends each unit to its NEAREST
    friendly building."""
    home = M.my_hq
    fr = sorted(friendly_regions)
    fwd = min(fr, key=lambda f: nav.hops(f, M.opp_hq)) if fr else home
    for w in force:
        if home_recall:
            d = home
        elif forward:
            d = fwd
        else:
            d = min(fr, key=lambda f: nav.hops(w.region, f)) if fr else home
        if w.region != d:
            order_move(w, d)


def _raid_commit(S, M, nav, force, live, order_move, friendly_regions, turn, climb_pending=False):
    """SINGLE owner of the offense move branch: a crack-aware backdoor WITH COMMITMENT. Commit to ONE
    crackable enemy building and march the whole fist there (monotonic) until it falls or the lock
    expires -- target commitment is what kills the per-turn re-pick oscillation. Nothing crackable ->
    WITHDRAW to the nearest friendly base and watch for a short spell. A base locked the FULL spell
    without razing (enemy reinforces/heals faster than we chip) is BLACKLISTED so we stop bleeding on
    a wall and roam to a different target instead of re-locking it.
    climb_pending=True (HQ still climbing to L5, home safe): when there is nothing crackable, recall the
    fist HOME and sit (0g) rather than roam/forward-stage -- a defended enemy that offers no crackable base
    is not worth bleeding 10g/unit/turn on while the HQ climb (the win condition) goes unfunded (g8). When a
    base IS crackable we still commit (effective razing denies the enemy -- the turtle wins are preserved)."""
    if not force:
        return
    enemy = [w for w in S.warriors if w.id.side is not M.my_side]
    live_set = set(live)
    frm = Counter(w.region for w in force).most_common(1)[0][0]
    # EVASION (the user's rule): the backdoor WATCHES the enemy. If a CONCENTRATED enemy stack big
    # enough to STOP it (a single mobile relief group >= our fist size) has closed within FLEE_RADIUS,
    # do NOT trade the backdoor away -- release the target and FLEE to the nearest friendly base, then
    # watch for an opening. We key off the LARGEST single stack, not the total count: a turtle's
    # scattered 2-worker base garrisons must NOT scare us off (we raze those base-by-base, the per-base
    # defense is already handled by _can_crack) -- only a real massed relief column makes us run.
    _near = Counter(w.region for w in enemy if nav.hops(w.region, frm) <= FLEE_RADIUS)
    # The single-largest-stack test is precise for FORWARD razing (a turtle's scattered 2-worker base
    # garrisons must not scare us off). But INSIDE the enemy HQ cluster the converging HQ garrison arrives
    # in PIECES from several adjacent tiles -- it is never one pre-formed stack, so the single-stack test
    # under-reads it and the fist lingers taking papercut turret/garrison damage (k7/k8: 28+ dmg taken, 0
    # dealt). When the fist is parked in the cluster, flee on the TOTAL convergeable enemy near it, not just
    # the largest single stack -- so we disengage the HQ's doorstep instead of grinding it.
    _fist_in_cluster = nav.hops(frm, M.opp_hq) <= HQ_CLUSTER_DIST
    _stop = sum(_near.values()) if _fist_in_cluster else (max(_near.values()) if _near else 0)
    # PRESS-THROUGH (the user's precise per-turn attack/evade -- "기지에 아무도 없는데 빼지 마라"): a nearby
    # enemy stack should force a flee ONLY if it can actually reach and CONTEST our objective before we
    # finish razing it. If we are committed to a FORWARD base (outside the enemy HQ cluster) that is
    # CRACKABLE now and razes in `tc` siege turns, and the NEAREST enemy unit anywhere is farther than our
    # full march+siege (hops(fist->tgt) + tc), the raze COMPLETES before any reliever can arrive -- an
    # uncontested forward base is free value, so press instead of running from a column that cannot catch
    # us. Honest worst-case (closest enemy of all vs full march+siege) so it never dives a defendable base;
    # cluster-excluded so the HQ-doorstep disengage (k7/k8) is untouched.
    _press = False
    if _stop >= len(force) and BOT.raid_lock > 0 and not _fist_in_cluster:
        _t0 = BOT.raid_tgt
        _b0 = S.find_building(_t0) if _t0 in live_set else None
        if (_b0 is not None and _b0.type is BType.BASE
                and nav.hops(_t0, M.opp_hq) > HQ_CLUSTER_DIST):
            _d0 = [w.hp for w in enemy if nav.hops(w.region, _t0) <= REINFORCE_DIST]
            _ok, _tc, _sv = _sim_crack([w.hp for w in force], _b0.hp,
                                       BASE_LEVELS[_b0.level].turret, _d0, MAX_CRACK_TURNS)
            if _ok:
                _eta = min((nav.hops(w.region, _t0) for w in enemy), default=99)
                if _eta > nav.hops(frm, _t0) + _tc:
                    _press = True
    if _stop >= len(force) and not _press:
        BOT.raid_tgt = -1
        BOT.raid_lock = WATCH_LOCK
        _withdraw(M, nav, force, friendly_regions, order_move)
        return
    tgt = BOT.raid_tgt
    lock = BOT.raid_lock
    if lock > 0 and tgt in live_set and _can_crack(S, M, nav, force, tgt, MAX_CRACK_TURNS):
        BOT.raid_lock = lock - 1                   # committed to a live, still-crackable base -> keep marching
        BOT.no_target_streak = 0                   # we HAVE a crackable target -> razing is working, not futile
        _raid_advance(M, nav, force, tgt, order_move)
        return
    if lock > 0 and tgt < 0:                        # committed WITHDRAW -> sit at a friendly base & watch
        BOT.raid_lock = lock - 1
        _withdraw(M, nav, force, friendly_regions, order_move, home_recall=climb_pending)
        return
    if tgt >= 0 and tgt in live_set:               # lock expired but base STILL ALIVE -> stalled siege
        BOT.raid_skip[tgt] = turn + SKIP_WATCH      # blacklist it so we don't instantly re-lock the wall
    cand = [r for r in live if BOT.raid_skip.get(r, 0) <= turn]
    newt = _pick_target(S, M, nav, force, cand, MAX_CRACK_TURNS, frm)
    if newt < 0:                                   # crack nothing -> commit to a short WATCH at a friendly base
        BOT.raid_tgt = -1
        BOT.raid_lock = WATCH_LOCK
        BOT.no_target_streak += 1
        # Nothing crackable. If razing has been FUTILE for a while (no crackable base for FUTILE_STREAK
        # turns) AND the HQ is still climbing (home safe), recall HOME and bank for the climb -- roaming a
        # fully-defended enemy just bleeds the gold the L5 climb needs (the g8 coast). A turtle, by
        # contrast, gives us a crackable base every few turns (streak resets) so we keep razing it (wins
        # preserved). Otherwise, late-game, stage at the FRONTIER to keep pressure (the g6 rule).
        _recall = climb_pending and BOT.no_target_streak >= FUTILE_STREAK
        _withdraw(M, nav, force, friendly_regions, order_move,
                  forward=(turn >= HARASS_STAGE_TURN and not _recall),
                  home_recall=_recall)
        return
    BOT.raid_tgt = newt
    BOT.raid_lock = CRACK_LOCK
    BOT.no_target_streak = 0                        # found a crackable base -> razing is working, not futile
    _raid_advance(M, nav, force, newt, order_move)


def emit(a: Actions) -> None:
    out: list[str] = ["COMMAND"]
    for wid, target in a.moves:
        out.append(f"MOVE {wid} {target}")
    for r in a.upgrades:
        out.append(f"UPGRADE {r}")
    if a.train_n > 0:
        out.append(f"TRAIN {a.train_n}")
    out.append("END")
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


def main() -> None:
    M, S = parse_init()
    nav = Nav(M)
    nav.warm()
    while (turn := read_turn_start()) is not None:
        a = decide(S, M, nav, turn)
        emit(a)
        read_turn_result(S, M, a)


if __name__ == "__main__":
    main()
