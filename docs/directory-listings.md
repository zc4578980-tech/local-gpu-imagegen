# Prepared Directory Listings

These entries are release materials for version `0.8.3` only. They do not by themselves authorize a package publication, Registry publication, submission, maintainer contact, or third-party pull request.

## awesome-mcp-servers

Alphabetized entry under Image Generation:

```markdown
- [local-gpu-imagegen](https://github.com/zc4578980-tech/local-gpu-imagegen) - Connect Codex or Claude Code to existing local ComfyUI, AUTOMATIC1111/Forge, or Diffusers backends with explicit routes and review.
```

PR body:

```text
Adds local-gpu-imagegen `0.8.3`, a Python stdio MCP server that connects Codex or Claude Code to an existing local image-generation stack through a version-pinned durable `uvx` launcher, optional explicit Windows portable ComfyUI lifecycle management, supported ordinary ComfyUI API workflow onboarding, explicit model routes, bounded review, byte-bound finalization, and durable recovery. It does not bundle model weights or download or switch them silently. A historical Codex `0.7.0` generation demo and a Codex `0.8.0` zero-GPU onboarding session are retained separately; regional and two-stage composition remain experimental.
```

A current-v0.8 Codex managed-MCP live gate and its separately approved bounded
replacement produced two private, reviewed, ineligible runs. They are
fail-closed local development evidence, not publishable release-set artifacts;
Claude Code hosted generation remains pending.

Submission: [punkpeye/awesome-mcp-servers#11452](https://github.com/punkpeye/awesome-mcp-servers/pull/11452) is open, mergeable, and passed the target repository's `check-submission` job. The submitted entry uses the current `Multimedia Process` category rather than the stale prepared `Image Generation` category name.

## Glama

- Name: `local-gpu-imagegen`
- Repository: `https://github.com/zc4578980-tech/local-gpu-imagegen`
- Package: public PyPI `local-gpu-imagegen==0.8.3`
- Official Registry: `io.github.zc4578980-tech/local-gpu-imagegen` version `0.8.3`, status `active`
- Transport: `stdio`
- Install/run: `uvx local-gpu-imagegen serve`
- Description: `Run supported local image workflows from Codex or Claude Code across existing ComfyUI, AUTOMATIC1111/Forge, and Diffusers installations with explicit routes and review.`
- Limitations: `No model weights are bundled. Two private, reviewed, ineligible current-v0.8 Codex runs are fail-closed local development evidence, not a publishable generation release set. Claude Code hosted generation remains pending. Complete 9+3 acceptance is not claimed. Composition routes remain experimental; measured latency, VRAM, production readiness, and image-quality improvement are not claimed.`

Status: not submitted. The public `owner/repository` server path still returns 404, and Glama's current Add Server action requires an interactive browser surface that was unavailable in the submitting task. A similarly named 200 response did not contain the repository URL and is not treated as a listing.
