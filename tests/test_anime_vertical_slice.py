from __future__ import annotations

import base64
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.artifacts import validate_png  # noqa: E402
from local_gpu_imagegen.engine import AssetRunEngine  # noqa: E402
from local_gpu_imagegen.errors import AssetEngineError  # noqa: E402
from local_gpu_imagegen.preview import MAX_PREVIEW_BYTES  # noqa: E402
from local_gpu_imagegen.profile_registry import MODEL_REQUIRED, ProfileRegistry  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402


MODEL_ID = "test/approved-anime"
UPSCALE_MODEL = "realesrgan-x4plus-anime"
ROUND_HASHES = (
    "43c5bea8871e178dcce3742fbde7c234025091fb5d09e779399fc68bc3f42a55",
    "57ea58cd59c96e9900dfe281a72a5528ed2e814c1ad31216c54b9bd74c4c6ff3",
)
UPSCALED_HASH = "5428a45356c97dbbffc7c823e5eae898e1dac315e16e7754769bf0fe729dd5d9"
BRIEF_PATH = ROOT / "tests" / "fixtures" / "briefs" / "standalone-anime-character.json"
MODEL_PATH = ROOT / "tests" / "fixtures" / "models" / "approved-test-anime.json"


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _stored_zlib(data: bytes) -> bytes:
    encoded = bytearray(b"\x78\x01")
    for offset in range(0, len(data), 65535):
        block = data[offset:offset + 65535]
        encoded.append(1 if offset + len(block) == len(data) else 0)
        encoded.extend(struct.pack("<H", len(block)))
        encoded.extend(struct.pack("<H", 0xFFFF ^ len(block)))
        encoded.extend(block)
    encoded.extend(struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF))
    return bytes(encoded)


def _png_bytes(width: int, height: int, pixel: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = (b"\x00" + pixel * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", _stored_zlib(scanlines))
        + _chunk(b"IEND", b"")
    )


class FakeBackendRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, arguments: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(arguments))
        output = (
            Path(arguments[arguments.index("--output-dir") + 1])
            / arguments[arguments.index("--filename") + 1]
        )
        pixels = (b"\x24\x48\x90", b"\x30\x80\xc0")
        output.write_bytes(_png_bytes(256, 256, pixels[len(self.calls) - 1]))
        result = {
            "ok": True,
            "path": str(output),
            "backend": arguments[arguments.index("--backend") + 1],
            "mode": arguments[arguments.index("--mode") + 1],
            "seed": int(arguments[arguments.index("--seed") + 1]),
            "width": int(arguments[arguments.index("--width") + 1]),
            "height": int(arguments[arguments.index("--height") + 1]),
            "model": arguments[arguments.index("--model") + 1],
        }
        return 0, json.dumps(result), ""


class FakePostprocessor:
    def __init__(self, *, available: bool = True, fail: bool = False) -> None:
        self.available = available
        self.fail = fail
        self.upscale_calls: list[tuple[Path, Path, str]] = []

    def available_models(self) -> list[str]:
        return [UPSCALE_MODEL] if self.available else []

    def upscale(self, source: Path, destination: Path, model: str) -> dict[str, object]:
        source = Path(source).resolve()
        destination = Path(destination).resolve()
        self.upscale_calls.append((source, destination, model))
        if self.fail:
            raise AssetEngineError("postprocess_failed", "Synthetic adapter failure.", "postprocess")
        destination.write_bytes(_png_bytes(1024, 1024, b"\x50\xa0\xe0"))
        source_metadata = validate_png(source, 256, 256)
        output_metadata = validate_png(destination, 1024, 1024)
        source_metadata["path"] = str(source)
        output_metadata["path"] = str(destination)
        return {
            "type": "anime_upscale",
            "model": model,
            "scale": 4,
            "source": source_metadata,
            "output": output_metadata,
        }


class AnimeVerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temporary_root = Path(self.temporary_directory.name)
        self.assertTrue(BRIEF_PATH.is_file(), "fixed anime brief fixture is required")
        self.assertTrue(MODEL_PATH.is_file(), "isolated approved model fixture is required")
        self.brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
        self.model_fixture = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        self.registry_root = self.temporary_root / "registry"
        shutil.copytree(ROOT / "profiles", self.registry_root)
        overlay_model = self.registry_root / "models" / MODEL_PATH.name
        overlay_model.write_text(json.dumps(self.model_fixture), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _engine(
        self,
        output_name: str,
        *,
        postprocessor: FakePostprocessor | None = None,
    ) -> tuple[AssetRunEngine, FakeBackendRunner, FakePostprocessor]:
        runner = FakeBackendRunner()
        adapter = postprocessor or FakePostprocessor()
        engine = AssetRunEngine(
            ProfileRegistry(self.registry_root),
            RunStore(self.temporary_root / output_name),
            runner,
            lambda: {"available_backends": ["webui"], "cuda": True},
            adapter,
        )
        return engine, runner, adapter

    def _start(self, engine: AssetRunEngine, *, max_rounds: int = 2) -> str:
        started = engine.start_run({
            "profile": self.brief["profile"],
            "style": self.brief["style"],
            "subtype": self.brief["subtype"],
            "intent": self.brief["user_request"],
            "constraints": self.brief["constraints"],
            "model_choice": MODEL_ID,
            "backend": "webui",
            "upscale_policy": "auto",
            "max_rounds": max_rounds,
        })
        self.assertEqual(started["state"], "created")
        self.assertEqual(started["max_rounds"], max_rounds)
        return str(started["run_id"])

    def _plan(self, *, max_rounds: int, parameters: dict[str, object]) -> dict[str, object]:
        return {
            "profile": self.brief["profile"],
            "style": self.brief["style"],
            "intent": self.brief["user_request"],
            "positive_prompt": (
                "lone engineer overlooking a neon coastal city at dawn, anime key visual"
            ),
            "negative_prompt": "generated text, watermark, extra limbs, broken hands",
            "constraints": {**self.brief["constraints"], "width": 256, "height": 256},
            "model_choice": MODEL_ID,
            "backend": "webui",
            "parameters": parameters,
            "max_rounds": max_rounds,
            "upscale_policy": "auto",
        }

    def _generate(
        self,
        engine: AssetRunEngine,
        run_id: str,
        *,
        action: str,
        key: str,
        max_rounds: int,
        summary: str,
    ) -> tuple[dict[str, object], object]:
        parameters = (
            {"mode": "txt2img", "scheduler": "euler"}
            if action == "initial"
            else {"steps": 12, "guidance_scale": 6.5}
        )
        return engine.generate_round({
            "run_id": run_id,
            "idempotency_key": key,
            "action": action,
            "edit_mode": "txt2img",
            "seed": 42,
            "change_summary": summary,
            "plan": self._plan(max_rounds=max_rounds, parameters=parameters),
        })

    def _review(
        self,
        engine: AssetRunEngine,
        run_id: str,
        round_number: int,
        *,
        detail_quality: int,
        next_action: str,
    ) -> dict[str, object]:
        manifest = engine.get_run({"run_id": run_id})
        rubric = manifest["request"]["merged_profile"]["rubric"]
        scores = {name: 4 for name in rubric}
        scores["detail_quality"] = detail_quality
        return engine.record_review({
            "run_id": run_id,
            "round_number": round_number,
            "review": {
                "scores": scores,
                "hard_failures": [],
                "critique": (
                    "Small engineering details are indistinct in the retained preview."
                    if detail_quality == 2
                    else "Engineering details, anatomy, line work, and composition are coherent."
                ),
                "constraint_results": {
                    "aspect_ratio": {
                        "status": "pass",
                        "observation": "The retained image uses the confirmed wide composition.",
                    },
                    "generated_text": {
                        "status": "pass",
                        "observation": "No generated text is visible in the retained image.",
                    },
                },
                "next_action": next_action,
            },
        })

    def test_fixture_overlay_never_enters_production_catalog_or_runtime_data(self) -> None:
        self.assertEqual(self.brief, {
            "user_request": "Create an anime key visual of a lone engineer overlooking a neon coastal city at dawn.",
            "profile": "standalone-illustration",
            "style": "anime",
            "subtype": "character",
            "constraints": {"aspect_ratio": "16:9", "generated_text": False},
            "max_rounds": 2,
        })
        self.assertEqual(set(self.model_fixture), MODEL_REQUIRED)
        self.assertEqual(self.model_fixture["id"], MODEL_ID)
        self.assertEqual(self.model_fixture["source"], "test-fixture")
        self.assertEqual(self.model_fixture["license_id"], "test-only")
        self.assertEqual(self.model_fixture["license_status"], "approved")
        self.assertEqual(self.model_fixture["backends"], ["webui"])
        self.assertIs(self.model_fixture["known_local"], True)
        self.assertIs(self.model_fixture["enabled"], True)

        production_catalog = ProfileRegistry(ROOT / "profiles").list_catalog()
        self.assertNotIn(MODEL_ID, production_catalog["models"])
        self.assertIn(MODEL_ID, ProfileRegistry(self.registry_root).list_catalog()["models"])
        publishable_roots = (ROOT / "profiles", ROOT / "scripts", ROOT / "skills")
        publishable_files = [
            path
            for directory in publishable_roots
            for path in directory.rglob("*")
            if path.is_file() and path.suffix in {".json", ".md", ".py"}
        ]
        publishable_files.extend(ROOT / name for name in ("README.md", "CHANGELOG.md"))
        leaked = [
            str(path.relative_to(ROOT))
            for path in publishable_files
            if MODEL_ID in path.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertEqual(leaked, [])

    def test_two_round_anime_loop_records_evidence_and_exact_upscaled_final(self) -> None:
        engine, runner, adapter = self._engine("accepted-output")
        catalog_copy = engine.registry.list_catalog()
        catalog_copy["models"][MODEL_ID]["license_id"] = "mutated-copy"
        run_id = self._start(engine)
        self.assertEqual(engine.get_run({"run_id": run_id})["recoverable_next_actions"], ["generate_round"])

        initial_summary = "Preserve: confirmed brief. Change: create the initial candidate."
        initial, initial_preview = self._generate(
            engine,
            run_id,
            action="initial",
            key="anime-initial-42",
            max_rounds=2,
            summary=initial_summary,
        )
        self.assertEqual(initial["state"], "generated")
        self.assertEqual(initial["recoverable_next_actions"], ["record_review"])
        self.assertIsNotNone(initial_preview.path)
        self.assertLessEqual(len(base64.b64decode(initial_preview.data_base64)), MAX_PREVIEW_BYTES)
        first_review = self._review(
            engine,
            run_id,
            1,
            detail_quality=2,
            next_action="refine",
        )
        self.assertEqual(first_review["state"], "reviewed")
        self.assertEqual(
            first_review["recoverable_next_actions"],
            ["generate_round:refine", "generate_round:explore"],
        )

        refine_summary = (
            "Preserve: composition, subject, and seed. Change: improve small engineering details."
        )
        refined, refined_preview = self._generate(
            engine,
            run_id,
            action="refine",
            key="anime-refine-42",
            max_rounds=2,
            summary=refine_summary,
        )
        self.assertEqual(refined["state"], "generated")
        self.assertEqual(refined["recoverable_next_actions"], ["record_review"])
        self.assertIsNotNone(refined_preview.path)
        self.assertLessEqual(len(base64.b64decode(refined_preview.data_base64)), MAX_PREVIEW_BYTES)
        second_review = self._review(
            engine,
            run_id,
            2,
            detail_quality=4,
            next_action="finalize",
        )
        self.assertEqual(second_review["state"], "reviewed")
        self.assertEqual(second_review["recoverable_next_actions"], ["finalize_run"])

        finalized = engine.finalize_run({
            "run_id": run_id,
            "round_number": 2,
            "summary": "Round 2 nominated: detail issue resolved while preserving the approved composition.",
            "postprocess": {"type": "anime_upscale", "model": UPSCALE_MODEL},
        })
        manifest = engine.get_run({"run_id": run_id})
        run_root = Path(engine.store.output_root) / "runs" / run_id

        self.assertEqual(finalized["state"], "finalized")
        self.assertEqual(finalized["recoverable_next_actions"], ["get_run", "cleanup_run"])
        self.assertEqual(manifest["last_stable_state"], "finalized")
        self.assertEqual(len(manifest["rounds"]), 2)
        self.assertEqual(len(manifest["attempts"]), 2)
        self.assertEqual(len(manifest["reviews"]), 2)
        self.assertEqual([value["seed"] for value in manifest["rounds"]], [42, 42])
        self.assertEqual([value["action"] for value in manifest["rounds"]], ["initial", "refine"])
        self.assertEqual(
            [value["change_summary"] for value in manifest["rounds"]],
            [initial_summary, refine_summary],
        )
        self.assertEqual(
            [value["change_summary"] for value in manifest["attempts"]],
            [initial_summary, refine_summary],
        )
        self.assertEqual(manifest["reviews"][0]["scores"]["detail_quality"], 2)
        critical = {
            name
            for name, specification in manifest["request"]["merged_profile"]["rubric"].items()
            if specification.get("critical") is True
        }
        self.assertTrue(all(manifest["reviews"][1]["scores"][name] >= 3 for name in critical))
        self.assertEqual(manifest["reviews"][1]["hard_failures"], [])

        registry_metadata = {
            "profile": {"id": "standalone-illustration", "schema_version": 1},
            "style": {"id": "anime", "schema_version": 1},
            "model": {
                "id": MODEL_ID,
                "source": "test-fixture",
                "license_id": "test-only",
                "license_url": None,
                "license_status": "approved",
            },
        }
        self.assertEqual([value["registry_metadata"] for value in manifest["rounds"]], [registry_metadata] * 2)
        self.assertEqual(manifest["request"]["model_record"], self.model_fixture)
        self.assertEqual(
            [value["generation_plan"]["parameters"] for value in manifest["rounds"]],
            [{"mode": "txt2img", "scheduler": "euler"}, {"steps": 12, "guidance_scale": 6.5}],
        )

        for index, round_value in enumerate(manifest["rounds"], start=1):
            expected_image = f"round-{index:02d}.png"
            expected_preview = f"round-{index:02d}-preview.jpg"
            self.assertEqual(round_value["image"]["path"], expected_image)
            self.assertEqual(round_value["image"]["sha256"], ROUND_HASHES[index - 1])
            self.assertEqual(round_value["preview"]["path"], expected_preview)
            self.assertEqual(
                round_value["preview"]["sha256"],
                hashlib.sha256((run_root / expected_preview).read_bytes()).hexdigest(),
            )
            self.assertLessEqual((run_root / expected_preview).stat().st_size, MAX_PREVIEW_BYTES)
            validate_png(run_root / expected_image, 256, 256)

        self.assertEqual(len(runner.calls), 2)
        self.assertEqual([call[call.index("--seed") + 1] for call in runner.calls], ["42", "42"])
        self.assertEqual([call[call.index("--model") + 1] for call in runner.calls], [MODEL_ID, MODEL_ID])
        self.assertEqual(len(adapter.upscale_calls), 1)
        self.assertEqual(manifest["final"]["round_number"], 2)
        self.assertEqual(manifest["final"]["quality_status"], "accepted")
        self.assertEqual(manifest["final"]["image"]["path"], "final.png")
        self.assertEqual(manifest["final"]["image"]["sha256"], ROUND_HASHES[1])
        self.assertEqual(manifest["final"]["path"], "final-upscaled.png")
        self.assertEqual(manifest["final"]["postprocess"], {
            "type": "anime_upscale",
            "status": "completed",
            "model": UPSCALE_MODEL,
            "scale": 4,
            "source": {
                "path": "final.png",
                "width": 256,
                "height": 256,
                "mime_type": "image/png",
                "sha256": ROUND_HASHES[1],
            },
            "output": {
                "path": "final-upscaled.png",
                "width": 1024,
                "height": 1024,
                "mime_type": "image/png",
                "sha256": UPSCALED_HASH,
            },
        })
        self.assertEqual(hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest(), ROUND_HASHES[1])
        self.assertEqual(
            hashlib.sha256((run_root / "final-upscaled.png").read_bytes()).hexdigest(),
            UPSCALED_HASH,
        )
        self.assertEqual(finalized["full_image_path"], str((run_root / "final-upscaled.png").resolve()))

    def test_postprocess_warning_retains_original_without_regeneration(self) -> None:
        cases = (("unavailable", False, False), ("failed", True, True))
        for expected_status, available, fail in cases:
            with self.subTest(expected_status=expected_status):
                adapter = FakePostprocessor(available=available, fail=fail)
                engine, runner, _ = self._engine(f"warning-{expected_status}", postprocessor=adapter)
                run_id = self._start(engine, max_rounds=1)
                self._generate(
                    engine,
                    run_id,
                    action="initial",
                    key=f"warning-{expected_status}-42",
                    max_rounds=1,
                    summary="Preserve: confirmed brief. Change: create one candidate.",
                )
                self._review(engine, run_id, 1, detail_quality=4, next_action="finalize")
                backend_calls_before_finalize = len(runner.calls)

                finalized = engine.finalize_run({
                    "run_id": run_id,
                    "round_number": 1,
                    "summary": "Retain the reviewed original if optional upscaling cannot complete.",
                    "postprocess": {"type": "anime_upscale", "model": UPSCALE_MODEL},
                })
                run_root = Path(engine.store.output_root) / "runs" / run_id

                self.assertEqual(len(runner.calls), backend_calls_before_finalize)
                self.assertEqual(len(runner.calls), 1)
                self.assertEqual(finalized["final"]["quality_status"], "accepted")
                self.assertEqual(finalized["final"]["path"], "final.png")
                self.assertEqual(finalized["final"]["image"]["sha256"], ROUND_HASHES[0])
                self.assertEqual(finalized["final"]["postprocess"]["status"], expected_status)
                self.assertIn(f"postprocess_{expected_status}", finalized["warnings"])
                self.assertEqual(
                    hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest(),
                    ROUND_HASHES[0],
                )
                self.assertFalse((run_root / "final-upscaled.png").exists())
                self.assertFalse((run_root / "final-upscaled.pending.png").exists())


if __name__ == "__main__":
    unittest.main()
