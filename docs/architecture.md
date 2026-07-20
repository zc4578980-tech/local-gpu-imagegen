# Architecture

## Design Goal

Keep the MCP transport small and testable while allowing image backends to evolve independently. The server should explain failures to an agent without exposing Python tracebacks as its normal error contract.

## Components

| Component | Responsibility | Must not own |
|---|---|---|
| MCP client | Sends JSON-RPC requests and consumes tool results | GPU/model execution |
| `mcp_server.py` | Protocol lifecycle, schemas, validation, dispatch, timeout, structured results | Diffusion pipeline logic |
| Subprocess boundary | Isolates backend execution and provides exit code/stdout/stderr | MCP semantics |
| `generate_image.py` | WebUI/Diffusers selection, model loading, image generation, PNG output | JSON-RPC transport |
| `check_gpu.py` | Machine-readable readiness report | Installation or environment mutation |

## Request Flow

1. The MCP client writes one JSON-RPC request per line to stdin.
2. `process_line` parses the request and preserves a parsed request ID across internal errors.
3. `handle_request` handles initialization, ping, tool listing, or tool calls.
4. Tool arguments are checked against the published input schema before a subprocess starts.
5. The server runs the readiness or generation script with a bounded timeout.
6. Script stdout is parsed as a JSON object and returned as MCP `structuredContent` plus text content.
7. Tool failures use `isError: true`; protocol failures use JSON-RPC error envelopes.

## Error Layers

| Layer | Example | Contract |
|---|---|---|
| JSON parsing | malformed JSON line | JSON-RPC `-32700`, ID `null` |
| Request validation | `tools/call.params` is an array | JSON-RPC `-32602`, original ID retained |
| Tool validation | width is not divisible by 8 | tool result with `isError: true`, category `validation` |
| Timeout | generation exceeds command timeout | tool error code `command_timeout`, category `timeout` |
| Backend process | generator exits non-zero | tool error code `backend_command_failed`, exit code retained |
| Backend response | successful process prints invalid JSON | tool error code `invalid_backend_response` |
| Readiness state | CUDA/WebUI not ready | successful tool result with `ready: false` |

Readiness is deliberately separated from execution failure. A healthy diagnostic tool must be able to report that a backend is unavailable without presenting itself as broken.

## Network Boundary

- Stdio transport is local process I/O.
- WebUI generation contacts only the configured `webui_url`; loopback is the safe local default.
- Diffusers uses `local_files_only=True` unless the caller explicitly permits downloads.
- The installer downloads packages only when directly invoked by the user.

## Compatibility Strategy

The server implements the narrow protocol surface it uses: initialize, ping, tools/list, and tools/call over newline-delimited stdio JSON-RPC. The public verification script launches this exact path without relying on an AI client. Named client compatibility remains an integration-test responsibility and should be documented only after a retained run.
