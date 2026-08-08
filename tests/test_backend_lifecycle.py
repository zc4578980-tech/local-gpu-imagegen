from __future__ import annotations

import tempfile
import threading
import time
import unittest
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backend_lifecycle import (  # noqa: E402
    BackendLifecycleError,
    ComfyUIProcessSupervisor,
    build_comfyui_start_config,
)


def portable_root(parent: Path) -> Path:
    root = parent / "ComfyUI_windows_portable"
    python = root / "python_embeded" / "python.exe"
    main = root / "ComfyUI" / "main.py"
    python.parent.mkdir(parents=True)
    main.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    main.write_text("# ComfyUI", encoding="utf-8")
    return root


class FakeProcess:
    def __init__(self, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False
        self.wait_calls: list[int] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: int) -> int:
        self.wait_calls.append(timeout)
        return 0


class RecordingFactory:
    def __init__(self, process: FakeProcess | None = None) -> None:
        self.process = FakeProcess() if process is None else process
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> FakeProcess:
        self.calls.append((command, kwargs))
        return self.process


class ExitingProcess(FakeProcess):
    def __init__(self, stderr_text: str, pid: int = 4242) -> None:
        super().__init__(pid=pid, returncode=1)
        self.stderr_text = stderr_text


class BackendLifecycleTests(unittest.TestCase):
    def test_independent_supervisors_coordinate_one_cold_start_and_reuse_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(
                portable_root(parent), timeout_seconds=2
            )
            factory = RecordingFactory()
            launched = threading.Event()
            healthy = threading.Event()

            def process_factory(command: list[str], **kwargs: object) -> FakeProcess:
                process = factory(command, **kwargs)
                launched.set()
                return process

            def probe(_url: str, _timeout: float) -> dict[str, object]:
                return {
                    "available": healthy.is_set(),
                    "queue_running": 0 if healthy.is_set() else None,
                    "queue_pending": 0 if healthy.is_set() else None,
                }

            supervisors = [
                ComfyUIProcessSupervisor(
                    config,
                    process_factory=process_factory,
                    probe=probe,
                    state_dir=parent / "state",
                    platform_name="nt",
                    environ={},
                )
                for _ in range(2)
            ]
            reports: list[dict[str, object]] = []
            errors: list[BaseException] = []

            def start(supervisor: ComfyUIProcessSupervisor) -> None:
                try:
                    reports.append(supervisor.start())
                except BaseException as error:  # pragma: no cover - asserted below
                    errors.append(error)

            threads = [threading.Thread(target=start, args=(item,)) for item in supervisors]
            for thread in threads:
                thread.start()
            self.assertTrue(launched.wait(1))
            time.sleep(0.05)
            self.assertEqual(len(factory.calls), 1)
            healthy.set()
            for thread in threads:
                thread.join(2)

        self.assertEqual(errors, [])
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(
            sorted(report["status"] for report in reports),
            ["started_owned", "waited_for_existing"],
        )

    def test_config_builds_the_fixed_isolated_loopback_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = portable_root(Path(directory))
            config = build_comfyui_start_config(root)

        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8188)
        self.assertEqual(
            config.command[1:],
            (
                "-s",
                str(config.main_script),
                "--windows-standalone-build",
                "--listen",
                "127.0.0.1",
                "--port",
                "8188",
                "--disable-auto-launch",
            ),
        )

    def test_config_rejects_non_loopback_or_incomplete_portable_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = portable_root(parent)
            with self.assertRaisesRegex(
                BackendLifecycleError,
                "comfyui_autostart_requires_loopback_http",
            ):
                build_comfyui_start_config(root, base_url="http://192.168.1.20:8188")
            (root / "ComfyUI" / "main.py").unlink()
            with self.assertRaisesRegex(
                BackendLifecycleError,
                "comfyui_autostart_main_not_found",
            ):
                build_comfyui_start_config(root)

    def test_non_windows_rejection_does_not_mutate_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent))
            environment = {"LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "original"}
            supervisor = ComfyUIProcessSupervisor(
                config,
                state_dir=parent / "state",
                platform_name="posix",
                environ=environment,
            )

            with self.assertRaisesRegex(
                BackendLifecycleError,
                "comfyui_windows_portable_required",
            ):
                supervisor.start()

        self.assertEqual(environment, {"LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "original"})

    def test_log_directory_failure_restores_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            state_file = parent / "state"
            state_file.write_text("not a directory", encoding="utf-8")
            config = build_comfyui_start_config(portable_root(parent))
            environment = {"LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "original"}
            supervisor = ComfyUIProcessSupervisor(
                config,
                probe=lambda _url, _timeout: {
                    "available": False,
                    "queue_running": None,
                    "queue_pending": None,
                },
                state_dir=state_file,
                platform_name="nt",
                environ=environment,
            )

            with self.assertRaisesRegex(
                BackendLifecycleError,
                "comfyui_autostart_lock_unavailable",
            ):
                supervisor.start()

        self.assertEqual(environment, {"LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "original"})

    def test_existing_backend_is_reused_and_never_owned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent))
            factory = RecordingFactory()
            environment: dict[str, str] = {}
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: {
                    "available": True,
                    "queue_running": 1,
                    "queue_pending": 0,
                },
                state_dir=parent / "state",
                platform_name="nt",
                environ=environment,
            )

            started = supervisor.start()
            closed = supervisor.close()

        self.assertEqual(factory.calls, [])
        self.assertEqual(started["status"], "reused_existing")
        self.assertEqual(closed["cleanup_status"], "not_owned")
        self.assertEqual(environment, {})

    def test_owned_process_uses_fixed_command_and_stops_only_when_queue_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent))
            factory = RecordingFactory()
            probes = iter(
                (
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                )
            )
            environment: dict[str, str] = {"LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "old"}
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: next(probes),
                state_dir=parent / "state",
                platform_name="nt",
                environ=environment,
            )

            started = supervisor.start()
            command, kwargs = factory.calls[0]
            self.assertEqual(command, list(config.command))
            self.assertEqual(kwargs["cwd"], str(config.root))
            self.assertEqual(environment["LOCAL_GPU_IMAGEGEN_COMFYUI_MANAGED"], "1")
            closed = supervisor.close()

        self.assertEqual(started["owned_pid"], 4242)
        self.assertTrue(factory.process.terminated)
        self.assertEqual(factory.process.wait_calls, [10])
        self.assertEqual(closed["cleanup_status"], "stopped_owned_process")
        self.assertEqual(environment, {"LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "old"})

    def test_owned_process_is_retained_when_queue_is_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent))
            factory = RecordingFactory()
            probes = iter(
                (
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                    {"available": True, "queue_running": 1, "queue_pending": 0},
                )
            )
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: next(probes),
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )

            supervisor.start()
            closed = supervisor.close()

        self.assertFalse(factory.process.terminated)
        self.assertEqual(closed["cleanup_status"], "retained_nonempty_queue")

    def test_owned_process_is_retained_when_queue_state_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent))
            factory = RecordingFactory()
            probes = iter(
                (
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                    {"available": False, "queue_running": None, "queue_pending": None},
                )
            )
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: next(probes),
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )

            supervisor.start()
            closed = supervisor.close()

        self.assertFalse(factory.process.terminated)
        self.assertEqual(closed["cleanup_status"], "retained_unknown_queue")

    def test_exited_process_returns_bounded_structured_error_without_full_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(
                portable_root(parent), timeout_seconds=120
            )
            factory = RecordingFactory(FakeProcess(returncode=1))
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: {
                    "available": False,
                    "queue_running": None,
                    "queue_pending": None,
                },
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )

            started = time.monotonic()
            with self.assertRaises(BackendLifecycleError) as raised:
                supervisor.start()
            elapsed = time.monotonic() - started

        self.assertEqual(raised.exception.code, "startup_process_exited")
        self.assertLess(elapsed, 2)
        self.assertEqual(
            raised.exception.recoverable_next_actions,
            ["inspect_backend_logs", "retry_startup"],
        )
        self.assertLessEqual(
            len(str(raised.exception.details.get("stderr_summary", "")).encode()),
            4096,
        )

    def test_port_conflict_reuses_only_a_reprobed_healthy_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent), timeout_seconds=2)
            process = ExitingProcess("Port 8188 is already in use")
            factory = RecordingFactory(process)
            probes = iter(
                (
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                )
            )
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: next(probes),
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )

            with patch.object(
                supervisor, "_stderr_summary", return_value=process.stderr_text
            ):
                report = supervisor.start()

        self.assertEqual(report["status"], "reused_after_startup_conflict")
        self.assertIsNone(report["owned_pid"])

    def test_database_lock_exit_is_startup_conflict_not_model_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent), timeout_seconds=120)
            factory = RecordingFactory(FakeProcess(returncode=1))
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: {
                    "available": False,
                    "queue_running": None,
                    "queue_pending": None,
                },
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )

            with patch.object(
                supervisor,
                "_stderr_summary",
                return_value="Could not acquire lock on comfyui.db. Another ComfyUI process may already be using it.",
            ), self.assertRaises(BackendLifecycleError) as raised:
                supervisor.start()

        self.assertEqual(raised.exception.code, "startup_conflict")
        self.assertNotEqual(raised.exception.code, "no_models_installed")

    def test_dead_owner_startup_lock_is_reclaimed_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent), timeout_seconds=2)
            factory = RecordingFactory()
            probes = iter(
                (
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                )
            )
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: next(probes),
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )
            lock_dir = supervisor._startup_lock_dir()
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                json.dumps({
                    "pid": 999999,
                    "process_identity": "dead-process",
                    "owner_token": "dead-owner",
                    "base_url": config.base_url,
                }),
                encoding="utf-8",
            )

            with (
                patch(
                    "local_gpu_imagegen.backend_lifecycle.is_process_alive",
                    return_value=False,
                ),
                patch(
                    "local_gpu_imagegen.backend_lifecycle.process_identity",
                    return_value="current-process",
                ),
            ):
                report = supervisor.start()

        self.assertEqual(report["status"], "started_owned")
        self.assertEqual(len(factory.calls), 1)

    def test_abandoned_empty_startup_lock_is_reclaimed_after_grace_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent), timeout_seconds=2)
            factory = RecordingFactory()
            probes = iter(
                (
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": False, "queue_running": None, "queue_pending": None},
                    {"available": True, "queue_running": 0, "queue_pending": 0},
                )
            )
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=factory,
                probe=lambda _url, _timeout: next(probes),
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )
            lock_dir = supervisor._startup_lock_dir()
            lock_dir.mkdir()
            old = time.time() - 10
            os.utime(lock_dir, (old, old))

            report = supervisor.start()

        self.assertEqual(report["status"], "started_owned")
        self.assertEqual(len(factory.calls), 1)

    def test_unhealthy_owned_process_is_terminated_when_startup_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            config = build_comfyui_start_config(portable_root(parent), timeout_seconds=1)
            process = FakeProcess()
            supervisor = ComfyUIProcessSupervisor(
                config,
                process_factory=RecordingFactory(process),
                probe=lambda _url, _timeout: {
                    "available": False,
                    "queue_running": None,
                    "queue_pending": None,
                },
                state_dir=parent / "state",
                platform_name="nt",
                environ={},
            )

            with self.assertRaises(BackendLifecycleError) as raised:
                supervisor.start()

        self.assertEqual(raised.exception.code, "endpoint_unreachable")
        self.assertTrue(process.terminated)
        self.assertEqual(process.wait_calls, [10])

    def test_two_python_processes_share_one_cold_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = portable_root(parent)
            worker = ROOT / "tests" / "cold_start_worker.py"
            outputs = [parent / "worker-1.json", parent / "worker-2.json"]
            processes = [
                subprocess.Popen(
                    [sys.executable, str(worker), str(parent), str(root), str(output)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for output in outputs
            ]
            completed = [process.communicate(timeout=10) for process in processes]
            reports = [json.loads(output.read_text(encoding="utf-8")) for output in outputs]

        self.assertEqual([process.returncode for process in processes], [0, 0], completed)
        self.assertEqual(
            sorted(report["status"] for report in reports),
            ["started_owned", "waited_for_existing"],
        )

if __name__ == "__main__":
    unittest.main()
