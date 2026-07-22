from __future__ import annotations

import importlib.metadata
import os
import sys
import sysconfig
from pathlib import Path


RESOURCE_DIRECTORY = Path("share") / "local-gpu-imagegen"
RESOURCE_MARKERS = (
    Path("profiles") / "base.json",
    Path("workflows") / "comfyui",
    Path("skills") / "local-gpu-imagegen" / "SKILL.md",
)


def _missing_markers(root: Path) -> list[str]:
    return [str(marker) for marker in RESOURCE_MARKERS if not (root / marker).exists()]


def _distribution_resource_root() -> Path | None:
    try:
        distribution = importlib.metadata.distribution("local-gpu-imagegen")
    except importlib.metadata.PackageNotFoundError:
        return None
    for entry in distribution.files or ():
        normalized = str(entry).replace("\\", "/")
        if not normalized.endswith("share/local-gpu-imagegen/profiles/base.json"):
            continue
        base = Path(distribution.locate_file(entry)).resolve()
        return base.parent.parent
    return None


def resolve_resource_root() -> Path:
    explicit = os.environ.get("LOCAL_GPU_IMAGEGEN_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        missing = _missing_markers(root)
        if missing:
            raise RuntimeError(
                "LOCAL_GPU_IMAGEGEN_ROOT is missing required profiles/workflows/Skill assets: "
                + ", ".join(missing)
            )
        return root

    source_root = Path(__file__).resolve().parents[2]
    data_root = Path(sysconfig.get_path("data")) / RESOURCE_DIRECTORY
    candidates = (
        source_root,
        data_root,
        Path(sys.prefix) / RESOURCE_DIRECTORY,
        _distribution_resource_root(),
    )
    for candidate in candidates:
        if candidate is not None and not _missing_markers(candidate):
            return candidate.resolve()
    raise RuntimeError(
        "Unable to locate packaged profiles, workflows, and Skill assets. "
        "Reinstall the wheel or set LOCAL_GPU_IMAGEGEN_ROOT to a valid resource root."
    )


def is_source_checkout(root: Path) -> bool:
    return (Path(root) / "scripts" / "mcp_server.py").is_file()


def default_output_root(root: Path | None = None) -> Path:
    resource_root = resolve_resource_root() if root is None else Path(root)
    if is_source_checkout(resource_root):
        return resource_root / "outputs"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "local-gpu-imagegen" / "outputs"
