# Prepared Directory Listings

These entries are prepared release materials for version `0.9.0` only. They do not by themselves authorize a package publication, Registry publication, submission, maintainer contact, or third-party pull request.

## awesome-mcp-servers

Alphabetized entry under Image Generation:

```markdown
- [local-gpu-imagegen](https://github.com/zc4578980-tech/local-gpu-imagegen) - Connect Codex or Claude Code to existing local ComfyUI, AUTOMATIC1111/Forge, or Diffusers backends with explicit routes and review.
```

PR body:

```text
Adds local-gpu-imagegen `0.9.0`, a Python stdio MCP server that connects Codex or Claude Code to an existing local image-generation stack through a version-pinned durable `uvx` launcher, or guides an explicitly confirmed Windows/NVIDIA portable ComfyUI bootstrap with resumable checksum verification and bounded rollback. It supports ordinary ComfyUI API workflow onboarding, explicit model routes, bounded review, byte-bound finalization, and durable recovery. It does not bundle model weights or download or switch them silently. Docker is not required. Regional and two-stage composition remain experimental.
```

A local v0.9 Windows/NVIDIA acceptance finalized one reviewed environment
image through managed ComfyUI and the real seventeen-tool MCP path. The image
remains local, and the retained local runs are not publishable release-set
artifacts. The accepted environment still needs separate sanitization and
export. Two private character runs remain ineligible negative evidence, so
prominent-human anatomy quality is not established. Claude Code hosted
generation remains pending.

Historical submission: [punkpeye/awesome-mcp-servers#11452](https://github.com/punkpeye/awesome-mcp-servers/pull/11452) describes public `v0.8.3`; its last retained state was open with `check-submission` passing. No `0.9.0` update has been submitted in this local audit.

## Glama

- Name: `local-gpu-imagegen`
- Repository: `https://github.com/zc4578980-tech/local-gpu-imagegen`
- Package candidate: `local-gpu-imagegen==0.9.0` (not yet published)
- Official Registry candidate: `io.github.zc4578980-tech/local-gpu-imagegen` version `0.9.0` (not yet published)
- Transport: `stdio`
- Install/run: `uvx local-gpu-imagegen serve`
- Description: `Run supported local image workflows from Codex or Claude Code across existing ComfyUI, AUTOMATIC1111/Forge, and Diffusers installations with explicit routes and review.`
- Limitations: `No model weights are bundled. One accepted environment run remains local pending sanitized export; two private character runs are ineligible negative evidence, so prominent-human anatomy quality is not established. Claude Code hosted generation remains pending. Complete 9+3 acceptance is not claimed. Composition routes remain experimental; measured latency, VRAM, production readiness, and image-quality improvement are not claimed.`

Status: not submitted. The retained historical check found the public `owner/repository` server path returning 404, and no network recheck or submission occurred during this local audit.
