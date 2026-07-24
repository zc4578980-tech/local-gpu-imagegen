# Safe ComfyUI Workflow Onboarding Design

**Date:** 2026-07-24

**Status:** Approved

**Branch:** `codex/v080-workflow-onboarding`

## Capability

Local GPU Imagegen 0.8 will let an Agent inspect and immutably register an
existing, unambiguous ComfyUI `txt2img` API workflow without asking the caller
to supply node IDs. The Agent will show the exact source hash, normalized
workflow identity, inferred bindings, model components, owned output, and
limitations before presenting a digest-bound confirmation for a later user
message.

Registration is not model trust and is not public-use authority. A registered
workflow becomes usable only through the existing explicit model-trust flow.

This capability deepens the existing safe imported-workflow path. It does not
create a general ComfyUI graph editor, graph repair system, or custom-node
runtime.

## User Outcome

Today, the imported-workflow path is technically safe but shallow for callers:
`local_gpu_set_model_trust` requires both `workflow_path` and a low-level
`workflow_binding` containing node IDs. A user with an ordinary ComfyUI
workflow should instead be able to point the Agent at one local JSON file and
receive one of two truthful outcomes:

1. a complete, reviewable proposal that can be confirmed and registered; or
2. a structured explanation of why the graph is unsafe, unsupported,
   ambiguous, or not yet bound to a current local model identity.

The feature is complete for its declared topology set when the registered ID
can be consumed by the existing trust, recommendation, and generation path.
Broad compatibility with arbitrary graphs is not part of that definition.

## Scope

### Supported input envelopes

- One explicitly supplied local JSON file, at most 2 MiB.
- A bare ComfyUI API-format graph object.
- A wrapper containing exactly one API-format graph under `prompt`.
- Extra wrapper metadata is ignored. It is not copied into the registered
  document or included in the semantic workflow identity.

The source must be a regular file. Symbolic links, junctions, Windows reparse
points, directories, URLs, archives, clipboard input, and directory scans are
rejected.

### Supported operations and topologies

Only ordinary `txt2img` is supported. The graph must have one unambiguous
owned path from model and conditioning inputs through one sampler and latent
source to one saved output.

Two existing safe topology families are supported:

- **Single checkpoint:** exactly one `CheckpointLoaderSimple` primary model.
- **Split model:** exactly one `UNETLoader` primary model, with at most one
  role-unique `CLIPLoader` and `VAELoader` required by the connected path.

Both families may use only the existing imported-workflow safe-node and
safe-input allowlist. Optional reviewed pass-through nodes, such as the
currently allowed model-sampling or conditioning nodes, are accepted only
when the connected path remains unique and the existing validator accepts the
fully inferred binding.

Node IDs and JSON key order are irrelevant. Inference follows reviewed node
classes, input roles, and graph edges.

### Explicit exclusions

- ComfyUI UI-format conversion from `nodes`, `links`, and `widgets_values`.
- `img2img`, inpainting, regional composition, and two-stage composition.
- Multiple primary loaders, samplers, latent sources, or owned outputs.
- Custom nodes or new node classes, even when they are installed locally.
- Manual node selection, binding overrides, graph editing, graph repair, and
  automatic fallback to another workflow or model.
- Model, LoRA, runtime, or custom-node downloads.
- Workflow aliases, tags, rename, list, delete, garbage collection, or version
  history tools.

The frozen regional and two-stage implementations, tests, and negative
evidence remain unchanged. They are not inference candidates and are not
reopened by this milestone.

## Safety Invariants

1. Inspection is read-only and never writes registration or trust state.
2. Registration re-reads and completely revalidates the source; it never
   trusts an earlier in-memory graph.
3. Every inferred binding targets one existing scalar input with the reviewed
   class and field role expected by the current validator.
4. The positive prompt, negative prompt, model, sampler, latent source,
   decoder, and output must belong to one unique connected execution path.
5. The existing imported-workflow allowlist, limits, model-name checks,
   output ownership, and resource checks remain authoritative.
6. Ambiguity always fails closed. No deterministic-looking tie breaker may
   select the lowest node ID, first JSON key, shortest path, or first model.
7. A registerable proposal must bind every workflow component to exactly one
   current ComfyUI inventory identity by loader class, loader input, and
   backend-visible model name.
8. A diagnostic result without exact current inventory identity cannot emit a
   registration confirmation.
9. Workflow registration never grants private trust, public-candidate trust,
   license authority, or output-redistribution authority.
10. No failed or stale registration attempt may mutate local state.

## Hash And Confirmation Contract

The onboarding result carries distinct byte and semantic identities:

- `source_sha256` is the SHA-256 of the exact source file bytes.
- `workflow_sha256` is the canonical hash of the normalized registered
  workflow payload: operation, graph, inferred bindings, owned output, and
  frozen backend model names.
- `proposal_digest` canonically binds the schema version, source hash,
  workflow hash, topology, inferred binding, owned output, and exact current
  component identity tokens.

`local_gpu_inspect_workflow` emits an exact confirmation only when the result
is registerable:

```text
register_workflow:<source_sha256>:<proposal_digest>
```

`local_gpu_register_workflow` requires the path, proposal digest, and exact
confirmation. It re-reads the file, repeats inference and inventory matching,
recomputes all identities, and compares the exact confirmation before calling
the existing atomic registration implementation.

Any byte, graph, binding, output, or inventory drift invalidates the old
confirmation. Formatting-only changes therefore require a new inspection,
but, after separate confirmation, semantically equivalent JSON can resolve to
the same `imported:<workflow_sha256>` ID. Re-registering the same canonical
workflow is idempotent.

No proposal record, cache, TTL, cleanup job, or process-local confirmation
state is introduced. The contract remains valid across MCP server restarts
only while the source and exact inventory-derived proposal remain unchanged.

## States

```text
explicit local JSON
  -> invalid
     unsafe, unsupported, or ambiguous; no mutation
  -> diagnostic
     topology and bindings are inferable, but exact inventory identity is
     unavailable; registrable=false and no confirmation
  -> registerable
     exact current identities match; proposal and confirmation are returned
  -> stale
     registration recheck differs from the confirmed proposal; no mutation
  -> registered
     canonical immutable copy exists at imported:<workflow_sha256>
  -> trusted separately
     existing model-trust confirmation binds the registered workflow
```

Inspection does not persist a state transition. Only `registered` and the
existing trust states are durable.

## MCP Interface

The MCP surface increases from 15 to exactly 17 tools.

### `local_gpu_inspect_workflow`

Input:

```json
{
  "workflow_path": "<explicit local path>"
}
```

The bounded structured result includes:

- `status`: `diagnostic` or `registerable`;
- `registrable`;
- `source_sha256` and `workflow_sha256`;
- `topology`: `single_checkpoint` or `split_model`;
- the complete inferred standard binding;
- the owned output node identity;
- role-ordered model component descriptions;
- exact component identity tokens when available;
- explicit limitations and recoverable next actions;
- `proposal_digest` and `confirmation` only when registerable.

Offline or not-yet-discovered inspection may diagnose graph structure and
backend-visible names, but its next action is bounded ComfyUI API-only model
discovery. The tool does not start a backend or perform discovery implicitly.

### `local_gpu_register_workflow`

Input:

```json
{
  "workflow_path": "<same explicit local path>",
  "proposal_digest": "<64 lowercase hex characters>",
  "confirmation": "register_workflow:<source_sha256>:<proposal_digest>"
}
```

The result includes the immutable `registered_workflow_id`, template version,
both hashes, topology, owned output, component identity summary, and the exact
next action for model trust. It does not return the entire graph by default.

### Existing trust tool

`local_gpu_set_model_trust` gains `registered_workflow_id` with the existing
`imported:<64 lowercase hex characters>` shape. It is mutually exclusive with
both a shipped `workflow_template_id` and the legacy
`workflow_path + workflow_binding` pair.

The trust flow loads and revalidates the immutable registered copy, verifies
its current model/component identities, builds the existing component bundle,
and includes the registered workflow identity in the existing exact trust
confirmation. It never infers bindings again.

The legacy raw path and binding pair remains supported for compatibility and
advanced use. It is no longer the documented onboarding path, receives no new
features, and is not removed in 0.8.

## Module Ownership

One new concrete deep module,
`scripts/local_gpu_imagegen/workflow_onboarding.py`, owns:

- supported-envelope extraction;
- semantic graph traversal and standard-binding inference;
- topology classification and ambiguity reporting;
- source, workflow, and proposal identity construction;
- current inventory matching and registerability state;
- confirmation verification and orchestration of existing immutable
  registration.

It has one implementation and no abstract base class, factory, plugin
registry, adapter seam, or new dependency. Its narrow public interface is
inspection and confirmed registration.

`workflow_templates.py` remains authoritative for safe-node validation,
resource limits, canonical registered documents, atomic writes, and registered
copy loading. The onboarding module does not duplicate or weaken those checks.

`scripts/mcp_server.py` owns only the two schemas, nested input validation,
thin dispatch, bounded result projection, and the mutually exclusive trust
input shape. Graph traversal, inference, hashing policy, and confirmation
verification are forbidden in the MCP transport.

The existing discovery, trust registry, catalog, router, engine, run store,
and backend adapters retain their current responsibilities. The engine, run
store, and backend adapters are not changed for this capability.

## Failure Policy

Errors remain structured and stable. The implementation may reuse an existing
code when its meaning is exact; otherwise it adds narrowly scoped codes for:

- unsupported envelope or UI-format input;
- unsupported operation or topology;
- ambiguous binding/path, with candidate node IDs and roles;
- unavailable or ambiguous inventory identity;
- stale proposal or source bytes;
- invalid registration confirmation;
- drifted registered copy.

Error details may expose local node IDs and backend-visible component names to
the current local caller for diagnosis. They must not expose credentials,
model bytes, file contents, ignored wrapper metadata, or private absolute paths
in public evidence.

Pure UI-format input receives an actionable message directing the user to
enable ComfyUI developer mode and export API format. The tool does not launch
or automate the ComfyUI interface.

## Verification Strategy

### Model-free tests

- Single-checkpoint and split-model happy paths.
- Bare graph and unique `prompt` wrapper.
- Randomized node IDs, insertion order, and JSON key order.
- Reviewed optional pass-through nodes on one unique path.
- Duplicate loaders, samplers, latent sources, prompts, outputs, and mixed
  topology rejection.
- Disconnected or cross-wired conditioning, model, latent, decoder, and output
  rejection.
- Existing unsafe node, input, path, output, resource, and component fixtures.
- UI-format, multiple candidate envelopes, malformed UTF-8, oversized files,
  links, reparse points, and non-files.
- Offline diagnostic state and exact online inventory matching for single and
  split components.
- Source-byte drift, semantic drift, inventory drift, confirmation mismatch,
  idempotent registration, and registered-copy tampering.
- No mutation on every failure path.
- Legacy raw binding compatibility and mutual exclusion with registered IDs.
- Tool schema, exact 17-tool count, installed-package verification, and public
  documentation truthfulness.

Tests do not download models, start a backend, or require a GPU.

### Real-client gate

Before the capability is described as end-to-end, retain one real Codex or
Claude Code MCP client session using an isolated state directory:

```text
API-only discovery
  -> local_gpu_inspect_workflow
  -> later digest-bound user confirmation
  -> local_gpu_register_workflow
  -> local_gpu_set_model_trust with registered_workflow_id
```

The evidence must retain the genuine MCP JSON calls/results, source and
workflow hashes, proposal digest, immutable registered document identity, and
trust binding. It must validate without private paths or credentials.

This gate submits no ComfyUI prompt and requires no GPU generation. Backend
startup or a real-client session is performed only under its applicable later
authority.

### Repository gate

Run the focused onboarding, workflow-template, trust, MCP, packaging, Skill,
and documentation tests, followed by:

```text
python -m unittest discover -s tests -v
git diff --check
```

The frozen regional and two-stage workflow bytes and hashes must remain exact.

## Complexity Budget

This milestone follows minimum-code and surgical-change constraints:

- one new production module;
- no new runtime dependency;
- no abstract interface, factory, generic graph DSL, or speculative adapter;
- no new production module for aliases, proposal storage, or lifecycle
  management;
- no workflow-analysis implementation in `mcp_server.py`;
- no change to the generation engine, run store, or backend adapters;
- no node-ID or model-name special cases;
- exactly two new MCP tools.

Approximately 500 net new production lines is a review trigger, not a target.
If the capability crosses that threshold, needs another production module or
tool, or needs any forbidden ownership change above, implementation stops and
the design is reviewed before more code is added. Test code is not reduced at
the expense of trust-boundary, drift, or ambiguity coverage.

## Non-Goals

- Import every ComfyUI workflow.
- Convert UI-format graphs using live `/object_info` metadata.
- Select among ambiguous nodes interactively.
- Execute custom nodes or infer that an installed custom node is safe.
- Start ComfyUI, submit generation, or measure GPU performance during model-
  free implementation.
- Change model trust, license, or public-evidence policy.
- Repair regional or two-stage visual quality.
- Add async job control, reusable recipes, workflow management, or a web UI.
- Push, tag, publish, release, or mutate remote repository metadata.

## Acceptance Criteria

1. Both supported topology families complete inspect, later-confirmed
   registration, registered-ID trust binding, recommendation, and existing
   generation resolution without caller-supplied node IDs.
2. Every supported graph passes the existing imported-workflow validator after
   inference; no onboarding-only bypass exists.
3. Every ambiguous, unsafe, unsupported, stale, or unconfirmed case fails with
   no mutation and a structured recovery message.
4. Offline diagnosis cannot produce a registerable confirmation.
5. Source-byte confirmation, semantic registration identity, and exact current
   component identities remain independently verifiable.
6. Registration remains private and authority-neutral; existing trust and
   public-rights gates remain mandatory.
7. The legacy raw binding path still passes its current tests.
8. MCP exposes exactly 17 tools and installed-package verification agrees.
9. One separately authorized real-client, zero-GPU onboarding session is
   retained and validated before an end-to-end claim.
10. The complete model-free suite and repository checks pass with frozen
    experimental workflow bytes unchanged.

## Resolved Decisions

- Two thin MCP tools are preferable to adding more modes to the already broad
  model-trust tool.
- A single deep onboarding module concentrates complexity without adding a
  framework.
- Registration must be directly consumable by the existing trust path.
- The legacy raw binding interface remains compatible but frozen.
- Existing single-checkpoint and split-model safe topologies are both in scope.
- Ambiguity fails closed; the legacy advanced path is the escape hatch.
- Proposals are stateless and registration performs a full recheck.
- Bare API graphs and one `prompt` wrapper are accepted; UI conversion is not.
- Offline inspection is diagnostic only.
- Raw bytes bind confirmation while canonical semantics bind registration.
- Registration is separate from private/public trust and public-rights
  authority.
- One real-client, zero-GPU onboarding session is required for the end-to-end
  claim.
- No registration lifecycle management is added in 0.8.
- Regional and two-stage composition remain frozen and excluded.
