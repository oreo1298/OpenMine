"""Follow the desktop's light/dark preference and accent colour.

Qt already adapts to the platform in most cases, but coverage differs between
desktops and Qt versions. ``ThemeManager`` fills the gaps:

* Linux: reads ``color-scheme`` and ``accent-color`` from the XDG desktop
  portal (GNOME, KDE Plasma, and others) and listens for changes.
* Windows: uses Qt's colour scheme / accent, falling back to the registry.
  When Windows is in dark mode but the active Qt style cannot draw dark
  widgets (``windowsvista`` on Windows 10), the app switches to Fusion.
* If the palette Qt produced does not match the wanted scheme (or the user
  forces light/dark in the settings), a matching palette is generated from
  the accent colour.

Everything the game draws itself takes its colours from ``BoardColors``,
which is derived from the active palette plus the accent colour.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import SLOT, QEvent, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_IFACE = "org.freedesktop.portal.Settings"
APPEARANCE = "org.freedesktop.appearance"

DEFAULT_ACCENT = QColor("#3584e4")
# Native Windows styles ignore most palette colours, so they cannot be themed.
NATIVE_WINDOWS_STYLES = {"windows", "windowsvista", "windows11"}

_HAS_ACCENT_ROLE = hasattr(QPalette.ColorRole, "Accent")


def luminance(color: QColor) -> float:
    """WCAG relative luminance (0 = black, 1 = white)."""

    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.redF())
        + 0.7152 * channel(color.greenF())
        + 0.0722 * channel(color.blueF())
    )


def is_dark(color: QColor) -> bool:
    return luminance(color) < 0.2


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Blend from ``a`` (t=0) to ``b`` (t=1)."""
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


def with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def contrast_text(background: QColor) -> QColor:
    return QColor("#000000") if luminance(background) > 0.45 else QColor("#ffffff")


def tone(accent: QColor, lightness: float, min_sat: float = 0.12, max_sat: float = 0.85) -> QColor:
    """The accent's hue at a fixed HSL lightness (keeps contrast predictable)."""
    hue = accent.hslHueF()
    sat = accent.hslSaturationF()
    if hue < 0:  # achromatic accent (grey)
        hue, sat = 0.6, 0.0
    sat = max(min_sat if sat > 0.02 else 0.0, min(max_sat, sat))
    return QColor.fromHslF(hue, sat, lightness)


# --------------------------------------------------------------------------
# Platform probing
# --------------------------------------------------------------------------


_SCHEME_RE = re.compile(r"color-scheme[\"']\s*:?\s*<?(?:uint32|u)\s+(\d+)")
_NUMBER = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
_ACCENT_RE = re.compile(
    r"accent-color[\"']\s*:?\s*<?\s*(?:\(ddd\))?\s*\(?\s*" + r"[,\s]+".join([_NUMBER] * 3)
)


def parse_appearance(text: str) -> tuple[Optional[str], Optional[QColor]]:
    """Parse ``ReadAll`` output from ``gdbus call`` or ``busctl call``.

    Returns the colour scheme ('dark', 'light' or None for "no preference")
    and the accent colour (None when unset).
    """
    scheme = None
    match = _SCHEME_RE.search(text)
    if match:
        scheme = {1: "dark", 2: "light"}.get(int(match.group(1)))
    accent = None
    match = _ACCENT_RE.search(text)
    if match:
        r, g, b = (float(x) for x in match.groups())
        # Out-of-range values mean "no accent colour set".
        if all(0.0 <= v <= 1.0 for v in (r, g, b)):
            accent = QColor.fromRgbF(r, g, b)
    return scheme, accent


def read_appearance() -> Optional[tuple[Optional[str], Optional[QColor]]]:
    """Ask the desktop portal for its appearance settings (None if unavailable).

    This shells out to gdbus or busctl, one of which ships with practically
    every Linux desktop, because PySide6 cannot reliably unpack the D-Bus
    variants involved (and some releases crash trying).
    """
    commands = []
    if shutil.which("gdbus"):
        commands.append(
            ["gdbus", "call", "--session", "--timeout", "2", "--dest", PORTAL_SERVICE,
             "--object-path", PORTAL_PATH, "--method", f"{PORTAL_IFACE}.ReadAll", f"['{APPEARANCE}']"]
        )
    if shutil.which("busctl"):
        commands.append(
            ["busctl", "--user", "--timeout=2", "call", PORTAL_SERVICE, PORTAL_PATH, PORTAL_IFACE,
             "ReadAll", "as", "1", APPEARANCE]
        )
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return parse_appearance(result.stdout)
        if "ServiceUnknown" in result.stderr or "NameHasNoOwner" in result.stderr:
            return None  # no portal on this system; no need to try another tool
    return None


class Portal(QObject):
    """Follows org.freedesktop.appearance from the XDG desktop portal (Linux).

    ``scheme`` and ``accent`` hold the last values read; ``changed`` fires when
    either of them changes.
    """

    changed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.available = False
        self.scheme: Optional[str] = None
        self.accent: Optional[QColor] = None
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") and not os.path.exists(
            os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"), "bus")
        ):
            return
        self.available = True
        self.update()
        if not self.available:
            return
        try:
            from PySide6.QtDBus import QDBusConnection
        except ImportError:  # some distributions package QtDBus separately
            return
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        # The D-Bus signal goes straight to a C++ slot (QTimer.start): routing
        # it to a Python slot deadlocks with some PySide6 releases.
        self._poke = QTimer(self)
        self._poke.setSingleShot(True)
        self._poke.setInterval(50)
        self._poke.timeout.connect(self._on_poke)
        bus.connect(PORTAL_SERVICE, PORTAL_PATH, PORTAL_IFACE, "SettingChanged", self._poke, SLOT("start()"))
        self._bus = bus

    def _on_poke(self) -> None:
        if self.update():
            self.changed.emit()

    def update(self) -> bool:
        """Re-read the appearance settings. Returns True if anything changed."""
        if not self.available:
            return False
        old = (self.scheme, self.accent.name() if self.accent else None)
        values = read_appearance()
        if values is None:
            self.available = False
            self.scheme, self.accent = None, None
        else:
            self.scheme, self.accent = values
        return old != (self.scheme, self.accent.name() if self.accent else None)


def _windows_registry(path: str, name: str) -> Optional[int]:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return int(value)
    except (ImportError, OSError, ValueError):
        return None


def windows_color_scheme() -> Optional[str]:
    value = _windows_registry(
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme"
    )
    if value is None:
        return None
    return "light" if value else "dark"


def windows_accent() -> Optional[QColor]:
    value = _windows_registry(r"Software\Microsoft\Windows\DWM", "AccentColor")
    if value is None:
        return None
    # Stored as 0xAABBGGRR
    return QColor(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


# --------------------------------------------------------------------------
# Palettes
# --------------------------------------------------------------------------


def build_palette(dark: bool, accent: QColor) -> QPalette:
    """A clean, neutral palette in the spirit of modern desktop themes."""
    if dark:
        window, base, alt, button = "#242424", "#1e1e1e", "#2a2a2a", "#383838"
        text, muted, disabled = "#f2f2f2", "#9a9a9a", "#7a7a7a"
        light, midlight, mid, dark_c, shadow = "#505050", "#404040", "#2e2e2e", "#151515", "#000000"
        tooltip = "#383838"
        link = tone(accent, 0.72)
    else:
        window, base, alt, button = "#fafafa", "#ffffff", "#f4f4f5", "#ededee"
        text, muted, disabled = "#222226", "#8e8e93", "#a2a2a6"
        light, midlight, mid, dark_c, shadow = "#ffffff", "#f5f5f5", "#c8c8cc", "#9e9ea3", "#5e5e63"
        tooltip = "#ffffff"
        link = tone(accent, 0.40)
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: window,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: alt,
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: button,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Light: light,
        QPalette.ColorRole.Midlight: midlight,
        QPalette.ColorRole.Mid: mid,
        QPalette.ColorRole.Dark: dark_c,
        QPalette.ColorRole.Shadow: shadow,
        QPalette.ColorRole.ToolTipBase: tooltip,
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.PlaceholderText: muted,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled))
    p.setColor(QPalette.ColorRole.Link, link)
    p.setColor(QPalette.ColorRole.LinkVisited, link.darker(115) if not dark else link.lighter(115))
    apply_accent(p, accent)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(mid))
    return p


def apply_accent(palette: QPalette, accent: QColor) -> None:
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Highlight, accent)
        palette.setColor(group, QPalette.ColorRole.HighlightedText, contrast_text(accent))
        if _HAS_ACCENT_ROLE:
            palette.setColor(group, QPalette.ColorRole.Accent, accent)


@dataclass
class BoardColors:
    dark: bool
    accent: QColor
    background: QColor
    text: QColor
    muted: QColor
    surface: QColor
    hidden: QColor
    hidden_alt: QColor
    hidden_hover: QColor
    hidden_edge: QColor
    hidden_shine: QColor
    revealed: QColor
    revealed_alt: QColor
    numbers: tuple
    flag: QColor
    pole: QColor
    mine: QColor
    mine_shine: QColor
    exploded: QColor
    wrong: QColor
    cursor: QColor
    hint: QColor
    win_glow: QColor

    @classmethod
    def from_palette(cls, palette: QPalette, accent: QColor, dark: bool) -> "BoardColors":
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        if dark:
            hidden = tone(accent, 0.37)
            hidden_alt = tone(accent, 0.345)
            hidden_hover = tone(accent, 0.44)
            hidden_edge = tone(accent, 0.24)
            numbers = ("#78aeed", "#57e389", "#ff7b63", "#dc8add",
                       "#ffa348", "#5bc8af", "#f6f5f4", "#c0bfbc")
            flag, exploded, hint = QColor("#ff6b5b"), QColor("#c01c28"), QColor("#57e389")
        else:
            hidden = tone(accent, 0.74)
            hidden_alt = tone(accent, 0.715)
            hidden_hover = tone(accent, 0.80)
            hidden_edge = tone(accent, 0.57)
            numbers = ("#1c71d8", "#26a269", "#e01b24", "#813d9c",
                       "#c64600", "#0f8a8a", "#241f31", "#77767b")
            flag, exploded, hint = QColor("#e01b24"), QColor("#e01b24"), QColor("#26a269")
        return cls(
            dark=dark,
            accent=QColor(accent),
            background=window,
            text=text,
            muted=mix(window, text, 0.55),
            surface=mix(window, text, 0.045),
            hidden=hidden,
            hidden_alt=hidden_alt,
            hidden_hover=hidden_hover,
            hidden_edge=hidden_edge,
            hidden_shine=with_alpha(QColor("#ffffff"), 0.10 if dark else 0.35),
            revealed=mix(window, text, 0.075),
            revealed_alt=mix(window, text, 0.095),
            numbers=tuple(QColor(c) for c in numbers),
            flag=flag,
            pole=QColor("#f6f5f4") if dark else QColor("#3d3846"),
            mine=QColor("#e6e6e6") if dark else QColor("#241f31"),
            mine_shine=with_alpha(QColor("#ffffff"), 0.85),
            exploded=exploded,
            wrong=QColor("#ff6b5b") if dark else QColor("#c01c28"),
            cursor=with_alpha(text, 0.9),
            hint=hint,
            win_glow=QColor("#ffffff") if not dark else tone(accent, 0.75),
        )


# --------------------------------------------------------------------------
# Theme manager
# --------------------------------------------------------------------------


class ThemeManager(QObject):
    """Keeps the application palette in sync with the desktop."""

    changed = Signal()

    def __init__(self, app: QApplication, mode: str = "system") -> None:
        super().__init__(app)
        self.app = app
        self.mode = mode
        self.dark = False
        self.accent = QColor(DEFAULT_ACCENT)
        self.colors = BoardColors.from_palette(app.palette(), self.accent, False)
        self._native_style = app.style().name()
        self._style_overridden = False
        self._palette_overridden = False
        self._applying = False
        self._requested_scheme = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self.refresh)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._schedule)
        self.portal: Optional[Portal] = None
        if sys.platform.startswith("linux") or "bsd" in sys.platform:
            self.portal = Portal(self)
            self.portal.changed.connect(self._schedule)
        app.installEventFilter(self)
        self.refresh()

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.refresh()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if (
            obj is self.app
            and not self._applying
            and event.type() == QEvent.Type.ApplicationPaletteChange
        ):
            self._schedule()
        return False

    def _schedule(self, *_args: object) -> None:
        if not self._applying:
            self._debounce.start()

    # ----------------------------------------------------------- detection
    def system_scheme(self) -> str:
        if self.portal is not None and self.portal.scheme:
            return self.portal.scheme
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme") and self._requested_scheme in (None, Qt.ColorScheme.Unknown):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
        if sys.platform == "win32":
            scheme = windows_color_scheme()
            if scheme:
                return scheme
        window = self.app.palette().color(QPalette.ColorRole.Window)
        return "dark" if is_dark(window) else "light"

    def system_accent(self, native: QPalette) -> tuple[QColor, bool]:
        """Returns (accent, came_from_outside_qt)."""
        if self.portal is not None and self.portal.accent is not None and self.portal.accent.isValid():
            return QColor(self.portal.accent), True
        if sys.platform == "win32" and not _HAS_ACCENT_ROLE:
            accent = windows_accent()
            if accent is not None:
                return accent, True
        role = QPalette.ColorRole.Accent if _HAS_ACCENT_ROLE else QPalette.ColorRole.Highlight
        accent = native.color(QPalette.ColorGroup.Active, role)
        if not accent.isValid() or (accent.saturationF() < 0.05 and accent.lightnessF() > 0.9):
            accent = QColor(DEFAULT_ACCENT)
        return accent, False

    # ------------------------------------------------------------- applying
    @Slot()
    def refresh(self) -> None:
        self._applying = True
        try:
            self._request_scheme()
            # Start from what the platform gives us.
            if self._style_overridden:
                self.app.setStyle(self._native_style)
                self._style_overridden = False
            if self._palette_overridden:
                self.app.setPalette(QPalette())
                self._palette_overridden = False
            native = self.app.palette()
            if self.mode == "system":
                want_dark = self.system_scheme() == "dark"
            else:
                want_dark = self.mode == "dark"
            native_dark = is_dark(native.color(QPalette.ColorRole.Window))
            accent, external_accent = self.system_accent(native)

            palette: Optional[QPalette] = None
            if native_dark != want_dark:
                if self.app.style().name().lower() in NATIVE_WINDOWS_STYLES:
                    self.app.setStyle("Fusion")
                    self._style_overridden = True
                palette = build_palette(want_dark, accent)
            elif external_accent and native.color(QPalette.ColorRole.Highlight) != accent:
                palette = QPalette(native)
                apply_accent(palette, accent)
            if palette is not None:
                self.app.setPalette(palette)
                self._palette_overridden = True

            self.dark = want_dark
            self.accent = accent
            self.colors = BoardColors.from_palette(self.app.palette(), accent, want_dark)
        finally:
            self._applying = False
        self.changed.emit()

    def _request_scheme(self) -> None:
        """Ask Qt (6.8+) for the scheme so native parts such as title bars match."""
        hints = QGuiApplication.styleHints()
        if not hasattr(hints, "setColorScheme"):
            return
        target = {
            "light": Qt.ColorScheme.Light,
            "dark": Qt.ColorScheme.Dark,
        }.get(self.mode, Qt.ColorScheme.Unknown)
        if target != self._requested_scheme:
            self._requested_scheme = target
            hints.setColorScheme(target)
