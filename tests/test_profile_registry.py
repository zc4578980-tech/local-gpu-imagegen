from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.profile_registry import PROFILE_REQUIRED, ProfileRegistry  # noqa: E402


class ProfileRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ProfileRegistry(ROOT / "profiles")

    def test_lists_standalone_profile_without_styles(self) -> None:
        catalog = self.registry.list_catalog()
        self.assertIn("standalone-illustration", catalog["profiles"])
        self.assertEqual(catalog["styles"], {})

    def test_user_constraints_override_profile_defaults(self) -> None:
        merged = self.registry.merge(
            "standalone-illustration",
            None,
            {"aspect_ratio": "16:9", "max_rounds": 2},
        )
        self.assertEqual(merged["constraints"]["aspect_ratio"], "16:9")
        self.assertEqual(merged["constraints"]["max_rounds"], 2)

    def test_bundled_profile_declares_all_designated_critical_dimensions(self) -> None:
        merged = self.registry.merge("standalone-illustration", None, {})
        critical = {
            name
            for name, specification in merged["rubric"].items()
            if specification.get("critical") is True
        }

        self.assertEqual(
            critical,
            {
                "intent_adherence",
                "composition",
                "artifact_control",
                "subject_completeness",
                "face_quality",
                "hand_quality",
                "style_consistency",
                "detail_quality",
            },
        )

    def test_released_profile_validation_rejects_missing_critical_markers(self) -> None:
        cases = (
            ("base.json", "intent_adherence"),
            ("use-cases/standalone-illustration.json", "subject_completeness"),
        )
        for relative_path, dimension in cases:
            with self.subTest(dimension=dimension), tempfile.TemporaryDirectory() as directory:
                profiles = Path(directory) / "profiles"
                shutil.copytree(ROOT / "profiles", profiles)
                path = profiles / relative_path
                document = json.loads(path.read_text(encoding="utf-8"))
                document["rubric"][dimension].pop("critical", None)
                path.write_text(json.dumps(document), encoding="utf-8")

                with self.assertRaisesRegex(ValidationError, "missing_critical_rubric_dimension"):
                    ProfileRegistry(profiles).list_catalog()

    def test_rejects_unknown_profile(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown_profile"):
            self.registry.merge("missing", None, {})

    def test_runtime_required_fields_match_published_schema(self) -> None:
        schema = json.loads((ROOT / "profiles" / "schemas" / "profile.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), PROFILE_REQUIRED)

    def test_published_schema_matches_runtime_identity_contract(self) -> None:
        schema = json.loads((ROOT / "profiles" / "schemas" / "profile.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["id"], {"type": "string", "minLength": 1})
        self.assertEqual(schema["properties"]["kind"], {"type": "string", "const": "use_case"})
        self.assertEqual(schema["properties"]["schema_version"], {"type": "integer", "const": 1})

    def test_runtime_rejects_invalid_identity_fields(self) -> None:
        source = json.loads((ROOT / "profiles" / "use-cases" / "standalone-illustration.json").read_text(encoding="utf-8"))
        for field, value, error_code in (
            ("id", "", "invalid_profile_document"),
            ("kind", "style", "invalid_profile_kind"),
            ("schema_version", True, "unsupported_profile_schema"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                profiles = Path(directory)
                (profiles / "use-cases").mkdir()
                shutil.copyfile(ROOT / "profiles" / "base.json", profiles / "base.json")
                document = {**source, field: value}
                (profiles / "use-cases" / "candidate.json").write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValidationError, error_code):
                    ProfileRegistry(profiles).list_catalog()


if __name__ == "__main__":
    unittest.main()
