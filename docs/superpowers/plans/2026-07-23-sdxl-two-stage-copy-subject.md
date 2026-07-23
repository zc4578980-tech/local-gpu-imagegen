# SDXL Two-Stage Copy-Subject Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, no-download SDXL route that generates a copy-safe base image, generates one subject through an immutable right-side mask, retains base/mask/final artifacts, and proves protected pixels did not change.

**Architecture:** A new pure contract module owns pixel geometry, subject conditioning, live node signatures, and seed derivation. One reviewed 21-node ComfyUI template performs both samplers in one submitted job and returns three role-bound outputs. The adapter, Engine, and RunStore retain stage evidence and enforce a derived stage budget, while routing and trust bind workflow, control, and component-bundle identities without changing the fifteen-tool MCP surface.

**Tech Stack:** Python 3.11/3.12 standard library, MCP JSON-RPC schemas, ComfyUI HTTP API, JSON workflow assets, `unittest`, and offline `uv` wheel tooling.

## Global Constraints

- Work only in `.worktrees/v061-launch-readiness` on `feature/v061-launch-readiness`; do not modify `main`.
- Treat `docs/superpowers/specs/2026-07-23-sdxl-two-stage-copy-subject-design.md` at commit `d373134` as authoritative.
- Do not download a model, ControlNet, custom node, workflow, Python package, or dependency.
- Do not modify shared/global Python or the separately managed learning environment.
- Keep exactly 15 MCP tools and exactly 20 top-level generation-plan fields.
- Keep `sdxl-txt2img-v1.json` and `sdxl-regional-txt2img-v1.json` byte-for-byte unchanged.
- Keep `dist/local_gpu_imagegen-0.6.1-py3-none-any.whl` unchanged at SHA-256 `33ed4bc1564a92e3252b80f79cf1a7dd91f726774045801fd617bf9d0ef02655`.
- Preserve historical manifests and the old single-pass route; never use either old SDXL route as fallback.
- Model-free tests must not contact ComfyUI, load a checkpoint, require a GPU, or require Pillow.
- Do not push, tag, publish, export evidence, contact maintainers, or claim visual-quality improvement.
- Use TDD for every task. Run the focused red test before implementation and commit only after focused green tests pass.
- Stop after deriving and displaying the new exact workflow/control/bundle/route identities. A later explicit confirmation is required before the one-round GPU gate.

---

## File Structure

**Create**

- `scripts/local_gpu_imagegen/two_stage_layout.py`: immutable pixel geometry, subject conditioning, seed derivation, control digest, and live node-signature validation.
- `scripts/local_gpu_imagegen/png_pixels.py`: bounded dependency-free RGB/RGBA PNG decoding, protected-pixel comparison, and soft-mask validation.
- `workflows/comfyui/sdxl-two-stage-copy-subject-v1.json`: the only reviewed 21-node, three-output two-stage graph.
- `tests/test_two_stage_layout.py`: pure contract and live-signature tests.
- `tests/test_png_pixels.py`: bounded decoder, preservation, and mask tests.
- `tests/test_two_stage_vertical_slice.py`: model-free route-to-stage-to-review lifecycle.

**Modify**

- `scripts/local_gpu_imagegen/workflow_templates.py`: load, bind, and exactly validate the 21-node template without weakening standard/imported workflows.
- `scripts/local_gpu_imagegen/backends/base.py`: generalize the bounded layout capability provider.
- `scripts/local_gpu_imagegen/backends/comfyui.py`: recheck six live signatures and retrieve three exact role-bound outputs.
- `scripts/local_gpu_imagegen/backend_contract.py`: validate two-stage backend stage metadata only for the new workflow.
- `scripts/local_gpu_imagegen/run_store.py`: retain stage artifacts, count stage units, enter fail-closed `partial`, and protect finalization.
- `scripts/local_gpu_imagegen/engine.py`: compile both prompt pairs, derive the subject seed, validate three outputs, run pixel gates, and commit one round.
- `scripts/local_gpu_imagegen/generation_plan.py`: pair the new route, immutable layout, and initial subject conditioning.
- `scripts/local_gpu_imagegen/model_catalog.py`: advertise the new layout mode on the exact workflow-bound trust variant.
- `scripts/local_gpu_imagegen/model_router.py`: normalize the new requirement and bind `control_sha256` into the route token.
- `scripts/local_gpu_imagegen/trust_registry.py`: retain the control digest in the new workflow-bound trust variant while preserving existing records.
- `scripts/local_gpu_imagegen/services.py`: wire the generalized layout capability provider.
- `scripts/mcp_server.py`: add nested two-stage start/plan/review schema fields without adding a tool.
- `scripts/local_gpu_imagegen/visual_review.py`: validate route-specific `stage_checks` without changing standard review behavior.
- `scripts/export_acceptance_evidence.py`, `scripts/validate_acceptance_evidence.py`: retain and validate stage/mask/pixel evidence.
- `docs/evidence/schemas/run-evidence.schema.json`: describe exact optional two-stage evidence.
- `profiles/use-cases/standalone-illustration.json`, `presentation-visual.json`, `ui-visual-asset.json`: permit `two_stage_conditioning` during reviewed mutations.
- `skills/local-gpu-imagegen/SKILL.md`: gather, display, confirm, execute, review, and stop on the new route.
- `README.md`, `docs/architecture.md`, `docs/troubleshooting.md`, `CHANGELOG.md`: document the experimental route and negative single-pass evidence truthfully.
- Focused tests for every modified module plus packaging, public-doc, Skill, and MCP-surface regressions.
- `<project-root>/PROJECT_NODES.md` and `<project-root>/NEXT_SESSION.md`: update the project-root, Git-ignored continuity records after the verified milestone.

## Task 1: Add The Pure Two-Stage Contract

**Files:**
- Create: `scripts/local_gpu_imagegen/two_stage_layout.py`
- Create: `tests/test_two_stage_layout.py`

**Interfaces:**
- Produces: `TWO_STAGE_LAYOUT_MODE`, `TWO_STAGE_TEMPLATE_ID`, `SEED_DERIVATION_ID`, `validate_two_stage_layout(value)`, `validate_two_stage_conditioning(value)`, `derive_subject_seed(seed)`, `build_control_identity(...)`, and `validate_two_stage_node_info(value) -> None`.
- Consumes: `ValidationError` from `scripts/local_gpu_imagegen/errors.py`.

- [ ] **Step 1: Write failing geometry, conditioning, seed, digest, and node-signature tests**

```python
class TwoStageLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = {
            "mode": "copy-subject-two-stage-v1",
            "canvas": {"width": 1280, "height": 720},
            "copy_protected_rect": {"x": 0, "y": 0, "width": 576, "height": 720},
            "subject_mask_rect": {"x": 720, "y": 24, "width": 512, "height": 672},
            "feather_pixels": 32,
            "vae_grow_mask_by": 8,
        }
        self.conditioning = {
            "subject_prompt": "one complete brass telescope on a tripod",
            "subject_negative_prompt": "cropped telescope, duplicate telescope, text",
            "subject_denoise": 0.9,
        }

    def test_approved_contract_is_normalized_and_deep_copied(self) -> None:
        layout = validate_two_stage_layout(self.layout)
        conditioning = validate_two_stage_conditioning(self.conditioning)
        layout["subject_mask_rect"]["x"] = 800
        self.assertEqual(self.layout["subject_mask_rect"]["x"], 720)
        self.assertEqual(conditioning["subject_denoise"], 0.9)

    def test_geometry_rejects_float_bool_alignment_overlap_and_margin_failures(self) -> None:
        changes = (
            ("canvas", "width", 1280.0),
            ("subject_mask_rect", "x", True),
            ("subject_mask_rect", "x", 721),
            ("subject_mask_rect", "x", 576),
            ("subject_mask_rect", "width", 640),
            ("copy_protected_rect", "width", 1280),
        )
        for section, field, value in changes:
            changed = copy.deepcopy(self.layout)
            changed[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaisesRegex(
                ValidationError, "invalid_two_stage_layout"
            ):
                validate_two_stage_layout(changed)

    def test_conditioning_trims_prompts_and_rejects_unknown_fields_or_denoise_bounds(self) -> None:
        trimmed = {**self.conditioning, "subject_prompt": "  telescope  "}
        self.assertEqual(validate_two_stage_conditioning(trimmed)["subject_prompt"], "telescope")
        for value in (
            {**self.conditioning, "extra": True},
            {**self.conditioning, "subject_prompt": " "},
            {**self.conditioning, "subject_negative_prompt": "x" * 2001},
            {**self.conditioning, "subject_denoise": 0.79},
            {**self.conditioning, "subject_denoise": 1.01},
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError, "invalid_two_stage_conditioning"
            ):
                validate_two_stage_conditioning(value)

    def test_subject_seed_wraps_exactly_and_control_digest_is_stable(self) -> None:
        self.assertEqual(derive_subject_seed(2026072303), 2026072304)
        self.assertEqual(derive_subject_seed(2**64 - 1), 0)
        first = build_control_identity(self.layout, "a" * 64, "base-subject-v1")
        second = build_control_identity(copy.deepcopy(self.layout), "a" * 64, "base-subject-v1")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_live_node_signatures_require_exact_required_types_and_mask_add(self) -> None:
        validate_two_stage_node_info(exact_node_info())
        changed = exact_node_info()
        changed["MaskComposite"]["input"]["required"]["operation"][1]["options"] = ["subtract"]
        with self.assertRaisesRegex(ValidationError, "two_stage_layout_unavailable"):
            validate_two_stage_node_info(changed)
```

- [ ] **Step 2: Run the focused test and verify the missing-module failure**

Run: `python -m unittest tests.test_two_stage_layout -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.two_stage_layout'`.

- [ ] **Step 3: Implement exact constants, layout validation, and seed derivation**

```python
TWO_STAGE_LAYOUT_MODE = "copy-subject-two-stage-v1"
TWO_STAGE_TEMPLATE_ID = "sdxl-two-stage-copy-subject"
SEED_DERIVATION_ID = "increment-mod-2^64-v1"
MAX_SEED = 2**64 - 1
RECT_FIELDS = frozenset({"x", "y", "width", "height"})
LAYOUT_FIELDS = frozenset({
    "mode", "canvas", "copy_protected_rect", "subject_mask_rect",
    "feather_pixels", "vae_grow_mask_by",
})
CONDITIONING_FIELDS = frozenset({
    "subject_prompt", "subject_negative_prompt", "subject_denoise",
})


def derive_subject_seed(seed: object) -> int:
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValidationError("invalid_seed", "Seed must be an unsigned 64-bit integer.")
    return (seed + 1) & MAX_SEED


def validate_two_stage_layout(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != LAYOUT_FIELDS:
        raise _layout_error()
    if value["mode"] != TWO_STAGE_LAYOUT_MODE:
        raise _layout_error()
    canvas = _integer_record(value["canvas"], frozenset({"width", "height"}))
    copy_rect = _integer_record(value["copy_protected_rect"], RECT_FIELDS)
    subject_rect = _integer_record(value["subject_mask_rect"], RECT_FIELDS)
    width, height = canvas["width"], canvas["height"]
    feather, grow = value["feather_pixels"], value["vae_grow_mask_by"]
    if (
        width < 256 or height < 256 or width > 1536 or height > 1536
        or width % 8 or height % 8
        or any(number % 8 for number in (*copy_rect.values(), *subject_rect.values()))
        or copy_rect != {"x": 0, "y": 0, "width": copy_rect["width"], "height": height}
        or copy_rect["width"] * 100 < width * 35
        or not _inside(subject_rect, width, height)
        or subject_rect["x"] - copy_rect["width"] < 64
        or subject_rect["width"] < 256 or subject_rect["height"] < 256
        or width - subject_rect["x"] - subject_rect["width"] < 16
        or subject_rect["y"] < 16
        or height - subject_rect["y"] - subject_rect["height"] < 16
        or type(feather) is not int or not 0 <= feather <= 64
        or feather * 4 > min(subject_rect["width"], subject_rect["height"])
        or type(grow) is not int or not 0 <= grow <= 64
    ):
        raise _layout_error()
    return {
        "mode": TWO_STAGE_LAYOUT_MODE,
        "canvas": canvas,
        "copy_protected_rect": copy_rect,
        "subject_mask_rect": subject_rect,
        "feather_pixels": feather,
        "vae_grow_mask_by": grow,
    }
```

- [ ] **Step 4: Implement conditioning, live signature, and control digest validation**

```python
def validate_two_stage_conditioning(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != CONDITIONING_FIELDS:
        raise _conditioning_error()
    normalized = copy.deepcopy(value)
    for field in ("subject_prompt", "subject_negative_prompt"):
        text = normalized[field]
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 2000:
            raise _conditioning_error()
        normalized[field] = text.strip()
    denoise = normalized["subject_denoise"]
    if isinstance(denoise, bool) or not isinstance(denoise, (int, float)) or not math.isfinite(denoise):
        raise _conditioning_error()
    if not 0.80 <= float(denoise) <= 1.00:
        raise _conditioning_error()
    normalized["subject_denoise"] = float(denoise)
    return normalized


def build_control_identity(layout: object, workflow_sha256: object, stage_contract: object) -> str:
    normalized = validate_two_stage_layout(layout)
    if not isinstance(workflow_sha256, str) or SHA256_PATTERN.fullmatch(workflow_sha256) is None:
        raise ValidationError("invalid_two_stage_control", "Workflow SHA-256 is invalid.")
    if stage_contract != "base-subject-v1":
        raise ValidationError("invalid_two_stage_control", "Stage contract is invalid.")
    document = {
        "schema_version": 1,
        "layout": normalized,
        "workflow_sha256": workflow_sha256,
        "seed_derivation_id": SEED_DERIVATION_ID,
        "stage_contract": stage_contract,
        "output_roles": ["base", "mask", "final"],
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
```

`validate_two_stage_node_info` must normalize `/object_info/<class>` documents into required input-name/type maps, require the six signatures from the spec, and require `add` among `MaskComposite.operation` options. It must reject extra required inputs but tolerate optional descriptive metadata.

- [ ] **Step 5: Run the focused test**

Run: `python -m unittest tests.test_two_stage_layout -v`

Expected: PASS.

- [ ] **Step 6: Commit the pure contract**

```powershell
git add scripts/local_gpu_imagegen/two_stage_layout.py tests/test_two_stage_layout.py
git commit -m "feat: validate two-stage SDXL control"
```

## Task 2: Add Bounded PNG Pixel Verification

**Files:**
- Create: `scripts/local_gpu_imagegen/png_pixels.py`
- Create: `tests/test_png_pixels.py`
- Modify: `scripts/local_gpu_imagegen/artifacts.py`

**Interfaces:**
- Produces: `DecodedPng(width, height, channels, pixels)`, `decode_png_pixels(path, expected_width, expected_height)`, `compare_protected_pixels(base, final, layout)`, and `validate_saved_soft_mask(mask, layout)`.
- Consumes: `ensure_within`/PNG limits from `artifacts.py` and `validate_two_stage_layout`.

- [ ] **Step 1: Write failing decoder and invariant tests with standard-library PNG fixtures**

```python
class PngPixelTests(unittest.TestCase):
    def test_rgb_and_rgba_round_trip_without_pillow(self) -> None:
        for channels in (3, 4):
            path = self.write_png(16, 8, channels, pixel_pattern(channels))
            decoded = decode_png_pixels(path, 16, 8)
            self.assertEqual((decoded.width, decoded.height, decoded.channels), (16, 8, channels))
            self.assertEqual(decoded.pixels, pixel_pattern(channels))

    def test_all_png_filters_decode(self) -> None:
        for filter_type in range(5):
            path = self.write_png(16, 8, 3, pixel_pattern(3), filter_type=filter_type)
            self.assertEqual(decode_png_pixels(path, 16, 8).pixels, pixel_pattern(3))

    def test_unsupported_or_malformed_png_fails_closed(self) -> None:
        for mutation in ("indexed", "grayscale", "interlaced", "truncated", "bad-filter", "overflow"):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                ArtifactError, "unsupported_two_stage_png|invalid_generated_image"
            ):
                decode_png_pixels(self.fixture(mutation), 16, 8)

    def test_protected_comparison_detects_one_changed_pixel(self) -> None:
        layout = approved_layout(width=1280, height=720)
        base = self.solid_image(1280, 720, (10, 20, 30))
        final = base.copy()
        final.set_pixel(800, 100, (200, 100, 50))
        passing = compare_protected_pixels(base.path, final.path, layout)
        self.assertEqual(passing["mismatched_pixels"], 0)
        final.set_pixel(100, 100, (200, 100, 50))
        failing = compare_protected_pixels(base.path, final.path, layout)
        self.assertEqual(failing["mismatched_pixels"], 1)

    def test_soft_mask_must_be_zero_outside_and_feather_inward(self) -> None:
        metadata = validate_saved_soft_mask(self.soft_mask(), approved_layout())
        self.assertEqual(metadata["outside_nonzero_pixels"], 0)
        with self.assertRaisesRegex(ArtifactError, "invalid_two_stage_mask"):
            validate_saved_soft_mask(self.mask_with_left_leak(), approved_layout())
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run: `python -m unittest tests.test_png_pixels -v`

Expected: FAIL because `local_gpu_imagegen.png_pixels` does not exist.

- [ ] **Step 3: Implement the bounded decoder**

Implement these exact rules in `png_pixels.py`:

```python
@dataclass(frozen=True)
class DecodedPng:
    width: int
    height: int
    channels: int
    pixels: bytes


def decode_png_pixels(path: Path, expected_width: int, expected_height: int) -> DecodedPng:
    data = _read_bounded_regular_file(path, MAX_IMAGE_BYTES)
    ihdr, compressed = _parse_exact_png_chunks(data)
    width, height, bit_depth, color_type, compression, filtering, interlace = ihdr
    if (width, height) != (expected_width, expected_height):
        raise _invalid(path, "dimension_mismatch")
    if bit_depth != 8 or color_type not in {2, 6} or compression != 0 or filtering != 0 or interlace != 0:
        raise ArtifactError(
            "unsupported_two_stage_png",
            "Two-stage pixel verification requires non-interlaced 8-bit RGB or RGBA PNG.",
        )
    channels = 3 if color_type == 2 else 4
    row_size = width * channels
    raw = _bounded_decompress(compressed, height * (row_size + 1))
    rows = _unfilter_rows(raw, width, height, channels)
    return DecodedPng(width, height, channels, b"".join(rows))
```

`_unfilter_rows` must implement PNG filters 0 through 4 exactly, use byte modulo 256, use the prior unfiltered row, and reject all other filter values. Reuse the existing PNG chunk/CRC/size safety limits instead of accepting looser files. Enforce the PNG chunk-type reserved bit, and reject `tRNS` rather than discarding transparency semantics from an otherwise supported RGB image.

- [ ] **Step 4: Implement preservation and mask checks**

```python
def compare_protected_pixels(base_path: Path, final_path: Path, layout: object) -> dict[str, object]:
    normalized = validate_two_stage_layout(layout)
    width = normalized["canvas"]["width"]
    height = normalized["canvas"]["height"]
    base = decode_png_pixels(base_path, width, height)
    final = decode_png_pixels(final_path, width, height)
    if base.channels != final.channels:
        raise ArtifactError("unsupported_two_stage_png", "Stage PNG channel counts differ.")
    subject = normalized["subject_mask_rect"]
    copy_rect = normalized["copy_protected_rect"]
    mismatch = 0
    copy_mismatch = 0
    checked = 0
    for y in range(height):
        for x in range(width):
            outside_subject = not _contains(subject, x, y)
            inside_copy = _contains(copy_rect, x, y)
            if not outside_subject:
                continue
            checked += 1
            changed = _pixel(base, x, y) != _pixel(final, x, y)  # Includes RGBA alpha.
            mismatch += int(changed)
            copy_mismatch += int(changed and inside_copy)
    return {
        "protected_rect": copy.deepcopy(copy_rect),
        "checked_pixels": checked,
        "mismatched_pixels": mismatch,
        "copy_mismatched_pixels": copy_mismatch,
    }
```

`validate_saved_soft_mask` must require equal RGB channels, zero RGB outside the subject rectangle, a positive strict interior, and no nonzero pixel in the protected copy rectangle. Preserve the approved installed `FeatherMask` semantics: for `f > 0`, each side's first `f` pixels use `(distance + 1) / f`, corner factors multiply, and `SaveImage` truncates `255 * value` to 8-bit RGB. Positive outer-edge values are therefore valid and corner values may quantize to zero. Validate nondecreasing inward direction across every row on the left/right edges and every column on the top/bottom edges. Require a positive rise when `f > 1`; `f = 1` is a valid unchanged hard edge because its only multiplier is `1/1`. For `f = 0`, accept a positive hard perimeter with a positive strict interior.

- [ ] **Step 5: Run focused artifact regressions**

Run: `python -m unittest tests.test_png_pixels tests.test_masks tests.test_preview -v`

Expected: PASS.

- [ ] **Step 6: Commit pixel verification**

```powershell
git add scripts/local_gpu_imagegen/png_pixels.py scripts/local_gpu_imagegen/artifacts.py tests/test_png_pixels.py
git commit -m "feat: verify two-stage protected pixels"
```

## Task 3: Add The Reviewed 21-Node Workflow

**Files:**
- Create: `workflows/comfyui/sdxl-two-stage-copy-subject-v1.json`
- Modify: `scripts/local_gpu_imagegen/workflow_templates.py`
- Modify: `tests/test_workflow_templates.py`

**Interfaces:**
- Produces: a resolved workflow with `layout_mode`, `output_nodes`, `control_sha256`, exact base/subject bindings, and the unchanged component loader binding.
- Consumes: validators and constants from `two_stage_layout.py`.

- [ ] **Step 1: Write failing exact-topology and binding tests**

```python
def test_two_stage_template_binds_exact_graph_and_roles(self) -> None:
    resolved = self.registry.resolve(
        "sdxl-two-stage-copy-subject",
        MODEL,
        "txt2img",
        standard_parameters(
            positive_prompt="empty blue-hour observatory background",
            negative_prompt="telescope, text, people",
            seed=2026072303,
        ),
        two_stage_layout=approved_layout(),
        two_stage_conditioning=approved_conditioning(),
    )
    graph = resolved["graph"]
    self.assertEqual(len(graph), 21)
    self.assertEqual(resolved["output_nodes"], {"base": "19", "mask": "20", "final": "21"})
    self.assertEqual(graph["5"]["inputs"]["seed"], 2026072303)
    self.assertEqual(graph["15"]["inputs"]["seed"], 2026072304)
    self.assertEqual(graph["11"]["inputs"], {
        "destination": ["9", 0], "source": ["10", 0],
        "x": 720, "y": 24, "operation": "add",
    })
    self.assertEqual(graph["17"]["inputs"], {
        "destination": ["6", 0], "source": ["16", 0],
        "x": 0, "y": 0, "resize_source": False, "mask": ["13", 0],
    })
    self.assertRegex(resolved["workflow_sha256"], r"^[0-9a-f]{64}$")
    self.assertRegex(resolved["control_sha256"], r"^[0-9a-f]{64}$")

def test_two_stage_graph_rejects_every_topology_and_static_drift(self) -> None:
    mutations = (
        lambda graph: graph.pop("20"),
        lambda graph: graph["15"]["inputs"].update(seed=9),
        lambda graph: graph["17"]["inputs"].update(resize_source=True),
        lambda graph: graph["13"]["inputs"].update(source=["10", 0]),
        lambda graph: graph.update({"22": copy.deepcopy(graph["21"])}),
    )
    for mutate in mutations:
        with self.subTest(mutate=mutate), self.assertRaisesRegex(
            (ArtifactError, ValidationError), "invalid_workflow_template|unsafe_comfy_workflow"
        ):
            self.load_mutated_two_stage(mutate)
```

- [ ] **Step 2: Run the focused registry tests and confirm template absence**

Run: `python -m unittest tests.test_workflow_templates.WorkflowTemplateTests.test_two_stage_template_binds_exact_graph_and_roles -v`

Expected: FAIL with `workflow_template_not_found`.

- [ ] **Step 3: Create the exact workflow document**

Create a schema-version-1 document with:

```json
{
  "schema_version": 1,
  "template_id": "sdxl-two-stage-copy-subject",
  "template_version": 1,
  "operation": "txt2img",
  "model_families": ["sdxl"],
  "layout_mode": "copy-subject-two-stage-v1",
  "stage_contract": "base-subject-v1",
  "output_nodes": {"base": "19", "mask": "20", "final": "21"}
}
```

The same document must contain exactly the node IDs/classes/edges in design spec section 7. Static values are:

```json
{
  "2": {"width": 1280, "height": 720, "batch_size": 1},
  "5": {"steps": 30, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0},
  "9": {"value": 0.0, "width": 1280, "height": 720},
  "10": {"value": 1.0, "width": 512, "height": 672},
  "11": {"x": 720, "y": 24, "operation": "add"},
  "12": {"left": 32, "top": 32, "right": 32, "bottom": 32},
  "13": {"x": 720, "y": 24, "operation": "add"},
  "14": {"grow_mask_by": 8},
  "15": {"steps": 30, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 0.9},
  "17": {"x": 0, "y": 0, "resize_source": false},
  "19": {"filename_prefix": "local-gpu-imagegen"},
  "20": {"filename_prefix": "local-gpu-imagegen"},
  "21": {"filename_prefix": "local-gpu-imagegen"}
}
```

Every omitted input in this compact table is the exact edge in the design node table. The actual workflow JSON contains complete `class_type` and `inputs` objects for all 21 nodes; no node may rely on ComfyUI UI defaults.

- [ ] **Step 4: Add a dedicated two-stage validator path**

In `workflow_templates.py`:

- add only `SolidMask`, `MaskComposite`, `FeatherMask`, `ImageCompositeMasked`, and `MaskToImage` to a `TWO_STAGE_NODE_INPUTS` map;
- do not add those nodes to `SAFE_NODE_INPUTS` used by imported workflows;
- allow three `SaveImage` nodes only when template ID is `TWO_STAGE_TEMPLATE_ID`;
- validate exact class counts, output roles, edges, static values, and scalar bindings;
- bind base seed to node 5 and derived subject seed to node 15;
- bind canvas dimensions to nodes 2 and 9;
- bind subject dimensions/placement to nodes 10 through 13;
- bind prompts to nodes 3, 4, 7, and 8;
- bind shared sampling settings to nodes 5 and 15, except base denoise stays 1.0 and subject denoise comes from conditioning; and
- return `control_sha256` from `build_control_identity`.

- [ ] **Step 5: Run focused workflow regressions**

Run: `python -m unittest tests.test_workflow_templates -v`

Expected: PASS, including unchanged old workflow digest assertions.

- [ ] **Step 6: Commit the reviewed workflow**

```powershell
git add workflows/comfyui/sdxl-two-stage-copy-subject-v1.json scripts/local_gpu_imagegen/workflow_templates.py tests/test_workflow_templates.py
git commit -m "feat: add reviewed two-stage SDXL workflow"
```

## Task 4: Add Live Capability And Three-Output Adapter Handling

**Files:**
- Modify: `scripts/local_gpu_imagegen/backends/base.py`
- Modify: `scripts/local_gpu_imagegen/backends/comfyui.py`
- Modify: `scripts/local_gpu_imagegen/services.py`
- Modify: `tests/test_comfyui_adapter.py`
- Modify: `tests/test_runtime_services.py`

**Interfaces:**
- Produces: generalized `layout_capability(mode)` and a ComfyUI backend result with `stage_outputs`, `mask_output`, `subject_seed`, `workflow_job_id`, and `control_sha256` for only the new template.
- Consumes: the resolved workflow role map and exact live signature validator.

- [ ] **Step 1: Add failing capability, drift, and three-output tests**

```python
def test_two_stage_capability_requires_all_six_exact_live_signatures(self) -> None:
    result = self.adapter.layout_capability("copy-subject-two-stage-v1")
    self.assertEqual(result, {
        "mode": "copy-subject-two-stage-v1",
        "available": True,
        "endpoint_identity": self.adapter.endpoint_identity,
        "reason": None,
    })
    self.server.remove(("GET", "/object_info/MaskToImage"))
    unavailable = self.adapter.layout_capability("copy-subject-two-stage-v1")
    self.assertFalse(unavailable["available"])

def test_two_stage_generate_rechecks_before_prompt_submission(self) -> None:
    self.server.drift("ImageCompositeMasked", required_name="resize_image")
    with self.assertRaisesRegex(ConflictError, "two_stage_layout_drifted"):
        self.adapter.generate(self.two_stage_request())
    self.assertEqual(self.server.requests_to("/prompt"), [])

def test_two_stage_generate_downloads_exact_role_outputs(self) -> None:
    result = self.adapter.generate(self.two_stage_request())
    self.assertEqual(set(result["stage_outputs"]), {"base", "final"})
    self.assertEqual(result["subject_seed"], 2026072304)
    self.assertTrue(Path(result["stage_outputs"]["base"]["path"]).is_file())
    self.assertTrue(Path(result["mask_output"]["path"]).is_file())
    self.assertTrue(Path(result["stage_outputs"]["final"]["path"]).is_file())

def test_two_stage_history_rejects_missing_extra_duplicate_or_unsafe_roles(self) -> None:
    for history in invalid_three_output_histories():
        self.server.set_history(history)
        with self.subTest(history=history), self.assertRaisesRegex(
            ArtifactError, "invalid_comfyui_output"
        ):
            self.adapter.generate(self.two_stage_request())
```

- [ ] **Step 2: Run the focused adapter tests and confirm failure**

Run: `python -m unittest tests.test_comfyui_adapter tests.test_runtime_services -v`

Expected: FAIL because the adapter knows only the regional capability and one owned output.

- [ ] **Step 3: Generalize capability routing without weakening old behavior**

Replace the backend-registry `regional_layout_capability` entry point with `layout_capability(mode)`. Dispatch `copy-subject-v1` to the existing two-node validator and `copy-subject-two-stage-v1` to the new six-node validator. Unsupported modes return `available: false` without probing ComfyUI.

The router/service constructor field becomes `layout_capability_provider`. Keep a compatibility alias only inside `BackendRegistry` if existing tests require it; do not expose a new MCP field.

- [ ] **Step 4: Implement exact role-output retrieval**

```python
def _owned_outputs(history: dict[str, object], job_id: str, roles: dict[str, str]) -> dict[str, dict[str, str]]:
    if set(roles) != {"base", "mask", "final"} or len(set(roles.values())) != 3:
        raise ArtifactError("invalid_comfyui_output", "Two-stage output roles are invalid.")
    outputs = _history_outputs(history, job_id)
    if set(outputs) != set(roles.values()):
        raise ArtifactError("invalid_comfyui_output", "ComfyUI returned unexpected output nodes.")
    return {role: _one_owned_png(outputs[node_id], job_id) for role, node_id in roles.items()}
```

Download each role into a distinct adapter-owned pending path supplied by the Engine. Return standard `path` as the final path for compatibility, plus exact stage/mask metadata. Old workflows continue through `_owned_output` and return the current result shape.

- [ ] **Step 5: Revalidate the rendered two-stage graph before submission**

The adapter must independently check template ID/version, layout mode, control digest, 21-node topology, bound prompt/scalar values, subject seed derivation, and three output roles before `POST /prompt`.

- [ ] **Step 6: Run focused adapter regressions**

Run: `python -m unittest tests.test_comfyui_adapter tests.test_runtime_services tests.test_backend_base -v`

Expected: PASS.

- [ ] **Step 7: Commit capability and adapter work**

```powershell
git add scripts/local_gpu_imagegen/backends/base.py scripts/local_gpu_imagegen/backends/comfyui.py scripts/local_gpu_imagegen/services.py tests/test_comfyui_adapter.py tests/test_runtime_services.py tests/test_backend_base.py
git commit -m "feat: retain two-stage ComfyUI outputs"
```

## Task 5: Add Stage-Aware Backend And Run-Store State

**Files:**
- Modify: `scripts/local_gpu_imagegen/backend_contract.py`
- Modify: `scripts/local_gpu_imagegen/run_store.py`
- Modify: `tests/test_backend_contract.py`
- Modify: `tests/test_run_store.py`

**Interfaces:**
- Produces: strict two-stage backend metadata, stage-aware `mark_attempt_artifacts`, `complete_attempt` stage records, derived stage usage, and `partial` transition.
- Consumes: existing `AttemptHandle`, manifest locking, and image validation.

- [ ] **Step 1: Write failing backend-result and stage-budget tests**

```python
def test_two_stage_backend_result_requires_exact_stage_shape(self) -> None:
    result = validate_backend_result(
        two_stage_backend_result(), "txt2img", 1280, 720,
        expected_seed=2026072303, expected_backend="comfyui",
    )
    self.assertEqual(result["subject_seed"], 2026072304)
    self.assertEqual(set(result["stage_outputs"]), {"base", "final"})
    self.assertEqual(result["control_sha256"], "c" * 64)

def test_complete_two_stage_attempt_consumes_two_stages_and_one_round(self) -> None:
    store, run_id, handle = self.started_two_stage_attempt(max_rounds=2)
    store.mark_attempt_artifacts(handle, base_image(), mask_image(), final_image(), backend_result())
    manifest = store.complete_attempt(handle, two_stage_result())
    self.assertEqual(len(manifest["rounds"]), 1)
    self.assertEqual(manifest["rounds"][0]["stage_units"], 2)
    self.assertEqual(manifest["stage_budget"], {"maximum": 4, "consumed": 2})

def test_base_only_partial_blocks_new_generation(self) -> None:
    store, run_id, handle = self.started_two_stage_attempt(max_rounds=2)
    manifest = store.record_partial_attempt(handle, [base_stage()], error("final_missing"))
    self.assertEqual(manifest["state"], "partial")
    self.assertEqual(manifest["stage_budget"]["consumed"], 1)
    with self.assertRaisesRegex(StateError, "two_stage_run_partial"):
        store.begin_attempt(run_id, "another-key", next_request())
```

- [ ] **Step 2: Run focused store tests and confirm current single-image assumptions fail**

Run: `python -m unittest tests.test_backend_contract tests.test_run_store -v`

Expected: FAIL because stage fields and `partial` do not exist.

- [ ] **Step 3: Extend backend validation only for the new template**

For `workflow_template_id == TWO_STAGE_TEMPLATE_ID`, require:

```python
TWO_STAGE_RESULT_FIELDS = frozenset({
    "stage_outputs", "mask_output", "subject_seed", "control_sha256",
})
```

Require role set `{base, final}`, exact integer subject seed equal to `derive_subject_seed(expected_seed)`, three safe non-empty paths, and a 64-character lowercase control digest. Reject those fields on every other backend/workflow result.

- [ ] **Step 4: Add stage-aware manifest records and budget computation**

Only a run whose confirmed workflow is `TWO_STAGE_TEMPLATE_ID` receives this request metadata:

```python
"stage_budget": {
    "maximum": request["max_rounds"] * 2,
    "consumed": 0,
}
```

Standard, old regional, and historical manifests do not receive a synthetic `stage_budget` field.

Add methods:

```python
def mark_attempt_artifacts(
    self, handle: AttemptHandle, base: dict[str, object], mask: dict[str, object],
    final: dict[str, object], backend_result: dict[str, object],
) -> dict[str, object]: ...

def record_partial_attempt(
    self, handle: AttemptHandle, retained_stages: list[dict[str, object]],
    error: dict[str, object],
) -> dict[str, object]: ...
```

`mark_attempt_artifacts` validates all files under the run root, stores them on the active attempt, and leaves `image` pointing to final for compatibility. `complete_attempt` copies `stages`, `mask_artifact`, and `pixel_preservation` into the round and increments consumed stage units by two. `record_partial_attempt` archives exact retained stages, increments by their count, clears the active attempt, sets `state` and `last_stable_state` to `partial`, and releases the run lock.

- [ ] **Step 5: Fail closed on partial and protect finalization/cleanup**

- `_validate_attempt_transition` rejects any manifest in `partial`.
- `recoverable_next_actions` returns only `get_run` for `partial`.
- finalization requires a normal generated/reviewed round and always selects `round.image`, never a stage or mask.
- cleanup and stale-attempt recovery retain stage paths consistently.
- historical manifests without `stage_budget` remain readable.

- [ ] **Step 6: Run focused state-machine regressions**

Run: `python -m unittest tests.test_backend_contract tests.test_run_store tests.test_revisions -v`

Expected: PASS.

- [ ] **Step 7: Commit stage-aware persistence**

```powershell
git add scripts/local_gpu_imagegen/backend_contract.py scripts/local_gpu_imagegen/run_store.py tests/test_backend_contract.py tests/test_run_store.py tests/test_revisions.py
git commit -m "feat: account for retained generation stages"
```

## Task 6: Execute Confirmed Two-Stage Plans In The Engine

**Files:**
- Modify: `scripts/local_gpu_imagegen/generation_plan.py`
- Modify: `scripts/local_gpu_imagegen/engine.py`
- Modify: `scripts/mcp_server.py`
- Modify: three Profile JSON files
- Modify: `tests/test_generation_plan.py`
- Modify: `tests/test_asset_run_engine.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Produces: exact start validation, second prompt compilation, three pending artifact paths, pixel/mask verification, and one committed round.
- Consumes: the new workflow, adapter result, RunStore stage APIs, and PNG gates.

- [ ] **Step 1: Add failing plan-pairing and route-drift tests**

```python
def test_initial_two_stage_plan_must_match_confirmed_layout_and_conditioning(self) -> None:
    request = two_stage_run_request()
    plan = two_stage_plan(request)
    validate_generation_plan(plan, request, "initial", "txt2img")
    changed = copy.deepcopy(plan)
    changed["parameters"]["two_stage_conditioning"]["subject_denoise"] = 0.95
    with self.assertRaisesRegex(ValidationError, "generation_plan_mismatch"):
        validate_generation_plan(changed, request, "initial", "txt2img")

def test_standard_and_old_regional_routes_reject_two_stage_data(self) -> None:
    for request in (standard_request(), old_regional_request()):
        request["constraints"]["two_stage_layout"] = approved_layout()
        with self.assertRaisesRegex(ValidationError, "invalid_two_stage_conditioning"):
            validate_confirmed_run_request(request)
```

- [ ] **Step 2: Add failing Engine success, mismatch, and technical-partial tests**

Cover:

- both prompt pairs compiled by the same confirmed compiler version;
- subject seed derived rather than accepted from the caller;
- three distinct pending paths under the run root;
- exact workflow/control/bundle validation before the backend;
- zero protected mismatches commits one round;
- base-only result records partial;
- mask leak or one protected changed pixel records partial; and
- standard/old routes keep current behavior.

- [ ] **Step 3: Run focused plan and Engine tests**

Run: `python -m unittest tests.test_generation_plan tests.test_asset_run_engine tests.test_mcp_server -v`

Expected: FAIL on unknown two-stage fields and single-output Engine flow.

- [ ] **Step 4: Extend plan and start validation**

Pair exact route state:

```python
two_stage_route = route.get("workflow_template_id") == TWO_STAGE_TEMPLATE_ID
has_layout = "two_stage_layout" in constraints
has_conditioning = "two_stage_conditioning" in parameters
if two_stage_route != has_layout or two_stage_route != has_conditioning:
    raise ValidationError("invalid_two_stage_conditioning", "Two-stage route data is incomplete.")
```

For `action == "initial"`, normalized plan conditioning must equal `request["initial_two_stage_conditioning"]`. Later actions use Profile allowlists but layout remains equal to the route requirement. Add `two_stage_conditioning` to refine/explore lists in all three Profiles.

- [ ] **Step 5: Add exact MCP nested fields without changing the tool list**

`local_gpu_start_run` accepts optional `initial_two_stage_conditioning`. Existing required fields do not change. The nested schema requires exactly subject positive, subject negative, and denoise. Generation remains the existing `local_gpu_generate_round` tool and receives no caller-controlled subject seed.

- [ ] **Step 6: Implement Engine execution and technical gates**

The Engine must:

1. validate the confirmed route/layout/conditioning before `begin_attempt`;
2. compile base prompts through the existing plan path;
3. compile subject prompts through the same compiler ID/version and store the result as `compiled_subject_prompt`;
4. derive the subject seed;
5. create base, mask, and final pending paths;
6. resolve the two-stage workflow with all exact values;
7. validate the backend result and locked identities;
8. validate and atomically rename all three PNGs;
9. run `validate_saved_soft_mask` and `compare_protected_pixels`;
10. call `record_partial_attempt` on retained technical failure;
11. call `mark_attempt_artifacts` then `complete_attempt` only on zero mismatch; and
12. create previews only for the final image.

- [ ] **Step 7: Run focused Engine and MCP regressions**

Run: `python -m unittest tests.test_generation_plan tests.test_asset_run_engine tests.test_mcp_server tests.test_profile_registry -v`

Expected: PASS.

- [ ] **Step 8: Commit Engine execution**

```powershell
git add scripts/local_gpu_imagegen/generation_plan.py scripts/local_gpu_imagegen/engine.py scripts/mcp_server.py profiles/use-cases tests/test_generation_plan.py tests/test_asset_run_engine.py tests/test_mcp_server.py tests/test_profile_registry.py
git commit -m "feat: execute confirmed two-stage SDXL plans"
```

## Task 7: Bind Routing, Control Identity, And Trust

**Files:**
- Modify: `scripts/local_gpu_imagegen/model_catalog.py`
- Modify: `scripts/local_gpu_imagegen/model_router.py`
- Modify: `scripts/local_gpu_imagegen/trust_registry.py`
- Modify: `scripts/local_gpu_imagegen/services.py`
- Modify: focused catalog/router/trust/runtime tests

**Interfaces:**
- Produces: a route whose token binds normalized layout, `control_sha256`, and `component_bundle_sha256` for the exact new trust variant.
- Consumes: existing workflow-variant trust support and component-bundle construction.

- [ ] **Step 1: Write failing coexistence and no-fallback tests**

```python
def test_standard_regional_and_two_stage_variants_coexist_for_one_model(self) -> None:
    catalog = self.catalog_with_three_sdxl_variants()
    self.assertEqual(
        {item["workflow_template_id"] for item in catalog.list_models("public_evidence")},
        {"sdxl-txt2img", "sdxl-regional-txt2img", "sdxl-two-stage-copy-subject"},
    )

def test_two_stage_requirement_returns_only_exact_capable_variant(self) -> None:
    result = self.router.recommend(two_stage_requirements())
    self.assertEqual(len(result["routes"]), 1)
    route = result["routes"][0]
    self.assertEqual(route["workflow_template_id"], "sdxl-two-stage-copy-subject")
    self.assertEqual(route["control_sha256"], CONTROL_SHA256)

def test_two_stage_route_never_falls_back(self) -> None:
    for failure in ("capability", "workflow", "control", "bundle", "endpoint"):
        router = self.router_with_failure(failure)
        self.assertEqual(router.recommend(two_stage_requirements())["routes"], [])
```

- [ ] **Step 2: Run focused routing tests and confirm the new mode is unavailable**

Run: `python -m unittest tests.test_model_catalog tests.test_model_router tests.test_trust_registry tests.test_runtime_services -v`

Expected: FAIL because only `copy-subject-v1` is normalized and routed.

- [ ] **Step 3: Generalize optional layout requirements**

Allow exactly one of `regional_layout` or `two_stage_layout`, never both. Normalize each with its dedicated validator. Pass the selected mode to the generalized capability provider. `_hard_match` requires the workflow template associated with that mode and rejects layout-specific variants from ordinary requests.

- [ ] **Step 4: Bind the control digest into the route and lock verification**

Add `control_sha256` to the issued boundary only for `TWO_STAGE_TEMPLATE_ID`. Because route tokens hash the complete boundary, this binds the control digest. `verify_locked_route`, Engine start, backend result validation, and evidence validation must compare the same digest.

- [ ] **Step 5: Preserve existing trust records and add one new variant shape**

The trust registry keeps its current model/workflow-bundle variant key. For the two-stage variant, require `workflow_binding.control_sha256`. Reject this field on existing workflow IDs so their serialized identity and behavior do not drift. Revocation remains exact-variant only.

- [ ] **Step 6: Run focused route/trust tests**

Run: `python -m unittest tests.test_model_catalog tests.test_model_router tests.test_trust_registry tests.test_runtime_services -v`

Expected: PASS.

- [ ] **Step 7: Commit routing and trust binding**

```powershell
git add scripts/local_gpu_imagegen/model_catalog.py scripts/local_gpu_imagegen/model_router.py scripts/local_gpu_imagegen/trust_registry.py scripts/local_gpu_imagegen/services.py tests/test_model_catalog.py tests/test_model_router.py tests/test_trust_registry.py tests/test_runtime_services.py
git commit -m "feat: bind two-stage SDXL route identity"
```

## Task 8: Extend Review And Evidence Without Weakening Existing Runs

**Files:**
- Modify: `scripts/local_gpu_imagegen/visual_review.py`
- Modify: `scripts/local_gpu_imagegen/run_store.py`
- Modify: `scripts/export_acceptance_evidence.py`
- Modify: `scripts/validate_acceptance_evidence.py`
- Modify: `docs/evidence/schemas/run-evidence.schema.json`
- Modify: review/export/validator tests

**Interfaces:**
- Produces: exact `stage_checks` validation for only the new route and byte-bound exported stage evidence.
- Consumes: round stage records, mask record, pixel preservation record, and current finalization gates.

- [ ] **Step 1: Write failing stage-review tests**

```python
def passing_stage_checks() -> dict[str, object]:
    return {
        "base_copy_space": check("pass", "Left 45 percent is dark and low-detail."),
        "base_subject_absent": check("pass", "No telescope or focal machinery appears in base."),
        "final_subject_inside_mask": check("pass", "One complete telescope stays inside the mask."),
        "final_safe_margins": check("pass", "All telescope edges and tripod feet remain visible."),
        "final_forbidden_content": check("pass", "No text, people, controls, or anatomy artifacts."),
        "feather_transition": check("pass", "Boundary is visually coherent."),
        "pixel_preservation": check("pass", "Machine report records zero mismatches."),
    }

def test_two_stage_review_requires_exact_stage_checks(self) -> None:
    review = passing_review()
    review["stage_checks"] = passing_stage_checks()
    self.store.record_review(self.two_stage_run_id, 1, review)
    del review["stage_checks"]["pixel_preservation"]
    with self.assertRaisesRegex(ValidationError, "invalid_stage_checks"):
        self.store.record_review(self.other_two_stage_run_id, 1, review)

def test_standard_review_rejects_stage_checks_and_keeps_old_schema(self) -> None:
    review = passing_review()
    review["stage_checks"] = passing_stage_checks()
    with self.assertRaisesRegex(ValidationError, "invalid_review"):
        self.store.record_review(self.standard_run_id, 1, review)
```

- [ ] **Step 2: Add failing evidence export/validation tests**

Prove the package contains exact base, mask, and final paths/hashes, control digest, subject seed, stage budget, and zero-mismatch result. Reject missing files, extra files, changed hashes, mask leaks, nonzero mismatches, partial runs, and stage images referenced outside the package.

- [ ] **Step 3: Run focused review/evidence tests**

Run: `python -m unittest tests.test_visual_review tests.test_run_store tests.test_export_acceptance_evidence tests.test_validate_acceptance_evidence -v`

Expected: FAIL on unknown stage checks and evidence fields.

- [ ] **Step 4: Implement exact conditional stage checks**

Add `STAGE_CHECK_NAMES` with the seven names above. Each check has exactly `status` and `observation`; status is `pass`, `fail`, or `uncertain`. Two-stage finalization requires every status to be `pass` and the recorded pixel report to contain zero mismatches. Standard/historical routes reject `stage_checks` and retain current behavior.

- [ ] **Step 5: Export and validate stage provenance**

Copy stage/mask files byte-for-byte, use relative paths only, verify hashes before and after copy, and add the exact optional two-stage object to the evidence schema. The validator recomputes file hashes and rejects `partial` manifests. Do not treat base or mask as accepted images.

- [ ] **Step 6: Run focused review/evidence regressions**

Run: `python -m unittest tests.test_visual_review tests.test_run_store tests.test_export_acceptance_evidence tests.test_validate_acceptance_evidence -v`

Expected: PASS.

- [ ] **Step 7: Commit review and evidence support**

```powershell
git add scripts/local_gpu_imagegen/visual_review.py scripts/local_gpu_imagegen/run_store.py scripts/export_acceptance_evidence.py scripts/validate_acceptance_evidence.py docs/evidence/schemas/run-evidence.schema.json tests/test_visual_review.py tests/test_run_store.py tests/test_export_acceptance_evidence.py tests/test_validate_acceptance_evidence.py
git commit -m "feat: retain two-stage review evidence"
```

## Task 9: Teach The Agent, Document Scope, And Add A Vertical Slice

**Files:**
- Modify: `skills/local-gpu-imagegen/SKILL.md`
- Modify: `README.md`, `docs/architecture.md`, `docs/troubleshooting.md`, `CHANGELOG.md`
- Create: `tests/test_two_stage_vertical_slice.py`
- Modify: `tests/test_skill_contract.py`, `tests/test_public_docs.py`, `tests/test_packaging.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Produces: an exact confirmation/review flow and one model-free end-to-end lifecycle.
- Consumes: all prior tasks.

- [ ] **Step 1: Add failing Skill and public-document contract assertions**

Require the Skill to state:

- base prompt excludes the subject;
- exact pixel geometry plus percentages are displayed;
- base and derived subject seeds are displayed;
- workflow, control, and bundle digests are displayed;
- one round costs two stage units;
- both base and final require full-resolution review;
- partial output stops the run;
- no fallback is allowed; and
- the first GPU gate is exactly one two-stage round.

- [ ] **Step 2: Write the model-free vertical slice**

The fake backend must return deterministic 1280x720 base/mask/final PNGs whose protected pixels are equal and whose final changes only inside the subject mask. The test performs:

```text
catalog variants
  -> live capability true
  -> recommend exact two-stage route
  -> confirm route
  -> start run with layout and initial conditioning
  -> generate one two-stage round
  -> verify two stages, mask, pixel report, and budgets
  -> record passing stage review
  -> verify only final is a candidate
  -> mutate one protected pixel in a second fixture
  -> verify partial state and no candidate
```

- [ ] **Step 3: Run focused Skill, packaging, MCP, and vertical-slice tests**

Run: `python -m unittest tests.test_skill_contract tests.test_public_docs tests.test_packaging tests.test_mcp_server tests.test_two_stage_vertical_slice -v`

Expected: FAIL until docs/assets/schema assertions are updated.

- [ ] **Step 4: Update the Skill and public documentation truthfully**

Describe the old single-pass route as retained negative evidence/experimental compatibility. Do not claim visual improvement. List the new workflow among packaged assets, document the three artifacts and technical gates, and preserve the fifteen-tool surface.

- [ ] **Step 5: Run focused integration tests**

Run: `python -m unittest tests.test_skill_contract tests.test_public_docs tests.test_packaging tests.test_mcp_server tests.test_two_stage_vertical_slice -v`

Expected: PASS.

- [ ] **Step 6: Commit interaction and vertical-slice coverage**

```powershell
git add skills/local-gpu-imagegen/SKILL.md README.md docs/architecture.md docs/troubleshooting.md CHANGELOG.md tests/test_two_stage_vertical_slice.py tests/test_skill_contract.py tests/test_public_docs.py tests/test_packaging.py tests/test_mcp_server.py
git commit -m "docs: add two-stage SDXL control flow"
```

## Task 10: Run The Complete Model-Free Gate And Derive Exact Identities

**Files:**
- Modify outside the linked worktree: `<project-root>/PROJECT_NODES.md`
- Modify outside the linked worktree: `<project-root>/NEXT_SESSION.md`
- Modify only already-planned release metadata if tests prove packaged version/resource drift.

**Interfaces:**
- Produces: verified model-free milestone, exact workflow/control/bundle identities, clean branch, and an explicit later GPU confirmation boundary.
- Consumes: all previous tasks and the already installed checkpoint identity.

- [ ] **Step 1: Run Python compilation and the full suite**

```powershell
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
```

Expected: all tests pass with only the existing expected Windows link-privilege skips.

- [ ] **Step 2: Parse all tracked JSON and run repository gates**

```powershell
git ls-files '*.json' | ForEach-Object {
  $null = Get-Content -Raw -LiteralPath $_ | ConvertFrom-Json
}
python -m unittest tests.test_public_docs tests.test_repository_hygiene tests.test_packaging -v
git diff --check
```

Expected: all JSON parses, focused gates pass, and `git diff --check` reports no errors.

- [ ] **Step 3: Verify the immutable old wheel before any new build**

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\dist\local_gpu_imagegen-0.6.1-py3-none-any.whl
```

Expected SHA-256: `33ed4bc1564a92e3252b80f79cf1a7dd91f726774045801fd617bf9d0ef02655`.

- [ ] **Step 4: Build a new candidate only into a fresh scratch directory**

Use `%TEMP%\local-gpu-imagegen-verification\two-stage-<commit>`; never use or overwrite `dist/`.

```powershell
uv build --offline --wheel --out-dir $candidateDirectory
uv venv --python 3.12 $verificationVenv
uv pip install --offline --python "$verificationVenv\Scripts\python.exe" --no-deps $candidateWheel
& "$verificationVenv\Scripts\local-gpu-imagegen.exe" verify
```

Expected: installed package reports the active project version, exactly 15 tools, and includes all six ComfyUI workflows including `sdxl-two-stage-copy-subject-v1.json`.

- [ ] **Step 5: Perform read-only live signature and workflow inspection**

Query only the six `/object_info/<node>` endpoints, inspect the shipped workflow against the already installed SDXL component identity, and derive:

- exact workflow SHA-256;
- exact control SHA-256;
- exact component bundle SHA-256; and
- the exact workflow-bound trust confirmation token.

Do not submit `/prompt`, mutate trust, fingerprint unrelated roots, or load model tensors.

- [ ] **Step 6: Update continuity records**

Record in the project-root `PROJECT_NODES.md`:

- control flow;
- technical and visual failure modes;
- full verification commands/results;
- exact workflow/control/bundle digests;
- test count and skips;
- immutable old wheel digest;
- new scratch wheel digest/path;
- no-download/no-GPU/no-publication facts; and
- open limitation that visual quality remains unverified.

Replace the project-root `NEXT_SESSION.md` instructions with the exact later route summary and one-round GPU authority gate. These two continuity files are intentionally ignored and are not staged from the linked worktree.

- [ ] **Step 7: Verify the implementation commits and both worktree boundaries**

```powershell
git status --short --branch
git -C ..\.. status --short --branch
```

Expected: clean `feature/v061-launch-readiness` implementation worktree. The project root retains its pre-existing ignored/untracked local evidence state; only the two intended continuity files change outside Git tracking.

- [ ] **Step 8: Stop and display the exact GPU confirmation boundary**

Display checkpoint/component identity, workflow/control/bundle digests, route token, 1280x720 geometry, base and subject prompts, both seeds, two stage units, one round, no downloads, no model switch, no upscale, no export, and no publication. Do not perform GPU generation in the same message.

## Self-Review Checklist

- [ ] Every design-spec requirement maps to one task.
- [ ] No task weakens imported/standard workflow validation.
- [ ] Node IDs, role IDs, layout values, and seed derivation are consistent across tests, workflow, adapter, Engine, and docs.
- [ ] Partial technical output and visual rejection remain distinct states.
- [ ] Root and revision stage budgets use the same formula.
- [ ] Historical manifests and old workflow digests remain compatible.
- [ ] No code path can finalize base or mask artifacts.
- [ ] No fallback, model download, dependency install, or extra MCP tool was introduced.
- [ ] Complete model-free verification precedes identity derivation and GPU authority.

## Execution Handoff

After this plan is approved, execute Tasks 1-10 in order. Review each focused test result and commit before proceeding. Do not parallelize tasks that modify shared core files. Stop after Task 10 Step 8 for the user's exact GPU confirmation.
