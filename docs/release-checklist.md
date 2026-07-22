# Preview Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, or public acceptance authority.

## Local gate

- [x] All model-free tests pass on the release commit.
- [x] Python sources compile.
- [x] All tracked JSON documents parse.
- [x] A wheel builds and installs in an isolated virtual environment outside the checkout.
- [x] The installed wheel exposes exactly fifteen MCP tools.
- [x] The protocol demo regenerates byte-for-byte and contains no private values.
- [x] Codex and Claude Desktop configuration contracts parse and launch the equivalent stdio contract.
- [x] Tracked files contain no credentials or personal absolute paths.
- [x] `git diff --check` passes.
- [x] `docs/evidence/runs/`, `outputs/`, trust state, and private images remain untracked and unstaged.

## Publication gate

- [x] Version is `0.6.0` in package metadata, MCP initialize, and plugin metadata.
- [ ] GitHub description and topics match `docs/github-listing.md`.
- [ ] Release branch is pushed without private artifacts.
- [ ] Tag `v0.6.0` points to the verified release commit.
- [ ] Preview release notes preserve all evidence and host-compatibility limitations.
- [ ] Public repository and release URLs resolve.

## Still pending after preview

- Complete retained 9+3 real host/vision acceptance.
- Real hosted-client sessions for Codex and Claude Desktop.
- Publishable real-model output whose route and output rights are fully authorized.
- Measured image quality, latency, performance, and VRAM evidence.
