# Troubleshooting

## Start With Two Checks

Verify the MCP transport without loading GPU packages:

```powershell
python .\scripts\verify_mcp.py
```

Then inspect backend readiness:

```powershell
python .\scripts\check_gpu.py
```

The second command exits with code 1 when no backend is ready, but its JSON report is still valid diagnostic output. ComfyUI adapter: contract-tested; local Z-Image and Anima adapter executions: observed; public acceptance evidence: not retained.

`local_gpu_list_profiles` returns the scoped merged model catalog beside backend capabilities. A high-level run uses the exact backend from a confirmed route; there is no `auto` fallback and no silent model switch. Capability reporting does not install packages, trust a model, or download one.

No model weights are bundled. The repository contains an auditable `civitai/anything-v5@30163` template for one reviewed existing local WebUI checkpoint; actual eligibility still depends on current discovery identity, requested `private` or `public_evidence` scope, backend readiness, and exact route confirmation. Do not bypass this with the low-level compatibility tool, an arbitrary model name, or an implicit download.

On Windows PowerShell 5.1, manual native-process pipelines may prefix stdin with a UTF-8 byte-order mark. The server tolerates that mark, but `scripts/verify_mcp.py` remains the preferred transport check because it controls encoding and validates all required responses.

To test a specific environment without activating it:

```powershell
python .\scripts\verify_mcp.py --python C:\path\to\.venv\Scripts\python.exe --check-readiness
```

## WebUI Is Unavailable

Symptoms:

- `webui.available` is `false`
- connection refused at `127.0.0.1:7860`

Checks:

1. Start AUTOMATIC1111 or Forge with API access enabled.
2. Confirm its API URL and port.
3. Set `LOCAL_GPU_IMAGEGEN_WEBUI_URL` or pass `--webui-url` when using a non-default port.
4. Keep the URL on loopback unless remote exposure is intentional and secured.

## Discovery Plan Expired Or Changed

`discovery_plan_expired` means the short-lived plan is no longer valid. `discovery_plan_changed` means mode, roots, exclusions, selected candidates, or endpoint facts differ from what was displayed. Request a new `plan` phase, show the complete scope again, and obtain the new exact confirmation. Never reuse an older confirmation.

The four scan modes are `api_only`, `selected_folders`, `common_locations`, and `full_drive`. `index` is metadata-only; `fingerprint` hashes only explicitly selected indexed candidates. If a scan is canceled, the result is `incomplete: true` and its inventory remains untrusted. Resume with a new plan instead of treating partial results as trusted.

## A Fresh Process Cannot Recover A Public Route

A fresh MCP process has no discovery inventory even though user-local trust still exists. Do not begin with recommendation or accept a private fallback. Rebuild the current evidence in this order:

1. Plan `selected_folders` `index` for one previously confirmed model root and the exact `explicit_includes` file.
2. Display the unchanged scope, `cost_warning`, expiration, local metadata-read cost, and exact confirmation; execute only after that confirmation.
3. Require exactly one candidate and verify its filename and byte size.
4. Plan `selected_folders` `fingerprint` with `selected_candidates` containing only that candidate. Display that hashing reads the full file, obtain the new exact confirmation, and execute it.
5. Verify the filesystem identity token, full SHA-256, and byte size against the expected checkpoint.
6. Run an `api_only` ComfyUI `index` in the same process, then recommend and verify the exact `public_evidence` route.

Do not downgrade to `backend_binding` or `private` identity. Do not scan unrelated roots, reuse an expired plan, omit the full-file cost warning, or recommend before both filesystem and API identities are current.

## LAN Or Public Endpoint Is Rejected

Loopback is local. A LAN WebUI/ComfyUI endpoint requires the exact displayed transmission confirmation; otherwise discovery returns `network_scan_confirmation_required`. Public internet endpoints return `public_endpoint_rejected`. Do not work around either result with a DNS alias, credentials in a URL, HTTPS downgrade, port forwarding, or a broader scan.

## No Eligible Route

`no_eligible_model` means every candidate failed at least one hard requirement such as operation, Profile/style, dimensions, VRAM, trust scope, backend readiness, prompt compiler, or ComfyUI workflow. Inspect the returned requirements and catalog limitations. Change a requirement only with the user; do not silently substitute a model or weaken the boundary.

`route_confirmation_expired` means the route token was missing, consumed, expired, or confirmed against another model. Recommend again, display the exact replacement route, and obtain a new post-display confirmation.

## Model Identity Drifted

`model_identity_drifted` means endpoint, backend-visible model binding, file metadata, SHA-256, trust identity, or workflow binding no longer matches the frozen route. Generation stops before backend invocation and before an attempt is created. Rediscover, re-fingerprint if needed, review trust, recommend again, and obtain a new confirmation. Never edit the manifest or transplant the old route token.

`invalid_component_bundle`, `workflow_component_binding_ambiguous`, or `component_bundle_mismatch` means a split workflow component is missing, duplicated, mapped to the wrong loader/name, changed after hashing, or no longer matches the reviewed workflow digest. Repeat API discovery and selected-folder fingerprinting, then run `inspect_workflow_binding` again. Inspection is read-only. Do not reuse an older bundle confirmation or fill missing license facts by inference.

User-local trust defaults to the OS state directory; set `LOCAL_GPU_IMAGEGEN_STATE_DIR` only before launching the server when an explicit alternative is needed. A `backend_binding` record remains private. Public evidence requires `cryptographic` identity plus authority; changing the state directory cannot promote trust.

## ComfyUI Workflow Is Rejected

`invalid_workflow_template`, `invalid_workflow_source`, or `workflow_registration_drifted` means the graph is malformed, changed, over budget, contains an unapproved node/input, or no longer matches its registered local copy. Use the shipped `sd15-txt2img-v1`, `z-image-turbo-txt2img-v1`, or `anima-txt2img-v1` template, or re-import a reviewed graph. Shell, Python/script/process, command, HTTP/download/fetch/webhook behavior, unknown custom nodes, unbound parameters, traversal paths, and resource overruns are rejected.

An empty `CheckpointLoaderSimple` choice list is normal when ComfyUI contains only split diffusion models; discovery should still return `UNETLoader` choices. If a split workflow fails at submission, verify the exact text encoder and VAE named by the template are already installed. The plugin never downloads a missing component. Do not substitute another encoder/VAE or change loader type without a new reviewed workflow and route confirmation.

## ComfyUI Job Times Out Or Disappears

`comfyui_submission_rejected`, `comfyui_job_timed_out`, `comfyui_job_disappeared`, `comfyui_job_rejected`, and `comfyui_job_canceled` are distinct outcomes. A timeout queries the exact known job before returning. Query that job and inspect ComfyUI logs; cancellation deletes only an exact queued job, and a running job is never interrupted globally. Do not resubmit blindly with the same idempotency key.

## VRAM Or Model Loading Fails

Routing can filter a declared `required_vram_gb`, but it does not prove runtime fit. A backend load failure or out-of-memory error remains a backend failure and consumes no successful round. Confirm the selected checkpoint is loaded, close unrelated GPU work, or ask the user to choose a smaller eligible route. Do not fall back to CPU, another model, or lower dimensions silently.

## Backend Output Is Not Normalized

`invalid_backend_result`, `invalid_backend_response`, or `invalid_comfyui_output` means the backend did not return the confirmed backend/model identity, dimensions, seed, workflow/compiler fields, bounded output metadata, or a valid PNG. The attempt is retained as failed and does not consume a successful round. Inspect the backend response and route identity; never patch the manifest into success.

## Diffusers Model Is Not Available Locally

The project blocks implicit model downloads. Choose one:

- preload the named model into the configured Hugging Face cache;
- pass a local model directory;
- explicitly use `--allow-download` after reviewing the model license and disk requirement.

The MCP equivalent is `allow_download: true`.

## CUDA Is Not Available

Confirm that the selected Python executable contains a CUDA-enabled PyTorch build and can see the GPU. Do not repair an unrelated global/shared Python environment for this project. Prefer the project-local `.venv` created by `scripts/install.ps1`.

CPU fallback is disabled by default. Use `--allow-cpu` or MCP `allow_cpu: true` only when slow CPU generation is intentional.

## Python Crashes While Importing PyTorch

Native OpenMP or DLL collisions usually indicate a contaminated shared environment. Create a clean Python 3.11/3.12 project `.venv`; do not resolve the collision by removing packages from another project.

## Generation Times Out

The MCP subprocess timeout defaults to 900 seconds. Set `LOCAL_GPU_IMAGEGEN_COMMAND_TIMEOUT_SECONDS` before launching the server if a verified model/hardware combination needs a different limit. Raising the timeout does not fix a hung backend; inspect the backend directly first.

## A Run Was Interrupted Or Reports Busy

Call `local_gpu_get_run` and inspect its state, warnings, attempts, and `recoverable_next_actions`. A live attempt remains busy so a concurrent caller cannot overwrite it. Stale attempt and lock metadata are recovered when process ownership can no longer be verified.

Retry the exact generation with the same `idempotency_key` and the same request. A completed retry returns the retained round without calling the backend again. If a validated PNG was retained before interruption, the engine can rebuild its preview. Do not reuse an idempotency key after changing the action, seed, or plan; that returns `idempotency_conflict`.

## Round Budget And Final Selection

`max_rounds` is limited to 1 through 3 successful rounds. Backend failures do not consume a round. Every generated round must be reviewed before another round is created. Inspect the original full-resolution PNG, not only its preview, and supply all structured visual checks. For a prominent human, limb separation, feet/contact, and hands/held objects are always applicable; text/watermark inspection is always applicable.

`visual_checks_require_revision` means a required check was `fail` or `uncertain` while the review requested finalization. The review is rejected before manifest mutation. Record the honest observation again with `next_action: refine` or `explore`; when confirmed budget remains, generate the next round on the same run. Do not reset the run or relabel the retained image as a failed attempt to regain budget.

An eligible review response contains quality status `candidate` and the exact `finalize:<run_id>:<round_number>:<image_sha256>` value. Display the original image, limitations, and that value, then wait for a later user message. `finalization_confirmation_mismatch` means the supplied value is missing, stale, belongs to another run or round, has another image hash, or the reviewed round is not eligible. Nothing is published. Call `local_gpu_get_run`; if it returns a candidate, display its current exact value and obtain a new later confirmation. If it returns no candidate, refine or explore while budget remains, or retain the reviewed artifact and request a new user decision without publication.

## A Preview Is Missing

The JPEG preview is optional and bounded for MCP transport. The full-resolution local PNG is authoritative. Check the tool's `full_image_path`, manifest round image metadata, and warnings such as `preview_unavailable:pillow_missing`. Installing or repairing Pillow should happen only in the project environment; a preview failure does not justify regenerating a valid retained PNG.

New previews are named `round-NN-preview.jpg`. A stored legacy manifest may still reference `round-NN.preview.jpg`; that path remains supported and is not a reason to rename or regenerate the retained round.

## A Child Revision Cannot Start

`revision_parent_not_reviewed` means the nominated parent round is missing, failed, or has no review. Read the parent run and select an existing reviewed round. `revision_edit_mode_mismatch` means the generation request tried to override the immutable child contract; use txt2img for `prompt-refine`, img2img for `img2img`, or inpaint for `inpaint`.

The child copies its own `parent-source.png`. A `revision_source_changed` conflict means that copy no longer matches the hash recorded at branch creation. Do not replace it or rewrite the parent manifest. Create a new child from an unchanged reviewed parent round. A valid child workflow never changes the parent manifest or the selected parent PNG.

## An Inpaint Mask Is Rejected

`inpaint_mask_required` means the child generation omitted `mask_id`. `mask_not_found` also covers a mask ID prepared for a foreign run. `mask_not_confirmed` means the overlay has not received explicit user approval. Show the JPEG overlay returned by `local_gpu_prepare_mask`, then call `local_gpu_confirm_mask` only after approval.

`mask_changed_since_prepare` means the child source or mask bytes no longer match the retained hashes. Do not silently reconfirm changed bytes. Prepare a new mask, show its new overlay, and obtain new approval. Empty, full-image, out-of-bounds, or self-intersecting masks must be corrected at preparation time; the plugin does not run automatic segmentation.

## Anime Postprocessing Is Unavailable Or Failed

Real-ESRGAN is never invoked automatically. It is anime-only and must be requested explicitly during finalization after `LOCAL_GPU_IMAGEGEN_REALESRGAN_DIR` points to an already reviewed local installation containing `realesrgan-ncnn-vulkan.exe` and one supported model pair: `realesrgan-x4plus-anime` or `realesr-animevideov3-x4`. The plugin does not accept an arbitrary binary/model path and does not download either dependency.

`postprocess_unavailable` means the exact configured executable/model files were not available. `postprocess_failed` means invocation or output validation failed. In both cases, the reviewed original `final.png` is the fallback; do not treat `final-upscaled.png` as successful unless the returned final metadata identifies it and includes its hashes and dimensions.

Start inspection with `local_gpu_get_run`. Check the persisted state, warnings, original-final metadata, and the exact `final-upscaled.png` / `final-upscaled.pending.png` entries. Correct the environment, supported model selection, or local permissions outside the plugin, then retry only when `recoverable_next_actions` and the current state permit it. If the run is already finalized, keep the original final or begin a new confirmed run rather than repeating finalization.

`postprocess_cleanup_failed` is an additional warning: the original-final fallback may still be usable, but exact-name pending, rollback, directory, link, or junction residue may remain for diagnosis. Do not recursively delete the run directory, follow a link target, remove an unfamiliar target, or trigger a hidden download. Preserve the manifest and original, inspect the exact entry type and permissions, and use an administrator-approved local cleanup procedure before any safe retry.

## Cleanup Confirmation Is Rejected

For both `intermediates` and `all`, confirmation must exactly equal the `run_id`. The `intermediates` scope keeps `manifest.json` and the final PNG. The `all` scope deletes the run directory, so read the run and verify the identifier before confirming it.

## WebUI Returns Invalid Image Data

The generator rejects missing, empty, or invalid Base64 image payloads. Check the WebUI logs and confirm that the configured endpoint is AUTOMATIC1111-compatible. A JSON HTTP response alone is not sufficient evidence of successful generation; a valid non-empty PNG must be written.
