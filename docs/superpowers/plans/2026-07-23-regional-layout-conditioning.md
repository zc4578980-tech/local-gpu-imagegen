# Regional Layout Conditioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed `copy-subject-v1` SDXL/ComfyUI route that binds one confirmed copy-safe rectangle and one confirmed subject rectangle into native regional conditioning while preserving the existing MCP surface and prompt-only routes.

**Architecture:** A new pure validation module owns the two-zone contract. The existing workflow registry renders one reviewed regional graph, the ComfyUI adapter proves the required native nodes both before recommendation and immediately before submission, and route/trust records bind the new workflow bundle without replacing the legacy SDXL route. Run requests retain the confirmed initial conditioning; generation plans freeze geometry but permit reviewed prompt/strength changes.

**Tech Stack:** Python 3.11/3.12 standard library, MCP JSON-RPC schemas, ComfyUI HTTP API, JSON workflow assets, `unittest`, `uv` wheel builds.

## Global Constraints

- Work only in the existing linked worktree on `feature/v061-launch-readiness`; do not modify `main`.
- Do not download a model, ControlNet, custom node, Python package, or dependency.
- Do not modify global Python or the user's separate `pytorch-vla` learning environment.
- Keep exactly 15 MCP tools and exactly 20 top-level generation-plan fields.
- Keep `workflows/comfyui/sdxl-txt2img-v1.json` byte-for-byte unchanged.
- Keep `dist/local_gpu_imagegen-0.6.1-py3-none-any.whl` unchanged at SHA-256 `33ed4bc1564a92e3252b80f79cf1a7dd91f726774045801fd617bf9d0ef02655`.
- Standard and imported workflows must reject regional data; no prompt-only fallback is allowed when regional layout is required.
- Model-free tests must not require ComfyUI, a GPU, or model weights.
- Do not push, tag, publish, export evidence, contact maintainers, or claim visual-quality improvement.
- Use TDD for every task and commit only after its focused tests pass.

---

## File Structure

**Create**

- `scripts/local_gpu_imagegen/regional_layout.py`: pure geometry, conditioning, and live-node-signature validation.
- `tests/test_regional_layout.py`: exhaustive contract tests independent of ComfyUI and GPU state.
- `workflows/comfyui/sdxl-regional-txt2img-v1.json`: the only reviewed two-zone graph.
- `tests/test_regional_vertical_slice.py`: model-free route-to-manifest lifecycle coverage.

**Modify**

- `scripts/local_gpu_imagegen/generation_plan.py`: pair regional route, confirmed layout, initial conditioning, and mutable later conditioning.
- `scripts/local_gpu_imagegen/workflow_templates.py`: accept the two built-in regional nodes only for the shipped regional template and bind all 12 regional scalar fields.
- `scripts/local_gpu_imagegen/backends/base.py`: expose a bounded backend-registry regional capability query.
- `scripts/local_gpu_imagegen/backends/comfyui.py`: inspect live signatures and independently revalidate the rendered graph before `POST /prompt`.
- `scripts/local_gpu_imagegen/trust_registry.py`: preserve legacy trust IDs and add workflow-bundle route variants.
- `scripts/local_gpu_imagegen/model_catalog.py`: retain multiple trusted bundles for one model identity and advertise optional regional modes.
- `scripts/local_gpu_imagegen/model_router.py`: normalize the optional layout requirement, filter on live capability, and bind geometry into the route token.
- `scripts/local_gpu_imagegen/services.py`: wire the shared ComfyUI capability provider into the router.
- `scripts/local_gpu_imagegen/engine.py`: verify the confirmed regional route and pass exact regional data to workflow rendering/backend validation.
- `scripts/mcp_server.py`: add optional nested fields and exact variant revocation without adding a tool.
- `profiles/use-cases/{standalone-illustration,presentation-visual,ui-visual-asset}.json`: allow the one nested `regional_conditioning` key during refine/explore.
- `skills/local-gpu-imagegen/SKILL.md`: gather, display, confirm, persist, and hot-modify the two-zone contract.
- Focused tests: `tests/test_generation_plan.py`, `tests/test_workflow_templates.py`, `tests/test_comfyui_adapter.py`, `tests/test_trust_registry.py`, `tests/test_model_catalog.py`, `tests/test_model_router.py`, `tests/test_runtime_services.py`, `tests/test_asset_run_engine.py`, `tests/test_mcp_server.py`, `tests/test_skill_contract.py`, and `tests/test_packaging.py`.
- Release surfaces: `pyproject.toml`, `scripts/local_gpu_imagegen/__init__.py`, `.codex-plugin/plugin.json`, `server.json`, `README.md`, `CHANGELOG.md`, and active release tests/docs that currently assert `0.6.1`.

## Task 1: Add Pure Two-Zone Contract Validation

**Files:**
- Create: `scripts/local_gpu_imagegen/regional_layout.py`
- Create: `tests/test_regional_layout.py`

**Interfaces:**
- Produces: `LAYOUT_MODE`, `REGIONAL_TEMPLATE_ID`, `validate_regional_layout(value)`, `validate_regional_conditioning(value)`, and `validate_regional_node_info(area_info, combine_info) -> None`.
- Consumes: `ValidationError` from `scripts/local_gpu_imagegen/errors.py`.

- [ ] **Step 1: Write failing geometry and conditioning tests**

```python
class RegionalLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = {
            "mode": "copy-subject-v1",
            "copy_region": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0},
            "subject_region": {"x": 0.68, "y": 0.0, "width": 0.30, "height": 1.0},
        }
        self.conditioning = {
            "copy_prompt": "dark empty low-detail copy space",
            "copy_strength": 1.15,
            "subject_prompt": "one complete brass telescope on a tripod",
            "subject_strength": 1.25,
        }

    def test_valid_contract_is_trimmed_and_deep_copied(self) -> None:
        conditioning = {**self.conditioning, "copy_prompt": "  empty copy space  "}
        layout = validate_regional_layout(self.layout)
        normalized = validate_regional_conditioning(conditioning)
        layout["copy_region"]["width"] = 0.2
        self.assertEqual(self.layout["copy_region"]["width"], 0.45)
        self.assertEqual(normalized["copy_prompt"], "empty copy space")

    def test_touching_regions_pass_but_interior_overlap_fails(self) -> None:
        touching = copy.deepcopy(self.layout)
        touching["subject_region"]["x"] = 0.45
        validate_regional_layout(touching)
        overlapping = copy.deepcopy(touching)
        overlapping["subject_region"]["x"] = 0.449
        with self.assertRaisesRegex(ValidationError, "invalid_regional_layout"):
            validate_regional_layout(overlapping)

    def test_invalid_numbers_bounds_fields_prompts_and_strengths_fail(self) -> None:
        invalid_layouts = [
            {**self.layout, "extra": True},
            {**self.layout, "copy_region": {**self.layout["copy_region"], "x": True}},
            {**self.layout, "copy_region": {**self.layout["copy_region"], "width": 0.0}},
            {**self.layout, "subject_region": {**self.layout["subject_region"], "x": 0.9, "width": 0.2}},
        ]
        for value in invalid_layouts:
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "invalid_regional_layout"):
                validate_regional_layout(value)
        for value in (
            {**self.conditioning, "copy_prompt": " "},
            {**self.conditioning, "subject_prompt": "x" * 501},
            {**self.conditioning, "copy_strength": -0.01},
            {**self.conditioning, "subject_strength": 2.01},
        ):
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "invalid_regional_conditioning"):
                validate_regional_conditioning(value)
```

- [ ] **Step 2: Run the new test and confirm the import failure**

Run: `python -m unittest tests.test_regional_layout -v`

Expected: FAIL because `local_gpu_imagegen.regional_layout` does not exist.

- [ ] **Step 3: Implement the complete pure validators**

```python
from __future__ import annotations

import copy
import math

from .errors import ValidationError

LAYOUT_MODE = "copy-subject-v1"
REGIONAL_TEMPLATE_ID = "sdxl-regional-txt2img"
REGION_FIELDS = frozenset({"x", "y", "width", "height"})
CONDITIONING_FIELDS = frozenset({
    "copy_prompt", "copy_strength", "subject_prompt", "subject_strength",
})


def validate_regional_layout(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"mode", "copy_region", "subject_region"}:
        raise _layout_error()
    if value["mode"] != LAYOUT_MODE:
        raise _layout_error()
    normalized = {"mode": LAYOUT_MODE}
    for name in ("copy_region", "subject_region"):
        region = value[name]
        if not isinstance(region, dict) or set(region) != REGION_FIELDS:
            raise _layout_error()
        if any(not _number(region[field]) for field in REGION_FIELDS):
            raise _layout_error()
        x, y = float(region["x"]), float(region["y"])
        width, height = float(region["width"]), float(region["height"])
        if not (0.0 <= x < 1.0 and 0.0 <= y < 1.0 and 0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            raise _layout_error()
        if x + width > 1.0 or y + height > 1.0:
            raise _layout_error()
        normalized[name] = copy.deepcopy(region)
    left = normalized["copy_region"]
    right = normalized["subject_region"]
    horizontal = min(left["x"] + left["width"], right["x"] + right["width"]) - max(left["x"], right["x"])
    vertical = min(left["y"] + left["height"], right["y"] + right["height"]) - max(left["y"], right["y"])
    if horizontal > 0.0 and vertical > 0.0:
        raise _layout_error()
    return normalized


def validate_regional_conditioning(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != CONDITIONING_FIELDS:
        raise _conditioning_error()
    normalized = copy.deepcopy(value)
    for field in ("copy_prompt", "subject_prompt"):
        prompt = normalized[field]
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.strip()) > 500:
            raise _conditioning_error()
        normalized[field] = prompt.strip()
    for field in ("copy_strength", "subject_strength"):
        if not _number(normalized[field]) or not 0.0 <= float(normalized[field]) <= 2.0:
            raise _conditioning_error()
    return normalized


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _layout_error() -> ValidationError:
    return ValidationError("invalid_regional_layout", "Regional layout is outside the copy-subject-v1 contract.")


def _conditioning_error() -> ValidationError:
    return ValidationError("invalid_regional_conditioning", "Regional conditioning is outside the copy-subject-v1 contract.")
```

Add this exact live-signature validator in the same module:

```python
def validate_regional_node_info(area_info: object, combine_info: object) -> None:
    area = _required_types(area_info, "ConditioningSetAreaPercentage")
    combine = _required_types(combine_info, "ConditioningCombine")
    expected_area = {
        "conditioning": "CONDITIONING", "width": "FLOAT", "height": "FLOAT",
        "x": "FLOAT", "y": "FLOAT", "strength": "FLOAT",
    }
    expected_combine = {
        "conditioning_1": "CONDITIONING", "conditioning_2": "CONDITIONING",
    }
    if area != expected_area or combine != expected_combine:
        raise ValidationError(
            "regional_layout_unavailable",
            "Required ComfyUI regional node signatures are unavailable.",
        )


def _required_types(value: object, class_name: str) -> dict[str, str]:
    node = value.get(class_name) if isinstance(value, dict) else None
    inputs = node.get("input") if isinstance(node, dict) else None
    required = inputs.get("required") if isinstance(inputs, dict) else None
    if not isinstance(required, dict):
        raise ValidationError("regional_layout_unavailable", "Required ComfyUI regional node is unavailable.")
    result: dict[str, str] = {}
    for name, specification in required.items():
        if (
            not isinstance(name, str)
            or not isinstance(specification, list)
            or not specification
            or not isinstance(specification[0], str)
        ):
            raise ValidationError("regional_layout_unavailable", "ComfyUI regional node signature is malformed.")
        result[name] = specification[0]
    return result
```

- [ ] **Step 4: Run the focused contract test**

Run: `python -m unittest tests.test_regional_layout -v`

Expected: all regional layout, conditioning, and node-signature tests PASS.

- [ ] **Step 5: Commit the pure contract**

```powershell
git add scripts/local_gpu_imagegen/regional_layout.py tests/test_regional_layout.py
git commit -m "feat: validate two-zone regional contracts"
```

## Task 2: Add the Reviewed Regional Workflow Template

**Files:**
- Create: `workflows/comfyui/sdxl-regional-txt2img-v1.json`
- Modify: `scripts/local_gpu_imagegen/workflow_templates.py:16-86,98-231,284-502,587-618`
- Modify: `tests/test_workflow_templates.py:86-318`

**Interfaces:**
- Consumes: Task 1 validators and constants.
- Produces: `WorkflowTemplateRegistry.resolve(..., regional_layout=None, regional_conditioning=None)` and `inspect_shipped(...)`; resolved regional workflows add `layout_mode` while standard results remain byte/schema compatible.

- [ ] **Step 1: Write failing registry tests**

```python
def test_reviewed_sdxl_regional_template_binds_all_confirmed_values(self) -> None:
    layout = {
        "mode": "copy-subject-v1",
        "copy_region": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0},
        "subject_region": {"x": 0.68, "y": 0.0, "width": 0.30, "height": 1.0},
    }
    conditioning = {
        "copy_prompt": "empty dark copy space", "copy_strength": 1.15,
        "subject_prompt": "complete telescope", "subject_strength": 1.25,
    }
    rendered = self.registry.resolve(
        "sdxl-regional-txt2img", "sd_xl_base_1.0.safetensors", "txt2img",
        self.settings, regional_layout=layout, regional_conditioning=conditioning,
    )
    graph = rendered["graph"]
    self.assertEqual(rendered["layout_mode"], "copy-subject-v1")
    self.assertEqual(graph["10"]["inputs"], {
        "conditioning": ["8", 0], "width": 0.45, "height": 1.0,
        "x": 0.0, "y": 0.0, "strength": 1.15,
    })
    self.assertEqual(graph["12"]["inputs"]["x"], 0.68)
    self.assertEqual(graph["11"]["inputs"]["text"], "complete telescope")

def test_regional_template_requires_data_and_imports_cannot_use_regional_nodes(self) -> None:
    with self.assertRaisesRegex(ValidationError, "invalid_regional_layout"):
        self.registry.resolve(
            "sdxl-regional-txt2img", "sd_xl_base_1.0.safetensors", "txt2img", self.settings,
        )
    graph = copy.deepcopy(self.safe_graph)
    graph["20"] = {"class_type": "ConditioningCombine", "inputs": {
        "conditioning_1": ["6", 0], "conditioning_2": ["7", 0],
    }}
    with self.assertRaisesRegex(ValidationError, "unsafe_comfy_workflow"):
        validate_imported_workflow(graph, self.binding, [MODEL])
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `python -m unittest tests.test_workflow_templates -v`

Expected: FAIL because the regional template and optional arguments do not exist.

- [ ] **Step 3: Create the exact reviewed graph**

Use these exact node identities and edges in `sdxl-regional-txt2img-v1.json`:

```json
{
  "schema_version": 1,
  "template_id": "sdxl-regional-txt2img",
  "template_version": 1,
  "operation": "txt2img",
  "model_families": ["sdxl"],
  "layout_mode": "copy-subject-v1",
  "allowed_node_classes": ["CheckpointLoaderSimple", "CLIPTextEncode", "ConditioningSetAreaPercentage", "ConditioningCombine", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage"],
  "output_node": "16",
  "bindings": {
    "model": ["4", "inputs", "ckpt_name"],
    "positive_prompt": ["6", "inputs", "text"],
    "negative_prompt": ["7", "inputs", "text"],
    "seed": ["3", "inputs", "seed"],
    "steps": ["3", "inputs", "steps"],
    "guidance_scale": ["3", "inputs", "cfg"],
    "sampler": ["3", "inputs", "sampler_name"],
    "scheduler": ["3", "inputs", "scheduler"],
    "width": ["5", "inputs", "width"],
    "height": ["5", "inputs", "height"]
  },
  "regional_bindings": {
    "copy_prompt": ["8", "inputs", "text"],
    "copy_x": ["10", "inputs", "x"], "copy_y": ["10", "inputs", "y"],
    "copy_width": ["10", "inputs", "width"], "copy_height": ["10", "inputs", "height"],
    "copy_strength": ["10", "inputs", "strength"],
    "subject_prompt": ["11", "inputs", "text"],
    "subject_x": ["12", "inputs", "x"], "subject_y": ["12", "inputs", "y"],
    "subject_width": ["12", "inputs", "width"], "subject_height": ["12", "inputs", "height"],
    "subject_strength": ["12", "inputs", "strength"]
  },
  "graph": {
    "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 30, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0, "model": ["4", 0], "positive": ["14", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
    "8": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
    "10": {"class_type": "ConditioningSetAreaPercentage", "inputs": {"conditioning": ["8", 0], "width": 0.45, "height": 1.0, "x": 0.0, "y": 0.0, "strength": 1.15}},
    "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
    "12": {"class_type": "ConditioningSetAreaPercentage", "inputs": {"conditioning": ["11", 0], "width": 0.30, "height": 1.0, "x": 0.68, "y": 0.0, "strength": 1.25}},
    "13": {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": ["6", 0], "conditioning_2": ["10", 0]}},
    "14": {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": ["13", 0], "conditioning_2": ["12", 0]}},
    "15": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "16": {"class_type": "SaveImage", "inputs": {"filename_prefix": "local-gpu-imagegen", "images": ["15", 0]}}
  }
}
```

- [ ] **Step 4: Extend registry validation without weakening imports**

```python
REGIONAL_NODE_CLASSES = frozenset({"ConditioningSetAreaPercentage", "ConditioningCombine"})
REGIONAL_BINDING_KEYS = frozenset({
    "copy_prompt", "copy_x", "copy_y", "copy_width", "copy_height", "copy_strength",
    "subject_prompt", "subject_x", "subject_y", "subject_width", "subject_height", "subject_strength",
})

layout_mode = template.get("layout_mode")
if layout_mode is None:
    if regional_layout is not None or regional_conditioning is not None:
        raise ValidationError("invalid_regional_conditioning", "Standard workflows reject regional data.")
elif layout_mode == LAYOUT_MODE:
    layout = validate_regional_layout(regional_layout)
    conditioning = validate_regional_conditioning(regional_conditioning)
    values = {
        "copy_prompt": conditioning["copy_prompt"],
        "copy_x": layout["copy_region"]["x"], "copy_y": layout["copy_region"]["y"],
        "copy_width": layout["copy_region"]["width"], "copy_height": layout["copy_region"]["height"],
        "copy_strength": conditioning["copy_strength"],
        "subject_prompt": conditioning["subject_prompt"],
        "subject_x": layout["subject_region"]["x"], "subject_y": layout["subject_region"]["y"],
        "subject_width": layout["subject_region"]["width"], "subject_height": layout["subject_region"]["height"],
        "subject_strength": conditioning["subject_strength"],
    }
    for key, scalar in values.items():
        _set_binding(graph, template["regional_bindings"][key], scalar)
else:
    raise ArtifactError("invalid_workflow_template", "Reviewed layout mode is unsupported.")
```

The `resolve` signature is exactly `resolve(template_id, model_id, operation, parameters, *, regional_layout=None, regional_conditioning=None)`. Its returned dictionary adds `layout_mode` only for the regional template. Implement `inspect_shipped(template_id, model_id, operation, parameters)` as a separate read-only renderer used only for component-bundle inspection: it validates the shipped document and standard bindings while retaining its reviewed static regional scalars. It must never be called by generation.

- [ ] **Step 5: Run registry and old-digest tests**

Run: `python -m unittest tests.test_workflow_templates -v`

Expected: PASS, including an assertion that the SHA-256 of `sdxl-txt2img-v1.json` remains `05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e`.

- [ ] **Step 6: Commit the workflow boundary**

```powershell
git add workflows/comfyui/sdxl-regional-txt2img-v1.json scripts/local_gpu_imagegen/workflow_templates.py tests/test_workflow_templates.py
git commit -m "feat: add reviewed SDXL regional workflow"
```

## Task 3: Add Live ComfyUI Capability And Submission Drift Checks

**Files:**
- Modify: `scripts/local_gpu_imagegen/backends/base.py:22-41,224-306`
- Modify: `scripts/local_gpu_imagegen/backends/comfyui.py:41-166,268-526`
- Modify: `tests/test_comfyui_adapter.py:43-443`

**Interfaces:**
- Consumes: Task 1 `validate_regional_node_info` and Task 2 resolved workflow shape.
- Produces: `ComfyUIAdapter.regional_layout_capability(mode)` and `BackendRegistry.regional_layout_capability(mode)` returning `{mode, available, endpoint_identity, reason}`.

- [ ] **Step 1: Add failing live-signature and pre-submit drift tests**

```python
def install_regional_object_info(self) -> None:
    self.server.routes[("GET", "/object_info/ConditioningSetAreaPercentage")] = FakeResponse.json({
        "ConditioningSetAreaPercentage": {"input": {"required": {
            "conditioning": ["CONDITIONING", {}], "width": ["FLOAT", {}],
            "height": ["FLOAT", {}], "x": ["FLOAT", {}], "y": ["FLOAT", {}],
            "strength": ["FLOAT", {}],
        }}}
    })
    self.server.routes[("GET", "/object_info/ConditioningCombine")] = FakeResponse.json({
        "ConditioningCombine": {"input": {"required": {
            "conditioning_1": ["CONDITIONING", {}],
            "conditioning_2": ["CONDITIONING", {}],
        }}}
    })

def test_regional_capability_requires_both_exact_required_signatures(self) -> None:
    self.install_regional_object_info()
    self.assertTrue(self.adapter.regional_layout_capability("copy-subject-v1")["available"])
    drifted = copy.deepcopy(self.server.routes[("GET", "/object_info/ConditioningCombine")])
    drifted.body = drifted.body.replace(b"conditioning_2", b"conditioning_x")
    self.server.routes[("GET", "/object_info/ConditioningCombine")] = drifted
    self.assertFalse(self.adapter.regional_layout_capability("copy-subject-v1")["available"])

def test_regional_generate_rechecks_nodes_before_prompt_submission(self) -> None:
    self.install_regional_object_info()
    request = self.regional_request()
    self.server.routes.pop(("GET", "/object_info/ConditioningCombine"))
    with self.assertRaisesRegex(ConflictError, "regional_layout_drifted"):
        self.adapter.generate(request)
    self.assertFalse(any(item["method"] == "POST" for item in self.server.requests))
```

- [ ] **Step 2: Run the adapter test and confirm failure**

Run: `python -m unittest tests.test_comfyui_adapter -v`

Expected: FAIL because no regional capability method or request branch exists.

- [ ] **Step 3: Implement bounded capability probing**

```python
def regional_layout_capability(self, mode: str) -> dict[str, object]:
    if mode != LAYOUT_MODE:
        return {"mode": mode, "available": False, "endpoint_identity": self.endpoint_identity, "reason": "unsupported_layout_mode"}
    try:
        area = self.client.get_json("/object_info/ConditioningSetAreaPercentage")
        combine = self.client.get_json("/object_info/ConditioningCombine")
        validate_regional_node_info(area, combine)
    except AssetEngineError as error:
        return {"mode": mode, "available": False, "endpoint_identity": self.endpoint_identity, "reason": error.code}
    return {"mode": mode, "available": True, "endpoint_identity": self.endpoint_identity, "reason": None}
```

Add the delegating registry method. It returns `regional_layout_unavailable` when no ComfyUI adapter is registered and never probes WebUI or Diffusers.

- [ ] **Step 4: Add exact regional graph validation before submission**

For regional requests, require exact request fields `regional_layout` and `regional_conditioning`, resolved workflow `layout_mode == copy-subject-v1`, node counts `{CLIPTextEncode: 4, ConditioningSetAreaPercentage: 2, ConditioningCombine: 2}`, exact prompt multiset, both exact area tuples, and the existing model/sampler/dimensions/output checks. Immediately before `POST /prompt`, call `regional_layout_capability`; if unavailable, raise `ConflictError("regional_layout_drifted", ...)`.

```python
if workflow.get("layout_mode") == LAYOUT_MODE:
    capability = self.regional_layout_capability(LAYOUT_MODE)
    if capability["available"] is not True:
        raise ConflictError(
            "regional_layout_drifted",
            "Required ComfyUI regional nodes changed before submission.",
        )
```

- [ ] **Step 5: Run focused adapter regression tests**

Run: `python -m unittest tests.test_comfyui_adapter tests.test_backend_contract -v`

Expected: PASS; standard generation still performs no regional `/object_info` requests.

- [ ] **Step 6: Commit live capability enforcement**

```powershell
git add scripts/local_gpu_imagegen/backends/base.py scripts/local_gpu_imagegen/backends/comfyui.py tests/test_comfyui_adapter.py
git commit -m "feat: fail closed on ComfyUI regional drift"
```

## Task 4: Make Trust Records Workflow-Variant Aware

**Files:**
- Modify: `scripts/local_gpu_imagegen/trust_registry.py:53-305,399-509`
- Modify: `scripts/mcp_server.py:461-516,1493-1565`
- Modify: `tests/test_trust_registry.py:60-350`
- Modify: `tests/test_mcp_server.py:80-170,360-620`

**Interfaces:**
- Produces: `_variant_catalog_id(identity_token, bundle_sha256)` and `TrustRegistry.revoke(catalog_id: str | None, identity, confirmation)`.
- Compatibility: exact legacy identity/bundle pairs keep their old ID; old documents remain readable without rewrite.

- [ ] **Step 1: Write failing coexistence, collision, reapproval, and revoke tests**

```python
def test_same_identity_can_keep_legacy_and_add_new_bundle_variant(self) -> None:
    record = discovery_record(identity_strength="cryptographic", sha256="a" * 64)
    bundle_a = component_bundle(workflow_sha256="c" * 64)
    bundle_b = component_bundle(workflow_sha256="d" * 64)
    capabilities = {"operations": ["txt2img"]}
    token = identity_token(record)
    legacy_id = "local:" + token.removeprefix("model:")[:24]
    self.registry.approve_private(
        record,
        self.registry.confirmation_value("approve_private", record),
        capabilities=capabilities,
    )
    document = json.loads((self.root / "trust.json").read_text(encoding="utf-8"))
    document["records"][0]["workflow_binding"] = {"backend": "comfyui", "component_bundle_sha256": bundle_a["bundle_sha256"]}
    document["records"][0]["component_bundle"] = bundle_a
    self.registry._write(document)
    first = self.registry.approve_private(
        record,
        self.registry.confirmation_value("approve_private", record, bundle_a),
        capabilities=capabilities,
        workflow_binding=document["records"][0]["workflow_binding"],
        component_bundle=bundle_a,
    )
    second = self.registry.approve_private(
        record,
        self.registry.confirmation_value("approve_private", record, bundle_b),
        capabilities=capabilities,
        workflow_binding={"backend": "comfyui", "component_bundle_sha256": bundle_b["bundle_sha256"]},
        component_bundle=bundle_b,
    )
    records = self.registry.list_records()
    self.assertEqual(len(records), 2)
    self.assertEqual(first["catalog_id"], legacy_id)
    self.assertNotEqual(first["catalog_id"], second["catalog_id"])
    self.assertEqual({item["identity_token"] for item in records}, {token})

def test_ambiguous_revoke_requires_exact_catalog_id(self) -> None:
    records = self.install_two_variants()
    token = records[0]["identity_token"]
    with self.assertRaisesRegex(ValidationError, "ambiguous_trust_variant"):
        self.registry.revoke(None, token, "unused")
    selected = records[1]["catalog_id"]
    result = self.registry.revoke(selected, token, f"revoke:{selected}:{token}")
    self.assertEqual(result["catalog_id"], selected)
    self.assertEqual(len(self.registry.list_records()), 1)
```

Change the existing `component_bundle()` test helper to accept `workflow_sha256: str = "c" * 64` and use that argument as the workflow `sha256`. Import `identity_token` beside `build_component_bundle`. Add this test helper:

```python
def install_two_variants(self) -> list[dict[str, object]]:
    record = discovery_record(identity_strength="cryptographic", sha256="a" * 64)
    bundle_a = component_bundle(workflow_sha256="c" * 64)
    bundle_b = component_bundle(workflow_sha256="d" * 64)
    capabilities = {"operations": ["txt2img"]}
    self.registry.approve_private(
        record,
        self.registry.confirmation_value("approve_private", record),
        capabilities=capabilities,
    )
    document = json.loads((self.root / "trust.json").read_text(encoding="utf-8"))
    document["records"][0]["workflow_binding"] = {
        "backend": "comfyui",
        "component_bundle_sha256": bundle_a["bundle_sha256"],
    }
    document["records"][0]["component_bundle"] = bundle_a
    self.registry._write(document)
    for bundle in (bundle_a, bundle_b):
        self.registry.approve_private(
            record,
            self.registry.confirmation_value("approve_private", record, bundle),
            capabilities=capabilities,
            workflow_binding={
                "backend": "comfyui",
                "component_bundle_sha256": bundle["bundle_sha256"],
            },
            component_bundle=bundle,
        )
    return self.registry.list_records()
```

- [ ] **Step 2: Run trust tests and confirm the replacement bug**

Run: `python -m unittest tests.test_trust_registry tests.test_mcp_server -v`

Expected: FAIL because approval currently derives only the legacy model ID and replaces the first bundle.

- [ ] **Step 3: Implement exact pair lookup and variant ID derivation**

```python
def _bundle_sha(record: dict[str, object]) -> str | None:
    bundle = record.get("component_bundle")
    return str(bundle["bundle_sha256"]) if isinstance(bundle, dict) else None


def _variant_catalog_id(token: str, bundle_sha256: str) -> str:
    digest = hashlib.sha256(f"{token}\n{bundle_sha256}".encode("utf-8")).hexdigest()
    return "local:" + digest[:24]
```

In `_approve`, find the previous record by exact `(identity_token, bundle_sha256)` first and preserve its `catalog_id`; otherwise derive a variant ID for a bundle or the legacy ID without a bundle. Before writing, reject any same-ID/different-pair record with `catalog_id_collision`. Preserve evidence only from the exact pair.

In `_validate_document`, accept either the legacy ID or the bundle-derived ID, reject duplicate pairs even under different IDs, and require a bundle for a variant ID.

- [ ] **Step 4: Add optional exact catalog ID to the existing MCP tool**

```python
"catalog_id": {"type": "string", "pattern": "^local:[0-9a-f]{24}$"}
```

Pass `arguments.get("catalog_id")` to `TrustRegistry.revoke`. When omitted, resolve only one record for the identity; when multiple records exist, return `ambiguous_trust_variant` with sorted candidate IDs. Keep the confirmation `revoke:<catalog_id>:<identity_token>`.

- [ ] **Step 5: Run focused trust and MCP tests**

Run: `python -m unittest tests.test_trust_registry tests.test_mcp_server -v`

Expected: PASS and `len(tool_schema()) == 15`.

- [ ] **Step 6: Commit route-variant trust**

```powershell
git add scripts/local_gpu_imagegen/trust_registry.py scripts/mcp_server.py tests/test_trust_registry.py tests/test_mcp_server.py
git commit -m "feat: preserve workflow-bound trust variants"
```

## Task 5: Route Regional Requirements Only Through Capable Live Endpoints

**Files:**
- Modify: `scripts/local_gpu_imagegen/model_catalog.py:246-360,422-498`
- Modify: `scripts/local_gpu_imagegen/model_router.py:12-300`
- Modify: `scripts/local_gpu_imagegen/services.py:13-82`
- Modify: `scripts/mcp_server.py:519-552`
- Modify: `tests/test_model_catalog.py:131-441`
- Modify: `tests/test_model_router.py:17-235`
- Modify: `tests/test_runtime_services.py:19-43`
- Modify: `tests/test_mcp_server.py:80-170,300-360`

**Interfaces:**
- Consumes: Task 3 capability provider and Task 4 multiple trust records.
- Produces: optional `regional_layout` requirement and route reason `regional_layout_unavailable`.

- [ ] **Step 1: Write failing catalog/router tests**

```python
def test_regional_requirement_filters_workflow_mode_and_live_endpoint(self) -> None:
    layout = {
        "mode": "copy-subject-v1",
        "copy_region": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0},
        "subject_region": {"x": 0.68, "y": 0.0, "width": 0.30, "height": 1.0},
    }
    self.catalog.models = [self.regional_model, self.ordinary_model]
    self.capability = {
        "mode": "copy-subject-v1", "available": True,
        "endpoint_identity": self.regional_model["endpoint_identity"], "reason": None,
    }
    result = self.router.recommend(requirements(regional_layout=layout))
    self.assertEqual([item["model_id"] for item in result["routes"]], [self.regional_model["id"]])
    changed = copy.deepcopy(layout)
    changed["copy_region"]["width"] = 0.40
    other = self.router.recommend(requirements(regional_layout=changed))
    self.assertNotEqual(result["routes"][0]["route_token"], other["routes"][0]["route_token"])

def test_unavailable_nodes_return_no_route_without_fallback(self) -> None:
    self.capability["available"] = False
    result = self.router.recommend(requirements(regional_layout=self.layout))
    self.assertEqual(result["routes"], [])
    self.assertEqual(result["reason"], "regional_layout_unavailable")
```

- [ ] **Step 2: Run routing tests and confirm failure**

Run: `python -m unittest tests.test_model_catalog tests.test_model_router tests.test_runtime_services -v`

Expected: FAIL because route requirements reject the new field and services do not provide live capability.

- [ ] **Step 3: Extend capability documents compatibly**

Allow optional `regional_layout_modes` in trusted capability documents. Normalize absence to `[]`; accept only a unique string list whose only v1 value is `copy-subject-v1`. Emit it inside each catalog model's `capabilities`. Existing records with the old exact field set remain valid.

Use `WorkflowTemplateRegistry.inspect_shipped` in catalog and trust inspection so regional generation still cannot invent geometry or conditioning.

- [ ] **Step 4: Extend the router and bind the exact geometry**

```python
OPTIONAL_REQUIREMENT_FIELDS = frozenset({"regional_layout"})

def __init__(
    self, catalog: object, compilers: PromptCompilerRegistry, *,
    regional_capability_provider: Callable[[str], dict[str, object]] | None = None,
    clock: Callable[[], float] = time.time, ttl_seconds: float = 300,
) -> None:
    self.regional_capability_provider = regional_capability_provider
```

Accept either the old exact requirement field set or that set plus `regional_layout`. Normalize the layout with Task 1. Probe once per regional recommendation. `_hard_match` must require ComfyUI, matching endpoint identity, `sdxl-regional-txt2img`, and the requested mode in `capabilities.regional_layout_modes`. The normalized layout stays inside `route.requirements`, so the existing canonical route hash binds every coordinate.

- [ ] **Step 5: Wire services and MCP schema**

```python
router = CapabilityRouter(
    catalog,
    compilers,
    regional_capability_provider=backends.regional_layout_capability,
)
```

Add optional `regional_layout: {"type": "object"}` to `local_gpu_recommend_models`; do not add a tool or make the field required for standard calls.

- [ ] **Step 6: Run routing and MCP tests**

Run: `python -m unittest tests.test_model_catalog tests.test_model_router tests.test_runtime_services tests.test_mcp_server -v`

Expected: PASS; ordinary recommendations do not call the regional provider.

- [ ] **Step 7: Commit regional routing**

```powershell
git add scripts/local_gpu_imagegen/model_catalog.py scripts/local_gpu_imagegen/model_router.py scripts/local_gpu_imagegen/services.py scripts/mcp_server.py tests/test_model_catalog.py tests/test_model_router.py tests/test_runtime_services.py tests/test_mcp_server.py
git commit -m "feat: route confirmed regional layouts"
```

## Task 6: Persist Initial Conditioning And Execute Exact Regional Plans

**Files:**
- Modify: `scripts/local_gpu_imagegen/generation_plan.py:12-180`
- Modify: `scripts/local_gpu_imagegen/engine.py:82-134,153-296,912-1008`
- Modify: `scripts/mcp_server.py:553-610`
- Modify: `profiles/use-cases/standalone-illustration.json`
- Modify: `profiles/use-cases/presentation-visual.json`
- Modify: `profiles/use-cases/ui-visual-asset.json`
- Modify: `tests/test_generation_plan.py:18-143`
- Modify: `tests/test_asset_run_engine.py:272-1050`
- Modify: `tests/test_mcp_server.py:80-170,620-970`

**Interfaces:**
- Consumes: confirmed `route.requirements.regional_layout` and Task 2 workflow renderer.
- Produces: optional start field `initial_regional_conditioning`; generation plans retain the same 20 top-level fields.

- [ ] **Step 1: Write failing generation-plan tests**

```python
def test_regional_initial_plan_matches_confirmation_and_geometry_is_frozen(self) -> None:
    request, plan = self.regional_contract()
    validated = validate_generation_plan(plan, request, "initial")
    self.assertEqual(validated["parameters"]["regional_conditioning"], request["initial_regional_conditioning"])
    changed = copy.deepcopy(plan)
    changed["constraints"]["regional_layout"]["copy_region"]["width"] = 0.40
    with self.assertRaisesRegex(ValidationError, "generation_plan_mismatch"):
        validate_generation_plan(changed, request, "refine")

def test_regional_refine_can_change_conditioning_but_standard_route_rejects_it(self) -> None:
    request, plan = self.regional_contract()
    changed = copy.deepcopy(plan)
    changed["parameters"]["regional_conditioning"]["subject_strength"] = 1.4
    validate_generation_plan(changed, request, "refine")
    standard = copy.deepcopy(self.plan)
    standard["parameters"]["regional_conditioning"] = changed["parameters"]["regional_conditioning"]
    with self.assertRaisesRegex(ValidationError, "invalid_regional_conditioning"):
        validate_generation_plan(standard, self.run_request, "initial")
```

- [ ] **Step 2: Run plan/engine tests and confirm failure**

Run: `python -m unittest tests.test_generation_plan tests.test_asset_run_engine tests.test_mcp_server -v`

Expected: FAIL because start requests and backend rendering do not carry regional data.

- [ ] **Step 3: Enforce pairing and initial equality**

```python
def _validate_regional_plan(
    plan: dict[str, object], run_request: dict[str, object], action: str,
) -> None:
    layout = plan["constraints"].get("regional_layout")
    conditioning = plan["parameters"].get("regional_conditioning")
    regional_route = plan["workflow_template_id"] == REGIONAL_TEMPLATE_ID
    if regional_route:
        normalized_layout = validate_regional_layout(layout)
        normalized_conditioning = validate_regional_conditioning(conditioning)
        if action == "initial" and normalized_conditioning != run_request.get("initial_regional_conditioning"):
            raise ValidationError("generation_plan_mismatch", "Initial regional conditioning differs from confirmation.")
    elif layout is not None or conditioning is not None or "initial_regional_conditioning" in run_request:
        raise ValidationError("invalid_regional_conditioning", "Standard routes cannot accept regional data.")
```

At confirmed-run validation, require `initial_regional_conditioning` exactly when the route template and `constraints.regional_layout` are regional. Keep `PLAN_REQUIRED` unchanged and assert `len(PLAN_REQUIRED) == 20` in tests.

Append `regional_conditioning` once to both mutable arrays in all three stable Profile JSON files.

- [ ] **Step 4: Bind route geometry at start and pass exact backend data**

In `_validate_start_route`, compare `route["requirements"].get("regional_layout")` with `merged["constraints"].get("regional_layout")` after normalization. In `_backend_request`, pass both normalized objects to `workflows.resolve` and include them in the ComfyUI request only for the regional template.

```python
regional_layout = plan["constraints"].get("regional_layout")
regional_conditioning = parameters.get("regional_conditioning")
request["workflow"] = workflows.resolve(
    template_id,
    str(model.get("backend_model_id")),
    mode,
    workflow_parameters,
    regional_layout=regional_layout,
    regional_conditioning=regional_conditioning,
)
if regional_layout is not None:
    request["regional_layout"] = copy.deepcopy(regional_layout)
    request["regional_conditioning"] = copy.deepcopy(regional_conditioning)
```

- [ ] **Step 5: Add the optional MCP start field**

Add `initial_regional_conditioning` as an optional object property of `local_gpu_start_run`. Existing required fields and all 15 tool names remain unchanged. Add MCP tests that forward it byte-for-byte and reject unknown nested route/plan combinations before an attempt.

- [ ] **Step 6: Run focused generation tests**

Run: `python -m unittest tests.test_generation_plan tests.test_asset_run_engine tests.test_mcp_server tests.test_profile_registry -v`

Expected: PASS; invalid regional data creates neither a run nor an attempt and never invokes the backend.

- [ ] **Step 7: Commit regional run execution**

```powershell
git add scripts/local_gpu_imagegen/generation_plan.py scripts/local_gpu_imagegen/engine.py scripts/mcp_server.py profiles/use-cases/standalone-illustration.json profiles/use-cases/presentation-visual.json profiles/use-cases/ui-visual-asset.json tests/test_generation_plan.py tests/test_asset_run_engine.py tests/test_mcp_server.py
git commit -m "feat: execute confirmed regional plans"
```

## Task 7: Teach The Agent Skill The Regional Confirmation Loop

**Files:**
- Modify: `skills/local-gpu-imagegen/SKILL.md:32-105,140-152`
- Modify: `tests/test_skill_contract.py:137-530`

**Interfaces:**
- Consumes: optional recommend/start fields and the existing exact 20-field plan reconstruction.
- Produces: user-facing boundary gathering, percentage display, post-display confirmation, and hot modification rules.

- [ ] **Step 1: Add failing Skill contract assertions**

```python
def test_regional_route_requires_displayed_geometry_conditioning_and_later_confirmation(self) -> None:
    required = (
        "copy-subject-v1", "copy_region", "subject_region",
        "initial_regional_conditioning", "copy_prompt", "subject_prompt",
        "copy_strength", "subject_strength", "regional_layout_unavailable",
        "sdxl-regional-txt2img",
    )
    for phrase in required:
        with self.subTest(phrase=phrase):
            self.assertIn(phrase, self.skill)
    self.assertRegex(self.skill, r"display.*percentage.*before.*confirm")
    self.assertRegex(self.skill, r"geometry.*frozen")

def test_regional_skill_forbids_prompt_only_fallback_and_geometry_hot_mutation(self) -> None:
    self.assertIn("Never fall back to `sdxl-txt2img`", self.skill)
    self.assertIn("new root or child revision", self.skill)
    self.assertIn("change only regional prompts or strengths", self.skill)
```

- [ ] **Step 2: Run Skill tests and confirm failure**

Run: `python -m unittest tests.test_skill_contract -v`

Expected: FAIL because the regional branch is not documented.

- [ ] **Step 3: Add the exact Skill workflow**

Add a `Regional copy-subject route` section with this operational order:

```text
1. Ask only for missing copy-side/size, subject-side/size, regional prompt intent, strengths, and round budget.
2. Normalize one copy_region and one subject_region; reject overlap and ambiguity.
3. Call local_gpu_recommend_models with regional_layout.
4. Display normalized decimals and percentages, both regional prompts/strengths, exact route/bundle/compiler/dimensions, policies, and budget.
5. Wait for a later explicit confirmation of that displayed summary.
6. Call local_gpu_start_run with constraints.regional_layout and initial_regional_conditioning.
7. Fetch the persisted run and construct the existing exact 20-field plan with parameters.regional_conditioning.
8. On refine/explore, change only regional prompts or strengths unless another already-allowed parameter is explicitly selected; geometry remains frozen.
9. A geometry change requires a newly confirmed root or child revision. Never fall back to sdxl-txt2img when regional capability is unavailable or drifted.
```

State that a successful backend round which violates the copy/subject relation is retained and reviewed as `explicit_constraint_violation`; it still consumes one successful-round budget slot.

- [ ] **Step 4: Run Skill and packaging asset tests**

Run: `python -m unittest tests.test_skill_contract tests.test_packaging -v`

Expected: PASS with no change to the 15-tool assertion.

- [ ] **Step 5: Commit the Agent interaction contract**

```powershell
git add skills/local-gpu-imagegen/SKILL.md tests/test_skill_contract.py
git commit -m "docs: add regional Agent confirmation flow"
```

## Task 8: Add A Model-Free Regional Vertical Slice

**Files:**
- Create: `tests/test_regional_vertical_slice.py`
- Modify: `tests/test_packaging.py:94-150`

**Interfaces:**
- Consumes: Tasks 1-7 public MCP/engine interfaces.
- Produces: one deterministic fake-backend lifecycle proving route, initial run, two attempts, reviews, exhaustion, and retained conditioning.

- [ ] **Step 1: Write the lifecycle verification test**

Create a test fixture with two trusted records sharing the SDXL identity: legacy `sdxl-txt2img` and bundle-derived `sdxl-regional-txt2img`. Use a fake live capability provider reporting the exact endpoint. Then execute:

```python
recommendation = router.recommend({**requirements, "regional_layout": layout})
route = router.confirm(recommendation["routes"][0]["route_token"], regional_catalog_id)
started = engine.start_run({
    "intent": "Telescope hero with left copy space",
    "profile": "ui-visual-asset", "subtype": "hero", "style": None,
    "constraints": {"width": 1280, "height": 720, "regional_layout": layout},
    "initial_regional_conditioning": initial_conditioning,
    "model_choice": regional_catalog_id, "backend": "comfyui",
    "authorization_scope": "public_evidence", "route_token": route["route_token"],
    "max_rounds": 2, "upscale_policy": "off",
})
```

Generate round 1 with the exact initial conditioning, record a failed structured review, generate round 2 with changed `subject_strength`, and record another failed review. Assert:

```python
self.assertEqual(manifest["request"]["constraints"]["regional_layout"], layout)
self.assertEqual(manifest["request"]["initial_regional_conditioning"], initial_conditioning)
self.assertNotEqual(manifest["attempts"][0]["request_hash"], manifest["attempts"][1]["request_hash"])
self.assertEqual(manifest["attempts"][1]["request"]["plan"]["parameters"]["regional_conditioning"]["subject_strength"], 1.4)
self.assertEqual(manifest["state"], "reviewed")
self.assertEqual(recoverable_next_actions(manifest), ["get_run"])
self.assertNotIn("candidate", engine.get_run({"run_id": started["run_id"]}))
```

- [ ] **Step 2: Run the vertical slice as a cross-module verification**

Run: `python -m unittest tests.test_regional_vertical_slice -v`

Expected: PASS using only the interfaces completed in Tasks 1-7; no GPU or network call occurs. A failure returns execution to the owning earlier task instead of widening Task 8.

- [ ] **Step 3: Verify packaging sees both workflow assets**

Add these exact wheel-entry assertions:

```python
self.assertIn("share/local-gpu-imagegen/workflows/comfyui/sdxl-txt2img-v1.json", names)
self.assertIn("share/local-gpu-imagegen/workflows/comfyui/sdxl-regional-txt2img-v1.json", names)
self.assertIn("local_gpu_imagegen/regional_layout.py", names)
```

- [ ] **Step 4: Run the focused integration suite**

Run: `python -m unittest tests.test_regional_vertical_slice tests.test_packaging -v`

Expected: PASS from a checkout-independent temporary wheel installation.

- [ ] **Step 5: Commit the vertical slice**

```powershell
git add tests/test_regional_vertical_slice.py tests/test_packaging.py
git commit -m "test: cover regional route lifecycle"
```

## Task 9: Prepare And Verify The Local v0.7.0 Artifact

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `scripts/local_gpu_imagegen/__init__.py:3`
- Modify: `.codex-plugin/plugin.json:3`
- Modify: `server.json:6,17`
- Modify: active version assertions in `tests/test_mcp_server.py`, `tests/test_packaging.py`, `tests/test_public_docs.py`, and `tests/test_repository_hygiene.py`
- Modify: `README.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/github-listing.md`, `docs/directory-listings.md`, and `docs/release-checklist.md`
- Update after verification, outside the branch checkout: `<project-root>/PROJECT_NODES.md` and `<project-root>/NEXT_SESSION.md`.

**Interfaces:**
- Consumes: all model-free feature tasks.
- Produces: one new isolated `0.7.0` wheel and recorded digest; no remote publication authority.

- [ ] **Step 1: Capture the immutable old wheel digest**

Run:

```powershell
Get-FileHash -Algorithm SHA256 .\dist\local_gpu_imagegen-0.6.1-py3-none-any.whl
```

Expected: `33ED4BC1564A92E3252B80F79CF1A7DD91F726774045801FD617BF9D0EF02655`.

- [ ] **Step 2: Add failing active-version assertions for v0.7.0**

Update only active package/plugin/server/public-preview assertions to `0.7.0`. Keep retained `0.6.1` client/demo validators and historical changelog sections unchanged.

Run: `python -m unittest tests.test_mcp_server tests.test_packaging tests.test_public_docs tests.test_repository_hygiene -v`

Expected: FAIL until active metadata and documentation agree on `0.7.0`.

- [ ] **Step 3: Update active local-preview metadata truthfully**

Set package, runtime, plugin, and `server.json` versions to `0.7.0`. Add a dated `## [0.7.0] - 2026-07-23` changelog section that says regional conditioning is model-free verified and real image-quality acceptance remains pending. Update active README/architecture/listing/release-checklist text; do not claim public CI, PyPI, Registry, GPU quality, or release publication.

- [ ] **Step 4: Run the complete model-free gate**

Run:

```powershell
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests PASS with only the existing documented Windows link-privilege skips.

- [ ] **Step 5: Run tracked JSON and hygiene checks**

Run:

```powershell
Get-ChildItem -Recurse -File -Filter *.json | Where-Object { $_.FullName -notmatch '\\.git\\|\\outputs\\|\\dist\\' } | ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json | Out-Null }
python -m unittest tests.test_repository_hygiene tests.test_public_docs -v
```

Expected: all tracked JSON parses as UTF-8 and hygiene tests PASS with no local path, credential, private candidate, or output leak.

- [ ] **Step 6: Build the new wheel into a separate scratch directory**

Run:

```powershell
$suffix = git rev-parse --short HEAD
$scratchRoot = Join-Path $env:TEMP 'local-gpu-imagegen-verification'
$out = Join-Path $scratchRoot "v070-dist-$suffix"
if (Test-Path -LiteralPath $out) { throw "Verification output already exists: $out" }
New-Item -ItemType Directory -Path $out | Out-Null
uv build --offline --wheel --out-dir $out
Get-ChildItem -LiteralPath $out -Filter 'local_gpu_imagegen-0.7.0-*.whl'
```

Expected: exactly one new `0.7.0` wheel; `dist\local_gpu_imagegen-0.6.1-py3-none-any.whl` is not opened for writing.

- [ ] **Step 7: Install and verify outside the checkout**

Run:

```powershell
$suffix = git rev-parse --short HEAD
$scratchRoot = Join-Path $env:TEMP 'local-gpu-imagegen-verification'
$out = Join-Path $scratchRoot "v070-dist-$suffix"
$venv = Join-Path $scratchRoot "v070-verify-$suffix"
if (Test-Path -LiteralPath $venv) { throw "Verification environment already exists: $venv" }
$python312 = uv python find 3.12
uv venv --offline --python $python312 $venv
& "$venv\Scripts\python.exe" -m pip install (Get-ChildItem "$out\local_gpu_imagegen-0.7.0-*.whl").FullName --no-deps
Push-Location $env:TEMP
& "$venv\Scripts\local-gpu-imagegen.exe" verify
& "$venv\Scripts\local-gpu-imagegen.exe" setup-codex --dry-run
& "$venv\Scripts\local-gpu-imagegen.exe" setup-claude-code --dry-run
Pop-Location
```

Expected: installed version `0.7.0`, exactly 15 MCP tools, both SDXL workflows present, read-only setup plans, and no import from the repository checkout.

- [ ] **Step 8: Recheck both artifact hashes and commit metadata**

Run:

```powershell
Get-FileHash -Algorithm SHA256 .\dist\local_gpu_imagegen-0.6.1-py3-none-any.whl
$suffix = git rev-parse --short HEAD
$scratchRoot = Join-Path $env:TEMP 'local-gpu-imagegen-verification'
Get-FileHash -Algorithm SHA256 (Join-Path $scratchRoot "v070-dist-$suffix\local_gpu_imagegen-0.7.0-*.whl")
git status --short
```

Expected: old hash remains `33ed4bc...02655`; record the complete new hash. Then commit only tracked metadata/docs/tests:

```powershell
git add pyproject.toml scripts/local_gpu_imagegen/__init__.py .codex-plugin/plugin.json server.json README.md CHANGELOG.md docs/architecture.md docs/github-listing.md docs/directory-listings.md docs/release-checklist.md tests/test_mcp_server.py tests/test_packaging.py tests/test_public_docs.py tests/test_repository_hygiene.py
git commit -m "chore(release): prepare v0.7.0 regional preview"
```

- [ ] **Step 9: Update continuity records and stop at the GPU authority gate**

Append control flow, failure modes, exact commands, test totals, old/new artifact hashes, known limitations, and the next authority gate to `<project-root>/PROJECT_NODES.md`. Replace stale `<project-root>/NEXT_SESSION.md` instructions with the exact regional bundle inspection/trust/recommendation sequence. Write a brief entry to the configured Obsidian daily log according to the project rules.

Do not start ComfyUI, inspect the real checkpoint bundle, mutate trust, generate an image, export evidence, push, tag, or publish. Those actions require a new displayed route/bundle/budget confirmation after the model-free milestone is reported.

## Self-Review Checklist

- Spec sections 1-6: Tasks 1 and 6 cover exact geometry, conditioning, confirmation, Profiles, and immutable/mutable boundaries.
- Spec sections 7-8: Tasks 2, 3, 5, and 6 cover architecture, graph, live signatures, exact bindings, and backend drift checks.
- Spec section 9: Task 4 covers legacy/variant coexistence, exact pair updates, collision failure, revoke ambiguity, and observation isolation.
- Spec sections 10-11: Tasks 3-6 cover fail-closed behavior, compatibility, security, and no fallback.
- Spec section 12: Tasks 1-8 cover contract, plan, workflow, adapter, trust, routing, engine, MCP, packaging, and regression tests.
- Spec sections 13-14: Task 9 stops before GPU work, preserves the old wheel, creates one isolated new artifact, and records the later authority gate.
- No task downloads a dependency/model, modifies shared Python, changes the tool count, expands arbitrary regions, or publishes externally.

## Post-Implementation Authority Gate

After Task 9 is reported complete, present the exact live ComfyUI node signatures, SDXL identity, regional workflow digest, component-bundle digest, route geometry, regional prompts/strengths, dimensions, and proposed round budget. Wait for a later explicit user message before trust mutation or GPU generation. Retain and honestly review every original PNG; do not extend the exhausted historical runs.
