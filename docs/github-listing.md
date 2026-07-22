# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> Auditable Agent control plane for local image generation across ComfyUI, AUTOMATIC1111/Forge, and Diffusers: trusted routes, bounded review, immutable revisions, no silent downloads.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## Preview release

Title: `v0.6.0 Preview - Auditable local image-generation control plane`

Summary:

This preview packages the fifteen-tool MCP server as an installable Python CLI and adds deterministic route confirmation, bounded successful-round budgets, structured full-resolution review, immutable preserve/change revisions, durable manifests, WebUI/Forge and reviewed ComfyUI routes, and explicit local-model trust. It includes a deterministic simulated protocol demo, cross-platform model-free tests, and checked configuration contracts for Codex and Claude Desktop.

The demo is not model output. The client checks are not real hosted LLM sessions. The release does not include model weights, private runs, a publishable real-model showcase, complete 9+3 real acceptance, or measured quality, latency, VRAM, or production-readiness claims.

Install from a clone:

```shell
python -m pip install .
local-gpu-imagegen verify
local-gpu-imagegen config codex
```
