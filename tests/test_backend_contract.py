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
from local_gpu_imagegen.two_stage_layout import TWO_STAGE_TEMPLATE_ID  # noqa: E402


def result(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ok": True,
        "path": "C:/runs/round-01.pending.png",
        "backend": "webui",
        "mode": "txt2img",
        "seed": 42,
        "width": 256,
        "height": 256,
        "model": "anything-v5.safetensors",
        "endpoint_identity": "endpoint:test",
        "model_identity_token": "model:test",
        "identity_strength": "cryptographic",
        "workflow_template_id": None,
        "workflow_template_version": None,
        "prompt_compiler_id": "sd15-tags-v1",
        "prompt_compiler_version": 1,
    }
    value.update(changes)
    return value


def validate(value: object, *, backend: str = "webui", seed: int = 42) -> dict[str, object]:
    return validate_backend_result(
        value,
        "txt2img",
        256,
        256,
        expected_seed=seed,
        expected_backend=backend,
        available_backends=["webui", "diffusers"],
    )


def two_stage_backend_result(**changes: object) -> dict[str, object]:
    value = result(
        path="C:/runs/final.pending.png",
        backend="comfyui",
        seed=2026072303,
        width=1280,
        height=720,
        workflow_template_id=TWO_STAGE_TEMPLATE_ID,
        workflow_template_version=1,
        workflow_job_id="prompt-two-stage-1",
        prompt_compiler_id="natural-v1",
        stage_outputs={
            "base": {"path": "C:/runs/base.pending.png"},
            "final": {"path": "C:/runs/final.pending.png"},
        },
        mask_output={"path": "C:/runs/mask.pending.png"},
        subject_seed=2026072304,
        control_sha256="c" * 64,
    )
    value.update(changes)
    return value


class BackendContractTests(unittest.TestCase):
    def test_required_fields_are_the_normalized_cross_backend_contract(self) -> None:
        self.assertEqual(
            BACKEND_RESULT_REQUIRED,
            {
                "ok", "path", "backend", "mode", "seed", "width", "height", "model",
                "endpoint_identity", "model_identity_token", "identity_strength",
                "workflow_template_id", "workflow_template_version", "prompt_compiler_id",
                "prompt_compiler_version",
            },
        )

    def test_accepts_all_registered_backends_and_returns_a_copy(self) -> None:
        for backend in ("webui", "diffusers", "comfyui"):
            with self.subTest(backend=backend):
                changes: dict[str, object] = {"backend": backend}
                if backend == "comfyui":
                    changes.update({
                        "workflow_template_id": "sd15-txt2img-v1",
                        "workflow_template_version": 1,
                        "workflow_job_id": "prompt-1",
                    })
                original = result(**changes)
                validated = validate_backend_result(
                    original,
                    "txt2img",
                    256,
                    256,
                    expected_seed=42,
                    expected_backend=backend,
                    available_backends=["webui", "diffusers", "comfyui"],
                )
                self.assertEqual(validated, original)
                self.assertIsNot(validated, original)

    def test_comfyui_requires_a_workflow_job_id(self) -> None:
        with self.assertRaises(ArtifactError) as raised:
            validate_backend_result(
                result(
                    backend="comfyui",
                    workflow_template_id="sd15-txt2img-v1",
                    workflow_template_version=1,
                ),
                "txt2img",
                256,
                256,
                expected_seed=42,
                expected_backend="comfyui",
                available_backends=["comfyui"],
            )
        self.assertEqual(raised.exception.code, "invalid_backend_result")

    def test_two_stage_backend_result_requires_exact_stage_shape(self) -> None:
        original = two_stage_backend_result()
        validated = validate_backend_result(
            original,
            "txt2img",
            1280,
            720,
            expected_seed=2026072303,
            expected_backend="comfyui",
            available_backends=["comfyui"],
        )

        self.assertEqual(validated["subject_seed"], 2026072304)
        self.assertEqual(set(validated["stage_outputs"]), {"base", "final"})
        self.assertEqual(validated["control_sha256"], "c" * 64)
        self.assertEqual(validated, original)
        self.assertIsNot(validated, original)

    def test_two_stage_backend_result_rejects_invalid_stage_metadata(self) -> None:
        cases = {
            "missing-field": {key: value for key, value in two_stage_backend_result().items() if key != "mask_output"},
            "extra-role": two_stage_backend_result(stage_outputs={
                "base": {"path": "C:/runs/base.pending.png"},
                "mask": {"path": "C:/runs/mask.pending.png"},
                "final": {"path": "C:/runs/final.pending.png"},
            }),
            "extra-output-field": two_stage_backend_result(mask_output={
                "path": "C:/runs/mask.pending.png", "role": "mask",
            }),
            "wrong-subject-seed": two_stage_backend_result(subject_seed=2026072305),
            "boolean-subject-seed": two_stage_backend_result(subject_seed=True),
            "unsafe-path": two_stage_backend_result(mask_output={"path": ""}),
            "uppercase-digest": two_stage_backend_result(control_sha256="C" * 64),
            "short-digest": two_stage_backend_result(control_sha256="c" * 63),
        }
        for name, value in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                ArtifactError, "invalid_backend_result"
            ):
                validate_backend_result(
                    value,
                    "txt2img",
                    1280,
                    720,
                    expected_seed=2026072303,
                    expected_backend="comfyui",
                    available_backends=["comfyui"],
                )

    def test_non_two_stage_results_reject_two_stage_metadata(self) -> None:
        for field in ("stage_outputs", "mask_output", "subject_seed", "control_sha256"):
            value = result()
            value[field] = two_stage_backend_result()[field]
            with self.subTest(field=field), self.assertRaisesRegex(
                ArtifactError, "invalid_backend_result"
            ):
                validate(value)

    def test_rejects_invalid_results_with_stable_error_code(self) -> None:
        cases: dict[str, object] = {
            "non-object": [],
            "not-successful": result(ok=1),
            "unknown-backend": result(backend="comfyui"),
            "list-backend": result(backend=["webui"]),
            "object-backend": result(backend={"name": "webui"}),
            "boolean-backend": result(backend=True),
            "wrong-mode": result(mode="img2img"),
            "list-mode": result(mode=["txt2img"]),
            "object-mode": result(mode={"name": "txt2img"}),
            "empty-path": result(path=""),
            "non-string-path": result(path=Path("round.png")),
            "wrong-width": result(width=512),
            "wrong-height": result(height=512),
            "boolean-width": result(width=True),
            "float-width": result(width=256.0),
            "boolean-height": result(height=True),
            "float-height": result(height=256.0),
            "boolean-seed": result(seed=True),
            "string-seed": result(seed="42"),
            "wrong-seed": result(seed=43),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ArtifactError) as raised:
                    validate(value)
                self.assertEqual(raised.exception.code, "invalid_backend_result")

    def test_rejects_each_missing_required_field(self) -> None:
        for field in sorted(BACKEND_RESULT_REQUIRED):
            with self.subTest(field=field):
                value = result()
                del value[field]
                with self.assertRaises(ArtifactError) as raised:
                    validate(value)
                self.assertEqual(raised.exception.code, "invalid_backend_result")
                if field != "ok":
                    self.assertEqual(raised.exception.details, {"fields": [field]})

    def test_fixed_backend_must_match_exactly(self) -> None:
        with self.assertRaises(ArtifactError) as raised:
            validate(result(backend="diffusers"), backend="webui")
        self.assertEqual(raised.exception.code, "invalid_backend_result")

    def test_exact_backend_must_be_advertised(self) -> None:
        accepted = validate_backend_result(
            result(backend="diffusers"),
            "txt2img",
            256,
            256,
            expected_seed=42,
            expected_backend="diffusers",
            available_backends=["diffusers"],
        )
        self.assertEqual(accepted["backend"], "diffusers")
        for actual, advertised in (("webui", ["diffusers"]), ("diffusers", ["webui"])):
            with self.subTest(actual=actual, advertised=advertised):
                with self.assertRaises(ArtifactError) as raised:
                    validate_backend_result(
                        result(backend=actual),
                        "txt2img",
                        256,
                        256,
                        expected_seed=42,
                        expected_backend=actual,
                        available_backends=advertised,
                    )
                self.assertEqual(raised.exception.code, "invalid_backend_result")


if __name__ == "__main__":
    unittest.main()
