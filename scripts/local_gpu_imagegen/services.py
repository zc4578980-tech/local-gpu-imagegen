from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .backends.base import BackendAdapter, BackendRegistry
from .backends.comfyui import ComfyUIAdapter
from .backends.webui import WebUIAdapter
from .discovery import DiscoveryService
from .engine import AssetRunEngine
from .model_catalog import ModelCatalog
from .model_router import CapabilityRouter
from .profile_registry import ProfileRegistry
from .prompt_compilers import PromptCompilerRegistry
from .run_store import RunStore
from .trust_registry import TrustRegistry
from .workflow_templates import WorkflowTemplateRegistry


BackendRunner = Callable[[dict[str, object]], dict[str, object]]
CapabilityProvider = Callable[[], dict[str, object]]


@dataclass(slots=True)
class RuntimeServices:
    discovery: DiscoveryService
    trust: TrustRegistry
    catalog: ModelCatalog
    router: CapabilityRouter
    workflows: WorkflowTemplateRegistry
    backends: BackendRegistry
    engine: AssetRunEngine


def adapters_from_environment() -> list[BackendAdapter]:
    return [
        WebUIAdapter(
            os.environ.get("LOCAL_GPU_IMAGEGEN_WEBUI_URL", "http://127.0.0.1:7860"),
            lan_confirmation=os.environ.get("LOCAL_GPU_IMAGEGEN_WEBUI_LAN_CONFIRMATION"),
        ),
        ComfyUIAdapter(
            os.environ.get("LOCAL_GPU_IMAGEGEN_COMFYUI_URL", "http://127.0.0.1:8188"),
            lan_confirmation=os.environ.get("LOCAL_GPU_IMAGEGEN_COMFYUI_LAN_CONFIRMATION"),
        ),
    ]


def build_services(
    root: Path,
    output_root: Path,
    state_dir: Path,
    capabilities: CapabilityProvider,
    diffusers_runner: BackendRunner,
) -> RuntimeServices:
    root = Path(root)
    workflows = WorkflowTemplateRegistry(root / "workflows" / "comfyui", state_dir)
    backends = BackendRegistry(adapters_from_environment(), {"diffusers": diffusers_runner})
    trust = TrustRegistry(state_dir)
    discovery = DiscoveryService(backends)
    catalog = ModelCatalog(
        root / "profiles" / "models",
        discovery.inventory,
        trust,
        capabilities,
        workflows,
    )
    compilers = PromptCompilerRegistry()
    router = CapabilityRouter(
        catalog,
        compilers,
        layout_capability_provider=backends.layout_capability,
    )
    engine = AssetRunEngine(
        ProfileRegistry(root / "profiles"),
        RunStore(output_root),
        backends.generate,
        capabilities,
        catalog=catalog,
        router=router,
        compilers=compilers,
        workflows=workflows,
    )
    return RuntimeServices(discovery, trust, catalog, router, workflows, backends, engine)
