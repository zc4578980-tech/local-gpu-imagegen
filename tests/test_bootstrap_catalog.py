from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.bootstrap_catalog import (  # noqa: E402
    MAX_ARTIFACT_BYTES,
    BootstrapFacts,
    build_bootstrap_plan,
    load_bootstrap_manifest,
    validate_bootstrap_manifest,
)
from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.paths import default_bootstrap_paths  # noqa: E402


def fixture_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "windows-nvidia-default",
        "platform": "win32",
        "architecture": "amd64",
        "gpu_vendor": "nvidia",
        "minimum_windows_build": 19045,
        "minimum_free_disk_bytes": 30 * 1024 * 1024 * 1024,
        "minimum_nvidia_gpu_generation": "rtx-20-series",
        "cuda_runtime": "13.0",
        "comfyui": {
            "id": "comfyui-windows-portable-test-fixture",
            "version": "2026.08.05-test-fixture",
            "source_url": "https://downloads.example.invalid/comfyui-fixture.7z",
            "source_host": "downloads.example.invalid",
            "license_id": "LicenseRef-Test-Fixture",
            "license_url": "https://downloads.example.invalid/LICENSE.txt",
            "byte_size": 1048576,
            "sha256": "0" * 64,
            "archive_format": "7z",
            "install_relative_path": "ComfyUI_windows_portable",
        },
        "model": {
            "id": "audited-default-model",
            "version": "2026.08.05-test-fixture",
            "source_url": "https://models.example.invalid/default-fixture.safetensors",
            "source_host": "models.example.invalid",
            "license_id": "LicenseRef-Test-Fixture",
            "license_url": "https://models.example.invalid/LICENSE.txt",
            "byte_size": 2097152,
            "sha256": "1" * 64,
            "minimum_vram_gb": 10,
            "install_relative_path": (
                "ComfyUI_windows_portable/ComfyUI/models/checkpoints/"
                "default-fixture.safetensors"
            ),
            "archive_format": None,
        },
        "workflow": {
            "backend": "comfyui",
            "template_id": "sdxl-txt2img",
            "template_version": 1,
            "operation": "txt2img",
        },
    }


class BootstrapCatalogTests(unittest.TestCase):
    def validate(self, document: dict[str, object]):
        return validate_bootstrap_manifest(
            document,
            allowed_hosts={"downloads.example.invalid", "models.example.invalid"},
        )

    def assert_invalid(self, document: dict[str, object], code: str) -> None:
        with self.assertRaises(ValidationError) as raised:
            self.validate(document)
        self.assertEqual(raised.exception.code, code)

    def test_fixture_manifest_normalizes_to_immutable_artifacts(self) -> None:
        manifest = self.validate(fixture_manifest())

        self.assertEqual(manifest.manifest_id, "windows-nvidia-default")
        self.assertEqual(manifest.comfyui.kind, "comfyui")
        self.assertEqual(manifest.comfyui.archive_format, "7z")
        self.assertEqual(manifest.model.kind, "model")
        self.assertEqual(manifest.model.minimum_vram_gb, 10)
        self.assertEqual(manifest.required_download_bytes, 3145728)

        source = fixture_manifest()
        source["comfyui"]["id"] = "changed"  # type: ignore[index]
        self.assertEqual(manifest.comfyui.artifact_id, "comfyui-windows-portable-test-fixture")

    def test_production_manifest_freezes_approved_sources(self) -> None:
        path = ROOT / "profiles" / "bootstrap" / "windows-nvidia.json"
        manifest = load_bootstrap_manifest(path)

        self.assertEqual(manifest.minimum_windows_build, 19045)
        self.assertEqual(manifest.minimum_nvidia_gpu_generation, "rtx-20-series")
        self.assertEqual(manifest.cuda_runtime, "13.0")
        self.assertEqual(manifest.minimum_free_disk_bytes, 30 * 1024**3)
        self.assertEqual(manifest.comfyui.version, "0.30.0")
        self.assertEqual(manifest.comfyui.byte_size, 2110797220)
        self.assertEqual(
            manifest.comfyui.sha256,
            "f4353d069dd7342e3bef421f07f003cca53ca84168102705cfc83f66449f5ae5",
        )
        self.assertEqual(
            manifest.comfyui.source_url,
            "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.30.0/"
            "ComfyUI_windows_portable_nvidia.7z",
        )
        self.assertEqual(manifest.model.version, "1.0")
        self.assertEqual(manifest.model.byte_size, 6938078334)
        self.assertEqual(
            manifest.model.sha256,
            "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
        )
        self.assertIn("/resolve/462165984030d82259a11f4367a4eed129e94a7b/", manifest.model.source_url)
        self.assertEqual(manifest.required_download_bytes, 9048875554)

    def test_loader_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "manifest.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ValidationError) as raised:
                load_bootstrap_manifest(path)
        self.assertEqual(raised.exception.code, "invalid_bootstrap_manifest_json")

    def test_loader_rejects_duplicate_json_fields(self) -> None:
        production = (ROOT / "profiles" / "bootstrap" / "windows-nvidia.json").read_text(
            encoding="utf-8"
        )
        duplicate = '{"schema_version": 1,' + production.lstrip()[1:]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "manifest.json"
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaises(ValidationError) as raised:
                load_bootstrap_manifest(path)
        self.assertEqual(raised.exception.code, "invalid_bootstrap_manifest_json")

    def test_rejects_unknown_fields_at_every_level(self) -> None:
        for location in ("root", "comfyui", "model", "workflow"):
            with self.subTest(location=location):
                document = fixture_manifest()
                target = document if location == "root" else document[location]
                target["unexpected"] = True  # type: ignore[index]
                self.assert_invalid(document, "unknown_bootstrap_manifest_fields")

    def test_rejects_non_https_and_unapproved_or_mismatched_hosts(self) -> None:
        mutations = (
            ("http://downloads.example.invalid/comfyui.7z", "downloads.example.invalid"),
            ("https://unapproved.example.invalid/comfyui.7z", "unapproved.example.invalid"),
            ("https://downloads.example.invalid/comfyui.7z", "models.example.invalid"),
        )
        for source_url, source_host in mutations:
            with self.subTest(source_url=source_url, source_host=source_host):
                document = fixture_manifest()
                document["comfyui"]["source_url"] = source_url  # type: ignore[index]
                document["comfyui"]["source_host"] = source_host  # type: ignore[index]
                self.assert_invalid(document, "invalid_bootstrap_source")

    def test_rejects_noncanonical_hashes_and_invalid_sizes(self) -> None:
        cases = (
            ("sha256", "A" * 64),
            ("sha256", "0" * 63),
            ("byte_size", 0),
            ("byte_size", MAX_ARTIFACT_BYTES + 1),
            ("byte_size", True),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                document = fixture_manifest()
                document["model"][field] = value  # type: ignore[index]
                self.assert_invalid(document, "invalid_bootstrap_artifact")

    def test_rejects_unsafe_install_paths(self) -> None:
        paths = (
            "C:/ComfyUI",
            "../ComfyUI",
            "/ComfyUI",
            "ComfyUI/../outside",
            "ComfyUI:stream",
            "",
        )
        for path in paths:
            with self.subTest(path=path):
                document = fixture_manifest()
                document["comfyui"]["install_relative_path"] = path  # type: ignore[index]
                self.assert_invalid(document, "invalid_bootstrap_install_path")

    def test_rejects_missing_license_metadata(self) -> None:
        for field in ("license_id", "license_url"):
            with self.subTest(field=field):
                document = fixture_manifest()
                del document["model"][field]  # type: ignore[index]
                self.assert_invalid(document, "invalid_bootstrap_artifact")

    def test_rejects_unsupported_platform_contract(self) -> None:
        cases = (
            ("schema_version", True),
            ("platform", "linux"),
            ("architecture", "arm64"),
            ("gpu_vendor", "amd"),
            ("minimum_windows_build", 0),
            ("minimum_free_disk_bytes", 0),
            ("minimum_nvidia_gpu_generation", "gtx-10-series"),
            ("cuda_runtime", "12.6"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                document = fixture_manifest()
                document[field] = value
                self.assert_invalid(document, "unsupported_bootstrap_contract")

    def test_rejects_more_than_one_default_model(self) -> None:
        document = fixture_manifest()
        document["model"] = [document["model"], copy.deepcopy(document["model"])]
        self.assert_invalid(document, "invalid_bootstrap_model_selection")

    def test_rejects_invalid_workflow_binding(self) -> None:
        cases = (("template_id", "unknown"), ("template_version", True))
        for field, value in cases:
            with self.subTest(field=field, value=value):
                document = fixture_manifest()
                document["workflow"][field] = value  # type: ignore[index]
                self.assert_invalid(document, "invalid_bootstrap_workflow")

    def test_manifest_digest_is_stable_for_key_order(self) -> None:
        document = fixture_manifest()
        reordered = json.loads(json.dumps(document, sort_keys=True))

        first = self.validate(document)
        second = self.validate(reordered)

        self.assertEqual(first.manifest_sha256, second.manifest_sha256)


class BootstrapPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_bootstrap_manifest(
            ROOT / "profiles" / "bootstrap" / "windows-nvidia.json"
        )

    @staticmethod
    def facts(**overrides: object) -> BootstrapFacts:
        values: dict[str, object] = {
            "platform": "win32",
            "architecture": "amd64",
            "gpu_vendor": "nvidia",
            "gpu_generation": "rtx-50-series",
            "vram_bytes": 16 * 1024**3,
            "windows_build": 26100,
            "free_disk_bytes": 40 * 1024**3,
            "network_allowed": True,
            "endpoint_ready": False,
            "portable_status": "missing",
            "model_status": "missing",
        }
        values.update(overrides)
        return BootstrapFacts(**values)

    def build(self, facts: BootstrapFacts, temporary_directory: str):
        root = Path(temporary_directory)
        return build_bootstrap_plan(
            self.manifest,
            facts,
            install_root=root / "install",
            plan_root=root / "plans",
        )

    def test_ready_endpoint_requires_no_install_or_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            plan = self.build(self.facts(endpoint_ready=True), temporary_directory)

        self.assertEqual(plan.status, "ready")
        self.assertEqual([action.kind for action in plan.actions], ["reuse_endpoint"])
        self.assertEqual(plan.required_download_bytes, 0)
        self.assertEqual(plan.required_disk_bytes, 0)
        self.assertIsNone(plan.confirmation)

    def test_existing_exact_portable_and_model_are_reused(self) -> None:
        facts = self.facts(portable_status="valid", model_status="valid")
        with tempfile.TemporaryDirectory() as temporary_directory:
            plan = self.build(facts, temporary_directory)

        self.assertEqual(plan.status, "ready")
        self.assertEqual(
            [action.kind for action in plan.actions],
            ["reuse_portable", "reuse_model", "verify_install"],
        )
        self.assertEqual(plan.required_download_bytes, 0)
        self.assertIsNone(plan.confirmation)

    def test_missing_portable_and_model_require_exact_confirmed_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self.build(self.facts(), temporary_directory)
            records = list((root / "plans").glob("*.json"))
            record = json.loads(records[0].read_text(encoding="utf-8"))

        self.assertEqual(plan.status, "confirmation_required")
        self.assertEqual(
            [action.kind for action in plan.actions],
            [
                "download_comfyui",
                "extract_comfyui",
                "download_model",
                "install_model",
                "verify_install",
            ],
        )
        self.assertEqual(plan.required_download_bytes, 9048875554)
        self.assertEqual(plan.required_disk_bytes, 30 * 1024**3)
        self.assertEqual(plan.confirmation, f"bootstrap:{plan.plan_id}:{plan.scope_sha256}")
        self.assertEqual(len(records), 1)
        self.assertEqual(record["plan_id"], plan.plan_id)
        self.assertEqual(record["scope_sha256"], plan.scope_sha256)
        self.assertEqual(record["confirmation"], plan.confirmation)

    def test_existing_portable_downloads_only_the_missing_model(self) -> None:
        facts = self.facts(portable_status="valid", model_status="missing")
        with tempfile.TemporaryDirectory() as temporary_directory:
            plan = self.build(facts, temporary_directory)

        self.assertEqual(plan.status, "confirmation_required")
        self.assertEqual(
            [action.kind for action in plan.actions],
            ["reuse_portable", "download_model", "install_model", "verify_install"],
        )
        self.assertEqual(plan.required_download_bytes, self.manifest.model.byte_size)

    def test_insufficient_disk_blocks_before_confirmation(self) -> None:
        facts = self.facts(free_disk_bytes=self.manifest.minimum_free_disk_bytes - 1)
        with tempfile.TemporaryDirectory() as temporary_directory:
            plan = self.build(facts, temporary_directory)

        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.reason, "insufficient_disk")
        self.assertIsNone(plan.confirmation)
        self.assertEqual(plan.actions, ())

    def test_missing_download_with_no_network_permission_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            plan = self.build(self.facts(network_allowed=False), temporary_directory)

        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.reason, "network_permission_required")
        self.assertIsNone(plan.confirmation)
        self.assertEqual(plan.required_download_bytes, 9048875554)
        self.assertEqual(plan.required_disk_bytes, 30 * 1024**3)

    def test_unsupported_system_contracts_stop_without_actions(self) -> None:
        cases = (
            {"platform": "linux"},
            {"architecture": "arm64"},
            {"gpu_vendor": "amd"},
            {"gpu_generation": "rtx-10-series"},
            {"gpu_generation": "unknown"},
            {"windows_build": 19044},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temporary_directory:
                plan = self.build(self.facts(**overrides), temporary_directory)
                self.assertEqual(plan.status, "unsupported")
                self.assertIsNotNone(plan.reason)
                self.assertEqual(plan.actions, ())
                self.assertIsNone(plan.confirmation)

    def test_insufficient_vram_is_an_unsupported_contract(self) -> None:
        facts = self.facts(vram_bytes=8 * 1024**3)
        with tempfile.TemporaryDirectory() as temporary_directory:
            plan = self.build(facts, temporary_directory)

        self.assertEqual(plan.status, "unsupported")
        self.assertEqual(plan.reason, "insufficient_vram")
        self.assertEqual(plan.actions, ())
        self.assertIsNone(plan.confirmation)

    def test_conflicting_existing_artifacts_are_never_overwritten(self) -> None:
        for field in ("portable_status", "model_status"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary_directory:
                plan = self.build(self.facts(**{field: "conflict"}), temporary_directory)
                self.assertEqual(plan.status, "conflict")
                self.assertEqual(plan.reason, f"existing_{field.removesuffix('_status')}_conflict")
                self.assertEqual(plan.actions, ())
                self.assertIsNone(plan.confirmation)

    def test_plan_identity_is_deterministic_and_binds_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install-a",
                plan_root=root / "plans-a",
            )
            second = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install-a",
                plan_root=root / "plans-b",
            )
            different = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install-b",
                plan_root=root / "plans-c",
            )

        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(first.scope_sha256, second.scope_sha256)
        self.assertEqual(first.confirmation, second.confirmation)
        self.assertNotEqual(first.plan_id, different.plan_id)
        self.assertNotEqual(first.scope_sha256, different.scope_sha256)

    def test_scope_record_binds_artifact_sources_licenses_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self.build(self.facts(), temporary_directory)
            record = json.loads(
                (root / "plans" / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )

        artifacts = record["scope"]["artifacts"]
        self.assertEqual(artifacts["comfyui"]["source_url"], self.manifest.comfyui.source_url)
        self.assertEqual(artifacts["comfyui"]["license_id"], self.manifest.comfyui.license_id)
        self.assertEqual(artifacts["model"]["sha256"], self.manifest.model.sha256)
        self.assertEqual(record["scope"]["required_download_bytes"], 9048875554)
        self.assertEqual(record["scope"]["required_disk_bytes"], 30 * 1024**3)

    def test_planning_makes_no_network_or_process_calls(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("network called")),
            mock.patch("subprocess.run", side_effect=AssertionError("process called")),
        ):
            plan = self.build(self.facts(), temporary_directory)
        self.assertEqual(plan.status, "confirmation_required")

    def test_default_bootstrap_paths_are_user_local_and_do_not_create_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            xdg_data_home = Path(temporary_directory) / "xdg-data"
            with mock.patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": str(local_app_data),
                    "XDG_DATA_HOME": str(xdg_data_home),
                },
            ):
                paths = default_bootstrap_paths()

            expected_base = local_app_data if os.name == "nt" else xdg_data_home
            expected_root = expected_base.resolve() / "local-gpu-imagegen" / "bootstrap"
            self.assertEqual(paths.root, expected_root)
            self.assertEqual(paths.cache, expected_root / "cache")
            self.assertEqual(paths.install, expected_root / "runtime")
            self.assertEqual(paths.plans, expected_root / "plans")
            self.assertFalse(paths.root.exists())


if __name__ == "__main__":
    unittest.main()
