"""Core Minesweeper rules.

This module is pure Python and has no Qt dependency so it can be unit tested
(and reused) on its own. Cells are addressed by a flat index
``i = row * cols + col``.
"""

from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

MIN_COLS = 5
MAX_COLS = 60
MIN_ROWS = 5
MAX_ROWS = 40
MIN_MINES = 1


class Cell(IntEnum):
    HIDDEN = 0
    REVEALED = 1
    FLAGGED = 2
    QUESTION = 3


class Status(IntEnum):
    READY = 0  # nothing clicked yet, mines not placed
    PLAYING = 1
    WON = 2
    LOST = 3


@dataclass(frozen=True)
class Difficulty:
    key: str
    cols: int
    rows: int
    mines: int

    @property
    def label(self) -> str:
        return PRESET_LABELS.get(self.key, "Custom")

    @property
    def is_custom(self) -> bool:
        return self.key not in PRESETS


BEGINNER = Difficulty("beginner", 9, 9, 10)
INTERMEDIATE = Difficulty("intermediate", 16, 16, 40)
EXPERT = Difficulty("expert", 30, 16, 99)

PRESETS = {d.key: d for d in (BEGINNER, INTERMEDIATE, EXPERT)}
PRESET_LABELS = {"beginner": "Beginner", "intermediate": "Intermediate", "expert": "Expert"}


def max_mines(cols: int, rows: int) -> int:
    """Most mines a board may hold while still guaranteeing a 3x3 opening."""
    return cols * rows - 9


def custom_difficulty(cols: int, rows: int, mines: int) -> Difficulty:
    cols = max(MIN_COLS, min(MAX_COLS, int(cols)))
    rows = max(MIN_ROWS, min(MAX_ROWS, int(rows)))
    mines = max(MIN_MINES, min(max_mines(cols, rows), int(mines)))
    for preset in PRESETS.values():
        if (preset.cols, preset.rows, preset.mines) == (cols, rows, mines):
            return preset
    return Difficulty("custom", cols, rows, mines)


def neighbor_table(cols: int, rows: int) -> list[tuple[int, ...]]:
    table = []
    for r in range(rows):
        for c in range(cols):
            table.append(
                tuple(
                    rr * cols + cc
                    for rr in range(max(0, r - 1), min(rows, r + 2))
                    for cc in range(max(0, c - 1), min(cols, c + 2))
                    if rr != r or cc != c
                )
            )
    return table


class Game:
    """State of a single game of Minesweeper.

    Mines are placed lazily on the first reveal so the first click is always
    safe and, whenever the mine density allows it, opens up an area.
    """

    # Seconds to spend looking for a no-guess layout before giving up.
    NO_GUESS_TIME_BUDGET = 2.5

    def __init__(
        self,
        cols: int,
        rows: int,
        mines: int,
        *,
        no_guess: bool = False,
        seed: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (1 <= cols and 1 <= rows):
            raise ValueError("board must have at least one cell")
        if not (0 < mines < cols * rows):
            raise ValueError("mine count out of range")
        self.cols = cols
        self.rows = rows
        self.mine_count = mines
        self.size = cols * rows
        self.neighbors = neighbor_table(cols, rows)
        self.mines = bytearray(self.size)
        self.counts = bytearray(self.size)
        self.cells = bytearray(self.size)
        self.status = Status.READY
        self.revealed = 0
        self.flags = 0
        self.exploded: set[int] = set()
        self.no_guess = no_guess
        # None until mines are placed; False if a no-guess board could not be
        # generated in time and a regular random board was used instead.
        self.no_guess_ok: Optional[bool] = None
        self.hints_used = 0
        self._placed = False
        self._rng = random.Random(seed)
        self._clock = clock
        self._started: Optional[float] = None
        self._accumulated = 0.0
        self._paused = False

    @classmethod
    def from_layout(cls, layout: str, **kwargs) -> "Game":
        """Build a game with a fixed mine layout, e.g. ``"*..\\n...\\n..*"``."""
        rows = [row.strip() for row in layout.strip().splitlines() if row.strip()]
        cols = len(rows[0])
        if any(len(row) != cols for row in rows):
            raise ValueError("all rows must have the same length")
        mines = bytearray(1 if ch == "*" else 0 for row in rows for ch in row)
        game = cls(cols, len(rows), sum(mines), **kwargs)
        game._set_mines(mines)
        game._placed = True
        return game

    # ------------------------------------------------------------------ info
    def index(self, col: int, row: int) -> int:
        return row * self.cols + col

    def coords(self, i: int) -> tuple[int, int]:
        return i % self.cols, i // self.cols

    @property
    def finished(self) -> bool:
        return self.status in (Status.WON, Status.LOST)

    @property
    def mines_left(self) -> int:
        """Mine counter shown to the player (may go negative)."""
        return self.mine_count - self.flags

    @property
    def safe_left(self) -> int:
        return self.size - self.mine_count - self.revealed

    def flagged_neighbors(self, i: int) -> int:
        cells = self.cells
        return sum(1 for n in self.neighbors[i] if cells[n] == Cell.FLAGGED)

    def can_chord(self, i: int) -> bool:
        if self.status != Status.PLAYING or self.cells[i] != Cell.REVEALED:
            return False
        count = self.counts[i]
        if count == 0 or self.flagged_neighbors(i) != count:
            return False
        return any(self.cells[n] in (Cell.HIDDEN, Cell.QUESTION) for n in self.neighbors[i])

    def is_wrong_flag(self, i: int) -> bool:
        return self.status == Status.LOST and self.cells[i] == Cell.FLAGGED and not self.mines[i]

    # ----------------------------------------------------------------- timer
    def elapsed(self) -> float:
        total = self._accumulated
        if self._started is not None and not self._paused:
            total += self._clock() - self._started
        return total

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        if self.status == Status.PLAYING and not self._paused:
            self._accumulated = self.elapsed()
            self._started = None
            self._paused = True

    def resume(self) -> None:
        if self._paused:
            self._paused = False
            if self.status == Status.PLAYING:
                self._started = self._clock()

    def _stop_timer(self) -> None:
        self._accumulated = self.elapsed()
        self._started = None

    # --------------------------------------------------------------- actions
    def reveal(self, i: int) -> list[tuple[int, int]]:
        """Reveal a cell. Returns ``(cell, depth)`` for every newly revealed cell.

        ``depth`` is the flood-fill distance from ``i`` and is handy for
        animating the cascade.
        """
        if self.finished or self._paused:
            return []
        if self.cells[i] not in (Cell.HIDDEN, Cell.QUESTION):
            return []
        if self.status == Status.READY:
            if not self._placed:
                self._place_mines(i)
            self.status = Status.PLAYING
            self._started = self._clock()
        if self.mines[i]:
            self.cells[i] = Cell.REVEALED
            self._lose({i})
            return [(i, 0)]
        opened = self._flood(i)
        self._check_win()
        return opened

    def chord(self, i: int) -> list[tuple[int, int]]:
        """Reveal all unflagged neighbours of a satisfied number."""
        if not self.can_chord(i) or self._paused:
            return []
        targets = [n for n in self.neighbors[i] if self.cells[n] in (Cell.HIDDEN, Cell.QUESTION)]
        boom = {n for n in targets if self.mines[n]}
        if boom:
            opened = []
            for n in targets:
                if self.mines[n]:
                    self.cells[n] = Cell.REVEALED
                    opened.append((n, 1))
            self._lose(boom)
            return opened
        opened: list[tuple[int, int]] = []
        for n in targets:
            if self.cells[n] != Cell.REVEALED:
                opened.extend((cell, depth + 1) for cell, depth in self._flood(n))
        self._check_win()
        return opened

    def cycle_mark(self, i: int, question_marks: bool = False) -> bool:
        """Hidden → flag → (question →) hidden. Returns True if anything changed."""
        if self.finished or self._paused:
            return False
        state = self.cells[i]
        if state == Cell.HIDDEN:
            self.cells[i] = Cell.FLAGGED
            self.flags += 1
        elif state == Cell.FLAGGED:
            self.flags -= 1
            self.cells[i] = Cell.QUESTION if question_marks else Cell.HIDDEN
        elif state == Cell.QUESTION:
            self.cells[i] = Cell.HIDDEN
        else:
            return False
        return True

    # -------------------------------------------------------------- internal
    def _safe_zone(self, first: int) -> set[int]:
        zone = {first, *self.neighbors[first]}
        if self.size - len(zone) >= self.mine_count:
            return zone
        return {first}

    def _place_mines(self, first: int) -> None:
        zone = self._safe_zone(first)
        if self.no_guess:
            from openmine.solver import generate_no_guess

            mines, ok = generate_no_guess(self, first, zone, self._rng, self.NO_GUESS_TIME_BUDGET)
            self.no_guess_ok = ok
        else:
            candidates = [i for i in range(self.size) if i not in zone]
            mines = bytearray(self.size)
            for i in self._rng.sample(candidates, self.mine_count):
                mines[i] = 1
        self._set_mines(mines)
        self._placed = True

    def _set_mines(self, mines: bytearray) -> None:
        self.mines = bytearray(mines)
        neighbors = self.neighbors
        self.counts = bytearray(
            sum(self.mines[n] for n in neighbors[i]) for i in range(self.size)
        )

    def _flood(self, start: int) -> list[tuple[int, int]]:
        cells, counts, neighbors = self.cells, self.counts, self.neighbors
        opened = []
        queue = deque([(start, 0)])
        cells[start] = Cell.REVEALED
        while queue:
            i, depth = queue.popleft()
            opened.append((i, depth))
            if counts[i] == 0:
                for n in neighbors[i]:
                    if cells[n] in (Cell.HIDDEN, Cell.QUESTION):
                        cells[n] = Cell.REVEALED
                        queue.append((n, depth + 1))
        self.revealed += len(opened)
        return opened

    def _check_win(self) -> None:
        if self.status == Status.PLAYING and self.safe_left == 0:
            self.status = Status.WON
            self._stop_timer()
            for i in range(self.size):
                if self.mines[i] and self.cells[i] != Cell.FLAGGED:
                    self.cells[i] = Cell.FLAGGED
            self.flags = self.mine_count

    def _lose(self, exploded: set[int]) -> None:
        self.exploded = exploded
        self.status = Status.LOST
        self._stop_timer()
