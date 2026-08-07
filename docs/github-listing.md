# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> MCP-first control plane for supported ComfyUI workflows with cryptographic model identity, explicit approvals, durable evidence, and no silent downloads.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## GitHub Release

Title: `Local GPU Imagegen v0.9.0`

Summary:

This release packages a seventeen-tool MCP server and installed Python CLI for
Codex and Claude Code. It adds a confirmation-bound Windows/NVIDIA guided
bootstrap with explicit sources and licenses, resumable checksum verification,
bounded extraction and rollback, installed readiness checks, and optional
managed ComfyUI startup. Existing ComfyUI environments remain the fast path;
AUTOMATIC1111/Forge and Diffusers remain compatibility paths. Docker is not
required, and no model or runtime is downloaded or switched silently.

One retained installed Codex onboarding session exercised discovery, inspection, registration, exact checkpoint fingerprinting, component binding, and private trust without submitting a prompt or using the GPU. A separate retained Codex generation produced the ordinary-route SDXL image described below. The records are not one end-to-end imported-workflow generation and make no image-quality superiority claim.

A fresh local Windows/NVIDIA acceptance used user-approved ComfyUI and SDXL
artifacts, reached managed readiness, exercised the real seventeen-tool MCP
path, and finalized one reviewed non-human environment image with
byte-identical source and final hashes. That artifact remains local until a
separate sanitized export and is not bundled in the wheel. Two separate
character attempts remained private and ineligible because strict hand, eye,
and tail review failed; prominent-human anatomy quality is not established.
Claude Code hosted generation remains pending.

One installed Codex session produced a validated ordinary `sdxl-txt2img` SDXL/ComfyUI result retained as its original 1024x1024 finalized PNG with a sanitized MCP result, full-resolution review, exact hashes, and public rights. Its disclosed limitations are a red-purple palette rather than clear blue hour, no distinct directional beacon beam, one extra navigation beacon, and minor railing/cliff-ladder artifacts. Regional and two-stage composition remain experimental, are not part of the golden path, and provide no fallback; their retained negative evidence does not establish a visual-quality improvement.

`v0.9.0` is a local release candidate and is not yet on PyPI, tagged, published
as a GitHub Release, or registered as the latest MCP Registry version. Public
`v0.8.3` remains the current published package and Registry record. The
existing `awesome-mcp-servers` PR `#11452` describes that older public release;
the `0.9.0` update and Glama submission remain pending. `100 net-new GitHub
Stars` is the minimum acceptable first-month outcome and planning floor. The
floor is not a guarantee; it is a post-release adoption goal and does not block publication.
A missed result does not retract the Release.
The release does not claim complete 9+3 acceptance, character-quality
readiness, measured quality, latency, VRAM, concurrency, or production
readiness.

Install:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
