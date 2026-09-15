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
                # HEAL-AWARE DETECTION (axis-1): an enemy UPGRADE on an ALREADY-MAX base is, by the
                # referee, a HEAL-to-full (500g). This is the unambiguous heal-wall signal sent directly by
                # the referee -- robust where HP-diffing our own siege model is not. Stamp the turn so
                # _can_crack reads this base as a heal-wall and stops the futile trickle (the game-4 fix).
                if HEAL_AWARE and b.type is BType.BASE:
                    BOT.heal_turn[region] = BOT.turn
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
# --- ETA-REACT (real ladder loss 1(2)): don't turtle/recall the forward fist for a stack that merely
# crossed the midline but is still FAR. The `committed` gate (L~1185) already intends "wait for the stack to
# actually CLOSE" (see its comment) but its past-midline disjunct fires on a stack 10 hops away, collapsing
# home_safe and yanking the whole fist home for nothing (the user's "적이 튀어나오면 HQ 복귀 + 동선 낭비";
# "거리가 있으니 빨리 반응할 이유 없다"). ETA-REACT keeps the past-midline turtle ONLY when the stack is close
# enough to beat our forward fist home: stack_dist <= (our most-forward warrior's return ETA) + margin. The
# close-in disjunct (stack_dist <= CONCENTRATE_DIST), on_hq, and siege_recall (the SIEGE_EMERG all-in rush
# floor, range 9) are ALL untouched -> a genuine beelining rush still triggers concentrate/recall in time
# (rush HQ-crack must stay 0 -- VERIFY). Rollback: ETA_REACT=0 restores the raw past-midline trigger.
ETA_REACT = 1
ETA_REACT_MARGIN = 3      # extra muster/train slack (turns) beyond the fist-return ETA before we turtle.
# --- VELOCITY-HOLD (user, log-8 t133: "상대가 우리 기지로 전진해 오면 그때 돌아가도 늦지 않는다 -- 전방 라인을 넘어
# HQ로 오는지 그 움직임을 봐라"). The past-midline `committed` disjunct still fires on a stack that is PARKED or
# RETREATING (log-8 t133: the enemy's stack, having razed our forward base, was falling BACK to its own HQ, yet
# we recalled the whole fist home anyway = ceded the forward line for nothing). VELOCITY-HOLD adds the missing
# signal: the past-midline turtle fires ONLY when the stack is actually ADVANCING on us (its hop-distance to
# our HQ strictly DECREASED since last turn). A parked/retreating stack no longer collapses home_safe -> we
# hold the forward line and re-engage. UNTOUCHED (rush-safe): the close-in disjunct (stack_dist <=
# CONCENTRATE_DIST), on_hq, siege_recall -- a genuine beeline is ALWAYS advancing so it still turtles in time
# (rush HQ-crack must stay 0 -- VERIFY). Stacks that appear (prev=inf) count as advancing (react on first sight).
# Rollback: VELOCITY_HOLD=0 restores the raw past-midline trigger.
VELOCITY_HOLD = 1
# --- LATCH-FIX TRIO (2026-07-02 replay forensic: resubmission games 4/6/7/8 ALL TURN_LIMIT draws; the same
# states driven through the #30 winner build produce near-identical decisions, so the draws were the opponents
# playing harder -- but the forensic exposed three structural "threat latch freezes everything while we are
# WINNING" pathologies, confirmed gate-by-gate with a locals tracer. Each lever below is independently
# flag-gated; all three = 0 restores the byte-identical pre-fix build (backup proto_pre_latchfix.py).
# Local testing is anti-predictive for these -- validation = no-regression suite + replay gate-fire check;
# real efficacy only via resubmission.)
# (1) VELOCITY-MUSTER (g7 t124 / g8 t120 full-army home recall): WAVE_STACK_MIN's "ANYWHERE" latch reads an
#     enemy stack GARRISONED AT ITS OWN HQ (8 hops away, parked, never advancing) as a forming wave; the
#     harass branch then holds target_garrison home and recalls everything beyond a HARASS_CAP fist -> we
#     cede the forward line, and the real wave later razes our forward bases unopposed and REBUILDS THEM AS
#     ITS OWN (g7: bases 21+26, g8: base 27 -> income swing -> enemy climbs L4 -> draw). VELOCITY_HOLD above
#     already gates `concentrate` on the advance signal; this extends the SAME signal to the muster: while
#     the latched stack is FAR (beyond the approach gate), NOT advancing, and nothing is in our half
#     (threat==0, on_hq==0), commit the FULL raid surplus forward instead of shrinking the fist. The garrison
#     TARGET (training ramp) and the fortify climb window are untouched; the instant the stack advances (a
#     real beeline always does) the normal matched muster resumes, and SIEGE_EMERGENCY still force-recalls.
VELOCITY_MUSTER = 1
# (2) UNDERMASS-PRESS (g6 t95-152 deadlock: ~60 turns of literally zero orders, gold 970->3,745 idle while
#     the enemy free-upgraded its bases and free-climbed): _under_massed suppresses ALL 1d base upgrades,
#     which is exactly the escape route _smallmap_econ points to ("drop the pin, deepen the economy") ->
#     mutual lock. The g3 rationale for the suppression (every gold to the HQ climb while a deathball forms)
#     only applies while the mass is actually PRESSING us; a stack parked on ITS OWN HQ all game is a
#     garrison, not an incoming wave. So suppress 1d only while PRESSING: advancing (velocity), within the
#     approach gate, on our half, or on our HQ / concentrate. Parked-at-home mass -> 1d resumes (income
#     compounds -> funds the same climb faster). 1c HQ-climb priority within a turn is unchanged.
UNDERMASS_PRESS = 1
# (3) DENY-DOMINANT (g4 t122: the enemy reached L3 first -> _behind_hq switched OFF deny_mode AND the
#     PRESSURE/CRACK fist funding in one stroke -> want_spare 16->2, combat losses never replaced (28->20),
#     and from t152 raid_force=0 = offense fully stopped for 48 turns while we held a 2x army + 8v5 base
#     lead). Keep the deny/pressure/crack gates OPEN while behind on HQ level IFF we decisively dominate the
#     field (army >= DENY_DOM_F x enemy total AND base lead): the climb catch-up keeps absolute gold priority
#     (hq_reserve/_bank_climb untouched -- the fist only ever trains from surplus ABOVE the banked upgrade),
#     we just stop disbanding the offense that is what keeps the enemy's economy (and thus ITS next level)
#     suppressed. Near-even armies (mirror) or non-econ-lead states never qualify -> inert outside g4-class
#     dominance.
DENY_DOMINANT = 1
DENY_DOM_F = 1.5          # "dominant" = our TOTAL army >= ceil(this x enemy total) (g4 t122: 27 v 13 = 2.1x)
# (1b) BASE-RALLY (new-g8 LOSS forensic, 2nd submission, t133): when the latched wave finally ADVANCES, the
#     muster resumed and ordered the 8 forward units HOME PAST the incoming 11-stack -- they were all mid-move
#     (MOVING, un-reorderable) when the stack landed on our base 27 at t135, so _relief could dispatch only 2
#     stationary bodies, the base fell piecemeal, B rebuilt it as its own (income swing) and out-climbed us.
#     The user's standing rule: don't walk the army out of the wave's path -- meet it AT the base ("기지에서
#     받아쳐라"). So when the advancing wave's predicted first target is one of our forward BASES (nearest of
#     our buildings to the stack, not the HQ), we can CONTEST it (army + that base's turret >= wave), and the
#     base keeps interior lines (no farther from our HQ than the wave is, so a bypassing beeline can never
#     beat us home), the muster rallies AT that base instead of at the HQ. A true HQ beeline (nearest = HQ,
#     or interior lines lost) still rallies home exactly as before; concentrate/siege_recall are untouched.
BASE_RALLY = 1
GOLD_FLOOR = 60           # never let planned spend leave us below upkeep cushion + this
HEAL_RESERVE = 1000       # bank this once HQ is strong, for emergency heal/upgrade
ASSAULT_START = 70        # earliest turn to consider committing surplus to offense
ECON_PAYBACK_CUTOFF = 175 # stop opening new work slots after this turn (won't pay back)
GUARD_MIN = 3             # standing home-guard floor (kept at HQ, never raids)
MUSTER = 6                # raid stack size to commit when we are AHEAD in territory
MIN_RAID = 4              # commit size when BEHIND in territory (and stack floor)
COUNTER_PUSH = 1          # 8(3).txt (user: "큰 웨이브 막고 인원차 생기면 러쉬, 지원 계산해서 정밀하게"): after we GRIND
#                           DOWN the enemy's wave we hold a clear UNIT advantage, and _can_crack (reinforcement-
#                           aware, referee-exact) confirms the enemy's forward bases are crackable -- but every
#                           eager-raid gate keys on _econ_lead (a BASE lead) which we DON'T have (we just defended,
#                           still base-behind). So the fist sat home 20 turns while the enemy retrained 7->20 and we
#                           lost the tiebreak (8(3) t88: home_safe, 15v9 units, bases 27+29 CRACKABLE, fwd~1 = zero
#                           attack). When home_safe + a real UNIT lead (>= enemy + COUNTER_PUSH_MARGIN) + a crackable
#                           enemy base exists, commit the raid at the MIN_RAID floor. Precision is _can_crack's job
#                           (it models the enemy's converging reinforcement, so it only commits to bases we actually
#                           raze -- never the turreted HQ / a defended base). MIRROR-SAFE: equal armies never clear
#                           the unit margin, so an even game never fires it (no climb-stall / draw regression). Rides
#                           the TRUE surplus (raid_force is beyond garrison need) so the L5 climb bank is untouched;
#                           not _behind_hq so we never trade the fist while losing the HQ race. COUNTER_PUSH=0 =>
#                           byte-identical.
COUNTER_PUSH_MARGIN = 5   # our warriors must exceed the enemy's by THIS to count as a DECISIVE post-defense unit
#                           advantage (8(3) t88 was 15v9 = +6). A transient mirror +1..3 lead must NOT trip it (that
#                           over-commits a near-even game -> loss); +5 fires only on a real post-defense edge. Also
#                           K-gated (M.K <= WIDE_FORCE_ANCHOR=15): wide maps regressed in the mirror (K19 1W4L), and
#                           every game-8-class defense-then-counter case is K9-K15 anyway.
# --- CONSOLIDATE-BEFORE-SIEGE (user, log-6 t81-85: "적 L1 기지에 수비 2기인데 5병력으로 못 이겨?" -- proto fed
# the fist in PIECEMEAL: A16 arrived t81, A15 t83, A18 t87, one at a time, so only 1-2 ever sieged base 32 at
# once, got chipped by the turret + 2 defenders, dealt 2 damage, and fled -- while 3 more units patrolled our
# own bases). ROOT: _raid_advance marches every unit toward the target INDEPENDENTLY (monotonic per-unit), so a
# scattered fist dribbles onto a DEFENDED target and dies in detail. FIX: when the target is DEFENDED, units
# that reach ADJACENCY HOLD there (they do NOT step onto the target alone) until a crackable-fraction of the
# fist is assembled adjacent -- then they all step on together and siege as one body. It only ever HOLDS FORWARD
# (never retreats), so it cannot reproduce the 0<->adjacent ping-pong the old 'regroup onto most-common node'
# rule caused. UNDEFENDED bases are untouched (dribble-raze is fine, and delaying would slow the turtle-raze
# wins). Rollback: CONSOLIDATE=0 restores the raw per-unit advance.
CONSOLIDATE = 1
CONSOLIDATE_FRAC = 0.6    # step onto a DEFENDED target only once this fraction of the fist is assembled adjacent
TERRITORY_SLACK = 0       # tolerate enemy leading by this many bases before contesting (0 = stay >= even)
CONTEST_REACH = 2         # also claim strongholds the enemy is closer to by <= this (race the middle).
#                           Raised 1->2 per the user's "don't yield the center" directive: contest a
#                           wider central band so we don't cede our fair share of the midline economy
#                           (no regression on the test maps; may claim a central stronghold on others).
CONTEST_CLAIM = 1         # R16 (game 6 root fix, user's "초반 러쉬 점령"): the 2b claim SKIPS any stronghold in
#                           enemy_at (an enemy body on it), a guard against feeding a lone claimer to a turret.
#                           But that CEDES a contested/TIE stronghold the enemy merely RESERVES with a single
#                           scout (g6 forensic: B held 32 with 1 body for 25 turns, 2 hops from our idle 4-11
#                           surplus, while we fell behind on bases -> lost the 6-vs-7 race -> economy behind ->
#                           every harass lever correctly OFF -> draw). When BEHIND on territory, a stronghold we
#                           are AT LEAST as close to (dm<=do, never overreaching into the enemy half) that is
#                           held by only a SMALL beatable force gets a SIZED STACK (enemy-within-our-ETA +
#                           CONTEST_MARGIN) sent to TAKE it instead of skipping. +1 PERMANENT base (net-positive,
#                           not a raid), near (our band, ~2 hops), early-only, surplus-only (garrison filled in
#                           2a first), one measured contest/turn -> far lower rush-exposure than a deep harass.
#                           flag=0 = byte-identical (the enemy_at skip stands).
CONTEST_MAX = 3           # only contest a stronghold held by <= this many enemy within CONTEST_REINFORCE hops (a
#                           lone reservation, not a defended stack -- a real garrison reads uncontestable, skip).
CONTEST_MARGIN = 2        # send (enemy within reinforce radius) + THIS so we decisively WIN the co-located fight
#                           and absorb a body of reinforcement that may join during the march.
CONTEST_REINFORCE = 2     # count enemy within THIS many hops of the stronghold as its defenders (a FIXED local
#                           radius -- an ETA-scaled radius over-counts B's whole forward area when our surplus is
#                           at home and mis-reads a scout-held stronghold as a garrison).
CONTEST_ETA_MAX = 5       # only contest a stronghold our nearest surplus can reach within this many hops -- a
#                           longer march leaves the stack out of position too long / gives B time to reinforce.
CONTEST_TURN_MAX = 100    # contest the middle only in the opening/early-mid; after this the map is settled and a
#                           forward stack is a raid (that path is _raid_commit's, crack-aware), not an expansion.
RACE_TIE = 1              # R17 (3pm 8-loss forensic, 6/8 = early territory-race deficit). CLAIM_SAFE_ORDER claims a
#                           near-CENTER stronghold we are AT-LEAST-as-close-to LAST (equal-own-dist -> farther-from-
#                           enemy first), so the enemy -- which sprints its opening worker at the midline -- BUILDS
#                           the contested center on arrival (1(26) region 35 dm4/do5 built by t8; 1(27) all 3 ties;
#                           1(29) 2 of 3 ties). R16 CONTEST_CLAIM can't reach that (it needs a BARE reservation, not
#                           a BUILT base). RACE_TIE promotes ONE genuinely-contested center stronghold (dm<=do<=dm+
#                           RACE_TIE_REACH: we are as-close-or-closer AND the enemy is ~equidistant) to be claimed
#                           FIRST in the opening, so we plant before the enemy. Pure EXPANSION (a lone claimer to our
#                           OWN-or-tie side, dm<=do STRICT so never overreaching into the enemy half) -- NOT the
#                           rejected mid-game military harass. Bounded: one race-claim/turn, opening-only, affordable
#                           + spare-claimer gated. 1(4) center-last safety: gated on NOT already base-ahead
#                           (len(my_bases) <= _ebct_wide) so a winning short-center map never over-extends. flag=0 =
#                           byte-identical (the claim loop's center-last order stands).
RACE_TIE_TURN = 60        # opening-only: race the center before the map settles; after this the normal claim order rules.
RACE_TIE_REACH = 1        # a stronghold is a CONTEST race-target only if dm <= do <= dm+this (genuinely central: we
#                           are as-close-or-closer AND the enemy is within 1 hop of the same distance). A deep-own-half
#                           base (do >> dm) is safely ours -> claimed by the normal order, never force-raced.
RACE_TIE_ETA = 1          # user ("초반 무리한 중앙 선점 -> 상대 응징"): gate the R17 center race on WINNING the build
#                           race. RACE_TIE picks the nearest genuinely-contested tie and marches ONE lone claimer with
#                           ZERO check on whether we actually arrive before the enemy builds -- so on a tie the enemy is
#                           CLOSER to, our body marches un-recallably (the referee forbids re-moving a moving warrior)
#                           into a just-built base/turret and dies for nothing (the "응징" the user observed). This fires
#                           the race ONLY if OUR claimer's arrival ETA <= the enemy's earliest BUILD ETA at that tie
#                           (enemy plants on arrival, so build-ETA = the nearest enemy body's hop count). A tie we can't
#                           win reverts to the normal center-last claim order (near/own-half economy first, faster
#                           payback). default 1<<30 when NO enemy body is near => uncontested races always send. It is
#                           SUPPRESS-ONLY (can only REMOVE a race dispatch, never add one), so every RACE_TIE safety
#                           guard (rush/siege_recall/_fort_hold/base-ahead) stays fully in force. RACE_TIE_ETA=0 =>
#                           byte-identical to the pre-gate live (single-knob rollback).
RACE_TIE_ETA_MARGIN = 0   # tie tolerance: fire if our_eta <= enemy_build_eta + this. 0 = must strictly tie-or-beat
#                           (strictest: never march into a race we are behind in). The ETA model is CONSERVATIVE (it
#                           assumes the enemy builds the turn it arrives), so 0 already errs toward caution; raise to 1
#                           to buy back speculative races where a nominally-closer enemy is slow to commit the build.
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
BURST_MIN = 5
ATTACK_MIN_HQ = 2
FUND_GATE = 2
LATE_CLIMB = 130
LATE_BACKSTOP = 150
FINAL_RUSH = 0           # DECOMMISSIONED -> replaced by ENDGAME_FINISHER below. The old lever only bumped
#                          want_spare (army SIZE) and gated on _is_max(hq) (true only ~t182), so it (a) fired too
#                          late to cover the t150-182 coast and (b) never DEPLOYED: the record-driven 5(2) trace
#                          showed moves_to_enemy_building=0 across t155-200 with a 40-body army parked home,
#                          because at LATE_BACKSTOP(150) the funding gate reverts _train_reserve->hq_reserve and
#                          the offensive want_spare bodies (n > worker_deficit) can no longer clear the ~3600 bank
#                          on proto's ~300-600 gold -> raid_force starves to empty -> the live deny branch (the
#                          "_harass_now and home_safe and raid_force" owner) runs with no bodies. FINAL_RUSH_TURN/
#                          FORCE kept only as legacy constants (unused). See ENDGAME_FINISHER for the real fix.
FINAL_RUSH_TURN = 150    # (legacy, unused) earliest turn for the old final rush.
FINAL_RUSH_FORCE = 24    # (legacy, unused) old final-rush army size.
# --- ENDGAME FINISHER (5(2) forensic + user spec) ------------------------------------------------------
# User: "이미 턴당 골드 수급으로 HQ[L5]에 도달할 수 있는게 계산되면 그때부터 병력을 찍어내고 190턴까지 유지하다가 한번에 끝내는 방식.
#        계산은 군대 유지비 + 턴당 골드 명령비(+여유분)로 발화. 이 피니셔는 우리가 유리할 때 작동."
# Once OUR OWN L5 is INCOME-GUARANTEED by the t190 horizon (banked gold + net income over the remaining turns,
# net of the fielded army's upkeep + a per-turn move/command bill + a buffer, covers the remaining climb cost
# WITH the operating reserve intact), ARM the finisher: keep a K-scaled deny fist funded RESERVE-FREE but only
# for the bodies income can afford ABOVE the reserved climb (so proto's L5 always banks -- self-limiting: as
# turn->ALLIN_TURN the horizon shrinks -> the affordable count -> 0 -> gold banks the climb), and let the
# already-live line-~3840 crack-aware backdoor RAZE B's income bases continuously through t150-190 (the coast
# the old lever wasted). Winning-only: fires only home_safe + climb-ahead (not behind on HQ level) + enemy still
# sub-L5 (a denial exists) on the K19 game-5-class map. NO _income_lead gate: game 5's B OUT-EARNS proto (2x
# income), so requiring income-lead would never fire in the exact game this targets; g7/g8 (the even-income
# draws that must not push) are K9 = already excluded by the K19 gate. ENDGAME_FINISHER=0 => byte-identical.
ENDGAME_FINISHER = 1
FIN_START_TURN   = 150    # earliest arm turn (= LATE_BACKSTOP; the coast window the old lever wasted).
FIN_FORCE        = 24     # base endgame deny fist (K-scaled up like WIDE_FORCE below).
FIN_MOVE_UNITS   = 3      # per-turn move/command allowance charged in the income-secured calc (~3 re-orders).
FIN_CAP          = 44     # hard ceiling on the finisher fist (matches the K19 _wide_force ceiling).
# --- 6-REPLAY FORENSIC FIXES (1(37)..1(42) bracket round, all instrumented-confirmed) -----------------
FIN_COMPACT = 1           # 1(41) K9: proto hit L5@t170 vs B L4 with ONE crackable income base, then emitted
#                           EMPTY commands t172-189 while B banked L5@t188 -> DRAW. Sole blocker (clause-proven
#                           with the K test counterfactually removed): the finisher family is hard-gated
#                           M.K > WIDE_FORCE_ANCHOR(15). Generalize _endgame_finish/_win_endgame(/_deny_allin)
#                           to compact maps. Safe: home_safe + climb-ahead + enemy sub-L5 + referee-exact
#                           _sim_crack (staggered relief) gate every commit -- rush/mirror structurally inert
#                           (mirror keeps behind-or-tied + ehl0==5; rush kills home_safe). FIN_COMPACT=0 =>
#                           byte-identical (K19-only as before).
DEAD_BANK_HEALTHY = 1     # 1(39) K15: A led L4-vs-L3 for t173-199, then DEAD_BANK_RELEASE's 0.5x half-rate
#                           discount declared the REACHABLE 3600 L5 bank dead (full-rate math: ~5672 bankable
#                           vs 3600 needed -> L5 lands ~t190 = WIN) and dumped the gold into a useless home
#                           army -> B tied at the buzzer -> DRAW. The 0.5x was tuned for game-5 (K19, income-
#                           BEHIND); on income-healthy compact maps use the FULL net rate so a reachable bank
#                           holds. DEAD_BANK_HEALTHY=0 => byte-identical (0.5x everywhere).
CLIMB_TO_WIN = 1          # 1(38) K17: proto fielded 33-40 warriors vs total_need=8, home_safe ALL endgame,
#                           enemy HQ stuck L2 -- ONE L3 (1200g) wins the tiebreak, but the INCOME_FLOOR wallet
#                           re-trained every spare gold and the bank flatlined at ~188 -> L2/L2 DRAW with a
#                           31w-vs-16w army lead. When home_safe + level-lead-or-tie + t>=FIN_START_TURN and
#                           NOT the armed finisher: (a) cap want_spare at CTW_SPARE_CAP so target_army stops
#                           over-funding (INCOME_FLOOR/READY_FLOOR floors go inert automatically once
#                           target_army < len(my_warriors)); (b) _fin_climb_left counts only the NEXT level
#                           when that level already beats the enemy (1200, not the full 7200 L2->L5 sum) so
#                           _income_secured is achievable. Mirror-safe (symmetric gate, both cap), rush-safe
#                           (home_safe). CLIMB_TO_WIN=0 => byte-identical.
CTW_SPARE_CAP = 2         # spare army kept above total_need while the climb bank is the winning move.
CTW_STALL_TURNS = 40      # cap only when the enemy HQ has not leveled for THIS long (a stalled climber --
#                           1(38)'s B: 120+ turns at L2); an actively climbing enemy keeps the deny fist
#                           (turtle-K19: capping vs a steady climber let it ride to L5 -> W->D regression).
CTW_K_MAX = 17            # CLIMB_TO_WIN applies only up to THIS map size: on K19 the game-5 deny/raze
#                           doctrine owns the endgame gold flow (capping the fist there converted a turtle
#                           win into an L2/L2 draw even with the stall test passing -- seed-2008 isolation);
#                           the 1(38)-class stalled-enemy bank-one-level win lives on K<=17.
PARITY_CLIMB = 1          # R42 (1(44)/1(45)/1(46)/1(49) wallet forensic, all four fidelity-0 replays): at
#                           HQ-level PARITY-or-ahead the MID-game has NO state in which training yields to
#                           the climb bank -- the window (_hq_climb_window) opens on _under_massed, which
#                           coincides with home_safe==False, so _bank_climb never arms (measured 0/152
#                           turns in 1(45)); the want_spare/worker_deficit floors then train reserve-free
#                           and, with the raid move bill, consume 100% of income forever. Measured max bank
#                           500-844g vs a 600-2400g step in ALL FOUR games: 1(44) DREW holding 7-bases-vs-1
#                           at L2 (a climb = win), 1(45)/1(46) lost the tiebreak L2-vs-L4 / L3-vs-L5, 1(49)
#                           ended L1. THE WEDGE: while our OWN HQ level has been stalled >= PC_STALL turns
#                           (and not behind -- CLIMB_HOLD banks that case), force the hq_reserve bank + the
#                           _bank_climb wallet treatment (reserve-free training capped at the ECON floor)
#                           regardless of window/home_safe, and shield the bank from DEAD_BANK_RELEASE
#                           (self-fulfilling in 1(46): floor-trains starved the bank at 47g/turn, then the
#                           rate arithmetic declared it dead for 35 turns and released it to more trains).
#                           SAFETY: off under _mg_on / concentrate / on_hq>0 / _om_drop / an advancing-or-
#                           near WAVE-sized stack (real assaults train at the full reserve-free rate), and
#                           on WIDE maps it yields to a live deny fist (BOT.deny_mode = the g4/g5 raze-first
#                           doctrine). PARITY_CLIMB=0 => decision-identical.
PC_STALL = 35             # own-HQ level age (turns at the same level) before the wedge arms
PC_TURN = 40              # never before the opening claim wave settles (claim funding owns the wallet there)
PC_GIVEUP = 45            # armed this long on one level with no real bank progress -> stand down (poverty maps;
#                             45 not 30 -- 1(44) banks slow-then-fast: armed t102, bank only accelerates t136+ once
#                             the raid force thins, L3 lands t142; a 30-turn valve killed it 10 turns short)
PC_REARM = 1              # R45 (7(1) forensic): the give-up latch is one-way per level, but a WAR-starved
#                           bank reads like a poor map -- 7(1) latched dead t131 (gold 185) mid-wave-cycle,
#                           then the map went quiet and gold recovered to 990 with the wedge off. Re-arm
#                           when gold has gained half the step since the death verdict (the valve's own
#                           progress bar, now run in reverse). True poverty maps never gain half a step
#                           after death -> stay stood-down untouched. PC_REARM=0 => decision-identical.
HP_FIGHT_BAR = 1          # R49 (HP audit, adversarially CONFIRMED gap #1): FIELD-FIGHT verdicts count
#                           heads while the referee fights hit points -- warrior hp follows HQ level
#                           (4/5/6/7/8), so when the enemy HQ outlevels ours a "matched + 1" contest
#                           (base_eating gate, FORWARD-PUSH turtle-or-contest, need_fight sizing) walks
#                           into a fight it mathematically loses (their hp7-8 vs our hp5-6 = 1.3-2x
#                           effective-HP deficit at equal counts), exactly in the mid/late behind states
#                           where those gates fire. Fix: weight the ENEMY stack by the warrior-hp ratio
#                           (their_hp / our_hp, only when > 1) in the three field-fight comparisons.
#                           HOLD-RULE staffing (siege = attackers - defenders) stays headcount -- the
#                           audit confirmed counts are CORRECT there (threat+1, TRIVIAL_SIEGE,
#                           PREDICT_STAGE, defenders_needed). RELIEF family deliberately untouched: its
#                           optimism is load-bearing for wave STAGING (the REACH_WIN 8(5) scar -- a
#                           stricter bar there recalled the staging and LOST the base). Level-equal or
#                           level-ahead -> ratio 1.0 -> byte-identical. HP_FIGHT_BAR=0 => identical.
OPEN_CLAIM = 1            # R48 (8-series root, ledger-measured on 8(8)===8(11)): the opening CLAIM loses
OPEN_CLAIM_TMAX = 40      # the wallet race to the TRAIN. 1b bills a standing claimer's build at
#                           300 + reserve while the train bills 120 + reserve, so at t7 (gold ~310, A2
#                           standing on stronghold 27 since t4) the claim fails, TRAIN A4@8 eats the fund,
#                           and the claim slips to t16 -- then A4 stands on stronghold 2 from t11 and
#                           claims only at t28. The 8-AI plays the opposite order (claim 54@2, 55@7, THEN
#                           train B4@10) and its 2-base income from t7 compounds into 5-vs-4 bases, a
#                           13-vs-9 train window, the lost race to 28 (B7@43 -> claim@49) and the wave
#                           that razes 27 = the whole income-asymmetry loss class (also 7(1): A4 stands
#                           on 26 from t13, claims @29). Fix: in the OPENING (turn <= OPEN_CLAIM_TMAX) a
#                           claimer ALREADY STANDING on an unclaimed stronghold bills the build LEAN (raw
#                           300 + _eg_hold, no reserve cushion) -- the body is sunk, the build is pure
#                           income conversion, and every turn unbuilt is 15g burned. RUSH_BRAKE keeps its
#                           veto (under a closing rush the 300 IS the defense budget), 2b dispatch gates
#                           (AVAIL_CLAIM_GATE etc.) are untouched -- this changes WHEN a standing claim
#                           pays, never who gets dispatched. OPEN_CLAIM=0 => decision-identical.
L2_WATCH = 0              # R47 ROLLBACK (ladder falsification 7(3)/8(10), both fidelity-0): the watch made
#                           7 WORSE (draw -> L1-vs-L4 LOSS): B's 12-train stream extended the hold, the
#                           follow-trains (13, deliberately exempt from the leak guard) consumed the 600,
#                           and the ensuing wave-cycle war poverty kept gold below 600+reserve FOREVER --
#                           our HQ finished the game at L1 (hp-4 warriors vs hp5-7) and the bases fell in
#                           sequence (26@66, 24@131, 5@135, 8@163). In 8(10) the watch released after only
#                           5 turns (MG delta signal, L2@52) = no effect on the known 8-class loss. The
#                           t47-L2 opportunity cost was real (R46 forensics stand), but naive follow-train
#                           at L1 vs an economy-backed streamer is the waverush death spiral in slow motion.
#                           Verdict: fast L2 was RIGHT on these maps after all. Original doctrine comment
#                           below preserved for the record.
#                           R46 (user doctrine: "간을 보다가 유닛을 찍는게 보이면 우리도 따라 찍는다"): the
L2_WATCH_TURNS = 10       # 7/8 AIs (and likely human mid-ladder) DELAY their HQ (L2@81 / L2@160) and pour
L2_WATCH_TMAX = 90        # everything into units+bases; our unconditional L2@47 buy cost a 9-turn train
L2_WATCH_STREAM = 4       # blackout (9 vs 13 bodies in the t40-62 window) and an empty raid pool while
L2_WATCH_KMAX = 9         # small-map gate: the delay-opening class lives on K9 (both 7/8 ladder maps);
#                           on K13/K19 the same watch measurably LOSES tempo vs climbing opponents
#                           (battery: my-bot K13 10W->7W, mirror K19 5W->1W before the leak guard;
#                           still -2W/+3L after) -- big maps reward the fast L2, small maps punish it.
#                           their side bases sat 1-defender-open (7(1) t63-75, measured). And the doctrine
#                           comment "L2 doubles train_cap" is a TABLE BUG -- train_cap is 1 at BOTH L1 and
#                           L2 (2 only from L3), so delaying L2 costs income/turret/warrior-hp, NOT
#                           production speed. Fix: when our HQ is L1, the enemy HQ is L1, and the 1c L1->L2
#                           buy first becomes FUNDABLE, hold the purchase for a WATCH window
#                           (L2_WATCH_TURNS): the freed 600g flows to trains/claims via the normal
#                           pipelines (measured in the no-L2 probe: +3 trains / stronghold-31 contest).
#                           Release triggers: enemy L2 observed (_ehl0 >= 2 -> buy next turn, 6(2)-class
#                           costs only +1~2 turns), forced climb window (_hq_climb_window: fortify/siege
#                           heal outranks the watch -- 1a emergency heal is a separate path and is never
#                           touched), window expiry with no signal (5-class turtles). Extension: an enemy
#                           TRAIN STREAM (>= L2_WATCH_STREAM in MG_STREAM_WIN turns, mg_tlog sensor -- no
#                           base cap, unlike MG's arm) keeps the hold alive while they stay L1, hard-capped
#                           at L2_WATCH_TMAX (before the LATE_CLIMB/ZERO_OPS bank clocks). While holding,
#                           PARITY_CLIMB's wedge and MG's parity-bank are co-gated (they would silently
#                           re-bank the 600 the watch just freed). L2_WATCH=0 => decision-identical.
DEAD_OPPONENT_MARCH = 1   # 1(40) K13: B's rush died t14, B built ZERO bases + had ZERO units from t29 (a
#                           defenseless L1/hp10 HQ husk that can never train again) -- yet proto idled 12
#                           bodies on base 3 for 170 turns and DREW: _raid_commit is base-only (empty target
#                           list -> raid_tgt=-1), _finisher's FIN_FULLBILL wanted move-bill+reserve (~210g)
#                           the CRACK_FORCE-starved +2g/turn economy couldn't pay until t197. When the enemy
#                           is an annihilated remnant (0 bases, <=DEAD_OPP_MAXW warriors) and home_safe and
#                           the referee-exact sim cracks its HQ: march the raid_force at opp_hq, pay only the
#                           raw move bill (no reserve -- hoarding an upkeep cushion against a corpse is
#                           self-defeating), and cap want_spare at DEAD_OPP_SPARE so the walkover army stops
#                           starving the wallet. Gated on the remnant signal -> live games byte-identical.
DEAD_OPP_TURN = 40        # earliest walkover turn (rush aftermath settles by then; sim still gates).
DEAD_OPP_MAXW = 2         # "no units": at most this many enemy warriors left anywhere.
DEAD_OPP_SPARE = 8        # spare cap while the walkover signal holds (enough to crack an L1-L2 HQ).
# --- FWD_GARRISON (user doctrine, 8(5)/8(6): "둘 다 HQ에 많이 있어 -- 전방으로 배치할 순 없나") ----------
# The enemy marches deterministic shortest paths at 1 hop/turn; a body STANDING on our forward base is
# re-orderable EVERY turn and moves to friendly buildings for free. So the idle reserve can hold a forward
# base whenever the RETURN GUARANTEE holds: hops(base, my_hq) + FWDG_MARGIN <= nearest enemy's distance to
# our HQ (margin covers the one-turn detection lag) -- we then always beat a committing enemy home, and in
# the meantime the posture buys faster base relief, wider intercept reach (HI/relief count reach from body
# positions) and the staging deterrence 8(6) demonstrated. Implemented as the WATCH/withdraw parking choice
# inside _raid_commit: the fist parks on the most forward return-guaranteed base instead of the HQ doorstep;
# as the enemy closes, the guarantee tightens and the post collapses toward home automatically. climb-bank
# home_recall keeps absolute precedence (g8 coast rule). #40 FORWARD-INTERCEPT distinction: this STANDS and
# waits on OUR building (the validated FWD_STATION class), it never marches out to trade. FWD_GARRISON=0 =>
# byte-identical.
FWD_GARRISON = 0
FWDG_MARGIN = 2           # return-trip headroom in hops (1 detection lag + 1 safety).
FWDG_MAX = 3              # post only on CORE bases (<= this many hops from our HQ): the un-capped midline
#                           post fed the reserve to competent raiders piecemeal (my-bot K13 10W->6W, mirror
#                           L 3->5) -- the guarantee protects the HQ, not the post itself. 8(6)'s winning
#                           stage was hops~3 = inside the core/turret mutual-support envelope.
# --- MIL_GAMBIT (1(45) scout + waverush hard gate; user doctrine: "군사력 증강을 눈치 채야") -----------
# Top-tier gambits trade economy for army (2-base claim + continuous training + wave stream / early fist).
# Measured loss chain vs them (waverush K9 s2000 / K13 s2002): opening gold -> 3 base builds (900g) ->
# bank never reaches 600 -> HQ stuck L1 -> train_cap pinned at 1/turn -> out-produced ~2:1 -> bases razed
# -> income spiral -> HQ dead. At the fire turn proto was EXPANDING (3rd/4th base) and had trained ZERO
# warriors for 12 straight turns with 227-375g idle. Detector (validated: fires 9/9 gambit games t3-54,
# 0/7 normal games incl. mirrors) -- within the t<=MG_TURN_MAX gate, fire on ANY of
#   (a) enemy_warriors - my_warriors >= MG_DELTA_HARD                    (map-independent army lead)
#   (b) delta >= MG_DELTA_SOFT and an enemy within MG_DEEP_FRAC of the  (lead + real incursion; hop
#       HQ-to-HQ hop distance of OUR HQ                                  thresholds must be map-normalized)
#   (c) enemy trained >= MG_STREAM_TRAINS in MG_STREAM_WIN turns while  (base-capped army stream --
#       holding <= MG_STREAM_MAXB bases and delta >= MG_DELTA_SOFT)      catches the low-delta striker)
# Response while latched: FREEZE claim dispatch + 1b base builds (each 300g = 2.5 bodies of misallocation),
# floor target_army at enemy total + MG_EDGE (funded RESERVE-FREE like READY_FLOOR), keep the harass
# surplus HOME, and open the climb bank the moment parity is reached (L2 doubles train_cap = the
# structural counter). Latch releases at parity with no deep incursion; re-latch allowed after a first
# in-gate fire (a persistent rusher re-surges past t60). MIL_GAMBIT=0 => byte-identical.
MIL_GAMBIT = 1
MG_TURN_MAX = 60          # first-fire gate (the one ungated FP: mirror-K19 endgame swing at t180)
MG_DELTA_HARD = 3
MG_DELTA_SOFT = 2
MG_DEEP_FRAC = 0.40       # "deep" = within this fraction of HQ-to-HQ hops of OUR HQ (never absolute hops)
MG_STREAM_TRAINS = 4      # enemy trains in the window ...
MG_CLAIM_SAFE = 3         # while latched-and-outnumbered, claims are allowed ONLY when no enemy body is
#                           within this many hops of the target: the blanket freeze left OUR razed
#                           strongholds unrebuilt for 100+ turns (income 30-v-45 = the slow death in every
#                           crack seed), while the 1(46) winner's whole doctrine was the cheap 300g rebuild.
#                           The roving wave cycles ~12-15 turns, so safe windows always come.
MG_STREAM_WIN = 12        # ... of this many turns ...
MG_STREAM_MAXB = 2        # ... while holding at most this many bases
MG_EDGE = 1               # parity floor = enemy total + this
MG_SPARE_CAP = 2          # want_spare ceiling while latched (raid is off; garrisons live in total_need)
# --- TRIVIAL_SIEGE (3(1) drip war; user: "상대 하나가 공격 나가는데 노동자까지 다 막더라 -- 인원분배") ----
# AI#3's endgame is a 1-body DRIP at our HQ every ~15 turns. Each drip set on_hq>0 / a 1-2 "stack" inside
# CONCENTRATE_DIST -> full concentrate + siege_recall -> the entire roster (base workers included)
# shuttled home and back, 130 turns straight: income strangled, training starved (0 trains the whole
# phase), no surplus ever formed to counter a 5-body enemy, and the guard gaps during the shuttle let the
# drips chip exactly the 2 HQ hp that decided the TURN_LIMIT tiebreak. The referee hold rule says the
# STANDING HQ guard + turret already win these fights where they stand (equality is safe: the turret is
# invulnerable and the HQ hp pool absorbs the grind). So: when the threatening count on/near the HQ is
# <= turret + standing HQ garrison, do NOT arm concentrate/siege_recall -- the guard absorbs it, everyone
# else keeps working/raiding. Real waves exceed the standing guard and arm exactly as before.
# TRIVIAL_SIEGE=0 => byte-identical.
TRIVIAL_SIEGE = 1
# DRIP_GUARD (3(3) follow-up): a RECURRING trivial dribble keeps a STANDING TRIV_MAX+1 HQ guard --
# the per-arrival staffing pull rotated bodies every cycle and the drips landed siege ticks in the
# 1-turn rotation gaps (3(3) t162-175). Window-decayed; DRIP_GUARD=0 => byte-identical.
DRIP_GUARD = 1
DRIP_MIN = 2              # arrivals within the window that mark a drip WAR (a one-off stays reactive)
DRIP_WINDOW = 40          # turns; the standing guard decays this long after the last arrival
# WORKER_SPARE (3(3) follow-up; user: "막기 충분한 인원만, 노동자는 안 보내게"): under hq_pressure the
# base workers are released into the staffing pool (real-siege survival rule, unchanged) -- but the
# picker now gives EARNING workers a WORKER_SPARE_BIAS-hop penalty, so an about-as-close true spare
# goes first and the income keeps flowing. Quantity/urgency untouched (a worker still goes whenever
# it is the only body in reach) -> the early-rush defense is structurally unaffected.
WORKER_SPARE = 1
WORKER_SPARE_BIAS = 1     # hops of penalty; 1 = spare the worker only when a spare is at most 1 hop farther
TRIV_MAX = 2              # only 1-2 body dribbles qualify (the uncapped hold-rule formula also waved
#                           3-4 groups through vs a big standing garrison and cost a reproducible
#                           my-bot K19 draw->loss; the drip class the fix targets is 1-2 bodies)
MG_BASE_GARRISON = 3      # standing garrison per base while latched (3 + turret1 = holds a 4-fist,
#                           grinds a 5-wave at 1hp/turn -- the 1(47) hold rule, pre-positioned because
#                           reactive relief arrives one turn late on 2-hop base geometry)
MG_RELIEF_LEAN = 1        # R87 (1(94) K17, we=LEFT, RIGHT_WIN TURN_LIMIT, ★mm matches record thru t85; user:
#                           "맨 후방 L1 기지에 3마리씩(+2,+2=4) t73부터 이유 없이 박혀 교전에 안 온다; 초반 대등할 땐
#                           유닛 하나하나가 중요"): MG_BASE_GARRISON=3 pins max(work_cap,3) at EVERY base while a
#                           MIL_GAMBIT is latched. On L1 bases (work_cap 1) that is 1 worker + 2 IDLE bodies -- and
#                           1(94) parked 3 at nodes 6/19 (node 6 is 1 HOP from the active fight at base 21) from t73
#                           while base 21 went out-manned. Fix: when a base's MG garrison sits WITHIN MG_LEAN_REACH
#                           hops of a base under ACTIVE attack (an enemy adjacent to it), lean THIS base to work_cap
#                           so its excess falls to surplus and the relief feeds the real fight. ★Tight: EARLY +
#                           near-parity only (a masser out-massing us keeps the full 3-per-base -> waverush-safe),
#                           and only near an ACTIVE fight (no fight = full garrison, rear coverage intact -- the
#                           'frontier-only worse' scar). MG_RELIEF_LEAN=0 => decision-identical.
MG_LEAN_TMAX = 100        # early-mid only (late, hold the full pre-garrison for the endgame waves).
MG_LEAN_MARGIN = 5        # near-parity: lean only if enemy_total <= our army + THIS (a masser keeps the full 3).
MG_LEAN_REACH = 2         # lean a base whose garrison is within THIS many hops of a base under active attack.
# --- WIN_ENDGAME_COMMIT (the REAL game-5 fix: shadow-box, not funding) --------------------------------
# Two workflows + a replay probe (bdefense.py on 5(2)) proved the finisher's fund/size levers targeted the
# WRONG problem. In the ACTUAL game-5 endgame proto had ALREADY razed B to its LAST base r100 (L2, hp12)
# and had 37 bodies DEPLOYED, and _can_crack(full fist, r100) = True for all of t150-199 -- yet r100 sat
# at hp12 for 50 turns (proto dealt it ZERO damage). Root cause: r100 is adjacent to B's 20-body HQ
# GARRISON (which never sorties -- it stays defending the HQ), so the naive _stop flee-count inflates on
# that parked garrison and proto FLEES a base it could cleanly raze (COMMIT_CRACK's assembly requirement
# never engages because the fist flees before it can assemble). Razing r100 ONCE drops B's income 90->60
# g/turn -> B needs 60 turns for its final 3600 -> t215 > t200 -> B NEVER reaches L5 -> proto WINS. So in
# the WINNING endgame (climb-ahead, home-safe, K19), trust the referee-exact FULL-force _can_crack over
# the _stop count: commit the whole fist to the best crackable enemy base and march in, ignoring the
# stay-at-home HQ garrison. _can_crack is survivor-gated (CLUSTER_KEEP_F), so this is a sim-approved WIN,
# not a Pyrrhic suicide. Gated: home_safe (rush-safe), climb-ahead (winning-only), K19, enemy sub-L5.
# WIN_ENDGAME_COMMIT=0 => byte-identical (the override block is skipped).
WIN_ENDGAME_COMMIT = 1
WIN_ENDGAME_LOCK   = 4    # commit-lock turns when the endgame override seizes a crackable base.
# --- GARRISON-PROOF CLIMB RESERVE (8-loss campaign fix #1: the HQ-climb-stall root cause) -------------
# Forensic+instrumentation across 8 ladder losses: in every tiebreak loss the climb window was OPEN
# (behind_hq) yet the HQ upgrade was NEVER affordable, because army training + upkeep drained gold below
# the next-level cost every turn faster than it could bank. The existing climb reserve only guards the
# OFFENSIVE surplus (n > worker_deficit); worker_deficit includes the DEFENSIVE standoff-matching need, so
# training up to the matched garrison bypassed the reserve and starved the climb (g1_4 t90: gold 1244, one
# turn from L3, trained 9 warriors instead -> gold pinned to 0 by upkeep, HQ frozen at L2 to t200 while the
# enemy reached L5). BANK_CLIMB protects the next HQ cost against the STANDOFF army beyond our economic
# work_cap (income workers are NEVER frozen -- the sacred "workers first" invariant), and ONLY in a CALM
# climb state (home_safe, no committed wave, not fortress) so it AUTO-DROPS the instant a real assault forms
# (home_safe/concentrate flips) -> the rush HQ-crack-0 defense is untouched. Self-capping: the reserve is
# one level's cost; once banked+upgraded it resets to the next. Rollback: BANK_CLIMB=0.
BANK_CLIMB = 1
# --- RELATIVE ECONOMY INVEST (8-loss campaign fix #3, the user's refined vision) ----------------------
# The user's principle: don't blindly over-produce, and don't HOARD idle gold toward the HQ (hp does not
# compound) -- when we are OUT-ECONOMIED, invest the surplus into ECONOMY (work_cap) so income COMPOUNDS,
# then climb the HQ decisively at the end to the highest level the income supports ("최대한 상대와 차이를
# 만들어 내는 구간을 만들고 막판에 HQ를 올린다"). It is RELATIVE: it fires ONLY while our per-turn income
# (work_cap) TRAILS the enemy's -- verified that every game we WIN we are income-AHEAD (K9 turtle: 19 vs 1),
# so the wins stay byte-identical; it fires only in the losses (all income-behind), shifting their idle
# hoard (2746g @L4) into base upgrades earlier -> higher income -> a higher final climb. Unlike SMALLMAP_ECON
# it is NOT K-gated (relative, all maps) and fires EVEN when behind_hq (that IS the state we must dig out
# of), but only while home_safe / not under a forming assault (then defence/fortify outrank economy).
ECON_INVEST = 1
ECON_INVEST_WIDE = 1      # 1(4) loss (K15/K17): _econ_invest above is K-gated to K<15 -> excludes the WIDE loss maps
#                          where we SPRAWLED into L1 bases (base 8 > enemy 7) while the enemy UPGRADED (income 17 > our
#                          11) then out-produced+rushed us. Extend income-invest to K>=WIDE_FORCE_ANCHOR ONLY when we
#                          have razed the enemy NOTHING all game (not BOT.offense_engaged). That razing-activity gate
#                          STRUCTURALLY self-excludes the g4/g5 WINS (they raze 119/132 -> offense_engaged True by ~t75,
#                          before the turn-gate) so g4/g5/7/8 stay byte-identical. Rollback: ECON_INVEST_WIDE=0.
ECON_WIDE_TURN = 110      # late anchor (past the mid-opening deny window); with offense_engaged this can never arm on g4/g5
ECON_WIDE_INCOME_MARGIN = 3   # enemy income (Sum work_cap) must lead ours by >= this (1(4): 17 vs 11); rejects tiny deny-dips
ECON_WIDE_BASE_LEAD = 1   # AND we out-base the enemy by >= this (1(4): 8 vs 7 = STRICTLY more = the "기지를 더 가져갔다"
#                          sprawl signature). Was 2 but the real 1(4) loss only reached a base LEAD of 1, so 2 could
#                          never arm on its own target; the g4/g5 safety is `not offense_engaged`, NOT this margin.
# --- STAND-UP: convert idle bodies STACKED on a base into income by upgrading THAT base in place -------
# The user's compounding goal (g4/g5): widen the margin by growing turn-gold WITHOUT cutting razing. The
# referee pays income = 15*min(warriors_present, work_cap) per building, so a warrior ALREADY STANDING on a
# base earns +15/turn up to work_cap and NOTHING beyond it. Forensic 4.txt: base 60 carries 4-5 warriors on a
# cap-1 base from t170 (3-4 of them idle, +0 income, -2 upkeep each) while the idle mustering army parks on the
# saturated HQ (count>work_cap). Upgrading base 60 in place (no march, no new garrison, no claimer) absorbs those
# ALREADY-PRESENT bodies into income (+15 each up to the new cap). This is a PARETO gain: it needs no extra
# warrior and diverts ZERO razing gold, because it is gated to fire ONLY on gold that is provably surplus to the
# entire remaining HQ climb-to-L5 (STANDUP_CLIMB_KEEP below) -- so it can never delay the L4->L5 that decides the
# tiebreak. STRUCTURAL g4/g5 SAFETY: g4's bank never reaches (base_cost + remaining_climb_to_L5 + reserve) before
# L5 fires (bank climbs toward the 3600 L4->L5 bar and is spent the instant it clears it), so the gate is FALSE
# every pre-L5 turn -> g4 command stream byte-identical; it can only arm from the exact turn HQ hits L5 (climb
# term -> 0), spending genuine post-climb surplus on already-idle bodies. Rollback: STANDUP=0.
STANDUP = 1
STANDUP_MIN_SURPLUS = 1   # require >= this many warriors ALREADY stacked on the base ABOVE its current work_cap
#                           (so the upgrade is filled by bodies already present -- a real Pareto conversion,
#                           never a speculative slot begging for a worker that must first march there).
# --- FLYWHEEL (real ladder loss 1(2), M.K=9): convert a MILITARY-SUPPRESSION advantage into TURN-GOLD ----
# The user diagnosis, confirmed by parse_1_2.py: proto WON the early fight (razing, offense_engaged by ~t59)
# but NEVER converted that edge into economy -- it kept every base at L1 and dumped gold into army, so its HQ
# stalled at L2 and its razing FLATLINED at 34 after t130. The opponent, though suppressed, upgraded held bases
# L1->L2 (the 40-turn-payback sweet spot, NOT deep L3), pulled a turn-gold lead (+45g/turn by t120), and that
# funded a BIGGER army (48 vs 37) that OVERTOOK proto and took over the raiding (siege 18->60) to win the
# tiebreak. FLYWHEEL closes that loop: when we HAVE the military initiative (offense_engaged) but are NOT ahead
# on income (_my_workcap0 <= _enemy_workcap), upgrade held bases L1->L2 from surplus so the turn-gold grows and
# funds a bigger sustained army -- a compounding cycle, not a one-shot economy pivot, done WHILE we keep raiding.
# SAFETY: g4(K15)/g5(K19) are excluded by M.K < WIDE_FORCE_ANCHOR (byte-identical, K-gated). g7/g8 are M.K=9
# (SAME band, no K separation) but proto WINS them by out-climbing -> HQ-AHEAD -> `_behind_hq` is FALSE -> gate
# cannot arm -> byte-identical there too (the load-bearing relative discriminator; same one _econ_invest uses).
# 1(2) fires because proto fell HQ-BEHIND at t50 (L2 vs the opponent L3) while still income-even and razing.
# L2-capped (b.level >= 2 skip) per the user: pull turn-gold via L2 timing, not inefficient L3. Rollback: FLYWHEEL=0.
FLYWHEEL = 1
FLYWHEEL_KEEP = 0        # extra gold (beyond the standing `reserve`) to hold back before an L2 turn-gold upgrade.
# --- PRESS-L2 (the user's "유리할 때 격차를 더 벌려라"): the COMPLEMENT to FLYWHEEL. When we are OUT-EARNING the
# enemy (income AHEAD), pour surplus gold into MORE L1->L2 base upgrades to WIDEN the turn-gold gap -- the
# 1(2)-winner's pressure engine, now applied when WE hold the economic lead. L2-capped (efficient tier, no L3).
# SAFETY: K-gated to compact (M.K < WIDE_FORCE_ANCHOR) so g4/g5 (wide) are byte-identical -- the #26 economy-
# divert regression zone is excluded outright; the income-AHEAD gate is a second lock (g4/g5 also win income-
# BEHIND). Surplus-only (spends above the full operating `reserve`, same bar as FLYWHEEL) so it never starves
# army/defense/climb. Fires on compact/mid maps (where 1(2) lives) when we out-earn. Rollback: PRESS_L2=0.
PRESS_L2 = 1
PRESS_L2_KEEP = 0        # extra gold beyond `reserve` to hold before a press upgrade (0 = spend all true surplus).
# --- WIDE-L2 (user gamble: "4/5에서도 L2 시도"): remove the compact-only K-gate from FLYWHEEL/PRESS_L2 so the
# L2 turn-gold logic ALSO fires on WIDE maps (g4 M.K=15, g5 M.K=19). RISK: #26 -- on g4/g5 proto wins income-
# BEHIND by RAZING (119/132); diverting surplus to L2 could delay the razing/climb and turn win->draw. Mitigated
# only by the surplus gate (>= reserve) -- but g4/g5 are near-zero-slack so this is a genuine gamble. Efficacy +
# safety are re-submission-only (real g4/g5 opponent not locally reproducible). Rollback: WIDE_L2=0 restores the
# compact-only K-gate (= byte-identical to the pre-gamble build). Default 1 per user request to test it.
WIDE_L2 = 1
RUSH_SNOWBALL = 1        # 5.txt (user's policy): "초중반 러쉬가 성공했고(기지 리드) 상대의 뒤집기 공격이 실패한 후
#                          라면 L2 업글하기 충분한 타이밍 -- 후반 지나면 L2는 손해니까." This is the SAFE trigger that
#                          resolves the gold-wall (l2-base-economy-timing): REL_ARMY/PRESS_L2 gate on income-AHEAD
#                          (chicken-egg -- proto is income-BEHIND precisely because it has no L2), so they never fire
#                          in the g5 draw. Instead trigger on the ATTACK/DEFENSE state: base-ahead (rush won) AND the
#                          enemy's operational army is spent (op_army <= SNOWBALL_EN_OP = counter failed) AND home-safe
#                          AND not-behind-HQ AND early-mid (t<=SNOWBALL_UNTIL, before L2 stops paying back). Trace of
#                          g5: the window is REAL -- t77-100, bases 10v9, home_safe, enemy_op 1-2, yet want_spare=44
#                          (proto builds a 44-army vs a 2-army enemy = the redirectable gold). Two coupled actions in
#                          that window: (A) CAP want_spare to SNOWBALL_SPARE_CAP so the army-gold frees up, (B) let 1d
#                          upgrade held rear L1->L2 from the lean claim. Self-limiting: the instant the enemy re-arms
#                          (op_army rises past the gate, ~t100) the cap lifts and want_spare re-scales to the threat.
#                          CAUTION: cutting army on WIDE razing-deny maps regressed REL_ARMY -- the tight
#                          counter-failed trigger must be shown non-regressive by test. flag=0 -> byte-identical.
SNOWBALL_EN_OP = 4       # enemy OPERATIONAL army (enemy_total - workcap) <= this = "the counter attack failed/spent".
SNOWBALL_UNTIL = 100     # PHASE PIVOT (user, 5(1) forensic): the economy phase ENDS here. 5(1) proved the
#                          economy race is a wash -- RUSH_SNOWBALL got proto to L5 but B (2x income surplus)
#                          ALSO reached L5 (faster: B L5@t150, proto@t180) -> DRAW. The ONLY asymmetric win is
#                          DENYING B's L5 by razing its income bases (proto razed just 66; the winning g5 razed
#                          132). But the army-cap REDUCED razing. So cap the army ONLY t60-100 (build the L2 lead),
#                          then LIFT it so the economy-funded army is free to raze B through t100-160 (its climb
#                          window). "t100 이후엔 L2 더 올리기보다 병력으로 기지를 부숴 HQ가 L5 못 가게" -- the user's核心.
SNOWBALL_SPARE_CAP = 6   # lean offensive fist kept during the snowball window (rest of the gold -> L2). = REL_ARMY cap.
SNOWBALL_PARK_MIN = 12    # (user: "이건 상대가 수비형일 때 특히 좋다 -- 7/8 처럼 공격적인 애들과 다르게"). Require the
#                          enemy to be a SUSTAINED TURTLE: its largest stack has sat parked on its own buildings for
#                          >= this many turns (BOT.park_streak). An AGGRESSIVE opponent advances its stack -> park_streak
#                          resets -> snowball never fires (so we keep our army vs 7/8-type attackers). This is the fix
#                          for the mirror/my-bot regression: those have attack phases (park_streak low) so they no
#                          longer trip the cut; a real turtle (park_streak high) still does -> L2 economy -> L5.
# --- REL-ARMY (user: "이것도 상대적으로 판단하자 -- 상대가 내가 견제되는 만큼 뽑는게 아니면 군사력 강화를 조금 내리고
# L2 비중을 늘려라; L2가 본격적으로 생기면 장악력이 더 강해진다"). Military production is RELATIVE to the enemy's.
# proto keeps its bank near-empty because the OFFENSIVE surplus (want_spare) drains gold into raiders every
# turn (measured: avail 280-534g/turn -> the PRESS_ECON L2 path finds nothing to spend). When the enemy's army
# is CONTAINED (we already match-or-exceed its total, it is NOT out-producing a deathball) AND we are safe +
# income-ahead + not trailing the HQ climb, we trim want_spare to a lean cap so the freed gold ACCUMULATES and
# 1d PRESS_ECON converts it into L2 base income (compounding control). This trims ONLY the offensive surplus;
# the matched DEFENSIVE garrison (total_need / mil_switch) is untouched -> rush-crack invariant preserved. It
# is self-reverting: the instant the enemy out-produces / out-armies / out-climbs us, the gate drops and the
# full offensive surplus returns. income-ahead keeps g4/g5 (income-BEHIND razing-deny wins) OFF -> #26-safe.
# Rollback: REL_ARMY=0. Efficacy is anti-predictive (a real economy-contesting opponent) -> re-submission only.
REL_ARMY = 0             # ROLLED BACK: validation (10-agent workflow) showed the lever bites (army->L2 shift
                         #   confirmed) and rush-crack stays 0, BUT it regressed 3 games vs my-bot (the only
                         #   competitive peer), ALL at M.K>=13: KP6 mirror LEFT_WIN->RIGHT_WIN (loss!), KP7
                         #   (g4-class wide) LEFT_WIN->DRAW, KP9 (g5-class wide) DRAW->RIGHT_WIN. On the WIDE
                         #   maps (= eval games 4/5) the winning doctrine is razing-DENY (a big offensive army
                         #   grinds the enemy economy to deny its L5); cutting that army for L2 turns those
                         #   wins into draws -- the exact opposite of the goal. "cut army for L2" only helps on
                         #   small/passive maps, and even there vs a competitive peer (KP6 mirror) it lost. Kept
                         #   as a documented knob. To revisit: K-gate to M.K < WIDE_K AND `not _climb_push`, then
                         #   re-run relarmy-validate. Re-enable with REL_ARMY=1 only after that passes clean.
REL_ARMY_MARGIN = 4       # enemy total army may exceed ours by up to this and still count as "contained" (our
                          #   L5 turret + matched garrison covers a small edge -- same slack as MATCH_TOTAL_MARGIN)
REL_ARMY_SPARE_CAP = 6    # lean offensive fist we still keep while investing the rest in L2 (a chip raider for
                          #   pressure/scouting; NOT a full standing army). Raise if local outcomes regress.
# --- WIN-PUSH (the user's "공세를 추가": convert a territory lead into a WIN instead of a draw) -------
# Confirmed draw mechanism (4/5/6, timeline forensics): we OUT-BASE the enemy and reach L5/30 (safe),
# but we UNDER-ARMY it because gold is banked for the L5 climb + idle reserve -- so we have no surplus
# to attack with, the enemy is never denied, and it completes its own L4->L5 (3600g) late (t160-189) ->
# both L5/30 -> DRAW. WIN-PUSH breaks this: when we hold a DECISIVE base lead and home is safe, release
# the banked climb reserve into ARMY (out-produce the enemy) -- the existing backdoor then routes that
# surplus to siege the enemy's bases continuously, denying the gold it needs for L5 (-> our L5 > its L4).
#   Tiebreak-SAFE & self-limiting (the structural guards that make this not a coin-flip):
#   * not _behind_hq: if the enemy out-climbs our HQ level, _winning turns OFF -> the reserve is restored
#     and the climb resumes -> we never lose the tiebreak by level. (self-correcting)
#   * enemy_bases >= WIN_ENEMY_BASES: a low-economy RUSHER has nothing to deny, so _winning never fires
#     and it just gets the clean climb-win -> home-defense / rush path is byte-untouched.
#   * not _fortress: once a real wave forces the late fortress, survival outranks pushing (reserve back).
#   * turn >= PRESSURE_TURN, base_lead >= WIN_BASE_LEAD(3): only a DECISIVE, established lead (a +2 bar
#     scatter-lost vs my-bot in earlier tuning; +3 = only when genuinely dominating -> no even-match regress).
WIN_PUSH = 0             # DISABLED (confirmed net-negative): re-submission showed it REGRESSED games 7 & 8
#                          (previously WON). Mechanism (user's diagnosis, harness-confirmed): dropping the
#                          climb reserve into army drained the bank every turn, so the HQ never accumulated
#                          enough for its next upgrade -> g7 stalled at L3 instead of climbing to L4 (which
#                          beat the enemy's L3) -> WIN turned to DRAW. On these tight maps the win comes from
#                          climbing ONE HQ level above the opponent; ANY gold diverted to offense costs that
#                          climb (the FLEE-fix regressed g7 the same way). Kept as a knob (off) for reference;
#                          breaking the 4/5/6 draws needs offense that does NOT touch the climb gold (e.g.
#                          POST-L5 surplus only) -- the resource-diverting kind is -EV here.
WIN_BASE_LEAD = 3        # out-base the enemy by >= this many BASES to trigger the push (decisive lead only)
WIN_ENEMY_BASES = 2      # AND the enemy must hold >= this many bases (a real economy to deny)
WIN_FORCE = 12           # army surplus to fund while winning (true surplus on top of total_need; backdoor-routed)
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
# --- FINISHER (3rd-submission forensic, g7/g8 DRAWS the user called out: "후반에 상대 HQ를 터뜨릴 수 있었는데
#     안 터뜨린다"). g7 ended A 16w/5b vs B 4w/0b, g8 A 20w/4b vs B 9w/1b -- BOTH drawn on the HQ-level
#     tiebreak while the enemy stood functionally ANNIHILATED. Replay-driven worst-case sims confirm long
#     approved kill windows (g7 t184-196, g8 t176-200, vs an L2/15 HQ) that HQ_CRUSH=0 left on the table;
#     worse, with 0-1 enemy bases left the backdoor has NOTHING to raze, so the fist just idled (g7 t192+
#     tgt=-1). FINISHER re-arms the HQ assault ONLY in that annihilation end-state, with the failures that
#     killed old HQ_CRUSH each addressed:
#       * stale-snapshot suicide -> the sim re-validates EVERY turn (flips false -> the march stops), and
#         it adds PHANTOM defenders = what the enemy can TRAIN during our march ETA from its live income
#         (the old t130 read assumed the world froze for 10 turns);
#       * "threw the army at a healthy turtle" -> gated on annihilation (enemy bases <= FINISH_MAX_BASES)
#         AND decisive dominance (our army >= FINISH_DOM_F x theirs) AND a real fist (>= FINISH_MIN);
#       * abandoning home -> home_safe/on_hq gates unchanged, guard stays via 2a.
#     Nothing fires in even games (dominance+annihilation never both hold) -> mirror/rush untouched.
FINISHER = 1
FINISH_TURN = 140         # late-game only (the observed kill windows open ~t150-185)
FINISH_MAX_BASES = 1      # "annihilated" = the enemy holds at most this many bases (nothing left to raze)
FINISH_DOM_F = 2          # ...and our TOTAL army is at least this multiple of its total
FINISH_MIN = 5            # ...and the committed fist is a real body of force
FINISH_PHANTOM_CAP = 8    # cap on simulated mid-march enemy reinforcements (income-bounded anyway)
# --- FINISH-SHARP (verified small-map draw, forensic on 선공/1(2) K11 t169): the default finisher hides a
#     PROVABLE kill because its worst-case sim is over-conservative in THREE ways -- (1) it front-loads all
#     _fph phantom defenders into the initial def_hps (they cannot all be present turn-1; the enemy trains
#     them one/turn), (2) it caps the sim at MAX_CRACK_TURNS=12 while the true endgame horizon is 20+ turns,
#     and (3) it gates on FINISH_MAX_BASES=1 / FINISH_DOM_F=2 before the sim even runs. On the SMALL maps
#     (K < WIDE_FORCE_ANCHOR) where the army-to-HQ ETA is short, a genuinely reachable slow-grind kill (선공/
#     1(2): 31 v 18, cracks at siege-turn ~14 with staggered relief) is thereby suppressed -> DRAW. FINISH_SHARP
#     re-checks the SAME referee-exact _sim_crack but with the phantom as STAGGERED ARRIVALS (its unused
#     `arrivals=` param) and the TRUE remaining horizon, on the reachable whole-army pool, with relaxed pre-gates
#     -- the SIM (not the ratio) is the gate. SAFETY: (a) K < WIDE_FORCE_ANCHOR keeps g4(K15)/g5(K19) byte-
#     identical even when ON; (b) only ADDS firings (guarded `not _finisher and not _finisher_all`) so OFF =
#     byte-identical everywhere; (c) home_safe + not siege_recall + not _fortress + FIN_HOLD_BEHIND guard the
#     forward commit so it never strips a threatened home (the relaxed annihilation gate no longer implies a
#     harmless enemy); (d) the FULL move bill must clear the reserve up front. Small-map forward commits are
#     the most ANTI-PREDICTIVE surface (memory), so effect is re-submission-validated; OFF by default.
FINISH_SHARP = 0
FINISH_SHARP_DOM_F = 1.5   # relaxed dominance (main finisher needs 2.0); the staggered-relief sim is the real gate
FINISH_SHARP_MAX_BASES = 6 # allow firing vs an economy still holding bases (main finisher needs <= 1)
# --- CLUSTER-TARGETING (3rd-submission g4 draw, the user's "상대 기지 분포가 많은 쪽으로 공격해야"): the
#     roam key `hops(fist->base) - hops(base->enemyHQ)` chases whichever single base is near-and-forward --
#     in g4 the enemy kept REBUILDING a lone far-from-its-HQ base up top (region 71, y=+9321), the key
#     rewarded it twice (near AND forward), and the fist commuted top<->bottom all late game while the
#     DURABLE 3-base bottom cluster (53/75/80) was never worked. Add a cluster bonus: a candidate with more
#     live enemy bases within CLUSTER_R hops sorts earlier, so the fist parks itself where razing one base
#     puts it a short march from the NEXT (the user's "지속적으로 짧은 거리로 공격"). Flag-gated; the memory
#     invariant "don't touch _pick_target" refers to SKIPPING candidates (the flee-skip regression) -- this
#     only re-ORDERS them, every candidate still crack-checked in order. Rollback: CLUSTER_TGT=0.
CLUSTER_TGT = 0           # ROLLED BACK (user, 4th submission): the re-ordering rippled into OTHER matchups
#                           ("2번을 넣으니까 다른게 영향을 받아버리네") -- FINISHER alone is the validated keep.
#                           =0 restores the exact old near-and-forward ordering (rollback equivalence proven).
CLUSTER_R = 3             # "nearby" = another live enemy base within this many hops of the candidate
CLUSTER_W = 2             # sort-key bonus (in hops) per nearby base -- outweighs a 2-hop-longer march per neighbor
# ==== USERBOT-META PACK (2026-07-02, 유저봇 본선 6전 전패 포렌식; memory: userbot-bracket-losses) =========
# The user-bracket bots play a different meta than the 8-AI ladder: they out-EXPAND us early (+1~2 bases by
# t40-60, one reached 17), keep CONTINUOUS 4-8-unit pulse harassment (we suffered 24-66 siege while dealing
# LITERALLY 0 in three games), and climb steadily while we sat at L1-L2 (two games ended with our HQ still
# L1 at t200 / HQ destroyed). Five flag-gated counter-levers; all =0 -> byte-identical pre-pack build.
FAST_EXPAND = 0       # ABLATED OFF: dispatch-at-150g starved the rush defense (2L!) and the peer climb (0W7L my-bot) -- the expansion-race answer needs a different shape           # (1) win the opening land race: dispatch claimers BEFORE the full base cost is
#                           banked (income covers it during the 3-5 turn march) and fund MORE claimer bodies.
FAST_EXPAND_LEAD = 150    # dispatch while gold >= base_cost - this (arrival income closes the gap)
FAST_CLAIM_TRAIN = 2      # claimer-body funding floor while unclaimed strongholds remain... (3 broke the
#                           rush/mirror economy in ablation -- the extra body's train+upkeep starved defense)
FAST_CLAIM_TURN = 90      # ...until this turn (after that the old 1-2 funding resumes)
EXPAND_AHEAD = 1          # 8(2).txt (user: "인원 많은데 확장 공격적으로"): FAST_EXPAND is ablated OFF because
#                           dispatch-at-150g starved rush defense + climb UNCONDITIONALLY. But that left a real
#                           hole -- mid-game, BASE-behind + UNIT-ahead + home_safe, a claimable CONTESTED stronghold
#                           (empty, in our band) sat un-taken for 16 turns (8(2) t87-102 region 28) because gold
#                           went to TRAINING (already 18v11 units) and never cleared the cost+reserve brake -> the
#                           enemy built it (t104) -> we stayed 3 bases vs 6 -> draw. Fix: ONLY when unit-ahead (spare
#                           bodies we don't need for defense) AND base-behind AND home_safe, drop the claim brake to
#                           GOLD_FLOOR so a lone claimer is dispatched to STAND on the stronghold NOW -- that alone
#                           blocks the enemy build (referee: cannot build with an enemy warrior present) and it
#                           becomes a base when income funds it. Rush-safe by the home_safe gate (collapses the
#                           instant a threat closes -- unlike blanket FAST_EXPAND). EXPAND_AHEAD=0 => byte-identical.
EXPAND_AHEAD_MARGIN = 2   # require my_warriors >= enemy_warriors + THIS (a real, spendable unit surplus).
PULSE = 0                 # ROLLED BACK (user, real bracket matches): pack live-tested and pulled -- see DEF_CAP note                 # (2) continuous pulse harassment, econ_lead NOT required (the losses show the old
#                           "only raid from a base lead" gate = structural pacifism exactly when behind).
#                           Rides want_spare (still trimmed below the banked HQ upgrade -> tiebreak-safe).
PULSE_TURN = 30           # standing small-squad funding from here
PULSE_FORCE = 6           # the squad size funded
PULSE_HP_F = 0.55         # chip-and-run: disengage the chip when fist hp-sum < this fraction of commit hp
CHIP_LOCK = 5             # turns per chip commit (then rotate to the next softest base = pulse pressure)
EARLY_L2 = 0          # ABLATED OFF: the 600g hold delayed bases 3+ -> peer income race lost (1W4L3D my-bot); the bracket L1-forever pathology needs a narrower fix              # (3) guarantee HQ L1->L2 early: after EARLY_L2_BASES bases stand, HOLD 600g for
#                           the HQ before building/claiming more (two losses ended with a t200 L1 HQ).
EARLY_L2_BASES = 2
DEF_CAP = 0               # ROLLED BACK (user, real bracket matches): vs an HQ-mass-pump rush we did NOT match-train and lost big. Root: the defender-side sim caps the garrison from a SNAPSHOT wave -- it does not model the enemy TRAINING 1-3/turn DURING the assault, so the real wave outgrows the capped garrison. Needs a production-aware model before re-arming.               # (4) cap the matched garrison by DEFENSE MATH (the smallest body count that
#                           SURVIVES the worst-case wave storming our HQ, referee-exact defender-side sim +
#                           slack) instead of 1.15x the enemy's TOTAL army -- 1(3) matched a boomer to 59
#                           bodies (118g/turn upkeep!) and never banked L3. Once the garrison suffices,
#                           training stops, the bank fills, the climb resumes.
DEF_CAP_SLACK = 3         # bodies beyond the min-survivable garrison
DEF_CAP_HORIZON = 30      # defender-side siege sim horizon (a wave that can't crack us in 30 turns won't)
ETA_CRACK = 0         # ABLATED OFF: scheduling EVERY enemy body as timed relief reads any army-keeping opponent as uncrackable -> razing collapsed to 0 vs my-bot (0W6L2D); precision became paralysis. PULSE+DEF_CAP without it = 6W2L (BETTER than baseline)             # (5) precision siege math (the user's spec): when evaluating a crack, schedule
#                           enemy REINFORCEMENTS by ARRIVAL TIME relative to our fist's own march ETA --
#                           "we arrive at T, their relief lands T+k, can we finish before it?" -- instead
#                           of the fixed 1-hop snapshot (which both missed real relief AND over-counted the
#                           HQ-cluster garrison as instantly present).
ETA_GRACE = 4             # count relief that can join within this many turns of our arrival (farther units
#                           can't affect a short siege; chip-and-run covers the rest)
# ---- USERBOT STEP-1 (2026-07-02, 팩 전패 3~8.txt 포렌식 대응; '하나씩 추가' 독트린) ---------------------
TRAIN_RESCUE = 1          # SURVIVAL TRAINING OUTRANKS THE CLIMB BANK while the HQ is still LOW-LEVEL and a
#                           latched threat stands. The #1 killer in the pack losses: user bots scout early
#                           (t19-30) -> threat latches -> mil_switch banks the 600g HQ upgrade forever on a
#                           poor economy (gold 150-395 < 600+120) -> training FROZE for 25-80 turns (3.txt:
#                           L1 HQ one-shot by a 12-wave at t76 with tr=0 since t50; 8.txt: 0 warriors + gold
#                           pinned at 170 for 80 turns). The existing wave-response unfreeze waits for the
#                           stack to CLOSE within the detection gate -- right for an L3+ fortress with real
#                           hp/turret, FATAL for an L1/L2 HQ (train cap 1/turn: by the time the wave closes,
#                           ~4 bodies stand). Rescue: while hq.level <= RESCUE_HQ_MAXLVL with a latched threat
#                           and the army below the garrison target, bypass the stack-distance and behind-hq
#                           gates and train every body we can afford (reserve-free). L3+ keeps the proven
#                           bank-first behavior untouched (the g7/g8 "garrison stole the climb gold" stall
#                           lives there).
RESCUE_HQ_MAXLVL = 2      # rescue only while the HQ is this level or lower (the one-shottable window)
# ==== V2 RESET (2026-07-02, 사용자 지정 베이스라인 재출발 + 신규 패배 g1/g2 포렌식) ========================
# The user reset the campaign to THIS build ("여기 코드에서 다시 천천히") and supplied two fresh bracket
# losses played by it (fidelity 0, we = RIGHT in both). Four flag-gated levers; all = 0 restores the
# byte-identical reset baseline (backup proto_v2_base.py).
SPEND_LOG = 0             # dev instrumentation: per-turn spend ledger by category (expand/base_up/hq_up/
#                           train/moves) to stderr. Pure logging -- decisions untouched. Keep 0 for
#                           submission (referee stderr noise); the offline twin is scratchpad/spend_ledger.py
#                           which reconstructs the same ledger for BOTH sides from any replay.
L2_SAFE = 1               # (g1, N109/K17 tiebreak loss, the user's "L2를 상대에게 가까운 위치에 = 아주 큰 패착"):
#                           every base-upgrade loop ordered candidates by RAW REGION NUMBER -- and region
#                           indices run left(A HQ=0)-to-right(B HQ=N-1), so as RIGHT we upgraded the bases
#                           NEAREST THE ENEMY first. g1 receipts: our L2s r43@t86/r54@t90/r56@t99/r65@t108
#                           were sieged at t108/93/99(!! same turn)/116 -- all four razed, 2400g donated,
#                           and A REBUILT its own bases on 43/65/100 (t127-151). A side-symmetric fix:
#                           order by hops-to-OUR-HQ (safe rear first) and SKIP any base not strictly on
#                           our side of the midline (hops to enemy HQ must EXCEED hops to ours) -- an L2
#                           is a 600g compounding asset only if it SURVIVES 40+ turns.
RUSH_BRAKE = 1            # (g2, N75/K15 t21 HQ 함락, the user's "기지 탐욕을 캐치해 병력으로 막아야"): we spent
#                           500g start bank on TWO bases (r60@t3, r68@t11) while A trained 4 extra bodies
#                           (t4-7) and marched a 6-pack straight at our L1 HQ (visible advancing from t8,
#                           arrived t15, HQ dead t21). TRAIN_RESCUE fired t13 but the bank was already in
#                           base 68 -- one train (t16) total. The brake: in the opening window, when an
#                           enemy pack (>= RUSH_MIN) has been CLOSING on our HQ for ADV_STREAK straight
#                           turns and our reachable defenders alone cannot match it, FREEZE all economy
#                           spends (base build 1b / base upgrades 1d-1g / claim dispatch 2b) and latch
#                           threat_army so TRAIN_RESCUE pours the whole bank into bodies instead. The
#                           counterfactual math for g2: skipping base-68 funds trains from t11 (cap 1/turn)
#                           -> ~7 defenders on the HQ by t15 vs the 6-pack -> siege/turn = 6 - defenderHP
#                           = 0 -> holds trivially.
RUSH_BRAKE_TURN = 40      # opening window only; past it the normal threat machinery owns defense
ADV_STREAK = 2            # "committed" = the pack's hop-distance to our HQ strictly decreased this many
#                           consecutive turns (a roaming/patrolling group flickers; a beeline never does)
EXPAND_RHYTHM = 1         # (replays3 정량화: 3호 기지가 우리 t60~159 vs 상대 t21~23 -- 40~130턴 확장 공백이 모든
#                           패배의 공통 상류): keep a BASE-COUNT SCHEDULE -- 3rd base by ~t32, then one per
#                           ~22 turns, capped by our claimable band -- and while BEHIND schedule give
#                           expansion first claim on gold: fund claimer bodies like WORKERS (reserve-free,
#                           they pay back +13/turn), drop the 2b dispatch brake to cost+GOLD_FLOOR (the
#                           full-reserve brake was the 40-turn stall), never while rush-braked/concentrate.
EXPAND_EVERY = 22         # one additional scheduled base per this many turns after the 3rd (t32)
EXPAND_UNTIL = 100        # schedule pressure ends here (late bases barely pay back; normal gates resume)
EATER_RELIEF = 1          # (g1 t93-129: 3-4-unit eaters razed ALL TEN of our bases while 12-16 warriors
#                           stood on the HQ node): the relief detector keys on the GLOBAL largest enemy
#                           stack -- in g1 that was the enemy's HOME GARRISON (4@its HQ, d12), so the
#                           actual eaters (3 bodies ON our base, d2 from our HQ!) never became the relief
#                           target, and _relief fired ZERO times all game. Fix: detect the largest enemy
#                           group standing ON ONE OF OUR OWN BUILDINGS directly and relieve THAT (same
#                           win-the-fight guards: our army + that base's turret must cover it). This is
#                           the #39 RELIEF doctrine with the stack-identity bug removed -- NOT the
#                           rejected FORWARD-INTERCEPT (no pre-emptive forward holds; we only fight units
#                           already razing our buildings).
# ---- V2 ROUND-2 (2026-07-02, 첫 승리 라운드 4승1무 포렌식: 4번 무승부 + 6/7번 승리 품질) ----------------
TGT_VALUE = 1             # (g4 DRAW): the raid target key had NO value term -- it is de-facto "nearest
#                           crackable", so B's 300g L1 REBUILDS (71, 2 hops from our forward base) decoyed
#                           the fist forever while B's 1900g L3 income engine (53) was NEVER attacked in
#                           200 turns (SIEGE@53 = 0; counterfactual: razing 53+75 denies ~5000g -> B misses
#                           its L5 -> WIN instead of DRAW). Adds to the key: high LEVEL first (engines),
#                           DAMAGED-building finish bonus, and a repeat-raze DECOY discount per region.
#                           Plus the SIEGE LATCH: a live committed target that is already DAMAGED may not
#                           be dropped by branch flapping (t129: MULTI_PRONG flapped at rf 9/10 and walked
#                           9 units OFF a 1-hp L3 -- one siege point from killing 1900g).
TGT_LVL_W = 2             # key bonus (hops) per building level
TGT_DMG_BONUS = 3         # key bonus for a damaged building (finish what we started)
TGT_REBUILD_W = 2         # key PENALTY (hops) per time this region was already razed (decoy discount, cap 3)
FLEE_FIX = 1              # (g6 WIN quality + g4): the raid EVASION counts a PARKED enemy HQ garrison as a
#                           stopper by pure distance snapshot -- base 22 sits exactly FLEE_RADIUS from B's
#                           HQ, so stepping onto it pulled the parked 13-body garrison into radius and the
#                           fist fled 9+ cycles (commit/march/flee/watch, 6-7 turns each) while the honest
#                           referee-exact sim cracks the base in 2 turns EVEN IF the garrison sorties
#                           instantly. User doctrine: units sitting on their HQ are not a threat until
#                           they MOVE. Fix (a): units standing ON the enemy HQ tile are not stoppers while
#                           the fist is outside the HQ cluster (they count again the moment they step off
#                           -- 1-turn detection lag vs a 3-turn march = safe). Fix (b, g4): the
#                           cluster-TOTAL flee applies only when the TARGET is in the cluster --
#                           transiting a cluster-adjacent corridor (node 72) aborted 3 marches to
#                           non-cluster targets and burned 74% of t113-151 on movement.
FLEE_TURRET = 1           # 5(2) (user: "피할 필요 없는 싸움인데도 피하네 -- 기지도 있고 우리 노동자도 전투 안한다는
#                          듯이 계산"). The raid flee compared _stop (enemy near the fist) vs the RAW fist count,
#                          ignoring OUR home-defense bonus when the fist stands ON/adjacent our own building: the
#                          referee fights FOR the owner with turret + EVERY present warrior (workers included --
#                          "working" is a separate evening phase; all warriors fight in day combat). So the fist
#                          fled base defenses it would actually WIN. Credit _home_turret(frm) + the friendly
#                          warriors present at frm but NOT in the fist (the base garrison/workers) -- exactly what
#                          the home/relief paths already do (2411/2704/2740). flag=0 -> byte-identical.
COMMIT_CRACK = 1          # 5.txt/6.txt (user: "연속적으로 공격을 이어가라 -- 상대가 HQ에서 나오는게 아니면 반응할
#                           이유가 없다, 위험한 병력 숫자인지 판단하는게 제일 중요"; the "쉐도우 복싱" fix). FLEE_FIX(a)
#                           only spares the PARKED garrison while the fist is OUTSIDE the cluster; approaching a
#                           base NEAR the enemy HQ (g6 bases 22/47/52, all 2-4 hops from HQ) the fist is IN the
#                           cluster, so the crude _stop TOTAL re-counts the parked ~10-body garrison (stop=14-18
#                           vs only 4-6 enemies actually out) and the fist flees a base it could raze -> never
#                           reaches the FLEE_FINISH/_can_crack decision -> shadow-boxes the whole midgame, razes
#                           ~nothing, both climb -> DRAW. But _can_crack is the PRECISE danger judgment the user
#                           asks for: it ETA-schedules the whole convergeable garrison as ARRIVALS and requires
#                           CLUSTER_KEEP_F(70%) of the fist to survive. Forensic (g6): at 6/7 flee points the
#                           LIVE raid target reads _can_crack=CRACK yet we fled the count. Fix: for a LIVE
#                           committed BASE that the arrival-aware sim deems crackable, trust it over the blunt
#                           count -- do NOT flee, keep committing. Never suicidal (the sim refuses a bad trade);
#                           HQ targets / uncrackable walls / a shrunk remnant still flee normally. flag=0 ->
#                           byte-identical (the _stop veto is unchanged). Rush-safety = the hard validation gate.
#                           REFINED (assembly-aware, user "이동+공격 총 턴 계산"): the sim must run on the ASSEMBLED
#                           fist (units already ON/adjacent the base), NOT the whole marching force -- the referee
#                           fights whoever is THERE, so a full-force read over-counts still-marching bodies (g6
#                           t99/t105: 0 units at the target yet the FULL read said crackable -> committing a
#                           spread fist that gets chewed up piecemeal = why the naive version lost the mirror).
COMMIT_ASSEMBLE_HOPS = 1  # only count units within this many hops of the target as "arrived" for the commit sim.
COMMIT_MIN_ON = 3         # and require at least this many ARRIVED -- a 1-2-body vanguard must not hold the commit.
FORT_VELO = 1             # (g7 WIN quality): FORTRESS_TURN=140 recalled our 8 forward bodies ON THE CLOCK
#                           while the enemy 11-stack had been PARKED on its own HQ (d8) for 15 straight
#                           turns -- the recall emptied the path and the stack then one-shot three of our
#                           bases (21/5/26) and STOLE two strongholds. The fortress HOLD (recall +
#                           offense-off) now requires the stack to be actually PRESSING: advancing this
#                           turn, inside the approach gate, in our half, or on our HQ. The fortress CLIMB
#                           priority is untouched.
RELIEF_ETA = 1            # (g7): our beyond-midline bases are structurally outside every defense gate --
#                           the relief midline test fails there, FORWARD-PUSH sees no invader (stack still
#                           on its half while marching), and an L1 base dies to an 11-stack in ONE turn so
#                           the stack-on-our-base branch never sees it alive. New arm: a WAVE_STACK_MIN+
#                           stack ADVANCING within 2 hops of one of OUR bases that we can beat (army +
#                           that base's turret >= stack) -> relieve AT THE BASE (fight on our turret
#                           ground; a few bodies of HP zero the siege). The midline cap applies to the
#                           BASE (ours by definition), not to the stack's position.
INCOME_FLOOR = 1          # (g7, 사용자 지적 그대로): t121-140 our income was 3.8x B's and we trained FOUR
#                           bodies to its ELEVEN -- the climb reserve (1200g) froze training and the only
#                           escape valve tops out at "match the enemy count". A rich economy must convert
#                           gold into a SURPLUS army, not parity: while a threat is latched and our
#                           work-capacity is >= INCOME_RATIO x the enemy's, raise the army target to
#                           enemy_total + INCOME_EDGE + base-worker need AND fund that deficit
#                           reserve-free (income pays for it: 15g/slot vs 2g upkeep). The BOOM_MATCH
#                           lesson applied: raising the target without opening the wallet does nothing.
#                           SWARM GUARD (ablation: 4W->4D, INCOME_FLOOR sole culprit): fires only while a
#                           WAVE_STACK_MIN-grade (10+) mass actually stands on the board -- a swarm's
#                           dispersed pressure must not divert the raid fist into a standing home army.
INCOME_RATIO = 1.5
INCOME_EDGE = 4
CLIMB_HOLD = 1            # (g1: L2s r43/54/56/65 raided the HQ-L3 bank 4x600g while _behind_hq -- gold
#                           peaked 792, L3 costs 1200, we finished the game at HQ L2 vs L5): while we
#                           TRAIL the enemy HQ level and our HQ is not maxed, every base upgrade must
#                           clear cost + THE NEXT HQ STEP on top of its usual cushion, and 2b claim
#                           dispatch holds the same step once we already out-base the enemy by 2+ (g1
#                           opening: two 1b builds t70/72 delayed HQ L2 by 11 turns while LEFT hit L3
#                           t81 and doubled its train cap). BANK_CLIMB covers K<15 only; this is the
#                           side-agnostic, all-K version of the same doctrine.
ENDGAME_FINISH = 1        # ENDGAME FINISH-PUSH. Both draws were DOMINATED games we failed to convert because
#                           the "keep every base worker" rule dissolved the fist into economy duty exactly at
#                           the finish window: 4.txt rf 9->0 (t150-190, 10 bases) -> razing stopped -> enemy's
#                           last L5 landed at exactly t200; 7.txt rf 0 at the t190 kill window vs a 3-warrior
#                           remnant AND the pulse spare ate the gold that would have won the HQ-level tiebreak
#                           (t200 gold 1150 vs L3=1200). Two coupled moves, one gate (turn>=FINISH_TURN, home
#                           quiet, army >= ENDGAME_DOM_F x enemy): (1) RELEASE base workers -- closest-to-the-
#                           enemy first, HQ guard untouched -- until FINISH_KEEP bodies stay free as the fist;
#                           (2) vs a <=ENDGAME_REMNANT_BASES remnant, cap the offensive spare funding so the
#                           gold banks the tiebreak climb instead of a redundant 120g body.
ENDGAME_DOM_F = 1.5       # army dominance to open the finish-push (2.0 missed 4.txt's t150-180 deny window)
FINISH_KEEP = 8           # bodies kept free of worker duty for the fist
ENDGAME_REMNANT_BASES = 1 # spare-cap arm: enemy reduced to this many bases = annihilated remnant
ENDGAME_SPARE_CAP = 2     # offensive spare funding cap vs a remnant (bodies exist; gold -> climb)
# ---- USERBOT STEP-2b (2026-07-02, 4(1)/7(1) 재제출 포렌식: '이긴 판 마무리' 2차) --------------------------
# 4(1) flipped draw->LOSS: the released fist DID deny the enemy L5 (4 bases -> 1, they stalled at L4) but our
# own climb stalled at L3 -- ~1400g leaked into 1d base upgrades + 1b rebuilds at t150-160, and we finished
# t200 at L3 + 2046g, 354 short of the L4 that would have re-drawn (L5 would have WON). 7(1) drew AGAIN 95g
# short of the L3 tiebreak, with a 7-body fist parked "uncrackable" next to a 5-warrior remnant while 13
# bodies TOTAL would crack it (the user's "남는 병력 모두 투자" / "병력이 나뉜다").
ENDGAME_CLIMB_LOCK = 1    # while the endgame gate is on and the HQ below L5: base upgrades (1d) are OFF and
#                           base builds/claims (1b/2b) must clear cost + the NEXT HQ step -- every gold banks
#                           the level race the tiebreak is decided by. The fist keeps razing regardless.
ENDGAME_LVL_TGT = 1       # target selection (user): while the endgame gate is on, crackable HIGH-LEVEL enemy
#                           bases sort first (-LVL_TGT_W x level hops) -- razing an L3 base cuts 3x the income
#                           of an L1 and torches the gold they are saving for their own HQ. Gated on
#                           BOT.endgame ONLY (never plain deny_mode) so ENDGAME_FINISH=0 keeps _pick_target
#                           byte-identical (the '_pick_target 손대지마' invariant holds for all other states).
LVL_TGT_W = 2             # hops of sort-key bonus per base level
ENDGAME_ALLIN = 1         # REMNANT ALL-IN: enemy down to <=ENDGAME_REMNANT_BASES bases, home quiet, dominance
#                           met, and the referee-exact sim says ALL our warriors TOGETHER (workers included,
#                           phantom reinforcements counted) crack the enemy HQ -> send every body at it and
#                           end the game. 7(1): 8-fist uncrackable forever, 13-total crackable = the miss.
# ---- V2 ROUND-3 (2026-07-02, 재제출 4(1) 무 / 5(1) 승->패 포렌식) ----------------------------------------
# 5(1) flipped WIN->LOSS: _finisher_all fired t149/t175 and mobilized the WORKERS into the charge -- but the
# sim assumes every body arrives TOGETHER while reality trickles them in 1-3/turn from 2-14 hops out (35 dead,
# SIEGE@enemy-HQ = 0 all game, income 210->15), and gold ran dry after 19 of 36 MOVE orders so even the launch
# itself was half-strength. 사용자 독트린(이번 세션): 워커까지 모두 동원하는 최후의 러쉬는 t190~200의 'HQ 흠집용'
# 전략이지 t150의 수단이 아니다 -- 보급(턴골드)이 군력 유지와 지속 공격의 전제 (t120에 L3까지 211g 남았었고, 그
# 골드만 지켰어도 최소 무승부·L4면 승리였다).
LATE_ALLIN = 1            # _finisher_all (workers included) fires only from ALLIN_TURN, only with bodies that
#                           can actually REACH the enemy HQ by game end (the rest keep working = supply), and
#                           only if the FULL move bill clears the reserve (no more 19-of-36 partial launches
#                           trickling 1-3 bodies/turn into a turret). Rollback: LATE_ALLIN=0.
ALLIN_TURN = 190          # the user's stated window for the final everyone-included rush (190~200)
GAME_TURNS = 200          # ladder games end at t200 (arrival window for the all-in pool)
INC_PARKFIX = 1           # 5(1): B PARKED 13-16 bodies on its own HQ ALL GAME (never advanced once) -- that
#                           parked garrison latched threat_army and kept INCOME_FLOOR retraining dead pulse
#                           bodies (34 trains = 4080g, reserve-free) which both bypassed the L3 climb bank AND
#                           re-armed the 2x dominance for the SECOND suicide charge. FLEE_FIX doctrine ("units
#                           sitting on their HQ are not a threat until they MOVE") applied to the income-floor
#                           gate: a stack parked ON the enemy HQ and not advancing does not open the pump.
MP_FALLTHRU = 1           # 4(1) drew AGAIN -- 사용자 진단 '로직 중복' 확증: MULTI_PRONG owned 15 of the 16
#                           peak-force turns (rf oscillated 7<->14 across MIN=10) yet folded to a SINGLE prong
#                           every one of them (spread contribution: zero) -- a second, value-BLIND single-fist
#                           targeter (key = hops(my_hq,r)) that reset BOT.raid_tgt each turn, destroying
#                           _raid_commit's committed target (9 turns of zero siege flapping 53<->80, 4 turns
#                           on a 300g rebuild decoy the value key ranks LAST; the L3 engine 53 died at 3hp).
#                           Fix: when the fold collapses below 2 distinct targets, _two_front_raid DECLINES
#                           (returns False) and the turn falls through to _raid_commit -- MP only ever owns a
#                           GENUINE spread; the value key / siege latch / commit lock own single-fist turns,
#                           and raid_tgt is only reset when MP actually dispatches.
MP_VALUE = 1              # when MP does spread, its target ordering gains the same value terms as
#                           _pick_target (level / damaged / rebuild-decoy, TGT_VALUE weights) so a genuine
#                           spread still prefers engines over decoys. Ordering only; fold logic untouched.
# ---- V2 ROUND-4 (2026-07-02, 재제출 신규 4.txt 무 / 5.txt 패 포렌식) --------------------------------------
# RULE (referee, testing-tool.py 1443-1450): the TURN_LIMIT tiebreak is (HQ alive, HQ CURRENT HP) -- level
# is only the max-hp proxy (10/15/20/25/30) and an UPGRADE heals to full. The endgame currency is HP.
# 신규 5.txt (L3/20 vs L4/25 패): t168 FINISHER가 gold 325로 22기 중 19기만 부분발진(자기 sim으로도 19기=전멸
# 판정) -> 19기 전멸 -> 잉여가 FINISH_KEEP 밑으로 -> t174-176 _eg_gate 워커 릴리즈(사용자 목격 "노동하던
# 인원들이 튀어나와") -> 소득 1635g 증발 -> L4(2400)를 112g 차이로 미달. 신규 4.txt (L4/25 = L4/25 무): deny
# 피스트가 기지 80으로 가는 유일 경로(82=B HQ)를 지나며 t136 시즈 8점(B HQ 15->7hp)을 넣고도 타겟래치가 기지
# 80으로 걸어 나감(2턴만 머물면 격파=완승) + t186에 8기(4홉, 이동비 80g)를 B HQ에 보냈으면 B의 t192 L4 업글
# 자체가 차단(referee: 적 워리어가 있는 건물은 UPGRADE 불법)돼 승리. 칩의 하방 = 현상유지 무승부(0).
EG_RELEASE_LATE = 1       # the _eg_gate worker RELEASE (need[] cut) is deferred while we TRAIL the enemy
#                           HQ level: releasing income bodies while behind on the climb dismantles the very
#                           bank the tiebreak is decided by (5.txt t174-176). While _behind_hq the release
#                           waits for ALLIN_TURN (the user's t190+ final-rush window); when we lead or tie
#                           the climb the release is unchanged (the round-2 dominant-finish role).
FIN_FULLBILL = 1          # FINISHER may not launch unless the FULL move bill (10g x every fist body not
#                           already on the enemy HQ) clears the reserve -- the same guard LATE_ALLIN has.
#                           5.txt t168: sim approved 22, gold funded 19, own sim says 19 = annihilation.
FIN_HOLD_BEHIND = 1       # no kill-shot gambles while we TRAIL the HQ level: a failed charge burns the
#                           army AND the tiebreak bank at once (t168: -19 bodies, then the release spiral).
#                           When the charge is genuinely winning we are usually ahead or even; _finisher_all
#                           (t190+, its own gates) is NOT affected -- the user's final window stays open.
HQ_SNAP = 1               # TRANSIT SNAP (4.txt t136): the fist stands ON the enemy HQ mid-march and the
#                           referee-exact sim (defenders present + train_cap-per-turn refill phantom) says
#                           the bodies ALREADY THERE crack it within HQ_SNAP_TURNS -> HOLD them (drop the
#                           march for those bodies). Killing the HQ ends the game -- no base target beats
#                           that. Re-evaluated every turn; if the read flips they resume the march.
HQ_SNAP_TURNS = 4         # snap window: 4.txt t136 referee-exact probe -- 11 bodies (52hp) on the 15-hp
#                           L2 HQ + 1 defender vs a train-EVERY-turn phantom = crack in 4 standing turns
#                           with 8 survivors (2/3-turn windows miss it; the real B trained nothing and
#                           died in 2). Worst-case-defense guarantee, re-read every turn.
HQ_CHIP = 1               # ENDGAME HP-CHIP (the user's "막판에 HQ 피를 줄이면 되는건데", now referee-load-
#                           bearing): from CHIP_TURN, when the tiebreak is NOT won on HP (enemy HQ hp >=
#                           ours, or the enemy trails on LEVEL and could upgrade-heal past us), send the
#                           arrival-window surplus to STAND ON the enemy HQ: standing there blocks its
#                           upgrade-heal outright, grinds its garrison, and every cleared defender turns
#                           attack ticks into siege = tiebreak HP. Deliberately NO crack sim -- one net
#                           siege point is enough, and the worst case is the status-quo draw. Home guard
#                           (raid_force = surplus only), our own climb bank, and the reserve are untouched.
CHIP_TURN = 185           # chip window start (arrive ~189+, the user's endgame-rush window)
CHIP_MIN = 4              # minimum chip squad (fewer cannot out-tick a garrison + turret)
CHIP_DWELL = 2            # must arrive with at least this many turns left to actually fight
CHIP_SETTLED_EARLY = 1    # R45 (6(2) ladder forensic, fidelity-0): our L5 landed t175 but CHIP_TURN=185
CHIP_TURN_SETTLED = 160   # held the window shut 15 turns; the t190 one-shot pool (22 bodies) streamed in
#                           piecemeal t192-197 and STILL blocked the enemy's L5 for 8 straight turns (their
#                           buy slipped t192->t200, landing on the literal last turn = draw). The late
#                           window exists to protect OUR climb bank (EG_UPG_REACH); once the HQ is MAXED at
#                           FULL hp there is nothing left to protect -- waiting is pure waste. Fix: a
#                           settled HQ opens the window at CHIP_TURN_SETTLED instead. Earlier open = the
#                           enemy's PRE-L5 upgrades get contested too (6(2): occupation from ~t180 blocks
#                           their L4@182 -> the L5 never even queues) and the wider arrival window lets
#                           HQ-trained reinforcements keep feeding the stream (t190: cwin=8 excludes fresh
#                           trains; t175: cwin=23 includes them). All existing guards carry unchanged:
#                           CHIP_SIM_GUARD, home_safe, on_hq==0, surplus-only pool, hp/level condition.
#                           CHIP_SETTLED_EARLY=0 => decision-identical.
CHIP_LEAN_FINAL = 1       # R43 (5(4) ladder forensic, fidelity-0): the drawing sequence measured turn by
#                           turn -- we razed the AI's LAST base t150 (36w/12b vs 16w/0b), EG_UPG_REACH
#                           correctly held the chip t185-189 to fund OUR L5 (bought t190, gold 3726->324),
#                           and at t191-192 a legal 21-body chip pool stood INSIDE the arrival window with
#                           the enemy HQ still L4 -- but the chip wallet demanded move-bill + FULL reserve
#                           incl. the 1000g HEAL cushion (1,344g vs 522g in hand) two turns after the L5
#                           purchase emptied the bank, so the pool was discarded, the army idled, and the
#                           AI bought its drawing L5 on t199 with HQ-worker income alone. A standing body
#                           on the enemy HQ makes that UPGRADE referee-illegal = the draw was two turns of
#                           wallet away from a WIN. Fix: when our HQ is MAXED at FULL hp and home is safe,
#                           the final chip pays only the RAW move bill (the DOM doctrine: "an upkeep cushion
#                           against a corpse is self-defeating"; a heal cushion for an untouched L5 fortress
#                           in the last 10 turns doubly so). Worst case = the chip's own contract:
#                           status-quo draw. CHIP_LEAN_FINAL=0 => decision-identical.
# ---- V2 ROUND-5 (2026-07-02, 재제출 6.txt L2/L2 무 / 5.txt L4/L4 무 포렌식) -------------------------------
# 사용자 지시: "배회하는 쓸데없는 움직임으로 행동 비용" 제거 + "중간중간 L2 건물로 돈 수급을 더 올려라" +
# "불필요한 명령으로 돈 쓰지 않게". 6.txt: 클러스터-플리<->재커밋 6사이클(t97-137)이 1,200g를 태워 L3(1200)
# 뱅킹을 정확히 그 금액만큼 놓침(잔고 피크 858, CF: 진동 제거시 t136 L3 = HP승) — 타겟 52는 '클러스터 밖'
# (3홉)인데 유일한 행군로의 중간 노드 41/49가 클러스터 안(2홉)이라 진입 순간 주차 가리슨 17~28기가 스토퍼로
# 계산돼 플리, 기존 raid_skip 블랙리스트는 플리 브랜치가 raid_tgt를 먼저 지워 게임 전체 등록 0회. 5.txt:
# 유료 MOVE 913건 중 588건(5,880g)이 '직전 턴에도 명령받은 같은 워리어 재과금' — referee는 원거리 목표 1회
# 명령(10g)에 스탠딩오더 무과금 행군을 제공(t185 칩 디스패치가 실증: 21건 1회 과금 후 4턴 공짜 행군). CF:
# 이동비 절감시 L4 t167/L5 t194 = 승리. 기지 L2는 t112-136(워크캡 우위 25턴)에 B의 자기-HQ 주차 12스택이
# _under_massed를 래치해 1d를 동결 — FLEE_FIX/INC_PARKFIX의 '주차 스택 != 위협' 독트린 미적용 마지막 창구.
FLEE_SKIP = 1             # a CLUSTER-flee is an "unreachable target" verdict: register the abandoned
#                           target in the existing raid_skip blacklist (SKIP_WATCH=12) so the next pick is
#                           forced elsewhere (g6: 47 fell to THREE bodies unopposed at t142-151 -- a safe
#                           target existed the whole time). Open-field flees (a real mobile relief force)
#                           stay un-blacklisted: the enemy can leave, so re-engaging is correct. Unlike the
#                           rejected _pick_target flee-skip (v2/v3, 5W->2W), this touches no selection
#                           order -- it only reacts to an ACTUAL flee, time-boxed, via existing machinery.
FAR_MARCH = 1             # stop re-billing the march: order the node FAR_MARCH_HOPS ahead (or the target)
#                           instead of next-hop -- 10g once per chunk instead of per hop (5.txt: 5,880g of
#                           re-billed hops = 1.6x the entire L5 step). Gated to UNDEFENDED targets with a
#                           2:1 flee headroom, and chunked (not full-distance) so a marching fist is
#                           uncommandable for at most FAR_MARCH_HOPS turns (the 5(1) all-in taught us
#                           multi-hop MOVE latches are irreversible -- bounded latch, bounded risk).
FAR_MARCH_HOPS = 2        # chunk length (half the billing saved, <=2-turn reaction latency -- 3-hop
#                           chunks still flipped my-bot K15 s2002 even distance-gated; 2 restores it)
FAR_MARCH_MIN_D = 5       # chunk only the LONG approach (>= this many hops out): a marching unit is
#                           uncommandable and drops out of raid_force (MOVING), so near the fight the
#                           per-hop reactivity is worth the 10g -- ablation: unrestricted chunking flipped
#                           my-bot K11/K15/K19 seeds (2 L, 1 D->L; FAR_MARCH sole culprit, off = restored)
#                           while the re-billing waste lives on 5-7-hop corridors (5.txt: 57->87).
UNDERMASS_PARKFIX = 1     # the FLEE_FIX / INC_PARKFIX doctrine ("units sitting on their own HQ are not a
#                           threat until they MOVE") applied to the LAST remaining latch consumer: a parked
#                           non-advancing enemy-HQ stack no longer freezes 1d base upgrades (_um_pressing)
#                           nor vetoes the income-ahead PRESS_L2 lean path (5.txt t112-136: 25 frozen turns
#                           exactly when the user's "중간중간 L2" window was open). The moment the stack
#                           steps off / advances, the freeze is back -- rush safety unchanged.
CHIP_SIM_GUARD = 1        # the chip's "worst case = status-quo draw" premise fails when the parked
#                           garrison out-bodies the pool (g6 t185: 33x5hp vs 35x5hp+turret -> 39 dead,
#                           siege 0, 1,080g of retrains). Referee-exact sim vs the CURRENT on-HQ garrison
#                           (no phantom -- only the grossly hopeless are filtered): fire only if the pool
#                           cracks or at least one attacker outlives the defense (= net siege is landing).
# ---- V2 ROUND-6 (2026-07-02, 구 빌드(proto_v2_base) 시절 로그 1(2)~1(6) 커버리지 감사) --------------------
# 사용자가 구 빌드 로그 5건의 지적을 제시("현재 코드에서 달라질 수 있으니 판별해 달라"). 5-에이전트 감사 결과:
# 1(4)④ 전원소집=EATER_RELIEF 커버, 1(4)③ 우세 미압박=CLIMB_HOLD가 진짜 병인(뱅크누수) 수정 — 이 둘은 기존
# 레버가 대처. 나머지는 미대처 갭 7건 (아래 각 flag). 이 게임들에서 우리=RIGHT, 구 빌드 fidelity 0.
CLAIM_PARK_RELEASE = 1    # 1(2) t75-96 + 1(5) t21+: the claim-wait branch of the surplus classifier parks
#                           EVERY warrior standing on an unbuilt claim_set stronghold -- a 6-body raid stack
#                           that razed a contested stronghold idled 22 turns (2 hops from a live enemy base
#                           _raid_commit was ALREADY picking as raid_tgt), and 1(5)'s sole survivor was
#                           pinned into starvation while the enemy sat at 0 warriors for 173 turns. ONE body
#                           claims; the rest are released to surplus (fight/work). The last body is also
#                           released when a wave commits (survival outranks a waiting claim) or when the
#                           build can never fund (gold < cost AND zero staffed income = the 1(5) freeze).
STRAND_RECALL = 1         # R81 (1(88)/1(89), both K?, we=RIGHT, LEFT_WIN TURN_LIMIT; user: "과확장이
#                           또 발생. 가용병력서 빠지고 대기시키는거라 2~3기 빠지면 치명적. 기지 지으러 나온 유닛도
#                           모여야"): CLAIM_PARK_RELEASE's release-all only fires on concentrate / on_hq / zero-income;
#                           it does NOT catch a claimer parked on an UN-CONTESTED, unbuilt stronghold whose build is
#                           perpetually OUT-BID (gold < base cost but we DO have income, so the zero-income arm is
#                           False). 1(89): claimers stood on strongholds 77/47 unbuilt from t72 to game end (30+ turns)
#                           -- one body per stronghold kept OUT of surplus => invisible to nearest_surplus AND
#                           raid_force => 2-3 bodies permanently lost from the available army (the exact "2~3기 빠지면
#                           치명적"). Fix: a claimer parked STRAND_TURNS+ turns on an unbuilt claim stronghold is dead
#                           weight -- add the stronghold to _skip_build for the turn so (a) the surplus classifier
#                           releases the parked body (elif no longer matches -> else -> surplus) and (b) 2b does not
#                           re-dispatch to it. Time-based => rush/wave-safe (only widens release => MORE home defenders)
#                           and mirror-inert (normal claimers build within 1-3 turns, never reach STRAND_TURNS).
STRAND_TURNS = 18         # a claimer parked this many turns on an unbuilt claim stronghold without a base appearing
#                           is genuinely stranded. ★TUNED 9->18: at 9 a SLOW-but-eventual claimer (my-bot K13 econ
#                           games fund the build by arrive+10..17) was released early, forfeiting the base -> we
#                           climbed slower and lost the tiebreak (per-seed: my-bot K13 10W->8W, 2 wins lost). 18
#                           (< EXPAND_EVERY=22) spares those while still catching a GENUINELY dead claim (1(89): 77/47
#                           parked from t72 to game end, 30+ turns -> released ~t91). my-bot K13 recovers DIFFS:0 at 18.
SIEGE_BODY_HOLD = 1       # 1(4) t36/t52: bodies standing ON a DAMAGED enemy building (= actively sieging,
#                           the referee auto-sieges standers) were classified as surplus and POACHED by the
#                           claim dispatcher / garrison fill -- a 2-hp base was abandoned one turn from the
#                           kill, twice. The TGT_VALUE siege latch only guards the MULTI_PRONG re-split, not
#                           2a/2b poaching. Mid-siege bodies are no longer surplus; defense still preempts
#                           (siege_recall / concentrate / _relief release them wholesale).
CLAIM_SKIP_BUILT = 1      # 1(4) t55: the claim dispatcher sent a claimer to a stronghold with an ENEMY
#                           building standing on it -- 1b requires find_building()==None so it can never
#                           build there; the body just feeds the turret (t55 solo re-entry, 35<->32 shuttle).
#                           Skip strongholds that already carry any building (ours are in handled_targets).
GARRISON_HOLD = 0         # DEFAULT OFF (paired-matrix ablation: with RELIEF_ETA_BODY it thinned home
#                           defense on knife-edge peer seeds -- my-bot aggregate 6W2L vs the 7W1L of the
#                           safe set; a defense-path change is locally unverifiable (#41), so it ships as
#                           a documented knob for a dedicated resubmission test. The 1(6) t83 hold itself
#                           was verified working (7-body garrison stayed, HQ deficit trained instead).
#                           1(6) t83: our L2 base held SEVEN defenders vs an incoming 6-stack -- referee-
#                           exact sim: the garrison wins DECISIVELY (0 attacker survivors) -- yet the
#                           threat+1 headcount rule pulled 5 of them home to fill need[HQ] and the base was
#                           chipped/passed the next turn (사용자: "몇레벨 기지에 몇명이면 몇명을 막는지 계산이
#                           안 된다"). When an enemy stack (>= RUSH_MIN) stands on / within GARRISON_HOLD_R
#                           of one of our bases and _sim_crack says the CURRENT garrison holds decisively
#                           (not cracked, attackers wiped), pin that garrison in need[] for the turn. Only
#                           ever keeps bodies ALREADY there (never sends any -- #40 FORWARD-INTERCEPT stays
#                           NO-GO); on_hq/concentrate still override wholesale.
GARRISON_HOLD_R = 2       # "incoming" = stack within this many hops of the base (or on it)
RELIEF_ETA_BODY = 0       # DEFAULT OFF (same ablation as GARRISON_HOLD: the defense pair together lost a
#                           mirror HQ and flipped two peer seeds; single verified moments were correct but
#                           the aggregate says hold -- resubmission-test knob). 1(2)'s chain-backdoor is
#                           still covered by SIEGE_BODY_HOLD + CLAIM_PARK_RELEASE (the audit's #1 fix, one
#                           turn later). 1(2) t74: EATER_RELIEF pulled a 6-stack OFF a 4-hp siege toward a base 6 hops
#                           away that fell in 2 turns (TTL 2 vs ETA 6) -- a march to a funeral that also
#                           broke the siege hold. Relief math gains ARRIVAL: TTL = base hp / on-site
#                           eaters (+1); bodies that cannot arrive inside it are not dispatched, and if
#                           NOBODY can, the relief releases entirely (the base is lost -- the force keeps
#                           razing / backdoors instead, the user's exact call).
GRIND_RESCUE = 1          # 1(3)/1(6): vs a mid-game GRINDER (2.2x total training, 2-3-body waves, never a
#                           10-stack) every training unlock stays shut -- RUSH_BRAKE is t<=40, INCOME_FLOOR
#                           needs income-AHEAD, TRAIN_RESCUE needs a garrison deficit the stack math never
#                           produces -- so the L3 bank froze training while our bases were ground away.
#                           Extend the rescue window: _under_massed (real out-production latched) with a
#                           low HQ (<= RESCUE_HQ_MAXLVL) is ALSO an emergency -> the lean upkeep-only
#                           affordability (F2) applies before the gold collapses.
RESCUE_GATE = 1           # 1(5) G2 (dead-branch bug): the n==0 training unlock requires hq_reserve > 0,
#                           but a committed wave (concentrate) ZEROES hq_reserve first -- so the rescue
#                           retrain + its F2 upkeep-only cushion were unreachable exactly during the rush
#                           they exist for (t13: gold 137 could fund the 6th defender; chip said 4hp).
#                           The unlock now also opens on _rescue itself.
OUTMASSED_DROP = 1        # 1(6) t89+: income-BEHIND + outmassed + already losing bases, yet hq_reserve
#                           banking froze training (gold 264->1358 banked toward an L4 it could never
#                           reach) while the enemy rolled 11->20-stacks through every base = death spiral
#                           where the climb bank is DEAD CAPITAL. When _outproduced AND _um_pressing AND
#                           income-behind AND we have already LOST a base, ramp target_army toward the
#                           enemy total (ANTIBOOM without its K>15 gate) and drop the climb reserve --
#                           deterrence over a bank that buys nothing. Self-limiting: catching up turns
#                           _outproduced off; the winning games (income-ahead or base-intact) never enter.
# --- V2 ROUND-7 (2026-07-03, user-bracket 0W7L forensics: replays_v2/round7, we=RIGHT, all losses) -------
CLAIM_SAFE_ORDER = 1      # 1(4) short-center map: claim_order sorted by (own-HQ dist, region id) ONLY, so
#                           the race-even center 34 (3 hops from BOTH HQs) outranked safe 45 (3/6) purely by
#                           region number, and our-side 37 ranked LAST -> the enemy stole 37 (t52) and ground
#                           us down on the indefensible 34/61 salient (~740g re-buys + ~600g yo-yo moves).
#                           User doctrine: "우리한테 가깝고 상대한테 먼 쪽부터 채워야". Sort by symmetric-BFS
#                           (dm, -do, s): among equal own-distance, FARTHER from the enemy first. Membership
#                           (contested band) unchanged -- we still take the center, just LAST among equals.
NOREBUILD_HOT = 1         # 1.txt grinder: the enemy's 3-5-body eater party razed our forward bases 7x and we
#                           re-claimed the SAME sites 6x (~1800g) while it camped next door -- feeding bodies
#                           and gold into a grinder, starving the L3 climb for 75 turns (lost the tiebreak by
#                           exactly one HQ level). OUR razed strongholds are skip_build while any enemy body
#                           is within NOREBUILD_HOT_R hops (grinder on station); self-releases when they leave.
NOREBUILD_HOT_R = 2
CTR_LATE_STAND = 1        # 1(5) t107-109: COUNTER-DOOMSTACK set counter_now (canceling concentrate/final-
#                           stand muster) with the kill-stack at 3->2->1 hops from our HQ -- a counter-race
#                           needs ~10 hops of one-way marching and cannot finish before ours dies; the HQ fell
#                           4 turns later with 8 bodies parked 2 hops away. A stack already within
#                           CONCENTRATE_DIST = the final stand; counter_now may not cancel it.
CLAIM_MIL_GATE = 1        # 1(1) 2450-rank scout-park-strike: enemy PARKED 3-4 bodies at the d3==d3 midline
#                           t17-25 (adv_streak=0 -> arm 1 blind; 2 bases -> arm 2 blind; strictly-crossed
#                           midline -> RUSH_DEFENSE blind), confirmed the army gap, then one-shot our bases
#                           t26-30 and HQ t54. User doctrine: "기지 짓기 전에 병력 차이가 있다면 병력을 먼저
#                           뽑고 나서 건설 -- 좁은 맵은 상대 군사력이 최우선". Arm 3: a PARKED pack >= RUSH_MIN
#                           at/inside the midline within the approach gate + an absolute unit deficit >=
#                           CLAIM_MIL_DEFICIT -> rush brake (economy freeze + threat latch + lean-funded
#                           training), opening window (t <= RUSH_BRAKE_TURN) only. A mirror opening keeps its
#                           bodies at home (stack_dist ~ diameter > gate) -> never fires on ourselves.
CLAIM_MIL_DEFICIT = 2
RELIEF_SIZED = 1          # 1(3) poke-leash: 2-3-body pokes on our bases yanked the ENTIRE raid_force home
#                           and reset the raid commit >= 6 times (zero offense t85-140, ~600-800g re-bills)
#                           -- the exact leash a human runs on us. For a SMALL eater party (<= RELIEF_SIZED_MAX,
#                           no wave signal): send only the nearest (_eat_sz + 1) bodies (referee-exact: they
#                           zero the eater's siege overflow on our own turret ground) and KEEP the raid commit
#                           marching. Any bigger trigger keeps today's full-force pull byte-identically.
RELIEF_SIZED_MAX = 3
L2_MARCH_HOLD = 1         # 1(6): hq_reserve protects the climb fund from TRAIN only -- raid MOVE re-bills
#                           (10g each, 3,730g total in the game) kept gold under ~150 so the HQ sat L1 until
#                           t169 (L2 costs 600; we lost the (alive, HP) tiebreak 15v20). While the HQ is L1
#                           (past the opening, no emergency), DISCRETIONARY raid moves must clear reserve +
#                           the L2 cost; the hold self-disarms the turn the HQ upgrades (~10-15 turns).
L2_MARCH_HOLD_TURN = 45
RESCUE_TGT_FIX = 1        # R6 GRIND_RESCUE latch bug (g1 probe): GRIND_RESCUE sets _rescue via
#                           len(my_warriors) < target_army, but the n==0 unlock it is meant to open still
#                           tests len(my_warriors) < target_garrison (7, from a 6-body eater latch) -- with
#                           14-20 bodies the unlock NEVER opened and the R6 lever was fully inert (g1 t118+:
#                           resc=True, deficit 19-28, train=0). When _rescue is set, the unlock cap is
#                           max(target_garrison, target_army).
OUTMASSED_SOFT = 1        # 1.txt/1(3): human grinders hold a SUSTAINED ~1.5x army that dodges _outproduced's
#                           1.6x instantaneous ratio AND park their main stack at home so _um_pressing stays
#                           False (UNDERMASS_PARKFIX) while eater squads raze us -- both R6 ramps stayed dark
#                           through entire losses. Soft arm: absolute deficit >= OUTMASSED_SOFT_MARGIN AND we
#                           have LOST a base AND workcap-behind = proven real pressure regardless of where
#                           their main stack idles -> feeds GRIND_RESCUE + OUTMASSED_DROP only (never the
#                           mirror-sensitive threat/garrison machinery). Self-limiting like _outproduced.
OUTMASSED_SOFT_MARGIN = 6
CRACK_HORIZON = 0         # DEFAULT OFF (single-flag ablation vs my-bot K11: =1 -> 0W3L1D with our HQ
#                           stalled L2 vs L5 while every other R7 flag off stayed 0W; =0 alone restores
#                           3W1L. Phantom-off (PH_CAP=0) did NOT heal it -> the REAL-body horizon read is
#                           the paralysis, the ETA_CRACK NO-GO reproduced even with the 3x-ambush trigger
#                           + favorable-trade gate: an army-keeping peer always has bodies inside the
#                           horizon, razing collapses, the tiebreak dies. Verified the flag still blocks
#                           the 1(2) t73 kill-zone read when on -- KEEP THE CODE as a resubmission-only
#                           knob (#41 family: locally razing-collapse, vs humans the ambush is real).
#                           1(2) attack math (user: "L1/L2/L3에 N명이 있으면 몇 명으로 쳐야 하는지 계산이
#                           안돼"): _can_crack counts defenders within 1 hop only -- both raids DID raze
#                           their targets but donated 13 units to relief converging from 2-4 hops that the
#                           sim never saw (defs=1 vs 8 within 2h). Schedule enemies at local_rd < d <=
#                           eta+ETA_GRACE as STAGGERED arrivals (offset d - local_rd; + a small trained-refill
#                           phantom when the enemy HQ is inside the horizon), ONLY when they outnumber the
#                           counted defenders >= CRACK_HZ_OUTNUM x (the ambush signature -- a turtle's 2-worker
#                           garrisons never trip it; full-ETA scheduling was the ETA_CRACK paralysis NO-GO),
#                           and require a CLUSTER_KEEP_F favorable trade when they fired.
CRACK_HZ_OUTNUM = 3
CRACK_HZ_PH_CAP = 3
RAID_MIN_COMMIT = 1       # 1(2) trickle commits: _raid_commit re-picked targets for force=2-3 remnants
#                           (t75/t84) which fed the counterwave in detail. A NEW commit needs >= MIN_RAID
#                           bodies; an already-committed lock keeps marching regardless (no mid-siege abort).
# --- V2 ROUND-8 (2026-07-03, AI-ladder: 3.txt t73 all-in loss + 4.txt dominated L4/25==L4/25 draw) -------
RELIEF_ETA_HQGUARD = 1    # 3.txt kill window (t70-72): the 13-body worker all-in BEELINING OUR HQ passed
#                           within 2 hops of bases 14/11/4 en route, so RELIEF_ETA re-classified it as a
#                           "base raid", slashed defenders_needed 14->guard_floor(1), and at t72 marched
#                           8 of the 10 mustered defenders (30 of 39 HP) OFF node 0 -- one turn before
#                           impact (siege would have been 13-39 = 0; instead 4+11 killed the L2 HQ). The
#                           arm lacked classic _relief's own `stack_dist > CONCENTRATE_DIST` guard and
#                           ignored an armed siege_recall. Trains were 14v14 -- this evacuation WAS the loss.
RELIEF_UNDER_SIEGE = 1    # log-8 (8.txt) forensic: RELIEF_ETA_HQGUARD blocks ALL forward base-defense while
#                           siege_recall is armed -- 8.txt showed the cost. An 11-stack beelined our HQ THROUGH
#                           base 11 (2 hops from HQ, ON the path); siege_recall recalled the 8-body garrison OFF
#                           11 to turtle, so the L1 base (hp6) was razed for FREE (one-shot), then base 1, then
#                           the HQ was assaulted -- we WON the HQ fight (18 vs 10) but ceded every base, stayed
#                           HQ L2, and lost the tiebreak L2 vs L4. Key: a committed all-in (siege_recall proved
#                           it crossed the midline) has NO reinforcement behind it, so if we can DECISIVELY win
#                           at a base squarely ON its beeline path, holding there IS the HQ defense (the stack
#                           can't pass) AND saves the economy the turtle cedes for free -- and winning ENDS the
#                           assault (승리 확정). This re-enables RELIEF_ETA under siege_recall ONLY for such a
#                           base: forward of the HQ, on the stack's SHORTEST path (can't be bypassed), reachable
#                           in time, decisive win. 3.txt SAFETY: that loss relieved a base the all-in could
#                           BYPASS (siphoned HQ defenders -> HQ fell); the on-path (_hs+_hh<=stack_dist+1) +
#                           arrive-in-time (_hh<=_hs) + decisive-margin gates exclude it. RELIEF_UNDER_SIEGE=0
#                           => byte-identical (guard stands). Local: fires only vs a real HQ-beeline all-in (no
#                           local bot does this) => near-inert => efficacy is resubmission-only (anti-predictive).
RELIEF_UNDER_SIEGE_MARGIN = 1   # hold when (force reachable to the base in time + base turret) >= stack + THIS.
#                           =1 with a turret means "hold when our on-time force >= the stack" (user: 기지 아군 인원
#                           >= 상대면 막는다) -- the turret + defensive ground win the even fight. The count is now
#                           REACHABILITY-based (bodies within _hs hops of the base), so it is not the old
#                           len(my_warriors) over-count; raise this only if a bigger safety cushion is wanted.
PRESTAGE = 1             # 8(2).txt (user: "적이 최단경로로 오는 건 예측 가능 -> 미리 인원대비해서 배치"): the enemy
#                           moves along the DETERMINISTIC shortest path (Nav mirrors the referee exactly), so an
#                           ADVANCING WAVE_STACK_MIN+ stack's target base + ETA are predictable. RELIEF_ETA already
#                           relieves within 2 hops of a base; PRESTAGE fires the SAME relief EARLIER (up to
#                           PRESTAGE_REACH hops) so the winning force is STANDING on the base when the stack lands,
#                           not scrambling one turn late. RUSH-SAFE by the ON-PATH gate: the target sits on the
#                           stack's shortest path to our HQ (_hs+_hh<=stack_dist+1), so (a) holding it also guards
#                           the HQ approach AND (b) _hh < stack_dist means we recall to the HQ BEFORE the stack
#                           could -- a feint / 2-prong cannot beat us home (the STAND_GROUND rush-crack hole).
#                           Head-count is REACHABILITY-based (bodies that can be ON the base by the ETA, incl the
#                           garrison at 0 hops). Inherits RELIEF_ETA's not-siege_recall + stack_dist>CONCENTRATE_DIST
#                           + guard_floor guards; only fires when we DECISIVELY win (+PRESTAGE_MARGIN). PRESTAGE=0
#                           => byte-identical (RELIEF_ETA's 2-hop reactive relief stands).
PRESTAGE_REACH = 4      # pre-stage when the stack is within THIS many hops of the target base (RELIEF_ETA uses 2).
#                           Kept modest -- never commit to a base the stack is a long, divertible march from.
PRESTAGE_MARGIN = 1     # require reachable force + base turret >= stack + THIS (decisive; turret wins the even fight).
MASS_STAGE = 1          # R67 (8(13) AI-8 loss, TURN_LIMIT level deficit; user 1(73)+8(13): "상대가 기지를 노리려고
#                         인원을 밑에 배치했잖아 -- 가장 가까운 위치의 아군 기지로 상대 가용인원만큼 보내면 충분히
#                         막을 수 있다 ... 인원은 충분히 뽑았는데 배치가 늦어져서 손해를 크게 봤네"): PRESTAGE's
#                         PARKED-mass arm. AI-8 parked an 11-body wave at its HQ over t40-58; every stager keys on
#                         _stack_advancing or 2-hop heading, so the first order fired t62 against a t63 landing --
#                         base 27 one-shot, then 28, center lost, level-count loss. A PARKED mass's approach is
#                         still deterministic (nearest our-base, referee shortest path), so run PRESTAGE's exact
#                         on-path + decisive-reach arithmetic against the hypothetical march NOW and stand the
#                         winning force on the target base while the mass still trains (12-turn staging window vs
#                         2). Same-class safety as PRESTAGE (our turret ground, on-path => holds the HQ approach,
#                         recall geometry intact); the REACH bound keeps a turtle's deep home garrison and a far
#                         inter-wave park silent (their march is long => classic advancing machinery has time).
#                         MASS_STAGE=0 => decision-identical.
MASS_STAGE_MIN = 6      # parked-mass size that arms the arm (= SUBWAVE_MIN, the proven wave-signal floor; 8(13)
#                         hit 6 by ~t47 => 13 turns of staging headroom).
MASS_STAGE_REACH = 4    # only a mass whose nearest-our-base march is THIS short is an imminent-launch threat
#                         (8(13): HQ-park -> base 27 = 4 hops; turtle/waverush home parks on battery maps run 5+).
MS_NARROW_K = 9         # R69 (1(75) verification, user: "좁은맵 특성상 73번과 중복"): on a NARROW map (M.K <=
#                         this) the reach bound is +1 (=5) -- K9 geometry puts the enemy HQ-park exactly 5 hops
#                         from our center base (probe: t32-35 MS evaluated, target 25 picked, reach 7>=7 PASSED,
#                         killed only by mhs=5>4 -- then the 6-pack razed 25). A GLOBAL raise to 5 was per-seed
#                         refuted: my-bot K13 seeds 2004/2008 flipped W->D deterministically (-2W) -- on mid
#                         maps a 5-hop park is not imminent and the early defensive stance costs conversions.
#                         Battery K9 cells validated at reach 5 (rush 36/36 cr0, waverush 9W0L3D cr0).
PRESS_HOLD = 1          # R68 (1(74) loss, wide K19; user: "77턴에 압도적인 병사가 있는데 공격을 안하고 주변만
#                         서성이다 갑자기 방어하러가 -- 넓은 맵 특성상 이미 거리가 꽤 된다면 상대가 러쉬로 이득
#                         볼 때 우리도 빠르게 상대 기지를 공격해서 손해를 메꿔야"): a raid force marching DEEP
#                         is not homeward garrison supply. t78 forensic (TRMV): need[HQ] spiked when base 36
#                         fell and the 2a fill -- which runs BEFORE the raid section every turn -- yanked the
#                         whole 9-body expedition at ~5 hops; the raid re-grabbed it next turn (96<->75
#                         shuttle) while the enemy's two 6-packs razed 58/45/67 unopposed: the round trip
#                         donated four bases. Fix at the ONE supply gate (nearest_surplus): a body BOTH
#                         farther than PRESS_FAR from the pull target AND strictly closer to an enemy
#                         building keeps pressing -- recalling it can no longer affect any home deadline
#                         (the user's distance insight), razing back is the compensation. Depth-independent
#                         recall invariants (HQ contact / all-in siege_recall / committed wave concentrate)
#                         bypass the filter wholesale. PRESS_HOLD=0 => decision-identical.
PRESS_FAR = 3           # a body within THIS many hops of the pull target is ALWAYS recallable (it arrives
#                         inside real fight windows); the press exemption is for the genuinely far.
PRESS_TTL = 6           # the exemption follows ACTIVE raid marching only (a fresh _order_move_raid stamp
#                         within this many turns). Without it, deep IDLE bodies (post-raze campers, spent
#                         prongs) were locked out of the recycle pool forever -- my-bot K13 went 12W -> 6W6D
#                         (the endgame conversion starved), turtle K19 took its first loss. Expiry returns
#                         them to garrison/claim supply; a marching expedition re-stamps every turn.
# --- SUB-WAVE BASE DEFENSE (1(36).txt forensic: the t99 full-retreat -> base-26 loss -> cascade tiebreak
#     loss). A 6-body B stack marching on our forward base 26 sat in a COVERAGE HOLE: RELIEF_ETA/PRESTAGE
#     own E>=WAVE_STACK_MIN(10), SIEGE_EMERGENCY owns E>=8, HOME_INTERCEPT is confined to 2 hops of the HQ
#     strictly inside our half, EATER_RELIEF fires only once the stack STANDS on our base. The only armed
#     lever was threat+1 -> need[HQ] -> the 2a fill CONFISCATED the 6 nearest bodies to node 0 -- pulling
#     A26-29 (ONE hop from the stack's actual target, base 26) 3 hops backward -- while the gutted 4-body
#     fist fled to base 15. Base 26 fell unopposed t100-101 (referee-exact sim: defending it was a DECISIVE
#     win -- zero siege damage, all 7 attackers dead, 7/11 survivors). Three narrow, flag-gated fixes:
PRESTAGE_SUBWAVE = 1     # Fix 1: PRESTAGE's stack band widens from E>=WAVE_STACK_MIN(10) to E>=SUBWAVE_MIN(6)
#                           when the stack has ALREADY latched the threat counter (threat >= THREAT_MIN) --
#                           i.e. it is inside THREAT_RANGE of our HQ on our side of the midline. Reactive-only
#                           (a far-side roamer never fires it); all of PRESTAGE's own guards stand: advancing,
#                           on-path, stack_dist>CONCENTRATE_DIST, not siege_recall, REACHABILITY win test with
#                           +PRESTAGE_MARGIN. At 1(36) t99 PRESTAGE passed every clause except E>=10 with its
#                           own win math approving a decisive pre-stand on base 26. PRESTAGE_SUBWAVE=0 => byte-identical.
SUBWAVE_MIN = 6          # sub-wave band floor (= MOBILIZE_NEAR: the size that latches threat_army as a wave signal).
THREAT_FILL_FWD = 1      # Fix 2: when the threat spike's source stack targets a forward BASE (its nearest own
#                           building is not the HQ) and our reachable force + that base's turret beats it (+1),
#                           route the threat garrison demand to THAT base instead of node 0 (need[HQ] falls back
#                           to the guard floor). The 2a fill then stations the nearest bodies on the actual
#                           target's turret ground instead of confiscating them 3 hops backward. Placement-only
#                           (defenders_needed itself is untouched -> training targets identical); inert when a
#                           relief lever already owns the turn (not _relief), under concentrate/siege_recall/
#                           on_hq (survival paths untouched). THREAT_FILL_FWD=0 => byte-identical.
PREDICT_STAGE = 1        # R42 (1(50)/1(49) forensic; user: "적당히 크기가 있는 맵이면 보통 상대 여분 병력이 3칸
#                           움직일 때 어디로 명령이 떨어질지 특정이 되는 점을 이용해 로직을 구성"): HEADING
#                           INFERENCE. Track each enemy warrior's last three positions; two CONSECUTIVE hops
#                           both on a shortest path toward one of OUR bases identify its ordered destination
#                           (the referee walks units along shortest paths, so 2-3 consistent hops collapse the
#                           candidate set -- exactly the user's observation). The GROUP is every enemy body
#                           heading at the same base -- co-location NOT required: 1(50)'s 6-unit column marched
#                           spread over adjacent nodes, never formed a stack_reg, and every stack-based lever
#                           (PRESTAGE/RELIEF_ETA/THREAT_FILL_FWD) was geometrically blind while base 43 fell
#                           and reinforcements trickled in one turn late, one body at a time. When the predicted
#                           target is one of our BASES, the group is PRED_MIN+ strong with the earliest arrival
#                           inside PRED_HORIZON, and our reachable-by-ETA force + the base turret HOLDS
#                           (defenders_present + turret >= attackers, the 1(47)-proven referee hold rule,
#                           +PRED_MARGIN), route the garrison demand there NOW (need[] bump = the validated
#                           CORE_PREPOSITION placement-only pattern: total_need is summed BEFORE the bump so
#                           training is untouched, and the 2a fill serves the HQ guard FIRST by sort order).
#                           If the hold is NOT achievable the lever stays SILENT -- no doomed one-by-one feed
#                           (RELIEF_ETA_BODY doctrine). Sibling guards inherited (adversarial-review class):
#                           on_hq==0, not concentrate / siege_recall / _fort_hold / _relief.
#                           PREDICT_STAGE=0 => decision-identical (history tracking is state-only).
PRED_MIN = 3             # smallest heading-consistent group worth a garrison response (1(49) t58: 4 units)
PRED_HORIZON = 4         # act only when the earliest predicted arrival is within THIS many turns
PRED_MARGIN = 1          # hold bar: reachable force + turret >= group + THIS (turret wins the even fight)
FILL_REACH_SURPLUS = 0   # R50: FALSIFIED -- OFF. Hypothesis was "PS/TFF hold tests count the whole roster
#                           while the 2a fill delivers only surplus -> honest-supply operand (on-target +
#                           inbound + unassigned surplus in range) stops doomed one-body feeds". Measured
#                           reality (waverush K13 s2006, record-driven): at t54 the honest operand silenced
#                           the PS pre-staging of base 18 (supply 4 < group 5+1), the un-posted body A13
#                           stayed home, the wave landed t57, base 18 fell, and the attrition chain razed
#                           8/40/18 -> HQ DESTROYED t173 -- while the legacy-roster build (FRS off, all else
#                           identical) posted A13 at t54 and DREW. Root lesson: the 1-per-turn trickle to a
#                           PREDICTED base is pre-arrival ACCUMULATION on turret ground (each body shifts
#                           the hold rule defenders+turret>=attackers), not the mid-fight drip the 1(51)
#                           feed was -- and 1(51)'s actual feeder is MG_BASE_GARRISON staffing + 2a fill,
#                           which this flag never touched (1(51) divergence unchanged at t111 with FRS on).
#                           Keep 0. The code path stays for the record; do NOT re-arm without a staggered
#                           arrival-schedule model that credits accumulation-before-ETA.
RAID_PHANTOM = 1         # R42 (1(47) t140-163 forensic; user: "151턴에 상대 후반 지원군이 와서 막히거든 --
#                           후퇴 로직도 필요할 것 같아"): the committed-siege proof (_can_crack, re-proven
#                           every turn) schedules only the enemies it can SEE -- it has no model of the
#                           enemy's TRAIN STREAM. Measured: target base 19 sat 2-3 hops from an L4/L5 enemy
#                           HQ training ~2/turn into the fight; _can_crack said True 17 consecutive turns
#                           against the 3-5 visible defenders while our fist bled 13->3 without the raze
#                           (every finisher path already models this via FINISH_PHANTOM_CAP -- base commits
#                           were the one blind spot). THE VETO: when the committed/fresh BASE target sits
#                           within RAIDPH_FUNNEL hops of the enemy HQ AND the enemy has ACTUALLY trained
#                           >= RAIDPH_TRAINS bodies in the last RAIDPH_WIN turns (evidence-gated: a turtle /
#                           dormant economy gets NO phantoms, so the proven turtle/deny cracks are untouched),
#                           re-prove the crack with phantom arrivals at the OBSERVED production rate injected
#                           from the funnel distance. Fails -> release the commit through the existing
#                           machinery (raid_skip blacklist + withdraw/watch = the user's retreat, unit-
#                           preserving). RAID_PHANTOM=0 => decision-identical (sighting log is state-only).
RAIDPH_FUNNEL = 6        # the veto applies only to bases within THIS many hops of the enemy HQ (its relief
#                          funnel). 1(47)'s base 19 sat at FIVE hops and the 2/turn stream still crushed the
#                          siege (phantom offset _pvh+1 <= MAX_CRACK_TURNS keeps far funnels inert anyway).
RAIDPH_WIN = 8           # evidence window (turns) for the observed enemy production rate
RAIDPH_TRAINS = 4        # minimum trains observed in the window before any phantom is injected
REACH_WIN = 1            # (user: "가용병력 개념으로 정밀 계산해 수비/공격 조정 -- 효과 확실했던 로직을 그 기준으로
#                           통일") Migrate the SIX remaining defense win-tests that count the WHOLE army
#                           (len(my_warriors)) to the validated REACHABILITY standard (8(1) RELIEF_UNDER_SIEGE
#                           lesson: "사수가능?=REACHABILITY" -- bodies that can BE at the fight in time, not the
#                           global roster). The whole-army tests are vacuous (1(36) t103: a 4v6 open-field death
#                           march was approved because 20 total warriors >= 6-6 slack) and over-approve fights
#                           the dispatchable force loses piecemeal. Sites: classic RELIEF (+ drops RELIEF_SLACK
#                           in reach mode -- the slack WAS the vacuousness), EATER_RELIEF, RELIEF_ETA,
#                           SPLIT_RELIEF prong triage, BASE_RALLY hold test, base_eating contest arm. Horizon
#                           per site = the natural fight window (base TTL = ceil(hp/eaters)+1 for grinds; the
#                           stack's march ETA for approaches; stack_dist for the contest arm). PRESTAGE/
#                           RELIEF_UNDER_SIEGE/THREAT_FILL_FWD/HI already use reach -- this closes the family.
#                           REACH_WIN=0 => byte-identical (every site keeps its legacy whole-army operand).
RELIEF_POOL_GARRISON = 1 # Fix 3: an ARMED classic relief with an empty raid_force emitted ZERO orders while
#                           base 26 was razed (t100-101: every mobile body was mid-move = un-orderable, and the
#                           2a-kept HQ bodies are excluded from surplus by construction). Let the classic relief
#                           squad also draw the HQ-kept stationary bodies ABOVE guard_floor, TTL-gated (can
#                           arrive before the base falls). Workers on BASES are never pulled (the BASE_WORKER_
#                           RELIEF lesson: pulling income workers = economy death spiral); guard_floor stays
#                           home; on_hq==0 gated. RELIEF_POOL_GARRISON=0 => byte-identical.
NEIGHBOR_RELIEF = 1       # R50 (1(53)/1(55) forensic, user: "주변 기지에 배치돼 있는 인원이 막으면 충분했는데
#                           와서 막아주질 않더라고"): the classic-relief pool above only draws HQ-kept bodies --
#                           garrisons sitting on NEIGHBOR bases 1-3 hops from the dying base were structurally
#                           invisible (53: 2 bodies at base 4 = hold, sat motionless; 55: 3 at base 43 = hold).
#                           Extend _rp_pool to stationary bodies on OUR other bases within NR_HOPS of the
#                           relief target, TTL-gated like the HQ pool. Each source base keeps max(1, work_cap)
#                           bodies (income NEVER pulled -- the BASE_WORKER_RELIEF economy-death lesson) and is
#                           skipped entirely if an enemy stands on it (it is its own fight). Backfill is the
#                           existing 2a staffing. NEIGHBOR_RELIEF=0 => byte-identical.
NR_HOPS = 3               # neighbor radius (user: "가까운 기지에 2명 정도 보내면 막을 수 있었거든")
NR_MAX_PULL = 3           # bodies per rescue episode (53 pulled 1, 55 pulled 2 -- bounded strip)
NR_COOLDOWN = 8           # turns between rescue episodes: a stream rusher re-arms relief every few
#                           turns and an uncooled pull hollowed the MG garrison pins (waverush-K13
#                           s2006 HQ crack); one fight = one rescue, the treadmill gets nothing.
MG_DEEP_OPS = 1           # R50 (1(54) forensic): MIL_GAMBIT's posture-end release requires _mg_deep == 0, but
#                           _mg_deep counted enemy workers SEATED ON THEIR OWN forward buildings in our 40%
#                           zone -- economy, not incursion -- so the latch never released (t76+: enemy field
#                           army dead, 7 bases, release condition otherwise met; harass/counter stayed sealed
#                           through our +6 window -> draw). Release check now counts operators only; ARM
#                           semantics unchanged. MG_DEEP_OPS=0 => byte-identical.
# --- R51: the user's TEMPO doctrine, generalized (1(51) + "HQ 타이밍이 가장 약하다") ---------------------
INCOME_PRESS = 1          # R51 (1(51), user: "상대가 인원 차이가 심하고 우리가 턴당 골드가 많이 붙어 있다면
#                           시원하게 박는게 나아 -- 재생산성으로 밀어붙이면 되니까"): vs an ECONOMY-BACKED
#                           masser (enemy bases >= IP_ENEMY_BASES -- a base-capped waverush gambit stays
#                           fully sealed, that is MIL_GAMBIT's own criterion) while we OUT-EARN him and are
#                           BEHIND on bodies, the hold-and-out-econ freeze is the wrong stance: the income
#                           leader wins an attrition trade. Lift the MG harass seal + the HQ-level harass
#                           gate for this band only; targets still pass _can_crack, the MG garrison pins
#                           and parity lean-train stay (the re-production that funds the doctrine).
#                           INCOME_PRESS=0 => byte-identical.
IP_ENEMY_BASES = 4        # real economy bar: waverush maxes 2; 1(51)'s masser held 5
IP_INC_EDGE = 1           # our work capacity must exceed theirs by more than this
IP_DELTA_MIN = 2          # body deficit that arms the band ("인원 차이가 심하고")
L2_FIRST_GUARD = 1        # R51 (user: "우리가 2일 때 먼저 찍을 때는 먼저 병력을 반드시 뽑는 쪽으로 해야해
#                           분명 상대가 파고 들거니까"): the 600g L2 buy empties the wallet = our weakest
#                           window. For L2F_WIN turns after OUR first-to-L2 upgrade: trains get the wallet
#                           (1b claims carry a +L2F_HOLD_TRAINS*120 hold) and the army floors to enemy
#                           count + L2WIN_EDGE on the upkeep-lean bar. Post-purchase only -- the buy itself
#                           is never delayed (the L2_WATCH falsification: holding the L2 = war poverty).
#                           L2_FIRST_GUARD=0 => byte-identical.
L2F_WIN = 12              # guard window (turns) after our L2 lands
L2F_NEAR = 4              # incursion predicate: >= 2 enemy bodies within THIS many hops of our buildings
L2F_DEFICIT = 3           # arm only past the user's "-1 ~ -2 마지노선" (deficit 3+); guard trains stop at -2
L2F_HOLD_TRAINS = 2       # claim-wallet hold during the window, in TRAIN_COST units
L2_LATE_PUNISH = 1        # R51 (user: "우리가 HQ 2레벨 타이밍이 늦는다면 이득을 봐야하고 이때는 병력을
#                           찍어서 손해를 줘야하는 것"): the ENEMY's L2 buy empties HIS wallet -- convert
#                           our tech lag into military profit: for L2P_WIN turns after his HQ level-up
#                           while we are level-BEHIND, lean-train to his count + L2WIN_EDGE and open the
#                           harass gate (targets still _can_crack-proven). WINDOW-BOUND by design -- the
#                           L2_WATCH scar (open-ended punish trains ate the 600 climb bank -> L1 for 200
#                           turns) is the reason this expires. L2_LATE_PUNISH=0 => byte-identical.
L2P_WIN = 15              # punish window (turns) after the enemy HQ level-up
L2P_THIN = 3              # expedition arm only vs a THIN standing army (enemy total - workcap <= this)
L2WIN_EDGE = 1            # army bar over enemy count inside either HQ-timing window
L4_WINDOW = 1             # R52 (5(6) forensic; user: "다음 차이는 L3에서 L4로 올라갔을 때 -- 상대일 때와
#                           우리일 때, 특히 턴당 골드차이가 얼마 안 난다면"): the L2 window doctrine extends
#                           to the L4 buy (2400g = the deepest wallet dump before L5). Measured 5(6): enemy
#                           L4 first ~t135 with THIN standing army (avail 2) while we sat +4 bodies and
#                           workcap 19v18 -- the punish raid was exactly available and nothing fired; both
#                           reached L5 and the game drew. Same gates as L2 (deficit trains / parity+thin
#                           raid / 마지노선+prober guard). L5 stays EXCLUDED (the my-bot s2010 falsification:
#                           the endgame level race owns that band). L4_WINDOW=0 => byte-identical.
GARRISON_STAND = 1        # R52 (1(56) t97 forensic; user: "우리 기지로 오는 병력에 갑자기 모든 노동자가 다
#                           튀어나와... 인원 계산이 정밀하지 않아"): the 2a threat-fill flapped its target
#                           97<->98<->96 and re-stationed the garrison EVERY turn -- 5 bodies walked OFF
#                           base 97 on the exact siege turns and the base fell. A body standing on OUR OWN
#                           building with an enemy ON or ADJACENT to it is THE fight -- it is not surplus
#                           and nothing may poach it (the SIEGE_BODY_HOLD taxonomy, defense side). Under
#                           hq_pressure the rule yields (HQ survival outranks a base; rush-safety).
#                           GARRISON_STAND=0 => byte-identical.
MAX_SWEEP = 1             # R53 (5(7) forensic; user: "HQ에 5를 찍었으면 무작정 병력 뽑고 던져 -- 상대 기지들
#                           차례로 보내고 HQ 터뜨리는 피니쉬"): the ENTIRE finisher family is deny-framed
#                           (arms only while the enemy is sub-L5), so in a MUTUAL-L5 game there is no
#                           offense doctrine at all -- 5(7): our L5 t158, enemy L5 t145, t158-200 we
#                           trained 43 bodies and sieged ZERO enemy bases (the threat latch ta=38 matched
#                           target_garrison to the enemy pack parked at ITS OWN HQ, so surplus/raid_force
#                           was 0 the whole time), while the ENEMY ran the user's exact doctrine at us
#                           (25-stack at t190 -- which our HQ ground down, proving the hold). Once OUR HQ
#                           is MAXED (enemy level irrelevant -- the tiebreak is HQ hp), on the WIDE map:
#                           cap the home keep at SWEEP_GUARD (turret 3 + guard + train_cap 3/turn refill +
#                           heal reserve hold the fort) and let the freed surplus flow into the existing
#                           raid machinery -- nearest/crackable enemy bases fall first (RAID_PHANTOM
#                           naturally defers the funnel bases until their economy dies), then the chip
#                           finishes the HQ. Suspended while on_hq>0 / concentrate / siege_recall (real
#                           defense resumes; SIEGE_EMERGENCY force-recalls the fist vs a beeline all-in).
#                           Plus a lean top-up train arm (upkeep + heal-reserve bar) = "무작정 뽑고".
#                           MAX_SWEEP=0 => byte-identical.
SWEEP_GUARD = 6           # home keep while sweeping: 6 + turret 3 holds any sub-wave outright; a full
#                           stack gets ground by refill (3/turn) + the 1000g heal bank (5(7) t190-200 실증)
CONC_KEEP_ECON = 1        # R54 (1(59) t86-88 loss; user: "노동자 튀어나오는 바람에 겜이 터졌어 -- 최단거리로
#                           가는거라 HQ 거치지도 않는데 왜 반응하는거야"): the committed close-in arm
#                           (stack_dist <= CONCENTRATE_DIST) is heading-blind -- a 10-stack skirting the
#                           3-hop ring toward forward base 79 (HQ distance frozen at 3) tripped the full
#                           turtle at t86: EVERY base worker dumped to node 0, income died, the latch
#                           released and they all walked back. Fix: while the close stack is NOT advancing
#                           on the HQ and is closing on a non-HQ base (nearest our-building, <= 1 hop),
#                           concentrate keeps mustering the ARMY but the base WORKERS stay earning
#                           (need = work_cap instead of 0). A rushing beeline advances every turn and
#                           never trips this; the turn the eater pivots HQ-ward the full dump resumes.
#                           CONC_KEEP_ECON=0 => byte-identical.
NARROW_NEAR = 1           # R65 (1(72) K11 loss; user: "좁은 맵에서는 최대한 가까운 위치로 확장"): on a
#                           NARROW map (K in the NN_K band) whose opening offers ample NEAR supply, the center
#                           TIE race is sealed for the whole opening -- the second claimer stops marching to a
#                           4-hop salient it can never defend and nearest-first claiming takes over. BOTH terms
#                           are mechanism-anchored: sealing is only safe when it REDIRECTS the claim (base count
#                           preserved). Forensic (waverush s2005-K9 / s2001-K19): with thin near supply a seal
#                           DROPS a base (center-last order never reaches the tie once wave brakes lock claims
#                           ~t25+) -> 3-base economy, trains 16 vs 27 -> HQ crack. The race's real value vs
#                           pressure = front-loading base #4 into the pre-wave window, so small/large maps keep
#                           it and only near-supply-rich narrow maps seal. NARROW_NEAR=0 => decision-identical.
NN_K_LO = 10              # "narrow" band: the K11 bracket (1(64)/1(69)/1(72) all K=11). K<=9 maps NEED the race
NN_K_HI = 12              #   economically (s2005 crack); K>=13 mid/large maps keep the proven center race.
NN_HOPS = 3               # near supply = strictly-ours (dm<do) unclaimed strongholds within the bot's standing
NN_MIN = 4                #   3-hop relief radius; >=4 of them = the seal provably redirects instead of shrinking.
RALLY_HOLD = 1            # R64 (7(6) AI loss; user: "11명 러쉬, 가용인원 보내면 충분히 막는데 또
#                           소극적"): BASE_RALLY's winning stand at the wave's predicted target latches --
#                           the home muster may not reverse it while the rally base stands, the stack is
#                           live, and army+turret >= stack still holds (t71 rally -> t72 u-turn -> piecemeal
#                           rout was one home_safe flicker). Break any condition -> legacy muster resumes.
#                           RALLY_HOLD=0 => byte-identical.
RALLY_HOLD_TTL = 10       # turns a latched rally may keep intercepting the muster before it expires
ROUTE_AVOID = 1           # R62 (1(70) loss; user: "이동 경로에 적 기지가 있어 ... 언젠가
#                           발생할 수 있으니까 고쳐줘"): when the referee's own routing would step onto an
#                           enemy building in TRANSIT (t85: 35->30 via enemy base 29, equal-length clean
#                           route via 24 existed -- three bodies turret-ground mid-march, recurring), the
#                           march is issued one safe hop at a time via an enemy-building-barred dijkstra.
#                           Destination-is-enemy-building (assault) untouched; unreachable-when-barred
#                           falls back to the plain order. ROUTE_AVOID=0 => byte-identical.
TRIV_HOLD = 1             # R61 (1(69) loss; user: "167턴 수에 모든 노동자가 튀어나옴,
#                           인원도 4명뿐이라 HQ 가용병력으로 잡을 수 있었다"): TRIVIAL_SIEGE's fixed cap
#                           (TRIV_MAX=2) generalizes to the HOLD bar itself -- a squad no bigger than the
#                           HQ turret + standing HQ bodies is trivial at any size (the hold rule zeroes
#                           its siege and the fort out-kills it). 4-body poke at a garrisoned fort no
#                           longer dumps the economy; a 10+ rush never clears the bar. TRIV_HOLD=0 =>
#                           byte-identical.
CLAIM_WALLET = 1          # R60 (1(67) loss; user: "t46에 갑자기 5곳에 확장하기 위해 인원
#                           확 퍼뜨리더라 -- 어차피 턴당 골드로는 전부 못 짓는다, 많아야 2마리"): outstanding
#                           claimers (in-flight + parked on unbuilt strongholds + this turn) are capped at
#                           the wallet's foreseeable funding: gold // 300 + 1. The old brake only checked
#                           the instant a claimer left, so consecutive turns stacked 5 unfunded claimers
#                           and the follow-up wave walked through the thinned home. EXPAND_AHEAD exempt
#                           (a standing blocker is worth it unfunded). CLAIM_WALLET=0 => byte-identical.
CW_HORIZON = 4            # R60: income turns credited to the claim wallet (the FAST_EXPAND march window)
CW_EA_CAP = 2             # R60: outstanding-claimer bound while EXPAND_AHEAD is live (blockers are
#                           worth standing unfunded, but 1(67) measured 11 stacked bodies -- cap at the
#                           user's "많아야 2마리")
RAZE_CAMP = 1             # R59 (1(65) loss; user: "t74에 기가막히게 공격 ... 상대는 또 기지를
#                           짓지 -- 응징을 해줘야하는데 용인한 시간이 좀 길어"): after a raze, the watch-
#                           withdraw abandoned razed node 54 on t75 and the enemy rebuilt t78. Standing on
#                           an empty stronghold BLOCKS the rebuild (referee: no UPGRADE with an enemy
#                           present -- EXPAND_AHEAD's own blockade, mirrored offensively). On watch
#                           disengages, bodies already on an empty non-HQ stronghold stay unless locally
#                           outnumbered (enemies within 2 hops > campers). RAZE_CAMP=0 => byte-identical.
PS_TTL = 1                # R58 (1(64) loss; user: "32턴에 이미 우리 기지를 공격하러 오는걸
#                           알아야 -- 인지하면 가까운 밑에 기지 가용인원으로 충분히 막았다"): PREDICT_STAGE's
#                           reach window extends from the group's ARRIVAL to the base's FALL (arrival +
#                           ceil(hp / (group - turret)), defenders-dead worst case). The t32 inference was
#                           already firing; the arrival-bar just could not see the 2-hop reinforcements
#                           that make the hold. Same TTL arithmetic as RELIEF_TRIAGE, defensive twin.
#                           PS_TTL=0 => byte-identical.
PS_PULL_MAX = 3           # R58 delivery: neighbor-sitter pull per episode (NEIGHBOR_RELIEF's proven cap)
PS_PULL_COOLDOWN = 8      # R58 delivery: turns between pull episodes (sizing arithmetic loses; throttle wins)
RELIEF_TRIAGE = 1         # R57 (1(63) loss; user: "이미 늦어버린 싸움에서는 그냥 상대기지를
#                           공격하는 전술이 필요해 ... 방어하러 명령 보내기 전에 계산부터 하고 보내는
#                           로직"): before the FULL relief dispatch, compute whether ANY winning relief
#                           can arrive -- TTL = ceil(hp / net-siege) + 1, winning = sitters + turret +
#                           within-TTL bodies >= attackers. A lost relief re-commits the same fist to
#                           the raid machine (_raid_commit: crack-sim + phantom gated). 1(63) t86: base
#                           33 TTL ~2 vs a 6-hop march (15 bodies wasted; enemy base 43 unguarded at 2
#                           hops -- razed only 12 turns later). home_safe + on_hq==0 gated: a home
#                           emergency keeps the defensive march. RELIEF_TRIAGE=0 => byte-identical.
COMMIT_STRIKE = 1         # R71 (1(77) loss, wide K15, current-build mm=0; user: "70턴 상대가 밑으로
#                           러쉬 -- 경로 확실하니 방어할지 공격할지 정해야, 이때는 공격이 정답. 우리는 중앙에
#                           모여있고 상대 가용이 최하단으로 이동해 상대 HQ가 멀어짐 = 큰 기회. HQ 부술 수 있는지
#                           정밀 계산 -> 불가면 가까운 상대 기지. 우리 큰 부대가 3턴 내 지원 불가면 공격으로").
#                           Verified referee-exact: t67-71 our 7-9 fist _can_crack the enemy's OPEN L2 HQ while
#                           our own HQ sat L1 all game -> reactive defense chased the stack 45->64 and we lost
#                           the tiebreak. COUNTER-DOOMSTACK owns the territory-BEHIND case (counter_now); this
#                           fires while EVEN/AHEAD, gated PURELY by (a) the enemy stack far from its own HQ
#                           (rear open, CS_OPEN+ hops), (b) a REFEREE-EXACT _can_crack of that HQ -- else its
#                           nearest crackable base (the user's fallback), and (c) a RACE guard: our slowest
#                           striker reaches the target no later than the enemy stack reaches OUR HQ (so we win
#                           the mutual race; cracking their HQ ENDS the game before their march even lands).
#                           Rush/turtle self-exclude (rush HQ far+garrisoned => _can_crack False + race lost;
#                           turtle keeps its stack home => CS_OPEN fails). COMMIT_STRIKE=0 => decision-identical.
CS_OPEN = 4               # the enemy stack must be >= this many hops from its OWN HQ (its rear is genuinely
#                           open; 1(77) t67 stack@29 = 6 hops from enemy HQ). A stack hugging its HQ is not a
#                           strike opening -- that is a turtle/fortress (never committed forward).
CS_MIN_FORCE = 6          # a real gathered fist (= MOBILIZE_NEAR); a 2-3-body trickle never all-ins an HQ.
CS_RACE = 0               # our slowest striker's hops-to-target must be <= the stack's hops-to-OUR-HQ + this.
#                           0 = strict (we arrive before they even reach our HQ, let alone crack it). The
#                           _can_crack gate already guarantees we FINISH the siege; this guarantees we START
#                           it in time. Raising it trades safety for aggression -- keep strict, battery-tuned.
CS_FINISH = 1             # R75 (5(12) AI5 loss, K19; user: "t176 상대 본진을 20명으로 치면 끝낼 수 있었어? 아니면
#                           일찍이 막던지"): 5(12) went to TURN_LIMIT and we LOST the level tiebreak (our HQ L4 <
#                           enemy L5) -- turtling was a GUARANTEED loss, so cracking the enemy HQ was the ONLY win.
#                           The enemy HQ was OPEN (its all-in fist left only 8 defenders) and REFEREE-CRACKABLE by
#                           our 35-unit forward army from t174, but COMMIT_STRIKE never fired -- its force pool is
#                           the surplus raid_force (13 at t176), while the army that can crack the L5 HQ is the
#                           FORWARD SIEGE army roaming enemy bases (assigned, invisible to raid_force). Razing
#                           bases we cannot convert to a win while an open HQ sits there is a wasted endgame.
#                           CS_FINISH: when BEHIND on HQ level (must crack to win) and the enemy HQ is open, pull
#                           the forward MOBILE army (closer to the enemy HQ than to ours = not the home garrison)
#                           onto the HQ, gated by the same referee-exact _can_crack + de-poisoned race guard
#                           (nearest cracking subset, straggler-immune -- the R71b fix). Only fires late-game
#                           (turn >= CS_FIN_TURN) and only when behind on level, so it is a last-resort finisher,
#                           not a general all-in. CS_FINISH=0 => decision-identical (COMMIT_STRIKE R71/R71b only).
CS_FIN_TURN = 140         # CS_FINISH ARM 1 (behind-on-level) only from this turn on (endgame must-win closer)
CS_FIN_AHEAD = 1          # R77 (1(84) t77): CS_FINISH ARM 2 -- even AHEAD on level, finish an OPEN referee-crackable
#                           enemy HQ with the forward army we already have deep on the offensive (a decisive HQ kill
#                           beats grinding to a turn-limit tiebreak). CS_FIN_AHEAD=0 => ARM 1 only (R75-identical).
CS_FIN_NEAR = 7           # ARM 2 arms only when our nearest forward body is within THIS many hops of the enemy HQ
#                           (we are genuinely ON THE OFFENSIVE -- the gate that separates it from rush defense,
#                           where our army sits home far from the enemy HQ)
CS_FIN_REACH = 4          # R106 (1(102) t63-65 draw, we=RIGHT; user: "소수가 상대 HQ에 박혀서 죽는 유닛들"). ARM 2's
#                           _cs_near gate checks only the NEAREST body, so it committed a fist SPREAD 4-8 hops from the
#                           enemy HQ (1(102): reach=8, 7 bodies) that trickled in over 8 turns and died piecemeal to the
#                           turret + the train_cap warriors the HQ pumps EVERY turn -- the static HQ_CRACK_MARGIN buffer
#                           (~2 turns of training) cannot model an 8-turn approach. Fix: ARM 2 also requires the whole
#                           cracking fist GATHERED within THIS many hops of the HQ (the same gathered-fist discipline
#                           COMMIT_STRIKE's max-hop bound and ARM 1's race bound already enforce) -- commit only an
#                           ASSEMBLED fist, never a spread trickle. 1(84) ARM 2 fires at t158 (fist AT the HQ) so it is
#                           preserved. If no gathered prefix cracks, _cs_tgt stays -1 -> the fist raids bases / holds.
CS_FIN_AHEAD_TURN = 60    # ARM 2 turn floor (keep it out of the opening; the army-deep + HQ-safe guards do the rest)
CS_FIN_HOLD_MARGIN = 1    # ARM 2 commits only if home defenders (reachable by the stack's arrival) + turret exceed
#                           the stack by THIS -- a referee-aligned "our HQ survives while we take theirs" guard
CS_FIN_EARLY = 1          # R78 (1(85) t56-70, narrow K9; user: "좁은맵 특성상 적이 기지 연달아 노리면 HQ 털기 쉬움
#                           -- 방금 넣은 로직 동작 확인"): ARM 2 was DEAD-LETTERED -- its CS_FIN_AHEAD_TURN(60) floor
#                           sat INSIDE the CS_FIN_TURN(140) outer gate, so the ahead-finish could never fire before
#                           t140 (1(85): enemy over-commits forward t56-58, HQ open + referee-crackable from t58, yet
#                           ARM 2 silent). This drops the OUTER floor to ARM 2's own CS_FIN_AHEAD_TURN when armed;
#                           ARM 1 keeps its 140 floor via its own _cs_behind guard. Same army-deep + HQ-safe +
#                           referee-crack guards do the safety work. CS_FIN_EARLY=0 => outer floor stays 140 (R77-exact).
SPENT_RAZE = 1            # R79 (1(86), long map K17; user: "잘 막았는데 치고 나가는 타이밍 놓쳐 패 --
#                           t158 우리 가용5 vs 적1, 적 중앙기지 밀 수 있었다. 긴맵이라 HQ 못털어도 중앙기지 밀기는 가능"):
#                           the enemy's early all-in is militarily SPENT (avail 0-1, a 1-2 residual chip) but its
#                           ECONOMY bases stand intact and it BANKS that income into HQ climbs -- it out-leveled us
#                           (enemy L2@166->L3@191 vs our L2@176) while our surplus (raid 5-8, referee-CAN crack its
#                           central base) sat home (threat_army sticky-maxed by the residual routed the surplus to
#                           muster-home). Turtling to the tiebreak with a crackable enemy ECONOMY base in reach LOSES:
#                           convert the idle surplus into razing it (long map => enemy HQ uncrackable, but its base
#                           is) to deny its climb. NOT a COMMIT_STRIKE relax (its enemy_stack_sz>=6 premise is rush
#                           defense and must stay) -- this is the OPPOSITE trigger (enemy SPENT, not over-committed).
SPENT_RAZE_TURN = 120    # endgame/mid-late only (the climb race is decided here; keep out of the opening where a
#                          between-waves lull can look spent). Rush/wave are excluded by the stack/avail gates anyway.
SPENT_RAZE_STACK = 3     # enemy's largest stack must be <= this (a residual chip, NOT a committed rush/wave >= 6)
SPENT_RAZE_EAV = 2       # enemy AVAILABLE army (total - workcap) must be <= this = genuinely spent
SPENT_RAZE_MIN = 4       # our committing fist floor (referee _can_crack does the real sufficiency check; this just
#                          keeps stragglers from committing). Below CS_MIN_FORCE(6) because the target is def 1-2.
SPENT_RAZE_HOLD = 1      # home referee-safe margin (home turret + reachable defenders >= residual stack + this)
SPENT_FINISH = 1         # R83 (4(2) vs AI DRAW, K15; user: "후반에 HQ에 인원소비하지말고 좀더 후에 한방에 모아서
#                          보내가지고 HQ를 깨는게 나을거 같은데"): when the enemy is SPENT, SPENT_RAZE only razes BASES
#                          -- it never takes the enemy HQ even when a GATHERED fist referee-cracks it. 4(2): tied L3,
#                          enemy avail 1-2(spent), our 20-30 army referee-CAN crack the enemy L3 HQ from t120, but we
#                          only razed bases -> DRAW. The spent-gate (avail<=2 => enemy can't reinforce) is EXACTLY what
#                          makes an HQ crack safe here where the peer fight (5(13) avail 15v15 -> R82 loss) is not. Fix:
#                          inside SPENT_RAZE, PREFER the enemy HQ when our forward fist referee-cracks it AND clearly
#                          out-numbers its MOBILE reachable defense; else fall to the base pick. A decisive HQ kill
#                          converts these spent-enemy draws into wins. Bypasses CS_FIN_LVLGATE because the spent-gate
#                          (not the level gap) is the crack-reliability guarantee here.
SPENT_FIN_REACH = 5      # count enemy MOBILE (off-building) defenders within THIS many hops of the enemy HQ
SPENT_FIN_MIN = 8        # gathered fist floor for an HQ crack (bigger than a base raze -- an HQ has hp+turret)
SPENT_FIN_MARGIN = 2     # fist must exceed the reachable mobile defense by THIS (covers the HQ turret)
HQ_CRACK_MARGIN = 1      # R95 (1(101-104), we=RIGHT; user: "HQ 공격 판단은 주먹 = 수비 + 터렛 + (2*train_cap+2)"):
#                          COMMIT_STRIKE / CS_FINISH's `_can_crack(opp_hq)` reads STATIC defenders -- blind to the
#                          train_cap warriors the enemy HQ pumps out EVERY siege turn. A thin fist that merely TIES the
#                          snapshot then loses to the reinforcements, so it must not be committed to that grind. Fix:
#                          model the production as a STATIC buffer -- add (2*train_cap + 2) phantom warrior bodies to
#                          the HQ's defenders so `_can_crack` demands fist >= defense + turret + that buffer. Short of
#                          it => not crackable => the caller falls through to a base raze. HQ targets only, and only
#                          when the caller flags an HQ-finish (COMMIT_STRIKE / CS_FINISH). SPENT_FINISH (R83) stays
#                          UN-buffered on purpose: its spent-gate (enemy avail<=2) already proves the enemy CANNOT
#                          reinforce, so a buffer there would wrongly block a genuine finish. HQ_CRACK_MARGIN=0 =>
#                          byte-identical baseline (hq_reinf never adds anything).
CS_FIN_LVLGATE = 1       # R82 (5(13) vs AI loss, K19; user: "5번은 상대에게 막히면서 유리했던 경우를 다 토해내버려"):
#                          CS_FINISH ARM 2 is the "even AHEAD on level, finish the OPEN enemy HQ" arm (R77 1(84)), but its
#                          _cs_near gate never actually checked the level -- so it also fired at EQUAL level against a PEER
#                          HQ that can defend. 5(13) t119-125: both L3, avail 15 v 15, ARM 2 (fired early by R78) committed
#                          ~15 to the enemy L3 HQ; `_can_crack` is blind to the enemy pouring its 15 onto the HQ, the crack
#                          STALLED, we bled our army's tempo and fell behind (t176 L4<L5) -> lost a drawn/won game. Fix:
#                          ARM 2 requires STRICTLY ahead on level (mhL > ehL) -- restores R77's intent. AHEAD => the enemy
#                          HQ is a level weaker (fewer hp/turret) so the crack is reliable (1(84) L5 vs L2, 1(85) L2 vs L1
#                          both PRESERVED); EQUAL level (peer HQ, 5(13)) is a coin-flip we must not throw our army into.
#                          ARM 1 (behind) is unaffected (its own _cs_behind gate). CS_FIN_LVLGATE=0 => ARM 2 level-agnostic (R78).
OVEREXPAND_PUNISH = 1     # R56 (1(62) loss; user: "기지를 우리보다 2개 앞서가는 타이밍(t65)은 분명
#                           병력을 찍고 응징을 했어야 ... t76 가용인원이 훨씬 많은데 전혀 고려하지 않았어 --
#                           단순히 전체 병력수로만 계산"): punish window = enemy out-bases us by
#                           OXP_BASE_LEAD+ while its AVAILABLE army (total - workcap) is <= OXP_THIN.
#                           1(62) probe: offense gates open from t55, raid_force 0-1 through t65-77 --
#                           the gap was threat-driven TRAINING staying silent vs an all-worker expander.
#                           Arms the R51 army floor + upkeep-lean train; self-expires when the enemy
#                           fields an army. OVEREXPAND_PUNISH=0 => byte-identical.
OXP_BASE_LEAD = 2         # enemy bases >= ours + this ("기지 2개 앞서가는 타이밍")
OXP_THIN = 3              # enemy available (total - workcap) at/below this = unguarded land-grab
#                           (1(62) t65 measured 0; 1(71) t56-62 measured 3 while the enemy ran 8->11
#                           bases -- the punish window flickered shut at exactly the user's "가용병력
#                           3명뿐" moment, so the bar rises to 3. A masser/waverusher holds 5+ -> never arms)
EXPAND_ESCORT = 1         # R66 (1(73) K11 loss; user: "확장을 빨리하는건 좋은데 조금이라도
#                           상대가 우리보다 높은 가용인원이라면 기지 하나를 세울 때 반드시 HQ에서는 인원을
#                           뽑아놔야해 -- 이게 스노우볼이 터지는데"): in the OPENING, an available-army DEFICIT
#                           (enemy avail - ours, both total-workcap, the R56 operand pair) arms the R51 train
#                           plumbing with a floor of EXACTLY the deficit ("상대 가용인원만큼"). The loss: enemy
#                           trained 4 over t41-45 and hit center 34 at t46 while our wallet bought two far bases
#                           (t42/43) and our first train came t46 -> piecemeal relief fed the 4-stack -> center
#                           lost t50 -> avail snowball -> HQ cracked t127 with a 6v5 BASE lead (trains 30 v 36).
#                           MATCH_AVAIL needs a +3 base lead (had 1) and floors the HOME garrison; this fires on
#                           the deficit itself and merely restores PARITY, so a mirror (symmetric avail) and a
#                           passive economist (deficit <= 0) never arm it. Self-closing: parity reached => off.
#                           EXPAND_ESCORT=0 => decision-identical.
EE_TURN = 60              # opening window ("초반 특히") -- same band as MIL_GAMBIT's posture window; past this
#                           the READY_FLOOR / threat ramp / MATCH_AVAIL machinery owns army sizing.
EE_DEFICIT = 1            # fire from the FIRST body of deficit ("조금이라도 ... 높은 가용인원이라면").
EE_TURN_MIN = 25          # the escort belongs to MID-opening squad play (1(73): t41-50). Turns 1-24 are the
#                           foundational build-order where every 120g displaces the 600g L2 bank -- EE fires
#                           there refuted as waverush-K9 cracks (small maps run the thinnest L2-vs-first-wave
#                           margin, and a ramping masser passes through the <=4 avail band exactly then).
EE_EAV_MAX = 4            # escort only a SQUAD-sized enemy avail (1(73) squad = 4). Above this = a massing
#                           army -- MIL_GAMBIT / threat-ramp territory (fortress + lean), never 1:1 chasing
#                           (the refuted matcher chased waverush's ramp through this band into bankruptcy).
EE_CLAIM_WIN = 6          # escort window: fires only within this many turns of our most recent base BUILD
#                           ("기지 하나를 세울 때" -- the train is attached to the expansion event, not standing
#                           policy). A claim-frozen game (waverush pins the wallet) closes the window itself.
CK_PARK_MIN = 2           # R55 (1(60) t98 draw; user: "99턴에 노동자가 모든 작업장에서 튀어나와 골드 누수로
#                           이길 수 있던 게임을 놓침"): second OR-arm of CONC_KEEP_ECON. The not-advancing
#                           test misses a parked outpost when the largest-cluster pick JUMPS (enemy-HQ
#                           recruit pool dist 10 -> outpost dist 3 reads as advancing; next turn a marching
#                           column takes the pick and releases the latch -> repeated worker round-trips).
#                           If the stack's node also held >= this many enemies LAST turn it is a sitting
#                           outpost -- keep the base workers. Two-turn residency is impossible for a
#                           rushing beeline (fresh node every turn).
RAIDPH_LEAN = 0           # R52: FALSIFIED -- OFF. Hypothesis: the 4-trains/8t evidence bar let 1(52)'s
#                           feeder hold EXACTLY 3/8t under it (t79-81/t112-119: commits resumed, 14 dead).
#                           Measured refutation (my-bot K19 s2003): at bar 3 the phantom veto fires on a
#                           TURTLE training 3/8t while besieged -- the r51 build RAZED its HQ (win); with
#                           the lean bar the winning crack was vetoed and withdrew (W->D, isolated to this
#                           flag). Low evidence = noisy rate estimate; bar 4 exists to demand confidence
#                           before injecting phantoms. The 1(52) feeder class goes back on the residual
#                           list. Keep 0 unless a shape separating 'human drip-feeder' from 'besieged
#                           turtle' is found (e.g. feeder trains while NOT under siege).
MASS_DEPART = 1           # 3.txt t65 (the user's worker-vs-operator rule, launch side): bodies stored in
#                           enemy WORK SLOTS are latent army -- the turn >= MASS_DEPART_F of their whole
#                           army pops off a multi-turn park (>= MASS_DEPART_PARK turns on an enemy building)
#                           and advances 2 straight turns, treat it as the all-in launch: arm the
#                           SIEGE_EMERGENCY recall WITHOUT waiting for the crossed-midline test (t67 vs
#                           t70 = 3 extra turns of recall + rescue training). A mirror fist (~30-40% of
#                           total) or a turtle (never advances) can't trip the 55%-commit signature.
MASS_DEPART_PARK = 5
MASS_DEPART_F = 0.55
RAZE_CHAIN_HOLD = 1       # 4.txt (user: "그냥 차례로 공격해도 됐는데"): the turn a base falls, most fist
#                           bodies are MOVING (landing on it) so the re-orderable force reads 1-3 <
#                           MIN_RAID -> R7's RAID_MIN_COMMIT forced newt=-1 -> WATCH_LOCK(4) withdraw
#                           yo-yoed the whole fist home (raze t136 -> next commit t145), letting B rebuild
#                           razed slots (66/71 razed 3x each) and keeping FINISHER's remnant gate closed.
#                           If the landing mates (MOVING, target within 1 hop of the fist) refill the fist
#                           to >= MIN_RAID, HOLD one turn (no orders, no lock change) and re-pick with the
#                           full fist next turn = chain razing, ~2,000g of double-commutes saved.
CHIP_STATIONARY = 1       # 4.txt t190 (honesty bug): the HQ_CHIP ALLIN-window pool counted MOVING bodies
#                           the sim approved as attackers/survivors, but order_move() no-ops MOVING -- 9
#                           simmed, 6 launched, wiped for ZERO siege on a 25==25 HP race. Pool = STATIONARY
#                           only, so the sim, the bill, and the launched squad are the same set.
ZERO_OPS_CLIMB = 1        # 4.txt (worker-vs-operator, bank side): B fielded ZERO operating units from t40
#                           (every body on a B building) yet our climb bank waited for LATE_CLIMB=130 --
#                           all prior income fed a want_spare=16 fist (3,840g trains + 6,760g move bills ~
#                           2x the L5 step) against an enemy that never came, so L3 landed t167 / L4 t196 /
#                           L5 unreachable and total domination ended 25==25. When the enemy has fielded no
#                           operator for ZERO_OPS_STREAK straight turns (and home is safe), open the climb
#                           bank from ZERO_OPS_TURN. Streak resets the turn ANY enemy body steps off a
#                           building (= the MASS_DEPART launch signal), restoring the fist funding.
ZERO_OPS_TURN = 80
ZERO_OPS_STREAK = 15
ZERO_OPS_SLACK = 2        # <= this many off-building enemy bodies still counts as zero-ops (transit noise;
#                           we cannot see enemy move targets). 3+ = a real operator squad -> streak resets.
# --- V2 ROUND-9 (2026-07-03, AI-ladder rematch: 3 WIN t148 / 4 WIN tiebreak / 5 LOSS / 8 dropped-WIN draw)
# The user's "간극": R8 fixed defense+conversion for 3/4 but 5/8 exposed the other side — production and
# final purchase. g5(K19): B boomed zero-ops 100+ turns then trained 2/turn t104+ (19v31 -> 38v74) while
# our climb banks froze n=0 in every calm window (worker_deficit=0 makes the FIRST surplus train carry the
# whole reserve) — the armed K19 deny fist (want_spare=44) trained 2 bodies in its 40-turn life, and the
# catch-up ramps opened late (need base_lost) / self-terminated (margin hysteresis) / disarmed perversely
# (our razing flipped workcap parity at t172, re-latching a dead 3600 bank; HQ died t196 with 2810 peaked).
# g8(K9): we won attrition 22v11 and banked to 2313 (L4 bar 2506) — then HQ_CHIP launched 19 bodies in two
# waves into B's HQ park (march-blind sim), 14 died for ZERO siege, the 193g-short upgrade was never bought,
# and the winning 25v20 tiebreak was forfeited to a L3/20==L3/20 draw.
ZOPS_DENY_GUARD = 1       # g5: ZERO_OPS_CLIMB moved the 1200/2400 latches onto the ONLY window where the
#                           K-scaled deny fist was armed and B was soft (13-19 all-workers). An armed wide-map
#                           deny fist outranks the early bank — the zero-ops economist is exactly its prey.
#                           Ablation on 5.txt: 23 trains t77-104 vs 2, L3 lands 1 turn later (income covered
#                           both). g3=K11/g4=K15 <= WIDE_FORCE_ANCHOR -> byte-identical (their wins untouched).
OM_MASS_OR_INCOME = 1     # g5 t172 perverse disarm: our own razing flipped workcap to 19v17 in OUR favor ->
#                           _outmassed_soft/_om_drop (both require workcap-behind) DISARMED at army 38v66 and
#                           re-latched the dead 3600 bank. A 2x-margin absolute deficit is pressure regardless
#                           of the income sign.
VIS_RAMP_MATCH = 1        # g5 t104-115: B's 2/turn burst was PUBLIC information (total count growth) but the
#                           first ramp gate opened only t116 after a base burned. Sustained visible growth
#                           (>= VIS_RAMP_GROW over VIS_RAMP_WIN turns) + absolute deficit >= OUTMASSED_SOFT_
#                           MARGIN = a real bounded signal -> feeds _outmassed_soft (GRIND_RESCUE/_om_drop).
#                           K > WIDE_FORCE_ANCHOR only: g3/g4/rush byte-identical; a turtle's army does not
#                           GROW 0.8/turn; self-limiting (closes when deficit shrinks or growth stops).
VIS_RAMP_GROW = 8
VIS_RAMP_WIN = 10
DEAD_BANK_RELEASE = 1     # g5 t172-179: hq_reserve=3600 was arithmetically unreachable (needed 2212 more at
#                           realized ~76g/turn net with 28 turns left) yet froze training at 38v74. A bank the
#                           arithmetic says cannot fill by t200 — at HALF the ideal net rate (workcap income
#                           minus upkeep), the conservative margin — is dead capital; release _train_reserve
#                           (1c still buys opportunistically if gold ever crosses).
EG_UPG_REACH = 1          # g8 (the 193g miss): both chip launches outranked the L4 purchase that WON the
#                           tiebreak (upgrade heals to full 25 vs B's max 20). When our own next HQ upgrade is
#                           NET-income-reachable by t198 WITHOUT launching AND its full hp >= the enemy HQ max
#                           hp (wins/ties the race), suppress the chip pool entirely: everyone keeps earning,
#                           1c buys the upgrade. Own heal outranks the chip — now with projected affordability.
CHIP_MARCH_SIM = 1        # g8 honesty fix #3 (after STATIONARY/phantom): CHIP_SIM_GUARD simmed the fight as
CHIP_REACH_DEF = 1        # R70 (1(76) draw, 상호 L5 K19; user: "상대 HQ와 인원 계산해서 한방 주먹
#                           모으고 조금이라도 피 깎을 수 있을 정도가 모이면 그때 보내자"): the chip sim counted
#                           defenders within 1 HOP of the enemy HQ -- lain's 25-body army sat 2-4 hops out at
#                           launch (t160), converged during our 10-turn column march, and ate 36 bodies for
#                           1 siege while the sim had approved a fight vs ~8. Defenders that can REACH their
#                           HQ inside OUR arrival ETA are in the fight (REACH_WIN's proven arithmetic, applied
#                           to the other side) -- count them. An honest bar auto-implements the user's "모이면
#                           그때": blocked chips keep the MAX_SWEEP lean top-up training (our 3-4x income wins
#                           the accumulation race), and the launch fires only into winning arithmetic.
#                           CHIP_REACH_DEF=0 => decision-identical.
#                           starting NOW (12 fight-turns approved) but the march was 7-8 hops — real window 7
#                           turns; and it counted only ON-TILE defenders (6) while B's park sat 1 hop away.
#                           Horizon = turns left MINUS march ETA; defenders include enemies within 1 hop.
CHIP_NET_KEEP = 1         # g8 t190: _keep used GROSS income (3 workers "cover" a 193g shortfall) and launched
#                           8 earners; with 44g/turn upkeep the real net was +1..29/turn. Fund the shortfall
#                           from NET income (add the upkeep bill to the numerator).
# --- V2 ROUND-10 (2026-07-03, v2r5-era user-bracket draws 1(7)/1(8)/1(9); dup-audit round) ---------------
# 1(7) "교착+우위+기지격파 -> 아군근접 L2" = ALREADY COVERED (PRESS_L2 + L2_SAFE fire at t149 in the current
# build's drive; v2r5 missed it only through raze-chain MOVE churn R8 already removed). No new lever (dup).
FLEE_FINISH = 1           # 1(8) t74: the fist stood ON enemy base 48 with 2hp left (one siege tick) and the
#                           flee test (_stop >= force) yanked it — no kill-ETA term, and flee runs BEFORE the
#                           lock-commit _can_crack so even CRACK_HORIZON=1 cannot reach it. The base then
#                           lived 37 more turns and the freed stopper razed our 37/33. When the committed
#                           bodies ALREADY within 1 hop of the live target provably raze it within
#                           FLEE_FINISH_TURNS by referee-exact sim — with the stopper injected as arrivals at
#                           offset=hops (same-turn arrivals DO defend: referee resolves moves before combat/
#                           siege) and the CLUSTER_KEEP_F survivor gate — postpone the flee and finish the
#                           tick. The user's 지원군-ETA doctrine on the DISENGAGE side (commit side =
#                           CRACK_HORIZON, resubmission knob). Fires only on a provable kill; a stopper that
#                           can genuinely contest in time still reads uncrackable -> flee stands.
FLEE_FINISH_TURNS = 2
SPLIT_RELIEF = 1          # 1(9) t95-130: the enemy split 4+3 onto two of our bases; EVERY response-target
#                           picker (stack_reg / _fwd / _relief_tgt / _eat_reg) is Counter.most_common(1) —
#                           all 8 relief bodies chased the top prong while the bottom razed 38/43 nearly
#                           unopposed, then whack-a-mole through t130 (bases 6->1). When >= 2 eater groups
#                           stand on OUR buildings, dispatch a SIZED squad (group+1 nearest, the
#                           RELIEF_SIZED rule) to each winnable group (army + local turret >= group+1),
#                           urgent-first (base hp / eaters TTL), from raid_force ONLY (defenders_needed and
#                           the HQ guard are funded first = 운용 가능 병력 한정); the remainder keeps its
#                           commit. Defense lever: locally provable only as no-regression (#41).
PRONG_DETECT_K = 3
BEHIND_PRONG = 1          # 1(9) (the user: "이 팀 전략이 맘에 듦 — 밀린다고 판단되면 우리도 분산해서 피해를")
#                           MULTI_PRONG's gates are winning-side only (not-behind/econ-lead/overwhelm). Add
#                           the LOSING-side arm — the enemy's own d9 move: land deficit (enemy bases - ours
#                           >= BEHIND_PRONG_BASELEAD) or a latched _outmassed_soft, with a real fist
#                           (raid_force >= BEHIND_PRONG_MIN, surplus AFTER defense is funded) and time for
#                           the round trip (turn <= BEHIND_PRONG_UNTIL) -> fire _two_front_raid, but ONLY at
#                           targets a HALF-fist provably cracks (_can_crack pre-filter) = guaranteed razes,
#                           never trades. The mirror lesson (분산<집중, 13W7D->9W11D) is contained by the
#                           asymmetric losing gates a ~1x mirror never enters + per-prong crack certainty.
BEHIND_PRONG_BASELEAD = 3
BEHIND_PRONG_MIN = 8
BEHIND_PRONG_UNTIL = 170
# ======================================================================================================
# V2R12 (2026-07-03, user doctrine from bracket losses 1(10)..1(15) -- all six fidelity-0 on this build).
# The user's forensic reading, confirmed gate-by-gate on the replays:
#   1(10)/1(11)/1(13): "전방 기지에 가용 인원을 배치 안 한다 (근무태만)" -- the surplus fist WATCH-loops at
#     the HQ (withdraw -> nearest friendly = HQ where it trained; forward staging only from t100), so when
#     the enemy strikes a forward base we arrive one turn late every time (1(13) t45: else-branch mustered
#     the defenders HOME to 54 while the 5-stack landed on base 40 one hop away; t46 relief u-turned; base
#     fell; the chase stayed one hop behind through t53).
#   1(12) t62 / 1(15) t56: "상대 가용(운용) 병력을 세지 않는다" -- the enemy fielded 5-8 visible operators
#     while our spare stayed 1-2; the rush prep was visible for 10+ turns and we neither trained nor staged.
#   1(14) t66-67: a FORMING far stack (d=8, parked at its own HQ, not advancing) inflated the home garrison,
#     shrank raid_force 5->1 mid-siege (commit released), and the re-formed fist -- standing ON a 9-hp base
#     -- walked home under the fresh WATCH lock. "HQ 훈련으로 막을 수 있으면 백도어는 계속한다."
# FOUR active levers (OPS_MATCH / FWD_STATION / FLEE_HOLD / SIEGE_STICK), all riding EXISTING paths
# (single-owner _raid_commit / _withdraw / else-muster unchanged in shape; no new dispatcher). A fifth,
# STAND_GROUND, was designed and then REMOVED after adversarial review (rush-safety breach -- see its flag).
# _hold_ground = home_safe AND not out-produced AND no closing wave AND K<=15 -- the user's "HQ에서 계속
# 뽑아내면 막을 수 있을 때" condition -- gates every offensive/positional hold below.
# Rollback: set the four flags to 0 (byte-identical command stream to v2r10, verified).
OPS_MATCH = 1             # 1(15): count the enemy's OPERATIONAL army (total warriors MINUS its income-worker
#                           need = enemy_total - _enemy_workcap, the R8 노동/운용 구분) and floor want_spare at
#                           it, so a rush BUILDUP is answered with our own fielded bodies BEFORE it launches.
#                           Forensic: the off-building _en_ops8 count only spikes AT launch (g15 0->8 at t56,
#                           too late), while enemy_total-workcap grew visibly 3->8 across t43-54 -- 13 turns of
#                           warning. Correctly INERT vs a balanced economy (g12: surplus ~0, we already
#                           out-number them -- that was a climb/positioning loss, not an army-count one).
#                           Placed among the want_spare floors so the REL_ARMY/ENDGAME min-trims still win vs
#                           a contained army / annihilated remnant. Gated home_safe (the buildup window) and
#                           not-behind-HQ (trailing the climb -> bank it, never pin spares).
OPS_TURN = 35             # not before the opening claim wave settles (claim funding owns want_spare there)
OPS_MIN = 3               # enemy operational surplus <= 2 is normal economy slack, not a forming army
OPS_CAP = 12              # never fund past a CRACK_FORCE-sized fist off this signal alone
# --- MID-GAME MILITARY READINESS (V2R13, 2026-07-03, user directive from games 4/6) -------------------
# The user's observation on the two structural draws: mid-game we over-bank the HQ climb and let our army
# fall well below the enemy's -- "if the attack had come in 4/6 we'd have been helpless." The rule: when we
# hold the advantage (not trailing the HQ race, home safe) keep AT LEAST the enemy's operational-army count
# fielded so a surprise assault during the bank window cannot take our bases -- WITHOUT abandoning the climb
# (proper balance). Mechanism = INCOME_FLOOR's template generalised off the enemy's TOTAL operational count
# (enemy_total - workcap) instead of a 10-stack: raise target_army to workcap+enemy_ops and fund it RESERVE-
# FREE (worker_deficit / _econ_floor), so those bodies train DURING the climb window; the climb still banks
# from income ABOVE them, and train_cap (1-2/turn) keeps it a gradual ramp, not a gold dump. Self-limiting:
# a FLOOR -- once we reach parity, deficit is 0 and we bank fully. Self-correcting: gated `not _behind_hq`,
# so if matching the army ever costs us the HQ lead, it drops and the catch-up climb resumes (no spiral, no
# turtle-pin loss). K<=15 (wide maps keep deny/ANTIBOOM). off = byte-identical.
READY_FLOOR = 1
READY_TURN = 50           # mid-game onset (after the opening claim/army settles)
READY_MIN = 4             # enemy operational surplus below this = normal economy slack, no readiness needed
READY_CAP = 16            # cap the matched soldier count (bounds the ramp; upkeep-safe)
READY_EDGE = 1            # "at least MORE than the enemy's available" -- match + this
# --- MATCH_AVAIL (user 8(4).txt: "상대 가용인원 +1~2로 유지하면 어느 상황에서나 괜찮다") ------------------------
# READY_FLOOR (above) already matches the enemy's AVAILABLE army (_op_surplus = enemy_total - workcap) -- but it
# raises target_ARMY and lives ONLY in the else/build branch (RTRACE: it fires ZERO times in 8.txt/8(4) because
# the bot is always in an OFFENSE branch: _finisher/_deny/_hq_chip/_harass). The offense branches decide how many
# to hold HOME off target_GARRISON, which only a CONCENTRATED stack (threat_army) raises -- so during the enemy's
# STEADY buildup (no concentrated stack yet) harass_budget = my_warriors - target_garrison sends nearly everyone
# forward and the home is thin when the wave finally commits (8.txt: bases razed one by one). MATCH_AVAIL floors
# target_GARRISON at the enemy's AVAILABLE army + margin so EVERY branch keeps the matched deterrent home (the
# 8(4) winning tempo: matched standing army -> enemy can't crack -> we win on economy/climb). Counts AVAILABLE not
# TOTAL, so enemy base-WORKERS never inflate it (the 복리-collapse MATCH_TOTAL was turned off for). BASE-AHEAD
# gated: a symmetric mirror is never base-ahead by the margin (measured max mirror base-lead = 2), so MATCH_AVAIL
# is byte-INERT in the mirror -> it CANNOT reproduce MATCH_TOTAL's 13W7D->9W8D3L over-train regression. Rollback:
# MATCH_AVAIL = 0 (byte-identical). Backup proto_v2r30matchavail.
MATCH_AVAIL = 1
MATCH_AVAIL_MARGIN = 2     # hold enemy-available + THIS at home (the user's "+1~2").
MATCH_AVAIL_BASE_MARGIN = 3   # only when we lead by THIS many bases (mirror never sustains +3 -> byte-inert there).
MATCH_AVAIL_MIN = 4        # enemy available below this = economy slack, no deterrent needed (matches READY_MIN).
MATCH_AVAIL_CAP = 22      # cap the matched home garrison (upkeep-safe; base-ahead surplus funds it, never starves climb).
MATCH_AVAIL_TURN = 45     # onset (after the opening claim/army settles; below READY_TURN so the deterrent forms early).
CONSOLIDATE_ARMY = 1      # R73 (5(9) AI-5 loss, K19; user: "HQ 3레벨 올리자마자 인원을 다량 찍어내는게 맞아 --
#                           땅을 우리가 많이 소유하면 상대는 2레벨 기지 잃으면 타격이 엄청나고 우린 1레벨 기지
#                           잃는건 별 손해 아니니 이 트레이드가 유리, 굳히기"): once the HQ has climbed to a
#                           defensible level (>= CONSOL_HQ) and we are LAND-DOMINANT (bases >= enemy +
#                           CONSOL_BASE_LEAD), the accumulating gold must become ARMY, not sit idle. 5(9): gold
#                           446 -> 2566 banked idle over t117-130 (right after HQ hit L3) while our army shrank
#                           30 -> 22 and the enemy massed a 32-total / 15-available army; the garrison floor
#                           (MATCH_AVAIL) was set but nothing drove the training. Floor the army at the enemy's
#                           TOTAL (so a straight fight never out-masses us; capped MOBILIZE_CAP) -- the surplus
#                           gold consolidates the win. The land-dominance gate makes it mirror-inert, and the
#                           climb reserve + worker-first + upkeep-lean guards in the train loop are untouched
#                           (we militarize the EXCESS above the climb, never starve it). CONSOLIDATE_ARMY=0
#                           => decision-identical.
CONSOL_HQ = 3             # HQ level at which consolidation opens ("3레벨 올리자마자")
CONSOL_BASE_LEAD = 2      # land-dominance margin (our bases >= enemy + this); the L1-vs-L2 trade favors us here
CONSOL_EN_MIN = 6         # only when the enemy actually fields an army (available >= this = a real match target)
MIDEXPAND_ARM = 1         # R76 (1(82) AI loss, K17; user: "기지수 같으면 군사로 이득, 확장하려면 기지=인원"):
#                           mid-game (past AVAIL_CLAIM_GATE) over-expansion at an available-deficit -- suppress new
#                           claims + redirect the gold to the army (reuses CONSOLIDATE_ARMY's floor + lean bar).
#                           MIDEXPAND_ARM=0 => decision-identical.
MXA_TMAX = 110            # mid window ends here (endgame army logic owns it after); opens at ACG_TURN_MAX(55)
MXA_DEFICIT = 2           # fire only at a CLEAR deficit (enemy avail >= our avail + THIS); +1 tripped mirror noise
MXA_EN_MIN = 8            # enemy must field a real army (total >= this) -- a lone econ enemy never arms it
MXA_PRESSED = 1           # R84 (1(91) 유저 K17 loss, RIGHT_WIN TURN_LIMIT; user: "초반 과확장으로 치명타 -- t95
#                           HQ 인원이 적 한방주먹 근처 아군기지에 배치가 안돼 방어를 못 함"): MIDEXPAND_ARM's base
#                           gate (_oxh_myb>=_oxh_enb, "behind => catch-up expand is fine") is FALSE here -- we were
#                           behind on BASES (my 3-5 vs enemy 5-6) AND out-massed on TOTAL army AND under a SUSTAINED
#                           enemy push -- but NOT out-AVAILABLED (the enemy sinks its army into MORE bases so its
#                           avail reads low while its TOTAL out-masses us; the R76 avail-deficit gate is blind here).
#                           Measured t68-74: base 4<5, TOTAL 12 v 14, threat 8 -> 2b claimed a d5 midline salient
#                           (node 40) that razed for free; the run kept claiming (11/40/29/6th) while our army
#                           DROPPED 12->9 -> out-massed 14v17 -> lost the level race (both HQ L1 all game). Catch-up
#                           expansion is NOT fine while LOSING the military brawl: a SECOND, base-COUNT-INDEPENDENT
#                           arm fires on a clear TOTAL-army deficit (enemy total >= ours + MXA_DEFICIT) under a real
#                           push (threat >= MXA_THREAT_MIN). The +MXA_DEFICIT margin keeps it MIRROR-inert (a
#                           symmetric total never gaps +2; R76's mirror scar), and the threat floor is the safety:
#                           only stop expanding when the enemy is actively pressuring us on our half.
#                           MXA_PRESSED=0 => MIDEXPAND_ARM behaves exactly as R76 (base-ahead + avail arm only).
MXA_THREAT_MIN = 5        # the pressed arm needs THIS many ADVANCED enemy (on our half, within THREAT_RANGE) -- a
#                           genuine concentrated push (1(91) t68-88 ran 7-9), well above THREAT_MIN(4)/a lone raid.
RALLY_FALLBACK = 1        # R74 (5(11) AI5 loss, K19; user: "상대 공격으로 해당 기지를 못 막으면 집결 위치를 그 다음
#                           인근 기지에 -- 인원 뽑아 잘 막으면 된다"): a wave-band base-relief targets the base CLOSEST
#                           to the stack = the most-forward = the one razed first; the len(my_warriors) win test
#                           (reach-win NO-GO) fires it even when only a handful of bodies can reach that forward base
#                           by the raze. 5(11): a 11-stack serially razed 71/47/39/16 while ~30 of our bodies never
#                           made a stand. When the natural target is reach-UNholdable, redirect the relief to the
#                           MOST-FORWARD base on the stack's path to HQ that we CAN hold (reach-by-raze + turret >=
#                           stack) -- a defensive line one base back where the army converges. Only redirects a
#                           doomed target; does NOT change the fire decision (NO-GO's domain). RALLY_FALLBACK=0
#                           => decision-identical.
RALLY_FB_MARGIN = 0       # hold rule is defenders+turret >= attackers -> siege 0, so parity holds (>= stack)
RALLY_FB_SLACK = 1        # on-path slack: hops(stack->base) + hops(base->HQ) <= stack_dist + THIS
# --- AVAIL_CLAIM_GATE (user 1(30..33).txt: "초반 과확장 -> 가용인원 얇아짐 -> 기지 하나 앞서는 순간 상대 러쉬에 무너짐") --
# The 2b claim loop (~3560) scatters up to MAX_CLAIMERS surplus bodies/turn to expand, with NO check of our own
# AVAILABLE (mobile) personnel vs the enemy's FORWARD mobile army (workflow-confirmed critical gap: at NO dispatch
# point is our home thinness compared to the enemy's poised rush). So the moment we take a +1 base lead, the base-
# behind enemy commits a forward mobile stack (1(31) t36: A 0->5 fwd; 1(32) t32: A 0->5 fwd) at our new base while
# our surplus is still scattering 1-each -> 0 available -> the new base is razed and the economy bleeds out. This
# gate refuses to dispatch a claimer once doing so would drop our available reserve below the enemy's forward
# mobile + margin, keeping just enough home/near-core to hold the +1 base (1(31) base 38 needed only 2 vs 3
# attackers, and we had 4 reachable -- holdable if not scattered). _en_fwd_mob = enemy bodies OFF their buildings
# AND on our side of the midline = the rush FORMING before it concentrates (which _rush_brake/concentrate/threat
# all miss until too late). SAFETY: base-ahead(+1) gate + opening-only turn window => a symmetric mirror (early,
# no forward fist, never a sustained +1) stays byte-INERT; on a real committed beeline concentrate/siege_recall
# fire and the `not concentrate and not siege_recall` terms self-disable this, deferring to the STRONGER existing
# recall (holds MORE, never fewer) -> rush-crack-0 untouched. It only throttles CLAIMS; never lowers defenders.
# Turret covers 1 attacker so avail == en_fwd_mob already holds; +ACG_MARGIN is the decisive safety. AVAIL_CLAIM_GATE=0
# => byte-identical (every added term gated). Backup proto_v2r31availgate. Rollback: AVAIL_CLAIM_GATE=0.
AVAIL_CLAIM_GATE = 1
ACG_TURN_MAX = 55         # opening window only (the +1-lead rush hits t30-45); keeps it mirror-inert (early mirrors have no forward fist).
ACG_MIN = 3               # enemy off-building bodies near our territory below this = a scout/harass, not a rush (matches RUSH_MIN).
ACG_RANGE = 4             # count enemy off-building bodies within THIS many hops of one of OUR buildings = a rush APPROACHING our
#                           base (verified on 1(31): 5 within 4 hops of base 38 at t36, 3 turns before it razed at t39). The
#                           earlier "crossed toward our HQ" predicate was too late for a FORWARD-base rush (attackers reach the
#                           midline only at t37, one turn before razing) -- a forward-base rush must be read by proximity to the BASE.
ACG_MARGIN = 1            # keep enemy_forward_mobile + THIS available at home (turret covers 1; +1 = the decisive safety per feasibility).
# --- POST_WAVE_HOLD (1(30) t68: the wave passes -> defenders_needed collapses to guard-floor 1 -> the freed
# surplus is DUMPED out through the claim loop in a single turn, 3 claimers at once, and our available craters
# right when the repelled enemy can re-commit). Detector = the defenders_needed COLLAPSE itself (drop >= PWH_DROP
# after the final adjustment), NOT a concentrate transition -- trace-verified on 1(30) that the t63-66 wave
# defense was THREAT-driven (concentrate never armed), so only the collapse detector catches the release
# uniformly across the concentrate/threat/relief episode kinds. For POST_WAVE_TURNS after a collapse, clamp the
# claim dispatch to 1/turn -- expansion still proceeds, just BLED over a few turns so available never
# one-turn-craters. Mirror/economy safety: a 4-turn 1/turn clamp delays at most 2 claimers by 1-3 turns (the
# "확장 공백" failures were 40-130 TURN stalls); flag=0 => bookkeeping + clamp both skipped = byte-identical.
POST_WAVE_HOLD = 1
POST_WAVE_TURNS = 4       # consolidation window after the hold releases (the 1(30) dump was the very next turn).
PWH_DROP = 3              # defenders_needed must fall by THIS in one turn = a real episode released 3+ bodies (1(30) was 4).
# --- CORE_PREPOSITION (1(32): we hoarded 3 IDLE bodies deep on the HQ, hop-5 from the fight, while the enemy's
# +1-lead rush razed our forward bases one by one -- core bases 57/54 needed only 1/3 defenders and the idle
# reserve could hold them, it was merely MIS-POSITIONED). While base-ahead in the opening with an enemy mobile
# pack nearing our territory (same ACG signal), hold the reserve ON the reachable CORE base nearest that pack
# (within CORE_HOP_MAX of the HQ -- the outermost base is indefensible-as-built and is NOT reinforced) instead
# of deep on the HQ. Placement-only: inserted AFTER total_need is summed, so training targets are untouched; the
# 2a fill still fills the HQ guard FIRST (sort order) so the HQ is never starved -> rush-crack-0 preserved; a
# committed wave (concentrate/siege_recall) disables it wholesale and the standing garrison recalls as before.
# The held bodies were income-0 idle anyway (2nd+ body on an L1 building earns nothing) = zero tempo cost.
CORE_PREPOSITION = 1
CORE_HOP_MAX = 4          # a "core" base sits within THIS many hops of our HQ (1(32) base 47 was hop-5 = outermost).
FWD_STATION = 1           # 1(10)/1(11)/1(13): when the fist has nothing to do in a HELD state (_hold_ground),
#                           WATCH/stage at our FRONTIER base (the existing _withdraw(forward=True) machinery,
#                           today gated to t>=100) instead of idling at the HQ -- the user's "최전방 아군
#                           기지에 배치" (standing on our own base costs nothing per turn and the bodies are
#                           STATIONARY there when a wave lands, so base defense is by PRESENCE, not by a
#                           one-turn-late dispatch). Unsafe states keep the old nearest-friendly/home paths.
FWD_STATION_TURN = 40     # from the end of the claim wave; before that the spare IS the claim escort
STAND_GROUND = 0          # REMOVED (adversarial review, confirmed unsafe): holding a body on a contested
#                           forward base during the home muster modifies the RUSH/all-in recall else-branch
#                           (home_safe False), which a two-prong HQ-beeline + side scout could exploit to
#                           delay the HQ defenders -- a breach of the inviolable rush-crack-0 invariant the
#                           local rush suite does not cover. The 1(13) "근무태만" is covered by FWD_STATION
#                           (forward presence) + the existing _relief/base_eating. Flag kept at 0; no code
#                           references it now (the muster else-branch is byte-identical to v2r10).
FLEE_HOLD = 1             # 1(14): under _hold_ground, extend the FLEE_FINISH referee-exact finish proof from
#                           2 to FLEE_HOLD_TURNS turns -- "막을 수 있으면 백도어를 계속" (the 2-turn horizon
#                           only covers cracked-open bases; a 9-hp base 3 turns from death was abandoned).
FLEE_HOLD_TURNS = 5
SIEGE_STICK = 1           # 1(14) t67: bodies ALREADY ON/adjacent a live enemy BASE they alone provably raze
#                           within FLEE_HOLD_TURNS (same _sim_crack proof + CLUSTER_KEEP_F survivor gate,
#                           enemies in the window injected as arrivals) re-commit and finish instead of
#                           honoring a WATCH lock / re-pick walk-away. Base-only (never the HQ turret),
#                           _hold_ground-gated, monotone advance -> cannot oscillate.
# ======================================================================================================
# --- DENY-GAMBLE (user's g6 "견제" directive, 2026-07-02, EXPLICITLY OPTED-IN GAMBLE) --------------------
# The user's repeated demand across g4/g6/g7/g8: "우리가 HQ 앞서고 상대는 조용히 L2 경제 지어 따라오는데 우리는 아무
# 액션을 안 한다 -- 군사를 폭발적으로 찍어내서 상대 HQ 업그레이드를 못하게 견제하고 다녀야 한다." This funds the
# BASE-RAZING half of the old HQ_CRUSH doctrine (pour free gold ABOVE the climb reserve into a big army whose
# surplus routes through the backdoor and grinds the enemy's economy) WITHOUT the suicide _hq_assault (that
# stays HQ_CRUSH-gated=off). Fires EARLY (from DENY_GAMBLE_TURN) and continuously, vs an ECONOMIST too --
# memory says pinning an economist loses locally (weak local bots never climb), but the REAL ladder economist
# climbs to L4/L5 and takes the tiebreak, so denying its income is the user's knowing gamble. Efficacy =
# re-submission only. SAFETY (hard invariants preserved): home_safe + not _behind_hq + not _fortress + on_hq==0
# -> a rush (breaks home_safe / stands on our HQ) or an out-climber (breaks the HQ lead) turns it OFF, so the
# rush HQ-crack-0 defense and the trailing-climb catch-up bank are untouched. Rollback: DENY_GAMBLE=0.
DENY_GAMBLE = 1
DENY_GAMBLE_TURN = 60    # continuous 견제 from mid-opening (deny the enemy's economy BEFORE it funds the climb)
DENY_GAMBLE_GAP = 1      # any HQ-level lead (>=1) arms it -- "even a slight lead, keep harassing"
# --- WIDE-MAP DENIAL (the user's "조건 세분화", games 4/5): on a WIDE map (many strongholds) the win is
#     NOT out-climbing (both reach L5 -> draw) but DENYING the enemy's L5 climb -- keep the surplus army
#     EMPLOYED forward razing the enemy economy so it can never bank the 3600g for L4->L5 (the old v1
#     HQ_CRUSH doctrine, which WON 4/5 with 108-129 siege & B stuck L4, while the current coast DRAWS at
#     28-63 siege & B reaching L5 with a 0%-forward idle army). Gated to WIDE maps + army dominance so
#     COMPACT maps (7/8, K=9) NEVER enter it -> their verified out-climb wins are untouched (no regression).
WIDE_DENY = 1
WIDE_K = 11              # K (stronghold count, known at game start) >= this = WIDE map. 13->11: the BOUNDARY map (6=K11) drew because deny never fired (8 siege, B free-climbed L3->L5 in t150-176); 11 brings it into the SAME proven regime that won game 4. 7/8=K9 still OUT (out-climb wins untouched); 4=K15,5=K19 unchanged.
DENY_TURN = 60           # fire from mid-opening (the OLD code suppressed from the opening; a late gate misses the enemy's t170+ climb)
DENY_TURN_WIDE = 35      # on the WIDEST maps (K > WIDE_FORCE_ANCHOR, i.e. K>=17 = game-5-class) start razing + income-push EARLIER (t35; was 45, default 60). #15 forensics: the income-push pushed B's L5 from t188 to t198 (2 turns from the buzzer) but B STILL banked it -- the first siege only lands ~t75. Advancing the attack crushes B's economy from the opening so its whole climb slips past t200. Still gated by _econ_lead/_income_lead/home_safe -> only fires once A actually leads. K15 (game 4) and K9 (7/8) keep DENY_TURN=60 -> byte-identical.
WIDE_FORCE = 16          # under wide-map denial, fund THIS continuous attacking fist (the old code razed with a real army -> 129 siege, not a 6-unit chip -> 63). Sized to out-DPS forward L2/L3 bases while the enemy is still poor. SCALED UP on bigger maps (see WIDE_FORCE_ANCHOR/STEP) -- a 16-fist mustered only 36 siege on K19/N105 (game 5) where it must cover a huge spread AND the enemy out-produces.
AVAIL_DENY = 1           # R85 (1(92) 유저 K19 loss, RIGHT_WIN TURN_LIMIT L3<L5; user: "기지수는 상대에 훨씬 밀리는데
#                          총병력 비등 = 가용병력이 훨씬 많은데 이걸 못 굴린다; 우리 한방주먹은 계속 상대 기지를 부숴야"):
#                          1(92) t95-104 we were base-BEHIND (4-7 vs 9) yet held a clear AVAILABLE-army lead (myav 8-9
#                          vs enav 3-6), were HQ-AHEAD (L2 vs L1), and 8-9 of the enemy's 9 bases were _can_crack-able
#                          by our idle fist, home_safe. But over-expansion churn kept the army perpetually MOVING so
#                          the raid pool starved to 0 -- after razing ONE base (61) the fist drifted home while the
#                          enemy free-climbed L1->L5 uncontested -> lost the level race. Fix: re-form the raid fist
#                          from the MOBILE army (fist arm, below) so it keeps razing the next base. ★THREE tight
#                          gates isolate this from the wide-map wins it would wreck: (1) enemy OUT-INCOMES us
#                          (work_cap +INC -- it wins the race unless we deny); (2) EARLY-MID only (turn<=TMAX);
#                          (3) clear AVAIL lead (+MARGIN, mirror-inert). Ablation: dropping (1) lost turtle/my-bot
#                          K19 (there we out-income and must CONSOLIDATE); dropping (2) lost my-bot K19 seed2010
#                          (t143+ late raze threw a won race). With all three: matrix byte-identical to R84, 1(92)
#                          razes 61->87. home_safe + not-_behind_hq, _sim_crack self-limits. AVAIL_DENY=0 => byte-identical.
AVAIL_DENY_MARGIN = 3    # arm only at a CLEAR available-army lead (myav >= enav + THIS) -- a transient +1/+2 (mirror
#                          noise, a squad trade) must not flip into raze mode; +MARGIN keeps it MIRROR-inert.
AVAIL_DENY_INC = 2       # AND the enemy must OUT-INCOME us by THIS (its work_cap >= ours + THIS): the "it wins the
#                          level race unless we deny" discriminator that spares the wide-map wins we close by climbing.
AVAIL_DENY_TMAX = 120    # AND only in the EARLY-MID game -- denial suppresses the enemy's climb only BEFORE it techs;
#                          LATE (t143+ my-bot K19 seed2010) it trades our own climb-to-finish for pointless razing
#                          and threw a won level race. 1(92)'s window is t92-102; my-bot's harmful firing is t143+.
WIDE_FORCE_ANCHOR = 15   # K at/below which the fist stays at the base WIDE_FORCE. Anchored at game 4's K=15 so the WINNING config (K15) is byte-identical; only LARGER maps (K19 game 5) get a bigger fist.
WIDE_FORCE_STEP = 7      # extra fist per stronghold above the anchor: K19 -> 16 + (19-15)*7 = 44 (was 36 at step 5, 28 at step 3).
# --- WIDE INCOME-PUSH (the user's strategy) -- ONLY K>15 (K>=17) -----------------------------------------
# 5(1).txt proved the bigger fist is INERT in game 5: the fist CAP never binds because A is not TRAINING --
# A trains 0 troops across t100-180, HOARDING gold for its OWN HQ climb (reached L5 at t181 with 19 turns of
# slack), then floods 23 troops AFTER L5 = too late (B finished L5 at t188). The user's fix: when A's per-turn
# income DOMINATES the enemy's, the L5 climb is a foregone conclusion, so STOP hoarding the climb reserve and
# pour the surplus into the army that smashes the enemy's HQ-feeding economy. This is WIN_PUSH (rolled back for
# regressing the COMPACT out-climb wins 7/8) -- now hard-gated to K>15 (K>=17) so 7/8 (K9) and game 4 (K15)
# keep banking for their out-climb and stay byte-identical; only the widest maps convert hoard into army.
# The climb reserve is RESTORED from LATE_BACKSTOP(150) (guaranteeing A's own L5 by t200) and the instant the
# enemy out-climbs us (not _behind_hq) -- so the day-200 tiebreak is never forfeited.
WIDE_PUSH = 1
DOMINATE_PUSH = 1        # R14 (user: "턴당 골드 차이가 났는데 상대가 기지 업그레이드에 힘을 싣는 경우 -> 군사 더 찍어 응징"). _wide_push (above) does EXACTLY this but is hard-gated K>15, so games 4(K15)/6(K11) never get it: they bank income into their own L3->L5 climb while the enemy techs to L5 in parallel -> both-L5 draw. DOMINATE_PUSH is a K11-15 twin, gated on the SAME _income_lead margin so it only fires once our per-turn gold decisively leads AND the enemy holds a real (>=2-base) economy worth denying AND we are not 2+ HQ levels ahead (vs a low-econ rusher A out-climbs cleanly -- dropping the reserve there would forfeit that into a draw). K9 (games 7/8) stays OUT: their compact out-climb win is the reason WIN_PUSH was disabled, so it must not regress. flag=0 -> byte-identical.
WIN_INCOME_MARGIN = 2    # A's total work_cap (= income / WORK_INCOME) must exceed the enemy's by >= this for an "income lead" (2 work_cap = +30 gold/turn). Keeps the push off near-even economies.
WIN_GAP_FORCE = 2        # GAP-SCALED FORCE (the user's "턴골드 차이 확 벌어지면 병력 더 뽑자"): beyond the trigger margin, add THIS many warriors to the fist per extra unit of income (work_cap) lead. After mid-game A's income gap widens hard, so the fist should grow with it instead of capping at the flat K-scaled value.
WIN_GAP_CAP = 16         # ...capped here so a runaway gap (e.g. vs a crushed turtle, work_cap lead 15+) cannot train an unaffordable army that starves the economy/own L5. K19 fist: 44 (K-scaled) + up to 16 = 60. Self-limited further by train affordability + upkeep.
BEHIND_PUSH = 0          # KEPT OFF (freshly A/B tested 2026-07-03, not dismissed by analogy). Result: RUSH-SAFE
#                          (12/12 crack-0, unlike R15 -- home_safe + can-out-field gates hold), but (a) the GATED
#                          version below is INERT vs our own model/my-bot -- proto/my-bot balance army, so "behind
#                          on bases BUT enemy light on army" never occurs (BPvR17 mirror == R17-self byte-identical);
#                          (b) a BROAD "attack whenever behind" variant (enemy-light gate removed) mostly stays inert
#                          AND slightly HURTS where it fires (K19 mirror 5W-4L vs the 5W-2L baseline = 2 draws->losses).
#                          Root: when behind on BASES in a balanced matchup you are behind on ARMY too, so attacking
#                          loses the field then the tiebreak (the NOTE's 12/12, now confirmed by direct test). It
#                          COULD punish a real GREEDY over-expander (the user-bracket), but local bots can't create
#                          that scenario -> unvalidatable, and dropping the climb reserve when behind is a real risk.
#                          The SAFE expression of "don't lose when the enemy over-expands" is RACE_TIE (don't fall
#                          behind: race the center), which is validated-positive. Code kept flag-off + documented.
#                          [test scaffold] when the enemy is
#                          GREEDY early (out-bases us but is LIGHT on operational army = economy not yet converted),
#                          out-train (fund BEHIND_PUSH_FORCE reserve-free) and commit forward to PUNISH the timing
#                          window before the economy becomes army. This is a BEHIND-gated twin of DOMINATE_PUSH
#                          (which is AHEAD-gated). home_safe-gated (covers siege_recall/concentrate/_fort_hold ->
#                          rush-safe), only while we can still out-field them (enemy_total<=my_warriors+SLACK = a real
#                          timing window, not a hopeless deficit). Default 0; flipped on ONLY to A/B test the
#                          hypothesis head-to-head vs my-bot/mirror. flag=0 -> byte-identical.
BEHIND_PUSH_MAX = 130    # timing-attack window: after this the enemy's economy has converted to army -> too late.
BEHIND_PUSH_ENEMY_ARMY = 5  # enemy OPERATIONAL army (enemy_total - enemy_workcap) must be <= this = they went greedy
#                          on bases instead of army = the punishable window (a big enemy army = attacking loses).
BEHIND_PUSH_SLACK = 3    # only push while enemy_total <= my_warriors + this (we can win the field fight NOW; a
#                          hopeless army deficit means the timing has already passed -> revert to expand/defend).
BEHIND_PUSH_FORCE = 16   # army surplus to fund+commit for the punish (mirrors WIDE_FORCE).
# --- CLIMB-LEAD PUSH (game 6 -- the user's small-map insight) -----------------------------------------
# Game 6 (K11) forensics: the current bot out-climbs to L5 (t152) then COASTS (trains 0 t80-159), which lets
# B free-climb L3->L4->L5 (t150-176) => both L5 => DRAW. The old WINNING code never banked to L5: it trained
# army CONTINUOUSLY (45 spread across t40-179), pinning B into an army standoff so B spent all its gold
# matching the army and NEVER climbed past L2 -- final A_L3 > B_L2 = WIN. So on the BOUNDARY band, once we
# hold a DECISIVE HQ lead, do not coast: keep an army that pins the enemy (forces it to react/garrison
# instead of climbing). Unlike _wide_push this does NOT drop the climb reserve (we keep our own lead); the
# want_spare surplus only trains once our HQ is maxed -- exactly the post-L5 window the old coast wasted.
CLIMB_PUSH = 1
CLIMB_LEAD_MIN = 2       # need a >= this HQ-level lead to switch from coasting to pinning. Game 4 (K15) only ever leads by 1 (A_L5/B_L4) so it never trips -> byte-identical; game 6 reaches L4/L5 vs B's L2 (2-3 lead).
CLIMB_FORCE = 12         # standing army surplus to fund for the pin (routed through _harass_now). On top of the MATCH_TOTAL garrison, so the enemy faces a sustained force and cannot peel off to climb.
CLIMB_ENEMY_ARMY = 6     # ADAPTIVE gate (memory: pinning a PURE ECONOMIST loses 12/12 -- bases rebuild for 300, workers redistribute, our climb stalls). Only commit the pin once the enemy is clearly ARMY-INVESTING (its army exceeds its base count by >= this), i.e. a REACTIVE opponent that the pin actually slows. A pure economy-turtle (few warriors, many bases) never trips it -> we just out-climb it (no wasted army).
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
# --- EARLY FORTRESS (8-loss campaign fix #2: the HQ-kill root cause) ---------------------------------
# The 3 HQ-kills all shared: we were OUT-PRODUCED (enemy army 2-3x ours), threw our smaller army FORWARD
# into a losing battle (g1_6 t118: 11 units to region 15, ground down t121-125), and fortress could not
# rescue it because it is hard-gated to turn>=FORTRESS_TURN(140) -- g1_1's HQ died at t131 (fortress NEVER
# fired) and g1_6 lost its army at t121-125 (fortress fired 20 turns too late). EARLY_FORT lets fortress
# engage BEFORE the clock the instant the enemy army decisively out-scales ours, so the army consolidates
# HOME (holds, does not race out to die) and survives to climb/tiebreak instead of feeding a lost forward
# trade. Gated past the opening claim race (EARLY_FORT_TURN) and on a DECISIVE gap (EARLY_FORT_MARGIN) so a
# turtle/mirror that is not out-massing us never trips it. Rollback: EARLY_FORT=0.
EARLY_FORT = 1
EARLY_FORT_TURN = 70     # not before the opening/claim race is settled (firing at t60 cedes the whole midgame)
EARLY_FORT_MARGIN = 8    # enemy army must exceed ours by >= this -- a DECISIVE production gap, not a transient +6
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
# --- HOME_INTERCEPT (user directive) --------------------------------------------------------------------
# User: "소수 인원이 아니더라도 동선상 가까운 적을, 우리 가용병력으로 막을 수 있다면 막자. 계산할 때 HQ에서도 병력을 찍어
#        내는 것까지 계산해라." The diagnosis (intercept_test.py): an APPROACHING sub-wave stack (3..9) near our HQ
# triggers NO interception -- base_eating/counter_now/_relief/forward-push all need >=MOBILIZE_NEAR/>=WAVE_STACK_MIN
# or a stack already ON a base -- so we passively garrison until it hits WAVE_STACK_MIN(10)/on_hq and then panic-
# mobilize (mass-train + release base workers). Instead, when the stack is advancing, in our half, within reach,
# and a REFEREE-EXACT sim says (our surplus that can rally + our turret + the warriors the HQ can TRAIN over the
# ETA, gold-gated, as staggered arrivals) DECISIVELY annihilates it on our turret ground, RALLY the surplus there
# and kill it early. Surplus-only (guard stays home), home-side w/ turret support, decisive-win-only, short round-
# trip -> the anti-#40 posture (forward-intercept was net-negative; this fights ON our turret, not deep). The
# _sim_crack roles are INVERTED for defense: atk=enemy stack, base+turret=our rally building, def=our surplus,
# arrivals=our HQ trainees -> `not cracked` = we hold, and the returned survivors are the ATTACKER's (enemy) --
# so a decisive win is `not cracked AND enemy_survivors == 0`. HOME_INTERCEPT=0 => byte-identical (rollback).
HOME_INTERCEPT = 1        # LIVE. Validated on the combined build (with RELIEF_UNDER_SIEGE=1): rush 12/12 (0 HQ
#                           cracks) K9/K13/K19; mirror NEUTRAL (HI on==off) K13 5W3L4D / K19 1W5L6D. The
#                           UNRESTRICTED version regressed the pre-RUS K13 mirror 6W4L->4W6L (rallying surplus to
#                           a forward base costs raiding tempo = the #40 net-negative); fixed by the HI_RALLY_HOME
#                           (near-home only) + HI_MARGIN (clear-superiority) tighten. Rollback: HOME_INTERCEPT=0.
HI_MIN = 3                # smallest APPROACHING pack worth intercepting (1-2 = scout noise -> passive garrison).
HI_REACH = 6              # only intercept a stack within this many hops of our HQ (= THREAT_RANGE; "not too far").
HI_HORIZON = 12           # can-stop sim turn horizon (= MAX_CRACK_TURNS).
# Anti-mirror-regression gates (K13 mirror 6W4L->4W6L when unrestricted -- rallying surplus to a FORWARD
# base to defend costs raiding tempo, the #40 net-negative). Restrict to CLEAR-superiority + NEAR-HOME so
# the kill-squad only ever crushes a small stack at our own doorstep and returns fast (no forward diversion):
HI_MARGIN = 4             # squad must out-number the arrivable stack by this (no marginal/pyrrhic trades).
HI_RALLY_HOME = 2         # rally building must be within this many hops of our HQ (HQ-approach defense only,
#                           never a forward base -- base_eating/_relief own those; keeps the round-trip short).
# --- BASE_WORKER_RELIEF (user refinement of HI) ---------------------------------------------------------
# User: "초반 싸움 중 상대가 병력을 보내 아군기지 3칸 범위 내에 가용병력이 온다고 판단하면, 가까운 거리 노동자를 동원해
#        막을 수 있다고 판단하면 보내자. 물론 턴으로 도착 가능한 상황에서 모든 인원이 가는 방식이 아니라." The sim
# (bot_pusher) found HI never fires because its squad is sourced from raid_force, which concentrate/mil_switch
# DRAIN to 0 as the stack closes. This lever fixes that + generalizes to ANY base: when a sub-wave stack is
# advancing within BRW_REACH(3) hops of a friendly BASE, source the defense squad from NEARBY WORKERS that can
# ARRIVE IN TIME (hops<=ETA), grow it nearest-first to the MINIMAL size the referee-exact sim (squad + base
# turret) needs to hold AND wipe the stack, and send ONLY that many (not everyone). The HQ guard stays home;
# WAVE_STACK_MIN caps it to sub-waves (a real rush is turtle's) and siege_recall/on_hq veto an all-in. Uses
# workers (income earners) so it costs a little income, sized to the minimum -> the base income it saves is
# worth more. BASE_WORKER_RELIEF=0 => byte-identical. Validate mirror (the #40 tempo trap) before shipping ON.
BASE_WORKER_RELIEF = 0    # default OFF; flip to 1 after rush-12/12 + mirror + turtle validation.
BRW_MIN = 2               # smallest approaching pack worth a worker-relief (1 = a scout the turret handles).
BRW_REACH = 3             # enemy within this many hops of a friendly base (the user's "3칸 범위").
BRW_HORIZON = 12          # can-stop sim turn horizon.

MAX_CLAIMERS = 3          # claimers we may dispatch in a single turn (faster expansion)
EXPAND_CAP = 1            # R105 (user 2026-07-08: "확장 전부 한꺼번에 다하는거 하면 안될거 같아 -- 유리할 때 가용병력에서
#                          빠져도 괜찮으면 최대 2개만 보내자"). When FAVORABLE (base parity-or-ahead) and past the opening land
#                          race, throttle the per-turn claim dispatch to EXPAND_CAP_MAX so we expand GRADUALLY (2 at a time)
#                          instead of fanning the whole surplus out to every open stronghold at once (which thins the army).
#                          Behind on bases keeps the full MAX_CLAIMERS (the catch-up race / EXPAND_AHEAD territory). The
#                          claimers already come ONLY from nearest_surplus + the ACG reserve gate, so "가용병력에서 빠져도
#                          괜찮으면" is enforced -- the cap just makes it MORE conservative. Touches ONLY the expansion
#                          dispatch; attack (COMMIT_STRIKE/CS_FINISH) and defense (relief/recall/garrison) are untouched
#                          (user: "공격 판단이나 수비 판단에 영향가지 않게"). EXPAND_CAP=0 => MAX_CLAIMERS everywhere (baseline).
EXPAND_CAP_MAX = 2        # max claimers dispatched per turn while favorable ("최대 2개만")
EXPAND_CAP_TURN = 45      # turn floor: never throttle the OPENING land race (base-behind losses are all early); the
#                          "comfortable fan-out" the user means is a mid-game behaviour, so the cap only binds past this.
ASSAULT_CAP = 80          # cap extra warriors funded from the late-game gold hoard
RAID_FUND_HQLEVEL = 3     # economy floor (HQ level) before funding the land-taking raid army
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
SMALLWAVE = 0             # R107 (1(106)/1(107)/1(108)/1(116)/1(117); user: "상대가 5마리 병력을 주기적으로 보내는데
#                          이걸 초반에 눈치채고 대비"). The opponent sends waves of EXACTLY 5 -- which sits ONE below
#                          MOBILIZE_NEAR=6, so `is_wave` never latches threat_army and no matched garrison forms (and
#                          line ~3373 even DISSOLVES a 5-stack as "no wave"). Detect a COMPACT, APPROACHING sub-wave of
#                          SW_MIN..MOBILIZE_NEAR (4-5) and latch it into threat_army -- reusing the SAME matched-garrison
#                          (defense) + mil_switch (attack) machinery a real wave uses ("방어와 공격 코드에 잘 녹아들게").
#                          Two arms: RECURRING (>=SW_RECUR hits within SW_WINDOW = the "주기적으로" signal) OR EARLY
#                          military commit (turn<=SW_EARLY_TURN + enemy holds <=SW_EARLY_MAXB bases = "초반에 눈치채고").
#                          Turtle-safe: requires a COMPACT stack that is APPROACHING (stack_dist<=gate), never a
#                          scattered economy. The latch HOLDS for SW_WINDOW turns (spans the ~20-turn wave period so the
#                          garrison persists between waves) and decays once the pattern stops. SMALLWAVE=0 => baseline.
SW_MIN = 4                # compact sub-wave floor (below this = TRIVIAL_SIEGE/DRIP_GUARD territory: HQ guard holds it)
SW_RECUR = 2              # this many compact 4-5 approaches within SW_WINDOW = a recurring wave pattern ("주기적")
SW_WINDOW = 40            # recurrence window AND post-latch garrison hold (> the observed ~20-turn wave period)
SW_EARLY_TURN = 55        # ARM B: an early compact commit is a rush tell even on the FIRST wave
SW_EARLY_MAXB = 2         # ARM B: only when the enemy holds <= this many bases (committed to MILITARY, not economy)
SW_HOLD = 6               # modest fixed HQ garrison floor while a small-wave is active (holds a 5-fist: 5 defenders +
#                          turret out-kill; NOT the full threat_army match that ballooned the garrison + starved climb)
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
ANTIBOOM = 1              # S2 (real losses 1(1)/1(2), K17): a SPREAD out-producer (army distributed across many
#                           bases -> never a concentrated stack) slips past mil_switch AND MATCH_TOTAL is off, so
#                           our army FROZE at 14 while the enemy boomed to 44 and razed us (we razed it 0 all game).
#                           When the mirror-SAFE _outproduced detector fires, ALSO ramp our army toward the enemy
#                           total so we can defend our economy + feed the harass. Self-limiting (reaching <1.6x the
#                           enemy turns _outproduced off -> no escalation spiral); K>WIDE_FORCE_ANCHOR only (compact
#                           7/8 + g4/K15 byte-identical). Rollback: ANTIBOOM=0.
CONCENTRATE_DIST = 3      # pull EVERYONE home (abandon base income) only once the wave's stack
#                           is this close OR has advanced strictly past the midline toward us
CONC_WAVE_GATE = 1        # R86b (1(93) K15, we=LEFT, RIGHT_WIN HQ_DESTROYED, ★mm=0 현행재현; user: "101턴에
#                           노동자가 갑자기 탈줄하는 버그, 이후 복구 불가"): `committed`'s PAST-MIDLINE arm (a stack
#                           advanced onto our half + advancing + within fist-return ETA) fired full CONCENTRATE for a
#                           mere 4-stack at d5 (t100), dumping 7 of our 10 workers onto node 0 (workers 10->3) -> income
#                           crashed -> never recovered -> HQ razed t181. But the code's OWN comment says "do NOT
#                           concentrate for scouts (threat 2-6)" -- a code-vs-design gap. Gate the APPROACHING arm on
#                           WAVE-scale (max(stack, threat_army) >= CONC_WAVE_MIN): a sub-wave that has NOT yet closed to
#                           CONCENTRATE_DIST no longer abandons the whole economy -- `threat` still pulls the surplus
#                           home (2a) and _relief/base_eating defend the pressed base, so we HOLD income + fight with
#                           army (the user's "교전 비중 늘려라"). ★The ON-US arm (stack_dist<=CONCENTRATE_DIST) and
#                           on_hq/siege_recall are UNGATED -> a real waverush (6+ wave, or any stack ON us) still
#                           full-turtles: waverush crack-0 preserved. CONC_WAVE_GATE=0 => decision-identical.
CONC_WAVE_MIN = 6         # the approaching arm needs a wave-scale stack (= SUBWAVE_MIN); below this a not-yet-close
#                           stack is harass the standing garrison + turret + relief handle without an economy dump.
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
# --- MULTI-PRONG raid (the user's "분산해서 때려라"): when we hold a BIG army and are NOT behind, the
#     single concentrated fist wastes the many opportunities a turn offers. Spread it across up to
#     MAX_PRONGS enemy bases at once -- the enemy moves ONE hop/turn and can only defend one place, so a
#     prong that meets a relief force peels off and MERGES into another (the proven disengage-and-fold).
#     Gated to a big surplus + not-behind + >=2 enemy bases, so the proven single-fist razing (turtle/
#     mirror wins) and all defense are untouched. Only chooses MOVE targets for the committed raid_force.
MULTI_PRONG = 1
MULTI_PRONG_MIN = 10      # need at least this big a raid surplus to split into >2 prongs
MAX_PRONGS = 3            # cap simultaneous prongs (each must still be >= PRONG_MIN to crack anything)
OVERWHELM_F = 2          # OVERWHELMING-ARMY override for the spread (the user's "병사가 압도적으로 많아지면"): on the WIDEST maps, fire MULTI_PRONG even while transiently _behind_hq when our army >= this * the enemy's. 2x never trips the symmetric mirror (~1x) -> no mirror regression; in game 5 the income-push wrecks B's army so A is easily 2x+.
OVERWHELM_ENEMY_MIN = 3  # ...and the enemy must still field >= this many warriors (below it the single fist already cleans up; avoids splitting against a near-empty enemy).
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
# HEAL-AWARE CRACK (game-4 fix, the user's "다축 게이트" axis-1): a base the enemy is ACTIVELY HEALING
# (UPGRADE on a max base = heal-to-full, 500g) cannot be razed by a slow multi-turn chip -- the enemy
# undoes every chip. We OBSERVE heals directly from the referee (an enemy UPGRADE on an already-max base
# IS a heal; stamped in read_turn_result) and, for a base healed within HEAL_MEMORY turns, model the heal
# in the crack sim (the building regenerates toward full each turn it is not yet dead). Net: such a base
# reads crackable ONLY if the fist can ONE-SHOT it
# (overwhelm full hp in a single siege turn, before the heal lands). Otherwise _can_crack returns False ->
# the backdoor stops grinding the heal-wall and forward-stages / banks for the climb (game-4 trickle cut),
# WHILE un-healed forward bases (7/8's contested strongholds) are untouched -> midfield pressure preserved.
HEAL_MEMORY = 25          # a base healed within this many turns is treated as a heal-wall (covers the
#                           CRACK_LOCK(18)+SKIP_WATCH(12) oscillation window so a re-locked wall stays flagged)
HEAL_AWARE = 1            # master switch for the heal-aware gate (0 = exact legacy behaviour)
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
OVEREXTEND_HOLD = 1       # R72 (5(8) AI-5 loss, K19, current-build mm=0; user: "t116 상대 기지 부수고 그
#                           자리에 기지 짓는데 상대 가용이 훨씬 많은 상황이라 위험 -- 군사에 더 보중해야, 돈은
#                           상대 HQ 따라가려 모으는 것, 기지까지 더 지으면 과욕"): the razed-enemy-ground
#                           rebuild is "GOOD early" (NO_REBUILD_TURN) ONLY while we are NOT being out-availabled.
#                           5(8) t116: enemy available 15 > ours 12, we already held 12 bases to their 7, HQ
#                           behind (L2 vs L3) -- yet we razed base 57 and spent 300g rebuilding our 12th base
#                           there instead of the army the incoming 15-body available demanded. When enemy
#                           available >= ours + OXH_AVAIL AND we are base-even-or-ahead (expansion is not a
#                           catch-up need), the razed ground goes off-limits regardless of turn -> the freed
#                           gold funds MATCH_AVAIL's army floor + the HQ climb. OVEREXTEND_HOLD=0 => byte-id.
OXH_AVAIL = 2             # enemy available must exceed ours by at least this (a real deficit, not noise).
OXH_DOM_LEAD = 3          # R72b (5(10) t119-120: our available caught up to PARITY (15v15) so the +2 gate closed
#                           for two turns and the razed-57 rebuild slipped through -- exactly the user's "가용
#                           비슷" case). A second arm: when we are LAND-DOMINANT (bases >= enemy + this) the
#                           razed rebuild is overreach even at available PARITY -- we do not need the base and
#                           the trade (our L1 loss << their L2 loss) favors army. Only strong dominance arms it.
OXH_PARITY_SLACK = 1      # ... and only while we are NOT available-ahead by a real margin: suppress if
#                           enemy_avail + this >= ours (i.e., ours <= enemy_avail + 1). If we lead available by
#                           2+, expansion is affordable snowball -> not suppressed.
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
HARASS_WHEN_PASSIVE = 0   # DEACTIVATED (adversarial review, 2 CONFIRMED HIGH rush-safety holes): _passive_release
#                           keys every gate on the LARGEST (parked) stack (most_common(1)), so a peeled-off 6-9
#                           unit SPLIT-RUSH detachment at our HQ is invisible (threat=0 until dist<=THREAT_RANGE=6),
#                           the lever flings the WHOLE surplus forward leaving only guard_floor=3 home, and 9
#                           attackers crack an L3 HQ in 5 turns before the fist (5+ hops out, off-axis so the flee
#                           net never sees the home-aimed mass) can return -> HQ cracked = invariant (1) violated.
#                           ROOT = the same most_common(1) split-force blindness as SPLIT_RELIEF. The fundamental
#                           tension the review exposed: harass needs a real fist forward, rush-safety-when-BEHIND
#                           needs the whole army home -- you cannot have both, which is WHY the NOTE above rejected
#                           this class 12/12. A rush-safe cap would release only ~6 (near-inert). Kept flag-gated
#                           OFF (=byte-identical to validated R14/proto_pre_r15) rather than shipping a known
#                           HQ-crack hole. R15 (game 6, user's explicit request + prior-win evidence). The NOTE above rejects a
#                           MID-GAME income-raid vs a DEFENDING economist. This is the NARROW complement it did
#                           NOT cover, and it changes ONLY the harass_budget SIZE (not the target logic): when the
#                           enemy mass is PARKED + PASSIVE (park_streak high, stack far past `gate`, NOT advancing)
#                           AND we are BEHIND on income with HQ-parity (_smallmap_econ: K11-14, not_behind_hq,
#                           workcap<=enemy -> a game we CANNOT win by climbing and would otherwise coast to a
#                           draw), release the ALREADY-BUILT idle fist (sunk-cost non-workers) forward through the
#                           UNCHANGED crack-aware backdoor -- exactly VELOCITY_MUSTER's full-surplus release, just
#                           with its threat==0 veto lifted for the parked-passive case (the passive forward-base
#                           defenders that make threat>0 do NOT reinforce). SAFETY = the user's model: the existing
#                           EVASION flee (FLEE_RADIUS) retreats the whole fist to the nearest friendly base the
#                           instant the superior enemy mass MOVES toward it, so it is never peeled (the #40
#                           failure). SELF-DISABLES via _smallmap_econ the moment we fall behind on HQ
#                           (not_behind_hq) -> the climb/tiebreak is never forfeited. Move-gold/climb-stall (the
#                           NOTE's failure modes) are mooted: _smallmap_econ means the climb race is already lost,
#                           and the fist is idle sunk-cost. flag=0 = byte-identical. VALIDATION-GATED: applied only
#                           if the matrix (esp. vs economist bots turtle/climber/grinder) shows no regression.
HARASS_PARK_MIN = 8       # turns the enemy mass must sit PARKED on its buildings (BOT.park_streak) before we
#                           trust it passive enough to release the fist -- a robust multi-turn read, not a
#                           one-turn dip (the user's "가용인원이 안 움직였다").


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
    claim_stand: dict = field(default_factory=dict)        # STRAND_RECALL (R81): region -> first turn a claimer parked there unbuilt
    threat_army: int = 0                                  # sticky running-max enemy WAVE we must match
    threat_total: int = 0                                 # sticky running-max enemy TOTAL army we must match
    raid_tgt: int = -1                                    # crack-backdoor: the ONE enemy building we are committed to (-1 = none / watching)
    raid_lock: int = 0                                    # crack-backdoor: turns left on the current commit/watch spell (commitment = anti-oscillation)
    raid_skip: dict = field(default_factory=dict)         # crack-backdoor: region -> watch-expiry turn (stalled-siege blacklist)
    no_target_streak: int = 0                             # consecutive backdoor turns with NOTHING crackable (razing futile -> climb-priority recall)
    seen_enemy: set = field(default_factory=set)          # every region that EVER held an enemy building -> we raze & LEAVE EMPTY, never rebuild our own base on razed enemy land
    offense_engaged: bool = False                         # sticky: have we EVER stood a warrior on an enemy building (=dealt siege / razed)? Monotonic. False all game = purely passive (the 1(3)/1(4) loss signature); True by ~t75 in the g4/g5 WINS (razed 119/132). Gates ECON_INVEST_WIDE so g4/g5 self-exclude.
    turn: int = 0                                         # current turn (so _can_crack can read it without a signature change)
    heal_turn: dict = field(default_factory=dict)         # HEAL-AWARE: region -> last turn the enemy HEALED this base (UPGRADE on a max base). Healed within HEAL_MEMORY => a heal-wall.
    deny_mode: bool = False                               # WIDE-MAP DENIAL active: relax _can_crack so the army keeps razing the enemy economy (deny its L5 climb)
    prev_stack_dist: int = 1 << 30                        # VELOCITY: last turn's largest-enemy-stack distance to our HQ (so we know if it is ADVANCING vs retreating/parked)
    prev_defneed: int = 0                                 # POST_WAVE_HOLD: last turn's final defenders_needed (collapse detector)
    nn_seal: int = -1                                     # NARROW_NEAR (R65): -1 undecided / 0 race / 1 seal -- t1 geometry snapshot, latched for the game (a mid-opening recount would UNSEAL once the near bases get claimed and march the racer out after all)
    ee_bases: set = field(default_factory=set)            # EXPAND_ESCORT (R66): last-seen own-base regions (new region -> a claim landed -> escort window opens)
    ee_claim_turn: int = -(1 << 30)                       # EXPAND_ESCORT (R66): turn of our most recent base BUILD (the escort window anchor)
    cs_base: int = -1                                     # COMMIT_STRIKE (R71b): the base target we are committed to, latched so a straggler-driven min-max-hop flip cannot abandon a near-cracked siege mid-flight (5(11) t121: 65 hp5 dropped for 84)
    fb_tgt: int = -1                                       # RALLY_FALLBACK (R74): the defensive-line base we regrouped onto, latched so the rally point does not flap 52->47->39 each turn as the stack advances (bodies must commit to ONE stand, not chase a receding target)
    press_log: dict = field(default_factory=dict)         # PRESS_HOLD (R68): warrior id -> last turn it received a RAID march order (the press exemption is for actively-marching raiders only; idle deep bodies expire back into the recycle pool after PRESS_TTL)
    wave_cleared_turn: int = -(1 << 30)                   # POST_WAVE_HOLD: turn the last defensive episode released its hold (opens the consolidation window)
    adv_streak: int = 0                                   # V2: consecutive turns the largest enemy stack CLOSED on our HQ (a beeline never flickers; a roamer does)
    raze_count: dict = field(default_factory=dict)        # V2 TGT_VALUE: region -> times an enemy base there was razed (rebuild-decoy discount)
    prev_enemy_bases: set = field(default_factory=set)    # V2 TGT_VALUE: last turn's live enemy-base regions (raze detection)
    endgame: bool = False                                 # ENDGAME_FINISH gate state this turn (lets _pick_target apply the level-weighted ordering safely)
    chip_mode: bool = False                               # PULSE chip-and-run: current raid_tgt is a CHIP commit (not sim-crackable; disengage on the HP threshold)
    chip_hp0: int = 0                                     # fist hp-sum at chip commit (the run threshold baseline)
    my_base_lost: int = 0                                 # V2R6 OUTMASSED_DROP: cumulative count of OUR bases razed by the enemy (bookkeeping)
    prev_my_base_regs: set = field(default_factory=set)   # V2R6: last turn's own-base regions (loss detection)
    my_razed: dict = field(default_factory=dict)          # V2R7 NOREBUILD_HOT: region -> times OUR base there was razed (bookkeeping)
    park_streak: int = 0                                  # V2R8 MASS_DEPART: turns the largest enemy stack has sat on an enemy building (latent army park)
    zero_ops_streak: int = 0                              # V2R8 ZERO_OPS_CLIMB: consecutive turns the enemy fielded ZERO operators (all bodies on its buildings)
    en_total_hist: list = field(default_factory=list)     # V2R9 VIS_RAMP_MATCH: last VIS_RAMP_WIN enemy total-army counts (visible production growth)
    en_node_cnt: dict = field(default_factory=dict)        # R55 CK_PARK: LAST turn's per-node enemy head-counts (parked-stack detector for CONC_KEEP_ECON)
    eg_hold: bool = False                                 # V2R9 EG_UPG_REACH: chip-hold latched (one decision per endgame; the hold's own recall must not un-justify it)


BOT = Bot()


def _bfs_hops(M: GameMap, src: int) -> list[int]:
    """Plain symmetric BFS hop counts over the adjacency (V2R7 CLAIM_SAFE_ORDER ordering key)."""
    dist = [-1] * M.N
    dist[src] = 0
    q = [src]
    for u in q:
        for v in M.adj[u]:
            if dist[v] < 0:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def _init_bot(M: GameMap, nav: Nav) -> None:
    # Strongholds to claim: NOT just our strict half — also the CENTER and the
    # contested band (enemy closer by at most CONTEST_REACH). Conceding the middle
    # is how you fall behind in territory: the enemy grabs every neutral stronghold
    # and out-bases you. Order by distance from our HQ so we race the nearest first.
    # V2R7 CLAIM_SAFE_ORDER (1(4), see flag): among equal own-distance, claim the sites FARTHER from
    # the enemy first ("가깝고 상대한테 먼 쪽부터") -- the race-even center salient is claimed LAST, not
    # 3rd. Membership (contested band) is unchanged; only the order key gains the -do component.
    _sdm = _bfs_hops(M, M.my_hq) if bool(CLAIM_SAFE_ORDER) else None
    _sdo = _bfs_hops(M, M.opp_hq) if bool(CLAIM_SAFE_ORDER) else None
    scored = []
    for s in M.strongholds:
        dm = nav.hops(s, M.my_hq)
        do = nav.hops(s, M.opp_hq)
        if dm <= do + CONTEST_REACH:      # ours + center + contested band
            scored.append(((_sdm[s], -_sdo[s], s) if bool(CLAIM_SAFE_ORDER) else (dm, s), s))
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
    BOT.turn = turn   # so _can_crack can read the current turn (heal-wall recency) without a signature change
    my_warriors = [w for w in S.warriors if w.id.side is me]
    enemy_warriors = [w for w in S.warriors if w.id.side is not me]
    # PREDICT_STAGE heading history (R42, see flag block) -- STATE ONLY, updated every turn: last <=3
    # positions per enemy warrior, RESET the moment it holds still (order completed/changed -> the old
    # heading is stale). Two consecutive hops in the tuple = an inferable destination downstream.
    _eh_prev = getattr(BOT, 'en_hist', {})
    _eh_new = {}
    for _ew in enemy_warriors:
        _ek = str(_ew.id)
        _ep = _eh_prev.get(_ek)
        if _ep is None or _ep[-1] == _ew.region:
            _eh_new[_ek] = (_ew.region,)
        else:
            _eh_new[_ek] = (_ep + (_ew.region,))[-3:]
    BOT.en_hist = _eh_new
    # RAID_PHANTOM sighting log (R42, see flag block) -- STATE ONLY: new enemy ids per turn = observed
    # enemy production (the MG detector keeps its own copy behind its flag; this one is flag-independent).
    if not hasattr(BOT, 'ph_seen'):
        BOT.ph_seen, BOT.ph_tlog = set(), []
    _ph_new = [w.id for w in enemy_warriors if w.id not in BOT.ph_seen]
    BOT.ph_seen.update(_ph_new)
    BOT.ph_tlog.append((turn, 0 if turn <= 1 else len(_ph_new)))
    # NB heal-wall detection lives in read_turn_result (an enemy UPGRADE on a MAX base = a heal) -> BOT.heal_turn.
    my_buildings = [b for b in S.buildings if b.side is me]
    my_bases = [b for b in my_buildings if b.type is BType.BASE]
    hq = S.find_building(M.my_hq)
    my_building_regions = {b.region for b in my_buildings}
    # remember every stronghold that has EVER held an enemy building, so once the backdoor razes it
    # we leave the land EMPTY (never rebuild our own base on razed enemy land) and bank the gold.
    BOT.seen_enemy.update(b.region for b in S.buildings if b.side is not me)
    # V2 TGT_VALUE bookkeeping: enemy-base regions that disappeared since last turn were razed -- count
    # them so the target key can discount cheap-rebuild DECOY sites (pure bookkeeping, no decisions).
    _cur_eb = {b.region for b in S.buildings if b.side is not me and b.type is BType.BASE}
    for _rz in (BOT.prev_enemy_bases - _cur_eb):
        BOT.raze_count[_rz] = BOT.raze_count.get(_rz, 0) + 1
    BOT.prev_enemy_bases = _cur_eb
    # V2R6 OUTMASSED_DROP bookkeeping: OUR bases that disappeared were razed by the enemy (bases cannot
    # be unbuilt). Pure bookkeeping -- only the OUTMASSED_DROP gate reads it.
    _cur_mb = {b.region for b in my_bases}
    _lost_mb = BOT.prev_my_base_regs - _cur_mb
    BOT.my_base_lost += len(_lost_mb)
    for _rz2 in _lost_mb:                          # V2R7 NOREBUILD_HOT: remember where (and how often) we were razed
        BOT.my_razed[_rz2] = BOT.my_razed.get(_rz2, 0) + 1
    BOT.prev_my_base_regs = _cur_mb
    # OFFENSE-ENGAGED (sticky, monotonic): a warrior standing ON an enemy building region IS dealing siege
    # to it (the referee auto-sieges). Once true we have razed/pressured the enemy at least once. This is the
    # razing-activity discriminator: g4/g5 WINS flip it True ~t75 (razed 119/132); the 1(3)/1(4) LOSSES never
    # do (razed 0 all game). It gates ECON_INVEST_WIDE below so the g4/g5 wins structurally self-exclude.
    if not BOT.offense_engaged:
        _enemy_bldg_regs = {b.region for b in S.buildings if b.side is not me}
        if any(w.region in _enemy_bldg_regs for w in my_warriors):
            BOT.offense_engaged = True
    # Razed enemy land is OFF-LIMITS for our own bases ONLY from NO_REBUILD_TURN onward (leave it empty,
    # bank the gold). BEFORE that turn this set is empty, so we freely capture & rebuild razed enemy
    # strongholds and let them compound. One gate, used everywhere a build/claim is decided -> no tangle.
    _skip_build = BOT.seen_enemy if turn >= NO_REBUILD_TURN else frozenset()
    # V2R7 NOREBUILD_HOT (1.txt grinder, see flag): OUR razed stronghold with an enemy body still within
    # NOREBUILD_HOT_R hops = the grinder is on station; re-claiming feeds it 300g + a claimer each cycle
    # (6 re-claims = ~1800g = the starved L3 step). Razed TWICE = a rotating grinder's proven kill-box
    # (the party steps 3 hops away, our re-claim lands, it walks back) -- skip it for good; a single raze
    # only skips while the neighborhood is hot.
    if bool(NOREBUILD_HOT) and BOT.my_razed:
        _hot = {r for r, _n in BOT.my_razed.items()
                if r not in my_building_regions
                and (_n >= 2
                     or any(nav.hops(w.region, r) <= NOREBUILD_HOT_R for w in enemy_warriors))}
        if _hot:
            _skip_build = frozenset(_skip_build) | _hot

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
            BOT.big_wave_seen = True                                 # R107: a real 6+ wave -> exclude SMALLWAVE
        # R107 SMALLWAVE (see flag): the periodic EXACTLY-5 wave is 1 under MOBILIZE_NEAR=6 -> never latches above,
        # so no garrison forms. Catch a COMPACT, APPROACHING 4-5 sub-wave when RECURRING (주기적) OR an EARLY military
        # commit (초반 눈치채기). Gate `not big_wave_seen`: a real WAVERUSH sends 6+ waves that own threat_army above --
        # exclude it so SMALLWAVE fires ONLY vs an opponent that uses ONLY <=5 waves (the human 5-rush). RESPONSE is a
        # MODEST fixed HQ garrison floor (SW_HOLD, holds a 5-fist) -- NOT the full threat_army match, which ballooned
        # the garrison + starved the climb (the over-defense that lost waverush/my-bot). Held SW_WINDOW turns.
        if (bool(SMALLWAVE) and not is_wave and turn >= MOBILIZE_ARM_TURN
                and not getattr(BOT, 'big_wave_seen', False)
                and SW_MIN <= enemy_stack_sz < MOBILIZE_NEAR and stack_dist <= gate):
            if not hasattr(BOT, 'sw_hits'):
                BOT.sw_hits = []
            if not BOT.sw_hits or BOT.sw_hits[-1] != turn:
                BOT.sw_hits.append(turn)
            _sw_recur = sum(1 for _t in BOT.sw_hits if _t > turn - SW_WINDOW) >= SW_RECUR
            _sw_ebases = sum(1 for _b in S.buildings if _b.side is not me and _b.type is BType.BASE)
            _sw_early = (turn <= SW_EARLY_TURN and _sw_ebases <= SW_EARLY_MAXB)
            if _sw_recur or _sw_early:
                BOT.sw_latch_turn = turn
        if (bool(SMALLWAVE) and not getattr(BOT, 'big_wave_seen', False)
                and turn - getattr(BOT, 'sw_latch_turn', -(1 << 30)) <= SW_WINDOW):
            defenders_needed = min(len(my_warriors), max(defenders_needed, SW_HOLD))
    # TRIVIAL_SIEGE (see flag block; 3(1)/3(2) drip war): a 1-2 body dribble that the STANDING HQ guard
    # + turret kill where they stand (hold rule; equality is safe -- siege dmg = attackers - defenders
    # and the guard out-kills first) must not flip ANY global posture. Phase 1 gated only concentrate/
    # siege_recall; the 3(2) resubmission (fidelity-0) showed the roster STILL shuttled every drip --
    # `on_hq == 0` guards ~70 posture/dispatch/offense gates (harass, ready-floor, relief family,
    # home_safe, finishers, claim/expand...) and each inverted per drip, so the whole roster ping-ponged
    # 0<->bases for 130 turns and the guard gaps chipped the tiebreak hp AGAIN (7 v 10). Neutralize at
    # the SOURCE: on_hq itself reads 0 while the dribble is trivial. The PROPORTIONAL local response is
    # intact by construction: defenders_needed's `on_hq + 2` staffing above reads the REAL count, and
    # the referee-facing upgrade_legal/enemy_at checks are position-based, untouched.
    _triv_n = max(on_hq, enemy_stack_sz if (stack_reg >= 0 and stack_dist <= CONCENTRATE_DIST) else 0)
    # TRIV_HOLD (R61, 1(69) t167; user: "인원도 4명뿐이라 충분히 HQ 가용병력으로 잡을 수 있었다"):
    # the fixed TRIV_MAX=2 cap let a FOUR-body poke flip the full turtle (committed close-in arm) --
    # every worker dumped to node 0 at t167, then the threat-fill re-scattered them 43/70/72 in a
    # shuttle for the rest of a WON game. The second condition (n <= turret + standing HQ bodies) IS
    # the hold rule -- the fort grinds them where they stand -- so the cap rises to that guard count:
    # any squad the HQ provably holds alone is trivial at ANY size. A rush stack (10+) never clears
    # the guard bar -> the full-turtle survival doctrine is untouched.
    _triv_guard = (_home_turret(S, M, me, M.my_hq)
                   + sum(1 for w in my_warriors
                         if w.region == M.my_hq and w.state is WState.STATIONARY))
    _triv_hq = (bool(TRIVIAL_SIEGE) and 0 < _triv_n <= (max(TRIV_MAX, _triv_guard)
                                                        if bool(TRIV_HOLD) else TRIV_MAX)
                and _triv_n <= _triv_guard)
    if _triv_hq:
        if on_hq > 0:                              # raw pre-rebind count = a live trivial arrival
            if not hasattr(BOT, 'drip_hits'):
                BOT.drip_hits = []
            if not BOT.drip_hits or BOT.drip_hits[-1] != turn:
                BOT.drip_hits.append(turn)
        on_hq = 0
    # DRIP_GUARD (3(3); user: "상대 오는 걸 아니까 HQ 배치 비중을 조금 올려라"): a RECURRING dribble
    # (>= DRIP_MIN trivial arrivals inside DRIP_WINDOW turns) keeps a STANDING TRIV_MAX+1 guard at the
    # HQ. The per-arrival 1->3 staffing pull worked but rotated bodies every cycle, and the drips landed
    # their siege ticks exactly in the 1-turn rotation gaps (3(3) t162-175 chip run). A standing guard
    # = zero gap, zero churn; it decays back to guard_floor by itself once the dribble stops (window).
    if (bool(DRIP_GUARD)
            and sum(1 for _t in getattr(BOT, 'drip_hits', []) if _t > turn - DRIP_WINDOW) >= DRIP_MIN):
        defenders_needed = min(len(my_warriors), max(defenders_needed, TRIV_MAX + 1))
    if BOT.threat_army > 0 and enemy_stack_sz < MOBILIZE_NEAR and on_hq == 0 and threat == 0:
        BOT.threat_army = 0                       # wave dissolved & home clear -> baseline
    # VELOCITY (shared signal): did the largest enemy stack ADVANCE on our HQ since last turn (hop-distance
    # strictly decreased)? Computed BEFORE the prev_stack_dist bookkeeping below so every consumer -- the
    # `committed` gate (VELOCITY_HOLD), the muster fist-sizing in 2c (VELOCITY_MUSTER), and the 1d press-gate
    # (UNDERMASS_PRESS) -- reads the same pre-update signal. A newly-seen stack (prev = inf) counts as
    # advancing so first sight still reacts.
    _stack_advancing = (stack_reg >= 0 and stack_dist < BOT.prev_stack_dist)
    # V2 ADV-STREAK bookkeeping: how many consecutive turns has the largest stack CLOSED on our HQ?
    # (RUSH_BRAKE keys on a SUSTAINED approach -- a patrol/roam flickers between advance and retreat,
    # a committed rush pack decreases its distance every single turn.)
    BOT.adv_streak = (BOT.adv_streak + 1) if _stack_advancing else 0
    # V2R8 worker-vs-operator bookkeeping (see MASS_DEPART / ZERO_OPS_CLIMB flags). park_streak: turns the
    # largest enemy stack has sat on an enemy BUILDING region (bodies stored in work slots = latent army);
    # the streak FREEZES (not resets) while the stack advances off the park -- that launch window is exactly
    # when MASS_DEPART reads it. zero_ops_streak: turns the enemy fielded no operator at all.
    _enemy_bldg_regs8 = {b.region for b in S.buildings if b.side is not me}
    if stack_reg >= 0 and stack_reg in _enemy_bldg_regs8:
        BOT.park_streak += 1
    elif stack_reg < 0 or not _stack_advancing:
        BOT.park_streak = 0
    # ZERO_OPS_SLACK: an enemy body in TRANSIT between its own buildings reads as an "operator" for 1-3
    # turns (we cannot see enemy move targets), and 4.txt's turtle relocated 1-3 bodies every ~10 turns --
    # a strict all-on-buildings test never accumulated 15 turns. <= 2 off-building bodies still counts as
    # zero-ops; a REAL operator squad (3+, e.g. the R7 grinder's eater parties) resets the streak.
    _en_ops8 = sum(1 for w in enemy_warriors if w.region not in _enemy_bldg_regs8)
    if enemy_warriors and _en_ops8 <= ZERO_OPS_SLACK:
        BOT.zero_ops_streak += 1
    else:
        BOT.zero_ops_streak = 0
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
    # --- V2 RUSH-BRAKE (g2 t21 함락, see flag): a pack >= RUSH_MIN has been CLOSING on our HQ for
    # ADV_STREAK straight turns in the opening, it is at/inside the midline band, and the bodies we can
    # physically have home by its arrival cannot match it -> FREEZE every economy spend this turn (1b
    # build / 1d-1g base upgrades / 2b claim dispatch) and latch threat_army so TRAIN_RESCUE pours the
    # bank into defenders instead. g2 receipts: the 6-pack advanced every turn from t8 (streak >= 2 by
    # t10) while we held 3 bodies -- the t11 base-68 build (300g) was the exact spend this brake blocks;
    # skipping it funds 1 train/turn from t11 -> ~7 defenders on the HQ at its t15 arrival -> siege/turn
    # = 6 - defenderHP = 0 -> the HQ holds. A stack massing at ITS OWN HQ never trips this (distance
    # bound fails by the map diameter); a roaming patrol never sustains the streak.
    _rush_brake = False
    if (bool(RUSH_BRAKE) and turn <= RUSH_BRAKE_TURN and hq is not None and stack_reg >= 0
            and enemy_stack_sz >= RUSH_MIN and BOT.adv_streak >= ADV_STREAK
            and stack_dist <= nav.hops(stack_reg, M.opp_hq) + 2):
        _eta = max(1, stack_dist)
        _reachable = sum(1 for w in my_warriors if nav.hops(w.region, M.my_hq) <= _eta)
        if _reachable < enemy_stack_sz + 1:
            _rush_brake = True
            BOT.threat_army = max(BOT.threat_army, enemy_stack_sz)
    # V2 RUSH-BRAKE arm 2 (g2 F1): the pack-approach arm above fires at t11 -- one turn before the
    # fatal build in g2 (enough, verified) but with zero margin. The ALL-IN SIGNATURE is complete at
    # t8: the enemy holds ZERO bases past the opening (every normal player claims by ~t3), out-numbers
    # us by 3+, and fields 3+ idle bodies beyond its work capacity = the bank went into an army, not an
    # economy. Freeze our economy spends and latch the threat then -- four extra turns of training.
    if (bool(RUSH_BRAKE) and not _rush_brake and 8 <= turn <= RUSH_BRAKE_TURN
            and hq is not None and enemy_warriors):
        _ebases2 = sum(1 for _b in S.buildings if _b.side is not me and _b.type is BType.BASE)
        _ewcap2 = sum((HQ_LEVELS if _b.type is BType.HQ else BASE_LEVELS)[_b.level].work_cap
                      for _b in S.buildings if _b.side is not me)
        if (_ebases2 == 0 and len(enemy_warriors) >= len(my_warriors) + 3
                and (len(enemy_warriors) - _ewcap2) >= 3):
            _rush_brake = True
            BOT.threat_army = max(BOT.threat_army,
                                  enemy_stack_sz if stack_reg >= 0 else len(enemy_warriors))
    # V2R7 CLAIM_MIL_GATE (1(1) scout-park-strike, see flag): arm 3 -- a PARKED forward pack. Arm 1
    # needs an advance streak (a parked pack has none), arm 2 needs a zero-base all-in (they held 2),
    # RUSH_DEFENSE needs a strictly-crossed midline (they parked exactly ON it, d3==d3). A pack of
    # RUSH_MIN+ standing at/inside the midline within the approach gate, while the enemy holds an
    # ABSOLUTE unit lead of CLAIM_MIL_DEFICIT+, is a confirmed strike setup ("간보다가 치는" 정찰-주둔-강습):
    # freeze the economy spends and latch the threat so the bank trains defenders first. Opening only.
    # ECONOMY-BACKED only (enemy holds >= 1 base): the scout-park-striker expands WHILE parking (1(1):
    # 2 bases). A ZERO-base pure rusher stays arm 1/2's job -- ablation receipt: arm 3 firing on
    # bot_rush froze BOTH economies into a mutual-deterrence A1/B1 stalemate draw (seed 2002; win
    # restored by this base gate), while the crack-0 home defense never needed the extra brake.
    if (bool(CLAIM_MIL_GATE) and not _rush_brake and turn <= RUSH_BRAKE_TURN
            and hq is not None and stack_reg >= 0
            and enemy_stack_sz >= RUSH_MIN
            and stack_dist <= nav.hops(stack_reg, M.opp_hq)
            and stack_dist <= gate
            and len(enemy_warriors) >= len(my_warriors) + CLAIM_MIL_DEFICIT
            and any(_b.side is not me and _b.type is BType.BASE for _b in S.buildings)):
        _rush_brake = True
        BOT.threat_army = max(BOT.threat_army, enemy_stack_sz)
    # --- V2 EXPAND-RHYTHM schedule (see flag): 3rd base by ~t32, +1 per EXPAND_EVERY turns, capped by
    # our claimable band. While BEHIND schedule (and not rush-braked), expansion gets first claim on
    # gold: 2b's dispatch brake drops to cost+GOLD_FLOOR and claimer bodies are funded reserve-free
    # like workers (they pay back +13/turn). replays3 정량화: 3호 기지 우리 t60~159 vs 상대 t21~23.
    _expand_lag = False
    _sched_deficit = 0
    if bool(EXPAND_RHYTHM) and turn <= EXPAND_UNTIL and not _rush_brake and on_hq == 0:
        _sched_bases = min(len(BOT.claim_order), 2 + max(0, (turn - 10) // EXPAND_EVERY))
        _inflight = sum(1 for w in my_warriors
                        if ((w.state is WState.MOVING and w.target in BOT.claim_set
                             and S.find_building(w.target) is None)
                            or (w.state is WState.STATIONARY and w.region in BOT.claim_set
                                and S.find_building(w.region) is None)))
        _sched_deficit = max(0, _sched_bases - (len(my_bases) + _inflight))
        _expand_lag = _sched_deficit > 0
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
    _my_workcap0 = sum((HQ_LEVELS if b.type is BType.HQ else BASE_LEVELS)[b.level].work_cap
                       for b in S.buildings if b.side is M.my_side)
    # OVEREXTEND_HOLD (R72, see flag block): out-availabled + base-even-or-ahead -> the razed-enemy-ground
    # rebuild is overreach; add seen_enemy to the build blacklist so the freed gold arms the army/climb.
    _oxh_enav = len(enemy_warriors) - _enemy_workcap
    _oxh_myav = len(my_warriors) - _my_workcap0
    _oxh_myb = sum(1 for _b in S.buildings if _b.side is me and _b.type is BType.BASE)
    _oxh_enb = sum(1 for _b in S.buildings if _b.side is not me and _b.type is BType.BASE)
    # MIDEXPAND_ARM (R76, 1(82) AI loss, K17; user: "55턴 기지를 잃었는데 이후 과확장 -- 기지수가 같다면 군사력
    # 으로 이득을 반드시 봐야, 확장하려면 기지 하나 세울 때 인원 하나를 찍어야"): after the opening (past
    # AVAIL_CLAIM_GATE's t<=55 window) the 2b claim loop keeps scattering claimers to NEW neutral strongholds
    # even at an available-deficit. 1(82) measured: from t50 parity (myav7 vs enav6) four claims (25/24/46/42)
    # at t54-67 craters our AVAILABLE army 7->3->1->0 while the enemy out-masses to 15 total, and 440-631 gold
    # BANKS (for the climb) instead of training. Existing levers miss it: EXPAND_ESCORT's window+squad-band is
    # early/small-enemy, OVEREXTEND_HOLD only blacklists razed-ENEMY ground (not fresh neutral claims), and
    # AVAIL_CLAIM_GATE stops at t55. When base-even-or-ahead (no catch-up need) AND out-availabled AND the enemy
    # fields a real army, in this mid window: (a) suppress NEW claims and (b) redirect the freed gold to the army
    # (reuse CONSOLIDATE_ARMY's floor + lean-train bar). MIDEXPAND_ARM=0 => decision-identical.
    # R84 MXA_PRESSED arm: base-COUNT-independent. The base arm's avail-deficit signal is BLIND here -- the
    # enemy invests its army into MORE bases (higher workcap => lower AVAIL) so enav reads low (5-8) even as its
    # TOTAL out-masses us; meanwhile we hold fewer bases so OUR avail reads healthy. The real "losing the brawl"
    # signal is a clear TOTAL-army deficit under a sustained push (1(91) t73-74: base 4<5, total 12 v 14, threat 8
    # -> we claimed a d5 salient (node 40) that razed for free). Same +MXA_DEFICIT margin as the base arm keeps it
    # mirror-inert (a symmetric total never gaps +2), and threat>=MXA_THREAT_MIN requires a real concentrated push.
    _mxa_press = (bool(MXA_PRESSED) and threat >= MXA_THREAT_MIN
                  and len(enemy_warriors) >= len(my_warriors) + MXA_DEFICIT)
    _mxa = (bool(MIDEXPAND_ARM) and ACG_TURN_MAX < turn <= MXA_TMAX
            and len(enemy_warriors) >= MXA_EN_MIN                     # enemy actually fields an army (not a lone econ)
            and ((_oxh_myb >= _oxh_enb and _oxh_enav >= _oxh_myav + MXA_DEFICIT)  # R76 arm: base-even + out-availabled
                 or _mxa_press))                                     # R84 arm: base-behind but out-massed under push
    if (bool(OVEREXTEND_HOLD) and BOT.seen_enemy and turn < NO_REBUILD_TURN
            and _oxh_myb >= _oxh_enb
            and (_oxh_enav >= _oxh_myav + OXH_AVAIL                                  # clearly out-availabled
                 or (_oxh_myb >= _oxh_enb + OXH_DOM_LEAD                             # R72b: land-dominant AND
                     and _oxh_enav + OXH_PARITY_SLACK >= _oxh_myav))):              #        available not-ahead
        _skip_build = frozenset(_skip_build) | BOT.seen_enemy
    _outproduced = (bool(OUTPRODUCE) and turn >= MOBILIZE_ARM_TURN
                    and enemy_total >= len(my_warriors) + OUTPRODUCE_MARGIN
                    and enemy_total >= OUTPRODUCE_RATIO * max(len(my_warriors), 1)
                    and (enemy_total - _enemy_workcap) >= OUTPRODUCE_IDLE_MIN)
    # V2R7 OUTMASSED_SOFT (see flag): the human grinder's SUSTAINED ~1.5x standing army dodges the 1.6x
    # instantaneous ratio and the idle-count gate (big workcap reads it as "just an economy"), and its
    # parked home stack keeps _um_pressing False -- yet our bases are demonstrably being razed. Absolute
    # deficit + a lost base + workcap-behind = proven pressure; feeds ONLY GRIND_RESCUE / OUTMASSED_DROP.
    # V2R9 OM_MASS_OR_INCOME: a 2x-margin ABSOLUTE deficit is pressure regardless of the income sign (g5
    # t172: our razing flipped workcap to our favor and disarmed the ramp at army 38v66).
    _outmassed_soft = (bool(OUTMASSED_SOFT) and turn >= MOBILIZE_ARM_TURN
                       and enemy_total >= len(my_warriors) + OUTMASSED_SOFT_MARGIN
                       and BOT.my_base_lost >= 1
                       and (_my_workcap0 < _enemy_workcap
                            or (bool(OM_MASS_OR_INCOME)
                                and enemy_total >= len(my_warriors) + 2 * OUTMASSED_SOFT_MARGIN)))
    # V2R9 VIS_RAMP_MATCH (see flag): the enemy's TOTAL army count is public information -- a sustained
    # burst (>= VIS_RAMP_GROW over VIS_RAMP_WIN turns) with an absolute deficit is a confirmed ramp; do
    # not wait for a base to burn. Wide maps only; feeds the same bounded _outmassed_soft consumers.
    BOT.en_total_hist.append(enemy_total)
    if len(BOT.en_total_hist) > VIS_RAMP_WIN:
        BOT.en_total_hist.pop(0)
    # R55 CK_PARK state (unconditional, state-only): swap in this turn's per-node enemy head-counts and
    # keep LAST turn's in a local for the CONC_KEEP_ECON parked-stack test below. A rushing stack moves
    # every turn (no node holds >= CK_PARK_MIN two turns running); a parked forward outpost does.
    _ck_prev_nodes = BOT.en_node_cnt
    BOT.en_node_cnt = {}
    for _e in enemy_warriors:
        BOT.en_node_cnt[_e.region] = BOT.en_node_cnt.get(_e.region, 0) + 1
    if (bool(VIS_RAMP_MATCH) and not _outmassed_soft and M.K > WIDE_FORCE_ANCHOR
            and turn >= MOBILIZE_ARM_TURN
            and len(BOT.en_total_hist) >= VIS_RAMP_WIN
            and enemy_total - BOT.en_total_hist[0] >= VIS_RAMP_GROW
            and enemy_total >= len(my_warriors) + OUTMASSED_SOFT_MARGIN):
        _outmassed_soft = True
    if MATCH_TOTAL and turn >= MOBILIZE_ARM_TURN and enemy_total >= len(my_warriors) + MATCH_TOTAL_MARGIN:
        BOT.threat_total = max(BOT.threat_total, min(MATCH_TOTAL_CAP, math.ceil(MATCH_TOTAL_F * enemy_total)))
    elif BOT.threat_total > 0:
        BOT.threat_total = min(BOT.threat_total, max(enemy_total, len(my_warriors)))
    mil_switch = BOT.threat_army > 0 or BOT.threat_total > 0
    target_garrison = 0
    concentrate = False
    base_eating = False
    counter_now = False
    _hpfb = 1.0   # HP_FIGHT_BAR ratio -- computed below once _ehl0 is known (see flag block)
    # (TRIVIAL_SIEGE _triv_hq/_triv_n are computed at the SOURCE next to the stack detector above --
    # on_hq is already rebound to 0 there while the dribble is trivial; the guards below are kept as
    # defense-in-depth for the stack-proximity arm of _triv_n.)
    _ehqb0 = S.find_building(M.opp_hq); _ehl0 = _ehqb0.level if _ehqb0 is not None else 1
    # R51 HQ-timing trackers (state-only, unconditional like the PARITY_CLIMB tracker; decisions read
    # them only under their flags): the turn each side's HQ last changed level = the wallet-empty window.
    if _ehl0 != getattr(BOT, 'ehq_lvl', -1):
        BOT.ehq_lvl = _ehl0
        BOT.ehq_dev_turn = turn
    if hq is not None and hq.level != getattr(BOT, 'mhq_lvl', -1):
        BOT.mhq_lvl = hq.level
        BOT.mhq_dev_turn = turn
    # HP_FIGHT_BAR (R49, see flag block): FIELD-FIGHT verdicts weigh the enemy stack by the warrior-hp
    # ratio when their HQ outlevels ours (their bodies are tankier); 1.0 at level-parity = inert.
    if bool(HP_FIGHT_BAR) and hq is not None and _ehl0 > hq.level:
        _hpfb = HQ_LEVELS[_ehl0].warrior_hp / max(1, HQ_LEVELS[hq.level].warrior_hp)
    _terr_deficit = (sum(1 for b in S.buildings if b.side is not M.my_side and b.type is BType.BASE)
                     > len(my_bases) + LOSE_MARGIN)
    losing = (_terr_deficit and hq is not None and hq.level < _ehl0)  # economy/CDROP: only when strictly behind
    if BOT.threat_total > 0:                       # match the enemy's TOTAL army (workers + garrison)
        target_garrison = min(MATCH_TOTAL_CAP, BOT.threat_total)
    if BOT.threat_army > 0:
        mf = MOBILIZE_MATCH if (hq is not None and _is_max(hq)) else MOBILIZE_MATCH_SUBL5
        target_garrison = max(target_garrison, min(MOBILIZE_CAP, math.ceil(mf * BOT.threat_army)))
        # DEF-CAP (userbot pack #4): cap the matched garrison by DEFENSE MATH -- the smallest body count
        # that SURVIVES the worst-case wave storming our HQ (defender-side referee-exact siege sim, full-hp
        # attackers, + slack) -- instead of ~1.15x the enemy's TOTAL army. 1(3): we matched a boomer to 59
        # bodies whose 118g/turn upkeep ate the L3 bank forever while it out-climbed us on 10 bases. Once
        # the garrison is sufficient the train deficit closes, the bank fills, and the climb resumes ("웨이브
        # 격퇴 후 등정 복귀"). Binary search is valid because more defenders is monotonically safer. If even
        # the full match cannot hold (sim cracks at every size), the cap leaves target_garrison unchanged.
        if bool(DEF_CAP) and hq is not None and target_garrison > 0:
            _atk_hp = HQ_LEVELS[_ehl0].warrior_hp
            _def_hp = HQ_LEVELS[hq.level].warrior_hp
            _wave = [_atk_hp] * max(BOT.threat_army, enemy_stack_sz)
            _tur = HQ_LEVELS[hq.level].turret
            _lo, _hi = 0, target_garrison
            while _lo < _hi:
                _mid = (_lo + _hi) // 2
                if _sim_crack(_wave, hq.hp, _tur, [_def_hp] * _mid, DEF_CAP_HORIZON)[0]:
                    _lo = _mid + 1
                else:
                    _hi = _mid
            if _lo < target_garrison:
                target_garrison = min(target_garrison, _lo + DEF_CAP_SLACK)
        # CONCENTRATE everyone on node 0 only once the wave is genuinely CLOSING -- right on
        # top of us (<= CONCENTRATE_DIST) or having advanced strictly past the midline toward
        # us. We give up base income here on purpose (surviving outranks economy -- the user's
        # "don't be greedy" rule). The bar is tight: a stack merely PARKED at the gate boundary
        # is not committing, and concentrating on it for 70 turns starved our economy + L5 climb
        # and then the real wave killed us (log6). The wide gate is for DETECTION only.
        # ETA-REACT: the past-midline arm counts as "committed" ONLY if the stack is close enough to beat
        # our most-forward warrior home (stack_dist <= fist_return_ETA + margin). A far parked stack no longer
        # collapses home_safe -> the fist keeps raiding. The close-in arm + on_hq + siege_recall are untouched.
        _fwd_ret_eta = max((nav.hops(w.region, M.my_hq) for w in my_warriors
                            if nav.hops(w.region, M.my_hq) > nav.hops(w.region, M.opp_hq)), default=0)
        # VELOCITY: is the largest stack ADVANCING on our HQ? (shared `_stack_advancing` signal, hoisted
        # above the prev_stack_dist bookkeeping -- same formula as before, now reused by 2c/1d too.)
        _advancing = _stack_advancing
        committed = stack_reg >= 0 and (
            stack_dist <= CONCENTRATE_DIST
            or (stack_dist < nav.hops(stack_reg, M.opp_hq)
                and (not bool(ETA_REACT) or stack_dist <= _fwd_ret_eta + ETA_REACT_MARGIN)
                and (not bool(VELOCITY_HOLD) or _advancing)
                # R86b CONC_WAVE_GATE: an APPROACHING (not-yet-on-us) stack must be WAVE-scale to abandon the
                # economy -- a sub-wave (1(93) 4-stack) is harass; the surplus-pull (2a) + relief defend it.
                and (not bool(CONC_WAVE_GATE) or max(enemy_stack_sz, BOT.threat_army) >= CONC_WAVE_MIN)))
        # NOTE: do NOT concentrate merely because `threat > 0`. A couple of advanced enemy
        # scouts (threat 2-6) parked past the midline must not make us abandon our whole
        # economy for 100+ turns (that stalled HQ at L2 and the real late wave then killed us,
        # log6). `threat` still raises defenders_needed (pull surplus home); full concentration
        # waits for the stack to actually CLOSE, or the enemy to stand ON our HQ.
        concentrate = (on_hq > 0 or committed) and not _triv_hq   # TRIVIAL_SIEGE: standing guard handles it
        # CONC_KEEP_ECON (R54, 1(59) t86; user: "최단거리로 가는거라 HQ 거치지도 않는데 왜 반응하냐"):
        # the close-in committed arm (stack_dist <= CONCENTRATE_DIST) never looks at HEADING -- a
        # 10-stack sliding sideways along the 3-hop ring to eat our forward base 79 (hops-to-HQ
        # frozen 3->3->3 while hops-to-base79 fell 2->1->0) tripped the full turtle and dumped EVERY
        # base worker to node 0; the enemy never came, the latch released, and the workers walked
        # back -- income round-trip annihilation, the whole loss. When the close stack is NOT
        # advancing on the HQ and its nearest our-building is a non-HQ base it is closing on, keep
        # the base WORKERS earning (need = work_cap in the concentrate branch below); the ARMY still
        # musters home. A rush stack beelines (advancing every turn) and never trips this; the moment
        # the base-eater turns toward the HQ, _advancing flips and the full dump resumes.
        # R55 CK_PARK arm (1(60) t98; user: "99턴에 노동자가 모든 작업장에서 튀어나와 골드 누수"): the
        # not-advancing test alone misses a PARKED outpost when the largest-cluster pick JUMPS between
        # clusters (1(60): enemy-HQ recruit pool dist 10 -> outpost 60 dist 3 read as "advancing", then
        # a marching reinforcement column dist 8 took over and released the latch -- one 9-worker dump
        # plus the walk-back, repeating). If the stack's node ALSO held >= CK_PARK_MIN enemies last turn,
        # it is a sitting outpost regardless of the cluster-pick jitter. A rushing beeline occupies a
        # fresh node every turn and can never satisfy the two-turn residency test.
        _conc_keep_econ = False
        if (bool(CONC_KEEP_ECON) and concentrate and on_hq == 0
                and stack_reg >= 0
                and (not _advancing
                     or _ck_prev_nodes.get(stack_reg, 0) >= CK_PARK_MIN)):
            _ck_nb = min(my_building_regions, key=lambda r: nav.hops(stack_reg, r))
            _conc_keep_econ = (_ck_nb != M.my_hq and nav.hops(stack_reg, _ck_nb) <= 1)
        # FORWARD BASE-EATING: a sizable wave has pushed into OUR half (past the midline) but is NOT
        # on our HQ -- it is grinding our forward bases one by one. The default `concentrate` here
        # would turtle our whole army at node 0 and just watch the economy die while the enemy never
        # even comes to the HQ -- the EXACT log7/8 tiebreak loss (bases eaten -> income collapses ->
        # our HQ stalls at L3 while theirs reaches L5). Instead, when we can actually contest the
        # stack (our army >= its size), keep the economy lean and march our matched surplus out to
        # FIGHT the eaters where they stand (handled in 2c). Transitions back to a real HQ-turtle the
        # instant the stack actually closes on us (stack_dist <= CONCENTRATE_DIST -> base_eating off).
        # REACH_WIN: contest only with the force that can join the fight before the stack could reach our
        # HQ (stack_dist turns) -- the roster count approved contests the arriving trickle lost piecemeal.
        # HP_FIGHT_BAR (R49, see flag block): the contest is a FIELD FIGHT, so the bar weighs the
        # enemy stack by the warrior-hp ratio when their HQ outlevels ours (their bodies are tankier).
        base_eating = (on_hq == 0 and stack_reg >= 0
                       and stack_dist > CONCENTRATE_DIST
                       and stack_dist < nav.hops(stack_reg, M.opp_hq)
                       and enemy_stack_sz >= MOBILIZE_NEAR
                       and (sum(1 for w in my_warriors
                                if nav.hops(w.region, stack_reg) <= max(1, stack_dist))
                            if (bool(REACH_WIN) and enemy_stack_sz < WAVE_STACK_MIN)
                            else len(my_warriors))
                           + _home_turret(S, M, me, stack_reg) >= int(math.ceil(enemy_stack_sz * _hpfb)))
        if base_eating:
            concentrate = False
        # COUNTER-DOOMSTACK (user: hit the all-in's weakness -- their rear is empty): when we are
        # LOSING the land war AND the enemy committed its stack forward into our half, its HQ is
        # open. We lose the tiebreak anyway (economy collapsing), so RACE a counter-stack at the
        # enemy HQ to crack it outright instead of dying slowly. Overrides turtle/defend.
        _hq_ok = (hq is not None and (hq.level < _ehl0 if COUNTER_MODE == 'lt' else hq.level <= _ehl0))
        # V2R7 CTR_LATE_STAND (1(5) t107-109, see flag): a stack ALREADY within CONCENTRATE_DIST arrives
        # in <= 3 turns -- a counter-race needs ~10 hops of un-reorderable marching and cannot finish
        # first, so canceling the final-stand muster for it is a no-op that opens the HQ. Counter only
        # while the committing stack is still far.
        if (_terr_deficit and _hq_ok and stack_reg >= 0 and on_hq == 0 and enemy_stack_sz >= MOBILIZE_NEAR
                and stack_dist < nav.hops(stack_reg, M.opp_hq)
                and (not bool(CTR_LATE_STAND) or stack_dist > CONCENTRATE_DIST)
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
        # HP_FIGHT_BAR (R49): the turtle-or-contest fork is a field-fight verdict -> hp-weighted bar.
        # The defenders_needed staffing below stays headcount (hold rule).
        if _hq_bound or len(my_warriors) < int(math.ceil(fwd_sz * _hpfb)):
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
    # MATCH_AVAIL (user 8(4): "상대 가용인원 +1~2로 유지"): floor target_garrison at the enemy's AVAILABLE army
    # (enemy_total - its work capacity = the force it cannot be working = its real attack potential) + margin,
    # so EVERY branch -- including harass, whose harass_budget = my_warriors - target_garrison would otherwise
    # send nearly everyone forward during the enemy's steady buildup -- holds the matched deterrent home. Only
    # when BASE-AHEAD (economy winning, so the enemy pivots to a military breakthrough); a symmetric mirror is
    # never base-ahead by the margin, so this is byte-INERT there (no MATCH_TOTAL-style over-train regression).
    if (bool(MATCH_AVAIL) and turn >= MATCH_AVAIL_TURN and on_hq == 0):
        _ma_ebases = sum(1 for _b in S.buildings if _b.side is not M.my_side and _b.type is BType.BASE)
        _ma_avail = max(0, enemy_total - _enemy_workcap)
        if (len(my_bases) >= _ma_ebases + MATCH_AVAIL_BASE_MARGIN and _ma_avail >= MATCH_AVAIL_MIN):
            target_garrison = max(target_garrison,
                                  min(MATCH_AVAIL_CAP, _ma_avail + MATCH_AVAIL_MARGIN))
    # VELOCITY bookkeeping: remember this turn's largest-stack distance-to-HQ so next turn can tell if it is
    # ADVANCING (see the `committed` velocity gate). Reset to inf when there is no stack, so a fresh stack next
    # turn reads as advancing (first-sight reaction preserved).
    BOT.prev_stack_dist = stack_dist if stack_reg >= 0 else (1 << 30)

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
        if on_hq > 0 and not _triv_hq:   # TRIVIAL_SIEGE: a dribble the standing guard kills is no all-in
            _incoming_all_in = on_hq
        if (stack_reg >= 0 and enemy_stack_sz >= SIEGE_EMERG_STACK
                and stack_dist <= SIEGE_EMERG_RANGE
                and stack_dist < nav.hops(stack_reg, M.opp_hq)):   # has crossed toward us (beelining)
            _incoming_all_in = max(_incoming_all_in, enemy_stack_sz)
        # V2R8 MASS_DEPART (3.txt t65-67, see flag): a park-unload -- >= MASS_DEPART_F of the enemy's WHOLE
        # army popping off a multi-turn work-slot park and advancing 2 straight turns -- is the all-in
        # launch; waive ONLY the crossed-midline test (the recall was 3 turns late waiting for it).
        if (bool(MASS_DEPART) and stack_reg >= 0
                and enemy_stack_sz >= SIEGE_EMERG_STACK
                and enemy_stack_sz >= math.ceil(MASS_DEPART_F * max(1, len(enemy_warriors)))
                and BOT.adv_streak >= 2 and BOT.park_streak >= MASS_DEPART_PARK
                and stack_dist <= SIEGE_EMERG_RANGE):
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
    # --- MIL_GAMBIT detector (see flag block): is the opponent trading economy for an army lead? ---
    _mg_on = False
    _mg_hold = False
    if bool(MIL_GAMBIT) and hq is not None:
        if not hasattr(BOT, 'mg_seen'):
            BOT.mg_seen, BOT.mg_tlog, BOT.mg_latch, BOT.mg_fired = set(), [], False, False
        _mg_new = [w.id for w in enemy_warriors if w.id not in BOT.mg_seen]
        BOT.mg_seen.update(_mg_new)
        BOT.mg_tlog.append((turn, 0 if turn <= 1 else len(_mg_new)))  # t1 sightings = starting trio, not trains
        _mg_tr12 = sum(_n for _t, _n in BOT.mg_tlog if _t > turn - MG_STREAM_WIN)
        _mg_delta = len(enemy_warriors) - len(my_warriors)
        _mg_enb = sum(1 for b in S.buildings if b.side is not me and b.type is BType.BASE)
        _mg_hh = max(1, nav.hops(M.my_hq, M.opp_hq))
        _mg_deep = sum(1 for w in enemy_warriors
                       if nav.hops(w.region, M.my_hq) <= int(round(MG_DEEP_FRAC * _mg_hh)))
        # MG_DEEP_OPS (R50, 1(54) forensic): for the RELEASE check only, "deep" counts OPERATORS --
        # an enemy worker seated on its OWN forward building in our 40% zone is economy, not a gambit,
        # and counting it blocked the posture-end release FOREVER (t76-79: enemy field army dead, 7
        # bases > MG_STREAM_MAXB = release condition met, except one worker sitting on their forward
        # base 42 kept _mg_deep >= 1 -- harass/counter stayed sealed through our +6 body-lead window
        # and the winnable game drew). ARM semantics are untouched (a stack staging on a forward
        # building is still an incursion for arming purposes).
        _mg_deep_rel = _mg_deep
        if bool(MG_DEEP_OPS):
            _mg_own_bld = {b.region for b in S.buildings if b.side is not me}
            _mg_deep_rel = sum(1 for w in enemy_warriors
                               if nav.hops(w.region, M.my_hq) <= int(round(MG_DEEP_FRAC * _mg_hh))
                               and w.region not in _mg_own_bld)
        _mg_sig = (_mg_delta >= MG_DELTA_HARD
                   or (_mg_delta >= MG_DELTA_SOFT and _mg_deep >= 1)
                   or (_mg_tr12 >= MG_STREAM_TRAINS and _mg_enb <= MG_STREAM_MAXB
                       and _mg_delta >= MG_DELTA_SOFT))
        if _mg_sig and (turn <= MG_TURN_MAX or BOT.mg_fired):
            BOT.mg_latch = True
            BOT.mg_fired = True
        elif (BOT.mg_latch and _mg_deep_rel == 0
              and (_mg_enb > MG_STREAM_MAXB or _mg_tr12 == 0)):
            # POSTURE-END release ONLY. Parity-release thrashed (floors collapsed 4-vs-8, stream re-opened
            # the gap); the body-LEAD release was worse (measured t100-120: lead 11v7 -> unlatch -> harass
            # resumed -> the lead fed his base turrets -> 11 bodies bled to 0 by t200). Against an
            # unchanged gambit posture the hold-and-out-econ stance is permanent; unlatch only when he
            # actually expands past the base cap or fully stops producing for a window.
            BOT.mg_latch = False
        _mg_on = BOT.mg_latch
        _mg_hold = _mg_on and _mg_delta >= 1  # austerity tier: claim/harass freeze only while OUTNUMBERED
    # --- R51 tempo bands (see flag block). Computed here so the harass gate below reads them. ----------
    # INCOME_PRESS: economy-backed masser (enb >= bar separates him from a base-capped waverush gambit)
    # + we out-earn + we are body-behind -> the freeze is wrong, the income leader wins the trade.
    _inc_press = (bool(INCOME_PRESS) and _mg_on
                  and _mg_enb >= IP_ENEMY_BASES
                  and _my_workcap0 > _enemy_workcap + IP_INC_EDGE
                  and len(enemy_warriors) - len(my_warriors) >= IP_DELTA_MIN)
    # L2_FIRST_GUARD: our first-to-L2 wallet just emptied -- the enemy will probe; bodies now.
    # Armed only when there is a prober TO guard against: >= 2 enemy bodies within L2F_NEAR hops of
    # OUR buildings (the AVAIL_CLAIM_GATE proximity predicate -- the user's "분명 상대가 파고 들거니까"
    # presumes a visible incursion force). A midline test was tried first and failed: routine enemy
    # CLAIMERS cross the midline all game, so the unconditional guard still burned claim/bank tempo
    # against a home-parked climber (measured my-bot K19 2W->2D, isolated to this flag).
    # ...and only from a REAL deficit: the user's own bar is "-1 ~ -2가 최대 마지노선", so the guard
    # arms at deficit >= L2F_DEFICIT and its own trains close back to -2 and stop (self-expiring).
    # Measured: 55-t54 fired at 5v8 (deficit 3, active attackers -> the save); my-bot-2001-t82 fired
    # at 16v18 (deficit 2, a parked deterrent cloud) and the 11-turn premium was the W->D margin.
    _l2f_ebld = {b.region for b in S.buildings if b.side is not me} if bool(L2_FIRST_GUARD) else set()
    _l2f_win = (bool(L2_FIRST_GUARD) and hq is not None
                # L4_WINDOW (R52): the guard also covers OUR L4 buy (2400g dump); L5 excluded (s2010).
                and ((hq.level == 2 and _ehl0 < 2)
                     or (bool(L4_WINDOW) and hq.level == 4 and _ehl0 < 4))
                and turn - getattr(BOT, 'mhq_dev_turn', -99) <= L2F_WIN
                and len(enemy_warriors) - len(my_warriors) >= L2F_DEFICIT
                # probers = OFF-BUILDING bodies near our stuff; a worker seated on its own building
                # is economy, not an incursion (the MG_DEEP_OPS taxonomy) -- my-bot's parked cloud
                # satisfied the raw proximity count through its adjacent expansions.
                and sum(1 for w in enemy_warriors
                        if w.region not in _l2f_ebld
                        and any(nav.hops(w.region, _br) <= L2F_NEAR
                                for _br in my_building_regions)) >= 2)
    # L2_LATE_PUNISH: HIS wallet just emptied and we are level-behind -- convert lag into damage.
    # THE L2 WINDOW ONLY (_ehl0 == 2), exactly as the user stated ("HQ 2레벨 타이밍이 늦는다면"):
    # a first-draft any-level-gap predicate re-armed at his L4->L5 (my-bot s2010 t178) and lean-trained
    # 9 bodies with the gold that had to bank OUR L5 -- the level race owns the late game; higher-gap
    # catch-up is _behind_hq climb machinery's job, not a punish window's.
    _l2p_win = (bool(L2_LATE_PUNISH) and hq is not None and hq.level < _ehl0
                # L4_WINDOW (R52): HIS L4 buy is punishable too (5(6) t135: thin avail-2 enemy, untouched).
                and (_ehl0 == 2 or (bool(L4_WINDOW) and _ehl0 == 4))
                and turn - getattr(BOT, 'ehq_dev_turn', -99) <= L2P_WIN)
    # The punish EXPEDITION (harass arm) launches only from body-parity AND only when his STANDING
    # army is thin (avail = total - workcap): the doctrine's target is the human whose tech buy left
    # him army-poor. Measured counterexample: my-bot 2007 teched L3 while HOLDING avail 8 -- the
    # parity-only arm opened 21 turns of pokes at a garrisoned turtle, bled tempo, and our own climb
    # lagged L3-vs-L4 (W->D). The punish TRAINS (the 1(51) t44-48 fix) are deficit-gated inside the
    # train loop and stay as-is.
    _l2p_raid = (_l2p_win and len(my_warriors) >= len(enemy_warriors)
                 and len(enemy_warriors) - _enemy_workcap <= L2P_THIN)
    # OVEREXPAND_PUNISH (R56, 1(62) loss; user: "기지 2개 앞서가는 타이밍(t65)에 병력을 찍고 응징을 했어야
    # ... 단순히 전체 병력수로만 계산한 판단"): the enemy is planting bases FASTER than us while its
    # standing army is all WORKERS (total - workcap thin) -- an unguarded land-grab. 1(62) measured:
    # every offense gate (_harass_now, home_safe, _terr_deficit) was OPEN from t55 but raid_force sat
    # at 0-1 through t65-77 because training is threat-driven (thA/thT = 0: seven enemy bodies, seven
    # seated workers) -- no bodies, no punish, and by t102 the fist finally left against 8 bases. The
    # window closes ITSELF when the enemy starts fielding an army (avail > OXP_THIN), so a masser or
    # waverusher (large avail) can never arm this. Consumed by the two R51 train arms below (army
    # floor + upkeep-lean funding); the release machinery needs no change -- gates were never the gap.
    _oxp_win = (bool(OVEREXPAND_PUNISH) and hq is not None and on_hq == 0 and not _mg_on
                and sum(1 for b in S.buildings
                        if b.side is not M.my_side and b.type is BType.BASE)
                    >= len(my_bases) + OXP_BASE_LEAD
                and len(enemy_warriors) - _enemy_workcap <= OXP_THIN)
    # EXPAND_ESCORT (R66, see flag): opening available-army deficit (symmetric total-workcap arithmetic,
    # the R56 operand on BOTH sides) -> train the deficit back, but ONLY as an escort ATTACHED to live
    # expansion ("기지 하나를 세울 때 반드시 ... 뽑아놔야") and ONLY against a SQUAD-sized enemy avail.
    # An unconditional matcher was built first and waverush-refuted (cr 5/9/7): matching a mass-RAMP 1:1
    # pins the wallet under ~200g forever -> the 600g L2 fortress is never banked and claims freeze ->
    # the wave meets a L1 turret. The claim-window term makes a frozen-claim game self-close EE (negative
    # feedback: no expansion -> no escort -> bank recovers), and the avail band hands mass-armies to the
    # MIL_GAMBIT / threat machinery that correctly answers them with fortress+lean, not parity chasing.
    _ee_regs = {b.region for b in my_bases}
    if _ee_regs - BOT.ee_bases:
        BOT.ee_claim_turn = turn
    BOT.ee_bases = _ee_regs
    _ee_def = ((len(enemy_warriors) - _enemy_workcap) - (len(my_warriors) - _my_workcap0)
               if bool(EXPAND_ESCORT) else 0)
    _ee_win = (bool(EXPAND_ESCORT) and hq is not None and on_hq == 0 and not _mg_on
               and EE_TURN_MIN <= turn <= EE_TURN and _ee_def >= EE_DEFICIT
               and len(enemy_warriors) - _enemy_workcap <= EE_EAV_MAX
               and turn - BOT.ee_claim_turn <= EE_CLAIM_WIN)
    # PROACTIVE HARASS (the user's 양동작전): once our economy is healthy (HQ >= HARASS_HQLEVEL)
    # OR we are already behind, send the TRUE surplus to grind the enemy's bases as TWO evasive
    # squads (_two_front_raid: two prongs on opposite flanks; a prong that meets a bigger force
    # DISENGAGES and hits where they ain't). This denies the enemy economy so it cannot out-climb
    # us in a quiet game (real log 5: we did zero damage and lost the HQ race by one level).
    _harass_now = (bool(PROTO_ATTACK) and on_hq == 0 and hq is not None
                   # MIL_GAMBIT: the surplus stays HOME while latched -- re-opening the raid at parity was
                   # tried and measured (-1 game): any body that leaves is punished by the next wave cycle.
                   # R51 INCOME_PRESS is the ONE exception: an economy-backed masser (enb >= 4, never a
                   # base-capped waverush) while we out-earn -- the income leader takes the trade.
                   and (not _mg_on or _inc_press)
                   and (_terr_deficit or hq.level >= HARASS_HQLEVEL
                        or _inc_press or _l2p_raid
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
    # EARLY FORTRESS (campaign fix #2): engage before FORTRESS_TURN when the enemy army DECISIVELY out-scales
    # ours (>= ours + EARLY_FORT_MARGIN AND a real army) -- consolidate home NOW rather than feed the smaller
    # army into a lost forward trade (the g1/g1_6/g1_1 HQ-kills). Implies the enemy>=ours-SLACK and >=ARMY
    # sub-conditions, so it slots straight into the existing gate as an alternative to the turn clock.
    # Gated K<=WIDE_FORCE_ANCHOR (the HQ-kills were all K13-K15): on the widest maps (K17/K19) the doctrine is
    # deny/push, not turtle, and the loss there (g1_3 K19) was upkeep-starvation not an HQ-kill -- so early
    # fortress is off-target there and left byte-identical (keeps wide-map play untouched).
    _overwhelmed = (bool(EARLY_FORT) and M.K <= WIDE_FORCE_ANCHOR and turn >= EARLY_FORT_TURN
                    and enemy_total >= len(my_warriors) + EARLY_FORT_MARGIN
                    and enemy_total >= FORTRESS_ARMY)
    _fortress = (bool(FORTRESS) and (turn >= FORTRESS_TURN or _overwhelmed) and hq is not None
                 and enemy_total >= len(my_warriors) - FORTRESS_SLACK
                 and (enemy_total >= FORTRESS_ARMY or _inbound >= FORTRESS_MIN))
    # DECISIVE-PIN exception (game 6): when our HQ is ALREADY MAXED (L5) and we hold a decisive HQ-level
    # lead on the BOUNDARY band, fortress-turtling is pointless -- we cannot climb higher and we are already
    # ahead, so cowering home just hands the enemy a free catch-up climb (the game-6 DRAW: A_L5 coasts, B
    # free-climbs to L5). Provided the enemy is NOT actually storming our HQ (_inbound < FORTRESS_MIN; our
    # maxed turret+30hp holds the rest), keep the army OUT pinning the enemy. Gated K11-15 (K9 game-8 fortress
    # win is L4/1-ahead, never maxed-and-decisive -> untouched; K17+ is _wide_push's zone).
    _decisive_pin = (bool(CLIMB_PUSH) and WIDE_K <= M.K < WIDE_FORCE_ANCHOR and hq is not None
                     and _is_max(hq) and (hq.level - _ehl0) >= CLIMB_LEAD_MIN
                     and on_hq == 0 and _inbound < FORTRESS_MIN)
    # V2 FORT_VELO (g7, see flag): the fortress HOLD (recall + offense-off) fires only when the enemy
    # stack is actually PRESSING -- advancing this turn, inside the approach gate, in our half, or on our
    # HQ. A stack PARKED on its own HQ for 15 turns is a garrison, not an assault; recalling on the t140
    # clock emptied the forward line and donated three bases. First sight (prev=inf) counts as advancing.
    _fort_hold = (_fortress and FORTRESS_HOLD and not _decisive_pin
                  and (not bool(FORT_VELO) or on_hq > 0 or _stack_advancing
                       or (stack_reg >= 0 and (stack_dist <= gate
                                               or stack_dist < nav.hops(stack_reg, M.opp_hq)))))
    if _fort_hold:
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
    # MIDLINE FIX (log-8 forensic): a stack sitting literally ON one of our OWN bases is razing our economy
    # wherever that base sits -- so for the ON-OUR-BASE case relieve it even when the base is exactly AT the
    # midline. Log-8 t128: the enemy's 11-stack stood ON our forward base 27, which is equidistant (4 hops to
    # our HQ == 4 hops to theirs); the old strict `stack_dist < hops(stack_reg, opp_hq)` read that as "not in
    # our half" and NEVER relieved, so the base was razed for free while our whole army sat home. The
    # `stack_reg in my_building_regions` test already proves it is OUR base under siege, so the extra half-map
    # test is redundant there -- relax it to `<=` (still capped at the midline so we never march the army PAST
    # the midline chasing a lone base on ENEMY ground = over-extension). A stack merely ADJACENT to our base
    # keeps the strict our-half test (it is not yet grinding us). All the contest guards (army+turret >= stack,
    # army >= guard+FORCE) are unchanged, so this only ever fires a relief we can actually win.
    _stack_on_ours = stack_reg in my_building_regions
    # REACH_WIN (see flag block): the win test counts bodies that can BE at the fight inside its window
    # (grind TTL for an on-ours stack, 2 turns for a merely-adjacent one), not the global roster; the
    # RELIEF_SLACK that made the whole-army test vacuous is dropped in reach mode.
    # ★WAVE-BAND EXEMPTION (8(5) vs 8(6) regression): REACH_WIN's tightened counts apply ONLY to the
    # SUB-wave band (E < WAVE_STACK_MIN). Wave-scale relief is a STAGING fight -- the base + turret +
    # garrison hold while the whole army converges over many turns (and the early muster itself deters:
    # 8(6)'s wave rerouted on contact) -- so the legacy whole-army arm is load-bearing there. 8(5) proved
    # it: the reach test recalled the t72 stagers to the HQ, ceded base 27 to the 11-wave, lost the game
    # the pre-REACH_WIN build (8(6)) had won on the identical map/opponent.
    _rw_relief = len(my_warriors)
    if bool(REACH_WIN) and stack_reg >= 0 and enemy_stack_sz < WAVE_STACK_MIN:
        _rwb = S.find_building(stack_reg)
        # adjacent (not-on-ours) stack: the fight develops over the stack's own approach window
        # (stack_dist turns to our HQ), so home-mustered bodies arriving mid-grind count (Opus review
        # finding 1: a hardcoded 2 refused winnable slow-reinforcement reliefs -- the arm requires
        # stack_dist > CONCENTRATE_DIST, so the muster is always 4+ hops out).
        # window = the LONGER of the static grind TTL and the stack's own approach window (stack_dist):
        # the referee grind slows as defenders arrive (rate = attackers - defenders), so the static TTL
        # badly under-counts home-mustered reinforcement (K19 ablation: static TTL alone lost 4 wins vs
        # my-bot -- both relief arms refused and nobody relieved).
        _rw_h = (max(math.ceil(_rwb.hp / max(1, enemy_stack_sz)) + 1, stack_dist)
                 if (_rwb is not None and _rwb.side is me) else max(2, stack_dist))
        _rw_relief = sum(1 for w in my_warriors if nav.hops(w.region, stack_reg) <= _rw_h)
    _relief = (bool(RELIEF) and on_hq == 0 and stack_reg >= 0
               and enemy_stack_sz >= RELIEF_MIN
               and stack_dist > CONCENTRATE_DIST
               and (stack_dist <= nav.hops(stack_reg, M.opp_hq) if _stack_on_ours
                    else stack_dist < nav.hops(stack_reg, M.opp_hq))
               and (_stack_on_ours
                    or any(nb in my_building_regions for nb in M.adj[stack_reg]))
               and _rw_relief + _home_turret(S, M, me, stack_reg)
                   >= enemy_stack_sz - (0 if (bool(REACH_WIN) and enemy_stack_sz < WAVE_STACK_MIN)
                                        else RELIEF_SLACK)
               and len(my_warriors) >= guard_floor + RELIEF_FORCE)
    _relief_tgt = stack_reg
    # V2 EATER-RELIEF (g1, see flag): the detector above keys on the GLOBAL largest stack; in g1 that
    # was the enemy's home garrison, so 3-body eaters ON OUR BASES never became the target and ten
    # bases fell with relief firing zero times. Detect the largest enemy group standing on one of OUR
    # buildings directly (that group is provably razing us -- the referee auto-sieges) and relieve it
    # when we win the local fight. Same guards as classic relief; the HQ node itself stays on_hq's job.
    _eat_relief_sz = 0                 # V2R7 RELIEF_SIZED: size of the eater party when EATER_RELIEF fired
    if bool(EATER_RELIEF) and not _relief and on_hq == 0:
        _ecnt = Counter(w.region for w in enemy_warriors
                        if w.region in my_building_regions and w.region != M.my_hq)
        if _ecnt:
            _eat_reg, _eat_sz = _ecnt.most_common(1)[0]
            # REACH_WIN: bodies that can reach the eaten base inside its TTL (ceil(hp/eaters)+1).
            _rw_eat = len(my_warriors)
            if bool(REACH_WIN):
                _rweb = S.find_building(_eat_reg)
                # same widened window as classic relief: grind TTL OR the home-muster march time,
                # whichever is longer (defender arrivals slow the referee grind, extending the window).
                _rwe_h = max((math.ceil(_rweb.hp / max(1, _eat_sz)) + 1) if _rweb is not None else 2,
                             nav.hops(M.my_hq, _eat_reg))
                _rw_eat = sum(1 for w in my_warriors if nav.hops(w.region, _eat_reg) <= _rwe_h)
            if (_eat_sz >= 2
                    and _rw_eat + _home_turret(S, M, me, _eat_reg) >= _eat_sz + 1
                    and len(my_warriors) >= guard_floor + RELIEF_FORCE):
                _relief = True
                _relief_tgt = _eat_reg
                _eat_relief_sz = _eat_sz
    # V2 RELIEF_ETA (g7, see flag): a WAVE_STACK_MIN+ stack ADVANCING within 2 hops of one of OUR bases
    # that we can beat -> relieve AT THE BASE (our turret ground; bodies standing there zero the siege).
    # Covers the beyond-midline bases every other gate is geometrically blind to (base 21: razed in one
    # turn by an 11-stack while 21 of our bodies sat at home).
    # V2R8 RELIEF_ETA_HQGUARD (3.txt t70-72, see flag): a stack already within CONCENTRATE_DIST of our HQ
    # (or with the all-in recall armed) is beelining US -- classifying it as a "base relief" slashed
    # defenders_needed to 1 and evacuated the mustered garrison one turn before impact. Same guard classic
    # _relief already has; an ON-our-base stack stays classic/EATER relief's job (their exemptions intact).
    if (bool(RELIEF_ETA) and not _relief and on_hq == 0 and stack_reg >= 0
            and enemy_stack_sz >= WAVE_STACK_MIN and _stack_advancing
            and (not bool(RELIEF_ETA_HQGUARD)
                 or (stack_dist > CONCENTRATE_DIST and not siege_recall))
            and len(my_warriors) >= guard_floor + RELIEF_FORCE):
        _rb = min(my_bases, key=lambda b: nav.hops(stack_reg, b.region), default=None)
        # REACH_WIN: bodies that can BE ON the base by the stack's arrival (same _preach pattern as PRESTAGE).
        # Wave-band exemption (8(5)): RELIEF_ETA arms only for E>=WAVE_STACK_MIN, so the reach test here is
        # ALWAYS a wave staging fight -- keep the legacy whole-army arm (see the classic-relief note above).
        if (_rb is not None and nav.hops(stack_reg, _rb.region) <= 2
                and nav.hops(_rb.region, M.my_hq) < stack_dist + 2
                and (sum(1 for w in my_warriors
                         if nav.hops(w.region, _rb.region) <= max(1, nav.hops(stack_reg, _rb.region)))
                     if (bool(REACH_WIN) and enemy_stack_sz < WAVE_STACK_MIN) else len(my_warriors))
                    + _home_turret(S, M, me, _rb.region) >= enemy_stack_sz):
            _relief = True
            _relief_tgt = _rb.region
    # PRESTAGE (8(2).txt, see flag): predictive pre-stage -- the enemy's shortest-path approach is deterministic,
    # so fire RELIEF_ETA's base-relief EARLIER (up to PRESTAGE_REACH hops) on the stack's on-path target base we
    # DECISIVELY win at, so the winning force STANDS there before the stack lands. Rush-safe: on-path
    # (_phs+_phh<=stack_dist+1) => holds the HQ approach AND _phh<stack_dist => we recall home before a feint/2-prong.
    # PRESTAGE_SUBWAVE (see flag block): the stack band drops to SUBWAVE_MIN(6) once the stack has latched
    # the threat counter (inside THREAT_RANGE, our side of the midline) -- the 1(36) coverage hole where a
    # 6-stack razing forward bases had NO smart defender and the threat+1 fill retreated the army instead.
    _ps_min = (SUBWAVE_MIN if (bool(PRESTAGE_SUBWAVE) and threat >= THREAT_MIN)
               else WAVE_STACK_MIN)
    if (bool(PRESTAGE) and not _relief and on_hq == 0 and not siege_recall
            and stack_reg >= 0 and enemy_stack_sz >= _ps_min and _stack_advancing
            and stack_dist > CONCENTRATE_DIST
            and len(my_warriors) >= guard_floor + RELIEF_FORCE):
        _pb = min(my_bases, key=lambda b: nav.hops(stack_reg, b.region), default=None)
        if _pb is not None:
            _phs = nav.hops(stack_reg, _pb.region)       # stack -> target base (ETA in turns)
            _phh = nav.hops(_pb.region, M.my_hq)          # target base -> our HQ
            _preach = sum(1 for w in my_warriors if nav.hops(w.region, _pb.region) <= _phs)
            if (1 <= _phs <= PRESTAGE_REACH and _phh < stack_dist   # forward of HQ, within predictive reach
                    and _phs + _phh <= stack_dist + 1               # base ON the stack's shortest path to our HQ
                    and _preach + _home_turret(S, M, me, _pb.region) >= enemy_stack_sz + PRESTAGE_MARGIN):
                _relief = True
                _relief_tgt = _pb.region
    # MASS_STAGE (R67, see flag block): PRESTAGE's parked-mass arm -- identical target pick, on-path and
    # decisive-reach arithmetic, but fired while the mass is still STANDING (not _stack_advancing). The
    # moment it launches, _stack_advancing flips and classic PRESTAGE/RELIEF_ETA/concentrate own the fight
    # (same _relief plumbing -> clean ownership handoff, no second owner to flap against).
    if (bool(MASS_STAGE) and not _relief and on_hq == 0 and not siege_recall
            and stack_reg >= 0 and enemy_stack_sz >= MASS_STAGE_MIN
            and not _stack_advancing
            and stack_dist > CONCENTRATE_DIST
            and len(my_warriors) >= guard_floor + RELIEF_FORCE):
        _mb = min(my_bases, key=lambda b: nav.hops(stack_reg, b.region), default=None)
        if _mb is not None:
            _mhs = nav.hops(stack_reg, _mb.region)        # the mass's march to its nearest target base
            _mhh = nav.hops(_mb.region, M.my_hq)          # target base -> our HQ
            _mreach = sum(1 for w in my_warriors if nav.hops(w.region, _mb.region) <= _mhs)
            _ms_reach = MASS_STAGE_REACH + (1 if M.K <= MS_NARROW_K else 0)
            if (1 <= _mhs <= _ms_reach and _mhh < stack_dist
                    and _mhs + _mhh <= stack_dist + 1
                    and _mreach + _home_turret(S, M, me, _mb.region) >= enemy_stack_sz + PRESTAGE_MARGIN):
                _relief = True
                _relief_tgt = _mb.region
    # RELIEF_UNDER_SIEGE (8.txt forensic, see flag): re-enable a forward base-relief that RELIEF_ETA_HQGUARD
    # would block under siege_recall -- but ONLY for a base squarely ON the all-in's SHORTEST path to our HQ
    # that we DECISIVELY win at. Holding such a base IS the HQ defense (the stack must fight through it, can't
    # bypass), and the all-in has no reinforcement, so winning there ENDS the assault AND saves the economy the
    # pure HQ-turtle cedes for free (8.txt: 8 bodies+turret on base 11 recalled home, base razed, tiebreak lost).
    # 3.txt SAFETY: that loss relieved a base the all-in could BYPASS; on-path + arrive-in-time + decisive-margin
    # exclude it. This only FIRES when siege_recall already armed -> RELIEF_UNDER_SIEGE=0 => byte-identical.
    if (bool(RELIEF_UNDER_SIEGE) and not _relief and siege_recall and on_hq == 0
            and stack_reg >= 0 and enemy_stack_sz >= WAVE_STACK_MIN and _stack_advancing
            and len(my_warriors) >= guard_floor + RELIEF_FORCE):
        _rbs = min(my_bases, key=lambda b: nav.hops(stack_reg, b.region), default=None)
        if _rbs is not None:
            _hs = nav.hops(stack_reg, _rbs.region)       # turns until the stack reaches the base
            _hh = nav.hops(_rbs.region, M.my_hq)          # base -> our HQ
            # 8(1).txt fix (user: "기지에 아군 인원 >= 상대면 막을 수 있다"): count the force that can BE ON the
            # base when the stack hits -- the garrison already there (0 hops) PLUS any body within _hs hops that
            # converges in time. The old gate used len(my_warriors) behind an `_hh<=_hs` HQ-reinforce-ETA test,
            # which REFUSED to hold when we already had a WINNING garrison ON the base but the base sat nearer HQ
            # than the stack (t85: 12 bodies on base 11 vs an 11-stack 1 hop out -> recalled -> base razed). The
            # right test is REACHABILITY (can this force be there in time), not whether the HOME army can also arrive.
            _reach = sum(1 for w in my_warriors if nav.hops(w.region, _rbs.region) <= _hs)
            if (1 <= _hs and _hh < stack_dist             # base is forward of HQ, stack not yet on it
                    and _hs + _hh <= stack_dist + 1        # base sits ON the stack's SHORTEST path to our HQ
                    and _reach + _home_turret(S, M, me, _rbs.region)
                        >= enemy_stack_sz + RELIEF_UNDER_SIEGE_MARGIN):   # our on-time force wins the base fight
                _relief = True
                _relief_tgt = _rbs.region
    # V2R6 RELIEF_ETA_BODY (1(2) t74): a relief NOBODY can reach in time is a march to a funeral -- the
    # 6-stack was pulled off a 4-hp siege toward a base 6 hops away that fell in 2 turns. TTL = base hp /
    # on-site eaters (+1 slack); if no body can arrive inside it, the base is already lost -- release the
    # relief so the force keeps razing / backdoors instead (사용자: "지킬 수 없으니 연속적으로 가까운 상대
    # 기지를 공격하는 것"). A merely-adjacent stack (no eater on the tile yet) keeps a loose TTL.
    if bool(RELIEF_ETA_BODY) and _relief:
        _rtb = S.find_building(_relief_tgt)
        _rte = max(1, sum(1 for w in enemy_warriors if w.region == _relief_tgt))
        _rttl = (math.ceil(_rtb.hp / _rte) + 1) if _rtb is not None else (1 << 30)
        if not any(nav.hops(w.region, _relief_tgt) <= _rttl for w in my_warriors):
            _relief = False
    # RALLY_FALLBACK (R74, 5(11) AI5 패, see flag): a wave-band base-relief fires on the base CLOSEST to the
    # stack (the most-forward base = the one the stack razes first). The wave arm's win test uses len(my_warriors)
    # (the reach-win-unification NO-GO: whole-army for a genuine staging fight), so it fires even when that forward
    # base is UNHOLDABLE -- only the handful of bodies inside the stack's ETA can actually be there at the raze,
    # not the whole army. 5(11): a 11-stack razed base 71 (7 bodies reach in 2 hops) then serially 47/39/16 while
    # 30 of our bodies never made a stand. User: "이미 상대 공격으로 해당 기지를 막을 수 없다면 집결 위치를 그
    # 다음 인근 기지에 -- 인원 뽑아 잘 막으면 된다." When the natural target is reach-UNholdable, re-pick the relief
    # to the MOST-FORWARD base on the stack's path to our HQ that we CAN hold (reach-by-raze + turret >= stack) --
    # a fallback defensive line one base back, where the army actually converges. This does NOT touch the FIRE
    # decision (the NO-GO's domain -- keep relieving); it only redirects an already-doomed target to a live one.
    _rf_fire = (bool(RALLY_FALLBACK) and _relief and on_hq == 0 and stack_reg >= 0
                and enemy_stack_sz >= WAVE_STACK_MIN
                and _relief_tgt in my_building_regions and _relief_tgt != M.my_hq)
    if _rf_fire:
        def _rf_hold(_reg):   # bodies that can BE ON _reg by the time the stack would raze it (arrival + grind)
            _b = S.find_building(_reg)
            if _b is None:
                return -1
            _w = nav.hops(stack_reg, _reg) + math.ceil(_b.hp / max(1, enemy_stack_sz))  # raze-ETA window
            return (sum(1 for w in my_warriors if nav.hops(w.region, _reg) <= _w)
                    + _home_turret(S, M, me, _reg))
        def _rf_ok(_reg):     # a base still worth rallying to: exists, forward of HQ, on-path, and holdable
            return (_reg in my_building_regions and _reg != M.my_hq
                    and nav.hops(_reg, M.my_hq) < stack_dist
                    and nav.hops(stack_reg, _reg) + nav.hops(_reg, M.my_hq) <= stack_dist + RALLY_FB_SLACK
                    and _rf_hold(_reg) >= enemy_stack_sz + RALLY_FB_MARGIN)
        # LATCH: once we regroup onto a defensive-line base, HOLD it (don't re-pick the most-forward base every
        # turn as the stack advances -- bodies must commit to ONE stand, not chase a receding target). Release the
        # latch only when that base can no longer be held (razed / stack passed it / went off-path).
        if BOT.fb_tgt >= 0 and _rf_ok(BOT.fb_tgt):
            _relief_tgt = BOT.fb_tgt
        elif _rf_hold(_relief_tgt) < enemy_stack_sz + RALLY_FB_MARGIN:   # natural target is a march to a funeral
            _rf_cands = [b for b in my_bases if _rf_ok(b.region)]
            if _rf_cands:
                # most-forward holdable = the defensive line as far up as we can still win (user: "다음 인근 기지"),
                # then latch it so the following turns consolidate here instead of retargeting.
                _relief_tgt = max(_rf_cands, key=lambda b: nav.hops(b.region, M.my_hq)).region
                BOT.fb_tgt = _relief_tgt
        else:
            BOT.fb_tgt = -1   # the natural forward target is holdable -- no fallback line needed, drop the latch
    else:
        BOT.fb_tgt = -1       # not relieving a wave -- clear any stale latch
    # V2R7 RELIEF_SIZED (1(3) poke-leash, see flag): a SMALL eater party with NO wave signal anywhere is
    # a leash, not an assault -- relieve it with a sized squad and let the committed fist keep marching.
    _relief_small = (bool(RELIEF_SIZED) and _relief and 0 < _eat_relief_sz <= RELIEF_SIZED_MAX
                     and on_hq == 0
                     and (stack_reg < 0 or (enemy_stack_sz < WAVE_STACK_MIN and not _stack_advancing)))
    # When relieving, the ONLY threat is that forward stack (it is sitting on our
    # base, not our HQ -- on_hq==0). Don't let `threat` pin the whole army home; hold
    # just the guard and send the rest as a real relief force to fight the column.
    if _relief:
        defenders_needed = min(len(my_warriors), guard_floor)

    # POST_WAVE_HOLD bookkeeping (see flag block): the scatter dump is triggered by defenders_needed COLLAPSING
    # the turn a defensive episode ends (concentrate OR threat OR relief releases its hold) -- so detect the
    # COLLAPSE itself, after the LAST defenders_needed adjustment above. 1(30): defneed 5 (t63-66 wave defense,
    # threat-driven, concentrate never armed) -> 1 at t67-68 = drop 4 -> the freed surplus dumped 3 claimers at
    # once at t68. A drop >= PWH_DROP opens the consolidation window; 1-2 body threat-wobbles never trip it.
    if bool(POST_WAVE_HOLD):
        if BOT.prev_defneed - defenders_needed >= PWH_DROP:
            BOT.wave_cleared_turn = turn
        BOT.prev_defneed = defenders_needed

    # MAX_SWEEP (R53, see flag block): our HQ is MAXED on the wide map -- the tiebreak is HQ hp and
    # the fort holds itself (turret 3 + SWEEP_GUARD + 3/turn refill + the heal bank), so the threat-
    # matched home keep is the wrong posture: cap BOTH keep operands at SWEEP_GUARD and let everything
    # else flow into surplus -> raid_force -> the sweep. Suspended the moment real defense owns the
    # turn (on_hq / concentrate / siege_recall) -- the keeps snap back to their matched values.
    _sweep_on = (bool(MAX_SWEEP) and hq is not None and _is_max(hq)
                 and M.K > WIDE_FORCE_ANCHOR
                 and on_hq == 0 and not concentrate and not siege_recall
                 and any(_b.side is not me and _b.type is BType.BASE for _b in S.buildings))
    if _sweep_on:
        defenders_needed = min(defenders_needed, SWEEP_GUARD)
        target_garrison = min(target_garrison, SWEEP_GUARD)
    # --- per-building garrison need -----------------------------------------
    # Keep economy LEAN so a raid army actually forms: each base holds only
    # WORKERS_PER_BASE worker(s) (still earns income); the HQ holds just the guard
    # (the mustering raid army parked at the HQ supplies its work income anyway).
    # Everyone beyond this becomes the raid force -> attacking is possible from far
    # lower thresholds, on far more maps.
    need: dict[int, int] = {}
    # R87 MG_RELIEF_LEAN (see flag block): bases under ACTIVE attack (an enemy adjacent) -- a base whose MG
    # pre-garrison sits within MG_LEAN_REACH hops of one of these should feed the fight, not idle.
    _mg_lean_ok = (bool(MG_RELIEF_LEAN) and _mg_on and turn <= MG_LEAN_TMAX
                   and enemy_total <= len(my_warriors) + MG_LEAN_MARGIN)
    _mg_under_attack = ({bb.region for bb in my_buildings
                         if any(nav.hops(e.region, bb.region) <= 1 for e in enemy_warriors)}
                        if _mg_lean_ok else set())
    for b in my_buildings:
        if b.region == M.my_hq:
            need[b.region] = max(b.work_cap(), defenders_needed)   # HQ: full income (safe at home)
        elif concentrate and not (_mg_on and enemy_stack_sz < WAVE_STACK_MIN):
            # CONC_KEEP_ECON (R54, see predicate above): a base-eating sideways stack keeps the
            # workers earning; only a genuine HQ-ward wave empties the bases.
            need[b.region] = b.work_cap() if _conc_keep_econ else 0
        elif _mg_on:
            # MIL_GAMBIT pre-garrison (see flag block; 1(47) hold rule: a building holds iff
            # defenders_present + turret >= attackers, and reactive relief arrives one turn late on the
            # 2-hop geometry) -- against a latched army-gambit every base keeps a STANDING garrison, so a
            # 4-fist bounces outright (3+turret=4) and a 5-wave grinds at 1hp/turn (6 turns = relief/HI
            # arrive with the fight still winnable). The sub-wave carve-out above also stops concentrate
            # from yanking these garrisons home mid-siege (the measured base-8 tug-of-war collapse).
            # (Frontier-only concentration was tried and measured WORSE: cr11 -> cr14, the 2 wins lost --
            # the even floor's training demand and rear coverage carry the held games.)
            # R87 MG_RELIEF_LEAN: this base's excess should REINFORCE an adjacent ACTIVE fight rather than idle
            # (base 6, 1 hop from the base-21 fight, held 2 idle bodies for 12 turns). Lean to work_cap only when
            # a base under active attack sits within reach AND this base is not itself the one being stormed.
            if (_mg_lean_ok and b.region not in _mg_under_attack
                    and any(nav.hops(b.region, _ua) <= MG_LEAN_REACH for _ua in _mg_under_attack)):
                need[b.region] = b.work_cap()
            else:
                need[b.region] = max(b.work_cap(), MG_BASE_GARRISON)
        else:
            # KEEP EVERY BASE WORKER (the user's compounding rule): each base earns its FULL work_cap
            # so the economy compounds. We NEVER pull a working soldier into the army -- raiders come
            # ONLY from the TRUE surplus trained on top of total_need (want_spare). Pulling workers to
            # "match the enemy's total" was the critical error that collapsed the compounding.
            need[b.region] = b.work_cap()
    total_need = sum(need.values())
    # ENDGAME FINISH-PUSH (userbot step2, arm 1): release workers into the fist while we are army-dominant
    # late -- see the ENDGAME_FINISH flag comment. Bases closest to the ENEMY HQ are freed first (their
    # bodies reach the front fastest); the HQ entry (guard/income) is never touched; a committed wave or an
    # enemy on node 0 turns this off wholesale (survival needs untouched).
    _eg_gate = (bool(ENDGAME_FINISH) and turn >= FINISH_TURN and on_hq == 0 and not concentrate
                and len(my_warriors) >= ENDGAME_DOM_F * max(1, len(enemy_warriors)))
    BOT.endgame = _eg_gate
    # V2R4 EG_RELEASE_LATE (5.txt t174-176): while we TRAIL the enemy HQ level, releasing income workers
    # dismantles the climb bank the HP tiebreak is decided by (income 210->135, L4 missed by 112g). Defer
    # the release to the user's t190+ window; a leading/tied climb keeps the round-2 behavior unchanged.
    # Gates only the RELEASE arm -- BOT.endgame (LVL_TGT/CLIMB_LOCK/spare-cap) is untouched.
    if _eg_gate and (not bool(EG_RELEASE_LATE) or not _behind_hq or turn >= ALLIN_TURN):
        _free = FINISH_KEEP - (len(my_warriors) - total_need)
        if _free > 0:
            # HQ released LAST and only down to the guard floor -- its work_cap otherwise soaks the freed
            # bodies right back up via the 2a deficit fill (probe: 4.txt rf stayed 0, the 8-worker L5 HQ
            # re-absorbed every released body).
            def _rel_key(bb):
                return (bb.region == M.my_hq, nav.hops(bb.region, M.opp_hq))
            for _b in sorted(my_buildings, key=_rel_key):
                if _free <= 0:
                    break
                _floor = max(defenders_needed, guard_floor) if _b.region == M.my_hq else 0
                _cut = min(max(0, need[_b.region] - _floor), _free)
                need[_b.region] -= _cut
                _free -= _cut
            total_need = sum(need.values())
    # V2R6 GARRISON_HOLD (1(6) t83): a base whose CURRENT garrison decisively beats the incoming stack
    # (referee-exact: not cracked AND every attacker dies) keeps that garrison this turn -- the threat+1
    # headcount rule used to pull 5 of 7 winning defenders off an L2 base to stand at the HQ while the
    # stack walked in behind them. Holds only bodies ALREADY there (sends none -- #40 stays NO-GO);
    # on_hq / concentrate override wholesale (survival math unchanged).
    if bool(GARRISON_HOLD) and on_hq == 0 and not concentrate and enemy_warriors:
        _gh_changed = False
        for _b in my_buildings:
            if _b.region == M.my_hq or _b.region not in need:
                continue
            _gar = [w.hp for w in my_warriors if w.region == _b.region]
            if len(_gar) <= need[_b.region]:
                continue
            # per-base incoming pool (the GLOBAL largest-stack detector points at the enemy's parked
            # home mass and missed the 6-stack actually approaching -- 1(6) t83): every enemy body on
            # or within GARRISON_HOLD_R of THIS base can converge during the fight, so it all attacks.
            _atk = [w.hp for w in enemy_warriors
                    if w.region == _b.region or nav.hops(w.region, _b.region) <= GARRISON_HOLD_R]
            if len(_atk) < RUSH_MIN:
                continue
            _tur = (HQ_LEVELS if _b.type is BType.HQ else BASE_LEVELS)[_b.level].turret
            _gh = _sim_crack(_atk, _b.hp, _tur, _gar, DEF_CAP_HORIZON)
            if not _gh[0] and _gh[2] == 0:
                need[_b.region] = len(_gar)
                _gh_changed = True
        if _gh_changed:
            total_need = sum(need.values())
    # (RELIEF_ETA_BODY dispatch-side filter lives in the 2c relief branch below)

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

    # EARLY-L2 HOLD (userbot pack #3): once EARLY_L2_BASES bases stand, RESERVE the HQ L1->L2 cost (600g)
    # against further base builds/claims until the HQ actually reaches L2 -- two bracket losses ended with
    # a t200 L1 HQ because base-first spending + trains outbid the 600 every single turn. 1c (below) does
    # the upgrade itself the moment the gold is there; this just stops the fund being poached.
    _l2_hold = (HQ_LEVELS[2].upgrade_cost
                if (bool(EARLY_L2) and hq is not None and hq.level < 2
                    and len(my_bases) >= EARLY_L2_BASES) else 0)
    # ENDGAME CLIMB-LOCK (step-2b): in the endgame the HQ-level race IS the game -- hold the next HQ step
    # against every base build/claim and switch 1d base upgrades off entirely (4(1): 1400g leaked there and
    # we lost the tiebreak 354g short of L4 while the deny itself had already succeeded).
    _eg_lock = (bool(ENDGAME_CLIMB_LOCK) and _eg_gate and hq is not None and not _is_max(hq))
    _eg_hold = _next_cost(hq) if _eg_lock else 0
    # L2_FIRST_GUARD (R51, see flag block): inside our post-L2 wallet-empty window the TRAINS own the
    # wallet -- claims wait behind a small train-sized hold (window-bound; the buy itself was never held).
    if _l2f_win:
        _eg_hold += TRAIN_COST * L2F_HOLD_TRAINS

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
            # NB: the EARLY_L2 hold deliberately does NOT apply here -- a claimer ALREADY STANDING on the
            # stronghold is a sunk body; stranding it unbuilt (earning nothing) while 600g banks was the
            # ablated starvation combo (FAST dispatch + L2 hold = idle claimers, rush/mirror collapse).
            # The hold gates NEW dispatches in 2b only; an arrived claimer always converts to income.
            # V2 RUSH_BRAKE exception: while a committed rush is closing and we cannot match it, the 300g
            # IS the defense budget (g2's t11 base-68 build = the fatal spend) -- hold the build; the
            # claimer keeps standing and builds the turn the brake clears.
            # OPEN_CLAIM (R48, see flag block): in the opening a standing claimer's build bills LEAN --
            # the 300+reserve bar lost the wallet race to the 120+reserve train every turn (8(8): A2 on
            # stronghold 27 from t4, claim slipped t7 -> t16 while trains ate the fund).
            _oc_lean = (bool(OPEN_CLAIM) and turn <= OPEN_CLAIM_TMAX
                        and (S.gold - spent) >= BASE_LEVELS[1].cost + _eg_hold)
            if not _rush_brake and (can(BASE_LEVELS[1].cost + _eg_hold) or _oc_lean):
                plan_upgrade(r, BASE_LEVELS[1].cost)
                my_building_regions.add(r)  # treat as ours for the rest of this turn

    # 1c) HQ economic / defensive upgrades.
    _l2w_hold = False
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
            # [BUGFIX #4] L1->L2 also honors the climb window (symmetry with L2->L5 below): past turn 160
            # econ_ok goes permanently False (payback can't amortize), which would strand an L1 HQ forever;
            # the climb window (behind/fortress/under-massed/late) reopens it.
            want = econ_ok or _hq_climb_window               # L1->L2: cheap economic, or forced by climb window
        elif len(my_bases) >= 1 or _hq_climb_window:
            # [BUGFIX #2 HIGH] `or _hq_climb_window`: the whole L2->L5 climb (incl. its forced override) was
            # nested under `len(my_bases) >= 1`. HQ is excluded from my_bases, so if the enemy razes EVERY
            # base (len(my_bases)==0) the HQ could NEVER upgrade past its current level -- even with gold in
            # hand -- so it sat at a low level and auto-lost the tiebreak at the exact moment the fortress
            # was most needed (economy collapsing). Opening the branch when the climb window is set lets the
            # HQ keep climbing to L5 even with zero bases standing.
            # L2->L5 fortress insurance. Reaching L5 (30hp) outranks holding the 1000 heal
            # cushion -- the upgrade itself heals the HQ to full -- so the climb may dip into
            # that reserve, holding back only a lean operating float. This stops the expensive
            # L4->L5 step (3600g) from stalling forever behind the cushion and losing the
            # tiebreak by a single upgrade (HQ L4=25 < their L5=30).
            lean = GOLD_FLOOR + UPKEEP_PER_WARRIOR * (len(my_warriors) + 1)
            want = (S.gold - spent) >= (cost + lean)
            if _hq_climb_window and (S.gold - spent) >= (cost + GOLD_FLOOR):
                want = True
        # L2_WATCH (R46, see flag block): the watch clock starts the first turn the L1->L2 buy is
        # FUNDABLE; the purchase waits out the window (or an enemy train stream) while the enemy HQ
        # is also L1. Forced climbs (_hq_climb_window) and the 1a emergency heal preempt the watch.
        # RELEASE ON ANY ARMY SIGNAL (battery-measured): under a threat latch the train pipeline is
        # reserve-free anyway -- holding buys nothing while costing the fortify (hp15 + turret2). This
        # also breaks the MUTUAL-WATCH deadlock (mirror NEW-vs-NEW: both sides waiting for the other's
        # L2 while skirmish trains extend both holds -- mirror K19 5W -> 1W before this gate).
        if (bool(L2_WATCH) and M.K <= L2_WATCH_KMAX
                and hq.level == 1 and turn <= L2_WATCH_TMAX
                and _ehl0 <= 1 and on_hq == 0 and not _hq_climb_window
                and not _mg_on and not concentrate
                and not (stack_reg >= 0 and enemy_stack_sz >= 3 and _stack_advancing)
                and want and can(cost, ignore_heal_reserve=True)):
            if getattr(BOT, 'l2w_start', -1) < 0:
                BOT.l2w_start = turn
            _l2w_stream = (sum(_n for _t, _n in getattr(BOT, 'mg_tlog', [])
                               if _t > turn - MG_STREAM_WIN) >= L2_WATCH_STREAM)
            _l2w_hold = (turn - BOT.l2w_start < L2_WATCH_TURNS) or _l2w_stream
        if want and not _l2w_hold and can(cost, ignore_heal_reserve=True):
            plan_upgrade(hq.region, cost)

    # SMALL-MAP ECONOMY RACE (game 6, K11-14): the HQ tiebreak there is decided by INCOME (work_cap) -- the
    # army standoff freezes BOTH armies home, so whoever out-economies out-climbs. Forensic 6(1).txt: the pin's
    # army surplus FROZE our economy at wc7 from t60 while the enemy grew to wc11, handing it the climb (both
    # reached L3, draw). When we are NOT ahead on income in the band, deepen our BASE economy (and below, drop
    # the offensive army surplus) instead of hoarding army -- the user's "반응하면 천천히 찍으면서 HQ레벨을 올린다".
    # Vs a RUSHER we are income-AHEAD (flag off -> base/defense untouched, rush HQ-crack invariant preserved);
    # vs a turtle/reactive we out-climb on economy. The instant our income passes the enemy's, the flag flips
    # off and the pin re-engages (press the lead with army). K9 (7/8) and K15/K19 (4/5) are outside the band.
    _smallmap_econ = (WIDE_K <= M.K < WIDE_FORCE_ANCHOR and turn >= PRESSURE_TURN
                      and not _behind_hq and _my_workcap0 <= _enemy_workcap)
    # RELATIVE ECONOMY INVEST (fix #3): while OUT-ECONOMIED (income strictly behind) AND trailing on HQ level,
    # invest surplus gold in base work_cap instead of hoarding it -- compound the economy toward a higher
    # final HQ climb. The _behind_hq gate is essential: a pure ECONOMIST (turtle) also out-economies us, but
    # there we are HQ-AHEAD (we out-climb it by razing) so we must NOT match its economy race (draws a game we
    # win) -- requiring _behind_hq excludes it and keeps firing only in the real losses (income-behind AND
    # HQ-behind). All maps (relative, not K-gated); calm-state only (home_safe, no forming assault) so
    # defence/fortify outrank it under threat. Wins are income-ahead or HQ-ahead -> never fires -> untouched.
    # NB: `home_safe` is not defined until ~L1696 (after this base-upgrade section), so referencing it here
    # threw UnboundLocalError -> the bare except in decide() swallowed it and TRUNCATED the whole turn exactly
    # when this would fire (K<15, income-behind, HQ-behind). Inline home_safe's early-available terms instead
    # (on_hq/concentrate/siege_recall are all computed above); home_safe's remaining fortress term is already
    # subsumed by the `not _fortress` conjunct below, so this is exactly equivalent to the intended gate.
    _econ_invest = (bool(ECON_INVEST) and M.K < WIDE_FORCE_ANCHOR and turn >= PRESSURE_TURN
                    and _my_workcap0 < _enemy_workcap and _behind_hq
                    and on_hq == 0 and not concentrate and not siege_recall
                    and not _fortress and not _under_massed)
    # ECON-INVEST WIDE (1(4) loss): the same income-invest on WIDE maps (K>=WIDE_FORCE_ANCHOR), gated on the
    # razing-activity discriminator (not BOT.offense_engaged = we have razed the enemy NOTHING all game). That
    # is FALSE on the g4/g5 wins (razing starts ~t75) well before ECON_WIDE_TURN, so this cannot arm there ->
    # g4/g5 byte-identical. Fires on the 1(4) "base-ahead but income-behind" sprawl. _ebct computed inline (the
    # enemy_base_regs list is defined later at ~L1725; referencing it here would UnboundLocalError-truncate).
    _ebct_wide = sum(1 for _b in S.buildings if _b.side is not M.my_side and _b.type is BType.BASE)
    _econ_invest_wide = (bool(ECON_INVEST_WIDE) and M.K >= WIDE_FORCE_ANCHOR and turn >= ECON_WIDE_TURN
                         and not BOT.offense_engaged
                         and (_enemy_workcap - _my_workcap0) >= ECON_WIDE_INCOME_MARGIN
                         and len(my_bases) >= _ebct_wide + ECON_WIDE_BASE_LEAD
                         and on_hq == 0 and not concentrate and not siege_recall
                         and not _fortress and not _under_massed)

    # 1d) Base work-slot upgrades when economy supports and payback is positive.
    #     SUPPRESSED while fortifying (g3): when a real massed army is forming, every gold goes to the HQ
    #     climb + army, NOT into deepening base work-slots -- spending on bases here is exactly what left
    #     the HQ at a paper L2 while the deathball grew (the user's "기지를 짓느라 돈을 너무 써버린").
    # UNDERMASS-PRESS (latch-fix 2): that suppression only makes sense while the mass is actually PRESSING
    # us -- a stack parked on ITS OWN HQ all game latched _under_massed permanently and froze our whole base
    # economy for 60 turns (the g6 deadlock; see the flag block). Suppress only while pressing: advancing,
    # within the approach gate, on our half, or on our HQ / concentrate. UNDERMASS_PRESS=0 -> old behavior.
    # INCOME GUARD (new-g8 LOSS forensic, 2nd submission): the unlock is for CATCHING UP an income deficit
    # (g6: income-behind, gold idled to 3.7k). When our income already LEADS, the economy race is won and
    # every banked gold belongs to the HQ step that decides the tiebreak -- the unlocked 1d spent 250g at
    # t129 + 250g at t138 on L2 upgrades on a thin compact-K9 income, the L3 bank (1200) never filled, and
    # we finished L2 vs B's L3 = tiebreak LOSS in a game the pre-fix build drew. So: income-ahead -> keep
    # the old full suppression; only an income-behind under-massed state unlocks 1d.
    # V2R5 UNDERMASS_PARKFIX (5.txt t112-136): a stack PARKED on the enemy's own HQ and not advancing is
    # not a threat until it moves (the FLEE_FIX / INC_PARKFIX doctrine) -- it froze 1d for 25 turns
    # exactly while our work-cap led and the user's "중간중간 L2" window was open. Steps off / closes
    # distance -> the freeze is back the same turn.
    _um_park = (bool(UNDERMASS_PARKFIX) and stack_reg == M.opp_hq and not _stack_advancing)
    _um_pressing = (_under_massed and not _um_park
                    and (not bool(UNDERMASS_PRESS) or on_hq > 0 or concentrate
                    or _my_workcap0 > _enemy_workcap
                    or (stack_reg >= 0 and (_stack_advancing or stack_dist <= gate
                                            or stack_dist < nav.hops(stack_reg, M.opp_hq)))))
    # V2 CLIMB-HOLD (g1, see flag): while we TRAIL the enemy HQ level, base upgrades / extra claims
    # must clear the NEXT HQ STEP on top of their usual cushion -- the four 600g L2s (t86-108) raided
    # the 1200g L3 bank (gold peaked 792) and we finished the game at HQ L2 vs L5.
    _climb_hold_amt = (_next_cost(hq) if (bool(CLIMB_HOLD) and _behind_hq and hq is not None
                                          and not _is_max(hq)) else 0)
    # L2_WATCH leak guard (R46, mirror-measured): while the watch holds the L1->L2 buy, base
    # builds/claims must not poach the 600 (seed-2000 mirror: gold 923 -> 281 during the hold via a
    # claim + trains, then a from-scratch re-save pushed L2 past t70 -- the exact EARLY_L2 ablation
    # pathology). _climb_hold_amt is consumed by ALL four base-spend paths (1d/_ecush, 1f FLYWHEEL,
    # 1g PRESS_L2, 2b claim brake), so one bump covers every leak; TRAINS stay free on purpose
    # (the user's follow-train doctrine is the whole point of the watch).
    if _l2w_hold:
        _climb_hold_amt = max(_climb_hold_amt, HQ_LEVELS[2].upgrade_cost)
    # --- V2 L2-SAFE (g1, see flag): every base-upgrade loop below ordered candidates by RAW REGION
    # NUMBER -- side-asymmetric (indices run A-HQ..B-HQ, so as RIGHT the FRONTLINE sorted first: our
    # r43/54/56/65 L2s were sieged 0-20 turns after the spend, 2400g razed, A rebuilt on the rubble).
    # Fix: upgrade the SAFE REAR first (hops-to-our-HQ ascending) and never a base at/past the midline
    # (an L2 pays back over 40 turns only if it SURVIVES; a frontline L2 is a donation). Flag=0 restores
    # the exact old ordering and no skip.
    def _up_order(_bs):
        if not bool(L2_SAFE):
            return sorted(_bs, key=lambda bb: bb.region)
        return sorted(_bs, key=lambda bb: (nav.hops(bb.region, M.my_hq), bb.region))
    def _up_unsafe(bb):
        return bool(L2_SAFE) and nav.hops(bb.region, M.opp_hq) <= nav.hops(bb.region, M.my_hq)
    for b in _up_order(my_bases):
        if (b.region in upgraded_regions or _is_max(b) or not upgrade_legal(b.region) or _um_pressing
                or _eg_lock or _up_unsafe(b) or _rush_brake):
            continue
        cost = _next_cost(b)
        payback = cost / WORK_INCOME
        # On the small map, when out-economied, base income IS the win condition -- give base upgrades first
        # claim on gold (only the lean upkeep float, not the full climb-reserve cushion, is held back) so the
        # economy actually deepens instead of every gold draining into the standoff army.
        # PRESS-ECON (user: 'when AHEAD, pour into L2 to widen the turn-gold gap'): the flywheel is built by
        # upgrading bases EARLY (40-turn payback) so higher income funds a faster late climb + bigger army,
        # NOT by finding surplus above the climb (there is none -- every gold banks the L5 climb). So when we
        # OUT-EARN the enemy and are safe, give base upgrades the SAME lean GOLD_FLOOR claim the income-behind
        # econ-invest paths use -- the 1d loop is where L2 actually happens.
        _press_econ_win = (bool(PRESS_L2) and (M.K < WIDE_FORCE_ANCHOR or bool(WIDE_L2)) and turn >= PRESSURE_TURN
                           and _my_workcap0 > _enemy_workcap and on_hq == 0 and not concentrate
                           and not siege_recall and not _fortress
                           and (not _under_massed or _um_park))   # V2R5: parked stack does not veto PRESS_L2
        # RUSH_SNOWBALL L2-arm (see flag block): the freed army-gold (want_spare cap in section 3) is spent on L1->L2
        # HERE. Gated on the user's trigger -- base-ahead (rush won) + enemy counter spent (op_army low) + safe +
        # not-behind-HQ + early-mid -- so it fires when income-BEHIND-but-base-ahead (the g5 hole PRESS_L2 misses).
        _snowball_l2 = (bool(RUSH_SNOWBALL) and b.level < 2 and turn >= PRESSURE_TURN and turn <= SNOWBALL_UNTIL
                        and not _behind_hq and on_hq == 0 and not concentrate and not siege_recall and not _fortress
                        and (not _under_massed or _um_park) and len(my_bases) > _ebct_wide
                        and BOT.park_streak >= SNOWBALL_PARK_MIN
                        and max(0, sum(1 for _w in S.warriors if _w.id.side is not M.my_side) - _enemy_workcap)
                            <= SNOWBALL_EN_OP)
        _ecush = GOLD_FLOOR if (_smallmap_econ or _econ_invest or _econ_invest_wide or _press_econ_win
                                or _snowball_l2) else (reserve + 200)
        _ecush += _climb_hold_amt   # V2 CLIMB-HOLD: never raid the catch-up climb bank for a base level
        if turn + payback <= MAX_TURN and (S.gold - spent) >= (cost + _ecush):
            if can(cost):
                if plan_upgrade(b.region, cost) and PRESTAFF:
                    need[b.region] = max(need.get(b.region, 0), BASE_LEVELS[b.level + 1].work_cap)

    # 1e) STAND-UP (Pareto income compound, the user's g4/g5 "keep growing turn-gold"): upgrade a base IN PLACE
    #     to absorb warriors ALREADY STACKED on it (present > work_cap) into income (+15/turn each up to the new
    #     cap). No march, no claimer, no garrison change -- the bodies are already there. Gated to spend ONLY
    #     gold that is provably surplus to the WHOLE remaining HQ climb-to-L5, so it can never delay the L4->L5
    #     that decides the tiebreak (= the forbidden draw regression). See STANDUP notes at the flag.
    if STANDUP:
        # remaining gold the HQ still needs to finish climbing to L5 (0 once maxed) -- the load-bearing reserve
        # this lever must never touch. Summed straight from the cost table (upgrade_cost of each level above ours).
        _climb_keep = 0
        if hq is not None and not _is_max(hq):
            _climb_keep = sum(HQ_LEVELS[lv].upgrade_cost for lv in range(hq.level + 1, HQ_MAX_LEVEL + 1))
        # warriors physically standing on each of our regions right now (referee income basis)
        _present_ct: dict[int, int] = defaultdict(int)
        for _w in my_warriors:
            _present_ct[_w.region] += 1
        for b in _up_order(my_bases):
            if (b.region in upgraded_regions or _is_max(b) or not upgrade_legal(b.region)
                    or _under_massed or concentrate or siege_recall or on_hq > 0
                    or _up_unsafe(b) or _rush_brake):
                continue
            # Pareto precondition: bodies ALREADY stacked above this base's current work_cap. Upgrading converts
            # THOSE present-but-idle warriors to income; without a real stack we'd just buy an empty slot (a gold
            # trade, not Pareto) -- so require a genuine surplus already sitting here.
            if _present_ct.get(b.region, 0) - b.work_cap() < STANDUP_MIN_SURPLUS:
                continue
            cost = _next_cost(b)
            # STRUCTURAL SAFETY BAR: after paying for this base we STILL hold the full remaining HQ climb-to-L5
            # (_climb_keep) plus an operating float. Pre-L5 in g4/g5 the bank never clears (climb_keep>=3600 for the
            # last step and the bank is spent the instant it reaches it) -> byte-identical. The float we hold is:
            #   * the FULL reserve (incl. the 1000 HEAL cushion) whenever the HQ is still CLIMBING or DAMAGED or
            #     under any pressure -- so the emergency-repair bank is never raided while the game is still live;
            #   * only the LEAN operating float (reserve - HEAL_RESERVE) once the HQ is MAXED, at FULL hp, and no
            #     enemy stands on it -- then the 1000 heal cushion is provably idle (nothing left to climb, nothing
            #     to repair, no siege), so spending it to convert already-present idle bodies to income is pure
            #     Pareto. This relaxation is guarded by _is_max(hq) which is FALSE for every pre-L5 turn in g4/g5,
            #     so the pre-L5 command stream stays byte-identical; it only ever loosens the DECIDED endgame.
            _hq_settled = (hq is not None and _is_max(hq) and hq.hp >= hq.current_hp() and on_hq == 0)
            _keep = _climb_keep + reserve - (HEAL_RESERVE if (_hq_settled and reserve >= HEAL_RESERVE) else 0)
            if (S.gold - spent) - cost >= _keep:
                if can(cost, ignore_heal_reserve=_hq_settled):
                    if plan_upgrade(b.region, cost) and PRESTAFF:
                        need[b.region] = max(need.get(b.region, 0), BASE_LEVELS[b.level + 1].work_cap)

    # 1f) FLYWHEEL (compact ladder loss 1(2)): while we HOLD the military initiative (offense_engaged) but are
    #     NOT ahead on income, convert surplus gold into L1->L2 base upgrades so turn-gold grows and funds a
    #     bigger sustained army -- the compounding cycle the loss lacked. L2-CAPPED (the efficient 40-turn tier;
    #     no gold sunk into inefficient L3). K-gated to compact (M.K < WIDE_FORCE_ANCHOR) so g4/g5 (wide) stay
    #     byte-identical; the income-not-ahead conjunct keeps the SAME-band g7/g8 wins (income-ahead) inert.
    _flywheel = (bool(FLYWHEEL) and (M.K < WIDE_FORCE_ANCHOR or bool(WIDE_L2)) and turn >= PRESSURE_TURN
                 and BOT.offense_engaged and _my_workcap0 <= _enemy_workcap and _behind_hq
                 and on_hq == 0 and not concentrate and not siege_recall
                 and not _fortress and not _under_massed)
    if _flywheel:
        for b in _up_order(my_bases):
            if (b.region in upgraded_regions or b.level >= 2 or not upgrade_legal(b.region)
                    or _up_unsafe(b) or _rush_brake):
                continue   # L1 -> L2 ONLY (turn-gold sweet spot); leave deeper L3 to the normal 1d gate
            cost = _next_cost(b)
            if turn + cost / WORK_INCOME <= MAX_TURN and (S.gold - spent) >= cost + reserve + FLYWHEEL_KEEP + _climb_hold_amt:
                if can(cost):
                    if plan_upgrade(b.region, cost) and PRESTAFF:
                        need[b.region] = max(need.get(b.region, 0), BASE_LEVELS[b.level + 1].work_cap)

    # 1g) PRESS-L2 (the user's "유리할 때 L2로 격차를 더 벌려라"): when we OUT-EARN the enemy (income ahead),
    #     spend surplus gold on MORE L1->L2 upgrades to WIDEN the turn-gold lead -> bigger army -> more pressure
    #     (the 1(2) winner's engine, applied when WE lead). L2-capped. The income-AHEAD gate keeps g4/g5 (which
    #     win income-BEHIND via razing) inert -> no #26 regression; surplus-only (>= reserve) never starves
    #     army/climb. Complements FLYWHEEL (behind/even case); together they prefer L2 whenever gold is surplus.
    _press_l2 = (bool(PRESS_L2) and (M.K < WIDE_FORCE_ANCHOR or bool(WIDE_L2)) and turn >= PRESSURE_TURN
                 and _my_workcap0 > _enemy_workcap
                 and on_hq == 0 and not concentrate and not siege_recall
                 and not _fortress and not _under_massed)
    if _press_l2:
        for b in _up_order(my_bases):
            if (b.region in upgraded_regions or b.level >= 2 or not upgrade_legal(b.region)
                    or _up_unsafe(b) or _rush_brake):
                continue   # L1 -> L2 ONLY (efficient turn-gold tier; never inefficient L3)
            cost = _next_cost(b)
            if turn + cost / WORK_INCOME <= MAX_TURN and (S.gold - spent) >= cost + reserve + PRESS_L2_KEEP + _climb_hold_amt:
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

    def order_move(w: Warrior, target: int, hold: int = 0, lean: bool = False) -> bool:
        # hold: extra reserve this bill must clear (V2R7 L2_MARCH_HOLD -- discretionary raid moves only;
        # hold=0 for every other caller = byte-identical billing).
        # lean (R43 CHIP_LEAN_FINAL): bill against the reserve WITHOUT the idle heal cushion -- the
        # STANDUP "_hq_settled" doctrine (maxed + full-hp HQ => the 1000g repair bank is provably idle).
        # Only the final-chip dispatch passes lean=True; every other caller is byte-identical.
        nonlocal spent
        if w.id in assigned or w.state is not WState.STATIONARY:
            return False
        if target == w.region:                       # avoid wasted 10g + stuck-MOVING bug
            return False
        if not nav.reachable(w.region, target):
            return False
        # ROUTE_AVOID (R62, 1(70) t85; user: "이동 경로에 적 기지가 있어 ... 기지 사이에 적 기지가
        # 있다면 아군 기지를 찍으면서 진행"): the referee routes by ITS shortest path and its tie-break
        # happily steps ONTO an enemy building in transit -- 35->30 went via enemy base 29 while an
        # EQUAL-length route via 24 existed; three bodies were ground down by the turret mid-march
        # (and it recurred all game). When the referee's path would cross an enemy building, issue the
        # march one SAFE hop at a time (enemy-building-barred dijkstra, destination itself exempt so
        # deliberate assaults are untouched); each arrival re-enters STATIONARY and re-routes, so the
        # order reverts to the plain multi-hop march the moment the remaining path is clean.
        if bool(ROUTE_AVOID):
            _ra_n = w.region
            _ra_cross = False
            for _ in range(64):
                _ra_n = nav.next_hop(_ra_n, target)
                if _ra_n < 0 or _ra_n == target:
                    break
                _rab = S.find_building(_ra_n)
                if _rab is not None and _rab.side is not me:
                    _ra_cross = True
                    break
            if _ra_cross:
                _ra_bar = {b.region for b in S.buildings
                           if b.side is not me and b.region != target}
                _ra_dist = {w.region: 0.0}
                _ra_pq = [(0.0, w.region, -1)]
                _ra_first = -1
                while _ra_pq:
                    _rd, _ru, _rf = heapq.heappop(_ra_pq)
                    if _rd > _ra_dist.get(_ru, math.inf):
                        continue
                    if _ru == target:
                        _ra_first = _rf
                        break
                    for _rv in M.adj[_ru]:
                        if _rv in _ra_bar:
                            continue
                        _rnd = _rd + math.ceil(math.hypot(M.x[_ru] - M.x[_rv],
                                                          M.y[_ru] - M.y[_rv]))
                        if _rnd < _ra_dist.get(_rv, math.inf):
                            _ra_dist[_rv] = _rnd
                            heapq.heappush(_ra_pq, (_rnd, _rv, _rv if _rf == -1 else _rf))
                if _ra_first >= 0 and _ra_first != w.region:
                    target = _ra_first           # one safe hop; re-routes on arrival
        dest_b = S.find_building(target)
        cost = 0 if (dest_b is not None and dest_b.side is me) else MOVE_COST
        if cost > 0 and not can(cost + hold, ignore_heal_reserve=lean):
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
    # WORKER_SPARE (3(3); user: "막기 충분한 인원만 보내고 노동자는 안 보내면 안 되나"): when hq_pressure
    # releases the base WORKERS into the pool (a real siege -- survival still outranks income), tag the
    # EARNING ones (within their building's work_cap) so the picker below prefers a true spare when one
    # is about-as-close. Quantity is untouched: workers still go whenever the spares cannot cover.
    _earning_ids: set = set()

    def keep_earn(r: int) -> int:
        _b = S.find_building(r)
        return _b.work_cap() if (_b is not None and _b.side is me) else 0

    # STRAND_RECALL (R81, see flag block): track how long each unbuilt claim stronghold has had a PARKED claimer;
    # a body stranded STRAND_TURNS+ turns (build perpetually out-bid: gold < cost yet we HAVE income, so the
    # zero-income release arm never fires) is dead weight. Mark it _skip_build so the classifier's claim-park elif
    # no longer matches -> the body falls to the else and is RELEASED to surplus (visible to defense + raid again),
    # and the 2b dispatch skips it (no re-park). The tracker persists while a body stands (clock does not reset),
    # so the release holds; it clears the moment the body leaves or a base is built (region drops from claim_stand).
    if bool(STRAND_RECALL):
        _cs_new: dict = {}
        _strand_skip: set = set()
        for _sr in stationary_at:
            if (_sr in BOT.claim_set and _sr != M.my_hq and _sr not in enemy_at
                    and S.find_building(_sr) is None):
                _since = BOT.claim_stand.get(_sr, turn)
                _cs_new[_sr] = _since
                if turn - _since >= STRAND_TURNS:
                    _strand_skip.add(_sr)
        BOT.claim_stand = _cs_new
        if _strand_skip:
            _skip_build = frozenset(_skip_build) | _strand_skip
    for r, ws in stationary_at.items():
        # GARRISON_STAND (R52, see flag block): a body on OUR OWN building with an enemy ON or ADJACENT
        # to it IS the fight -- the hold rule counts defenders PRESENT, and 1(56) lost base 97 because
        # the flapping threat-fill poached its 5 sitters on the exact siege turns. Pin them ONLY when
        # the stand actually WINS (sitters + turret >= contact enemies -- 56: 5+1 vs 6 holds); pinning
        # a LOSING garrison froze bodies into doomed fights and blocked the HQ muster (first-draft
        # unconditional pin: waverush hard gate collapsed 0->17 cracks, isolated to this flag). A losing
        # stand keeps the legacy redeploy behavior; hq_pressure still overrides everything (HQ survival
        # outranks a base -- the rush-safety rule).
        # NEVER the HQ (r != M.my_hq): the HQ keep is the guard floor's job, and pinning HQ sitters
        # froze the entire reserve out of the surplus pool whenever a stream touched node 0 -- the
        # probe showed every waverush-s2000 pin was r=0, and the muster paralysis cracked the HQ.
        if (bool(GARRISON_STAND) and not hq_pressure and r != M.my_hq
                and r in my_building_regions):
            _gs_thr = sum(1 for e in enemy_warriors
                          if e.region == r or nav.hops(e.region, r) <= 1)
            if _gs_thr > 0 and len(ws) + _home_turret(S, M, me, r) >= _gs_thr:
                continue
        if r in need:
            keep = 0 if (hq_pressure and r != M.my_hq) else need[r]
            for i, w in enumerate(ws):
                if i >= keep:
                    if bool(WORKER_SPARE) and i < keep_earn(r):
                        _earning_ids.add(w.id)
                    surplus.append(w)
        elif (bool(SIEGE_BODY_HOLD) and not (siege_recall or concentrate or (_relief and not _relief_small))
                and (_sbh := S.find_building(r)) is not None and _sbh.side is not me
                and _sbh.hp < _sbh.current_hp()):
            pass  # V2R6: mid-siege bodies (standing on a DAMAGED enemy building) are not poachable --
            #       the referee auto-sieges standers; 1(4) abandoned a 2-hp base twice to claim/fill
            #       poaching. Defense still preempts wholesale (the not(...) guard above).
        elif (r in BOT.claim_set and S.find_building(r) is None
                and r not in _skip_build and r not in enemy_at):
            # V2R6 CLAIM_PARK_RELEASE (1(2)/1(5)): ONE body claims; the rest are surplus (the old
            # unconditional park idled a 6-body raid stack 22 turns on a razed contested stronghold,
            # and starved 1(5)'s sole survivor into hunger). The last body is also released when a
            # wave commits (survival outranks a waiting claim) or when the build can never fund
            # (gold below cost with ZERO staffed income = the 1(5) freeze).
            if bool(CLAIM_PARK_RELEASE):
                if (concentrate or on_hq > 0
                        or ((S.gold - spent) < BASE_LEVELS[1].cost
                            and not any(_w.region in my_building_regions for _w in my_warriors))):
                    surplus.extend(ws)
                else:
                    surplus.extend(ws[1:])
            # flag off: a claimer waiting to build (kept; building handled above / next turns)
        else:
            surplus.extend(ws)   # stranded warriors -> reassignable

    def nearest_surplus(target: int) -> Warrior | None:
        best = None
        best_h = 1 << 30
        for w in surplus:
            if w.id in assigned:
                continue
            # PRESS_HOLD (R68, see flag): a deep-committed body is not homeward supply outside real
            # emergencies -- leave it to the raid machinery that is already marching it (the 2a fill
            # runs FIRST each turn, so without this test code ORDER, not doctrine, owned the wave).
            if (bool(PRESS_HOLD) and on_hq == 0 and not siege_recall and not concentrate
                    and BOT.press_log.get(w.id, -(1 << 30)) >= turn - PRESS_TTL
                    and nav.hops(w.region, target) > PRESS_FAR):
                _ph_eb = min((nav.hops(w.region, _b.region) for _b in S.buildings
                              if _b.side is not me), default=1 << 30)
                if _ph_eb + 1 < nav.hops(w.region, target):
                    continue
            # WORKER_SPARE: an EARNING worker carries a small distance penalty, so an about-as-close
            # true spare is picked first and the income keeps flowing; the worker still goes whenever
            # it is the only body that can arrive in time (quantity/urgency untouched -> rush-safe).
            h = nav.hops(w.region, target) + (WORKER_SPARE_BIAS if w.id in _earning_ids else 0)
            if h < best_h:
                best_h = h
                best = w
        return best

    # CORE_PREPOSITION (see flag block): while base-ahead in the opening with an enemy mobile pack nearing our
    # territory, hold the idle reserve ON the reachable CORE base nearest that pack instead of deep on the HQ
    # (1(32): 3 idle bodies hoarded on the HQ hop-5 from the fight while core 57/54 needed only 1/3 defenders).
    # Placement-only: total_need was summed BEFORE this bump, so training targets are untouched; the fill below
    # still serves the HQ guard FIRST (sort order) -> the HQ garrison is never starved by this hold.
    if (bool(CORE_PREPOSITION) and turn <= ACG_TURN_MAX and on_hq == 0
            and not concentrate and not siege_recall and not _fort_hold
            and len(my_bases) >= _ebct_wide + 1):
        _cp_my_regs = [_b.region for _b in my_buildings]
        _cp_fwd = [_ew for _ew in enemy_warriors
                   if S.find_building(_ew.region) is None
                   and min(nav.hops(_ew.region, _br) for _br in _cp_my_regs) <= ACG_RANGE]
        if len(_cp_fwd) >= ACG_MIN:
            # vanguard = the forward enemy body nearest any of our buildings; core = our bases within
            # CORE_HOP_MAX of the HQ (the outermost base is indefensible-as-built -> NOT reinforced)
            _cp_van = min(_cp_fwd,
                          key=lambda _ew: min(nav.hops(_ew.region, _br) for _br in _cp_my_regs))
            _cp_core = [_b for _b in my_bases if nav.hops(_b.region, M.my_hq) <= CORE_HOP_MAX]
            if _cp_core:
                _cp_tgt = min(_cp_core,
                              key=lambda _b: (nav.hops(_cp_van.region, _b.region), _b.region))
                _cp_hold = max(0, len(_cp_fwd) - BASE_LEVELS[_cp_tgt.level].turret)
                if _cp_hold > 0:
                    need[_cp_tgt.region] = max(need.get(_cp_tgt.region, 0), _cp_hold)
    # THREAT_FILL_FWD (1(36) forensic, see flag block): the threat+1 garrison demand parks at node 0 even
    # when the spiking stack's nearest own building is a forward BASE -- at t99 it confiscated A26-29 (ONE
    # hop from the stack's target, base 26) three hops backward to an HQ that was never attacked. When no
    # relief lever owns the turn, the stack is a real threat-latched group, and our REACHABLE force + the
    # target base's turret beats it (+1), route the demand to that base's turret ground instead (need[HQ]
    # falls back to the guard floor). Placement-only: defenders_needed is untouched (training identical);
    # the 2a fill below serves the HQ first by sort order, then stations the nearest bodies on the base.
    if (bool(THREAT_FILL_FWD) and threat >= THREAT_MIN and on_hq == 0
            and not concentrate and not siege_recall and not _fort_hold and not _relief
            and stack_reg >= 0 and THREAT_MIN <= enemy_stack_sz < WAVE_STACK_MIN
            and nav.hops(stack_reg, M.my_hq) <= THREAT_RANGE
            and nav.hops(stack_reg, M.my_hq) <= nav.hops(stack_reg, M.opp_hq)):
        _tf_tt = min(my_building_regions, key=lambda r: nav.hops(stack_reg, r))
        if _tf_tt != M.my_hq and _tf_tt in need:
            _tf_eta = max(1, nav.hops(stack_reg, _tf_tt))
            _tf_reach = sum(1 for w in my_warriors if nav.hops(w.region, _tf_tt) <= _tf_eta)
            # FILL_REACH_SURPLUS (R50, see flag): honest supply -- on-target + inbound + deliverable spares.
            if bool(FILL_REACH_SURPLUS):
                _tf_reach = (len(stationary_at.get(_tf_tt, [])) + incoming.get(_tf_tt, 0)
                             + sum(1 for w in surplus if w.id not in assigned
                                   and nav.hops(w.region, _tf_tt) <= _tf_eta))
            if _tf_reach + _home_turret(S, M, me, _tf_tt) >= enemy_stack_sz + 1:
                need[_tf_tt] = max(need[_tf_tt], min(len(my_warriors), enemy_stack_sz + 1))
                if M.my_hq in need and hq is not None:
                    need[M.my_hq] = max(hq.work_cap(), guard_floor)
    # PREDICT_STAGE (R42, see flag block): heading-inferred base defense. Placement-only need[] bump
    # (total_need already summed -> training identical); 2a fills the HQ guard first, then stations the
    # nearest bodies on the predicted target's turret ground -- BEFORE the group lands, which is the whole
    # point (reactive relief arrives one turn late on 2-hop geometry, the 1(50) base-43 death).
    if (bool(PREDICT_STAGE) and on_hq == 0
            and not concentrate and not siege_recall and not _fort_hold and not _relief
            and my_bases):
        _ps_inc: dict[int, list] = {}
        for _ek, _eh in BOT.en_hist.items():
            if len(_eh) < 3:
                continue
            _r2, _r1, _r0 = _eh
            _cands = [_b for _b in my_bases
                      if nav.hops(_r1, _b.region) == nav.hops(_r2, _b.region) - 1
                      and nav.hops(_r0, _b.region) == nav.hops(_r1, _b.region) - 1]
            if not _cands:
                continue
            _b0 = min(_cands, key=lambda _b: (nav.hops(_r0, _b.region), _b.region))
            _pe0 = nav.hops(_r0, _b0.region)
            if 1 <= _pe0 <= PRED_HORIZON:
                _ps_inc.setdefault(_b0.region, []).append(_pe0)
        for _pr in sorted(_ps_inc.keys()):
            _petas = _ps_inc[_pr]
            if len(_petas) < PRED_MIN or _pr not in need:
                continue
            _pe = min(_petas)                            # earliest arrival = the hold deadline
            _ptur = _home_turret(S, M, me, _pr)
            # PS_TTL (R58, 1(64) t32; user: "32턴에 이미 공격하러 오는걸 알아야 -- 가까운 밑에 기지
            # 가용인원으로 충분히 막았다"): the heading inference DID fire on t32 (three-hop beeline,
            # five bodies, ETA 1) but the reach window ended at the group's ARRIVAL -- base 37's two
            # sitters + turret 2 < 5+1 and the two 2-hop bodies at base 36 were invisible to the bar.
            # The real deadline is the base's FALL: arrival + ceil(hp / worst-case net siege) more
            # turns (defenders assumed dead -> attackers - turret, the conservative fastest fall; the
            # referee moves bodies before the siege tick, so a fall-turn arrival still blunts it).
            # t32 arithmetic: deadline 1+2=3 hops -> reach 5 + turret 2 >= 6 -> stage fires, the hold
            # rule zeroes the siege, base 37 stands.
            _ps_dl = _pe
            # SUBWAVE band only (REACH_WIN's proven rule: the kind of fight picks the doctrine --
            # subwave = reach math, WAVE = staging/concentrate own it). Unbanded, the widened window
            # re-staged the waverush stream's defense and cracked the K9 hard gate (1 HQ crack).
            _ps_tr = sum(_n for _t, _n in getattr(BOT, 'ph_tlog', []) if _t > turn - RAIDPH_WIN)
            if (bool(PS_TTL) and len(_petas) < WAVE_STACK_MIN
                    and _ps_tr < RAIDPH_TRAINS):
                # ... and only vs a SLOW producer: the waverush stream (4+ trains/8t, RAID_PHANTOM's
                # own evidence bar, state updated unconditionally) re-feeds the fight faster than any
                # pre-stage holds -- unbanded, the widened window re-staged that defense and cracked
                # the K9 hard gate (its waves ARE 5-body subwaves; mg_on could not discriminate --
                # 1(64)'s precise creeper trips MIL_GAMBIT too but trains only 2-3/8t). A one-shot
                # expedition is exactly the fight a computed pre-stage wins.
                _psb = S.find_building(_pr)
                if _psb is not None and len(_petas) > _ptur:
                    _ps_dl = _pe + math.ceil(_psb.hp / (len(_petas) - _ptur))
            _preach3 = sum(1 for w in my_warriors if nav.hops(w.region, _pr) <= _ps_dl)
            # FILL_REACH_SURPLUS (R50, see flag): honest supply -- on-target + inbound + deliverable spares.
            if bool(FILL_REACH_SURPLUS):
                _preach3 = (len(stationary_at.get(_pr, [])) + incoming.get(_pr, 0)
                            + sum(1 for w in surplus if w.id not in assigned
                                  and nav.hops(w.region, _pr) <= _pe))
            # PS_TTL two-stage hold (waverush s2010 crack forensic): the fall-deadline window counts
            # bodies that land AFTER the group does, but the hold arithmetic treated them as massed --
            # a zero-sitter base is stormed on arrival and the trickle is eaten piecemeal (the pull fed
            # 3 bodies/cycle into a losing stand every 21-turn wave). Stage 1: what is ON the ground by
            # the group's ARRIVAL must survive the landing (>= half the group with the turret). Stage 2:
            # the fall-deadline muster must win outright. 1(64): 5>=3 and 9>=6 both hold; the waverush
            # bait base starts empty -> stage 1 fails -> silent.
            _ps_ok = _preach3 + _ptur >= len(_petas) + PRED_MARGIN
            if _ps_ok and bool(PS_TTL) and _ps_dl > _pe:
                _preach_pe = sum(1 for w in my_warriors if nav.hops(w.region, _pr) <= _pe)
                _ps_ok = _preach_pe + _ptur >= math.ceil(len(_petas) / 2)
            if _ps_ok:
                need[_pr] = max(need[_pr],
                                min(len(my_warriors), len(_petas) + PRED_MARGIN - _ptur))
                # PS_TTL delivery (R58, 1(64) t32): the staffing pool was assembled ABOVE this bump,
                # so every nearby body is a neighbor-base sitter and the 2a fill has nothing to send
                # (measured: need[37] raised to 5, zero orders moved, the base fell two turns later).
                # Pull the deficit from neighbor-base sitters that reach within the fall deadline --
                # NEIGHBOR_RELIEF's proven shape: episode throttle (bounded pull + cooldown), one
                # earner always stays home, and a base with contact enemies keeps its own stand
                # (GARRISON_STAND owns that fight).
                if (bool(PS_TTL) and len(_petas) < WAVE_STACK_MIN
                        and _ps_tr < RAIDPH_TRAINS):
                    _pd = (need[_pr] - len(stationary_at.get(_pr, []))
                           - incoming.get(_pr, 0))
                    if _pd > 0 and turn - getattr(BOT, 'ps_pull_t', -99) >= PS_PULL_COOLDOWN:
                        _pcs = []
                        for _nr2, _nws in stationary_at.items():
                            if (_nr2 == _pr or _nr2 == M.my_hq
                                    or _nr2 not in my_building_regions
                                    or not (1 <= nav.hops(_nr2, _pr) <= _ps_dl)
                                    or any(e.region == _nr2 or nav.hops(e.region, _nr2) <= 1
                                           for e in enemy_warriors)):
                                continue
                            _pcs.extend(_nws[1:])
                        if _pcs:
                            BOT.ps_pull_t = turn
                            _pcs.sort(key=lambda w: nav.hops(w.region, _pr))
                            _pn = 0
                            for _w in _pcs:
                                if _pn >= min(_pd, PS_PULL_MAX):
                                    break
                                if order_move(_w, _pr):
                                    incoming[_pr] = incoming.get(_pr, 0) + 1
                                    _pn += 1
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
    _cw_out = 0
    for w in my_warriors:
        if w.state is WState.MOVING and w.target in BOT.claim_set:
            handled_targets.add(w.target)
            _cw_out += 1
        if w.region in BOT.claim_set:
            handled_targets.add(w.region)
            if S.find_building(w.region) is None:
                _cw_out += 1                     # parked claimer waiting on an unbuilt stronghold
    # 2b') RACE_TIE (R17, see flag block): BEFORE the center-last claim order runs, PROMOTE one genuinely-
    # contested CENTER stronghold (dm<=do<=dm+RACE_TIE_REACH -- we are as-close-or-closer AND the enemy is ~
    # equidistant) to be claimed FIRST, so we plant before the enemy sprints its opening worker there (the
    # dominant 6/8 bracket-loss mode: enemy BUILDS the center on arrival, past R16's bare-reservation reach).
    # Pure expansion: a lone claimer to an unclaimed/unbuilt tie on OUR-or-equal side (dm<=do STRICT, never the
    # enemy half). Opening-only, one race-claim/turn, affordable+spare gated, and ONLY while NOT base-ahead
    # (len(my_bases)<=_ebct_wide) so a winning short-center map (1(4)) never over-extends -> center-last preserved.
    # `not siege_recall and not _fort_hold` (adversarial review, same CONFIRMED-HIGH class as CONTEST_CLAIM's
    # guard below): _rush_brake only covers t<=40 and concentrate arms only at return-ETA+3, so a t41-59 delayed
    # all-in trips siege_recall (range 9) while both stay False -- without this term RACE_TIE would march a lone
    # surplus claimer un-recallably toward the midline while siege_recall is pulling everyone home (thinning the
    # knife-edge HQ defense by one body). These two terms are home_safe's early-available components.
    # NARROW_NEAR (R65, see flag): one-shot opening-geometry latch. Decided on the FIRST decide() call
    # (nothing claimed yet -> a pure map read), never recomputed (R64 lesson: a boundary signal that a
    # decision stands on gets a latch, or the decision flips mid-flight).
    if bool(NARROW_NEAR) and BOT.nn_seal < 0:
        _nn = 0
        if NN_K_LO <= M.K <= NN_K_HI:
            for _ns in M.strongholds:
                if (S.find_building(_ns) is None and _ns not in enemy_at
                        and nav.hops(_ns, M.my_hq) <= NN_HOPS
                        and nav.hops(_ns, M.my_hq) < nav.hops(_ns, M.opp_hq)):
                    _nn += 1
        BOT.nn_seal = 1 if _nn >= NN_MIN else 0
    if (bool(RACE_TIE) and turn < RACE_TIE_TURN and not concentrate and not _rush_brake
            and not siege_recall and not _fort_hold and len(my_bases) <= _ebct_wide
            and BOT.nn_seal != 1):
        _rt_best = None
        _rt_bd = 1 << 30
        for s in BOT.claim_order:
            if (s in handled_targets or s in enemy_at or s in _skip_build
                    or S.find_building(s) is not None):
                continue
            _rt_dm = nav.hops(s, M.my_hq)
            _rt_do = nav.hops(s, M.opp_hq)
            if _rt_dm <= _rt_do <= _rt_dm + RACE_TIE_REACH and _rt_dm < _rt_bd:
                _rt_bd = _rt_dm
                _rt_best = s
        if _rt_best is not None and (S.gold - spent) >= BASE_LEVELS[1].cost - FAST_EXPAND_LEAD:
            _rt_w = nearest_surplus(_rt_best)
            _rt_ok = _rt_w is not None
            if _rt_ok and bool(RACE_TIE_ETA):
                # ETA race gate (see RACE_TIE_ETA flag): only race a center we can actually WIN. Our arrival ETA vs
                # the enemy's earliest BUILD ETA (enemy plants on arrival -> nearest enemy body's hops). A race we
                # arrive too late for marches a lone body un-recallably into a just-built turret; cede it to the
                # normal center-last order instead. default huge => no enemy near => uncontested race, always send.
                _rt_en_eta = min((nav.hops(w.region, _rt_best) for w in enemy_warriors), default=1 << 30)
                _rt_ok = nav.hops(_rt_w.region, _rt_best) <= _rt_en_eta + RACE_TIE_ETA_MARGIN
            if _rt_ok and order_move(_rt_w, _rt_best):
                handled_targets.add(_rt_best)

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
    # EXPAND_AHEAD (8(2).txt, see flag): base-behind + unit-ahead + home_safe -> race the claimable contested
    # strongholds our over-training left un-taken. Computed here so the claim brake below can drop to GOLD_FLOOR.
    _ea_en_bases = sum(1 for b in S.buildings if b.side is not me and b.type is BType.BASE)
    _expand_ahead = (bool(EXPAND_AHEAD) and on_hq == 0 and not siege_recall and not _fort_hold
                     and len(my_bases) < _ea_en_bases
                     and len(my_warriors) >= len(enemy_warriors) + EXPAND_AHEAD_MARGIN)
    # AVAIL_CLAIM_GATE (see flag block): while base-ahead in the opening, do not scatter surplus below the enemy's
    # FORWARD mobile army + margin -- keep a reserve home/near-core to meet the +1-lead rush before it concentrates.
    # Signal = enemy bodies OFF their buildings AND within ACG_RANGE hops of one of OUR buildings (a rush approaching
    # a base, read by proximity to the BASE not to our HQ -- a forward-base rush never nears our HQ until too late).
    _acg_my_regs = [_b.region for _b in my_buildings]
    _en_fwd_mob = sum(1 for _ew in enemy_warriors
                      if S.find_building(_ew.region) is None and _acg_my_regs
                      and min(nav.hops(_ew.region, _br) for _br in _acg_my_regs) <= ACG_RANGE)
    _acg_pool = sum(1 for _sw in surplus if _sw.id not in assigned)
    _acg_active = (bool(AVAIL_CLAIM_GATE) and turn <= ACG_TURN_MAX
                   and len(my_bases) >= _ebct_wide + 1
                   and on_hq == 0 and not concentrate and not siege_recall and not _fort_hold
                   and _en_fwd_mob >= ACG_MIN)
    # POST_WAVE_HOLD (see flag block): for a few turns after a committed wave clears, bleed the claim dispatch
    # to 1/turn so the freed surplus is not dumped out in a single turn (1(30) t68: 3 claimers at once).
    _pwh_hold = (bool(POST_WAVE_HOLD) and turn - BOT.wave_cleared_turn <= POST_WAVE_TURNS)
    # MIL_GAMBIT (see flag block): while an army-lead gambit is latched, NEW claim dispatch is frozen --
    # the 300g/claim is the exact misallocation the detector caught (2b only; an arrived claimer still
    # converts in 1b per the idle-claimer ablation lesson above it). A safety-gated reclaim variant was
    # tried and measured net-negative in combination (crack seeds never had the 300g anyway).
    if turn < ECON_PAYBACK_CUTOFF and not concentrate and not _rush_brake and not _mg_hold:
        dispatched = 0
        # CLAIM_WALLET (R60, 1(67) t46-47; user: "턴당 골드를 생각하면 절대 전부를 지을 수 없는데 많아야
        # 2마리"): the per-turn cap lets consecutive turns stack OUTSTANDING claimers with no wallet
        # check -- 5 bodies scattered to 5 strongholds on a 2-base income (only 97/77 ever funded), and
        # the wave that followed walked through the thinned home. Cap in-flight + parked + this turn's
        # dispatch at what the wallet can foreseeably FUND (bases affordable now, +1 for income en
        # route). EXPAND_AHEAD keeps its own doctrine (standing on a contested stronghold blocks the
        # enemy build -- worth it unfunded).
        # Ablation history: an instant-wallet cap on ALL claims cost turtle-K19 its first loss ever
        # (throttled the normal FAST_EXPAND rhythm); an arrival-wallet cap still bled my-bot K19.
        # The 1(67) probe showed EVERY scattered claimer left under _expand_ahead (its GOLD_FLOOR
        # brake is the only path that dispatches with no wallet check at all -- 11 unfunded bodies
        # by t52). So the cap binds EXACTLY that path: while EXPAND_AHEAD is live, outstanding +
        # this-turn claimers are bounded by the arrival wallet, floor CW_EA_CAP (a standing blocker
        # is worth it unfunded, but "많아야 2마리"). Ordinary claims keep their proven brakes untouched.
        _cw_inc = sum(WORK_INCOME * min(len(stationary_at.get(_b.region, [])), _b.work_cap())
                      for _b in my_buildings)
        _cw_cap = max(CW_EA_CAP,
                      (S.gold - spent + _cw_inc * CW_HORIZON) // BASE_LEVELS[1].cost + 1)
        # R105 EXPAND_CAP (see flag): past the opening, when we are NOT behind on bases (favorable), expand
        # GRADUALLY -- cap the per-turn dispatch so the surplus is not fanned out to every stronghold at once.
        _ecap_max = (EXPAND_CAP_MAX if (bool(EXPAND_CAP) and turn >= EXPAND_CAP_TURN
                                        and len(my_bases) >= _ea_en_bases) else MAX_CLAIMERS)
        for s in BOT.claim_order:
            if dispatched >= (1 if _pwh_hold else _ecap_max):
                break
            if (bool(CLAIM_WALLET) and _expand_ahead
                    and _cw_out + dispatched >= _cw_cap):
                break
            if _acg_active and (_acg_pool - (dispatched + 1)) < _en_fwd_mob + ACG_MARGIN:
                break                                   # keep the reserve home to meet the forward rush (over-expansion restraint)
            if _mxa:
                break                                   # R76 MIDEXPAND_ARM: mid-game avail-deficit -- stop expanding, the freed gold arms the army
            if s in handled_targets or s in enemy_at or s in _skip_build:   # ours/incoming, contested, or (late) razed-enemy land to leave empty
                continue
            # V2R6 CLAIM_SKIP_BUILT (1(4) t55): an ENEMY building stands there -- 1b can never build on it
            # (find_building()==None required), so the claimer only feeds the turret. Ours are already in
            # handled_targets, so this skips exactly the enemy-built strongholds.
            if bool(CLAIM_SKIP_BUILT) and S.find_building(s) is not None:
                continue
            # FAST-EXPAND (userbot pack #1): dispatch the claimer while the base cost is still FAST_EXPAND_LEAD
            # short -- the 3-5 turn march earns it back before arrival. The old full-cost+reserve brake made us
            # 1-2 bases late by t40-60 in every bracket loss, and that income gap compounded into everything.
            # EARLY_L2 hold still applies (the HQ L2 fund is never poached for yet another base).
            # V2 EXPAND-RHYTHM: while behind the base-count schedule, the dispatch brake drops to
            # cost + GOLD_FLOOR -- the full-reserve brake is the measured 40-130-turn 3rd-base stall
            # (replays3: our 3rd base t60-159 vs the opponents' t21-23).
            _claim_brake = ((BASE_LEVELS[1].cost + GOLD_FLOOR) if _expand_lag
                            else (BASE_LEVELS[1].cost - FAST_EXPAND_LEAD) if bool(FAST_EXPAND)
                            else (BASE_LEVELS[1].cost + reserve - 100)) + _l2_hold + _eg_hold
            # V2 CLIMB-HOLD arm 2 (g1 opening: 1b builds t70/72 delayed HQ L2 by 11 turns while ahead
            # 10v7 on bases): once we out-base the enemy by 2+, a NEW claim also holds the climb step.
            if len(my_bases) >= _ebct_wide + 2:
                _claim_brake += _climb_hold_amt
            if _expand_ahead:
                _claim_brake = GOLD_FLOOR               # unit-ahead + base-behind + home_safe: dispatch a lone
                #   claimer to STAND on the contested stronghold NOW (blocks the enemy build; it converts to a
                #   base once income funds it) instead of banking gold into yet more army we don't need.
            if S.gold - spent < _claim_brake:
                break                                   # can't foreseeably afford more bases yet
            w = nearest_surplus(s)
            if w is None:
                break                                   # no spare warrior to send
            if order_move(w, s):
                handled_targets.add(s)
                dispatched += 1

    # 2b') CONTEST_CLAIM (R16, game 6 root fix -- see flag block): the 2b loop above SKIPS any stronghold in
    # enemy_at, so the enemy RESERVES a contested/TIE stronghold with a single scout and we cede it for tens of
    # turns while behind on bases (g6: base 32, 1 enemy body, 25 turns, 2 hops from our idle 4-11 surplus). When
    # BEHIND on territory, TAKE such a stronghold with a sized winning stack instead. Surplus-only (2a garrison
    # already filled), one measured contest/turn, near (dm<=do) + early (turn<CONTEST_TURN_MAX) so it stays a
    # rush-safe EXPANSION, not a deep raid. Placed BEFORE raid_force so the contest stack is not double-committed.
    # `not siege_recall and not _fort_hold` (adversarial review, CONFIRMED HIGH): match the sibling
    # surplus-dispatch branches' guard (the BUGFIX #1 CRITICAL "fist too deep -> HQ cracked" invariant).
    # SIEGE_EMERGENCY arms siege_recall at range 9 while `concentrate` only arms at return-ETA+3 and
    # `_rush_brake` only fires t<=40 -- so a delayed timing-all-in from an opponent that out-expanded us
    # (behind=True) could otherwise fire CONTEST and march the surplus out un-recallably while the HQ is
    # cracked. These two terms are home_safe's early-available components (home_safe itself is defined below).
    if (bool(CONTEST_CLAIM) and turn < CONTEST_TURN_MAX and on_hq == 0
            and not concentrate and not _rush_brake and not siege_recall and not _fort_hold):
        _en_bases_now = sum(1 for b in S.buildings if b.side is not me and b.type is BType.BASE)
        if _en_bases_now > len(my_bases) + TERRITORY_SLACK:              # strictly behind on territory
            for s in BOT.claim_order:
                if (s in handled_targets or s in _skip_build or s not in enemy_at
                        or S.find_building(s) is not None):
                    continue
                if nav.hops(s, M.my_hq) > nav.hops(s, M.opp_hq):         # never overreach into the enemy half
                    continue
                _cav = [w for w in surplus if w.id not in assigned]
                if not _cav:
                    break
                _ceta = min(nav.hops(w.region, s) for w in _cav)         # our arrival ETA (nearest surplus)
                if _ceta > CONTEST_ETA_MAX:                              # too far to contest safely
                    continue
                _cec = sum(1 for w in enemy_warriors if nav.hops(w.region, s) <= CONTEST_REINFORCE)
                if _cec == 0 or _cec > CONTEST_MAX:                       # unheld / a real garrison -> not a lone reservation
                    continue
                _cneed = _cec + CONTEST_MARGIN
                if len(_cav) < _cneed:
                    continue
                # the stack BUILDS on arrival (~_ceta turns out), so fund like FAST_EXPAND: march income closes the
                # gap. Full-cost-now would never fire while we spend on army/climb (g6 gold hovered 135-275<300).
                if (S.gold - spent) < BASE_LEVELS[1].cost - FAST_EXPAND_LEAD:
                    break
                _csent = 0
                for _cw in sorted(_cav, key=lambda w: nav.hops(w.region, s))[:_cneed]:
                    if order_move(_cw, s):
                        _csent += 1
                if _csent:
                    handled_targets.add(s)
                    break                                                # one measured contest per turn

    # 2c) RAID (two-front backdoor): move the TRUE surplus as concentrated stacks to deny the
    #     enemy's economy — siege their bases, then the enemy HQ. Moving as a stack is the whole
    #     point: a lone attacker is picked off and deals 0; a stack of N cracks a base (turret +
    #     lone worker) and accumulates real siege. The GUARD_MIN guard stays home, so committing
    #     the raid never opens our own HQ.
    raid_force = [w for w in surplus if w.id not in assigned]
    # R85 AVAIL_DENY (fist arm): over-expansion churn keeps the army perpetually MOVING (never stationary
    # surplus) so the raid pool starves to 0 even at a big avail lead -- the fist razes ONE base then drifts
    # home while the enemy free-climbs. Re-form the fist from the MOBILE army (every non-garrison body >= 2 hops
    # off the HQ, so the HQ ring stays put) so a just-razed/wandering fist immediately re-targets the next
    # crackable base. THREE tight gates jointly isolate the 1(92) situation from the wide-map wins this would
    # otherwise wreck: (1) enemy OUT-INCOMES us (+INC) -- its base lead means it WINS the level race unless we
    # deny its economy; (2) EARLY-MID only (turn <= TMAX) -- late denial trades our own climb-to-finish (my-bot
    # K19 seed2010 t143+ threw a won race); (3) clear AVAIL lead (+MARGIN, mirror-inert). home_safe + not-
    # _behind_hq, and _sim_crack self-limits every commit. Ablation: dropping (1) lost turtle/my-bot K19; dropping
    # (2) lost my-bot K19 seed2010. With all three, the matrix is byte-identical to R84 and 1(92) razes 61->87.
    _avdr = (bool(AVAIL_DENY) and M.K >= WIDE_K and turn <= AVAIL_DENY_TMAX and on_hq == 0 and not concentrate
             and not siege_recall and not _behind_hq and _oxh_enb > _oxh_myb
             and _oxh_myav >= _oxh_enav + AVAIL_DENY_MARGIN
             and _enemy_workcap >= _my_workcap0 + AVAIL_DENY_INC)
    if _avdr:
        _rf_ids = {w.id for w in raid_force}
        raid_force = raid_force + [w for w in my_warriors if w.id not in assigned
                                   and w.id not in _rf_ids and w.region != M.my_hq
                                   and nav.hops(w.region, M.my_hq) >= 2]
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
                 and not _fort_hold)
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
    # DENY-DOMINANT (latch-fix 3): decisive field dominance (big army lead + base lead) keeps the deny/
    # pressure/crack offense funded even while the HQ level transiently trails (see the flag block). The
    # climb catch-up keeps absolute gold priority -- hq_reserve/_bank_climb are untouched, so the fist only
    # trains from surplus ABOVE the banked upgrade. Near-even armies (mirror) never reach DENY_DOM_F.
    _offense_dominant = (bool(DENY_DOMINANT) and _econ_lead
                         and len(my_warriors) >= math.ceil(DENY_DOM_F * max(1, enemy_total)))
    # INCOME lead (work_cap = income / WORK_INCOME): A's per-turn gold dominates the enemy's -> the wide
    # income-push reads this to decide A's L5 is assured (so the climb hoard can be poured into army).
    _income_lead = _my_workcap0 >= _enemy_workcap + WIN_INCOME_MARGIN  # canonical caps from turn-top (L1092-1095)
    # WIDE-MAP EARLY SUPPRESSION (games 4/5 -- the gamble): the OLD code won wide maps by razing the enemy's
    # economy CONTINUOUSLY FROM THE OPENING, so the enemy never built an army or climbed (its B trained only
    # 12-19 ALL GAME, stuck at L4). The forensic shows a LATE "deny when army-dominant" gate is useless: by the
    # time the enemy climbs L4->L5 (t170-190) we have lost dominance and may even trail the HQ race. So fire
    # EARLY (from DENY_TURN, mid-opening) while we hold the ECONOMIC lead -- that is the window where the
    # enemy's bases are still lightly defended and razing actually suppresses its growth. We DROP the army-
    # dominance precondition (it was circular -- dominance is the RESULT of early suppression, not a
    # prerequisite); _sim_crack still self-limits (it never commits a fist that gets wiped before razing), so
    # this presses HARD when the enemy is weak and naturally backs off when it is strong. Hard-gated:
    #   * M.K >= WIDE_K  -> WIDE maps only (compact 7/8 at K=9 NEVER enter -> their out-climb wins untouched)
    #   * home_safe / not _behind_hq -> never under a committed threat or while trailing the HQ race
    #   * _econ_lead and the enemy still HOLDS bases to raze.
    # K-gated start: the WIDEST maps (K > WIDE_FORCE_ANCHOR = game-5-class) begin razing EARLIER (DENY_TURN_WIDE);
    # K15 (game 4) and the K11-K15 band keep DENY_TURN -> byte-identical, only K>=17 advances.
    _deny_turn = DENY_TURN_WIDE if M.K > WIDE_FORCE_ANCHOR else DENY_TURN
    BOT.deny_mode = (bool(WIDE_DENY) and M.K >= WIDE_K and home_safe and turn >= _deny_turn
                     and hq is not None and (not _behind_hq or _offense_dominant)
                     and _econ_lead and bool(enemy_base_regs))
    # Early window: commit eagerly at the MIN_RAID floor (continuous pressure) instead of waiting for the
    # safe MUSTER stack -- _can_crack + the evasion keep a small fist from throwing itself away.
    _early_window = bool(EARLY_RAID) and turn < PRESSURE_TURN and _econ_lead
    # PULSE (userbot pack #2) also commits at the small-squad floor: 4-6-unit pulse squads are the whole
    # point (the chip branch bounds their downside), waiting for a 6+ MUSTER stack was part of the pacifism.
    # COUNTER_PUSH (8(3).txt, see flag): a clear UNIT lead after a won defense + a crackable enemy base is the
    # counter-attack window. Used in the offense branch below to RELEASE THE FULL SURPLUS: the stale threat_army
    # latch otherwise pins target_garrison high, so harass_budget = my_warriors - target_garrison collapses to ~1
    # (8(3) t88: 15v9 units, bases 27/29 crackable, yet only ~1 body committed while the enemy retrained 7->20).
    _counter_push = (bool(COUNTER_PUSH) and M.K <= WIDE_FORCE_ANCHOR and home_safe and not _behind_hq
                     and len(my_warriors) >= len(enemy_warriors) + COUNTER_PUSH_MARGIN
                     and bool(enemy_base_regs))
    commit_threshold = MIN_RAID if (stuck_behind or _early_window or BOT.deny_mode or bool(PULSE)) else MUSTER
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
    # (enemy_base_regs from L1700 is this exact list -- same immutable S, same filter/order -- reused below)
    # OVERWHELMING-ARMY HQ ASSAULT (the user's rule): late-game, if our committing force can DESTROY the
    # enemy HQ even when its ENTIRE army converges to defend it (honest worst-case siege sim -> never the
    # suicide the user hated), throw everything at the HQ to win outright instead of just razing bases.
    _hq_assault = (bool(HQ_CRUSH) and turn >= HQ_CRUSH_TURN and on_hq == 0 and _ehqb0 is not None
                   and len(raid_force) >= MIN_RAID and len(my_warriors) > len(enemy_warriors)
                   and _sim_crack([w.hp for w in raid_force], _ehqb0.hp,
                                  HQ_LEVELS[_ehl0].turret,
                                  [w.hp for w in enemy_warriors], MAX_CRACK_TURNS)[0])
    # FINISHER (see flag block): the enemy is functionally annihilated and the honest worst-case sim --
    # including PHANTOM defenders it could still train during our march (income-bounded) -- says the fist
    # destroys its HQ even if everything converges. Re-evaluated every turn, so a read that goes stale
    # mid-march stops the assault the same turn (the old HQ_CRUSH suicide cannot recur).
    _finisher = False
    _finisher_all = False
    _allin_pool = []
    if (bool(FINISHER) and turn >= FINISH_TURN and on_hq == 0 and _ehqb0 is not None
            and len(enemy_base_regs) <= FINISH_MAX_BASES
            and len(raid_force) >= FINISH_MIN
            and len(my_warriors) >= FINISH_DOM_F * max(1, len(enemy_warriors))):
        _feta = max((nav.hops(w.region, M.opp_hq) for w in raid_force), default=0)
        _fph = min(FINISH_PHANTOM_CAP,
                   math.ceil(_feta * _enemy_workcap * WORK_INCOME / TRAIN_COST))
        _finisher = _sim_crack([w.hp for w in raid_force], _ehqb0.hp,
                               HQ_LEVELS[_ehl0].turret,
                               [w.hp for w in enemy_warriors]
                               + [HQ_LEVELS[_ehl0].warrior_hp] * _fph,
                               MAX_CRACK_TURNS)[0]
        # V2R4 (5.txt t168): no kill-shot gambles while trailing the climb -- a failed charge burns the
        # army AND the tiebreak bank at once (19 dead, then the worker-release spiral). _finisher_all
        # (t190+ window below) keeps its own gates.
        if _finisher and bool(FIN_HOLD_BEHIND) and _behind_hq:
            _finisher = False
        # V2R4 (5.txt t168): the FULL move bill must clear the reserve up front -- gold funded 19 of the
        # 22 sim-approved bodies and the bot's own sim rates 19 as annihilation (same guard as LATE_ALLIN).
        if _finisher and bool(FIN_FULLBILL):
            _fmv = sum(1 for w in raid_force if w.region != M.opp_hq)
            if (S.gold - spent) < MOVE_COST * _fmv + reserve:
                _finisher = False
        # REMNANT ALL-IN (step-2b): the fist alone may be too small to crack the remnant's HQ while our
        # TOTAL body count (workers included) cracks it easily -- 7(1) parked an 8-fist "uncrackable" next
        # to a 5-warrior remnant for 10 turns while 13 bodies would have ended it. Same per-turn sim, same
        # phantom model, ALL warriors as the attacker pool; income stops mattering the moment the HQ dies.
        _finisher_all = False
        if (bool(ENDGAME_ALLIN) and not _finisher and on_hq == 0
                and turn >= (ALLIN_TURN if bool(LATE_ALLIN) else FINISH_TURN)
                and _ehqb0 is not None and len(enemy_base_regs) <= ENDGAME_REMNANT_BASES
                and len(my_warriors) >= max(FINISH_MIN, ENDGAME_DOM_F * max(1, len(enemy_warriors)))):
            _allin_pool = list(my_warriors)
            if bool(LATE_ALLIN):
                # V2R3 (5(1) WIN->LOSS): the all-in pool is only the bodies that can REACH the enemy HQ
                # before the game ends -- far-home workers keep earning (supply preserved, 사용자: "보급이
                # 가장 중요") -- and the FULL move bill must clear the reserve up front: a 19-of-36 partial
                # launch fed the turret 1-3 bodies a turn (35 dead, siege 0). Anything less -> no launch.
                _allin_pool = [w for w in my_warriors
                               if nav.hops(w.region, M.opp_hq) <= GAME_TURNS - turn]
                _amv = sum(1 for w in _allin_pool if w.region != M.opp_hq)
                if (len(_allin_pool) < FINISH_MIN
                        or (S.gold - spent) < MOVE_COST * _amv + reserve):
                    _allin_pool = []
            if _allin_pool:
                _aeta = max((nav.hops(w.region, M.opp_hq) for w in _allin_pool), default=0)
                _aph = min(FINISH_PHANTOM_CAP,
                           math.ceil(_aeta * _enemy_workcap * WORK_INCOME / TRAIN_COST))
                _finisher_all = _sim_crack([w.hp for w in _allin_pool], _ehqb0.hp,
                                           HQ_LEVELS[_ehl0].turret,
                                           [w.hp for w in enemy_warriors]
                                           + [HQ_LEVELS[_ehl0].warrior_hp] * _aph,
                                           MAX_CRACK_TURNS)[0]
    # FINISH-SHARP (see flag block): re-check the SAME referee-exact kill on SMALL maps with the honest
    # phantom-STAGGERED, true-horizon sim -- catches the provable slow-grind kill the default finisher hides.
    # Only ADDS a firing (guarded `not _finisher and not _finisher_all`); FINISH_SHARP=0 -> byte-identical.
    if (bool(FINISH_SHARP) and not _finisher and not _finisher_all
            and M.K < WIDE_FORCE_ANCHOR and turn >= FINISH_TURN and on_hq == 0
            and home_safe and not siege_recall and not _fortress
            and _ehqb0 is not None and not (bool(FIN_HOLD_BEHIND) and _behind_hq)
            and len(enemy_base_regs) <= FINISH_SHARP_MAX_BASES):
        _sp = [w for w in my_warriors if nav.hops(w.region, M.opp_hq) <= GAME_TURNS - turn]
        if (len(_sp) >= FINISH_MIN
                and len(_sp) >= FINISH_SHARP_DOM_F * max(1, len(enemy_warriors))):
            _seta = max((nav.hops(w.region, M.opp_hq) for w in _sp), default=0)
            _sph = min(FINISH_PHANTOM_CAP,
                       math.ceil(_seta * _enemy_workcap * WORK_INCOME / TRAIN_COST))
            _shorizon = max(MAX_CRACK_TURNS, GAME_TURNS - turn - _seta)
            _sarr = [(k, HQ_LEVELS[_ehl0].warrior_hp) for k in range(1, _sph + 1)]
            if _sim_crack([w.hp for w in _sp], _ehqb0.hp, HQ_LEVELS[_ehl0].turret,
                          [w.hp for w in enemy_warriors], _shorizon, arrivals=_sarr)[0]:
                _smv = sum(1 for w in _sp if w.region != M.opp_hq)
                if (S.gold - spent) >= MOVE_COST * _smv + reserve:
                    _finisher_all = True
                    _allin_pool = _sp
    # DEAD_OPPONENT_MARCH (1(40), see flag block): the enemy is an annihilated remnant -- ZERO bases and
    # (near-)zero warriors -- nothing to raze, no income, no relief; the only winning move is to walk the
    # surplus over its HQ. _raid_commit is base-only (empty target list -> raid_tgt=-1) and the default
    # finishers gate on FINISH_TURN/ALLIN_TURN + a move-bill-PLUS-reserve wallet the starved economy could
    # not pay until t197 -- 1(40) idled 12 bodies for 170 turns beside a defenseless L1/hp10 husk and DREW.
    # Pay only the RAW move bill (no reserve: an upkeep cushion against a corpse is self-defeating); the
    # referee-exact sim with the phantom-train model still gates the launch.
    _dead_march = False
    _dm_pool: list = []
    if (bool(DEAD_OPPONENT_MARCH) and not _finisher and not _finisher_all and on_hq == 0
            and home_safe and turn >= DEAD_OPP_TURN and _ehqb0 is not None
            and len(enemy_base_regs) == 0 and len(enemy_warriors) <= DEAD_OPP_MAXW
            and raid_force):
        _dm_pool = [w for w in raid_force if nav.hops(w.region, M.opp_hq) <= GAME_TURNS - turn]
        if _dm_pool:
            _dmv = sum(1 for w in _dm_pool if w.region != M.opp_hq)
            if (S.gold - spent) >= MOVE_COST * _dmv:
                _deta = max((nav.hops(w.region, M.opp_hq) for w in _dm_pool), default=0)
                _dph = min(FINISH_PHANTOM_CAP,
                           math.ceil(_deta * _enemy_workcap * WORK_INCOME / TRAIN_COST))
                _dead_march = _sim_crack([w.hp for w in _dm_pool], _ehqb0.hp,
                                         HQ_LEVELS[_ehl0].turret,
                                         [w.hp for w in enemy_warriors]
                                         + [HQ_LEVELS[_ehl0].warrior_hp] * _dph,
                                         MAX_CRACK_TURNS)[0]
    # V2R4 HQ-CHIP (see flag block): the TURN_LIMIT tiebreak is (alive, HQ HP) -- referee testing-tool.py
    # 1443-1450. From CHIP_TURN, when the HP race is not already won (enemy hp >= ours, or the enemy
    # trails on LEVEL and an upgrade would heal it past us), the arrival-window surplus goes to STAND ON
    # the enemy HQ: occupation blocks its upgrade-heal (UPGRADE with an enemy present is illegal), and
    # cleared defenders turn attack ticks into siege = tiebreak HP. Deliberately NO crack sim (one net
    # siege point suffices; worst case = status-quo draw). The move bill may not touch the reserve OR a
    # currently-banked own upgrade (our own upgrade is our own heal -- it outranks the chip).
    _hq_chip = False
    _chip_pool = []
    # CHIP_SETTLED_EARLY (R45, see flag block): a MAXED full-hp HQ has no climb bank left for the late
    # window to protect -- open at CHIP_TURN_SETTLED so the enemy's pre-L5 upgrades get contested too.
    _chip_open = (CHIP_TURN_SETTLED
                  if (bool(CHIP_SETTLED_EARLY) and hq is not None and _is_max(hq)
                      and hq.hp >= hq.current_hp())
                  else CHIP_TURN)
    if (bool(HQ_CHIP) and turn >= _chip_open and on_hq == 0 and home_safe
            and _ehqb0 is not None and hq is not None
            and not _finisher and not _finisher_all
            and (_ehqb0.hp >= hq.hp or _ehl0 < hq.level)):
        # V2R9 EG_UPG_REACH (g8 193g miss, see flag): our own next upgrade is NET-income-reachable by
        # t198 without launching anyone AND its full hp wins/ties the enemy's max hp -> the purchase
        # outranks ANY chip (own heal doctrine, now with projected instead of instant affordability).
        _eg_hold_chip = False
        if bool(EG_UPG_REACH) and not _is_max(hq):
            # POTENTIAL earners (workcap-capped total bodies), not current on-building count: the hold's
            # own recall puts bodies in transit for a few turns, and counting only seated workers made
            # the net-income estimate collapse to +1/turn at t191 -> the hold un-latched and the chip
            # launched after all (the exact flap this lever exists to prevent). Bodies re-seat within
            # 1-3 turns; upkeep is still charged on everyone.
            _egr_net = max(0, WORK_INCOME * min(len(my_warriors), _my_workcap0)
                           - UPKEEP_PER_WARRIOR * len(my_warriors))
            _egr_short = _next_cost(hq) + reserve - (S.gold - spent)
            if (_egr_short <= _egr_net * max(0, 198 - turn)
                    and HQ_LEVELS[hq.level + 1].hp >= HQ_LEVELS[_ehl0].hp):
                _eg_hold_chip = True
                BOT.eg_hold = True                 # latch: one hold decision per endgame, no flapping
            elif BOT.eg_hold:
                _eg_hold_chip = True
        _cwin = GAME_TURNS - turn - CHIP_DWELL
        if _eg_hold_chip:
            pass                                   # pool stays empty; everyone keeps earning, 1c buys
        elif turn >= ALLIN_TURN or _chip_open < CHIP_TURN:
            # CHIP_SETTLED_EARLY mobilization (R45, 6(2)): the pre-190 surplus pool (rf<=13) rightly fails
            # the sim vs a 21-body HQ garrison -- only the ALLIN-style mobilization blocks, and at t190 the
            # shrunken arrival window (cwin 8 < the 9-hop HQ-to-HQ walk) locks fresh trains OUT of the
            # stream, which is exactly why the real block ran dry on t199. When the HQ is SETTLED
            # (_chip_open < CHIP_TURN => maxed at full hp), mobilize NOW: the _keep computation below funds
            # the remaining UPKEEP bill from kept earners (the CHIP_NET_KEEP pattern -- worker release can
            # never starve the army), the wider cwin keeps HQ-trained reinforcements feeding the tile
            # through t200, and the sim guard still vetoes unwinnable grinds every turn.
            # FINAL-RUSH WINDOW (user doctrine, this session: "러쉬를 하는건 190턴에 이뤄져야해" + 워커까지
            # 동원하는 최후의 러쉬는 t190~200의 흠집용): every body in the arrival window joins EXCEPT the
            # HQ tile (guard + its workers never march) and the minimum income crew that keeps a REACHABLE
            # own upgrade funded -- our own upgrade is our own heal AND max-hp raise, it outranks the chip
            # (4.txt: the t185-189 surplus was 1 body because the fist had been absorbed into work slots;
            # only worker mobilization puts bodies on the enemy HQ). Unreachable upgrade -> nothing to
            # protect, everyone in the window goes.
            # V2R8 CHIP_STATIONARY (4.txt t190, see flag): MOVING bodies cannot receive the order --
            # counting them let the sim approve a launch whose real squad was 6 of 9 and died for 0 siege.
            _cand = [w for w in my_warriors
                     if w.region != M.my_hq and nav.hops(w.region, M.opp_hq) <= _cwin
                     and (not bool(CHIP_STATIONARY) or w.state is WState.STATIONARY)]
            _tl = max(1, GAME_TURNS - turn)
            _keep = 0
            if not _is_max(hq):
                _short = _next_cost(hq) + reserve - (S.gold - spent)
                if _short > 0:
                    # V2R9 CHIP_NET_KEEP (see flag): the shortfall must be funded by NET income --
                    # the upkeep bill runs whether or not the bodies march (gross math kept 3 workers
                    # against a 193g shortfall while 44g/turn upkeep ate the difference).
                    if bool(CHIP_NET_KEEP):
                        _keep = math.ceil((_short + UPKEEP_PER_WARRIOR * len(my_warriors) * _tl)
                                          / (WORK_INCOME * _tl))
                    else:
                        _keep = math.ceil(_short / (WORK_INCOME * _tl))
            elif turn < ALLIN_TURN:
                # CHIP_SETTLED_EARLY (R45): pre-190 settled mobilization -- nothing left to climb, but the
                # UPKEEP bill to t200 still needs funding; keep just enough earners that bank + their
                # income covers it (6(2) t176: bill 1,728 vs bank 416 -> keep 4, march the other ~20).
                _short = UPKEEP_PER_WARRIOR * len(my_warriors) * _tl - (S.gold - spent)
                if _short > 0:
                    _keep = math.ceil(_short / (WORK_INCOME * _tl))
            # workers outside the window / on the HQ keep earning no matter what -- they cover part of it
            _keep -= sum(1 for w in my_warriors
                         if w.region in my_building_regions
                         and (w.region == M.my_hq or nav.hops(w.region, M.opp_hq) > _cwin))
            _cw = sorted((w for w in _cand if w.region in my_building_regions),
                         key=lambda w: nav.hops(w.region, M.opp_hq))
            _cn = [w for w in _cand if w.region not in my_building_regions]
            if 0 < _keep <= len(_cw):
                _cw = _cw[:len(_cw) - _keep]   # keep the rearmost earners; the front joins the rush
            # _keep > len(_cw): even keeping every worker cannot fund the step -> nothing to protect
            _chip_pool = _cn + _cw
        else:
            # pre-190: pure surplus only (working bodies are supply -- the user's t190 line holds)
            _chip_pool = [w for w in raid_force if nav.hops(w.region, M.opp_hq) <= _cwin]
        # V2R5 CHIP_SIM_GUARD (g6 t185): 33 bodies charged a 35-body parked garrison + turret -- 39 dead,
        # siege 0, and the deaths pumped 1,080g of retrains. Sim vs the CURRENT on-HQ garrison only (no
        # phantom, so a winnable grind like 4.txt's 7-warrior remnant still fires): the pool must crack
        # or end the grind with a CHIP_MIN squad still standing -- a 1-survivor margin is fiction once
        # the enemy's (unmodelable) bank-funded refills arrive, and a blocked chip keeps the workers
        # earning the own-upgrade heal instead (g6 t190: 875g + kept income = the L3 that wins 20v15).
        if bool(CHIP_SIM_GUARD) and _chip_pool:
            # V2R9 CHIP_MARCH_SIM (see flag): the fight starts AFTER the march -- horizon = turns left
            # minus the pool's arrival ETA; and enemies within 1 hop of the HQ join the tile fight in
            # one turn (g8: 6 on-tile + 2 at 1 hop shredded a "12-fight-turns-approved" chip in 7).
            if bool(CHIP_MARCH_SIM):
                _cg_eta = max((nav.hops(w.region, M.opp_hq) for w in _chip_pool), default=0)
                # CHIP_REACH_DEF (R70, see flag): every defender that reaches its HQ inside our arrival
                # ETA fights us there (1(76): the "1-hop" count saw 8 of lain's 25 -> 36 dead, siege 1).
                _cg_def = [ww.hp for ww in enemy_warriors
                           if nav.hops(ww.region, M.opp_hq)
                           <= (max(1, _cg_eta) if bool(CHIP_REACH_DEF) else 1)]
                _cg_hz = max(1, GAME_TURNS - turn - _cg_eta)
            else:
                _cg_def = [ww.hp for ww in enemy_warriors if ww.region == M.opp_hq]
                _cg_hz = max(1, GAME_TURNS - turn)
            _cg = _sim_crack([w.hp for w in _chip_pool], _ehqb0.hp,
                             HQ_LEVELS[_ehl0].turret, _cg_def,
                             _cg_hz)
            if not _cg[0] and _cg[2] < CHIP_MIN:
                _chip_pool = []
        _cmv = sum(1 for w in _chip_pool if w.region != M.opp_hq)
        _cbank = (_next_cost(hq) if (not _is_max(hq) and (S.gold - spent) >= _next_cost(hq) + reserve)
                  else 0)
        # CHIP_LEAN_FINAL (R43, see flag block): a MAXED, FULL-hp, home-safe HQ has nothing left for the
        # reserve to protect in the final window -- the chip pays only the raw move bill (5(4): the full
        # reserve+heal demand discarded a legal 21-body pool two turns after our own L5 purchase, and the
        # AI bought its drawing L5 on t199 that a single standing body would have made illegal).
        _clean_final = (bool(CHIP_LEAN_FINAL) and hq is not None and _is_max(hq)
                        and hq.hp >= hq.current_hp() and home_safe)
        if (len(_chip_pool) < CHIP_MIN
                or (S.gold - spent) < MOVE_COST * _cmv + (0 if _clean_final else reserve + _cbank)):
            _chip_pool = []
        _hq_chip = bool(_chip_pool)
    # V2 SIEGE-LATCH (g4 t129): a live, committed, already-DAMAGED target may not be dropped by branch
    # flapping (MULTI_PRONG re-dispatched 9 bodies OFF a 1-hp L3 when rf crossed 9->10). Defense branches
    # (relief/counter/finisher/recall) still preempt -- only the MULTI_PRONG re-split respects the latch.
    _siege_latch = False
    if bool(TGT_VALUE) and BOT.raid_tgt >= 0:
        _sl_b = S.find_building(BOT.raid_tgt)
        if _sl_b is not None and _sl_b.side is not me and _sl_b.hp < _sl_b.current_hp():
            _siege_latch = True
    # V2R7 L2_MARCH_HOLD (1(6), see flag): while the HQ is still L1 past the opening (and no emergency),
    # DISCRETIONARY raid marches must leave the L2 fund intact -- the 10g re-bill drip is what kept the
    # HQ at L1 for 130 turns. Relief/counter/finisher/chip loops keep plain billing (defense/endgame first).
    _march_hold = 0
    if (bool(L2_MARCH_HOLD) and hq is not None and hq.level < 2 and turn >= L2_MARCH_HOLD_TURN
            and not (concentrate or siege_recall or on_hq > 0 or _rush_brake or _under_massed)):
        _march_hold = _next_cost(hq)

    def _order_move_raid(w: Warrior, target: int) -> bool:
        _omr_ok = order_move(w, target, _march_hold)
        if _omr_ok:
            BOT.press_log[w.id] = turn    # PRESS_HOLD (R68): an ACTIVE raid march stamps its bodies
        return _omr_ok

    # V2R10 BEHIND_PRONG (1(9), see flag): the LOSING-side distributed-raid arm — land deficit or a
    # latched outmassed signal, a real post-defense fist, and round-trip time left.
    _behind_prong = (bool(BEHIND_PRONG) and turn <= BEHIND_PRONG_UNTIL
                     and (len(enemy_base_regs) - len(my_bases) >= BEHIND_PRONG_BASELEAD
                          or _outmassed_soft)
                     and len(raid_force) >= BEHIND_PRONG_MIN)

    # V2R12 _hold_ground (see flag block): the user's "HQ 훈련으로 막을 수 있을 때" condition -- home is
    # safe, the enemy is NOT out-producing us, and no wave is actually closing (none latched, or its stack
    # is farther than the recall gate). Under it the forward posture holds: FWD_STATION stages the idle
    # fist at the frontier, FLEE_HOLD/SIEGE_STICK finish provable sieges instead of walking home. The
    # moment any condition flips (real wave closing / out-produced / home unsafe) every consumer reverts
    # to the proven defensive paths -- rush defense is byte-identical (home_safe is False throughout it).
    # K-GATED to the small/mid maps (K <= WIDE_FORCE_ANCHOR = 15): every one of the six bracket losses is
    # K9-K15, while K17+ runs the proven deny/WIDE_PUSH doctrine -- and the matrix showed the levers ARE
    # a regression there (my-bot K19: 3W0L -> 1W2L with them on; K9-K13 unchanged-or-better). The widest
    # maps stay byte-identical to v2r10.
    _hold_ground = (M.K <= WIDE_FORCE_ANCHOR and home_safe and not _outproduced
                    and (BOT.threat_army == 0 or stack_reg < 0 or stack_dist > CONCENTRATE_DIST))

    # WIN_ENDGAME_COMMIT (see flag block): the winning-endgame flag handed to _raid_commit so it trusts
    # the referee-exact full-force _can_crack over the naive _stop flee-count -- razing B's last income
    # base (parked next to its stay-at-home HQ garrison) denies B's final HQ level. Climb-ahead + home_safe
    # + K19 + enemy sub-L5 with a base to raze. NO income/_is_max gate (proto out-razes B to its last base
    # BEFORE reaching L5, so an L5 requirement never co-occurs with enemy_base_regs>0 -- the finisher's
    # structural dead-end). Rush-safe via home_safe; winning-only via not _behind_hq + hq.level >= _ehl0.
    _win_endgame = (bool(WIN_ENDGAME_COMMIT) and home_safe and not _fortress and on_hq == 0
                    and hq is not None
                    and (M.K > WIDE_FORCE_ANCHOR or bool(FIN_COMPACT))   # FIN_COMPACT: 1(41) K9 generalization
                    and turn >= FIN_START_TURN
                    and not _behind_hq and (_is_max(hq) or hq.level >= _ehl0)
                    and _ehl0 < HQ_MAX_LEVEL and len(enemy_base_regs) > 0)

    # ENDGAME DENY ALL-IN (game-5 forensic, see flag block): once OUR climb is DONE (L5, income worthless)
    # and B is still sub-L5 with an INCOME BASE it needs to bank its last upgrade, the SURPLUS fist alone is
    # too small/far to commit (game 5: 21 bodies parked 7 hops from B's last base r100 -> _can_crack(surplus)
    # =False -> never marches -> r100 sat at hp12 for 50 turns -> B reached L5 @t197). But the FULL army
    # (workers included) DOES crack it (_can_crack(all 40)=True). _finisher_all already releases the workers
    # this way but targets the turreted opp_HQ (uncrackable) -> never fires; retarget it to B's highest-income
    # crackable BASE (razing it denies B's final level = the win). Reachability + full move-bill guard mirror
    # _finisher_all; home_safe keeps it rush-safe; _is_max means no own-climb is starved by the release.
    _deny_allin = False
    _deny_pool: list = []
    _deny_tgt = -1
    if (_win_endgame and _is_max(hq) and not _finisher_all and not _finisher
            and enemy_base_regs and len(my_warriors) >= FINISH_MIN):
        _dp = [w for w in my_warriors
               if min((nav.hops(w.region, r) for r in enemy_base_regs), default=99) <= GAME_TURNS - turn]
        if len(_dp) >= FINISH_MIN:
            def _deny_key(r):
                _b = S.find_building(r)                 # higher base level = higher income = deny it first
                return (-(_b.level if _b is not None else 1),
                        min(nav.hops(w.region, r) for w in _dp))
            for _r in sorted(enemy_base_regs, key=_deny_key):
                if _can_crack(S, M, nav, _dp, _r, MAX_CRACK_TURNS):
                    _deny_tgt = _r
                    break
            if _deny_tgt >= 0:
                # move bill: only STATIONARY bodies need a fresh 10g order (marching ones auto-advance
                # free). NO climb reserve -- proto is L5, there is nothing left to bank, so every spare
                # gold should buy the denial march (the reserve blocked the launch through t195 while
                # proto sat on r100's crackable base with 40 idle bodies -> B banked L5 @t197).
                _dmv = sum(1 for w in _dp if w.state is WState.STATIONARY and w.region != _deny_tgt)
                if (S.gold - spent) >= MOVE_COST * _dmv:
                    _deny_pool = _dp
                    _deny_allin = True

    # HOME_INTERCEPT (see flag block): an APPROACHING sub-wave stack we can DECISIVELY defeat on our turret
    # ground -> rally the surplus to kill it now instead of passive-garrison-then-panic. Referee-exact
    # can-stop sim CREDITS HQ production (train_cap/turn over the ETA, gold-gated) as staggered arrivals.
    # Computed here (raid_force/reserve/spent all live) so the dispatch elif can gate on the sim result;
    # when the sim rejects, _hi_go stays False and control falls through to the normal cascade (byte-safe).
    _hi_go = False
    _hi_rally = M.my_hq
    _hi_squad: list = []
    # NOTE: intentionally fires even under `concentrate` -- the user's case (turtle-20-vs-3) IS the
    # concentrate turtle over-committing home vs a small advancing stack. WAVE_STACK_MIN caps it to
    # sub-wave stacks (a real 10+ rush is excluded -> turtle owns it) and siege_recall/on_hq veto an
    # all-in, so a decisive kill-squad here never opens the HQ (the matched garrison stays home).
    if (bool(HOME_INTERCEPT) and hq is not None and turn >= MOBILIZE_ARM_TURN and on_hq == 0
            and not siege_recall and not _fort_hold
            and not _relief and not base_eating and not counter_now
            and stack_reg >= 0 and HI_MIN <= enemy_stack_sz < WAVE_STACK_MIN
            and stack_dist < nav.hops(stack_reg, M.opp_hq)
            and stack_dist <= HI_REACH and _stack_advancing and raid_force):
        _hi_rally = (min(my_building_regions, key=lambda r: nav.hops(stack_reg, r))
                     if my_building_regions else M.my_hq)
        _hi_eta = max(1, nav.hops(stack_reg, _hi_rally))
        # NEAR-HOME only (HQ-approach defense, not a forward base -- base_eating/_relief own those; rallying
        # deep costs raiding tempo = the K13-mirror #40 regression). Skip if the rally is not close to home.
        if nav.hops(_hi_rally, M.my_hq) <= HI_RALLY_HOME:
            # arrivable surplus, sized to the MINIMAL decisive squad (stack + margin); the rest stays home.
            _hi_avail = sorted((w for w in raid_force if nav.hops(w.region, _hi_rally) <= _hi_eta),
                               key=lambda w: nav.hops(w.region, _hi_rally))
            _hi_squad0 = _hi_avail[:enemy_stack_sz + HI_MARGIN]
            if len(_hi_squad0) >= enemy_stack_sz + HI_MARGIN:                # CLEAR numerical advantage only
                _hi_tc  = HQ_LEVELS[hq.level].train_cap
                _hi_dhp = HQ_LEVELS[hq.level].warrior_hp
                _hi_ahp = HQ_LEVELS[_ehl0].warrior_hp
                # gold for trains WITHOUT touching the operating reserve: banked-above-reserve now + NET income
                # over the approach window (the user's "HQ에서 찍어내는 것까지 계산").
                _hi_net  = (WORK_INCOME * min(len(my_warriors), _my_workcap0)
                            - UPKEEP_PER_WARRIOR * len(my_warriors))
                _hi_gold = max(0, (S.gold - spent) - reserve) + max(0, _hi_net) * _hi_eta
                _hi_afford = _hi_gold // TRAIN_COST
                _hi_present_tr = min(_hi_tc * _hi_eta, _hi_afford)          # trains READY by contact (present)
                _hi_fight_tr   = min(_hi_tc * HI_HORIZON, max(0, _hi_afford - _hi_present_tr))
                _hi_def   = [_hi_dhp] * (len(_hi_squad0) + _hi_present_tr)  # defenders present when the stack lands
                _hi_reinf = [((_i // max(1, _hi_tc)) + 1, _hi_dhp) for _i in range(_hi_fight_tr)]  # trains in-fight
                _hi_rb  = S.find_building(_hi_rally)
                _hi_bhp = _hi_rb.hp if _hi_rb is not None else (1 << 30)
                _hi_turret = _home_turret(S, M, me, _hi_rally)
                # DEFENSE-inverted _sim_crack: enemy stack SIEGES our rally building; def = our squad + turret,
                # arrivals = our HQ trainees. `not cracked` = we hold; returned survivors are the ATTACKER's.
                _hi_crk, _hi_tn, _hi_esurv = _sim_crack([_hi_ahp] * enemy_stack_sz, _hi_bhp, _hi_turret,
                                                        _hi_def, HI_HORIZON, arrivals=(_hi_reinf or None))
                if (not _hi_crk) and _hi_esurv == 0:                        # decisive: hold AND annihilate
                    _hi_go = True
                    _hi_squad = _hi_squad0

    # BASE_WORKER_RELIEF (see flag block): a sub-wave stack advancing within BRW_REACH(3) hops of a friendly
    # BASE -> source the defense from NEARBY WORKERS that can arrive by contact (not the drained raid_force),
    # grow nearest-first to the MINIMAL size the referee-exact sim (squad + base turret) needs to hold AND
    # wipe it, and send ONLY that many. HQ guard stays home; sub-wave + not-siege_recall keep it rush-safe.
    _brw_go = False
    _brw_base = -1
    _brw_squad: list = []
    if (bool(BASE_WORKER_RELIEF) and hq is not None and turn >= MOBILIZE_ARM_TURN and on_hq == 0
            and not siege_recall and not _fort_hold and not _relief and not base_eating
            and stack_reg >= 0 and BRW_MIN <= enemy_stack_sz < WAVE_STACK_MIN
            and _stack_advancing and my_building_regions):
        _brw_base = min(my_building_regions, key=lambda r: nav.hops(stack_reg, r))
        if nav.hops(stack_reg, _brw_base) <= BRW_REACH:
            _brw_eta = max(1, nav.hops(stack_reg, _brw_base))          # turns until the stack reaches the base
            _brw_ahp = HQ_LEVELS[_ehl0].warrior_hp                     # enemy warrior hp
            _brw_dhp = HQ_LEVELS[hq.level].warrior_hp                  # our warrior hp
            _brw_turret = _home_turret(S, M, me, _brw_base)
            _brwb = S.find_building(_brw_base)
            _brw_bhp = _brwb.hp if _brwb is not None else (1 << 30)
            # keep the minimum HQ guard home (only when defending a NON-HQ base); pull NEARBY workers that can
            # arrive at the threatened base by contact (hops <= ETA), nearest first.
            _brw_guard = set(w.id for w in sorted((w for w in my_warriors if w.region == M.my_hq),
                                                  key=lambda w: w.id.num)[:guard_floor]) \
                         if _brw_base != M.my_hq else set()
            _brw_avail = sorted((w for w in my_warriors
                                 if w.id not in _brw_guard and nav.hops(w.region, _brw_base) <= _brw_eta),
                                key=lambda w: nav.hops(w.region, _brw_base))
            # MINIMAL decisive squad: grow nearest-first until (squad + turret) holds AND wipes the stack.
            for _bn in range(BRW_MIN, len(_brw_avail) + 1):
                _bc, _bt, _besurv = _sim_crack([_brw_ahp] * enemy_stack_sz, _brw_bhp, _brw_turret,
                                               [_brw_dhp] * _bn, BRW_HORIZON)
                if (not _bc) and _besurv == 0:
                    _brw_go = True
                    _brw_squad = _brw_avail[:_bn]
                    break

    # RELIEF_POOL_GARRISON (1(36) forensic, see flag block): an ARMED classic relief whose raid_force is
    # empty emits ZERO orders while the base dies (t100-101: every mobile body mid-move, HQ-kept bodies
    # excluded from surplus by construction). Draw the HQ-kept stationary bodies ABOVE guard_floor into the
    # classic relief squad, TTL-gated (must arrive before the base falls). Base workers are NEVER pulled
    # (the BASE_WORKER_RELIEF economy-death lesson); guard_floor stays home; on_hq==0 gated.
    _rp_pool: list = []
    if (bool(RELIEF_POOL_GARRISON) and _relief and not _relief_small and on_hq == 0
            and not concentrate and not siege_recall):
        _rp_kept = stationary_at.get(M.my_hq, [])[:need.get(M.my_hq, 0)]
        _rp_free = _rp_kept[guard_floor:]
        _rp_b = S.find_building(_relief_tgt)
        _rp_e = max(1, sum(1 for e in enemy_warriors if e.region == _relief_tgt))
        _rp_ttl = (math.ceil(_rp_b.hp / _rp_e) + 1) if _rp_b is not None else (1 << 30)
        if _rp_free:
            _rp_pool = [w for w in _rp_free
                        if w.id not in assigned and nav.hops(w.region, _relief_tgt) <= _rp_ttl]
        # NEIGHBOR_RELIEF (R50, see flag): garrisons on OUR other bases within NR_HOPS join the squad --
        # but WINNABLE-only and MINIMAL: pull exactly the deficit the rest of the squad (sitters on the
        # target + inbound + HQ pool + TTL-reachable raid_force + turret) leaves against attackers+1, and
        # pull NOTHING when even the full neighborhood cannot close it (an unwinnable strip only feeds the
        # grinder AND leaves the source bases naked for the next wave -- the waverush-K13-s2006 crack:
        # unsized pulls drained MG_BASE_GARRISON pins mid-stream and the HQ fell behind them). Each source
        # keeps max(1, work_cap) bodies (income never pulled); a source with an enemy standing on it is
        # its own fight and is skipped; same TTL gate as the HQ pool.
        if bool(NEIGHBOR_RELIEF):
            _nr_enemy_on = {e.region for e in enemy_warriors}
            _nr_cands = []
            for _nb in my_bases:
                if (_nb.region == _relief_tgt or _nb.region in _nr_enemy_on
                        or nav.hops(_nb.region, _relief_tgt) > NR_HOPS):
                    continue
                _nr_sit = [w for w in stationary_at.get(_nb.region, []) if w.id not in assigned]
                _nr_keep = max(1, _nb.work_cap())
                for _w in _nr_sit[_nr_keep:]:
                    if nav.hops(_w.region, _relief_tgt) <= _rp_ttl:
                        _nr_cands.append(_w)
            # EPISODE THROTTLE, not sizing arithmetic: both sizing operands measured wrong on the
            # replays (static-e over-credited slow arrivals and went silent at 55-t77; stream-e
            # over-counted the tail and went silent at 53-t31). What actually cracked waverush-K13
            # s2006 was CHRONIC drain -- the stream re-arms relief every few turns and every arm
            # stripped the neighborhood again, hollowing the MG garrison pins mid-stream. So the
            # single-fight rescue stays exactly as the replays validated it (pull the whole eligible
            # neighborhood, capped), and a cooldown blocks the re-arm treadmill from farming it.
            if _nr_cands and turn - getattr(BOT, 'nr_pull_t', -99) >= NR_COOLDOWN:
                BOT.nr_pull_t = turn
                _nr_cands.sort(key=lambda w: nav.hops(w.region, _relief_tgt))
                _rp_pool.extend(_nr_cands[:NR_MAX_PULL])
    _cs_tgt = -1
    # COMMIT_STRIKE (R71, see flag block): seize a referee-exact-crackable OPEN enemy HQ (or its nearest
    # crackable base) when the enemy stack is committed far from its own HQ and we win the mutual race.
    _cs_force = raid_force
    if (bool(COMMIT_STRIKE) and on_hq == 0 and not concentrate and not siege_recall
            and not counter_now and raid_force and len(raid_force) >= CS_MIN_FORCE
            and stack_reg >= 0 and enemy_stack_sz >= MOBILIZE_NEAR
            and nav.hops(stack_reg, M.opp_hq) >= CS_OPEN):
        if (_can_crack(S, M, nav, raid_force, M.opp_hq, MAX_CRACK_TURNS, hq_reinf=True)
                and max(nav.hops(w.region, M.opp_hq) for w in raid_force) <= stack_dist + CS_RACE):
            _cs_tgt = M.opp_hq
        elif enemy_base_regs:
            # COMMIT_STRIKE base-target LATCH (R71b, 5(11) t121: the min-max-hop pick flipped 65->84 as ONE
            # straggler inflated 65's max-hop, abandoning a base at hp5 one hit from death -- user's "부술 수
            # 있었는데 중단"). If a real fist is ALREADY sieging the committed base (>= CS_MIN_FORCE bodies on
            # or adjacent) and it is still enemy + crackable, FINISH it -- ignore the straggler-poisoned
            # max-hop metric (SIEGE-LATCH doctrine for the strike). Otherwise pick fresh by min-max-hop.
            _cs_lb = BOT.cs_base
            _cs_at_lb = (sum(1 for w in raid_force if nav.hops(w.region, _cs_lb) <= 1)
                         if _cs_lb in enemy_base_regs else 0)
            if (_cs_at_lb >= CS_MIN_FORCE
                    and _can_crack(S, M, nav, raid_force, _cs_lb, MAX_CRACK_TURNS)):
                _cs_tgt = _cs_lb
            else:
                _cs_nb = min(enemy_base_regs,
                             key=lambda r: max(nav.hops(w.region, r) for w in raid_force))
                if (_can_crack(S, M, nav, raid_force, _cs_nb, MAX_CRACK_TURNS)
                        and max(nav.hops(w.region, _cs_nb) for w in raid_force) <= stack_dist + CS_RACE):
                    _cs_tgt = _cs_nb
    # CS_FINISH (R75, 5(12) AI5 loss, see flag block): must-win endgame -- we are BEHIND on HQ level (turtling
    # to turn-limit LOSES the tiebreak: 5(12) our HQ L4 < enemy L5) and the enemy HQ is OPEN (its all-in fist
    # left), but the force that can crack it is the FORWARD SIEGE army roaming enemy bases, INVISIBLE to the
    # surplus raid_force (5(12) t176: raid_force=13 cannot crack the L5 HQ, yet the 35-unit siege army 6 hops
    # away referee-CAN). Razing bases we cannot convert to a win while the open HQ sits there is a wasted
    # endgame -- pull the forward MOBILE army (closer to the enemy HQ than to ours, i.e. NOT the home garrison)
    # onto the HQ, using the de-poisoned race guard (nearest cracking subset, straggler-immune -- the R71b fix).
    # OVERRIDES the base arm and the defensive postures (concentrate/siege_recall): when behind on level the
    # race to the open enemy HQ is the ONLY win, so razing a base or turtling home just loses more slowly. Fires
    # every turn the conditions hold -> a SUSTAINED commit (no separate latch needed). on_hq==0 kept: if the enemy
    # is literally razing our HQ this turn, defend.
    # R78 CS_FIN_EARLY: outer floor = the LOOSER of the two arms' floors so ARM 2 can reach its own
    # CS_FIN_AHEAD_TURN window (ARM 1 still self-gates at CS_FIN_TURN via _cs_behind). Flag off => 140 (R77-exact).
    _cs_floor = CS_FIN_AHEAD_TURN if (bool(CS_FIN_EARLY) and bool(CS_FIN_AHEAD)) else CS_FIN_TURN
    if (bool(CS_FINISH) and on_hq == 0 and turn >= _cs_floor
            and stack_reg >= 0 and nav.hops(stack_reg, M.opp_hq) >= CS_OPEN):
        _cs_eh = S.find_building(M.opp_hq); _cs_mh = S.find_building(M.my_hq)
        if _cs_eh is not None and _cs_mh is not None and _cs_eh.type is BType.HQ:
            _cs_seen = {w.id for w in raid_force}
            _cs_fpool = raid_force + [w for w in my_warriors if w.id not in _cs_seen
                                      and nav.hops(w.region, M.opp_hq) < nav.hops(w.region, M.my_hq)]
            _cs_srt = sorted(_cs_fpool, key=lambda w: nav.hops(w.region, M.opp_hq))
            # ARM 1 (R75): must-win endgame -- BEHIND on level, the race is the only win.
            _cs_behind = (turn >= CS_FIN_TURN and _cs_mh.level < _cs_eh.level)
            # ARM 2 (R77, 1(84) t77; user: "적이 우리 기지 치려고 병력 뺐을 때 우리 한방주먹 9명이면 중앙 밀고
            # 상대 HQ를 그대로 공격했어도 -- 완전 베스트"): even AHEAD on level, if our forward army is ALREADY DEEP
            # on the offensive (nearest unit within CS_FIN_NEAR hops of the open enemy HQ) and referee-cracks it, a
            # decisive HQ kill beats grinding to a turn-limit tiebreak. The army-deep gate is what separates this
            # from RUSH defense: in a rush our army sits HOME (far from the enemy HQ), so ARM 2 never arms; and the
            # race guard below still refuses a commit our own HQ cannot survive. Turn floor keeps it out of the
            # opening. CS_FIN_AHEAD=0 => ARM 1 only (R75-identical).
            _cs_near = (bool(CS_FIN_AHEAD) and _cs_srt and turn >= CS_FIN_AHEAD_TURN
                        and nav.hops(_cs_srt[0].region, M.opp_hq) <= CS_FIN_NEAR
                        and ((not bool(CS_FIN_LVLGATE)) or _cs_mh.level > _cs_eh.level))  # R82: strictly ahead only (5(13) tied-L3 loss)
            # ARM 2's safety is NOT the march race (their stack is razing a BASE, not our HQ -- 1(84) t77): it is
            # whether our HQ can HOLD that stack (home defenders reachable by its arrival + turret >= stack). If the
            # HQ is safe we can take the open enemy HQ at leisure; the strict march race that ARM 1 needs (behind =
            # our HQ IS the target) would refuse this correct commit. Reuse the REACH_WIN defensive count.
            _cs_hqsafe = (_home_turret(S, M, me, M.my_hq)
                          + sum(1 for w in my_warriors if nav.hops(w.region, M.my_hq) <= stack_dist)
                          >= enemy_stack_sz + CS_FIN_HOLD_MARGIN)
            if _cs_behind or _cs_near:
                # de-poisoned reach: the SMALLEST nearest-first prefix that referee-cracks the HQ defines the reach
                # (bodies beyond it neither help nor veto).
                for _cs_k in range(max(CS_MIN_FORCE, 1), len(_cs_srt) + 1):
                    if _can_crack(S, M, nav, _cs_srt[:_cs_k], M.opp_hq, MAX_CRACK_TURNS, hq_reinf=True):
                        _cs_reach = nav.hops(_cs_srt[_cs_k - 1].region, M.opp_hq)
                        # ARM 1 (behind): win the march race to our HQ. ARM 2 (ahead-finish): our HQ holds, so commit.
                        if ((_cs_behind and _cs_reach <= stack_dist + CS_RACE)
                                or (_cs_near and _cs_hqsafe and _cs_reach <= CS_FIN_REACH)):   # R106: ARM 2 needs a GATHERED fist
                            _cs_tgt = M.opp_hq
                            _cs_force = _cs_fpool
                        break
    # SPENT_RAZE (R79, see flag block): the enemy is militarily SPENT (a 1-2 residual chip, no committed stack)
    # but its ECONOMY bases stand and out-climb us -- raze the nearest referee-crackable enemy base with our idle
    # surplus to deny its climb. Only when NOT ahead on level (turtling would else win the tiebreak), our HOME is
    # referee-safe against the residual, and a real fist referee-CAN raze it. Reuses the _cs_tgt override + BOT.cs_base
    # SIEGE-LATCH. Gated below the COMMIT_STRIKE/CS_FINISH arms (_cs_tgt < 0): an open enemy HQ always outranks a base.
    if (bool(SPENT_RAZE) and _cs_tgt < 0 and on_hq == 0 and turn >= SPENT_RAZE_TURN
            and not concentrate and not siege_recall and not counter_now
            and raid_force and len(raid_force) >= SPENT_RAZE_MIN and enemy_base_regs
            and enemy_stack_sz <= SPENT_RAZE_STACK
            and (len(enemy_warriors) - _enemy_workcap) <= SPENT_RAZE_EAV):
        _sr_mh = S.find_building(M.my_hq); _sr_eh = S.find_building(M.opp_hq)
        _sr_homesafe = (_home_turret(S, M, me, M.my_hq)
                        + sum(1 for w in my_warriors if nav.hops(w.region, M.my_hq) <= max(stack_dist, 1))
                        >= enemy_stack_sz + SPENT_RAZE_HOLD)
        if (_sr_mh is not None and _sr_eh is not None and _sr_mh.level <= _sr_eh.level and _sr_homesafe):
            # R83 SPENT_FINISH: prefer a DECISIVE enemy-HQ crack over a base raze when a gathered forward fist
            # referee-cracks the HQ and out-numbers its MOBILE reachable defense (the spent enemy can't reinforce
            # enough). 4(2): 20-30 fist vs an L3 HQ the enemy (avail 1-2) cannot defend -> win instead of draw.
            _sf_seen = {w.id for w in raid_force}
            _sf_pool = raid_force + [w for w in my_warriors if w.id not in _sf_seen
                                     and nav.hops(w.region, M.opp_hq) < nav.hops(w.region, M.my_hq)]
            _sf_reinf = sum(1 for e in enemy_warriors
                            if nav.hops(e.region, M.opp_hq) <= SPENT_FIN_REACH
                            and S.find_building(e.region) is None)
            if (bool(SPENT_FINISH) and len(_sf_pool) >= SPENT_FIN_MIN
                    and _can_crack(S, M, nav, _sf_pool, M.opp_hq, MAX_CRACK_TURNS)
                    and len(_sf_pool) > _sf_reinf + SPENT_FIN_MARGIN):
                _cs_tgt = M.opp_hq
                _cs_force = _sf_pool
            else:
                _sr_cands = [r for r in enemy_base_regs
                             if _can_crack(S, M, nav, raid_force, r, MAX_CRACK_TURNS)]
                if _sr_cands:
                    # raze the nearest crackable enemy economy base first (fastest raze, least exposure); next turn
                    # the pipe re-picks the next one -> progressive economy denial.
                    _cs_tgt = min(_sr_cands, key=lambda r: min(nav.hops(w.region, r) for w in raid_force))
                    _cs_force = raid_force
    # COMMIT_STRIKE latch bookkeeping (R71b): commit a new BASE target when the strike picks one; otherwise
    # KEEP the latch across turns where the fist is mid-move (raid_force momentarily empty) -- release ONLY
    # when the base leaves enemy_base_regs (cracked / razed). The eager per-turn clear was the bug: it dropped
    # the 65 commit the one turn raid_force was empty, so the next turn re-picked 84 (5(11)).
    if _cs_tgt >= 0 and _cs_tgt != M.opp_hq:
        BOT.cs_base = _cs_tgt
    elif BOT.cs_base not in enemy_base_regs:
        BOT.cs_base = -1
    if _cs_tgt >= 0:
        # confirmed race-winning crack -> commit the whole fist; preempts the reactive relief/defend below
        # (the strike ENDS the game before the forward stack can convert on our HQ). raid_tgt cleared so the
        # backdoor does not fight the commit; the strike itself is a straight march (not _raid_commit, which
        # would re-target a base mid-flight).
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for _w in _cs_force:
            if _w.region != _cs_tgt:
                _order_move_raid(_w, _cs_tgt)
    elif _relief and (raid_force or _rp_pool):
        # V2R10 SPLIT_RELIEF (1(9) two-prong all-in, see flag): >= 2 eater groups standing on OUR
        # buildings -> a sized squad per WINNABLE group, urgent (lowest base-TTL) first, from raid_force
        # only; the remainder keeps its raid commit. One group -> the original single-target paths below.
        _sr_groups = []
        if bool(SPLIT_RELIEF):
            _sr_cnt = Counter(w.region for w in enemy_warriors
                              if w.region in my_building_regions and w.region != M.my_hq)
            _sr_groups = _sr_cnt.most_common(PRONG_DETECT_K)
        if len(_sr_groups) >= 2 and raid_force:
            def _sr_ttl(rc):
                _b = S.find_building(rc[0])
                return (_b.hp / max(1, rc[1])) if _b is not None else 99.0
            _sr_groups.sort(key=_sr_ttl)
            _sr_used = set()
            for _gr, _gc in _sr_groups:
                # REACH_WIN: triage on bodies that can reach the prong inside its TTL, not the roster.
                _rw_pr = len(my_warriors)
                if bool(REACH_WIN):
                    _prb = S.find_building(_gr)
                    _pr_h = (math.ceil(_prb.hp / max(1, _gc)) + 1) if _prb is not None else 2
                    _rw_pr = sum(1 for w in my_warriors if nav.hops(w.region, _gr) <= _pr_h)
                if _rw_pr + _home_turret(S, M, me, _gr) < _gc + 1:
                    continue                       # unwinnable prong -> triage (defend the winnable ones)
                for _w in sorted((w for w in raid_force if w.id not in _sr_used),
                                 key=lambda w, _g=_gr: nav.hops(w.region, _g))[:_gc + 1]:
                    _sr_used.add(_w.id)
                    if _w.region != _gr:
                        order_move(_w, _gr)
            _sr_rest = [w for w in raid_force if w.id not in _sr_used]
            if len(_sr_rest) >= MIN_RAID:
                _raid_commit(S, M, nav, _sr_rest, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground)
        elif _relief_small:
            # V2R7 RELIEF_SIZED (see flag): sized squad only -- the nearest (_eat_sz + 1) bodies zero the
            # eater's siege overflow on our own turret ground (same math the EATER_RELIEF arming gate
            # asserts); the raid commit is NOT reset, and a >= MIN_RAID remainder keeps its march instead
            # of yo-yoing home on every 2-3-body poke.
            _sq = sorted(raid_force, key=lambda w: nav.hops(w.region, _relief_tgt))[:_eat_relief_sz + 1]
            _sq_ids = {w.id for w in _sq}
            for _w in _sq:
                if _w.region != _relief_tgt:
                    order_move(_w, _relief_tgt)
            _rest = [w for w in raid_force if w.id not in _sq_ids]
            if len(_rest) >= MIN_RAID:
                _raid_commit(S, M, nav, _rest, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground)
        else:
            # RELIEF_TRIAGE (R57, 1(63) t86 loss; user: "방어하러 명령 보내기 전에 계산부터 하고 보내는
            # 로직이 필요해 -- 아예 늦어버린 싸움에서는 그냥 상대기지를 공격하는 전술"): compute the
            # battle BEFORE dispatching. TTL = ceil(base hp / net siege) + 1 (hold rule: attackers -
            # sitters - turret); winning relief = sitters + turret + bodies arriving within TTL >=
            # attackers. 1(63) measured: base 33 TTL ~2 turns vs the fist's 6-hop march -- 15 bodies
            # were dead on departure (RELIEF_ETA_BODY, the per-body filter, sits ablated at 0), while
            # enemy base 43 stood UNGUARDED 2 hops away. A lost relief spends the same fist RAZING via
            # _raid_commit (crack-sim gated, so this is never a blind suicide march); home_safe-gated
            # so a genuine home emergency keeps the defensive march.
            _rd_base = raid_force + _rp_pool
            _rt_lost = False
            if bool(RELIEF_TRIAGE) and enemy_base_regs and home_safe and on_hq == 0:
                _tb = S.find_building(_relief_tgt)
                _te = sum(1 for e in enemy_warriors if e.region == _relief_tgt)
                _tsit = sum(1 for w in my_warriors if w.region == _relief_tgt)
                _ttur = _home_turret(S, M, me, _relief_tgt)
                _tsg = _te - _tsit - _ttur
                if _tb is not None and _te > 0 and _tsg > 0:
                    _tttl = math.ceil(_tb.hp / _tsg) + 1
                    _treach = (_tsit + _ttur
                               + sum(1 for w in _rd_base
                                     if nav.hops(w.region, _relief_tgt) <= _tttl))
                    if _treach < _te and _rd_base:
                        # my-bot K19 ablation (9W0L3D -> 6W3L3D, seeds 2002/2006/2009 pure-R57):
                        # a lost relief alone is NOT enough to walk away -- against a compact
                        # defender the counter trade LOSES. Convert only when the counter BEATS
                        # the relief on both axes: the nearest enemy base is STRICTLY CLOSER than
                        # the doomed base (t86: 2 hops vs 6) AND provably crackable; otherwise
                        # keep the defensive march (bodies still cover the next line).
                        _rt_ctr = min(enemy_base_regs,
                                      key=lambda r: min(nav.hops(w.region, r) for w in _rd_base))
                        _rt_cd = min(nav.hops(w.region, _rt_ctr) for w in _rd_base)
                        _rt_rd = min(nav.hops(w.region, _relief_tgt) for w in _rd_base)
                        _rt_lost = (_rt_cd < _rt_rd
                                    and _can_crack(S, M, nav, _rd_base, _rt_ctr, MAX_CRACK_TURNS))
            if _rt_lost:
                _raid_commit(S, M, nav, _rd_base, enemy_base_regs, _order_move_raid,
                             my_building_regions, turn, climb_pending=_climb_pending,
                             hold_ground=_hold_ground)
            else:
                BOT.raid_tgt = -1; BOT.raid_lock = 0     # real enemy stack on our base -> release the commit & defend
                # V2R6 RELIEF_ETA_BODY: only bodies that can ARRIVE before the base falls march; the rest keep
                # their current business (a mid-siege body re-enters via SIEGE_BODY_HOLD next turn).
                # RELIEF_POOL_GARRISON: the HQ-kept-above-guard pool (already TTL-gated) joins the squad.
                _rd_pool = _rd_base
                if bool(RELIEF_ETA_BODY):
                    _rdb = S.find_building(_relief_tgt)
                    _rde = max(1, sum(1 for e in enemy_warriors if e.region == _relief_tgt))
                    _rdttl = (math.ceil(_rdb.hp / _rde) + 1) if _rdb is not None else (1 << 30)
                    _rd_pool = [w for w in _rd_base if nav.hops(w.region, _relief_tgt) <= _rdttl]
                for _w in _rd_pool:
                    if _w.region != _relief_tgt:
                        order_move(_w, _relief_tgt)
    elif counter_now and raid_force:
        # RACE the enemy's open rear with our whole counter-force -- but at its nearest BASE, NEVER its
        # turreted HQ (an HQ march is a suicide). If the enemy has no live base to punish, fall through to
        # the crack-aware backdoor (which is base-only and withdraws when nothing is crackable) rather
        # than throwing the fist at the HQ turret.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        if COUNTER_TGT == 'base' and not enemy_base_regs:
            _raid_commit(S, M, nav, raid_force, enemy_base_regs, order_move, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground)
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
        # COMMIT-BACKDOOR (the user's rule: "상대가 하나에 응집해 공격하면 소수로 다른 기지를 친다"). The enemy
        # committed its army forward, so its REAR is open. Send just enough to WIN the field fight at
        # the stack (matched + 1); peel the EXCESS to raze the enemy's now-undefended bases instead of
        # piling everyone onto the same fight -- otherwise we only trade ("안그럼 손해밖에 안나"). The
        # backdoor squad uses the crack toolkit (commits only to bases it can actually raze).
        # HP_FIGHT_BAR (R49): size the fight squad to WIN the hp-weighted exchange, not the headcount.
        need_fight = min(len(raid_force), int(math.ceil(enemy_stack_sz * _hpfb)) + 1)
        fight = sorted(raid_force, key=lambda w: nav.hops(w.region, stack_reg))[:need_fight]
        fight_ids = {w.id for w in fight}
        extra = [w for w in raid_force if w.id not in fight_ids]
        for w in fight:
            if w.region != stack_reg:
                order_move(w, stack_reg)
        if len(extra) >= MIN_RAID and enemy_base_regs:
            _raid_commit(S, M, nav, extra, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground)
        else:
            for w in extra:
                if w.region != stack_reg:
                    order_move(w, stack_reg)
    elif _hi_go and _hi_squad:
        # HOME_INTERCEPT dispatch (see flag block): rally the sim-approved surplus onto our turret ground to
        # annihilate the approaching stack (MOVE to a friendly building is FREE). Surplus-only; the HQ garrison
        # stays home. When the sim did NOT approve a decisive win, _hi_go is False and this branch is skipped,
        # so control falls to the existing cascade -- byte-identical when HOME_INTERCEPT=0.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for w in _hi_squad:
            if w.region != _hi_rally:
                order_move(w, _hi_rally)
    elif _brw_go and _brw_squad:
        # BASE_WORKER_RELIEF dispatch (see flag block): send the sized nearby-worker squad to defend the
        # threatened base (turret ground; MOVE to a friendly building is FREE). Only the sim-approved MINIMAL
        # number go -- the HQ guard and the rest of the economy keep working. Skipped when _brw_go is False.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for w in _brw_squad:
            if w.region != _brw_base:
                order_move(w, _brw_base)
    elif (_harass_now and on_hq == 0 and concentrate and stack_dist > CONCENTRATE_DIST
            and len(raid_force) >= MIN_RAID and not siege_recall):
        # [BUGFIX #1 CRITICAL] `and not siege_recall`: when a committed all-in is beelining our HQ,
        # SIEGE_EMERGENCY sets siege_recall=True to RECALL the fist home (the g3 loss fix). But this
        # parked-stack pin-break branch only gated on `concentrate` (true in the dist 4-9 recall window)
        # and `_harass_now` (almost always true via EARLY_RAID), so it reached BEFORE the else-recall and
        # sent the fist BACK OUT via _raid_commit -- exactly the "fist too deep, came home too late -> HQ
        # cracked" failure siege_recall exists to prevent. Now siege_recall suppresses this branch too, so
        # the fist falls through to the else-branch and marches home to defend.
        # PARKED-STACK PIN BREAK (the g6 draw): a far enemy stack parked past its own midline trips
        # `concentrate` -> home_safe=False -> the whole offense branch closes and our big army sits idle to
        # a draw (g6: 36 units, only 6 total siege ALL game). But the MATCHED garrison is already held home
        # (2a inflated defenders_needed to target_garrison under concentrate), so `raid_force` here is the
        # TRUE EXCESS above it. Commit that excess to RAZE the enemy's economy via the proven crack-aware
        # backdoor (base-only, never opp_hq, evasion-guarded) -> deny growth, reach L5 first, break the
        # stalemate. Excess-only + matched garrison home = the home HQ is never stripped. Gated on the stack
        # NOT closing (stack_dist > CONCENTRATE_DIST); a genuinely closing wave still recalls everyone below.
        _raid_commit(S, M, nav, raid_force, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground, win_endgame=_win_endgame)
    elif _finisher_all:
        # REMNANT ALL-IN dispatch: every body in the (sim-approved) pool converges on the enemy HQ --
        # under LATE_ALLIN that is only the arrival-window bodies (the rest keep working the economy).
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for w in _allin_pool:
            if w.region != M.opp_hq:
                order_move(w, M.opp_hq)
    elif _finisher and raid_force:
        # FINISHER: annihilation end-state, sim-approved every turn -> commit the whole surplus at the
        # enemy HQ and END the game (the g7/g8 drawn kill-windows). Placed before the threat_army muster
        # so a stale wave latch from the enemy's long-dead mid-game army cannot veto the finish.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for w in raid_force:
            if w.region != M.opp_hq:
                order_move(w, M.opp_hq)
    elif _dead_march and _dm_pool:
        # DEAD_OPPONENT_MARCH dispatch (see flag block): walk the sim-approved surplus over the remnant HQ.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for w in _dm_pool:
            if w.region != M.opp_hq:
                order_move(w, M.opp_hq)
    elif _deny_allin and _deny_pool:
        # ENDGAME DENY ALL-IN dispatch (see the compute block): B's HQ is uncrackable so _finisher_all never
        # fired, but proto is L5 (own climb done) and B is one upgrade from L5 with a crackable INCOME base.
        # Commit the FULL worker-released pool to that base via _raid_commit (win_endgame=True so it drives
        # THROUGH the parked HQ-garrison flee-count on the final approach). Razing B's last income base drops
        # its per-turn gold below the final upgrade cost -> B can NEVER reach L5 -> proto WINS the tiebreak.
        _raid_commit(S, M, nav, _deny_pool, [_deny_tgt], _order_move_raid, my_building_regions, turn,
                     climb_pending=False, hold_ground=_hold_ground, win_endgame=True)
    elif _hq_chip:
        # V2R4 HQ-CHIP dispatch: the arrival-window surplus occupies the enemy HQ tile -- blocks its
        # upgrade-heal, grinds the garrison, converts cleared ticks into tiebreak siege. Defense branches
        # (relief/counter/base_eating) preempt above; the home garrison never marches (surplus only).
        # CHIP_LEAN_FINAL (R43): the settled-endgame chip bills lean -- 5(4) measured order_move's own
        # can(cost) re-check silently refusing all 21 approved moves against the idle 1000g heal cushion
        # (gold 522 two turns after our own L5 purchase), which is exactly the pool-level wallet bug again
        # one layer down. lean only when the pool-level _clean_final already held.
        BOT.raid_tgt = -1; BOT.raid_lock = 0
        for w in _chip_pool:
            if w.region != M.opp_hq:
                order_move(w, M.opp_hq, lean=_clean_final)
    elif _harass_now and home_safe and raid_force:
        # ACTIVE crack-aware committed BACKDOOR (single owner of the offense branch). Fires from
        # mid-game (HQ >= HARASS_HQLEVEL) as BROADLY as the proven v1 -- so the attack stays vigorous
        # -- but it now ROAMS razing only enemy bases it can ACTUALLY crack (monotonic march -> never
        # ping-pongs) and withdraws-to-watch otherwise, instead of v1's chip-and-retreat. During a
        # FORMING wave (mil_switch) it holds the matched garrison home and commits only the EXCESS, so
        # going on offense never under-defends our HQ; with no wave it commits the whole surplus.
        # home_safe-gated so it never marches out into a committed wave (that loses winnable games).
        if BOT.threat_army > 0:
            # a CONCENTRATED wave is forming -> hold the matched garrison home and commit only the
            # EXCESS to the backdoor (so attacking never under-defends our HQ vs the building wave).
            # Keyed on threat_army (a real massed stack), NOT mil_switch: a turtle that merely
            # out-PRODUCES us with spread units (threat_total) is no imminent threat -- against that we
            # commit a FULL fist and raze, instead of cowering behind a huge idle garrison.
            harass_budget = max(0, len(my_warriors) - target_garrison)
            harass_budget = min(len(raid_force), max(harass_budget, min(HARASS_CAP, len(raid_force))))
            # VELOCITY-MUSTER (latch-fix 1): the latched "wave" is still sitting FAR away and NOT advancing
            # (a garrison at its own HQ) and nothing is in our half -- keep the WHOLE surplus committed
            # forward instead of walking it home (the g7 t124 / g8 t120 recall; see the flag block).
            # Training still ramps toward target_garrison and the fortify climb window stays open; the
            # moment the stack advances the matched muster below resumes (and SIEGE_EMERGENCY still
            # force-recalls a genuine all-in regardless).
            # R15 HARASS_WHEN_PASSIVE (game 6, see flag block): same full-surplus release as VELOCITY_MUSTER
            # but for the PARKED-PASSIVE + BEHIND-ECON case where threat>0 (B's passive forward-base defenders
            # sit in our half) would otherwise veto it. The mass is parked far (park_streak) and not advancing;
            # if it MOVES, the crack-aware EVASION flee retreats the fist. Only fires when we cannot win by
            # climbing (_smallmap_econ) so a winnable game is never traded for a raid.
            _passive_release = (bool(HARASS_WHEN_PASSIVE) and _smallmap_econ and stack_reg >= 0
                                and stack_dist > gate and not _stack_advancing and on_hq == 0
                                and BOT.park_streak >= HARASS_PARK_MIN)
            if ((bool(VELOCITY_MUSTER) and stack_reg >= 0 and stack_dist > gate
                    and not _stack_advancing and on_hq == 0 and threat == 0)
                    or _passive_release
                    or (_counter_push and not _stack_advancing)):   # COUNTER_PUSH: unit-ahead post-defense +
                #   enemy NOT advancing -> release the FULL surplus to the counter-attack (the crack sim still
                #   gates the target). not _stack_advancing so a fresh incoming wave reverts to the matched muster.
                harass_budget = len(raid_force)
            fist = sorted(raid_force, key=lambda w: w.id.num)[:harass_budget]
            fist_ids = {w.id for w in fist}
            # BASE-RALLY (latch-fix 1b, see flag block): the advancing wave's predicted first target is one
            # of our forward BASES we can contest with interior lines -- rally the mustered surplus AT that
            # base (own turreted ground; the bodies are STATIONARY there when the wave lands, so _relief can
            # actually use them) instead of walking it home PAST the wave (the new-g8 t133 piecemeal rout).
            # Nearest-building predicts the target exactly like FORWARD-PUSH's _wtgt does; a true HQ beeline
            # (nearest = HQ) or lost interior lines (base farther from home than the wave) rallies home as
            # before, and the on-top/committed cases never reach here (concentrate/_relief branch first).
            _rally = M.my_hq
            if (bool(BASE_RALLY) and stack_reg >= 0 and _stack_advancing and on_hq == 0
                    and my_building_regions):
                _rt = min(my_building_regions, key=lambda r: nav.hops(stack_reg, r))
                # REACH_WIN: hold the forward rally only if the force reachable by the stack's ETA wins there.
                # Wave-band exemption (8(5) t72: the reach test sent the stagers home and ceded base 27 to
                # the 11-wave the legacy rally had held/deterred in 8(6)) -- waves keep the legacy arm.
                if (_rt != M.my_hq and nav.hops(_rt, M.my_hq) <= stack_dist
                        and (sum(1 for w in my_warriors
                                 if nav.hops(w.region, _rt) <= max(1, nav.hops(stack_reg, _rt)))
                             if (bool(REACH_WIN) and enemy_stack_sz < WAVE_STACK_MIN)
                             else len(my_warriors))
                            + _home_turret(S, M, me, _rt) >= enemy_stack_sz):
                    _rally = _rt
                    BOT.rally_tgt = _rt          # RALLY_HOLD (R64): latch the winning stand
                    BOT.rally_turn = turn
            for w in raid_force:
                if w.id not in fist_ids and w.region != _rally:
                    order_move(w, _rally)
            if fist:
                _raid_commit(S, M, nav, fist, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground, win_endgame=_win_endgame)
            else:
                BOT.raid_tgt = -1; BOT.raid_lock = 0
        elif _hq_assault:
            # OVERWHELMING: throw the whole surplus at the enemy HQ to end it (guaranteed crackable above).
            BOT.raid_tgt = -1; BOT.raid_lock = 0
            for w in raid_force:
                if w.region != M.opp_hq:
                    order_move(w, M.opp_hq)
        elif (bool(MULTI_PRONG) and len(raid_force) >= MULTI_PRONG_MIN
              and not _siege_latch
              and len(enemy_base_regs) >= 2
              # DENY-DOMINANT extension (new-g4 replay, byte-identical rerun of the draw): the split-raid was
              # RUNNING at t106-121 and _behind_hq switched it off at t122 exactly while we held a ~1.9x army
              # + 8v5 base lead -- same kill-switch, same dominant exception as deny/PRESSURE/CRACK (fix 3).
              and (((not _behind_hq or _offense_dominant)
                    and (_econ_lead or len(my_warriors) >= len(enemy_warriors) + OUTPRODUCE_MARGIN))
                   # OVERWHELMING-ARMY override (the user's "병사가 압도적으로 많아지면"): on the WIDEST maps,
                   # distribute even while TRANSIENTLY behind on HQ -- in game 5 A trails B's climb, which
                   # disabled the spread exactly when A's army was crushing B's. When our army is >= OVERWHELM_F
                   # times the enemy's (its army is wrecked by the income-push, so it cannot punish split prongs),
                   # parallel razing denies more economy than one fist overkilling a single base. The 2x gate
                   # never trips the SYMMETRIC mirror (armies ~1x) -> the mirror that this previously regressed
                   # stays on the proven single fist.
                   or (M.K > WIDE_FORCE_ANCHOR and len(enemy_warriors) >= OVERWHELM_ENEMY_MIN
                       and len(my_warriors) >= OVERWHELM_F * len(enemy_warriors))
                   # V2R10 BEHIND_PRONG (see flag): the losing-side arm — the enemy's own 1(9) move.
                   or _behind_prong)):
            # BIG ARMY + CLEAR LEAD (we out-base OR out-produce the enemy): spread the surplus across
            # multiple enemy bases at once (the user's "분산해서 때려라"). The enemy moves one hop/turn and
            # can only defend one place; a prong that meets a relief force folds into another (disengage-
            # and-fold inside _two_front_raid). The CLEAR-LEAD gate is what keeps the SYMMETRIC mirror from
            # tripping it (verified: without it, mirror 13W->9W as dispersed raiding converts worse than
            # the single fist) -- so the proven single-fist razing (turtle/mirror) and all defense are
            # untouched, and the spread only kicks in when we genuinely dominate (games 4/5).
            # V2R3 MP_FALLTHRU: MP keeps the turn ONLY if it actually dispatches a genuine spread (>= 2
            # distinct prongs). A fold collapsed to one target returns False and the turn falls through
            # to _raid_commit (value key + siege latch + commit lock) WITHOUT resetting the committed
            # target -- ending the RC<->MP ownership war that burned 4(1)'s peak-force window.
            # V2R10 BEHIND_PRONG per-prong crack certainty: when the LOSING arm is (co-)active, only
            # bases a HALF-fist provably razes qualify as prong targets — guaranteed razes, never trades.
            _mp_targets = enemy_base_regs
            if _behind_prong:
                _mp_half = sorted(raid_force, key=lambda w: w.id.num)[:max(2, len(raid_force) // 2)]
                _mp_targets = [r for r in enemy_base_regs
                               if _can_crack(S, M, nav, _mp_half, r, MAX_CRACK_TURNS)]
            if len(_mp_targets) >= 2 and _two_front_raid(S, M, nav, raid_force, _mp_targets, _order_move_raid):
                BOT.raid_tgt = -1; BOT.raid_lock = 0
            else:
                _raid_commit(S, M, nav, raid_force, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground, win_endgame=_win_endgame)
        else:
            _raid_commit(S, M, nav, raid_force, enemy_base_regs, _order_move_raid, my_building_regions, turn, climb_pending=_climb_pending, hold_ground=_hold_ground, win_endgame=_win_endgame)
    else:
        BOT.raid_tgt = -1; BOT.raid_lock = 0     # wave committed / nothing to attack -> muster & defend
        # RALLY_HOLD (R64, 7(6) t72; user: "11명 러쉬 -- 가용인원 보내면 충분히 막는데 소극적"): the
        # BASE_RALLY stand at the wave's predicted first target (t71: 8 bodies -> base 26) was REVERSED
        # one turn later when home_safe flipped and this muster branch took the turn -- half the rally
        # u-turned to the HQ and the rest trickled into base 26 piecemeal, ground down one-by-one while
        # three forward bases fell. A committed WINNING stand must not flap: while the latched rally
        # base still stands, the stack is still live, and the hold arithmetic (whole army + its turret
        # >= stack) still passes, the muster keeps feeding the RALLY instead of node 0. The moment any
        # of that breaks (base razed / stack gone / arithmetic fails) the legacy home muster resumes.
        _rh = getattr(BOT, 'rally_tgt', -1)
        _rh_b = S.find_building(_rh) if _rh >= 0 else None
        if (bool(RALLY_HOLD) and _rh >= 0
                and turn - getattr(BOT, 'rally_turn', -99) <= RALLY_HOLD_TTL
                and _rh_b is not None and _rh_b.side is me
                and stack_reg >= 0 and on_hq == 0
                and len(my_warriors) + _home_turret(S, M, me, _rh) >= enemy_stack_sz):
            for w in raid_force:
                if w.region != _rh:
                    order_move(w, _rh)
            return_dummy = None                      # fall through skipped via else below
        else:
            # V2R12 note: STAND_GROUND (hold bodies on a contested forward base during the home muster) was
            # designed here but REMOVED after adversarial review -- this else-branch IS the rush/all-in home
            # recall (home_safe False, siege_recall/concentrate closing), and holding bodies off node 0 there
            # breaks the depth-independent recall the g3 fix guarantees (a two-prong HQ-beeline + side scout
            # would delay the HQ defenders). The 1(13) "근무태만" is instead solved by FWD_STATION (staging the
            # idle fist forward so bodies are PRESENT when a base is hit) + the existing _relief/base_eating
            # interception -- this branch stays byte-identical to v2r10. RALLY_HOLD above only intercepts a
            # LATCHED WINNING stand; every other path lands here exactly as before.
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
            # FAST-EXPAND (userbot pack #1): fund claimer BODIES aggressively while land remains -- the old
            # 1-2 floor is why the bracket bots out-claimed us (they train claimers continuously).
            _claim_fund = (min(FAST_CLAIM_TRAIN, unclaimed_now)
                           if (bool(FAST_EXPAND) and turn < FAST_CLAIM_TURN)
                           else min(2 if behind else 1, unclaimed_now))
            # V2 EXPAND-RHYTHM: behind schedule -> fund the scheduled claimer bodies (cap 2/turn)
            if _expand_lag:
                _claim_fund = max(_claim_fund, min(2, _sched_deficit, unclaimed_now))
            want_spare = max(want_spare, _claim_fund)
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
        # DENY-GAMBLE: same base-razing army-ramp, armed EARLY by any HQ-level lead in a SAFE state (the user's
        # "앞서면 견제하고 다녀라"). free_gold is measured ABOVE `reserve` (which still holds the climb bank), so
        # our own HQ keeps maxing while the surplus grinds the enemy economy. home_safe/not-behind/not-fortress
        # keep the rush + trailing-climb defense byte-identical.
        _deny_gamble = (bool(DENY_GAMBLE) and turn >= DENY_GAMBLE_TURN and hq is not None
                        and (hq.level - _ehl0) >= DENY_GAMBLE_GAP and on_hq == 0 and not _fortress
                        and home_safe and not _behind_hq)
        if hq_crush or _deny_gamble:
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
        if (bool(PRESSURE) and _harass_now and turn >= PRESSURE_TURN and not _fortress
                and (not _behind_hq or _offense_dominant)
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
        if (bool(EARLY_RAID) and (_econ_lead or bool(PULSE)) and _harass_now and not _fortress
                and EARLY_RAID_TURN <= turn < PRESSURE_TURN):
            want_spare = max(want_spare, EARLY_RAID_FORCE)
        # PULSE (userbot pack #2): standing small-squad funding, NO econ_lead / not-behind gates -- the
        # bracket losses prove "only raid from a lead" = never raiding at all when it matters. Rides
        # want_spare, which the affordability loop still trims below the banked HQ upgrade (hq_reserve /
        # _bank_climb untouched) -> the climb keeps absolute gold priority; this only stops us DISBANDING
        # the pulse squad the moment we fall behind.
        if (bool(PULSE) and _harass_now and turn >= PULSE_TURN and not _fortress and on_hq == 0):
            want_spare = max(want_spare, PULSE_FORCE)
        if (_harass_now and turn >= PRESSURE_TURN and not _fortress
                and (not _behind_hq or _offense_dominant)):
            want_spare = max(want_spare, CRACK_FORCE)
        if (BOT.raid_lock > 0 and on_hq == 0 and hq.level >= HARASS_HQLEVEL
                and (not _behind_hq or _offense_dominant)):
            want_spare = max(want_spare, CRACK_FORCE)
        # WIDE-MAP SUPPRESSION (the gamble): on a wide map, while we hold the economic lead, fund a REAL
        # sustained attacking fist (not the 6-12 chip) so the backdoor continuously razes the enemy economy
        # and starves its army/climb -- the old code's 129-siege behaviour. Rides want_spare (TRUE surplus on
        # top of the worker/garrison need) and is still trimmed by the L5-climb reserve, so our own HQ keeps
        # maxing in parallel (the old code reached L5 AND razed). K-gated -> compact 7/8 never fund this.
        if BOT.deny_mode:
            # K-scaled fist: base WIDE_FORCE up to the anchor (K15 = game 4, untouched), +STEP per extra
            # stronghold beyond it. The biggest maps (K19/game 5) dilute a fixed fist across a huge spread
            # while the enemy out-produces -> they need a proportionally larger sustained force to land the
            # razing that denies the enemy's L5.
            _wide_force = WIDE_FORCE + max(0, M.K - WIDE_FORCE_ANCHOR) * WIDE_FORCE_STEP
            want_spare = max(want_spare, _wide_force)
        # WIN-PUSH: a DECISIVE territory lead + safe home -> fund a real army surplus (out-produce the
        # enemy). enemy_base_regs/_behind_hq/_fortress/home_safe are all in scope here. The reserve-drop
        # below then frees the gold so this surplus actually trains (instead of banking idle for L5).
        _winning = (bool(WIN_PUSH) and home_safe and turn >= PRESSURE_TURN
                    and hq is not None and not _behind_hq and not _fortress
                    and len(enemy_base_regs) >= WIN_ENEMY_BASES
                    and (len(my_bases) - len(enemy_base_regs)) >= WIN_BASE_LEAD)
        if _winning:
            want_spare = max(want_spare, WIN_FORCE)
        # WIDE INCOME-PUSH (user's strategy): on the widest maps a dominant income makes our L5 assured, so
        # convert the would-be climb-hoard into army that smashes the enemy economy. Hard-gated K>15 so
        # compact 7/8 (K9) and game 4 (K15) are untouched (their out-climb banking is preserved). not_behind_hq
        # /not_fortress/home_safe keep it off when trailing the climb or under threat -> tiebreak-safe.
        # Two guards (from the original WIN_PUSH): the enemy must hold a REAL economy worth denying
        # (enemy_base_regs >= WIN_ENEMY_BASES), AND we must NOT already be 2+ HQ levels ahead -- against a
        # low-economy RUSHER A out-climbs to a clean win, so dropping the climb reserve to build an army with
        # nothing to raze would only forfeit that out-climb into a draw (K19-rush regression). In game 5 A
        # trails/ties B's climb (never 2+ ahead) and B holds 9 bases, so both guards pass.
        _wide_push = (bool(WIDE_PUSH) and M.K > WIDE_FORCE_ANCHOR and home_safe and turn >= DENY_TURN_WIDE
                      and hq is not None and not _behind_hq and not _fortress and _income_lead
                      and len(enemy_base_regs) >= WIN_ENEMY_BASES and hq.level - _ehl0 <= 1)
        if _wide_push:
            # GAP-SCALED FORCE (user's "중반 이후 턴골드 차이 확 벌어지면 병력 더 뽑자"): grow the fist in
            # proportion to how far our per-turn income (work_cap) leads the enemy's, beyond the trigger
            # margin -- capped (WIN_GAP_CAP) so a runaway lead cannot train an unaffordable army. Already
            # self-limited by train affordability + upkeep, and only fires under the _wide_push guards.
            _gap_force = min(WIN_GAP_CAP, max(0, _my_workcap0 - _enemy_workcap - WIN_INCOME_MARGIN) * WIN_GAP_FORCE)
            want_spare = max(want_spare,
                             WIDE_FORCE + max(0, M.K - WIDE_FORCE_ANCHOR) * WIDE_FORCE_STEP + _gap_force)
        # DOMINATE_PUSH (R14, game 4/6 draw fix): the K11-15 twin of _wide_push. When the enemy answers our
        # income lead by TECHING (banking gold into its own base/HQ upgrades) rather than massing army,
        # _climb_push below never fires (it needs enemy_total >= bases + CLIMB_ENEMY_ARMY) and _wide_push
        # never fires (K>15), so we coast -- banking our own income into a parallel L3->L5 climb while the
        # enemy techs to L5 too -> both-L5 draw (agg_probe on 4(2)/6(2): deny=T, want_spare=16, but train=0
        # because hq_reserve soaks all the gold). This drops that reserve so the income surplus TRAINS the
        # deny fist instead of banking idle, and gap-scales it to the income lead. Gated on the SAME
        # _income_lead margin (+2 work_cap) as _wide_push so it only fires once our per-turn gold DECISIVELY
        # leads -- the exact discriminator vs the g7/g8 games that disabled WIN_PUSH (there income was even/
        # behind, so dropping the reserve starved the climb). not_behind_hq + hq.level-_ehl0<=1 keep it off
        # when we trail the climb or already out-climb a rusher 2+ levels (there we bank the clean win).
        # The opportunistic HQ upgrade (section 1, ABOVE training in section 3) still buys L5 first whenever
        # gold crosses the bar, so an income lead reaches L5 AND fields the fist. K9 (7/8) stays OUT (>=WIDE_K).
        _dominate_push = (bool(DOMINATE_PUSH) and WIDE_K <= M.K <= WIDE_FORCE_ANCHOR and home_safe
                          and turn >= DENY_TURN and hq is not None and not _behind_hq and not _fortress
                          and _income_lead and len(enemy_base_regs) >= WIN_ENEMY_BASES
                          and hq.level - _ehl0 <= 1)
        if _dominate_push:
            _dom_gap = min(WIN_GAP_CAP, max(0, _my_workcap0 - _enemy_workcap - WIN_INCOME_MARGIN) * WIN_GAP_FORCE)
            want_spare = max(want_spare, WIDE_FORCE + _dom_gap)
        # BEHIND_PUSH (EXPERIMENT, see flag block): the user's "punish a greedy over-expander with an out-trained
        # timing attack". Fires when BEHIND on bases (they out-expanded) but the enemy is LIGHT on operational army
        # (enemy_total-workcap small = economy not yet converted) AND we can still out-field them now (a real timing
        # window). home_safe-gated (rush-safe). Funds+commits BEHIND_PUSH_FORCE via the reserve drop below.
        _behind_push = (bool(BEHIND_PUSH) and home_safe and turn >= DENY_TURN and turn < BEHIND_PUSH_MAX
                        and hq is not None and not _behind_hq and not _fortress
                        and len(enemy_base_regs) > len(my_bases) + TERRITORY_SLACK
                        and max(0, enemy_total - _enemy_workcap) <= BEHIND_PUSH_ENEMY_ARMY
                        and enemy_total <= len(my_warriors) + BEHIND_PUSH_SLACK)
        if _behind_push:
            want_spare = max(want_spare, BEHIND_PUSH_FORCE)
        # CLIMB-LEAD PUSH (game 6): on the BOUNDARY band (WIDE_K..WIDE_FORCE_ANCHOR = K11-15), once we hold a
        # DECISIVE HQ lead, fund a standing army to PIN the enemy instead of coasting -- denying its catch-up
        # climb. Does NOT touch the climb reserve (we keep our own lead). K9 excluded (out-climb wins); K17+
        # is _wide_push's zone; K15 never reaches a 2-level lead -> all byte-identical.
        # Fire EARLY on the small map -- whenever we are NOT behind on HQ and hold base PARITY-or-better
        # (not a 2-level lead, which only arrives at t120+ AFTER the army drought already lost the game).
        # This keeps a pin army up from the mid-opening, exactly like the old winning code (continuous army
        # t40-179). Game 4 (K15) and K9 (7/8) excluded by the K-band.
        # ADAPTIVE pin (the user's vision): fire EARLY (not_behind + base parity, so we keep an army up from
        # mid-opening like the old winning code) BUT ONLY against a REACTIVE/army-investing opponent
        # (enemy army >= bases + CLIMB_ENEMY_ARMY) -- a pure economy-turtle never trips it, so we just out-climb
        # it with no wasted army (memory: pinning an economist loses 12/12). not_behind/parity are the back-off:
        # the instant the opponent out-climbs or out-bases us, the pin drops and we revert to climbing/defending.
        # ...and NOT while out-economied (_smallmap_econ): when behind on income the army surplus FREEZES the
        # economy that decides the tiebreak (forensic 6(1): wc7 vs wc11 -> draw), so we drop the offensive pin
        # (want_spare + _pin_floor both off) and pour the freed gold into base economy via 1d above. The pin
        # re-engages the instant our income passes the enemy's (then _smallmap_econ is False).
        _climb_push = (bool(CLIMB_PUSH) and WIDE_K <= M.K < WIDE_FORCE_ANCHOR and home_safe
                       and turn >= PRESSURE_TURN and hq is not None and not _fortress
                       and not _behind_hq and not _smallmap_econ
                       and len(my_bases) >= len(enemy_base_regs)
                       and len(enemy_base_regs) >= WIN_ENEMY_BASES
                       and enemy_total >= len(enemy_base_regs) + CLIMB_ENEMY_ARMY)
        if _climb_push:
            want_spare = max(want_spare, CLIMB_FORCE)
        # V2R12 OPS_MATCH (1(15), see flag block): the user's rule -- COUNT the enemy's OPERATIONAL army
        # (total warriors minus its income-worker need = enemy_total - _enemy_workcap) and field at least
        # that many spares BEFORE the rush launches. The off-building _en_ops8 count only spikes at launch
        # (g15 0->8 at t56, too late); the surplus measure grew 3->8 across t43-54 (13 turns of warning).
        # Placed among the want_spare floors so the REL_ARMY/ENDGAME min-trims still win vs a CONTAINED army
        # or annihilated remnant. Same back-off as every sibling floor: home_safe (the buildup window; once
        # the wave CONTACTS, defenders_needed/total_need matches it) and (not _behind_hq or _offense_dominant)
        # (trailing the HQ climb -> bank it, never pin spares -- the starvation that lost these games).
        # ...but ONLY when that operational army actually EXCEEDS our own fielded spare (we are being
        # out-fielded, the g15 rush-buildup). Against a turtle we keep pace with, enemy surplus <= our spare
        # so this stays inert and we OUT-CLIMB instead of pinning an economist (memory: matching a contained
        # economist loses the climb). our_spare = warriors above the worker/garrison need = total_need.
        _op_surplus = max(0, enemy_total - _enemy_workcap)
        _our_spare = max(0, len(my_warriors) - total_need)
        if (bool(OPS_MATCH) and M.K <= WIDE_FORCE_ANCHOR   # K17+ = proven deny doctrine, byte-identical
                and turn >= OPS_TURN and home_safe and not _fortress
                and (not _behind_hq or _offense_dominant)
                and _op_surplus >= OPS_MIN and _op_surplus > _our_spare):
            want_spare = max(want_spare, min(OPS_CAP, _op_surplus))
        # REL-ARMY (user's relative-military rule): the enemy's army is CONTAINED (we match-or-exceed its total
        # and it is not massing a deathball) and we are safe, income-ahead, and not trailing the climb -> we do
        # NOT need to keep funding a big offensive fist. Trim want_spare to a lean cap so the freed gold banks
        # and 1d PRESS_ECON turns it into L2 income. OFFENSIVE-only: total_need (workers + matched garrison) is
        # untouched below, so the rush/assault defense is byte-identical. Off the instant the enemy out-arms us.
        _army_contained = (bool(REL_ARMY) and turn >= PRESSURE_TURN and home_safe
                           and hq is not None and not _behind_hq and not _fortress
                           and _my_workcap0 > _enemy_workcap and not _outproduced
                           and enemy_total <= len(my_warriors) + REL_ARMY_MARGIN)
        if _army_contained:
            want_spare = min(want_spare, REL_ARMY_SPARE_CAP)
        # RUSH_SNOWBALL (see flag block): the user's SAFE L2 window -- rush succeeded (base lead) AND the enemy's
        # counter is spent (op_army low) AND home-safe/not-behind/early-mid. Unlike REL_ARMY this does NOT require
        # income-ahead (the g5 chicken-egg), so it fires when we are income-behind-but-base-ahead. Cap the army so
        # the ~40-body over-investment (want_spare 44 vs a 2-army enemy) frees up for L2. Self-lifts when the enemy
        # re-arms (op_surplus rises past the gate). total_need (workers + matched garrison) untouched -> rush-safe.
        _snowball = (bool(RUSH_SNOWBALL) and turn >= PRESSURE_TURN and turn <= SNOWBALL_UNTIL
                     and home_safe and hq is not None and not _behind_hq and not _fortress
                     and len(my_bases) > len(enemy_base_regs)
                     and _op_surplus <= SNOWBALL_EN_OP and BOT.park_streak >= SNOWBALL_PARK_MIN)
        if _snowball:
            want_spare = min(want_spare, SNOWBALL_SPARE_CAP)
        # ENDGAME FINISH-PUSH (userbot step2, arm 2): vs an annihilated remnant the marginal 120g body adds
        # nothing -- the freed-worker fist already dwarfs them -- but the same gold IS the HQ-level tiebreak
        # (7.txt drew a 13v5 total-domination game 50 gold short of L3). Cap the spare; 1c banks the climb.
        if (bool(ENDGAME_FINISH) and turn >= FINISH_TURN and home_safe and on_hq == 0
                and len(enemy_base_regs) <= ENDGAME_REMNANT_BASES
                and len(my_warriors) >= ENDGAME_DOM_F * max(1, len(enemy_warriors))):
            want_spare = min(want_spare, ENDGAME_SPARE_CAP)
        # ENDGAME FINISHER (see flag block): once OUR L5 is INCOME-GUARANTEED by the t190 horizon -- banked gold
        # + net income over the remaining turns (net of the fielded army's upkeep + a per-turn move/command bill
        # + a buffer) covers the remaining climb WITH the operating reserve intact -- ARM a K-scaled deny fist so
        # the live crack-aware backdoor razes B's income bases through the endgame. Replaces the broken FINAL_RUSH
        # (sized want_spare but never deployed; fired only at _is_max ~t182, too late for the t150-182 coast).
        # Winning-only: home_safe + climb-ahead (not behind on HQ level) + enemy still sub-L5, on the K19 map.
        # The FUNDING half (reserve-free but bounded to the income-secured surplus above the climb) is the
        # worker_deficit floor below; the SIZE half is here (placed AFTER every spare cap so it overrides coast).
        # CLIMB_TO_WIN (1(38), see flag block): when the NEXT level alone already beats the enemy's HQ,
        # the bank target is that ONE upgrade, not the full remaining L5 climb -- the 7200 whole-climb sum
        # made _income_secured unsatisfiable at a negative net while ONE 1200g L3 won the tiebreak outright.
        _fin_climb_left = 0 if (hq is None or _is_max(hq)) else (
            HQ_LEVELS[hq.level + 1].upgrade_cost
            if (bool(CLIMB_TO_WIN) and M.K <= CTW_K_MAX and hq.level + 1 > _ehl0) else sum(
                HQ_LEVELS[lv].upgrade_cost for lv in range(hq.level + 1, HQ_MAX_LEVEL + 1)))
        _fin_horizon = max(0, ALLIN_TURN - turn)                        # bank window closes at the t190 all-in
        _fin_gross = WORK_INCOME * min(len(my_warriors), _my_workcap0)  # workcap-capped gross income / turn
        _fin_hold = max(len(my_warriors), total_need + FIN_FORCE)       # army we intend to maintain (upkeep basis)
        _fin_net = (_fin_gross - UPKEEP_PER_WARRIOR * _fin_hold
                    - MOVE_COST * FIN_MOVE_UNITS - GOLD_FLOOR)          # conservative per-turn net gold
        _income_secured = ((S.gold - spent) + _fin_net * _fin_horizon) >= (_fin_climb_left + reserve)
        # NO _income_lead gate: game 5's B OUT-EARNS proto, so income-lead would never fire here; g7/g8
        # (even-income draws that must not push) are K9 = already excluded by the K19 gate below.
        _climb_ahead = (hq is not None and not _behind_hq and (_is_max(hq) or hq.level >= _ehl0))
        _endgame_finish = (bool(ENDGAME_FINISHER) and home_safe and not _fortress and on_hq == 0
                           and hq is not None
                           and (M.K > WIDE_FORCE_ANCHOR or bool(FIN_COMPACT))   # FIN_COMPACT: 1(41) K9
                           and turn >= FIN_START_TURN and _climb_ahead
                           and _ehl0 < HQ_MAX_LEVEL and len(enemy_base_regs) > 0
                           and (_is_max(hq) or _income_secured))
        if _endgame_finish:
            _fin_force = min(FIN_CAP, FIN_FORCE + max(0, M.K - WIDE_FORCE_ANCHOR) * WIDE_FORCE_STEP)
            want_spare = max(want_spare, _fin_force)
        # CLIMB_TO_WIN spare cap (1(38), see flag block): home-safe, level-lead-or-tie endgame with NO armed
        # finisher -> the climb bank IS the winning move; the spare army yields to it. INCOME_FLOOR/READY_
        # FLOOR wallets go inert automatically (target_army drops below len(my_warriors)) so the freed gold
        # actually banks the upgrade instead of re-training the surplus.
        # STALLED-CLIMBER discriminator (turtle-K19 regression fix): only cap when the ENEMY's HQ climb has
        # been stalled >= CTW_STALL_TURNS -- 1(38)'s B sat at L2 for 120+ turns (one banked level wins), but
        # an ACTIVELY climbing enemy (turtle) still needs the deny fist or it rides the freed pressure to L5.
        if _ehl0 > getattr(BOT, 'ctw_ehl', 1):
            BOT.ctw_ehl = _ehl0
            BOT.ctw_ehl_turn = turn
        if (bool(CLIMB_TO_WIN) and M.K <= CTW_K_MAX
                and not _endgame_finish and home_safe and not _behind_hq
                and hq is not None and not _is_max(hq) and hq.level >= _ehl0
                and turn >= FIN_START_TURN
                and turn - getattr(BOT, 'ctw_ehl_turn', 0) >= CTW_STALL_TURNS):
            want_spare = min(want_spare, CTW_SPARE_CAP)
        # DEAD_OPPONENT_MARCH economy guard (see flag block): an annihilated remnant needs only a small
        # walkover fist -- stop funding CRACK_FORCE-sized spares the starved economy cannot feed (1(40):
        # 14 bodies on a workcap-2 economy = +2g/turn = neither the 600g climb nor the move bill ever fund).
        if (bool(DEAD_OPPONENT_MARCH) and len(enemy_base_regs) == 0
                and len(enemy_warriors) <= DEAD_OPP_MAXW):
            want_spare = min(want_spare, DEAD_OPP_SPARE)
        # MIL_GAMBIT spare cap (see flag block): while latched the raid is OFF, so bodies beyond the
        # garrison total_need just idle at home while the 600g L2 (train_cap/work_cap/turret all scale)
        # goes unbanked -- measured t100-120: want_spare-driven trains burned the lead to gold 165 max,
        # L2 never bought, then the idle army bled back to 0. The garrisons live in total_need.
        if _mg_on:
            want_spare = min(want_spare, MG_SPARE_CAP)
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
        # V2 INCOME-FLOOR (g7, see flag): with income >= INCOME_RATIO x the enemy's and a latched
        # threat, a rich economy buys SUPERIORITY, not parity -- army target = enemy total + edge +
        # base-worker need. The wallet half lives at the worker_deficit floors below.
        _income_floor = (bool(INCOME_FLOOR) and BOT.threat_army > 0
                         and stack_reg >= 0 and enemy_stack_sz >= WAVE_STACK_MIN
                         and _my_workcap0 >= INCOME_RATIO * max(1, _enemy_workcap)
                         # V2R3 INC_PARKFIX (5(1)): a garrison PARKED on the enemy's own HQ and not
                         # advancing is not a live threat (FLEE_FIX doctrine) -- it must not hold the
                         # reserve-free surplus pump open (34 dead-pulse retrains = 4080g pre-empted the
                         # L3 climb bank all endgame). The moment it steps off / closes distance, the
                         # pump re-opens.
                         and not (bool(INC_PARKFIX) and stack_reg == M.opp_hq
                                  and not _stack_advancing))
        if _income_floor:
            target_army = max(target_army,
                              min(max(MOBILIZE_CAP, MATCH_TOTAL_CAP),
                                  len(enemy_warriors) + INCOME_EDGE
                                  + max(0, total_need - need[M.my_hq])))
        # V2R13 READY_FLOOR (games 4/6, see flag block): the user's mid-game military-readiness rule --
        # while we hold the advantage (home safe, not trailing the HQ race) keep at least the enemy's
        # OPERATIONAL army (_op_surplus = enemy_total - workcap) fielded, so the climb-bank window cannot be
        # punished by a surprise assault. A FLOOR (reach parity -> stop -> bank), reserve-free funded below,
        # self-correcting via not_behind_hq. Distinct from INCOME_FLOOR (which needs a 10-stack + 1.5x income)
        # -- this fires on the enemy's total operational count with no wave required. K<=15 (wide maps keep
        # the deny/ANTIBOOM doctrine).
        _ready_target = 0
        _ready_floor = (bool(READY_FLOOR) and M.K <= WIDE_FORCE_ANCHOR and turn >= READY_TURN
                        and home_safe and on_hq == 0 and not _fortress
                        and hq is not None and not _behind_hq
                        and _op_surplus >= READY_MIN)
        if _ready_floor:
            _ready_target = min(max(MOBILIZE_CAP, MATCH_TOTAL_CAP),
                                _my_workcap0 + min(READY_CAP, _op_surplus + READY_EDGE))
            target_army = max(target_army, _ready_target)
        # ANTI-BOOM ARMY RAMP (S2): a SPREAD out-producer never trips mil_switch, so the block above
        # leaves target_army frozen while the enemy booms (real losses 1(1)/1(2): our army stuck at 14
        # vs 44, we razed it 0 all game). When _outproduced fires (>=1.6x = a real deathball, never a
        # ~1:1 mirror/turtle) on a WIDE map, ramp toward the enemy total so we can defend our economy AND
        # feed _harass_now. Self-limiting: catching up to <1.6x turns _outproduced off (no spiral). The
        # train loop below trims by can()/hq_reserve, so the climb + worker income are never starved.
        if bool(ANTIBOOM) and _outproduced and M.K > WIDE_FORCE_ANCHOR:
            _boom_base_need = total_need - need[M.my_hq]
            _boom_tgt = min(MATCH_TOTAL_CAP, len(enemy_warriors)) + _boom_base_need
            target_army = max(target_army, min(max(MOBILIZE_CAP, MATCH_TOTAL_CAP), _boom_tgt))
        # MIL_GAMBIT parity floor (see flag block): the latched gambit traded economy for army -- match his
        # total (+edge) NOW with the gold the claim freeze liberated. Composes via max() like its siblings;
        # funded reserve-free at the wallet below.
        _mg_target = 0
        if _mg_on and len(enemy_warriors) > len(my_warriors):
            # BEHIND only: at parity the garrison total_need alone holds the line and every further body
            # would eat the L2 bank -- the level (turret/hp/train_cap/work_cap all double) outranks a
            # spare body once the hold rule is satisfied.
            _mg_target = min(max(MOBILIZE_CAP, MATCH_TOTAL_CAP),
                             len(enemy_warriors) + MG_EDGE + max(0, total_need - need[M.my_hq]))
            target_army = max(target_army, _mg_target)
        # R51 HQ-TIMING WINDOWS (see flag block): inside either wallet-empty window (ours = guard the
        # probe, his = punish the lag) the army floors to his count + edge; funded on the upkeep-lean
        # bar in the train loop below and EXPIRES with the window (the L2_WATCH climb-bank scar).
        if _l2f_win or _l2p_win or _oxp_win:
            target_army = max(target_army,
                              min(MATCH_TOTAL_CAP, len(enemy_warriors) + L2WIN_EDGE))
        # EXPAND_ESCORT (R66): restore available-army PARITY only ("상대 가용인원만큼") -- floor by the
        # measured deficit, never the total-matching L2WIN form (enemy TOTAL includes its seated workers).
        if _ee_win:
            target_army = max(target_army,
                              min(MATCH_TOTAL_CAP, len(my_warriors) + _ee_def))
        # CONSOLIDATE_ARMY (R73, see flag block): HQ climbed to a defensible level + land-dominant -> floor the
        # army at the enemy's TOTAL so idle gold becomes troops ("다량 찍어내기 / 굳히기"). Capped MOBILIZE_CAP;
        # the climb reserve + upkeep-lean guards below keep the L4/L5 climb and income intact.
        _consol = (bool(CONSOLIDATE_ARMY) and hq is not None and hq.level >= CONSOL_HQ and on_hq == 0
                   and len(my_bases) >= sum(1 for _b in S.buildings
                                            if _b.side is not me and _b.type is BType.BASE) + CONSOL_BASE_LEAD
                   and (enemy_total - _enemy_workcap) >= CONSOL_EN_MIN)
        if _consol or _mxa:   # R76: mid-game avail-deficit also floors the army at the enemy's total ("기지=인원")
            target_army = max(target_army, min(MOBILIZE_CAP, enemy_total))
        # V2R8 ZERO_OPS_CLIMB (4.txt, see flag): an enemy that has fielded ZERO operators for
        # ZERO_OPS_STREAK straight turns cannot spend our fist's time -- open the climb bank early; the
        # streak resets (bank drops back to the fist) the turn any enemy body steps off a building.
        _zero_ops_bank = (bool(ZERO_OPS_CLIMB) and turn >= ZERO_OPS_TURN
                          and BOT.zero_ops_streak >= ZERO_OPS_STREAK
                          and home_safe and on_hq == 0
                          # V2R9 ZOPS_DENY_GUARD (g5, see flag): an armed K-scaled deny fist outranks the
                          # early bank -- the zero-ops economist is exactly the fist's prey (2 trains in a
                          # 40-turn deny window was the whole loss).
                          and not (bool(ZOPS_DENY_GUARD)
                                   and M.K > WIDE_FORCE_ANCHOR and BOT.deny_mode))
        # MIL_GAMBIT: parity reached under a latched gambit -> bank the next HQ level immediately (L2
        # doubles train_cap = the structural counter to a stream rusher). The enemy-tempo climb windows
        # stay closed against a masser, which is exactly when the unlock matters most.
        _mg_parity_bank = (_mg_on and hq is not None and not _is_max(hq)
                           and len(my_warriors) >= len(enemy_warriors) - 1
                           # L2_WATCH (R46): while the watch holds the L1->L2 buy, do not silently
                           # re-bank the 600 it just freed (the follow-train doctrine owns that gold;
                           # the bank resumes the moment the watch releases).
                           and not _l2w_hold)
        # PARITY_CLIMB (R42, see flag block): own-HQ stall detector + the mid-game wedge. The tracker runs
        # unconditionally (state only -- no decision reads it while the flag is 0).
        if hq is not None and hq.level != getattr(BOT, 'pc_lvl', -1):
            BOT.pc_lvl = hq.level
            BOT.pc_lvl_turn = turn
        _pc_on = (bool(PARITY_CLIMB) and hq is not None and not _is_max(hq)
                  and turn >= PC_TURN and turn - getattr(BOT, 'pc_lvl_turn', 0) >= PC_STALL
                  and not _behind_hq and not _mg_on
                  and not _l2w_hold
                  and on_hq == 0 and not concentrate
                  and not (stack_reg >= 0 and enemy_stack_sz >= WAVE_STACK_MIN
                           and (_stack_advancing or stack_dist <= gate))
                  and not (M.K >= WIDE_FORCE_ANCHOR and BOT.deny_mode))
        # PARITY_CLIMB GIVE-UP VALVE (R42 isolation: grinder/swarm K13 seeds 2006/2009/2011): on a POVERTY
        # map (both HQs L1 all game, ~10 trains total) the wedge can freeze training forever while the move
        # bill eats the tiny income -- the bank NEVER fills, and the one suppressed body was the HQ kill
        # (3 HQ_DESTROYED wins -> both-L1 draws). If the wedge has been armed PC_GIVEUP turns on the SAME
        # level and the bank shows no real progress (gold gained < half the step AND still short of it),
        # the wedge is not converting on this map: stand down for this level (re-arms after a level-up).
        # 1(44)/1(46) both bank at 40-95g/turn -> pass the progress test untouched (verified).
        if _pc_on:
            if getattr(BOT, 'pc_arm_lvl', -1) != hq.level:
                BOT.pc_arm_lvl = hq.level
                BOT.pc_arm_turn = turn
                BOT.pc_arm_gold = S.gold
            elif (turn - BOT.pc_arm_turn >= PC_GIVEUP
                  and S.gold < _next_cost(hq)
                  and (S.gold - BOT.pc_arm_gold) < _next_cost(hq) // 2):
                BOT.pc_dead_lvl = hq.level
                BOT.pc_dead_gold = S.gold
        if hq is not None and getattr(BOT, 'pc_dead_lvl', -1) == hq.level:
            # PC_REARM (R45, 7(1) ladder forensic): the give-up verdict is "this map is poverty", but a
            # WAR-starved bank reads the same as a poor one -- 7(1) armed t83, the enemy's wave cycle ate
            # the bank, the valve latched dead at t131 (gold 185), and when the map went QUIET afterward
            # gold recovered 185->990 with the wedge permanently off -> L3 only at t177 vs the enemy's
            # t161. The latch is a one-way door per level; give it the SAME progress test the valve used:
            # once gold has gained half the step since the death verdict, the poverty diagnosis is
            # disproven -> re-arm fresh. True poverty maps (grinder/swarm K13 seeds) never gain half a
            # step after death, so they stay stood-down untouched. PC_REARM=0 => decision-identical.
            if (bool(PC_REARM) and _pc_on
                    and S.gold - getattr(BOT, 'pc_dead_gold', 0) >= _next_cost(hq) // 2):
                BOT.pc_dead_lvl = -1
                BOT.pc_arm_lvl = -1
            else:
                _pc_on = False
        if ((turn >= LATE_CLIMB or _hq_climb_window or _zero_ops_bank or _mg_parity_bank or _pc_on) and hq is not None
                and not _is_max(hq) and (not concentrate or (_behind_hq and on_hq == 0))
                and not (losing and COUNTER_DROP)):
            # [BUGFIX #3 MEDIUM] `and not (losing and COUNTER_DROP)`: the block above drops hq_reserve to 0
            # when losing (COUNTER_DROP: feed the gold to a counter-army instead of banking the climb). But
            # this line re-banked it one statement later -- and `losing` implies `_behind_hq`, which opens
            # `_hq_climb_window`, so the restore ALWAYS fired and COUNTER_DROP was a dead knob (no counter-
            # army ever funded). Mirroring the guard here makes COUNTER_DROP actually divert the gold.
            hq_reserve = max(hq_reserve, _next_cost(hq))
        # V2R6 OUTMASSED_DROP (1(6) t89+): income-BEHIND + genuinely out-produced + already losing bases
        # = the climb bank is DEAD CAPITAL (banked 1358 toward an unreachable 2400 while 11-20-stacks
        # rolled every base). Ramp toward the enemy total (ANTIBOOM without its K>15 gate) and drop the
        # reserve -- deterrence over a bank that buys nothing. Self-limiting (_outproduced clears on
        # catch-up); income-ahead or base-intact games never enter.
        _om_drop = (bool(OUTMASSED_DROP) and ((_outproduced and _um_pressing) or _outmassed_soft)
                    and (_my_workcap0 < _enemy_workcap
                         or (bool(OM_MASS_OR_INCOME)   # V2R9: 2x-margin deficit = pressure either way
                             and enemy_total >= len(my_warriors) + 2 * OUTMASSED_SOFT_MARGIN))
                    and BOT.my_base_lost >= 1
                    and hq is not None)
        if _om_drop:
            _om_base_need = total_need - need[M.my_hq]
            target_army = max(target_army,
                              min(max(MOBILIZE_CAP, MATCH_TOTAL_CAP),
                                  min(MATCH_TOTAL_CAP, enemy_total) + _om_base_need))
            hq_reserve = 0
            _pc_on = False   # PARITY_CLIMB yields to the outmassed survival ramp (dead-capital doctrine)
        deficit = target_army - len(my_warriors)
        n = max(0, min(cap, deficit))
        # WORKERS FIRST: the warriors filling the economy/garrison need WORK and pay for
        # themselves (+13/turn net), so the HQ-climb reserve must NEVER freeze them -- starving
        # workers starves the income that funds the climb itself, the exact self-defeating stall
        # that froze a poor compact map at 6 warriors (banked 3600g for L5 while income stayed
        # ~90g/turn -> never climbed, never massed). The reserve only gates the OFFENSIVE surplus
        # BEYOND the worker/garrison need; workers are funded down to the base reserve.
        worker_deficit = max(0, min(cap, total_need - len(my_warriors)))
        # V2 EXPAND-RHYTHM: scheduled claimers are funded like WORKERS (reserve-free) -- a claimer
        # becomes a base (+15/turn within ~13 turns' payback), so freezing it behind the climb bank
        # is the exact 3rd-base stall. Applies only while behind schedule, never under a rush brake.
        if _expand_lag and on_hq == 0:
            worker_deficit = min(cap, worker_deficit + _sched_deficit)
        # V2 INCOME-FLOOR wallet (g7): the surplus army of a rich economy is funded reserve-free -- the
        # income literally pays for it (>=1.5x work capacity vs 2g/turn upkeep). Without this the climb
        # reserve froze training at 4 bodies vs 11 while we out-earned the enemy 3.8x.
        if _income_floor and on_hq == 0:
            worker_deficit = min(cap, max(worker_deficit, target_army - len(my_warriors)))
        # V2R13 READY_FLOOR wallet (see flag block): fund the readiness army RESERVE-FREE so it actually
        # trains during the climb-bank window (up to the readiness target only, not the offensive want_spare
        # above it). The climb still banks from income above; train_cap keeps it gradual.
        if _ready_floor and on_hq == 0:
            worker_deficit = min(cap, max(worker_deficit, _ready_target - len(my_warriors)))
        # MIL_GAMBIT wallet (see flag block): fund the parity army RESERVE-FREE up to the parity target --
        # bodies first while the gambit presses; the climb bank re-engages via _mg_parity_bank at parity.
        if _mg_on and on_hq == 0:
            worker_deficit = min(cap, max(worker_deficit, _mg_target - len(my_warriors)))
        # ENDGAME FINISHER wallet (see flag block): fund the deny fist RESERVE-FREE, but ONLY the bodies income
        # can afford ABOVE the reserved remaining climb, so proto's own L5 always banks (never stranded). This is
        # the DEPLOYMENT fix: post-t150 the offensive want_spare bodies (n > worker_deficit) could no longer clear
        # hq_reserve on proto's thin gold -> raid_force starved to empty -> the live deny branch had nothing to
        # march. Raising worker_deficit funds them reserve-free, refilling surplus -> raid_force next turn. Bounded
        # by _fin_afford (the SAME income-secured projection as the fire gate): self-limiting as turn->ALLIN_TURN
        # (horizon->0 -> afford->0 -> gold banks the climb -> L5 lands ~t185-190). Post-L5 hq_reserve is already 0
        # so the full want_spare funds without this. Mirrors the READY_FLOOR wallet above; workers funded first.
        if _endgame_finish and on_hq == 0:
            _fin_afford = max(0, ((S.gold - spent) + _fin_net * _fin_horizon
                                  - _fin_climb_left - reserve) // TRAIN_COST)
            worker_deficit = min(cap, max(worker_deficit,
                                          min(target_army - len(my_warriors), _fin_afford)))
        # WIN-PUSH reserve-drop: while we are decisively winning (and before the LATE_BACKSTOP, after which
        # we re-bank to guarantee L5 by t200), the OFFENSIVE surplus is funded WITHOUT holding the climb
        # reserve -- so the army actually grows and denies the enemy. The climb still advances in 1c
        # opportunistically and is fully restored from LATE_BACKSTOP / the instant _winning drops (enemy
        # catches up on HQ level), so the day-200 tiebreak is never forfeited. Workers are funded first
        # regardless (worker_deficit), exactly as before -- compounding is untouched.
        # V2R9 DEAD_BANK_RELEASE (g5 t172, see flag): a bank the arithmetic says cannot fill by t200 even
        # at HALF the ideal net rate (workcap income minus upkeep) is dead capital -- release it to bodies;
        # 1c still buys opportunistically if gold ever crosses the bar.
        # DEAD_BANK_HEALTHY (1(39), see flag block): the 0.5x haircut was tuned for the K19 income-BEHIND
        # g5 case; on compact income-healthy maps it declared a REACHABLE L5 bank dead (full-rate ~5672
        # bankable vs 3600 needed) and dumped the winning tiebreak lead into a useless home army. Compact
        # maps judge the bank at the FULL net rate.
        _dbr_f = 0.5 if (M.K > WIDE_FORCE_ANCHOR or not bool(DEAD_BANK_HEALTHY)) else 1.0
        _dead_bank = (bool(DEAD_BANK_RELEASE) and hq_reserve > 0
                      and hq is not None and not _is_max(hq)
                      and not _pc_on   # PARITY_CLIMB (R42): the wedge's own bank is never "dead" -- the rate
                                       # arithmetic below assumes the floor-trains keep draining, which is the
                                       # exact self-fulfilling release measured in 1(46) (35 dead-bank turns)
                      and (_next_cost(hq) + GOLD_FLOOR - (S.gold - spent))
                          > _dbr_f * max(0, WORK_INCOME * min(len(my_warriors), _my_workcap0)
                                         - UPKEEP_PER_WARRIOR * len(my_warriors))
                          * max(0, GAME_TURNS - turn))
        # MIL_GAMBIT: the WIN-PUSH reserve-drop assumes the spare army goes DENY something -- while latched
        # the raid is off, so the drop just fed the L2 bank to idle bodies. Keep the bank under a latch.
        _train_reserve = 0 if ((((_winning or _wide_push or _dominate_push or _behind_push)
                                 and turn < LATE_BACKSTOP and not _mg_on)) or _dead_bank) else hq_reserve
        # PIN FLOOR (game 6): fund a continuous CLIMB_FORCE army BELOW the climb reserve so we keep the pin army
        # up WHILE still banking the HQ climb ("천천히 찍으면서 HQ 레벨을 올리는"). Only active under the adaptive
        # _climb_push gate (reactive opponent), so an economist never triggers it. Workers funded first regardless.
        # PARITY_CLIMB (R42): the pin floor's own charter is to ride BELOW the climb bank ("천천히 찍으면서
        # HQ 레벨을 올리는") -- but CLIMB_FORCE(12) > train cap means it NEVER yields, and 1(44) measured it
        # funding every train reserve-free for 60+ turns while the L3 bank sat empty behind a 7-bases-vs-1
        # economy (DRAW a climb would have WON). While the wedge is armed the pin has demonstrably failed
        # to convert; the bank takes priority (the pin army persists by attrition, not retrain).
        _pin_floor = CLIMB_FORCE if (_climb_push and not _pc_on) else 0
        # GARRISON-PROOF CLIMB RESERVE (campaign fix #1): in a CALM climb state (window open, home_safe, no
        # committed wave, not fortress) protect the next HQ cost against the STANDOFF army -- i.e. cap the
        # reserve-free training at our economic work_cap (_econ_floor) instead of the full defensive garrison
        # (worker_deficit). Income workers (<= work_cap) are still funded first and NEVER frozen; only the
        # surplus standoff army beyond them yields to the climb, so the gold actually banks the upgrade. Drops
        # to the old behaviour the instant home is unsafe / a wave commits / fortress engages (assault defense
        # keeps full training). _my_workcap0 is our total building work_cap (income-worker capacity).
        # K<WIDE_FORCE_ANCHOR: on the WIDE maps (K15/K19 = eval games 4/5) the proven doctrine is aggressive
        # L5-DENIAL (deny_mode/WIDE_PUSH) -- banking the climb there instead of razing lets the enemy reach
        # L5 and turns a WIN into a DRAW (verified: campaign build diverged from the winning pre-campaign play
        # on g4/g5). Confine the campaign climb-reserve to the small/mid maps where the losses actually live.
        _bank_climb = (bool(BANK_CLIMB) and M.K < WIDE_FORCE_ANCHOR and hq is not None and not _is_max(hq)
                       and _hq_climb_window and home_safe and on_hq == 0 and not concentrate and not _fortress
                       and not _om_drop)   # V2R6: a dead-capital bank must not re-freeze the ramp
        # PARITY_CLIMB (R42): the wedge forces the same calm-climb wallet treatment (reserve-free training
        # capped at the ECON floor, reserve forced to the next HQ cost) even though window/home_safe are
        # closed -- that closed-window state is exactly where the four stalls lived (see flag block).
        _bank_climb = _bank_climb or _pc_on
        _econ_floor = max(0, min(cap, _my_workcap0 - len(my_warriors)))
        if _expand_lag and on_hq == 0:
            _econ_floor = min(cap, _econ_floor + _sched_deficit)   # V2: claimers pass the calm-climb reserve too
        if _income_floor and on_hq == 0:
            _econ_floor = min(cap, max(_econ_floor, target_army - len(my_warriors)))  # V2 INCOME-FLOOR
        if _ready_floor and on_hq == 0:
            _econ_floor = min(cap, max(_econ_floor, _ready_target - len(my_warriors)))  # V2R13 READY_FLOOR: pass calm-climb cap
        # In the calm climb state, (1) cap reserve-free training at economic work_cap so the standoff army
        # yields to the climb, and (2) FORCE the reserve to the next HQ cost even if COUNTER_DROP/mil_switch
        # zeroed hq_reserve -- that drop is meant for losing-UNDER-ASSAULT (divert gold to a counter-army),
        # but _bank_climb already excludes assault (home_safe, not concentrate, not fortress), so here the
        # right spend is the climb, not more bodies. Forensic g1_4 t89: hq_reserve was dropped to 0 exactly
        # as gold hit 1262 (16 short of L3), re-enabling training that drained it; forcing _next_cost holds
        # the bank one more turn -> the upgrade lands. Auto-reverts the instant the calm state ends.
        _res_floor = _econ_floor if _bank_climb else worker_deficit
        _res_amt = max(_train_reserve, _next_cost(hq)) if _bank_climb else _train_reserve
        while n > 0 and not can(TRAIN_COST * n + (_res_amt if n > _res_floor + _pin_floor else 0)):
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
        # TRAIN-RESCUE (userbot step1): with a LOW-LEVEL HQ (<= RESCUE_HQ_MAXLVL) the "wait until the
        # stack closes" rule below is a death sentence (see flag comment) -- a latched threat + army below
        # the garrison target is already the emergency. Bypass the distance/behind gates and train now.
        _rescue = (bool(TRAIN_RESCUE) and BOT.threat_army > 0 and hq is not None
                   and hq.level <= RESCUE_HQ_MAXLVL and len(my_warriors) < target_garrison)
        # V2R6 GRIND_RESCUE (1(3)/1(6)): a mid-game GRINDER (2-3-body waves, 2x total training, never a
        # 10-stack) inflates no garrison target, so the rescue never opened while our bases were ground
        # away and the L3 bank froze training. A latched _under_massed (real out-production) with a low
        # HQ is the same emergency -- open the rescue window (and its F2 lean affordability) there too.
        if (bool(GRIND_RESCUE) and bool(TRAIN_RESCUE) and not _rescue
                and (_under_massed or _outmassed_soft)   # V2R7 OUTMASSED_SOFT: sustained-deficit grinder arm
                and BOT.threat_army > 0 and hq is not None
                and hq.level <= RESCUE_HQ_MAXLVL and len(my_warriors) < target_army):
            _rescue = True
        # V2R6 RESCUE_GATE (1(5) G2, dead-branch bug): concentrate zeroes hq_reserve BEFORE this unlock,
        # making the rescue retrain + its F2 upkeep-only cushion unreachable exactly during the rush they
        # exist for (t13: gold 137 funded the 6th defender; the chip said 4hp). _rescue opens it too.
        if (n == 0 and (hq_reserve > 0 or (bool(RESCUE_GATE) and _rescue))
                # V2R7 RESCUE_TGT_FIX (see flag): GRIND_RESCUE latches _rescue on a target_ARMY deficit,
                # but this cap re-tested target_garrison (7 vs our 14-20 bodies) -> the R6 lever was inert.
                # BOUNDED to _outmassed_soft (base actually lost + workcap-behind + absolute deficit):
                # unbounded, a turtle's fortress garrison kept _under_massed latched and the lean trains
                # drained the climb bank every turn (turtle41 4W -> 2W2D with our HQ stuck L2; ablation-
                # confirmed). A REAL grind (bases falling) opens the wide cap; a mere standoff never does.
                and len(my_warriors) < (max(target_garrison, target_army)
                                        if (bool(RESCUE_TGT_FIX) and _rescue and _outmassed_soft)
                                        else target_garrison)
                and (not _behind_hq or on_hq > 0 or stack_dist <= CONCENTRATE_DIST or _rescue)
                and ((BOT.threat_army > 0 and stack_dist <= gate)
                     or (MATCH_EAGER and BOT.threat_total > 0)
                     or _rescue)):
            # ...but ONLY once the wave's stack is actually APPROACHING our HQ (within the
            # detection gate). While the enemy is still massing FAR at its own HQ (stack_dist =
            # ~diameter) we have time, so we keep banking for the L5 climb. The instant the wave
            # starts marching in (stack_dist drops into the gate), survival outranks the climb ->
            # train. This fires for AI#3's early rush (it marches in ~turn 66) but NOT for a
            # late econ-swarmer whose army masses far and arrives only after we have reached L5.
            n = max(0, min(cap, deficit))
            # V2 (g2 F2): in a genuine survival emergency (rescue window / rush brake) the GOLD_FLOOR
            # cushion must not starve the last train -- g2's t15 missed the defender that holds the HQ
            # by TWO gold (needed 188, had 186). Keep only the upkeep cushion.
            if bool(RUSH_BRAKE) and (_rescue or _rush_brake):
                while n > 0 and (S.gold - spent - TRAIN_COST * n) < UPKEEP_PER_WARRIOR * (len(my_warriors) + n):
                    n -= 1
            else:
                while n > 0 and not can(TRAIN_COST * n):
                    n -= 1
        # MIL_GAMBIT lean-train (see flag block): while latched AND outnumbered, a body in hand outranks
        # the GOLD_FLOOR cushion -- the stream rusher trains from gold>=120 while our cushion pushed the
        # effective bar to ~186, a permanent ~1.5x production handicap at 45g/turn income (the measured
        # 2:1 body gap). Mirror of the _rescue lean bar: keep only the upkeep cushion.
        if (n == 0 and _mg_on and cap > 0
                and len(my_warriors) < len(enemy_warriors)
                and len(my_warriors) < target_army):
            _mg_n = min(cap, target_army - len(my_warriors))
            while _mg_n > 0 and (S.gold - spent - TRAIN_COST * _mg_n) < UPKEEP_PER_WARRIOR * (len(my_warriors) + _mg_n):
                _mg_n -= 1
            n = max(n, _mg_n)
        # R51 HQ-TIMING lean-train (see flag block): mirror of the MG lean bar for the two wallet-empty
        # windows -- a body in hand outranks the GOLD_FLOOR cushion exactly while the timing window is
        # open (ours: the enemy probes our empty wallet; his: every body now taxes his tech buy).
        if (n == 0 and (_l2f_win or _l2p_win or _oxp_win or _ee_win or _consol or _mxa) and cap > 0
                and len(my_warriors) < len(enemy_warriors) + L2WIN_EDGE
                and len(my_warriors) < target_army):
            _lw_n = min(cap, target_army - len(my_warriors))
            while _lw_n > 0 and (S.gold - spent - TRAIN_COST * _lw_n) < UPKEEP_PER_WARRIOR * (len(my_warriors) + _lw_n):
                _lw_n -= 1
            n = max(n, _lw_n)
        # MAX_SWEEP top-up (R53, see flag block): the climb is DONE (maxed HQ) -- every unspent gold
        # above the upkeep bill and the heal bank is a body for the sweep ("무작정 병력 뽑고"). Tops the
        # regular pipeline up to the full train cap; the heal reserve stays whole (the fort's only
        # repair source at max level).
        if _sweep_on and cap > n:
            _sw_n = cap - n
            while _sw_n > 0 and (S.gold - spent - TRAIN_COST * _sw_n) < (
                    UPKEEP_PER_WARRIOR * (len(my_warriors) + n + _sw_n) + HEAL_RESERVE):
                _sw_n -= 1
            n += _sw_n
        a.train_n = n

    # V2 SPEND-LOG: per-turn spend ledger by category (pure instrumentation -- decisions untouched).
    # The offline twin (scratchpad/spend_ledger.py) reconstructs the same ledger for BOTH sides from a
    # replay; this in-bot version is for live local runs (the harness captures stderr).
    if SPEND_LOG:
        _led = {'expand': 0, 'base_up': 0, 'hq_up': 0, 'train': TRAIN_COST * a.train_n, 'moves': 0}
        for _r in a.upgrades:
            _lb = S.find_building(_r)
            if _lb is None:
                _led['expand'] += BASE_LEVELS[1].cost
            elif _lb.type is BType.HQ:
                _led['hq_up'] += _next_cost(_lb)
            else:
                _led['base_up'] += _next_cost(_lb)
        for _wid, _mt in a.moves:
            _db = S.find_building(_mt)
            if _db is None or _db.side is not me:
                _led['moves'] += MOVE_COST
        print(f"# SPEND t{turn} gold={S.gold} " + " ".join(f"{k}={v}" for k, v in _led.items() if v)
              + f" | bases={len(my_bases)} army={len(my_warriors)} rushbrake={int(_rush_brake)}"
              + f" expand_lag={int(_expand_lag)}", file=sys.stderr, flush=True)

    if DEBUG and turn % 25 == 0:
        print(f"# t{turn} gold={S.gold} spent={spent} w={len(my_warriors)} "
              f"bld={len(my_buildings)} need={total_need} hqL={hq.level if hq else 0} "
              f"thr={threat} up={a.upgrades} tr={a.train_n} mv={len(a.moves)}",
              file=sys.stderr, flush=True)



def _two_front_raid(S, M, nav, raid_force, enemy_base_regs, order_move):
    """Two-front "backdoor" offense: split the raid army into a TOP and BOTTOM prong along the
    my_hq->opp_hq axis and strike the enemy's land on both flanks. A prong that meets a LARGER
    enemy force at its target DISENGAGES and reroutes to reinforce the other (open) flank --
    "hit where they ain't". Each prong advances as a CONCENTRATED stack (the verified combat
    math rewards concentration); per-warrior moves give the organic split/regroup control.
    This only chooses MOVE targets for the already-committed raid_force; it never touches the
    home guard, the L5 climb, or the wave mobilization, so defense is unchanged."""
    enemy_warriors = [w for w in S.warriors if w.id.side is not M.my_side]
    # REAR PRESSURE (the user's strategy 2, safe form): when our army OVERWHELMS the enemy's on a WIDE map
    # (its army is wrecked, so it cannot defend its rear), order targets from the enemy HQ OUTWARD -- hit the
    # HQ-FEEDING rear bases first (their income funds the enemy's final L5), instead of the forward land. This
    # is the bias that REGRESSED as a single-fist (#12: it stalled on the HQ-adjacent wall and razed less); but
    # here each prong that meets defenders >= its size PEELS OFF and folds into the open flank (below), so the
    # spread cannot stall on a wall -- it just razes whichever rear bases the wrecked enemy left undefended.
    _my_n = sum(1 for w in S.warriors if w.id.side is M.my_side)
    _overwhelm = (M.K > WIDE_FORCE_ANCHOR and len(enemy_warriors) >= OVERWHELM_ENEMY_MIN
                  and _my_n >= OVERWHELM_F * len(enemy_warriors))
    _geo_key = (lambda r: nav.hops(r, M.opp_hq)) if _overwhelm else (lambda r: nav.hops(M.my_hq, r))

    def _base_key(r):
        k = _geo_key(r)
        if bool(MP_VALUE) and bool(TGT_VALUE):
            # V2R3: the same value terms as _pick_target -- engines (high level) first, finish what is
            # already damaged, discount repeat-razed rebuild DECOYS -- so a genuine spread stops burning
            # prongs on 300g rebuilds while L3 income engines sit untouched (4(1): t127-130 on decoy 71).
            _vb = S.find_building(r)
            if _vb is not None:
                k -= TGT_LVL_W * _vb.level
                if _vb.hp < _vb.current_hp():
                    k -= TGT_DMG_BONUS
            k += TGT_REBUILD_W * min(BOT.raze_count.get(r, 0), 3)
        return k

    # Flank of a region = which side of the my_hq->opp_hq axis it lies on (signed cross product).
    ax = M.x[M.opp_hq] - M.x[M.my_hq]
    ay = M.y[M.opp_hq] - M.y[M.my_hq]

    def flank(r: int) -> int:
        cross = ax * (M.y[r] - M.y[M.my_hq]) - ay * (M.x[r] - M.x[M.my_hq])
        return 1 if cross >= 0 else -1

    # Per-flank target = the enemy BASE on that flank nearest our HQ (land denial first; or, when
    # overwhelming, nearest the enemy HQ = rear pressure), else the enemy HQ.
    ebases = sorted(enemy_base_regs, key=_base_key)

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
    # assign by current position -- we split the force itself by warrior id (stable across turns
    # as the prongs advance toward their separate targets).
    rf = sorted(raid_force, key=lambda w: w.id.num)
    live_bases = [r for r in ebases if S.find_building(r) is not None]   # nearest-to-us first
    # N-PRONG (big army): hit the K nearest enemy bases at once, K bounded by how many prongs of >=
    # PRONG_MIN we can field, by the number of bases, and by MAX_PRONGS. Each prong that is OUTNUMBERED
    # at its target (defenders >= prong size) peels off and MERGES into the least-defended target (the
    # disengage-and-fold "hit where they ain't"). Falls back to the proven 2-flank / single-stack below.
    K = min(len(live_bases), n // max(PRONG_MIN, 1), MAX_PRONGS)
    if bool(MULTI_PRONG) and n >= MULTI_PRONG_MIN and K >= 2:
        targets = live_bases[:K]
        base = n // K
        groups = []
        i = 0
        for k in range(K):
            sz = base + (1 if k < n % K else 0)
            groups.append(rf[i:i + sz]); i += sz
        least_def = min(targets, key=enemy_def_near)        # the open flank to fold into
        assign = {}
        for grp, tgt in zip(groups, targets):
            if enemy_def_near(tgt) >= len(grp):              # outnumbered -> fold to the open target
                tgt = least_def
            assign.setdefault(tgt, []).extend(grp)           # merge prongs sharing a target
        prongs = [(g, t) for t, g in assign.items()]
    elif n >= TWO_FRONT_MIN and t_pos != t_neg:
        # Default 2-flank: half the force to each flank (force the enemy to divide their defenders).
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

    # V2R3 MP_FALLTHRU: a "spread" that folded down to ONE target is not a spread -- it is a second,
    # value-blind single-fist targeter fighting _raid_commit for ownership (4(1): 15/15 MP turns folded
    # single, 10/15 off the value ordering, commit reset every turn). Decline WITHOUT issuing orders;
    # the caller falls through to _raid_commit, which owns single-target turns (value key, siege latch,
    # commit lock). MP keeps every turn where it genuinely splits the force.
    if bool(MP_FALLTHRU) and len({t for g, t in prongs if g}) < 2:
        return False

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
    return True


# ----------------------------------------------------------------------------
# Crack-aware committed backdoor — referee-exact toolkit (validated 1:1 vs the
# referee's apply_day_combat / apply_day_siege). These are pure helpers; all the
# offense control flow lives in _raid_commit, the SINGLE owner of the raid branch.
# ----------------------------------------------------------------------------
def _sim_crack(atk_hps, base_hp, turret, def_hps, max_turns, heal=0, heal_cap=None, arrivals=None):
    """REFEREE-EXACT siege simulation. Attackers (list of hp) vs a building (base_hp, turret)
    defended by def_hps. Each turn the attack COUNTS are fixed at the start; our overflow beyond
    the defenders' HP sieges the building; their (defenders + turret) attacks kill our lowest-HP
    units. Returns (cracked, turns, survivors).
    heal>0 models an enemy that REPAIRS the building (UPGRADE-to-full): at the END of each turn the
    building is not yet dead, it regains `heal` hp (capped at heal_cap). With heal = full hp this makes
    only a ONE-SHOT crack (overwhelm full hp in a single turn) succeed -- a slow chip is undone.
    arrivals (ETA_CRACK): sorted [(turn_offset, hp), ...] of enemy RELIEF scheduled to join the defense
    turn_offset turns into the siege -- 'their reinforcements land k turns after we arrive'. None/empty
    keeps the legacy static-defender behavior byte-identical."""
    ours = sorted(atk_hps)
    theirs = sorted(def_hps)
    bh = base_hp
    cap = heal_cap if heal_cap is not None else base_hp
    _arr = list(arrivals) if arrivals else []
    _ai = 0
    for t in range(1, max_turns + 1):
        _joined = False
        while _ai < len(_arr) and _arr[_ai][0] <= t:      # relief that has marched in joins the defense
            theirs.append(_arr[_ai][1]); _ai += 1; _joined = True
        if _joined:
            theirs = sorted(theirs)
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
        if heal and bh > 0:                       # enemy repairs the building toward full each turn
            bh = min(cap, bh + heal)
    return (False, max_turns, len(ours))


def _can_crack(S, M, nav, grp, target, max_turns, hq_reinf=False):
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
    _arrivals = None
    _hz_fired = False        # V2R7 CRACK_HORIZON: horizon arrivals applied to THIS read
    if bool(ETA_CRACK):
        # PRECISION SIEGE MATH (userbot pack #5): schedule every enemy body by ARRIVAL TIME relative to
        # our own fist's march ETA. Units already on/next to the target defend from turn 1; relief at
        # distance d lands (d - our_eta) turns into the siege -- "we arrive at T, their support arrives
        # T+k; can we finish before it?" (_sim_crack plays the staggered timeline referee-exact). Relief
        # farther than our_eta + ETA_GRACE cannot affect a short siege and is ignored (the old cluster
        # rule instead counted the WHOLE HQ garrison as instantly present -- over-conservative -- while
        # missing 2-hop relief on forward bases -- over-optimistic; both mis-reads cost units).
        _eta = max((nav.hops(w.region, target) for w in grp), default=0)
        defs = []
        _arr = []
        for w in S.warriors:
            if w.id.side is me or w.hp <= 0:
                continue
            d = nav.hops(w.region, target)
            if d <= max(local_rd, _eta):              # there on/before our arrival -> defends from turn 1
                defs.append(w.hp)
            elif d <= _eta + ETA_GRACE:               # lands mid-siege, (d - eta) turns after we arrive
                _arr.append((d - _eta, w.hp))
        _arr.sort()
        _arrivals = _arr or None
    else:
        defs = [w.hp for w in S.warriors
                if w.id.side is not me and w.hp > 0 and nav.hops(w.region, target) <= local_rd]
        # V2R7 CRACK_HORIZON (1(2), see flag): the 1-hop defender model razed the base but donated the
        # fist to relief converging from 2-4 hops. Schedule that relief as STAGGERED arrivals (offset
        # d - local_rd: later than ETA_CRACK's everyone-present read -- razing fast still wins), plus a
        # small trained-refill phantom when the enemy HQ sits inside the horizon. Applied ONLY on the
        # ambush signature (horizon bodies >= CRACK_HZ_OUTNUM x counted defenders) so a turtle's scattered
        # 2-worker garrisons never re-create the ETA_CRACK paralysis. BASE targets, never in deny_mode.
        if bool(CRACK_HORIZON) and b.type is BType.BASE and not bool(BOT.deny_mode):
            _hz_eta = max((nav.hops(w.region, target) for w in grp), default=0)
            _hz = []
            for w in S.warriors:
                if w.id.side is me or w.hp <= 0:
                    continue
                _hd = nav.hops(w.region, target)
                if local_rd < _hd <= _hz_eta + ETA_GRACE:
                    _hz.append((max(1, _hd - local_rd), w.hp))
            _hz_hq = S.find_building(M.opp_hq)
            _hz_dhq = hq_hops                       # same orientation as the is_cluster read above
            if (_hz_hq is not None and _hz_hq.type is BType.HQ
                    and local_rd < _hz_dhq <= _hz_eta + ETA_GRACE):
                _hz_lv = HQ_LEVELS[_hz_hq.level]
                for _i in range(CRACK_HZ_PH_CAP):
                    for _ in range(_hz_lv.train_cap):
                        _hz.append((max(1, _hz_dhq - local_rd) + _i, _hz_lv.warrior_hp))
            if _hz and len(_hz) >= CRACK_HZ_OUTNUM * max(1, len(defs)):
                _hz.sort()
                _arrivals = _hz
                _hz_fired = True
    # HEAL-AWARE (axis-1): if the enemy has healed THIS base within HEAL_MEMORY turns, model the repair in
    # the sim -- the building regenerates to full each turn -> crackable ONLY by a one-shot. This kills the
    # game-4 futile trickle (oscillating chip on a base the enemy resets for 500g) without touching un-healed
    # forward bases (7/8's contested strongholds never trip it -> midfield razing/pressure preserved). HQ is
    # never in `live`, so this only ever gates BASE targets.
    # WIDE-MAP DENIAL: when deny_mode is active (wide map + army dominance), DROP the conservative gates so
    # the army keeps razing the enemy's near-HQ bases to starve its L5 climb (the old v1 behaviour that won
    # 4/5). _sim_crack still refuses a genuinely suicidal commit (it kills our units as the defenders+turret
    # fight back), so this only removes the EXTRA caution (the 70%-survivor cluster gate + heal modelling)
    # that, on a wide map where we out-number the enemy, made the army coast instead of denying.
    _deny = bool(BOT.deny_mode)
    _heal = 0
    if HEAL_AWARE and not _deny and b.type is BType.BASE and (BOT.turn - BOT.heal_turn.get(target, -10**9)) <= HEAL_MEMORY:
        _heal = (HQ_LEVELS if b.type is BType.HQ else BASE_LEVELS)[b.level].hp   # full hp = repair-to-full
    # R95 HQ_CRACK_MARGIN (user: "HQ 공격 판단은 주먹 = 수비 + 터렛 + (2*train_cap+2)"): the enemy HQ trains
    # train_cap warriors EVERY siege turn, invisible to the static `defs` snapshot -- so a thin fist that only ties
    # the snapshot reads crackable yet loses to the reinforcements. Add a (2*train_cap + 2) phantom-body buffer
    # (each a freshly-trained warrior_hp) so the required fist = defense + turret + buffer. Only when the caller
    # flagged an HQ-finish (COMMIT_STRIKE / CS_FINISH); base targets and SPENT_FINISH never pass hq_reinf.
    if hq_reinf and bool(HQ_CRACK_MARGIN) and b.type is BType.HQ:
        _hqm = 2 * HQ_LEVELS[b.level].train_cap + 2
        defs = list(defs) + [HQ_LEVELS[b.level].warrior_hp] * _hqm
    cracked, _t, survivors = _sim_crack([w.hp for w in grp], b.hp, turret, defs, max_turns,
                                        heal=_heal, heal_cap=_heal or None, arrivals=_arrivals)
    # V2R7 CRACK_HORIZON: when horizon arrivals were applied, a bare "cracked" is not enough -- the g3
    # raids DID raze their targets and still lost 13 units to the relief. Require the same favorable-trade
    # margin the cluster gate uses (survivors >= CLUSTER_KEEP_F of the fist).
    if cracked and not _deny and ((is_cluster and b.type is not BType.HQ) or _hz_fired):
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
    picks off the enemy's forward economy first and works the edge, instead of diving at the HQ.
    CLUSTER-TARGETING (flag): candidates sitting in a CLUSTER of live enemy bases sort earlier (bonus
    CLUSTER_W per other base within CLUSTER_R hops), so the fist works the dense side -- razing one base
    leaves it a short march from the next -- instead of chasing a lone near-and-forward rebuild across
    the map (the g4 top<->bottom commute). Ordering only; every candidate is still crack-checked."""
    def _key(r):
        k = nav.hops(frm, r) - nav.hops(r, M.opp_hq)
        if bool(TGT_VALUE):
            # V2 (g4): value terms -- a high-level base is the enemy's income/HQ-fund engine (an L3 = 3x
            # an L1's slots and 1900g sunk), a DAMAGED one is nearly-paid-for, and a region we already
            # razed n times is a 300g rebuild DECOY (B rebuilt 71 three times to keep our fist commuting
            # while its L3 engine 53 was never touched).
            _vb = S.find_building(r)
            if _vb is not None:
                k -= TGT_LVL_W * _vb.level
                if _vb.hp < _vb.current_hp():
                    k -= TGT_DMG_BONUS
            k += TGT_REBUILD_W * min(BOT.raze_count.get(r, 0), 3)
        if bool(CLUSTER_TGT):
            k -= CLUSTER_W * sum(1 for o in live if o != r and nav.hops(r, o) <= CLUSTER_R)
        if bool(ENDGAME_LVL_TGT) and BOT.endgame:
            # ENDGAME (user): a high-level base is the enemy's income engine AND its HQ fund -- razing it
            # first hurts most. Endgame-gated only; every candidate is still crack-checked below.
            _tb = S.find_building(r)
            if _tb is not None:
                k -= LVL_TGT_W * _tb.level
        return k
    for r in sorted(live, key=_key):
        if _can_crack(S, M, nav, force, r, max_turns):
            return r
    return -1


def _raid_advance(M, nav, force, target, order_move, defended=False, stop_count=None):
    """MONOTONIC march: every unit steps exactly one hop toward `target`, so its distance to the
    target strictly DECREASES each turn -> it can NEVER oscillate (the documented 0<->adjacent
    ping-pong came from a 'regroup onto the most-common node' rule). Units on the target hold & siege.
    CONSOLIDATE (defended targets only): units that reach ADJACENCY HOLD (do not step onto the defended
    target alone) until a crackable-fraction of the fist is assembled at/adjacent to it, then all step on
    together -- so we never feed a defended base 1-2 units at a time to be chipped and killed in detail
    (log-6). Holding is forward-only (no retreat) so it cannot ping-pong; undefended targets are untouched."""
    if bool(CONSOLIDATE) and defended and len(force) >= 3:
        _adjset = set(M.adj[target]) | {target}
        _assembled = sum(1 for w in force if w.region in _adjset)
        _need = max(2, math.ceil(CONSOLIDATE_FRAC * len(force)))
        if _assembled < _need:
            for w in force:
                if w.region in _adjset:
                    continue            # on/adjacent the target -> HOLD, wait for the fist to assemble
                nh = nav.next_hop(w.region, target)
                order_move(w, nh if nh >= 0 else target)   # bring the stragglers up
            return
    # V2R5 FAR_MARCH (5.txt): the per-hop stepping below re-billed 10g EVERY hop (588 re-billed commands
    # = 5,880g in one game) while the referee charges a MOVE once and walks the standing order for free.
    # Order the node FAR_MARCH_HOPS ahead instead -- billed once per chunk. Only for UNDEFENDED targets
    # with a 2:1 flee headroom (a marching unit cannot be re-tasked, so the latch is kept short and only
    # taken when nothing can plausibly stop the fist within the chunk).
    _far = (bool(FAR_MARCH) and not defended and stop_count is not None
            and 2 * stop_count <= len(force))
    for w in force:
        if w.region == target:
            continue
        if _far and nav.hops(w.region, target) >= FAR_MARCH_MIN_D:
            _node = w.region
            for _ in range(FAR_MARCH_HOPS):
                _nh = nav.next_hop(_node, target)
                if _nh < 0:
                    break
                _node = _nh
                if _node == target:
                    break
            if _node != w.region:
                order_move(w, _node)
            continue
        nh = nav.next_hop(w.region, target)
        order_move(w, nh if nh >= 0 else target)


def _withdraw(M, nav, force, friendly_regions, order_move, forward=False, home_recall=False,
              fwd_pick=-1, camp=None):
    """Disengage: each unit makes a one-way march to a friendly building, to watch and re-engage on
    opportunity. Monotone -> the disengage path itself cannot oscillate. home_recall=True drives the whole
    fist back to NODE 0 (and it then sits at 0g) so a pending HQ climb is not bled by per-turn roam moves
    (the g8 coast: ineffective roaming at 10g/unit/turn starved the L2->L5 climb). forward=True stages the
    fist at our FRONTIER base to keep pressure on a turtle; forward=False sends each unit to its NEAREST
    friendly building. fwd_pick>=0 (FWD_GARRISON) overrides the frontier choice with the RETURN-GUARANTEED
    forward base (user doctrine: stand forward, we always beat a committing enemy home; moves to friendly
    buildings are FREE so the posture costs nothing)."""
    home = M.my_hq
    # RAZE_CAMP (R59, 1(65) t75; user: "상대 기지를 부쉈는데 상대는 또 기지를 짓지 -- 용인한 시간이 좀
    # 길어"): a body STANDING on an empty stronghold blocks the rebuild outright (referee rule: no
    # UPGRADE with an enemy present -- the EXPAND_AHEAD blockade, mirrored). The watch-withdraw after a
    # raze walked all four bodies off node 54 on t75 and the enemy rebuilt on t78, un-doing the whole
    # t74 strike. On a NON-home-recall disengage, units already standing on an empty non-HQ stronghold
    # STAY (no order = free) unless the local fight is lost (enemies within 2 hops outnumber the camp).
    if camp is not None and not home_recall and bool(RAZE_CAMP):
        _cS, _cen = camp
        _csh = set(M.strongholds)
        _campers = {}
        _rest = []
        for w in force:
            if (w.region in _csh and w.region != M.opp_hq and w.region != home
                    and _cS.find_building(w.region) is None):
                _campers.setdefault(w.region, []).append(w)
            else:
                _rest.append(w)
        for _cn, _cws in _campers.items():
            _cthr = sum(1 for e in _cen if nav.hops(e.region, _cn) <= 3)
            if _cthr > len(_cws):
                _rest.extend(_cws)      # losing camp -> disengage as before
            # else: stand -- the occupied stronghold cannot be rebuilt
        force = _rest
    fr = sorted(friendly_regions)
    fwd = fwd_pick if fwd_pick >= 0 else (min(fr, key=lambda f: nav.hops(f, M.opp_hq)) if fr else home)
    for w in force:
        if home_recall:
            d = home
        elif forward:
            d = fwd
        else:
            d = min(fr, key=lambda f: nav.hops(w.region, f)) if fr else home
        if w.region != d:
            order_move(w, d)


def _raid_commit(S, M, nav, force, live, order_move, friendly_regions, turn, climb_pending=False,
                 hold_ground=False, win_endgame=False):
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

    # RAID_PHANTOM (R42, see flag block): evidence-gated train-stream veto for BASE commits inside the
    # enemy HQ's relief funnel. Returns True = the crack proof does NOT survive the observed production
    # stream -> release the commit (blacklist + withdraw handled by the existing machinery downstream).
    def _ph_veto(_pt):
        if not bool(RAID_PHANTOM) or _pt < 0 or _pt == M.opp_hq:
            return False
        _pvb = S.find_building(_pt)
        if _pvb is None or _pvb.type is not BType.BASE:
            return False
        _ehqb = S.find_building(M.opp_hq)
        if _ehqb is None or _ehqb.side is M.my_side:
            return False
        _pvh = nav.hops(M.opp_hq, _pt)
        if _pvh > RAIDPH_FUNNEL:
            return False
        _pv_tr = sum(_n for _t, _n in getattr(BOT, 'ph_tlog', []) if _t > turn - RAIDPH_WIN)
        # RAIDPH_LEAN (R52, see flag block): 1(52)'s feeder held EXACTLY one train under the bar.
        if _pv_tr < RAIDPH_TRAINS - (1 if bool(RAIDPH_LEAN) else 0):
            return False                          # no live stream observed -> no phantoms (turtle-safe)
        # phantoms at the OBSERVED rate, landing from the funnel distance onward (capped like the finisher)
        _pv_n = min(FINISH_PHANTOM_CAP,
                    math.ceil(_pv_tr * MAX_CRACK_TURNS / RAIDPH_WIN))
        _pv_hp = HQ_LEVELS[_ehqb.level].warrior_hp
        _pv_ph = []
        _pv_step = max(1, RAIDPH_WIN // max(1, _pv_tr))     # observed inter-train spacing
        for _k in range(_pv_n):
            _off = _pvh + 1 + _k * _pv_step
            if _off > MAX_CRACK_TURNS:
                break
            _pv_ph.append((_off, _pv_hp))
        if not _pv_ph:
            return False
        _pv_def = [ww.hp for ww in enemy if ww.region == _pt]
        _pv_arr = sorted([(nav.hops(ww.region, _pt), ww.hp) for ww in enemy
                          if 1 <= nav.hops(ww.region, _pt) <= MAX_CRACK_TURNS] + _pv_ph)
        _pv = _sim_crack([w.hp for w in force], _pvb.hp,
                         BASE_LEVELS[_pvb.level].turret, _pv_def,
                         MAX_CRACK_TURNS, arrivals=_pv_arr or None)
        return not (_pv[0] and _pv[2] >= max(1, int(CLUSTER_KEEP_F * len(force) + 0.999)))
    # FWD_GARRISON (user doctrine, 8(5)/8(6) "양측 HQ 대군 주차"): the enemy marches deterministic shortest
    # paths at 1 hop/turn, and a STATIONARY body is re-orderable every turn -- so a reserve standing on a
    # forward base ALWAYS beats a committing enemy home as long as our return trip is shorter than their
    # remaining approach (hops(base, my_hq) + FWDG_MARGIN <= nearest enemy's distance to my_hq; the margin
    # covers the 1-turn detection lag). Pick the most forward friendly base satisfying that guarantee and
    # park the idle fist THERE instead of the HQ doorstep: faster relief reach, interception coverage, and
    # the staging deterrence the 8(6) win demonstrated -- at zero gold (moves to friendly buildings are
    # free). When the enemy closes, the guarantee tightens and the pick collapses toward home by itself.
    _fwdg_pick = -1
    if bool(FWD_GARRISON):
        _fg_near = min((nav.hops(w.region, M.my_hq) for w in enemy), default=1 << 30)
        _fg_cands = [f for f in friendly_regions
                     if f != M.my_hq and nav.hops(f, M.my_hq) <= FWDG_MAX
                     and nav.hops(f, M.my_hq) + FWDG_MARGIN <= _fg_near]
        if _fg_cands:
            _fwdg_pick = min(_fg_cands, key=lambda f: (nav.hops(f, M.opp_hq), f))
    # V2R4 HQ_SNAP (4.txt t136): the fist TRANSITS the enemy HQ tile (the only path to base 80 runs over
    # 82) and the bodies ALREADY STANDING THERE crack it within HQ_SNAP_TURNS per the referee-exact sim
    # (defenders present + train_cap/turn bank-funded refill as phantom arrivals) -> HOLD them; the march
    # order that walked 10 bodies off a 7-hp HQ is the whole miss (2 more turns = the game). Re-evaluated
    # every turn: if the read flips (heavy reinforcement), the hold releases and the march resumes.
    if bool(HQ_SNAP):
        _snap_units = [w for w in force if w.region == M.opp_hq]
        if len(_snap_units) >= 2:
            _snap_hq = S.find_building(M.opp_hq)
            if _snap_hq is not None:
                _snap_def = [ww.hp for ww in enemy if ww.region == M.opp_hq]
                _snap_arr = [(k, HQ_LEVELS[_snap_hq.level].warrior_hp)
                             for k in range(1, HQ_SNAP_TURNS + 1)
                             for _ in range(HQ_LEVELS[_snap_hq.level].train_cap)]
                if _sim_crack([w.hp for w in _snap_units], _snap_hq.hp,
                              HQ_LEVELS[_snap_hq.level].turret, _snap_def,
                              HQ_SNAP_TURNS, arrivals=_snap_arr)[0]:
                    force = [w for w in force if w.region != M.opp_hq]
                    if not force:
                        return
    live_set = set(live)
    frm = Counter(w.region for w in force).most_common(1)[0][0]

    def _is_defended(t):
        # a target with any enemy warrior on/within the reinforce radius -> a piecemeal single-unit arrival
        # would be chipped by turret+defenders, so CONSOLIDATE the fist before stepping on (see _raid_advance).
        return any(nav.hops(w.region, t) <= REINFORCE_DIST for w in enemy)
    # EVASION (the user's rule): the backdoor WATCHES the enemy. If a CONCENTRATED enemy stack big
    # enough to STOP it (a single mobile relief group >= our fist size) has closed within FLEE_RADIUS,
    # do NOT trade the backdoor away -- release the target and FLEE to the nearest friendly base, then
    # watch for an opening. We key off the LARGEST single stack, not the total count: a turtle's
    # scattered 2-worker base garrisons must NOT scare us off (we raze those base-by-base, the per-base
    # defense is already handled by _can_crack) -- only a real massed relief column makes us run.
    _fist_in_cluster = nav.hops(frm, M.opp_hq) <= HQ_CLUSTER_DIST
    # V2 FLEE_FIX (g6, see flag): a PARKED enemy HQ garrison is not a stopper -- it counts only once it
    # leaves the HQ tile (or when we fight inside the cluster itself, where convergence is 1 hop).
    # Referee-exact CF: base 22 cracked in 2 turns even vs an INSTANT sortie of the parked 13-stack.
    _near = Counter(w.region for w in enemy
                    if nav.hops(w.region, frm) <= FLEE_RADIUS
                    and (not bool(FLEE_FIX) or _fist_in_cluster or w.region != M.opp_hq))
    # The single-largest-stack test is precise for FORWARD razing (a turtle's scattered 2-worker base
    # garrisons must not scare us off). But INSIDE the enemy HQ cluster the converging HQ garrison arrives
    # in PIECES from several adjacent tiles -- it is never one pre-formed stack, so the single-stack test
    # under-reads it and the fist lingers taking papercut turret/garrison damage (k7/k8: 28+ dmg taken, 0
    # dealt). When the fist is parked in the cluster, flee on the TOTAL convergeable enemy near it, not just
    # the largest single stack -- so we disengage the HQ's doorstep instead of grinding it.
    # V2 FLEE_FIX (g4, see flag): the cluster-TOTAL test applies only when the TARGET is in the cluster;
    # a fist merely TRANSITING a cluster-adjacent corridor (node 72) to a non-cluster target keeps the
    # single-stack test (3 marches to 66/75 were aborted mid-corridor by the parked home-garrison total).
    _tgt_in_cluster = (BOT.raid_tgt >= 0 and nav.hops(BOT.raid_tgt, M.opp_hq) <= HQ_CLUSTER_DIST)
    _total_flee = _fist_in_cluster and (not bool(FLEE_FIX) or _tgt_in_cluster or BOT.raid_tgt < 0)
    _stop = sum(_near.values()) if _total_flee else (max(_near.values()) if _near else 0)
    # COMMIT_CRACK (see flag block): the crude _stop total counts the PARKED HQ garrison, so the fist flees a
    # cluster BASE it could actually raze. _can_crack is arrival-aware (ETA-scheduled garrison) AND survivor-gated
    # (CLUSTER_KEEP_F) -- the precise "is this number DANGEROUS to us" judgment. If our LIVE committed target is a
    # BASE that sim deems crackable, trust it over the count and keep committing instead of shadow-boxing.
    if (bool(COMMIT_CRACK) and _stop >= len(force) and BOT.raid_tgt >= 0 and BOT.raid_tgt in live_set):
        _cc_b = S.find_building(BOT.raid_tgt)
        if _cc_b is not None and _cc_b.type is BType.BASE:
            # ASSEMBLY-AWARE: the referee fights whoever is at the base THIS turn, so sim only the ARRIVED fist
            # (units on/adjacent the target), not still-marching bodies. A spread fist (0 arrived) keeps fleeing.
            _cc_on = [w for w in force if nav.hops(w.region, BOT.raid_tgt) <= COMMIT_ASSEMBLE_HOPS]
            if (len(_cc_on) >= COMMIT_MIN_ON
                    and _can_crack(S, M, nav, _cc_on, BOT.raid_tgt, MAX_CRACK_TURNS)):
                _stop = 0
    # FLEE_TURRET (see flag block): our EFFECTIVE defense when the fist stands on/adjacent OUR building is the
    # fist + that turret + any friendly warriors present but not in the fist (base garrison/workers -- all fight
    # in day combat). Comparing _stop vs the raw fist count alone fled winnable base defenses (referee-exact,
    # same bonus the home/relief paths credit via _home_turret).
    _fist_def = 0
    if bool(FLEE_TURRET):
        _fist_at = sum(1 for f in force if f.region == frm)
        _present = sum(1 for w in S.warriors if w.id.side is M.my_side and w.region == frm)
        _fist_def = _home_turret(S, M, M.my_side, frm) + max(0, _present - _fist_at)
    # WIN_ENDGAME_COMMIT (see flag block): in the winning endgame, a live enemy base the FULL fist can
    # crack per the referee-exact, survivor-gated _can_crack is a free raze that denies the enemy's final
    # HQ level -- do NOT flee it just because the naive _stop count sees the enemy's parked, stay-at-home
    # HQ garrison (game 5: r100 crackable + 37 bodies deployed, yet fled 50 turns on a 20-garrison that
    # never sortied). Seize the best crackable base and zero _stop so the commit/advance below marches in.
    if win_endgame and _stop >= len(force) + _fist_def:
        _wec = _pick_target(S, M, nav, force,
                            [r for r in live_set if BOT.raid_skip.get(r, 0) <= turn],
                            MAX_CRACK_TURNS, frm)
        if _wec >= 0:
            BOT.raid_tgt = _wec
            BOT.raid_lock = max(BOT.raid_lock, WIN_ENDGAME_LOCK)
            BOT.no_target_streak = 0
            _stop = 0
    if _stop >= len(force) + _fist_def:
        # V2R10 FLEE_FINISH (1(8) t74, see flag): the committed bodies already within 1 hop of the live
        # target (they arrive AND siege this turn -- referee resolves moves before combat/siege) alone
        # raze it within FLEE_FINISH_TURNS per referee-exact sim, with every enemy within that window
        # injected as arrivals at offset=hops (same-turn arrivals DO defend) and the CLUSTER_KEEP_F
        # survivor gate -> postpone the flee and finish the kill. Re-proven every turn; the moment the
        # proof breaks, the normal flee (incl. FLEE_SKIP blacklist) resumes.
        if bool(FLEE_FINISH) and BOT.raid_tgt >= 0 and BOT.raid_tgt in live_set:
            # V2R12 FLEE_HOLD (1(14), see flag block): under _hold_ground (home safe by training, enemy
            # not out-producing, no closing wave) the finish proof gets the longer FLEE_HOLD_TURNS window
            # -- the 2-turn horizon only ever held already-cracked bases; a 9-hp base 3 turns from death
            # was abandoned mid-siege. Same referee-exact sim, same survivor gate, just a longer horizon
            # (and the arrivals window widens WITH it, so closing enemies inside the window still count).
            _ff_win = (FLEE_HOLD_TURNS if (bool(FLEE_HOLD) and hold_ground) else FLEE_FINISH_TURNS)
            _ffb = S.find_building(BOT.raid_tgt)
            _ff_on = [w for w in force if nav.hops(w.region, BOT.raid_tgt) <= 1]
            if _ffb is not None and _ff_on:
                _ff_def = [ww.hp for ww in enemy if ww.region == BOT.raid_tgt]
                _ff_arr = sorted((nav.hops(ww.region, BOT.raid_tgt), ww.hp) for ww in enemy
                                 if 1 <= nav.hops(ww.region, BOT.raid_tgt) <= _ff_win)
                _ffc = _sim_crack([w.hp for w in _ff_on], _ffb.hp,
                                  (HQ_LEVELS if _ffb.type is BType.HQ else BASE_LEVELS)[_ffb.level].turret,
                                  _ff_def, _ff_win, arrivals=_ff_arr or None)
                if _ffc[0] and _ffc[2] >= max(1, int(CLUSTER_KEEP_F * len(_ff_on) + 0.999)):
                    BOT.raid_lock = max(BOT.raid_lock - 1, 1)
                    BOT.no_target_streak = 0
                    _raid_advance(M, nav, force, BOT.raid_tgt, order_move,
                                  defended=_is_defended(BOT.raid_tgt), stop_count=_stop)
                    return
        # V2R5 FLEE_SKIP (g6 deadlock): a cluster-flee means the target is UNREACHABLE while the parked
        # garrison sits on the corridor -- blacklist it like a stalled siege so the next pick is forced
        # to a reachable base (the flee branch used to clear raid_tgt BEFORE lock expiry, so the 3784
        # blacklist never fired: skip{} stayed empty all game while the fist paid 6 round trips).
        if bool(FLEE_SKIP) and BOT.raid_tgt >= 0 and _fist_in_cluster:
            BOT.raid_skip[BOT.raid_tgt] = turn + SKIP_WATCH
        BOT.raid_tgt = -1
        BOT.raid_lock = WATCH_LOCK
        _withdraw(M, nav, force, friendly_regions, order_move, camp=(S, enemy))
        return
    tgt = BOT.raid_tgt
    lock = BOT.raid_lock
    # CHIP-AND-RUN commit (PULSE, userbot pack #2): the current target is a CHIP (not sim-crackable --
    # we are trading hp for siege/economic denial, like the user-bracket bots do to us). Keep grinding
    # while the fist retains PULSE_HP_F of its commit hp and no stopper stack has closed; DISENGAGE the
    # moment either flips (never a slow bleed-out). Lock expiry rotates to the next softest base via the
    # normal blacklist path = sustained pulse pressure across the enemy economy.
    if lock > 0 and BOT.chip_mode:
        _hp_now = sum(w.hp for w in force)
        if (tgt in live_set and _hp_now >= PULSE_HP_F * max(1, BOT.chip_hp0) and _stop < len(force)):
            BOT.raid_lock = lock - 1
            BOT.no_target_streak = 0
            _raid_advance(M, nav, force, tgt, order_move, defended=_is_defended(tgt), stop_count=_stop)
            return
        BOT.chip_mode = False                       # razed it / bled to threshold / stopper closed -> out
        BOT.raid_tgt = -1
        BOT.raid_lock = WATCH_LOCK
        _withdraw(M, nav, force, friendly_regions, order_move, camp=(S, enemy))
        return
    BOT.chip_mode = False                           # any non-chip path owns the lock from here
    if lock > 0 and tgt in live_set and not _ph_veto(tgt) and _can_crack(S, M, nav, force, tgt, MAX_CRACK_TURNS):
        BOT.raid_lock = lock - 1                   # committed to a live, still-crackable base -> keep marching
        BOT.no_target_streak = 0                   # we HAVE a crackable target -> razing is working, not futile
        _raid_advance(M, nav, force, tgt, order_move, defended=_is_defended(tgt), stop_count=_stop)
        return
    # V2R12 SIEGE_STICK (1(14) t67, see flag block): bodies ALREADY standing on/adjacent a live enemy BASE
    # that they ALONE provably raze within FLEE_HOLD_TURNS (referee-exact _sim_crack; every enemy within the
    # window injected as an arrival at offset=hops; CLUSTER_KEEP_F survivors required) re-commit and finish
    # -- a WATCH lock or a lock-expiry re-pick must not walk a fist off a 9-hp base it is stood on. The
    # forensic: a far FORMING stack shrank raid_force mid-siege (commit released), and the re-formed fist
    # obeyed the fresh WATCH lock home. Base-only (an HQ turret grind is HQ_SNAP/_hq_chip business),
    # _hold_ground-gated, re-proven every turn, monotone advance -> cannot oscillate.
    if bool(SIEGE_STICK) and hold_ground:
        _ss_best = None
        _ss_on_best: list = []
        for _ss_r in sorted(live_set):
            _ssb = S.find_building(_ss_r)
            if _ssb is None or _ssb.type is BType.HQ:
                continue
            _ss_on = [w for w in force if nav.hops(w.region, _ss_r) <= 1]
            if len(_ss_on) < 2 or len(_ss_on) <= len(_ss_on_best):
                continue
            _ss_def = [ww.hp for ww in enemy if ww.region == _ss_r]
            _ss_arr = sorted((nav.hops(ww.region, _ss_r), ww.hp) for ww in enemy
                             if 1 <= nav.hops(ww.region, _ss_r) <= FLEE_HOLD_TURNS)
            _ssc = _sim_crack([w.hp for w in _ss_on], _ssb.hp,
                              BASE_LEVELS[_ssb.level].turret,
                              _ss_def, FLEE_HOLD_TURNS, arrivals=_ss_arr or None)
            if _ssc[0] and _ssc[2] >= max(1, int(CLUSTER_KEEP_F * len(_ss_on) + 0.999)):
                _ss_best, _ss_on_best = _ss_r, _ss_on
        if _ss_best is not None:
            # Preserve the stalled-siege blacklist: if we were locked on a DIFFERENT live-but-uncrackable
            # base (a wall we could not crack), record it in raid_skip before switching, so PULSE/re-pick
            # cannot instantly re-lock the wall the moment _ss_best falls (the SKIP_WATCH anti-bleed contract).
            if tgt >= 0 and tgt in live_set and tgt != _ss_best:
                BOT.raid_skip[tgt] = turn + SKIP_WATCH
            BOT.raid_tgt = _ss_best
            BOT.raid_lock = max(lock, 2)           # a live finish-commit; re-proven (or released) next turn
            BOT.no_target_streak = 0
            _raid_advance(M, nav, force, _ss_best, order_move,
                          defended=_is_defended(_ss_best), stop_count=_stop)
            return
    if lock > 0 and tgt < 0:                        # committed WITHDRAW -> sit at a friendly base & watch
        BOT.raid_lock = lock - 1
        # V2R12 FWD_STATION (see flag block): in a HELD state the WATCH parking is our FRONTIER base --
        # the fist waits where the next fight/opening actually is, instead of at the HQ it trained at
        # (nearest-friendly == HQ for home-trained bodies: the 1(10)/1(11)/1(13) "근무태만"). home_recall
        # (a pending climb bank) takes precedence inside _withdraw exactly as before.
        _withdraw(M, nav, force, friendly_regions, order_move,
                  forward=((bool(FWD_STATION) and turn >= FWD_STATION_TURN and hold_ground
                            or _fwdg_pick >= 0)                       # FWD_GARRISON: return-guaranteed post
                           and not climb_pending),
                  home_recall=climb_pending,
                  fwd_pick=_fwdg_pick, camp=(S, enemy))
        return
    if tgt >= 0 and tgt in live_set:               # lock expired but base STILL ALIVE -> stalled siege
        BOT.raid_skip[tgt] = turn + SKIP_WATCH      # blacklist it so we don't instantly re-lock the wall
    cand = [r for r in live if BOT.raid_skip.get(r, 0) <= turn]
    newt = _pick_target(S, M, nav, force, cand, MAX_CRACK_TURNS, frm)
    # RAID_PHANTOM (R42): a FRESH pick must clear the stream veto too, or the fist re-commits to the same
    # funnel the veto just released (t157 in the 1(47) record was exactly this re-commit). Blacklist it
    # like a stalled siege so the next pick moves on; PULSE chips keep their own bounded-bleed contract.
    if newt >= 0 and _ph_veto(newt):
        BOT.raid_skip[newt] = turn + SKIP_WATCH
        cand = [r for r in cand if r != newt]
        newt = _pick_target(S, M, nav, force, cand, MAX_CRACK_TURNS, frm)
        if newt >= 0 and _ph_veto(newt):
            BOT.raid_skip[newt] = turn + SKIP_WATCH
            newt = -1
    # V2R7 RAID_MIN_COMMIT (1(2) t75/t84, see flag): a 2-3-body remnant re-picking a target feeds the
    # defense in detail. NEW commits need a real fist; an existing lock (handled above) keeps marching.
    if bool(RAID_MIN_COMMIT) and len(force) < MIN_RAID:
        # V2R8 RAZE_CHAIN_HOLD (4.txt, see flag): the turn a base falls the mates are still MOVING onto
        # it -- if they refill the fist to >= MIN_RAID, HOLD one turn (no orders, no lock change) and
        # re-pick with the full fist next turn instead of yo-yoing home for a 4-turn WATCH_LOCK.
        if bool(RAZE_CHAIN_HOLD):
            _mates = sum(1 for w in S.warriors
                         if w.id.side is M.my_side and w.state is WState.MOVING
                         and w.target >= 0 and nav.hops(w.target, frm) <= 1)
            if len(force) + _mates >= MIN_RAID:
                return
        newt = -1
    if newt < 0 and bool(PULSE) and cand and len(force) >= MIN_RAID:
        # PULSE (userbot pack #2): nothing deterministically crackable -- the old build then NEVER attacked
        # (three real losses with literally 0 siege dealt while the enemy pulse-razed us all game). Instead,
        # CHIP the softest live base: fewest defenders reachable within 2 hops, then lowest level, then
        # nearest. Commit as a chip (see the chip branch above: HP-threshold + stopper disengage, CHIP_LOCK
        # rotation) so we trade a bounded amount of hp for continuous economic denial.
        def _soft(r):
            bb = S.find_building(r)
            return (sum(1 for w in enemy if nav.hops(w.region, r) <= 2),
                    bb.level if bb is not None else 0,
                    nav.hops(frm, r))
        newt = min(cand, key=_soft)
        BOT.raid_tgt = newt
        BOT.raid_lock = CHIP_LOCK
        BOT.chip_mode = True
        BOT.chip_hp0 = sum(w.hp for w in force)
        BOT.no_target_streak = 0
        _raid_advance(M, nav, force, newt, order_move, defended=_is_defended(newt), stop_count=_stop)
        return
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
        # V2R12 FWD_STATION (see flag block): the t100 staging clock becomes state-driven -- in a HELD
        # state the fresh WATCH commit stages at the frontier base from FWD_STATION_TURN (the user's
        # "최전방 아군 기지에 배치"); outside _hold_ground the original clock/nearest-friendly behaviour
        # is untouched (and the home_recall climb-bank path keeps absolute precedence).
        _withdraw(M, nav, force, friendly_regions, order_move,
                  forward=((turn >= HARASS_STAGE_TURN
                            or (bool(FWD_STATION) and turn >= FWD_STATION_TURN and hold_ground)
                            or _fwdg_pick >= 0)                       # FWD_GARRISON: return-guaranteed post
                           and not _recall),
                  home_recall=_recall,
                  fwd_pick=_fwdg_pick, camp=(S, enemy))
        return
    BOT.raid_tgt = newt
    BOT.raid_lock = CRACK_LOCK
    BOT.no_target_streak = 0                        # found a crackable base -> razing is working, not futile
    _raid_advance(M, nav, force, newt, order_move, defended=_is_defended(newt), stop_count=_stop)


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
