from __future__ import annotations

import json
import sys
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

    def test_rejects_unknown_profile(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown_profile"):
            self.registry.merge("missing", None, {})

    def test_runtime_required_fields_match_published_schema(self) -> None:
        schema = json.loads((ROOT / "profiles" / "schemas" / "profile.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), PROFILE_REQUIRED)


if __name__ == "__main__":
    unittest.main()
