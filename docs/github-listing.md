# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> Auditable Agent control plane for local image generation across ComfyUI, AUTOMATIC1111/Forge, and Diffusers: trusted routes, bounded review, immutable revisions, no silent downloads.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## Preview release

Title: `v0.6.1 Preview - Auditable local image-generation control plane`

Summary:

This preview packages the fifteen-tool MCP server as an installable Python CLI and adds read-only guided Codex/Claude Code setup, deterministic route confirmation, bounded successful-round budgets, structured full-resolution review, immutable preserve/change revisions, durable manifests, WebUI/Forge and reviewed ComfyUI routes, and explicit local-model trust. It includes a deterministic simulated protocol demo and cross-platform model-free tests.

Publication is blocked until the genuine SDXL before/after showcase, retained Codex and Claude Code tool-call records, four public CI jobs, PyPI artifact, and MCP Registry record all validate. The simulated demo is not model output. The release does not include model weights, private runs, complete 9+3 real acceptance, or measured quality, latency, VRAM, or production-readiness claims.

Install after PyPI publication:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
