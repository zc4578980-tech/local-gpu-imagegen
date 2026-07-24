from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_social_preview import validate_social_preview


class SocialPreviewTests(unittest.TestCase):
    def test_social_preview_is_bound_to_validated_public_image(self) -> None:
        self.assertEqual(validate_social_preview(ROOT), [])

    def test_social_preview_copy_names_product_clients_and_backends(self) -> None:
        source = (
            ROOT / "docs" / "assets" / "github-social-preview.html"
        ).read_text(encoding="utf-8")
        for text in (
            "Local GPU Imagegen",
            "Codex + Claude Code",
            "ComfyUI / Forge / Diffusers",
            "Use the image models you already run locally",
            "../demo/real/final.png",
        ):
            with self.subTest(text=text):
                self.assertIn(text, source)

        manifest = json.loads(
            (ROOT / "docs" / "assets" / "github-social-preview.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["width"], 1280)
        self.assertEqual(manifest["height"], 640)


if __name__ == "__main__":
    unittest.main()
