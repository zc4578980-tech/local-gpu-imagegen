from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


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
    ROOT / "scripts" / "mcp_server.py",
    ROOT / "scripts" / "local_gpu_imagegen" / "generation_plan.py",
)


def unsupported_release_claims(public_copy: str) -> list[str]:
    claim_patterns = (
        r"\bcodex\b[^\n.]{0,80}\b(?:verified|validated|supported)\s+host\b",
        r"\bverified\s+(?:on|with|by)\s+codex\b",
        r"\breal\s+(?:codex|vision|gpu|generation|image)[^\n.]{0,80}\b(?:accepted|approved|verified|validated)\b",
        r"\bretained\s+real\s+(?:codex|vision|model|gpu|image|real-esrgan)[^\n.]{0,80}\bevidence\s+exists\b",
        r"\bproduction[- ](?:ready|proven|verified)\b",
        r"\bproduction\s+model[^\n.]{0,80}\b(?:bundled|included|approved|enabled|ready)\b",
        r"\b(?:sd-turbo|model)[^\n.]{0,40}\blicense\s+(?:is\s+)?approved\b",
        r"\bapproved\s+license\s+(?:record|status|for)\b",
        r"\b(?:quality|performance|vram)\s+(?:is|was|are|has been)\s+(?:verified|proven|measured)\b",
        r"\b(?:production|professional|high)[- ]quality\b",
        r"\b(?:uses?|requires?|needs?)\s+\d+(?:\.\d+)?\s*(?:gb|gib)\s+(?:of\s+)?vram\b",
        r"\b\d+(?:\.\d+)?\s*(?:x|%|percent)\s+(?:faster|speedup)\b",
        r"\b(?:five|[1-5])[- ]star(?:s| rating)?\b",
        r"\b(?:supports|includes|ships|provides)\b[^\n.]{0,80}\b(?:masks?|child revisions?|ppt|ui|v0\.5)\b",
    )
    negations = re.compile(
        r"\b(?:no|not|never|without|unverified|unvalidated|absent|does not|do not|has not|have not|remains? unverified)\b"
    )
    findings = []
    for line in public_copy.lower().splitlines():
        for statement in re.split(
            r"(?<=[.!?;])\s+|,\s*(?=(?:but|yet|however|though)\b)|\s+(?=(?:but|yet|however|though)\b)",
            line,
        ):
            if negations.search(statement):
                continue
            if any(re.search(pattern, statement) for pattern in claim_patterns):
                findings.append(statement.strip())
    return findings


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
        active_copy = "\n".join(path.read_text(encoding="utf-8") for path in ACTIVE_VERSION_FILES)

        self.assertEqual(plugin["version"], "0.4.0")
        self.assertIn('"version": "0.4.0"', readme)
        self.assertNotRegex(active_copy, r"(?i)\b(?:v|version\s*)?0\.3(?:\.0)?\b")
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
        )
        for false_claim in false_claims:
            with self.subTest(false_claim=false_claim):
                self.assertTrue(unsupported_release_claims(false_claim))

    def test_stale_active_version_mutations_are_rejected(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for stale_version in ("v0.3", "version 0.3", '"version": "0.3.0"'):
            with self.subTest(stale_version=stale_version):
                mutated = readme + "\nActive release: " + stale_version
                self.assertRegex(mutated, r"(?i)\b(?:v|version\s*)?0\.3(?:\.0)?\b")


if __name__ == "__main__":
    unittest.main()
