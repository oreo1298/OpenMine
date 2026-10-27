"""Small custom widgets used by the main window."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openmine.painting import draw_face, make_icon
from openmine.theme import ThemeManager, mix, with_alpha


def tabular_font(base: QFont, pixel_size: int, bold: bool = True) -> QFont:
    font = QFont(base)
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    if hasattr(font, "setFeature"):  # Qt 6.7+: tabular figures keep digits from jiggling
        try:
            font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
    return font


class Pill(QWidget):
    """Rounded counter with an icon, used for the mine counter and the clock."""

    def __init__(
        self,
        theme: ThemeManager,
        draw_icon: Callable,
        sample: str,
        tooltip: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self._draw_icon = draw_icon
        self._text = ""
        self._sample = sample
        self._alert = False
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def _font(self) -> QFont:
        return tabular_font(self.font(), 17)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._font())
        width = fm.horizontalAdvance(self._sample) + 20 + 22 + 8
        return QSize(width, 36)

    def set_text(self, text: str, alert: bool = False) -> None:
        if text != self._text or alert != self._alert:
            self._text = text
            self._alert = alert
            self.setAccessibleDescription(text)
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        colors = self.theme.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(with_alpha(colors.text, 0.08), 1))
        p.setBrush(colors.surface)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        icon_rect = QRectF(12, (self.height() - 20) / 2, 20, 20)
        self._draw_icon(p, icon_rect, mix(colors.muted, colors.text, 0.5) if not self._alert else colors.wrong)
        p.setFont(self._font())
        p.setPen(colors.wrong if self._alert else colors.text)
        p.drawText(
            QRectF(icon_rect.right() + 6, 0, self.width() - icon_rect.right() - 18, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            self._text,
        )
        p.end()


class IconButton(QToolButton):
    """Flat tool button whose icon is drawn in the current text colour."""

    def __init__(
        self, theme: ThemeManager, draw: Callable, tooltip: str, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self._draw = draw
        self.setAutoRaise(True)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip.split(" (")[0])
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(QSize(38, 38))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.changed.connect(self._refresh)
        self._refresh()

    def set_drawing(self, draw: Callable) -> None:
        self._draw = draw
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(make_icon(self._draw, 20, self.theme.colors.text))


class FaceButton(QToolButton):
    """The classic smiley: starts a new game and shows how things are going."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAutoRaise(True)
        self.setIconSize(QSize(32, 32))
        self.setFixedSize(QSize(46, 46))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("New game (F2)")
        self.setAccessibleName("New game")
        self._mood = ""
        self._icons: dict[str, object] = {}
        self.set_mood("smile")

    def set_mood(self, mood: str) -> None:
        if mood == self._mood:
            return
        self._mood = mood
        if mood not in self._icons:
            self._icons[mood] = make_icon(draw_face, 32, mood)
        self.setIcon(self._icons[mood])


class _Card(QWidget):
    """Base for floating overlays: draws a rounded card with a soft shadow."""

    SHADOW = 10

    def __init__(self, theme: ThemeManager, parent: QWidget) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._fade_done)
        self._hiding = False
        theme.changed.connect(self.update)
        self.hide()

    def card_rect(self) -> QRectF:
        s = self.SHADOW
        return QRectF(self.rect()).adjusted(s, s - 2, -s, -s - 2)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        colors = self.theme.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self.card_rect()
        radius = 14.0
        shadow = QColor(0, 0, 0)
        for k in range(self.SHADOW, 0, -2):
            shadow.setAlphaF(0.035 if not colors.dark else 0.07)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shadow)
            p.drawRoundedRect(card.adjusted(-k / 2, -k / 2 + 2, k / 2, k / 2 + 2), radius + k / 2, radius + k / 2)
        background = mix(colors.background, colors.text, 0.06) if colors.dark else colors.background
        p.setBrush(background)
        p.setPen(QPen(with_alpha(colors.text, 0.12), 1))
        p.drawRoundedRect(card, radius, radius)
        p.end()

    def popup(self) -> None:
        self._hiding = False
        self._fade.stop()
        self.reposition()
        self.show()
        self.raise_()
        if self.theme_animations():
            self._fade.setDuration(180)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._effect.setOpacity(1.0)

    def dismiss(self) -> None:
        if not self.isVisible() or self._hiding:
            return
        if self.theme_animations():
            self._hiding = True
            self._fade.stop()
            self._fade.setDuration(220)
            self._fade.setStartValue(self._effect.opacity())
            self._fade.setEndValue(0.0)
            self._fade.start()
        else:
            self.hide()

    def _fade_done(self) -> None:
        if self._hiding:
            self._hiding = False
            self.hide()

    def theme_animations(self) -> bool:
        window = self.window()
        settings = getattr(window, "settings", None)
        return bool(getattr(settings, "animations", True))

    def preferred_width(self) -> int:
        """Width the card would like when there is enough room."""
        return self.sizeHint().width()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = max(120, min(self.preferred_width(), parent.width() - 8))
        self.layout().activate()
        height = self.heightForWidth(width)
        if height <= 0:
            height = self.sizeHint().height()
        x = (parent.width() - width) // 2
        bottom = parent.height() - 8
        board_rect = getattr(parent, "board_rect", None)
        if callable(board_rect):
            bottom = min(bottom, int(board_rect().bottom()) + self.SHADOW - 6)
        self.setGeometry(x, max(0, bottom - height), width, height)


class Toast(_Card):
    """A short message that disappears on its own."""

    def __init__(self, theme: ThemeManager, parent: QWidget) -> None:
        super().__init__(theme, parent)
        layout = QHBoxLayout(self)
        s = self.SHADOW
        layout.setContentsMargins(s + 16, s + 8, s + 16, s + 12)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def preferred_width(self) -> int:
        fm = QFontMetrics(self.label.font())
        margins = self.layout().contentsMargins()
        return min(fm.horizontalAdvance(self.label.text()) + margins.left() + margins.right() + 8, 440)

    def show_message(self, text: str, msec: int = 3500) -> None:
        self.label.setText(text)
        self.popup()
        self._timer.start(msec)


class EndCard(_Card):
    """Shown when a game ends: result, time and a "Play again" button."""

    play_again = Signal()

    def __init__(self, theme: ThemeManager, parent: QWidget) -> None:
        super().__init__(theme, parent)
        s = self.SHADOW
        outer = QHBoxLayout(self)
        outer.setContentsMargins(s + 14, s + 10, s + 10, s + 12)
        outer.setSpacing(12)
        self.face = QLabel()
        self.face.setFixedSize(40, 40)
        outer.addWidget(self.face, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel()
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() * 1.25)
        self.title.setFont(title_font)
        self.subtitle = QLabel()
        self.subtitle.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        outer.addLayout(text, 1)
        self.button = QPushButton("Play again")
        self.button.setDefault(True)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.play_again)
        outer.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip("Close (Esc)")
        self.close_button.setAccessibleName("Close")
        self.close_button.clicked.connect(self.dismiss)
        outer.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        theme.changed.connect(self._restyle)

    def _restyle(self) -> None:
        colors = self.theme.colors
        self.subtitle.setStyleSheet(f"color: {colors.muted.name()};")

    def preferred_width(self) -> int:
        # Everything but the text, plus the text on one line (capped).
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        chrome = (
            margins.left() + margins.right() + self.face.width() + self.button.sizeHint().width()
            + self.close_button.sizeHint().width() + 3 * spacing
        )
        text = max(
            QFontMetrics(self.title.font()).horizontalAdvance(self.title.text()),
            QFontMetrics(self.subtitle.font()).horizontalAdvance(self.subtitle.text()),
        )
        return chrome + min(text + 8, 300)

    def show_result(self, mood: str, title: str, subtitle: str) -> None:
        self._restyle()
        icon = make_icon(draw_face, 40, mood)
        self.face.setPixmap(icon.pixmap(QSize(40, 40)))
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.popup()
