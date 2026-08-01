from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ArtifactError, ValidationError  # noqa: E402
from local_gpu_imagegen.file_verification import FileVerificationRegistry  # noqa: E402


class FileVerificationRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=str(Path.home()))
        self.state_dir = Path(self.temporary_directory.name) / "state"
        self.root = Path(self.temporary_directory.name) / "models"
        self.root.mkdir()
        self.model = self.root / "model.safetensors"
        self.model.write_bytes(b"model-bytes")
        self.registry = FileVerificationRegistry(
            self.state_dir,
            now=lambda: "2026-07-28T08:00:00Z",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def authorize(self, path: Path | None = None, model_id: str = "model.safetensors") -> dict[str, object]:
        selected = path or self.model
        file_stat = selected.stat()
        return self.registry.record_verified(
            local_path=selected,
            resolved_root=self.root,
            backend_model_id=model_id,
            fingerprint={
                "sha256": "a" * 64,
                "byte_size": file_stat.st_size,
                "modified_ns": file_stat.st_mtime_ns,
            },
        )

    def test_verified_record_round_trips_with_exact_schema(self) -> None:
        record = self.authorize()
        self.assertRegex(str(record["authorization_id"]), r"^verification:[0-9a-f]{24}$")
        self.assertEqual(record["status"], "active")
        self.assertEqual(
            set(record),
            {
                "authorization_id", "local_path", "resolved_root",
                "backend_model_id", "sha256", "byte_size", "modified_ns",
                "status", "created_at", "last_verified_at",
            },
        )
        self.assertEqual(
            FileVerificationRegistry(self.state_dir).resolve(
                backend_model_id="model.safetensors"
            ),
            record,
        )

    def test_resolve_fails_closed_on_ambiguous_model_name(self) -> None:
        self.authorize()
        second = self.root / "nested" / "model.safetensors"
        second.parent.mkdir()
        second.write_bytes(b"second")
        self.authorize(second)
        with self.assertRaisesRegex(ValidationError, "ambiguous_file_verification"):
            self.registry.resolve(backend_model_id="model.safetensors")

    def test_status_change_retains_digest_and_removes_active_resolution(self) -> None:
        record = self.authorize()
        changed = self.registry.set_status(str(record["authorization_id"]), "drifted")
        self.assertEqual(changed["sha256"], "a" * 64)
        self.assertEqual(changed["status"], "drifted")
        self.assertIsNone(self.registry.resolve(backend_model_id="model.safetensors"))
        self.assertEqual(
            self.registry.resolve(
                authorization_id=str(record["authorization_id"]), active_only=False
            ),
            changed,
        )
        revoked = self.registry.set_status(str(record["authorization_id"]), "revoked")
        self.assertEqual(revoked["status"], "revoked")

    def test_record_verified_refreshes_same_authorization_without_duplicate(self) -> None:
        first = self.authorize()
        refreshed = self.registry.record_verified(
            local_path=self.model,
            resolved_root=self.root,
            backend_model_id="model.safetensors",
            fingerprint={
                "sha256": "a" * 64,
                "byte_size": self.model.stat().st_size,
                "modified_ns": self.model.stat().st_mtime_ns,
            },
        )
        document = json.loads((self.state_dir / "file-verifications.json").read_text(encoding="utf-8"))
        self.assertEqual(refreshed["authorization_id"], first["authorization_id"])
        self.assertEqual(refreshed["created_at"], first["created_at"])
        self.assertEqual(len(document["records"]), 1)

    def test_record_verified_rejects_extra_fingerprint_fields(self) -> None:
        with self.assertRaisesRegex(ValidationError, "invalid_file_fingerprint"):
            self.registry.record_verified(
                local_path=self.model,
                resolved_root=self.root,
                backend_model_id="model.safetensors",
                fingerprint={
                    "sha256": "a" * 64,
                    "byte_size": self.model.stat().st_size,
                    "modified_ns": self.model.stat().st_mtime_ns,
                    "token": "secret",
                },
            )

    def test_registry_rejects_state_outside_user_local_roots(self) -> None:
        outside = Path("\\\\server\\share\\local-gpu-imagegen")
        with self.assertRaisesRegex(ValidationError, "invalid_file_verification_state_dir"):
            FileVerificationRegistry(outside)

    def test_corrupt_unknown_duplicate_credential_and_nonlocal_state_fail_closed(self) -> None:
        record = self.authorize()
        path = self.state_dir / "file-verifications.json"
        valid = json.loads(path.read_text(encoding="utf-8"))
        cases = (
            {**valid, "unknown": True},
            {**valid, "records": [record, record]},
            {**valid, "api_key": "secret"},
            {**valid, "records": [{**record, "sha256": "A" * 64}]},
            {**valid, "records": [{**record, "local_path": str(self.root / "other.safetensors")}]},
            {**valid, "records": [{**record, "local_path": r"\\server\share\model.safetensors"}]},
        )
        for document in cases:
            with self.subTest(document=document):
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ArtifactError, "corrupt_file_verification_registry"):
                    self.registry.resolve(authorization_id=str(record["authorization_id"]))

    def test_atomic_replace_failure_preserves_existing_document(self) -> None:
        record = self.authorize()
        path = self.state_dir / "file-verifications.json"
        original = path.read_bytes()
        with patch("local_gpu_imagegen.artifacts.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.registry.set_status(str(record["authorization_id"]), "revoked")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
