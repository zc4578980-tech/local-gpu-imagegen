from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.engine import AssetRunEngine  # noqa: E402
from local_gpu_imagegen.errors import AssetEngineError, ValidationError  # noqa: E402
from local_gpu_imagegen.preview import PreviewResult  # noqa: E402
from local_gpu_imagegen.profile_registry import ProfileRegistry  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF)


def write_test_png(path: Path, width: int = 256, height: int = 256) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x20\x40\x80" * width for _ in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(scanlines)) + _chunk(b"IEND", b""))


class FakeBackendRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.exit_code = 0
        self.stderr = ""
        self.path_override: Path | None = None

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(args))
        output_dir = Path(args[args.index("--output-dir") + 1])
        filename = args[args.index("--filename") + 1]
        output_path = output_dir / filename
        if self.exit_code == 0:
            write_test_png(output_path)
        result = {
            "ok": True,
            "path": str(self.path_override or output_path),
            "backend": args[args.index("--backend") + 1],
            "mode": args[args.index("--mode") + 1],
            "seed": int(args[args.index("--seed") + 1]),
            "width": int(args[args.index("--width") + 1]),
            "height": int(args[args.index("--height") + 1]),
        }
        return self.exit_code, json.dumps(result), self.stderr


class SimulatedCrash(BaseException):
    pass


class AssetRunEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temporary_directory.name) / "output"
        self.runner = FakeBackendRunner()
        self.capabilities = {"available_backends": ["webui", "diffusers"], "cuda": True}
        self.engine = AssetRunEngine(
            ProfileRegistry(ROOT / "profiles"),
            RunStore(self.output_root),
            self.runner,
            lambda: self.capabilities,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def start_arguments(self, *, max_rounds: int = 3) -> dict[str, object]:
        return {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A calm coast at dawn.",
            "constraints": {"width": 256, "height": 256},
            "model_choice": "local-model",
            "backend": "webui",
            "available_backends": ["webui", "diffusers"],
            "upscale_policy": "never",
            "max_rounds": max_rounds,
        }

    def plan(self, *, max_rounds: int = 3, parameters: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A calm coast at dawn.",
            "positive_prompt": "calm coast at dawn",
            "negative_prompt": "watermark, text",
            "constraints": {"width": 256, "height": 256},
            "model_choice": "local-model",
            "backend": "webui",
            "parameters": parameters or {"mode": "txt2img", "scheduler": "euler"},
            "max_rounds": max_rounds,
            "upscale_policy": "never",
        }

    def generate_arguments(
        self,
        run_id: str,
        *,
        key: str = "initial-1",
        action: str = "initial",
        seed: int = 42,
        max_rounds: int = 3,
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "idempotency_key": key,
            "action": action,
            "seed": seed,
            "plan": self.plan(
                max_rounds=max_rounds,
                parameters={"steps": 8, "guidance_scale": 6.0} if action == "refine" else None,
            ),
        }

    def start(self, *, max_rounds: int = 3) -> dict[str, object]:
        return self.engine.start_run(self.start_arguments(max_rounds=max_rounds))

    def review(self, run_id: str, round_number: int, score: int = 4, hard_failures: list[str] | None = None) -> dict[str, object]:
        rubric = self.engine.get_run({"run_id": run_id})["request"]["merged_profile"]["rubric"]
        return self.engine.record_review({
            "run_id": run_id,
            "round_number": round_number,
            "review": {
                "scores": {name: score for name in rubric},
                "hard_failures": hard_failures or [],
                "critique": "Reviewed candidate.",
                "constraint_results": {
                    "width": {"status": "pass", "observation": "Width matches."},
                    "height": {"status": "pass", "observation": "Height matches."},
                },
                "next_action": "finalize",
            },
        })

    def test_list_profiles_injects_capabilities_without_mutating_registry(self) -> None:
        catalog_before = self.engine.registry.list_catalog()
        listed = self.engine.list_profiles()
        self.assertEqual(listed["capabilities"], self.capabilities)
        self.assertEqual(self.engine.registry.list_catalog(), catalog_before)
        self.capabilities["cuda"] = False
        self.assertTrue(listed["capabilities"]["cuda"])

    def test_start_and_get_return_run_id_rubric_and_deterministic_actions(self) -> None:
        started = self.start()
        self.assertTrue(started["ok"])
        self.assertRegex(started["run_id"], r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
        self.assertEqual(started["max_rounds"], 3)
        self.assertIn("subject_completeness", started["merged_rubric"])
        fetched = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(fetched["recoverable_next_actions"], ["generate_round"])

    def test_start_rejects_invalid_round_budget_before_creating_run(self) -> None:
        arguments = self.start_arguments(max_rounds=4)
        with self.assertRaises(ValidationError) as raised:
            self.engine.start_run(arguments)
        self.assertEqual(raised.exception.code, "invalid_round_budget")
        self.assertFalse((self.output_root / "runs").exists())

    def test_argument_validation_happens_before_state_mutation(self) -> None:
        with self.assertRaises(ValidationError) as missing:
            self.engine.start_run({})
        self.assertEqual(missing.exception.code, "missing_argument")
        started = self.start()
        invalid = self.generate_arguments(started["run_id"])
        invalid["seed"] = True
        with self.assertRaises(ValidationError) as wrong_type:
            self.engine.generate_round(invalid)
        self.assertEqual(wrong_type.exception.code, "invalid_argument_type")
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(manifest["attempts"], [])
        self.assertEqual(self.runner.calls, [])

    def test_one_round_uses_pending_then_atomic_final_name_and_returns_bounded_preview(self) -> None:
        started = self.start()
        data, preview = self.engine.generate_round(self.generate_arguments(started["run_id"]))
        run_root = self.output_root / "runs" / started["run_id"]
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0][self.runner.calls[0].index("--filename") + 1], "round-01.pending.png")
        self.assertFalse((run_root / "round-01.pending.png").exists())
        self.assertTrue((run_root / "round-01.png").is_file())
        self.assertEqual(data["round"]["image"]["path"], "round-01.png")
        self.assertEqual(data["round"]["backend"], "webui")
        self.assertEqual(data["round"]["mode"], "txt2img")
        self.assertEqual(data["full_image_path"], str((run_root / "round-01.png").resolve()))
        self.assertIsNotNone(preview)
        self.assertIsNotNone(preview.data_base64)

    def test_invalid_full_plan_does_not_begin_attempt(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        arguments["plan"]["intent"] = "Different intent."
        with self.assertRaises(ValidationError):
            self.engine.generate_round(arguments)
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(self.runner.calls, [])

    def test_invalid_derived_plan_values_do_not_begin_attempt(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        arguments["plan"]["parameters"]["width"] = True
        with self.assertRaises(ValidationError) as raised:
            self.engine.generate_round(arguments)
        self.assertEqual(raised.exception.code, "invalid_dimensions")
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(manifest["attempts"], [])
        self.assertEqual(self.runner.calls, [])

    def test_backend_result_path_must_remain_inside_the_run(self) -> None:
        started = self.start()
        self.runner.path_override = self.output_root.parent / "escape.png"
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.generate_round(self.generate_arguments(started["run_id"]))
        self.assertEqual(raised.exception.code, "path_outside_output_root")
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["rounds"], [])
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")

    def test_backend_failure_is_recorded_without_consuming_round(self) -> None:
        started = self.start()
        self.runner.exit_code = 9
        self.runner.stderr = "backend unavailable"
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.generate_round(self.generate_arguments(started["run_id"]))
        self.assertEqual(raised.exception.code, "backend_command_failed")
        failed = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(failed["state"], "created")
        self.assertEqual(failed["rounds"], [])
        self.assertEqual(failed["attempts"][-1]["status"], "failed")
        self.runner.exit_code = 0
        data, _ = self.engine.generate_round(self.generate_arguments(started["run_id"], key="initial-2"))
        self.assertEqual(data["round"]["round_number"], 1)

    def test_unexpected_exception_releases_owned_attempt_lock(self) -> None:
        started = self.start()
        with patch("local_gpu_imagegen.engine.validate_backend_result", side_effect=RuntimeError("unexpected")):
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                self.engine.generate_round(self.generate_arguments(started["run_id"]))
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")
        self.assertFalse((self.output_root / "runs" / started["run_id"] / ".run.lock").exists())

    def test_preview_warning_keeps_full_image_and_is_appended_to_run(self) -> None:
        started = self.start()
        unavailable = PreviewResult(None, None, None, None, None, "preview_unavailable:test")
        with patch("local_gpu_imagegen.engine.create_preview", return_value=unavailable):
            data, preview = self.engine.generate_round(self.generate_arguments(started["run_id"]))
        self.assertEqual(preview, unavailable)
        self.assertTrue(Path(data["full_image_path"]).is_file())
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertIn("preview_unavailable:test", manifest["warnings"])

    def test_crash_after_marked_image_rebuilds_preview_without_backend(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        with patch("local_gpu_imagegen.engine.create_preview", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
            data, preview = self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(data["round"]["round_number"], 1)
        self.assertIsNotNone(preview)

    def test_completed_retry_revalidates_artifact_and_never_calls_backend(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        preview_path = Path(first["full_image_path"]).with_suffix(".preview.jpg")
        preview_path.unlink(missing_ok=True)
        second, preview = self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(second["round"]["round_number"], 1)
        self.assertIsNotNone(preview)

    def test_review_and_weighted_eligible_selection_publish_final_atomically(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        self.review(run_id, 1, score=3)
        self.engine.generate_round(self.generate_arguments(run_id, key="refine-1", action="refine"))
        self.review(run_id, 2, score=5)
        finalized = self.engine.finalize_run({"run_id": run_id, "summary": "Best reviewed result."})
        run_root = self.output_root / "runs" / run_id
        self.assertEqual(finalized["final"]["round_number"], 2)
        self.assertEqual(finalized["final"]["quality_status"], "accepted")
        self.assertEqual(finalized["final"]["image"]["path"], "final.png")
        self.assertTrue((run_root / "final.png").is_file())
        self.assertFalse((run_root / "final.pending.png").exists())

    def test_early_finalize_accepts_eligible_round(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        self.review(run_id, 1)
        finalized = self.engine.finalize_run({"run_id": run_id, "summary": "Accepted early."})
        self.assertEqual(finalized["final"]["quality_status"], "accepted")

    def test_exhausted_custom_budget_selects_best_ineligible_for_user_review(self) -> None:
        started = self.start(max_rounds=1)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=1))
        self.review(run_id, 1, score=5, hard_failures=["missing_subject"])
        finalized = self.engine.finalize_run({"run_id": run_id, "summary": "Budget exhausted."})
        self.assertEqual(finalized["max_rounds"], 1)
        self.assertEqual(finalized["final"]["quality_status"], "needs_user_review")

    def test_ineligible_run_cannot_finalize_before_budget_is_exhausted(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        self.review(run_id, 1, hard_failures=["missing_subject"])
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.finalize_run({"run_id": run_id, "summary": "Too early."})
        self.assertEqual(raised.exception.code, "no_eligible_round")

    def test_invalid_final_summary_does_not_publish_an_artifact(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        self.review(run_id, 1)
        with self.assertRaises(ValidationError) as raised:
            self.engine.finalize_run({"run_id": run_id, "summary": " "})
        self.assertEqual(raised.exception.code, "invalid_final_summary")
        self.assertFalse((self.output_root / "runs" / run_id / "final.png").exists())
        self.assertEqual(self.engine.get_run({"run_id": run_id})["state"], "reviewed")

    def test_cleanup_requires_exact_confirmation(self) -> None:
        started = self.start()
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.cleanup_run({"run_id": started["run_id"], "scope": "all", "confirmation": "wrong"})
        self.assertEqual(raised.exception.code, "cleanup_confirmation_mismatch")
        cleaned = self.engine.cleanup_run({
            "run_id": started["run_id"],
            "scope": "all",
            "confirmation": started["run_id"],
        })
        self.assertEqual(cleaned, {"ok": True, "run_id": started["run_id"], "scope": "all"})
        self.assertFalse((self.output_root / "runs" / started["run_id"]).exists())


if __name__ == "__main__":
    unittest.main()
