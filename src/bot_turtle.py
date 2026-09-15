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
from collections import defaultdict
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


def _max_level(b: Building) -> int:
    return HQ_MAX_LEVEL if b.type is BType.HQ else BASE_MAX_LEVEL


def _is_max(b: Building) -> bool:
    return b.level >= _max_level(b)


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


BOT = Bot()


def _init_bot(M: GameMap, nav: Nav) -> None:
    # Strongholds on my half: closer (in hops) to my HQ than to the enemy HQ.
    scored = []
    for s in M.strongholds:
        dm = nav.hops(s, M.my_hq)
        do = nav.hops(s, M.opp_hq)
        if dm < do:                       # strictly on my side
            scored.append((dm, s))
    scored.sort()
    BOT.claim_order = [s for _, s in scored]
    BOT.claim_set = set(M.strongholds)
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

    enemy_at: set[int] = {w.region for w in enemy_warriors}
    my_present: set[int] = {w.region for w in my_warriors}  # regions with a live friendly

    # --- threat & defender requirement -------------------------------------
    threat = sum(1 for w in enemy_warriors if nav.hops(w.region, M.my_hq) <= THREAT_RANGE)
    on_hq = sum(1 for w in enemy_warriors if w.region == M.my_hq)
    defenders_needed = 1
    if threat > 0:
        defenders_needed = min(len(my_warriors), threat + 1)
    if on_hq > 0:
        defenders_needed = min(len(my_warriors), max(defenders_needed, on_hq + 2))

    # --- per-building garrison need -----------------------------------------
    need: dict[int, int] = {}
    for b in my_buildings:
        c = b.work_cap()
        if b.region == M.my_hq:
            c = max(c, defenders_needed)
        need[b.region] = c
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
                and r not in upgraded_regions
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
        # levels 1->3 are economic; 3->5 are bought for tiebreak HP when rich.
        want = False
        if hq.level < 3:
            want = econ_ok
        else:
            # fortress upgrades: only when comfortably rich and game is maturing
            want = (turn >= 40) and (S.gold - spent) >= (cost + reserve + 400)
        if want and can(cost):
            plan_upgrade(hq.region, cost)

    # 1d) Base work-slot upgrades when economy supports and payback is positive.
    for b in sorted(my_bases, key=lambda bb: bb.region):
        if b.region in upgraded_regions or _is_max(b) or not upgrade_legal(b.region):
            continue
        cost = _next_cost(b)
        payback = cost / WORK_INCOME
        if turn + payback <= MAX_TURN and (S.gold - spent) >= (cost + reserve + 200):
            if can(cost):
                plan_upgrade(b.region, cost)

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
        elif r in BOT.claim_set and S.find_building(r) is None and r not in enemy_at:
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
    if turn < ECON_PAYBACK_CUTOFF:
        for s in BOT.claim_order:
            if s in handled_targets or s in enemy_at:   # don't bounce off a contested tile
                continue
            w = nearest_surplus(s)
            if w is None:
                break
            # only expand if we can foreseeably afford the base (300) soon
            if S.gold - spent >= BASE_LEVELS[1].cost + reserve - 100:
                if order_move(w, s):
                    handled_targets.add(s)
            break  # at most one new claim per turn (throttle expansion)

    # 2c) Assault: send TRUE surplus at the enemy HQ for tiebreak chip damage.
    remaining_surplus = [w for w in surplus if w.id not in assigned]
    assault_ok = (turn >= ASSAULT_START
                  and len(remaining_surplus) >= ASSAULT_MIN_SURPLUS
                  and on_hq == 0)
    if assault_ok:
        for w in remaining_surplus:
            order_move(w, M.opp_hq)
    else:
        # park leftover surplus on the HQ (free) so they at least defend / hold
        for w in remaining_surplus:
            if w.region != M.my_hq:
                order_move(w, M.my_hq)

    # ======================================================================
    # 3) TRAIN  (referee processes last; <= HQ train_cap, buffered)
    # ======================================================================
    if hq is not None:
        cap = _train_cap(hq)
        # target army = economy+defense need (+1 spare to fund expansion / chip)
        want_spare = 1 if (turn < ECON_PAYBACK_CUTOFF and
                           any(s not in handled_targets for s in BOT.claim_order)) else 0
        if turn >= ASSAULT_START:
            want_spare = max(want_spare, 2)
        target_army = total_need + want_spare
        deficit = target_army - len(my_warriors)
        n = max(0, min(cap, deficit))
        while n > 0 and not can(TRAIN_COST * n):
            n -= 1
        a.train_n = n

    if DEBUG and turn % 25 == 0:
        print(f"# t{turn} gold={S.gold} spent={spent} w={len(my_warriors)} "
              f"bld={len(my_buildings)} need={total_need} hqL={hq.level if hq else 0} "
              f"thr={threat} up={a.upgrades} tr={a.train_n} mv={len(a.moves)}",
              file=sys.stderr, flush=True)


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
