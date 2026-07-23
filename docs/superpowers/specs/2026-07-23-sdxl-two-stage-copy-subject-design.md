# SDXL Two-Stage Copy-Subject Design

**Status:** Approved by the user on 2026-07-23
**Date:** 2026-07-23
**Target:** Replace the failed single-pass SDXL regional-control strategy with one bounded, no-download ComfyUI route that first generates a copy-safe background and then generates the subject through a fixed right-side mask.

## 1. Objective

Add a reviewed `copy-subject-two-stage-v1` route for wide visual assets. One logical generation round performs two sampling stages against the already installed official SDXL Base 1.0 checkpoint:

1. generate a complete background with protected copy space and no target subject; then
2. generate the subject through one deterministic right-side inpaint mask and composite it back over the exact base image.

The route is intended to address retained negative evidence from run `20260723T023916Z-5ef87c6453d1`. Its first round filled the left side with a bright detailed shutter and turned the requested telescope into cropped building-scale machinery. Its second round omitted the telescope, generated text and human-like artifacts, and left only a small dark area. Both rounds exhausted the confirmed budget and remain ineligible.

This design changes the control method, not the model. It does not claim that SDXL Base will pass visual acceptance. A positive quality claim still requires a separately confirmed live MCP route, retained JSON result, retained stage artifacts, full-resolution review, and an eligible final image.

## 2. Observed Capability Boundary

The live local endpoint reported ComfyUI `0.28.0`, Python `3.13.12`, PyTorch `2.13.0+cu130`, and the NVIDIA GeForce RTX 5070 Ti Laptop GPU. The design inspection was read-only. It did not submit a prompt, load the SDXL checkpoint, generate an image, or download a model, node, dependency, or workflow.

The endpoint exposed these required built-in nodes and signatures:

| Node | Required inputs | Optional inputs | Output |
|---|---|---|---|
| `VAEEncodeForInpaint` | `pixels: IMAGE`, `vae: VAE`, `mask: MASK`, `grow_mask_by: INT` | none | `LATENT` |
| `SolidMask` | `value: FLOAT`, `width: INT`, `height: INT` | none | `MASK` |
| `MaskComposite` | `destination: MASK`, `source: MASK`, `x: INT`, `y: INT`, `operation: COMBO` | none | `MASK` |
| `FeatherMask` | `mask: MASK`, `left: INT`, `top: INT`, `right: INT`, `bottom: INT` | none | `MASK` |
| `ImageCompositeMasked` | `destination: IMAGE`, `source: IMAGE`, `x: INT`, `y: INT`, `resize_source: BOOLEAN` | `mask: MASK` | `IMAGE` |
| `MaskToImage` | `mask: MASK` | none | `IMAGE` |

`MaskComposite.operation` must continue to offer `add`. Missing, renamed, retyped, newly required, or semantically incompatible inputs are drift. Optional descriptive metadata is not part of the execution signature.

The installed implementation confirms two important semantics:

- a smaller source mask can be placed at an exact integer offset inside a full-canvas destination mask; and
- `ImageCompositeMasked` clones the destination and changes only pixels selected by the supplied mask.

The approved `FeatherMask` semantics are also bound to the installed built-in implementation. For a requested side width `f > 0`, its first `f` pixels are multiplied by `(distance + 1) / f`, starting at the outer edge. `SaveImage` then clips `255 * value` and truncates it to unsigned 8-bit RGB. A 32-pixel feather therefore normally saves side-edge values beginning at `7`, while corner products may truncate to `0`. Positive saved outer-edge values are expected runtime output and must not be rejected as leakage.

`VAEEncodeForInpaint` alone is not accepted as proof that unmasked pixels remain identical. It performs a VAE encode/decode path. The final pixel-space composite and a post-output pixel comparison are both required.

## 3. Approved Decisions

- Add a new `sdxl-two-stage-copy-subject` workflow version 1.
- Add layout mode `copy-subject-two-stage-v1` without changing or deleting historical `copy-subject-v1` manifests.
- Keep the installed SDXL checkpoint and existing component identity; do not download another model.
- Keep the MCP surface at exactly fifteen tools.
- Keep external operation `txt2img`; the internal second stage is a controlled inpaint operation.
- Keep the existing twenty top-level generation-plan fields.
- Treat plan `positive_prompt` and `negative_prompt` as the base-stage prompts for this route.
- Store the subject-stage prompt, negative prompt, and denoise value under `parameters.two_stage_conditioning`.
- Freeze canvas, protected copy rectangle, subject mask rectangle, feather width, and VAE mask growth in `constraints.two_stage_layout`.
- Generate the mask inside the reviewed workflow. Do not accept a user mask path or revision `mask_id` for this route.
- Validate the saved mask against the installed `FeatherMask` ramp and `SaveImage` quantization semantics; do not replace the reviewed 21-node graph to manufacture zero-valued subject borders.
- Retain exactly one base image, one mask image, and one final image for every technically successful round.
- Permit only the final image to become a finalization candidate.
- Retain the old single-pass route for compatibility, but do not recommend it as the new public-evidence control route and never use it as fallback.
- Preserve the immutable `0.6.1` wheel. A later wheel uses a new version and digest.

## 4. Non-Goals

- ControlNet, IP-Adapter, LoRA, SDXL Refiner, another checkpoint, a custom node, or automatic segmentation.
- Arbitrary masks, polygons, user uploads, drag-and-drop positioning, or a frontend mask editor.
- More than one subject mask or more than two sampling stages.
- Automatic subject detection, automatic visual-quality scoring, or automatic finalization.
- Pixel-perfect subject placement within the mask.
- A claim that the installed SDXL Base checkpoint is an inpainting-specific model.
- Changes to shared/global Python or the separately managed learning environment.
- Extending, finalizing, exporting, or modifying any exhausted historical run.
- Push, tag, GitHub release, PyPI upload, MCP Registry publication, or public visual-quality claims.

## 5. User Contract

### 5.1 Confirmed Geometry

For the first reviewed hero route, the confirmed constraint is:

```json
{
  "two_stage_layout": {
    "mode": "copy-subject-two-stage-v1",
    "canvas": {
      "width": 1280,
      "height": 720
    },
    "copy_protected_rect": {
      "x": 0,
      "y": 0,
      "width": 576,
      "height": 720
    },
    "subject_mask_rect": {
      "x": 720,
      "y": 24,
      "width": 512,
      "height": 672
    },
    "feather_pixels": 32,
    "vae_grow_mask_by": 8
  }
}
```

The Agent displays both pixels and derived percentages before confirmation:

- protected copy region: left `45%` of the full canvas;
- protected gap between copy and subject: `144` pixels, or `11.25%` of the canvas width;
- hard subject mask: `x=56.25%`, `y=3.333333%`, `width=40%`, `height=93.333333%`;
- right margin: `48` pixels;
- top and bottom margins: `24` pixels each; and
- feather: `32` pixels inward from every edge of the subject rectangle.

The pixel values are authoritative. Percentages are display-only and must not be converted back into geometry.

### 5.2 Prompt Contract

For this route, top-level `positive_prompt` describes only the base scene. It must explicitly omit the target subject. Top-level `negative_prompt` is the base-stage negative prompt.

The nested subject contract is:

```json
{
  "two_stage_conditioning": {
    "subject_prompt": "exactly one complete freestanding brass astronomical refracting telescope, long optical tube, objective lens and eyepiece, equatorial mount, three separated tripod legs, every foot visible, fully contained inside the mask, matching the blue-hour observatory lighting",
    "subject_negative_prompt": "missing telescope, cropped telescope, incomplete telescope, duplicate telescope, giant machinery, building-sized instrument, pedestal mount, fused tripod legs, cropped feet, people, anatomy, text, letters, numbers, logo, watermark, interface, labels",
    "subject_denoise": 0.9
  }
}
```

The base prompt must request a coherent, low-detail blue-hour observatory background, a dark empty left copy area, and an unobstructed right-side floor/background. Its negative prompt must include the telescope, focal machinery, people, generated text, controls, and high-detail left-side structures.

The final `intent` and required visual constraints still describe the complete hero with the telescope. Review evaluates the final image against that intent, not against the base prompt alone.

### 5.3 Seed And Sampling Contract

- Base seed is the confirmed round seed `S`.
- Subject seed is `(S + 1) mod 2^64`.
- Both stages use the confirmed sampler, scheduler, step count, and guidance scale.
- Base denoise is exactly `1.0`.
- Subject denoise is confirmed under `two_stage_conditioning` and must be from `0.80` through `1.00` inclusive.
- Initial recommended subject denoise is `0.90`.
- Batch size is exactly one.

The derived subject seed is displayed before generation and recorded in the round. It is not a second user-controlled seed.

### 5.4 Mutation Contract

Within one run:

- `refine` preserves the base seed and derived subject seed;
- `explore` changes the base seed, which deterministically changes the subject seed;
- either action may change the base prompts, subject prompts, or subject denoise after review;
- neither action may change canvas, protected copy rectangle, subject mask rectangle, feather, mask growth, workflow, model, or bundle; and
- a geometry change requires a newly displayed and confirmed root or child run.

Each Profile adds only `two_stage_conditioning` to its existing refine/explore parameter allowlist. The exact nested schema remains enforced by the two-stage validator.

## 6. Geometry And Mask Rules

All geometry values are integers. Booleans are rejected as integers.

- Canvas width and height must equal the confirmed route dimensions and each be divisible by 8.
- Every rectangle coordinate and extent must be non-negative and divisible by 8.
- Both rectangles must stay within the canvas.
- The copy rectangle must start at `(0, 0)`, span the full canvas height, and cover at least 35% of the width.
- The subject rectangle must be strictly to the right of the copy rectangle.
- The horizontal gap must be at least 64 pixels.
- Subject width and height must each be at least 256 pixels.
- Right, top, and bottom margins must each be at least 16 pixels.
- Feather must be an integer from 0 through 64 and no larger than one quarter of either subject-mask dimension.
- `vae_grow_mask_by` must be an integer from 0 through 64.
- Mask growth may enter the protected gap internally, but the final composite mask must not touch the copy rectangle.

The workflow builds two masks from the same rectangle:

1. a hard full-canvas mask for `VAEEncodeForInpaint`; and
2. a feathered full-canvas mask for final pixel compositing.

The small subject mask is feathered before it is placed into the full-canvas mask. Applying `FeatherMask` after placement is invalid because that node feathers canvas boundaries rather than discovering internal mask boundaries.

## 7. Workflow Graph

The reviewed graph contains exactly 21 nodes:

- one `CheckpointLoaderSimple`;
- four `CLIPTextEncode` nodes: base positive, base negative, subject positive, subject negative;
- one `EmptyLatentImage`;
- two `KSampler` nodes;
- two `VAEDecode` nodes;
- two `SolidMask` nodes: full-canvas zero mask and subject-size one mask;
- two `MaskComposite` nodes: hard full mask and feathered full mask;
- one `FeatherMask`;
- one `VAEEncodeForInpaint`;
- one `ImageCompositeMasked`;
- one `MaskToImage`; and
- three `SaveImage` nodes with roles `base`, `mask`, and `final`.

Node IDs and their principal edges are fixed:

| ID | Class | Reviewed role or principal inputs |
|---|---|---|
| `1` | `CheckpointLoaderSimple` | the one confirmed SDXL checkpoint |
| `2` | `EmptyLatentImage` | confirmed canvas, batch size one |
| `3` | `CLIPTextEncode` | base positive; `clip=[1,1]` |
| `4` | `CLIPTextEncode` | base negative; `clip=[1,1]` |
| `5` | `KSampler` | base; model `1`, positive `3`, negative `4`, latent `2` |
| `6` | `VAEDecode` | base image; samples `5`, VAE `[1,2]` |
| `7` | `CLIPTextEncode` | subject positive; `clip=[1,1]` |
| `8` | `CLIPTextEncode` | subject negative; `clip=[1,1]` |
| `9` | `SolidMask` | full-canvas zero mask |
| `10` | `SolidMask` | subject-size one mask |
| `11` | `MaskComposite` | hard mask; destination `9`, source `10`, confirmed x/y, `add` |
| `12` | `FeatherMask` | feather subject-size mask `10` on all four sides |
| `13` | `MaskComposite` | soft mask; destination `9`, source `12`, confirmed x/y, `add` |
| `14` | `VAEEncodeForInpaint` | base pixels `6`, VAE `[1,2]`, hard mask `11` |
| `15` | `KSampler` | subject; model `1`, positive `7`, negative `8`, latent `14` |
| `16` | `VAEDecode` | subject image; samples `15`, VAE `[1,2]` |
| `17` | `ImageCompositeMasked` | destination `6`, source `16`, soft mask `13`, x/y zero, no resize |
| `18` | `MaskToImage` | soft mask `13` |
| `19` | `SaveImage` | base image `6` |
| `20` | `SaveImage` | mask image `18` |
| `21` | `SaveImage` | final image `17` |

```text
CheckpointLoaderSimple
  +-> base CLIP positive/negative
  +-> EmptyLatentImage -> base KSampler -> base VAEDecode -> SaveImage(base)
  |
  +-> subject CLIP positive/negative ------------------------------+
  |                                                               |
  +-> VAE -----------------------------------------------------+   |
                                                              |   |
SolidMask(full zero) --+-> MaskComposite(hard) ---------------+---+-> VAEEncodeForInpaint
                       |                                          -> subject KSampler
SolidMask(subject one) -+-> FeatherMask -> MaskComposite(soft)     -> subject VAEDecode
                                                                  -> ImageCompositeMasked
                                                                     destination = base image
                                                                     source = subject image
                                                                     mask = soft full mask
                                                                     -> SaveImage(final)

MaskComposite(soft) -> MaskToImage -> SaveImage(mask)
```

The final composite uses `x=0`, `y=0`, and `resize_source=false`. The base and subject images are full-canvas images with identical dimensions. Any crop, resize, or second composite node is invalid.

## 8. Output Ownership And Retention

The two-stage template uses an exact role map rather than the standard single `output_node` field:

```json
{
  "output_nodes": {
    "base": "19",
    "mask": "20",
    "final": "21"
  }
}
```

The adapter accepts exactly those three history output nodes and exactly one PNG from each. Extra output nodes, extra images, missing roles, duplicate role targets, unsafe paths, non-output file types, or wrong dimensions fail closed.

The Engine copies them into the run directory as:

```text
round-01-base.png
round-01-mask.png
round-01.png
```

Each artifact receives width, height, byte size, path, MIME type, and SHA-256 metadata. The mask is a supporting artifact and cannot be finalized. The base is a stage artifact and cannot be finalized. `round-01.png` remains the authoritative final-stage image used by the existing review and finalization flow.

The round stores:

```json
{
  "stages": [
    {"role": "base", "seed": 2026072303, "image": {}},
    {"role": "subject", "seed": 2026072304, "image": {}}
  ],
  "mask_artifact": {},
  "pixel_preservation": {
    "protected_rect": {},
    "checked_pixels": 0,
    "mismatched_pixels": 0
  }
}
```

The example seeds demonstrate the fixed `S` and `S + 1` relationship. Real values are the exact confirmed and derived seeds, geometry, counts, and image metadata.

## 9. Pixel-Preservation Gate

After all three PNGs are downloaded and structurally validated, the Engine decodes the base, mask, and final PNGs with a bounded standard-library path. This gate must not add Pillow or another runtime dependency.

The decoder supports the exact non-interlaced 8-bit RGB/RGBA PNG shape produced by the confirmed ComfyUI route. Unsupported color modes, interlacing, decompression overflow, invalid filters, invalid PNG chunk reserved bits, dimension mismatch, or `tRNS` transparency fail closed. RGB plus `tRNS` is not silently treated as opaque RGB.

The Engine compares base and final pixels:

- every pixel in `copy_protected_rect` must be identical;
- every pixel outside the hard `subject_mask_rect` must be identical; and
- comparisons include every decoded channel, including RGBA alpha; and
- the recorded mismatch count for both checks must be zero.

The saved mask must also match the reviewed mask geometry. RGB channels must be equal, every RGB value outside the subject rectangle and in the protected copy rectangle must be zero, and the strict subject interior must contain a positive value. For `feather_pixels > 0`, every row across both left/right feather widths and every column across both top/bottom feather widths must be nondecreasing inward and must end positive. Widths greater than one must rise across the requested feather; width one legitimately quantizes to an unchanged hard edge because its only multiplier is `1/1`. The subject's saved outer edge may be positive after runtime quantization; corner products may be zero. For `feather_pixels = 0`, a positive hard perimeter with a positive strict interior is valid. The project does not infer mask correctness from an image filename.

If any technical invariant fails, the final output cannot become a successful round. The failed attempt records hashes and a structured error, and automatic generation on that run stops.

## 10. Round And Stage Budgets

`max_rounds` keeps its existing meaning: the maximum number of technically successful, reviewable final images in a root or revision run. It remains an integer from one through three.

For this two-stage route:

```text
max_stage_units = max_rounds * 2
```

- a retained base stage consumes one stage unit;
- a retained subject/final stage consumes one stage unit;
- the retained mask consumes no GPU stage unit;
- a complete two-stage round consumes two stage units and one round;
- visual rejection consumes the complete round exactly as it does today; and
- stage units are identical for root and revision runs.

A stage unit is consumed only when the corresponding artifact bytes are copied into the run directory and their hash is committed to the manifest. Backend execution without a retained artifact remains a failed attempt, not evidence of a retained stage.

If a base artifact is retained but the final artifact is missing or invalid, the attempt records one consumed stage unit, the run enters `partial`, and only read-only recovery is exposed. The Agent must not create another idempotency key for the same run. A fresh root or child requires a new displayed confirmation.

If both stages are retained but pixel preservation or mask validation fails, two stage units are consumed, no successful round is created, the run enters `partial`, and only read-only recovery is exposed.

An unknown timeout does not authorize a resubmission. The existing exact job query/recovery path must first resolve the submitted job.

## 11. Generation Plan And Manifest Contract

The existing twenty top-level generation-plan fields remain unchanged. For the new route:

- `constraints.two_stage_layout` contains immutable geometry and mask settings;
- top-level positive/negative prompts are base-stage prompts;
- `parameters.two_stage_conditioning` contains subject-stage prompts and denoise;
- `seed` supplied to `local_gpu_generate_round` is the base seed;
- the derived subject seed is recomputed and compared before submission; and
- the route must use `sdxl-two-stage-copy-subject` version 1.

The start request persists `initial_two_stage_conditioning`. The initial plan must match it exactly after normalization. A standard or old regional route rejects two-stage fields rather than ignoring them.

Historical manifests without stage data remain readable. Their round budget continues to be `len(rounds)`. They do not synthesize stage records or pixel-preservation claims.

## 12. Capability, Routing, And Fallback

Discovery validates all six additional live node signatures before advertising `copy-subject-two-stage-v1`. The capability result is scoped to the current ComfyUI endpoint identity.

The router requires all of the following:

- backend `comfyui`;
- operation `txt2img`;
- model family `sdxl`;
- exact layout mode `copy-subject-two-stage-v1`;
- workflow `sdxl-two-stage-copy-subject` version 1;
- exact current component bundle;
- canvas dimensions matching the route; and
- live capability `available: true`.

The adapter rechecks the live signatures immediately before `/prompt`. A missing or drifted capability returns `two_stage_layout_drifted` before submission.

There is no fallback to:

- `sdxl-regional-txt2img`;
- ordinary `sdxl-txt2img`;
- prompt-only generation;
- a WebUI backend;
- a different local model; or
- a newly downloaded component.

The previous `copy-subject-v1` route remains readable and explicitly selectable for historical compatibility, but the Agent Skill does not recommend it for a new public-evidence hero route.

## 13. Workflow, Control, And Bundle Identity

Three distinct digests are required:

1. **Workflow SHA-256**: canonical hash of the reviewed template document, including all 21 nodes, exact edges, static values, bindings, and the three-role output map.
2. **Control SHA-256**: canonical hash of workflow identity, canvas, protected rectangle, subject rectangle, feather, mask growth, seed-derivation identifier, stage-count contract, and output-role contract.
3. **Component bundle SHA-256**: canonical bundle of the unchanged checkpoint component identity plus the new workflow identity.

The route token binds the control digest and component bundle digest. The run request, every round, backend result, evidence export, and authority validation retain both.

The unchanged checkpoint does not make the old bundle valid for the new graph. The new workflow necessarily produces a new bundle digest and a separate workflow-bound trust variant. The exact digest can be computed only after the reviewed template exists and passes canonical validation; this design does not invent it.

Read-only workflow inspection may reuse the already established checkpoint filesystem identity when current process evidence remains valid. It must not silently copy an old bundle, downgrade identity strength, or skip current endpoint verification.

Before the first GPU call, the Agent displays the exact checkpoint, workflow digest, control digest, bundle digest, geometry, prompts, both seeds, stage budget, round budget, and policies, then obtains a fresh exact confirmation.

## 14. Review And Finalization

A two-stage round requires full-resolution inspection of both `base` and `final` artifacts. The review additionally records these route-specific checks:

- base left copy space is dark, low-detail, and usable;
- base contains no telescope, focal machinery, people, text, logo, or controls;
- final contains exactly one complete telescope fully inside the mask boundary;
- final retains the required margins and avoids unsafe edge contact;
- final contains no generated text, controls, people, or anatomy-like artifacts;
- transition at the feathered boundary is visually coherent; and
- machine pixel preservation reports zero mismatches.

These checks are added as an exact `stage_checks` object only for the new route. Standard and historical reviews preserve their current schema.

Any required failed or uncertain stage check prevents `next_action=finalize` and requires `explicit_constraint_violation` where the user's required constraint failed. A retained image still consumes its successful round when visual acceptance fails.

Finalization remains bound to the final image's run ID, round number, and SHA-256. Base and mask hashes are retained as provenance but cannot satisfy a finalization confirmation.

## 15. Failure Handling

| Failure | Result |
|---|---|
| Geometry is invalid, misaligned, overlapping, or enters the copy region | `invalid_two_stage_layout`; no run or attempt |
| Subject conditioning is missing or invalid | `invalid_two_stage_conditioning`; no attempt |
| Initial plan differs from confirmed conditioning | `generation_plan_mismatch`; no attempt |
| Required live node is missing or drifted during recommendation | `two_stage_layout_unavailable`; no route |
| Required live node drifts before submission | `two_stage_layout_drifted`; no backend job |
| Workflow topology, bindings, output roles, or static values differ | `unsafe_comfy_workflow`; no backend job |
| Workflow, control, route, or bundle identity differs | structured conflict; no backend job |
| ComfyUI returns missing, extra, duplicate, or unsafe outputs | `invalid_comfyui_output`; no successful round |
| Base retained but final missing/invalid | run `partial`; one stage unit; read-only recovery |
| Both stages retained but mask/pixel invariant fails | run `partial`; two stage units; read-only recovery |
| Job times out in an unknown state | query exact job; no automatic resubmission |
| Base or final fails visual review | successful round consumed; no candidate |
| Budget is exhausted | only `get_run`; no additional generation |
| OOM or backend execution failure during live validation | stop live validation; no model or node change |

Partial artifacts are never public evidence and cannot be finalized or exported as accepted results.

## 16. Security And Compatibility

- Only reviewed built-in node classes are allowed.
- Imported workflows continue to reject the new mask/composite nodes unless separately reviewed under their existing import boundary.
- The two-stage graph rejects shell, Python, process, network, download, webhook, fetch, and unknown custom nodes.
- Model names, output paths, and history metadata retain existing traversal and reparse-point protections.
- Three output nodes are permitted only for this exact shipped template. All existing templates and imported workflows retain exactly one output node.
- The adapter downloads only exact history outputs owned by the submitted job and role map.
- Stage artifacts remain under the run root and are included in cleanup, export, schema, and hash validation.
- Existing finalized runs, standard rounds, inpaint revisions, and old regional runs remain readable without migration.
- The MCP tool count remains exactly fifteen.

## 17. Test Design

### 17.1 Pure Contract Tests

- Accept the approved geometry and return a deep copy.
- Reject booleans, floats, non-8-pixel alignment, overflow, overlap, insufficient gap, undersized mask, and unsafe margins.
- Reject feather or mask growth outside exact bounds.
- Validate conditioning keys, prompt lengths, finite denoise, and the inclusive `0.80..1.00` range.
- Prove deterministic wraparound subject-seed derivation.

### 17.2 Workflow Registry Tests

- Render the exact 21-node topology and three distinct output roles.
- Bind model, both prompt pairs, both seeds, both sampler settings, canvas, rectangle, feather, mask growth, and denoise.
- Prove that the hard and feathered masks originate from the same subject rectangle.
- Prove that feathering occurs before placement.
- Prove that final compositing uses the base destination, full subject source, soft mask, zero offset, and no resize.
- Reject any extra node, edge, sampler, mask, composite, loader, or output.
- Keep all existing standard/imported workflow tests unchanged.

### 17.3 Live Signature And Adapter Tests

- Accept the exact six live node signatures and required `add` operation.
- Reject missing, renamed, retyped, or newly required inputs.
- Recheck signatures before submission.
- Accept exactly three owned output nodes and one image per role.
- Reject extra history outputs, extra images, wrong output type, traversal, malformed PNG, or wrong dimensions.
- Retain base, mask, and final under deterministic run paths.
- Cover timeout, disappeared job, partial output, and idempotent completed-result recovery.

### 17.4 PNG And Pixel Tests

- Decode bounded synthetic RGB and RGBA PNG fixtures without Pillow.
- Reject unsupported color type, bit depth, interlacing, invalid filter, truncated data, and decompression overflow.
- Detect one changed pixel in the protected copy rectangle.
- Detect one changed pixel outside the subject mask.
- Accept changes only within the subject mask.
- Validate the exact saved soft-mask support and feather direction.

### 17.5 Budget And Store Tests

- A complete round records two stages, one mask, two stage units, and one round.
- A visual failure consumes the round and both stage units.
- Base-only partial output records one stage unit, no round, and read-only recovery.
- A technical failure after both stages records two stage units, no round, and read-only recovery.
- Root and revision runs derive identical stage limits.
- Historical manifests preserve current round counting.
- Base and mask artifacts can never be selected for finalization.

### 17.6 Routing, Trust, And Engine Tests

- Route only the exact two-stage workflow when the new mode is requested.
- Keep old standard and single-pass variants distinct.
- Never fall back when capability, workflow, control, or bundle identity differs.
- Build a distinct bundle for unchanged model bytes plus the new workflow.
- Bind geometry and stage contract into the control digest and route token.
- Reject changed geometry, subject seed, output role, or initial conditioning before backend work.
- Preserve the exact twenty-field generation plan and fifteen-tool MCP surface.

### 17.7 Vertical Slice And Regression Gates

- Run a deterministic fake-backend root through start, two-stage generation, review, exhaustion, and finalization rejection.
- Run a deterministic child with the same stage accounting.
- Prove standard `sdxl-txt2img` rejects all two-stage data.
- Run the complete model-free suite with no GPU and no model download.
- Compile all Python files, parse all tracked JSON as UTF-8, run public-document truthfulness tests, packaging tests, and `git diff --check`.

## 18. Real GPU Verification Gate

Model-free implementation and the full regression gate must pass before any GPU request.

The first live gate is one fresh confirmed root round only:

- one base stage;
- one subject/final stage;
- no refinement round;
- no child revision;
- no model switch;
- no download or installation;
- no upscale;
- no evidence export; and
- no publication.

The live result must retain the MCP JSON result plus base, mask, and final PNGs. The reviewer inspects both images at full resolution and records every route-specific stage check.

Stop immediately when any of these occurs:

- OOM or backend instability;
- node-signature, workflow, control, route, or bundle drift;
- partial output;
- nonzero protected-pixel mismatch;
- malformed mask artifact;
- base copy-space failure;
- missing, cropped, duplicated, or out-of-mask telescope;
- generated text, controls, people, or anatomy-like artifacts; or
- a failure pattern materially equivalent to the exhausted single-pass route.

No second live round is justified until the first result is reviewed and a new bounded confirmation is displayed.

## 19. Required Engineering Scope

Expected implementation areas are:

- a focused two-stage geometry/conditioning module;
- one shipped ComfyUI workflow;
- workflow registry and exact graph validation;
- live capability checks and multi-output adapter handling;
- engine/backend result and manifest stage metadata;
- bounded PNG pixel comparison;
- generation-plan, routing, trust, bundle, and Profile integration;
- two-stage review and evidence schemas;
- Agent Skill and public documentation; and
- focused unit, vertical-slice, packaging, and truthfulness tests.

No new MCP tool, model, custom node, runtime dependency, or global environment mutation is required.

## 20. Completion Criteria

The implementation milestone is complete only when:

1. the new workflow and all control contracts are model-free tested;
2. the old single-pass route remains compatible but is not a fallback or positive quality claim;
3. workflow, control, bundle, and route identities fail closed on drift;
4. every successful round retains valid base, mask, and final artifacts;
5. stage and round budgets are enforced for roots and revisions;
6. protected pixels are measured, not assumed;
7. all existing and new tests pass without GPU or model download;
8. `PROJECT_NODES.md` records control flow, failure modes, verification commands, and open limitations;
9. a fresh exact route summary is displayed before any live GPU request; and
10. any live result is described truthfully as positive or negative evidence based on retained full-resolution review.
