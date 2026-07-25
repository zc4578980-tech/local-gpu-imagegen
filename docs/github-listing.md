# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> Connect Codex or Claude Code to existing local ComfyUI, AUTOMATIC1111/Forge, or Diffusers image backends without silent downloads or model switches.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## Preview release

Title: `v0.8.0 Preview - Trusted local image generation for Agents`

Summary:

This preview packages the seventeen-tool MCP server as an installable Python CLI for Codex and Claude Code. It reuses an existing ComfyUI, AUTOMATIC1111/Forge, or Diffusers backend, delegates setup to each official client command, confirms deterministic model routes and budgets, and retains structured full-resolution review, byte-bound finalization, immutable revisions, and durable recovery without silently downloading or switching a model. Safe workflow onboarding covers ordinary `txt2img` API workflows with single checkpoint or split model topology, reports `source_sha256` and `workflow_sha256`, registers only after later digest-bound confirmation, and then requires separate trust through `registered_workflow_id`; registration does not grant model trust.

One installed Codex session produced a validated ordinary `sdxl-txt2img` SDXL/ComfyUI result retained as its original 1024x1024 finalized PNG with a sanitized MCP result, full-resolution review, exact hashes, and public rights. Its disclosed limitations are a red-purple palette rather than clear blue hour, no distinct directional beacon beam, one extra navigation beacon, and minor railing/cliff-ladder artifacts. Regional and two-stage composition remain experimental, are not part of the golden path, and provide no fallback; their retained negative evidence does not establish a visual-quality improvement.

Publication still requires a retained Claude Code generation session, four green public CI jobs at the exact release commit, the exact PyPI artifact, the MCP Registry record, reviewed social-preview metadata, synchronized release copy, and later explicit authority for every remote-publication action. The post-release 30-day net-new Star goal begins at formal GitHub Release publication and is not a publication blocker. Publication-dependent URLs remain pending. Zero-GPU real-client onboarding evidence is retained, but the release does not claim complete 9+3 acceptance, measured quality, latency, VRAM, concurrency, production readiness, or workflow-generated image evidence.

Install after PyPI publication:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
