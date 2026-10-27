"""Dialogs: custom board, statistics, help and about."""

from __future__ import annotations

import platform
from typing import Optional

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openmine import APP_NAME, HOMEPAGE, __version__
from openmine.config import Stats, describe_key, format_time
from openmine.game import (
    MAX_COLS,
    MAX_ROWS,
    MIN_COLS,
    MIN_MINES,
    MIN_ROWS,
    Difficulty,
    custom_difficulty,
    max_mines,
)


class CustomDialog(QDialog):
    def __init__(self, cols: int, rows: int, mines: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Game")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.cols = QSpinBox()
        self.cols.setRange(MIN_COLS, MAX_COLS)
        self.cols.setValue(cols)
        self.rows = QSpinBox()
        self.rows.setRange(MIN_ROWS, MAX_ROWS)
        self.rows.setValue(rows)
        self.mines = QSpinBox()
        self.mines.setRange(MIN_MINES, max_mines(cols, rows))
        self.mines.setValue(mines)
        for spin in (self.cols, self.rows, self.mines):
            spin.setMinimumWidth(90)
            spin.setAccelerated(True)
        form.addRow("&Width:", self.cols)
        form.addRow("&Height:", self.rows)
        form.addRow("&Mines:", self.mines)
        layout.addLayout(form)
        self.density = QLabel()
        self.density.setEnabled(False)
        layout.addWidget(self.density)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("&Play")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.cols.valueChanged.connect(self._update)
        self.rows.valueChanged.connect(self._update)
        self.mines.valueChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        self.mines.setMaximum(max_mines(self.cols.value(), self.rows.value()))
        cells = self.cols.value() * self.rows.value()
        density = self.mines.value() / cells * 100
        hint = "easy" if density < 13 else "medium" if density < 18 else "hard" if density < 23 else "brutal"
        self.density.setText(f"{cells} cells · {density:.1f}% mines ({hint})")

    def difficulty(self) -> Difficulty:
        return custom_difficulty(self.cols.value(), self.rows.value(), self.mines.value())


class StatsDialog(QDialog):
    def __init__(self, stats: Stats, current_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.stats = stats
        self.setWindowTitle("Statistics")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("&Board:"))
        self.selector = QComboBox()
        top.itemAt(0).widget().setBuddy(self.selector)
        top.addWidget(self.selector, 1)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        self.values: dict[str, QLabel] = {}
        labels = [
            ("played", "Games played"),
            ("won", "Games won"),
            ("rate", "Win rate"),
            ("best", "Best time"),
            ("average", "Average winning time"),
            ("streak", "Current winning streak"),
            ("best_streak", "Longest winning streak"),
        ]
        for row, (key, text) in enumerate(labels):
            grid.addWidget(QLabel(text), row, 0)
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            font = value.font()
            font.setBold(True)
            value.setFont(font)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        layout.addLayout(grid)

        layout.addSpacing(6)
        layout.addWidget(QLabel("Best times"))
        self.times = QTreeWidget()
        self.times.setColumnCount(3)
        self.times.setHeaderLabels(["#", "Time", "Date"])
        self.times.setRootIsDecorated(False)
        self.times.setAlternatingRowColors(True)
        self.times.setMinimumHeight(180)
        header = self.times.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.times)
        note = QLabel("Games won with hints don't count towards best times.")
        note.setEnabled(False)
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.reset_button = QPushButton("&Reset…")
        buttons.addButton(self.reset_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.reset_button.clicked.connect(self._reset)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate(current_key)
        self.selector.currentIndexChanged.connect(self._show)
        self._show()

    def _populate(self, current_key: str) -> None:
        order = ["beginner", "intermediate", "expert"]
        keys = order + [k + "-noguess" for k in order]
        keys += sorted(k for k in self.stats.keys() if k not in keys)
        if current_key not in keys:
            keys.append(current_key)
        self.selector.blockSignals(True)
        self.selector.clear()
        for key in keys:
            self.selector.addItem(describe_key(key), key)
        self.selector.setCurrentIndex(max(0, self.selector.findData(current_key)))
        self.selector.blockSignals(False)

    def _show(self) -> None:
        key = self.selector.currentData()
        record = self.stats.get(key)
        self.values["played"].setText(str(record.played))
        self.values["won"].setText(str(record.won))
        self.values["rate"].setText(f"{record.win_rate * 100:.0f}%" if record.played else "—")
        self.values["best"].setText(format_time(record.best_time))
        self.values["average"].setText(format_time(record.average_time))
        self.values["streak"].setText(str(record.streak))
        self.values["best_streak"].setText(str(record.best_streak))
        self.times.clear()
        for rank, entry in enumerate(record.times, start=1):
            item = QTreeWidgetItem([str(rank), format_time(entry["time"]), str(entry.get("date", ""))])
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.times.addTopLevelItem(item)
        self.reset_button.setEnabled(record.played > 0 or bool(self.stats.keys()))

    def _reset(self) -> None:
        key = self.selector.currentData()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Reset Statistics")
        box.setText("Reset statistics?")
        box.setInformativeText("This cannot be undone.")
        this_board = box.addButton(f"Reset “{describe_key(key)}”", QMessageBox.ButtonRole.DestructiveRole)
        everything = box.addButton("Reset Everything", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is this_board:
            self.stats.reset(key)
        elif box.clickedButton() is everything:
            self.stats.reset()
        else:
            return
        self._populate(key)
        self._show()


HELP_HTML = """
<h3>Goal</h3>
<p>Uncover every square that does not hide a mine. A number tells you how many
mines touch that square (including diagonals). Your first click is always
safe.</p>
<h3>Mouse</h3>
<table cellspacing="4">
<tr><td><b>Left click</b></td><td>Uncover a square</td></tr>
<tr><td><b>Right click</b></td><td>Place or remove a flag</td></tr>
<tr><td><b>Click a number</b></td><td>When all of its mines are flagged, uncover the
remaining neighbours (“chording”). Middle click or left+right click also works.</td></tr>
<tr><td><b>Long press</b></td><td>Flag on touch screens</td></tr>
</table>
<h3>Keyboard</h3>
<table cellspacing="4">
<tr><td><b>Arrow keys</b></td><td>Move the cursor (Ctrl moves 5 squares)</td></tr>
<tr><td><b>Space / Enter</b></td><td>Uncover, or chord on a number</td></tr>
<tr><td><b>F</b></td><td>Flag</td></tr>
<tr><td><b>H</b></td><td>Hint: highlights a square that is provably safe</td></tr>
<tr><td><b>P</b></td><td>Pause</td></tr>
<tr><td><b>F2</b> or <b>Ctrl+N</b></td><td>New game</td></tr>
<tr><td><b>Ctrl+1 … Ctrl+4</b></td><td>Beginner, Intermediate, Expert, Custom</td></tr>
<tr><td><b>F4</b></td><td>Statistics</td></tr>
</table>
<h3>No-guess boards</h3>
<p>With <i>No-guess boards</i> enabled in the menu, every game can be solved by
logic alone — you never have to rely on luck. Records for these games are
kept separately.</p>
"""


def show_help(parent: QWidget) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("How to Play")
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(HELP_HTML)
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    box.exec()


def show_about(parent: QWidget) -> None:
    text = f"""
    <h2>{APP_NAME} {__version__}</h2>
    <p>A free and open source Minesweeper that follows your system theme.</p>
    <p><a href="{HOMEPAGE}">{HOMEPAGE}</a></p>
    <p>Copyright © 2026 OpenMine contributors.<br>
    Licensed under the GNU General Public License, version 3 or later.
    This program comes with absolutely no warranty.</p>
    <p><small>Qt {qVersion()} · PySide6 {PYSIDE_VERSION} · Python {platform.python_version()}</small></p>
    """
    QMessageBox.about(parent, f"About {APP_NAME}", text)
