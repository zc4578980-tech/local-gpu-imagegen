# Changelog

All notable changes will be documented in this file.

## [Unreleased]

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
