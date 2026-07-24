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


def valid_session(
    client: str = "codex",
    purpose: str = "compatibility",
) -> dict[str, object]:
    lifecycle_result = {"run_id": "public-demo-run", "state": "finalized"}
    document = {
        "schema_version": "1.0",
        "evidence_class": "named_client_session",
        "session_purpose": purpose,
        "client": {
            "name": client,
            "version": "codex-cli 0.144.5" if client == "codex" else "2.1.195 (Claude Code)",
            "session_mode": "ephemeral" if client == "codex" else "no_session_persistence",
        },
        "installed_wheel": True,
        "hosted_client_session": True,
        "server": {
            "name": "local-gpu-imagegen",
            "version": "0.7.0",
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
    if purpose == "golden_generation":
        document["tool_calls"] = [
            tool_call(1, "local_gpu_imagegen_check", {"ready": True, "backend": "comfyui"}),
            tool_call(
                2,
                "local_gpu_start_run",
                {"run_id": "public-demo-run", "state": "confirmed"},
            ),
            tool_call(
                3,
                "local_gpu_generate_round",
                {
                    "run_id": "public-demo-run",
                    "state": "generated",
                    "round_number": 1,
                    "image_sha256": "b" * 64,
                },
            ),
        ]
    if purpose == "workflow_onboarding":
        document["server"]["version"] = "0.8.0"
        workflow_sha256 = "f" * 64
        source_sha256 = "e" * 64
        registered_id = f"imported:{workflow_sha256}"
        api_identity = "model:" + "a" * 64
        filesystem_identity = "model:" + "b" * 64
        bundle_sha256 = "c" * 64
        document["tool_calls"] = [
            tool_call(
                1,
                "local_gpu_discover_models",
                {
                    "phase": "api_only_execute",
                    "backend": "comfyui",
                    "target_model_present": True,
                    "candidate_count": 12,
                    "target_identity_strength": "backend_binding",
                    "target_model_identity": api_identity,
                },
            ),
            tool_call(
                2,
                "local_gpu_inspect_workflow",
                {
                    "status": "registerable",
                    "registrable": True,
                    "source_sha256": source_sha256,
                    "workflow_sha256": workflow_sha256,
                    "proposal_digest": "d" * 64,
                    "confirmation_sha256": "1" * 64,
                    "topology": "single_checkpoint",
                    "component_identities": [api_identity],
                },
            ),
            tool_call(
                3,
                "local_gpu_discover_models",
                {
                    "phase": "selected_fingerprint_execute",
                    "target_model_present": True,
                    "candidate_count": 1,
                    "target_identity_strength": "cryptographic",
                    "target_model_identity": filesystem_identity,
                    "target_sha256": "2" * 64,
                    "target_byte_size": 6938078334,
                },
            ),
            tool_call(
                4,
                "local_gpu_register_workflow",
                {
                    "registered_workflow_id": registered_id,
                    "template_version": 1,
                    "source_sha256": source_sha256,
                    "workflow_sha256": workflow_sha256,
                    "topology": "single_checkpoint",
                },
            ),
            tool_call(
                5,
                "local_gpu_set_model_trust",
                {
                    "action": "inspect_workflow_binding",
                    "model_identity": filesystem_identity,
                    "registered_workflow_id": registered_id,
                    "workflow_sha256": workflow_sha256,
                    "component_bundle_sha256": bundle_sha256,
                    "approve_private_confirmation_sha256": "3" * 64,
                },
            ),
            tool_call(
                6,
                "local_gpu_set_model_trust",
                {
                    "action": "approve_private",
                    "catalog_id": "local:" + "4" * 24,
                    "model_identity": filesystem_identity,
                    "scope": "private",
                    "identity_strength": "cryptographic",
                    "registered_workflow_id": registered_id,
                    "workflow_sha256": workflow_sha256,
                    "component_bundle_sha256": bundle_sha256,
                },
            ),
        ]
    return document


def release_set_findings(
    documents: list[object],
    *,
    expected_server_version: str = "0.7.0",
) -> list[str]:
    import validate_client_sessions

    validator = getattr(validate_client_sessions, "validate_release_set", None)
    if not callable(validator):
        return ["validate_release_set_missing"]
    return validator(
        documents,
        expected_server_version=expected_server_version,
    )


class ClientSessionEvidenceTests(unittest.TestCase):
    def test_accepts_real_installed_named_client_calls(self) -> None:
        from validate_client_sessions import validate_session

        for client in ("codex", "claude-code"):
            with self.subTest(client=client):
                self.assertEqual(
                    validate_session(valid_session(client), expected_server_version="0.7.0"),
                    [],
                )

    def test_accepts_golden_generation_with_exact_observable_result(self) -> None:
        from validate_client_sessions import validate_session

        self.assertEqual(
            validate_session(
                valid_session("codex", "golden_generation"),
                expected_server_version="0.7.0",
            ),
            [],
        )

    def test_accepts_golden_generation_without_redundant_health_check(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session("codex", "golden_generation")
        document["tool_calls"] = document["tool_calls"][1:]
        for sequence, call in enumerate(document["tool_calls"], start=1):
            call["sequence"] = sequence

        self.assertEqual(
            validate_session(document, expected_server_version="0.7.0"),
            [],
        )

    def test_accepts_workflow_onboarding_zero_gpu_sequence(self) -> None:
        from validate_client_sessions import validate_session

        self.assertEqual(
            validate_session(
                valid_session("codex", "workflow_onboarding"),
                expected_server_version="0.8.0",
            ),
            [],
        )

    def test_rejects_invalid_purpose_and_missing_golden_generation_calls(self) -> None:
        from validate_client_sessions import validate_session

        malformed = valid_session()
        malformed["session_purpose"] = "demo"
        self.assertIn(
            "invalid_session_purpose",
            validate_session(malformed, expected_server_version="0.7.0"),
        )

        missing_calls = valid_session("codex", "golden_generation")
        missing_calls["tool_calls"] = missing_calls["tool_calls"][:1]
        self.assertIn(
            "missing_golden_generation_calls",
            validate_session(missing_calls, expected_server_version="0.7.0"),
        )

    def test_rejects_invalid_golden_generation_result(self) -> None:
        from validate_client_sessions import validate_session

        mutations = (
            {"state": "generated", "round_number": 1, "image_sha256": "b" * 64},
            {
                "run_id": "public-demo-run",
                "state": "generated",
                "round_number": 0,
                "image_sha256": "b" * 64,
            },
            {
                "run_id": "public-demo-run",
                "state": "generated",
                "round_number": 1,
                "image_sha256": "B" * 64,
            },
        )
        for result in mutations:
            document = valid_session("codex", "golden_generation")
            document["tool_calls"][2] = tool_call(
                3,
                "local_gpu_generate_round",
                result,
            )
            with self.subTest(result=result):
                self.assertIn(
                    "invalid_golden_generation_result",
                    validate_session(document, expected_server_version="0.7.0"),
                )

    def test_rejects_workflow_onboarding_reordered_or_generation_sequence(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session("codex", "workflow_onboarding")
        document["tool_calls"][3], document["tool_calls"][4] = (
            document["tool_calls"][4],
            document["tool_calls"][3],
        )
        for sequence, call in enumerate(document["tool_calls"], start=1):
            call["sequence"] = sequence
        self.assertIn(
            "invalid_workflow_onboarding_sequence",
            validate_session(document, expected_server_version="0.8.0"),
        )

        generated = valid_session("codex", "workflow_onboarding")
        generated["tool_calls"][2] = tool_call(
            3,
            "local_gpu_generate_round",
            {"run_id": "public-demo-run", "state": "generated", "round_number": 1, "image_sha256": "5" * 64},
        )
        self.assertIn(
            "forbidden_workflow_onboarding_generation_call",
            validate_session(generated, expected_server_version="0.8.0"),
        )

    def test_rejects_workflow_onboarding_drifted_hashes_and_trust_identity(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session("codex", "workflow_onboarding")
        document["tool_calls"][3] = tool_call(
            4,
            "local_gpu_register_workflow",
            {
                **document["tool_calls"][3]["result"],
                "workflow_sha256": "6" * 64,
            },
        )
        self.assertIn(
            "invalid_workflow_onboarding_registration",
            validate_session(document, expected_server_version="0.8.0"),
        )

        document = valid_session("codex", "workflow_onboarding")
        document["tool_calls"][5] = tool_call(
            6,
            "local_gpu_set_model_trust",
            {
                **document["tool_calls"][5]["result"],
                "model_identity": "model:" + "7" * 64,
            },
        )
        self.assertIn(
            "invalid_workflow_onboarding_trust_approval",
            validate_session(document, expected_server_version="0.8.0"),
        )

    def test_release_set_requires_exact_named_clients_and_one_golden_session(self) -> None:
        valid = [
            valid_session("codex", "golden_generation"),
            valid_session("claude-code"),
        ]
        self.assertEqual(release_set_findings(valid), [])

        duplicate = [
            valid_session("codex", "golden_generation"),
            valid_session("codex"),
        ]
        self.assertIn("named_client_release_set_required", release_set_findings(duplicate))
        self.assertIn(
            "named_client_release_set_required",
            release_set_findings([valid_session("codex", "golden_generation")]),
        )

        compatibility_only = [valid_session("codex"), valid_session("claude-code")]
        self.assertIn(
            "golden_generation_session_required",
            release_set_findings(compatibility_only),
        )

    def test_release_set_rejects_mixed_server_versions(self) -> None:
        documents = [
            valid_session("codex", "golden_generation"),
            valid_session("claude-code"),
        ]
        documents[1]["server"]["version"] = "0.6.1"

        self.assertIn(
            "release_set_server_version_mismatch",
            release_set_findings(documents),
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
                    validate_session(document, expected_server_version="0.7.0"),
                )

        document = valid_session()
        document["server"]["version"] = "0.6.0"
        self.assertIn(
            "server_version_mismatch",
            validate_session(document, expected_server_version="0.7.0"),
        )

    def test_rejects_private_values_and_unhashed_results(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session()
        document["tool_calls"][1]["result"] = {
            "path": "C:\\Users\\Capricorn\\private.png"
        }

        findings = validate_session(document, expected_server_version="0.7.0")

        self.assertIn("private_value", findings)
        self.assertIn("result_sha256_mismatch", findings)

    def test_rejects_bad_sequence_time_and_required_tool_coverage(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session()
        document["completed_at"] = "2026-07-22T09:59:00Z"
        document["tool_calls"][1]["sequence"] = 4
        document["tool_calls"] = document["tool_calls"][:1]

        findings = validate_session(document, expected_server_version="0.7.0")

        self.assertIn("invalid_time_order", findings)
        self.assertIn("missing_required_tool_calls", findings)

        document = valid_session()
        document["tool_calls"][1]["sequence"] = 4
        self.assertIn(
            "invalid_tool_sequence",
            validate_session(document, expected_server_version="0.7.0"),
        )

    def test_rejects_wrong_session_mode_unknown_fields_and_false_sanitization(self) -> None:
        from validate_client_sessions import validate_session

        document = valid_session("codex")
        document["client"]["session_mode"] = "persistent"
        document["unexpected"] = True
        document["sanitization"]["credentials_omitted"] = False

        findings = validate_session(document, expected_server_version="0.7.0")

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
        self.assertIn("session_purpose", schema["properties"])
        self.assertEqual(
            schema["properties"]["session_purpose"]["enum"],
            ["compatibility", "golden_generation", "workflow_onboarding"],
        )
        self.assertIn("session_purpose", schema["required"])
        self.assertEqual(schema["properties"]["client"]["properties"]["name"]["enum"], ["codex", "claude-code"])
        for name in ("client", "server", "sanitization"):
            self.assertFalse(schema["properties"][name]["additionalProperties"])

    def test_cli_validates_multiple_documents_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "codex.json"
            second = root / "claude-code.json"
            first.write_text(
                json.dumps(valid_session("codex", "golden_generation")),
                encoding="utf-8",
            )
            second.write_text(json.dumps(valid_session("claude-code")), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_client_sessions.py"),
                    "--expected-server-version",
                    "0.7.0",
                    "--require-release-set",
                    str(first),
                    str(second),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["validated_files"], 2)
        self.assertEqual(report["release_set_findings"], [])


if __name__ == "__main__":
    unittest.main()
