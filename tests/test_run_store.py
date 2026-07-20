from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.artifacts import ensure_within, sha256_file  # noqa: E402
from local_gpu_imagegen.errors import ArtifactError, ConflictError  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
