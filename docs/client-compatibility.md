# Client Compatibility

## Verified boundary

The Codex and Claude Desktop configuration contracts are parsed and checked against the same installed command:

```text
local-gpu-imagegen serve
```

For each contract, the model-free verifier launches the equivalent local stdio server, checks its server identity and protocol version, and requires the exact fifteen-tool surface. This is a **Configuration contract** and stdio-launch verification. It is not a real hosted LLM session, UI integration test, or proof that either client completed an image-generation run.

Run the checks with:

```shell
python scripts/verify_client_configs.py
```

The report deliberately returns `hosted_client_session: false`. Full named-client host acceptance remains pending until a retained session shows the client calling the server and receiving the result.

## Codex

Generate the TOML block after installing the package:

```shell
local-gpu-imagegen config codex
```

Add the emitted block to the relevant Codex configuration, then restart the client.

## Claude Desktop

Generate the JSON object after installing the package:

```shell
local-gpu-imagegen config claude-desktop
```

Merge the emitted `mcpServers` entry into the Claude Desktop configuration, then restart the client.

## Unverified client templates

Other MCP clients can adapt the same stdio command and arguments, but no other named-client configuration or hosted session is currently verified:

```json
{
  "command": "local-gpu-imagegen",
  "args": ["serve"]
}
```

Do not infer compatibility from this generic template. Client-specific configuration keys, environment handling, working directories, and image-content rendering can differ.
