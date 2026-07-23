# GitHub Listing

## Repository

Name: `local-gpu-imagegen`

Description:

> Auditable Agent control plane for local image generation across ComfyUI, AUTOMATIC1111/Forge, and Diffusers: trusted routes, bounded review, immutable revisions, no silent downloads.

Topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`, `stable-diffusion`, `agent-tools`, `python`

## Preview release

Title: `v0.7.0 Preview - Auditable regional control for local image generation`

Summary:

This preview packages the fifteen-tool MCP server as an installable Python CLI and adds read-only guided Codex/Claude Code setup, deterministic route confirmation, bounded successful-round budgets, structured full-resolution review, immutable preserve/change revisions, durable manifests, WebUI/Forge and reviewed ComfyUI routes, and explicit local-model trust. Its fixed copy/subject SDXL route freezes displayed region geometry while allowing regional prompt and strength refinement. A deterministic model-free vertical slice verifies that lifecycle without starting ComfyUI or a GPU.

Publication is blocked until genuine regional SDXL output, retained Codex and Claude Code tool-call records, four public CI jobs, the PyPI artifact, and MCP Registry record all validate. The simulated demo and fake-backend regional slice are not model output. The release does not include model weights, private runs, complete 9+3 real acceptance, or measured quality, latency, VRAM, or production-readiness claims.

Install after PyPI publication:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```
