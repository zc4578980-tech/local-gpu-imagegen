# Changelog

All notable changes will be documented in this file.

## [Unreleased]

## [0.4.0] - 2026-07-21

### Added

- An adaptive Agent Skill workflow that lists Profile/style/model capabilities, asks only for missing high-impact boundaries, confirms the exact approved model, and manages one to three successful generate/review rounds.
- A versioned anime style and model registry. High-level runs require a registered, enabled, license-approved `model_choice`; production ships only a disabled `stabilityai/sd-turbo` candidate, so no production model is currently selectable.
- Explicit anime-only 4x Real-ESRGAN finalization for `realesrgan-x4plus-anime` and `realesr-animevideov3-x4`, configured only through `LOCAL_GPU_IMAGEGEN_REALESRGAN_DIR`.
- Mocked/model-free coverage for a two-round anime refine loop and optional postprocessing success/fallback behavior.

### Changed

- MCP initialize and the Codex plugin manifest now report version `0.4.0`; the public surface remains exactly nine tools and the low-level `local_gpu_generate_image` compatibility contract is unchanged.
- New JPEG previews use `round-NN-preview.jpg`; stored legacy `round-NN.preview.jpg` manifest paths remain readable without rewriting.
- Vision-capable hosts record evidence-based reviews and refine/explore decisions. Text-only hosts retain one successful round, mark review unavailable, and stop without fabricated scores or finalization.
- Successful optional postprocessing preserves `final.png`, publishes `final-upscaled.png`, and records exact source/output metadata. It is never automatic and accepts no arbitrary model or executable path.

### Fixed

- Failed or unavailable postprocessing falls back to the reviewed original final with sanitized warnings; cleanup problems also report `postprocess_cleanup_failed` and may retain diagnostic residue.

### Evidence Boundary

- The anime vertical slice uses fake backend/postprocessor boundaries. It is not retained real Codex, vision, model, GPU, or Real-ESRGAN evidence, and Codex is not a verified host.
- No production, quality, performance, VRAM, popularity, star, named-client, or real-acceptance claim is made. Masks, child revisions, PPT/UI workflows, and other v0.5 work are not part of this release.
- No model, license, binary, package, or output example is bundled or downloaded by this release work.

## [0.3.0] - 2026-07-21

### Added

- Seven high-level MCP tools for profile discovery, durable run creation, status recovery, generation rounds, review, final publication, and confirmed cleanup.
- A persisted run manifest with one-to-three-round budgets, idempotent attempts, stale-attempt recovery, review evidence, and recoverable next actions.
- Bounded JPEG previews beside validated full local PNG artifacts and atomic final publication.
- A standalone-illustration profile with merged constraints, rubric dimensions, hard failures, and allowed refine/explore changes.

### Changed

- MCP initialize and the Codex plugin manifest now report version `0.3.0`.
- The run engine stores a nullable internal model choice and accepts only `auto` or `off` for the recorded upscale policy.
- Public documentation now distinguishes model-free and mocked coverage from the still-absent retained real Codex-client/GPU generation evidence.
- The original readiness and direct generation compatibility tools, local-only Diffusers default, and explicit download permission remain available.

### Fixed

- High-level finalization now validates and publishes the caller-nominated reviewed round under the run lock instead of silently substituting a weighted-best round.

## [0.2.0]

### Added

- Structured success output schemas for readiness and generation tools.
- Server-side validation for types, enums, ranges, unknown fields, dimensions, and mode-specific inputs.
- MCP `ping` support.
- `scripts/verify_mcp.py` for a model-free stdio contract check, with optional environment-specific readiness verification.
- Architecture, troubleshooting, security, and contribution documentation.
- Explicit `allow_download` control for Diffusers models and LoRAs.

### Changed

- A valid `ready: false` readiness report is returned as tool success rather than backend failure.
- Diffusers now uses local model files only unless download permission is explicitly enabled.
- Successful script JSON is returned as MCP `structuredContent`.

### Fixed

- Empty array tool arguments are no longer treated as an empty object.
- A UTF-8 byte-order mark from Windows stdio diagnostics no longer causes a JSON parse failure.
- WebUI malformed image payloads and transport failures return concise errors.
