"""Smoke tests for the Qt user interface (run headless with the offscreen platform)."""

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from openmine.config import Settings, Stats  # noqa: E402
from openmine.game import Cell, Game, Status  # noqa: E402
from openmine.painting import FACE_LOST, FACE_SLEEP, FACE_WON  # noqa: E402
from openmine.theme import ThemeManager, is_dark  # noqa: E402
from openmine.window import MainWindow, format_clock  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(["openmine-tests"])


@pytest.fixture
def window(app):
    settings = Settings.load()
    theme = ThemeManager(app, "system")
    win = MainWindow(theme, settings, Stats())
    win.show()
    QTest.qWaitForWindowExposed(win)
    yield win
    win.close()
    theme.set_mode("system")
    app.removeEventFilter(theme)


def click(board, cell, button=Qt.MouseButton.LeftButton):
    center = board.cell_rect(cell).center().toPoint()
    QTest.mouseClick(board, button, Qt.KeyboardModifier.NoModifier, center)


def use_layout(window, layout):
    game = Game.from_layout(layout)
    window.game = game
    window.board.set_game(game)
    return game


LAYOUT = """
*........
.........
.........
.........
....*....
.........
.........
.........
........*
"""


# A wall of mines keeps the first click from clearing the whole board.
WALL = "\n".join(["....*...."] * 9)


def window_is_dark(app):
    return is_dark(app.palette().color(QPalette.ColorRole.Window))


def test_theme_modes(app, monkeypatch):
    native_window = app.palette().color(QPalette.ColorRole.Window)
    system = {"scheme": "light"}
    monkeypatch.setattr(ThemeManager, "system_scheme", lambda self: system["scheme"])
    theme = ThemeManager(app, "dark")
    try:
        assert theme.dark and window_is_dark(app)
        assert theme.colors.dark
        theme.set_mode("light")
        assert not theme.dark and not window_is_dark(app)
        theme.set_mode("system")
        assert not theme.dark
        assert app.palette().color(QPalette.ColorRole.Window) == native_window
        # The desktop switches to dark: the app follows.
        system["scheme"] = "dark"
        theme.refresh()
        assert theme.dark and window_is_dark(app)
        system["scheme"] = "light"
        theme.refresh()
        assert app.palette().color(QPalette.ColorRole.Window) == native_window
    finally:
        theme.set_mode("system")
        app.removeEventFilter(theme)


def test_left_click_reveals_and_starts_clock(window):
    board = window.board
    cell = window.game.index(4, 4)
    click(board, cell)
    assert window.game.status == Status.PLAYING
    assert window.game.cells[cell] == Cell.REVEALED
    assert window.clock.isActive()


def test_right_click_flags(window):
    board = window.board
    click(board, 0, Qt.MouseButton.RightButton)
    assert window.game.cells[0] == Cell.FLAGGED
    assert window.mine_pill._text == str(window.game.mine_count - 1)
    click(board, 0, Qt.MouseButton.RightButton)
    assert window.game.cells[0] == Cell.HIDDEN


def test_click_on_number_chords(window):
    game = use_layout(window, LAYOUT)
    one = game.index(1, 1)
    click(window.board, one)
    assert game.cells[one] == Cell.REVEALED
    click(window.board, 0, Qt.MouseButton.RightButton)
    click(window.board, one)
    assert game.cells[game.index(1, 0)] == Cell.REVEALED
    assert game.cells[game.index(0, 1)] == Cell.REVEALED


def test_middle_click_chords(window):
    game = use_layout(window, LAYOUT)
    one = game.index(1, 1)
    click(window.board, one)
    click(window.board, 0, Qt.MouseButton.RightButton)
    window.settings.chord_on_click = False
    click(window.board, one)
    assert game.cells[game.index(1, 0)] == Cell.HIDDEN
    click(window.board, one, Qt.MouseButton.MiddleButton)
    assert game.cells[game.index(1, 0)] == Cell.REVEALED


def test_keyboard_play(window):
    game = use_layout(window, LAYOUT)
    board = window.board
    board.setFocus()
    QTest.keyClick(board, Qt.Key.Key_Left)  # shows the cursor (centre cell)
    QTest.keyClick(board, Qt.Key.Key_Up)
    assert board._cursor == game.index(4, 3)
    QTest.keyClick(board, Qt.Key.Key_Space)
    assert game.cells[game.index(4, 3)] == Cell.REVEALED
    QTest.keyClick(board, Qt.Key.Key_Down)
    QTest.keyClick(board, Qt.Key.Key_F)
    assert game.cells[game.index(4, 4)] == Cell.FLAGGED


def test_loss_shows_card_and_records(window):
    game = use_layout(window, WALL)
    click(window.board, 0)
    assert game.status == Status.PLAYING
    click(window.board, game.index(4, 4))
    assert game.status == Status.LOST
    assert window.end_card.isVisible()
    assert window.end_card.title.text() == "Boom!"
    assert window.face._mood == FACE_LOST
    assert window.stats.get("beginner").played == 1


def test_win_records_time(window):
    game = use_layout(window, LAYOUT)
    for i in range(game.size):
        if not game.mines[i] and game.cells[i] != Cell.REVEALED:
            click(window.board, i)
    assert game.status == Status.WON
    assert window.face._mood == FACE_WON
    record = window.stats.get("beginner")
    assert record.won == 1 and record.best_time is not None
    assert "You won" in window.end_card.title.text()
    window.new_game()
    assert not window.end_card.isVisible()
    assert window.game.status == Status.READY


def test_hint_and_pause(window):
    game = use_layout(window, WALL)
    click(window.board, 0)
    window.hint()
    assert game.hints_used == 1
    assert window.board._hint is not None
    cell = window.board._hint[0]
    assert not game.mines[cell]
    window.toggle_pause()
    assert game.paused and window.face._mood == FACE_SLEEP
    click(window.board, cell)  # clicking a paused board resumes instead of playing
    assert not game.paused
    assert game.cells[cell] != Cell.REVEALED
    window.grab()


def test_double_click_on_paused_board_only_resumes(window):
    game = use_layout(window, WALL)
    click(window.board, 0)
    window.toggle_pause()
    target = game.index(6, 4)  # hidden, on the far side of the wall
    assert game.cells[target] == Cell.HIDDEN
    center = QPointF(window.board.cell_rect(target).center())
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    # What a real double click delivers: press, release, double-click, release.
    for kind, buttons in (
        (QEvent.Type.MouseButtonPress, left),
        (QEvent.Type.MouseButtonRelease, none),
        (QEvent.Type.MouseButtonDblClick, left),
        (QEvent.Type.MouseButtonRelease, none),
    ):
        event = QMouseEvent(kind, center, center, left, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(window.board, event)
    assert not game.paused
    assert game.cells[target] == Cell.HIDDEN


def test_held_keys_do_not_repeat_actions(window):
    game = use_layout(window, LAYOUT)
    board = window.board
    board.setFocus()
    QTest.keyClick(board, Qt.Key.Key_Left)  # show the cursor
    cell = board._cursor
    QTest.keyClick(board, Qt.Key.Key_F)
    assert game.cells[cell] == Cell.FLAGGED
    repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier, "f", True)
    QApplication.sendEvent(board, repeat)
    assert game.cells[cell] == Cell.FLAGGED


def test_difficulty_switch(window):
    window.choose_difficulty("expert")
    assert (window.game.cols, window.game.rows, window.game.mine_count) == (30, 16, 99)
    assert window.settings.difficulty == "expert"
    assert window.difficulty_box.currentData() == "expert"


def test_rendering_in_both_themes(window):
    game = use_layout(window, LAYOUT)
    click(window.board, game.index(4, 0))
    click(window.board, 0, Qt.MouseButton.RightButton)
    for mode in ("dark", "light", "system"):
        window.set_theme(mode)
        image = window.grab().toImage()
        assert not image.isNull()
        center = window.board.mapTo(window, QPoint(2, 2))
        assert image.pixelColor(center).isValid()


def test_format_clock():
    assert format_clock(0) == "0:00"
    assert format_clock(75.9) == "1:15"
    assert format_clock(3725) == "1:02:05"
