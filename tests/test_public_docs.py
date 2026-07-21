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
    "local_gpu_start_run",
    "local_gpu_get_run",
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
    def test_readme_documents_v04_agent_workflow_and_release_boundary(self) -> None:
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
            "`stabilityai/sd-turbo`",
            "No production model is bundled or currently approved",
            "Mocked/model-free",
            "not retained real Codex, vision, model, GPU, or Real-ESRGAN evidence",
            "`LOCAL_GPU_IMAGEGEN_REALESRGAN_DIR`",
            "`realesrgan-x4plus-anime`",
            "`realesr-animevideov3-x4`",
            "No postprocessor runs automatically",
            "low-level `local_gpu_generate_image` compatibility tool is unchanged",
            "confirmation must exactly equal the `run_id`",
            "publishes that nominated reviewed round",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, readme)

    def test_supporting_docs_cover_v04_architecture_recovery_and_release(self) -> None:
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
        self.assertIn("Mocked/model-free", changelog)
        self.assertIn("## [0.4.0] - 2026-07-21", changelog)
        self.assertIn("## [0.3.0]", changelog)

    def test_active_versions_are_v04_and_historical_versions_are_preserved(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        active_documents = tuple(
            (str(path.relative_to(ROOT)), path.read_text(encoding="utf-8"))
            for path in ACTIVE_VERSION_FILES
        )

        self.assertEqual(plugin["version"], "0.4.0")
        self.assertIn('"version": "0.4.0"', readme)
        self.assertEqual(active_version_findings(active_documents), [])
        self.assertIn("## [0.4.0] - 2026-07-21", changelog)
        self.assertIn("## [0.3.0] - 2026-07-21", changelog)

    def test_public_docs_do_not_make_unsupported_release_claims(self) -> None:
        public_copy = "\n".join(
            path.read_text(encoding="utf-8")
            for path in PUBLIC_RELEASE_DOCS
        )

        self.assertEqual(unsupported_release_claims(public_copy), [])
        for unsupported_scope in (
            "includes a mask workflow",
            "includes a child revision workflow",
            "includes a hot revision workflow",
            "includes a ppt workflow",
            "includes a ui workflow",
            "v0.5 feature",
        ):
            with self.subTest(unsupported_scope=unsupported_scope):
                self.assertNotIn(unsupported_scope, public_copy.lower())

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
        )
        for false_claim in false_claims:
            with self.subTest(false_claim=false_claim):
                self.assertTrue(unsupported_release_claims(false_claim))

    def test_stale_active_version_mutations_are_rejected(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for stale_version in ("v0.3", "version 0.3", '"version": "0.3.0"'):
            with self.subTest(stale_version=stale_version):
                mutated = readme + "\nActive release: " + stale_version
                self.assertTrue(active_version_findings((("README.md", mutated),)))

    def test_skill_active_v03_mutation_is_rejected(self) -> None:
        skill_path = ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md"
        self.assertIn(skill_path, ACTIVE_VERSION_FILES)
        mutated = skill_path.read_text(encoding="utf-8") + "\nActive Skill release: v0.3"
        findings = active_version_findings((("skills/local-gpu-imagegen/SKILL.md", mutated),))
        self.assertEqual(len(findings), 1)
        self.assertIn("skills/local-gpu-imagegen/SKILL.md", findings[0])

    def test_claim_scanner_preserves_truthful_negative_boundaries(self) -> None:
        truthful_boundaries = (
            "No production model is bundled or approved.",
            "Codex is not a verified host.",
            "Real GPU generation remains unverified.",
            "The model is disabled and its license is not approved.",
        )
        for boundary in truthful_boundaries:
            with self.subTest(boundary=boundary):
                self.assertEqual(unsupported_release_claims(boundary), [])


if __name__ == "__main__":
    unittest.main()
