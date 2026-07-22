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
    from .real_demo_helpers import (
        fake_showcase,
        read_json,
        write_json,
        write_source_fixture,
    )
else:
    from real_demo_helpers import fake_showcase, read_json, write_json, write_source_fixture


class ValidateRealDemoTests(unittest.TestCase):
    def _export(self, base: Path) -> Path:
        from export_real_demo import export_real_demo

        root_run, child_run, client, authority, output = write_source_fixture(base)
        export_real_demo(
            root_run,
            child_run,
            output,
            client,
            authority_path=authority,
            showcase_builder=fake_showcase,
        )
        return output

    def test_valid_real_demo_binds_route_lineage_and_every_artifact(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            self.assertEqual(validate_real_demo(output), [])

    def test_rejects_simulation_private_values_and_changed_image_bytes(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            manifest = read_json(output / "showcase-manifest.json")
            manifest["model_output"] = False
            manifest["route"]["backend_url"] = "http://127.0.0.1:8188"
            write_json(output / "showcase-manifest.json", manifest)
            (output / "after.png").write_bytes(b"changed")

            findings = validate_real_demo(output)

            self.assertIn("not_real_model_output", findings)
            self.assertIn("private_value", findings)
            self.assertIn("artifact_sha256_mismatch:after.png", findings)

    def test_rejects_extra_files_failed_review_and_client_digest_mismatch(self) -> None:
        from validate_real_demo import validate_real_demo

        with tempfile.TemporaryDirectory() as directory:
            output = self._export(Path(directory))
            (output / "unexpected.txt").write_text("extra", encoding="utf-8")
            manifest = read_json(output / "showcase-manifest.json")
            manifest["revision"]["visual_checks"]["text_and_watermarks"]["status"] = "uncertain"
            manifest["client_session"]["sha256"] = "0" * 64
            manifest["known_limitations"] = []
            write_json(output / "showcase-manifest.json", manifest)

            findings = validate_real_demo(output)

            self.assertIn("unexpected_demo_files", findings)
            self.assertIn("visual_checks_not_passed:revision", findings)
            self.assertIn("client_session_sha256_mismatch", findings)
            self.assertIn("missing_known_limitations", findings)

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

    def test_schema_is_closed_and_pins_real_output(self) -> None:
        schema = json.loads(
            (ROOT / "docs" / "evidence" / "schemas" / "real-demo.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["demo_kind"]["const"], "real_local_gpu_hot_revision")
        self.assertEqual(schema["properties"]["model_output"]["const"], True)
        for name in ("public_rights", "route", "root", "revision", "client_session"):
            self.assertFalse(schema["properties"][name]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
