#!/usr/bin/env python3
"""
bot_pusher.py — a controlled HARNESS opponent for MECHANISM testing.

Purpose: send a STEADILY GROWING warrior stack marching at the enemy HQ so we can
watch whether proto's HOME_INTERCEPT fires in time (kills the 3-9 stack while it is
approaching) BEFORE the stack steps on proto's HQ tile and triggers the worker-release
panic (hq_pressure). NOT a real strategy bot -- deliberately simple and predictable.

Behavior:
  - Keep exactly work_cap warriors on its own HQ working (income).
  - Train up to train_cap/turn while gold allows (and army < PUSH_CAP).
  - From turn PUSH_START on, release up to PUSH_RATE OTHER warriors per turn and
    MOVE them toward the ENEMY HQ (M.opp_hq). Already-marching ones auto-continue.

Env knobs:
  PUSH_START (default 30) — turn to begin releasing marchers.
  PUSH_RATE  (default 2)  — max NEW warriors released per turn (controls growth speed).
  PUSH_CAP   (default 40) — stop TRAINING past this army size.

The I/O framework (parse_init/read_turn_start/read_turn_result/emit/main + all
dataclasses/Nav) is copied VERBATIM from bot_climber.py (the verified sample
framework). Only decide() differs.
"""
from __future__ import annotations

import heapq
import math
import os
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
# Fast pathfinding (lazy weighted Dijkstra) — copied verbatim from bot_climber.
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
        self.dist(self.M.my_hq)
        self.dist(self.M.opp_hq)
        for s in self.M.strongholds:
            self.dist(s)


# ----------------------------------------------------------------------------
# PUSHER strategy — the ONLY logic that differs from the framework.
# ----------------------------------------------------------------------------
DEBUG = False


WR = {"claims": None, "tgt": -1}

def decide(S: GameState, M: GameMap, nav: Nav, turn: int) -> Actions:
    a = Actions()
    try:
        _decide_waverush(S, M, nav, turn, a)
    except Exception as e:  # never crash -> never WA
        import traceback, os as _os
        _sink = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_wr_err.txt")
        with open(_sink, "a", encoding="utf-8") as _f:
            _f.write("turn %d: %s\n%s\n" % (turn, e, traceback.format_exc()))
    return a


def _decide_waverush(S: GameState, M: GameMap, nav: Nav, turn: int, a: Actions) -> None:
    """Emulates the 1(45) LEFT high-rank rusher: claim the 2 nearest strongholds,
    train continuously, stage fresh warriors at the forward base, launch waves of
    WR_WAVE (default 5) at the nearest enemy building (bases first, HQ last)."""
    wave_sz = int(os.environ.get("WR_WAVE", "5"))

    me = M.my_side
    my_warriors = [w for w in S.warriors if w.id.side is me]
    hq = S.find_building(M.my_hq)
    my_bld = [b for b in S.buildings if b.side is me]
    my_bld_regions = {b.region for b in my_bld}
    enemy_bld = [b for b in S.buildings if b.side is not me]

    spent = 0

    def afford(cost: int) -> bool:
        return (S.gold - spent - cost) >= 0

    def order_move(w: Warrior, target: int) -> bool:
        nonlocal spent
        if w.state is not WState.STATIONARY:
            return False
        if target == w.region:
            return False
        if not nav.reachable(w.region, target):
            return False
        dest_b = S.find_building(target)
        cost = 0 if (dest_b is not None and dest_b.side is me) else MOVE_COST
        if cost > 0 and not afford(cost):
            return False
        spent += cost
        a.moves.append((w.id, target))
        return True

    # ---- claim plan: the 2 strongholds nearest OUR HQ (tie-break toward the enemy) ----
    if WR["claims"] is None:
        cand = [s for s in M.strongholds
                if s not in (M.my_hq, M.opp_hq) and nav.reachable(M.my_hq, s)
                and nav.hops(M.my_hq, s) <= nav.hops(M.opp_hq, s)]
        cand.sort(key=lambda s: (nav.hops(M.my_hq, s), nav.hops(M.opp_hq, s)))
        WR["claims"] = cand[:2]
    claims = [c for c in WR["claims"] if c not in my_bld_regions]

    # ---- build a base when a warrior stands on an unowned claim target ----
    for c in claims:
        if any(w.region == c and w.state is WState.STATIONARY for w in my_warriors):
            if S.find_building(c) is None and afford(BASE_LEVELS[1].cost):
                spent += BASE_LEVELS[1].cost
                a.upgrades.append(c)

    # ---- role assignment ----
    work_cap = hq.work_cap() if hq is not None else 1
    stationary = [w for w in my_warriors if w.state is WState.STATIONARY]
    keep_ids = set()
    on_hq = [w for w in stationary if w.region == M.my_hq]
    for w in on_hq[:work_cap]:
        keep_ids.add(w.id)                       # HQ income garrison
    for b in my_bld:
        if b.type is BType.BASE:
            on_b = [w for w in stationary if w.region == b.region]
            if on_b:
                keep_ids.add(on_b[0].id)         # 1 worker per base
    # claimers: nearest free warrior per pending claim keeps marching there
    for c in claims:
        free = [w for w in stationary if w.id not in keep_ids]
        if not free:
            break
        cl = min(free, key=lambda w: nav.hops(w.region, c))
        keep_ids.add(cl.id)
        order_move(cl, c)

    # ---- staging base = our base nearest the enemy HQ ----
    bases = [b for b in my_bld if b.type is BType.BASE]
    stage = (min(bases, key=lambda b: nav.hops(b.region, M.opp_hq)).region
             if bases else M.my_hq)

    def enemy_target(frm: int) -> int:
        eb = [b for b in enemy_bld if nav.reachable(frm, b.region)]
        if not eb:
            return M.opp_hq
        non_hq = [b for b in eb if b.region != M.opp_hq]
        pool = non_hq if non_hq else eb
        return min(pool, key=lambda b: nav.hops(frm, b.region)).region

    army = [w for w in stationary if w.id not in keep_ids]
    staged = [w for w in army if w.region == stage]
    forward = [w for w in army if w.region not in (stage, M.my_hq)]

    # ---- mid-wave bodies keep grinding at the nearest enemy building ----
    for w in forward:
        order_move(w, enemy_target(w.region))

    # ---- release a full wave from the staging base ----
    if len(staged) >= wave_sz:
        tgt = enemy_target(stage)
        for w in staged:
            order_move(w, tgt)

    # ---- fresh trainees walk to the staging base ----
    for w in army:
        if w.region == M.my_hq and stage != M.my_hq:
            order_move(w, stage)

    # ---- continuous training (reserve base cost while a claim is pending) ----
    reserve = BASE_LEVELS[1].cost if claims else 0
    if hq is not None and turn >= 8:
        cap = HQ_LEVELS[hq.level].train_cap
        n = 0
        while n < cap and afford(TRAIN_COST * (n + 1) + reserve):
            n += 1
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
