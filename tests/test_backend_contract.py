from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backend_contract import (  # noqa: E402
    BACKEND_RESULT_REQUIRED,
    validate_backend_result,
)
from local_gpu_imagegen.errors import ArtifactError  # noqa: E402


def result(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ok": True,
        "path": "C:/runs/round-01.pending.png",
        "backend": "webui",
        "mode": "txt2img",
        "seed": 42,
        "width": 256,
        "height": 256,
    }
    value.update(changes)
    return value


class BackendContractTests(unittest.TestCase):
    def test_required_fields_are_the_normalized_cross_backend_contract(self) -> None:
        self.assertEqual(
            BACKEND_RESULT_REQUIRED,
            {"ok", "path", "backend", "mode", "seed", "width", "height"},
        )

    def test_accepts_webui_and_diffusers_results_and_returns_a_copy(self) -> None:
        for backend in ("webui", "diffusers"):
            with self.subTest(backend=backend):
                original = result(backend=backend)
                validated = validate_backend_result(original, "txt2img", 256, 256)
                self.assertEqual(validated, original)
                self.assertIsNot(validated, original)

    def test_rejects_invalid_results_with_stable_error_code(self) -> None:
        cases: dict[str, object] = {
            "non-object": [],
            "not-successful": result(ok=1),
            "unknown-backend": result(backend="comfyui"),
            "wrong-mode": result(mode="img2img"),
            "empty-path": result(path=""),
            "non-string-path": result(path=Path("round.png")),
            "wrong-width": result(width=512),
            "wrong-height": result(height=512),
            "boolean-seed": result(seed=True),
            "string-seed": result(seed="42"),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ArtifactError) as raised:
                    validate_backend_result(value, "txt2img", 256, 256)
                self.assertEqual(raised.exception.code, "invalid_backend_result")

    def test_rejects_each_missing_required_field(self) -> None:
        for field in sorted(BACKEND_RESULT_REQUIRED):
            with self.subTest(field=field):
                value = result()
                del value[field]
                with self.assertRaises(ArtifactError) as raised:
                    validate_backend_result(value, "txt2img", 256, 256)
                self.assertEqual(raised.exception.code, "invalid_backend_result")
                if field != "ok":
                    self.assertEqual(raised.exception.details, {"fields": [field]})


if __name__ == "__main__":
    unittest.main()
