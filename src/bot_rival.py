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
THREAT_RANGE = 6
GOLD_FLOOR = 50
ECON_BASES = 3        # small sustain economy
MUSTER = 12           # army size to commit a raid
MIN_RAID = 6          # never advance the stack below this
HQ_TARGET_EARLY = 3   # rush HQ to lvl3 (train_cap 2) early
HOME_GUARD = 5        # warriors kept on the HQ so a backdoor cannot crack it


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
    claim_order: list = field(default_factory=list)
    claim_set: set = field(default_factory=set)
    raiding: bool = False


BOT = Bot()


def _init_bot(M: GameMap, nav: Nav) -> None:
    scored = []
    for s in M.strongholds:
        dm = nav.hops(s, M.my_hq); do = nav.hops(s, M.opp_hq)
        if dm < do:
            scored.append((dm, s))
    scored.sort()
    BOT.claim_order = [s for _, s in scored]
    BOT.claim_set = set(M.strongholds)
    BOT.inited = True


def decide(S: GameState, M: GameMap, nav: Nav, turn: int) -> Actions:
    a = Actions()
    try:
        _decide_impl(S, M, nav, turn, a)
    except Exception as e:
        if DEBUG:
            print(f"# swarm err t{turn}: {e}", file=sys.stderr, flush=True)
    return a


def _decide_impl(S, M, nav, turn, a):
    if not BOT.inited:
        _init_bot(M, nav)
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

    # ---- economy (lightweight sustain) ----
    for w in my:
        if (w.state is WState.STATIONARY and w.region in BOT.claim_set
                and S.find_building(w.region) is None and w.region not in ups
                and w.region not in enemy_at and len(my_bases) < ECON_BASES and turn < 140):
            if can(BASE_LEVELS[1].cost):
                up(w.region, BASE_LEVELS[1].cost)
    if hq and not _is_max(hq) and ulegal(hq.region) and hq.region not in ups:
        tgt = HQ_TARGET_EARLY if turn < 120 else HQ_MAX_LEVEL
        if hq.level < tgt:
            c = _next_cost(hq)
            if S.gold - spent >= c + reserve + 200 and can(c):
                up(hq.region, c)
    if hq and hq.hp < hq.current_hp() and ulegal(hq.region) and hq.region not in ups:
        c = _next_cost(hq)
        if can(c):
            up(hq.region, c)

    # ---- target hitlist: enemy bases (nearest to my HQ first), then enemy HQ ----
    ebases = sorted([b.region for b in S.buildings if b.side is not me and b.type is BType.BASE],
                    key=lambda r: nav.hops(M.my_hq, r))
    hit = ebases + [M.opp_hq]
    target = next((r for r in hit if S.find_building(r) is not None), M.opp_hq)

    # ---- split workers vs army ----
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
    army_all = [w for w in stat if w.id not in workers]
    army_sorted = sorted(army_all, key=lambda w: w.id.num)
    guard = army_sorted[:min(len(army_sorted), HOME_GUARD)]
    army = army_sorted[min(len(army_sorted), HOME_GUARD):]

    assigned = set()

    def mv(w, t):
        nonlocal spent
        if w.id in assigned or w.state is not WState.STATIONARY or t == w.region:
            return
        if not nav.reachable(w.region, t):
            return
        b = S.find_building(t)
        c = 0 if (b and b.side is me) else MOVE_COST
        if c and not can(c):
            return
        spent += c; a.moves.append((w.id, t)); assigned.add(w.id)

    # ---- home guard holds the HQ (defends the backdoor) ----
    for w in guard:
        if w.region != M.my_hq:
            mv(w, M.my_hq)

    # ---- raid state machine ----
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
                    mv(w, stack)              # stragglers converge; front sieges (holds)
        elif together:
            nh = nav.next_hop(stack, target)
            if nh >= 0:
                for w in at_stack:
                    mv(w, nh)                 # whole stack advances one hop together
            for w in army:
                if w.region != stack:
                    mv(w, stack)
        else:
            for w in army:
                if w.region != stack:
                    mv(w, stack)              # regroup
    else:
        for w in army:
            if w.region != M.my_hq:
                mv(w, M.my_hq)                # muster at home

    # ---- train continuously to grow the army ----
    if hq:
        cap = _train_cap(hq)
        n = cap
        while n > 0 and not can(TRAIN_COST * n):
            n -= 1
        a.train_n = n


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
