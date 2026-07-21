---
name: local-gpu-imagegen
description: Use when a user asks to create, generate, draw, render, transform, restyle, or revise a visual asset on the local GPU.
---

# Local GPU Visual Asset Workflow

## Core Rule

Brief first, confirm once, then run a bounded generate-review loop. Never substitute guesses for missing high-impact intent or visual evidence.

The plugin exposes exactly nine MCP tools: `local_gpu_imagegen_check`, `local_gpu_generate_image`, `local_gpu_list_profiles`, `local_gpu_start_run`, `local_gpu_get_run`, `local_gpu_generate_round`, `local_gpu_record_review`, `local_gpu_finalize_run`, and `local_gpu_cleanup_run`. Use the seven high-level profile/run tools for adaptive runs. The check and direct-generation tools are compatibility tools, not shortcuts around briefing and confirmation.

## Adaptive Brief

1. Call `local_gpu_list_profiles` before proposing a run. Select a Profile, optional style, compatible backend, and an approved non-empty `model_choice` from its returned catalog. The model must be registered, enabled, and license-approved. If none exists, state a clear unavailable-model boundary and stop. Do not invent a model ID, enable a candidate, download a model, or call `local_gpu_start_run`.
2. Extract known values first. Ask only for missing high-impact boundaries:
   - intended use/subtype;
   - subject/outcome;
   - style/composition;
   - dimensions/aspect ratio/safe area;
   - required/prohibited content;
   - round budget of 1 to 3 successful rounds;
   - permission for seed/model switching and compatible upscaling.
3. Do not ask the user to repeat or reconfirm known values. A stated cap selects that maximum as `max_rounds`. Do not start after one conversational turn when any high-impact boundary remains missing.
4. Present a concise summary covering Profile/style/model choice, dimensions/safe area, preserve/prohibit constraints, the selected 1 to 3 successful rounds, and backend/download/upscale policy:

```text
Profile/style/model choice: ...
Intent and composition: ...
Dimensions/safe area: ...
Preserve/prohibit constraints: ...
Budget: 1 to 3 successful rounds (selected: ...)
Backend/download/upscale policy: ...
Seed/model switching: ...
```

5. Confirmation must cover the resolved complete summary, including the exact `model_choice`. Generic wording such as "the approved local model and start" does not pre-authorize any concrete model ID: show the resolved ID and ask for confirmation without repeating known creative requirements. An explicit `use defaults and start` is immediate-default confirmation only when the catalog has exactly one compatible approved model and every other missing field has a safe displayed default. A safe default must be advertised by the selected catalog Profile or model and must not conflict with user constraints. Present that resolved summary, then start without re-asking. Do not call `local_gpu_start_run` before confirmation of the complete summary.

## Run Sequence

Follow this order exactly:

```text
`local_gpu_list_profiles` -> brief -> confirm -> `local_gpu_start_run`
-> `local_gpu_generate_round(action=initial)` -> inspect preview
-> `local_gpu_record_review` -> `local_gpu_generate_round(action=refine|explore)`
-> inspect preview -> `local_gpu_record_review` -> `local_gpu_finalize_run`
```

The second generation/review pair is conditional: repeat it only while the confirmed budget remains and improvement is worthwhile. `local_gpu_get_run` is for recovery or state checks. Use `local_gpu_cleanup_run` only for the scope the user authorized; deleting a whole run requires the tool's exact confirmation. Do not bypass the adaptive run with `local_gpu_generate_image`.

For each generation, use a unique idempotency key and a plan bound to the confirmed summary. The first action is `initial`. After each review:

- **Refine: preserve the seed.** Keep the accepted structure and make targeted parameter/prompt improvements.
- **Explore: change the seed.** Search a materially different composition or interpretation within the confirmed constraints.
- Put concise intent in `change_summary`: `Preserve: <what stays>. Change: <what changes>.`
- Never exceed the confirmed successful-round budget. Failed attempts do not consume a successful round, but time pressure, sunk cost, an offline user, or a likely improvement never authorizes another successful round.
- A retained image consumes one successful round regardless of visual quality. Do not relabel it as a failed attempt to evade the budget.
- Eligible means no hard failures and every critical rubric score is at least 3. Stop early when an eligible reviewed result exists and further GPU use is unlikely to help.

## Review Evidence

On a vision-capable host, inspect the actual returned preview or accessible full image. Record the complete returned rubric with evidence-based 1-to-5 scores, hard failures, explicit-constraint results, a concise critique, and the next action. Do not store chain-of-thought; store only conclusions, observed evidence, and the concise preserve/change intent.

On a text-only host, generate exactly one successful round per confirmed run. Mark `review unavailable`, stop after the first retained round, and report its path as unreviewed; any remaining round budget stays unused until a human or vision-capable host can review. Do not fabricate scores, constraint results, defects, or visual critique. Because `local_gpu_record_review` requires visual scores, do not call it or `local_gpu_finalize_run` without that evidence. Do not claim the result is accepted, polished, or visually verified.

For a vision-reviewed eligible result, finalize the nominated reviewed round and report the final absolute path and actual quality status. An ineligible budget-exhausted result may be finalized only with its `needs_user_review` limitation stated; never relabel it accepted.

## Hard Boundaries

- No hidden downloads. Do not enable downloads or suggest that a remote-looking model ID is locally available. Report unavailable dependencies/models and stop.
- Do not silently fall back to CPU or switch the confirmed model/backend policy.
- `upscale_policy: auto` records permission only; it does not prove a compatible upscaler is installed or that upscaling occurred.
- Do not promise masks, child revisions, or hot revision tools. Record only current-run refine/explore intent; those revision features are outside this workflow.
- A preview path is not visual evidence. One-turn urgency is not confirmation. A nearly-good last round is not authority to exceed the budget.
- Do not describe Codex or any other host as verified, and do not claim real image acceptance without retained acceptance evidence.
