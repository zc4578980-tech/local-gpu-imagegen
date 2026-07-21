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

The second command exits with code 1 when neither backend is ready, but its JSON report is still valid diagnostic output.

`local_gpu_list_profiles` also returns backend capabilities beside the registered profiles. A run with `backend: auto` still needs at least one advertised backend resolution; capability reporting does not install packages, select a model, or download one.

The production model catalog currently contains only disabled `stabilityai/sd-turbo`; no production model is bundled or approved. A high-level Agent run must stop at the unavailable-model boundary until a separate local source and license review enables an approved record. Do not bypass this with the low-level compatibility tool, an arbitrary model name, or an implicit download.

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

`max_rounds` is limited to 1 through 3 successful rounds. Backend failures do not consume a round. Every generated round must be reviewed before another round is created. Finalization requires an explicit reviewed `round_number`; the engine publishes that exact nomination rather than selecting another round by score.

When a caller nominates an ineligible reviewed round, final metadata uses `quality_status: needs_user_review`. Inspect the full local PNG and the recorded failures; this status does not mean the result passed the rubric.

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
