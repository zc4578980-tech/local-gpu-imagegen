from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backend_lifecycle import (  # noqa: E402
    ComfyUIProcessSupervisor,
    build_comfyui_start_config,
)


class SharedFakeProcess:
    pid = 4242

    def poll(self) -> None:
        return None


def main() -> int:
    shared = Path(sys.argv[1])
    root = Path(sys.argv[2])
    output = Path(sys.argv[3])
    launch_marker = shared / "launch.marker"
    healthy_marker = shared / "healthy.marker"

    def process_factory(_command: list[str], **_kwargs: object) -> SharedFakeProcess:
        launch_marker.write_text(str(Path(output).name), encoding="utf-8", errors="strict")

        def become_healthy() -> None:
            time.sleep(0.25)
            healthy_marker.write_text("healthy", encoding="utf-8")

        threading.Thread(target=become_healthy, daemon=True).start()
        return SharedFakeProcess()

    def probe(_url: str, _timeout: float) -> dict[str, object]:
        healthy = healthy_marker.exists()
        return {
            "available": healthy,
            "queue_running": 0 if healthy else None,
            "queue_pending": 0 if healthy else None,
        }

    config = build_comfyui_start_config(root, timeout_seconds=3)
    supervisor = ComfyUIProcessSupervisor(
        config,
        process_factory=process_factory,
        probe=probe,
        state_dir=shared / "state",
        platform_name="nt",
        environ={},
    )
    try:
        report = supervisor.start()
        output.write_text(json.dumps(report), encoding="utf-8")
    except BaseException as error:
        output.write_text(
            json.dumps({"error": type(error).__name__, "message": str(error)}),
            encoding="utf-8",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
