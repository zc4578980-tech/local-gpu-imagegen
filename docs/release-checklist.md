# Preview Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, client-configuration, publication, or public acceptance authority.

## Gate policy

The v0.8 preview gate requires exact-commit model-free tests, a clean wheel install, exactly seventeen tools, fail-closed `doctor` behavior, safe named-client setup contracts, the portable historical Codex 0.7 generation labeled historical, the Codex 0.8 zero-GPU onboarding record labeled non-generation, and explicit disclosure of missing evidence. A current-v0.8 Codex managed-MCP live gate and its separately approved bounded replacement produced two private, reviewed, ineligible runs. They are fail-closed local development evidence, not publishable release-set artifacts, finalized images, image-quality evidence, or full acceptance.

The unchanged `python scripts/validate_acceptance_evidence.py --strict` command remains the full-acceptance/v1.0 gate. It requires exactly nine accepted roots and three declared child revisions. Its expected failure on the currently incomplete matrix does not block the separately defined v0.8 preview gate, but it does block any full-acceptance or v1.0 claim.

## Local gate

- [ ] The offline release-candidate verifier passes at the exact final commit, and its new `candidate-report.json` contains `"status": "passed"` for the frozen wheel SHA-256.
- [ ] The final model-free suite, Python compilation, strict UTF-8 JSON parse, repository hygiene, and public-document truthfulness gates pass at one exact commit.
- [ ] A fresh isolated Python 3.12 environment installs the final exact-commit wheel outside the checkout and verifies version `0.8.2`, protocol `2024-11-05`, and exactly seventeen tools; exact-commit Python 3.11 verification remains a CI gate.
- [ ] Installed `verify`, fail-closed `doctor`, local-wheel `uvx`, and read-only Codex and Claude Code setup paths succeed against the final exact-commit wheel without a source clone or direct configuration-file edit.
- [ ] Tracked files, staged files, and wheel entries contain no credentials, personal paths, trust state, private runs, rejected images, model weights, or temporary client files.

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
- [ ] Explicit authority is granted for each remote metadata change and publication action.
- [ ] README, changelog, package metadata, plugin metadata, `server.json`, GitHub copy, directory copy, and release notes agree on version `0.8.2`, exactly seventeen tools, three backends, the ordinary golden path, and open limitations.
- [ ] Windows and Ubuntu jobs on Python 3.11 and 3.12 are green at the exact release commit.
- [ ] The exact locally verified wheel is published without rebuilding and its public digest matches.
- [ ] The official MCP Registry record resolves version `0.8.2` to the exact PyPI package and stdio command.
- [ ] Tag `v0.8.2`, the preview release, package URL, Registry URL, and repository evidence URLs resolve to the exact verified release state.
- [ ] Directory submissions remain unsubmitted until each receives separate authority.
- [ ] A written pessimistic forecast based on named channels, documented conversion assumptions, and available response capacity is at or above the planning floor; a forecast below `100 net-new GitHub Stars` blocks the formal launch.

## Post-release adoption measurement

- [ ] At formal GitHub Release publication time, initialize the append-only campaign baseline under `docs/evidence/adoption/<campaign_id>/` within five minutes when possible.
- [ ] During the inclusive 24-hour T+30 collection window, append the repository-level Star total and validate the complete hash chain.
- [ ] Measure the floor as T+30 total Stars minus baseline total Stars; `100 net-new GitHub Stars` is the minimum acceptable first-month outcome, not the target, and the operating target remains above it.
- [ ] Record `goal_met`, `goal_missed`, or `measurement_incomplete` without interpolation or stargazer identities; an actual result below the floor is `goal_missed` and requires continued iteration, while a missed or incomplete result does not retract the Release.

## Still pending after preview

- Complete retained 9+3 real host/vision acceptance.
- Additional named-client coverage beyond Codex and Claude Code.
- Additional publishable real-model routes beyond the bounded SDXL showcase.
- Measured image quality, latency, performance, and VRAM evidence.
