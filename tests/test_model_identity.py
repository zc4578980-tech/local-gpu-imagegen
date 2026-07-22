from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ConflictError, ValidationError  # noqa: E402
from local_gpu_imagegen.model_identity import (  # noqa: E402
    build_component_bundle,
    fingerprint_selected_file,
    identity_token,
    validate_component_bundle,
    validate_discovery_record,
)


def discovery_record(
    *,
    identity_strength: str = "backend_binding",
    sha256: str | None = None,
    byte_size: int | None = 1024,
    modified_ns: int | None = 123456789,
) -> dict[str, object]:
    return {
        "backend": "webui",
        "endpoint_identity": "endpoint:test",
        "backend_model_id": "anything-v5.safetensors",
        "format": ".safetensors",
        "byte_size": byte_size,
        "modified_ns": modified_ns,
        "sha256": sha256,
        "identity_strength": identity_strength,
        "metadata": {"family": "sd15"},
    }


class ModelIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_backend_binding_is_private_only_and_token_is_canonical(self) -> None:
        record = discovery_record()

        validated = validate_discovery_record(record)
        reordered = dict(reversed(list(record.items())))

        self.assertEqual(identity_token(validated), identity_token(reordered))
        self.assertFalse(validated["public_evidence_eligible"])
        self.assertNotIn("public_evidence_eligible", record)

    def test_cryptographic_identity_is_public_candidate_eligible(self) -> None:
        validated = validate_discovery_record(
            discovery_record(identity_strength="cryptographic", sha256="a" * 64)
        )

        self.assertTrue(validated["public_evidence_eligible"])

    def test_comfyui_loader_identity_is_part_of_route_token(self) -> None:
        checkpoint = discovery_record()
        checkpoint.update({
            "backend": "comfyui",
            "metadata": {
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
            },
        })
        unet = {
            **checkpoint,
            "metadata": {
                "loader_class": "UNETLoader",
                "loader_input": "unet_name",
            },
        }

        self.assertNotEqual(identity_token(checkpoint), identity_token(unet))

    def test_filesystem_is_a_discovery_source_not_a_generation_backend(self) -> None:
        record = discovery_record(
            identity_strength="cryptographic",
            sha256="a" * 64,
        )
        record["backend"] = "filesystem"

        validated = validate_discovery_record(record)

        self.assertEqual(validated["backend"], "filesystem")

    def test_component_bundle_is_canonical_and_binds_workflow_and_every_file(self) -> None:
        components = [
            {
                "role": "vae",
                "loader_class": "VAELoader",
                "loader_input": "vae_name",
                "backend_model_id": "ae.safetensors",
                "filesystem_identity_token": "model:" + "c" * 64,
                "sha256": "3" * 64,
                "byte_size": 300,
            },
            {
                "role": "primary_model",
                "loader_class": "UNETLoader",
                "loader_input": "unet_name",
                "backend_model_id": "z-image.safetensors",
                "filesystem_identity_token": "model:" + "a" * 64,
                "sha256": "1" * 64,
                "byte_size": 100,
            },
            {
                "role": "text_encoder",
                "loader_class": "CLIPLoader",
                "loader_input": "clip_name",
                "backend_model_id": "qwen.safetensors",
                "filesystem_identity_token": "model:" + "b" * 64,
                "sha256": "2" * 64,
                "byte_size": 200,
            },
        ]
        workflow = {
            "template_id": "z-image-turbo-txt2img",
            "template_version": 1,
            "sha256": "d" * 64,
        }

        first = build_component_bundle(components, workflow)
        second = build_component_bundle(list(reversed(components)), dict(reversed(list(workflow.items()))))

        self.assertEqual(first, second)
        self.assertEqual(validate_component_bundle(first), first)
        self.assertEqual(
            [item["role"] for item in first["components"]],
            ["primary_model", "text_encoder", "vae"],
        )

        tampered = {**first, "workflow": {**first["workflow"], "sha256": "e" * 64}}
        with self.assertRaisesRegex(ConflictError, "component_bundle_mismatch"):
            validate_component_bundle(tampered)

    def test_component_bundle_rejects_missing_primary_or_duplicate_role(self) -> None:
        component = {
            "role": "text_encoder",
            "loader_class": "CLIPLoader",
            "loader_input": "clip_name",
            "backend_model_id": "qwen.safetensors",
            "filesystem_identity_token": "model:" + "a" * 64,
            "sha256": "b" * 64,
            "byte_size": 100,
        }
        workflow = {
            "template_id": "z-image-turbo-txt2img",
            "template_version": 1,
            "sha256": "c" * 64,
        }

        for components in ([component], [component, {**component}]):
            with self.subTest(components=components), self.assertRaisesRegex(
                ValidationError,
                "invalid_component_bundle",
            ):
                build_component_bundle(components, workflow)

    def test_rejects_incomplete_or_inconsistent_identity_records(self) -> None:
        incomplete = discovery_record()
        del incomplete["backend_model_id"]
        invalid = (
            incomplete,
            discovery_record(identity_strength="cryptographic", sha256=None),
            discovery_record(identity_strength="cryptographic", sha256="A" * 64),
            discovery_record(identity_strength="backend_binding", sha256="a" * 64),
            discovery_record(identity_strength="filename", sha256=None),
            discovery_record(byte_size=True),
            discovery_record(modified_ns=-1),
        )

        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError, "invalid_model_identity"
            ):
                validate_discovery_record(value)

    def test_returns_a_deep_copy(self) -> None:
        original = discovery_record()
        validated = validate_discovery_record(original)

        validated["metadata"]["family"] = "changed"

        self.assertEqual(original["metadata"], {"family": "sd15"})

    def test_selected_file_fingerprint_returns_stable_low_cost_fields(self) -> None:
        path = self.root / "model.safetensors"
        contents = b"safe-test-weights"
        path.write_bytes(contents)
        path_stat = path.stat()

        result = fingerprint_selected_file(
            path,
            {"byte_size": path_stat.st_size, "modified_ns": path_stat.st_mtime_ns},
        )

        self.assertEqual(
            result,
            {
                "sha256": hashlib.sha256(contents).hexdigest(),
                "byte_size": path_stat.st_size,
                "modified_ns": path_stat.st_mtime_ns,
            },
        )

    def test_selected_file_fingerprint_rejects_pre_hash_drift(self) -> None:
        path = self.root / "model.safetensors"
        path.write_bytes(b"safe-test-weights")
        path_stat = path.stat()

        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            fingerprint_selected_file(
                path,
                {"byte_size": path_stat.st_size + 1, "modified_ns": path_stat.st_mtime_ns},
            )

    def test_selected_file_fingerprint_rejects_change_while_hashing(self) -> None:
        path = self.root / "model.safetensors"
        path.write_bytes(b"safe-test-weights")
        path_stat = path.stat()

        def mutate_during_hash(candidate: Path) -> str:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            candidate.write_bytes(b"changed-after-read")
            os.utime(candidate, ns=(path_stat.st_atime_ns, path_stat.st_mtime_ns + 1))
            return digest

        with patch(
            "local_gpu_imagegen.model_identity.sha256_file",
            side_effect=mutate_during_hash,
        ):
            with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
                fingerprint_selected_file(
                    path,
                    {"byte_size": path_stat.st_size, "modified_ns": path_stat.st_mtime_ns},
                )

    def test_selected_file_fingerprint_rejects_directories_and_links(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unsafe_model_path"):
            fingerprint_selected_file(
                self.root,
                {"byte_size": 0, "modified_ns": self.root.stat().st_mtime_ns},
            )

        target = self.root / "target.safetensors"
        target.write_bytes(b"safe-test-weights")
        link = self.root / "link.safetensors"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")
        link_stat = target.stat()
        with self.assertRaisesRegex(ValidationError, "unsafe_model_path"):
            fingerprint_selected_file(
                link,
                {"byte_size": link_stat.st_size, "modified_ns": link_stat.st_mtime_ns},
            )


if __name__ == "__main__":
    unittest.main()
