from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

if __package__:
    from .public_contract_helpers import (
        active_version_findings,
        plugin_discovery_findings,
        user_facing_strings,
    )
else:
    from public_contract_helpers import (
        active_version_findings,
        plugin_discovery_findings,
        user_facing_strings,
    )


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
        "-> `local_gpu_discover_models`",
        "-> `local_gpu_list_profiles`",
        "-> `local_gpu_recommend_models`",
        "-> display the exact route and resolved complete summary with exact `model_choice`",
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


def _assert_visual_acceptance_contract(text: str) -> None:
    section = _section(text, "## Review Evidence", "## Hard Boundaries")
    _assert_ordered(section, (
        "display the original full-resolution image",
        "`local_gpu_record_review`",
        "`quality_status: candidate`",
        "finalize:<run_id>:<round_number>:<image_sha256>",
        "stop and wait for a later user message",
        "`local_gpu_finalize_run`",
    ))
    for required in (
        "`full_resolution_inspected: true`",
        "`prominent_human`",
        "`limb_separation`",
        "`feet_and_contact`",
        "`hands_and_held_objects`",
        "`text_and_watermarks`",
        "fail or uncertain",
        "A candidate is not accepted until the later user confirmation is verified",
    ):
        if required not in section:
            raise AssertionError(f"Missing visual acceptance boundary: {required}")


def _assert_plugin_discovery_contract(plugin: dict[str, object]) -> None:
    findings = plugin_discovery_findings(plugin)
    if findings:
        raise AssertionError("\n".join(findings))


def _replace_user_facing_path(value: object, target: str, replacement: str, path: str = "$") -> object:
    if isinstance(value, str):
        return replacement if path == target else value
    if isinstance(value, list):
        return [
            _replace_user_facing_path(item, target, replacement, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return {
            key: _replace_user_facing_path(item, target, replacement, f"{path}.{key}")
            for key, item in value.items()
        }
    return value


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.plugin = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))

    def test_guided_bootstrap_requires_a_later_confirmation_and_fresh_discovery(self) -> None:
        section = _section(self.text, "## Guided Bootstrap", "## Codex-First Workflow Runner")
        _assert_ordered(section, (
            "`local_gpu_imagegen_check`",
            "`local-gpu-imagegen bootstrap status`",
            "`local-gpu-imagegen bootstrap plan --client codex`",
            "Display the actions, estimated bytes, and licenses",
            "later user message",
            "`local-gpu-imagegen bootstrap apply --plan-id <plan_id> --confirmation <confirmation>`",
            "`local-gpu-imagegen setup codex --apply`",
            "verify readiness",
            "fresh MCP discovery",
        ))
        for prohibited in ("silent download", "silent license acceptance"):
            self.assertIn(prohibited, section)

    def test_codex_first_runner_has_three_first_use_decisions_and_exact_revalidation(self) -> None:
        section = _section(
            self.text,
            "## Codex-First Workflow Runner",
            "## Adaptive Brief",
        )
        _assert_ordered(section, (
            "`local_gpu_discover_models`",
            "`local_gpu_inspect_workflow`",
            "File verification decision",
            "`exact_file` / `verify`",
            "stop and wait for a later user message",
            "`inspect_workflow_binding`",
            "Preparation decision",
            "stop and wait for a later user message",
            "`local_gpu_register_workflow`",
            "`approve_private`",
            "`local_gpu_recommend_models`",
            "Execution decision",
            "stop and wait for a later user message",
            "`local_gpu_start_run`",
            "`local_gpu_get_run`",
            "`local_gpu_generate_round`",
            "generated / unreviewed",
        ))
        for required in (
            "three first-use decisions",
            "one exact local model path",
            "complete contents",
            "same SHA-256",
            "new workflow on the same verified model requires two decisions",
            "already trusted unchanged workflow requires only the execution decision",
            "Never reuse a route token, prompt ID, or run ID",
            "same `capabilities` object",
            "`guidance_scale` to `recommended.guidance`",
            "`sampler_name` to `recommended.sampler`",
            "`max_rounds: 1`",
            "`upscale_policy: off`",
            "inert registration",
            "no automatic retry",
            "no model switch",
            "no CPU fallback",
            "no workflow fallback",
            "no download",
        ):
            with self.subTest(required=required):
                self.assertIn(required, section)

    def test_codex_first_runner_preserves_defaults_except_explicit_overrides(self) -> None:
        section = _section(
            self.text,
            "## Codex-First Workflow Runner",
            "## Adaptive Brief",
        )
        for field in (
            "`positive_prompt`",
            "`negative_prompt`",
            "`width`",
            "`height`",
            "`seed`",
            "`steps`",
            "`guidance_scale`",
            "`sampler_name`",
            "`scheduler`",
        ):
            with self.subTest(field=field):
                self.assertIn(field, section)
        self.assertIn(
            "only fields explicitly overridden by the user may differ",
            section,
        )
        self.assertIn("changed or expired route", section)

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

    def test_ui_hero_requires_semantic_anchors_before_prompting_and_start(self) -> None:
        section = _section(self.text, "## Adaptive Brief", "## Workflow Onboarding")
        for required_text in (
            "`semantic_fidelity`",
            "requested medium",
            "required visual anchors",
            "forbidden substitutions",
            "paper-only workspace",
            "before writing the generation prompt",
            "Do not call `local_gpu_start_run`",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, section)

    def test_semantic_review_precedes_polish_and_requires_per_anchor_evidence(self) -> None:
        section = _section(self.text, "## Review Evidence", "## Hard Boundaries")
        _assert_ordered(section, (
            "requested medium",
            "required visual anchors",
            "forbidden substitutions",
            "Before scoring polish",
        ))
        for required_text in (
            "`anchor_results`",
            "`substitution_results`",
            "`semantic_substitution`",
            "cannot request finalization",
        ):
            self.assertIn(required_text, section)

    def test_requires_route_resolution_before_post_display_confirmation(self) -> None:
        ordered = (
            "`local_gpu_discover_models`",
            "`local_gpu_list_profiles`",
            "`local_gpu_recommend_models`",
            "display the exact route",
            "receive post-display confirmation",
            "`local_gpu_start_run`",
        )
        _assert_ordered(self.text, ordered)
        for boundary in (
            "no silent model switch",
            "private",
            "public_evidence",
            "backend_binding",
            "cryptographic",
            "at most two alternatives",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, self.text)

    def test_safe_workflow_onboarding_requires_later_digest_bound_confirmation(self) -> None:
        section = _section(self.text, "## Workflow Onboarding", "## Confirmation Gate")
        _assert_ordered(section, (
            "`local_gpu_inspect_workflow`",
            "display the source SHA-256",
            "workflow SHA-256",
            "inferred binding",
            "component identities",
            "register_workflow:<source_sha256>:<proposal_digest>",
            "stop and wait for a later user message",
            "`local_gpu_register_workflow`",
            "`local_gpu_set_model_trust`",
        ))
        for boundary in (
            "does not start ComfyUI",
            "does not run discovery implicitly",
            "diagnostic",
            "no confirmation",
            "registration does not grant trust or public authority",
            "UI format",
            "developer mode",
        ):
            self.assertIn(boundary, section)

    def test_fresh_process_route_recovery_uses_authorized_exact_file_revalidation(self) -> None:
        section = _section(self.text, "## Adaptive Brief", "## Confirmation Gate")
        _assert_ordered(section, (
            "fresh MCP process",
            "`api_only/index` for ComfyUI",
            "`exact_file/verify`",
            "one exact local model path",
            "full-file read cost",
            "same SHA-256",
            "filesystem identity token, full SHA-256, and byte size",
            "`local_gpu_recommend_models`",
            "exact `public_evidence` route",
        ))
        for boundary in (
            "Never downgrade this recovery to `backend_binding` or `private` identity",
            "new file-verification decision",
            "Do not recommend until both filesystem and API identities are present",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, section)

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

    def test_regional_route_requires_displayed_geometry_conditioning_and_later_confirmation(self) -> None:
        required = (
            "copy-subject-v1",
            "copy_region",
            "subject_region",
            "initial_regional_conditioning",
            "copy_prompt",
            "subject_prompt",
            "copy_strength",
            "subject_strength",
            "regional_layout_unavailable",
            "sdxl-regional-txt2img",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        section = _section(self.text, "## Regional Copy-Subject Route", "## Run Sequence")
        _assert_ordered(section, (
            "display normalized decimals and percentages",
            "before asking the user to confirm",
            "later explicit confirmation",
            "geometry remains frozen",
        ))

    def test_regional_skill_forbids_prompt_only_fallback_and_geometry_hot_mutation(self) -> None:
        self.assertIn("Never fall back to `sdxl-txt2img`", self.text)
        self.assertIn("new root or child revision", self.text)
        self.assertIn("change only regional prompts or strengths", self.text)
        self.assertIn("explicit_constraint_violation", self.text)

    def test_single_pass_route_is_only_negative_evidence_and_never_substitutes_for_two_stage(self) -> None:
        section = _section(
            self.text,
            "## Regional Copy-Subject Route",
            "## Two-Stage Copy-Subject Route",
        )
        _assert_ordered(section, (
            "`copy-subject-v1`",
            "retained negative evidence",
            "experimental compatibility",
            "does not establish a visual-quality improvement",
            "not a substitute or fallback for `sdxl-two-stage-copy-subject`",
            "`sdxl-two-stage-copy-subject` is the required exact route for the controlled two-stage workflow",
        ))

    def test_two_stage_route_teaches_exact_confirmation_generation_and_review_contract(self) -> None:
        section = _section(self.text, "## Two-Stage Copy-Subject Route", "## Run Sequence")
        _assert_ordered(section, (
            "base prompt excludes the subject",
            "1280 x 720",
            "45%",
            "56.25%",
            "40%",
            "base seed",
            "derived subject seed",
            "workflow SHA-256",
            "control SHA-256",
            "bundle SHA-256",
            "one round costs two stage units",
            "base artifact at full resolution",
            "final artifact at full resolution",
            "exactly one two-stage round",
        ))
        for boundary in (
            "`sdxl-two-stage-copy-subject`",
            "`copy-subject-two-stage-v1`",
            "partial output stops the run",
            "No fallback is allowed",
            "Only the final artifact can become a candidate",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, section)

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
            "local_gpu_branch_run",
            "local_gpu_prepare_mask",
            "local_gpu_confirm_mask",
            "local_gpu_generate_round",
            "local_gpu_record_review",
            "local_gpu_finalize_run",
            "local_gpu_cleanup_run",
        ):
            with self.subTest(tool=tool):
                self.assertIn(f"`{tool}`", self.text)

    def test_generation_round_reconstructs_the_complete_frozen_plan_from_the_persisted_run(self) -> None:
        section = _section(self.text, "## Run Sequence", "## Hot Revision")
        _assert_ordered(section, (
            "`local_gpu_start_run`",
            "`local_gpu_get_run`",
            "persisted `request` and `route`",
            "`local_gpu_generate_round`",
        ))
        required_plan_fields = (
            "profile", "style", "intent", "positive_prompt", "negative_prompt",
            "constraints", "parameters", "max_rounds", "upscale_policy",
            "authorization_scope", "route_token", "model_choice", "backend",
            "endpoint_identity", "model_identity_token", "identity_strength",
            "workflow_template_id", "workflow_template_version",
            "prompt_compiler_id", "prompt_compiler_version",
        )
        for field in required_plan_fields:
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", section)
        self.assertIn("copy the frozen boundary exactly", section)
        self.assertIn("Do not construct a prompt-only plan", section)

    def test_hot_revision_requires_auditable_preserve_change_contract(self) -> None:
        for required_text in (
            "preserve/change contract",
            "immutable child run",
            "what the user likes",
            "what must remain",
            "what must change",
            "hard or soft",
            "revision budget",
            "one to three successful rounds",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

        section = _section(self.text, "## Hot Revision", "## Review Evidence")
        _assert_ordered(section, (
            "present the concise preserve/change contract",
            "user confirms",
            "`local_gpu_branch_run`",
        ))

    def test_revision_uses_least_destructive_supported_mode(self) -> None:
        section = _section(self.text, "## Hot Revision", "## Review Evidence")
        self.assertIn("prompt refinement -> low-strength img2img -> confirmed inpaint", section)
        self.assertIn("best-effort", section)
        self.assertIn("least destructive", section)

    def test_agent_geometry_requires_explicit_overlay_confirmation(self) -> None:
        section = _section(self.text, "## Hot Revision", "## Review Evidence")
        for required_text in (
            "Prefer a user-provided mask",
            "show the mask overlay",
            "wait for explicit approval",
            "Do not call `local_gpu_confirm_mask`",
            "silence",
            "prior consent",
            "prepare a new unconfirmed mask",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, section)

    def test_revision_review_records_preservation_results_without_inventing_vision(self) -> None:
        for required_text in (
            "one observable `preservation_results` entry per preserved target",
            "changed hard target is a hard failure",
            "uncertain hard target cannot be auto-accepted",
            "Text-only hosts must not invent preservation results",
            "return the child output for user review",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.text)

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

    def test_visual_acceptance_requires_a_later_user_turn(self) -> None:
        _assert_visual_acceptance_contract(self.text)

    def test_visual_acceptance_rejects_same_turn_and_self_acceptance_mutations(self) -> None:
        valid = self.text
        mutations = (
            valid.replace(
                "stop and wait for a later user message",
                "continue in the same turn",
            ),
            valid.replace(
                "A candidate is not accepted until the later user confirmation is verified",
                "The Agent may mark the candidate accepted",
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[-160:]):
                self.assertNotEqual(valid, mutation)
                with self.assertRaises(AssertionError):
                    _assert_visual_acceptance_contract(mutation)

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

    def test_forbids_hidden_downloads_chain_of_thought_and_unsupported_revision_claims(self) -> None:
        for required_text in (
            "Do not enable downloads",
            "Do not store chain-of-thought",
            "No hidden downloads",
            "Do not promise pixel-perfect no-mask preservation",
            "Do not perform automatic segmentation",
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
        self.assertIn("complete real 9+3 host/vision acceptance matrix", discovery)
        self.assertIn(
            "real comfyui generation evidence remains local development validation",
            discovery,
        )
        self.assertIn("rather than public acceptance evidence", discovery)
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

    def test_plugin_discovery_rejects_low_level_edit_scope_in_any_user_facing_field(self) -> None:
        claims = (
            "Agent image-to-image workflow",
            "Run img2img through the Agent workflow.",
            "Inpainting",
            "Create and edit with masks.",
        )
        for path, _ in user_facing_strings(self.plugin):
            for claim in claims:
                plugin = _replace_user_facing_path(self.plugin, path, claim)
                assert isinstance(plugin, dict)
                findings = plugin_discovery_findings(plugin)
                expected = f"Low-level edit scope in discovery at {path}:"
                with self.subTest(path=path, claim=claim):
                    self.assertTrue(
                        any(finding.startswith(expected) for finding in findings),
                        findings,
                    )

    def test_skill_active_release_uses_shared_version_scanner(self) -> None:
        self.assertEqual(
            active_version_findings((("skills/local-gpu-imagegen/SKILL.md", self.text),)),
            [],
        )


if __name__ == "__main__":
    unittest.main()
