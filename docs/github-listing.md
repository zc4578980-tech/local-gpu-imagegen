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

The release-blocking golden result uses ordinary `sdxl-txt2img` and remains pending. Regional and two-stage composition are experimental, not part of the golden path, and provide no fallback; their retained negative evidence does not establish a visual-quality improvement. Publication also remains blocked on retained Codex and Claude Code sessions, four public CI jobs, the exact PyPI artifact, and the MCP Registry record. The release does not claim complete 9+3 acceptance, measured quality, latency, VRAM, or production readiness.

Install after PyPI publication:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
