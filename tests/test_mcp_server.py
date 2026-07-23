from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mcp_server  # noqa: E402
from local_gpu_imagegen.errors import AssetEngineError  # noqa: E402
from local_gpu_imagegen.model_catalog import ModelCatalog  # noqa: E402
from local_gpu_imagegen.model_router import CapabilityRouter  # noqa: E402
from local_gpu_imagegen.preview import PreviewResult  # noqa: E402
from local_gpu_imagegen.prompt_compilers import PromptCompilerRegistry  # noqa: E402
from local_gpu_imagegen.trust_registry import TrustRegistry  # noqa: E402
from local_gpu_imagegen.two_stage_layout import (  # noqa: E402
    TWO_STAGE_LAYOUT_MODE,
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
)
from local_gpu_imagegen.workflow_templates import WorkflowTemplateRegistry  # noqa: E402


EXPECTED_TOOLS = {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
    "local_gpu_list_profiles",
    "local_gpu_discover_models",
    "local_gpu_set_model_trust",
    "local_gpu_recommend_models",
    "local_gpu_start_run",
    "local_gpu_get_run",
    "local_gpu_branch_run",
    "local_gpu_prepare_mask",
    "local_gpu_confirm_mask",
    "local_gpu_generate_round",
    "local_gpu_record_review",
    "local_gpu_finalize_run",
    "local_gpu_cleanup_run",
}

HIGH_LEVEL_TOOLS = EXPECTED_TOOLS - {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
}


def exact_two_stage_layout() -> dict[str, object]:
    return {
        "mode": TWO_STAGE_LAYOUT_MODE,
        "canvas": {"width": 640, "height": 320},
        "copy_protected_rect": {"x": 0, "y": 0, "width": 224, "height": 320},
        "subject_mask_rect": {"x": 304, "y": 16, "width": 320, "height": 288},
        "feather_pixels": 0,
        "vae_grow_mask_by": 0,
    }


def visual_checks() -> dict[str, object]:
    return {
        "full_resolution_inspected": True,
        "prominent_human": True,
        "limb_separation": {"status": "pass", "observation": "Limbs are distinct."},
        "feet_and_contact": {"status": "pass", "observation": "Feet are distinct."},
        "hands_and_held_objects": {"status": "pass", "observation": "Hands are distinct."},
        "text_and_watermarks": {"status": "pass", "observation": "No text is visible."},
    }


class McpServerUnitTests(unittest.TestCase):
    def test_schema_exposes_expected_tools(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        self.assertEqual(set(tools), EXPECTED_TOOLS)
        self.assertIn("prompt", tools["local_gpu_generate_image"]["inputSchema"]["required"])
        self.assertIn("allow_download", tools["local_gpu_generate_image"]["inputSchema"]["properties"])
        self.assertIn("outputSchema", tools["local_gpu_imagegen_check"])
        self.assertIn("outputSchema", tools["local_gpu_generate_image"])
        list_profiles_success = tools["local_gpu_list_profiles"]["outputSchema"]["oneOf"][0]
        self.assertIn("models", list_profiles_success["properties"])
        self.assertIn("models", list_profiles_success["required"])
        for name in HIGH_LEVEL_TOOLS:
            with self.subTest(name=name):
                self.assertFalse(tools[name]["inputSchema"]["additionalProperties"])
                output_schema = tools[name]["outputSchema"]
                self.assertIn("oneOf", output_schema)
                if "oneOf" not in output_schema:
                    continue
                self.assertEqual(len(output_schema["oneOf"]), 2)
                success, error = output_schema["oneOf"]
                self.assertFalse(success["additionalProperties"])
                self.assertIn("ok", success["required"])
                self.assertIn("warnings", success["required"])
                self.assertEqual(error["required"], ["error"])
                self.assertFalse(error["additionalProperties"])
                self.assertEqual(set(error["properties"]), {"error"})
                error_value = error["properties"]["error"]
                self.assertEqual(set(error_value["properties"]), {"code", "category", "message", "details"})
                self.assertEqual(set(error_value["required"]), {"code", "category", "message"})
                self.assertFalse(error_value["additionalProperties"])

    def test_plugin_manifest_reports_release_version(self) -> None:
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], "0.7.0")
        self.assertEqual(mcp_server.SERVER_VERSION, "0.7.0")

    def test_high_level_input_contracts_are_exact(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        expected = {
            "local_gpu_list_profiles": {"authorization_scope"},
            "local_gpu_discover_models": {
                "phase", "mode", "stage", "backends", "roots", "explicit_includes", "plan_id",
                "confirmation", "network_confirmation", "selected_candidates",
            },
            "local_gpu_set_model_trust": {
                "action", "identity_token", "confirmation", "capabilities", "public_metadata",
                "workflow_template_id", "workflow_path", "workflow_binding", "preference",
                "component_identity_tokens", "catalog_id", "two_stage_layout",
            },
            "local_gpu_recommend_models": {
                "authorization_scope", "operation", "profile", "style", "width", "height",
                "affinity_tags", "required_vram_gb", "preferred_model_id", "regional_layout",
                "two_stage_layout",
            },
            "local_gpu_start_run": {
                "intent", "profile", "subtype", "style", "constraints", "model_choice", "backend",
                "authorization_scope", "route_token", "max_rounds", "upscale_policy",
                "initial_regional_conditioning", "initial_two_stage_conditioning",
            },
            "local_gpu_get_run": {"run_id"},
            "local_gpu_branch_run": {
                "parent_run_id", "parent_round", "contract", "max_rounds", "edit_mode",
                "denoising_strength",
            },
            "local_gpu_prepare_mask": {"run_id", "user_mask_path", "geometry", "feather_pixels"},
            "local_gpu_confirm_mask": {"run_id", "mask_id"},
            "local_gpu_generate_round": {
                "run_id", "idempotency_key", "action", "edit_mode", "mask_id", "plan", "seed",
                "change_summary",
            },
            "local_gpu_record_review": {
                "run_id", "round_number", "scores", "hard_failures", "critique", "constraint_results",
                "visual_checks", "preservation_results", "next_action",
            },
            "local_gpu_finalize_run": {"run_id", "round_number", "summary", "confirmation", "postprocess"},
            "local_gpu_cleanup_run": {"run_id", "scope", "confirmation"},
        }
        for name, fields in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, tools)
                if name not in tools:
                    continue
                schema = tools[name]["inputSchema"]
                self.assertEqual(set(schema["properties"]), fields)
                optional = {
                    "local_gpu_list_profiles": {"authorization_scope"},
                    "local_gpu_discover_models": {
                        "mode", "stage", "backends", "roots", "explicit_includes", "plan_id",
                        "confirmation", "network_confirmation", "selected_candidates",
                    },
                    "local_gpu_set_model_trust": {
                        "confirmation", "capabilities", "public_metadata", "workflow_template_id",
                        "workflow_path", "workflow_binding", "preference", "component_identity_tokens",
                        "catalog_id", "two_stage_layout",
                    },
                    "local_gpu_recommend_models": {"regional_layout", "two_stage_layout"},
                    "local_gpu_start_run": {
                        "initial_regional_conditioning", "initial_two_stage_conditioning",
                    },
                    "local_gpu_branch_run": {"denoising_strength"},
                    "local_gpu_prepare_mask": {"user_mask_path", "geometry", "feather_pixels"},
                    "local_gpu_generate_round": {"mask_id"},
                    "local_gpu_record_review": {"preservation_results"},
                    "local_gpu_finalize_run": {"postprocess"},
                }.get(name, set())
                required = fields - optional
                self.assertEqual(set(schema.get("required", [])), required)

        trust_schema = tools["local_gpu_set_model_trust"]["inputSchema"]
        self.assertEqual(
            trust_schema["properties"]["workflow_template_id"]["enum"],
            [
                "anima-txt2img",
                "sd15-txt2img",
                "sdxl-regional-txt2img",
                "sdxl-two-stage-copy-subject",
                "sdxl-txt2img",
                "z-image-turbo-txt2img",
            ],
        )

    def test_two_stage_workflow_is_packaged_and_advertised_after_runtime_integration(self) -> None:
        source = ROOT / "workflows" / "comfyui" / "sdxl-two-stage-copy-subject-v1.json"
        document = json.loads(source.read_text(encoding="utf-8"))

        self.assertEqual(document["template_id"], "sdxl-two-stage-copy-subject")
        self.assertIn(
            document["template_id"],
            mcp_server._shipped_workflow_template_ids(),
        )
        tools = mcp_server.tool_schema()
        self.assertEqual(len(tools), 15)
        trust = next(tool for tool in tools if tool["name"] == "local_gpu_set_model_trust")
        self.assertIn(
            document["template_id"],
            trust["inputSchema"]["properties"]["workflow_template_id"]["enum"],
        )

    def test_start_run_accepts_exact_optional_two_stage_conditioning(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        self.assertEqual(len(tools), 15)
        start = tools["local_gpu_start_run"]["inputSchema"]
        self.assertNotIn("initial_two_stage_conditioning", start["required"])
        conditioning = start["properties"]["initial_two_stage_conditioning"]
        self.assertFalse(conditioning["additionalProperties"])
        self.assertEqual(
            set(conditioning["properties"]),
            {"subject_prompt", "subject_negative_prompt", "subject_denoise"},
        )
        self.assertEqual(set(conditioning["required"]), set(conditioning["properties"]))
        self.assertEqual(conditioning["properties"]["subject_denoise"]["minimum"], 0.8)
        self.assertEqual(conditioning["properties"]["subject_denoise"]["maximum"], 1.0)

    def test_revision_and_mask_schemas_are_exact(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        branch = tools["local_gpu_branch_run"]["inputSchema"]
        self.assertEqual(branch["properties"]["edit_mode"]["enum"], ["prompt-refine", "img2img", "inpaint"])
        self.assertEqual(branch["properties"]["denoising_strength"]["exclusiveMinimum"], 0)
        self.assertEqual(branch["properties"]["denoising_strength"]["maximum"], 1)
        self.assertFalse(branch["properties"]["contract"]["additionalProperties"])

        prepare = tools["local_gpu_prepare_mask"]["inputSchema"]
        self.assertEqual(prepare["properties"]["feather_pixels"]["maximum"], 64)
        geometry = prepare["properties"]["geometry"]
        self.assertEqual(geometry["type"], "array")
        self.assertEqual(geometry["minItems"], 1)
        self.assertFalse(geometry["items"]["additionalProperties"])

        generate = tools["local_gpu_generate_round"]["inputSchema"]
        self.assertEqual(generate["properties"]["edit_mode"]["enum"], ["txt2img", "img2img", "inpaint"])
        self.assertNotIn("mask_id", generate["required"])

    def test_finalize_postprocess_schema_is_optional_and_exact(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        schema = tools["local_gpu_finalize_run"]["inputSchema"]
        postprocess = schema["properties"]["postprocess"]

        self.assertNotIn("postprocess", schema["required"])
        self.assertEqual(postprocess["type"], "object")
        self.assertFalse(postprocess["additionalProperties"])
        self.assertEqual(set(postprocess["properties"]), {"type", "model"})
        self.assertEqual(set(postprocess["required"]), {"type", "model"})
        self.assertEqual(postprocess["properties"]["type"]["enum"], ["anime_upscale"])
        self.assertEqual(
            postprocess["properties"]["model"]["enum"],
            ["realesr-animevideov3-x4", "realesrgan-x4plus-anime"],
        )

    def test_review_visual_checks_schema_is_required_and_exact(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        schema = tools["local_gpu_record_review"]["inputSchema"]

        self.assertIn("visual_checks", schema["required"])
        checks = schema["properties"]["visual_checks"]
        self.assertFalse(checks["additionalProperties"])
        self.assertEqual(set(checks["required"]), {
            "full_resolution_inspected",
            "prominent_human",
            "limb_separation",
            "feet_and_contact",
            "hands_and_held_objects",
            "text_and_watermarks",
        })
        self.assertIs(checks["properties"]["full_resolution_inspected"]["const"], True)
        for name in (
            "limb_separation",
            "feet_and_contact",
            "hands_and_held_objects",
            "text_and_watermarks",
        ):
            evidence = checks["properties"][name]
            self.assertFalse(evidence["additionalProperties"])
            self.assertEqual(set(evidence["required"]), {"status", "observation"})
            self.assertEqual(
                evidence["properties"]["status"]["enum"],
                ["pass", "fail", "uncertain", "not_applicable"],
            )

    def test_finalize_confirmation_schema_is_required(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        schema = tools["local_gpu_finalize_run"]["inputSchema"]

        self.assertIn("confirmation", schema["required"])
        self.assertEqual(schema["properties"]["confirmation"]["type"], "string")
        self.assertEqual(schema["properties"]["confirmation"]["minLength"], 1)

    def test_each_high_level_tool_rejects_unknown_arguments_before_engine_work(self) -> None:
        for name in HIGH_LEVEL_TOOLS:
            with self.subTest(name=name), patch.object(mcp_server, "get_asset_engine", create=True) as get_engine:
                result = mcp_server.handle_tool_call({"name": name, "arguments": {"surprise": True}})
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["code"], "unknown_argument")
                get_engine.assert_not_called()

    def test_high_level_wrong_or_missing_values_are_rejected_before_engine_work(self) -> None:
        invalid_calls = (
            ("local_gpu_start_run", {}),
            ("local_gpu_start_run", {
                "intent": "valid", "profile": "missing-profile", "subtype": "character", "style": None, "constraints": {},
                "model_choice": "stabilityai/sd-turbo", "backend": "webui", "max_rounds": 3,
                "upscale_policy": "auto", "authorization_scope": "private", "route_token": "route:test",
            }),
            ("local_gpu_get_run", {"run_id": 1}),
            ("local_gpu_branch_run", {
                "parent_run_id": "run-1", "parent_round": 1, "contract": {}, "max_rounds": 1,
                "edit_mode": "erase",
            }),
            ("local_gpu_prepare_mask", {"run_id": "run-1"}),
            ("local_gpu_confirm_mask", {"run_id": "run-1", "mask_id": 1}),
            ("local_gpu_generate_round", {
                "run_id": "run-1", "idempotency_key": "key", "action": "initial", "edit_mode": "erase",
                "plan": {}, "seed": 1, "change_summary": "Initial.",
            }),
            ("local_gpu_record_review", {
                "run_id": "run-1", "round_number": 1, "scores": {}, "hard_failures": "none",
                "critique": "Reviewed.", "constraint_results": {}, "next_action": "finalize",
            }),
            ("local_gpu_finalize_run", {"run_id": "run-1", "round_number": 4, "summary": "Done."}),
            ("local_gpu_cleanup_run", {"run_id": "run-1", "scope": "invalid", "confirmation": "run-1"}),
        )
        for name, arguments in invalid_calls:
            with self.subTest(name=name, arguments=arguments), patch.object(mcp_server, "get_asset_engine") as get_engine:
                result = mcp_server.handle_tool_call({"name": name, "arguments": arguments})
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["category"], "validation")
                get_engine.assert_not_called()

    def test_capability_failures_are_structured_without_stderr(self) -> None:
        with patch.object(mcp_server, "run_script", return_value=(9, "", "secret traceback")):
            capabilities = mcp_server.get_capabilities()
        self.assertEqual(capabilities, {
            "ready": False,
            "backends": {},
            "warnings": ["capability_check_failed"],
        })
        self.assertNotIn("secret", json.dumps(capabilities))

    def test_capabilities_derive_internal_available_backends(self) -> None:
        report = {"ready": True, "webui_ready": True, "diffusers_ready": False, "comfyui_ready": True}
        with patch.object(mcp_server, "run_script", return_value=(0, json.dumps(report), "")):
            capabilities = mcp_server.get_capabilities()
        self.assertEqual(capabilities["available_backends"], ["webui", "comfyui"])

    def test_byom_tools_dispatch_through_composed_services(self) -> None:
        services = Mock()
        services.discovery.plan.return_value = {"plan_id": "plan-1", "confirmation": "scan:plan-1", "warnings": []}
        services.router.recommend.return_value = {
            "requirements": {}, "routes": [], "reason": "no_eligible_model", "warnings": [],
        }
        discover = {"phase": "plan", "mode": "api_only", "stage": "index", "backends": ["webui"]}
        recommend = {
            "authorization_scope": "private", "operation": "txt2img",
            "profile": "standalone-illustration", "style": None, "width": 512, "height": 512,
            "affinity_tags": [], "required_vram_gb": None, "preferred_model_id": None,
            "regional_layout": {
                "mode": "copy-subject-v1",
                "copy_region": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0},
                "subject_region": {"x": 0.68, "y": 0.0, "width": 0.30, "height": 1.0},
            },
        }

        with patch.object(mcp_server, "get_runtime_services", return_value=services):
            discover_result = mcp_server.handle_tool_call({"name": "local_gpu_discover_models", "arguments": discover})
            recommend_result = mcp_server.handle_tool_call({"name": "local_gpu_recommend_models", "arguments": recommend})

        self.assertFalse(discover_result["isError"])
        self.assertFalse(recommend_result["isError"])
        services.discovery.plan.assert_called_once_with({
            "mode": "api_only", "stage": "index", "backends": ["webui"],
        })
        services.router.recommend.assert_called_once_with(recommend)

    def test_discovery_result_omits_data_uris_and_oversized_metadata_without_mutating_inventory(self) -> None:
        thumbnail = "data:image/jpeg;base64," + ("A" * 500_000)
        oversized_note = "B" * 20_000
        discovery_data = {
            "candidates": [{
                "candidate_id": "candidate:sdxl",
                "metadata": {
                    "modelspec.title": "Stable Diffusion XL Base 1.0",
                    "modelspec.thumbnail": thumbnail,
                    "oversized_note": oversized_note,
                },
            }],
            "warnings": [],
        }
        services = Mock()
        services.discovery.execute.return_value = discovery_data

        with patch.object(mcp_server, "get_runtime_services", return_value=services):
            result = mcp_server.handle_tool_call({
                "name": "local_gpu_discover_models",
                "arguments": {
                    "phase": "execute",
                    "plan_id": "plan-1",
                    "confirmation": "scan:plan-1",
                },
            })

        serialized = json.dumps(result)
        metadata = result["structuredContent"]["candidates"][0]["metadata"]
        self.assertNotIn("data:image", serialized)
        self.assertNotIn("A" * 1_000, serialized)
        self.assertNotIn("B" * 1_000, serialized)
        self.assertLess(len(serialized.encode("utf-8")), 16_384)
        self.assertEqual(metadata["modelspec.title"], "Stable Diffusion XL Base 1.0")
        self.assertIn("omitted data URI", metadata["modelspec.thumbnail"])
        self.assertIn("omitted oversized string", metadata["oversized_note"])
        self.assertEqual(discovery_data["candidates"][0]["metadata"]["modelspec.thumbnail"], thumbnail)
        self.assertEqual(discovery_data["candidates"][0]["metadata"]["oversized_note"], oversized_note)

    def test_trust_tool_resolves_exact_current_inventory_identity(self) -> None:
        record = {
            "backend": "webui", "endpoint_identity": "endpoint:test",
            "backend_model_id": "anything-v5.safetensors", "format": ".safetensors",
            "byte_size": 1, "modified_ns": 1, "sha256": None,
            "identity_strength": "backend_binding", "metadata": {},
        }
        token = mcp_server.identity_token(record)
        services = Mock()
        services.discovery.inventory.return_value = [{
            "candidate_id": "candidate:index-only",
            "source_type": "filesystem",
            "identity_strength": None,
        }, record]
        services.trust.approve_private.return_value = {
            "catalog_id": "local:test", "identity_token": token,
            "identity_strength": "backend_binding", "scope": "private",
        }
        arguments = {
            "action": "approve_private", "identity_token": token,
            "confirmation": f"approve_private:{token}",
            "capabilities": {"operations": ["txt2img"]},
        }

        with patch.object(mcp_server, "get_runtime_services", return_value=services):
            result = mcp_server.handle_tool_call({"name": "local_gpu_set_model_trust", "arguments": arguments})

        self.assertFalse(result["isError"])
        services.trust.approve_private.assert_called_once_with(
            record,
            arguments["confirmation"],
            capabilities=arguments["capabilities"],
            workflow_binding=None,
            preference=0,
        )

    def test_trust_revoke_forwards_optional_exact_catalog_variant(self) -> None:
        token = "model:" + "a" * 64
        catalog_id = "local:" + "b" * 24
        for supplied in (None, catalog_id):
            services = Mock()
            services.trust.revoke.return_value = {
                "catalog_id": catalog_id,
                "identity_token": token,
                "revoked": True,
            }
            arguments = {
                "action": "revoke",
                "identity_token": token,
                "confirmation": f"revoke:{catalog_id}:{token}",
            }
            if supplied is not None:
                arguments["catalog_id"] = supplied

            with patch.object(
                mcp_server,
                "get_runtime_services",
                return_value=services,
            ):
                result = mcp_server.handle_tool_call({
                    "name": "local_gpu_set_model_trust",
                    "arguments": arguments,
                })

            with self.subTest(catalog_id=supplied):
                self.assertFalse(result["isError"])
                services.trust.revoke.assert_called_once_with(
                    supplied,
                    token,
                    arguments["confirmation"],
                )

    def test_registered_workflow_binds_exact_unet_loader_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            source = Path(directory) / "z-image.json"
            document = json.loads(
                (ROOT / "workflows" / "comfyui" / "z-image-turbo-txt2img-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            source.write_text(json.dumps(document["graph"]), encoding="utf-8")
            graph_binding = {
                **document["bindings"],
                "output": [document["output_node"]],
            }
            record = {
                "backend": "comfyui",
                "endpoint_identity": "endpoint:comfyui",
                "backend_model_id": "z_image_turbo_nvfp4.safetensors",
                "format": ".safetensors",
                "byte_size": None,
                "modified_ns": None,
                "sha256": None,
                "identity_strength": "backend_binding",
                "metadata": {
                    "loader_class": "UNETLoader",
                    "loader_input": "unet_name",
                },
            }
            services = Mock()
            services.discovery.inventory.return_value = [record]
            services.workflows = WorkflowTemplateRegistry(
                ROOT / "workflows" / "comfyui",
                state_dir,
            )

            trust_binding, registered, bundle = mcp_server._registered_workflow_binding(
                services,
                record,
                str(source),
                graph_binding,
            )

        self.assertEqual(trust_binding["backend_model_id"], record["backend_model_id"])
        self.assertEqual(trust_binding["backend_identity_token"], mcp_server.identity_token(record))
        self.assertTrue(registered["template_id"].startswith("imported:"))
        self.assertIsNone(bundle)

    def test_shipped_workflow_trust_binds_exact_unet_identity_without_import(self) -> None:
        record = {
            "backend": "comfyui",
            "endpoint_identity": "endpoint:comfyui",
            "backend_model_id": "z_image_turbo_nvfp4.safetensors",
            "format": ".safetensors",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {
                "loader_class": "UNETLoader",
                "loader_input": "unet_name",
            },
        }
        token = mcp_server.identity_token(record)
        capabilities = {
            "model_family": "z-image",
            "prompt_dialect": "natural-v1",
            "operations": ["txt2img"],
            "minimum_dimension": 256,
            "maximum_dimension": 1536,
            "minimum_vram_gb": 12,
            "negative_prompt": "ignored",
            "affinity": ["illustration", "character"],
            "recommended": {
                "resolution": {"width": 768, "height": 768},
                "steps": 8,
                "guidance": 1.0,
                "sampler": "res_multistep",
                "scheduler": "simple",
            },
        }
        services = Mock()
        services.discovery.inventory.return_value = [record]
        services.workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            Path(tempfile.gettempdir()) / "local-gpu-imagegen-shipped-test-state",
        )
        services.trust.approve_private.return_value = {
            "catalog_id": "local:test",
            "identity_token": token,
            "identity_strength": "backend_binding",
            "scope": "private",
        }
        arguments = {
            "action": "approve_private",
            "identity_token": token,
            "confirmation": f"approve_private:{token}",
            "capabilities": capabilities,
            "workflow_template_id": "z-image-turbo-txt2img",
            "preference": 100,
        }

        with patch.object(mcp_server, "get_runtime_services", return_value=services):
            result = mcp_server.handle_tool_call({
                "name": "local_gpu_set_model_trust",
                "arguments": arguments,
            })

        self.assertFalse(result["isError"])
        binding = services.trust.approve_private.call_args.kwargs["workflow_binding"]
        self.assertEqual(binding["template_id"], "z-image-turbo-txt2img")
        self.assertEqual(binding["backend_identity_token"], token)
        self.assertEqual(result["structuredContent"]["registered_workflow"]["source"], "shipped")

    def test_regional_shipped_workflow_can_be_inspected_without_generation_data(self) -> None:
        filesystem = {
            "backend": "filesystem",
            "endpoint_identity": "filesystem:test",
            "backend_model_id": "checkpoints/sd_xl_base_1.0.safetensors",
            "format": ".safetensors",
            "byte_size": 1024,
            "modified_ns": 1,
            "sha256": "a" * 64,
            "identity_strength": "cryptographic",
            "metadata": {},
        }
        comfy = {
            "backend": "comfyui",
            "endpoint_identity": "endpoint:comfyui",
            "backend_model_id": "sd_xl_base_1.0.safetensors",
            "format": ".safetensors",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
            },
        }
        capabilities = {
            "model_family": "sdxl",
            "prompt_dialect": "natural-v1",
            "operations": ["txt2img"],
            "minimum_dimension": 256,
            "maximum_dimension": 1536,
            "minimum_vram_gb": 12,
            "negative_prompt": "supported",
            "affinity": ["illustration"],
            "recommended": {
                "resolution": {"width": 1024, "height": 1024},
                "steps": 30,
                "guidance": 7.0,
                "sampler": "dpmpp_2m",
                "scheduler": "karras",
            },
        }
        services = Mock()
        services.discovery.inventory.return_value = [filesystem, comfy]
        services.workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            Path(tempfile.gettempdir()) / "local-gpu-imagegen-regional-state",
        )

        binding, registration, bundle = mcp_server._shipped_workflow_binding(
            services,
            filesystem,
            "sdxl-regional-txt2img",
            capabilities,
            [mcp_server.identity_token(filesystem)],
        )

        self.assertEqual(binding["template_id"], "sdxl-regional-txt2img")
        self.assertEqual(
            bundle["workflow"]["sha256"],
            registration["workflow_sha256"],
        )

    def test_workflow_inspection_builds_bundle_without_mutating_trust(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            endpoint = "endpoint:comfyui"
            component_specs = [
                ("primary_model", "UNETLoader", "unet_name", "diffusion_models/z_image_turbo_nvfp4.safetensors", "z_image_turbo_nvfp4.safetensors", "a"),
                ("text_encoder", "CLIPLoader", "clip_name", "text_encoders/qwen_3_4b_fp4_mixed.safetensors", "qwen_3_4b_fp4_mixed.safetensors", "b"),
                ("vae", "VAELoader", "vae_name", "vae/ae.safetensors", "ae.safetensors", "c"),
            ]
            filesystem = []
            api = []
            for _role, loader_class, loader_input, relative, backend_name, marker in component_specs:
                filesystem.append({
                    "backend": "filesystem",
                    "endpoint_identity": "filesystem:test",
                    "backend_model_id": relative,
                    "format": ".safetensors",
                    "byte_size": 100 + ord(marker),
                    "modified_ns": 1,
                    "sha256": marker * 64,
                    "identity_strength": "cryptographic",
                    "metadata": {},
                })
                api.append({
                    "backend": "comfyui",
                    "endpoint_identity": endpoint,
                    "backend_model_id": backend_name,
                    "format": ".safetensors",
                    "byte_size": None,
                    "modified_ns": None,
                    "sha256": None,
                    "identity_strength": "backend_binding",
                    "metadata": {"loader_class": loader_class, "loader_input": loader_input},
                })
            services = Mock()
            services.discovery.inventory.return_value = [*filesystem, *api]
            services.workflows = WorkflowTemplateRegistry(
                ROOT / "workflows" / "comfyui",
                Path(directory) / "workflow-state",
            )
            services.trust = TrustRegistry(Path(directory) / "trust-state")
            capabilities = {
                "model_family": "z-image",
                "prompt_dialect": "natural-v1",
                "operations": ["txt2img"],
                "minimum_dimension": 256,
                "maximum_dimension": 1536,
                "minimum_vram_gb": 12,
                "negative_prompt": "ignored",
                "affinity": ["illustration"],
                "recommended": {
                    "resolution": {"width": 768, "height": 768},
                    "steps": 8,
                    "guidance": 1.0,
                    "sampler": "res_multistep",
                    "scheduler": "simple",
                },
            }
            arguments = {
                "action": "inspect_workflow_binding",
                "identity_token": mcp_server.identity_token(filesystem[0]),
                "capabilities": capabilities,
                "workflow_template_id": "z-image-turbo-txt2img",
                "component_identity_tokens": [mcp_server.identity_token(item) for item in filesystem],
            }

            with patch.object(mcp_server, "get_runtime_services", return_value=services):
                result = mcp_server.handle_tool_call({
                    "name": "local_gpu_set_model_trust",
                    "arguments": arguments,
                })

            self.assertFalse(result["isError"])
            data = result["structuredContent"]
            self.assertEqual(len(data["component_bundle"]["components"]), 3)
            self.assertEqual(
                data["component_bundle"]["workflow"]["sha256"],
                data["registered_workflow"]["workflow_sha256"],
            )
            self.assertIn(
                data["component_bundle"]["bundle_sha256"],
                data["confirmations"]["approve_public_candidate"],
            )
            self.assertEqual(services.trust.list_records(), [])

    def test_supported_mcp_flow_creates_and_routes_exact_two_stage_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filesystem = {
                "backend": "filesystem",
                "endpoint_identity": "filesystem:test",
                "backend_model_id": "checkpoints/sd_xl_base_1.0.safetensors",
                "format": ".safetensors",
                "byte_size": 2048,
                "modified_ns": 1,
                "sha256": "a" * 64,
                "identity_strength": "cryptographic",
                "metadata": {},
            }
            comfy = {
                "backend": "comfyui",
                "endpoint_identity": "endpoint:comfyui",
                "backend_model_id": "sd_xl_base_1.0.safetensors",
                "format": ".safetensors",
                "byte_size": None,
                "modified_ns": None,
                "sha256": None,
                "identity_strength": "backend_binding",
                "metadata": {
                    "loader_class": "CheckpointLoaderSimple",
                    "loader_input": "ckpt_name",
                },
            }
            inventory = [filesystem, comfy]
            capabilities = {
                "model_family": "sdxl",
                "prompt_dialect": "natural-v1",
                "operations": ["txt2img"],
                "minimum_dimension": 256,
                "maximum_dimension": 1536,
                "minimum_vram_gb": 12,
                "negative_prompt": "supported",
                "affinity": ["illustration"],
                "recommended": {
                    "resolution": {"width": 640, "height": 320},
                    "steps": 30,
                    "guidance": 7.0,
                    "sampler": "dpmpp_2m",
                    "scheduler": "karras",
                },
                "two_stage_layout_modes": [TWO_STAGE_LAYOUT_MODE],
            }
            discovery = Mock()
            discovery.inventory.return_value = inventory
            workflows = WorkflowTemplateRegistry(
                ROOT / "workflows" / "comfyui",
                root / "workflow-state",
            )
            trust = TrustRegistry(root / "trust-state")
            services = SimpleNamespace(
                discovery=discovery,
                workflows=workflows,
                trust=trust,
            )
            layout = exact_two_stage_layout()
            base_arguments = {
                "identity_token": mcp_server.identity_token(filesystem),
                "capabilities": capabilities,
                "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
                "component_identity_tokens": [mcp_server.identity_token(filesystem)],
                "two_stage_layout": layout,
            }

            with patch.object(mcp_server, "get_runtime_services", return_value=services):
                inspected = mcp_server.handle_tool_call({
                    "name": "local_gpu_set_model_trust",
                    "arguments": {
                        **base_arguments,
                        "action": "inspect_workflow_binding",
                    },
                })
                self.assertFalse(inspected["isError"])
                inspection = inspected["structuredContent"]
                workflow_sha256 = inspection["registered_workflow"]["workflow_sha256"]
                control_sha256 = build_control_identity(
                    layout,
                    workflow_sha256,
                    "base-subject-v1",
                )
                confirmation = inspection["confirmations"]["approve_private"]
                self.assertIn(f":control:{control_sha256}", confirmation)

                changed_layout = copy.deepcopy(layout)
                changed_layout["subject_mask_rect"] = {
                    "x": 312, "y": 16, "width": 312, "height": 288,
                }
                tampered = mcp_server.handle_tool_call({
                    "name": "local_gpu_set_model_trust",
                    "arguments": {
                        **base_arguments,
                        "action": "approve_private",
                        "confirmation": confirmation,
                        "two_stage_layout": changed_layout,
                    },
                })
                self.assertTrue(tampered["isError"])
                self.assertEqual(
                    tampered["structuredContent"]["error"]["code"],
                    "trust_confirmation_mismatch",
                )

                approved = mcp_server.handle_tool_call({
                    "name": "local_gpu_set_model_trust",
                    "arguments": {
                        **base_arguments,
                        "action": "approve_private",
                        "confirmation": confirmation,
                    },
                })
                self.assertFalse(approved["isError"])

            reopened = TrustRegistry(root / "trust-state")
            records = reopened.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0]["workflow_binding"]["control_sha256"],
                control_sha256,
            )
            models_root = root / "models"
            models_root.mkdir()
            catalog = ModelCatalog(
                models_root,
                lambda: inventory,
                reopened,
                lambda: {"available_backends": ["comfyui"]},
                workflows,
            )
            router = CapabilityRouter(
                catalog,
                PromptCompilerRegistry(),
                layout_capability_provider=lambda mode: {
                    "mode": mode,
                    "available": True,
                    "endpoint_identity": "endpoint:comfyui",
                    "reason": None,
                },
            )
            recommendation = router.recommend({
                "authorization_scope": "private",
                "operation": "txt2img",
                "profile": "standalone-illustration",
                "style": None,
                "width": 640,
                "height": 320,
                "affinity_tags": ["illustration"],
                "required_vram_gb": 12,
                "preferred_model_id": None,
                "two_stage_layout": layout,
            })

            self.assertEqual(len(recommendation["routes"]), 1)
            self.assertEqual(
                recommendation["routes"][0]["control_sha256"],
                control_sha256,
            )

    def test_trust_layout_is_required_only_for_two_stage_shipped_workflow(self) -> None:
        tool = next(
            item for item in mcp_server.tool_schema()
            if item["name"] == "local_gpu_set_model_trust"
        )
        base = {
            "action": "inspect_workflow_binding",
            "identity_token": "model:" + "a" * 64,
            "capabilities": {},
            "component_identity_tokens": ["model:" + "a" * 64],
        }
        cases = (
            ({**base, "workflow_template_id": TWO_STAGE_TEMPLATE_ID}, "invalid_two_stage_layout"),
            ({
                **base,
                "workflow_template_id": "sdxl-txt2img",
                "two_stage_layout": exact_two_stage_layout(),
            }, "invalid_two_stage_layout"),
            ({
                **base,
                "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
                "two_stage_layout": {**exact_two_stage_layout(), "mode": "wrong"},
            }, "invalid_argument_value"),
        )

        for arguments, code in cases:
            with self.subTest(code=code):
                error = mcp_server.validate_tool_arguments(tool, arguments)
                self.assertIsNotNone(error)
                self.assertEqual(error["structuredContent"]["error"]["code"], code)

    def test_trust_rejects_shipped_and_imported_workflow_together(self) -> None:
        tool = next(
            item for item in mcp_server.tool_schema()
            if item["name"] == "local_gpu_set_model_trust"
        )
        error = mcp_server.validate_tool_arguments(tool, {
            "action": "approve_private",
            "identity_token": "model:test",
            "confirmation": "approve_private:model:test",
            "capabilities": {},
            "workflow_template_id": "z-image-turbo-txt2img",
            "workflow_path": "workflow.json",
            "workflow_binding": {},
        })

        self.assertEqual(error["structuredContent"]["error"]["code"], "invalid_workflow_binding")

    def test_start_run_rejects_empty_intent_before_engine_work(self) -> None:
        arguments = {
            "intent": " ",
            "profile": "standalone-illustration",
            "subtype": "character",
            "style": None,
            "constraints": {},
            "model_choice": "stabilityai/sd-turbo",
            "backend": "webui",
            "max_rounds": 3,
            "upscale_policy": "auto",
            "authorization_scope": "private",
            "route_token": "route:test",
        }
        with patch.object(mcp_server, "get_asset_engine", create=True) as get_engine:
            result = mcp_server.handle_tool_call({"name": "local_gpu_start_run", "arguments": arguments})
        self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_argument_value")
        get_engine.assert_not_called()

    def test_start_run_rejects_missing_or_empty_model_before_engine_work(self) -> None:
        base = {
            "intent": "A calm coast at dawn.",
            "profile": "standalone-illustration",
            "subtype": "character",
            "style": None,
            "constraints": {},
            "backend": "webui",
            "max_rounds": 3,
            "upscale_policy": "auto",
            "authorization_scope": "private",
            "route_token": "route:test",
        }
        cases = (
            (None, "missing_argument"),
            (" ", "invalid_argument_value"),
        )
        for model_choice, expected_code in cases:
            arguments = dict(base)
            if model_choice is not None:
                arguments["model_choice"] = model_choice
            with self.subTest(model_choice=model_choice), patch.object(
                mcp_server, "get_asset_engine", create=True
            ) as get_engine:
                result = mcp_server.handle_tool_call({"name": "local_gpu_start_run", "arguments": arguments})

                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["code"], expected_code)
                get_engine.assert_not_called()

    def test_start_run_forwards_public_v04_fields_and_model_choice_exactly(self) -> None:
        initial_regional_conditioning = {
            "copy_prompt": "quiet copy space",
            "copy_strength": 1.1,
            "subject_prompt": "a sailor looking over the sea",
            "subject_strength": 1.25,
        }
        arguments = {
            "intent": "A calm coast at dawn.",
            "profile": "standalone-illustration",
            "subtype": "character",
            "style": None,
            "constraints": {},
            "model_choice": "test/approved-anime",
            "backend": "webui",
            "authorization_scope": "private",
            "route_token": "route:test",
            "max_rounds": 3,
            "upscale_policy": "off",
            "initial_regional_conditioning": initial_regional_conditioning,
        }
        engine = Mock()
        engine.start_run.return_value = {
            "ok": True,
            "run_id": "run-1",
            "state": "created",
            "max_rounds": 3,
            "merged_rubric": {},
            "warnings": [],
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            result = mcp_server.handle_tool_call({"name": "local_gpu_start_run", "arguments": arguments})

        self.assertFalse(result["isError"])
        engine.start_run.assert_called_once_with(arguments)
        self.assertIs(
            engine.start_run.call_args.args[0]["initial_regional_conditioning"],
            initial_regional_conditioning,
        )

    def test_start_run_rejects_unknown_regional_conditioning_field_before_engine_work(self) -> None:
        arguments = {
            "intent": "A calm coast at dawn.",
            "profile": "standalone-illustration",
            "subtype": "character",
            "style": None,
            "constraints": {},
            "model_choice": "test/approved-anime",
            "backend": "comfyui",
            "authorization_scope": "private",
            "route_token": "route:test",
            "max_rounds": 2,
            "upscale_policy": "off",
            "initial_regional_conditioning": {
                "copy_prompt": "quiet copy space",
                "copy_strength": 1.1,
                "subject_prompt": "a sailor",
                "subject_strength": 1.25,
                "extra": True,
            },
        }

        with patch.object(mcp_server, "get_asset_engine") as get_engine:
            result = mcp_server.handle_tool_call({"name": "local_gpu_start_run", "arguments": arguments})

        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "unknown_argument")
        self.assertEqual(
            result["structuredContent"]["error"]["details"]["fields"],
            ["initial_regional_conditioning.extra"],
        )
        get_engine.assert_not_called()

    def test_finalize_run_rejects_missing_or_invalid_round_before_engine_work(self) -> None:
        calls = (
            {"run_id": "run-1", "summary": "Missing."},
            {"run_id": "run-1", "round_number": True, "summary": "Boolean."},
            {"run_id": "run-1", "round_number": "1", "summary": "String."},
            {"run_id": "run-1", "round_number": 0, "summary": "Low."},
            {"run_id": "run-1", "round_number": 4, "summary": "High."},
        )
        for arguments in calls:
            with self.subTest(arguments=arguments), patch.object(mcp_server, "get_asset_engine") as get_engine:
                result = mcp_server.handle_tool_call({"name": "local_gpu_finalize_run", "arguments": arguments})

                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["category"], "validation")
                get_engine.assert_not_called()

    def test_finalize_run_forwards_nominated_round_to_engine(self) -> None:
        arguments = {
            "run_id": "run-1",
            "round_number": 2,
            "summary": "Use round two.",
            "confirmation": "finalize:run-1:2:" + "a" * 64,
        }
        engine = Mock()
        engine.finalize_run.return_value = {
            "ok": True,
            "run_id": "run-1",
            "state": "finalized",
            "final": {"round_number": 2, "quality_status": "accepted"},
            "full_image_path": "D:/output/final.png",
            "recoverable_next_actions": ["get_run", "cleanup_run"],
            "warnings": [],
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            result = mcp_server.handle_tool_call({"name": "local_gpu_finalize_run", "arguments": arguments})

        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["final"]["round_number"], 2)
        engine.finalize_run.assert_called_once_with(arguments)

    def test_finalize_run_rejects_nested_postprocess_errors_before_engine_work(self) -> None:
        base = {
            "run_id": "run-1",
            "round_number": 1,
            "summary": "Done.",
            "confirmation": "finalize:run-1:1:" + "a" * 64,
        }
        cases = (
            ({}, "missing_argument"),
            ({"type": "anime_upscale"}, "missing_argument"),
            ({"model": "realesrgan-x4plus-anime"}, "missing_argument"),
            ({"type": "anime_upscale", "model": "realesrgan-x4plus-anime", "extra": True}, "unknown_argument"),
            ({"type": "other", "model": "realesrgan-x4plus-anime"}, "invalid_argument_value"),
            ({"type": "anime_upscale", "model": "../../model"}, "invalid_argument_value"),
            ({"type": "anime_upscale", "model": 1}, "invalid_argument_type"),
        )
        for postprocess, expected_code in cases:
            arguments = {**base, "postprocess": postprocess}
            with self.subTest(postprocess=postprocess), patch.object(mcp_server, "get_asset_engine") as get_engine:
                result = mcp_server.handle_tool_call({"name": "local_gpu_finalize_run", "arguments": arguments})

                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["code"], expected_code)
                get_engine.assert_not_called()

    def test_finalize_run_forwards_exact_postprocess_object_unchanged(self) -> None:
        postprocess = {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"}
        arguments = {
            "run_id": "run-1",
            "round_number": 1,
            "summary": "Publish the 4x result.",
            "confirmation": "finalize:run-1:1:" + "a" * 64,
            "postprocess": postprocess,
        }
        engine = Mock()
        engine.finalize_run.return_value = {
            "ok": True,
            "run_id": "run-1",
            "state": "finalized",
            "final": {"round_number": 1, "quality_status": "accepted"},
            "full_image_path": "D:/output/final-upscaled.png",
            "recoverable_next_actions": ["get_run", "cleanup_run"],
            "warnings": [],
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            result = mcp_server.handle_tool_call({"name": "local_gpu_finalize_run", "arguments": arguments})

        self.assertFalse(result["isError"])
        engine.finalize_run.assert_called_once_with(arguments)
        self.assertIs(engine.finalize_run.call_args.args[0]["postprocess"], postprocess)

    def test_cleanup_all_requires_exact_confirmation_before_engine_work(self) -> None:
        with patch.object(mcp_server, "get_asset_engine", create=True) as get_engine:
            result = mcp_server.handle_tool_call({
                "name": "local_gpu_cleanup_run",
                "arguments": {"run_id": "run-1", "scope": "all", "confirmation": "wrong"},
            })
        self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_confirmation")
        get_engine.assert_not_called()

    def test_revision_and_mask_tools_dispatch_exact_arguments(self) -> None:
        branch_arguments = {
            "parent_run_id": "run-parent",
            "parent_round": 1,
            "contract": {
                "preserve": [{"target": "subject", "strength": "hard"}],
                "change": ["calmer lighting"],
            },
            "max_rounds": 2,
            "edit_mode": "img2img",
            "denoising_strength": 0.25,
        }
        confirm_arguments = {"run_id": "run-child", "mask_id": "mask-01"}
        engine = Mock()
        engine.branch_run.return_value = {"ok": True, "run_id": "run-child", "state": "created", "warnings": []}
        engine.confirm_mask.return_value = {
            "ok": True,
            "run_id": "run-child",
            "mask_id": "mask-01",
            "confirmed": True,
            "warnings": [],
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            branch_result = mcp_server.handle_tool_call({
                "name": "local_gpu_branch_run",
                "arguments": branch_arguments,
            })
            confirm_result = mcp_server.handle_tool_call({
                "name": "local_gpu_confirm_mask",
                "arguments": confirm_arguments,
            })

        self.assertFalse(branch_result["isError"])
        self.assertFalse(confirm_result["isError"])
        engine.branch_run.assert_called_once_with(branch_arguments)
        engine.confirm_mask.assert_called_once_with(confirm_arguments)

    def test_prepare_mask_returns_text_then_jpeg_overlay(self) -> None:
        data = {
            "ok": True,
            "run_id": "run-child",
            "mask_id": "mask-01",
            "confirmed": False,
            "warnings": [],
        }
        preview = PreviewResult(Path("mask-01-overlay.jpg"), "image/jpeg", "b3ZlcmxheQ==", 32, 32, None)
        engine = Mock()
        engine.prepare_mask.return_value = (data, preview)
        arguments = {
            "run_id": "run-child",
            "geometry": [{"type": "rectangle", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}],
            "feather_pixels": 0,
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            result = mcp_server.handle_tool_call({"name": "local_gpu_prepare_mask", "arguments": arguments})

        self.assertFalse(result["isError"])
        self.assertEqual([block["type"] for block in result["content"]], ["text", "image"])
        self.assertEqual(result["content"][1]["mimeType"], "image/jpeg")
        self.assertEqual(result["content"][1]["data"], "b3ZlcmxheQ==")
        engine.prepare_mask.assert_called_once_with(arguments)

    def test_generate_round_returns_text_then_bounded_jpeg_image(self) -> None:
        data = {
            "ok": True,
            "run_id": "run-1",
            "state": "generated",
            "round": {"round_number": 1},
            "full_image_path": "D:/output/round-01.png",
            "warnings": [],
        }
        preview = PreviewResult(Path("round-01.preview.jpg"), "image/jpeg", "amFzZw==", 32, 32, None)
        engine = Mock()
        engine.generate_round.return_value = (data, preview)
        arguments = {
            "run_id": "run-1",
            "idempotency_key": "initial-1",
            "action": "initial",
            "edit_mode": "txt2img",
            "plan": {},
            "seed": 42,
            "change_summary": "Initial candidate.",
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine, create=True):
            result = mcp_server.handle_tool_call({"name": "local_gpu_generate_round", "arguments": arguments})

        self.assertFalse(result["isError"])
        self.assertEqual([block["type"] for block in result["content"]], ["text", "image"])
        self.assertEqual(result["content"][1]["mimeType"], "image/jpeg")
        self.assertEqual(result["content"][1]["data"], "amFzZw==")
        self.assertNotIn("data", result["structuredContent"])

    def test_child_review_forwards_optional_preservation_results(self) -> None:
        preservation_results = [
            {"target": "subject", "status": "preserved", "observation": "Identity matches."},
        ]
        arguments = {
            "run_id": "run-child",
            "round_number": 1,
            "scores": {"composition": 4},
            "hard_failures": [],
            "critique": "Reviewed child candidate.",
            "constraint_results": {},
            "visual_checks": visual_checks(),
            "preservation_results": preservation_results,
            "next_action": "finalize",
        }
        engine = Mock()
        engine.record_review.return_value = {
            "ok": True,
            "run_id": "run-child",
            "state": "reviewed",
            "rounds": [],
            "reviews": [],
            "recoverable_next_actions": ["finalize_run"],
            "warnings": [],
        }
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            result = mcp_server.handle_tool_call({"name": "local_gpu_record_review", "arguments": arguments})

        self.assertFalse(result["isError"])
        forwarded = engine.record_review.call_args.args[0]
        self.assertEqual(forwarded["review"]["preservation_results"], preservation_results)
        self.assertIs(forwarded["review"]["visual_checks"], arguments["visual_checks"])

    def test_generate_round_rejects_nested_non_txt2img_mode_before_engine_work(self) -> None:
        for nested_mode in ("img2img", "inpaint"):
            arguments = {
                "run_id": "run-1",
                "idempotency_key": f"initial-{nested_mode}",
                "action": "initial",
                "edit_mode": "txt2img",
                "plan": {"parameters": {"mode": nested_mode}},
                "seed": 42,
                "change_summary": "Initial candidate.",
            }
            engine = Mock()
            engine.generate_round.return_value = ({"ok": True, "warnings": []}, None)
            with self.subTest(nested_mode=nested_mode), patch.object(
                mcp_server, "get_asset_engine", return_value=engine
            ) as get_engine:
                result = mcp_server.handle_tool_call({"name": "local_gpu_generate_round", "arguments": arguments})

                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["code"], "edit_mode_mismatch")
                get_engine.assert_not_called()

    def test_oversized_preview_is_not_added_to_mcp_content(self) -> None:
        encoded_limit = 4 * ((1024 * 1024 + 2) // 3)
        preview = PreviewResult(
            Path("round-01.preview.jpg"), "image/jpeg", "A" * (encoded_limit + 1), 768, 768, None
        )
        self.assertIsNone(mcp_server._preview_block(preview))

    def test_asset_engine_error_is_converted_without_rewriting_fields(self) -> None:
        engine = Mock()
        engine.get_run.side_effect = AssetEngineError(
            "missing_run", "Run was not found.", "state", {"run_id": "run-1"}
        )
        with patch.object(mcp_server, "get_asset_engine", return_value=engine, create=True):
            result = mcp_server.handle_tool_call({
                "name": "local_gpu_get_run", "arguments": {"run_id": "run-1"},
            })
        self.assertEqual(result["structuredContent"]["error"], {
            "code": "missing_run",
            "category": "state",
            "message": "Run was not found.",
            "details": {"run_id": "run-1"},
        })

    def test_asset_engine_error_preserves_empty_details(self) -> None:
        engine = Mock()
        engine.get_run.side_effect = AssetEngineError("run_busy", "Run is busy.", "conflict")
        with patch.object(mcp_server, "get_asset_engine", return_value=engine):
            result = mcp_server.handle_tool_call({
                "name": "local_gpu_get_run", "arguments": {"run_id": "run-1"},
            })
        self.assertEqual(result["structuredContent"]["error"].get("details"), {})

    def test_missing_prompt_returns_tool_error(self) -> None:
        result = mcp_server.handle_tool_call({"name": "local_gpu_generate_image", "arguments": {}})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_prompt")
        self.assertIn("non-empty prompt", result["structuredContent"]["error"]["message"])

    def test_invalid_lora_type_returns_tool_error(self) -> None:
        result = mcp_server.handle_tool_call(
            {"name": "local_gpu_generate_image", "arguments": {"prompt": "test", "lora": "not-a-list"}}
        )
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["category"], "validation")
        self.assertIn("array of strings", result["structuredContent"]["error"]["message"])

    def test_unknown_tool_returns_tool_error(self) -> None:
        result = mcp_server.handle_tool_call({"name": "missing", "arguments": {}})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "unknown_tool")

    def test_command_timeout_returns_structured_tool_error(self) -> None:
        with patch.object(mcp_server, "run_script", return_value=(124, "", "generate_image.py timed out")):
            result = mcp_server.handle_tool_call(
                {"name": "local_gpu_generate_image", "arguments": {"prompt": "test"}}
            )

        error = result["structuredContent"]["error"]
        self.assertTrue(result["isError"])
        self.assertEqual(error["code"], "command_timeout")
        self.assertEqual(error["category"], "timeout")

    def test_empty_array_arguments_are_rejected(self) -> None:
        result = mcp_server.handle_tool_call({"name": "local_gpu_imagegen_check", "arguments": []})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_arguments")

    def test_unknown_argument_is_rejected_before_subprocess(self) -> None:
        with patch.object(mcp_server, "run_script") as run_script:
            result = mcp_server.handle_tool_call(
                {"name": "local_gpu_generate_image", "arguments": {"prompt": "test", "surprise": True}}
            )

        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "unknown_argument")
        run_script.assert_not_called()

    def test_invalid_dimensions_are_rejected_before_subprocess(self) -> None:
        with patch.object(mcp_server, "run_script") as run_script:
            result = mcp_server.handle_tool_call(
                {"name": "local_gpu_generate_image", "arguments": {"prompt": "test", "width": 513}}
            )

        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_dimensions")
        run_script.assert_not_called()

    def test_not_ready_check_is_a_structured_status_not_tool_failure(self) -> None:
        report = {"ready": False, "diffusers_ready": False, "webui_ready": False}
        with patch.object(mcp_server, "run_script", return_value=(1, json.dumps(report), "")):
            result = mcp_server.handle_tool_call({"name": "local_gpu_imagegen_check", "arguments": {}})

        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], report)

    def test_crashed_check_is_not_treated_as_not_ready_status(self) -> None:
        with patch.object(mcp_server, "run_script", return_value=(1, "", "torch import crashed")):
            result = mcp_server.handle_tool_call({"name": "local_gpu_imagegen_check", "arguments": {}})

        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "backend_command_failed")
        self.assertIn("torch import crashed", result["content"][0]["text"])

    def test_generation_success_returns_structured_content(self) -> None:
        report = {"ok": True, "path": "output.png", "backend": "webui", "mode": "txt2img"}
        with patch.object(mcp_server, "run_script", return_value=(0, json.dumps(report), "")):
            result = mcp_server.handle_tool_call(
                {"name": "local_gpu_generate_image", "arguments": {"prompt": "test"}}
            )

        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], report)

    def test_low_level_model_option_remains_compatibility_passthrough(self) -> None:
        tool = next(tool for tool in mcp_server.tool_schema() if tool["name"] == "local_gpu_generate_image")
        self.assertEqual(tool["inputSchema"]["required"], ["prompt"])
        self.assertIn("model", tool["inputSchema"]["properties"])
        report = {"ok": True, "path": "output.png", "backend": "diffusers", "mode": "txt2img"}
        with patch.object(mcp_server, "_approved_model_ids") as approved_models, patch.object(
            mcp_server, "run_script", return_value=(0, json.dumps(report), "")
        ) as run_script:
            result = mcp_server.handle_tool_call({
                "name": "local_gpu_generate_image",
                "arguments": {"prompt": "test", "model": "advanced/local-checkpoint"},
            })

        self.assertFalse(result["isError"])
        approved_models.assert_not_called()
        command = run_script.call_args.args[1]
        self.assertEqual(command[command.index("--model") + 1], "advanced/local-checkpoint")

    def test_download_permission_is_forwarded_only_when_enabled(self) -> None:
        report = {"ok": True, "path": "output.png", "backend": "diffusers", "mode": "txt2img"}
        with patch.object(mcp_server, "run_script", return_value=(0, json.dumps(report), "")) as run_script:
            mcp_server.handle_tool_call(
                {
                    "name": "local_gpu_generate_image",
                    "arguments": {"prompt": "test", "allow_download": True},
                }
            )

        self.assertIn("--allow-download", run_script.call_args.args[1])


class McpServerProtocolTests(unittest.TestCase):
    def test_protocol_only_requests_do_not_create_engine_or_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "must-not-exist"
            requests = "\n".join(
                json.dumps({"jsonrpc": "2.0", "id": index, "method": method, "params": {}})
                for index, method in enumerate(("initialize", "tools/list", "ping"), start=1)
            )
            environment = dict(os.environ)
            environment["LOCAL_GPU_IMAGEGEN_OUTPUT_DIR"] = str(output_dir)
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "mcp_server.py")],
                input=requests + "\n",
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
                env=environment,
            )
            self.assertEqual(len(completed.stdout.splitlines()), 3)
            self.assertFalse(output_dir.exists())

    def test_utf8_bom_is_accepted_for_windows_stdio_diagnostics(self) -> None:
        request = '\ufeff{"jsonrpc":"2.0","id":9,"method":"ping"}'
        with patch.object(mcp_server, "send") as send:
            mcp_server.process_line(request)

        self.assertEqual(send.call_args.args[0]["id"], 9)
        self.assertEqual(send.call_args.args[0]["result"], {})

    def test_initialize_and_list_tools_over_stdio(self) -> None:
        requests = "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}}),
            ]
        )
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            input=requests + "\n",
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "local-gpu-imagegen")
        self.assertEqual(responses[0]["result"]["serverInfo"]["version"], "0.7.0")
        self.assertEqual(responses[1]["result"]["tools"][0]["name"], "local_gpu_imagegen_check")
        self.assertEqual(responses[2]["result"], {})

    def test_bundled_mcp_config_is_portable_and_launches(self) -> None:
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["local-gpu-imagegen"]
        self.assertTrue(all(not Path(argument).is_absolute() for argument in server["args"]))

        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        completed = subprocess.run(
            [server["command"], *server["args"]],
            cwd=ROOT / server["cwd"],
            input=request + "\n",
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

        response = json.loads(completed.stdout)
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "local-gpu-imagegen")

    def test_invalid_call_params_preserve_request_id(self) -> None:
        request = json.dumps({"jsonrpc": "2.0", "id": "request-7", "method": "tools/call", "params": []})
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            input=request + "\n",
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

        response = json.loads(completed.stdout)
        self.assertEqual(response["id"], "request-7")
        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["data"]["category"], "invalid_params")


if __name__ == "__main__":
    unittest.main()
