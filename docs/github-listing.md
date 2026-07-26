# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> Connect Codex or Claude Code to existing local ComfyUI, AUTOMATIC1111/Forge, or Diffusers image backends without silent downloads or model switches.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## Preview release

Title: `v0.8.0 Preview - Run existing ComfyUI workflows from your Agent`

Summary:

This preview packages a seventeen-tool MCP server and installed Python CLI for Codex and Claude Code. Its primary launch path inspects and registers supported ordinary ComfyUI `txt2img` API workflows with single-checkpoint or split-model topology, reports `source_sha256`, `workflow_sha256`, inferred bindings, components, and limitations, then requires later digest-bound registration confirmation and separate trust through `registered_workflow_id`; registration does not grant model trust. The project reuses an existing ComfyUI backend without silently downloading or switching a model. AUTOMATIC1111/Forge and Diffusers remain compatibility paths.

One retained installed Codex onboarding session exercised discovery, inspection, registration, exact checkpoint fingerprinting, component binding, and private trust without submitting a prompt or using the GPU. A separate retained Codex generation produced the ordinary-route SDXL image described below. The records are not one end-to-end imported-workflow generation and make no image-quality superiority claim.

One installed Codex session produced a validated ordinary `sdxl-txt2img` SDXL/ComfyUI result retained as its original 1024x1024 finalized PNG with a sanitized MCP result, full-resolution review, exact hashes, and public rights. Its disclosed limitations are a red-purple palette rather than clear blue hour, no distinct directional beacon beam, one extra navigation beacon, and minor railing/cliff-ladder artifacts. Regional and two-stage composition remain experimental, are not part of the golden path, and provide no fallback; their retained negative evidence does not establish a visual-quality improvement.

Publication still requires a retained Claude Code generation session, four green public CI jobs at the exact release commit, the exact PyPI artifact, the MCP Registry record, reviewed social-preview metadata, synchronized release copy, and later explicit authority for every remote-publication action. The post-release 30-day net-new Star goal begins at formal GitHub Release publication and is not a publication blocker or guarantee. Publication-dependent URLs remain pending. Zero-GPU real-client onboarding evidence is retained, but the release does not claim complete 9+3 acceptance, measured quality, latency, VRAM, concurrency, production readiness, or workflow-generated image evidence.

Install after PyPI publication:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
