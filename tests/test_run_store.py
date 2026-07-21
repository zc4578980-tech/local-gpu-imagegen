from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.artifacts import ensure_within, sha256_file  # noqa: E402
from local_gpu_imagegen.errors import (  # noqa: E402
    ArtifactError,
    AssetEngineError,
    ConflictError,
    StateError,
    ValidationError,
)
from local_gpu_imagegen.run_store import AttemptHandle, RunStore, request_hash  # noqa: E402


INITIAL = {
    "action": "initial",
    "seed": 42,
    "plan": {"positive_prompt": "coast at dawn"},
    "change_summary": "Initial candidate.",
}
REFINE = {
    "action": "refine",
    "seed": 42,
    "plan": {"positive_prompt": "coast at dawn, cleaner detail"},
    "change_summary": "Improve visible detail.",
}


def visual_checks(*, limb_status: str = "pass") -> dict[str, object]:
    return {
        "full_resolution_inspected": True,
        "prominent_human": True,
        "limb_separation": {
            "status": limb_status,
            "observation": "Both leg silhouettes were inspected at full resolution.",
        },
        "feet_and_contact": {
            "status": "pass",
            "observation": "Both feet and contact points are distinct.",
        },
        "hands_and_held_objects": {
            "status": "pass",
            "observation": "Both hands are distinct from held objects.",
        },
        "text_and_watermarks": {
            "status": "pass",
            "observation": "No text or watermark is visible.",
        },
    }


def replace_with_directory_alias(alias: Path, target: Path) -> None:
    shutil.rmtree(alias)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)


class RunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temporary_directory.name) / "output"
        self.store = RunStore(self.output_root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_writes_manifest_under_run_root(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})

        path = self.output_root / "runs" / manifest["run_id"] / "manifest.json"
        self.assertTrue(path.is_file())
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(manifest["last_stable_state"], "created")
        self.assertEqual(
            manifest,
            {
                "schema_version": 1,
                "run_id": manifest["run_id"],
                "manifest_revision": 1,
                "state": "created",
                "last_stable_state": "created",
                "active_attempt": None,
                "parent": None,
                "request": {"profile": "standalone-illustration", "max_rounds": 2},
                "attempts": [],
                "rounds": [],
                "reviews": [],
                "masks": [],
                "warnings": [],
                "final": None,
            },
        )
        self.assertRegex(manifest["run_id"], r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")

    def test_create_rejects_non_json_values_without_an_orphan_run_directory(self) -> None:
        cyclic_request: dict[str, object] = {}
        cyclic_request["self"] = cyclic_request

        for invalid_request in ({"value": {"not-json"}}, cyclic_request):
            with self.subTest(value_type=type(invalid_request["value"]).__name__ if "value" in invalid_request else "cycle"):
                with tempfile.TemporaryDirectory() as directory:
                    output_root = Path(directory) / "output"
                    store = RunStore(output_root)

                    with self.assertRaisesRegex(ArtifactError, "invalid_manifest_json"):
                        store.create(invalid_request)

                    self.assertFalse((output_root / "runs").exists())

    def test_update_is_atomic_and_increments_revision(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})

        updated = self.store.update(manifest["run_id"], lambda value: value.update({"state": "reviewed"}))

        self.assertEqual(updated["manifest_revision"], 2)
        self.assertEqual(updated["state"], "reviewed")
        run_root = self.output_root / "runs" / manifest["run_id"]
        self.assertFalse(list(run_root.glob("*.tmp")))
        self.assertFalse((run_root / ".run.lock").exists())

    def test_update_rejects_non_json_output_without_replacing_manifest(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        manifest_path = run_root / "manifest.json"
        original = manifest_path.read_bytes()

        with self.assertRaisesRegex(ArtifactError, "invalid_manifest_json"):
            self.store.update(manifest["run_id"], lambda value: value.update({"invalid": object()}))

        self.assertEqual(manifest_path.read_bytes(), original)
        self.assertFalse((run_root / "manifest.json.tmp").exists())
        self.assertFalse((run_root / ".run.lock").exists())

    def test_rejects_path_outside_output_root(self) -> None:
        with self.assertRaisesRegex(ArtifactError, "path_outside_output_root"):
            ensure_within(self.output_root, self.output_root.parent / "escape")

    def test_hashes_file_contents(self) -> None:
        path = self.output_root / "asset.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"wave\n")

        self.assertEqual(sha256_file(path), hashlib.sha256(b"wave\n").hexdigest())

    def test_invalid_run_id_is_rejected_before_path_construction(self) -> None:
        with self.assertRaisesRegex(ArtifactError, "invalid_run_id"):
            self.store.get("../../escape")

    def test_corrupt_manifest_is_not_rewritten(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        path = self.output_root / "runs" / manifest["run_id"] / "manifest.json"
        corrupt = "{ not json\n"
        path.write_text(corrupt, encoding="utf-8")

        with self.assertRaisesRegex(ArtifactError, "corrupt_manifest"):
            self.store.update(manifest["run_id"], lambda value: value.update({"state": "reviewed"}))

        self.assertEqual(path.read_text(encoding="utf-8"), corrupt)

    def test_loaded_manifest_must_match_requested_run_id(self) -> None:
        for operation in ("get", "update", "cleanup"):
            with self.subTest(operation=operation):
                manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
                run_root = self.output_root / "runs" / manifest["run_id"]
                path = run_root / "manifest.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value["run_id"] = "20260721T000000Z-000000000000"
                path.write_text(json.dumps(value), encoding="utf-8")

                with self.assertRaisesRegex(ArtifactError, "manifest_run_id_mismatch"):
                    if operation == "get":
                        self.store.get(manifest["run_id"])
                    elif operation == "update":
                        self.store.update(manifest["run_id"], lambda item: item.update({"state": "reviewed"}))
                    else:
                        self.store.cleanup(manifest["run_id"], scope="all", confirmation=manifest["run_id"])

                self.assertTrue(run_root.is_dir())

    def test_internal_run_directory_alias_cannot_read_or_delete_another_run(self) -> None:
        alias_run = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        target_run = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        alias_root = self.output_root / "runs" / alias_run["run_id"]
        target_root = self.output_root / "runs" / target_run["run_id"]
        replace_with_directory_alias(alias_root, target_root)

        with self.assertRaisesRegex(ArtifactError, "unsafe_run_directory"):
            self.store.get(alias_run["run_id"])
        with self.assertRaisesRegex(ArtifactError, "unsafe_run_directory"):
            self.store.cleanup(alias_run["run_id"], scope="all", confirmation=alias_run["run_id"])

        self.assertTrue((target_root / "manifest.json").is_file())

    def test_outside_root_run_directory_alias_is_rejected(self) -> None:
        alias_run = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        alias_root = self.output_root / "runs" / alias_run["run_id"]
        outside = Path(self.temporary_directory.name) / "outside-run"
        outside.mkdir()
        replace_with_directory_alias(alias_root, outside)

        with self.assertRaisesRegex(ArtifactError, "unsafe_run_directory"):
            self.store.get(alias_run["run_id"])

    def test_update_rejects_live_owner_lock_with_matching_process_identity(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        lock_path = self.output_root / "runs" / manifest["run_id"] / ".run.lock"
        lock_path.write_text(
            json.dumps(
                {
                    "owner_pid": os.getpid(),
                    "owner_token": "other-owner",
                    "owner_process_identity": "process-start-a",
                    "created_at": "2026-07-20T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        with patch("local_gpu_imagegen.run_store.process_identity", return_value="process-start-a"):
            with self.assertRaisesRegex(ConflictError, "run_busy"):
                self.store.update(manifest["run_id"], lambda value: value.update({"state": "reviewed"}))

        self.assertTrue(lock_path.is_file())

    def test_update_reclaims_lock_when_live_pid_has_a_different_process_identity(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        lock_path = self.output_root / "runs" / manifest["run_id"] / ".run.lock"
        lock_path.write_text(
            json.dumps(
                {
                    "owner_pid": os.getpid(),
                    "owner_token": "reused-pid-owner",
                    "owner_process_identity": "old-process-start",
                    "created_at": "2026-07-20T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        with patch("local_gpu_imagegen.run_store.process_identity", return_value="new-process-start"):
            updated = self.store.update(manifest["run_id"], lambda value: value.update({"state": "reviewed"}))

        self.assertEqual(updated["state"], "reviewed")
        self.assertFalse(lock_path.exists())

    def test_lock_metadata_is_published_atomically(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        lock_path = run_root / ".run.lock"
        writing_metadata = threading.Event()
        continue_writing = threading.Event()
        original_dump = json.dump
        outcomes: list[tuple[Path, str] | Exception] = []

        def delayed_dump(value: object, stream: object, *args: object, **kwargs: object) -> None:
            if threading.current_thread().name == "first-lock-owner":
                writing_metadata.set()
                continue_writing.wait(timeout=5)
            original_dump(value, stream, *args, **kwargs)

        def acquire_first() -> None:
            try:
                outcomes.append(self.store._acquire_lock(run_root))
            except Exception as error:  # pragma: no cover - asserted through outcomes
                outcomes.append(error)

        with patch("local_gpu_imagegen.run_store.json.dump", side_effect=delayed_dump):
            thread = threading.Thread(target=acquire_first, name="first-lock-owner")
            thread.start()
            self.assertTrue(writing_metadata.wait(timeout=5))
            canonical_was_published_early = lock_path.exists()
            continue_writing.set()
            thread.join(timeout=5)

        self.assertFalse(canonical_was_published_early)
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], tuple)
        acquired_path, owner_token = outcomes[0]
        self.store._release_lock(acquired_path, owner_token)

    def test_update_falls_back_when_hard_links_are_unsupported(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})

        with patch("local_gpu_imagegen.run_store.os.link", side_effect=OSError(errno.EPERM, "not permitted")):
            updated = self.store.update(manifest["run_id"], lambda value: value.update({"state": "reviewed"}))

        self.assertEqual(updated["state"], "reviewed")
        run_root = self.output_root / "runs" / manifest["run_id"]
        self.assertFalse((run_root / ".run.lock").exists())
        self.assertFalse(list(run_root.glob(".run.lock.*.tmp")))

    def test_attempt_acquisition_falls_back_without_losing_ownership(self) -> None:
        manifest = self.store.create({
            "profile": "standalone-illustration",
            "max_rounds": 1,
            "merged_profile": {"rubric": {}, "hard_failures": []},
        })
        store = RunStore(self.output_root)

        with patch("local_gpu_imagegen.run_store.os.link", side_effect=OSError(errno.EPERM, "not permitted")):
            handle = store.begin_attempt(manifest["run_id"], "fallback-attempt", INITIAL)

        lock_path = self.output_root / "runs" / manifest["run_id"] / ".run.lock"
        self.assertTrue(lock_path.is_file())
        store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})
        self.assertFalse(lock_path.exists())

    def test_unexpected_lock_publication_error_is_structured(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})

        with patch("local_gpu_imagegen.run_store.os.link", side_effect=OSError(errno.EIO, "device error")):
            with self.assertRaisesRegex(AssetEngineError, "lock_operation_failed"):
                self.store.update(manifest["run_id"], lambda value: value.update({"state": "reviewed"}))

        run_root = self.output_root / "runs" / manifest["run_id"]
        self.assertFalse((run_root / ".run.lock").exists())
        self.assertFalse(list(run_root.glob(".run.lock.*.tmp")))

    def test_fallback_pending_metadata_prevents_live_lock_theft(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        other = RunStore(self.output_root)
        writing_canonical = threading.Event()
        continue_writing = threading.Event()
        original_dump = json.dump
        outcomes: list[tuple[Path, str] | Exception] = []
        owner_dump_count = 0

        def delayed_dump(value: object, stream: object, *args: object, **kwargs: object) -> None:
            nonlocal owner_dump_count
            if threading.current_thread().name == "fallback-owner":
                owner_dump_count += 1
                if owner_dump_count == 2:
                    writing_canonical.set()
                    continue_writing.wait(timeout=5)
            original_dump(value, stream, *args, **kwargs)

        def acquire_first() -> None:
            try:
                outcomes.append(self.store._acquire_lock(run_root))
            except Exception as error:  # pragma: no cover - asserted through outcomes
                outcomes.append(error)

        unsupported = OSError(errno.EPERM, "not permitted")
        with (
            patch("local_gpu_imagegen.run_store.os.link", side_effect=unsupported),
            patch("local_gpu_imagegen.run_store.json.dump", side_effect=delayed_dump),
        ):
            thread = threading.Thread(target=acquire_first, name="fallback-owner")
            thread.start()
            self.assertTrue(writing_canonical.wait(timeout=5))
            try:
                outcomes.append(other._acquire_lock(run_root))
            except Exception as error:
                outcomes.append(error)
            finally:
                continue_writing.set()
                thread.join(timeout=5)

        acquired = [value for value in outcomes if isinstance(value, tuple)]
        rejected = [value for value in outcomes if isinstance(value, Exception)]
        self.assertEqual(len(acquired), 1)
        self.assertEqual(len(rejected), 1)
        self.assertIsInstance(rejected[0], ConflictError)
        self.assertEqual(rejected[0].code, "run_busy")
        lock_path, owner_token = acquired[0]
        self.store._release_lock(lock_path, owner_token)

    def test_cleanup_rejects_mismatched_confirmation(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})

        with self.assertRaisesRegex(ArtifactError, "cleanup_confirmation_mismatch"):
            self.store.cleanup(manifest["run_id"], scope="all", confirmation="wrong-run")

    def test_cleanup_intermediates_keeps_manifest_and_final_file(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        intermediate = run_root / "rounds" / "round-001.png"
        intermediate.parent.mkdir(parents=True)
        intermediate.write_bytes(b"intermediate")
        final = run_root / "final.png"
        final.write_bytes(b"final")
        self.store.update(manifest["run_id"], lambda value: value.update({
            "state": "finalized",
            "last_stable_state": "finalized",
            "final": {"path": "final.png"},
        }))

        self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])

        self.assertTrue((run_root / "manifest.json").is_file())
        self.assertTrue(final.is_file())
        self.assertFalse(intermediate.exists())

    def test_cleanup_invalid_final_reference_does_not_rewrite_manifest(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        self.store.update(manifest["run_id"], lambda value: value.update({
            "state": "finalized",
            "last_stable_state": "finalized",
            "final": {"path": "../other-run/final.png"},
        }))
        manifest_path = run_root / "manifest.json"
        original = manifest_path.read_bytes()

        with self.assertRaisesRegex(ArtifactError, "path_outside_output_root"):
            self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])

        self.assertEqual(manifest_path.read_bytes(), original)

    def test_cleanup_requires_retained_regular_final_artifact(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        intermediate = run_root / "round-01.png"
        intermediate.write_bytes(b"only retained candidate")
        self.store.update(manifest["run_id"], lambda value: value.update({
            "state": "finalized",
            "last_stable_state": "finalized",
            "final": {"path": "final.png"},
        }))
        manifest_path = run_root / "manifest.json"
        original = manifest_path.read_bytes()

        with self.assertRaisesRegex(ArtifactError, "invalid_final_artifact"):
            self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])

        self.assertEqual(manifest_path.read_bytes(), original)
        self.assertTrue(intermediate.is_file())

    def test_cleanup_rejects_final_metadata_without_a_path(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        intermediate = run_root / "round-01.png"
        intermediate.write_bytes(b"only retained candidate")
        self.store.update(manifest["run_id"], lambda value: value.update({
            "state": "finalized",
            "last_stable_state": "finalized",
            "final": {},
        }))

        with self.assertRaisesRegex(ArtifactError, "invalid_final_artifact"):
            self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])

        self.assertTrue(intermediate.is_file())

    def test_cleanup_failure_stays_pending_without_claiming_completion(self) -> None:
        manifest = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        run_root = self.output_root / "runs" / manifest["run_id"]
        final = run_root / "final.png"
        final.write_bytes(b"published final")
        self.store.update(manifest["run_id"], lambda value: value.update({
            "state": "finalized",
            "last_stable_state": "finalized",
            "final": {"path": "final.png"},
        }))

        with patch.object(self.store, "_remove_intermediates", side_effect=OSError("cleanup failed")):
            with self.assertRaisesRegex(OSError, "cleanup failed"):
                self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])

        pending = self.store.get(manifest["run_id"])
        self.assertIn("intermediate_cleanup", pending)
        self.assertEqual(pending["intermediate_cleanup"]["status"], "pending")
        self.assertNotIn("intermediates_cleaned_at", pending)
        self.assertTrue(final.is_file())

        self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])
        completed = self.store.get(manifest["run_id"])
        self.assertEqual(completed["intermediate_cleanup"]["status"], "completed")
        self.assertIn("intermediates_cleaned_at", completed)


class RunStoreTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(Path(self.temp.name))
        self.manifest = self.store.create({
            "profile": "standalone-illustration",
            "max_rounds": 2,
            "merged_profile": {
                "rubric": {"intent_adherence": {"weight": 1, "critical": True}},
                "hard_failures": ["missing_subject"],
            },
        })

    def write_run_image(
        self,
        *,
        relative_path: str = "round-01.png",
        contents: bytes = b"trusted full image",
    ) -> dict[str, object]:
        path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return {
            "path": relative_path,
            "sha256": sha256_file(path),
            "width": 256,
            "height": 256,
        }

    def complete_initial(self, key: str = "initial-1") -> dict[str, object]:
        handle = self.store.begin_attempt(self.manifest["run_id"], key, INITIAL)
        return self.store.complete_attempt(handle, {
            "seed": 42,
            "image": {"path": "round-01.png", "sha256": "a" * 64, "width": 16, "height": 16},
        })

    def review_value(
        self,
        *,
        next_action: str = "refine",
        limb_status: str = "pass",
    ) -> dict[str, object]:
        return {
            "scores": {"intent_adherence": 3},
            "hard_failures": [],
            "critique": "Intent is present; detail can improve.",
            "constraint_results": {},
            "visual_checks": visual_checks(limb_status=limb_status),
            "next_action": next_action,
        }

    def review_initial(self, *, next_action: str = "refine") -> dict[str, object]:
        return self.store.record_review(
            self.manifest["run_id"],
            1,
            self.review_value(next_action=next_action),
        )

    def complete_marked_and_reviewed_initial(self) -> dict[str, object]:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-published", INITIAL)
        image = self.write_run_image(contents=b"published final contents")
        self.store.mark_attempt_image(handle, image)
        self.store.complete_attempt(handle, {})
        self.review_initial()
        return image

    def final_publication(self) -> tuple[Path, dict[str, object]]:
        final_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / "final.png"
        return final_path, {
            "path": "final.png",
            "sha256": hashlib.sha256(b"published final contents").hexdigest(),
            "width": 256,
            "height": 256,
        }

    def test_completed_idempotency_key_returns_existing_round(self) -> None:
        self.complete_initial()
        retried = self.store.begin_attempt(self.manifest["run_id"], "initial-1", INITIAL)
        self.assertEqual(retried.status, "completed")
        self.assertEqual(retried.existing_round["round_number"], 1)

    def test_attempt_and_completed_round_persist_normalized_plan_and_change_summary(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "audited-initial", INITIAL)
        active = self.store.get(self.manifest["run_id"])["active_attempt"]
        self.assertIn("generation_plan", active)
        self.assertIn("change_summary", active)
        self.assertEqual(active["generation_plan"], INITIAL["plan"])
        self.assertEqual(active["change_summary"], "Initial candidate.")

        completed = self.store.complete_attempt(handle, {})

        self.assertEqual(completed["attempts"][0]["generation_plan"], INITIAL["plan"])
        self.assertEqual(completed["attempts"][0]["change_summary"], "Initial candidate.")
        self.assertEqual(completed["rounds"][0]["generation_plan"], INITIAL["plan"])
        self.assertEqual(completed["rounds"][0]["change_summary"], "Initial candidate.")

    def test_same_key_with_changed_plan_or_summary_raises_conflict(self) -> None:
        self.complete_initial(key="audited-key")
        changes = (
            {**INITIAL, "plan": {"positive_prompt": "different coast"}},
            {**INITIAL, "change_summary": "Different explanation."},
        )
        for changed in changes:
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ConflictError, "idempotency_conflict"):
                    self.store.begin_attempt(self.manifest["run_id"], "audited-key", changed)

    def test_legacy_attempt_hash_accepts_an_identical_normalized_retry(self) -> None:
        self.complete_initial(key="legacy-key")
        legacy_request = {name: INITIAL[name] for name in ("action", "seed", "plan")}
        legacy_hash = request_hash(legacy_request)

        def make_legacy(manifest: dict[str, object]) -> None:
            attempt = manifest["attempts"][0]
            round_value = manifest["rounds"][0]
            for value in (attempt, round_value):
                value["request_hash"] = legacy_hash
                value.pop("generation_plan", None)
                value.pop("change_summary", None)

        self.store.update(self.manifest["run_id"], make_legacy)

        try:
            retried = self.store.begin_attempt(self.manifest["run_id"], "legacy-key", INITIAL)
        except ConflictError as error:
            self.fail(f"identical legacy retry conflicted: {error}")

        self.assertEqual(retried.status, "completed")
        self.assertEqual(retried.existing_round["round_number"], 1)

    def test_same_key_with_different_request_hash_raises_conflict(self) -> None:
        self.complete_initial()
        changed = {**INITIAL, "seed": 43}
        with self.assertRaisesRegex(ConflictError, "idempotency_conflict"):
            self.store.begin_attempt(self.manifest["run_id"], "initial-1", changed)

    def test_refine_preserves_seed(self) -> None:
        self.complete_initial()
        self.review_initial()
        with self.assertRaisesRegex(StateError, "refine_seed_mismatch"):
            self.store.begin_attempt(self.manifest["run_id"], "refine-1", {**REFINE, "seed": 43})

    def test_explore_requires_new_seed(self) -> None:
        self.complete_initial()
        self.review_initial()
        with self.assertRaisesRegex(StateError, "explore_seed_unchanged"):
            self.store.begin_attempt(
                self.manifest["run_id"],
                "explore-1",
                {
                    "action": "explore",
                    "seed": 42,
                    "plan": {"positive_prompt": "new composition"},
                    "change_summary": "Explore a new composition.",
                },
            )

    def test_next_round_requires_review(self) -> None:
        self.complete_initial()
        with self.assertRaisesRegex(StateError, "round_requires_review"):
            self.store.begin_attempt(self.manifest["run_id"], "refine-1", REFINE)

    def test_custom_round_budget_is_enforced(self) -> None:
        one_round = self.store.create({
            "profile": "standalone-illustration",
            "max_rounds": 1,
            "merged_profile": {"rubric": {}, "hard_failures": []},
        })
        handle = self.store.begin_attempt(one_round["run_id"], "initial-1", INITIAL)
        self.store.complete_attempt(handle, {"seed": 42, "image": {"path": "round-01.png"}})
        self.store.record_review(one_round["run_id"], 1, {
            "scores": {}, "hard_failures": [], "critique": "Complete.",
            "constraint_results": {}, "visual_checks": visual_checks(), "next_action": "finalize",
        })
        with self.assertRaisesRegex(StateError, "round_budget_exhausted"):
            self.store.begin_attempt(one_round["run_id"], "refine-1", REFINE)

    def test_failed_attempt_does_not_consume_round(self) -> None:
        failed = self.store.begin_attempt(self.manifest["run_id"], "initial-failed", INITIAL)
        self.store.fail_attempt(failed, {"code": "backend_command_failed", "message": "backend exited"})
        retry = self.store.begin_attempt(self.manifest["run_id"], "initial-retry", INITIAL)
        completed = self.store.complete_attempt(retry, {"seed": 42, "image": {"path": "round-01.png"}})
        self.assertEqual(len(completed["rounds"]), 1)
        self.assertEqual(completed["rounds"][0]["round_number"], 1)

    def test_live_repeated_key_returns_busy(self) -> None:
        self.store.begin_attempt(self.manifest["run_id"], "initial-live", INITIAL)
        repeated = self.store.begin_attempt(self.manifest["run_id"], "initial-live", INITIAL)
        self.assertEqual(repeated.status, "busy")
        self.assertIsNone(repeated.owner_token)

    def test_concurrent_identical_start_returns_busy(self) -> None:
        other = RunStore(Path(self.temp.name))
        original_acquire = self.store._acquire_lock
        other_handle: list[AttemptHandle] = []

        def start_other(run_root: Path) -> tuple[Path, str]:
            other_handle.append(other.begin_attempt(self.manifest["run_id"], "initial-race", INITIAL))
            return original_acquire(run_root)

        try:
            with patch.object(self.store, "_acquire_lock", side_effect=start_other):
                repeated = self.store.begin_attempt(self.manifest["run_id"], "initial-race", INITIAL)
            self.assertEqual(repeated.status, "busy")
            self.assertIsNone(repeated.owner_token)
        finally:
            if other_handle:
                other.fail_attempt(other_handle[0], {"code": "cancelled", "message": "cleanup"})

    def test_concurrent_identical_completion_returns_completed_round(self) -> None:
        other = RunStore(Path(self.temp.name))
        original_acquire = self.store._acquire_lock

        def complete_other(run_root: Path) -> tuple[Path, str]:
            handle = other.begin_attempt(self.manifest["run_id"], "initial-race", INITIAL)
            other.complete_attempt(handle, {"seed": 42, "image": {"path": "round-01.png"}})
            return original_acquire(run_root)

        with patch.object(self.store, "_acquire_lock", side_effect=complete_other):
            repeated = self.store.begin_attempt(self.manifest["run_id"], "initial-race", INITIAL)

        self.assertEqual(repeated.status, "completed")
        self.assertEqual(repeated.existing_round["round_number"], 1)
        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        self.assertFalse(lock_path.exists())

    def test_interrupted_attempt_with_image_resumes_preview(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-image", INITIAL)
        image = self.write_run_image()
        self.store.mark_attempt_image(handle, image)
        with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
            self.store.get(self.manifest["run_id"])
        resumed = self.store.begin_attempt(self.manifest["run_id"], "initial-image", INITIAL)
        self.assertEqual(resumed.status, "resume_preview")
        self.assertEqual(resumed.existing_round["image"]["path"], "round-01.png")

    def test_stale_active_attempt_recovers_to_last_stable_state(self) -> None:
        self.store.begin_attempt(self.manifest["run_id"], "initial-stale", INITIAL)
        with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
            recovered = self.store.get(self.manifest["run_id"])
        self.assertEqual(recovered["state"], "created")
        self.assertIsNone(recovered["active_attempt"])
        self.assertEqual(recovered["attempts"][-1]["status"], "interrupted")

    def test_attempt_lock_is_retained_until_completion(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-lock", INITIAL)
        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        self.assertTrue(lock_path.is_file())

        image = self.write_run_image(contents=b"owned checkpoint")
        self.store.mark_attempt_image(handle, image)
        self.assertTrue(lock_path.is_file())

        completed = self.store.complete_attempt(handle, {
            "seed": 99,
            "image": {"path": "unvalidated-replacement.png"},
        })
        self.assertEqual(completed["rounds"][0]["seed"], 42)
        self.assertEqual(completed["rounds"][0]["image"]["sha256"], image["sha256"])
        self.assertFalse(lock_path.exists())

    def test_foreign_handle_cannot_complete_or_release_attempt(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-owned", INITIAL)
        foreign = AttemptHandle(
            run_id=handle.run_id,
            idempotency_key=handle.idempotency_key,
            request_hash=handle.request_hash,
            status=handle.status,
            owner_token="foreign-owner",
            existing_round=None,
        )
        with self.assertRaisesRegex(ConflictError, "attempt_owner_mismatch"):
            self.store.complete_attempt(foreign, {"seed": 42, "image": {"path": "round-01.png"}})

        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        self.assertTrue(lock_path.is_file())
        self.store.fail_attempt(handle, {"code": "cancelled", "message": "owner cleanup"})

    def test_foreign_handle_is_rejected_before_image_validation(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-owned", INITIAL)
        foreign = AttemptHandle(
            run_id=handle.run_id,
            idempotency_key=handle.idempotency_key,
            request_hash=handle.request_hash,
            status=handle.status,
            owner_token="foreign-owner",
        )

        with self.assertRaisesRegex(ConflictError, "attempt_owner_mismatch"):
            self.store.mark_attempt_image(foreign, {"path": "incomplete.png"})

        self.store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})

    def test_invalid_handle_is_rejected_with_structured_conflict(self) -> None:
        with self.assertRaisesRegex(ConflictError, "attempt_owner_mismatch"):
            self.store.complete_attempt(object(), {})

    def test_stale_handle_cannot_release_a_new_attempt_lock(self) -> None:
        stale = self.store.begin_attempt(self.manifest["run_id"], "initial-stale-owner", INITIAL)
        self.store.fail_attempt(stale, {"code": "cancelled", "message": "first attempt ended"})
        current = self.store.begin_attempt(self.manifest["run_id"], "initial-current-owner", INITIAL)

        with self.assertRaisesRegex(ConflictError, "attempt_owner_mismatch"):
            self.store.complete_attempt(stale, {"seed": 42, "image": {"path": "round-01.png"}})

        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        self.assertTrue(lock_path.is_file())
        self.store.fail_attempt(current, {"code": "cancelled", "message": "cleanup"})

    def test_mismatched_request_handle_cannot_release_its_attempt_lock(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-owned", INITIAL)
        mismatched = AttemptHandle(
            run_id=handle.run_id,
            idempotency_key="different-key",
            request_hash=handle.request_hash,
            status=handle.status,
            owner_token=handle.owner_token,
            existing_round=None,
        )

        with self.assertRaisesRegex(ConflictError, "stale_attempt_handle"):
            self.store.complete_attempt(mismatched, {"seed": 42, "image": {"path": "round-01.png"}})

        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        self.assertTrue(lock_path.is_file())
        self.store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})

    def test_mark_attempt_image_requires_validated_full_image_metadata(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-image-invalid", INITIAL)
        with self.assertRaisesRegex(ValidationError, "invalid_image_metadata"):
            self.store.mark_attempt_image(handle, {"path": "round-01.png"})
        self.store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})

    def test_mark_attempt_image_rejects_path_escaping_run_directory(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-image-escape", INITIAL)
        outside = Path(self.temp.name) / "runs" / "outside.png"
        outside.write_bytes(b"outside")
        image = {
            "path": "../outside.png",
            "sha256": sha256_file(outside),
            "width": 16,
            "height": 16,
        }

        with self.assertRaisesRegex(ArtifactError, "invalid_image_path"):
            self.store.mark_attempt_image(handle, image)

        self.store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})

    def test_mark_attempt_image_rejects_missing_file(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-image-missing", INITIAL)
        image = {
            "path": "missing.png",
            "sha256": hashlib.sha256(b"missing").hexdigest(),
            "width": 16,
            "height": 16,
        }

        with self.assertRaisesRegex(ArtifactError, "image_not_found"):
            self.store.mark_attempt_image(handle, image)

        self.store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})

    def test_mark_attempt_image_rejects_hash_mismatch(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-image-hash", INITIAL)
        image = self.write_run_image(contents=b"actual contents")
        image["sha256"] = hashlib.sha256(b"different contents").hexdigest()

        with self.assertRaisesRegex(ArtifactError, "image_hash_mismatch"):
            self.store.mark_attempt_image(handle, image)

        self.store.fail_attempt(handle, {"code": "cancelled", "message": "cleanup"})

    def test_tampered_interrupted_image_does_not_resume_preview(self) -> None:
        handle = self.store.begin_attempt(self.manifest["run_id"], "initial-image-tampered", INITIAL)
        image = self.write_run_image(contents=b"original contents")
        self.store.mark_attempt_image(handle, image)
        with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
            self.store.get(self.manifest["run_id"])
        image_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / str(image["path"])
        image_path.write_bytes(b"tampered contents")

        restarted = self.store.begin_attempt(self.manifest["run_id"], "initial-image-tampered", INITIAL)

        self.assertEqual(restarted.status, "started")
        self.assertIsNone(restarted.existing_round)
        self.store.fail_attempt(restarted, {"code": "cancelled", "message": "cleanup"})

    def test_review_requires_exact_rubric_dimensions(self) -> None:
        self.complete_initial()
        review = {
            "scores": {},
            "hard_failures": [],
            "critique": "Missing score.",
            "constraint_results": {},
            "visual_checks": visual_checks(),
            "next_action": "refine",
        }
        with self.assertRaisesRegex(ValidationError, "invalid_review_scores"):
            self.store.record_review(self.manifest["run_id"], 1, review)

    def test_review_requires_visual_checks_without_manifest_mutation(self) -> None:
        self.complete_initial()
        before = self.store.get(self.manifest["run_id"])
        review = self.review_value()
        review.pop("visual_checks")

        with self.assertRaisesRegex(ValidationError, "invalid_review"):
            self.store.record_review(self.manifest["run_id"], 1, review)

        self.assertEqual(self.store.get(self.manifest["run_id"]), before)

    def test_failed_or_uncertain_visual_check_rejects_finalize_without_mutation(self) -> None:
        for index, status in enumerate(("fail", "uncertain"), start=1):
            manifest = self.store.create({
                "profile": "standalone-illustration",
                "max_rounds": 2,
                "merged_profile": {
                    "rubric": {"intent_adherence": {"weight": 1, "critical": True}},
                    "hard_failures": ["missing_subject"],
                },
            })
            handle = self.store.begin_attempt(manifest["run_id"], f"initial-{index}", INITIAL)
            self.store.complete_attempt(handle, {
                "seed": 42,
                "image": {"path": "round-01.png", "sha256": "a" * 64, "width": 16, "height": 16},
            })
            before = self.store.get(manifest["run_id"])
            review = self.review_value(next_action="finalize", limb_status=status)

            with self.subTest(status=status), self.assertRaisesRegex(
                ValidationError,
                "visual_checks_require_revision",
            ):
                self.store.record_review(manifest["run_id"], 1, review)

            self.assertEqual(self.store.get(manifest["run_id"]), before)

    def test_failed_visual_check_can_request_refine_and_preserves_round_budget(self) -> None:
        self.complete_initial()

        reviewed = self.store.record_review(
            self.manifest["run_id"],
            1,
            self.review_value(next_action="refine", limb_status="fail"),
        )

        self.assertEqual(reviewed["state"], "reviewed")
        self.assertEqual(len(reviewed["rounds"]), 1)
        self.assertEqual(reviewed["request"]["max_rounds"], 2)
        self.assertEqual(reviewed["reviews"][0]["visual_checks"]["limb_separation"]["status"], "fail")

    def test_required_failed_constraint_requires_registered_hard_failure(self) -> None:
        constrained = self.store.create({
            "profile": "standalone-illustration",
            "max_rounds": 1,
            "constraints": {"keep_logo": {"value": True, "required": True}},
            "merged_profile": {
                "rubric": {},
                "hard_failures": ["explicit_constraint_violation"],
            },
        })
        handle = self.store.begin_attempt(constrained["run_id"], "initial-1", INITIAL)
        self.store.complete_attempt(handle, {"seed": 42, "image": {"path": "round-01.png"}})
        review = {
            "scores": {},
            "hard_failures": [],
            "critique": "The required logo was omitted.",
            "constraint_results": {"keep_logo": {"status": "fail", "observation": "No logo is visible."}},
            "visual_checks": visual_checks(),
            "next_action": "finalize",
        }
        with self.assertRaisesRegex(ValidationError, "inconsistent_hard_failures"):
            self.store.record_review(constrained["run_id"], 1, review)

    def test_finalize_requires_reviewed_round(self) -> None:
        self.complete_initial()
        with self.assertRaisesRegex(StateError, "round_requires_review"):
            self.store.finalize(self.manifest["run_id"], 1, "Selected result.")

    def test_finalize_records_selected_reviewed_round(self) -> None:
        self.complete_initial()
        self.review_initial(next_action="finalize")

        finalized = self.store.finalize(self.manifest["run_id"], 1, "Selected result.")

        self.assertEqual(finalized["state"], "finalized")
        self.assertEqual(finalized["final"]["round_number"], 1)
        self.assertEqual(finalized["final"]["summary"], "Selected result.")
        self.assertEqual(finalized["final"]["quality_status"], "accepted")

    def test_finalize_marks_hard_failure_round_for_user_review(self) -> None:
        self.complete_initial()
        self.store.record_review(self.manifest["run_id"], 1, {
            "scores": {"intent_adherence": 5},
            "hard_failures": ["missing_subject"],
            "critique": "The requested subject is missing.",
            "constraint_results": {},
            "visual_checks": visual_checks(),
            "next_action": "finalize",
        })

        finalized = self.store.finalize(self.manifest["run_id"], 1, "User-selected exception.")

        self.assertEqual(finalized["final"]["quality_status"], "needs_user_review")

    def test_finalize_marks_low_critical_score_for_user_review(self) -> None:
        self.complete_initial()
        self.store.record_review(self.manifest["run_id"], 1, {
            "scores": {"intent_adherence": 2},
            "hard_failures": [],
            "critique": "Intent adherence remains below the acceptance threshold.",
            "constraint_results": {},
            "visual_checks": visual_checks(),
            "next_action": "finalize",
        })

        finalized = self.store.finalize(self.manifest["run_id"], 1, "User-selected draft.")

        self.assertEqual(finalized["final"]["quality_status"], "needs_user_review")

    def test_cleanup_prunes_recovered_attempt_artifacts_without_resuming_them(self) -> None:
        interrupted = self.store.begin_attempt(self.manifest["run_id"], "initial-interrupted", INITIAL)
        interrupted_image = self.write_run_image(relative_path="interrupted.png", contents=b"interrupted image")
        self.store.mark_attempt_image(interrupted, interrupted_image, {"path": "interrupted.png"})
        with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
            recovered = self.store.get(self.manifest["run_id"])
        self.assertEqual(recovered["attempts"][-1]["status"], "interrupted")

        self.complete_marked_and_reviewed_initial()
        final_path, final_image = self.final_publication()

        def publish() -> None:
            final_path.write_bytes(b"published final contents")

        self.store.finalize_published(
            self.manifest["run_id"],
            1,
            "Recovered run selected.",
            final_image,
            publish,
            final_path.unlink,
        )
        self.store.cleanup(
            self.manifest["run_id"],
            scope="intermediates",
            confirmation=self.manifest["run_id"],
        )

        cleaned = self.store.get(self.manifest["run_id"])
        recovered_attempt = next(item for item in cleaned["attempts"] if item["status"] == "interrupted")
        self.assertNotIn("image", recovered_attempt)
        self.assertNotIn("path", recovered_attempt["backend_result"])
        self.assertIn("artifacts_cleaned_at", recovered_attempt)
        self.assertTrue(final_path.is_file())
        with self.assertRaisesRegex(StateError, "run_finalized"):
            self.store.begin_attempt(self.manifest["run_id"], "initial-interrupted", INITIAL)

    def test_finalized_run_rejects_new_generation_attempt(self) -> None:
        self.complete_initial()
        self.review_initial()
        self.store.finalize(self.manifest["run_id"], 1, "Selected result.")

        with self.assertRaisesRegex(StateError, "run_finalized"):
            self.store.begin_attempt(self.manifest["run_id"], "refine-after-final", REFINE)

    def test_finalize_rejects_repeated_selection(self) -> None:
        self.complete_initial()
        self.review_initial()
        self.store.finalize(self.manifest["run_id"], 1, "Selected result.")

        with self.assertRaisesRegex(StateError, "already_finalized"):
            self.store.finalize(self.manifest["run_id"], 1, "Repeated selection.")

    def test_finalize_rejects_replacement_selection(self) -> None:
        self.complete_initial()
        self.review_initial()
        refine = self.store.begin_attempt(self.manifest["run_id"], "refine-1", REFINE)
        self.store.complete_attempt(refine, {"seed": 42, "image": {"path": "round-02.png"}})
        self.store.record_review(self.manifest["run_id"], 2, {
            "scores": {"intent_adherence": 4},
            "hard_failures": [],
            "critique": "The refined intent is clear.",
            "constraint_results": {},
            "visual_checks": visual_checks(),
            "next_action": "finalize",
        })
        self.store.finalize(self.manifest["run_id"], 1, "First reviewed round selected.")

        with self.assertRaisesRegex(StateError, "already_finalized"):
            self.store.finalize(self.manifest["run_id"], 2, "Replacement selection.")

    def test_published_finalize_rejects_active_attempt_before_publisher(self) -> None:
        self.complete_marked_and_reviewed_initial()
        active = self.store.begin_attempt(self.manifest["run_id"], "refine-live-finalize", REFINE)
        final_path, final_image = self.final_publication()
        publish_calls = 0

        def publish() -> None:
            nonlocal publish_calls
            publish_calls += 1
            final_path.write_bytes(b"published final contents")

        try:
            with self.assertRaisesRegex(ConflictError, "run_busy"):
                RunStore(Path(self.temp.name)).finalize_published(
                    self.manifest["run_id"], 1, "Blocked by active attempt.", final_image, publish, lambda: None
                )
            self.assertEqual(publish_calls, 0)
            self.assertFalse(final_path.exists())
        finally:
            self.store.fail_attempt(active, {"code": "cancelled", "message": "cleanup"})

    def test_published_finalize_rejects_earlier_round_when_latest_is_unreviewed(self) -> None:
        self.complete_marked_and_reviewed_initial()
        refine = self.store.begin_attempt(self.manifest["run_id"], "refine-unreviewed-finalize", REFINE)
        self.store.complete_attempt(refine, {"image": {"path": "round-02.png"}})
        final_path, final_image = self.final_publication()
        publish_calls = 0

        def publish() -> None:
            nonlocal publish_calls
            publish_calls += 1
            final_path.write_bytes(b"published final contents")

        with self.assertRaises(StateError) as raised:
            self.store.finalize_published(
                self.manifest["run_id"], 1, "Earlier reviewed round.", final_image, publish, lambda: None
            )
        self.assertEqual(raised.exception.code, "round_requires_review")
        self.assertEqual(publish_calls, 0)
        self.assertFalse(final_path.exists())

    def test_published_finalize_repeated_and_concurrent_callers_publish_once(self) -> None:
        self.complete_marked_and_reviewed_initial()
        final_path, final_image = self.final_publication()
        barrier = threading.Barrier(2)
        publisher_lock = threading.Lock()
        publish_calls = 0
        successes: list[dict[str, object]] = []
        failures: list[AssetEngineError] = []

        def finalize() -> None:
            nonlocal publish_calls
            store = RunStore(Path(self.temp.name))
            barrier.wait()

            def publish() -> None:
                nonlocal publish_calls
                with publisher_lock:
                    publish_calls += 1
                final_path.write_bytes(b"published final contents")

            try:
                successes.append(store.finalize_published(
                    self.manifest["run_id"], 1, "Concurrent selection.", final_image, publish, final_path.unlink
                ))
            except AssetEngineError as error:
                failures.append(error)

        threads = [threading.Thread(target=finalize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn(failures[0].code, {"run_busy", "already_finalized"})
        self.assertEqual(publish_calls, 1)
        self.assertEqual(final_path.read_bytes(), b"published final contents")

        repeated_calls = 0

        def repeated_publish() -> None:
            nonlocal repeated_calls
            repeated_calls += 1
            final_path.write_bytes(b"replacement")

        with self.assertRaisesRegex(StateError, "already_finalized"):
            self.store.finalize_published(
                self.manifest["run_id"], 1, "Repeated.", final_image, repeated_publish, lambda: None
            )
        self.assertEqual(repeated_calls, 0)
        self.assertEqual(final_path.read_bytes(), b"published final contents")

    def test_published_finalize_rolls_back_publisher_failure(self) -> None:
        self.complete_marked_and_reviewed_initial()
        final_path, final_image = self.final_publication()

        def publish() -> None:
            final_path.write_bytes(b"published final contents")
            raise OSError("publish failed")

        with self.assertRaisesRegex(OSError, "publish failed"):
            self.store.finalize_published(
                self.manifest["run_id"], 1, "Publisher failure.", final_image, publish, final_path.unlink
            )
        self.assertFalse(final_path.exists())
        self.assertEqual(self.store.get(self.manifest["run_id"])["state"], "reviewed")

    def test_published_finalize_rolls_back_manifest_write_failure(self) -> None:
        self.complete_marked_and_reviewed_initial()
        final_path, final_image = self.final_publication()

        def publish() -> None:
            final_path.write_bytes(b"published final contents")

        with patch("local_gpu_imagegen.run_store.atomic_write_json", side_effect=OSError("manifest failed")):
            with self.assertRaisesRegex(OSError, "manifest failed"):
                self.store.finalize_published(
                    self.manifest["run_id"], 1, "Manifest failure.", final_image, publish, final_path.unlink
                )
        self.assertFalse(final_path.exists())
        self.assertEqual(self.store.get(self.manifest["run_id"])["state"], "reviewed")
        self.assertFalse((Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock").exists())

    def test_missing_attempt_lock_is_recovered_with_warning(self) -> None:
        self.store.begin_attempt(self.manifest["run_id"], "initial-missing-lock", INITIAL)
        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        lock_path.unlink()

        recovered = self.store.get(self.manifest["run_id"])

        self.assertEqual(recovered["attempts"][-1]["status"], "interrupted")
        self.assertIn("interrupted_attempt_recovered", recovered["warnings"])
        self.assertFalse(lock_path.exists())

    def test_malformed_attempt_lock_is_recovered(self) -> None:
        self.store.begin_attempt(self.manifest["run_id"], "initial-malformed-lock", INITIAL)
        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        lock_path.write_text("not-json", encoding="utf-8")

        recovered = self.store.get(self.manifest["run_id"])

        self.assertEqual(recovered["state"], "created")
        self.assertEqual(recovered["attempts"][-1]["status"], "interrupted")
        self.assertFalse(lock_path.exists())

    def test_incomplete_live_pid_lock_is_recovered_as_malformed(self) -> None:
        self.store.begin_attempt(self.manifest["run_id"], "initial-incomplete-lock", INITIAL)
        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        lock_path.write_text(json.dumps({"owner_pid": os.getpid()}), encoding="utf-8")

        recovered = self.store.get(self.manifest["run_id"])

        self.assertEqual(recovered["attempts"][-1]["status"], "interrupted")
        self.assertFalse(lock_path.exists())

    def test_recovery_claims_stale_lock_before_removing_it(self) -> None:
        self.store.begin_attempt(self.manifest["run_id"], "initial-claimed-lock", INITIAL)
        lock_path = Path(self.temp.name) / "runs" / self.manifest["run_id"] / ".run.lock"
        original_unlink = Path.unlink
        canonical_unlinks = 0

        def tracked_unlink(path: Path, *args: object, **kwargs: object) -> None:
            nonlocal canonical_unlinks
            if path.resolve() == lock_path.resolve():
                canonical_unlinks += 1
            original_unlink(path, *args, **kwargs)

        with patch.object(type(lock_path), "unlink", new=tracked_unlink):
            with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
                recovered = self.store.get(self.manifest["run_id"])

        self.assertEqual(recovered["attempts"][-1]["status"], "interrupted")
        self.assertEqual(canonical_unlinks, 1)


if __name__ == "__main__":
    unittest.main()
