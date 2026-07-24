from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

if __package__:
    from .real_demo_helpers import read_json, sha256_file, write_json, write_source_fixture
else:
    from real_demo_helpers import read_json, sha256_file, write_json, write_source_fixture


EXPECTED_FILES = {
    "final.png",
    "preview.jpg",
    "run-manifest.json",
    "mcp-result.json",
    "transcript.md",
    "showcase-manifest.json",
    "README.md",
}


class ExportRealDemoTests(unittest.TestCase):
    def _export(self, base: Path) -> tuple[Path, Path, Path, Path, Path, dict[str, object]]:
        from export_real_demo import export_real_demo

        run_root, client, mcp_result, authority, output = write_source_fixture(base)
        manifest = export_real_demo(
            run_root,
            output,
            client,
            mcp_result,
            authority_path=authority,
        )
        return run_root, client, mcp_result, authority, output, manifest

    def test_export_copies_only_finalized_bytes_and_sanitizes_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run_root, _, mcp_result, _, output, manifest = self._export(base)

            self.assertEqual(
                (output / "final.png").read_bytes(),
                (run_root / "final.png").read_bytes(),
            )
            self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)
            self.assertEqual(manifest["demo_kind"], "real_local_gpu_generation")
            self.assertEqual(manifest["final"]["quality_status"], "accepted")
            self.assertEqual(
                manifest["mcp_result"]["source_sha256"],
                sha256_file(mcp_result),
            )
            source_review = read_json(run_root / "manifest.json")["reviews"][0]
            public_review = read_json(output / "run-manifest.json")["review"]
            self.assertEqual(public_review["constraint_results"], source_review["constraint_results"])
            self.assertEqual(public_review["critique"], source_review["critique"])
            self.assertEqual(set(public_review["scores"]), set(public_review["rubric"]))
            self.assertEqual(
                set(public_review["constraint_results"]),
                set(public_review["applicable_constraints"]),
            )
            public_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.iterdir()
                if path.suffix in {".json", ".md"}
            )
            self.assertNotIn(str(base), public_text)
            self.assertNotIn("endpoint:private-test", public_text)
            self.assertNotIn("private-job-id", public_text)
            self.assertFalse((output / "unrelated.tmp").exists())

    def test_export_rejects_child_missing_or_changed_final_and_existing_destination(self) -> None:
        from export_real_demo import export_real_demo

        cases = (
            ("child", "ordinary_root_required"),
            ("missing", "invalid_finalization"),
            ("changed", "source_artifact_sha256_mismatch"),
            ("destination", "demo_destination_exists"),
        )
        for case, error in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_root, client, mcp_result, authority, output = write_source_fixture(
                    Path(directory)
                )
                manifest = read_json(run_root / "manifest.json")
                if case == "child":
                    manifest["parent"] = {
                        "run_id": "parent-run",
                        "round": 1,
                        "image_sha256": "0" * 64,
                    }
                    write_json(run_root / "manifest.json", manifest)
                elif case == "missing":
                    manifest["final"] = None
                    write_json(run_root / "manifest.json", manifest)
                elif case == "changed":
                    (run_root / "final.png").write_bytes(b"changed")
                else:
                    output.mkdir(parents=True)

                with self.assertRaisesRegex(ValueError, error):
                    export_real_demo(
                        run_root,
                        output,
                        client,
                        mcp_result,
                        authority_path=authority,
                    )

    def test_export_rejects_ineligible_review_wrong_route_and_mismatched_mcp_result(self) -> None:
        from export_real_demo import export_real_demo

        cases = (
            ("review", "invalid_visual_candidate"),
            ("uncertain", "invalid_visual_candidate"),
            ("route", "invalid_public_route"),
            ("mcp", "invalid_mcp_result"),
        )
        for case, error in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_root, client, mcp_result, authority, output = write_source_fixture(
                    Path(directory)
                )
                manifest = read_json(run_root / "manifest.json")
                if case == "review":
                    manifest["reviews"][0]["hard_failures"] = ["explicit_constraint_violation"]
                    write_json(run_root / "manifest.json", manifest)
                elif case == "uncertain":
                    manifest["reviews"][0]["visual_checks"]["text_and_watermarks"][
                        "status"
                    ] = "uncertain"
                    write_json(run_root / "manifest.json", manifest)
                elif case == "route":
                    manifest["request"]["workflow_template_id"] = (
                        "sdxl-two-stage-copy-subject"
                    )
                    write_json(run_root / "manifest.json", manifest)
                else:
                    result = read_json(mcp_result)
                    result["run_id"] = "other-run"
                    write_json(mcp_result, result)

                with self.assertRaisesRegex(ValueError, error):
                    export_real_demo(
                        run_root,
                        output,
                        client,
                        mcp_result,
                        authority_path=authority,
                    )
                self.assertFalse(output.exists())

    def test_export_rejects_wrong_confirmation_client_purpose_and_public_rights(self) -> None:
        from export_real_demo import export_real_demo

        cases = (
            ("confirmation", "invalid_finalization"),
            ("client", "invalid_client_session"),
            ("rights", "invalid_public_authority"),
        )
        for case, error in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_root, client, mcp_result, authority, output = write_source_fixture(
                    Path(directory)
                )
                if case == "confirmation":
                    result = read_json(mcp_result)
                    result["confirmation"] = "finalize:wrong:1:" + "0" * 64
                    write_json(mcp_result, result)
                elif case == "client":
                    document = read_json(client)
                    document["session_purpose"] = "compatibility"
                    write_json(client, document)
                else:
                    document = read_json(authority)
                    document["models"][0]["output_redistribution_status"] = "unapproved"
                    write_json(authority, document)

                with self.assertRaisesRegex(ValueError, error):
                    export_real_demo(
                        run_root,
                        output,
                        client,
                        mcp_result,
                        authority_path=authority,
                    )

    def test_export_rejects_nested_route_and_generation_plan_drift(self) -> None:
        from export_real_demo import export_real_demo

        cases = (
            ("nested-route", "invalid_public_route"),
            ("bundle-workflow", "invalid_public_route"),
            ("plan-workflow", "invalid_generation_provenance"),
            ("plan-layout", "invalid_generation_provenance"),
            ("backend-mode", "invalid_generation_provenance"),
        )
        for case, error in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_root, client, mcp_result, authority, output = write_source_fixture(
                    Path(directory)
                )
                manifest = read_json(run_root / "manifest.json")
                if case == "nested-route":
                    manifest["request"]["route"]["workflow_template_id"] = (
                        "sdxl-two-stage-copy-subject"
                    )
                elif case == "bundle-workflow":
                    manifest["request"]["route"]["component_bundle"]["workflow"][
                        "template_id"
                    ] = "sdxl-two-stage-copy-subject"
                elif case == "plan-workflow":
                    manifest["rounds"][0]["generation_plan"]["workflow_template_id"] = (
                        "sdxl-two-stage-copy-subject"
                    )
                elif case == "plan-layout":
                    manifest["rounds"][0]["generation_plan"]["constraints"][
                        "two_stage_layout"
                    ] = {"unexpected": True}
                else:
                    manifest["rounds"][0]["backend_result"]["mode"] = "img2img"
                write_json(run_root / "manifest.json", manifest)

                with self.assertRaisesRegex(ValueError, error):
                    export_real_demo(
                        run_root,
                        output,
                        client,
                        mcp_result,
                        authority_path=authority,
                    )
                self.assertFalse(output.exists())

    def test_export_stages_then_removes_failed_self_validation(self) -> None:
        from export_real_demo import export_real_demo

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run_root, client, mcp_result, authority, output = write_source_fixture(base)
            with patch("export_real_demo.validate_real_demo", return_value=["forced"]):
                with self.assertRaisesRegex(ValueError, "invalid_exported_demo:forced"):
                    export_real_demo(
                        run_root,
                        output,
                        client,
                        mcp_result,
                        authority_path=authority,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(
                [path for path in output.parent.iterdir() if path.name.startswith(".real.staging-")],
                [],
            )


if __name__ == "__main__":
    unittest.main()
