# Configurable Compute Budget Design

## Status

Approved interactively on 2026-07-21. This document specifies the design only; implementation and real acceptance continuation require a separate plan.

## Problem

The current workflow asks for only a one-to-three successful-round cap. Width, height, steps, and postprocessing permission exist elsewhere in the request, but the confirmation summary does not present them as one understandable compute commitment. A visually unsuccessful retained image consumes the same successful-round budget as an accepted image, and an exhausted run cannot receive an explicitly approved extension without starting another run.

This creates three product problems:

1. A normal user cannot choose between a fast draft and a more deliberate search without understanding diffusion parameters.
2. An advanced user cannot inspect and customize the complete compute boundary before generation.
3. A user-approved extension fragments evidence across runs instead of preserving an auditable history.

## Goals

- Offer user-facing `quick`, `balanced`, `quality`, and `custom` compute choices.
- Resolve every preset into exact values before the confirmation gate.
- Enforce successful-round and per-round step ceilings before backend invocation.
- Support explicit, append-only budget extensions within an unfinished run.
- Apply the same contract to root runs and immutable revision runs.
- Retain actual per-attempt elapsed time without presenting estimates as guarantees.
- Read historical manifests without rewriting them.

## Non-Goals

- Enforcing a wall-clock deadline or VRAM quota.
- Predicting image quality from steps or elapsed time.
- Automatically changing models, dimensions, or aspect ratios when a budget is exhausted.
- Automatically spending the full budget after an eligible result exists.
- Adding downloads, enabling an unavailable upscaler, or changing current model authority.

## Considered Approaches

### Fixed presets only

This is simple for new users but blocks exact control and makes the resolved compute boundary opaque. It is not selected.

### Presets with auditable overrides

This is the selected approach. Most users select a named preset. Advanced users can expand the same confirmation UI and override rounds, steps, dimensions, and postprocessing permission. The MCP boundary receives only resolved exact values.

### Dynamic time or VRAM quotas

Hardware, backend, model, resolution, warm-up state, and postprocessing make wall-clock and VRAM estimates unstable. Actual elapsed time will be recorded so a later release can build a local estimator, but time and VRAM are not v1.0 enforcement units.

## Presets

| Preset | Successful rounds | Maximum steps per round | Dimensions | Upscale default |
| --- | ---: | ---: | --- | --- |
| `quick` | 2 | 24 | Exact model/Profile recommendation resolved for the requested aspect ratio | `off` |
| `balanced` | 3 | 32 | Exact model/Profile recommendation resolved for the requested aspect ratio | `auto` permission |
| `quality` | 6 | 40 | Exact model/Profile recommendation resolved for the requested aspect ratio | `auto` permission |
| `custom` | 1-6 | 1-80 | 256-1536 per side, divisible by 8 | Explicitly selected |

`auto` remains permission to offer compatible postprocessing after final selection. It does not run an upscaler automatically and does not authorize installation or download.

The budget is a ceiling, not a target. The workflow stops early after an eligible result when further GPU use is unlikely to help. Backend failures do not consume successful rounds. Every retained generated PNG consumes one successful round regardless of visual quality.

## Confirmation Experience

The Skill first asks for a preset. The default is `balanced`. It asks only for missing high-impact creative boundaries and offers an expandable custom section. Before `local_gpu_start_run` or `local_gpu_branch_run`, it displays:

```text
Compute preset: balanced
Maximum successful rounds: 3
Maximum steps per round: 32
Exact dimensions: 768x432
Early stop: eligible result may stop the run before the ceiling
Postprocessing: compatible local upscale permitted after final selection; no download
Estimated time: unavailable, or a clearly labeled non-binding local observation
```

The existing post-display confirmation gate applies. A preset name alone does not authorize an unresolved model, dimensions, or postprocessing policy.

## Data Model

New run requests store a normalized object as the sole compute-budget authority:

```json
{
  "compute_budget": {
    "schema_version": 1,
    "preset": "balanced",
    "max_successful_rounds": 3,
    "max_steps_per_round": 32
  }
}
```

Allowed presets are `quick`, `balanced`, `quality`, and `custom`. Preset values must exactly match the table after resolution; any override changes the stored preset to `custom`.

Dimensions remain exact creative constraints under `constraints.width` and `constraints.height`. Postprocessing permission remains `upscale_policy`. This avoids conflicting copies of dimensions or authorization inside the budget object.

The generation plan repeats the normalized `compute_budget` and is checked against the effective confirmed budget. `parameters.steps` must not exceed `max_steps_per_round`. Round availability is checked against `max_successful_rounds` before an attempt lock or backend process is created.

Root and child manifests add an append-only `budget_amendments` array. The original request is never rewritten. The effective budget is the original budget followed by each valid amendment in order.

## Budget Extension Tool

The MCP surface adds a thirteenth tool, `local_gpu_extend_budget`.

Input fields:

```json
{
  "run_id": "...",
  "expected_manifest_revision": 12,
  "idempotency_key": "...",
  "new_max_successful_rounds": 5,
  "new_max_steps_per_round": 40,
  "reason": "User approved two more candidates after the prior budget was exhausted."
}
```

Both new maximum fields are required so the complete effective budget is visible and hashable. At least one must increase. Neither may decrease. The effective maximum remains six successful rounds and 80 steps per round.

The Skill must display the old and proposed budgets, the additional capacity, the unchanged dimensions/model/backend, and a non-binding cost note before requesting a new explicit confirmation. Only a confirmation received after that display authorizes the tool call.

A valid amendment records:

- amendment ID and idempotency key;
- previous and new effective budgets;
- concise user-facing reason;
- expected pre-amendment manifest revision;
- amendment timestamp.

Extensions apply only to future rounds. They cannot change prior attempt metadata, dimensions, model, backend, prompts, seed policy, or postprocessing authority. A dimension change requires a new confirmed run because it changes composition and artifact geometry.

## State and Concurrency Rules

- Reviewed, non-finalized root and child runs may be extended.
- Created or generated runs may be extended only when no attempt is active; the next review/generation transition remains unchanged.
- Active, finalized, cleaned, corrupt, or externally rooted runs reject extension.
- `expected_manifest_revision` must match under the run lock. A mismatch returns `stale_budget_confirmation` and makes no mutation.
- The same idempotency key and request hash returns the prior amendment. Reusing the key with different values returns the existing idempotency conflict.
- The amendment and manifest revision update are one atomic write under the existing run lock.

## Legacy Compatibility

Historical manifests that contain only `request.max_rounds` remain readable and are not rewritten. Their effective budget is interpreted as schema version 1 with preset `custom`, `max_successful_rounds` equal to the stored integer `request.max_rounds`, and `max_steps_per_round` equal to the historical engine ceiling of 80.

If a legacy run receives its first valid budget extension, the manifest retains the original `request.max_rounds` and appends `budget_amendments`. No migration edits past request or attempt data.

New v1.0 high-level run and branch calls require `compute_budget`. The direct compatibility generation tool remains unchanged. Public documentation will identify the v1.0 high-level contract change.

All round-number MCP schema ceilings, finalization checks, lineage checks, and file handling expand from three to six. Existing round filenames remain `round-01.png` through `round-06.png` with corresponding previews.

## Timing Evidence

The engine measures backend elapsed time with a monotonic clock. Completed and observed failed attempts retain elapsed duration. An interruption observed by the current process may retain a duration; a duration is never inferred across a process crash. Resumed attempts preserve prior timing evidence and record the resumed invocation separately. Successful rounds expose the total applicable duration in backend result metadata. Timing does not decide eligibility and is not a successful-round counter.

The Skill may display a time estimate only when the host already has comparable local observations for the same backend, model, dimensions, and similar steps. Otherwise it displays `estimate unavailable`. Estimates are advisory and never authorize an over-budget call.

## Errors

New or refined structured errors include:

- `invalid_compute_budget`: malformed, inconsistent, or out-of-range resolved budget;
- `round_budget_exhausted`: no confirmed successful-round capacity remains;
- `steps_budget_exceeded`: a generation plan exceeds the effective step ceiling;
- `budget_extension_not_increase`: neither ceiling increases or a value decreases;
- `budget_hard_limit`: an extension exceeds six rounds or 80 steps;
- `stale_budget_confirmation`: manifest revision changed after the amendment summary was shown;
- existing idempotency, busy, finalized, cleanup, and artifact errors where applicable.

Every validation error occurs before backend invocation and preserves manifest bytes and retained artifacts. Budget exhaustion never offers a destructive discard action. Recovery choices are to request an explicit extension, hand the current artifacts to the user as unaccepted review material, or confirm a new model/run boundary.

## Testing

### Skill contract

- Requires preset selection or an explicitly resolved default.
- Displays exact rounds, steps, dimensions, early-stop behavior, and postprocessing policy.
- Requires a new post-display confirmation for roots, revisions, and amendments.
- Never treats a preset name, silence, urgency, or sunk cost as amendment authority.
- Does not offer discard as the budget-exhaustion recovery action.

### Schema and engine tests

- Registers exactly thirteen tools with the new extension schema.
- Accepts all presets and legal custom boundaries.
- Rejects preset/value mismatches and out-of-range values.
- Rejects excessive steps and exhausted rounds before invoking the backend runner.
- Expands root, child, finalization, and lineage round handling through round six.
- Covers extension idempotency, conflict, stale revision, active attempt, finalized run, hard limit, atomicity, and crash recovery.
- Covers legacy reads and a first extension without rewriting legacy request data.
- Verifies actual elapsed time is non-negative and serialized without affecting eligibility.

### Workflow tests

- Fake-backend matrices cover quick, balanced, quality, and custom root/child runs.
- An eligible early round leaves unused budget intact.
- A visually ineligible retained round consumes budget.
- A backend failure retains failure evidence without consuming a successful round.
- A user-confirmed amendment allows only the newly authorized future work.

### Real acceptance

Existing failed wallpaper attempts remain immutable evidence in their run directories. After implementation, the approved extension mechanism may add bounded future rounds to the unfinished source run without altering prior failures. Only a run that later contains an eligible finalized round may be exported to the fixed brief package.

The release gate remains exactly nine accepted roots and three immutable accepted revisions with strict evidence validation. A larger compute budget never lowers rubric thresholds, removes hard failures, or converts `needs_user_review` into `accepted`.

## Documentation Impact

- Update the bundled Skill, README workflow, tool table, troubleshooting, and budget examples.
- Document the thirteenth tool and the v1.0 high-level request contract.
- Explain that steps and candidates improve search effort but cannot repair a model that lacks the required capability.
- Keep model downloads, remote publication, and unavailable postprocessor claims outside this feature.
