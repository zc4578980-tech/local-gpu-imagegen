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
from local_gpu_imagegen.profile_registry import (  # noqa: E402
    MODEL_REQUIRED,
    PROFILE_REQUIRED,
    STYLE_REQUIRED,
    ProfileRegistry,
)


class ProfileRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ProfileRegistry(ROOT / "profiles")

    def test_lists_anime_style_and_disabled_candidate_model(self) -> None:
        catalog = self.registry.list_catalog()

        self.assertIn("anime", catalog["styles"])
        model = catalog["models"]["stabilityai/sd-turbo"]
        self.assertFalse(model["enabled"])
        self.assertFalse(model["known_local"])
        self.assertEqual(model["license_status"], "requires_user_review")
        self.assertIsNone(model["license_id"])
        self.assertIsNone(model["license_url"])

    def test_disabled_model_cannot_be_selected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "model_not_enabled"):
            self.registry.validate_model_choice("stabilityai/sd-turbo")

    def test_model_runtime_fields_match_published_schema(self) -> None:
        schema = json.loads((ROOT / "profiles" / "schemas" / "model.schema.json").read_text(encoding="utf-8"))

        self.assertEqual(MODEL_REQUIRED, {
            "schema_version", "id", "kind", "source", "license_id", "license_url",
            "license_status", "backends", "local_discovery_names", "strengths", "limitations",
            "use_cases", "styles", "recommended", "known_local", "enabled",
        })
        self.assertEqual(set(schema["required"]), MODEL_REQUIRED)

    def test_style_runtime_fields_match_published_schema(self) -> None:
        schema = json.loads((ROOT / "profiles" / "schemas" / "style.schema.json").read_text(encoding="utf-8"))

        self.assertEqual(set(schema["required"]), STYLE_REQUIRED)

    def test_lists_standalone_profile_and_anime_style(self) -> None:
        catalog = self.registry.list_catalog()
        self.assertIn("standalone-illustration", catalog["profiles"])
        self.assertIn("anime", catalog["styles"])

    def test_catalog_lists_all_v1_use_case_profiles(self) -> None:
        catalog = self.registry.list_catalog()

        self.assertEqual(
            set(catalog["profiles"]),
            {"standalone-illustration", "presentation-visual", "ui-visual-asset"},
        )

    def test_presentation_profile_marks_safe_area_as_critical(self) -> None:
        merged = self.registry.merge(
            "presentation-visual",
            "anime",
            {"text_safe_area": "right"},
        )

        self.assertTrue(merged["rubric"]["safe_area"]["critical"])
        self.assertEqual(merged["constraints"]["text_safe_area"], "right")

    def test_ui_profile_prohibits_baked_controls_and_text(self) -> None:
        merged = self.registry.merge("ui-visual-asset", None, {})

        self.assertIn("baked_controls", merged["hard_failures"])
        self.assertIn("incorrect_text", merged["hard_failures"])

    def test_each_profile_has_examples_for_every_subtype(self) -> None:
        for identifier, profile in self.registry.list_catalog()["profiles"].items():
            with self.subTest(profile=identifier):
                self.assertTrue(profile["aliases"])
                self.assertEqual(set(profile["examples"]), set(profile["subtypes"]))
                self.assertTrue(all(profile["examples"][name] for name in profile["subtypes"]))

    def test_runtime_rejects_invalid_profile_lists_and_rubric_items(self) -> None:
        cases = (
            ("subtypes", [], "subtypes"),
            ("hard_failures", ["missing_subject", 1], "hard_failures"),
            ("rubric.subject_completeness.weight", 0, "weight"),
            ("rubric.subject_completeness.critical", "yes", "critical"),
        )
        source_path = ROOT / "profiles" / "use-cases" / "standalone-illustration.json"
        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                profiles = Path(directory) / "profiles"
                shutil.copytree(ROOT / "profiles", profiles)
                path = profiles / "use-cases" / source_path.name
                document = json.loads(path.read_text(encoding="utf-8"))
                target = document
                parts = field.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                path.write_text(json.dumps(document), encoding="utf-8")

                with self.assertRaisesRegex(ValidationError, message):
                    ProfileRegistry(profiles).list_catalog()

    def test_anime_rubric_merges_before_use_case_rubric(self) -> None:
        merged = self.registry.merge("standalone-illustration", "anime", {})

        self.assertIn("line_coherence", merged["rubric"])
        self.assertIn("subject_completeness", merged["rubric"])
        self.assertEqual(merged["rubric"]["hand_quality"], merged["profile"]["rubric"]["hand_quality"])

    def test_catalog_exposes_copied_profile_style_and_model_metadata(self) -> None:
        catalog = self.registry.list_catalog()
        profile = catalog["profiles"]["standalone-illustration"]
        style = catalog["styles"]["anime"]
        model = catalog["models"]["stabilityai/sd-turbo"]

        self.assertEqual(profile["schema_version"], 1)
        self.assertIn("character", profile["examples"])
        self.assertIn("character", profile["subtypes"])
        self.assertIn("subject_completeness", profile["rubric"])
        self.assertIn("missing_subject", profile["hard_failures"])
        self.assertEqual(style["schema_version"], 1)
        self.assertIn("line_coherence", style["rubric"])
        self.assertIn("severe_face_error", style["hard_failures"])
        self.assertEqual(model["source"], "https://huggingface.co/stabilityai/sd-turbo")
        self.assertEqual(
            set(model["recommended"]),
            {"resolution", "steps", "guidance", "sampler", "scheduler"},
        )

        profile["examples"]["character"].append("mutated")
        style["rubric"]["line_coherence"]["weight"] = 99
        model["recommended"]["steps"] = 99
        fresh = self.registry.list_catalog()
        self.assertNotIn("mutated", fresh["profiles"]["standalone-illustration"]["examples"]["character"])
        self.assertEqual(fresh["styles"]["anime"]["rubric"]["line_coherence"]["weight"], 1)
        self.assertEqual(fresh["models"]["stabilityai/sd-turbo"]["recommended"]["steps"], 4)

    def test_approved_model_is_returned_as_a_deep_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profiles = Path(directory) / "profiles"
            shutil.copytree(ROOT / "profiles", profiles)
            path = profiles / "models" / "sd-turbo.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document.update({
                "id": "test/approved-anime",
                "source": "test-fixture",
                "license_id": "test-only",
                "license_status": "approved",
                "backends": ["webui"],
                "known_local": True,
                "enabled": True,
            })
            path.write_text(json.dumps(document), encoding="utf-8")
            registry = ProfileRegistry(profiles)

            selected = registry.validate_model_choice("test/approved-anime")
            selected["recommended"]["steps"] = 99

            fresh = registry.validate_model_choice("test/approved-anime")
            self.assertEqual(fresh["recommended"]["steps"], 4)

    def test_enabled_model_with_unapproved_license_cannot_be_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profiles = Path(directory) / "profiles"
            shutil.copytree(ROOT / "profiles", profiles)
            path = profiles / "models" / "sd-turbo.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document.update({"enabled": True, "known_local": True})
            path.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "model_license_unapproved"):
                ProfileRegistry(profiles).validate_model_choice("stabilityai/sd-turbo")

    def test_unknown_model_cannot_be_selected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown_model"):
            self.registry.validate_model_choice("missing/model")

    def test_runtime_rejects_invalid_model_approval_fields(self) -> None:
        for field, value in (
            ("enabled", "yes"),
            ("known_local", 1),
            ("license_status", "trusted"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                profiles = Path(directory) / "profiles"
                shutil.copytree(ROOT / "profiles", profiles)
                path = profiles / "models" / "sd-turbo.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                document[field] = value
                path.write_text(json.dumps(document), encoding="utf-8")

                with self.assertRaisesRegex(ValidationError, "invalid_profile_document"):
                    ProfileRegistry(profiles)

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
