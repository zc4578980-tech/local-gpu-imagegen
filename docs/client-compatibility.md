# Client Compatibility

## Verified Setup Boundary

The Codex and Claude Code official CLI setup contracts are parsed and checked against the same installed command:

```text
local-gpu-imagegen serve
```

For each contract, the model-free verifier launches the equivalent local stdio server, checks its `0.8.0` server identity and protocol version, and requires exactly seventeen tools. This is a **Configuration contract** backed by each client's official CLI setup shape plus stdio-launch verification. It is not a real hosted LLM session, UI integration test, or proof that either client completed an image-generation run.

Run the checks with:

```shell
python scripts/verify_client_configs.py
```

The report deliberately returns `hosted_client_session: false` because this verifier covers setup and stdio contracts only. Setup verification does not establish that a hosted client generated an image.

The retained Codex `0.7.0` generation is historical evidence and is not a v0.8 release-set record. The retained Codex `0.8.0` workflow-onboarding session is zero-GPU evidence and is not generation evidence. Separately, a current-v0.8 Codex managed-MCP live gate and its separately approved bounded replacement produced two private, reviewed, ineligible runs. They are fail-closed local development evidence, not publishable release-set artifacts, finalized images, or proof of image-quality improvement. Claude Code hosted generation remains pending. None of these runtime facts are inferred from the setup verifier.

## Codex

Preview the exact official setup plan without changing configuration:

```shell
local-gpu-imagegen setup codex
```

Apply it explicitly, then remove it when no longer needed:

```shell
local-gpu-imagegen setup codex --apply
codex mcp remove local-gpu-imagegen
```

## Claude Code

Preview, apply, and remove the user-scoped official setup:

```shell
local-gpu-imagegen setup claude-code
local-gpu-imagegen setup claude-code --apply
claude mcp remove --scope user local-gpu-imagegen
```

The project delegates mutation to each client's official `mcp add` command. It does not directly edit TOML or JSON configuration files.

## Legacy Claude Desktop Template

`local-gpu-imagegen config claude-desktop` still renders a legacy JSON template. The verifier parses it and launches an equivalent stdio process, but it is not an official guided setup contract or a hosted-session claim.

## Unverified client templates

Other MCP clients can adapt the same stdio command and arguments, but no other named-client configuration or hosted session is currently verified:

```json
{
  "command": "local-gpu-imagegen",
  "args": ["serve"]
}
```

Do not infer compatibility from this generic template. Client-specific configuration keys, environment handling, working directories, and image-content rendering can differ.
