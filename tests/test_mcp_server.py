from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mcp_server  # noqa: E402
from local_gpu_imagegen.errors import AssetEngineError  # noqa: E402
from local_gpu_imagegen.preview import PreviewResult  # noqa: E402


EXPECTED_TOOLS = {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
    "local_gpu_list_profiles",
    "local_gpu_start_run",
    "local_gpu_get_run",
    "local_gpu_generate_round",
    "local_gpu_record_review",
    "local_gpu_finalize_run",
    "local_gpu_cleanup_run",
}

HIGH_LEVEL_TOOLS = EXPECTED_TOOLS - {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
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
        self.assertEqual(plugin["version"], "0.4.0")
        self.assertEqual(mcp_server.SERVER_VERSION, "0.4.0")

    def test_high_level_input_contracts_are_exact(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        expected = {
            "local_gpu_list_profiles": set(),
            "local_gpu_start_run": {
                "intent", "profile", "style", "constraints", "model_choice", "backend", "max_rounds",
                "upscale_policy",
            },
            "local_gpu_get_run": {"run_id"},
            "local_gpu_generate_round": {
                "run_id", "idempotency_key", "action", "edit_mode", "plan", "seed", "change_summary",
            },
            "local_gpu_record_review": {
                "run_id", "round_number", "scores", "hard_failures", "critique", "constraint_results", "next_action",
            },
            "local_gpu_finalize_run": {"run_id", "round_number", "summary", "postprocess"},
            "local_gpu_cleanup_run": {"run_id", "scope", "confirmation"},
        }
        for name, fields in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, tools)
                if name not in tools:
                    continue
                schema = tools[name]["inputSchema"]
                self.assertEqual(set(schema["properties"]), fields)
                required = fields - {"postprocess"}
                self.assertEqual(set(schema.get("required", [])), required)

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
                "intent": "valid", "profile": "missing-profile", "style": None, "constraints": {},
                "model_choice": "stabilityai/sd-turbo", "backend": "auto", "max_rounds": 3,
                "upscale_policy": "auto",
            }),
            ("local_gpu_get_run", {"run_id": 1}),
            ("local_gpu_generate_round", {
                "run_id": "run-1", "idempotency_key": "key", "action": "initial", "edit_mode": "img2img",
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
        report = {"ready": True, "webui_ready": True, "diffusers_ready": False}
        with patch.object(mcp_server, "run_script", return_value=(0, json.dumps(report), "")):
            capabilities = mcp_server.get_capabilities()
        self.assertEqual(capabilities["available_backends"], ["webui"])

    def test_start_run_rejects_empty_intent_before_engine_work(self) -> None:
        arguments = {
            "intent": " ",
            "profile": "standalone-illustration",
            "style": None,
            "constraints": {},
            "model_choice": "stabilityai/sd-turbo",
            "backend": "auto",
            "max_rounds": 3,
            "upscale_policy": "auto",
        }
        with patch.object(mcp_server, "get_asset_engine", create=True) as get_engine:
            result = mcp_server.handle_tool_call({"name": "local_gpu_start_run", "arguments": arguments})
        self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_argument_value")
        get_engine.assert_not_called()

    def test_start_run_rejects_missing_or_unapproved_model_before_engine_work(self) -> None:
        base = {
            "intent": "A calm coast at dawn.",
            "profile": "standalone-illustration",
            "style": None,
            "constraints": {},
            "backend": "auto",
            "max_rounds": 3,
            "upscale_policy": "auto",
        }
        cases = (
            (None, "missing_argument"),
            (" ", "invalid_argument_value"),
            ("missing/model", "invalid_argument_value"),
            ("stabilityai/sd-turbo", "invalid_argument_value"),
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
        arguments = {
            "intent": "A calm coast at dawn.",
            "profile": "standalone-illustration",
            "style": None,
            "constraints": {},
            "model_choice": "test/approved-anime",
            "backend": "webui",
            "max_rounds": 3,
            "upscale_policy": "off",
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
        with patch.object(mcp_server, "_approved_model_ids", return_value=["test/approved-anime"]), patch.object(
            mcp_server, "get_asset_engine", return_value=engine
        ):
            result = mcp_server.handle_tool_call({"name": "local_gpu_start_run", "arguments": arguments})

        self.assertFalse(result["isError"])
        engine.start_run.assert_called_once_with(arguments)

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
        arguments = {"run_id": "run-1", "round_number": 2, "summary": "Use round two."}
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
        base = {"run_id": "run-1", "round_number": 1, "summary": "Done."}
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
        self.assertEqual(responses[0]["result"]["serverInfo"]["version"], "0.4.0")
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
