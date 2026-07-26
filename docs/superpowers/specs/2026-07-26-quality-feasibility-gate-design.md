# One-Day Quality Feasibility Gate

**Date:** 2026-07-26
**Branch:** `codex/v081-quality-feasibility-gate`
**Status:** Design awaiting written-spec review

## Objective

Decide within one bounded local-GPU trial whether Local GPU Imagegen can launch
as an Agent-native runner for an already-mature ComfyUI model and workflow. The
trial must produce three publishable-quality raster assets before any further
product, architecture, onboarding, release, or promotion work is authorized.

This gate does not claim that Local GPU Imagegen improves image quality. Model
and image quality come from an already-installed model and mature workflow. The
project must prove only that it can preserve that quality while providing an
Agent-facing local execution path.

## Product Decision Under Test

If the gate passes, the launch position becomes:

> Run proven local ComfyUI workflows from Codex or Claude Code to create useful
> visual assets with local compute. Explicit routing, privacy, recovery, and
> auditability remain supporting infrastructure rather than the headline.

If the gate fails, stop the quality and 100-Star launch direction. Do not add a
quality engine, more evidence machinery, architecture work, onboarding work, or
release polish to compensate for weak images. Preserve or archive the project
as an engineering prototype after a separate decision.

## Frozen Scope

The gate has exactly three cases:

1. An original adult anime character key visual with no franchise, artist,
   logo, text, or watermark reference.
2. A text-free wide hero raster for a concrete frontend product, with one
   usable overlay-safe area and robust desktop/mobile cropping.
3. A text-free 16:9 presentation cover raster with usable title space and no
   baked labels, charts, logos, or UI.

The gate excludes fan art, the historical lighthouse, regional composition,
two-stage composition, postprocessing development, frontend implementation,
slide implementation, release copy, package publication, and remote changes.

## Route Qualification

Before GPU submission, inspect the already-installed local ComfyUI inventory
and identify one mature route for each case. A route qualifies only when:

- all model weights, VAEs, text encoders, LoRAs, custom nodes, and workflow
  files already exist locally;
- the route can be understood and invoked without changing trust or client
  state;
- the endpoint is loopback-only;
- the workflow does not execute shell, Python, download, fetch, webhook, or
  arbitrary process nodes;
- the model and workflow identity remain fixed for all candidates in that
  case; and
- its license and output-use boundary are sufficient for a local trial.

Use only an existing reviewed project route that is already executable without
registration, trust mutation, or a new topology. Safe workflow onboarding may
inspect an explicit local API-format workflow for diagnostics, but this gate
cannot register or trust it. If no qualifying mature route already exists, stop
before GPU work and report `NO_QUALIFYING_ROUTE`.

## Generation Budget

The hard ceiling is twelve successful or attempted GPU submissions:

| Case | Maximum submissions | Candidate policy |
|---|---:|---|
| Anime character | 4 | One frozen prompt/settings set, deterministic seed set |
| Frontend hero | 4 | One frozen prompt/settings set, deterministic seed set |
| Presentation cover | 4 | One frozen prompt/settings set, deterministic seed set |

Each case uses one model, workflow, positive prompt, negative prompt behavior,
dimensions, sampler, scheduler, steps, and guidance setting. Only the seed may
vary between candidates. There is no adaptive prompt rewriting, parameter
tuning after seeing results, image-to-image repair, external editor, online
generator, or hidden extra candidate.

Stop early when:

- a case has one clearly publishable candidate and further sampling would only
  polish it;
- the first six total submissions contain no publishable candidate;
- two consecutive backend or route-identity failures occur; or
- any download, installation, trust mutation, client mutation, or unsafe node
  becomes necessary.

## Review Contract

Every retained candidate receives an opaque label rather than a route or seed
name during user review. Review the original full-resolution bytes, not only a
thumbnail. The user remains the final visual authority.

Each case is scored from 1 to 5 on:

- immediate visual appeal;
- composition and hierarchy;
- subject/detail coherence;
- absence of obvious generation defects;
- fitness for the intended asset slot; and
- readiness to show publicly without explanatory excuses.

A case passes only when one candidate:

- receives at least 4 on every dimension;
- has no severe anatomy, malformed object, baked text, watermark, unusable safe
  area, or obvious workflow artifact;
- needs no pixel editing or prompt-based justification to appear acceptable;
  and
- is explicitly accepted by the user as publishable.

The gate passes only when all three cases pass. A two-of-three result is a gate
failure, because the proposed launch position explicitly promises all three
practical asset categories.

## Evidence and Output Boundary

Local working artifacts live under
`outputs/quality-feasibility-gate/2026-07-26/` and remain ignored. Retain for
each submission:

- opaque review label;
- case ID and candidate number;
- exact model and workflow identity;
- prompt and negative-prompt behavior;
- seed, dimensions, sampler, scheduler, steps, and guidance;
- submission/result status;
- image path, dimensions, byte count, and SHA-256; and
- structured review with the final accept/reject decision.

Create one local contact sheet per case only after all retained candidates for
that case are fixed. The contact sheet may scale images for comparison but is
not authoritative evidence. Do not commit generated images or claim public
evidence during this gate.

## Engineering and Cost Boundary

- Production-code additions: zero lines.
- Test additions: zero unless a pre-GPU safety defect blocks execution; any
  such defect ends the gate and returns to design rather than being fixed here.
- Tracked changes: this design, its execution plan, and a final factual report
  only.
- GPU ceiling: twelve submissions and one working day.
- Model, dependency, custom-node, or workflow downloads: forbidden.
- New model training, LoRA training, postprocessor work, or quality-scoring
  dependency: forbidden.
- Remote push, tag, Release, PyPI, Registry, repository metadata, or campaign
  action: forbidden without later explicit authority.
- The regional and two-stage workflow files remain frozen and must retain zero
  working-tree and staged diff.

No remaining allowance may be spent merely because it exists. A failed gate
does not authorize a second gate with different rules.

## Execution Flow

1. Verify the branch, worktree, repository status, and frozen workflow diffs.
2. Inspect local backend/process state without starting or mutating anything.
3. Qualify exact already-installed routes and freeze one route per case.
4. Freeze all three briefs, prompts, settings, and deterministic seed sets
   before the first GPU submission.
5. Start one hidden loopback ComfyUI process only when no compatible process is
   already running and record ownership before use.
6. Execute cases sequentially and retain every submission outcome.
7. Build opaque-label contact sheets and review full-resolution candidates.
8. Apply the all-three pass rule without changing prompts, settings, rubric, or
   budget.
9. Stop only the backend process started and still owned by this task.
10. Run repository verification and write a factual pass/fail report.

## Failure Handling

- Missing route: stop with `NO_QUALIFYING_ROUTE` before generation.
- Weak output: retain it, mark the case failed, and do not tune around it.
- Baked text or severe defect: reject the candidate; seed variation may
  continue only within the original four-candidate case budget.
- Backend error: retain the exact error and count the submission against the
  ceiling.
- Identity drift: stop the case without substituting another route.
- User rejection: the case fails even when mechanical checks pass.
- Ambiguous result: fail closed. Publishable quality must be obvious enough not
  to require a favorable interpretation.

## Verification and Decision

The final report must state:

- exact submitted, successful, failed, accepted, and rejected counts;
- the selected SHA-256 for each passing case;
- route and settings used for every candidate;
- whether each stop condition remained respected;
- whether frozen workflow diffs remained zero;
- whether any code, dependency, model, trust/client state, or remote state
  changed; and
- the single decision `PASS_CONTINUE` or `FAIL_STOP`.

`PASS_CONTINUE` authorizes only a separately designed, maximum four-day launch
cut covering narrow Agent execution, first-run simplification, release
coherence, and launch materials. It does not authorize a quality engine.

`FAIL_STOP` ends this launch direction. There is no automatic follow-up phase.
