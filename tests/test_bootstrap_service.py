from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import py7zr


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.bootstrap_catalog import (  # noqa: E402
    BootstrapFacts,
    build_bootstrap_plan,
    load_bootstrap_manifest,
)
from local_gpu_imagegen.bootstrap_service import apply_bootstrap_plan  # noqa: E402
from local_gpu_imagegen.errors import ArtifactError, StateError, ValidationError  # noqa: E402


def create_directory_alias(alias: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)


def write_rebound_plan(
    state_dir: Path,
    record: dict[str, object],
) -> tuple[str, str]:
    canonical = json.dumps(
        record["scope"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    scope_sha256 = hashlib.sha256(canonical).hexdigest()
    plan_id = scope_sha256[:24]
    confirmation = f"bootstrap:{plan_id}:{scope_sha256}"
    record.update(
        plan_id=plan_id,
        scope_sha256=scope_sha256,
        confirmation=confirmation,
    )
    (state_dir / f"{plan_id}.json").write_text(json.dumps(record), encoding="utf-8")
    return plan_id, confirmation


class BootstrapServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_bootstrap_manifest(
            ROOT / "profiles" / "bootstrap" / "windows-nvidia.json"
        )

    @staticmethod
    def facts() -> BootstrapFacts:
        return BootstrapFacts(
            platform="win32",
            architecture="amd64",
            gpu_vendor="nvidia",
            gpu_generation="rtx-50-series",
            vram_bytes=16 * 1024**3,
            windows_build=26100,
            free_disk_bytes=40 * 1024**3,
            network_allowed=True,
            endpoint_ready=False,
            portable_status="valid",
            model_status="missing",
        )

    @staticmethod
    def write_portable_archive(root: Path) -> Path:
        source = root / "fixture-source" / "ComfyUI_windows_portable"
        python = source / "python_embeded" / "python.exe"
        main = source / "ComfyUI" / "main.py"
        python.parent.mkdir(parents=True)
        main.parent.mkdir(parents=True)
        python.write_bytes(b"python")
        main.write_bytes(b"main")
        archive_path = root / "portable.7z"
        with py7zr.SevenZipFile(archive_path, "w") as archive:
            archive.writeall(source, arcname="ComfyUI_windows_portable")
        return archive_path

    @staticmethod
    def write_portable_root(root: Path) -> Path:
        portable_root = root / "install" / "ComfyUI_windows_portable"
        python = portable_root / "python_embeded" / "python.exe"
        main = portable_root / "ComfyUI" / "main.py"
        python.parent.mkdir(parents=True)
        main.parent.mkdir(parents=True)
        python.write_bytes(b"python")
        main.write_bytes(b"main")
        return portable_root

    def synthetic_model_only_plan(
        self,
        root: Path,
        state_dir: Path,
    ) -> tuple[str, str, str, Path]:
        self.write_portable_root(root)
        model_file = root / "model.safetensors"
        model_file.write_bytes(b"synthetic-model")
        plan = build_bootstrap_plan(
            self.manifest,
            self.facts(),
            install_root=root / "install",
            plan_root=state_dir,
        )
        plan_path = state_dir / f"{plan.plan_id}.json"
        record = json.loads(plan_path.read_text(encoding="utf-8"))
        payload = model_file.read_bytes()
        record["scope"]["artifacts"]["model"]["byte_size"] = len(payload)
        record["scope"]["artifacts"]["model"]["sha256"] = hashlib.sha256(payload).hexdigest()
        record["scope"]["required_download_bytes"] = len(payload)
        record["scope"]["required_disk_bytes"] = len(payload)
        plan_path.unlink()
        plan_id, confirmation = write_rebound_plan(state_dir, record)
        return plan_id, confirmation, confirmation.rsplit(":", 1)[1], model_file

    def synthetic_plan(
        self,
        root: Path,
        state_dir: Path,
        portable_archive: Path,
        model_file: Path,
        *,
        install_root: Path | None = None,
    ) -> tuple[str, str]:
        facts = self.facts()
        facts = BootstrapFacts(
            platform=facts.platform,
            architecture=facts.architecture,
            gpu_vendor=facts.gpu_vendor,
            gpu_generation=facts.gpu_generation,
            vram_bytes=facts.vram_bytes,
            windows_build=facts.windows_build,
            free_disk_bytes=facts.free_disk_bytes,
            network_allowed=facts.network_allowed,
            endpoint_ready=facts.endpoint_ready,
            portable_status="missing",
            model_status="missing",
        )
        plan = build_bootstrap_plan(
            self.manifest,
            facts,
            install_root=root / "install" if install_root is None else install_root,
            plan_root=state_dir,
        )
        plan_path = state_dir / f"{plan.plan_id}.json"
        record = json.loads(plan_path.read_text(encoding="utf-8"))
        artifacts = record["scope"]["artifacts"]
        for kind, path in (("comfyui", portable_archive), ("model", model_file)):
            payload = path.read_bytes()
            artifacts[kind]["byte_size"] = len(payload)
            artifacts[kind]["sha256"] = hashlib.sha256(payload).hexdigest()
        required_bytes = portable_archive.stat().st_size + model_file.stat().st_size
        record["scope"]["required_download_bytes"] = required_bytes
        record["scope"]["required_disk_bytes"] = required_bytes
        plan_path.unlink()
        return write_rebound_plan(state_dir, record)

    def test_missing_portable_and_model_complete_fixed_install_without_starting_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )

            downloader = mock.Mock(
                side_effect=lambda artifact, _cache: {
                    "comfyui": portable_archive,
                    "model": model_file,
                }[artifact.kind]
            )
            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            repeated = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )

            portable_root = root / "install" / "ComfyUI_windows_portable"
            installed_model = (
                portable_root / "ComfyUI" / "models" / "checkpoints" / "sd_xl_base_1.0.safetensors"
            )
            self.assertEqual(result["status"], "installed")
            self.assertEqual(installed_model.read_bytes(), b"synthetic-model")
            self.assertTrue((portable_root / "python_embeded" / "python.exe").is_file())
            self.assertEqual(
                result["rediscovery"],
                {
                    "status": "deferred",
                    "mode": "api_only",
                    "next_action": "start_managed_comfyui_then_rediscover",
                },
            )
            self.assertEqual(result["setup"]["status"], "ready")
            self.assertIn(
                str(portable_root.resolve()),
                result["setup"]["managed_comfyui_server_command"],
            )
            self.assertEqual(repeated["status"], "already_installed")
            self.assertEqual(repeated["rediscovery"], result["rediscovery"])
            self.assertEqual(repeated["setup"], result["setup"])
            self.assertEqual(downloader.call_count, 2)

    def test_model_failure_retains_promoted_portable_and_consumes_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )

            def fail_model_download(artifact, _cache):
                if artifact.kind == "comfyui":
                    return portable_archive
                raise RuntimeError("synthetic model failure")

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=fail_model_download,
            )

            portable_root = root / "install" / "ComfyUI_windows_portable"
            transaction = json.loads(
                (state_dir / f"{plan_id}.transaction.json").read_text(encoding="utf-8")
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "recoverable_failure")
            self.assertTrue((portable_root / "ComfyUI" / "main.py").is_file())
            self.assertTrue(portable_archive.is_file())
            self.assertEqual(
                result["retained_state"],
                {
                    "portable": "installed",
                    "model": "missing",
                    "verified_cache_artifacts": [self.manifest.comfyui.artifact_id],
                },
            )
            self.assertEqual(
                result["recoverable_next_actions"],
                ["create_new_plan_reusing_portable"],
            )
            self.assertEqual(transaction["status"], "failed")
            self.assertEqual(transaction["retained_state"], result["retained_state"])
            self.assertEqual(
                transaction["recoverable_next_actions"],
                result["recoverable_next_actions"],
            )
            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=fail_model_download,
                )
            self.assertEqual(replayed.exception.code, "bootstrap_confirmation_consumed")

    def test_disappeared_valid_portable_persists_missing_and_replays_as_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_root = self.write_portable_root(root)
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            shutil.rmtree(portable_root)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            first = apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            self.assertEqual(first["status"], "recoverable_failure")
            self.assertEqual(first["retained_state"]["portable"], "missing")
            self.assertEqual(replayed.exception.code, "bootstrap_confirmation_consumed")
            self.assertEqual(
                replayed.exception.details["retained_state"]["portable"],
                "missing",
            )
            downloader.assert_not_called()

    def test_disappeared_valid_model_persists_missing_and_replays_as_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_path = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
                / "sd_xl_base_1.0.safetensors"
            )
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"synthetic-model")
            base_facts = self.facts()
            facts = BootstrapFacts(
                platform=base_facts.platform,
                architecture=base_facts.architecture,
                gpu_vendor=base_facts.gpu_vendor,
                gpu_generation=base_facts.gpu_generation,
                vram_bytes=base_facts.vram_bytes,
                windows_build=base_facts.windows_build,
                free_disk_bytes=base_facts.free_disk_bytes,
                network_allowed=base_facts.network_allowed,
                endpoint_ready=base_facts.endpoint_ready,
                portable_status="missing",
                model_status="valid",
            )
            plan = build_bootstrap_plan(
                self.manifest,
                facts,
                install_root=root / "install",
                plan_root=state_dir,
            )
            plan_path = state_dir / f"{plan.plan_id}.json"
            record = json.loads(plan_path.read_text(encoding="utf-8"))
            portable_payload = portable_archive.read_bytes()
            model_payload = model_path.read_bytes()
            record["scope"]["artifacts"]["comfyui"]["byte_size"] = len(portable_payload)
            record["scope"]["artifacts"]["comfyui"]["sha256"] = hashlib.sha256(
                portable_payload
            ).hexdigest()
            record["scope"]["artifacts"]["model"]["byte_size"] = len(model_payload)
            record["scope"]["artifacts"]["model"]["sha256"] = hashlib.sha256(
                model_payload
            ).hexdigest()
            record["scope"]["required_download_bytes"] = len(portable_payload)
            record["scope"]["required_disk_bytes"] = len(portable_payload)
            plan_path.unlink()
            plan_id, confirmation = write_rebound_plan(state_dir, record)
            shutil.rmtree(root / "install")
            downloader = mock.Mock(return_value=portable_archive)

            first = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            self.assertEqual(first["status"], "recoverable_failure")
            self.assertEqual(first["retained_state"]["portable"], "installed")
            self.assertEqual(first["retained_state"]["model"], "missing")
            self.assertEqual(replayed.exception.code, "bootstrap_confirmation_consumed")
            self.assertEqual(
                replayed.exception.details["retained_state"]["model"],
                "missing",
            )
            self.assertEqual(downloader.call_count, 1)

    def test_unowned_portable_appearing_after_snapshot_is_never_reported_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )
            portable_root = root / "install" / "ComfyUI_windows_portable"

            def create_unowned_portable_then_fail(_artifact, _cache):
                portable_root.mkdir(parents=True)
                (portable_root / "unowned.txt").write_text("keep", encoding="utf-8")
                raise RuntimeError("synthetic failure after drift")

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=create_unowned_portable_then_fail,
            )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["retained_state"]["portable"], "unsafe_drift")
            self.assertEqual(result["recoverable_next_actions"], ["create_new_bootstrap_plan"])
            self.assertEqual(
                (portable_root / "unowned.txt").read_text(encoding="utf-8"),
                "keep",
            )

    def test_replay_never_upgrades_marker_valid_late_portable_drift(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )
            portable_root = root / "install" / "ComfyUI_windows_portable"

            def create_marker_valid_drift_then_fail(*_args, **_kwargs):
                python = portable_root / "python_embeded" / "python.exe"
                main = portable_root / "ComfyUI" / "main.py"
                python.parent.mkdir(parents=True)
                main.parent.mkdir(parents=True)
                python.write_bytes(b"external-python")
                main.write_bytes(b"external-main")
                raise RuntimeError("synthetic late portable drift")

            with mock.patch.object(
                bootstrap_service,
                "safe_extract_portable",
                side_effect=create_marker_valid_drift_then_fail,
            ):
                first = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda artifact, _cache: {
                        "comfyui": portable_archive,
                        "model": model_file,
                    }[artifact.kind],
                )

            self.assertEqual(first["retained_state"]["portable"], "unsafe_drift")
            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )

            self.assertEqual(replayed.exception.code, "bootstrap_confirmation_consumed")
            self.assertEqual(
                replayed.exception.details["retained_state"]["portable"],
                "unsafe_drift",
            )
            self.assertEqual(
                replayed.exception.details["recoverable_next_actions"],
                ["create_new_bootstrap_plan"],
            )

    def test_unowned_model_appearing_after_snapshot_is_never_reported_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, _model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            destination = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
                / "sd_xl_base_1.0.safetensors"
            )

            def create_unowned_model_then_fail(_artifact, _cache):
                destination.parent.mkdir(parents=True)
                destination.write_bytes(b"unowned-model")
                raise RuntimeError("synthetic failure after drift")

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=create_unowned_model_then_fail,
            )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["retained_state"]["model"], "unsafe_drift")
            self.assertEqual(
                result["recoverable_next_actions"],
                ["create_new_plan_reusing_portable"],
            )
            self.assertEqual(destination.read_bytes(), b"unowned-model")

    def test_keyboard_interrupt_after_portable_commit_leaves_truthful_resumable_journal(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )
            original_write = bootstrap_service._atomic_write_state
            interrupted = False

            def interrupt_after_portable_write(path, value, state_root, expected_root_stat):
                nonlocal interrupted
                original_write(path, value, state_root, expected_root_stat)
                retained = value.get("retained_state", {})
                if (
                    not interrupted
                    and value.get("status") == "in_progress"
                    and retained.get("portable") == "installed"
                    and retained.get("model") == "missing"
                ):
                    interrupted = True
                    raise KeyboardInterrupt("after portable commit")

            with mock.patch.object(
                bootstrap_service,
                "_atomic_write_state",
                side_effect=interrupt_after_portable_write,
            ), self.assertRaises(KeyboardInterrupt):
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda artifact, _cache: {
                        "comfyui": portable_archive,
                        "model": model_file,
                    }[artifact.kind],
                )

            transaction = json.loads(
                (state_dir / f"{plan_id}.transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual(transaction["status"], "in_progress")
            self.assertEqual(transaction["retained_state"]["portable"], "installed")
            self.assertEqual(transaction["retained_state"]["model"], "missing")
            self.assertEqual(
                transaction["recoverable_next_actions"],
                ["create_new_plan_reusing_portable"],
            )
            self.assertFalse((state_dir / f".{plan_id}.apply.lock").exists())
            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )
            self.assertEqual(
                replayed.exception.details["retained_state"]["portable"],
                transaction["retained_state"]["portable"],
            )
            self.assertEqual(
                replayed.exception.details["retained_state"]["model"],
                transaction["retained_state"]["model"],
            )
            self.assertEqual(
                replayed.exception.details["retained_state"][
                    "verified_cache_artifacts"
                ],
                [],
            )
            self.assertEqual(
                replayed.exception.details["recoverable_next_actions"],
                transaction["recoverable_next_actions"],
            )

    def test_system_exit_after_model_commit_leaves_complete_retained_install_journal(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )
            original_write = bootstrap_service._atomic_write_state
            interrupted = False

            def interrupt_after_model_write(path, value, state_root, expected_root_stat):
                nonlocal interrupted
                original_write(path, value, state_root, expected_root_stat)
                retained = value.get("retained_state", {})
                if (
                    not interrupted
                    and value.get("status") == "in_progress"
                    and retained.get("portable") == "installed"
                    and retained.get("model") == "installed"
                ):
                    interrupted = True
                    raise SystemExit("after model commit")

            with mock.patch.object(
                bootstrap_service,
                "_atomic_write_state",
                side_effect=interrupt_after_model_write,
            ), self.assertRaises(SystemExit):
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda artifact, _cache: {
                        "comfyui": portable_archive,
                        "model": model_file,
                    }[artifact.kind],
                )

            transaction = json.loads(
                (state_dir / f"{plan_id}.transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual(transaction["status"], "in_progress")
            self.assertEqual(transaction["retained_state"]["portable"], "installed")
            self.assertEqual(transaction["retained_state"]["model"], "installed")
            self.assertEqual(
                transaction["recoverable_next_actions"],
                ["create_new_plan_reusing_retained_install"],
            )
            self.assertFalse((state_dir / f".{plan_id}.apply.lock").exists())
            self.assertEqual(
                list((root / "install").rglob("*.staging")),
                [],
            )

    def test_replay_requires_fresh_plan_after_portable_promotion_journal_gap(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
            )
            original_extract = bootstrap_service.safe_extract_portable

            def interrupt_after_promotion(*args, **kwargs):
                original_extract(*args, **kwargs)
                raise KeyboardInterrupt("portable promoted before journal update")

            with mock.patch.object(
                bootstrap_service,
                "safe_extract_portable",
                side_effect=interrupt_after_promotion,
            ), self.assertRaises(KeyboardInterrupt):
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda artifact, _cache: {
                        "comfyui": portable_archive,
                        "model": model_file,
                    }[artifact.kind],
                )

            transaction = json.loads(
                (state_dir / f"{plan_id}.transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                transaction["downloaded_artifacts"],
                [self.manifest.comfyui.artifact_id],
            )
            self.assertEqual(transaction["retained_state"]["portable"], "missing")

            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )

            self.assertEqual(
                replayed.exception.details["retained_state"]["portable"],
                "unsafe_drift",
            )
            self.assertEqual(
                replayed.exception.details["recoverable_next_actions"],
                ["create_new_bootstrap_plan"],
            )

    def test_replay_requires_fresh_plan_after_model_promotion_journal_gap(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            original_place = bootstrap_service._place_model_no_overwrite

            def interrupt_after_promotion(*args, **kwargs):
                original_place(*args, **kwargs)
                raise SystemExit("model promoted before journal update")

            with mock.patch.object(
                bootstrap_service,
                "_place_model_no_overwrite",
                side_effect=interrupt_after_promotion,
            ), self.assertRaises(SystemExit):
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            transaction = json.loads(
                (state_dir / f"{plan_id}.transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                transaction["downloaded_artifacts"],
                [self.manifest.model.artifact_id],
            )
            self.assertEqual(transaction["retained_state"]["model"], "missing")

            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )

            self.assertEqual(
                replayed.exception.details["retained_state"]["model"],
                "unsafe_drift",
            )
            self.assertEqual(
                replayed.exception.details["recoverable_next_actions"],
                ["create_new_plan_reusing_portable"],
            )

    def test_impossible_retained_provenance_is_rejected_on_replay(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            with mock.patch.object(
                bootstrap_service,
                "_place_model_no_overwrite",
                side_effect=RuntimeError("synthetic placement failure"),
            ):
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            transaction_path = state_dir / f"{plan_id}.transaction.json"
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["retained_state"]["portable"] = "installed"
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )

            self.assertEqual(raised.exception.code, "invalid_bootstrap_transaction")

    def test_failed_replay_reports_only_current_exact_cache_evidence(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            plan_record = json.loads(
                (state_dir / f"{plan_id}.json").read_text(encoding="utf-8")
            )
            model_record = plan_record["scope"]["artifacts"]["model"]
            cache_path = root / "cache" / f"{model_record['sha256']}.safetensors"
            with mock.patch.object(
                bootstrap_service,
                "_place_model_no_overwrite",
                side_effect=RuntimeError("synthetic placement failure"),
            ):
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            with self.assertRaises(StateError) as missing_cache:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )
            self.assertEqual(
                missing_cache.exception.details["retained_state"][
                    "verified_cache_artifacts"
                ],
                [],
            )

            cache_path.parent.mkdir()
            cache_path.write_bytes(b"x" * model_file.stat().st_size)
            with self.assertRaises(StateError) as wrong_cache:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )
            self.assertEqual(
                wrong_cache.exception.details["retained_state"][
                    "verified_cache_artifacts"
                ],
                [],
            )

            cache_path.write_bytes(model_file.read_bytes())
            with self.assertRaises(StateError) as exact_cache:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )
            self.assertEqual(
                exact_cache.exception.details["retained_state"][
                    "verified_cache_artifacts"
                ],
                [self.manifest.model.artifact_id],
            )

    def test_model_destination_drift_is_preserved_and_reported_pre_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            portable_root = root / "install" / "ComfyUI_windows_portable"
            destination = (
                portable_root / "ComfyUI" / "models" / "checkpoints" / "sd_xl_base_1.0.safetensors"
            )
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"pre-existing-model")
            config = portable_root / "ComfyUI" / "user" / "default" / "config.ini"
            config.parent.mkdir(parents=True)
            config.write_text("keep=true", encoding="utf-8")

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=lambda _artifact, _cache: model_file,
            )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["error"], {"code": "model_destination_conflict"})
            self.assertEqual(result["retained_state"]["model"], "pre_existing")
            self.assertEqual(destination.read_bytes(), b"pre-existing-model")
            self.assertEqual(config.read_text(encoding="utf-8"), "keep=true")
            self.assertEqual(list(destination.parent.glob(".*.staging")), [])

            with self.assertRaises(StateError) as replayed:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=AssertionError("download called")),
                )

            self.assertEqual(replayed.exception.code, "bootstrap_confirmation_consumed")
            self.assertEqual(
                replayed.exception.details["retained_state"]["model"],
                "pre_existing",
            )

    def test_injected_downloader_output_is_reverified_before_model_placement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            untrusted_file = root / "untrusted.safetensors"
            untrusted_file.write_bytes(b"x" * model_file.stat().st_size)

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=lambda _artifact, _cache: untrusted_file,
            )

            destination = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
                / "sd_xl_base_1.0.safetensors"
            )
            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["error"], {"code": "downloaded_artifact_invalid"})
            self.assertFalse(destination.exists())
            self.assertTrue(untrusted_file.is_file())

    def test_model_source_swap_after_verification_is_rejected_before_copy_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            original_size = model_file.stat().st_size
            replacement = root / "replacement-model.safetensors"
            replacement.write_bytes(b"x" * 4096)
            displaced = root / "verified-model.safetensors"
            original_open = Path.open
            source_open_count = 0
            copied_read_sizes: list[int] = []

            class RecordingReader:
                def __init__(self, stream) -> None:
                    self.stream = stream

                def __enter__(self):
                    self.stream.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.stream, name)

                def read(self, size=-1):
                    copied_read_sizes.append(size)
                    return self.stream.read(size)

            def replace_before_model_copy(path: Path, *args, **kwargs):
                nonlocal source_open_count
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == model_file and "r" in mode:
                    source_open_count += 1
                    if source_open_count == 2:
                        model_file.replace(displaced)
                        replacement.replace(model_file)
                        return RecordingReader(original_open(path, *args, **kwargs))
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", new=replace_before_model_copy):
                result = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["error"], {"code": "downloaded_artifact_invalid"})
            self.assertTrue(
                not copied_read_sizes or max(copied_read_sizes) <= original_size + 1
            )

    @unittest.skipUnless(os.name == "nt", "Windows Path.open staging injection")
    def test_replaced_empty_model_parent_is_never_removed_by_failure_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            checkpoints = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
            )
            destination = checkpoints / "sd_xl_base_1.0.safetensors"
            staging = destination.with_name(f".{destination.name}.{plan_id}.staging")
            displaced = root / "owned-checkpoints"
            original_open = Path.open

            def replace_parent_before_staging_open(path: Path, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if "x" in mode:
                    self.assertEqual(path.parent.resolve(), checkpoints.resolve())
                    self.assertTrue(path.name.endswith(".staging"))
                    checkpoints.replace(displaced)
                    checkpoints.mkdir()
                    raise OSError("synthetic staging failure after parent replacement")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", new=replace_parent_before_staging_open):
                result = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertTrue(checkpoints.is_dir())
            self.assertEqual(list(checkpoints.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows junction swap-back semantics")
    def test_model_writer_swap_back_never_writes_nonempty_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            checkpoints = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
            )
            destination = checkpoints / "sd_xl_base_1.0.safetensors"
            staging = destination.with_name(f".{destination.name}.{plan_id}.staging")
            displaced = root / "displaced-checkpoints"
            external = root / "external-checkpoints"
            external.mkdir()
            original_open = Path.open
            original_lstat = Path.lstat
            swapped = False
            restored = False

            def redirect_staging_open(path: Path, *args, **kwargs):
                nonlocal swapped
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == staging and "x" in mode and not swapped:
                    checkpoints.replace(displaced)
                    create_directory_alias(checkpoints, external)
                    swapped = True
                return original_open(path, *args, **kwargs)

            def restore_after_path_stat(path: Path, *args, **kwargs):
                nonlocal restored
                current = original_lstat(path, *args, **kwargs)
                if path == staging and swapped and not restored:
                    os.rmdir(checkpoints)
                    displaced.replace(checkpoints)
                    restored = True
                return current

            with mock.patch.object(
                Path,
                "open",
                new=redirect_staging_open,
            ), mock.patch.object(Path, "lstat", new=restore_after_path_stat):
                result = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertTrue(swapped)
            self.assertTrue(restored)
            external_file = external / staging.name
            self.assertTrue(not external_file.exists() or external_file.read_bytes() == b"")

    def test_downloader_source_equal_to_model_staging_is_never_unlinked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            destination = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
                / "sd_xl_base_1.0.safetensors"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = destination.with_name(f".{destination.name}.{plan_id}.staging")
            staging.write_bytes(model_file.read_bytes())

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=lambda _artifact, _cache: staging,
            )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertTrue(staging.is_file())
            self.assertEqual(staging.read_bytes(), model_file.read_bytes())
            self.assertEqual(
                result["retained_state"]["verified_cache_artifacts"],
                [self.manifest.model.artifact_id],
            )

    def test_model_placement_rejects_a_link_like_parent_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            external = root / "external-models"
            external.mkdir()
            models = root / "install" / "ComfyUI_windows_portable" / "ComfyUI" / "models"
            try:
                create_directory_alias(models, external)
            except OSError as error:
                self.skipTest(f"directory alias creation unavailable: {type(error).__name__}")

            result = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=lambda _artifact, _cache: model_file,
            )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["error"], {"code": "unsafe_model_destination"})
            self.assertEqual(list(external.rglob("*.safetensors")), [])

    def test_model_parent_swap_after_handle_promotion_never_writes_external_model(self) -> None:
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            portable_root = root / "install" / "ComfyUI_windows_portable"
            models = portable_root / "ComfyUI" / "models"
            displaced = root / "displaced-models"
            external = root / "external-models"
            (external / "checkpoints").mkdir(parents=True)
            original_promote = bootstrap_service.promote_owned_path_no_replace
            swapped = False

            def swap_parent_after_promotion(*args, **kwargs) -> None:
                nonlocal swapped
                original_promote(*args, **kwargs)
                models.replace(displaced)
                create_directory_alias(models, external)
                swapped = True

            with mock.patch.object(
                bootstrap_service,
                "promote_owned_path_no_replace",
                side_effect=swap_parent_after_promotion,
            ):
                result = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["error"], {"code": "unsafe_model_destination"})
            self.assertEqual(list(external.rglob("*.safetensors")), [])
            self.assertEqual(
                (
                    displaced
                    / "checkpoints"
                    / "sd_xl_base_1.0.safetensors"
                ).read_bytes(),
                model_file.read_bytes(),
            )

    @unittest.skipUnless(os.name == "nt", "Windows handle-relative promotion semantics")
    def test_promotion_time_swap_back_returns_model_to_captured_parent(self) -> None:
        import local_gpu_imagegen._filesystem_capability as filesystem_capability
        import local_gpu_imagegen.bootstrap_service as bootstrap_service

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            checkpoints = (
                root
                / "install"
                / "ComfyUI_windows_portable"
                / "ComfyUI"
                / "models"
                / "checkpoints"
            )
            destination = checkpoints / "sd_xl_base_1.0.safetensors"
            staging = destination.with_name(f".{destination.name}.{plan_id}.staging")
            displaced = root / "captured-checkpoints"
            external = root / "external-checkpoints"
            external.mkdir()
            external_staging = external / staging.name
            original_descriptor_promote = filesystem_capability._promote_descriptor_no_replace
            original_promote = bootstrap_service.promote_owned_path_no_replace
            swapped = False
            restored = False

            def swap_during_descriptor_promotion(*args, **kwargs) -> None:
                nonlocal swapped
                staging.replace(external_staging)
                checkpoints.replace(displaced)
                create_directory_alias(checkpoints, external)
                swapped = True
                original_descriptor_promote(*args, **kwargs)

            def restore_after_capability_closes(*args, **kwargs):
                nonlocal restored
                try:
                    return original_promote(*args, **kwargs)
                finally:
                    if swapped:
                        os.rmdir(checkpoints)
                        displaced.replace(checkpoints)
                        restored = True

            with mock.patch.object(
                filesystem_capability,
                "_promote_descriptor_no_replace",
                side_effect=swap_during_descriptor_promotion,
            ), mock.patch.object(
                bootstrap_service,
                "promote_owned_path_no_replace",
                side_effect=restore_after_capability_closes,
            ):
                result = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda _artifact, _cache: model_file,
                )

            self.assertEqual(result["status"], "installed")
            self.assertTrue(swapped)
            self.assertTrue(restored)
            self.assertEqual(destination.read_bytes(), model_file.read_bytes())
            self.assertEqual(list(external.rglob("*")), [])

    def test_install_root_parent_swap_during_staging_creation_never_promotes_external_portable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            planned_parent = root / "planned-parent"
            install_root = planned_parent / "install"
            portable_archive = self.write_portable_archive(root)
            model_file = root / "model.safetensors"
            model_file.write_bytes(b"synthetic-model")
            plan_id, confirmation = self.synthetic_plan(
                root,
                state_dir,
                portable_archive,
                model_file,
                install_root=install_root,
            )
            displaced = root / "displaced-parent"
            external = root / "external-parent"
            (external / "install").mkdir(parents=True)
            original_mkdir = Path.mkdir
            swapped = False

            def swap_parent_before_staging(path: Path, *args, **kwargs):
                nonlocal swapped
                if path.name == f".local-gpu-imagegen-{plan_id}.staging" and not swapped:
                    planned_parent.replace(displaced)
                    create_directory_alias(planned_parent, external)
                    swapped = True
                return original_mkdir(path, *args, **kwargs)

            with mock.patch.object(Path, "mkdir", new=swap_parent_before_staging):
                result = apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=lambda artifact, _cache: {
                        "comfyui": portable_archive,
                        "model": model_file,
                    }[artifact.kind],
                )

            self.assertEqual(result["status"], "recoverable_failure")
            self.assertEqual(result["error"], {"code": "invalid_install_root"})
            self.assertFalse((external / "install" / "ComfyUI_windows_portable").exists())
            retained_staging = list(
                (external / "install").glob(".local-gpu-imagegen-*.staging")
            )
            self.assertEqual(len(retained_staging), 0 if os.name == "nt" else 1)
            if retained_staging:
                self.assertEqual(list(retained_staging[0].iterdir()), [])

    def test_exact_confirmation_executes_once_and_then_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            downloader = mock.Mock(return_value=model_file)

            first = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            second = apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )

        self.assertEqual(first["status"], "installed")
        self.assertEqual(first["plan_id"], plan_id)
        self.assertEqual(first["scope_sha256"], scope_sha256)
        self.assertEqual(second["status"], "already_installed")
        self.assertEqual(second["plan_id"], plan_id)
        self.assertEqual(second["scope_sha256"], scope_sha256)
        self.assertEqual(downloader.call_count, 1)

    def test_duplicate_plan_fields_are_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record_path = state_dir / f"{plan.plan_id}.json"
            duplicate = record_path.read_text(encoding="utf-8").replace(
                '"schema_version": 1,',
                '"schema_version": 1, "schema_version": 1,',
                1,
            )
            record_path.write_text(duplicate, encoding="utf-8")
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_unknown_plan_fields_are_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record_path = state_dir / f"{plan.plan_id}.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["unexpected"] = True
            record_path.write_text(json.dumps(record), encoding="utf-8")
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_non_executable_scope_is_rejected_even_with_recomputed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            original_path = state_dir / f"{plan.plan_id}.json"
            record = json.loads(original_path.read_text(encoding="utf-8"))
            record["scope"]["status"] = "ready"
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_plan_not_executable")
        downloader.assert_not_called()

    def test_unknown_action_is_rejected_even_with_recomputed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record = json.loads(
                (state_dir / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )
            record["scope"]["actions"][1]["kind"] = "ignore_model"
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_unknown_scope_field_is_rejected_even_with_recomputed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record = json.loads(
                (state_dir / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )
            record["scope"]["unexpected"] = True
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_unknown_artifact_field_is_rejected_without_consuming_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record = json.loads(
                (state_dir / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )
            record["scope"]["artifacts"]["model"]["unexpected"] = True
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            transaction_path = state_dir / f"{changed_plan_id}.transaction.json"
            self.assertFalse(transaction_path.exists())

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_invalid_artifact_metadata_is_rejected_without_consuming_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record = json.loads(
                (state_dir / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )
            record["scope"]["artifacts"]["model"]["byte_size"] = "6938078334"
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            transaction_path = state_dir / f"{changed_plan_id}.transaction.json"
            self.assertFalse(transaction_path.exists())

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_download_byte_total_must_match_frozen_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record = json.loads(
                (state_dir / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )
            record["scope"]["required_download_bytes"] += 1
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            transaction_path = state_dir / f"{changed_plan_id}.transaction.json"
            self.assertFalse(transaction_path.exists())

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_non_executable_facts_are_rejected_even_with_recomputed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record = json.loads(
                (state_dir / f"{plan.plan_id}.json").read_text(encoding="utf-8")
            )
            record["scope"]["facts"]["network_allowed"] = False
            changed_plan_id, changed_confirmation = write_rebound_plan(state_dir, record)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    changed_plan_id,
                    changed_confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            transaction_path = state_dir / f"{changed_plan_id}.transaction.json"
            self.assertFalse(transaction_path.exists())

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_concurrent_confirmation_cannot_enter_downloader_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            entered = threading.Event()
            release = threading.Event()
            calls: list[str] = []
            result: list[dict[str, object]] = []
            failure: list[BaseException] = []

            def downloader(artifact: object, cache_dir: Path) -> Path:
                calls.append("download")
                entered.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("test did not release downloader")
                return model_file

            def execute() -> None:
                try:
                    result.append(
                        apply_bootstrap_plan(
                            plan_id,
                            confirmation,
                            state_dir=state_dir,
                            downloader=downloader,
                        )
                    )
                except BaseException as error:
                    failure.append(error)

            worker = threading.Thread(target=execute)
            worker.start()
            self.assertTrue(entered.wait(timeout=5))
            try:
                with self.assertRaises(StateError) as raised:
                    apply_bootstrap_plan(
                        plan_id,
                        confirmation,
                        state_dir=state_dir,
                        downloader=downloader,
                    )
            finally:
                release.set()
                worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(failure, [])
        self.assertEqual(result[0]["status"], "installed")
        self.assertEqual(raised.exception.code, "bootstrap_confirmation_consumed")
        self.assertEqual(calls, ["download"])

    def test_state_directory_alias_is_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            alias = root / "plans-alias"
            create_directory_alias(alias, state_dir)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=alias,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_state_dir")
        downloader.assert_not_called()

    def test_install_root_identity_drift_is_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            install_root = root / "install"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=install_root,
                plan_root=state_dir,
            )
            redirect_target = root / "redirect-target"
            redirect_target.mkdir()
            create_directory_alias(install_root, redirect_target)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_plan_path_drift")
        downloader.assert_not_called()

    def test_hard_linked_plan_record_is_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record_path = state_dir / f"{plan.plan_id}.json"
            external_record = root / "external-plan.json"
            record_path.replace(external_record)
            os.link(external_record, record_path)
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_plan")
        downloader.assert_not_called()

    def test_edited_completed_transaction_is_not_treated_as_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            downloader = mock.Mock(return_value=model_file)
            apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            transaction_path = state_dir / f"{plan_id}.transaction.json"
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["retained_state"]["model"] = "missing"
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_transaction")
        self.assertEqual(downloader.call_count, 1)

    def test_incomplete_completed_transaction_is_not_idempotent_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            downloader = mock.Mock(return_value=model_file)
            apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            transaction_path = state_dir / f"{plan_id}.transaction.json"
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["downloaded_artifacts"] = []
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_transaction")
        self.assertEqual(downloader.call_count, 1)

    def test_missing_confirmation_is_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(ValidationError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    "",
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_confirmation_required")
        downloader.assert_not_called()

    def test_mismatched_confirmation_is_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(ValidationError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    f"bootstrap:{plan.plan_id}:{'f' * 64}",
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_confirmation_mismatch")
        downloader.assert_not_called()

    def test_edited_scope_is_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            record_path = state_dir / f"{plan.plan_id}.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["scope"]["required_download_bytes"] += 1
            record_path.write_text(json.dumps(record), encoding="utf-8")
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(ValidationError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_plan_identity_mismatch")
        downloader.assert_not_called()

    def test_wrong_plan_id_is_stale_and_does_not_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            wrong_plan_id = "f" * 24 if plan.plan_id != "f" * 24 else "e" * 24
            downloader = mock.Mock(side_effect=AssertionError("download called"))

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    wrong_plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_plan_not_found")
        downloader.assert_not_called()

    def test_failed_execution_consumes_confirmation_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            self.write_portable_root(root)
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(side_effect=RuntimeError("synthetic failure"))

            failed = apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(failed["status"], "recoverable_failure")
        self.assertEqual(failed["error"], {"code": "bootstrap_execution_failed"})
        self.assertEqual(raised.exception.code, "bootstrap_confirmation_consumed")
        self.assertEqual(downloader.call_count, 1)

    def test_untrusted_exception_code_is_never_persisted_or_returned(self) -> None:
        class UntrustedFailure(RuntimeError):
            code = "C:\\private\\model\n" + "secret" * 200

        secret_code = "C:\\private\\model\n" + "secret" * 200
        failures = (
            UntrustedFailure("do not persist"),
            ArtifactError(secret_code, "do not persist"),
        )
        for failure in failures:
            with (
                self.subTest(error_type=type(failure).__name__),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                state_dir = root / "plans"
                self.write_portable_root(root)
                plan = build_bootstrap_plan(
                    self.manifest,
                    self.facts(),
                    install_root=root / "install",
                    plan_root=state_dir,
                )

                downloader = mock.Mock(side_effect=failure)
                result = apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

                transaction = json.loads(
                    (state_dir / f"{plan.plan_id}.transaction.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(result["error"], {"code": "bootstrap_execution_failed"})
                self.assertEqual(transaction["failure_code"], "bootstrap_execution_failed")
                self.assertNotIn("private", json.dumps(transaction))
                self.assertNotIn("secret", json.dumps(result))
                downloader.assert_called_once()

    def test_non_string_artifact_error_codes_use_the_fixed_failure_code(self) -> None:
        for code in ([], {}, 17):
            with (
                self.subTest(code_type=type(code).__name__),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                state_dir = root / "plans"
                self.write_portable_root(root)
                plan = build_bootstrap_plan(
                    self.manifest,
                    self.facts(),
                    install_root=root / "install",
                    plan_root=state_dir,
                )
                failure = ArtifactError(code, "do not persist")

                result = apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=mock.Mock(side_effect=failure),
                )

                transaction = json.loads(
                    (state_dir / f"{plan.plan_id}.transaction.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(result["error"], {"code": "bootstrap_execution_failed"})
                self.assertEqual(transaction["status"], "failed")
                self.assertEqual(transaction["failure_code"], "bootstrap_execution_failed")

    def test_edited_failed_transaction_with_unknown_code_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            self.write_portable_root(root)
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(side_effect=RuntimeError("synthetic failure"))
            result = apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            transaction_path = state_dir / f"{plan.plan_id}.transaction.json"
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["failure_code"] = "C:\\private\\model\nsecret"
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

            self.assertEqual(result["error"], {"code": "bootstrap_execution_failed"})
            self.assertEqual(raised.exception.code, "invalid_bootstrap_transaction")
            downloader.assert_called_once()

    def test_different_confirmation_cannot_replay_completed_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan_id, confirmation, _scope_sha256, model_file = self.synthetic_model_only_plan(
                root,
                state_dir,
            )
            downloader = mock.Mock(return_value=model_file)
            apply_bootstrap_plan(
                plan_id,
                confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )

            with self.assertRaises(ValidationError) as raised:
                apply_bootstrap_plan(
                    plan_id,
                    confirmation + "-replay",
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_confirmation_mismatch")
        self.assertEqual(downloader.call_count, 1)


if __name__ == "__main__":
    unittest.main()
