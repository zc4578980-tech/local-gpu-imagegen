from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

if __package__:
    from .real_demo_helpers import read_json, sha256_file, write_json, write_source_fixture
else:
    from real_demo_helpers import read_json, sha256_file, write_json, write_source_fixture


class ValidateRealDemoTests(unittest.TestCase):
    def _export(self, base: Path) -> Path:
        from export_real_demo import export_real_demo

        run_root, client, mcp_result, authority, output = write_source_fixture(base)
        export_real_demo(
            run_root,
            output,
            client,
            mcp_result,
            authority_path=authority,
        )
        return output

    def test_valid_real_demo_binds_route_generation_final_and_every_artifact(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            self.assertEqual(validate_real_demo(output), [])

    def test_retained_v070_demo_validates_only_with_explicit_historical_version(
        self,
    ) -> None:
        from validate_real_demo import validate_real_demo

        retained = ROOT / "docs" / "demo" / "real"
        self.assertEqual(
            validate_real_demo(retained, expected_server_version="0.7.0"),
            [],
        )
        self.assertIn(
            "server_version_mismatch",
            validate_real_demo(retained, expected_server_version="0.8.0"),
        )

    def test_rejects_simulation_private_values_and_changed_image_bytes(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            manifest = read_json(output / "showcase-manifest.json")
            manifest["model_output"] = False
            manifest["route"]["backend_url"] = "http://127.0.0.1:8188"
            write_json(output / "showcase-manifest.json", manifest)
            (output / "final.png").write_bytes(b"changed")

            findings = validate_real_demo(output)

            self.assertIn("not_real_model_output", findings)
            self.assertIn("private_value", findings)
            self.assertIn("artifact_sha256_mismatch:final.png", findings)
            self.assertIn("invalid_final_png", findings)

    def test_rejects_extra_files_failed_review_client_digest_and_limitations(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            (output / "unexpected.txt").write_text("extra", encoding="utf-8")
            (output / "unexpected-directory").mkdir()
            manifest = read_json(output / "showcase-manifest.json")
            manifest["final"]["visual_checks"]["text_and_watermarks"][
                "status"
            ] = "uncertain"
            manifest["client_session"]["sha256"] = "0" * 64
            manifest["known_limitations"] = []
            write_json(output / "showcase-manifest.json", manifest)

            findings = validate_real_demo(output)

            self.assertIn("unexpected_demo_files", findings)
            self.assertIn("visual_checks_not_passed", findings)
            self.assertIn("client_session_sha256_mismatch", findings)
            self.assertIn("missing_known_limitations", findings)

    def test_rejects_symlinked_showcase_manifest(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = self._export(base)
            manifest_path = output / "showcase-manifest.json"
            external_manifest = base / "external-showcase-manifest.json"
            external_manifest.write_bytes(manifest_path.read_bytes())
            manifest_path.unlink()
            try:
                manifest_path.symlink_to(external_manifest)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            self.assertIn("invalid_showcase_manifest", validate_real_demo(output))

    def test_rejects_version_mcp_generation_finalization_and_route_drift(self) -> None:
        from validate_real_demo import validate_real_demo

        mutations = (
            ("installed_package", "version", "0.6.1", "server_version_mismatch"),
            ("mcp_result", "source_sha256", "0" * 64, "mcp_source_sha256_invalid"),
            ("generation", "positive_prompt", "", "invalid_generation_provenance"),
            ("final", "finalization_verified", False, "invalid_finalization"),
            (
                "route",
                "workflow_template_id",
                "sdxl-two-stage-copy-subject",
                "invalid_public_route",
            ),
        )
        for section, key, value, finding in mutations:
            with self.subTest(finding=finding), tempfile.TemporaryDirectory() as directory:
                output = self._export(Path(directory))
                manifest = read_json(output / "showcase-manifest.json")
                manifest[section][key] = value
                write_json(output / "showcase-manifest.json", manifest)

                self.assertIn(finding, validate_real_demo(output))

    def test_validator_rejects_generation_dimension_drift(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            manifest_path = output / "showcase-manifest.json"
            manifest = read_json(manifest_path)
            manifest["generation"]["width"] = 1280
            write_json(manifest_path, manifest)

            self.assertIn("invalid_generation_provenance", validate_real_demo(output))

    def test_rejects_changed_public_mcp_and_sanitized_manifest_bytes(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            (output / "mcp-result.json").write_text("{}\n", encoding="utf-8")
            (output / "run-manifest.json").write_text("{}\n", encoding="utf-8")

            findings = validate_real_demo(output)

            self.assertIn("artifact_sha256_mismatch:mcp-result.json", findings)
            self.assertIn("artifact_sha256_mismatch:run-manifest.json", findings)
            self.assertIn("invalid_public_mcp_result", findings)
            self.assertIn("run_manifest_mismatch", findings)

    def test_rejects_semantically_invalid_or_private_review(self) -> None:
        from validate_real_demo import validate_real_demo

        cases = (
            ("hard-failure", "invalid_review_evidence"),
            ("next-action", "invalid_review_evidence"),
            ("email", "private_value"),
            ("url", "private_value"),
            ("low-scores", "invalid_review_evidence"),
            ("fake-score-key", "invalid_review_evidence"),
            ("fake-constraint-key", "invalid_review_evidence"),
        )
        for case, finding in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                output = self._export(Path(directory))
                run_manifest_path = output / "run-manifest.json"
                run_manifest = read_json(run_manifest_path)
                review = run_manifest["review"]
                if case == "hard-failure":
                    review["hard_failures"] = ["explicit_constraint_violation"]
                elif case == "next-action":
                    review["next_action"] = "explore"
                elif case == "email":
                    review["critique"] = "Contact alice@example.com for details."
                elif case == "url":
                    review["critique"] = "Inspect https://private.example.test/run/1."
                elif case == "low-scores":
                    review["scores"] = {name: 1 for name in review["scores"]}
                elif case == "fake-score-key":
                    review["scores"] = {"not_the_rubric": 5}
                else:
                    review["constraint_results"] = {
                        "not_a_constraint": {
                            "status": "pass",
                            "observation": "Unrelated check passed.",
                        }
                    }
                write_json(run_manifest_path, run_manifest)
                showcase = read_json(output / "showcase-manifest.json")
                showcase["artifacts"]["run-manifest.json"]["sha256"] = sha256_file(
                    run_manifest_path
                )
                showcase["artifacts"]["run-manifest.json"]["bytes"] = (
                    run_manifest_path.stat().st_size
                )
                write_json(output / "showcase-manifest.json", showcase)

                self.assertIn(finding, validate_real_demo(output))

    def test_rejects_non_jpeg_preview_even_when_manifest_hash_matches(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            preview = output / "preview.jpg"
            preview.write_bytes(b"not a jpeg")
            showcase = read_json(output / "showcase-manifest.json")
            showcase["artifacts"]["preview.jpg"]["sha256"] = sha256_file(preview)
            showcase["artifacts"]["preview.jpg"]["bytes"] = preview.stat().st_size
            write_json(output / "showcase-manifest.json", showcase)

            self.assertIn("invalid_preview_jpeg", validate_real_demo(output))

    def test_cli_returns_machine_readable_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_real_demo.py"), str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["findings"], [])

    def test_schema_is_closed_and_pins_finalized_ordinary_output(self) -> None:
        schema = json.loads(
            (ROOT / "docs" / "evidence" / "schemas" / "real-demo.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], "2.0")
        self.assertEqual(
            schema["properties"]["demo_kind"]["const"],
            "real_local_gpu_generation",
        )
        self.assertEqual(schema["properties"]["model_output"]["const"], True)
        self.assertEqual(
            set(schema["required"]),
            {
                "schema_version",
                "demo_kind",
                "model_output",
                "installed_package",
                "public_rights",
                "route",
                "generation",
                "final",
                "client_session",
                "mcp_result",
                "artifacts",
                "known_limitations",
            },
        )
        for name in (
            "installed_package",
            "public_rights",
            "route",
            "generation",
            "final",
            "client_session",
            "mcp_result",
        ):
            self.assertFalse(schema["properties"][name]["additionalProperties"])
        artifacts = schema["properties"]["artifacts"]
        self.assertFalse(artifacts["additionalProperties"])
        self.assertEqual(
            set(artifacts["required"]),
            {
                "final.png",
                "preview.jpg",
                "run-manifest.json",
                "mcp-result.json",
                "transcript.md",
                "README.md",
            },
        )
        self.assertEqual(
            schema["properties"]["route"]["properties"]["model_id"]["const"],
            "local:1a4a27ae037d08ad44e98772",
        )
        self.assertEqual(
            schema["properties"]["public_rights"]["properties"]["license_id"]["const"],
            "CreativeML Open RAIL++-M",
        )
        self.assertTrue(
            schema["properties"]["final"]["properties"]["confirmation"]["pattern"]
        )
        dimension = schema["$defs"]["dimension"]
        self.assertEqual(
            dimension,
            {
                "maximum": 1536,
                "minimum": 256,
                "multipleOf": 8,
                "type": "integer",
            },
        )
        for section in ("final", "generation"):
            for field in ("width", "height"):
                self.assertEqual(
                    schema["properties"][section]["properties"][field],
                    {"$ref": "#/$defs/dimension"},
                )


if __name__ == "__main__":
    unittest.main()
