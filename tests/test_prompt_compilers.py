from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.prompt_compilers import PromptCompilerRegistry  # noqa: E402


class PromptCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compilers = PromptCompilerRegistry()

    def test_unknown_family_uses_conservative_natural_language(self) -> None:
        compiled = self.compilers.compile(
            "natural-v1",
            "  A   calm sea\n at dawn. ",
            " text   artifacts ",
        )

        self.assertEqual(compiled, {
            "compiler_id": "natural-v1",
            "compiler_version": 1,
            "positive_prompt": "A calm sea at dawn.",
            "negative_prompt": "text artifacts",
        })

    def test_sd15_compiler_normalizes_explicit_tags_without_inventing_any(self) -> None:
        compiled = self.compilers.compile(
            "sd15-tags-v1",
            " masterpiece,  calm sea ,, dawn ",
            " artifacts,  text, ",
        )

        self.assertEqual(compiled["positive_prompt"], "masterpiece, calm sea, dawn")
        self.assertEqual(compiled["negative_prompt"], "artifacts, text")
        self.assertEqual(compiled["compiler_version"], 1)

    def test_rejects_unknown_compiler_or_empty_positive_prompt(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown_prompt_compiler"):
            self.compilers.compile("magic-v2", "sea", "")
        with self.assertRaisesRegex(ValidationError, "invalid_prompt"):
            self.compilers.compile("natural-v1", "   ", "")


if __name__ == "__main__":
    unittest.main()
