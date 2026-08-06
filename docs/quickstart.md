# Five-Minute Quickstart

## Choose The Bootstrap Path

An existing environment uses `bootstrap status` and reuses only verified local
artifacts. A zero-environment path uses `bootstrap plan`, then `bootstrap apply`
only after an explicit confirmation of downloads, licenses, hashes, disk/VRAM
effects, and rollback behavior. Transfers are resumable and there are no silent
downloads. This is Windows 10/11 x64 NVIDIA only (10 GiB VRAM and 30 GiB free
disk); Docker is not required. The contract does not prove image generation.

[English](quickstart.md) | [简体中文](quickstart.zh-CN.md)

By default, this path is for Python 3.11 or 3.12 users whose supported backend and model are already running.
An existing Windows portable ComfyUI may instead
be explicitly registered for managed startup. This path excludes backend
installation, model downloads, and generation time.

## 1. Verify The Installed Server

```shell
uvx local-gpu-imagegen verify
```

Checkpoint: the JSON reports `ok: true`, version `0.8.3`, and exactly seventeen tools. Stop and use [First-Run Problems](#first-run-problems) if it does not.

## 2. Add It To Codex Or Claude Code

Run the command for the client you use:

```shell
uvx local-gpu-imagegen setup codex --apply
uvx local-gpu-imagegen setup claude-code --apply
```

For an existing Windows portable ComfyUI that should start with the MCP server,
add the explicit managed-start options to the selected client command:

```powershell
uvx local-gpu-imagegen setup codex --apply `
  --auto-start-comfyui `
  --comfyui-root "<ComfyUI_windows_portable>"
```

This validates, but does not install, the portable runtime. It pins
`python_embeded\python.exe -s ComfyUI\main.py`, `127.0.0.1:8188`, and a
120-second first-readiness window into the displayed official setup plan.
Review the full `server.command` before applying it.

Checkpoint: setup JSON reports `applied: true`. The command delegates to the
client's official MCP command and does not edit its configuration file directly.
It registers the resolved `uvx` executable with this version-pinned server
command, rather than relying on a console script from the temporary `uvx`
environment:

```text
uvx --from local-gpu-imagegen==0.8.3 local-gpu-imagegen serve
```

If setup reports `client_setup_drift`, the existing entry uses a different
launcher. Do not edit client configuration directly. Run the selected client's
documented remove command under [Roll Back Client Setup](#roll-back-client-setup),
then run its setup command once more. Starting ComfyUI cannot repair an MCP
launcher failure; backend readiness is checked only after the client loads the
server.

## 3. Restart Or Reload The Client

Restart or reload the selected client, then confirm its MCP server list includes `local-gpu-imagegen`. A setup result alone does not prove that the running client loaded the server.

## 4. Check Backend Readiness

```shell
uvx local-gpu-imagegen doctor
```

Checkpoint: doctor reports the selected backend reachable. `doctor` is always
read-only. In managed mode the MCP process starts ComfyUI in the background,
and its first `local_gpu_imagegen_check` waits for the configured startup
window. An existing endpoint is reused without being owned or stopped.

## 5. Run One Supported Workflow

For one supported ordinary ComfyUI API workflow, enable Developer mode, use
`Save (API Format)`, then ask Codex:

```text
Run this supported ComfyUI API workflow from Codex: <path>.
Use this prompt: <prompt>. Preserve every other workflow setting.
```

First use has three first-use decisions. A new workflow on the same verified
model requires two decisions; an already trusted unchanged workflow requires
one execution decision. The MCP surface remains exactly 17 tools.

### File verification decision

Codex performs API-only discovery, calls `local_gpu_inspect_workflow`, then
plans `local_gpu_discover_models` with `exact_file` / `verify` for one exact
local model path. It displays the path, loader name, byte size, full-file read
cost, expiry, and exact confirmation before reading the complete model file.
Approve only that future exact-path read. It does not grant trust, register a
workflow, approve a route, or submit a prompt.

Later processes automatically revalidate only the workflow-referenced model.
The same SHA-256 restores cryptographic inventory without a new confirmation;
path, stat, or digest drift requires a new file-verification decision.

### Preparation decision

With current API and cryptographic filesystem identities, Codex inspects the
exact component binding without writing state. It then displays workflow
hashes, defaults, endpoint, components, requested overrides, limitations, and
the two stored confirmations. Approve only after that complete proposal is visible.
`local_gpu_register_workflow` writes one immutable copy, and private trust
binds the same workflow, endpoint, and components. A trust failure leaves an
inert registration and stops.

### Execution decision

Codex calls `local_gpu_recommend_models`, resolves and displays one exact route,
all prompt and generation values, the fields changed from imported defaults,
and a one successful round budget. Approve only after that route is visible.
Codex then calls `local_gpu_start_run`, restores the frozen run, and calls
`local_gpu_generate_round` once. The run uses no retry, no model switch, no CPU
or workflow fallback, and no download.

A successful first round returns the original image and durable run evidence
as `generated / unreviewed`. Review and finalization are optional follow-up
work; they do not block the first result.

Inspection is read-only and does not start ComfyUI or submit a prompt.
Registration does not grant public authority or model-download permission.

See the [retained Codex onboarding session](demo/workflow-onboarding.md). It is
real zero-GPU client evidence for discovery, inspection, registration, and trust
binding, not generated-image or quality evidence.

## Profile-Driven Run

You can instead ask the bundled Agent Skill to resolve a shipped route from a
visual brief. For example:

> Create one complete lighthouse environment illustration with no people, text, logo, or watermark. Reuse my existing local backend and model, keep downloads and model switching disabled, use at most two successful rounds, and ask me before finalization.

Before generation, the Agent should show the results of `local_gpu_discover_models`, any required `local_gpu_set_model_trust` action, `local_gpu_recommend_models`, and the exact selected route. It should wait for your confirmation before `local_gpu_generate_round`, display each retained image for review, and wait for a later byte-bound finalization confirmation.

Both paths require an installed supported backend and model. UI-format conversion,
workflows that require unsupported custom nodes, img2img, inpaint, regional/two-stage onboarding,
model installation, and backend discovery remain outside this quickstart.
Backend startup occurs only through the explicit Windows portable option above;
that option does not remove or manage custom nodes already present in the
selected installation.

## Roll Back Client Setup

Remove only the MCP entry created for the selected client:

```shell
codex mcp remove local-gpu-imagegen
claude mcp remove --scope user local-gpu-imagegen
```

Restart or reload the client and confirm `local-gpu-imagegen` no longer appears. This does not delete local models, backend files, or retained runs.

## First-Run Problems

Use [Troubleshooting](troubleshooting.md) for install, transport, backend, trust, route, and recovery failures. See [Client compatibility](client-compatibility.md) for deeper Codex and Claude Code setup details and the current named-client evidence boundary.
