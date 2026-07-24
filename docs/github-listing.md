# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> Connect Codex or Claude Code to existing local ComfyUI, AUTOMATIC1111/Forge, or Diffusers image backends without silent downloads or model switches.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## Preview release

Title: `v0.7.0 Preview - Trusted local image generation for Agents`

Summary:

This preview packages the fifteen-tool MCP server as an installable Python CLI for Codex and Claude Code. It reuses an existing ComfyUI, AUTOMATIC1111/Forge, or Diffusers backend, delegates setup to each official client command, confirms deterministic model routes and budgets, and retains structured full-resolution review, byte-bound finalization, immutable revisions, and durable recovery without silently downloading or switching a model.

One installed Codex session produced a validated ordinary `sdxl-txt2img` SDXL/ComfyUI result retained as its original 1024x1024 finalized PNG with a sanitized MCP result, full-resolution review, exact hashes, and public rights. Its disclosed limitations are a red-purple palette rather than clear blue hour, no distinct directional beacon beam, one extra navigation beacon, and minor railing/cliff-ladder artifacts. Regional and two-stage composition remain experimental, are not part of the golden path, and provide no fallback; their retained negative evidence does not establish a visual-quality improvement.

Publication remains blocked on a retained Claude Code generation session, four public CI jobs, the exact PyPI artifact, the MCP Registry record, reviewed social-preview metadata, an evidence-backed pessimistic 30-day forecast of at least 100 Stars, and later explicit remote-publication authority. Publication-dependent URLs remain pending. The release does not claim complete 9+3 acceptance, measured quality, latency, VRAM, concurrency, or production readiness.

Install after PyPI publication:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
