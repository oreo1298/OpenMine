"""The minefield widget: drawing, input handling and animations."""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QInputDevice,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QStaticText,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from openmine.config import Settings
from openmine.game import Cell, Game, Status
from openmine.painting import draw_cross, draw_flag, draw_mine
from openmine.theme import BoardColors, ThemeManager, mix, with_alpha

REVEAL_DURATION = 0.17
REVEAL_STEP = 0.022
REVEAL_MAX_DELAY = 0.45
FLAG_DURATION = 0.22
MINE_DURATION = 0.2
MINE_SPREAD = 0.9
WAVE_STEP = 0.03
WAVE_DURATION = 0.55
LONG_PRESS_MS = 420


def _ease_out_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


class BoardWidget(QWidget):
    changed = Signal()  # counters / status changed
    started = Signal()  # first reveal of a game
    finished = Signal(bool)  # True when won
    pressing = Signal(bool)  # a cell is held down (for the face button)
    resume_requested = Signal()

    MARGIN = 6
    MIN_TILE = 14
    MAX_TILE = 72
    PREFERRED_TILE = 36

    def __init__(self, theme: ThemeManager, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.theme = theme
        self.settings = settings
        self.game: Optional[Game] = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Minefield")

        self._tile = 32
        self._origin = QPointF(0, 0)
        self._hover = -1
        self._cursor = 0
        self._show_cursor = False
        self._pressed: set[int] = set()
        self._left = False
        self._right = False
        self._chording = False
        self._swallow_release = False
        self._paused = False
        self._last_action = 0

        self._reveal_anim: dict[int, float] = {}
        self._flag_anim: dict[int, float] = {}
        self._mine_anim: dict[int, float] = {}
        self._wave_start: Optional[float] = None
        self._wave_origin = (0, 0)
        self._hint: Optional[tuple[int, str, float]] = None

        self._font = QFont()
        self._glyphs: dict[str, QStaticText] = {}
        self._glyph_tile = -1

        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._tick)
        self._long_press = QTimer(self)
        self._long_press.setSingleShot(True)
        self._long_press.setInterval(LONG_PRESS_MS)
        self._long_press.timeout.connect(self._on_long_press)
        self._long_press_cell = -1
        theme.changed.connect(self.update)

    # ------------------------------------------------------------ public api
    @property
    def colors(self) -> BoardColors:
        return self.theme.colors

    def set_game(self, game: Game) -> None:
        self.game = game
        self._reveal_anim.clear()
        self._flag_anim.clear()
        self._mine_anim.clear()
        self._wave_start = None
        self._hint = None
        self._pressed.clear()
        self._hover = -1
        self._paused = False
        self._cursor = game.index(game.cols // 2, game.rows // 2)
        self._relayout()
        self.updateGeometry()
        self.update()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pressed.clear()
        self.update()

    def show_hint(self, cell: int, kind: str) -> None:
        self._hint = (cell, kind, time.monotonic())
        self._cursor = cell
        self._ensure_ticking()
        self.update()

    def preferred_size(self, tile: Optional[int] = None) -> QSize:
        tile = tile or self.PREFERRED_TILE
        if not self.game:
            return QSize(9 * tile, 9 * tile)
        return QSize(self.game.cols * tile + 2 * self.MARGIN, self.game.rows * tile + 2 * self.MARGIN)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.preferred_size()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.preferred_size(self.MIN_TILE)

    def cell_rect(self, i: int) -> QRectF:
        assert self.game
        col, row = self.game.coords(i)
        t = self._tile
        return QRectF(self._origin.x() + col * t, self._origin.y() + row * t, t, t)

    def board_rect(self) -> QRectF:
        if not self.game:
            return QRectF(self.rect())
        t = self._tile
        return QRectF(self._origin.x(), self._origin.y(), self.game.cols * t, self.game.rows * t)

    # -------------------------------------------------------------- geometry
    def _relayout(self) -> None:
        if not self.game:
            return
        w = self.width() - 2 * self.MARGIN
        h = self.height() - 2 * self.MARGIN
        tile = int(min(w / self.game.cols, h / self.game.rows))
        self._tile = max(self.MIN_TILE, min(self.MAX_TILE, tile))
        bw = self._tile * self.game.cols
        bh = self._tile * self.game.rows
        self._origin = QPointF(round((self.width() - bw) / 2), round((self.height() - bh) / 2))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._relayout()
        super().resizeEvent(event)

    def cell_at(self, pos: QPointF) -> int:
        if not self.game:
            return -1
        col = math.floor((pos.x() - self._origin.x()) / self._tile)
        row = math.floor((pos.y() - self._origin.y()) / self._tile)
        if 0 <= col < self.game.cols and 0 <= row < self.game.rows:
            return self.game.index(col, row)
        return -1

    # ------------------------------------------------------------ animations
    @property
    def _animated(self) -> bool:
        return self.settings.animations

    def _ensure_ticking(self) -> None:
        if not self._ticker.isActive():
            self._ticker.start()

    def _tick(self) -> None:
        now = time.monotonic()
        self._reveal_anim = {c: t for c, t in self._reveal_anim.items() if now - t < REVEAL_DURATION}
        self._flag_anim = {c: t for c, t in self._flag_anim.items() if now - t < FLAG_DURATION}
        self._mine_anim = {c: t for c, t in self._mine_anim.items() if now - t < MINE_DURATION}
        if self._wave_start is not None and self.game:
            longest = (self.game.cols + self.game.rows) * WAVE_STEP + WAVE_DURATION
            if now - self._wave_start > longest:
                self._wave_start = None
        busy = self._reveal_anim or self._flag_anim or self._mine_anim or self._wave_start is not None
        if not busy and self._hint is None:
            self._ticker.stop()
        self.update()

    def _animate_reveal(self, opened: list[tuple[int, int]]) -> None:
        if not self._animated:
            return
        now = time.monotonic()
        for cell, depth in opened:
            self._reveal_anim[cell] = now + min(depth * REVEAL_STEP, REVEAL_MAX_DELAY)
        self._ensure_ticking()

    def _animate_loss(self) -> None:
        game = self.game
        if not self._animated or not game:
            return
        now = time.monotonic()
        ox, oy = game.coords(next(iter(game.exploded)))
        mines = [
            i for i in range(game.size)
            if game.mines[i] and i not in game.exploded and game.cells[i] != Cell.FLAGGED
        ]
        mines.sort(key=lambda i: math.dist((ox, oy), game.coords(i)))
        step = MINE_SPREAD / max(1, len(mines))
        for rank, i in enumerate(mines):
            self._mine_anim[i] = now + 0.12 + rank * min(step, 0.05)
        self._ensure_ticking()

    def _animate_win(self, origin: int) -> None:
        game = self.game
        if not self._animated or not game:
            return
        now = time.monotonic()
        self._wave_start = now
        self._wave_origin = game.coords(origin)
        for i in range(game.size):
            if game.mines[i] and i not in self._flag_anim:
                col, row = game.coords(i)
                self._flag_anim[i] = now + math.dist((col, row), self._wave_origin) * WAVE_STEP
        self._ensure_ticking()

    # ---------------------------------------------------------------- moves
    def _after_move(self, cell: int) -> None:
        game = self.game
        assert game
        self._hint = None
        self._last_action = cell
        if game.status == Status.LOST:
            self._animate_loss()
            self.finished.emit(False)
        elif game.status == Status.WON:
            self._animate_win(cell)
            self.finished.emit(True)
        self.changed.emit()
        self.update()

    def reveal(self, cell: int) -> None:
        game = self.game
        if not game or cell < 0 or self._paused:
            return
        was_ready = game.status == Status.READY
        opened = game.reveal(cell)
        if not opened:
            return
        if was_ready:
            self.started.emit()
        self._animate_reveal(opened)
        self._after_move(cell)

    def chord(self, cell: int) -> None:
        game = self.game
        if not game or cell < 0 or self._paused:
            return
        opened = game.chord(cell)
        if opened:
            self._animate_reveal(opened)
            self._after_move(cell)

    def mark(self, cell: int) -> None:
        game = self.game
        if not game or cell < 0 or self._paused:
            return
        if game.cycle_mark(cell, self.settings.question_marks):
            if game.cells[cell] == Cell.FLAGGED and self._animated:
                self._flag_anim[cell] = time.monotonic()
                self._ensure_ticking()
            if self._hint and self._hint[0] == cell:
                self._hint = None
            self.changed.emit()
            self.update()

    def act(self, cell: int) -> None:
        """Primary action: reveal hidden cells, chord on numbers."""
        game = self.game
        if not game or cell < 0:
            return
        if game.cells[cell] in (Cell.HIDDEN, Cell.QUESTION):
            self.reveal(cell)
        elif game.cells[cell] == Cell.REVEALED:
            self.chord(cell)

    # ---------------------------------------------------------------- input
    def _press_targets(self, cell: int) -> set[int]:
        game = self.game
        if not game or cell < 0 or game.finished:
            return set()
        cells = game.cells
        covered = (Cell.HIDDEN, Cell.QUESTION)
        if self._chording:
            area = (cell, *game.neighbors[cell])
            return {i for i in area if cells[i] in covered}
        if cells[cell] in covered:
            return {cell}
        if cells[cell] == Cell.REVEALED and self.settings.chord_on_click and game.counts[cell]:
            return {i for i in game.neighbors[cell] if cells[i] in covered}
        return set()

    def _set_pressed(self, cell: int) -> None:
        targets = self._press_targets(cell)
        if targets != self._pressed:
            self._pressed = targets
            self.update()

    @staticmethod
    def _is_touch(event: QMouseEvent) -> bool:
        device = event.device()
        return device is not None and device.type() == QInputDevice.DeviceType.TouchScreen

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.game:
            return
        if self._paused:
            self._swallow_release = True
            self.resume_requested.emit()
            return
        self._show_cursor = False
        cell = self.cell_at(event.position())
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            self._left = True
        elif button == Qt.MouseButton.RightButton:
            self._right = True
        if self.game.finished:
            return
        if cell >= 0:
            self._cursor = cell
        if button == Qt.MouseButton.MiddleButton or (self._left and self._right):
            self._chording = True
            self._long_press.stop()
            self._set_pressed(cell)
            self.pressing.emit(True)
        elif button == Qt.MouseButton.RightButton:
            self.mark(cell)
        elif button == Qt.MouseButton.LeftButton:
            self._set_pressed(cell)
            self.pressing.emit(bool(self._pressed))
            if self._is_touch(event) and cell >= 0:
                self._long_press_cell = cell
                self._long_press.start()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.game:
            return
        cell = self.cell_at(event.position())
        if cell != self._hover:
            old = self._hover
            self._hover = cell
            for c in (old, cell):
                if c >= 0:
                    self.update(self.cell_rect(c).toAlignedRect().adjusted(-2, -2, 2, 2))
        if self._show_cursor:
            self._show_cursor = False
            self.update()
        if (self._left or self._chording) and not self._paused:
            if cell != self._long_press_cell:
                self._long_press.stop()
            self._set_pressed(cell)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.game:
            return
        button = event.button()
        cell = self.cell_at(event.position())
        if button == Qt.MouseButton.LeftButton:
            self._left = False
        elif button == Qt.MouseButton.RightButton:
            self._right = False
        self._long_press.stop()
        if not self._paused and not self.game.finished:
            if self._chording:
                self._chording = False
                self._swallow_release = self._left or self._right
                self.chord(cell)
            elif button == Qt.MouseButton.LeftButton and not self._swallow_release:
                if cell >= 0:
                    covered = self.game.cells[cell] in (Cell.HIDDEN, Cell.QUESTION)
                    if covered or self.settings.chord_on_click:
                        self.act(cell)
        if not self._left and not self._right:
            self._swallow_release = False
            self._chording = False
        if self._pressed:
            self._pressed = set()
            self.update()
        self.pressing.emit(False)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.mousePressEvent(event)

    def _on_long_press(self) -> None:
        if self._left and self._long_press_cell >= 0:
            self.mark(self._long_press_cell)
            self._swallow_release = True
            self._pressed = set()
            self.pressing.emit(False)
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover >= 0:
            self._hover = -1
            self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self._show_cursor = True
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._left = self._right = self._chording = False
        self._pressed = set()
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        game = self.game
        if not game:
            return super().keyPressEvent(event)
        key = event.key()
        moves = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if key in moves:
            if self._show_cursor:
                col, row = game.coords(self._cursor)
                dx, dy = moves[key]
                step = 5 if event.modifiers() & Qt.KeyboardModifier.ControlModifier else 1
                col = max(0, min(game.cols - 1, col + dx * step))
                row = max(0, min(game.rows - 1, row + dy * step))
                self._cursor = game.index(col, row)
            self._show_cursor = True
            self.update()
            return
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            col, row = game.coords(self._cursor)
            self._cursor = game.index(0 if key == Qt.Key.Key_Home else game.cols - 1, row)
            self._show_cursor = True
            self.update()
            return
        if self._paused:
            return super().keyPressEvent(event)
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._show_cursor = True
            self.act(self._cursor)
            return
        if key == Qt.Key.Key_F:
            self._show_cursor = True
            self.mark(self._cursor)
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- paint
    def _prepare_glyphs(self) -> None:
        if self._glyph_tile == self._tile:
            return
        self._glyph_tile = self._tile
        font = QFont(self.font())
        font.setBold(True)
        font.setWeight(QFont.Weight.Bold)
        font.setPixelSize(max(8, round(self._tile * 0.56)))
        self._font = font
        self._glyphs = {}
        for text in [str(n) for n in range(1, 9)] + ["?"]:
            st = QStaticText(text)
            st.setTextFormat(Qt.TextFormat.PlainText)
            st.prepare(font=font)
            self._glyphs[text] = st

    def _draw_glyph(self, p: QPainter, rect: QRectF, text: str, color: QColor) -> None:
        st = self._glyphs[text]
        size = st.size()
        p.setPen(color)
        p.drawStaticText(
            QPointF(rect.center().x() - size.width() / 2, rect.center().y() - size.height() / 2), st
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        game = self.game
        if not game:
            return
        self._prepare_glyphs()
        colors = self.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font)
        now = time.monotonic()

        t = self._tile
        exposed = QRectF(event.rect())
        col0 = max(0, math.floor((exposed.left() - self._origin.x()) / t))
        col1 = min(game.cols - 1, math.floor((exposed.right() - self._origin.x()) / t))
        row0 = max(0, math.floor((exposed.top() - self._origin.y()) / t))
        row1 = min(game.rows - 1, math.floor((exposed.bottom() - self._origin.y()) / t))

        gap = max(1.0, round(t * 0.07))
        radius = max(2.0, t * 0.17)
        lip = max(1.0, round(t * 0.07))
        finished = game.finished
        lost = game.status == Status.LOST
        cells, mines, counts = game.cells, game.mines, game.counts
        wave = self._wave_start

        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                i = row * game.cols + col
                rect = QRectF(self._origin.x() + col * t, self._origin.y() + row * t, t, t)
                inner = rect.adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2)
                checker = (row + col) % 2 == 1
                state = cells[i]

                if self._paused:
                    self._draw_hidden(p, inner, radius, lip, colors, checker, False)
                    continue

                if state == Cell.REVEALED:
                    progress = 1.0
                    start = self._reveal_anim.get(i)
                    if start is not None:
                        progress = max(0.0, min(1.0, (now - start) / REVEAL_DURATION))
                    if i in game.exploded:
                        bg = colors.exploded
                    else:
                        bg = colors.revealed_alt if checker else colors.revealed
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(bg)
                    p.drawRoundedRect(inner, radius, radius)
                    if mines[i]:
                        body = QColor("#1e1e1e") if i in game.exploded else colors.mine
                        draw_mine(p, inner.adjusted(t * 0.1, t * 0.1, -t * 0.1, -t * 0.1), body, colors.mine_shine)
                    elif counts[i]:
                        color = QColor(colors.numbers[counts[i] - 1])
                        if progress < 1:
                            color.setAlphaF(_ease_out(progress))
                        self._draw_glyph(p, inner, str(counts[i]), color)
                    if progress < 1:
                        # The cover shrinks and fades away.
                        e = _ease_out(progress)
                        p.save()
                        p.setOpacity(1 - e)
                        shrink = inner.width() * 0.22 * e
                        self._draw_hidden(
                            p, inner.adjusted(shrink, shrink, -shrink, -shrink), radius, lip, colors, checker, False
                        )
                        p.restore()
                else:
                    show_mine = lost and mines[i] and state != Cell.FLAGGED
                    if show_mine:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(colors.revealed_alt if checker else colors.revealed)
                        p.drawRoundedRect(inner, radius, radius)
                        scale = 1.0
                        start = self._mine_anim.get(i)
                        if start is not None:
                            k = (now - start) / MINE_DURATION
                            scale = 0.0 if k < 0 else _ease_out_back(min(1.0, k))
                        if scale > 0:
                            m = inner.adjusted(t * 0.1, t * 0.1, -t * 0.1, -t * 0.1)
                            c = m.center()
                            m = QRectF(c.x() - m.width() * scale / 2, c.y() - m.height() * scale / 2,
                                       m.width() * scale, m.height() * scale)
                            draw_mine(p, m, colors.mine, colors.mine_shine)
                    elif i in self._pressed and state != Cell.FLAGGED:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(mix(colors.revealed, colors.hidden, 0.25))
                        p.drawRoundedRect(inner, radius, radius)
                    else:
                        hover = i == self._hover and not finished and not self._left
                        self._draw_hidden(p, inner, radius, lip, colors, checker, hover)
                        if state == Cell.FLAGGED:
                            scale = 1.0
                            start = self._flag_anim.get(i)
                            if start is not None:
                                k = (now - start) / FLAG_DURATION
                                scale = 0.0 if k < 0 else 0.35 + 0.65 * _ease_out_back(min(1.0, k))
                            if scale > 0:
                                f = inner.adjusted(0, 0, 0, -lip)
                                c = f.center()
                                f = QRectF(c.x() - f.width() * scale / 2, c.y() - f.height() * scale / 2,
                                           f.width() * scale, f.height() * scale)
                                draw_flag(p, f, colors.flag, colors.pole)
                            if lost and not mines[i]:
                                draw_cross(p, inner, colors.wrong)
                        elif state == Cell.QUESTION:
                            self._draw_glyph(p, inner.adjusted(0, 0, 0, -lip), "?", colors.pole)

                if wave is not None:
                    d = math.dist((col, row), self._wave_origin)
                    k = (now - wave - d * WAVE_STEP) / WAVE_DURATION
                    if 0 < k < 1:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(with_alpha(colors.win_glow, 0.55 * math.sin(math.pi * k)))
                        p.drawRoundedRect(inner, radius, radius)

        if not self._paused:
            if self._hint is not None:
                cell, kind, start = self._hint
                pulse = 0.5 + 0.5 * math.sin((now - start) * 6.0) if self._animated else 1.0
                color = colors.hint if kind == "safe" else colors.wrong
                rect = self.cell_rect(cell).adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2)
                glow = with_alpha(color, 0.25 + 0.25 * pulse)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(glow, max(3.0, t * 0.16)))
                p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
                p.setPen(QPen(color, max(2.0, t * 0.07)))
                p.drawRoundedRect(rect, radius, radius)
            if self._show_cursor and self.hasFocus() and 0 <= self._cursor < game.size:
                rect = self.cell_rect(self._cursor).adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(colors.background, max(4.0, t * 0.14)))
                p.drawRoundedRect(rect, radius, radius)
                p.setPen(QPen(colors.cursor, max(2.0, t * 0.07)))
                p.drawRoundedRect(rect, radius, radius)
        else:
            self._draw_paused(p, colors)
        p.end()

    def _draw_hidden(
        self, p: QPainter, rect: QRectF, radius: float, lip: float,
        colors: BoardColors, checker: bool, hover: bool,
    ) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colors.hidden_edge)
        p.drawRoundedRect(rect, radius, radius)
        face = colors.hidden_hover if hover else (colors.hidden_alt if checker else colors.hidden)
        p.setBrush(face)
        p.drawRoundedRect(rect.adjusted(0, 0, 0, -lip), radius, radius)

    def _draw_paused(self, p: QPainter, colors: BoardColors) -> None:
        board = self.board_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(colors.background, 0.55))
        p.drawRect(board)
        title = QFont(self.font())
        title.setBold(True)
        title.setPixelSize(max(16, min(40, int(board.width() / 9))))
        sub = QFont(self.font())
        sub.setPixelSize(max(11, min(18, int(board.width() / 22))))
        box = QRectF(0, 0, min(board.width() - 16, 360), title.pixelSize() + sub.pixelSize() * 2 + 40)
        box.moveCenter(board.center())
        p.setBrush(with_alpha(colors.background, 0.92))
        p.setPen(QPen(with_alpha(colors.text, 0.12), 1))
        p.drawRoundedRect(box, 14, 14)
        p.setPen(colors.text)
        p.setFont(title)
        text_rect = box.adjusted(12, 14, -12, -box.height() / 2)
        p.drawText(text_rect, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom), "Paused")
        p.setFont(sub)
        p.setPen(colors.muted)
        p.drawText(
            box.adjusted(12, box.height() / 2 + 6, -12, -10),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            "Click or press P to continue",
        )
