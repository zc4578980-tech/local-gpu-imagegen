from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def result_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def tool_call(sequence: int, name: str, result: dict[str, object]) -> dict[str, object]:
    return {
        "sequence": sequence,
        "name": name,
        "result": result,
        "result_sha256": result_sha256(result),
    }


def valid_session(client: str = "codex") -> dict[str, object]:
    lifecycle_result = {"run_id": "public-demo-run", "state": "finalized"}
    return {
        "schema_version": "1.0",
        "evidence_class": "named_client_session",
        "client": {
            "name": client,
            "version": "codex-cli 0.144.5" if client == "codex" else "2.1.195 (Claude Code)",
            "session_mode": "ephemeral" if client == "codex" else "no_session_persistence",
        },
        "installed_wheel": True,
        "hosted_client_session": True,
        "server": {
            "name": "local-gpu-imagegen",
            "version": "0.6.1",
            "protocol_version": "2024-11-05",
            "wheel_sha256": "a" * 64,
        },
        "started_at": "2026-07-22T10:00:00Z",
        "completed_at": "2026-07-22T10:02:00Z",
        "tool_calls": [
            tool_call(1, "local_gpu_imagegen_check", {"ready": True, "backend": "comfyui"}),
            tool_call(2, "local_gpu_get_run", lifecycle_result),
        ],
        "sanitization": {
            "prompts_omitted": True,
            "account_identifiers_omitted": True,
            "credentials_omitted": True,
            "machine_paths_omitted": True,
            "raw_transcript_retained": False,
        },
    }


class ClientSessionEvidenceTests(unittest.TestCase):
    def test_accepts_real_installed_named_client_calls(self) -> None:
        from validate_client_sessions import validate_session

        for client in ("codex", "claude-code"):
            with self.subTest(client=client):
                self.assertEqual(
                    validate_session(valid_session(client), expected_server_version="0.6.1"),
                    [],
                )

    def test_rejects_config_only_source_checkout_and_version_mismatch(self) -> None:
        from validate_client_sessions import validate_session

        mutations = (
            ("hosted_client_session", False, "hosted_client_session_required"),
            ("installed_wheel", False, "installed_wheel_required"),
        )
        for key, value, finding in mutations:
            document = valid_session("claude-code")
            document[key] = value
            with self.subTest(key=key):
                self.assertIn(
                    finding,
                    validate_session(document, expected_server_version="0.6.1"),
                )

        document = valid_session()
        document["server"]["version"] = "0.6.0"
        self.assertIn(
            "server_version_mismatch",
            validate_session(document, expected_server_version="0.6.1"),
        )

    def test_rejects_private_values_and_unhashed_results(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session()
        document["tool_calls"][1]["result"] = {
            "path": "C:\\Users\\Capricorn\\private.png"
        }

        findings = validate_session(document, expected_server_version="0.6.1")

        self.assertIn("private_value", findings)
        self.assertIn("result_sha256_mismatch", findings)

    def test_rejects_bad_sequence_time_and_required_tool_coverage(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session()
        document["completed_at"] = "2026-07-22T09:59:00Z"
        document["tool_calls"][1]["sequence"] = 4
        document["tool_calls"] = document["tool_calls"][:1]

        findings = validate_session(document, expected_server_version="0.6.1")

        self.assertIn("invalid_time_order", findings)
        self.assertIn("missing_required_tool_calls", findings)

        document = valid_session()
        document["tool_calls"][1]["sequence"] = 4
        self.assertIn(
            "invalid_tool_sequence",
            validate_session(document, expected_server_version="0.6.1"),
        )

    def test_rejects_wrong_session_mode_unknown_fields_and_false_sanitization(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session("codex")
        document["client"]["session_mode"] = "persistent"
        document["unexpected"] = True
        document["sanitization"]["credentials_omitted"] = False

        findings = validate_session(document, expected_server_version="0.6.1")

        self.assertIn("invalid_session_mode", findings)
        self.assertIn("invalid_top_level_fields", findings)
        self.assertIn("invalid_sanitization", findings)

    def test_schema_is_closed_and_pins_the_public_shape(self) -> None:
        schema = json.loads(
            (ROOT / "docs" / "evidence" / "schemas" / "client-session.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["evidence_class"]["const"], "named_client_session")
        self.assertEqual(schema["properties"]["client"]["properties"]["name"]["enum"], ["codex", "claude-code"])
        for name in ("client", "server", "sanitization"):
            self.assertFalse(schema["properties"][name]["additionalProperties"])

    def test_cli_validates_multiple_documents_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "codex.json"
            second = root / "claude-code.json"
            first.write_text(json.dumps(valid_session("codex")), encoding="utf-8")
            second.write_text(json.dumps(valid_session("claude-code")), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_client_sessions.py"),
                    "--expected-server-version",
                    "0.6.1",
                    str(first),
                    str(second),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["validated_files"], 2)


if __name__ == "__main__":
    unittest.main()
