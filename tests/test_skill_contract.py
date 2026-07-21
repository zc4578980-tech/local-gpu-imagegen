from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md"
PLUGIN_PATH = ROOT / ".codex-plugin" / "plugin.json"


def _section(text: str, start: str, end: str) -> str:
    try:
        start_index = text.index(start)
        end_index = text.index(end, start_index + len(start))
    except ValueError as error:
        raise AssertionError(f"Missing contract section boundary: {start} -> {end}") from error
    return text[start_index:end_index]


def _assert_ordered(text: str, parts: tuple[str, ...]) -> None:
    position = -1
    for part in parts:
        next_position = text.find(part, position + 1)
        if next_position == -1:
            raise AssertionError(f"Missing ordered contract part: {part}")
        position = next_position


def _assert_confirmation_contract(text: str) -> None:
    section = _section(text, "## Confirmation Gate", "## Run Sequence")
    match = re.search(r"Required temporal order:\s*```text\n(?P<flow>.*?)\n```", section, re.DOTALL)
    if match is None:
        raise AssertionError("Missing fenced confirmation state machine")
    expected_flow = (
        "early `use defaults and start` -> intent only",
        "-> `local_gpu_list_profiles`",
        "-> display resolved complete summary with exact `model_choice`",
        "-> receive post-display confirmation",
        "-> `local_gpu_start_run`",
    )
    actual_flow = tuple(line.strip() for line in match.group("flow").splitlines())
    if actual_flow != expected_flow:
        raise AssertionError(f"Confirmation state machine differs: {actual_flow}")
    for required in (
        "never authorizes an unseen model",
        "require a new explicit confirmation after displaying",
        "Do not call `local_gpu_start_run` before that post-display confirmation",
    ):
        if required not in section:
            raise AssertionError(f"Missing confirmation boundary: {required}")
    if "start without re-asking" in section.lower():
        raise AssertionError("Pre-resolution intent still bypasses post-display confirmation")


def _text_only_paragraph(text: str) -> str:
    start = text.index("On a text-only host")
    end = text.index("\n\n", start)
    return text[start:end]


def _assert_text_only_contract(text: str) -> None:
    paragraph = _text_only_paragraph(text)
    _assert_ordered(paragraph, (
        "generate exactly one successful round",
        "mark `review unavailable`",
        "Do not call `local_gpu_record_review` or `local_gpu_finalize_run`",
    ))
    if re.search(r"\b(?:may|can|then) call `local_gpu_(?:record_review|finalize_run)`", paragraph, re.IGNORECASE):
        raise AssertionError("Text-only branch permits a review/finalize call")


def _user_facing_strings(value: object, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        result: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            result.extend(_user_facing_strings(item, f"{path}[{index}]"))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            result.extend(_user_facing_strings(item, f"{path}.{key}"))
        return result
    return []


FORBIDDEN_DISCOVERY_CLAIMS = (
    re.compile(r"\bapproved\s+(?:catalog\s+)?model\s+(?:selection|available|included|bundled|ready)\b", re.IGNORECASE),
    re.compile(r"\bbundled\s+(?:approved\s+)?production\s+model\b", re.IGNORECASE),
    re.compile(r"\bapproved\s+production\s+model\b", re.IGNORECASE),
    re.compile(r"\b(?:bundles?|includes?|ships with|comes with)\b.{0,30}\b(?:approved|production|ready|enabled)\s+model\b", re.IGNORECASE),
    re.compile(r"\bproduction\s+model\b.{0,20}\b(?:approved|available|included|bundled|ready)\b", re.IGNORECASE),
    re.compile(r"\b(?:codex|host)\b.{0,30}\bverified\b", re.IGNORECASE),
    re.compile(r"\bverified\b.{0,30}\b(?:codex|host)\b", re.IGNORECASE),
    re.compile(r"\breal\s+(?:image|output)\b.{0,30}\b(?:acceptance|accepted)\b.{0,15}\bverified\b", re.IGNORECASE),
)


def _assert_plugin_discovery_contract(plugin: dict[str, object]) -> None:
    strings = _user_facing_strings(plugin)
    combined = "\n".join(value for _, value in strings).lower()
    for required in (
        "catalog-gated model resolution",
        "no production model is bundled or currently approved",
        "real host/gpu output acceptance remains unverified",
    ):
        if required not in combined:
            raise AssertionError(f"Missing discovery boundary: {required}")
    for path, value in strings:
        value_without_required_boundary = re.sub(
            r"\bno production model is bundled or currently approved\b",
            "",
            value,
            flags=re.IGNORECASE,
        )
        for pattern in FORBIDDEN_DISCOVERY_CLAIMS:
            if pattern.search(value_without_required_boundary):
                raise AssertionError(f"Forbidden discovery claim at {path}: {value}")


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

    def test_confirmation_gate_enforces_post_display_temporal_order(self) -> None:
        _assert_confirmation_contract(self.text)

    def test_confirmation_gate_rejects_permissive_or_reordered_mutations(self) -> None:
        valid = self.text
        mutations = (
            valid.replace("early `use defaults and start` -> intent only", "early `use defaults and start` -> confirmed"),
            valid.replace(
                "receive post-display confirmation\n-> `local_gpu_start_run`",
                "`local_gpu_start_run`\n-> receive post-display confirmation",
            ),
            valid.replace(
                "Do not call `local_gpu_start_run` before that post-display confirmation",
                "Start without re-asking after displaying the summary",
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[:80]):
                self.assertNotEqual(valid, mutation)
                with self.assertRaises(AssertionError):
                    _assert_confirmation_contract(mutation)

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

        _assert_text_only_contract(self.text)

        for required_text in (
            "generate exactly one successful round per confirmed run",
            "stop after the first retained round",
            "remaining round budget stays unused",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

    def test_text_only_branch_rejects_missing_or_contradictory_prohibitions(self) -> None:
        prohibition = "Do not call `local_gpu_record_review` or `local_gpu_finalize_run`"
        mutations = (
            self.text.replace(prohibition, "Call `local_gpu_record_review` and `local_gpu_finalize_run`"),
            self.text.replace(prohibition, f"{prohibition}. You may call `local_gpu_finalize_run`"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[-120:]):
                self.assertNotEqual(self.text, mutation)
                with self.assertRaises(AssertionError):
                    _assert_text_only_contract(mutation)

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
        _assert_plugin_discovery_contract(self.plugin)

    def test_plugin_discovery_rejects_equivalent_claims_in_any_string_field(self) -> None:
        mutations = (
            ("defaultPrompt", "Use the bundled approved production model."),
            ("capabilities", "Codex verified host"),
            ("shortDescription", "Real image acceptance is verified."),
        )
        for field, claim in mutations:
            plugin = copy.deepcopy(self.plugin)
            interface = plugin["interface"]
            assert isinstance(interface, dict)
            if field in {"defaultPrompt", "capabilities"}:
                values = interface[field]
                assert isinstance(values, list)
                values.append(claim)
            else:
                interface[field] = claim
            with self.subTest(field=field), self.assertRaises(AssertionError):
                _assert_plugin_discovery_contract(plugin)


if __name__ == "__main__":
    unittest.main()
