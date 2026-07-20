from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.artifacts import ensure_within, sha256_file  # noqa: E402
from local_gpu_imagegen.errors import ArtifactError, ConflictError, StateError, ValidationError  # noqa: E402
from local_gpu_imagegen.run_store import AttemptHandle, RunStore  # noqa: E402


INITIAL = {"action": "initial", "seed": 42, "plan": {"positive_prompt": "coast at dawn"}}
REFINE = {"action": "refine", "seed": 42, "plan": {"positive_prompt": "coast at dawn, cleaner detail"}}


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
        self.store.update(manifest["run_id"], lambda value: value.update({"final": {"path": "final.png"}}))

        self.store.cleanup(manifest["run_id"], scope="intermediates", confirmation=manifest["run_id"])

        self.assertTrue((run_root / "manifest.json").is_file())
        self.assertTrue(final.is_file())
        self.assertFalse(intermediate.exists())


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

    def complete_initial(self, key: str = "initial-1") -> dict[str, object]:
        handle = self.store.begin_attempt(self.manifest["run_id"], key, INITIAL)
        return self.store.complete_attempt(handle, {
            "seed": 42,
            "image": {"path": "round-01.png", "sha256": "a" * 64, "width": 16, "height": 16},
        })

    def review_initial(self) -> dict[str, object]:
        return self.store.record_review(self.manifest["run_id"], 1, {
            "scores": {"intent_adherence": 3},
            "hard_failures": [],
            "critique": "Intent is present; detail can improve.",
            "constraint_results": {},
            "next_action": "refine",
        })

    def test_completed_idempotency_key_returns_existing_round(self) -> None:
        self.complete_initial()
        retried = self.store.begin_attempt(self.manifest["run_id"], "initial-1", INITIAL)
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
                {"action": "explore", "seed": 42, "plan": {"positive_prompt": "new composition"}},
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
            "constraint_results": {}, "next_action": "finalize",
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
        self.store.mark_attempt_image(handle, {
            "path": "round-01.png", "sha256": "a" * 64, "width": 256, "height": 256,
        })
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

        self.store.mark_attempt_image(handle, {
            "path": "round-01.png", "sha256": "b" * 64, "width": 16, "height": 16,
        })
        self.assertTrue(lock_path.is_file())

        completed = self.store.complete_attempt(handle, {
            "seed": 99,
            "image": {"path": "unvalidated-replacement.png"},
        })
        self.assertEqual(completed["rounds"][0]["seed"], 42)
        self.assertEqual(completed["rounds"][0]["image"]["sha256"], "b" * 64)
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

    def test_review_requires_exact_rubric_dimensions(self) -> None:
        self.complete_initial()
        review = {
            "scores": {},
            "hard_failures": [],
            "critique": "Missing score.",
            "constraint_results": {},
            "next_action": "refine",
        }
        with self.assertRaisesRegex(ValidationError, "invalid_review_scores"):
            self.store.record_review(self.manifest["run_id"], 1, review)

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
        self.review_initial()

        finalized = self.store.finalize(self.manifest["run_id"], 1, "Selected result.")

        self.assertEqual(finalized["state"], "finalized")
        self.assertEqual(finalized["final"]["round_number"], 1)
        self.assertEqual(finalized["final"]["summary"], "Selected result.")

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
