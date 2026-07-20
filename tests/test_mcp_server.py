from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mcp_server  # noqa: E402


class McpServerUnitTests(unittest.TestCase):
    def test_schema_exposes_expected_tools(self) -> None:
        tools = {tool["name"]: tool for tool in mcp_server.tool_schema()}
        self.assertEqual(set(tools), {"local_gpu_imagegen_check", "local_gpu_generate_image"})
        self.assertIn("prompt", tools["local_gpu_generate_image"]["inputSchema"]["required"])
        self.assertIn("allow_download", tools["local_gpu_generate_image"]["inputSchema"]["properties"])
        self.assertIn("outputSchema", tools["local_gpu_imagegen_check"])
        self.assertIn("outputSchema", tools["local_gpu_generate_image"])

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
