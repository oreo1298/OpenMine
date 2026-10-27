import pytest

pytest.importorskip("PySide6.QtGui")

from PySide6.QtGui import QColor  # noqa: E402

from openmine.theme import BoardColors, build_palette, luminance, parse_appearance  # noqa: E402

GDBUS = (
    "({'org.freedesktop.appearance': {'color-scheme': <uint32 1>, "
    "'accent-color': <(0.20784313725490197, 0.51764705882352946, 0.89411764705882357)>, "
    "'contrast': <uint32 0>}},)"
)
BUSCTL = (
    'a{sa{sv}} 1 "org.freedesktop.appearance" 3 "color-scheme" u 2 '
    '"accent-color" (ddd) 0.207843 0.517647 0.894118 "contrast" u 0'
)


def test_parse_gdbus_output():
    scheme, accent = parse_appearance(GDBUS)
    assert scheme == "dark"
    assert accent.name() == "#3584e4"


def test_parse_busctl_output():
    scheme, accent = parse_appearance(BUSCTL)
    assert scheme == "light"
    assert accent.name() == "#3584e4"


def test_parse_no_preference_and_unset_accent():
    text = "({'org.freedesktop.appearance': {'color-scheme': <uint32 0>, 'accent-color': <(-1.0, -1.0, -1.0)>}},)"
    assert parse_appearance(text) == (None, None)
    assert parse_appearance("({},)") == (None, None)


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("accent", ["#3584e4", "#f6d32d", "#6f8396", "#e62d42", "#808080"])
def test_board_colors_keep_contrast(dark, accent):
    palette = build_palette(dark, QColor(accent))
    colors = BoardColors.from_palette(palette, QColor(accent), dark)
    # Covered and uncovered squares must be told apart by brightness, not just hue.
    assert abs(luminance(colors.hidden) - luminance(colors.revealed)) > 0.05
    for number in colors.numbers[:6]:
        assert abs(luminance(number) - luminance(colors.revealed)) > 0.1
