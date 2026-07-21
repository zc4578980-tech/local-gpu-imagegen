# User-Bound Visual Acceptance Design

## Problem

The current review boundary trusts Agent-supplied rubric scores and hard-failure lists. `local_gpu_finalize_run` then needs only a run ID, round number, and summary. An Agent can therefore overlook an obvious artifact, score the image above threshold, and publish it as `accepted` without proving that the original image was shown to the user.

Run `20260721T154550Z-5ecc084d8053` reproduced the failure: a visually polished character image had fused lower legs, boots, feet, hands, and a held device, but the Agent over-weighted composition and marked it accepted. The generation backend behaved as requested; the missing boundary was review and finalization authority.

## Goals

- Make full-resolution visual integrity checks structured and mandatory.
- Prevent failed or uncertain anatomy from becoming a finalization candidate.
- Bind finalization authority to one run, round, and retained image SHA-256.
- Require a user message after the exact candidate image and boundary are displayed.
- Preserve the confirmed successful-round budget inside the same run after a rejected candidate.
- Keep the MCP surface at exactly fifteen tools and require no model, package, or workflow download.

## Non-Goals

- Automatic anatomy detection or a second vision model.
- Claiming that structured checks make subjective visual review infallible.
- Retrofitting or rewriting finalized manifests and legacy evidence.
- Resetting a run budget after an Agent review mistake.

## Structured Visual Checks

`local_gpu_record_review` gains a required `visual_checks` object:

```json
{
  "full_resolution_inspected": true,
  "prominent_human": true,
  "limb_separation": {"status": "pass", "observation": "Two independent leg and arm silhouettes are visible."},
  "feet_and_contact": {"status": "pass", "observation": "Both feet and their contact points are anatomically readable."},
  "hands_and_held_objects": {"status": "pass", "observation": "Hands remain distinct from each other and from the held object."},
  "text_and_watermarks": {"status": "pass", "observation": "No text, logo, signature, or watermark is visible."}
}
```

Allowed statuses are `pass`, `fail`, `uncertain`, and `not_applicable`. Every observation must be concise and non-empty.

Validation rules:

- `full_resolution_inspected` must be exactly `true` for a vision review.
- When `prominent_human` is true, the three anatomy checks cannot be `not_applicable`.
- When `prominent_human` is false, the three anatomy checks must be `not_applicable` with an observation explaining why.
- `text_and_watermarks` cannot be `not_applicable`.
- Any required `fail` or `uncertain` check makes the round ineligible and rejects `next_action: finalize` before manifest mutation.
- Eligibility and final quality status evaluate the stored visual checks independently of Agent-supplied scores and `hard_failures`; omitting a failure code cannot bypass the gate.

This is a review contract, not an automated detector. It forces the Agent to make the overlooked regions explicit and makes an uncertain result fail closed.

## Finalization Candidate

An eligible review with `next_action: finalize` produces a derived candidate boundary:

```text
finalize:<run_id>:<round_number>:<full image sha256>
```

The confirmation is derived from retained manifest data, not stored as mutable authority. Review and recovery responses expose a `finalization_candidate` containing:

- `run_id`
- `round_number`
- `image_sha256`
- `confirmation`
- `quality_status: candidate`

`candidate` is the strongest status an Agent may claim before the user responds. It is not public acceptance evidence.

## User Confirmation Gate

The required temporal flow is:

```text
generate round
-> display the original/full-resolution image
-> record structured review and visual checks
-> display candidate, limitations, image SHA-256, and exact finalization boundary
-> stop
-> receive a later user message approving that displayed image
-> call local_gpu_finalize_run with the exact confirmation
```

Early route approval, generation approval, silence, the Agent's own judgment, and a previous image approval do not authorize finalization.

`local_gpu_finalize_run` gains required `confirmation`. Before copying or publishing any artifact, the engine derives the expected value from the selected reviewed round and compares it exactly. Missing, stale, wrong-round, or wrong-image confirmation fails with `finalization_confirmation_mismatch` and leaves the manifest and files unchanged.

The MCP server cannot cryptographically prove that a human authored a chat message. Defense therefore has two layers: the engine binds authority to exact retained bytes, while the Skill contract and tests require a later user turn after display.

## Budget And Recovery

A failed visual check leaves the run in `reviewed`. If the confirmed successful-round budget remains, recovery actions offer only the allowed refine/explore generation paths. The Agent must not create a replacement run to reset the budget.

An eligible candidate remains recoverable after process restart because its confirmation is deterministically derived from the manifest. If image bytes, round identity, or review eligibility change, the old confirmation no longer matches.

## Compatibility

- MCP still exposes exactly fifteen tools.
- The pre-release input contract intentionally becomes stricter: new reviews require `visual_checks`, and new finalization calls require `confirmation`.
- Existing finalized manifests remain readable but are not rewritten.
- Existing unfinalized reviews without structured visual checks cannot produce a new accepted final through this boundary.
- Public evidence export continues to require current route authority and an accepted finalized result.

## Testing

Focused tests will prove:

1. MCP schemas require exact structured visual checks and finalization confirmation.
2. Missing, malformed, inconsistent, failed, or uncertain checks fail before manifest mutation.
3. Non-human images require explicit anatomy `not_applicable` observations.
4. Eligible reviews return a byte-bound `candidate`, not `accepted`.
5. Wrong run, round, image hash, or confirmation cannot publish a final artifact.
6. A failed character review retains the remaining round budget and offers refine/explore, not finalize.
7. The Skill waits for a later user message after displaying the exact candidate.
8. Existing route, evidence, recovery, and fifteen-tool contracts remain intact.

The final gate remains the full model-free suite, Python compilation, exact MCP verification, and a focused regression that reproduces fused-anatomy rejection without invoking a GPU.
