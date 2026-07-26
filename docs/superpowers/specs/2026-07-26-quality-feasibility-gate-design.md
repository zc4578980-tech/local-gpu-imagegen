# One-Day Quality Feasibility Gate

**Date:** 2026-07-26
**Branch:** `codex/v081-quality-feasibility-gate`
**Status:** Approved; amended to require a true raw-ComfyUI no-regression gate

## Objective

Decide within one bounded local-GPU trial whether the complete Local GPU
Imagegen workflow degrades image quality relative to competent raw ComfyUI
generation under the same model and GPU budget. Anime, frontend-hero, and
presentation-cover cases each receive two paired seeds and a blinded review.

Model quality and workflow regression are separate outcomes. Weak results in
both lanes are recorded as `MODEL_QUALITY_LIMIT`; they cannot excuse a workflow
lane that is worse than its raw baseline. A later model recommendation or
download flow may be designed only after this no-regression question is
answered, and still requires separate approval.

## Product Decision Under Test

If the workflow adds value without regression, the launch position may become:

> Run proven local ComfyUI workflows from Codex or Claude Code to create useful
> visual assets with local compute. Explicit routing, privacy, recovery, and
> auditability remain supporting infrastructure rather than the headline.

If the workflow regresses against raw ComfyUI, stop the quality and 100-Star
launch direction. Do not add a quality engine, more evidence machinery,
architecture work, onboarding work, or release polish to compensate. Preserve,
remove, or redesign the regressing workflow only after a separate decision.

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

| Case | Raw baseline | Project workflow | Total |
|---|---:|---:|---:|
| Anime character | 2 seeds | Same 2 seeds | 4 |
| Frontend hero | 2 seeds | Same 2 seeds | 4 |
| Presentation cover | 2 seeds | Same 2 seeds | 4 |

Each case uses one model, dimensions, sampler, scheduler, steps, and guidance
setting across both lanes. The same two deterministic seeds are paired across
the lanes. The raw lane bypasses this project's MCP, engine, prompt compiler,
and run workflow and submits a reviewed ordinary API graph directly to local
ComfyUI. Its competent one-shot prompt is frozen from the common brief. The
project lane consumes the same brief through the current project path, including
its current compiler and reviewed workflow. Both effective prompts and graphs
are frozen before the first output is seen.

The comparison therefore measures the complete value or harm introduced by the
project workflow rather than isolating one graph node. There is no adaptive
prompt rewriting, parameter tuning after seeing results, image-to-image repair,
external editor, online generator, or hidden extra candidate.

Stop early when:

- two consecutive backend or route-identity failures occur; or
- any download, installation, trust mutation, client mutation, or unsafe node
  becomes necessary.

Do not stop a healthy case after one attractive image: both paired seeds in
both lanes are required to assess regression. A global stop may occur before
twelve submissions only for a route, safety, identity, or backend stop
condition.

## Review Contract

Every retained candidate receives a randomized opaque label rather than a lane,
route, or seed name during user review. Lane assignment remains concealed until
all scores and pair preferences are frozen. Review the original full-resolution
bytes, not only a thumbnail. The user remains the final visual authority.

Each case is scored from 1 to 5 on:

- immediate visual appeal;
- composition and hierarchy;
- subject/detail coherence;
- absence of obvious generation defects;
- fitness for the intended asset slot; and
- readiness to show publicly without explanatory excuses.

For each lane, select its best candidate by total rubric score, breaking a tie
by the user's frozen pair preference. The workflow regresses a case when its
best candidate scores at least two points below the best raw candidate, or when
it introduces a severe anatomy error, malformed object, baked text, watermark,
unusable safe area, or obvious workflow artifact absent from the paired raw
candidate. A difference of zero or one total point is a tie.

Publishable quality is reported separately. A candidate is publishable only
when it receives at least 4 on every dimension, has no hard defect, needs no
pixel editing or explanatory excuse, and is explicitly accepted by the user.
When neither lane has a publishable candidate, record `MODEL_QUALITY_LIMIT` for
that case. When raw is publishable but workflow is not, the case is a workflow
regression regardless of aggregate score.

The final workflow outcome is:

- `PASS_WORKFLOW_VALUE`: no case regresses and the workflow wins by at least two
  points in one or more cases;
- `PASS_NO_REGRESSION`: no case regresses, but the workflow proves no visible
  quality gain; or
- `FAIL_WORKFLOW_REGRESSION`: one or more cases regress.

All three cases must avoid regression. A two-of-three result is a failure.

## Evidence and Output Boundary

Local working artifacts live under
`outputs/quality-feasibility-gate/2026-07-26/` and remain ignored. Retain for
each submission:

- opaque review label and concealed lane assignment;
- case ID and candidate number;
- exact model and workflow identity;
- common brief, lane-specific effective prompt, and negative-prompt behavior;
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
4. Freeze all three briefs, raw prompts, project effective prompts, graphs,
   settings, paired execution order, and deterministic seed sets before the
   first GPU submission.
5. Start one hidden loopback ComfyUI process only when no compatible process is
   already running and record ownership before use.
6. Execute the raw and project lanes in the frozen paired order and retain every
   submission outcome.
7. Build randomized opaque-label contact sheets and review full-resolution
   candidates without revealing lane assignment.
8. Freeze scores and preferences, reveal lanes, then apply the no-regression
   rule without changing prompts, settings, rubric, or budget.
9. Stop only the backend process started and still owned by this task.
10. Run repository verification and write a factual pass/fail report.

## Failure Handling

- Missing route: stop with `NO_QUALIFYING_ROUTE` before generation.
- Weak output in both lanes: retain it as `MODEL_QUALITY_LIMIT`; do not tune
  around it or misclassify it as workflow regression.
- Baked text or severe defect: reject the candidate; seed variation may
  continue only within the original four-candidate case budget.
- Backend error: retain the exact error and count the submission against the
  ceiling.
- Identity drift: stop the case without substituting another route.
- User rejection: the candidate is not publishable even when mechanical checks
  pass; lane regression is still computed from the frozen blinded scores.
- Ambiguous result: fail closed. Publishable quality must be obvious enough not
  to require a favorable interpretation.

## Verification and Decision

The final report must state:

- exact submitted, successful, failed, publishable, and rejected counts by lane;
- the selected raw and workflow SHA-256 for each case;
- route, graph, effective prompt, and settings used for every candidate;
- all blinded scores, pair preferences, and the lane reveal;
- the per-case regression result and any `MODEL_QUALITY_LIMIT` result;
- whether each stop condition remained respected;
- whether frozen workflow diffs remained zero;
- whether any code, dependency, model, trust/client state, or remote state
  changed; and
- the single workflow decision `PASS_WORKFLOW_VALUE`, `PASS_NO_REGRESSION`, or
  `FAIL_WORKFLOW_REGRESSION`.

`PASS_WORKFLOW_VALUE` authorizes only a separately designed, maximum four-day
launch cut covering narrow Agent execution, first-run simplification, release
coherence, and launch materials. It does not authorize a quality engine.

`PASS_NO_REGRESSION` authorizes only a decision about model recommendation and
onboarding. It does not support an image-quality-improvement claim or authorize
image engineering.

`FAIL_WORKFLOW_REGRESSION` ends this launch direction. There is no automatic
follow-up phase.
