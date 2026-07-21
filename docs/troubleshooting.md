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

## Cleanup Confirmation Is Rejected

For both `intermediates` and `all`, confirmation must exactly equal the `run_id`. The `intermediates` scope keeps `manifest.json` and the final PNG. The `all` scope deletes the run directory, so read the run and verify the identifier before confirming it.

## WebUI Returns Invalid Image Data

The generator rejects missing, empty, or invalid Base64 image payloads. Check the WebUI logs and confirm that the configured endpoint is AUTOMATIC1111-compatible. A JSON HTTP response alone is not sufficient evidence of successful generation; a valid non-empty PNG must be written.
