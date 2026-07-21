from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.artifacts import sha256_file  # noqa: E402
from local_gpu_imagegen.engine import AssetRunEngine  # noqa: E402
from local_gpu_imagegen.profile_registry import ProfileRegistry  # noqa: E402
from local_gpu_imagegen.prompt_compilers import PromptCompilerRegistry  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402
from tests.test_asset_run_engine import FakeCatalog, FakeRouter  # noqa: E402
from tests.test_anime_vertical_slice import (  # noqa: E402
    FakeBackendRunner,
    FakePostprocessor,
    MODEL_ID,
    install_fixture_registry,
)


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "acceptance" / "v1-briefs.json"
ASPECT_DIMENSIONS = {
    "16:9": (512, 288),
    "4:3": (512, 384),
    "3:1": (768, 256),
}
REVISION_IDS = {"illustration-character", "presentation-cover", "ui-hero"}


class ProfileAcceptanceMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temporary_root = Path(self.temporary_directory.name)
        self.registry_root = self.temporary_root / "registry"
        install_fixture_registry(self.registry_root)
        self.briefs = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _engine(self, fixture_id: str) -> tuple[AssetRunEngine, FakeBackendRunner]:
        runner = FakeBackendRunner()
        catalog = FakeCatalog()
        router = FakeRouter(catalog)
        engine = AssetRunEngine(
            ProfileRegistry(self.registry_root),
            RunStore(self.temporary_root / fixture_id),
            runner,
            lambda: {"available_backends": ["webui"], "cuda": True},
            FakePostprocessor(available=False),
            catalog=catalog,
            router=router,
            compilers=PromptCompilerRegistry(),
        )
        return engine, runner

    @staticmethod
    def _constraints(brief: dict[str, object]) -> dict[str, object]:
        width, height = ASPECT_DIMENSIONS[str(brief["aspect_ratio"])]
        return {
            "aspect_ratio": brief["aspect_ratio"],
            "generated_text": False,
            "width": width,
            "height": height,
        }

    def _start(self, engine: AssetRunEngine, brief: dict[str, object], max_rounds: int) -> str:
        arguments: dict[str, object] = {
            "profile": brief["profile"],
            "style": brief["style"],
            "subtype": brief["subtype"],
            "intent": brief["brief"],
            "constraints": self._constraints(brief),
            "model_choice": MODEL_ID,
            "backend": "webui",
            "upscale_policy": "off",
            "max_rounds": max_rounds,
            "authorization_scope": "private",
        }
        route = engine.router.issue(arguments)
        arguments["route_token"] = route["route_token"]
        result = engine.start_run(arguments)
        return str(result["run_id"])

    def _plan(
        self,
        brief: dict[str, object],
        *,
        max_rounds: int,
        parameters: dict[str, object],
        route: dict[str, object],
    ) -> dict[str, object]:
        return {
            "profile": brief["profile"],
            "style": brief["style"],
            "intent": brief["brief"],
            "positive_prompt": brief["brief"],
            "negative_prompt": "generated text, watermark, malformed subject",
            "constraints": self._constraints(brief),
            "model_choice": MODEL_ID,
            "backend": "webui",
            "authorization_scope": route["authorization_scope"],
            "route_token": route["route_token"],
            "endpoint_identity": route["endpoint_identity"],
            "model_identity_token": route["identity_token"],
            "identity_strength": route["identity_strength"],
            "workflow_template_id": route["workflow_template_id"],
            "workflow_template_version": route["workflow_template_version"],
            "prompt_compiler_id": route["prompt_compiler_id"],
            "prompt_compiler_version": route["prompt_compiler_version"],
            "parameters": parameters,
            "max_rounds": max_rounds,
            "upscale_policy": "off",
        }

    def _generate(
        self,
        engine: AssetRunEngine,
        brief: dict[str, object],
        run_id: str,
        *,
        edit_mode: str,
        mask_id: str | None = None,
    ) -> tuple[dict[str, object], object]:
        route = engine.get_run({"run_id": run_id})["request"]["route"]
        arguments: dict[str, object] = {
            "run_id": run_id,
            "idempotency_key": f"{brief['id']}-{edit_mode}-1",
            "action": "initial",
            "edit_mode": edit_mode,
            "seed": 42,
            "change_summary": "Create the contract candidate.",
            "plan": self._plan(
                brief,
                max_rounds=1 if edit_mode != "txt2img" else 2,
                parameters={},
                route=route,
            ),
        }
        if mask_id is not None:
            arguments["mask_id"] = mask_id
        return engine.generate_round(arguments)

    def _review(
        self,
        engine: AssetRunEngine,
        run_id: str,
        *,
        preservation_targets: list[str] | None = None,
    ) -> dict[str, object]:
        manifest = engine.get_run({"run_id": run_id})
        rubric = manifest["request"]["merged_profile"]["rubric"]
        review: dict[str, object] = {
            "scores": {name: 4 for name in rubric},
            "hard_failures": [],
            "critique": "Model-free fixture evidence satisfies the deterministic contract.",
            "constraint_results": {
                name: {"status": "pass", "observation": f"Fixture retained {name}."}
                for name in manifest["request"]["constraints"]
            },
            "next_action": "finalize",
        }
        if preservation_targets is not None:
            review["preservation_results"] = [
                {"target": target, "status": "preserved", "observation": "Retained in fixture output."}
                for target in preservation_targets
            ]
        return engine.record_review({"run_id": run_id, "round_number": 1, "review": review})

    def _assert_round_evidence(
        self,
        engine: AssetRunEngine,
        run_id: str,
        preview: object,
    ) -> dict[str, object]:
        manifest = engine.get_run({"run_id": run_id})
        round_value = manifest["rounds"][0]
        run_root = engine.store.run_root(run_id)
        image = round_value["image"]
        preview_record = round_value["preview"]
        preview_bytes = base64.b64decode(preview.data_base64, validate=True)

        self.assertEqual(image["sha256"], sha256_file(run_root / image["path"]))
        self.assertEqual(preview_record["sha256"], hashlib.sha256(preview_bytes).hexdigest())
        self.assertEqual(preview.mime_type, "image/jpeg")
        self.assertEqual(round_value["registry_metadata"]["profile"]["id"], manifest["request"]["profile"])
        expected_style = manifest["request"]["style"]
        stored_style = round_value["registry_metadata"]["style"]
        self.assertEqual(stored_style["id"] if stored_style else None, expected_style)
        return manifest

    def test_fixture_contains_exactly_nine_stable_briefs_and_three_revisions(self) -> None:
        self.assertEqual(len(self.briefs), 9)
        self.assertEqual({brief["id"] for brief in self.briefs}, {
            "illustration-character",
            "illustration-environment",
            "illustration-wallpaper",
            "presentation-cover",
            "presentation-section",
            "presentation-background",
            "ui-hero",
            "ui-section",
            "ui-background",
        })
        self.assertEqual({brief["id"] for brief in self.briefs if "revision" in brief}, REVISION_IDS)

    def test_all_briefs_and_revisions_preserve_the_deterministic_contract(self) -> None:
        for brief in self.briefs:
            with self.subTest(fixture=brief["id"]):
                engine, runner = self._engine(str(brief["id"]))
                parent_id = self._start(engine, brief, max_rounds=2)
                _, preview = self._generate(engine, brief, parent_id, edit_mode="txt2img")
                self.assertIsNotNone(preview)
                self._review(engine, parent_id)
                finalized = engine.finalize_run({
                    "run_id": parent_id,
                    "round_number": 1,
                    "summary": "Publish the reviewed model-free fixture candidate.",
                })
                parent = self._assert_round_evidence(engine, parent_id, preview)
                self.assertEqual(parent["request"]["profile"], brief["profile"])
                self.assertEqual(parent["request"]["style"], brief["style"])
                self.assertEqual(parent["request"]["subtype"], brief["subtype"])
                self.assertEqual(parent["request"]["constraints"]["aspect_ratio"], brief["aspect_ratio"])
                self.assertEqual(finalized["final"]["quality_status"], "accepted")
                self.assertEqual(len(runner.calls), 1)

                if "revision" not in brief:
                    continue
                parent_root = engine.store.run_root(parent_id)
                parent_manifest_path = parent_root / "manifest.json"
                parent_manifest_before = parent_manifest_path.read_bytes()
                parent_hash_before = parent["rounds"][0]["image"]["sha256"]
                revision = brief["revision"]
                preserve_targets = list(revision["preserve"])
                edit_mode = "inpaint" if brief["id"] == "ui-hero" else "img2img"
                branch_arguments: dict[str, object] = {
                    "parent_run_id": parent_id,
                    "parent_round": 1,
                    "contract": {
                        "preserve": [
                            {"target": target, "strength": "hard"}
                            for target in preserve_targets
                        ],
                        "change": [revision["change"]],
                    },
                    "max_rounds": 1,
                    "edit_mode": edit_mode,
                    "denoising_strength": 0.25,
                }
                child = engine.branch_run(branch_arguments)
                child_id = str(child["run_id"])
                self.assertEqual(len(child["revision"]["contract"]["preserve"]), 2)
                self.assertTrue(all(
                    item["strength"] == "hard"
                    for item in child["revision"]["contract"]["preserve"]
                ))
                self.assertEqual(child["revision"]["contract"]["change"], [revision["change"]])

                mask_id = None
                if edit_mode == "inpaint":
                    prepared, overlay = engine.prepare_mask({
                        "run_id": child_id,
                        "geometry": [
                            {"type": "rectangle", "x": 0.1, "y": 0.1, "width": 0.25, "height": 0.25},
                        ],
                        "feather_pixels": 0,
                    })
                    self.assertIsNotNone(overlay)
                    confirmed = engine.confirm_mask({"run_id": child_id, "mask_id": prepared["mask_id"]})
                    self.assertIs(confirmed["confirmed"], True)
                    mask_id = str(prepared["mask_id"])
                _, child_preview = self._generate(
                    engine,
                    brief,
                    child_id,
                    edit_mode=edit_mode,
                    mask_id=mask_id,
                )
                self._review(engine, child_id, preservation_targets=preserve_targets)
                child_finalized = engine.finalize_run({
                    "run_id": child_id,
                    "round_number": 1,
                    "summary": "Publish the preserved model-free revision fixture.",
                })
                self._assert_round_evidence(engine, child_id, child_preview)
                self.assertEqual(child_finalized["final"]["quality_status"], "accepted")
                self.assertEqual(parent_manifest_path.read_bytes(), parent_manifest_before)
                self.assertEqual(sha256_file(parent_root / "round-01.png"), parent_hash_before)
                self.assertEqual(len(runner.calls), 2)


if __name__ == "__main__":
    unittest.main()
