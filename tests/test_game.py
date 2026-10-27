import pytest

from openmine.game import (
    BEGINNER,
    EXPERT,
    INTERMEDIATE,
    MAX_COLS,
    MIN_ROWS,
    Cell,
    Game,
    Status,
    custom_difficulty,
    max_mines,
    neighbor_table,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_neighbor_table_shapes():
    table = neighbor_table(4, 3)
    assert len(table) == 12
    assert sorted(table[0]) == [1, 4, 5]  # corner
    assert len(table[1]) == 5  # edge
    assert sorted(table[5]) == [0, 1, 2, 4, 6, 8, 9, 10]  # interior
    for i, neighbors in enumerate(table):
        assert i not in neighbors
        for n in neighbors:
            assert i in table[n]


@pytest.mark.parametrize("difficulty", [BEGINNER, INTERMEDIATE, EXPERT])
def test_first_click_always_opens(difficulty):
    for seed in range(40):
        game = Game(difficulty.cols, difficulty.rows, difficulty.mines, seed=seed)
        first = (seed * 7919) % game.size
        opened = game.reveal(first)
        assert game.status == Status.PLAYING
        assert sum(game.mines) == difficulty.mines
        assert not game.mines[first]
        assert game.counts[first] == 0
        assert len(opened) > 1


def test_first_click_safe_on_densest_board():
    cols, rows = 5, 5
    for seed in range(20):
        game = Game(cols, rows, max_mines(cols, rows), seed=seed)
        game.reveal(12)
        assert game.status in (Status.PLAYING, Status.WON)
        assert not game.mines[12]


def test_first_click_safe_even_when_no_opening_fits():
    for seed in range(20):
        game = Game(3, 3, 8, seed=seed)
        game.reveal(4)
        assert game.status == Status.WON


def test_flood_fill_stops_at_numbers():
    game = Game.from_layout(
        """
        .....
        .....
        ....*
        """
    )
    opened = game.reveal(0)
    revealed = {i for i, _ in opened}
    assert game.counts[game.index(3, 1)] == 1
    assert game.index(3, 1) in revealed
    assert game.index(4, 2) not in revealed
    depths = dict(opened)
    assert depths[0] == 0
    assert max(depths.values()) >= 3
    assert game.status == Status.WON


def test_revealing_a_mine_loses():
    game = Game.from_layout("*.\n..")
    game.reveal(1)
    game.reveal(0)
    assert game.status == Status.LOST
    assert game.exploded == {0}
    assert game.finished
    # No more moves once the game is over.
    assert game.reveal(3) == []
    assert not game.cycle_mark(3)


def test_flags_and_question_marks():
    game = Game(9, 9, 10, seed=1)
    assert game.cycle_mark(0)
    assert game.cells[0] == Cell.FLAGGED and game.flags == 1 and game.mines_left == 9
    assert game.reveal(0) == []  # flagged cells cannot be revealed
    assert game.cycle_mark(0, question_marks=True)
    assert game.cells[0] == Cell.QUESTION and game.flags == 0
    assert game.cycle_mark(0, question_marks=True)
    assert game.cells[0] == Cell.HIDDEN
    game.cycle_mark(0)
    game.cycle_mark(0, question_marks=False)
    assert game.cells[0] == Cell.HIDDEN


def test_mine_counter_can_go_negative():
    game = Game(5, 5, 1, seed=3)
    game.cycle_mark(0)
    game.cycle_mark(1)
    assert game.mines_left == -1


LAYOUT = """
*....
.....
.....
....*
"""


def test_chord_reveals_neighbours():
    game = Game.from_layout(LAYOUT)
    game.reveal(game.index(1, 1))  # a "1" next to the corner mine
    assert game.counts[game.index(1, 1)] == 1
    assert not game.can_chord(game.index(1, 1))
    game.cycle_mark(0)
    assert game.can_chord(game.index(1, 1))
    opened = game.chord(game.index(1, 1))
    assert opened
    assert game.cells[game.index(0, 1)] == Cell.REVEALED
    assert game.status in (Status.PLAYING, Status.WON)


def test_chord_with_wrong_flag_loses():
    game = Game.from_layout(LAYOUT)
    game.reveal(game.index(1, 1))
    game.cycle_mark(game.index(1, 0))  # wrong flag; the mine is at (0, 0)
    assert game.can_chord(game.index(1, 1))
    game.chord(game.index(1, 1))
    assert game.status == Status.LOST
    assert game.exploded == {0}
    assert game.is_wrong_flag(game.index(1, 0))


def test_win_flags_all_mines():
    game = Game.from_layout(LAYOUT)
    for i in range(game.size):
        if not game.mines[i]:
            game.reveal(i)
    assert game.status == Status.WON
    assert game.flags == 2
    assert game.cells[0] == Cell.FLAGGED
    assert game.safe_left == 0


def test_wrongly_flagged_safe_cell_blocks_win():
    game = Game.from_layout("*.\n..\n..")
    game.cycle_mark(5)
    for i in (1, 2, 3, 4):
        game.reveal(i)
    assert game.status == Status.PLAYING
    game.cycle_mark(5)
    game.reveal(5)
    assert game.status == Status.WON


def test_timer_pause_and_resume():
    clock = FakeClock()
    game = Game.from_layout(LAYOUT, clock=clock)
    assert game.elapsed() == 0
    game.reveal(game.index(1, 1))
    assert game.status == Status.PLAYING
    clock.now += 5
    assert game.elapsed() == pytest.approx(5)
    game.pause()
    assert game.paused
    assert game.reveal(game.index(2, 2)) == []  # no moves while paused
    clock.now += 100
    assert game.elapsed() == pytest.approx(5)
    game.resume()
    clock.now += 2
    assert game.elapsed() == pytest.approx(7)
    for i in range(game.size):
        if not game.mines[i]:
            game.reveal(i)
    clock.now += 50
    assert game.status == Status.WON
    assert game.elapsed() == pytest.approx(7)


def test_custom_difficulty_is_clamped():
    d = custom_difficulty(1000, 1, 10_000)
    assert d.cols == MAX_COLS
    assert d.rows == MIN_ROWS
    assert d.mines == max_mines(d.cols, d.rows)
    assert d.is_custom
    assert custom_difficulty(9, 9, 10) is BEGINNER


def test_layout_rows_must_match():
    with pytest.raises(ValueError):
        Game.from_layout("*..\n..")
