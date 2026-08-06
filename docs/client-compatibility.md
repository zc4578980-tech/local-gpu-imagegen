# Client Compatibility

## Bootstrap Before Client Setup

An existing environment can take the read-only `bootstrap status` fast path. A
zero-environment user must inspect `bootstrap plan` and then provide the exact
displayed confirmation to `bootstrap apply`; downloads, licenses, SHA-256
hashes, disk/VRAM effects, resumable transfer state, and bounded rollback are
explicit. This guided path supports Windows 10/11 x64 NVIDIA only (10 GiB VRAM,
30 GiB free disk); Docker is not required and bootstrap readiness does not prove
image generation.

## Verified Setup Boundary

The Codex and Claude Code official CLI setup contracts are parsed and checked
against the same version-pinned `uvx` command:

```text
uvx --from local-gpu-imagegen==0.8.3 local-gpu-imagegen serve
```

At apply time, setup resolves `uvx` to an executable path before delegating to
the client's official CLI. For each contract, the model-free verifier requires
that launcher to be executable, launches the equivalent local stdio server,
checks its `0.8.3` server identity and protocol version, and requires exactly seventeen tools. This is a **Configuration contract** backed by each client's
official CLI setup shape, launcher resolution, and equivalent stdio-launch
verification. It is not a real hosted LLM session, UI integration test, or
proof that either client completed an image-generation run.

Run the checks with:

```shell
python scripts/verify_client_configs.py
```

The report deliberately returns `hosted_client_session: false` because this verifier covers setup and stdio contracts only. Setup verification does not establish that a hosted client generated an image.

The retained Codex `0.7.0` generation is historical evidence and is not a v0.8 release-set record. The retained Codex `0.8.0` workflow-onboarding session is zero-GPU evidence and is not generation evidence. Separately, a current-v0.8 Codex managed-MCP live gate and its separately approved bounded replacement produced two private, reviewed, ineligible runs. They are fail-closed local development evidence, not publishable release-set artifacts, finalized images, or proof of image-quality improvement. Claude Code hosted generation remains pending. None of these runtime facts are inferred from the setup verifier.

## Codex

Preview the exact official setup plan without changing configuration:

```shell
uvx local-gpu-imagegen setup codex
```

Apply it explicitly, then remove it when no longer needed:

```shell
uvx local-gpu-imagegen setup codex --apply
codex mcp remove local-gpu-imagegen
```

## Claude Code

Preview, apply, and remove the user-scoped official setup:

```shell
uvx local-gpu-imagegen setup claude-code
uvx local-gpu-imagegen setup claude-code --apply
claude mcp remove --scope user local-gpu-imagegen
```

The project delegates mutation to each client's official `mcp add` command. It does not directly edit TOML or JSON configuration files.

An entry created by the earlier bare-command setup may exist while still being
unable to launch after the temporary `uvx` process exits. The corrected setup
compares the observed command with the expected resolved launcher. If it reports
`client_setup_drift`, use the selected client's remove command above, then apply
setup once more. It fails closed instead of overwriting an existing entry.
Starting ComfyUI does not repair an MCP launcher failure; backend reachability
is a separate check after the client has loaded the server.

## Legacy Claude Desktop Template

`local-gpu-imagegen config claude-desktop` still renders a legacy JSON template. The verifier parses it and launches an equivalent stdio process, but it is not an official guided setup contract or a hosted-session claim.

## Unverified client templates

Other MCP clients can adapt the same stdio command and arguments, but no other named-client configuration or hosted session is currently verified:

```json
{
  "command": "uvx",
  "args": [
    "--from",
    "local-gpu-imagegen==0.8.3",
    "local-gpu-imagegen",
    "serve"
  ]
}
```

Do not infer compatibility from this generic template. Client-specific configuration keys, environment handling, working directories, and image-content rendering can differ.
