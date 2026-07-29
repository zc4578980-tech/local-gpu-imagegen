from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backends.base import BackendRegistry  # noqa: E402
from local_gpu_imagegen.discovery import DiscoveryService  # noqa: E402
from local_gpu_imagegen.errors import ConflictError, ValidationError  # noqa: E402
from local_gpu_imagegen.file_verification import FileVerificationRegistry  # noqa: E402
from local_gpu_imagegen.model_identity import identity_token, validate_discovery_record  # noqa: E402


def safetensors_bytes(metadata: dict[str, str], body: bytes = b"weights") -> bytes:
    encoded = json.dumps({"__metadata__": metadata}, separators=(",", ":")).encode("utf-8")
    return len(encoded).to_bytes(8, "little") + encoded + body


class MutableClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FakeAdapter:
    backend_id = "webui"
    endpoint_identity = "endpoint:api"

    def __init__(self) -> None:
        self.discovery_calls = 0

    def probe(self) -> dict[str, object]:
        return {"backend": "webui", "ready": True}

    def discover(self) -> list[dict[str, object]]:
        self.discovery_calls += 1
        record = validate_discovery_record({
            "backend": "webui",
            "endpoint_identity": self.endpoint_identity,
            "backend_model_id": "api-model.safetensors",
            "format": ".safetensors",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {},
        })
        record["identity_token"] = identity_token(record)
        return [record]

    def generate(self, _request: dict[str, object]) -> dict[str, object]:
        raise AssertionError("Discovery must not generate.")

    def cancel_or_query(self, _job_id: str, *, cancel: bool = False) -> dict[str, object]:
        raise AssertionError(f"Discovery must not query jobs: {cancel}")


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "models"
        self.root.mkdir()
        self.clock = MutableClock()
        self.adapter = FakeAdapter()
        self.file_verifications = FileVerificationRegistry(
            Path(self.temporary_directory.name) / "state"
        )
        self.service = DiscoveryService(
            BackendRegistry([self.adapter]),
            self.file_verifications,
            clock=self.clock,
            ttl_seconds=300,
            common_roots_provider=lambda: [self.root],
            network_root_detector=lambda _path: False,
            drive_root_validator=lambda _path: True,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def index_plan(self, **changes: object) -> dict[str, object]:
        request: dict[str, object] = {
            "mode": "selected_folders",
            "stage": "index",
            "roots": [str(self.root)],
        }
        request.update(changes)
        return self.service.plan(request)

    def execute_index(self, **changes: object) -> dict[str, object]:
        plan = self.index_plan(**changes)
        return self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))

    def exact_plan(self, **changes: object) -> dict[str, object]:
        request: dict[str, object] = {
            "mode": "exact_file",
            "stage": "verify",
            "roots": [str(self.root)],
            "explicit_includes": [str(self.root / "model.safetensors")],
            "expected_backend_model_id": "model.safetensors",
        }
        request.update(changes)
        return self.service.plan(request)

    def test_plan_displays_exact_scope_hash_confirmation_and_cost(self) -> None:
        plan = self.index_plan()

        self.assertEqual(plan["mode"], "selected_folders")
        self.assertEqual(plan["stage"], "index")
        self.assertEqual(plan["roots"], [str(self.root.resolve())])
        self.assertEqual(plan["extensions"], [".ckpt", ".safetensors"])
        self.assertEqual(
            plan["confirmation"],
            f"scan:{plan['plan_id']}:{plan['scope_hash']}",
        )
        self.assertIn("metadata", str(plan["cost_warning"]).lower())
        self.assertIn("hash", str(plan["cost_warning"]).lower())

    def test_wrong_confirmation_does_not_consume_plan_but_success_does(self) -> None:
        plan = self.index_plan()
        plan_id = str(plan["plan_id"])

        with self.assertRaisesRegex(ValidationError, "discovery_confirmation_mismatch"):
            self.service.execute(plan_id, "scan:wrong")
        result = self.service.execute(plan_id, str(plan["confirmation"]))
        self.assertFalse(result["incomplete"])
        with self.assertRaisesRegex(ConflictError, "discovery_plan_unavailable"):
            self.service.execute(plan_id, str(plan["confirmation"]))

    def test_expired_plan_fails_without_scanning(self) -> None:
        (self.root / "model.safetensors").write_bytes(safetensors_bytes({}))
        plan = self.index_plan()
        self.clock.value = float(plan["expires_at"]) + 1

        with self.assertRaisesRegex(ConflictError, "discovery_plan_expired"):
            self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))

        self.assertEqual(self.service.inventory(), [])

    def test_api_only_calls_selected_adapter_without_filesystem_or_generation(self) -> None:
        plan = self.service.plan({
            "mode": "api_only",
            "stage": "index",
            "backends": ["webui"],
        })

        result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))

        self.assertEqual(self.adapter.discovery_calls, 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertFalse(result["candidates"][0]["trusted"])

    def test_discovery_modes_reject_cross_family_stages_before_work(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"unread")
        cases = (
            {"mode": "exact_file", "stage": "index"},
            {"mode": "api_only", "stage": "revoke"},
            {"mode": "selected_folders", "stage": "verify", "roots": [str(self.root)]},
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaisesRegex(
                ValidationError, "invalid_discovery_stage"
            ):
                self.service.plan(request)
        self.assertEqual(self.adapter.discovery_calls, 0)
        self.assertEqual(self.service.inventory(), [])

    def test_exact_file_first_plan_is_stat_only_and_confirmation_bound(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(safetensors_bytes({}, b"weights"))
        with patch(
            "local_gpu_imagegen.discovery.fingerprint_selected_file",
            side_effect=AssertionError("plan hashed model bytes"),
        ):
            plan = self.exact_plan()
        self.assertTrue(plan["confirmation_required"])
        self.assertEqual(plan["roots"], [str(self.root.resolve())])
        self.assertEqual(plan["explicit_includes"], [str(model.resolve())])
        self.assertEqual(plan["expected_backend_model_id"], "model.safetensors")
        self.assertEqual(plan["byte_size"], model.stat().st_size)
        self.assertIn("complete contents", str(plan["cost_warning"]))

    def test_exact_file_execution_hashes_persists_then_inserts_inventory(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(safetensors_bytes({}, b"weights"))
        plan = self.exact_plan()
        result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["backend"], "filesystem")
        self.assertEqual(candidate["backend_model_id"], "model.safetensors")
        self.assertEqual(candidate["identity_strength"], "cryptographic")
        self.assertEqual(candidate["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
        stored = self.file_verifications.resolve(backend_model_id="model.safetensors")
        self.assertEqual(stored["sha256"], candidate["sha256"])
        self.assertEqual(self.service.inventory(), [candidate])

    def test_active_authorization_rehashes_in_fresh_service_without_confirmation(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(safetensors_bytes({}, b"weights"))
        first = self.exact_plan()
        self.service.execute(str(first["plan_id"]), str(first["confirmation"]))
        fresh = DiscoveryService(
            BackendRegistry([self.adapter]), self.file_verifications,
            clock=self.clock, network_root_detector=lambda _path: False,
        )
        plan = fresh.plan({
            "mode": "exact_file", "stage": "verify",
            "expected_backend_model_id": "model.safetensors",
        })
        self.assertFalse(plan["confirmation_required"])
        result = fresh.execute(str(plan["plan_id"]), None)
        self.assertEqual(result["candidates"][0]["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())

    def test_changed_bytes_mark_authorization_drifted_without_inventory_restore(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"first")
        first = self.exact_plan()
        self.service.execute(str(first["plan_id"]), str(first["confirmation"]))
        authorization = self.file_verifications.resolve(backend_model_id="model.safetensors")
        model.write_bytes(b"changed")
        fresh = DiscoveryService(BackendRegistry([self.adapter]), self.file_verifications)
        plan = fresh.plan({
            "mode": "exact_file", "stage": "verify",
            "roots": [str(self.root)], "explicit_includes": [str(model)],
            "expected_backend_model_id": "model.safetensors",
            "authorization_id": authorization["authorization_id"],
        })
        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            fresh.execute(str(plan["plan_id"]), str(plan["confirmation"]))
        self.assertEqual(fresh.inventory(), [])
        self.assertEqual(
            self.file_verifications.resolve(
                authorization_id=authorization["authorization_id"], active_only=False
            )["status"],
            "drifted",
        )

    def test_exact_file_revoke_requires_confirmation_and_never_reads_model(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"weights")
        verified = self.exact_plan()
        self.service.execute(str(verified["plan_id"]), str(verified["confirmation"]))
        authorization = self.file_verifications.resolve(backend_model_id="model.safetensors")
        plan = self.service.plan({
            "mode": "exact_file", "stage": "revoke",
            "authorization_id": authorization["authorization_id"],
        })
        with patch(
            "local_gpu_imagegen.discovery.fingerprint_selected_file",
            side_effect=AssertionError("revoke hashed model bytes"),
        ):
            result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
        self.assertEqual(result["authorization"]["status"], "revoked")
        self.assertEqual(result["candidates"], [])

    def test_revocation_invalidates_an_older_automatic_reverify_plan(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"weights")
        verified = self.exact_plan()
        self.service.execute(str(verified["plan_id"]), str(verified["confirmation"]))
        authorization = self.file_verifications.resolve(backend_model_id="model.safetensors")
        stale = self.service.plan({
            "mode": "exact_file", "stage": "verify",
            "authorization_id": authorization["authorization_id"],
        })
        revoke = self.service.plan({
            "mode": "exact_file", "stage": "revoke",
            "authorization_id": authorization["authorization_id"],
        })
        self.service.execute(str(revoke["plan_id"]), str(revoke["confirmation"]))

        with patch(
            "local_gpu_imagegen.discovery.fingerprint_selected_file",
            wraps=__import__(
                "local_gpu_imagegen.discovery", fromlist=["fingerprint_selected_file"]
            ).fingerprint_selected_file,
        ) as fingerprint:
            with self.assertRaisesRegex(ConflictError, "file_verification_not_found"):
                self.service.execute(str(stale["plan_id"]), None)
        fingerprint.assert_not_called()
        self.assertEqual(
            self.file_verifications.resolve(
                authorization_id=authorization["authorization_id"], active_only=False
            )["status"],
            "revoked",
        )

    def test_exact_file_rejects_unsafe_or_ambiguous_plans_without_state_mutation(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"weights")
        second = self.root / "second.safetensors"
        second.write_bytes(b"second")
        outside = self.root.parent / "outside.safetensors"
        outside.write_bytes(b"outside")
        registry_path = self.file_verifications.path
        cases = (
            ({"roots": [], "explicit_includes": []}, "invalid_discovery_plan"),
            ({"roots": [str(self.root), str(self.root.parent)], "explicit_includes": [str(model)]}, "invalid_discovery_plan"),
            ({"roots": [str(self.root)], "explicit_includes": [str(model), str(second)]}, "invalid_discovery_plan"),
            ({"roots": [str(self.root)], "explicit_includes": [str(outside)]}, "unsafe_model_path"),
            ({"roots": [str(self.root)], "explicit_includes": [str(self.root)]}, "unsafe_model_path"),
            ({"roots": [str(self.root)], "explicit_includes": [str(self.root / "missing.bin")]}, "unsafe_model_path"),
            ({"roots": [str(self.root)], "explicit_includes": [str(model)], "expected_backend_model_id": ""}, "invalid_discovery_plan"),
            ({"authorization_id": "verification:" + "f" * 24}, "file_verification_not_found"),
        )
        original = registry_path.read_bytes() if registry_path.exists() else None
        for changes, code in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValidationError, code):
                    self.exact_plan(**changes)
                self.assertEqual(self.service.inventory(), [])
                self.assertEqual(
                    registry_path.read_bytes() if registry_path.exists() else None,
                    original,
                )

    def test_exact_file_first_execution_requires_confirmation(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"weights")
        plan = self.exact_plan()
        with self.assertRaisesRegex(ValidationError, "discovery_confirmation_mismatch"):
            self.service.execute(str(plan["plan_id"]), None)
        self.assertEqual(self.service.inventory(), [])

    def test_exact_file_mid_read_drift_marks_authorization_and_keeps_inventory_empty(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(b"before")
        plan = self.exact_plan()

        def mutate_during_hash(path: Path) -> str:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_bytes(b"changed during hash")
            return digest

        with patch(
            "local_gpu_imagegen.model_identity.sha256_file",
            side_effect=mutate_during_hash,
        ), self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
        self.assertEqual(self.service.inventory(), [])
        self.assertIsNone(self.file_verifications.resolve(backend_model_id="model.safetensors"))

    def test_stage_one_reads_safe_metadata_without_hashing_weights(self) -> None:
        model = self.root / "anime.safetensors"
        model.write_bytes(safetensors_bytes({"modelspec.title": "Anime Model"}))
        (self.root / "anime.json").write_text(
            json.dumps({"description": "local test"}),
            encoding="utf-8",
        )

        with patch(
            "local_gpu_imagegen.discovery.fingerprint_selected_file",
            side_effect=AssertionError("stage one hashed weights"),
        ):
            result = self.execute_index()

        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["metadata"]["modelspec.title"], "Anime Model")
        self.assertEqual(candidate["metadata"]["description"], "local test")
        self.assertIsNone(candidate["sha256"])
        self.assertIsNone(candidate["identity_strength"])
        self.assertFalse(candidate["trusted"])

    def test_ckpt_is_opaque_and_never_opened(self) -> None:
        checkpoint = self.root / "opaque.ckpt"
        checkpoint.write_bytes(b"pickle-looking-bytes")
        original_open = Path.open

        def guarded_open(path: Path, *args: object, **kwargs: object):
            if path == checkpoint:
                raise AssertionError("ckpt contents were opened")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            result = self.execute_index()

        self.assertEqual(result["candidates"][0]["metadata"], {})

    def test_default_exclusions_skip_dependency_cache_and_explicit_include_restores_it(self) -> None:
        excluded = self.root / ".venv"
        excluded.mkdir()
        (excluded / "hidden.safetensors").write_bytes(safetensors_bytes({}))
        (self.root / "visible.safetensors").write_bytes(safetensors_bytes({}))

        ordinary = self.execute_index()
        included = self.execute_index(explicit_includes=[str(excluded)])

        self.assertEqual([item["filename"] for item in ordinary["candidates"]], ["visible.safetensors"])
        self.assertEqual(
            sorted(item["filename"] for item in included["candidates"]),
            ["hidden.safetensors", "visible.safetensors"],
        )

    def test_links_are_not_followed(self) -> None:
        outside = Path(self.temporary_directory.name) / "outside"
        outside.mkdir()
        (outside / "outside.safetensors").write_bytes(safetensors_bytes({}))
        link = self.root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")

        result = self.execute_index()

        self.assertEqual(result["candidates"], [])

    def test_cancellation_retains_untrusted_incomplete_inventory(self) -> None:
        for index in range(5):
            (self.root / f"model-{index}.safetensors").write_bytes(safetensors_bytes({}))
        checks = 0

        def cancel() -> bool:
            nonlocal checks
            checks += 1
            return checks > 4

        plan = self.index_plan()
        result = self.service.execute(
            str(plan["plan_id"]),
            str(plan["confirmation"]),
            cancel=cancel,
        )

        self.assertTrue(result["incomplete"])
        self.assertGreater(len(result["candidates"]), 0)
        self.assertLess(len(result["candidates"]), 5)
        self.assertEqual(self.service.inventory(), result["candidates"])
        self.assertTrue(all(item["trusted"] is False for item in result["candidates"]))

    def test_fingerprint_plan_hashes_only_selected_indexed_candidate(self) -> None:
        first = self.root / "first.safetensors"
        second = self.root / "second.safetensors"
        first.write_bytes(safetensors_bytes({"name": "first"}, b"first"))
        second.write_bytes(safetensors_bytes({"name": "second"}, b"second"))
        indexed = self.execute_index()
        selected = next(item for item in indexed["candidates"] if item["filename"] == "first.safetensors")
        plan = self.service.plan({
            "mode": "selected_folders",
            "stage": "fingerprint",
            "roots": [str(self.root)],
            "selected_candidates": [selected["candidate_id"]],
        })

        result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))

        self.assertEqual(len(result["candidates"]), 1)
        fingerprinted = result["candidates"][0]
        self.assertEqual(fingerprinted["backend"], "filesystem")
        self.assertEqual(fingerprinted["identity_strength"], "cryptographic")
        self.assertEqual(fingerprinted["sha256"], hashlib.sha256(first.read_bytes()).hexdigest())
        self.assertRegex(fingerprinted["identity_token"], r"^model:[0-9a-f]{64}$")
        inventory = self.service.inventory()
        untouched = next(item for item in inventory if item.get("filename") == "second.safetensors")
        self.assertIsNone(untouched["sha256"])

    def test_fingerprint_rejects_unindexed_candidate_and_drift(self) -> None:
        model = self.root / "model.safetensors"
        model.write_bytes(safetensors_bytes({}))
        indexed = self.execute_index()
        candidate_id = indexed["candidates"][0]["candidate_id"]

        with self.assertRaisesRegex(ValidationError, "unknown_discovery_candidate"):
            self.service.plan({
                "mode": "selected_folders",
                "stage": "fingerprint",
                "roots": [str(self.root)],
                "selected_candidates": ["candidate:missing"],
            })

        plan = self.service.plan({
            "mode": "selected_folders",
            "stage": "fingerprint",
            "roots": [str(self.root)],
            "selected_candidates": [candidate_id],
        })
        model.write_bytes(model.read_bytes() + b"changed")
        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))

    def test_common_locations_are_displayed_before_scanning(self) -> None:
        model = self.root / "common.safetensors"
        model.write_bytes(safetensors_bytes({}))

        plan = self.service.plan({"mode": "common_locations", "stage": "index"})

        self.assertEqual(plan["roots"], [str(self.root.resolve())])
        self.assertEqual(self.service.inventory(), [])
        result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
        self.assertEqual(result["candidates"][0]["filename"], "common.safetensors")

    def test_network_root_requires_a_second_exact_confirmation(self) -> None:
        service = DiscoveryService(
            BackendRegistry([self.adapter]),
            self.file_verifications,
            clock=self.clock,
            common_roots_provider=lambda: [],
            network_root_detector=lambda _path: True,
            drive_root_validator=lambda _path: True,
        )
        plan = service.plan({
            "mode": "full_drive",
            "stage": "index",
            "roots": [str(self.root)],
        })
        self.assertEqual(plan["network_roots"], [str(self.root.resolve())])

        with self.assertRaisesRegex(ValidationError, "network_scan_confirmation_required"):
            service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
        result = service.execute(
            str(plan["plan_id"]),
            str(plan["confirmation"]),
            network_confirmation=str(plan["network_confirmation"]),
        )
        self.assertFalse(result["incomplete"])


if __name__ == "__main__":
    unittest.main()
