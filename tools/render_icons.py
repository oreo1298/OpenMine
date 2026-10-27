"""Render the SVG app icon to the PNG and ICO files committed in the repo.

Run from the repository root after editing data/icons/*.svg:

    python tools/render_icons.py

Needs PySide6 (QtSvg) and Pillow.
"""

import io
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.oreo1298.OpenMine"
SVG = ROOT / "data" / "icons" / f"{APP_ID}.svg"
ASSETS = ROOT / "src" / "openmine" / "assets"
ICO = ROOT / "packaging" / "windows" / "openmine.ico"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def to_png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> int:
    from PIL import Image

    QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"cannot read {SVG}", file=sys.stderr)
        return 1
    ASSETS.mkdir(parents=True, exist_ok=True)
    for size in PNG_SIZES:
        render(renderer, size).save(str(ASSETS / f"{APP_ID}-{size}.png"))
    frames = [Image.open(io.BytesIO(to_png_bytes(render(renderer, s)))) for s in ICO_SIZES]
    frames[-1].save(ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    print(f"wrote {len(PNG_SIZES)} PNGs to {ASSETS} and {ICO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
