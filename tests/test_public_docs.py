from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

if __package__:
    from .public_contract_helpers import active_version_findings, unsupported_release_claims
else:
    from public_contract_helpers import active_version_findings, unsupported_release_claims


ROOT = Path(__file__).resolve().parents[1]
REAL_DEMO = ROOT / "docs" / "demo" / "real"
QUICKSTART = ROOT / "docs" / "quickstart.md"
ALTERNATIVES = ROOT / "docs" / "alternatives.md"
RELEASE_CHECKLIST = ROOT / "docs" / "release-checklist.md"
GITHUB_LISTING = ROOT / "docs" / "github-listing.md"
EVIDENCE_README = ROOT / "docs" / "evidence" / "README.md"
QUALITY_CONTROL = ROOT / "docs" / "image-quality-control.md"
HISTORICAL_STAR_GATE_DOCS = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-24-github-conversion-release-gate-design.md",
    ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-24-github-conversion-release-gate.md",
)
PUBLIC_TOOLS = {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
    "local_gpu_list_profiles",
    "local_gpu_discover_models",
    "local_gpu_inspect_workflow",
    "local_gpu_register_workflow",
    "local_gpu_set_model_trust",
    "local_gpu_recommend_models",
    "local_gpu_start_run",
    "local_gpu_get_run",
    "local_gpu_branch_run",
    "local_gpu_prepare_mask",
    "local_gpu_confirm_mask",
    "local_gpu_generate_round",
    "local_gpu_record_review",
    "local_gpu_finalize_run",
    "local_gpu_cleanup_run",
}
ACTIVE_PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "troubleshooting.md",
    ROOT / ".codex-plugin" / "plugin.json",
)
PUBLIC_RELEASE_DOCS = ACTIVE_PUBLIC_DOCS + (
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "github-listing.md",
    QUICKSTART,
    ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md",
)
ACTIVE_VERSION_FILES = ACTIVE_PUBLIC_DOCS + (
    ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md",
    ROOT / "scripts" / "mcp_server.py",
    ROOT / "scripts" / "local_gpu_imagegen" / "generation_plan.py",
)


def real_showcase() -> dict[str, object]:
    return json.loads(
        (REAL_DEMO / "showcase-manifest.json").read_text(encoding="utf-8")
    )


def _assert_ordered(text: str, values: tuple[str, ...]) -> None:
    positions = [text.index(value) for value in values]
    if positions != sorted(positions):
        raise AssertionError(f"Values are out of order: {values}")


class PublicDocumentationTests(unittest.TestCase):
    def test_codex_first_viewport_states_literal_offer_and_ready_request(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        first_viewport = readme[:3500]
        for required in (
            "Run a supported ComfyUI workflow from Codex without modifying your setup.",
            "uvx local-gpu-imagegen setup codex --apply",
            "Run this supported ComfyUI API workflow from Codex: <path>.",
            "Use this prompt: <prompt>. Preserve every other workflow setting.",
            "Python 3.11 or 3.12",
            "already-running local ComfyUI",
            "already-installed model",
            "ordinary `txt2img` API workflow",
        ):
            with self.subTest(required=required):
                self.assertIn(required, first_viewport)
        for forbidden in (
            "any workflow",
            "arbitrary workflow",
            "better image quality",
            "production ready",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, first_viewport.lower())

    def test_quickstart_uses_three_first_use_decisions_and_one_successful_round(self) -> None:
        quickstart = QUICKSTART.read_text(encoding="utf-8")
        _assert_ordered(quickstart, (
            "File verification decision",
            "local_gpu_inspect_workflow",
            "`exact_file` / `verify`",
            "Preparation decision",
            "local_gpu_register_workflow",
            "Execution decision",
            "local_gpu_recommend_models",
            "local_gpu_start_run",
            "local_gpu_generate_round",
            "generated / unreviewed",
        ))
        for required in (
            "three first-use decisions",
            "two decisions",
            "one execution decision",
            "exactly 17 tools",
            "one successful round",
            "no retry",
            "no model switch",
            "no download",
            "UI-format conversion",
            "custom nodes",
        ):
            self.assertIn(required, quickstart)

    def test_alternatives_are_dated_source_linked_and_non_hostile(self) -> None:
        alternatives = ALTERNATIVES.read_text(encoding="utf-8")
        for required in (
            "Checked 2026-07-27",
            "https://github.com/artokun/comfyui-mcp",
            "https://github.com/joenorton/comfyui-mcp-server",
            "https://github.com/filliptm/ComfyUI_FL-MCP",
        ):
            with self.subTest(required=required):
                self.assertIn(required, alternatives)
        lowered = alternatives.lower()
        for category in (
            "broad control plane",
            "lightweight relay",
            "bounded codex runner",
        ):
            self.assertIn(category, lowered)
        self.assertNotIn(" Stars", alternatives)
        self.assertNotIn("better than", alternatives.lower())

    def test_star_goal_is_post_release_measurement_not_publication_gate(
        self,
    ) -> None:
        checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")
        listing = GITHUB_LISTING.read_text(encoding="utf-8")
        evidence = EVIDENCE_README.read_text(encoding="utf-8")
        self.assertNotIn(
            "forecast is at least `100 GitHub Stars`",
            checklist,
        )
        self.assertNotIn("Publication remains blocked", listing)
        self.assertIn("Post-release adoption measurement", checklist)
        self.assertIn("100 net-new GitHub Stars", checklist)
        self.assertIn(
            "formal GitHub Release publication time",
            checklist,
        )
        self.assertIn("does not retract the Release", checklist)
        self.assertIn("post-release 30-day net-new Star goal", listing)
        self.assertIn("not a publication blocker", listing)
        for required in (
            "docs/evidence/adoption/<campaign_id>/campaign.json",
            "docs/evidence/adoption/<campaign_id>/events.jsonl",
            "record_star_observation.py",
            "validate_star_campaign.py",
            "repository-level Star totals only",
            "goal_met",
            "goal_missed",
            "measurement_incomplete",
        ):
            with self.subTest(required=required):
                self.assertIn(required, evidence)

    def test_historical_star_gate_documents_have_superseded_notice(self) -> None:
        for path in HISTORICAL_STAR_GATE_DOCS:
            with self.subTest(path=path):
                prefix = path.read_text(encoding="utf-8")[:1200]
                self.assertIn("**Status:** Superseded", prefix)
                self.assertIn(
                    "2026-07-25-post-release-star-measurement-design.md",
                    prefix,
                )
                self.assertIn("historical", prefix.lower())
                self.assertIn(
                    "not a pre-release publication gate",
                    prefix,
                )

    def test_readme_leads_with_literal_offer_and_installed_path(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        first_viewport = "\n".join(readme.splitlines()[:70])
        promise = "Run a supported ComfyUI workflow from Codex without modifying your setup."
        self.assertIn("# Local GPU Imagegen", first_viewport)
        self.assertIn(promise, first_viewport)
        self.assertIn("Bring Your Own ComfyUI Workflow", first_viewport)
        self.assertIn("uvx local-gpu-imagegen verify", first_viewport)
        self.assertIn("uvx local-gpu-imagegen setup codex --apply", first_viewport)
        self.assertLess(
            first_viewport.index(promise),
            first_viewport.index("Bring Your Own ComfyUI Workflow"),
        )

    def test_readme_first_viewport_uses_validated_evidence(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        first_viewport = "\n".join(readme.splitlines()[:55])
        showcase = real_showcase()
        image_sha256 = showcase["final"]["image_sha256"]

        required = (
            "docs/demo/real/final.png",
            image_sha256,
            "`sdxl-txt2img`",
            "uvx local-gpu-imagegen verify",
            "uvx local-gpu-imagegen setup codex --apply",
            "docs/quickstart.md",
            "existing local image backend",
            "no silent model downloads or switches",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, first_viewport)
        self.assertLess(
            readme.index("docs/demo/real/final.png"),
            readme.index("docs/demo/preview-loop.gif"),
        )

    def test_quickstart_is_bounded_reversible_and_private_value_free(self) -> None:
        quickstart = QUICKSTART.read_text(encoding="utf-8")
        required = (
            "Python 3.11 or 3.12",
            "backend and model are already running",
            "uvx local-gpu-imagegen verify",
            "uvx local-gpu-imagegen setup codex --apply",
            "uvx local-gpu-imagegen setup claude-code --apply",
            "uvx local-gpu-imagegen doctor",
            "Restart or reload",
            "codex mcp remove local-gpu-imagegen",
            "claude mcp remove --scope user local-gpu-imagegen",
            "local_gpu_discover_models",
            "local_gpu_set_model_trust",
            "local_gpu_recommend_models",
            "local_gpu_generate_round",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, quickstart)
        forbidden = ("D:\\", "C:\\Users\\", "route:", "model:")
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, quickstart)

    def test_launch_docs_lead_with_supported_workflow_onboarding(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quickstart = QUICKSTART.read_text(encoding="utf-8")
        for required in (
            "supported ordinary ComfyUI API workflow",
            "Save (API Format)",
            "local_gpu_inspect_workflow",
            "local_gpu_register_workflow",
            "registration does not grant model trust",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme + "\n" + quickstart)
        self.assertLess(
            quickstart.index("local_gpu_inspect_workflow"),
            quickstart.index("Profile-Driven Run"),
        )
        self.assertIn("did not submit a prompt", readme)
        self.assertIn("separate retained Codex generation", readme)

    def test_quality_control_rejects_semantic_substitution(self) -> None:
        quality = QUALITY_CONTROL.read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        quality_contract = " ".join(quality.replace("**", "").split())
        for required in (
            "semantic substitution",
            "product medium",
            "failed constraint",
            "MODEL_QUALITY_LIMIT",
            "FAIL_WORKFLOW_REGRESSION",
        ):
            with self.subTest(required=required):
                self.assertIn(required, quality_contract)
        for required in (
            "semantic substitution",
            "`constraint_results`",
            "`hard_failures`",
            "do not finalize",
        ):
            with self.subTest(skill_required=required):
                self.assertIn(required, skill)

    def test_github_listing_bounds_the_workflow_offer(self) -> None:
        listing = GITHUB_LISTING.read_text(encoding="utf-8")
        self.assertIn(
            "v0.8.0 Preview - Run supported ComfyUI workflows from your Agent",
            listing,
        )

    def test_release_mainline_keeps_composition_routes_experimental(self) -> None:
        public = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in ("README.md", "CHANGELOG.md", "docs/github-listing.md")
        ).lower()
        self.assertIn("ordinary `sdxl-txt2img`", public)
        self.assertIn("experimental", public)
        self.assertIn("not part of the golden path", public)
        self.assertIn("does not establish a visual-quality improvement", public)
        self.assertNotIn("regional control for local image generation", public)

    def test_readme_shipped_workflow_inventory_matches_packaged_assets(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        inventory = re.search(
            r"ComfyUI ships reviewed (?P<files>.+?) workflow files\.",
            readme,
        )

        self.assertIsNotNone(inventory)
        assert inventory is not None
        documented = set(re.findall(r"`([^`]+\.json)`", inventory["files"]))
        packaged = {
            path.name
            for path in (ROOT / "workflows" / "comfyui").glob("*.json")
            if path.is_file()
        }
        self.assertEqual(documented, packaged)

    def test_readme_documents_v05_agent_workflow_and_release_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        documented_tools = set(re.findall(r"`(local_gpu_[a-z_]+)`", readme))
        self.assertEqual(documented_tools, PUBLIC_TOOLS)
        for tool in PUBLIC_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(f"`{tool}`", readme)
        for required_text in (
            "Agent Skill Workflow",
            "Call `local_gpu_list_profiles`",
            "missing high-impact boundaries",
            "read the persisted frozen run -> construct the complete generation plan",
            "exact resolved `model_choice`",
            "`max_rounds` must be from `1` through `3`",
            "vision-capable host",
            "text-only host",
            "review unavailable",
            "refine preserves the seed",
            "explore changes the seed",
            "`outputs/runs/<run_id>/manifest.json`",
            "`round-01.png`",
            "`round-01-preview.jpg`",
            "`round-01.preview.jpg`",
            "`final.png`",
            "`final-upscaled.png`",
            "`idempotency_key`",
            "`recoverable_next_actions`",
            "`needs_user_review`",
            "`civitai/anything-v5@30163`",
            "No model weights are bundled",
            "Mocked/model-free",
            "Local Z-Image and Anima calls through the project adapter have been observed",
            "`LOCAL_GPU_IMAGEGEN_REALESRGAN_DIR`",
            "`realesrgan-x4plus-anime`",
            "`realesr-animevideov3-x4`",
            "No postprocessor runs automatically",
            "low-level `local_gpu_generate_image` compatibility tool is unchanged",
            "confirmation must exactly equal the `run_id`",
            "publishes that nominated reviewed round",
            "exactly seventeen tools",
            "`standalone-illustration`",
            "`presentation-visual`",
            "`ui-visual-asset`",
            "immutable child run",
            "preserve/change contract",
            "explicit mask-overlay confirmation",
            "`parent-source.png`",
            "`masks/mask-01.png`",
            "nine fixed briefs",
            "three child revisions",
            "fake-backend contract matrix",
            "does not prove visual quality",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, readme)

    def test_supporting_docs_cover_v05_architecture_recovery_and_release(self) -> None:
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn("`RunStore`", architecture)
        self.assertIn("`manifest.json` is the durable source of truth", architecture)
        self.assertIn("bounded JPEG preview", architecture)
        self.assertIn("full-resolution local PNG", architecture)
        self.assertIn("same `idempotency_key` and the same request", troubleshooting)
        self.assertIn("`unresolved`", troubleshooting)
        self.assertIn("`generate_round:recover`", troubleshooting)
        self.assertIn("does not submit a second `/prompt`", troubleshooting)
        self.assertIn("`recoverable_next_actions`", troubleshooting)
        self.assertIn("confirmation must exactly equal the `run_id`", troubleshooting)
        self.assertIn("`postprocess_failed`", troubleshooting)
        self.assertIn("`postprocess_cleanup_failed`", troubleshooting)
        self.assertIn("original `final.png`", troubleshooting)
        self.assertIn("residue", troubleshooting)
        self.assertIn("Do not recursively delete", troubleshooting)
        self.assertIn("does not download", architecture)
        self.assertIn("original `final.png`", architecture)
        self.assertIn("`final-upscaled.png`", architecture)
        self.assertIn("immutable child", architecture)
        self.assertIn("confirmed mask", architecture)
        self.assertIn("`mask_changed_since_prepare`", troubleshooting)
        self.assertIn("`mask_not_confirmed`", troubleshooting)
        self.assertIn("parent manifest", troubleshooting)
        self.assertIn("Mocked/model-free", changelog)
        self.assertIn("omits embedded data URIs and oversized metadata strings", changelog)
        self.assertIn("complete frozen generation plan", changelog)
        self.assertIn("fresh-process public-route recovery", changelog)
        self.assertIn("## [0.5.0] - 2026-07-21", changelog)
        self.assertIn("## [0.4.0] - 2026-07-21", changelog)
        self.assertIn("## [0.3.0]", changelog)

    def test_docs_distinguish_local_comfyui_validation_from_public_acceptance(self) -> None:
        public = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in ("README.md", "docs/architecture.md", "docs/troubleshooting.md")
        )
        self.assertIn("ComfyUI adapter: contract-tested", public)
        self.assertIn("local Z-Image and Anima adapter executions: observed", public)
        self.assertIn("public acceptance evidence: not retained", public)
        self.assertIn("`z-image-turbo-txt2img-v1`", public)
        self.assertIn("`anima-txt2img-v1`", public)
        self.assertIn("`UNETLoader`", public)
        self.assertNotIn("supports arbitrary models", public.lower())

    def test_plugin_manifest_describes_current_byom_boundary(self) -> None:
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        description = plugin["interface"]["longDescription"].lower()
        self.assertIn("bounded local model discovery", description)
        self.assertIn("no model weights are bundled or downloaded implicitly", description)
        self.assertNotIn("no production model is bundled or currently approved", description)

    def test_docs_cover_safe_byom_discovery_trust_and_routing(self) -> None:
        public = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "README.md",
                "docs/architecture.md",
                "docs/troubleshooting.md",
                "SECURITY.md",
            )
        )
        for required in (
            "api_only",
            "selected_folders",
            "common_locations",
            "full_drive",
            "index",
            "fingerprint",
            "LOCAL_GPU_IMAGEGEN_STATE_DIR",
            "backend_binding",
            "public_evidence",
            "no silent model switch",
            "sd15-txt2img-v1",
            "z-image-turbo-txt2img-v1",
            "anima-txt2img-v1",
            "model quality still comes from the user's model",
        ):
            with self.subTest(required=required):
                self.assertIn(required, public)

    def test_docs_define_exact_file_fresh_process_recovery_without_identity_downgrade(self) -> None:
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        for required in (
            "Fresh-process public route recovery",
            "FileVerificationRegistry",
            "`exact_file` / `verify`",
            "one exact local model path",
            "full-file read cost",
            "same SHA-256",
            "full SHA-256",
            "`api_only` ComfyUI `index`",
            "exact `public_evidence` route",
            "`active` / `drifted` / `revoked`",
            "exactly 17 tools",
            "does not improve image quality",
            "new file-verification decision",
            "Do not downgrade to `backend_binding` or `private`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, architecture + "\n" + troubleshooting)

    def test_docs_describe_candidate_and_user_bound_confirmation(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")

        for document in (readme, architecture):
            with self.subTest(document=document[:40]):
                self.assertIn("quality status `candidate`", document)
                self.assertIn("finalize:<run_id>:<round_number>:<image_sha256>", document)
                self.assertIn("later user message", document)
        self.assertIn("visual_checks_require_revision", troubleshooting)
        self.assertIn("finalization_confirmation_mismatch", troubleshooting)
        self.assertNotIn("An ineligible nomination receives `needs_user_review`", readme)

    def test_docs_define_two_stage_artifacts_gates_and_honest_single_pass_scope(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        public = "\n".join((readme, architecture, troubleshooting, changelog))

        for required in (
            "`sdxl-two-stage-copy-subject-v1.json`",
            "base artifact",
            "mask artifact",
            "final artifact",
            "protected-pixel",
            "full-resolution stage review",
            "two stage units",
            "partial",
            "no fallback",
            "exactly one two-stage round",
        ):
            with self.subTest(required=required):
                self.assertIn(required, public)
        self.assertIn("retained negative evidence", public)
        self.assertIn("experimental compatibility", public)
        self.assertIn("does not establish a visual-quality improvement", public)

    def test_active_versions_are_v080_and_historical_versions_are_preserved(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        active_documents = tuple(
            (str(path.relative_to(ROOT)), path.read_text(encoding="utf-8"))
            for path in ACTIVE_VERSION_FILES
        )

        self.assertEqual(plugin["version"], "0.8.0")
        self.assertIn('"version": "0.8.0"', readme)
        self.assertEqual(active_version_findings(active_documents), [])
        self.assertIn("## [0.8.0] - 2026-07-24", changelog)
        self.assertIn("## [0.7.0] - 2026-07-23", changelog)
        self.assertIn("## [0.6.1] - 2026-07-22", changelog)
        self.assertIn("## [0.6.0] - 2026-07-22", changelog)
        self.assertIn("## [0.5.0] - 2026-07-21", changelog)
        self.assertIn("## [0.4.0] - 2026-07-21", changelog)
        self.assertIn("## [0.3.0] - 2026-07-21", changelog)

    def test_public_docs_do_not_make_unsupported_release_claims(self) -> None:
        public_copy = "\n".join(
            path.read_text(encoding="utf-8")
            for path in PUBLIC_RELEASE_DOCS
        )

        self.assertEqual(unsupported_release_claims(public_copy), [])
        for excluded_scope in (
            "Complete PPT decks are excluded",
            "Frontend code and components are excluded",
            "Production icons, SVG, and transparent PNG are excluded",
            "Automatic segmentation is excluded",
            "Seamless-texture guarantees are excluded",
        ):
            with self.subTest(excluded_scope=excluded_scope):
                self.assertIn(excluded_scope, public_copy)

    def test_v080_docs_describe_safe_workflow_onboarding_truthfully(self) -> None:
        public = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "README.md",
                "docs/architecture.md",
                "docs/quickstart.md",
                "docs/troubleshooting.md",
                "docs/github-listing.md",
            )
        )
        for required in (
            "exactly seventeen tools",
            "ordinary `txt2img`",
            "single checkpoint",
            "split model",
            "`source_sha256`",
            "`workflow_sha256`",
            "`registered_workflow_id`",
            "registration does not grant model trust",
            "Zero-GPU real-client onboarding evidence is retained",
        ):
            self.assertIn(required, public)

    def test_active_release_guides_pin_v080_and_seventeen_tools(self) -> None:
        for path in (RELEASE_CHECKLIST, ROOT / "docs" / "client-compatibility.md"):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("`0.8.0`", text)
                self.assertIn("exactly seventeen tools", text)
                self.assertNotIn("exactly fifteen tools", text)

    def test_retained_client_evidence_keeps_historical_and_current_roles(self) -> None:
        root = ROOT / "docs" / "evidence" / "client-sessions"
        historical = json.loads(
            (root / "codex-v070.json").read_text(encoding="utf-8")
        )
        onboarding = json.loads(
            (root / "codex-v080-workflow-onboarding.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(historical["server"]["version"], "0.7.0")
        self.assertEqual(historical["session_purpose"], "golden_generation")
        self.assertEqual(onboarding["server"]["version"], "0.8.0")
        self.assertEqual(onboarding["session_purpose"], "workflow_onboarding")

    def test_preview_and_full_acceptance_gates_remain_distinct(self) -> None:
        for path in (RELEASE_CHECKLIST, EVIDENCE_README):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("v0.8 preview gate", text)
                self.assertIn("full-acceptance/v1.0 gate", text)
                self.assertIn(
                    "does not establish current-v0.8 GPU generation",
                    text,
                )

    def test_release_coherence_docs_share_v080_state(self) -> None:
        release_documents = (
            RELEASE_CHECKLIST,
            ROOT / "docs" / "client-compatibility.md",
            ROOT / "docs" / "directory-listings.md",
            EVIDENCE_README,
        )
        for path in release_documents:
            with self.subTest(path=path):
                self.assertIn("0.8.0", path.read_text(encoding="utf-8"))

        for path in (RELEASE_CHECKLIST, ROOT / "docs" / "client-compatibility.md"):
            with self.subTest(path=path):
                self.assertIn(
                    "exactly seventeen tools",
                    path.read_text(encoding="utf-8"),
                )

    def test_claim_scanner_rejects_equivalent_false_claims(self) -> None:
        false_claims = (
            "Codex is a verified host for this workflow.",
            "The workflow was verified on Codex.",
            "Real vision output has been accepted.",
            "Real GPU generation is validated.",
            "This plugin is production-ready.",
            "Image quality has been measured.",
            "VRAM is verified.",
            "This model needs 8 GB VRAM.",
            "Generation is 2x faster.",
            "It delivers production-quality output.",
            "This is a five-star plugin.",
            "Version 0.4 includes child revisions.",
            "The production model is approved.",
            "The sd-turbo license is approved.",
            "No production model is bundled, but Codex is a verified host.",
            "No production model is bundled, and Codex is a verified host.",
            "Real GPU generation is not unverified: it is validated.",
            "The model is not disabled and its license is approved.",
            "Real GPU generation is not verified, but it is validated.",
            "The production model is not approved, but it is ready.",
            "Codex and other clients are verified hosts.",
            "The production model is available.",
            "The production model is selectable.",
            "Real backend acceptance is verified.",
            "The production model is not unavailable.",
            "Real backend acceptance is not unverified.",
            "Real GPU generation is not verified but it is validated.",
            "Real GPU generation is not verified, although it is validated.",
            "Real GPU generation is not verified; however, it is validated.",
            "A license record is approved.",
            "A license record is available.",
            "A license record is present.",
            "The license is not unapproved.",
            "This release generates complete PPT decks.",
            "This release provides frontend code and components.",
            "This release supports SVG and transparent PNG.",
            "This release includes automatic segmentation.",
            "This launch is guaranteed to reach 100 Stars.",
            "The server supports 8 concurrent generations.",
            "Its image quality is better than every alternative.",
        )
        for false_claim in false_claims:
            with self.subTest(false_claim=false_claim):
                self.assertTrue(unsupported_release_claims(false_claim))

    def test_stale_active_version_mutations_are_rejected(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for stale_version in (
            "v0.3", "version 0.3", '"version": "0.3.0"',
            "v0.4", "version 0.4", '"version": "0.4.0"',
            "v0.6", "version 0.6", '"version": "0.6.0"',
            "v0.6.1", "version 0.6.1", '"version": "0.6.1"',
        ):
            with self.subTest(stale_version=stale_version):
                mutated = readme + "\nActive release: " + stale_version
                self.assertTrue(active_version_findings((("README.md", mutated),)))

    def test_skill_stale_version_mutation_is_rejected(self) -> None:
        skill_path = ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md"
        self.assertIn(skill_path, ACTIVE_VERSION_FILES)
        for stale_version in ("v0.3", "v0.4", "v0.6", "v0.6.1"):
            mutated = skill_path.read_text(encoding="utf-8") + f"\nActive Skill release: {stale_version}"
            findings = active_version_findings((("skills/local-gpu-imagegen/SKILL.md", mutated),))
            self.assertEqual(len(findings), 1)
            self.assertIn("skills/local-gpu-imagegen/SKILL.md", findings[0])

    def test_unretained_real_evidence_is_not_presented_as_complete(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        client_docs = (ROOT / "docs" / "client-compatibility.md").read_text(encoding="utf-8")
        demo_root = ROOT / "docs" / "demo" / "real"
        client_root = ROOT / "docs" / "evidence" / "client-sessions"

        real_demo_ready = all(
            (demo_root / name).is_file()
            for name in ("final.png", "mcp-result.json", "showcase-manifest.json")
        )
        named_clients_ready = all(
            (client_root / name).is_file()
            for name in ("codex-v070.json", "claude-code-v070.json")
        )
        if real_demo_ready:
            self.assertIn("docs/demo/real/final.png", readme)
            self.assertLess(
                readme.index("docs/demo/real/final.png"),
                readme.index("docs/demo/preview-loop.gif"),
            )
        else:
            self.assertIn("Genuine local-GPU result: release gate pending", readme)
        if named_clients_ready:
            self.assertIn("retained named-client sessions", client_docs)
        else:
            self.assertIn("Named-client session evidence remains pending", client_docs)

        simulated = readme.index("docs/demo/preview-loop.gif")
        boundary = readme.index("deterministic simulated protocol demonstration")
        self.assertLess(simulated, boundary)

    def test_claim_scanner_preserves_truthful_negative_boundaries(self) -> None:
        truthful_boundaries = (
            "No production model is bundled or approved.",
            "Codex is not a verified host.",
            "Real GPU generation remains unverified.",
            "The model is disabled and its license is not approved.",
            "The production model is absent.",
            "The production model is unavailable.",
            "The model license is unapproved.",
            "The model is disabled.",
            "Real backend execution remains unsupported.",
            "Real backend acceptance remains unverified.",
            "An approved license record is absent.",
            "An approved license record is unavailable.",
            "Real GPU generation is not verified but it is also not validated.",
            "Real GPU generation is unverified; however, it remains unvalidated.",
        )
        for boundary in truthful_boundaries:
            with self.subTest(boundary=boundary):
                self.assertEqual(unsupported_release_claims(boundary), [])


if __name__ == "__main__":
    unittest.main()
