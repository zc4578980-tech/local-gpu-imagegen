from __future__ import annotations

import json
import shutil
import sys
import tempfile
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
            "Run supported ComfyUI workflows from your Agent",
            "SEPARATE VALIDATED OUTPUT",
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

    def test_social_preview_rejects_html_drift_after_render(self) -> None:
        retained = (
            "docs/assets/github-social-preview.html",
            "docs/assets/github-social-preview.json",
            "docs/assets/github-social-preview.png",
            "docs/demo/real/final.png",
            "docs/demo/real/showcase-manifest.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in retained:
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            html = root / "docs/assets/github-social-preview.html"
            html.write_text(
                html.read_text(encoding="utf-8") + "\n<!-- stale render -->\n",
                encoding="utf-8",
            )

            self.assertIn(
                "social_preview_html_sha256_mismatch",
                validate_social_preview(root),
            )


if __name__ == "__main__":
    unittest.main()
