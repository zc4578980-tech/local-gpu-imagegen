# Five-Minute Quickstart

This path is for Python 3.11 or 3.12 users whose supported backend and model are already running. It excludes backend installation, model downloads, and generation time.

## 1. Verify The Installed Server

```shell
uvx local-gpu-imagegen verify
```

Checkpoint: the JSON reports `ok: true`, version `0.8.0`, and exactly seventeen tools. Stop and use [First-Run Problems](#first-run-problems) if it does not.

## 2. Add It To Codex Or Claude Code

Run the command for the client you use:

```shell
uvx local-gpu-imagegen setup codex --apply
uvx local-gpu-imagegen setup claude-code --apply
```

Checkpoint: setup JSON reports `applied: true`. The command delegates to the client's official MCP command and does not edit its configuration file directly.

## 3. Restart Or Reload The Client

Restart or reload the selected client, then confirm its MCP server list includes `local-gpu-imagegen`. A setup result alone does not prove that the running client loaded the server.

## 4. Check Backend Readiness

```shell
uvx local-gpu-imagegen doctor
```

Checkpoint: doctor reports the selected backend reachable. A backend or model that is not already running is outside this five-minute path.

## 5. Run One Supported Workflow

For one supported ordinary ComfyUI API workflow, enable Developer mode, use
`Save (API Format)`, then ask Codex:

```text
Run this supported ComfyUI API workflow from Codex: <path>.
Use this prompt: <prompt>. Preserve every other workflow setting.
```

### Preparation decision

Codex performs API-only discovery when needed, calls
`local_gpu_inspect_workflow`, and inspects the exact component binding without
writing state. It then displays workflow hashes, defaults, endpoint,
components, requested overrides, limitations, and the two stored
confirmations. Approve only after that complete proposal is visible.
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

Both paths require an already-running supported backend and model. UI-format conversion,
custom nodes, img2img, inpaint, regional/two-stage onboarding,
implicit backend startup, and model installation remain outside this quickstart.

## Roll Back Client Setup

Remove only the MCP entry created for the selected client:

```shell
codex mcp remove local-gpu-imagegen
claude mcp remove --scope user local-gpu-imagegen
```

Restart or reload the client and confirm `local-gpu-imagegen` no longer appears. This does not delete local models, backend files, or retained runs.

## First-Run Problems

Use [Troubleshooting](troubleshooting.md) for install, transport, backend, trust, route, and recovery failures. See [Client compatibility](client-compatibility.md) for deeper Codex and Claude Code setup details and the current named-client evidence boundary.
