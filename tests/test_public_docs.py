from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_TOOLS = {
    "local_gpu_list_profiles",
    "local_gpu_start_run",
    "local_gpu_get_run",
    "local_gpu_generate_round",
    "local_gpu_record_review",
    "local_gpu_finalize_run",
    "local_gpu_cleanup_run",
}


class PublicDocumentationTests(unittest.TestCase):
    def test_readme_documents_v03_run_contract_and_evidence_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for tool in RUN_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(f"`{tool}`", readme)
        for required_text in (
            "`max_rounds` must be from `1` through `3`",
            "`outputs/runs/<run_id>/manifest.json`",
            "`round-01.png`",
            "`round-01.preview.jpg`",
            "`final.png`",
            "`idempotency_key`",
            "`recoverable_next_actions`",
            "`needs_user_review`",
            "`model_choice` is currently stored as `null`",
            "`upscale_policy` accepts only `auto` or `off`",
            "confirmation must exactly equal the `run_id`",
            "No retained real Codex-client/GPU generation evidence exists for v0.3",
            "Current AUTOMATIC1111/Forge and Diffusers backend readiness has not been verified for v0.3",
            "publishes that nominated reviewed round",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, readme)

    def test_supporting_docs_cover_persistence_recovery_and_release(self) -> None:
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
        self.assertIn("## [0.3.0]", changelog)

    def test_v03_docs_do_not_claim_later_milestones(self) -> None:
        public_copy = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "README.md",
                ROOT / "docs" / "architecture.md",
                ROOT / "docs" / "troubleshooting.md",
                ROOT / ".codex-plugin" / "plugin.json",
            )
        ).lower()

        for unsupported_claim in (
            "includes an adaptive codex skill",
            "includes an adaptive model registry",
            "includes an anime workflow",
            "includes a ppt workflow",
            "includes a revision workflow",
            "includes real-esrgan integration",
        ):
            with self.subTest(unsupported_claim=unsupported_claim):
                self.assertNotIn(unsupported_claim, public_copy)


if __name__ == "__main__":
    unittest.main()
