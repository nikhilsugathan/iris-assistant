from __future__ import annotations

from pathlib import Path
import sys

from PySide6 import QtGui

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.visual_identity import render_orb_image


def main():
    app = QtGui.QGuiApplication([])
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    png_path = assets_dir / "iris_aletheia.png"
    ico_path = assets_dir / "iris_aletheia.ico"

    image = render_orb_image(512)
    if not image.save(str(png_path), "PNG"):
        raise RuntimeError(f"Failed to write {png_path}")

    try:
        from PIL import Image

        base = Image.open(png_path)
        base.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    except Exception:
        if not image.save(str(ico_path), "ICO"):
            raise RuntimeError(f"Failed to write {ico_path}")

    print(f"Wrote {png_path}")
    print(f"Wrote {ico_path}")
    app.quit()


if __name__ == "__main__":
    main()
