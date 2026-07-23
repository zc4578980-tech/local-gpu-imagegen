# Preview Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, or public acceptance authority.

## Local gate

- [x] The complete `0.7.0` model-free gate passes: 584 tests passed, 4 expected Windows link-privilege skips, 0 failures.
- [x] The focused regional suites cover normalized geometry, graph compilation, live capability signatures, exact bundle routing, frozen plans, MCP validation, the Agent confirmation contract, and a deterministic two-round vertical slice.
- [x] Python compilation, all 31 tracked UTF-8 JSON documents, repository hygiene, public-document claims, and `git diff --check` pass.
- [x] The `0.7.0` wheel builds offline into a separate temporary directory and installs under isolated Python 3.12.12 outside the checkout.
- [x] The installed `0.7.0` wheel reports version `0.7.0`, exposes exactly fifteen MCP tools and both SDXL workflow assets, and returns read-only Codex/Claude Code setup plans with `applied: false`.
- [x] Codex and Claude Code guided setup remains read-only without `--apply`.
- [x] Real SDXL discovery metadata produces a 3,878-byte bounded MCP result instead of 34,116 bytes; the bounded result contains no data URI and leaves source metadata unchanged.
- [x] The protocol demo regenerates byte-for-byte and contains no private values.
- [x] Tracked files contain no credentials or personal absolute paths.
- [x] `docs/evidence/runs/`, `outputs/`, trust state, and private images remain untracked and unstaged.

Immutable retained artifact: `local_gpu_imagegen-0.6.1-py3-none-any.whl`

Size: `191674` bytes

SHA-256: `33ed4bc1564a92e3252b80f79cf1a7dd91f726774045801fd617bf9d0ef02655`

Verified isolated candidate: `%TEMP%\local-gpu-imagegen-verification\v070-dist-51ebe49\local_gpu_imagegen-0.7.0-py3-none-any.whl`

Size: `202383` bytes

SHA-256: `1262ecab160231da88accff4f6417ababb2395a2d4e1f7f68f2d157977e934d0`

The retained `0.6.1` artifact must not be rebuilt or overwritten. All local observations must be repeated at the exact final release commit after genuine demo and named-client evidence are added.

## Evidence gate

- [ ] Genuine regional SDXL root and immutable child bytes validate under `docs/demo/real/`.
- [ ] The child is finalized by a later byte-bound user confirmation.
- [ ] Retained Codex and Claude Code sessions both call the installed wheel and pass the public validator.

## Publication gate

- [x] Version is `0.7.0` in package metadata, MCP initialize, plugin metadata, and `server.json`.
- [ ] GitHub description and topics match `docs/github-listing.md`.
- [ ] Release branch is pushed without private artifacts.
- [ ] All four Windows/Linux Python 3.11/3.12 GitHub Actions jobs are green at the release commit.
- [ ] The exact verified wheel is published as `local-gpu-imagegen==0.7.0` on PyPI.
- [ ] Official MCP Registry metadata resolves to the published PyPI package.
- [ ] Tag `v0.7.0` points to the verified release commit; historical tags remain unchanged.
- [ ] Preview release notes preserve all evidence and host-compatibility limitations.
- [ ] Public repository and release URLs resolve.

## Still pending after preview

- Complete retained 9+3 real host/vision acceptance.
- Additional named-client coverage beyond Codex and Claude Code.
- Additional publishable real-model routes beyond the bounded SDXL showcase.
- Measured image quality, latency, performance, and VRAM evidence.
