#!/usr/bin/env python3
"""
TEST OPPONENT — opening ALL-IN HQ rush (replicates the real-user losses 1(4)/1.txt).
Trains a handful of warriors with zero economy and beelines the enemy HQ as a stack,
arriving ~turn 10-14 to crack an undefended L1 HQ (10hp, turret 1). Pure stress test of
our home-defense; reuses the verified sample I/O + Nav framework from bot_swarm.py.
"""
from __future__ import annotations
import heapq, math, sys
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

MAX_TURN = 200; START_GOLD = 500; START_WARRIORS = 3; MOVE_COST = 10
TRAIN_COST = 120; WORK_INCOME = 15; UPKEEP_PER_WARRIOR = 2
HQ_MAX_LEVEL = 5; BASE_MAX_LEVEL = 3; HQ_HEAL_COST = 1000; BASE_HEAL_COST = 500


class HqLevelEntry(NamedTuple):
    upgrade_cost: int; warrior_hp: int; hp: int; turret: int; train_cap: int; work_cap: int


class BaseLevelEntry(NamedTuple):
    cost: int; hp: int; turret: int; work_cap: int


HQ_LEVELS = (HqLevelEntry(0,0,0,0,0,0), HqLevelEntry(0,4,10,1,1,1), HqLevelEntry(600,5,15,2,1,2),
             HqLevelEntry(1200,6,20,2,2,3), HqLevelEntry(2400,7,25,3,2,4), HqLevelEntry(3600,8,30,3,3,5))
BASE_LEVELS = (BaseLevelEntry(0,0,0,0), BaseLevelEntry(300,6,1,1), BaseLevelEntry(600,12,1,2), BaseLevelEntry(1000,18,2,3))


class Side(Enum):
    LEFT = "A"; RIGHT = "B"
    @property
    def opposite(self): return Side.RIGHT if self is Side.LEFT else Side.LEFT
    @classmethod
    def from_word(cls, w): return cls.LEFT if w == "LEFT" else cls.RIGHT
    @classmethod
    def from_char(cls, c): return cls.LEFT if c == "A" else cls.RIGHT


class BType(Enum): HQ = "HQ"; BASE = "BASE"
class WState(Enum): STATIONARY = 0; MOVING = 1


@dataclass(frozen=True)
class WarriorId:
    side: Side; num: int
    def __str__(self): return f"{self.side.value}{self.num}"
    @classmethod
    def parse(cls, tok): return cls(Side.from_char(tok[0]), int(tok[1:]))


@dataclass
class Warrior:
    id: WarriorId; region: int; hp: int; state: WState = WState.STATIONARY; target: int = 0


@dataclass
class Building:
    region: int; side: Side; type: BType; level: int = 1; hp: int = 10
    def current_hp(self): return HQ_LEVELS[self.level].hp if self.type is BType.HQ else BASE_LEVELS[self.level].hp
    def work_cap(self): return HQ_LEVELS[self.level].work_cap if self.type is BType.HQ else BASE_LEVELS[self.level].work_cap
    def apply_upgrade(self): self.level += 1; self.hp = self.current_hp()
    def upgrade_cost(self):
        return HQ_LEVELS[self.level+1].upgrade_cost if self.type is BType.HQ else BASE_LEVELS[self.level+1].cost


@dataclass
class GameMap:
    N: int = 0; K: int = 0; x: list = field(default_factory=list); y: list = field(default_factory=list)
    strongholds: list = field(default_factory=list); adj: list = field(default_factory=list)
    my_side: Side = Side.LEFT; my_hq: int = 0; opp_hq: int = 0
    def hq_of(self, s): return 0 if s is Side.LEFT else self.N - 1


@dataclass
class GameState:
    gold: int = START_GOLD; my_countdown: int = 5; opp_countdown: int = 5
    warriors: list = field(default_factory=list); buildings: list = field(default_factory=list)
    def find_building(self, region): return next((b for b in self.buildings if b.region == region), None)
    def find_warrior(self, wid): return next((w for w in self.warriors if w.id == wid), None)


@dataclass
class Actions:
    train_n: int = 0; moves: list = field(default_factory=list); upgrades: list = field(default_factory=list)


def make_base(region, s): return Building(region, s, BType.BASE, 1, BASE_LEVELS[1].hp)
def readln():
    line = sys.stdin.readline()
    if not line: sys.exit(0)
    return line.rstrip("\n")
def read_tokens(): return readln().split()


def parse_init():
    M = GameMap()
    t = read_tokens(); assert len(t) >= 2 and t[0] == "READY"; M.my_side = Side.from_word(t[1])
    t = read_tokens(); M.N, M.K = int(t[0]), int(t[1])
    M.x = [int(v) for v in read_tokens()]; M.y = [int(v) for v in read_tokens()]
    M.strongholds = sorted(int(v) for v in read_tokens())
    M.adj = [[] for _ in range(M.N)]
    for r in range(M.N):
        t = read_tokens(); deg = int(t[0]); M.adj[r] = sorted(int(v) for v in t[1:1+deg])
    M.my_hq = M.hq_of(M.my_side); M.opp_hq = M.hq_of(M.my_side.opposite)
    S = GameState(); opp = M.my_side.opposite
    for sfx in range(1, START_WARRIORS + 1):
        S.warriors.append(Warrior(WarriorId(M.my_side, sfx), M.my_hq, HQ_LEVELS[1].warrior_hp))
        S.warriors.append(Warrior(WarriorId(opp, sfx), M.opp_hq, HQ_LEVELS[1].warrior_hp))
    S.buildings.append(Building(0, Side.LEFT, BType.HQ, 1, HQ_LEVELS[1].hp))
    S.buildings.append(Building(M.N - 1, Side.RIGHT, BType.HQ, 1, HQ_LEVELS[1].hp))
    print("OK", flush=True); return M, S


def read_turn_start():
    line = readln()
    if line == "FINISH": return None
    t = line.split(); assert t and t[0] == "START"; return int(t[2])


def read_turn_result(S, M, submitted):
    for region in submitted.upgrades:
        b = S.find_building(region)
        if b is None: S.gold -= BASE_LEVELS[1].cost; S.buildings.append(make_base(region, M.my_side))
        else:
            max_level = HQ_MAX_LEVEL if b.type is BType.HQ else BASE_MAX_LEVEL
            if b.level >= max_level:
                S.gold -= (HQ_HEAL_COST if b.type is BType.HQ else BASE_HEAL_COST); b.hp = b.current_hp()
            else: S.gold -= b.upgrade_cost(); b.apply_upgrade()
    for wid, target in submitted.moves:
        b = S.find_building(target); cost = 0 if (b is not None and b.side is M.my_side) else MOVE_COST
        S.gold -= cost; w = S.find_warrior(wid)
        if w is not None: w.state = WState.MOVING; w.target = target
    S.gold -= TRAIN_COST * submitted.train_n
    line = readln()
    if line == "FINISH": sys.exit(0)
    t = line.split(); assert t and t[0] == "TURN"
    t = read_tokens(); S.my_countdown = int(t[2]); S.opp_countdown = int(t[4])
    t = read_tokens(); n = int(t[1])
    for _ in range(n):
        r = read_tokens(); s = Side.from_char(r[0][0]); region = int(r[1]); b = S.find_building(region)
        if b is None: S.buildings.append(make_base(region, s))
        elif b.side is not M.my_side:
            max_level = HQ_MAX_LEVEL if b.type is BType.HQ else BASE_MAX_LEVEL
            if b.level >= max_level: b.hp = b.current_hp()
            else: b.apply_upgrade()
    t = read_tokens(); n = int(t[1])
    if n > 0:
        ids = read_tokens()
        for i in range(n):
            wid = WarriorId.parse(ids[i]); hq_region = M.hq_of(wid.side); hq_b = S.find_building(hq_region)
            hq_level = hq_b.level if hq_b is not None else 1
            S.warriors.append(Warrior(wid, hq_region, HQ_LEVELS[hq_level].warrior_hp))
    t = read_tokens(); n = int(t[1])
    for _ in range(n):
        r = read_tokens(); wid = WarriorId.parse(r[0]); region = int(r[1]); w = S.find_warrior(wid)
        if w is not None:
            w.region = region
            if wid.side is M.my_side and w.state is WState.MOVING and w.region == w.target:
                w.state = WState.STATIONARY
    t = read_tokens(); n = int(t[1])
    for _ in range(n):
        r = read_tokens(); wid = WarriorId.parse(r[1]); damage = int(r[2]); w = S.find_warrior(wid)
        if w is not None: w.hp -= damage
    S.warriors = [w for w in S.warriors if w.hp > 0]
    t = read_tokens(); n = int(t[1])
    for _ in range(n):
        r = read_tokens(); region = int(r[1]); dmg = int(r[2]); b = S.find_building(region)
        if b is not None: b.hp -= dmg
    S.buildings = [b for b in S.buildings if b.hp > 0]
    readln()
    income = 0
    for b in S.buildings:
        if b.side is not M.my_side: continue
        count = sum(1 for w in S.warriors if w.id.side is M.my_side and w.region == b.region)
        income += WORK_INCOME * min(count, b.work_cap())
    S.gold += income
    alive = sum(1 for w in S.warriors if w.id.side is M.my_side)
    S.gold = max(0, S.gold - UPKEEP_PER_WARRIOR * alive)


class Nav:
    def __init__(self, M):
        self.M = M; self.N = M.N; self._dist = {}; self._next = {}; self._hops = {}
    def _w(self, u, v): return math.ceil(math.hypot(self.M.x[u]-self.M.x[v], self.M.y[u]-self.M.y[v]))
    def dist(self, target):
        d = self._dist.get(target)
        if d is None: d = self._dijkstra(target); self._dist[target] = d
        return d
    def _dijkstra(self, target):
        INF = math.inf; dist = [INF]*self.N; dist[target] = 0.0; pq = [(0.0, target)]
        while pq:
            du, u = heapq.heappop(pq)
            if du > dist[u]: continue
            for v in self.M.adj[u]:
                nd = du + self._w(u, v)
                if nd < dist[v]: dist[v] = nd; heapq.heappush(pq, (nd, v))
        return dist
    def next_hop(self, u, target):
        if u == target: return target
        key = (u, target); nh = self._next.get(key)
        if nh is None:
            d = self.dist(target); best = -1; best_score = math.inf
            for nb in self.M.adj[u]:
                if d[nb] == math.inf: continue
                score = self._w(u, nb) + d[nb]
                if score < best_score: best_score = score; best = nb
            nh = best; self._next[key] = nh
        return nh
    def hops(self, u, target):
        if u == target: return 0
        key = (u, target); h = self._hops.get(key)
        if h is None:
            cur = u; cnt = 0; guard = self.N + 5
            while cur != target and cnt < guard:
                nh = self.next_hop(cur, target)
                if nh < 0: cnt = self.N + 99; break
                cur = nh; cnt += 1
            h = cnt; self._hops[key] = h
        return h
    def reachable(self, u, target): return self.dist(target)[u] != math.inf
    def warm(self):
        self.dist(self.M.my_hq); self.dist(self.M.opp_hq)


DEBUG = False
RUSH_N = 12         # BAIT: accumulate this big a column parked at HQ before launching
GOLD_BUF = 40
LAUNCH_TURN = 50   # park on HQ (spoofs passivity -> trips enemy PARKED_SPLIT) until this turn, THEN all-in
N_BASES = 3        # claim this many strongholds for the income to fund a 12-stack


@dataclass
class Bot:
    inited: bool = False; base_reg: int = -1; marching: bool = False; claim_order: list = field(default_factory=list)


BOT = Bot()


def decide(S, M, nav, turn):
    a = Actions()
    try:
        _impl(S, M, nav, turn, a)
    except Exception as e:
        if DEBUG: print(f"# rush err t{turn}: {e}", file=sys.stderr, flush=True)
    return a


def _impl(S, M, nav, turn, a):
    me = M.my_side
    if not BOT.inited:
        BOT.claim_order = sorted(M.strongholds, key=lambda s: nav.hops(s, M.my_hq))
        BOT.inited = True
    my = [w for w in S.warriors if w.id.side is me]
    hq = S.find_building(M.my_hq)
    target = M.opp_hq
    spent = 0
    assigned = set()
    enemy_at = {w.region for w in S.warriors if w.id.side is not me}

    def can(c): return S.gold - spent - c >= GOLD_BUF

    def mv(w, t):
        nonlocal spent
        if w.id in assigned or w.state is not WState.STATIONARY or t == w.region: return
        if not nav.reachable(w.region, t): return
        b = S.find_building(t); c = 0 if (b and b.side is me) else MOVE_COST
        if c and not can(c): return
        spent += c; a.moves.append((w.id, t)); assigned.add(w.id)

    # ECONOMY: claim N_BASES nearest strongholds (income to fund the parked column).
    bases = [r for r in BOT.claim_order if r != M.my_hq][:N_BASES]
    base_set = set(bases)
    worker_ids = set()
    for br in bases:
        w_on = next((w for w in my if w.region == br), None)
        if w_on is not None:
            worker_ids.add(w_on.id)
            if S.find_building(br) is None and br not in enemy_at and S.gold - spent - BASE_LEVELS[1].cost >= 0:
                spent += BASE_LEVELS[1].cost; a.upgrades.append(br)
        elif not any(w.state is WState.MOVING and w.target == br for w in my):
            cand = next((w for w in my if w.state is WState.STATIONARY and w.region == M.my_hq
                         and w.id not in assigned), None)
            if cand is not None:
                mv(cand, br); worker_ids.add(cand.id)

    # COLUMN = all non-worker warriors. PARK on HQ (spoofs passivity -> trips enemy PARKED_SPLIT)
    # until LAUNCH_TURN, then all-in the whole column at the enemy HQ.
    column = [w for w in my if w.id not in worker_ids and w.region not in base_set]
    stat = [w for w in column if w.state is WState.STATIONARY]
    if turn >= LAUNCH_TURN and len(column) >= RUSH_N:
        BOT.marching = True
    if BOT.marching and column:
        cnt = Counter(w.region for w in column); stack = cnt.most_common(1)[0][0]
        at_stack = [w for w in stat if w.region == stack]
        together = len(at_stack) >= max(2, int(0.6 * len(column)))
        if stack == target:
            for w in stat:
                if w.region != stack: mv(w, stack)
        elif together:
            nh = nav.next_hop(stack, target)
            for w in at_stack:
                if nh >= 0: mv(w, nh)
            for w in stat:
                if w.region != stack: mv(w, stack)
        else:
            for w in stat:
                if w.region != stack: mv(w, stack)
    else:
        for w in stat:
            if w.region != M.my_hq: mv(w, M.my_hq)

    if hq:
        cap = HQ_LEVELS[hq.level].train_cap; n = cap
        while n > 0 and not can(TRAIN_COST * n): n -= 1
        a.train_n = n


def emit(a):
    out = ["COMMAND"]
    for wid, target in a.moves: out.append(f"MOVE {wid} {target}")
    for r in a.upgrades: out.append(f"UPGRADE {r}")
    if a.train_n > 0: out.append(f"TRAIN {a.train_n}")
    out.append("END")
    sys.stdout.write("\n".join(out) + "\n"); sys.stdout.flush()


def main():
    M, S = parse_init(); nav = Nav(M); nav.warm()
    while (turn := read_turn_start()) is not None:
        a = decide(S, M, nav, turn); emit(a); read_turn_result(S, M, a)


if __name__ == "__main__":
    main()
