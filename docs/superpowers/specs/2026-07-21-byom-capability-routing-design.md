# BYOM Discovery and Capability Routing Design

## Status

Approved interactively on 2026-07-21. This document specifies the v1.0 BYOM and capability-routing design. Implementation requires a separate written plan.

## Product Position

The project is not a replacement for local image models. It is an Agent-native control plane that discovers user-owned local models, selects an appropriate approved model for a visual-asset task, executes through a bounded local backend, and retains reviewable and reproducible evidence.

Natural-language prompting alone is not a differentiator. A strong model may already follow natural-language instructions better than an Agent-authored prompt. The product must instead reduce model-selection work, integrate project context, preserve authorization boundaries, normalize execution across backends, and carry outputs through review, revision, and delivery.

## Problem

The current production catalog is static. It enables one exact AUTOMATIC1111 checkpoint and rejects any model that is not represented by a repository-owned JSON record with approved license metadata. The backend contract accepts only `webui` and `diffusers`, and the runtime has no ComfyUI adapter. This is safe but prevents users from bringing an existing local model library and makes a single model responsible for tasks outside its demonstrated strengths.

## Goals

- Support user-owned local models exposed by AUTOMATIC1111/Forge and ComfyUI.
- Discover models without copying, moving, loading, or downloading their weights.
- Permit progressively authorized API, folder, common-location, and full-drive discovery.
- Separate approval for private local generation from eligibility for public evidence.
- Rank trusted available models using explicit capabilities and evidence levels.
- Display one exact recommendation and at most two alternatives before confirmation.
- Freeze model, backend, identity record, workflow template, and prompt dialect for a run.
- Preserve the existing durable manifest, review, immutable revision, and evidence boundaries.

## Non-Goals

- Supporting arbitrary backend plugins or third-party executable adapters in v1.0.
- Supporting public Internet image endpoints.
- Downloading models, LoRAs, VAEs, custom nodes, or workflows.
- Inferring a model license or capability from its filename alone.
- Promising that routing improves the pixels produced by a selected model.
- Executing arbitrary ComfyUI workflows or unknown custom nodes.
- Cross-model hot revision in v1.0.
- Recursively scanning any disk without a post-plan user confirmation.

## v1.0 Backend Scope

### AUTOMATIC1111 and Forge

The existing `webui` backend remains compatible with AUTOMATIC1111-style APIs. Discovery uses the configured API to list checkpoints and obtain available identity fields. Execution retains txt2img, img2img, and inpaint support through the current normalized result contract.

### ComfyUI

A new `comfyui` backend supports model discovery and generation through reviewed workflow templates. The adapter submits a validated graph, polls or observes task state, retrieves the named output, and returns the same normalized backend result required by the run engine.

### Deferred backends

The existing Diffusers compatibility path remains available but is not expanded as part of BYOM v1.0. Generic local HTTP adapters, InvokeAI, SwarmUI, and arbitrary plugin SDKs are deferred until the two selected backends have retained integration evidence.

## Considered Architectures

### Static records only

Users would manually author model JSON. This is safe but offers poor onboarding and does not solve discovery. It is not selected.

### Dynamic discovery with a local trust overlay

This is selected. Backend and filesystem discovery produce untrusted inventory records. A separate user-local trust registry records private-use approval, public metadata, capability declarations, workflow bindings, and user preferences. A merged catalog exposes only models valid for the requested authorization scope.

### Arbitrary adapter SDK

An open adapter SDK would maximize backend reach but introduce executable extension, dependency, versioning, and supply-chain boundaries before the core workflow is proven. It is not selected for v1.0.

## Components

### `BackendAdapter`

A narrow protocol with independently testable methods:

- `probe`: report backend identity, version, endpoint class, and readiness;
- `discover`: return backend-visible model identities without changing backend state;
- `generate`: execute one already validated and confirmed generation request;
- `cancel_or_query`: inspect or cancel a known submitted backend job when supported.

Adapters do not approve models, route tasks, mutate trust, or interpret user intent.

### `WebUIAdapter`

Encapsulates AUTOMATIC1111/Forge API discovery, checkpoint binding, generation, and loaded-model verification. It replaces backend-specific branching that currently lives directly in the generation script while preserving the public `webui` backend identifier.

### `ComfyUIAdapter`

Encapsulates ComfyUI system probing, model-list discovery, validated workflow submission, job identity, status polling, cancellation/query, output retrieval, and normalized errors. It accepts only a resolved workflow from `WorkflowTemplateRegistry`.

### `DiscoveryService`

Plans and executes API or filesystem discovery. It owns scope hashing, exclusion rules, progress, cancellation, safe directory walking, candidate indexing, and selected-candidate fingerprinting. It never grants trust.

### `TrustRegistry`

Stores user-local approvals, fingerprints, evidence scope, capability overrides, workflow bindings, and preferences. It uses atomic writes and never enters the Git repository.

The default location follows the operating system user-data convention. `LOCAL_GPU_IMAGEGEN_STATE_DIR` may override it. Tests always inject an isolated temporary state directory.

### `ModelCatalog`

Merges:

1. repository-owned public templates;
2. current discovered inventory;
3. local trust records;
4. runtime backend readiness.

The existing `ProfileRegistry` continues to own use-case and style profiles. Model loading and eligibility move into the dedicated catalog so static profile composition and user-private model state do not share one responsibility.

### `CapabilityRouter`

Transforms a resolved visual brief into hard capability requirements and deterministic soft ranking. It returns one recommendation and at most two alternatives with machine-readable reasons, evidence levels, and limitations. It never invokes a backend.

### `PromptCompilerRegistry`

Selects a prompt strategy by confirmed model family or explicit prompt dialect. Known SD1.5 tag-oriented checkpoints may receive concise tag prompts. Instruction-following families receive natural-language instructions. Unknown models use a conservative natural-language compiler. No compiler may claim model capabilities not present in the catalog.

### `WorkflowTemplateRegistry`

Stores versioned, repository-reviewed ComfyUI workflow templates and their parameter bindings, supported operations, required node classes, model-family compatibility, and output node. User-imported workflows must pass the same validator before a local registration can reference them.

## MCP Surface

BYOM adds three MCP tools to the current twelve-tool surface:

### `local_gpu_discover_models`

The tool has explicit `plan` and `execute` phases.

- `plan` returns a short-lived plan ID, exact API endpoints or roots, extensions, exclusions, scan mode, and cost warning.
- `execute` requires the unchanged plan ID and exact confirmation value. It returns progress-aware discovery results and never approves them.

### `local_gpu_set_model_trust`

Actions are `approve_private`, `approve_public_candidate`, and `revoke`.

- Private approval requires an exact current identity record and a post-display user confirmation. A cryptographic file fingerprint is preferred; an explicitly disclosed backend binding is permitted for private-only use when a LAN API cannot expose model bytes or a strong backend hash.
- A public candidate additionally requires source, SHA-256, license identifier, license URL, and output-redistribution status.
- Formal public acceptance still requires the existing acceptance-authority gate for the exact backend/model combination. A trust record alone cannot authorize release evidence.

For ComfyUI, the trust call may reference a user-selected workflow JSON. The tool validates it before copying a normalized, inert workflow record into the user state directory and binding it to the approved model. It never executes the source workflow during approval.

### `local_gpu_recommend_models`

Accepts normalized task requirements and authorization scope. It returns the ranked recommendation set and explanations. It returns no eligible model rather than weakening a hard requirement.

`local_gpu_list_profiles` gains an optional `authorization_scope` of `private` or `public_evidence` and returns the merged, currently available catalog for that scope. Existing start and branch tools continue to require one exact `model_choice` and backend after confirmation.

If the approved configurable-budget design is implemented later, that tool raises the eventual total from fifteen to sixteen. BYOM implementation and tests must not hard-code an outdated twelve-tool claim.

## Discovery Authorization

Discovery has four user-visible levels:

1. `api_only`: configured and ready local backend APIs;
2. `selected_folders`: one or more user-selected roots;
3. `common_locations`: an exact proposed list of conventional model locations;
4. `full_drive`: exact selected drive roots and exclusions.

The default is `api_only`. Every broader level requires the tool to display a plan before execution. A generic earlier approval does not authorize a later broader plan.

### Two-stage filesystem discovery

Stage one indexes only:

- local path;
- filename and extension;
- byte size;
- modification timestamp;
- safe sidecar JSON or safetensors metadata that can be read without model loading.

It does not compute full hashes for every large file. The user selects candidates after indexing. Stage two computes SHA-256 for selected candidates and creates fingerprintable discovery records.

`.ckpt` files are opaque. Discovery never calls `torch.load`, unpickles model files, imports adjacent Python, or invokes model tooling.

### Filesystem boundaries

- Directory walking supports progress and cancellation.
- It does not follow symlinks, junctions, or reparse points. A target may be scanned only when selected as a separate resolved root.
- System directories, recycle bins, dependency caches, and network drives are excluded by default.
- The user may explicitly include a normally excluded local root in a new plan.
- Network-drive scanning requires a separate exact root confirmation and remains different from a LAN generation endpoint.
- Scan cancellation preserves an untrusted partial inventory marked `incomplete`; it creates no trust record.

## Network Boundaries

- Loopback HTTP endpoints are local by default.
- A LAN endpoint requires separate confirmation after a notice that prompts, input images, and masks will be transmitted to that host.
- Endpoint identity and base URL are frozen for a confirmed run.
- Public Internet endpoints are rejected in v1.0.
- Requests enforce response-size limits, timeouts, job IDs, and structured errors.
- No BYOM state file stores API keys or credentials.

## Model Identity and Trust

### Discovery identity

A discovery record contains backend, endpoint identity or safe local path, backend-visible model name, format, byte size, modification timestamp, optional metadata, optional SHA-256, and `identity_strength`.

`identity_strength` is:

- `cryptographic` when a local file SHA-256 or strong backend-reported content hash is available;
- `backend_binding` when only the frozen endpoint identity and exact backend-visible model identifier can be verified.

A backend binding may be explicitly approved for private use, but the confirmation must state that same-name byte replacement cannot be detected. Public evidence always requires a cryptographic SHA-256.

### Private approval

An explicitly approved private model may generate local private outputs even when source or license metadata is incomplete. Its outputs and model facts are excluded from public acceptance packages, README showcases, and release claims.

### Public candidate

A public candidate requires complete source, license, hash, and redistribution metadata. It is only potentially eligible. The strict evidence exporter still checks the exact approved authority file and observed backend/model facts.

### Drift detection

Cryptographic approval stores the full fingerprint plus low-cost identity fields. Before each run the catalog verifies backend-visible identity and the low-cost fields. A changed size, timestamp, backend hash, or binding invalidates trust, triggers a full re-fingerprint where possible, and requires new approval.

Backend-binding approval revalidates the endpoint identity, exact model identifier, workflow binding, and currently reported model list before each run. It cannot detect byte replacement under the same identifier; that limitation remains visible in the route and manifest. No automatic model substitution occurs.

## Capabilities and Evidence

### Hard capabilities

- operations: txt2img, img2img, inpaint;
- backend and model family;
- supported dimensions or resolution class;
- VRAM class;
- negative-prompt behavior;
- required workflow template and node classes;
- prompt dialect;
- backend-local availability and trust scope.

### Soft affinity tags

- anime and illustration;
- photorealism;
- environment and architecture;
- complex objects and vehicles;
- presentation safe areas;
- UI visual assets;
- text rendering;
- character consistency.

### Evidence levels

- `declared`: repository template or user declaration only;
- `observed`: a retained local run completed through the normalized contract;
- `benchmarked`: a fixed brief passed the applicable visual and evidence gate.

The system never converts marketing copy, a filename, or private approval into `observed` or `benchmarked`. User overrides remain `declared` until independent evidence exists.

## Routing Algorithm

1. Normalize the brief into operation, profile, style, dimensions, content needs, preservation needs, authorization scope, and local resource constraints.
2. Hard-filter by backend readiness, operation, trust scope, dimensions, VRAM, safe workflow availability, and public-evidence requirements.
3. Score remaining candidates by profile/style affinity, benchmark evidence, observed local success, explicit user preference, and model-specific recommended settings.
4. Break ties by `benchmarked > observed > declared`, then explicit user pin, then a stable model ID ordering.
5. Return one exact recommendation and at most two alternatives with score components, limitations, and evidence levels.
6. Display model, backend, identity strength and either hash prefix or backend binding, workflow template version, prompt dialect, dimensions, and budget in the confirmation summary.
7. Freeze the confirmed selection for the run.

A model failure or poor review cannot trigger a silent switch. Switching retains existing artifacts and starts a newly confirmed model boundary.

## Budget Integration Order

The model route resolves before compute-preset resolution because model recommendations determine meaningful dimensions, steps, guidance, and optional postprocessing. The approved compute-budget design remains valid, but its implementation follows BYOM so `quick`, `balanced`, and `quality` can resolve against the chosen model instead of global defaults.

## Run and Revision Behavior

The run request freezes:

- stable catalog model ID, local identity token, and identity strength;
- backend type and endpoint identity;
- workflow template ID and version where applicable;
- prompt dialect/compiler ID and version;
- trust scope;
- exact generation plan and budget.

Backend output still passes the normalized result validator before retention. Manifest attempts record the actual backend-reported model identity and workflow job ID where available.

Immutable hot revisions use the parent model and backend in v1.0. If the parent model lacks the required edit operation, the Skill may offer prompt refinement within the existing capability or propose a separately confirmed new root run. It does not silently route a child to another model.

## ComfyUI Workflow Safety

### Shipped templates

Each template declares an exact allowed node-class set, parameter bindings, graph-size ceiling, supported operations, model-family compatibility, output node, and template version. Submission is rendered from structured parameters rather than arbitrary string replacement.

### Imported workflows

An imported workflow enters through `local_gpu_set_model_trust`, is copied only after validation, and remains inert until a confirmed generation. The validator rejects:

- unknown or unapproved custom node classes;
- Shell, Python, script, arbitrary process, or code execution nodes;
- download, arbitrary HTTP, webhook, or remote-fetch nodes;
- arbitrary file-write nodes or paths;
- absolute model paths not exposed by the ComfyUI model API;
- excessive graph size, batch, steps, dimensions, or output count;
- missing required model, prompt, seed, sampler, or output bindings;
- ambiguous output ownership.

Changing workflow bytes, node classes, bindings, or template version invalidates its registration and any unseen confirmation.

## Failure and Recovery

Structured failures distinguish:

- backend unavailable or unsupported version;
- discovery plan expired, changed, canceled, or escaped scope;
- model identity incomplete or drifted;
- model untrusted for the requested scope;
- no eligible route;
- workflow template missing, incompatible, unsafe, or missing required nodes;
- backend model mismatch before generation;
- ComfyUI job rejected, timed out, canceled, disappeared, or returned invalid output;
- local model load or VRAM failure;
- normalized output contract or artifact validation failure.

ComfyUI timeouts query the known job state before any retry. Idempotency binds backend endpoint, model identity token and strength, template version, prompt compiler version, and the complete generation plan. Invalid output never consumes a successful round. Existing artifacts remain retained when a later route or backend fails.

## Testing

### Discovery

- Fake API inventories for AUTOMATIC1111, Forge, and ComfyUI.
- Temporary filesystem trees for every discovery level.
- Plan hashing, exact confirmation, expiry, cancellation, partial inventory, exclusions, scope escape, and selected-candidate hashing.
- Symlink, junction, and reparse behavior with privilege-dependent skips where required.
- Opaque `.ckpt` handling and safe metadata parsing without imports or model loading.

### Trust and catalog

- Private approval, public-candidate requirements, revoke, atomic writes, drift, corrupt state, and state-directory overrides.
- No absolute private path or model name enters public repository fixtures or exported evidence.
- Static public templates merge with local inventory without mutating repository files.

### Routing

- Hard filters for operation, readiness, trust, dimensions, VRAM, workflow, and public scope.
- Evidence-level ordering, user pinning, stable ties, alternatives, reasons, and no-route behavior.
- Prompt compiler selection and conservative fallback for unknown families.
- No quality claim can be promoted without the required evidence.

### Adapters and workflow security

- Fake WebUI and ComfyUI servers for discovery, loaded-model verification, submission, polling, cancellation/query, output retrieval, timeout, and malformed responses.
- Malicious workflow fixtures for code execution, downloads, arbitrary HTTP, unknown nodes, path writes, excessive resource values, and ambiguous outputs.
- Normalized backend result parity across `webui` and `comfyui`.

### Regression and real acceptance

- Existing WebUI generation, durable manifests, idempotency, recovery, review, finalization, cleanup, immutable revisions, and evidence export remain covered.
- The current real AUTOMATIC1111 acceptance may continue with the already approved local model.
- Without an available real ComfyUI installation and explicitly approved model, release claims are limited to adapter and contract verification. Documentation provides an opt-in integration command for users with an existing ComfyUI backend.
- No installation, download, shared Python mutation, model enablement, remote creation, push, tag, or publication is implied by this design.

## Success Criteria

v1.0 BYOM is successful when a user can:

1. review and confirm a bounded discovery plan;
2. discover an existing model without moving or loading its weights;
3. grant private or public-candidate trust without conflating the two;
4. receive an explainable recommendation based on current backend and model facts;
5. confirm one exact model, backend, identity record, workflow, prompt dialect, dimensions, and budget;
6. generate through the correct adapter into the existing durable review workflow;
7. receive a reliable pre-generation failure when identity, trust, workflow, or capability changes.

The project must not claim support for arbitrary models. It claims support only for discovered and trusted models that match a validated adapter and workflow contract.

## Documentation Impact

- Reposition the project as an Agent-native local visual-asset control plane rather than a natural-language prompt translator.
- Add BYOM onboarding, discovery-scope explanations, trust-scope warnings, routing explanations, and backend-specific readiness checks.
- Document supported ComfyUI templates and rejected node categories.
- Separate contract-tested backends from retained real integration evidence.
- Retain explicit no-download, no-silent-switch, privacy, license, and evidence limitations.
