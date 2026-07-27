---
name: local-gpu-imagegen
description: Use when a user asks to create, generate, draw, render, transform, restyle, or revise a visual asset on the local GPU.
---

# Local GPU Visual Asset Workflow

## Core Rule

Brief first, resolve one exact local route, confirm after displaying it, then run a bounded generate-review loop. Never substitute guesses for missing high-impact intent, model identity, or visual evidence.

The plugin exposes exactly seventeen MCP tools: `local_gpu_imagegen_check`, `local_gpu_generate_image`, `local_gpu_discover_models`, `local_gpu_inspect_workflow`, `local_gpu_register_workflow`, `local_gpu_list_profiles`, `local_gpu_set_model_trust`, `local_gpu_recommend_models`, `local_gpu_start_run`, `local_gpu_get_run`, `local_gpu_branch_run`, `local_gpu_prepare_mask`, `local_gpu_confirm_mask`, `local_gpu_generate_round`, `local_gpu_record_review`, `local_gpu_finalize_run`, and `local_gpu_cleanup_run`. Use the fifteen high-level discovery/onboarding/profile/run/revision tools for adaptive runs. The check and direct-generation tools are compatibility tools, not shortcuts around briefing, route resolution, and confirmation.

## Codex-First Workflow Runner

Use this golden path when the user supplies one existing supported ComfyUI API
workflow and asks Codex to run it. The user sees exactly two user decisions:
one preparation decision and one execution decision. Internal confirmation
tokens are copied by the Agent only after the matching proposal has been
displayed and approved in a later user message.

Before the preparation decision, call `local_gpu_discover_models` in
`api_only` mode when inventory is absent, call
`local_gpu_inspect_workflow`, then call `local_gpu_set_model_trust` with
`action` set to `inspect_workflow_binding`, the raw `workflow_path`, the exact inferred
binding and component identities, and one capability object. These calls are
read-only. Build `capabilities.recommended` only from `workflow_defaults`: map
`width` and `height` into `recommended.resolution`, `steps` unchanged,
`guidance_scale` to `recommended.guidance`, `sampler_name` to `recommended.sampler`,
and `scheduler` unchanged. Use the same `capabilities`
object for later `approve_private`. Never substitute Profile or repository
defaults.

The nine exact defaults are `positive_prompt`, `negative_prompt`, `width`,
`height`, `seed`, `steps`, `guidance_scale`, `sampler_name`, and `scheduler`.
The Agent must display one preparation proposal containing the source and
workflow hash prefixes, topology, owned output, endpoint, all component
identities, all nine workflow defaults, requested prompt overrides,
limitations, both exact confirmations, and the statement that no model, node,
or runtime download will occur. Then stop and wait for a later user message. A
natural-language approval permits `local_gpu_register_workflow` with the
stored registration confirmation and then `local_gpu_set_model_trust` with
`action` set to `approve_private`, the registered workflow ID, the same component
identities, the same `capabilities` object, and the stored trust confirmation.

Registration and trust approval are sequential. If registration succeeds and
trust approval fails, report the immutable copy as an inert registration and
stop. Do not delete it, weaken identity, repeat approval, recommend a route, or
start a run.

After successful private trust, call `local_gpu_recommend_models` for the exact
imported route. The Agent must display one execution route containing the
endpoint, registered workflow, model identity, positive and negative prompts,
width, height, seed, steps, guidance, sampler, scheduler, and every field that
differs from `workflow_defaults`. State `max_rounds: 1`, `upscale_policy: off`,
no automatic retry, no model switch, no CPU fallback, no workflow fallback,
and no download. Ensure that only fields explicitly overridden by the user may differ
from the inspected defaults. A changed or expired route must be
displayed again. Then stop and wait for a later user message.

After approval, call `local_gpu_start_run`, immediately call
`local_gpu_get_run`, construct the existing complete frozen generation plan,
and call `local_gpu_generate_round` once with `action: initial`. A backend
failure remains attached to the recoverable run ID and never triggers an
automatic retry or fallback. On success, return the original image, actual
workflow/model/parameter summary, durable `run_id`, and evidence location
labeled `generated / unreviewed`. Review and finalization are optional
follow-up work; they do not block the first result.

## Adaptive Brief

1. Extract known values first.
2. Call `local_gpu_discover_models` with `api_only` when current backend inventory is unknown. A broader `selected_folders`, `common_locations`, or `full_drive` scan must first return and display an unchanged plan, then receive its exact scan confirmation. Discovery indexes metadata without loading weights; run `fingerprint` only for explicitly selected candidates. Never infer trust from discovery.
3. If a discovered identity needs trust, display its exact backend, endpoint class, backend-visible model name, identity strength, capabilities, scope, and workflow binding before calling `local_gpu_set_model_trust`. For a split ComfyUI workflow, fingerprint every selected primary model, text encoder, and VAE, then call the same tool with `inspect_workflow_binding`. Display the returned component roles, names, byte sizes, SHA-256 values, reviewed workflow SHA-256, bundle SHA-256, and exact confirmation before any mutating call. Inspection never writes trust. A `backend_binding` identity is `private` only. `public_evidence` requires a complete cryptographic bundle plus exact source, license, and redistribution metadata for every component; this candidate status still does not replace acceptance authority. Receive a new exact trust confirmation after displaying those facts.

When a fresh MCP process must recover a previously confirmed cryptographic public candidate, follow this exact order:

1. Plan `selected_folders/index` for one already confirmed model root and the exact `explicit_includes` path. Do not scan unrelated roots.
2. Display the unchanged plan, scope, expiration, and `cost_warning`. State the estimated local file I/O and hashing cost: indexing reads bounded metadata, while the later fingerprint reads every byte of the selected file. Wait for the exact scan confirmation, then execute that unchanged index plan.
3. Select exactly one expected candidate. Verify its filename and byte size against the previously confirmed checkpoint; stop on zero, multiple, or mismatched candidates.
4. Plan `selected_folders/fingerprint` with `selected_candidates` containing only that candidate. Display its full-file read cost and the new exact confirmation, wait for that confirmation, then execute the unchanged fingerprint plan.
5. Verify the returned filesystem identity token, full SHA-256, and byte size against the expected public candidate.
6. Run `api_only/index` for ComfyUI so the current backend-visible loader binding is present in the same process.
7. Call `local_gpu_recommend_models` and verify the exact `public_evidence` route matches the expected model, endpoint, cryptographic identity, workflow, bundle when applicable, and compiler before displaying it for confirmation.

Never downgrade this recovery to `backend_binding` or `private` identity. Do not recommend until both filesystem and API identities are present. A mismatch requires a new bounded discovery decision, not a broader scan or a weaker route.

4. Call `local_gpu_list_profiles` with the intended `private` or `public_evidence` scope before proposing a run. Select a Profile, optional style, compatible backend, and an approved non-empty `model_choice` from its merged catalog. The model must be registered, enabled, and license-approved. If none exists, state a clear unavailable-model boundary and stop. Do not invent a model ID, enable a candidate, download a model, or call `local_gpu_start_run`.
5. Ask only for missing high-impact boundaries:
   - intended use/subtype;
   - subject/outcome;
   - style/composition;
   - dimensions/aspect ratio/safe area;
   - required/prohibited content;
   - round budget of 1 to 3 successful rounds;
   - permission for seed/model switching and compatible upscaling.
   For every `ui-visual-asset` hero, freeze a required `semantic_fidelity`
   constraint before writing the generation prompt. It must name the requested medium,
   one or more required visual anchors, and one or more forbidden substitutions.
   A software-product hero might require a blank or deliberately defocused device
   area for later real-UI compositing and forbid a paper-only workspace.
   Do not call `local_gpu_start_run` until this contract is complete.
6. Do not ask the user to repeat or reconfirm known values. A stated cap selects that maximum as `max_rounds`. Do not start after one conversational turn when any high-impact boundary remains missing. A safe default must be advertised by the selected catalog Profile or model and must not conflict with user constraints.
7. Call `local_gpu_recommend_models` with the resolved operation, Profile, style, dimensions, affinity, VRAM boundary, and optional preferred model. Accept one exact route and at most two alternatives. Never weaken a hard requirement to obtain a result.
8. Present a concise resolved summary and display the exact route: Profile/style/model ID, backend, identity strength, SHA-256 prefix or `backend_binding` warning, workflow/template version, prompt compiler/version, dimensions/safe area, preserve/prohibit constraints, selected 1 to 3 successful rounds, and download/upscale policy:

```text
Profile/style/model choice: ...
Route: backend / identity / hash-or-binding / workflow / compiler
Intent and composition: ...
Dimensions/safe area: ...
Preserve/prohibit constraints: ...
Budget: 1 to 3 successful rounds (selected: ...)
backend/download/upscale policy: ...
Seed/model switching: ...
```

## Workflow Onboarding

When the user supplies one existing ComfyUI workflow, call `local_gpu_inspect_workflow` with only its explicit local path. The tool does not start ComfyUI and does not run discovery implicitly. If it returns `diagnostic`, display the inferred topology/binding, limitations, and recovery action; there is no confirmation and registration must stop.

For a registerable result, display the source SHA-256, workflow SHA-256, topology, complete inferred binding, owned output, component identities, limitations, and exact `register_workflow:<source_sha256>:<proposal_digest>`. Explain that registration does not grant trust or public authority, then stop and wait for a later user message containing that exact confirmation.

Only after that later message, call `local_gpu_register_workflow` with the same path, proposal digest, and exact confirmation. Then use the returned `registered_workflow_id` in the existing `local_gpu_set_model_trust` flow with fresh exact component identities. UI format is not converted: direct the user to enable ComfyUI developer mode and export API format. Never select node IDs, edit the graph, start a backend, download components, or substitute another workflow automatically.

## Confirmation Gate

An early `use defaults and start` received before catalog resolution records intent only; it never authorizes an unseen model. Generic wording such as "the approved local model and start" does not pre-authorize any concrete model ID. Confirmation must cover the resolved complete summary, including the exact `model_choice`.

After `local_gpu_recommend_models` resolves one exact route and the complete summary is ready, display it. Always require a new explicit confirmation after displaying that summary, even when the user supplied start/default intent earlier. Only a user message received after the display and clearly accepting the shown route and summary is confirmation; that later message may itself say `use defaults and start`.

Required temporal order:

```text
early `use defaults and start` -> intent only
-> `local_gpu_discover_models`
-> `local_gpu_list_profiles`
-> `local_gpu_recommend_models`
-> display the exact route and resolved complete summary with exact `model_choice`
-> receive post-display confirmation
-> `local_gpu_start_run`
```

Do not call `local_gpu_start_run` before that post-display confirmation.

## Regional Copy-Subject Route

Use this decision contract before selecting a copy/subject route:

- Use `copy-subject-v1` only for an ordinary separated-region request where the user accepts retained negative evidence and experimental compatibility. It does not establish a visual-quality improvement and is not a substitute or fallback for `sdxl-two-stage-copy-subject`.
- When the request requires pixel-protected copy space, separate base/subject stages, or the controlled workflow below, `sdxl-two-stage-copy-subject` is the required exact route for the controlled two-stage workflow. Resolve that route or stop.

When the decision selects the experimental single-pass route, follow this order:

1. Ask only for missing copy side/size, subject side/size, regional prompt intent, `copy_strength`, `subject_strength`, and round budget.
2. Normalize exactly one `copy_region` and one `subject_region`. Reject overlap, ambiguity, out-of-bounds geometry, or any additional region.
3. Call `local_gpu_recommend_models` with the normalized `regional_layout`. The route must use ComfyUI and the reviewed `sdxl-regional-txt2img` workflow. If the result is `regional_layout_unavailable`, stop. Never fall back to `sdxl-txt2img` or a prompt-only approximation.
4. First display normalized decimals and percentages; do this before asking the user to confirm. The displayed summary contains both rectangles, `copy_prompt`, `subject_prompt`, `copy_strength`, `subject_strength`, the exact route/model/bundle/workflow/compiler/dimensions, policies, and successful-round budget.
5. Wait for a later explicit confirmation of that displayed regional summary. Earlier intent, defaults, or confirmation of a different geometry does not authorize the run.
6. Call `local_gpu_start_run` with the same `constraints.regional_layout` and exact `initial_regional_conditioning`.
7. Call `local_gpu_get_run`, then construct the existing exact 20-field plan. Copy the persisted layout into plan `constraints` and the confirmed conditioning into `parameters.regional_conditioning` for the initial round.
8. On refine or explore, change only regional prompts or strengths unless the user explicitly selects another parameter already allowed by the Profile. The geometry remains frozen for the confirmed run.
9. A geometry change requires a newly displayed and confirmed new root or child revision. It never mutates an existing run in place.

A successful backend round that violates the confirmed copy/subject relation is retained, reviewed with `explicit_constraint_violation`, and consumes one successful-round budget slot.

## Two-Stage Copy-Subject Route

Use `copy-subject-two-stage-v1` only when the user needs a pixel-protected copy area plus a separately generated subject. Resolve `sdxl-two-stage-copy-subject` from the live catalog; missing capability, identity drift, or an unavailable route stops the request. No fallback is allowed to `sdxl-regional-txt2img`, `sdxl-txt2img`, prompt-only approximation, another model, or another backend.

Follow this positive confirmation recipe:

1. Write a base scene `positive_prompt` where the base prompt excludes the subject. Put the subject name and its close variants in the base `negative_prompt`. Keep the separately confirmed `subject_prompt`, `subject_negative_prompt`, and `subject_denoise` only in `two_stage_conditioning`.
2. Display every rectangle in pixels and percentages before confirmation. For the reviewed 1280 x 720 layout, show: copy protected `x=0 (0%), y=0 (0%), width=576 (45%), height=720 (100%)`; subject mask `x=720 (56.25%), y=24 (3.33%), width=512 (40%), height=672 (93.33%)`; `feather_pixels=32`; `vae_grow_mask_by=8`. A different valid layout requires its own exact pixel and percentage display.
3. Display the base seed and the derived subject seed, where `subject_seed = (base_seed + 1) mod 2^64`. Display the exact model identity, endpoint, workflow SHA-256, control SHA-256, bundle SHA-256, compiler, dimensions, conditioning, policies, and budget in the same summary.
4. State that one round costs two stage units. Wait for a later explicit confirmation of that complete summary, then call `local_gpu_start_run` with the frozen `two_stage_layout` and exact `initial_two_stage_conditioning`.
5. Read the persisted run and construct the existing exact 20-field plan. The base prompts stay in `positive_prompt` and `negative_prompt`; the subject-only prompts and denoise stay in `parameters.two_stage_conditioning`. Geometry, route, workflow, control, bundle, model, endpoint, compiler, and policy values remain frozen.
6. Generate once and require all three retained artifacts: base, mask, and final. If any artifact is missing, malformed, ambiguous, outside the run, or fails mask/protected-pixel verification, partial output stops the run. Do not retry, review, nominate, or fall back from a `partial` run without a new user decision and a newly confirmed route when required.
7. On a vision-capable host, inspect the base artifact at full resolution and record `base_copy_space` plus `base_subject_absent`. Then inspect the final artifact at full resolution and record `final_subject_inside_mask`, `final_safe_margins`, `final_forbidden_content`, `feather_transition`, and `pixel_preservation`. Every stage check must pass and the machine report must record zero mismatches.
8. Only the final artifact can become a candidate; the base and mask are supporting evidence. Display the final PNG and its byte-bound finalization confirmation only after both full-resolution stage reviews and the ordinary visual/rubric checks pass.

The first live GPU gate is exactly one two-stage round: set `max_rounds: 1`, spend exactly two stage units, review the base and final, and stop. Additional GPU rounds, a geometry change, or another route require a later explicit decision; unused general run capacity is not permission.

## Run Sequence

Follow this order exactly:

```text
`local_gpu_list_profiles` -> brief -> `local_gpu_recommend_models` -> confirm -> `local_gpu_start_run`
-> `local_gpu_get_run` -> construct the complete frozen plan
-> `local_gpu_generate_round(action=initial)` -> inspect preview
-> `local_gpu_record_review` -> `local_gpu_generate_round(action=refine|explore)`
-> inspect preview -> `local_gpu_record_review` -> `local_gpu_finalize_run`
```

Immediately after `local_gpu_start_run`, call `local_gpu_get_run` with the returned run ID. Treat its persisted `request` and `route` as authoritative and copy the frozen boundary exactly into every `local_gpu_generate_round` plan. Do not construct a prompt-only plan. The complete plan contains exactly these fields:

```text
`profile`, `style`, `intent`, `positive_prompt`, `negative_prompt`,
`constraints`, `parameters`, `max_rounds`, `upscale_policy`,
`authorization_scope`, `route_token`, `model_choice`, `backend`,
`endpoint_identity`, `model_identity_token`, `identity_strength`,
`workflow_template_id`, `workflow_template_version`,
`prompt_compiler_id`, `prompt_compiler_version`
```

Copy `profile`, `style`, `intent`, `constraints`, `max_rounds`, `upscale_policy`, `authorization_scope`, `route_token`, `model_choice`, and `backend` from the persisted request. Copy the endpoint, model identity, workflow, and compiler values from its frozen route, mapping route `identity_token` to plan `model_identity_token`. Add only the compiled `positive_prompt`, `negative_prompt`, and profile-compatible `parameters`; never guess or omit a frozen field. On later rounds, fetch the current run again when process memory or route state is uncertain, then preserve the same frozen boundary.

The second generation/review pair is conditional: repeat it only while the confirmed budget remains and improvement is worthwhile. `local_gpu_get_run` also serves recovery and state checks. Use `local_gpu_cleanup_run` only for the scope the user authorized; deleting a whole run requires the tool's exact confirmation. Do not bypass the adaptive run with `local_gpu_generate_image`.

For each generation, use a unique idempotency key and a plan bound to the confirmed summary. The first action is `initial`. After each review:

- **Refine: preserve the seed.** Keep the accepted structure and make targeted parameter/prompt improvements.
- **Explore: change the seed.** Search a materially different composition or interpretation within the confirmed constraints.
- Put concise intent in `change_summary`: `Preserve: <what stays>. Change: <what changes>.`
- Never exceed the confirmed successful-round budget. Failed attempts do not consume a successful round, but time pressure, sunk cost, an offline user, or a likely improvement never authorizes another successful round.
- A retained image consumes one successful round regardless of visual quality. Do not relabel it as a failed attempt to evade the budget.
- Eligible means no hard failures and every critical rubric score is at least 3. Stop early when an eligible reviewed result exists and further GPU use is unlikely to help.

## Hot Revision

When the user likes part of a reviewed or finalized candidate but wants another part changed, create an auditable preserve/change contract for an immutable child run. Extract what the user likes, what must remain, what must change, and whether every preserved target is hard or soft. Ask only for missing high-impact boundaries, including a revision budget of one to three successful rounds. Do not ask again for values already stated.

Present the concise preserve/change contract, selected parent round, edit mode, denoising strength when applicable, and revision budget. Call `local_gpu_branch_run` only after the user confirms that summary or directly instructs immediate use of the displayed defaults. The order is:

```text
extract likes/remain/change -> present the concise preserve/change contract
-> user confirms -> `local_gpu_branch_run` -> immutable child run
```

Choose the least destructive supported mode in this order: `prompt refinement -> low-strength img2img -> confirmed inpaint`.

- Use prompt refinement for semantic, lighting, or wording changes that can retain the parent seed; the child branch uses `prompt-refine` and generation uses `txt2img` without a source image.
- Use low-strength img2img when rendering must change broadly; the child contract fixes the source image and denoising strength.
- Use confirmed inpaint only when the requested change is local and spatially identifiable. Preservation without a mask is best-effort. Do not promise pixel-perfect no-mask preservation.

Prefer a user-provided mask. For Agent-proposed rectangles or polygons, call `local_gpu_prepare_mask`, show the mask overlay, and wait for explicit approval. Do not call `local_gpu_confirm_mask` based on silence, prior consent, or the Agent's own judgment. A requested change to geometry, source, or feathering must prepare a new unconfirmed mask and repeat overlay approval. Do not perform automatic segmentation.

Run the immutable child with the same bounded initial/refine/explore state rules as a root run. On a vision-capable host, record one observable `preservation_results` entry per preserved target. A changed hard target is a hard failure, and an uncertain hard target cannot be auto-accepted. Text-only hosts must not invent preservation results; return the child output for user review without claiming the preserve/change contract passed.

## Review Evidence

On a vision-capable host, display the original full-resolution image and inspect that image before recording a review. A preview is an auxiliary navigation aid, not sufficient visual evidence. Record `full_resolution_inspected: true`, `prominent_human`, and an observed status plus concise observation for `limb_separation`, `feet_and_contact`, `hands_and_held_objects`, and `text_and_watermarks`. When `prominent_human` is true, the three anatomy checks cannot be `not_applicable`. Any required check that is fail or uncertain requires `next_action` refine or explore; it cannot be finalized.

For a frozen semantic contract, compare the requested medium, then the required visual anchors,
then the forbidden substitutions. Record one exact
`anchor_results` item per required anchor and one exact `substitution_results`
item per forbidden substitution. A failed semantic result requires both
`explicit_constraint_violation` and `semantic_substitution`; a failed or
uncertain semantic result cannot request finalization.

Before scoring polish, compare the full-resolution image with the frozen intent. A change to the requested product medium, subject, practical use, or asset slot is semantic substitution. Record it in the existing `constraint_results` as a failed constraint, add a concise `hard_failures` entry, and do not finalize that round, even when the substitute is cleaner or has fewer rendering defects. For example, a paper notebook is not an acceptable substitute for a requested software product merely because it avoids malformed generated UI.

Call `local_gpu_record_review` only after those checks. Record the complete returned rubric with evidence-based 1-to-5 scores, hard failures, explicit-constraint results, a concise critique, and the next action. Do not store chain-of-thought; store only conclusions, observed evidence, and the concise preserve/change intent.

For an eligible reviewed result, display `quality_status: candidate`, its limitations, the full image SHA-256, and the exact confirmation `finalize:<run_id>:<round_number>:<image_sha256>`. Then stop and wait for a later user message. Only that later message may provide the displayed confirmation for `local_gpu_finalize_run`. A candidate is not accepted until the later user confirmation is verified, and the Agent cannot accept it on the user's behalf.

On a text-only host, generate exactly one successful round per confirmed run, then mark `review unavailable` and stop after the first retained round. Do not call `local_gpu_record_review` or `local_gpu_finalize_run`. Report the retained path as unreviewed; any remaining round budget stays unused until a human or vision-capable host can review. Do not fabricate scores, constraint results, defects, or visual critique. Do not claim the result is accepted, polished, or visually verified.

An ineligible or uncertain result is never publishable, including when its round budget is exhausted. Keep it as a reviewed artifact; refine or explore when confirmed budget remains, otherwise report the limitation and wait for a new user decision without publication.

## Hard Boundaries

- No hidden downloads. Do not enable downloads or suggest that a remote-looking model ID is locally available. Report unavailable dependencies/models and stop.
- Enforce no silent model switch. Do not silently fall back to CPU or switch the confirmed model, backend, endpoint, workflow, compiler, or authorization scope in a root run or child revision.
- `upscale_policy: auto` records permission only; it does not prove a compatible upscaler is installed or that upscaling occurred.
- Do not promise pixel-perfect no-mask preservation or describe best-effort semantic preservation as guaranteed.
- Do not perform automatic segmentation or imply that a geometry mask was approved before the returned overlay received explicit user approval.
- A preview path is not visual evidence. One-turn urgency is not confirmation. A nearly-good last round is not authority to exceed the budget.
- Do not describe Codex or any other host as verified, and do not claim real image acceptance without retained acceptance evidence.
