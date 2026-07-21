# Architecture

## Design Goal

Keep the MCP transport small and testable while allowing image backends to evolve independently. The server should explain failures to an agent without exposing Python tracebacks as its normal error contract.

## Components

| Component | Responsibility | Must not own |
|---|---|---|
| MCP client | Sends JSON-RPC requests and consumes tool results | GPU/model execution |
| `mcp_server.py` | Protocol lifecycle, schemas, validation, dispatch, timeout, structured results | Diffusion pipeline logic |
| `AssetRunEngine` | Confirmed run orchestration, generation plans, previews, review, and final publication | Filesystem locking details |
| `RunStore` | Atomic manifest updates, attempt ownership, idempotency, recovery, and cleanup | Backend execution |
| `ProfileRegistry` | Validated use-case profile loading and constraint merging | Model discovery |
| Subprocess boundary | Isolates backend execution and provides exit code/stdout/stderr | MCP semantics |
| `generate_image.py` | WebUI/Diffusers selection, model loading, image generation, PNG output | JSON-RPC transport |
| `check_gpu.py` | Machine-readable readiness report | Installation or environment mutation |

## Request Flow

1. The MCP client writes one JSON-RPC request per line to stdin.
2. `process_line` parses the request and preserves a parsed request ID across internal errors.
3. `handle_request` handles initialization, ping, tool listing, or tool calls.
4. Tool arguments are checked against the published input schema before a subprocess starts.
5. Compatibility tools run the readiness or generation script with a bounded timeout.
6. High-level tools delegate to `AssetRunEngine`, which validates confirmed plans before changing run state.
7. The run engine uses the same subprocess backend boundary, validates the returned PNG, and persists the transition through `RunStore`.
8. Structured data is returned as MCP `structuredContent` plus text content; a generation round may also include a bounded JPEG preview.
9. Tool failures use `isError: true`; protocol failures use JSON-RPC error envelopes.

## Durable Run State

Each high-level run lives under `outputs/runs/<run_id>/` by default. `manifest.json` is the durable source of truth for the confirmed request, attempt history, retained rounds, reviews, warnings, final selection, and monotonically increasing revision. The output root can be replaced with `LOCAL_GPU_IMAGEGEN_OUTPUT_DIR`.

Full generated artifacts are validated full-resolution local PNG files such as `round-01.png`. The optional `round-01-preview.jpg` is a bounded JPEG preview for MCP content; it is not the authoritative image. Finalization validates the caller-nominated reviewed round and current state under the run lock, copies that exact round through `final.pending.png`, and atomically publishes `final.png` before committing final manifest metadata.

Generation attempts carry an idempotency key plus a hash of their confirmed request. The same key and request can return a retained completed round without rerunning the backend. A conflicting request is rejected. Run locks include process identity so stale ownership can be reclaimed without taking a live attempt. If interruption occurs after the PNG is retained, the next matching call can resume preview creation rather than regenerate the image.

Run responses expose `recoverable_next_actions`, derived from persisted state. A run permits one to three successful rounds; failed backend attempts do not consume that budget. Review eligibility comes from the merged profile rubric and hard-failure rules. Final metadata marks the nominated reviewed round as `accepted` or `needs_user_review`; finalization does not replace the nomination with a weighted-best candidate.

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
| Run transition | generation before review or premature finalization | structured state/conflict tool error |
| Artifact validation | retained path, digest, or PNG is invalid | structured artifact tool error; no publication |

Readiness is deliberately separated from execution failure. A healthy diagnostic tool must be able to report that a backend is unavailable without presenting itself as broken.

## Network Boundary

- Stdio transport is local process I/O.
- WebUI generation contacts only the configured `webui_url`; loopback is the safe local default.
- Diffusers uses `local_files_only=True` unless the caller explicitly permits downloads.
- The installer downloads packages only when directly invoked by the user.

## Compatibility Strategy

The server implements the narrow protocol surface it uses: initialize, ping, tools/list, and tools/call over newline-delimited stdio JSON-RPC. The public verification script launches this exact path without relying on an AI client, output directory, model, or GPU import. Named client compatibility and real GPU generation remain integration-test responsibilities and should be documented only after retained evidence exists.
