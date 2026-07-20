# Changelog

All notable changes will be documented in this file.

## [Unreleased]

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
