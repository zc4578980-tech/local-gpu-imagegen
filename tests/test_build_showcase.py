from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

if __package__:
    from .real_demo_helpers import png_bytes
else:
    from real_demo_helpers import png_bytes


class BuildShowcaseTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is an optional local showcase encoder.")
    def test_builds_two_frame_gif_from_retained_png_bytes(self) -> None:
        from build_showcase import build_showcase

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.png"
            after = root / "after.png"
            output = root / "showcase.gif"
            before.write_bytes(png_bytes(24, 72, 96))
            after.write_bytes(png_bytes(160, 88, 72))

            build_showcase(before, after, output)

            encoded = output.read_bytes()
            self.assertEqual(encoded[:6], b"GIF89a")
            self.assertGreater(len(encoded), 100)


if __name__ == "__main__":
    unittest.main()
