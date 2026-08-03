# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> MCP-first control plane for supported ComfyUI workflows with cryptographic model identity, explicit approvals, durable evidence, and no silent downloads.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## GitHub Release

Title: `Local GPU Imagegen v0.8.3`

Summary:

This preview packages a seventeen-tool MCP server and installed Python CLI for Codex and Claude Code. Its primary launch path inspects and registers supported ordinary ComfyUI `txt2img` API workflows with single-checkpoint or split-model topology, reports `source_sha256`, `workflow_sha256`, inferred bindings, components, and limitations, then requires later digest-bound registration confirmation and separate trust through `registered_workflow_id`; registration does not grant model trust. The project reuses an existing ComfyUI backend without silently downloading or switching a model. AUTOMATIC1111/Forge and Diffusers remain compatibility paths.

One retained installed Codex onboarding session exercised discovery, inspection, registration, exact checkpoint fingerprinting, component binding, and private trust without submitting a prompt or using the GPU. A separate retained Codex generation produced the ordinary-route SDXL image described below. The records are not one end-to-end imported-workflow generation and make no image-quality superiority claim.

A current-v0.8 Codex managed-MCP live gate completed exact-file verification, immutable workflow preparation, fresh route approval, and one generation round; its separately approved bounded replacement completed two more rounds. The two private, reviewed, ineligible runs are fail-closed local development evidence, not publishable release-set artifacts, finalized images, or image-quality evidence. Claude Code hosted generation remains pending.

One installed Codex session produced a validated ordinary `sdxl-txt2img` SDXL/ComfyUI result retained as its original 1024x1024 finalized PNG with a sanitized MCP result, full-resolution review, exact hashes, and public rights. Its disclosed limitations are a red-purple palette rather than clear blue hour, no distinct directional beacon beam, one extra navigation beacon, and minor railing/cliff-ladder artifacts. Regional and two-stage composition remain experimental, are not part of the golden path, and provide no fallback; their retained negative evidence does not establish a visual-quality improvement.

Public `v0.8.3` is available from PyPI and as a non-prerelease GitHub Release at `https://github.com/zc4578980-tech/local-gpu-imagegen/releases/tag/v0.8.3`; its exact release commit passed the four-job Windows/Ubuntu and Python 3.11/3.12 matrix. MCP Registry publication, repository topics, social-preview metadata, and directory submissions remain pending. `100 net-new GitHub Stars` is the minimum acceptable first-month outcome and planning floor, not the target; it is a post-release adoption goal and does not block publication. The threshold is not a guarantee, and a miss does not retract the Release. Zero-GPU real-client onboarding evidence is retained, but the release does not claim complete 9+3 acceptance, measured quality, latency, VRAM, concurrency, production readiness, or workflow-generated image evidence.

Install:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
