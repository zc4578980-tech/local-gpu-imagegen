from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "scripts"))

import mcp_server  # noqa: E402
from local_gpu_imagegen.services import RuntimeServices, build_services  # noqa: E402


class FakeComfyUIAdapter:
    backend_id = "comfyui"
    endpoint_identity = "endpoint:test-comfyui"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.generate_calls = 0

    def discover(self) -> list[dict[str, object]]:
        return [{
            "backend": "comfyui",
            "endpoint_identity": self.endpoint_identity,
            "backend_model_id": self.model_name,
            "format": "comfyui-choice",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {"loader_class": "CheckpointLoaderSimple", "loader_input": "ckpt_name"},
        }]

    def probe(self) -> dict[str, object]:
        return {"backend": self.backend_id, "ready": True}

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        self.generate_calls += 1
        return dict(request)

    def layout_capability(self, mode: str) -> dict[str, object]:
        return {"mode": mode, "available": False, "endpoint_identity": self.endpoint_identity, "reason": "test"}

    def cancel_or_query(self, job_id: str, *, cancel: bool = False) -> dict[str, object]:
        return {"job_id": job_id, "state": "unknown", "cancel_supported": False}


class RuntimeServicesTests(unittest.TestCase):
    def test_build_services_composes_one_shared_runtime_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = lambda request: dict(request)  # noqa: E731
            capabilities = lambda: {  # noqa: E731
                "available_backends": ["diffusers"],
                "diffusers_ready": True,
            }
            with patch(
                "local_gpu_imagegen.services.adapters_from_environment",
                return_value=[],
            ):
                services = build_services(
                    ROOT,
                    root / "outputs",
                    root / "state",
                    capabilities,
                    runner,
                )

        self.assertIsInstance(services, RuntimeServices)
        self.assertIs(services.engine.catalog, services.catalog)
        self.assertIs(services.engine.router, services.router)
        self.assertIs(services.engine.compilers, services.router.compilers)
        self.assertIs(services.discovery.adapters, services.backends)
        self.assertIs(
            services.router.layout_capability_provider.__self__,
            services.backends,
        )

    def test_build_services_wires_workflow_onboarding_to_shared_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "local_gpu_imagegen.services.adapters_from_environment",
                return_value=[],
            ):
                services = build_services(
                    ROOT,
                    root / "outputs",
                    root / "state",
                    lambda: {"available_backends": []},
                    lambda request: {},
                )

        self.assertIs(services.onboarding.workflows, services.workflows)
        self.assertEqual(
            services.onboarding.inventory_provider(),
            services.discovery.inventory(),
        )

    def test_build_services_injects_one_shared_file_verification_registry(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as directory:
            root = Path(directory)
            with patch("local_gpu_imagegen.services.adapters_from_environment", return_value=[]):
                services = build_services(
                    ROOT,
                    root / "outputs",
                    root / "state",
                    lambda: {"available_backends": []},
                    lambda request: {},
                )

        self.assertIs(services.discovery.file_verifications, services.file_verifications)
        self.assertEqual(services.file_verifications.path, root / "state" / "file-verifications.json")

    def test_fresh_process_restores_exact_file_before_workflow_trust_inspection(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as directory:
            root = Path(directory)
            model_root = root / "models"
            model_root.mkdir()
            model = model_root / "model.safetensors"
            model.write_bytes(b"verified-model")
            state_dir = root / "state"
            source_workflow = ROOT / "workflows" / "comfyui" / "sd15-txt2img-v1.json"
            workflow = root / "workflow.json"
            workflow.write_text(
                json.dumps(json.loads(source_workflow.read_text(encoding="utf-8"))["graph"]),
                encoding="utf-8",
            )
            adapter = FakeComfyUIAdapter(model.name)

            with patch("local_gpu_imagegen.services.adapters_from_environment", return_value=[adapter]):
                first = build_services(
                    ROOT, root / "outputs-1", state_dir,
                    lambda: {"available_backends": ["comfyui"]}, lambda request: {},
                )
                plan = first.discovery.plan({
                    "mode": "exact_file", "stage": "verify",
                    "roots": [str(model_root)], "explicit_includes": [str(model)],
                    "expected_backend_model_id": model.name,
                })
                first.discovery.execute(str(plan["plan_id"]), str(plan["confirmation"]))

                second = build_services(
                    ROOT, root / "outputs-2", state_dir,
                    lambda: {"available_backends": ["comfyui"]}, lambda request: {},
                )
                api_plan = second.discovery.plan({"mode": "api_only", "stage": "index"})
                second.discovery.execute(str(api_plan["plan_id"]), str(api_plan["confirmation"]))
                exact_plan = second.discovery.plan({
                    "mode": "exact_file", "stage": "verify",
                    "expected_backend_model_id": model.name,
                })
                self.assertFalse(exact_plan["confirmation_required"])
                with patch("local_gpu_imagegen.discovery.fingerprint_selected_file", wraps=__import__(
                    "local_gpu_imagegen.discovery", fromlist=["fingerprint_selected_file"]
                ).fingerprint_selected_file) as fingerprint:
                    second.discovery.execute(str(exact_plan["plan_id"]), None)
                self.assertEqual(fingerprint.call_count, 1)
                proposal = second.onboarding.inspect(workflow)

                filesystem = next(
                    item for item in second.discovery.inventory()
                    if item["backend"] == "filesystem"
                )
                identity = mcp_server.identity_token(filesystem)
                trust_arguments = {
                    "action": "inspect_workflow_binding",
                    "identity_token": identity,
                    "capabilities": {"operations": ["txt2img"]},
                    "workflow_path": str(workflow),
                    "workflow_binding": proposal["binding"],
                    "component_identity_tokens": [identity],
                }
                with patch.object(mcp_server, "get_runtime_services", return_value=second):
                    trust_inspection = mcp_server.handle_tool_call({
                        "name": "local_gpu_set_model_trust",
                        "arguments": trust_arguments,
                    })

                control = build_services(
                    ROOT, root / "outputs-3", root / "control-state",
                    lambda: {"available_backends": ["comfyui"]}, lambda request: {},
                )
                control_plan = control.discovery.plan({
                    "mode": "api_only", "stage": "index",
                })
                control.discovery.execute(
                    str(control_plan["plan_id"]), str(control_plan["confirmation"])
                )
                api_identity = mcp_server.identity_token(control.discovery.inventory()[0])
                with patch.object(mcp_server, "get_runtime_services", return_value=control):
                    api_only_inspection = mcp_server.handle_tool_call({
                        "name": "local_gpu_set_model_trust",
                        "arguments": {
                            **trust_arguments,
                            "identity_token": api_identity,
                            "component_identity_tokens": [api_identity],
                        },
                    })

            self.assertTrue(proposal["registrable"])
            self.assertFalse(trust_inspection["isError"])
            self.assertTrue(
                trust_inspection["structuredContent"]["confirmations"]["approve_private"].startswith(
                    f"approve_private:{identity}:bundle:"
                )
            )
            self.assertTrue(api_only_inspection["isError"])
            self.assertIn(
                api_only_inspection["structuredContent"]["error"]["code"],
                {"component_primary_identity_required", "invalid_component_bundle"},
            )
            self.assertEqual(second.trust.list_records(), [])
            self.assertEqual(control.trust.list_records(), [])
            self.assertEqual({item["backend"] for item in second.discovery.inventory()}, {"comfyui", "filesystem"})
            self.assertEqual(adapter.generate_calls, 0)


if __name__ == "__main__":
    unittest.main()
