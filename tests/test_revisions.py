from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ArtifactError, StateError, ValidationError  # noqa: E402
from local_gpu_imagegen.revisions import RevisionService, validate_revision_contract  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402


VALID_CONTRACT = {
    "preserve": [
        {"target": "subject identity", "strength": "hard"},
        {"target": "composition", "strength": "hard"},
        {"target": "palette", "strength": "soft"},
    ],
    "change": ["simplify the background"],
}


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _png_bytes() -> bytes:
    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    scanlines = b"\x00\x20\x40\x60\x20\x40\x60\x00\x20\x40\x60\x20\x40\x60"
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


class RevisionContractTests(unittest.TestCase):
    def test_contract_requires_nonempty_change_list(self) -> None:
        with self.assertRaisesRegex(ValidationError, "invalid_revision_change"):
            validate_revision_contract({"preserve": [], "change": []})

    def test_contract_rejects_unknown_preserve_strength(self) -> None:
        for strength in ("medium", []):
            with self.subTest(strength=strength), self.assertRaisesRegex(
                ValidationError,
                "invalid_preserve_strength",
            ):
                validate_revision_contract({
                    "preserve": [{"target": "face", "strength": strength}],
                    "change": ["lighting"],
                })

    def test_contract_rejects_duplicate_targets_and_changes_after_casefold(self) -> None:
        cases = (
            {
                "preserve": [
                    {"target": "Face", "strength": "hard"},
                    {"target": " face ", "strength": "soft"},
                ],
                "change": ["lighting"],
            },
            {"preserve": [], "change": ["Lighting", " lighting "]},
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError,
                "duplicate_revision_item",
            ):
                validate_revision_contract(value)

    def test_contract_returns_a_normalized_deep_copy(self) -> None:
        value = {
            "preserve": [{"target": "  Subject Identity  ", "strength": "hard"}],
            "change": ["  Calm the lighting  "],
        }
        normalized = validate_revision_contract(value)
        value["preserve"][0]["target"] = "mutated"

        self.assertEqual(normalized, {
            "preserve": [{"target": "Subject Identity", "strength": "hard"}],
            "change": ["Calm the lighting"],
        })


class RevisionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temporary_directory.name) / "output"
        self.store = RunStore(self.output_root)
        self.service = RevisionService(self.store)
        self.parent = self.store.create({
            "profile": "standalone-illustration",
            "style": "anime",
            "subtype": "character",
            "intent": "A coastal engineer at dawn.",
            "constraints": {"aspect_ratio": "16:9"},
            "model_choice": "test/approved-anime",
            "model_record": {"id": "test/approved-anime"},
            "backend": "webui",
            "available_backends": ["webui"],
            "upscale_policy": "auto",
            "max_rounds": 3,
            "merged_profile": {
                "rubric": {"intent_adherence": {"weight": 1, "critical": True}},
                "hard_failures": [],
                "refine_mutable": ["steps"],
                "explore_mutable": ["seed"],
            },
        })
        self.parent_id = str(self.parent["run_id"])
        self.parent_root = self.output_root / "runs" / self.parent_id
        self.source_bytes = _png_bytes()
        self.source_path = self.parent_root / "round-01.png"
        self.source_path.write_bytes(self.source_bytes)
        self.source_hash = hashlib.sha256(self.source_bytes).hexdigest()

        def complete_parent(manifest: dict[str, object]) -> None:
            manifest["rounds"].append({
                "round_number": 1,
                "status": "generated",
                "seed": 42,
                "image": {
                    "path": "round-01.png",
                    "sha256": self.source_hash,
                    "width": 2,
                    "height": 2,
                    "mime_type": "image/png",
                },
            })
            manifest["reviews"].append({
                "round_number": 1,
                "scores": {"intent_adherence": 4},
                "hard_failures": [],
                "critique": "The parent candidate is suitable for revision.",
                "constraint_results": {
                    "aspect_ratio": {"status": "pass", "observation": "Wide ratio retained."},
                },
                "next_action": "finalize",
            })
            manifest["state"] = "reviewed"
            manifest["last_stable_state"] = "reviewed"

        self.store.update(self.parent_id, complete_parent)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def branch_arguments(self, contract: dict[str, object] | None = None, **updates: object) -> dict[str, object]:
        value: dict[str, object] = {
            "parent_run_id": self.parent_id,
            "parent_round": 1,
            "contract": contract or VALID_CONTRACT,
            "max_rounds": 2,
            "edit_mode": "img2img",
            "denoising_strength": 0.25,
        }
        value.update(updates)
        return value

    def test_branch_records_lineage_without_mutating_parent(self) -> None:
        parent_manifest_path = self.parent_root / "manifest.json"
        manifest_before = parent_manifest_path.read_bytes()
        source_before = self.source_path.read_bytes()

        child = self.service.branch(self.branch_arguments())

        self.assertEqual(parent_manifest_path.read_bytes(), manifest_before)
        self.assertEqual(self.source_path.read_bytes(), source_before)
        self.assertEqual(child["parent"], {
            "run_id": self.parent_id,
            "round": 1,
            "image_sha256": self.source_hash,
        })
        self.assertEqual(child["request"]["max_rounds"], 2)
        self.assertEqual(child["revision"]["contract"], VALID_CONTRACT)
        self.assertEqual(child["revision"]["edit_mode"], "img2img")
        self.assertEqual(child["revision"]["denoising_strength"], 0.25)
        child_source = self.output_root / "runs" / child["run_id"] / "parent-source.png"
        self.assertEqual(child_source.read_bytes(), source_before)
        self.assertEqual(child["revision"]["source_image"]["path"], "parent-source.png")
        self.assertEqual(child["revision"]["source_image"]["sha256"], self.source_hash)

    def test_branch_requires_reviewed_successful_parent_round(self) -> None:
        with self.assertRaisesRegex(StateError, "revision_parent_not_reviewed"):
            self.service.branch(self.branch_arguments(parent_round=2))

    def test_branch_validates_edit_mode_strength_and_round_budget(self) -> None:
        cases = (
            ({"edit_mode": "erase"}, "invalid_revision_edit_mode"),
            ({"edit_mode": []}, "invalid_revision_edit_mode"),
            ({"edit_mode": "prompt-refine", "denoising_strength": 0.2}, "invalid_denoising_strength"),
            ({"edit_mode": "img2img", "denoising_strength": 0}, "invalid_denoising_strength"),
            ({"edit_mode": "inpaint", "denoising_strength": 1.1}, "invalid_denoising_strength"),
            ({"max_rounds": 4}, "invalid_round_budget"),
        )
        for updates, error_code in cases:
            with self.subTest(updates=updates), self.assertRaisesRegex(ValidationError, error_code):
                self.service.branch(self.branch_arguments(**updates))

    def test_branch_rejects_changed_parent_image_without_leaving_child(self) -> None:
        self.source_path.write_bytes(_png_bytes() + b"changed")

        with self.assertRaisesRegex(ArtifactError, "revision_parent_image_changed"):
            self.service.branch(self.branch_arguments())

        run_directories = [path for path in (self.output_root / "runs").iterdir() if path.is_dir()]
        self.assertEqual(run_directories, [self.parent_root])

    def _generated_child(self) -> tuple[str, dict[str, object]]:
        child = self.service.branch(self.branch_arguments())
        child_id = str(child["run_id"])

        def add_round(manifest: dict[str, object]) -> None:
            manifest["rounds"].append({
                "round_number": 1,
                "status": "generated",
                "seed": 42,
                "image": {
                    "path": "round-01.png",
                    "sha256": self.source_hash,
                    "width": 2,
                    "height": 2,
                },
            })
            manifest["state"] = "generated"
            manifest["last_stable_state"] = "generated"

        return child_id, self.store.update(child_id, add_round)

    def _review(self, preservation_results: list[dict[str, str]], hard_failures: list[str]) -> dict[str, object]:
        return {
            "scores": {"intent_adherence": 4},
            "hard_failures": hard_failures,
            "critique": "Revision inspected against the confirmed preserve/change contract.",
            "constraint_results": {
                "aspect_ratio": {"status": "pass", "observation": "Wide ratio retained."},
            },
            "next_action": "finalize",
            "preservation_results": preservation_results,
        }

    def test_child_review_requires_one_result_per_preserve_target(self) -> None:
        child_id, _ = self._generated_child()
        with self.assertRaisesRegex(ValidationError, "invalid_preservation_results"):
            self.store.record_review(child_id, 1, self._review([], []))

    def test_child_review_rejects_non_string_hard_failures_structurally(self) -> None:
        child_id, _ = self._generated_child()
        results = [
            {"target": item["target"], "status": "preserved", "observation": "Retained."}
            for item in VALID_CONTRACT["preserve"]
        ]
        with self.assertRaisesRegex(ValidationError, "invalid_hard_failures"):
            self.store.record_review(child_id, 1, self._review(results, [{}]))

    def test_changed_hard_target_requires_registered_dynamic_failure(self) -> None:
        child_id, _ = self._generated_child()
        results = [
            {"target": "subject identity", "status": "changed", "observation": "Face changed."},
            {"target": "composition", "status": "preserved", "observation": "Layout matches."},
            {"target": "palette", "status": "preserved", "observation": "Palette matches."},
        ]
        with self.assertRaisesRegex(ValidationError, "inconsistent_preservation_results"):
            self.store.record_review(child_id, 1, self._review(results, []))

        stored = self.store.record_review(
            child_id,
            1,
            self._review(results, ["hard_preserve_violation:subject identity"]),
        )
        self.assertEqual(stored["reviews"][0]["preservation_results"], results)
        finalized = self.store.finalize(child_id, 1, "Retain for user inspection.")
        self.assertEqual(finalized["final"]["quality_status"], "needs_user_review")

    def test_uncertain_preservation_cannot_be_accepted_automatically(self) -> None:
        child_id, _ = self._generated_child()
        results = [
            {"target": "subject identity", "status": "uncertain", "observation": "Face is too small."},
            {"target": "composition", "status": "preserved", "observation": "Layout matches."},
            {"target": "palette", "status": "preserved", "observation": "Palette matches."},
        ]
        self.store.record_review(child_id, 1, self._review(results, []))

        finalized = self.store.finalize(child_id, 1, "Return for explicit user review.")

        self.assertEqual(finalized["final"]["quality_status"], "needs_user_review")

    def test_preserved_targets_allow_normal_eligibility(self) -> None:
        child_id, _ = self._generated_child()
        results = [
            {"target": item["target"], "status": "preserved", "observation": "Retained as requested."}
            for item in VALID_CONTRACT["preserve"]
        ]
        self.store.record_review(child_id, 1, self._review(results, []))

        finalized = self.store.finalize(child_id, 1, "Accepted revision.")

        self.assertEqual(finalized["final"]["quality_status"], "accepted")


if __name__ == "__main__":
    unittest.main()
