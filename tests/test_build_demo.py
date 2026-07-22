from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildDemoTests(unittest.TestCase):
    def test_demo_is_deterministic_bounded_and_explicitly_simulated(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import build_demo

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_manifest = build_demo.build_demo(Path(first))
            second_manifest = build_demo.build_demo(Path(second))
            first_gif = (Path(first) / "preview-loop.gif").read_bytes()
            second_gif = (Path(second) / "preview-loop.gif").read_bytes()

        self.assertEqual(first_gif, second_gif)
        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_gif[:6], b"GIF89a")
        width, height = struct.unpack("<HH", first_gif[6:10])
        self.assertEqual((width, height), (720, 405))
        self.assertLess(len(first_gif), 1_500_000)
        self.assertFalse(first_manifest["model_output"])
        self.assertEqual(first_manifest["demo_kind"], "simulated_protocol")
        self.assertEqual(len(first_manifest["frames"]), 5)
        self.assertEqual(first_manifest["gif"]["sha256"], hashlib.sha256(first_gif).hexdigest())

    def test_committed_demo_matches_generator_and_contains_no_private_values(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import build_demo

        demo_root = ROOT / "docs" / "demo"
        committed_manifest = json.loads((demo_root / "demo-manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            generated_manifest = build_demo.build_demo(Path(directory))
            generated_gif = (Path(directory) / "preview-loop.gif").read_bytes()

        committed_gif = (demo_root / "preview-loop.gif").read_bytes()
        self.assertEqual(committed_manifest, generated_manifest)
        self.assertEqual(committed_gif, generated_gif)
        public_bytes = committed_gif + json.dumps(committed_manifest).encode("utf-8")
        for forbidden in (b"D:\\", b"C:\\Users", b"Capricorn", b"127.0.0.1"):
            self.assertNotIn(forbidden, public_bytes)


if __name__ == "__main__":
    unittest.main()
