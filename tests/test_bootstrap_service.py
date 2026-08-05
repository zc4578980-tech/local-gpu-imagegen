from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.bootstrap_catalog import (  # noqa: E402
    BootstrapFacts,
    build_bootstrap_plan,
    load_bootstrap_manifest,
)
from local_gpu_imagegen.bootstrap_service import apply_bootstrap_plan  # noqa: E402
from local_gpu_imagegen.errors import StateError, ValidationError  # noqa: E402


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

    def test_exact_confirmation_executes_once_and_then_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(return_value=root / "cache" / "verified.safetensors")

            first = apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            second = apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )

        self.assertEqual(first["status"], "installed")
        self.assertEqual(first["plan_id"], plan.plan_id)
        self.assertEqual(first["scope_sha256"], plan.scope_sha256)
        self.assertEqual(second["status"], "already_installed")
        self.assertEqual(second["plan_id"], plan.plan_id)
        self.assertEqual(second["scope_sha256"], plan.scope_sha256)
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
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
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
                return cache_dir / "verified.safetensors"

            def execute() -> None:
                try:
                    result.append(
                        apply_bootstrap_plan(
                            plan.plan_id,
                            plan.confirmation,
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
                        plan.plan_id,
                        plan.confirmation,
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
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(return_value=root / "cache" / "verified.safetensors")
            apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            transaction_path = state_dir / f"{plan.plan_id}.transaction.json"
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["unexpected"] = True
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "invalid_bootstrap_transaction")
        self.assertEqual(downloader.call_count, 1)

    def test_incomplete_completed_transaction_is_not_idempotent_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(return_value=root / "cache" / "verified.safetensors")
            apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )
            transaction_path = state_dir / f"{plan.plan_id}.transaction.json"
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["downloaded_artifacts"] = []
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with self.assertRaises(StateError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation,
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
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(side_effect=RuntimeError("synthetic failure"))

            with self.assertRaises(RuntimeError):
                apply_bootstrap_plan(
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

        self.assertEqual(raised.exception.code, "bootstrap_confirmation_consumed")
        self.assertEqual(downloader.call_count, 1)

    def test_different_confirmation_cannot_replay_completed_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "plans"
            plan = build_bootstrap_plan(
                self.manifest,
                self.facts(),
                install_root=root / "install",
                plan_root=state_dir,
            )
            downloader = mock.Mock(return_value=root / "cache" / "verified.safetensors")
            apply_bootstrap_plan(
                plan.plan_id,
                plan.confirmation,
                state_dir=state_dir,
                downloader=downloader,
            )

            with self.assertRaises(ValidationError) as raised:
                apply_bootstrap_plan(
                    plan.plan_id,
                    plan.confirmation + "-replay",
                    state_dir=state_dir,
                    downloader=downloader,
                )

        self.assertEqual(raised.exception.code, "bootstrap_confirmation_mismatch")
        self.assertEqual(downloader.call_count, 1)


if __name__ == "__main__":
    unittest.main()
