# Preview Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, or public acceptance authority.

## Local gate

- [ ] All model-free tests pass on the exact `0.6.1` release commit.
- [ ] Python sources compile.
- [ ] All tracked JSON documents parse.
- [ ] The `0.6.1` wheel builds and installs in an isolated virtual environment outside the checkout.
- [ ] The installed wheel exposes exactly fifteen MCP tools and both evidence schemas.
- [ ] Codex and Claude Code guided setup remains read-only without `--apply`.
- [ ] The protocol demo regenerates byte-for-byte and contains no private values.
- [ ] Tracked files contain no credentials or personal absolute paths.
- [ ] `git diff --check` passes.
- [ ] `docs/evidence/runs/`, `outputs/`, trust state, and private images remain untracked and unstaged.

## Evidence gate

- [ ] Genuine SDXL root and immutable prompt-refine child bytes validate under `docs/demo/real/`.
- [ ] The child is finalized by a later byte-bound user confirmation.
- [ ] Retained Codex and Claude Code sessions both call the installed wheel and pass the public validator.

## Publication gate

- [x] Version is `0.6.1` in package metadata, MCP initialize, plugin metadata, and `server.json`.
- [ ] GitHub description and topics match `docs/github-listing.md`.
- [ ] Release branch is pushed without private artifacts.
- [ ] All four Windows/Linux Python 3.11/3.12 GitHub Actions jobs are green at the release commit.
- [ ] The exact verified wheel is published as `local-gpu-imagegen==0.6.1` on PyPI.
- [ ] Official MCP Registry metadata resolves to the published PyPI package.
- [ ] Tag `v0.6.1` points to the verified release commit; historical tag `v0.6.0` is unchanged.
- [ ] Preview release notes preserve all evidence and host-compatibility limitations.
- [ ] Public repository and release URLs resolve.

## Still pending after preview

- Complete retained 9+3 real host/vision acceptance.
- Additional named-client coverage beyond Codex and Claude Code.
- Additional publishable real-model routes beyond the bounded SDXL showcase.
- Measured image quality, latency, performance, and VRAM evidence.
