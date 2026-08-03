# v0.8.3 Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, client-configuration, publication, or public acceptance authority.

## Gate policy

The v0.8 preview gate requires exact-commit model-free tests, a clean wheel install, exactly seventeen tools, fail-closed `doctor` behavior, safe named-client setup contracts, the portable historical Codex 0.7 generation labeled historical, the Codex 0.8 zero-GPU onboarding record labeled non-generation, and explicit disclosure of missing evidence. A current-v0.8 Codex managed-MCP live gate and its separately approved bounded replacement produced two private, reviewed, ineligible runs. They are fail-closed local development evidence, not publishable release-set artifacts, finalized images, image-quality evidence, or full acceptance.

The unchanged `python scripts/validate_acceptance_evidence.py --strict` command remains the full-acceptance/v1.0 gate. It requires exactly nine accepted roots and three declared child revisions. Its expected failure on the currently incomplete matrix does not block the separately defined v0.8 preview gate, but it does block any full-acceptance or v1.0 claim.

The `100 net-new GitHub Stars` floor is a post-release adoption goal and
planning floor. The approved post-release measurement design supersedes the
earlier forecast gate: a forecast below the floor does not block publication,
and a missed result does not retract the Release.

## Local gate

- [x] The offline release-candidate verifier passed at exact commit `6627838`; its immutable report records `"status": "passed"` for the frozen wheel SHA-256.
- [x] The final model-free suite, Python compilation, strict UTF-8 JSON parse, repository hygiene, and public-document truthfulness gates passed at that commit.
- [x] A fresh isolated Python 3.12 environment installed the exact-commit wheel outside the checkout and verified version `0.8.3`, protocol `2024-11-05`, and exactly seventeen tools; the four-job CI matrix covered Python 3.11 and 3.12.
- [x] Installed `verify`, fail-closed `doctor`, local-wheel `uvx`, and read-only Codex and Claude Code setup paths passed without a source clone or direct configuration-file edit.
- [x] Tracked files, staged files, and wheel entries passed the bounded credential, private-path, local-state, image, model-weight, and temporary-client scans.

## Evidence gate

- [x] The retained Codex `0.7.0` generation is historical evidence and is not a v0.8 release-set record.
- [x] The retained Codex `0.8.0` workflow-onboarding session is zero-GPU evidence and is not generation evidence.
- [x] A current-v0.8 Codex managed-MCP live gate and its separately approved bounded replacement produced two private, reviewed, ineligible runs. They remain fail-closed local development evidence and not publishable release-set artifacts.
- [ ] Claude Code hosted generation remains pending, and no publishable current-v0.8 named-client generation release set is retained.
- [x] One historical ordinary-route SDXL root retains its original PNG and MCP result, passes full-resolution structured review, and is finalized by a later byte-bound user confirmation.
- [x] The historical ordinary-route public demo validates portably under `docs/demo/real/`, including public rights, exact artifact hashes, route identity, and sanitized client binding.
- [x] README evidence appears before the simulated protocol material and is derived from the validated manifest.
- [x] Regional and two-stage routes remain labeled experimental, outside the golden path and release blockers, with no visual-quality improvement claim.

## Publication gate

- [x] The genuine-image social preview is generated, validated at 1280x640, and visually reviewed without mutating remote metadata.
- [x] GitHub Release publication received explicit authority; other remote metadata changes remain independently controlled.
- [x] README, changelog, package metadata, plugin metadata, `server.json`, GitHub copy, directory copy, and release notes agree on version `0.8.3`, exactly seventeen tools, three backends, the ordinary golden path, and open limitations.
- [x] Windows and Ubuntu jobs on Python 3.11 and 3.12 are green at exact release commit `6627838`.
- [x] The exact locally verified wheel was published without rebuilding, and PyPI reports the matching 260,937-byte SHA-256 identity.
- [x] The official MCP Registry record is active and resolves version `0.8.3` to the exact PyPI package, `uvx` runtime, positional `serve` argument, and stdio transport.
- [x] Tag `v0.8.3`, the public non-prerelease GitHub Release, package URL, and repository evidence URLs resolve to the exact verified release state.
- [x] The public Registry API returns exactly one matching `0.8.3` record with `status: active` and `isLatest: true`.
- [x] The repository description and all eight prepared GitHub topics are applied and verified through the public repository API.
- [ ] Remote social-preview metadata remains pending; the validated local preview asset has not been uploaded.
- [ ] Directory submissions remain unsubmitted until each receives separate authority.
- [x] The earlier pessimistic forecast is retained as planning evidence, while the approved post-release measurement policy supersedes it as a publication gate.

## Post-release adoption measurement

- [x] Campaign `v0.8.3-release-364342670` is anchored to the formal GitHub Release publication time and recorded a truthful degraded baseline of zero Stars at `2026-08-03T16:50:55Z`, 37 minutes later. It is usable but must never be presented as an on-time publication count.
- [ ] During the inclusive 24-hour T+30 collection window, append the repository-level Star total and validate the complete hash chain.
- [ ] Measure the floor as T+30 total Stars minus baseline total Stars; `100 net-new GitHub Stars` is the minimum acceptable first-month outcome, not the target, and the operating target remains above it.
- [ ] Record `goal_met`, `goal_missed`, or `measurement_incomplete` without interpolation or stargazer identities; an actual result below the floor is `goal_missed` and requires continued iteration, while a missed or incomplete result does not retract the Release.

## Still pending after release

- Complete retained 9+3 real host/vision acceptance.
- Additional named-client coverage beyond Codex and Claude Code.
- Additional publishable real-model routes beyond the bounded SDXL showcase.
- Measured image quality, latency, performance, and VRAM evidence.
