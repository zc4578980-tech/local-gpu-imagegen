from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import (  # noqa: E402
    ArtifactError,
    ConflictError,
    StateError,
    ValidationError,
)
from local_gpu_imagegen.model_identity import (  # noqa: E402
    build_component_bundle,
    identity_token,
)
from local_gpu_imagegen.trust_registry import (  # noqa: E402
    TrustRegistry,
    default_state_dir,
)


def discovery_record(
    *,
    identity_strength: str = "backend_binding",
    sha256: str | None = None,
) -> dict[str, object]:
    return {
        "backend": "webui",
        "endpoint_identity": "endpoint:test",
        "backend_model_id": "anything-v5.safetensors",
        "format": ".safetensors",
        "byte_size": 1024,
        "modified_ns": 123456789,
        "sha256": sha256,
        "identity_strength": identity_strength,
        "metadata": {"family": "sd15"},
    }


def component_bundle(workflow_sha256: str = "c" * 64) -> dict[str, object]:
    return build_component_bundle(
        [{
            "role": "primary_model",
            "loader_class": "UNETLoader",
            "loader_input": "unet_name",
            "backend_model_id": "anything-v5.safetensors",
            "filesystem_identity_token": "model:" + "b" * 64,
            "sha256": "a" * 64,
            "byte_size": 1024,
        }],
        {
            "template_id": "z-image-turbo-txt2img",
            "template_version": 1,
            "sha256": workflow_sha256,
        },
    )


class TrustRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "state"
        self.registry = TrustRegistry(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def approve_private(self) -> dict[str, object]:
        record = discovery_record()
        return self.registry.approve_private(
            record,
            self.registry.confirmation_value("approve_private", record),
            capabilities={"operations": ["txt2img"]},
        )

    def install_two_variants(self) -> list[dict[str, object]]:
        record = discovery_record(
            identity_strength="cryptographic",
            sha256="a" * 64,
        )
        bundle_a = component_bundle(workflow_sha256="c" * 64)
        bundle_b = component_bundle(workflow_sha256="d" * 64)
        capabilities = {"operations": ["txt2img"]}
        self.registry.approve_private(
            record,
            self.registry.confirmation_value("approve_private", record),
            capabilities=capabilities,
        )
        document = json.loads(
            (self.root / "trust.json").read_text(encoding="utf-8")
        )
        document["records"][0]["workflow_binding"] = {
            "backend": "comfyui",
            "component_bundle_sha256": bundle_a["bundle_sha256"],
        }
        document["records"][0]["component_bundle"] = bundle_a
        self.registry._write(document)
        for bundle in (bundle_a, bundle_b):
            self.registry.approve_private(
                record,
                self.registry.confirmation_value(
                    "approve_private",
                    record,
                    bundle,
                ),
                capabilities=capabilities,
                workflow_binding={
                    "backend": "comfyui",
                    "component_bundle_sha256": bundle["bundle_sha256"],
                },
                component_bundle=bundle,
            )
        return self.registry.list_records()

    def test_state_dir_override_is_exact_and_does_not_create_it(self) -> None:
        override = self.root / "override"

        resolved = default_state_dir({"LOCAL_GPU_IMAGEGEN_STATE_DIR": str(override)})

        self.assertEqual(resolved, override)
        self.assertFalse(override.exists())

    def test_private_approval_requires_exact_confirmation_and_is_atomic(self) -> None:
        record = discovery_record()
        confirmation = self.registry.confirmation_value("approve_private", record)

        approved = self.registry.approve_private(
            record,
            confirmation,
            capabilities={"operations": ["txt2img"]},
        )

        self.assertEqual(approved["scope"], "private")
        self.assertEqual(approved["identity_strength"], "backend_binding")
        self.assertRegex(approved["catalog_id"], r"^local:[0-9a-f]{24}$")
        self.assertIn("same-name byte replacement", " ".join(approved["limitations"]))
        self.assertEqual(self.registry.list_records(), [approved])
        self.assertFalse((self.root / "trust.json.tmp").exists())
        document = json.loads((self.root / "trust.json").read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)

    def test_wrong_confirmation_does_not_create_state(self) -> None:
        with self.assertRaisesRegex(ValidationError, "trust_confirmation_mismatch"):
            self.registry.approve_private(
                discovery_record(),
                "approve_private:model:wrong",
                capabilities={"operations": ["txt2img"]},
            )

        self.assertFalse((self.root / "trust.json").exists())

    def test_public_candidate_requires_crypto_source_license_and_redistribution(self) -> None:
        record = discovery_record(identity_strength="cryptographic", sha256="a" * 64)
        confirmation = self.registry.confirmation_value("approve_public_candidate", record)
        complete = {
            "source": "https://example.invalid/model",
            "license_id": "Example-1.0",
            "license_url": "https://example.invalid/license",
            "output_redistribution_status": "approved",
        }
        for missing in complete:
            metadata = {key: value for key, value in complete.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaisesRegex(
                ValidationError, "public_metadata_incomplete"
            ):
                self.registry.approve_public_candidate(
                    record,
                    confirmation,
                    metadata=metadata,
                )

        approved = self.registry.approve_public_candidate(
            record,
            confirmation,
            metadata=complete,
            capabilities={"operations": ["txt2img"]},
        )

        self.assertEqual(approved["scope"], "public_candidate")
        self.assertEqual(approved["public_metadata"], complete)
        self.assertEqual(approved["evidence"], [{"level": "declared"}])

    def test_backend_binding_can_never_be_public_candidate(self) -> None:
        record = discovery_record()
        confirmation = self.registry.confirmation_value("approve_public_candidate", record)

        with self.assertRaisesRegex(ValidationError, "public_metadata_incomplete"):
            self.registry.approve_public_candidate(
                record,
                confirmation,
                metadata={
                    "source": "https://example.invalid/model",
                    "license_id": "Example-1.0",
                    "license_url": "https://example.invalid/license",
                    "output_redistribution_status": "approved",
                },
            )

    def test_bundle_digest_is_part_of_exact_approval_confirmation(self) -> None:
        record = discovery_record(identity_strength="cryptographic", sha256="a" * 64)
        bundle = component_bundle()
        confirmation = self.registry.confirmation_value(
            "approve_public_candidate",
            record,
            bundle,
        )

        self.assertEqual(
            confirmation,
            f"approve_public_candidate:{self.registry.confirmation_value('approve_public_candidate', record).split(':', 1)[1]}:bundle:{bundle['bundle_sha256']}",
        )
        with self.assertRaisesRegex(ValidationError, "trust_confirmation_mismatch"):
            self.registry.approve_public_candidate(
                record,
                self.registry.confirmation_value("approve_public_candidate", record),
                metadata={
                    "source": "https://example.invalid/model",
                    "license_id": "Example-1.0",
                    "license_url": "https://example.invalid/license",
                    "output_redistribution_status": "approved",
                    "components": [{
                        "role": "primary_model",
                        "sha256": "a" * 64,
                        "source": "https://example.invalid/component",
                        "license_id": "Example-1.0",
                        "license_url": "https://example.invalid/license",
                        "output_redistribution_status": "approved",
                    }],
                },
                capabilities={"operations": ["txt2img"]},
                workflow_binding={"backend": "comfyui"},
                component_bundle=bundle,
            )

    def test_public_comfyui_candidate_requires_complete_component_authority(self) -> None:
        record = discovery_record(identity_strength="cryptographic", sha256="a" * 64)
        bundle = component_bundle()
        base_metadata = {
            "source": "https://example.invalid/model",
            "license_id": "Example-1.0",
            "license_url": "https://example.invalid/license",
            "output_redistribution_status": "approved",
        }

        with self.assertRaisesRegex(ValidationError, "public_component_bundle_required"):
            self.registry.approve_public_candidate(
                record,
                self.registry.confirmation_value("approve_public_candidate", record),
                metadata=base_metadata,
                workflow_binding={"backend": "comfyui"},
            )
        with self.assertRaisesRegex(ValidationError, "public_metadata_incomplete"):
            self.registry.approve_public_candidate(
                record,
                self.registry.confirmation_value("approve_public_candidate", record, bundle),
                metadata={**base_metadata, "components": []},
                workflow_binding={"backend": "comfyui"},
                component_bundle=bundle,
            )

        metadata = {
            **base_metadata,
            "components": [{
                "role": "primary_model",
                "sha256": "a" * 64,
                "source": "https://example.invalid/component",
                "license_id": "Example-1.0",
                "license_url": "https://example.invalid/license",
                "output_redistribution_status": "approved",
            }],
        }
        approved = self.registry.approve_public_candidate(
            record,
            self.registry.confirmation_value("approve_public_candidate", record, bundle),
            metadata=metadata,
            capabilities={"operations": ["txt2img"]},
            workflow_binding={"backend": "comfyui"},
            component_bundle=bundle,
        )

        self.assertEqual(approved["component_bundle"], bundle)
        self.assertEqual(approved["public_metadata"], metadata)

    def test_rejects_credentials_recursively_before_writing(self) -> None:
        record = discovery_record()
        confirmation = self.registry.confirmation_value("approve_private", record)

        with self.assertRaisesRegex(ValidationError, "credentials_not_allowed"):
            self.registry.approve_private(
                record,
                confirmation,
                capabilities={"operations": ["txt2img"], "nested": {"api_key": "secret"}},
            )

        self.assertFalse((self.root / "trust.json").exists())

    def test_reapproval_replaces_same_identity_without_duplicates(self) -> None:
        first = self.approve_private()
        record = discovery_record()
        second = self.registry.approve_private(
            record,
            self.registry.confirmation_value("approve_private", record),
            capabilities={"operations": ["txt2img", "img2img"]},
            preference=25,
        )

        records = self.registry.list_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["catalog_id"], first["catalog_id"])
        self.assertEqual(records[0], second)
        self.assertEqual(records[0]["preference"], 25)

    def test_same_identity_can_keep_legacy_and_add_new_bundle_variant(self) -> None:
        records = self.install_two_variants()
        token = identity_token(
            discovery_record(identity_strength="cryptographic", sha256="a" * 64)
        )
        legacy_id = "local:" + token.removeprefix("model:")[:24]

        self.assertEqual(len(records), 2)
        self.assertIn(legacy_id, {item["catalog_id"] for item in records})
        self.assertEqual(
            {item["identity_token"] for item in records},
            {token},
        )
        self.assertEqual(
            len({item["component_bundle"]["bundle_sha256"] for item in records}),
            2,
        )

    def test_bundle_reapproval_preserves_only_the_exact_pairs_evidence(self) -> None:
        records = self.install_two_variants()
        selected = records[1]
        self.registry.record_observation(
            selected["catalog_id"],
            selected["identity_token"],
            "txt2img",
            "run-regional",
        )
        bundle = selected["component_bundle"]
        record = discovery_record(
            identity_strength="cryptographic",
            sha256="a" * 64,
        )

        reapproved = self.registry.approve_private(
            record,
            self.registry.confirmation_value("approve_private", record, bundle),
            capabilities={"operations": ["txt2img"]},
            workflow_binding={
                "backend": "comfyui",
                "component_bundle_sha256": bundle["bundle_sha256"],
            },
            component_bundle=bundle,
            preference=30,
        )

        self.assertEqual(reapproved["catalog_id"], selected["catalog_id"])
        self.assertEqual(reapproved["evidence"][-1]["run_id"], "run-regional")
        self.assertEqual(len(self.registry.list_records()), 2)

    def test_catalog_id_collision_fails_without_replacing_existing_pair(self) -> None:
        first = self.approve_private()
        record = discovery_record(
            identity_strength="cryptographic",
            sha256="a" * 64,
        )
        bundle = component_bundle()

        with patch(
            "local_gpu_imagegen.trust_registry._variant_catalog_id",
            return_value=first["catalog_id"],
        ), self.assertRaisesRegex(ConflictError, "catalog_id_collision"):
            self.registry.approve_private(
                record,
                self.registry.confirmation_value(
                    "approve_private",
                    record,
                    bundle,
                ),
                capabilities={"operations": ["txt2img"]},
                workflow_binding={"backend": "comfyui"},
                component_bundle=bundle,
            )

        self.assertEqual(self.registry.list_records(), [first])

    def test_ambiguous_revoke_requires_exact_catalog_id(self) -> None:
        records = self.install_two_variants()
        token = records[0]["identity_token"]

        with self.assertRaisesRegex(ValidationError, "ambiguous_trust_variant"):
            self.registry.revoke(None, token, "unused")

        selected = records[1]["catalog_id"]
        result = self.registry.revoke(
            selected,
            token,
            f"revoke:{selected}:{token}",
        )
        self.assertEqual(result["catalog_id"], selected)
        self.assertEqual(len(self.registry.list_records()), 1)

    def test_unique_revoke_can_resolve_omitted_catalog_id(self) -> None:
        approved = self.approve_private()
        result = self.registry.revoke(
            None,
            approved["identity_token"],
            f"revoke:{approved['catalog_id']}:{approved['identity_token']}",
        )

        self.assertEqual(result["catalog_id"], approved["catalog_id"])
        self.assertEqual(self.registry.list_records(), [])

    def test_revoke_requires_exact_identity_confirmation(self) -> None:
        approved = self.approve_private()
        catalog_id = str(approved["catalog_id"])
        identity = str(approved["identity_token"])

        with self.assertRaisesRegex(ValidationError, "trust_confirmation_mismatch"):
            self.registry.revoke(catalog_id, identity, "revoke:wrong")
        revoked = self.registry.revoke(
            catalog_id,
            identity,
            f"revoke:{catalog_id}:{identity}",
        )

        self.assertEqual(
            revoked,
            {"catalog_id": catalog_id, "identity_token": identity, "revoked": True},
        )
        self.assertEqual(self.registry.list_records(), [])

    def test_observation_is_deduplicated_and_requires_trust(self) -> None:
        approved = self.approve_private()
        catalog_id = str(approved["catalog_id"])
        identity = str(approved["identity_token"])

        self.registry.record_observation(catalog_id, identity, "txt2img", "run-1")
        self.registry.record_observation(catalog_id, identity, "txt2img", "run-1")

        evidence = self.registry.list_records()[0]["evidence"]
        self.assertEqual(
            evidence,
            [
                {"level": "declared"},
                {"level": "observed", "operation": "txt2img", "run_id": "run-1"},
            ],
        )
        with self.assertRaisesRegex(StateError, "trust_record_not_found"):
            self.registry.record_observation("missing", identity, "txt2img", "run-2")

    def test_corrupt_registry_fails_closed_without_overwriting_state(self) -> None:
        self.root.mkdir(parents=True)
        path = self.root / "trust.json"
        path.write_text("{", encoding="utf-8")

        with self.assertRaisesRegex(ArtifactError, "corrupt_trust_registry"):
            self.registry.list_records()

        self.assertEqual(path.read_text(encoding="utf-8"), "{")

    def test_semantically_corrupt_registry_cannot_inject_credentials_or_evidence(self) -> None:
        self.approve_private()
        path = self.root / "trust.json"
        original = json.loads(path.read_text(encoding="utf-8"))

        credential = copy.deepcopy(original)
        credential["records"][0]["capabilities"]["api_key"] = "secret"
        promoted = copy.deepcopy(original)
        promoted["records"][0]["evidence"] = [{"level": "benchmarked"}]
        wrong_catalog = copy.deepcopy(original)
        wrong_catalog["records"][0]["catalog_id"] = "local:" + "f" * 24

        for document in (credential, promoted, wrong_catalog):
            with self.subTest(document=document):
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ArtifactError, "corrupt_trust_registry"):
                    self.registry.list_records()

    def test_atomic_replace_failure_preserves_existing_registry(self) -> None:
        approved = self.approve_private()
        path = self.root / "trust.json"
        original = path.read_bytes()
        record = discovery_record()

        with patch(
            "local_gpu_imagegen.artifacts.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.registry.approve_private(
                    record,
                    self.registry.confirmation_value("approve_private", record),
                    capabilities={"operations": ["txt2img", "inpaint"]},
                )

        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.registry.list_records(), [approved])
        self.assertFalse((self.root / "trust.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
