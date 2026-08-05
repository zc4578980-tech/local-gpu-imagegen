from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.bootstrap_catalog import (  # noqa: E402
    MAX_ARTIFACT_BYTES,
    load_bootstrap_manifest,
    validate_bootstrap_manifest,
)
from local_gpu_imagegen.errors import ValidationError  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
