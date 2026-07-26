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

## 5. Export One Supported ComfyUI Workflow

In ComfyUI, enable Developer mode and use `Save (API Format)`. UI-format JSON
with `nodes`, `links`, and widget arrays is not accepted. The supported ordinary
ComfyUI API workflow is a `txt2img` graph with either one checkpoint loader or a
reviewed split-model topology, known built-in nodes, one owned image output, and
bindable prompt, dimensions, seed, sampler, scheduler, steps, and CFG inputs.

Give the exported local path to your Agent:

> Inspect my supported ordinary ComfyUI API workflow at
> `<path-to-workflow-api.json>`. Show its source hash, semantic workflow hash,
> inferred bindings, components, limitations, and exact registration
> confirmation. Do not register, trust, download, or run anything until I
> confirm each displayed boundary.

The Agent follows this sequence:

```text
local_gpu_discover_models (api_only when inventory is absent)
-> local_gpu_inspect_workflow
-> display source/workflow hashes, bindings, components, and limitations
-> wait for the exact registration confirmation in a later message
-> local_gpu_register_workflow
-> separate local_gpu_set_model_trust for the registered workflow and components
-> local_gpu_recommend_models
-> display and confirm the frozen route
-> local_gpu_start_run -> local_gpu_generate_round
```

Inspection is read-only and does not start ComfyUI or submit a prompt.
Registration copies an immutable reviewed graph only after exact confirmation;
registration does not grant model trust, public authority, or model-download
permission. Trust and route confirmation remain separate gates.

See the [retained Codex onboarding session](demo/workflow-onboarding.md). It is
real zero-GPU client evidence for discovery, inspection, registration, and trust
binding, not generated-image or quality evidence.

## Profile-Driven Run

You can instead ask the bundled Agent Skill to resolve a shipped route from a
visual brief. For example:

> Create one complete lighthouse environment illustration with no people, text, logo, or watermark. Reuse my existing local backend and model, keep downloads and model switching disabled, use at most two successful rounds, and ask me before finalization.

Before generation, the Agent should show the results of `local_gpu_discover_models`, any required `local_gpu_set_model_trust` action, `local_gpu_recommend_models`, and the exact selected route. It should wait for your confirmation before `local_gpu_generate_round`, display each retained image for review, and wait for a later byte-bound finalization confirmation.

Both paths require an already-running supported backend and model. UI-format
conversion, custom nodes, img2img, inpaint, regional/two-stage onboarding,
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
