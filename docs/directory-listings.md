# Prepared Directory Listings

These entries are release materials only. They do not authorize a submission, maintainer contact, or third-party pull request.

## awesome-mcp-servers

Alphabetized entry under Image Generation:

```markdown
- [local-gpu-imagegen](https://github.com/zc4578980-tech/local-gpu-imagegen) - Auditable local-first image-generation control plane for ComfyUI, AUTOMATIC1111/Forge, and Diffusers with trusted routes, bounded review, and immutable revisions.
```

PR body:

```text
Adds local-gpu-imagegen, a Python stdio MCP server that lets Agents use an existing local image-generation stack through confirmed model routes, bounded generation/review budgets, immutable preserve/change revisions, and an optional frozen copy/subject SDXL composition route. It does not bundle model weights or download them silently. Regional lifecycle behavior is model-free verified; visual quality, performance, VRAM, and the complete 9+3 acceptance matrix remain unverified.
```

## Glama

- Name: `local-gpu-imagegen`
- Repository: `https://github.com/zc4578980-tech/local-gpu-imagegen`
- Package: `local-gpu-imagegen==0.7.0` on PyPI
- Transport: `stdio`
- Install/run: `uvx local-gpu-imagegen serve`
- Description: `Auditable Agent control plane for trusted local image generation across ComfyUI, AUTOMATIC1111/Forge, and Diffusers.`
- Limitations: `No model weights are bundled; model quality comes from the user's local model; measured latency, VRAM, production readiness, and complete 9+3 real acceptance are not claimed.`

Status: prepared, not submitted
