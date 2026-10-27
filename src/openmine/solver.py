"""Logical Minesweeper solver.

Used to generate boards that can be finished without guessing and to give
hints. The solver only ever uses information a player could see: revealed
numbers, the total mine count, and mines it has deduced itself (player flags
are ignored because they may be wrong).

Deduction rules, cheapest first:

1. single constraint: a number whose remaining mines equal 0 or the number of
   unknown neighbours;
2. pairs of overlapping constraints (covers subset patterns such as 1-1 and
   1-2);
3. the global mine count;
4. exhaustive enumeration of small connected frontier regions.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from openmine.game import Game

UNKNOWN = 0
SAFE = 1
MINE = 2

# Limits that keep enumeration fast enough to run many times per second.
ENUM_MAX_CELLS = 26
ENUM_MAX_NODES = 40_000

Constraint = tuple[frozenset, int]


class Solver:
    def __init__(self, neighbors: list[tuple[int, ...]], total_mines: int) -> None:
        self.neighbors = neighbors
        self.size = len(neighbors)
        self.total = total_mines
        self.state = bytearray(self.size)
        self.counts = bytearray(self.size)
        self.frontier: set[int] = set()
        self.unknown = self.size
        self.mines_found = 0

    # ----------------------------------------------------------- knowledge
    def add_safe(self, i: int, count: int) -> None:
        if self.state[i] != UNKNOWN:
            return
        self.state[i] = SAFE
        self.counts[i] = count
        self.unknown -= 1
        # Zeros matter too: a player's (wrong) flag can stop the cascade next to one.
        self.frontier.add(i)

    def add_mine(self, i: int) -> None:
        if self.state[i] != UNKNOWN:
            return
        self.state[i] = MINE
        self.unknown -= 1
        self.mines_found += 1

    # ----------------------------------------------------------- deduction
    def constraints(self) -> list[Constraint]:
        state, neighbors, counts = self.state, self.neighbors, self.counts
        seen: dict[frozenset, int] = {}
        for c in list(self.frontier):
            unknown = []
            mines = 0
            for n in neighbors[c]:
                s = state[n]
                if s == UNKNOWN:
                    unknown.append(n)
                elif s == MINE:
                    mines += 1
            if not unknown:
                self.frontier.discard(c)
                continue
            seen[frozenset(unknown)] = counts[c] - mines
        return list(seen.items())

    def step(self) -> tuple[set[int], set[int]]:
        """Deduce some safe cells and/or mines. Empty sets mean "stuck"."""
        constraints = self.constraints()
        safe, mines = _single(constraints)
        if safe or mines:
            return safe, mines
        safe, mines = _pairs(constraints)
        if safe or mines:
            return safe, mines
        safe, mines = self._global()
        if safe or mines:
            return safe, mines
        return self._enumerate(constraints)

    def _global(self) -> tuple[set[int], set[int]]:
        left = self.total - self.mines_found
        if left == 0 or left == self.unknown:
            cells = {i for i in range(self.size) if self.state[i] == UNKNOWN}
            return (cells, set()) if left == 0 else (set(), cells)
        return set(), set()

    def _enumerate(self, constraints: list[Constraint]) -> tuple[set[int], set[int]]:
        safe: set[int] = set()
        mines: set[int] = set()
        bounds: list[tuple[int, int]] = []
        frontier_cells: set[int] = set()
        complete = True
        for comp_constraints, cells in _components(constraints):
            frontier_cells.update(cells)
            result = _enumerate_component(comp_constraints, cells)
            if result is None:
                complete = False
                continue
            always_safe, always_mine, lo, hi = result
            safe |= always_safe
            mines |= always_mine
            bounds.append((lo, hi))
        if safe or mines or not complete:
            return safe, mines
        # Mines that must lie in the cells no number touches.
        interior = [
            i for i in range(self.size) if self.state[i] == UNKNOWN and i not in frontier_cells
        ]
        if interior:
            left = self.total - self.mines_found
            most = left - sum(lo for lo, _ in bounds)
            least = left - sum(hi for _, hi in bounds)
            if most == 0:
                return set(interior), set()
            if least == len(interior):
                return set(), set(interior)
        return set(), set()


def _single(constraints: list[Constraint]) -> tuple[set[int], set[int]]:
    safe: set[int] = set()
    mines: set[int] = set()
    for cells, need in constraints:
        if need == 0:
            safe |= cells
        elif need == len(cells):
            mines |= cells
    return safe, mines


def _pairs(constraints: list[Constraint]) -> tuple[set[int], set[int]]:
    safe: set[int] = set()
    mines: set[int] = set()
    by_cell: dict[int, list[int]] = {}
    for idx, (cells, _) in enumerate(constraints):
        for cell in cells:
            by_cell.setdefault(cell, []).append(idx)
    for a_idx, (a, ra) in enumerate(constraints):
        partners = {b for cell in a for b in by_cell[cell] if b > a_idx}
        for b_idx in partners:
            b, rb = constraints[b_idx]
            inter = a & b
            a_only = a - inter
            b_only = b - inter
            hi = min(ra, rb, len(inter))
            lo = max(0, ra - len(a_only), rb - len(b_only))
            for only, r in ((a_only, ra), (b_only, rb)):
                if not only:
                    continue
                if r - lo == 0:
                    safe |= only
                elif r - hi == len(only):
                    mines |= only
            if hi == 0:
                safe |= inter
            elif lo == len(inter):
                mines |= inter
    return safe, mines


def _components(constraints: list[Constraint]) -> Iterable[tuple[list[Constraint], list[int]]]:
    parent = list(range(len(constraints)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[int, int] = {}
    for idx, (cells, _) in enumerate(constraints):
        for cell in cells:
            if cell in owner:
                ra, rb = find(owner[cell]), find(idx)
                if ra != rb:
                    parent[ra] = rb
            else:
                owner[cell] = idx
    groups: dict[int, list[int]] = {}
    for idx in range(len(constraints)):
        groups.setdefault(find(idx), []).append(idx)
    for members in groups.values():
        comp = [constraints[m] for m in members]
        cells = sorted({c for cs, _ in comp for c in cs})
        yield comp, cells


def _enumerate_component(
    constraints: list[Constraint], cells: list[int]
) -> Optional[tuple[set[int], set[int], int, int]]:
    """Enumerate all mine layouts of one frontier region.

    Returns cells that are safe/mines in every layout plus the minimum and
    maximum number of mines in the region, or None if the region is too big.
    """
    if len(cells) > ENUM_MAX_CELLS:
        return None
    # Order cells so that constraints are completed as early as possible.
    order: list[int] = []
    placed: set[int] = set()
    cell_cons: dict[int, list[int]] = {c: [] for c in cells}
    for idx, (cs, _) in enumerate(constraints):
        for c in cs:
            cell_cons[c].append(idx)
    for cs, _ in sorted(constraints, key=lambda con: len(con[0])):
        for c in sorted(cs):
            if c not in placed:
                placed.add(c)
                order.append(c)
    n = len(order)
    need = [r for _, r in constraints]
    remaining = [len(cs) for cs, _ in constraints]
    cons_of = [cell_cons[c] for c in order]
    assign = [0] * n
    mine_hits = [0] * n
    solutions = 0
    lo, hi = n + 1, -1
    nodes = 0

    def place(k: int, mines_so_far: int) -> bool:
        nonlocal solutions, lo, hi, nodes
        nodes += 1
        if nodes > ENUM_MAX_NODES:
            return False
        if k == n:
            solutions += 1
            lo = min(lo, mines_so_far)
            hi = max(hi, mines_so_far)
            for j in range(n):
                if assign[j]:
                    mine_hits[j] += 1
            return True
        for value in (0, 1):
            ok = True
            for ci in cons_of[k]:
                need[ci] -= value
                remaining[ci] -= 1
            for ci in cons_of[k]:
                if need[ci] < 0 or need[ci] > remaining[ci]:
                    ok = False
                    break
            if ok:
                assign[k] = value
                if not place(k + 1, mines_so_far + value):
                    for ci in cons_of[k]:
                        need[ci] += value
                        remaining[ci] += 1
                    return False
            for ci in cons_of[k]:
                need[ci] += value
                remaining[ci] += 1
        assign[k] = 0
        return True

    if not place(0, 0) or solutions == 0:
        return None
    safe = {order[j] for j in range(n) if mine_hits[j] == 0}
    mines = {order[j] for j in range(n) if mine_hits[j] == solutions}
    return safe, mines, lo, hi


# --------------------------------------------------------------------------
# Board-level helpers
# --------------------------------------------------------------------------


def _open(solver: Solver, i: int, counts: bytes, neighbors: list[tuple[int, ...]]) -> None:
    """Reveal ``i`` in the solver's view, flood-filling zeros like the game does."""
    stack = [i]
    while stack:
        c = stack.pop()
        if solver.state[c] != UNKNOWN:
            continue
        solver.add_safe(c, counts[c])
        if counts[c] == 0:
            stack.extend(n for n in neighbors[c] if solver.state[n] == UNKNOWN)


def is_solvable(
    mines: bytes, counts: bytes, neighbors: list[tuple[int, ...]], total: int, first: int
) -> bool:
    """Can the board be cleared from ``first`` using logic alone?"""
    solver = Solver(neighbors, total)
    _open(solver, first, counts, neighbors)
    safe_cells = len(neighbors) - total
    while solver.size - solver.unknown - solver.mines_found < safe_cells:
        safe, found = solver.step()
        if not safe and not found:
            return False
        for m in found:
            solver.add_mine(m)
        for s in safe:
            if mines[s]:  # would mean a solver bug; never accept such a board
                return False
            _open(solver, s, counts, neighbors)
    return True


def _counts(mines: bytes, neighbors: list[tuple[int, ...]]) -> bytearray:
    return bytearray(sum(mines[n] for n in neighbors[i]) for i in range(len(neighbors)))


def generate_no_guess(
    game: "Game",
    first: int,
    zone: set[int],
    rng: random.Random,
    time_budget: float = 2.5,
) -> tuple[bytearray, bool]:
    """Find a mine layout that can be solved without guessing.

    Falls back to the last random layout (and returns ``False``) when nothing
    is found within ``time_budget`` seconds, which can happen on very dense
    custom boards.
    """
    size, total, neighbors = game.size, game.mine_count, game.neighbors
    candidates = [i for i in range(size) if i not in zone]
    deadline = time.monotonic() + time_budget
    mines = bytearray(size)
    while True:
        mines = bytearray(size)
        for i in rng.sample(candidates, total):
            mines[i] = 1
        if is_solvable(mines, _counts(mines, neighbors), neighbors, total, first):
            return mines, True
        if time.monotonic() > deadline:
            return mines, False


def find_hint(game: "Game") -> Optional[tuple[int, str]]:
    """Find a cell that is provably safe from what the player can see.

    Returns ``(cell, kind)`` where kind is ``"safe"`` (a hidden cell that can
    be revealed) or ``"wrong-flag"`` (a flagged cell that cannot be a mine), or
    ``None`` when the position requires a guess.
    """
    from openmine.game import Cell

    solver = Solver(game.neighbors, game.mine_count)
    for i in range(game.size):
        if game.cells[i] == Cell.REVEALED and not game.mines[i]:
            solver.add_safe(i, game.counts[i])
    while True:
        safe, found = solver.step()
        if not safe and not found:
            return None
        for m in found:
            solver.add_mine(m)
        if safe:
            wrong = sorted(s for s in safe if game.cells[s] == Cell.FLAGGED)
            if wrong:
                return wrong[0], "wrong-flag"
            # Prefer the safe cell that touches the most revealed numbers: it is
            # the one the player is most likely looking at.
            best = max(
                safe,
                key=lambda s: (
                    sum(1 for n in game.neighbors[s] if game.cells[n] == Cell.REVEALED),
                    -s,
                ),
            )
            return best, "safe"
