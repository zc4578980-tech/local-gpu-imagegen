# Preview Release Checklist

This checklist covers repository release readiness. It does not grant model, workflow-component, generated-output, client-configuration, publication, or public acceptance authority.

## Local gate

- [x] The final model-free suite, Python compilation, strict UTF-8 JSON parse, repository hygiene, and public-document truthfulness gates pass at one exact commit.
- [x] Fresh isolated Python 3.11 and 3.12 environments install the exact candidate wheel outside the checkout and verify version `0.7.0`, protocol `2024-11-05`, and exactly fifteen tools.
- [x] Installed `verify`, `doctor`, local-wheel `uvx`, and read-only Codex and Claude Code setup paths succeed without a source clone or direct configuration-file edit.
- [x] Tracked files, staged files, and wheel entries contain no credentials, personal paths, trust state, private runs, rejected images, model weights, or temporary client files.

## Evidence gate

- [ ] Retained Codex and Claude Code records validate as one `0.7.0` release set, with at least one genuine installed-wheel generation session.
- [x] One installed Codex session retains a genuine generation result bound to the exact ordinary-route run, round, and image hash; Claude Code generation evidence remains pending.
- [x] One ordinary-route SDXL root retains its original PNG and MCP result, passes full-resolution structured review, and is finalized by a later byte-bound user confirmation.
- [x] The ordinary-route public demo validates under `docs/demo/real/`, including public rights, exact artifact hashes, route identity, and sanitized client binding.
- [x] README evidence appears before the simulated protocol material and is derived from the validated manifest.
- [x] Regional and two-stage routes remain labeled experimental, outside the golden path and release blockers, with no visual-quality improvement claim.

## Publication gate

- [x] The genuine-image social preview is generated, validated at 1280x640, and visually reviewed without mutating remote metadata.
- [ ] Explicit authority is granted for each remote metadata change and publication action.
- [ ] README, changelog, package metadata, plugin metadata, `server.json`, GitHub copy, directory copy, and release notes agree on version, fifteen tools, three backends, the ordinary golden path, and open limitations.
- [ ] Windows and Ubuntu jobs on Python 3.11 and 3.12 are green at the exact release commit.
- [ ] The exact locally verified wheel is published without rebuilding and its public digest matches.
- [ ] The official MCP Registry record resolves version `0.7.0` to the exact PyPI package and stdio command.
- [ ] Tag `v0.7.0`, the preview release, package URL, Registry URL, and repository evidence URLs resolve to the exact verified release state.
- [ ] Directory submissions remain unsubmitted until each receives separate authority.

## Post-release adoption measurement

- [ ] At formal GitHub Release publication time, initialize the append-only campaign baseline under `docs/evidence/adoption/<campaign_id>/` within five minutes when possible.
- [ ] During the inclusive 24-hour T+30 collection window, append the repository-level Star total and validate the complete hash chain.
- [ ] Measure the goal as T+30 total Stars minus baseline total Stars, targeting `100 net-new GitHub Stars` without interpolation or stargazer identities.
- [ ] Record `goal_met`, `goal_missed`, or `measurement_incomplete`; a missed or incomplete adoption goal triggers review and iteration but does not retract the Release.

## Still pending after preview

- Complete retained 9+3 real host/vision acceptance.
- Additional named-client coverage beyond Codex and Claude Code.
- Additional publishable real-model routes beyond the bounded SDXL showcase.
- Measured image quality, latency, performance, and VRAM evidence.
