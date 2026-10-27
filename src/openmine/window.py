"""Main window: header bar, board and menus."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QColor, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from openmine import APP_NAME
from openmine.board import BoardWidget
from openmine.config import Settings, Stats, format_time, stats_key
from openmine.dialogs import CustomDialog, StatsDialog, show_about, show_help
from openmine.game import PRESETS, Difficulty, Game, Status
from openmine.painting import (
    FACE_LOST,
    FACE_SLEEP,
    FACE_SMILE,
    FACE_WON,
    FACE_WORRIED,
    draw_bulb,
    draw_clock,
    draw_menu,
    draw_mine,
    draw_pause,
    draw_play,
)
from openmine.solver import find_hint
from openmine.theme import ThemeManager
from openmine.widgets import EndCard, FaceButton, IconButton, Pill, Toast

DIFFICULTY_ORDER = ["beginner", "intermediate", "expert", "custom"]


def format_clock(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _mine_icon(p, rect, color) -> None:
    draw_mine(p, rect, color, QColor(0, 0, 0, 0))


class MainWindow(QMainWindow):
    def __init__(self, theme: ThemeManager, settings: Settings, stats: Stats) -> None:
        super().__init__()
        self.theme = theme
        self.settings = settings
        self.stats = stats
        self.game: Optional[Game] = None
        self.difficulty: Difficulty = settings.current_difficulty()
        self.setWindowTitle(APP_NAME)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 12)
        root.setSpacing(6)
        self.setCentralWidget(central)

        # ---- header ---------------------------------------------------
        header = QWidget()
        grid = QGridLayout(header)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)

        self.difficulty_box = QComboBox()
        self.difficulty_box.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.difficulty_box.setToolTip("Difficulty")
        self.difficulty_box.setAccessibleName("Difficulty")
        for key in DIFFICULTY_ORDER:
            self.difficulty_box.addItem(PRESETS[key].label if key in PRESETS else "Custom…", key)
        self.difficulty_box.activated.connect(self._on_difficulty_box)
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.difficulty_box)
        left.addStretch(1)

        self.mine_pill = Pill(theme, _mine_icon, "-888", "Mines left")
        self.face = FaceButton()
        self.face.clicked.connect(lambda: self.new_game())
        self.time_pill = Pill(theme, draw_clock, "88:88", "Time")
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(10)
        center.addWidget(self.mine_pill)
        center.addWidget(self.face)
        center.addWidget(self.time_pill)

        self.hint_button = IconButton(theme, draw_bulb, "Hint (H)")
        self.pause_button = IconButton(theme, draw_pause, "Pause (P)")
        self.menu_button = IconButton(theme, draw_menu, "Menu")
        self.menu_button.setPopupMode(IconButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(2)
        right.addStretch(1)
        right.addWidget(self.hint_button)
        right.addWidget(self.pause_button)
        right.addWidget(self.menu_button)

        grid.addLayout(left, 0, 0)
        grid.addLayout(center, 0, 1)
        grid.addLayout(right, 0, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root.addWidget(header)
        self.header = header

        # ---- board ----------------------------------------------------
        self.board = BoardWidget(theme, settings)
        root.addWidget(self.board, 1)
        self.board.changed.connect(self._update_counters)
        self.board.started.connect(self._on_started)
        self.board.finished.connect(self._on_finished)
        self.board.pressing.connect(self._on_pressing)
        self.board.resume_requested.connect(self.toggle_pause)

        self.toast = Toast(theme, self.board)
        self.end_card = EndCard(theme, self.board)
        self.end_card.play_again.connect(lambda: self.new_game())

        self.clock = QTimer(self)
        self.clock.setInterval(200)
        self.clock.timeout.connect(self._update_clock)

        self._build_actions()
        self.hint_button.clicked.connect(self.hint)
        self.pause_button.clicked.connect(self.toggle_pause)
        theme.changed.connect(self._update_counters)

        self.new_game(fit=False)
        if not (settings.window_geometry and self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))):
            self.fit_window()
        self.board.setFocus()

    # ------------------------------------------------------------- actions
    def _action(self, text: str, slot, shortcut=None, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            shortcuts = shortcut if isinstance(shortcut, list) else [shortcut]
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.setCheckable(checkable)
        if checkable:
            action.toggled.connect(slot)
        else:
            action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        s = self.settings
        menu = QMenu(self)
        self.new_action = self._action("&New Game", lambda: self.new_game(), [QKeySequence.StandardKey.New, "F2"])
        menu.addAction(self.new_action)
        menu.addSeparator()

        self.difficulty_group = QActionGroup(self)
        self.difficulty_actions: dict[str, QAction] = {}
        labels = {
            "beginner": "&Beginner  ·  9 × 9, 10 mines",
            "intermediate": "&Intermediate  ·  16 × 16, 40 mines",
            "expert": "&Expert  ·  30 × 16, 99 mines",
            "custom": "&Custom…",
        }
        for n, key in enumerate(DIFFICULTY_ORDER, start=1):
            action = QAction(labels[key], self)
            action.setShortcut(QKeySequence(f"Ctrl+{n}"))
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, k=key: self.choose_difficulty(k))
            self.difficulty_group.addAction(action)
            self.addAction(action)
            menu.addAction(action)
            self.difficulty_actions[key] = action
        menu.addSeparator()

        self.hint_action = self._action("&Hint", self.hint, "H")
        self.pause_action = self._action("&Pause", self.toggle_pause, ["P", "Pause"])
        self.stats_action = self._action("&Statistics", self.show_stats, "F4")
        menu.addAction(self.hint_action)
        menu.addAction(self.pause_action)
        menu.addAction(self.stats_action)
        menu.addSeparator()

        prefs = menu.addMenu("Pr&eferences")
        theme_menu = prefs.addMenu("&Appearance")
        self.theme_group = QActionGroup(self)
        for key, label in (("system", "Follow &System"), ("light", "&Light"), ("dark", "&Dark")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.theme.mode == key)
            action.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            self.theme_group.addAction(action)
            theme_menu.addAction(action)
        prefs.addSeparator()
        self.no_guess_action = self._action("&No-Guess Boards", self._set_no_guess, checkable=True)
        self.no_guess_action.setToolTip("Every board can be solved with logic alone")
        self.question_action = self._action("&Question Marks", self._set_question_marks, checkable=True)
        self.chord_action = self._action("&Click Numbers to Chord", self._set_chord, checkable=True)
        self.animation_action = self._action("&Animations", self._set_animations, checkable=True)
        for action, value in (
            (self.no_guess_action, s.no_guess),
            (self.question_action, s.question_marks),
            (self.chord_action, s.chord_on_click),
            (self.animation_action, s.animations),
        ):
            action.blockSignals(True)
            action.setChecked(value)
            action.blockSignals(False)
            prefs.addAction(action)
        menu.addSeparator()

        self.help_action = self._action("How to &Play", lambda: show_help(self), QKeySequence.StandardKey.HelpContents)
        self.about_action = self._action(f"&About {APP_NAME}", lambda: show_about(self))
        self.quit_action = self._action("&Quit", self.close, [QKeySequence.StandardKey.Quit, "Ctrl+Q"])
        menu.addAction(self.help_action)
        menu.addAction(self.about_action)
        menu.addSeparator()
        menu.addAction(self.quit_action)

        self.close_card_action = self._action("Close", self._escape, "Esc")
        self.menu = menu
        self.menu_button.setMenu(menu)

    # ---------------------------------------------------------- game flow
    def new_game(self, fit: bool = True) -> None:
        d = self.difficulty
        size_changed = self.game is None or (self.game.cols, self.game.rows) != (d.cols, d.rows)
        self.game = Game(d.cols, d.rows, d.mines, no_guess=self.settings.no_guess)
        self.board.set_game(self.game)
        self.end_card.hide()
        self.toast.hide()
        self.clock.stop()
        self.face.set_mood(FACE_SMILE)
        self.pause_button.set_drawing(draw_pause)
        self.pause_button.setToolTip("Pause (P)")
        self._sync_difficulty_ui()
        self._update_counters()
        self._update_clock()
        if fit and size_changed:
            self.fit_window()
        self.board.setFocus()

    def choose_difficulty(self, key: str) -> None:
        if key == "custom":
            dialog = CustomDialog(
                self.settings.custom_cols, self.settings.custom_rows, self.settings.custom_mines, self
            )
            if dialog.exec() != CustomDialog.DialogCode.Accepted:
                self._sync_difficulty_ui()
                return
            d = dialog.difficulty()
            self.settings.custom_cols, self.settings.custom_rows, self.settings.custom_mines = d.cols, d.rows, d.mines
            self.settings.difficulty = d.key if not d.is_custom else "custom"
        else:
            self.settings.difficulty = key
        self.settings.save()
        self.difficulty = self.settings.current_difficulty()
        self.new_game()

    def _on_difficulty_box(self, index: int) -> None:
        self.choose_difficulty(self.difficulty_box.itemData(index))

    def _sync_difficulty_ui(self) -> None:
        key = "custom" if self.difficulty.is_custom else self.difficulty.key
        self.difficulty_box.blockSignals(True)
        self.difficulty_box.setCurrentIndex(DIFFICULTY_ORDER.index(key))
        if self.difficulty.is_custom:
            d = self.difficulty
            self.difficulty_box.setItemText(3, f"Custom ({d.cols}×{d.rows}, {d.mines})")
        else:
            self.difficulty_box.setItemText(3, "Custom…")
        self.difficulty_box.blockSignals(False)
        self.difficulty_actions[key].setChecked(True)

    def _on_started(self) -> None:
        self.clock.start()
        game = self.game
        if game and game.no_guess and game.no_guess_ok is False:
            self.toast.show_message(
                "Couldn't build a no-guess board this dense in time — this one may need a guess.", 5000
            )

    def _on_pressing(self, pressed: bool) -> None:
        if self.game and not self.game.finished and not self.game.paused:
            self.face.set_mood(FACE_WORRIED if pressed else FACE_SMILE)

    def _on_finished(self, won: bool) -> None:
        game = self.game
        assert game
        self.toast.hide()
        self.clock.stop()
        self._update_clock()
        self.face.set_mood(FACE_WON if won else FACE_LOST)
        elapsed = game.elapsed()
        key = stats_key(self.difficulty, game.no_guess)
        assisted = game.hints_used > 0
        rank = self.stats.record_game(key, won, elapsed, counts_for_times=not assisted)
        record = self.stats.get(key)
        label = self.difficulty.label
        if won:
            details = [f"{label} · {format_time(elapsed)}"]
            if assisted:
                details.append("hints used, time not recorded")
            elif rank == 1 and len(record.times) > 1:
                details.append("new best time!")
            elif rank == 1:
                details.append("first win on this board!")
            elif rank:
                details.append(f"#{rank} of your best times")
            if record.streak > 1:
                details.append(f"{record.streak} wins in a row")
            self.end_card.show_result(FACE_WON, "You won!", " · ".join(details))
        else:
            total_safe = game.size - game.mine_count
            cleared = game.revealed / total_safe * 100 if total_safe else 0
            self.end_card.show_result(
                FACE_LOST, "Boom!", f"{label} · {cleared:.0f}% cleared in {format_time(elapsed)}"
            )

    def _update_counters(self) -> None:
        game = self.game
        if not game:
            return
        left = game.mines_left
        self.mine_pill.set_text(str(left), alert=left < 0)
        playing = game.status == Status.PLAYING
        self.pause_action.setEnabled(playing)
        self.pause_button.setEnabled(playing)
        self.hint_action.setEnabled(not game.finished and not game.paused)
        self.hint_button.setEnabled(not game.finished and not game.paused)

    def _update_clock(self) -> None:
        if self.game:
            self.time_pill.set_text(format_clock(self.game.elapsed()))

    # -------------------------------------------------------------- extras
    def hint(self) -> None:
        game = self.game
        if not game or game.finished or game.paused:
            return
        if game.status == Status.READY:
            center = game.index(game.cols // 2, game.rows // 2)
            self.board.show_hint(center, "safe")
            self.toast.show_message("Your first click is always safe — start anywhere.")
            return
        result = find_hint(game)
        if result is None:
            self.toast.show_message("No square can be proven safe right now. Time to guess!")
            return
        cell, kind = result
        game.hints_used += 1
        self.board.show_hint(cell, kind)
        if kind == "wrong-flag":
            self.toast.show_message("This flag is wrong — that square can't be a mine.")
        elif game.hints_used == 1:
            self.toast.show_message("This square is safe. Games won with hints don't set records.")

    def toggle_pause(self) -> None:
        game = self.game
        if not game:
            return
        if game.paused:
            game.resume()
            self.clock.start()
            self.face.set_mood(FACE_SMILE)
            self.pause_button.set_drawing(draw_pause)
            self.pause_button.setToolTip("Pause (P)")
        elif game.status == Status.PLAYING:
            game.pause()
            self.clock.stop()
            self.face.set_mood(FACE_SLEEP)
            self.pause_button.set_drawing(draw_play)
            self.pause_button.setToolTip("Resume (P)")
        else:
            return
        self.board.set_paused(game.paused)
        self._update_counters()
        self._update_clock()

    def show_stats(self) -> None:
        key = stats_key(self.difficulty, self.settings.no_guess)
        StatsDialog(self.stats, key, self).exec()

    def set_theme(self, mode: str) -> None:
        self.settings.theme = mode
        self.settings.save()
        self.theme.set_mode(mode)

    def _set_no_guess(self, enabled: bool) -> None:
        self.settings.no_guess = enabled
        self.settings.save()
        if self.game and self.game.status == Status.READY:
            self.game.no_guess = enabled
        else:
            self.toast.show_message(
                "No-guess boards " + ("on" if enabled else "off") + " — starts with the next game."
            )

    def _set_question_marks(self, enabled: bool) -> None:
        self.settings.question_marks = enabled
        self.settings.save()

    def _set_chord(self, enabled: bool) -> None:
        self.settings.chord_on_click = enabled
        self.settings.save()

    def _set_animations(self, enabled: bool) -> None:
        self.settings.animations = enabled
        self.settings.save()

    def _escape(self) -> None:
        if self.end_card.isVisible():
            self.end_card.dismiss()
        elif self.game and self.game.paused:
            self.toggle_pause()

    # -------------------------------------------------------------- window
    def fit_window(self) -> None:
        """Resize so the board gets comfortable tiles while fitting the screen."""
        if self.isMaximized() or self.isFullScreen():
            return
        screen = self.screen().availableGeometry() if self.screen() else None
        margins = self.centralWidget().layout().contentsMargins()
        chrome_w = margins.left() + margins.right()
        chrome_h = margins.top() + margins.bottom() + self.header.sizeHint().height() + 6
        size = QSize()
        for tile in (36, 32, 28, 24, 20, 17, BoardWidget.MIN_TILE):
            board = self.board.preferred_size(tile)
            size = QSize(
                max(board.width() + chrome_w, self.header.minimumSizeHint().width() + chrome_w),
                board.height() + chrome_h,
            )
            if screen is None or (
                size.width() <= screen.width() * 0.94 and size.height() <= screen.height() * 0.9
            ):
                break
        self.resize(size)
        if screen is not None:
            frame = self.frameGeometry()
            if not screen.contains(frame):
                frame.moveCenter(screen.center())
                self.move(frame.topLeft())

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if self.game and self.game.status == Status.PLAYING and not self.game.paused:
                self.toggle_pause()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        for overlay in (self.toast, self.end_card):
            if overlay.isVisible():
                overlay.reposition()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.save()
        super().closeEvent(event)
