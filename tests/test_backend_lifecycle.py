from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


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
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode: int | None = None
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


class BackendLifecycleTests(unittest.TestCase):
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
                "comfyui_autostart_log_unavailable",
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

            supervisor.start()
            closed = supervisor.close()

        self.assertFalse(factory.process.terminated)
        self.assertEqual(closed["cleanup_status"], "retained_unknown_queue")

if __name__ == "__main__":
    unittest.main()
