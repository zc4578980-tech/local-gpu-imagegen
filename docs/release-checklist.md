# Preview Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, or public acceptance authority.

## Local gate

- [x] All model-free tests pass on the `0.6.1` local RC tree: 539 passed, 4 expected Windows link-privilege skips, 0 failures.
- [x] Python sources compile.
- [x] All 30 tracked JSON documents parse.
- [x] The `0.6.1` wheel builds and installs under isolated Python 3.12.12 outside the checkout.
- [x] The installed wheel exposes exactly fifteen MCP tools and both evidence schemas.
- [x] Codex and Claude Code guided setup remains read-only without `--apply`.
- [x] The protocol demo regenerates byte-for-byte and contains no private values.
- [x] Tracked files contain no credentials or personal absolute paths.
- [x] `git diff --check` passes.
- [x] `docs/evidence/runs/`, `outputs/`, trust state, and private images remain untracked and unstaged.

Local RC artifact: `local_gpu_imagegen-0.6.1-py3-none-any.whl`

SHA-256: `d4df7de961c872568d7a33ae1a029d3544b6303050c903f9b68d4375db7bdb44`

These local observations must be repeated at the exact final release commit after genuine demo and named-client evidence are added.

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
