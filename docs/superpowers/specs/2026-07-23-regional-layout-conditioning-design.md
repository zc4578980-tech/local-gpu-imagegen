# Regional Layout Conditioning Design

**Status:** Approved by the user on 2026-07-23
**Date:** 2026-07-23
**Target:** Add an auditable two-zone ComfyUI layout route that translates confirmed natural-language copy-space and subject placement into native regional conditioning without downloading another model.

## 1. Objective

Add a bounded `copy-subject-v1` layout capability for visual assets such as website heroes, presentation visuals, and UI banners. The Agent continues to gather natural-language intent, but generation uses two explicit normalized regions:

1. one copy-safe region; and
2. one subject region.

The Agent must display the resolved geometry, regional prompts, strengths, route, and budget before the user confirms a run. Geometry remains immutable within that run. Regional prompt wording and strength may change during a reviewed refinement.

The optional route is available to all three existing stable Profiles: `standalone-illustration`, `presentation-visual`, and `ui-visual-asset`. It does not add a fourth Profile or change ordinary prompt-only behavior for any Profile.

This feature addresses retained SDXL evidence in which prompt-only generation repeatedly omitted, misplaced, duplicated, or cropped the requested telescope and failed to preserve left-side copy space. The evidence motivates regional conditioning but does not prove that this design will improve visual quality.

## 2. Observed Capability Boundary

The project-local ComfyUI installation at the time of design is version `0.28.0`. Its installed source defines the built-in node classes:

- `ConditioningSetAreaPercentage` with required `conditioning`, `x`, `y`, `width`, `height`, and `strength` inputs; and
- `ConditioningCombine` with required `conditioning_1` and `conditioning_2` inputs.

The live probe requires those exact required-name sets and their reviewed `CONDITIONING`/`FLOAT` types. A missing, renamed, retyped, or additional required input is drift. Additional optional metadata does not by itself change the graph contract.

No ControlNet, custom node, model download, or Python package is required by the proposed graph. The ComfyUI service was not listening during the final design inspection, so installed source is design evidence only. A live route must re-check the current endpoint's `/object_info` signatures before recommendation and again before submission.

## 3. Approved Decisions

- Implement one copy-safe rectangle plus one subject rectangle, not arbitrary multi-region layouts.
- Derive the layout from natural language, display it, and require confirmation before run creation.
- Fail closed when either required ComfyUI node or its reviewed input signature is unavailable.
- Use a new `sdxl-regional-txt2img` workflow. Do not alter the existing `sdxl-txt2img` workflow or historical runs.
- Keep the public MCP surface at exactly fifteen tools.
- Keep the complete generation plan at its existing twenty top-level fields.
- Freeze layout mode and geometry in `constraints`.
- Store mutable regional prompt wording and strength in `parameters`.
- Persist the exact initially confirmed regional conditioning separately in the run request, then require the initial generation plan to match it.
- Preserve the old local trust route while allowing a second route for the same model bytes and a different workflow bundle.
- Preserve the existing `0.6.1` wheel as a reproducible artifact. A wheel containing this feature receives a new version and digest and does not overwrite the old artifact.

## 4. Non-Goals

- Arbitrary region counts, polygons, masks, automatic segmentation, drag-and-drop editing, or a frontend canvas.
- ControlNet, IP-Adapter, LoRA, refiner, new model, or custom-node installation.
- Pixel-perfect placement or a claim that regional conditioning guarantees visual compliance.
- Silent fallback to prompt-only generation.
- Changes to shared/global Python or `<local-ai-root>\envs\pytorch-vla`.
- Publication, push, tag, PyPI upload, MCP Registry publication, or GitHub release.
- Replacement or migration of retained failed runs.

## 5. User Contract

The Agent converts natural-language layout intent into this confirmed constraint:

```json
{
  "regional_layout": {
    "mode": "copy-subject-v1",
    "copy_region": {
      "x": 0.0,
      "y": 0.0,
      "width": 0.45,
      "height": 1.0
    },
    "subject_region": {
      "x": 0.68,
      "y": 0.0,
      "width": 0.30,
      "height": 1.0
    }
  }
}
```

The first generation plan includes mutable conditioning parameters:

```json
{
  "regional_conditioning": {
    "copy_prompt": "dark empty low-detail copy space",
    "copy_strength": 1.15,
    "subject_prompt": "one complete brass refracting telescope on a tripod",
    "subject_strength": 1.25
  }
}
```

A regional run request persists the same normalized conditioning object as `initial_regional_conditioning`. This is an additive confirmation record, not a generation-plan field. For the `initial` action, `parameters.regional_conditioning` must equal that persisted object. Later `refine` and `explore` actions may change it under the mutation rules below. A standard run rejects `initial_regional_conditioning` rather than ignoring it.

The displayed confirmation summary includes:

- layout mode;
- both normalized rectangles and their percentage equivalents;
- both regional prompts and strengths;
- global positive and negative intent summary;
- exact model, backend, endpoint identity, workflow, compiler, dimensions, and round budget;
- no-download, model-switch, and upscale policy.

Silence, an earlier root confirmation, or approval of another workflow does not confirm this regional route.

## 6. Validation Rules

### 6.1 Geometry

- `mode` must equal `copy-subject-v1`.
- Each region contains exactly `x`, `y`, `width`, and `height`.
- Values must be finite JSON numbers.
- `x` and `y` are in `[0.0, 1.0)`.
- `width` and `height` are in `(0.0, 1.0]`.
- `x + width` and `y + height` must not exceed `1.0`.
- The two rectangles may touch at their boundaries but must have zero interior overlap.
- Validation returns a normalized deep copy; it does not mutate caller input.

### 6.2 Conditioning

- The conditioning object contains exactly `copy_prompt`, `copy_strength`, `subject_prompt`, and `subject_strength`.
- Prompts are non-empty strings of at most 500 characters after trimming.
- Strengths are finite numbers in `[0.0, 2.0]`.
- The object is accepted only when the confirmed route and constraints use `copy-subject-v1`.
- A standard workflow rejects regional conditioning rather than ignoring it.
- A regional workflow requires regional conditioning rather than inventing defaults.
- A regional start request requires `initial_regional_conditioning`; the initial generation plan must match it exactly after normalization.
- Each existing Profile adds the single top-level key `regional_conditioning` to both `refine_mutable` and `explore_mutable`. Nested regional fields remain governed by this section's exact schema.

## 7. Architecture

```text
natural-language brief
  -> Agent Skill resolves two-zone contract
  -> CapabilityRouter probes and selects exact regional workflow variant
  -> display geometry, prompts, strengths, exact route, and budget
  -> user confirmation
  -> AssetRunEngine freezes geometry in request constraints
  -> run request retains the initially confirmed conditioning
  -> generation plan supplies current regional conditioning parameters
  -> WorkflowTemplateRegistry binds reviewed graph inputs
  -> ComfyUIAdapter revalidates node capability and exact graph
  -> local ComfyUI generation
  -> full-resolution structured review
  -> refine prompts/strengths only, or stop/finalize under existing gates
```

### 7.1 Agent Skill

The Skill gains a bounded regional-layout branch. It asks only for missing high-impact layout facts, converts them into normalized rectangles, requests a capability recommendation, and displays the exact contract and resolved route. It does not create arbitrary graphs or silently choose a region when the user's request is ambiguous.

### 7.2 Capability Router

`local_gpu_recommend_models` accepts an optional regional-layout requirement. The requirement includes the mode and normalized geometry. The route token binds that requirement together with the existing model, endpoint, workflow, compiler, dimensions, profile, style, authorization scope, and component bundle.

The router emits the regional variant only when all of these are true:

- the model capability record advertises `copy-subject-v1` through a reviewed workflow;
- the current ComfyUI endpoint reports both required node classes with the reviewed input names;
- the selected workflow and component bundle are currently trusted for the requested scope;
- all existing operation, dimension, VRAM, profile, style, and evidence filters pass.

### 7.3 Generation Plan

The existing twenty top-level fields remain unchanged. `constraints.regional_layout` stores immutable mode and geometry. `parameters.regional_conditioning` stores current prompts and strengths.

The regional start request also stores `initial_regional_conditioning`. `validate_generation_plan` compares that value only for `action=initial`. For later actions it still validates the nested object but relies on the Profile mutation allowlist. Legacy and standard run requests omit this additive field and retain their current validation path.

The mutation matrix is:

| Value | Initial | Refine | Explore | New root/revision required |
|---|---:|---:|---:|---:|
| Layout mode | set | frozen | frozen | yes |
| Copy rectangle | set | frozen | frozen | yes |
| Subject rectangle | set | frozen | frozen | yes |
| Copy prompt | set | mutable | mutable | no |
| Subject prompt | set | mutable | mutable | no |
| Copy strength | set | mutable | mutable | no |
| Subject strength | set | mutable | mutable | no |
| Seed | set | preserved | changed | no |

Every attempt request hash and retained attempt records the actual conditioning parameters used in that round.

### 7.4 Workflow Template Registry

Add shipped template `sdxl-regional-txt2img` version 1. It has the existing loader, latent, sampler, VAE, and output bindings plus reviewed regional bindings. The registry applies the immutable geometry and current conditioning parameters to a copied graph, validates the graph, and returns its canonical workflow digest.

The regional shipped document adds exactly two top-level fields to the current shipped-template schema:

- `layout_mode`, exactly `copy-subject-v1`; and
- `regional_bindings`, an object with exactly `copy_prompt`, `copy_x`, `copy_y`, `copy_width`, `copy_height`, `copy_strength`, `subject_prompt`, `subject_x`, `subject_y`, `subject_width`, `subject_height`, and `subject_strength`.

Each regional binding is the same reviewed three-segment scalar graph path used by existing bindings. The ordinary `bindings` object keeps its current exact keys. A template may contain these two additional fields only as a pair, and only for `copy-subject-v1`; standard shipped and imported templates retain their current exact field set and behavior. Imported arbitrary regional workflows are not enabled by this feature.

### 7.5 ComfyUI Adapter

The adapter accepts regional request data only with a resolved regional workflow. Before `POST /prompt`, it verifies:

- the endpoint still exposes the required node classes and input signatures;
- the graph contains only approved node classes and inputs;
- one model loader, one sampler, one output, and the expected latent dimensions remain present;
- global, negative, copy, and subject prompt values match the request exactly;
- region coordinates and strengths match the request exactly;
- the graph's model, sampler, scheduler, steps, CFG, seed, output node, and output prefix remain unchanged.

## 8. Reviewed Workflow Graph

The positive path is:

```text
global CLIPTextEncode ------------------------------+
                                                     +-> ConditioningCombine --+
copy CLIPTextEncode -> ConditioningSetAreaPercentage+                         |
                                                                               +-> ConditioningCombine -> KSampler positive
subject CLIPTextEncode -> ConditioningSetAreaPercentage -----------------------+
```

The negative prompt remains one global `CLIPTextEncode` connected to `KSampler.negative`.

The allowed classes for this workflow are:

- `CheckpointLoaderSimple`;
- `CLIPTextEncode`;
- `ConditioningSetAreaPercentage`;
- `ConditioningCombine`;
- `EmptyLatentImage`;
- `KSampler`;
- `VAEDecode`;
- `SaveImage`.

The reviewed graph contains exactly one checkpoint loader, four `CLIPTextEncode` nodes (global positive, global negative, copy, and subject), two `ConditioningSetAreaPercentage` nodes, two `ConditioningCombine` nodes, one latent node, one sampler, one VAE decode, and one output. Its exact edges, static values, and binding targets are covered by the canonical workflow digest; an allowlisted class with an extra node or edge is still rejected.

No dynamic script, execution, network, download, custom-node, or arbitrary file input is allowed.

## 9. Workflow-Bound Trust Variants

The current trust record shape already stores a component bundle containing the workflow digest, but catalog IDs are derived only from the model identity. To preserve both workflows for the same checkpoint, trust becomes route-variant aware without duplicating model bytes.

For a new bundle-backed record, derive the catalog ID from the SHA-256 of these UTF-8 bytes, with one newline separator and no trailing newline:

```text
<model identity token>\n<component bundle SHA-256>
```

The catalog ID remains `local:` followed by the first 24 hexadecimal characters.

Compatibility rules:

- Existing legacy catalog IDs remain valid and are never rewritten merely by reading them.
- Reapproval of an already stored identity-and-bundle pair updates that exact existing record.
- Approval of the same model identity with a new bundle creates a distinct catalog record.
- A legacy record that already stores the same identity-and-bundle pair keeps its legacy catalog ID when reapproved.
- Records may share a model identity token only when their catalog IDs and bundle digests differ.
- Revocation and evidence observations continue to require the exact catalog ID and identity token, so route variants cannot affect one another.
- The existing trust confirmation already contains the bundle SHA-256 and remains the authority boundary.
- Model catalog resolution emits one candidate per trusted workflow bundle. The router never substitutes one variant for another.

The registry resolves approval updates by exact `(identity_token, component_bundle_sha256)` before deriving an ID. A new bundle-backed pair receives the variant ID above. A new approval without a bundle retains the legacy model-derived ID behavior. If a truncated derived ID collides with a different identity-and-bundle pair, approval fails closed with `catalog_id_collision`; it never overwrites the existing record.

`local_gpu_set_model_trust` adds an optional `catalog_id` input without adding a tool. Callers revoking a displayed route variant supply its exact ID. For backward compatibility, an omitted catalog ID is accepted only when exactly one record matches the supplied identity token; multiple matches fail with `ambiguous_trust_variant` and list the candidate IDs. The exact selected ID and identity remain bound into the existing revoke confirmation.

The old `sdxl-txt2img` route and new `sdxl-regional-txt2img` route can therefore coexist against one installed checkpoint without copying or re-hashing model bytes after current identity has been recovered.

## 10. Failure Handling

| Condition | Required result |
|---|---|
| Invalid, out-of-bounds, or overlapping geometry | `invalid_regional_layout`; no run |
| Missing or invalid conditioning parameters | `invalid_regional_conditioning`; no attempt |
| Initial plan differs from confirmed initial conditioning | `generation_plan_mismatch`; no attempt |
| Endpoint lacks either reviewed node | `regional_layout_unavailable`; no route or backend submission |
| Node input signature changes after confirmation | `regional_layout_drifted`; no backend submission |
| Standard route receives regional parameters | validation failure; no silent ignore |
| Regional route receives no regional parameters | validation failure; no invented defaults |
| Geometry differs from confirmed run | generation-plan mismatch; no attempt |
| Workflow, bundle, model, endpoint, or compiler differs | existing drift/conflict failure; no attempt |
| Backend executes but image violates layout visually | retained successful round plus honest failed review |
| Visual review passes technical checks but not regional constraints | `explicit_constraint_violation`; no finalization candidate |
| Variant catalog ID collides or revoke omits an ambiguous ID | fail closed with `catalog_id_collision` or `ambiguous_trust_variant`; no trust mutation |

Visual noncompliance never becomes a fake backend failure and never refunds a successful-round budget.

## 11. Compatibility And Security

- The MCP tool count remains exactly fifteen.
- Existing tool fields remain valid; regional fields are optional until a regional route is requested.
- The optional trust `catalog_id` input preserves old single-record revoke calls while making variant revocation unambiguous.
- Existing `sdxl-txt2img` workflow bytes and digest remain unchanged.
- Existing manifests remain readable and are not rewritten.
- Existing trust records remain valid under their legacy catalog IDs.
- The regional workflow receives a new digest, component bundle, catalog route ID, and separate confirmation.
- The feature performs no model or dependency download.
- Local paths, trust state, failed images, credentials, and endpoint details remain excluded from tracked public artifacts.
- Runtime node probing is read-only. It does not install, enable, or modify ComfyUI nodes.

## 12. Test Design

### 12.1 Contract Tests

- Accept one valid copy-subject contract and normalize it without mutating input.
- Reject unknown fields, booleans as numbers, non-finite values, zero-size regions, bounds overflow, and interior overlap.
- Accept touching boundaries.
- Reject empty or oversized prompts and strengths outside `[0.0, 2.0]`.
- Reject regional conditioning without confirmed regional geometry and vice versa.
- Reject a regional initial plan that differs from `initial_regional_conditioning` while allowing validated later changes.
- Keep all three stable Profiles valid after adding `regional_conditioning` to their refine/explore allowlists.

### 12.2 Generation-Plan Tests

- Preserve the twenty top-level fields.
- Reject a geometry or mode change on later rounds before an attempt is created.
- Allow prompt and strength changes on refine/explore.
- Bind each conditioning change into a distinct request hash.
- Preserve existing prompt-only generation-plan behavior.

### 12.3 Workflow Registry Tests

- Load and hash the new shipped workflow deterministically.
- Bind global, negative, copy, and subject prompts exactly.
- Bind both region rectangles and strengths exactly.
- Reject unapproved nodes, inputs, edges, extra outputs, model changes, and unsafe prefixes.
- Keep the old SDXL workflow digest unchanged.

### 12.4 Adapter Tests

- Report regional capability only when both object-info signatures match.
- Reject missing nodes or signature drift before `POST /prompt`.
- Submit the exact reviewed regional graph to the fake backend.
- Reject prompt, geometry, strength, model, sampler, dimension, and output drift.
- Preserve queue/history race, timeout, cancellation, output-path, and PNG validation behavior.

### 12.5 Trust And Routing Tests

- Preserve a legacy model-derived catalog ID.
- Add a second bundle-derived catalog ID for the same identity without replacing the first.
- Update the exact existing identity-and-bundle record on reapproval.
- Preserve the legacy ID when reapproving its exact stored bundle.
- Reject a derived-ID collision without modifying either record.
- Require an exact catalog ID when one identity has multiple revocable variants while preserving unambiguous legacy revoke calls.
- Revoke and record observations against only the selected variant.
- Recommend the regional variant only for a regional requirement and a capable live endpoint.
- Never fall back to the ordinary variant when regional capability is required.
- Bind geometry, workflow, and bundle into the route token.

### 12.6 Engine And MCP Tests

- Exercise start, get, generate, review, refine, and exhausted-budget paths with a fake regional backend.
- Verify manifest retention of geometry and per-round conditioning.
- Verify full structured constraint results are still required.
- Keep the public MCP surface at exactly fifteen tools.
- Verify installed-package access to both workflows and the updated Skill.

### 12.7 Regression And Packaging Gates

- `python -m compileall -q scripts tests`
- `python -m unittest discover -s tests -v`
- parse all tracked JSON as UTF-8;
- run tracked path, credential, and candidate-artifact scans;
- `git diff --check`;
- build one new wheel into an isolated output path;
- install it into a fresh Python 3.12 environment;
- verify version, exactly fifteen tools, both workflow assets, setup dry-runs, and no repository import leakage;
- retain the old `0.6.1` wheel and its SHA-256 unchanged.

## 13. Real Verification Gate

Model-free completion does not authorize a quality claim. A real regional route requires this later sequence:

1. start or detect the current ComfyUI service;
2. perform read-only current node-signature inspection;
3. recover the exact checkpoint identity without unrelated scans;
4. inspect the new workflow binding and component bundle;
5. display and obtain exact trust/authority confirmation for the new bundle;
6. recommend and display the exact regional route and two-zone contract;
7. obtain a later route, prompt, geometry, and budget confirmation;
8. run bounded local-GPU generation;
9. inspect every original PNG and record complete reviews;
10. display a byte-bound finalize token only for an eligible candidate;
11. wait for a later user message before finalization or export.

If the regional route still fails visually, retain the negative evidence and stop. Do not expand the region count, download another control model, or extend the budget without a new design and authority decision.

## 14. Completion Criteria

The implementation milestone is complete only when:

- all model-free tests and packaging gates pass;
- old workflow, manifest, trust, and fifteen-tool compatibility tests pass;
- a new wheel is installed and verified outside the checkout;
- the old `0.6.1` wheel digest remains unchanged;
- no unapproved download, shared-environment mutation, remote operation, publication, or GPU quality claim occurs;
- `PROJECT_NODES.md` records control flow, failures, commands, results, limitations, artifact hashes, and the next authority gate.

Real visual acceptance remains a separate milestone requiring retained local-GPU evidence and the normal user confirmation gates.
