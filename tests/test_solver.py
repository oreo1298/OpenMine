import random

import pytest

from openmine.game import (
    BEGINNER,
    EXPERT,
    INTERMEDIATE,
    Cell,
    Game,
    Status,
    custom_difficulty,
    neighbor_table,
)
from openmine.solver import Solver, find_hint, is_solvable


def _solver_from_game(game: Game) -> Solver:
    solver = Solver(game.neighbors, game.mine_count)
    for i in range(game.size):
        if game.cells[i] == Cell.REVEALED:
            solver.add_safe(i, game.counts[i])
    return solver


@pytest.mark.parametrize("difficulty", [BEGINNER, INTERMEDIATE, EXPERT, custom_difficulty(12, 10, 30)])
def test_solver_never_makes_a_wrong_deduction(difficulty):
    rng = random.Random(42)
    for seed in range(25):
        game = Game(difficulty.cols, difficulty.rows, difficulty.mines, seed=seed)
        game.reveal(rng.randrange(game.size))
        solver = _solver_from_game(game)
        for _ in range(200):
            safe, mines = solver.step()
            if not safe and not mines:
                break
            for m in mines:
                assert game.mines[m], "solver marked a safe cell as a mine"
                solver.add_mine(m)
            for s in safe:
                assert not game.mines[s], "solver marked a mine as safe"
                game.reveal(s)
            for i in range(game.size):
                if game.cells[i] == Cell.REVEALED:
                    solver.add_safe(i, game.counts[i])
            if game.finished:
                break
        assert game.status != Status.LOST


@pytest.mark.parametrize("difficulty", [BEGINNER, INTERMEDIATE, EXPERT])
def test_no_guess_boards_are_solvable(difficulty):
    for seed in range(5):
        game = Game(difficulty.cols, difficulty.rows, difficulty.mines, no_guess=True, seed=seed)
        first = game.index(difficulty.cols // 3, difficulty.rows // 2)
        game.reveal(first)
        assert game.no_guess_ok is True
        assert is_solvable(game.mines, game.counts, game.neighbors, game.mine_count, first)
        # And the hint engine can actually finish it.
        for _ in range(game.size):
            if game.finished:
                break
            hint = find_hint(game)
            assert hint is not None
            cell, kind = hint
            assert kind == "safe"
            game.reveal(cell)
        assert game.status == Status.WON


def test_no_guess_falls_back_when_out_of_time(monkeypatch):
    monkeypatch.setattr(Game, "NO_GUESS_TIME_BUDGET", 0.0)
    found = []
    for seed in range(10):
        game = Game(16, 16, 80, no_guess=True, seed=seed)
        game.reveal(100)
        assert sum(game.mines) == 80
        assert not game.mines[100]
        found.append(game.no_guess_ok)
    assert False in found  # with no time at all, dense boards fall back


def test_pair_rule():
    # Hidden row above three revealed 1s; the mine is in the middle.
    solver = Solver(neighbor_table(3, 2), 1)
    for i in (3, 4, 5):
        solver.add_safe(i, 1)
    safe, mines = solver.step()
    assert safe == {0, 2}
    assert mines == set()
    for i in safe:
        solver.add_safe(i, 1)
    safe, mines = solver.step()
    assert mines == {1}


def test_interior_rule_uses_mine_count():
    # One "1" in a corner accounts for the only mine, so every cell it
    # doesn't touch must be safe.
    solver = Solver(neighbor_table(3, 3), 1)
    solver.add_safe(0, 1)
    safe, mines = solver.step()
    assert safe == {2, 5, 6, 7, 8}
    assert mines == set()


HINT_LAYOUT = """
*.*..
.....
.....
"""


def test_hint_finds_safe_cell():
    game = Game.from_layout(HINT_LAYOUT)
    game.reveal(game.index(4, 2))
    assert game.status == Status.PLAYING
    assert find_hint(game) == (game.index(1, 0), "safe")


def test_hint_reports_wrong_flag():
    game = Game.from_layout(HINT_LAYOUT)
    game.reveal(game.index(4, 2))
    game.cycle_mark(game.index(1, 0))
    assert find_hint(game) == (game.index(1, 0), "wrong-flag")


def test_hint_returns_none_for_a_coin_flip():
    game = Game.from_layout("*.\n..")
    game.reveal(3)
    assert game.counts[3] == 1
    assert find_hint(game) is None


def test_global_mine_count_rule():
    solver = Solver(neighbor_table(3, 3), 2)
    for i in range(7):
        solver.add_safe(i, 0)
    safe, mines = solver.step()
    assert mines == {7, 8}
