"""Vector drawing helpers for game pieces and icons.

Everything is drawn with QPainter at the target size, so it stays crisp at any
zoom level or display scale and can be recoloured for the current theme.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def square(rect: QRectF, scale: float = 1.0) -> QRectF:
    side = min(rect.width(), rect.height()) * scale
    return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)


def draw_mine(p: QPainter, rect: QRectF, body: QColor, shine: QColor) -> None:
    r = square(rect)
    s = r.width()
    c = r.center()
    p.save()
    p.setPen(_pen(body, max(s * 0.075, 1.8)))
    for k in range(8):
        angle = k * math.pi / 4
        length = s * (0.36 if k % 2 == 0 else 0.31)
        p.drawLine(c, QPointF(c.x() + math.cos(angle) * length, c.y() + math.sin(angle) * length))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(body)
    radius = s * (0.235 if s >= 24 else 0.27)
    p.drawEllipse(c, radius, radius)
    p.setBrush(shine)
    p.drawEllipse(QPointF(c.x() - radius * 0.38, c.y() - radius * 0.38), radius * 0.26, radius * 0.26)
    p.restore()


def draw_flag(p: QPainter, rect: QRectF, cloth: QColor, pole: QColor) -> None:
    r = square(rect)
    s = r.width()
    x0, y0 = r.left(), r.top()
    p.save()
    pole_x = x0 + s * 0.40
    p.setPen(_pen(pole, s * 0.075))
    p.drawLine(QPointF(pole_x, y0 + s * 0.20), QPointF(pole_x, y0 + s * 0.76))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pole)
    p.drawRoundedRect(QRectF(x0 + s * 0.25, y0 + s * 0.72, s * 0.40, s * 0.085), s * 0.04, s * 0.04)
    path = QPainterPath()
    path.moveTo(pole_x + s * 0.02, y0 + s * 0.18)
    path.cubicTo(
        QPointF(x0 + s * 0.58, y0 + s * 0.24),
        QPointF(x0 + s * 0.66, y0 + s * 0.30),
        QPointF(x0 + s * 0.78, y0 + s * 0.34),
    )
    path.cubicTo(
        QPointF(x0 + s * 0.66, y0 + s * 0.40),
        QPointF(x0 + s * 0.58, y0 + s * 0.46),
        QPointF(pole_x + s * 0.02, y0 + s * 0.52),
    )
    path.closeSubpath()
    p.setPen(_pen(cloth.darker(115), s * 0.03))
    p.setBrush(cloth)
    p.drawPath(path)
    p.restore()


def draw_cross(p: QPainter, rect: QRectF, color: QColor) -> None:
    r = square(rect, 0.62)
    p.save()
    p.setPen(_pen(color, r.width() * 0.16))
    p.drawLine(r.topLeft(), r.bottomRight())
    p.drawLine(r.topRight(), r.bottomLeft())
    p.restore()


def draw_clock(p: QPainter, rect: QRectF, color: QColor) -> None:
    r = square(rect, 0.80)
    s = r.width()
    c = r.center()
    p.save()
    p.setPen(_pen(color, s * 0.11))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r.adjusted(s * 0.06, s * 0.06, -s * 0.06, -s * 0.06))
    p.drawLine(c, QPointF(c.x(), c.y() - s * 0.26))
    p.drawLine(c, QPointF(c.x() + s * 0.18, c.y() + s * 0.08))
    p.restore()


def draw_menu(p: QPainter, rect: QRectF, color: QColor) -> None:
    r = square(rect, 0.62)
    s = r.width()
    p.save()
    p.setPen(_pen(color, s * 0.13))
    for k in (0.2, 0.5, 0.8):
        y = r.top() + s * k
        p.drawLine(QPointF(r.left() + s * 0.08, y), QPointF(r.right() - s * 0.08, y))
    p.restore()


def draw_bulb(p: QPainter, rect: QRectF, color: QColor) -> None:
    r = square(rect, 0.80)
    s = r.width()
    cx = r.center().x()
    p.save()
    p.setPen(_pen(color, s * 0.09))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    top = r.top() + s * 0.06
    path.moveTo(cx - s * 0.13, r.top() + s * 0.68)
    path.cubicTo(
        QPointF(cx - s * 0.13, r.top() + s * 0.52),
        QPointF(cx - s * 0.32, r.top() + s * 0.46),
        QPointF(cx - s * 0.32, r.top() + s * 0.30),
    )
    path.cubicTo(QPointF(cx - s * 0.32, top), QPointF(cx + s * 0.32, top), QPointF(cx + s * 0.32, r.top() + s * 0.30))
    path.cubicTo(
        QPointF(cx + s * 0.32, r.top() + s * 0.46),
        QPointF(cx + s * 0.13, r.top() + s * 0.52),
        QPointF(cx + s * 0.13, r.top() + s * 0.68),
    )
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(cx - s * 0.12, r.top() + s * 0.82), QPointF(cx + s * 0.12, r.top() + s * 0.82))
    p.restore()


def draw_pause(p: QPainter, rect: QRectF, color: QColor) -> None:
    r = square(rect, 0.56)
    s = r.width()
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(r.left() + s * 0.10, r.top(), s * 0.28, s), s * 0.08, s * 0.08)
    p.drawRoundedRect(QRectF(r.right() - s * 0.38, r.top(), s * 0.28, s), s * 0.08, s * 0.08)
    p.restore()


def draw_play(p: QPainter, rect: QRectF, color: QColor) -> None:
    r = square(rect, 0.56)
    s = r.width()
    path = QPainterPath()
    path.moveTo(r.left() + s * 0.16, r.top())
    path.lineTo(r.right(), r.center().y())
    path.lineTo(r.left() + s * 0.16, r.bottom())
    path.closeSubpath()
    p.save()
    p.setPen(_pen(color, s * 0.12))
    p.setBrush(color)
    p.drawPath(path)
    p.restore()


FACE_SMILE = "smile"
FACE_WORRIED = "worried"
FACE_WON = "won"
FACE_LOST = "lost"
FACE_SLEEP = "sleep"


def draw_face(p: QPainter, rect: QRectF, mood: str) -> None:
    r = square(rect, 0.92)
    s = r.width()
    c = r.center()
    ink = QColor("#3d2c00")
    p.save()
    grad = QRadialGradient(QPointF(c.x() - s * 0.18, c.y() - s * 0.22), s * 0.75)
    grad.setColorAt(0.0, QColor("#ffe98a"))
    grad.setColorAt(0.55, QColor("#f8d33a"))
    grad.setColorAt(1.0, QColor("#e5a50a"))
    p.setPen(_pen(QColor("#b07a00"), s * 0.045))
    p.setBrush(QBrush(grad))
    p.drawEllipse(r.adjusted(s * 0.03, s * 0.03, -s * 0.03, -s * 0.03))

    eye_y = c.y() - s * 0.10
    eye_dx = s * 0.16
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ink)
    if mood == FACE_WON:
        glass = QPainterPath()
        for sign in (-1, 1):
            glass.addRoundedRect(
                QRectF(c.x() + sign * eye_dx - s * 0.135, eye_y - s * 0.08, s * 0.27, s * 0.17),
                s * 0.06,
                s * 0.06,
            )
        p.drawPath(glass)
        p.setPen(_pen(ink, s * 0.05))
        p.drawLine(QPointF(c.x() - eye_dx, eye_y - s * 0.04), QPointF(c.x() + eye_dx, eye_y - s * 0.04))
        p.drawLine(QPointF(r.left() + s * 0.12, eye_y - s * 0.06), QPointF(c.x() - eye_dx - s * 0.12, eye_y - s * 0.04))
        p.drawLine(QPointF(r.right() - s * 0.12, eye_y - s * 0.06), QPointF(c.x() + eye_dx + s * 0.12, eye_y - s * 0.04))
    elif mood == FACE_LOST:
        p.setPen(_pen(ink, s * 0.055))
        for sign in (-1, 1):
            ex = c.x() + sign * eye_dx
            d = s * 0.06
            p.drawLine(QPointF(ex - d, eye_y - d), QPointF(ex + d, eye_y + d))
            p.drawLine(QPointF(ex + d, eye_y - d), QPointF(ex - d, eye_y + d))
    elif mood == FACE_SLEEP:
        p.setPen(_pen(ink, s * 0.05))
        for sign in (-1, 1):
            ex = c.x() + sign * eye_dx
            p.drawArc(QRectF(ex - s * 0.07, eye_y - s * 0.05, s * 0.14, s * 0.10), 200 * 16, 140 * 16)
    else:
        rx = s * 0.05
        ry = s * (0.075 if mood == FACE_WORRIED else 0.065)
        for sign in (-1, 1):
            p.drawEllipse(QPointF(c.x() + sign * eye_dx, eye_y), rx, ry)

    p.setPen(_pen(ink, s * 0.055))
    p.setBrush(Qt.BrushStyle.NoBrush)
    mouth_y = c.y() + s * 0.12
    if mood == FACE_WORRIED:
        p.setBrush(ink)
        p.drawEllipse(QPointF(c.x(), mouth_y + s * 0.02), s * 0.06, s * 0.075)
    elif mood == FACE_LOST:
        p.drawArc(QRectF(c.x() - s * 0.17, mouth_y, s * 0.34, s * 0.20), 30 * 16, 120 * 16)
    elif mood == FACE_SLEEP:
        p.drawLine(QPointF(c.x() - s * 0.08, mouth_y + s * 0.06), QPointF(c.x() + s * 0.08, mouth_y + s * 0.06))
    else:
        p.drawArc(QRectF(c.x() - s * 0.20, mouth_y - s * 0.14, s * 0.40, s * 0.26), 205 * 16, 130 * 16)
    p.restore()


def make_icon(draw, size: int, *args, dpr: float = 2.0) -> QIcon:
    """Render a drawing function into a high-DPI QIcon."""
    app = QGuiApplication.instance()
    if app is not None:
        dpr = max(dpr, app.devicePixelRatio())
    pixmap = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p, QRectF(0, 0, size, size), *args)
    p.end()
    return QIcon(pixmap)


def app_icon_pixmap(size: int) -> QPixmap:
    """Procedural version of the application icon (fallback if files are missing)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88)
    grad = QLinearGradient(r.topLeft(), r.bottomLeft())
    grad.setColorAt(0, QColor("#62a0ea"))
    grad.setColorAt(1, QColor("#1a5fb4"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(r, size * 0.2, size * 0.2)
    draw_mine(p, r.adjusted(size * 0.12, size * 0.12, -size * 0.12, -size * 0.12), QColor("#241f31"), QColor("#ffffff"))
    p.end()
    return pixmap
