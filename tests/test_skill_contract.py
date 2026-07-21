from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md"
PLUGIN_PATH = ROOT / ".codex-plugin" / "plugin.json"


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.plugin = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))

    def test_extracts_known_values_and_only_asks_for_missing_high_impact_boundaries(self) -> None:
        for required_text in (
            "Extract known values first",
            "Ask only for missing high-impact boundaries",
            "intended use/subtype",
            "subject/outcome",
            "style/composition",
            "dimensions/aspect ratio/safe area",
            "required/prohibited content",
            "round budget",
            "seed/model switching",
            "compatible upscaling",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_requires_complete_brief_confirmation_before_start(self) -> None:
        for required_text in (
            "Do not call `local_gpu_start_run` before",
            "use defaults and start",
            "Do not start after one conversational turn",
            "Profile/style/model choice",
            "dimensions/safe area",
            "preserve/prohibit constraints",
            "1 to 3 successful rounds",
            "backend/download/upscale policy",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_confirmation_resolves_the_exact_model_and_round_cap(self) -> None:
        for required_text in (
            "Do not ask the user to repeat or reconfirm known values",
            "A stated cap selects that maximum",
            "Confirmation must cover the resolved complete summary",
            "exact `model_choice`",
            "does not pre-authorize any concrete model ID",
            "A safe default must be advertised by the selected catalog Profile or model",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_requires_an_enabled_approved_non_empty_catalog_model(self) -> None:
        for required_text in (
            "approved non-empty `model_choice`",
            "registered, enabled, and license-approved",
            "unavailable-model boundary",
            "Do not invent a model ID",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_documents_the_exact_high_level_run_sequence(self) -> None:
        ordered_steps = (
            "`local_gpu_list_profiles`",
            "brief",
            "confirm",
            "`local_gpu_start_run`",
            "`local_gpu_generate_round(action=initial)`",
            "inspect preview",
            "`local_gpu_record_review`",
            "`local_gpu_generate_round(action=refine|explore)`",
            "inspect preview",
            "`local_gpu_record_review`",
            "`local_gpu_finalize_run`",
        )
        position = -1
        for step in ordered_steps:
            with self.subTest(step=step):
                position = self.text.find(step, position + 1)
                self.assertNotEqual(position, -1)

        for tool in (
            "local_gpu_imagegen_check",
            "local_gpu_generate_image",
            "local_gpu_list_profiles",
            "local_gpu_start_run",
            "local_gpu_get_run",
            "local_gpu_generate_round",
            "local_gpu_record_review",
            "local_gpu_finalize_run",
            "local_gpu_cleanup_run",
        ):
            with self.subTest(tool=tool):
                self.assertIn(f"`{tool}`", self.text)

    def test_round_loop_preserves_budget_seed_and_intent(self) -> None:
        for required_text in (
            "Never exceed the confirmed successful-round budget",
            "Refine: preserve the seed",
            "Explore: change the seed",
            "Preserve:",
            "Change:",
            "Stop early",
            "A retained image consumes one successful round regardless of visual quality",
            "Do not relabel it as a failed attempt",
            "every critical rubric score is at least 3",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_distinguishes_vision_and_text_only_hosts(self) -> None:
        for required_text in (
            "vision-capable",
            "text-only",
            "review unavailable",
            "Do not fabricate scores",
            "Do not claim the result is accepted",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

        for required_text in (
            "generate exactly one successful round per confirmed run",
            "stop after the first retained round",
            "remaining round budget stays unused",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_forbids_hidden_downloads_chain_of_thought_and_future_revision_claims(self) -> None:
        for required_text in (
            "Do not enable downloads",
            "Do not store chain-of-thought",
            "No hidden downloads",
            "Do not promise masks, child revisions, or hot revision tools",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_plugin_discovery_describes_only_model_free_visual_asset_behavior(self) -> None:
        interface = self.plugin["interface"]
        discovery = " ".join(
            (
                self.plugin["description"],
                interface["displayName"],
                interface["shortDescription"],
                interface["longDescription"],
            )
        ).lower()

        self.assertIn("visual asset", discovery)
        self.assertIn("adaptive briefing", discovery)
        self.assertIn("model-free", discovery)
        self.assertIn("real host/gpu output acceptance remains unverified", discovery)
        self.assertNotIn("codex is verified", discovery)
        self.assertNotIn("real image acceptance is verified", discovery)
        self.assertNotIn("v0.5", discovery)


if __name__ == "__main__":
    unittest.main()
