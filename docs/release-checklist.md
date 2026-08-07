# v0.9.0 Release Checklist

This checklist covers repository release readiness. It does not grant model,
workflow-component, generated-output, client-configuration, publication, or
public acceptance authority.

## Guided Bootstrap Gate

- [x] Existing-environment `bootstrap status` and zero-environment `bootstrap
  plan` / `bootstrap apply` paths are documented.
- [x] Explicit download and license confirmation, SHA-256 hash confirmation,
  source display, resumable transfers, bounded rollback, 10 GiB VRAM, 30 GiB
  free disk, and Windows 10/11 x64 NVIDIA scope are stated.
- [x] Docker is not required. No runtime or model download is silent, and
  bootstrap readiness is not described as production readiness.
- [x] One fresh local acceptance installed from user-approved ComfyUI and SDXL
  artifacts, reached managed readiness, and completed a bounded real MCP run.
  This does not prove the automatic download path on every network or host.

## Gate Policy

The v0.9 preview gate requires an exact-commit model-free suite, a reproducible
clean wheel, exactly seventeen tools, fail-closed `doctor` behavior, safe
named-client setup contracts, guided-bootstrap transaction coverage, and
truthful disclosure of missing evidence.

The unchanged `python scripts/validate_acceptance_evidence.py --strict`
command remains the full-acceptance/v1.0 gate. It requires exactly nine
accepted roots and three declared child revisions. Its expected failure on the
incomplete matrix does not block the separately defined v0.9 preview gate, but
it blocks any full-acceptance or v1.0 claim.

The `100 net-new GitHub Stars` floor is a post-release adoption goal and
planning floor. It does not block publication, and a missed or incomplete
result does not retract the Release.

## Local Gate

- [x] The finalized-run candidate leak has a RED/GREEN regression test;
  finalized and restarted responses omit the stale candidate, repeated
  finalization returns `already_finalized`, and concurrent generation keeps its
  established error semantics.
- [ ] Freeze an exact release commit with a clean tracked worktree.
- [x] The pre-freeze candidate content passed all 1,148 model-free tests with
  12 documented platform/privilege skips, Python compilation, `pip check`, and
  independent stdio verification of version `0.9.0` and exactly seventeen
  tools.
- [ ] Run the complete model-free suite and Python compilation at that exact
  commit; only documented privilege/integration skips may remain.
- [x] Build `local_gpu_imagegen-0.9.0-py3-none-any.whl` twice from the same
  source epoch and require byte-identical SHA-256 values.
- [ ] Pass the offline release-candidate verifier and isolated installed-wheel
  checks for version `0.9.0`, protocol `2024-11-05`, and exactly seventeen
  tools.
- [x] Pass bounded credential, private-path, local-state, image, model-weight,
  temporary-client, dependency, and `git diff --check` scans.

## Evidence Gate

- [x] The retained Codex `0.7.0` generation and `0.8.0` onboarding records
  remain historical evidence and are not relabeled as v0.9 acceptance.
- [x] A local v0.9 Windows/NVIDIA acceptance finalized one reviewed
  non-human environment PNG through managed ComfyUI and the real MCP path.
- [x] The accepted local source and final PNG bytes are identical at
  `1216x832`, 1,403,658 bytes, with SHA-256
  `f999cf440f1557017b0b1dd16d5dd1d4bddc3bac63d30b9aaa8b4e9c6f1cf61b`.
- [ ] The accepted environment run remains local pending a separate sanitized
  export, public-rights validation, and portable evidence check. It is not yet
  a publishable release-set artifact.
- [x] Two private character runs remain ineligible negative evidence. Strict
  prominent-human anatomy acceptance was not established, and neither image
  is a publishable release-set artifact or may be used as a release or
  promotional asset. They remain not publishable release-set artifacts.
- [ ] Claude Code hosted generation remains pending.
- [x] Regional and two-stage routes remain experimental, outside the golden
  path, and unsupported by a visual-quality improvement claim.

## Publication Gate

- [ ] README, changelog, package metadata, plugin metadata, `server.json`,
  release copy, and directory copy agree on `0.9.0`, exactly seventeen tools,
  the ordinary golden path, guided-bootstrap scope, and open limitations.
- [ ] Windows and Ubuntu CI on Python 3.11 and 3.12 are green at the exact
  frozen release commit.
- [ ] Push the exact commit without rebuilding the verified wheel.
- [ ] Publish the exact wheel to PyPI and verify its public SHA-256.
- [ ] Publish the matching MCP Registry descriptor and verify the resolved
  package, positional `serve` argument, stdio transport, and active version.
- [ ] Create tag `v0.9.0` and the non-prerelease GitHub Release from the same
  commit and wheel identity.
- [ ] Update the existing `awesome-mcp-servers` submission and separately
  decide whether to submit Glama.
- [ ] Review and upload the social preview under a separate remote-metadata
  publication action.
- [ ] Prepare, review, and publish Bilibili material only from approved public
  assets. Do not use either rejected character image.

Public `v0.8.3` remains the current released package until every v0.9
publication item above is completed. No old commit, wheel, proposal, route,
prompt ID, approval, or image can substitute for a fresh v0.9 publication
identity.

## Post-release adoption measurement

- [x] Campaign `v0.8.3-release-364342670` remains anchored to the historical
  formal GitHub Release publication time and retains its truthful degraded
  zero-Star baseline recorded 37 minutes after publication.
- [ ] Complete its T+30 observation within the documented inclusive window or
  retain `measurement_incomplete`; do not reconstruct publication-time data.
- [ ] Treat `100 net-new GitHub Stars` as a first-month planning floor, not a
  guarantee, quality result, or publication gate.

## Open Limitations

- Complete retained 9+3 real host/vision acceptance.
- Additional named-client generation coverage beyond Codex.
- Sanitized public export of the accepted v0.9 environment result.
- Candidate-grade prominent-human anatomy on the current SDXL base route.
- Measured image quality, latency, performance, concurrency, and VRAM evidence.
