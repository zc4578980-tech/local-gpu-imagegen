from __future__ import annotations

import json
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


EXPECTED_FILES = {
    "before.png",
    "after.png",
    "before-preview.jpg",
    "after-preview.jpg",
    "root-manifest.json",
    "revision-manifest.json",
    "transcript.md",
    "showcase.gif",
    "showcase-manifest.json",
    "README.md",
}


class ExportRealDemoTests(unittest.TestCase):
    def test_export_copies_only_nominated_bytes_and_sanitizes_manifests(self) -> None:
        from export_real_demo import export_real_demo

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root_run, child_run, client, authority, output = write_source_fixture(base)
            manifest = export_real_demo(
                root_run,
                child_run,
                output,
                client,
                authority_path=authority,
                showcase_builder=fake_showcase,
            )

            self.assertEqual(
                (output / "before.png").read_bytes(),
                (root_run / "round-01.png").read_bytes(),
            )
            self.assertEqual(
                (output / "after.png").read_bytes(),
                (child_run / "final.png").read_bytes(),
            )
            self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)
            public_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.iterdir()
                if path.suffix in {".json", ".md"}
            )
            self.assertNotIn(str(base), public_text)
            self.assertNotIn("private natural-language brief", public_text)
            self.assertNotIn("endpoint:private-test", public_text)
            self.assertNotIn("private-job-id", public_text)
            self.assertEqual(manifest["root"]["run_id"], "root-run")
            self.assertEqual(manifest["revision"]["parent"]["run_id"], "root-run")
            self.assertFalse((output / "unrelated.tmp").exists())

    def test_export_rejects_changed_parent_hash_without_creating_destination(self) -> None:
        from export_real_demo import export_real_demo

        with tempfile.TemporaryDirectory() as directory:
            root_run, child_run, client, authority, output = write_source_fixture(Path(directory))
            child_manifest = read_json(child_run / "manifest.json")
            child_manifest["parent"]["image_sha256"] = "0" * 64
            write_json(child_run / "manifest.json", child_manifest)

            with self.assertRaisesRegex(ValueError, "invalid_revision_lineage"):
                export_real_demo(
                    root_run,
                    child_run,
                    output,
                    client,
                    authority_path=authority,
                    showcase_builder=fake_showcase,
                )

            self.assertFalse(output.exists())

    def test_export_rejects_unapproved_authority_and_failed_preservation(self) -> None:
        from export_real_demo import export_real_demo

        with tempfile.TemporaryDirectory() as directory:
            root_run, child_run, client, authority, output = write_source_fixture(Path(directory))
            authority_document = read_json(authority)
            authority_document["models"][0]["output_redistribution_status"] = "unapproved"
            write_json(authority, authority_document)
            child_manifest = read_json(child_run / "manifest.json")
            child_manifest["reviews"][0]["preservation_results"][0]["status"] = "changed"
            write_json(child_run / "manifest.json", child_manifest)

            with self.assertRaisesRegex(ValueError, "invalid_public_authority"):
                export_real_demo(
                    root_run,
                    child_run,
                    output,
                    client,
                    authority_path=authority,
                    showcase_builder=fake_showcase,
                )


if __name__ == "__main__":
    unittest.main()
