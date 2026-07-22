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
PUBLIC_TOOLS = {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
    "local_gpu_list_profiles",
    "local_gpu_discover_models",
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
    ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md",
)
ACTIVE_VERSION_FILES = ACTIVE_PUBLIC_DOCS + (
    ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md",
    ROOT / "scripts" / "mcp_server.py",
    ROOT / "scripts" / "local_gpu_imagegen" / "generation_plan.py",
)

class PublicDocumentationTests(unittest.TestCase):
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
            "exactly fifteen tools",
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

    def test_active_versions_are_v061_and_historical_versions_are_preserved(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        active_documents = tuple(
            (str(path.relative_to(ROOT)), path.read_text(encoding="utf-8"))
            for path in ACTIVE_VERSION_FILES
        )

        self.assertEqual(plugin["version"], "0.6.1")
        self.assertIn('"version": "0.6.1"', readme)
        self.assertEqual(active_version_findings(active_documents), [])
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
        ):
            with self.subTest(stale_version=stale_version):
                mutated = readme + "\nActive release: " + stale_version
                self.assertTrue(active_version_findings((("README.md", mutated),)))

    def test_skill_stale_version_mutation_is_rejected(self) -> None:
        skill_path = ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md"
        self.assertIn(skill_path, ACTIVE_VERSION_FILES)
        for stale_version in ("v0.3", "v0.4", "v0.6"):
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
            for name in ("before.png", "after.png", "showcase-manifest.json")
        )
        named_clients_ready = all(
            (client_root / name).is_file()
            for name in ("codex-v061.json", "claude-code-v061.json")
        )
        if real_demo_ready:
            self.assertIn("docs/demo/real/before.png", readme)
            self.assertIn("docs/demo/real/after.png", readme)
            self.assertLess(
                readme.index("docs/demo/real/after.png"),
                readme.index("docs/demo/preview-loop.gif"),
            )
        else:
            self.assertIn("Genuine local-GPU showcase: pending retained evidence", readme)
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
