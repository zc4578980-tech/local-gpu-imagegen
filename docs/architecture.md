# Architecture

## Design Goal

Keep the MCP transport small and testable while allowing image backends to evolve independently. The server should explain failures to an agent without exposing Python tracebacks as its normal error contract.

## Components

| Component | Responsibility | Must not own |
|---|---|---|
| MCP client | Sends JSON-RPC requests and consumes tool results | GPU/model execution |
| `mcp_server.py` | Protocol lifecycle, schemas, validation, dispatch, timeout, structured results | Diffusion pipeline logic |
| `RuntimeServices` | Composes one discovery, trust, catalog, router, workflow, backend, and engine graph | User conversation policy |
| `DiscoveryService` | Plans bounded inventory, indexes metadata, fingerprints selected files, and reports cancellation | Model loading, trust, or generation |
| `TrustRegistry` | Stores exact private/public-candidate approvals and observations in user-local atomic state | Acceptance authority or repository metadata |
| `ModelCatalog` / `CapabilityRouter` | Merge current inventory/trust/readiness and issue one deterministic frozen route plus at most two alternatives | Silent fallback or weakened hard requirements |
| `WorkflowTemplateRegistry` | Validates, copies, hashes, and resolves reviewed ComfyUI graphs | Arbitrary custom-node execution |
| `BackendRegistry` | Dispatches exact WebUI/ComfyUI adapters and the Diffusers compatibility runner | Route selection |
| `AssetRunEngine` | Confirmed root/child orchestration, edit-mode mapping, previews, review, and final publication | Filesystem locking details |
| `RunStore` | Atomic manifest updates, attempt ownership, idempotency, recovery, and cleanup | Backend execution |
| `ProfileRegistry` | Validated Profile/style/model catalog loading, constraint merging, and model approval checks | Local model installation or license selection |
| `RevisionService` | Preserve/change validation, reviewed-parent lineage, and immutable child creation | Prompt policy or visual judgment |
| `MaskService` | Deterministic user/geometry masks, JPEG overlays, hashes, and explicit confirmation | Automatic segmentation or user approval |
| `RealEsrganAdapter` | Optional explicit anime-only 4x postprocessing from one configured tool root | Downloads, arbitrary commands, or automatic invocation |
| Diffusers subprocess boundary | Isolates compatibility execution and provides normalized JSON | MCP semantics or WebUI/ComfyUI routing |
| `generate_image.py` | Diffusers compatibility model loading, image generation, PNG output | JSON-RPC transport |
| `check_gpu.py` | Machine-readable readiness report | Installation or environment mutation |

## Request Flow

1. The MCP client writes one JSON-RPC request per line to stdin.
2. `process_line` parses the request and preserves a parsed request ID across internal errors.
3. `handle_request` handles initialization, ping, tool listing, or tool calls.
4. Tool arguments are checked against the published input schema before a subprocess starts.
5. `local_gpu_discover_models` freezes an `api_only`, `selected_folders`, `common_locations`, or `full_drive` plan. Broader scopes execute only after exact confirmation.
6. Discovery `index` reads bounded metadata without loading weights; `fingerprint` hashes only selected indexed candidates. Trust changes require a separate exact confirmation and write only user-local state.
7. `local_gpu_list_profiles` merges repository templates, current inventory, trust, workflow availability, and readiness for `private` or `public_evidence` scope.
8. `local_gpu_recommend_models` applies hard capability filters and returns one route plus at most two alternatives. The Agent displays the exact route and obtains a new post-display confirmation.
9. `AssetRunEngine` consumes the single-use `route_token`, persists endpoint/model/workflow/compiler identity, and rechecks it before backend work.
10. Revision services copy the reviewed parent source or validate a confirmed mask; a child inherits the parent route and cannot override it.
11. The exact WebUI, ComfyUI, or Diffusers compatibility adapter returns one normalized result. Only a validated PNG and matching identity consume a successful round.
12. Structured data is returned as MCP `structuredContent` plus text content; tool failures use `isError: true`, while protocol failures use JSON-RPC error envelopes.

Before step 9, the Agent Skill asks only for missing high-impact boundaries, displays the exact route and run summary, and requires post-display confirmation. On a vision-capable host it displays and inspects the original full-resolution image, records structured visual checks, and chooses refine or explore when a required check fails or is uncertain. An eligible review exposes quality status `candidate`; the Agent displays `finalize:<run_id>:<round_number>:<image_sha256>` and stops until a later user message supplies that exact value. A text-only host stops after one retained round without inventing review evidence or finalizing it.

## Discovery, Trust, And Frozen Routes

`api_only` contacts only explicitly configured WebUI/ComfyUI adapters. `selected_folders`, `common_locations`, and `full_drive` plans show roots, exclusions, endpoint transmission, expiration, and a scope hash before scanning. Filesystem traversal never follows symlinks, junctions, or reparse points; `.ckpt` files are opaque and never passed to pickle, Torch, model tooling, or adjacent code.

`TrustRegistry` defaults to the OS user-state directory and can be moved with `LOCAL_GPU_IMAGEGEN_STATE_DIR`. `backend_binding` identifies only the model currently reported by one endpoint and remains `private`. For reviewed split workflows, a non-mutating inspection joins current ComfyUI loader identities to explicitly fingerprinted filesystem identities, then hashes the primary model, text encoder, VAE, and workflow identity into one canonical component bundle. The bundle digest is frozen in trust confirmation, catalog resolution, route tokens, manifests, and public evidence. Public candidacy additionally requires component-by-component source/license/redistribution metadata and still cannot bypass acceptance authority.

A route freezes authorization scope, backend, endpoint identity, model ID and identity token, workflow/template version, prompt compiler/version, operation, dimensions, and normalized requirements. The route is part of run idempotency. Identity drift, compiler drift, or a backend result that reports another route fails before a successful round is retained. Root and child runs enforce no silent model switch.

## Durable Run State

Each high-level run lives under `outputs/runs/<run_id>/` by default. `manifest.json` is the durable source of truth for the confirmed request, attempt history, retained rounds, reviews, warnings, final selection, and monotonically increasing revision. The output root can be replaced with `LOCAL_GPU_IMAGEGEN_OUTPUT_DIR`.

Full generated artifacts are validated full-resolution local PNG files such as `round-01.png`. The optional `round-01-preview.jpg` is a bounded JPEG preview for MCP content; it is not the authoritative image and cannot satisfy `full_resolution_inspected`. Each new review records whether a prominent human is present plus explicit limb-separation, feet/contact, hands/held-object, and text/watermark observations. Required failed or uncertain checks reject a finalize action before manifest mutation.

An eligible stored review derives, but does not persist, a candidate bound to the retained PNG SHA-256. Recovery derives the same candidate after restart. Its strongest pre-user quality status is `candidate`; it becomes publication authority only when a later user message returns the exact `finalize:<run_id>:<round_number>:<image_sha256>` value. Finalization verifies this value before postprocessing and again under the run lock, copies that exact round through `final.pending.png`, and atomically publishes `final.png` before committing final manifest metadata.

New previews use `round-NN-preview.jpg`. Stored manifests using the legacy `round-NN.preview.jpg` name remain readable; loading or retrying them does not rewrite their retained path.

Generation attempts carry an idempotency key plus a hash of their confirmed request. The same key and request can return a retained completed round without rerunning the backend. A conflicting request is rejected. Run locks include process identity so stale ownership can be reclaimed without taking a live attempt. If interruption occurs after the PNG is retained, the next matching call can resume preview creation rather than regenerate the image.

Run responses expose `recoverable_next_actions`, derived from persisted state. A run permits one to three successful rounds; failed backend attempts do not consume that budget. Review eligibility comes from one shared predicate covering the Profile rubric, hard failures, preservation results, and structured visual checks. Ineligible reviews expose refine/explore while budget remains and never expose finalization. Existing finalized manifests with `needs_user_review` remain readable, but unfinalized legacy reviews without visual checks fail closed and cannot create a candidate. Eligible publication produces `accepted`; finalization does not replace the nomination with a weighted-best candidate.

## Immutable Revision And Mask Flow

`RevisionService` branches only from a successful reviewed parent round. It copies the selected PNG to the immutable child path `parent-source.png`, records parent run/round/image hash plus the preserve/change contract, and never updates the parent manifest. Prompt refinement maps to backend txt2img without a source image; img2img and inpaint inject the child source plus the contract's validated denoising strength.

`MaskService` operates only on an inpaint child. It accepts either one user mask path or normalized rectangle/polygon geometry, stores a grayscale mask and visible JPEG overlay under `masks/`, and records source/mask hashes. A confirmed mask is revalidated immediately before generation. Missing, unconfirmed, foreign-run, or changed masks fail before backend invocation; changed hard preserve targets make the reviewed child ineligible.

## Error Layers

| Layer | Example | Contract |
|---|---|---|
| JSON parsing | malformed JSON line | JSON-RPC `-32700`, ID `null` |
| Request validation | `tools/call.params` is an array | JSON-RPC `-32602`, original ID retained |
| Tool validation | width is not divisible by 8 | tool result with `isError: true`, category `validation` |
| Timeout | generation exceeds command timeout | tool error code `command_timeout`, category `timeout` |
| Backend process | generator exits non-zero | tool error code `backend_command_failed`, exit code retained |
| Backend response | successful process prints invalid JSON | tool error code `invalid_backend_response` |
| Discovery plan | plan expired or scope changed | `discovery_plan_expired` or `discovery_plan_changed`; no scan starts |
| Endpoint policy | public endpoint or unconfirmed LAN transmission | `public_endpoint_rejected` or `network_scan_confirmation_required` |
| Capability route | no hard-match model or stale route | `no_eligible_model`, `route_confirmation_expired`, or `model_identity_drifted` |
| ComfyUI workflow | unknown/unsafe node, binding, or changed registered copy | `invalid_workflow_template` or `workflow_registration_drifted` |
| ComfyUI job | submission, timeout, disappearance, rejection, or cancel | distinct `comfyui_*` result/error states; no fabricated success |
| Readiness state | CUDA/WebUI not ready | successful tool result with `ready: false` |
| Visual review | required check failed/uncertain while requesting finalization | `visual_checks_require_revision`; review is not stored |
| Final confirmation | missing, stale, wrong-round, wrong-hash, or ineligible candidate confirmation | `finalization_confirmation_mismatch`; no final artifact is published |
| Run transition | generation before review or premature finalization | structured state/conflict tool error |
| Revision lineage | missing/changed parent source or wrong fixed edit mode | structured validation/conflict error; parent remains unchanged |
| Mask confirmation | missing, unconfirmed, or changed mask | `mask_not_confirmed` or `mask_changed_since_prepare`; backend is not invoked |
| Artifact validation | retained path, digest, or PNG is invalid | structured artifact tool error; no publication |

Readiness is deliberately separated from execution failure. A healthy diagnostic tool must be able to report that a backend is unavailable without presenting itself as broken.

## Model And Postprocess Boundaries

High-level runs require an exact current discovery identity, the requested trust/authority scope, and a confirmed route. No model weights are bundled. The repository template `civitai/anything-v5@30163` describes one reviewed existing local WebUI checkpoint; other models require explicit user-local trust and do not become public-evidence authority merely because a backend reports them. Model quality still comes from the user's model.

The ComfyUI adapter executes the shipped `sd15-txt2img-v1`, `sdxl-txt2img-v1`, `z-image-turbo-txt2img-v1`, and `anima-txt2img-v1` workflows or a normalized local copy that passes the same allowlist. Primary model identity is bound to either `CheckpointLoaderSimple.ckpt_name` or `UNETLoader.unet_name`, including the loader identity in discovery and route tokens. The split-model templates pin reviewed `CLIPLoader`, `VAELoader`, conditioning, latent, sampling, decode, and output nodes. Shell, Python, script/process, command execution, HTTP/download/fetch/webhook behavior, unknown custom nodes, unbound fields, traversal paths, and resource overruns are rejected before submission.

The templates grant no model trust or license authority and do not install weights. Local development validation retained successful project-adapter calls for Z-Image and Anima; those two calls are not public acceptance evidence and do not prove visual quality, portability, commercial rights, or the complete 9+3 matrix.

`RealEsrganAdapter` is a separate optional finalization boundary. Its tool root comes only from `LOCAL_GPU_IMAGEGEN_REALESRGAN_DIR`, and its supported model names are exactly `realesrgan-x4plus-anime` and `realesr-animevideov3-x4`. It invokes no arbitrary executable/model path and does not download a binary or model. No postprocess request means no adapter call, including when the stored policy is `auto`; an explicit request also requires the confirmed `anime` style.

Success preserves the original `final.png`, atomically publishes `final-upscaled.png`, and records the model, 4x scale, relative source/output paths, SHA-256 values, dimensions, and MIME types under final postprocess metadata. Failure returns the original final with `postprocess_unavailable` or `postprocess_failed`; a cleanup problem adds `postprocess_cleanup_failed` and may leave exact-name diagnostic residue. Real binary/GPU execution, output quality, performance, and VRAM remain unverified.

## Network Boundary

- Stdio transport is local process I/O.
- Loopback WebUI/ComfyUI endpoints are local. Each LAN endpoint requires exact transmission confirmation; public internet endpoints are rejected.
- Diffusers uses `local_files_only=True` unless the caller explicitly permits downloads.
- Discovery, trust, and generation never accept or persist credentials; private model paths and endpoint identities are removed from public evidence.
- The installer downloads packages only when directly invoked by the user.

## Compatibility Strategy

The server implements the narrow protocol surface it uses: initialize, ping, tools/list, and tools/call over newline-delimited stdio JSON-RPC. The public verification script launches this exact path without relying on an AI client, output directory, model, or GPU import. Named-client compatibility and release acceptance remain separate integration responsibilities.

Public v0.6.1 contract evidence is Mocked/model-free. The deterministic matrix uses real registry/engine/store/revision/mask logic for nine fixed briefs and three child revisions, but fake backend and postprocessor boundaries; it is not real Codex, vision, model, GPU, or Real-ESRGAN acceptance evidence and does not prove visual quality. WebUI and ComfyUI adapters are contract-tested. The genuine SDXL demo and named-client records remain pending until their retained artifacts validate; no complete real 9+3 acceptance matrix is retained.
