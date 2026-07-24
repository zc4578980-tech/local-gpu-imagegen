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

## 5. Ask For One Bounded Image

Use this request:

> Create one complete lighthouse environment illustration with no people, text, logo, or watermark. Reuse my existing local backend and model, keep downloads and model switching disabled, use at most two successful rounds, and ask me before finalization.

Before generation, the Agent should show the results of `local_gpu_discover_models`, any required `local_gpu_set_model_trust` action, `local_gpu_recommend_models`, and the exact selected route. It should wait for your confirmation before `local_gpu_generate_round`, display each retained image for review, and wait for a later byte-bound finalization confirmation.

Optional existing ComfyUI workflows use a separate safe onboarding path for ordinary `txt2img` only:

```text
API-only discovery (when current inventory is absent)
-> local_gpu_inspect_workflow
-> display hashes, inferred binding, components, limitations, confirmation
-> later exact user confirmation
-> local_gpu_register_workflow
-> separate local_gpu_set_model_trust with `registered_workflow_id`
```

The supported graphs are single checkpoint or split model API workflows. Inspection displays `source_sha256`, `workflow_sha256`, and component identities; registration does not grant model trust. UI format, custom nodes, regional/two-stage onboarding, and implicit backend startup remain outside this path. The real-client onboarding evidence is pending.

## Roll Back Client Setup

Remove only the MCP entry created for the selected client:

```shell
codex mcp remove local-gpu-imagegen
claude mcp remove --scope user local-gpu-imagegen
```

Restart or reload the client and confirm `local-gpu-imagegen` no longer appears. This does not delete local models, backend files, or retained runs.

## First-Run Problems

Use [Troubleshooting](troubleshooting.md) for install, transport, backend, trust, route, and recovery failures. See [Client compatibility](client-compatibility.md) for deeper Codex and Claude Code setup details and the current named-client evidence boundary.
