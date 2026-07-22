# Changelog

All notable changes will be documented in this file.

## [Unreleased]

No unreleased changes.

## [0.6.0] - 2026-07-22

### Added

- An installable, dependency-free `local-gpu-imagegen` CLI with `serve`, `doctor`, `verify`, and client `config` commands.
- Wheel packaging for the MCP modules, immutable profiles, reviewed workflow templates, and Agent Skill, verified from outside the source checkout in an isolated virtual environment.
- A deterministic model-free protocol GIF and manifest that are explicitly marked as simulation rather than model output or quality evidence.
- Codex and Claude Desktop configuration-contract verification plus Windows/Ubuntu CI on Python 3.11 and 3.12.
- Bounded `api_only`, `selected_folders`, `common_locations`, and `full_drive` discovery with displayed plans, two-stage `index` / selected `fingerprint`, cancellation, and safe link/reparse exclusions.
- User-local atomic model trust, private versus `public_evidence` scope, deterministic capability routing, frozen route tokens, prompt compilers, and identity-drift rejection.
- A reviewed ComfyUI `sd15-txt2img-v1` template, imported-workflow allowlist validation, bounded job polling/output retrieval, and normalized adapter parity with WebUI.
- Three MCP tools: `local_gpu_discover_models`, `local_gpu_set_model_trust`, and `local_gpu_recommend_models`; the current source surface now contains exactly fifteen tools.
- Canonical component bundles for reviewed ComfyUI workflows, binding primary model, text encoder, VAE, workflow SHA-256, byte sizes, filesystem identities, and one bundle SHA-256 through a non-mutating trust inspection action.

### Changed

- The project is now MIT licensed and includes release-safe issue and pull-request templates.
- Public documentation now leads with the installed workflow, auditable protocol loop, and exact evidence limitations.
- Durable runs now retain and recheck backend, endpoint, model identity, workflow, and compiler fields. Child revisions inherit the parent route and cannot override it.
- The Agent Skill now resolves one route, displays it, obtains a new post-display confirmation, and starts without a silent model/backend/workflow switch.
- Public evidence validates the full private route against acceptance authority, then exports a minimal cryptographic route without local endpoint, checkpoint, or path values.
- ComfyUI public-evidence authority now requires component-by-component source, license, output-redistribution approval, and exact bundle equality; legacy monolithic WebUI evidence remains compatible.

### Security

- Public internet endpoints are rejected, LAN prompt/image transmission requires exact confirmation, `.ckpt` remains opaque during discovery, and credentials are rejected from trust state.
- ComfyUI shell/script/process/network/download/custom-node graphs, unbound parameters, traversal, and resource overruns fail before submission.

### Evidence Boundary

- Discovery, trust, routing, WebUI, and ComfyUI adapters are model-free contract-tested. Real ComfyUI integration evidence is not retained, and no complete real 9+3 visual-acceptance matrix, quality, performance, or VRAM claim is made.
- No model weights, private runs, local trust records, or real image-quality acceptance package are included in the preview release.
- The installed Z-Image component bytes match the public Comfy-Org hashes. The VAE embeds Apache-2.0 ModelSpec authority, but the NVFP4 primary model and FP4 text encoder do not bind their quantized bytes to an explicit source license, and the repack repository declares no license; public authority remains blocked and `release_ready` remains false.

## [0.5.0] - 2026-07-21

### Added

- `presentation-visual` and `ui-visual-asset` Profiles beside `standalone-illustration`, with delivery-specific subtypes, hard failures, rubrics, examples, and mutable fields.
- Immutable child revision runs with reviewed-parent lineage, copied `parent-source.png`, explicit preserve/change contracts, independent one-to-three-round budgets, and preservation review results.
- Deterministic user/rectangle/polygon inpaint masks, bounded JPEG overlays, content hashes, and explicit confirmation that is invalidated when source or mask bytes change.
- Three MCP tools: `local_gpu_branch_run`, `local_gpu_prepare_mask`, and `local_gpu_confirm_mask`; high-level generation now maps fixed prompt-refine, img2img, and inpaint child modes.
- A fixed nine-brief, three-revision fake-backend contract matrix covering all three visual Profiles.

### Changed

- At the historical `0.5.0` boundary, MCP initialize and the Codex plugin manifest reported twelve tools while the low-level compatibility tools remained unchanged.
- The Agent Skill can gather and confirm preserve/change intent, choose the least destructive supported revision mode, show geometry-mask overlays, and require explicit approval before confirmation.
- Child mask IDs participate in idempotency hashes and retained round evidence, preventing a different confirmed mask from reusing an earlier completed request.

### Evidence Boundary

- Mocked/model-free tests exercise real registry, engine, store, revision, mask, protocol, and artifact contracts with fake backend output. The matrix does not prove visual quality and is not retained real Codex, vision, model, GPU, backend, or Real-ESRGAN evidence.
- No production model is bundled or currently approved. No dependency/model download, license selection, remote creation, push, release, or publication is part of this release work.
- Complete PPT decks, frontend code/components, production icons, SVG, transparent PNG, seamless-texture guarantees, and automatic segmentation remain excluded.

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
