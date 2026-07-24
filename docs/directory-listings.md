# Prepared Directory Listings

These entries are release materials only. They do not authorize a submission, maintainer contact, or third-party pull request.

## awesome-mcp-servers

Alphabetized entry under Image Generation:

```markdown
- [local-gpu-imagegen](https://github.com/zc4578980-tech/local-gpu-imagegen) - Connect Codex or Claude Code to existing local ComfyUI, AUTOMATIC1111/Forge, or Diffusers backends with explicit routes and review.
```

PR body:

```text
Adds local-gpu-imagegen, a Python stdio MCP server that connects Codex or Claude Code to an existing local image-generation stack through installed commands, explicit model routes, bounded review, byte-bound finalization, and durable recovery. It does not bundle model weights or download or switch them silently. The ordinary `sdxl-txt2img` golden result remains pending; regional and two-stage composition are experimental and not part of the golden path.
```

## Glama

- Name: `local-gpu-imagegen`
- Repository: `https://github.com/zc4578980-tech/local-gpu-imagegen`
- Package: `local-gpu-imagegen==0.7.0` on PyPI
- Transport: `stdio`
- Install/run: `uvx local-gpu-imagegen serve`
- Description: `Trusted local image generation for Codex and Claude Code across ComfyUI, AUTOMATIC1111/Forge, and Diffusers.`
- Limitations: `No model weights are bundled; the golden result and named-client sessions remain pending; composition routes are experimental; measured latency, VRAM, production readiness, and complete 9+3 real acceptance are not claimed.`

Status: prepared, not submitted
