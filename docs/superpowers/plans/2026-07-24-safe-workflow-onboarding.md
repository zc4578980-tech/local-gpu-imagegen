# Safe ComfyUI Workflow Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, node-ID-free inspect-and-register path for ordinary single-checkpoint and split-model ComfyUI API workflows, then let the existing trust path consume the immutable registered workflow ID.

**Architecture:** Keep `workflow_templates.py` authoritative for bounded file reads, safe graph validation, canonical registered documents, atomic persistence, and drift detection. Add one concrete `WorkflowOnboarding` module for envelope extraction, semantic binding inference, inventory matching, dual hashes, stateless proposals, and confirmed registration; keep `mcp_server.py` limited to schemas, input-shape validation, dispatch, and bounded projection. Extend the existing trust path by loading an already registered document and reusing its current component-bundle checks, without changing the engine, run store, or backend adapters.

**Tech Stack:** Python 3.11/3.12 standard library, `unittest`, JSON-RPC/MCP stdio, existing Local GPU Imagegen registries and structured `AssetEngineError` hierarchy.

## Global Constraints

- Active release metadata becomes exactly `0.8.0`; retained v0.7 evidence and historical changelog entries remain byte-for-byte historical records.
- MCP exposes exactly 17 tools: the existing 15 plus `local_gpu_inspect_workflow` and `local_gpu_register_workflow`.
- Add exactly one production module: `scripts/local_gpu_imagegen/workflow_onboarding.py`.
- Add no runtime dependency, abstract base class, factory, generic graph DSL, proposal store, cache, alias, list/delete/lifecycle subsystem, custom-node runtime, or node-selection UI.
- Keep the MCP layer thin: no graph traversal, inference, hashing policy, inventory matching, or confirmation verification in `scripts/mcp_server.py`.
- Do not change `engine.py`, `run_store.py`, backend adapters, regional workflows, two-stage workflows, or their frozen evidence.
- Support only ordinary `txt2img`, bare API graphs, and a wrapper with one graph under `prompt`; reject UI format, img2img, inpaint, regional, two-stage, custom nodes, ambiguous paths, and manual binding overrides.
- Inspection is read-only. Registration re-reads and fully revalidates the source and current inventory before any mutation.
- `source_sha256` hashes exact file bytes; `workflow_sha256` hashes canonical registered semantics; `proposal_digest` binds schema, both hashes, topology, inferred binding, output, and exact current component identities.
- Offline or incomplete inventory produces `status: diagnostic`, `registrable: false`, and no `proposal_digest` or confirmation.
- Registration never grants private trust, public-candidate trust, license authority, or output-redistribution authority.
- Legacy `workflow_path + workflow_binding` remains compatible but frozen; it is mutually exclusive with both shipped `workflow_template_id` and new `registered_workflow_id`.
- Stop and return to design review before approximately 500 net new production lines, another production module/tool/dependency, any node-ID/model-name special case, or any ownership change forbidden by the approved spec.
- Model-free tests must not start a backend, load a model, download anything, require GPU access, or mutate a real user trust/client state.
- Do not push, tag, publish, create a release, change remote metadata, or claim end-to-end onboarding before the separately authorized real-client zero-GPU gate is retained.

## File Map

- `scripts/local_gpu_imagegen/workflow_templates.py`: expose one bounded source reader, split imported-workflow preparation from immutable persistence, preserve legacy `register_import` behavior, and fail closed on an existing drifted target.
- `scripts/local_gpu_imagegen/workflow_onboarding.py`: the only new production module; infer the supported graph semantics, match current ComfyUI inventory, construct hashes/proposals, verify confirmation, and orchestrate persistence.
- `scripts/local_gpu_imagegen/services.py`: construct one `WorkflowOnboarding` instance and expose it through `RuntimeServices`.
- `scripts/mcp_server.py`: declare the two tool schemas, validate trust input exclusivity, dispatch thin onboarding calls, and load registered IDs for the existing trust flow.
- `scripts/verify_mcp.py`: update the exact installed/default tool set to 17.
- `tests/test_workflow_templates.py`: lock preparation/storage equivalence, idempotency, drift failure, and legacy behavior.
- `tests/test_workflow_onboarding.py`: new model-free semantic, ambiguity, envelope, inventory, hash, confirmation, no-mutation, and drift coverage.
- `tests/test_runtime_services.py`: pin dependency wiring and object identity.
- `tests/test_mcp_server.py`: pin schemas, exact dispatch, structured errors, input exclusivity, registered-ID trust, and legacy compatibility.
- `tests/test_verify_mcp.py`, `tests/test_packaging.py`: pin exact 17-tool source and installed-wheel contracts plus inclusion of the new module.
- `tests/test_skill_contract.py`, `tests/test_public_docs.py`: pin the Agent workflow, truthfulness boundary, active version, tool inventory, and limitations.
- `skills/local-gpu-imagegen/SKILL.md`: teach inspect -> display -> later confirmation -> register -> separate trust, without hidden discovery/backend startup.
- `README.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/quickstart.md`, `docs/troubleshooting.md`, `docs/github-listing.md`, `.codex-plugin/plugin.json`, `pyproject.toml`, `server.json`, `scripts/local_gpu_imagegen/__init__.py`: document and synchronize active v0.8 behavior.
- `PROJECT_NODES.md`, `NEXT_SESSION.md`: ignored continuity records updated after each verified milestone and before real-client work.

---

### Task 1: Split Imported Workflow Preparation From Immutable Storage

**Files:**
- Modify: `scripts/local_gpu_imagegen/workflow_templates.py:424`
- Modify: `scripts/local_gpu_imagegen/workflow_templates.py:1130`
- Modify: `scripts/local_gpu_imagegen/workflow_templates.py:1373`
- Modify: `tests/test_workflow_templates.py`
- Test: `tests/test_workflow_templates.py`

**Interfaces:**
- Produces: `read_workflow_source(path: Path) -> tuple[bytes, object]`.
- Produces: `WorkflowTemplateRegistry.prepare_import(graph: object, binding: object, available_models: Collection[str]) -> dict[str, object]`.
- Produces: `WorkflowTemplateRegistry.store_prepared_import(document: object) -> dict[str, object]`.
- Preserves: `WorkflowTemplateRegistry.register_import(path: Path, binding: object, available_models: Collection[str]) -> dict[str, object]`.
- `store_prepared_import` accepts only a complete canonical registered document returned by `prepare_import`; it returns an existing identical registration idempotently and raises `workflow_registration_drifted` without overwriting an invalid existing target.

- [ ] **Step 1: Add preparation/storage regression tests**

Add these methods to `WorkflowTemplateTests`:

```python
def test_prepare_and_store_match_legacy_registration(self) -> None:
    self.write_safe_source()
    graph = json.loads(self.safe_source.read_text(encoding="utf-8"))

    prepared = self.registry.prepare_import(graph, binding(), [MODEL])
    stored = self.registry.store_prepared_import(prepared)
    legacy = self.registry.register_import(self.safe_source, binding(), [MODEL])

    self.assertEqual(prepared["template_id"], stored["template_id"])
    self.assertEqual(stored["template_id"], legacy["template_id"])
    self.assertEqual(stored["workflow_sha256"], legacy["workflow_sha256"])
    self.assertEqual(stored["graph"], legacy["graph"])

def test_store_prepared_import_is_idempotent_but_never_repairs_drift(self) -> None:
    prepared = self.registry.prepare_import(safe_graph(), binding(), [MODEL])
    first = self.registry.store_prepared_import(prepared)
    second = self.registry.store_prepared_import(copy.deepcopy(prepared))
    self.assertEqual(first, second)

    target = Path(first["local_path"])
    target.write_text("{}", encoding="utf-8")
    with self.assertRaisesRegex(ConflictError, "workflow_registration_drifted"):
        self.registry.store_prepared_import(prepared)
    self.assertEqual(target.read_text(encoding="utf-8"), "{}")

def test_public_source_reader_returns_exact_bytes_and_json_value(self) -> None:
    encoded = b'{"prompt":{"1":{"class_type":"SaveImage","inputs":{}}},"meta":1}'
    self.safe_source.write_bytes(encoded)

    actual_bytes, value = read_workflow_source(self.safe_source)

    self.assertEqual(actual_bytes, encoded)
    self.assertEqual(value["meta"], 1)
```

Import `read_workflow_source` beside the existing workflow-template imports.

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
python -m unittest tests.test_workflow_templates.WorkflowTemplateTests.test_prepare_and_store_match_legacy_registration tests.test_workflow_templates.WorkflowTemplateTests.test_store_prepared_import_is_idempotent_but_never_repairs_drift tests.test_workflow_templates.WorkflowTemplateTests.test_public_source_reader_returns_exact_bytes_and_json_value -v
```

Expected: errors report missing `prepare_import`, `store_prepared_import`, and `read_workflow_source`; existing tests still import successfully.

- [ ] **Step 3: Expose bounded reading and split prepare/store**

Replace `_read_bounded_json`'s private byte read with this public helper and keep `_read_source_graph` as the legacy bare-graph boundary:

```python
def read_workflow_source(path: Path) -> tuple[bytes, object]:
    candidate = Path(path)
    try:
        file_stat = os.stat(candidate, follow_symlinks=False)
        if (
            _link_like(candidate)
            or not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size > MAX_SOURCE_BYTES
        ):
            raise OSError("unsafe workflow file")
        encoded = candidate.read_bytes()
        if len(encoded) > MAX_SOURCE_BYTES:
            raise OSError("oversized workflow file")
        return encoded, json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactError(
            "invalid_workflow_source",
            "Workflow JSON is unreadable or unsafe.",
        ) from error


def _read_bounded_json(path: Path) -> object:
    return read_workflow_source(path)[1]
```

Refactor `WorkflowTemplateRegistry` with these exact methods:

```python
def prepare_import(
    self,
    graph: object,
    binding: object,
    available_models: Collection[str],
) -> dict[str, object]:
    normalized = validate_imported_workflow(graph, binding, available_models)
    payload = {
        "operation": _infer_operation(normalized["graph"]),
        "model_families": ["unknown"],
        "bindings": {
            key: value
            for key, value in normalized["binding"].items()
            if key != "output"
        },
        "output_node": normalized["output_node"],
        "graph": normalized["graph"],
    }
    digest = _canonical_hash(payload)
    return {
        "schema_version": 1,
        "template_id": f"imported:{digest}",
        "template_version": 1,
        "workflow_sha256": digest,
        **payload,
    }

def store_prepared_import(self, document: object) -> dict[str, object]:
    digest = document.get("workflow_sha256") if isinstance(document, dict) else None
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValidationError(
            "invalid_workflow_registration",
            "Prepared workflow registration is invalid.",
        )
    try:
        normalized = _validate_registered_document(document, digest)
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ValidationError(
            "invalid_workflow_registration",
            "Prepared workflow registration is invalid.",
        ) from error
    if self.registered_root.exists() and _link_like(self.registered_root):
        raise ArtifactError(
            "invalid_workflow_state",
            "Workflow state directory must not be a link or reparse point.",
        )
    target = self.registered_root / f"{digest}.json"
    if target.exists():
        existing = self.load_registered(normalized["template_id"])
        return existing
    atomic_write_json(target, normalized)
    return {**copy.deepcopy(normalized), "local_path": str(target.absolute())}

def register_import(
    self,
    path: Path,
    binding: object,
    available_models: Collection[str],
) -> dict[str, object]:
    graph = _read_source_graph(Path(path))
    _freeze_single_import_model(graph, binding, available_models)
    return self.store_prepared_import(
        self.prepare_import(graph, binding, available_models)
    )
```

Do not change `validate_imported_workflow`, its allowlist, resource limits, model checks, or registered-document format.

- [ ] **Step 4: Run workflow-template tests GREEN**

Run:

```powershell
python -m unittest tests.test_workflow_templates -v
```

Expected: all workflow-template tests pass, including frozen workflow byte hashes and legacy `register_import` coverage.

- [ ] **Step 5: Commit the refactor**

```powershell
git add scripts/local_gpu_imagegen/workflow_templates.py tests/test_workflow_templates.py
git commit -m "refactor: split workflow import preparation"
```

---

### Task 2: Infer One Supported Txt2img Binding Without Node-ID Assumptions

**Files:**
- Create: `scripts/local_gpu_imagegen/workflow_onboarding.py`
- Create: `tests/test_workflow_onboarding.py`
- Test: `tests/test_workflow_onboarding.py`

**Interfaces:**
- Produces: `infer_workflow_binding(graph: object) -> dict[str, object]` for internal tests and `WorkflowOnboarding` use.
- Return shape: `{"topology": "single_checkpoint" | "split_model", "binding": dict[str, list[str]], "output_node": str, "components": list[dict[str, str]]}`.
- `components` uses the exact role/class/input/name shape returned by `workflow_component_bindings`.
- Failures use `ValidationError` codes `unsupported_workflow_envelope`, `unsupported_workflow_operation`, `unsupported_workflow_topology`, or `ambiguous_workflow_binding`; ambiguity details contain `role` and sorted `candidate_node_ids`.

- [ ] **Step 1: Create graph helpers and happy-path tests**

Create `tests/test_workflow_onboarding.py` with reusable shipped-graph fixtures and these tests:

```python
from __future__ import annotations

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from local_gpu_imagegen.errors import AssetEngineError, ValidationError
from local_gpu_imagegen.workflow_onboarding import WorkflowOnboarding, infer_workflow_binding
from local_gpu_imagegen.workflow_templates import (
    WorkflowTemplateRegistry,
    validate_imported_workflow,
    workflow_component_bindings,
)

ROOT = Path(__file__).resolve().parents[1]


def shipped(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / "workflows" / "comfyui" / name).read_text(encoding="utf-8")
    )


def remap_graph(graph: dict[str, object], seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    old_ids = list(graph)
    new_ids = [f"node-{value}" for value in rng.sample(range(100, 999), len(old_ids))]
    mapping = dict(zip(old_ids, new_ids, strict=True))
    items = []
    for old_id, node in graph.items():
        changed = copy.deepcopy(node)
        for key, value in changed["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and value[0] in mapping:
                changed["inputs"][key] = [mapping[value[0]], value[1]]
        items.append((mapping[old_id], changed))
    rng.shuffle(items)
    return dict(items)


class WorkflowBindingInferenceTests(unittest.TestCase):
    def test_infers_single_checkpoint_and_passes_authoritative_validator(self) -> None:
        document = shipped("sd15-txt2img-v1.json")
        inferred = infer_workflow_binding(document["graph"])
        validated = validate_imported_workflow(
            document["graph"],
            inferred["binding"],
            ["model.safetensors"],
        )
        self.assertEqual(inferred["topology"], "single_checkpoint")
        self.assertEqual(inferred["output_node"], validated["output_node"])
        self.assertEqual(inferred["binding"], validated["binding"])

    def test_infers_split_model_after_node_and_key_randomization(self) -> None:
        document = shipped("z-image-turbo-txt2img-v1.json")
        for seed in range(10):
            graph = remap_graph(document["graph"], seed)
            inferred = infer_workflow_binding(graph)
            primary_names = [
                item["backend_model_id"]
                for item in inferred["components"]
                if item["role"] == "primary_model"
            ]
            validated = validate_imported_workflow(
                graph,
                inferred["binding"],
                primary_names,
            )
            self.assertEqual(inferred["topology"], "split_model")
            self.assertEqual(inferred["binding"], validated["binding"])
            self.assertEqual(
                [item["role"] for item in inferred["components"]],
                ["primary_model", "text_encoder", "vae"],
            )
```

- [ ] **Step 2: Add ambiguity and excluded-operation tests**

Add table-driven mutations:

```python
def test_duplicate_semantic_roles_fail_closed(self) -> None:
    base = shipped("sd15-txt2img-v1.json")["graph"]
    cases = {
        "primary_model": lambda graph: graph.update({"loader-copy": copy.deepcopy(graph["4"])}),
        "sampler": lambda graph: graph.update({"sampler-copy": copy.deepcopy(graph["3"])}),
        "latent_source": lambda graph: graph.update({"latent-copy": copy.deepcopy(graph["5"])}),
        "owned_output": lambda graph: graph.update({"output-copy": copy.deepcopy(graph["9"])}),
    }
    for role, mutate in cases.items():
        graph = copy.deepcopy(base)
        mutate(graph)
        with self.subTest(role=role), self.assertRaises(ValidationError) as raised:
            infer_workflow_binding(graph)
        self.assertIn(
            raised.exception.code,
            {"ambiguous_workflow_binding", "unsupported_workflow_topology"},
        )

def test_img2img_inpaint_regional_and_two_stage_are_not_candidates(self) -> None:
    cases = (
        ("img2img", "VAEEncode", {"pixels": ["8", 0], "vae": ["4", 2]}),
        ("inpaint", "VAEEncodeForInpaint", {
            "pixels": ["8", 0], "vae": ["4", 2], "mask": ["8", 0], "grow_mask_by": 6,
        }),
        ("regional", "ConditioningCombine", {"conditioning_1": ["6", 0], "conditioning_2": ["7", 0]}),
        ("two_stage", "SolidMask", {"value": 1.0, "width": 512, "height": 512}),
    )
    for label, class_type, inputs in cases:
        graph = shipped("sd15-txt2img-v1.json")["graph"]
        graph["excluded"] = {"class_type": class_type, "inputs": inputs}
        with self.subTest(label=label), self.assertRaises(ValidationError):
            infer_workflow_binding(graph)
```

Add this disconnected/cross-wired table; node IDs are derived from graph
semantics or the shipped binding and are never production special cases:

```python
def test_disconnected_or_cross_wired_execution_path_is_rejected(self) -> None:
    document = shipped("sd15-txt2img-v1.json")
    base = document["graph"]
    binding = {
        **document["bindings"],
        "output": [document["output_node"]],
    }
    sampler_id = binding["seed"][0]
    model_id = binding["model"][0]
    positive_id = binding["positive_prompt"][0]
    negative_id = binding["negative_prompt"][0]
    latent_id = binding["width"][0]
    decoder_id = next(
        node_id for node_id, node in base.items()
        if node["class_type"] == "VAEDecode"
    )
    output_id = document["output_node"]
    cases = (
        (sampler_id, "model", [latent_id, 0]),
        (sampler_id, "positive", [negative_id, 0]),
        (sampler_id, "negative", [positive_id, 0]),
        (sampler_id, "latent_image", [positive_id, 0]),
        (decoder_id, "samples", [latent_id, 0]),
        (decoder_id, "vae", [positive_id, 0]),
        (output_id, "images", [sampler_id, 0]),
    )
    for node_id, field, edge in cases:
        graph = copy.deepcopy(base)
        graph[node_id]["inputs"][field] = edge
        with self.subTest(field=field), self.assertRaises(ValidationError):
            infer_workflow_binding(graph)
    self.assertEqual(base[model_id]["class_type"], "CheckpointLoaderSimple")
```

- [ ] **Step 3: Run inference tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_workflow_onboarding.WorkflowBindingInferenceTests -v
```

Expected: import fails because `workflow_onboarding.py` and `infer_workflow_binding` do not exist.

- [ ] **Step 4: Implement semantic graph traversal**

Create `scripts/local_gpu_imagegen/workflow_onboarding.py` with these constants and helpers; keep all traversal here:

```python
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

from .errors import ConflictError, ValidationError
from .model_identity import identity_token, validate_discovery_record
from .workflow_templates import (
    COMPONENT_LOADER_INPUTS,
    MODEL_LOADER_INPUTS,
    WorkflowTemplateRegistry,
    read_workflow_source,
    workflow_component_bindings,
)

TOPOLOGIES = frozenset({"single_checkpoint", "split_model"})
PROPOSAL_SCHEMA_VERSION = 1
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXCLUDED_CLASSES = frozenset({
    "VAEEncode", "VAEEncodeForInpaint", "LoadImage", "LoadImageMask",
    "ConditioningSetAreaPercentage", "ConditioningCombine", "SolidMask",
    "MaskComposite", "FeatherMask", "ImageCompositeMasked", "MaskToImage",
})


def _node(graph: dict[str, object], node_id: str) -> dict[str, object]:
    value = graph.get(node_id)
    if not isinstance(value, dict) or not isinstance(value.get("inputs"), dict):
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Workflow path references an invalid node.",
            {"candidate_node_ids": [node_id]},
        )
    return value


def _link(value: object, role: str) -> tuple[str, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not isinstance(value[0], str)
        or type(value[1]) is not int
        or value[1] < 0
    ):
        raise ValidationError(
            "ambiguous_workflow_binding",
            f"Workflow {role} is not one exact graph edge.",
            {"role": role, "candidate_node_ids": []},
        )
    return value[0], value[1]


def _only_class(
    graph: dict[str, object],
    classes: frozenset[str],
    role: str,
) -> tuple[str, dict[str, object]]:
    matches = sorted(
        (node_id, node)
        for node_id, node in graph.items()
        if isinstance(node, dict) and node.get("class_type") in classes
    )
    if len(matches) != 1:
        raise ValidationError(
            "ambiguous_workflow_binding",
            f"Workflow requires one unambiguous {role}.",
            {"role": role, "candidate_node_ids": [item[0] for item in matches]},
        )
    return matches[0]


def _walk_passthrough(
    graph: dict[str, object],
    edge: object,
    role: str,
    targets: frozenset[str],
    passthrough_input: dict[str, str],
) -> tuple[str, int]:
    seen: set[str] = set()
    node_id, slot = _link(edge, role)
    while True:
        if node_id in seen:
            raise ValidationError(
                "ambiguous_workflow_binding",
                f"Workflow {role} contains a cycle.",
                {"role": role, "candidate_node_ids": sorted(seen)},
            )
        seen.add(node_id)
        node = _node(graph, node_id)
        class_type = node.get("class_type")
        if class_type in targets:
            return node_id, slot
        input_name = passthrough_input.get(str(class_type))
        if input_name is None:
            raise ValidationError(
                "ambiguous_workflow_binding",
                f"Workflow {role} does not reach one reviewed source.",
                {"role": role, "candidate_node_ids": [node_id]},
            )
        node_id, slot = _link(node["inputs"].get(input_name), role)
```

Implement `infer_workflow_binding` as one direct semantic pipeline:

```python
def infer_workflow_binding(graph: object) -> dict[str, object]:
    if not isinstance(graph, dict) or not graph:
        raise ValidationError(
            "unsupported_workflow_envelope",
            "Workflow must contain one ComfyUI API graph object.",
        )
    classes = {
        node.get("class_type")
        for node in graph.values()
        if isinstance(node, dict)
    }
    excluded = sorted(item for item in classes if item in EXCLUDED_CLASSES)
    if excluded:
        raise ValidationError(
            "unsupported_workflow_operation",
            "Workflow onboarding supports ordinary txt2img only.",
            {"node_classes": excluded},
        )

    sampler_id, sampler = _only_class(graph, frozenset({"KSampler"}), "sampler")
    latent_id, latent = _only_class(
        graph,
        frozenset({"EmptyLatentImage", "EmptySD3LatentImage"}),
        "latent_source",
    )
    decoder_id, decoder = _only_class(graph, frozenset({"VAEDecode"}), "decoder")
    output_id, output = _only_class(graph, frozenset({"SaveImage"}), "owned_output")

    if _link(sampler["inputs"].get("latent_image"), "latent_source")[0] != latent_id:
        raise ValidationError("ambiguous_workflow_binding", "Sampler latent path is cross-wired.")
    if _link(decoder["inputs"].get("samples"), "decoder")[0] != sampler_id:
        raise ValidationError("ambiguous_workflow_binding", "Decoder sample path is cross-wired.")
    if _link(output["inputs"].get("images"), "owned_output")[0] != decoder_id:
        raise ValidationError("ambiguous_workflow_binding", "Owned output path is cross-wired.")

    model_id, model_slot = _walk_passthrough(
        graph,
        sampler["inputs"].get("model"),
        "primary_model",
        frozenset(MODEL_LOADER_INPUTS),
        {"ModelSamplingAuraFlow": "model"},
    )
    positive_id, _ = _walk_passthrough(
        graph,
        sampler["inputs"].get("positive"),
        "positive_prompt",
        frozenset({"CLIPTextEncode"}),
        {},
    )
    negative_id, _ = _walk_passthrough(
        graph,
        sampler["inputs"].get("negative"),
        "negative_prompt",
        frozenset({"CLIPTextEncode"}),
        {"ConditioningZeroOut": "conditioning"},
    )
    if positive_id == negative_id:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Positive and negative prompts must be distinct.",
            {"role": "conditioning", "candidate_node_ids": [positive_id]},
        )

    model_class = str(_node(graph, model_id)["class_type"])
    if model_slot != 0:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Primary model path uses an unsupported loader output.",
            {"role": "primary_model", "candidate_node_ids": [model_id]},
        )
    topology = (
        "single_checkpoint" if model_class == "CheckpointLoaderSimple" else "split_model"
    )
    binding = {
        "model": [model_id, "inputs", MODEL_LOADER_INPUTS[model_class]],
        "positive_prompt": [positive_id, "inputs", "text"],
        "negative_prompt": [negative_id, "inputs", "text"],
        "seed": [sampler_id, "inputs", "seed"],
        "steps": [sampler_id, "inputs", "steps"],
        "guidance_scale": [sampler_id, "inputs", "cfg"],
        "sampler": [sampler_id, "inputs", "sampler_name"],
        "scheduler": [sampler_id, "inputs", "scheduler"],
        "width": [latent_id, "inputs", "width"],
        "height": [latent_id, "inputs", "height"],
        "output": [output_id],
    }
    components = workflow_component_bindings(graph)
    expected_roles = (
        {"primary_model"}
        if topology == "single_checkpoint"
        else {"primary_model", "text_encoder", "vae"}
    )
    actual_roles = {item["role"] for item in components}
    if actual_roles != expected_roles:
        raise ValidationError(
            "unsupported_workflow_topology",
            "Workflow loader topology is incomplete, mixed, or ambiguous.",
            {"roles": sorted(actual_roles), "topology": topology},
        )

    # Connectivity of CLIP and VAE sources is checked against the same sampler path.
    _validate_component_edges(graph, topology, model_id, positive_id, negative_id, decoder_id)
    return {
        "topology": topology,
        "binding": binding,
        "output_node": output_id,
        "components": components,
    }
```

Add this exact connected-component check. Checkpoint paths use model/clip/vae
outputs `0/1/2`; split paths use the unique loader output `0`. A disconnected
loader is rejected even when its class/name is unique:

```python
def _validate_component_edges(
    graph: dict[str, object],
    topology: str,
    model_id: str,
    positive_id: str,
    negative_id: str,
    decoder_id: str,
) -> None:
    positive_clip = _link(
        _node(graph, positive_id)["inputs"].get("clip"),
        "positive_clip",
    )
    negative_clip = _link(
        _node(graph, negative_id)["inputs"].get("clip"),
        "negative_clip",
    )
    decoder_vae = _link(
        _node(graph, decoder_id)["inputs"].get("vae"),
        "decoder_vae",
    )
    if topology == "single_checkpoint":
        expected_clip = (model_id, 1)
        expected_vae = (model_id, 2)
    else:
        clip_id, _ = _only_class(graph, frozenset({"CLIPLoader"}), "text_encoder")
        vae_id, _ = _only_class(graph, frozenset({"VAELoader"}), "vae")
        expected_clip = (clip_id, 0)
        expected_vae = (vae_id, 0)
    failures = []
    if positive_clip != expected_clip:
        failures.append(positive_clip[0])
    if negative_clip != expected_clip:
        failures.append(negative_clip[0])
    if decoder_vae != expected_vae:
        failures.append(decoder_vae[0])
    if failures:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Conditioning or decoder components are disconnected or cross-wired.",
            {"role": "component_path", "candidate_node_ids": sorted(set(failures))},
        )
```

After inference, call the existing validator in the later inspection step; do
not reproduce its allowlist/resource checks here.

- [ ] **Step 5: Run inference tests GREEN and inspect size**

Run:

```powershell
python -m unittest tests.test_workflow_onboarding.WorkflowBindingInferenceTests -v
git diff --stat
```

Expected: all inference tests pass. If the new production module is already approaching 300 lines before inventory/registration, pause and simplify before continuing; do not wait until it exceeds the 500-line review trigger.

- [ ] **Step 6: Commit semantic inference**

```powershell
git add scripts/local_gpu_imagegen/workflow_onboarding.py tests/test_workflow_onboarding.py
git commit -m "feat: infer safe ComfyUI workflow bindings"
```

---

### Task 3: Produce Diagnostic Or Registerable Stateless Proposals

**Files:**
- Modify: `scripts/local_gpu_imagegen/workflow_onboarding.py`
- Modify: `tests/test_workflow_onboarding.py`
- Test: `tests/test_workflow_onboarding.py`

**Interfaces:**
- Produces concrete class `WorkflowOnboarding(workflows: WorkflowTemplateRegistry, inventory_provider: Callable[[], list[dict[str, object]]])`.
- Produces `WorkflowOnboarding.inspect(path: Path) -> dict[str, object]`.
- Inspection result always includes `status`, `registrable`, `source_sha256`, `workflow_sha256`, `topology`, `binding`, `owned_output`, `components`, `limitations`, and `recoverable_next_actions`.
- Only a registerable result includes `proposal_digest` and `confirmation`.
- A component result has `role`, `loader_class`, `loader_input`, `backend_model_id`, and optional `identity_token`; component order is the existing role-order from `workflow_component_bindings`.

- [ ] **Step 1: Add envelope, hash, and offline tests**

Add a `WorkflowOnboardingTests` fixture using a temporary state directory and inventory callback, then add:

```python
def test_bare_graph_and_prompt_wrapper_share_semantic_hash_but_not_source_hash(self) -> None:
    document = shipped("sd15-txt2img-v1.json")
    graph = document["graph"]
    bare = self.write_json("bare.json", graph, compact=True)
    wrapped = self.write_json("wrapped.json", {"prompt": graph, "ignored": {"x": 1}})

    bare_result = self.onboarding.inspect(bare)
    wrapped_result = self.onboarding.inspect(wrapped)

    self.assertNotEqual(bare_result["source_sha256"], wrapped_result["source_sha256"])
    self.assertEqual(bare_result["workflow_sha256"], wrapped_result["workflow_sha256"])
    self.assertNotEqual(bare_result.get("proposal_digest"), wrapped_result.get("proposal_digest"))

def test_offline_inspection_is_diagnostic_and_has_no_confirmation(self) -> None:
    path = self.write_json("workflow.json", shipped("sd15-txt2img-v1.json")["graph"])
    result = self.onboarding.inspect(path)

    self.assertEqual(result["status"], "diagnostic")
    self.assertFalse(result["registrable"])
    self.assertNotIn("proposal_digest", result)
    self.assertNotIn("confirmation", result)
    self.assertIn("local_gpu_discover_models", result["recoverable_next_actions"])
    self.assertFalse((self.state_dir / "workflows" / "registered").exists())

def test_ui_format_and_multiple_prompt_graphs_are_actionable_rejections(self) -> None:
    ui = self.write_json("ui.json", {"nodes": [], "links": [], "widgets_values": []})
    with self.assertRaises(ValidationError) as raised:
        self.onboarding.inspect(ui)
    self.assertEqual(raised.exception.code, "unsupported_workflow_envelope")
    self.assertIn("developer mode", str(raised.exception).lower())
```

Add the portable unsafe-source cases below. Keep the existing Windows
reparse/junction helper from `test_workflow_templates.py` for one additional
Windows-only subtest and skip only when the OS denies link creation:

```python
def test_unsafe_or_unreadable_sources_fail_before_inspection(self) -> None:
    malformed = self.root / "malformed.json"
    malformed.write_bytes(b"\xff\xfe")
    oversized = self.root / "oversized.json"
    oversized.write_bytes(b" " * ((2 * 1024 * 1024) + 1))
    directory = self.root / "directory.json"
    directory.mkdir()
    cases = (malformed, oversized, directory)
    for path in cases:
        with self.subTest(path=path), self.assertRaises(AssetEngineError) as raised:
            self.onboarding.inspect(path)
        self.assertEqual(raised.exception.code, "invalid_workflow_source")
    self.assertFalse((self.state_dir / "workflows" / "registered").exists())

def test_symlink_source_is_rejected_when_supported(self) -> None:
    link = self.root / "linked.json"
    try:
        link.symlink_to(self.single_path)
    except OSError as error:
        self.skipTest(f"link creation unavailable: {error}")
    with self.assertRaises(AssetEngineError) as raised:
        self.onboarding.inspect(link)
    self.assertEqual(raised.exception.code, "invalid_workflow_source")
```

- [ ] **Step 2: Add exact inventory matching tests**

Use records validated through `validate_discovery_record`:

```python
def comfy_record(
    backend_model_id: str,
    loader_class: str,
    loader_input: str,
    *,
    endpoint: str = "http://127.0.0.1:8188",
) -> dict[str, object]:
    return {
        "backend": "comfyui",
        "endpoint_identity": endpoint,
        "backend_model_id": backend_model_id,
        "format": "comfyui-choice",
        "byte_size": None,
        "modified_ns": None,
        "sha256": None,
        "identity_strength": "backend_binding",
        "metadata": {"loader_class": loader_class, "loader_input": loader_input},
    }


class WorkflowOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_dir = self.root / "state"
        self.inventory: list[dict[str, object]] = []
        self.registry = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            self.state_dir,
        )
        self.onboarding = WorkflowOnboarding(
            self.registry,
            lambda: copy.deepcopy(self.inventory),
        )
        self.single_graph = shipped("sd15-txt2img-v1.json")["graph"]
        self.split_graph = shipped("z-image-turbo-txt2img-v1.json")["graph"]
        self.single_path = self.write_json("single.json", self.single_graph)
        self.split_path = self.write_json("split.json", self.split_graph)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_json(
        self,
        filename: str,
        value: object,
        *,
        compact: bool = False,
    ) -> Path:
        path = self.root / filename
        path.write_text(
            json.dumps(
                value,
                sort_keys=not compact,
                separators=(",", ":") if compact else None,
            ),
            encoding="utf-8",
        )
        return path

    def use_exact_single_inventory(self) -> None:
        component = workflow_component_bindings(self.single_graph)[0]
        self.inventory[:] = [comfy_record(
            component["backend_model_id"],
            component["loader_class"],
            component["loader_input"],
        )]

    def reset_single_case(self) -> None:
        self.write_json("single.json", self.single_graph)
        self.use_exact_single_inventory()

    def change_prompt_text(self, path: Path) -> None:
        graph = json.loads(path.read_text(encoding="utf-8"))
        inferred = infer_workflow_binding(graph)
        node_id = inferred["binding"]["positive_prompt"][0]
        graph[node_id]["inputs"]["text"] = "changed"
        self.write_json(path.name, graph)

    def change_inventory_endpoint(self) -> None:
        changed = copy.deepcopy(self.inventory[0])
        changed["endpoint_identity"] = "http://127.0.0.1:8288"
        self.inventory[:] = [changed]

    def ambiguous_inventory_cases(self) -> list[list[dict[str, object]]]:
        component = workflow_component_bindings(self.split_graph)[0]
        exact = comfy_record(
            component["backend_model_id"],
            component["loader_class"],
            component["loader_input"],
        )
        duplicate = copy.deepcopy(exact)
        duplicate["endpoint_identity"] = "http://127.0.0.1:8288"
        wrong_loader = copy.deepcopy(exact)
        wrong_loader["metadata"] = {
            "loader_class": "CheckpointLoaderSimple",
            "loader_input": "ckpt_name",
        }
        return [[exact, duplicate], [wrong_loader]]

    def test_exact_single_inventory_match_is_registerable(self) -> None:
        document = shipped("sd15-txt2img-v1.json")
        component = workflow_component_bindings(document["graph"])[0]
        self.inventory[:] = [comfy_record(
            component["backend_model_id"],
            component["loader_class"],
            component["loader_input"],
        )]
        result = self.onboarding.inspect(
            self.write_json("single.json", document["graph"])
        )

        self.assertEqual(result["status"], "registerable")
        self.assertTrue(result["registrable"])
        self.assertRegex(result["proposal_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            result["confirmation"],
            f"register_workflow:{result['source_sha256']}:{result['proposal_digest']}",
        )

    def test_duplicate_or_cross_endpoint_inventory_never_emits_confirmation(self) -> None:
        for inventory in self.ambiguous_inventory_cases():
            self.inventory[:] = inventory
            result = self.onboarding.inspect(self.split_path)
            self.assertFalse(result["registrable"])
            self.assertNotIn("confirmation", result)
```

Cover exact single and split matches, missing loader metadata, duplicate identities, same backend name under a wrong loader, and split components from different endpoints.

- [ ] **Step 3: Run proposal tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_workflow_onboarding.WorkflowOnboardingTests -v
```

Expected: errors report missing `WorkflowOnboarding` and proposal behavior; inference tests remain green.

- [ ] **Step 4: Implement envelope extraction, authoritative validation, matching, and hashes**

Add these helpers and class methods:

```python
def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_api_graph(value: object) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(node_id, str)
            and isinstance(node, dict)
            and isinstance(node.get("class_type"), str)
            and isinstance(node.get("inputs"), dict)
            for node_id, node in value.items()
        )
    )


def _extract_graph(value: object) -> dict[str, object]:
    if _looks_like_api_graph(value):
        return copy.deepcopy(value)
    if isinstance(value, dict) and _looks_like_api_graph(value.get("prompt")):
        other_graph_keys = sorted(
            key
            for key, item in value.items()
            if key != "prompt" and _looks_like_api_graph(item)
        )
        if other_graph_keys:
            raise ValidationError(
                "unsupported_workflow_envelope",
                "Workflow wrapper contains multiple API graph candidates.",
                {"fields": ["prompt", *other_graph_keys]},
            )
        return copy.deepcopy(value["prompt"])
    if isinstance(value, dict) and {"nodes", "links"} <= set(value):
        raise ValidationError(
            "unsupported_workflow_envelope",
            "ComfyUI UI format is unsupported; enable developer mode and export API format.",
        )
    raise ValidationError(
        "unsupported_workflow_envelope",
        "Workflow must be a bare API graph or contain one API graph under prompt.",
    )


class WorkflowOnboarding:
    def __init__(
        self,
        workflows: WorkflowTemplateRegistry,
        inventory_provider: Callable[[], list[dict[str, object]]],
    ) -> None:
        if not isinstance(workflows, WorkflowTemplateRegistry) or not callable(inventory_provider):
            raise ValidationError(
                "invalid_workflow_onboarding",
                "Workflow onboarding dependencies are invalid.",
            )
        self.workflows = workflows
        self.inventory_provider = inventory_provider

    def inspect(self, path: Path) -> dict[str, object]:
        encoded, source_value = read_workflow_source(Path(path))
        graph = _extract_graph(source_value)
        inferred = infer_workflow_binding(graph)
        available_models = [item["backend_model_id"] for item in inferred["components"]]
        prepared = self.workflows.prepare_import(
            graph,
            inferred["binding"],
            available_models,
        )
        if prepared["operation"] != "txt2img":
            raise ValidationError(
                "unsupported_workflow_operation",
                "Workflow onboarding supports ordinary txt2img only.",
            )
        source_sha256 = hashlib.sha256(encoded).hexdigest()
        matched, match_failures = self._match_inventory(inferred["components"])
        result: dict[str, object] = {
            "status": "registerable" if not match_failures else "diagnostic",
            "registrable": not match_failures,
            "source_sha256": source_sha256,
            "workflow_sha256": prepared["workflow_sha256"],
            "topology": inferred["topology"],
            "binding": inferred["binding"],
            "owned_output": {"node_id": inferred["output_node"]},
            "components": matched,
            "limitations": [
                "ordinary_txt2img_only",
                "no_custom_nodes_or_graph_editing",
                "registration_does_not_grant_model_trust_or_public_authority",
            ],
            "recoverable_next_actions": (
                ["local_gpu_register_workflow"]
                if not match_failures
                else ["local_gpu_discover_models:api_only"]
            ),
        }
        if not match_failures:
            proposal = self._proposal_payload(result)
            digest = _canonical_hash(proposal)
            result["proposal_digest"] = digest
            result["confirmation"] = f"register_workflow:{source_sha256}:{digest}"
        else:
            result["inventory_diagnostics"] = match_failures
        return result
```

Implement inventory matching without mutating or refreshing discovery. Invalid,
missing, duplicate, wrong-loader, and cross-endpoint identities remain
diagnostic rather than being guessed:

```python
def _match_inventory(
    self,
    components: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    raw_inventory = self.inventory_provider()
    if not isinstance(raw_inventory, list):
        raw_inventory = []
    inventory: list[dict[str, object]] = []
    for value in raw_inventory:
        try:
            inventory.append(validate_discovery_record(value))
        except ValidationError:
            continue

    matched: list[dict[str, str]] = []
    failures: list[dict[str, object]] = []
    endpoints: set[str] = set()
    for component in components:
        candidates = []
        for record in inventory:
            metadata = record.get("metadata")
            if (
                record.get("backend") == "comfyui"
                and record.get("backend_model_id") == component["backend_model_id"]
                and isinstance(metadata, dict)
                and metadata.get("loader_class") == component["loader_class"]
                and metadata.get("loader_input") == component["loader_input"]
            ):
                candidates.append(record)
        public_component = copy.deepcopy(component)
        if len(candidates) == 1:
            record = candidates[0]
            public_component["identity_token"] = identity_token(record)
            endpoints.add(str(record["endpoint_identity"]))
        else:
            failures.append({
                "role": component["role"],
                "reason": "unavailable" if not candidates else "ambiguous",
                "candidate_count": len(candidates),
            })
        matched.append(public_component)
    if len(endpoints) > 1:
        failures.append({
            "role": "workflow",
            "reason": "endpoint_mismatch",
            "candidate_count": len(endpoints),
        })
    return matched, failures

def _proposal_payload(self, result: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "source_sha256": result["source_sha256"],
        "workflow_sha256": result["workflow_sha256"],
        "topology": result["topology"],
        "binding": result["binding"],
        "owned_output": result["owned_output"],
        "components": result["components"],
    }
```

The proposal payload must include exactly:

```python
{
    "schema_version": PROPOSAL_SCHEMA_VERSION,
    "source_sha256": result["source_sha256"],
    "workflow_sha256": result["workflow_sha256"],
    "topology": result["topology"],
    "binding": result["binding"],
    "owned_output": result["owned_output"],
    "components": result["components"],
}
```

Do not include ignored wrapper metadata, absolute source path, inventory timestamps unrelated to `identity_token`, or the whole graph in the public result.

- [ ] **Step 5: Run all onboarding tests GREEN**

Run:

```powershell
python -m unittest tests.test_workflow_onboarding -v
```

Expected: happy, randomized, excluded, envelope, offline, inventory, and no-write tests pass without a backend or GPU.

- [ ] **Step 6: Commit proposal inspection**

```powershell
git add scripts/local_gpu_imagegen/workflow_onboarding.py tests/test_workflow_onboarding.py
git commit -m "feat: inspect workflow onboarding proposals"
```

---

### Task 4: Recheck And Register Exact Confirmed Proposals

**Files:**
- Modify: `scripts/local_gpu_imagegen/workflow_onboarding.py`
- Modify: `tests/test_workflow_onboarding.py`
- Test: `tests/test_workflow_onboarding.py`

**Interfaces:**
- Produces: `WorkflowOnboarding.register(path: Path, proposal_digest: str, confirmation: str) -> dict[str, object]`.
- Registration repeats the full read/infer/validate/inventory/hash pipeline by calling `inspect`; it does not accept a cached proposal or graph.
- Success returns `registered_workflow_id`, `template_version`, `source_sha256`, `workflow_sha256`, `topology`, `owned_output`, `components`, and `recoverable_next_actions`.
- Drift uses `ConflictError("workflow_proposal_stale", ...)`; malformed digest/confirmation uses `ValidationError("invalid_workflow_confirmation", ...)`.

- [ ] **Step 1: Add confirmed registration and idempotency tests**

```python
def test_confirmed_registration_is_immutable_and_idempotent(self) -> None:
    self.use_exact_single_inventory()
    proposal = self.onboarding.inspect(self.single_path)

    first = self.onboarding.register(
        self.single_path,
        proposal["proposal_digest"],
        proposal["confirmation"],
    )
    second = self.onboarding.register(
        self.single_path,
        proposal["proposal_digest"],
        proposal["confirmation"],
    )

    self.assertEqual(first, second)
    self.assertEqual(first["registered_workflow_id"], f"imported:{first['workflow_sha256']}")
    self.assertEqual(first["recoverable_next_actions"], ["local_gpu_set_model_trust"])
    registered = self.registry.load_registered(first["registered_workflow_id"])
    self.assertEqual(registered["workflow_sha256"], first["workflow_sha256"])
```

- [ ] **Step 2: Add every stale/no-mutation boundary**

```python
def test_registration_rejects_source_semantic_inventory_and_confirmation_drift(self) -> None:
    mutators = (
        lambda: self.single_path.write_bytes(self.single_path.read_bytes() + b"\n"),
        lambda: self.change_prompt_text(self.single_path),
        lambda: self.inventory.clear(),
        lambda: self.change_inventory_endpoint(),
    )
    for mutate in mutators:
        self.reset_single_case()
        proposal = self.onboarding.inspect(self.single_path)
        mutate()
        with self.subTest(mutate=mutate), self.assertRaises(AssetEngineError):
            self.onboarding.register(
                self.single_path,
                proposal["proposal_digest"],
                proposal["confirmation"],
            )
        self.assertFalse((self.state_dir / "workflows" / "registered").exists())

def test_registration_rejects_wrong_digest_or_confirmation_without_writing(self) -> None:
    self.use_exact_single_inventory()
    proposal = self.onboarding.inspect(self.single_path)
    cases = (
        ("A" * 64, proposal["confirmation"]),
        ("0" * 64, proposal["confirmation"]),
        (proposal["proposal_digest"], "register_workflow:wrong:wrong"),
    )
    for digest, confirmation in cases:
        with self.subTest(digest=digest), self.assertRaises(AssetEngineError):
            self.onboarding.register(self.single_path, digest, confirmation)
        self.assertFalse((self.state_dir / "workflows" / "registered").exists())
```

Add a formatting-only rewrite case: old confirmation fails due to `source_sha256`, a fresh inspection yields a new confirmation, and confirmed re-registration resolves to the same `imported:<workflow_sha256>` ID.

- [ ] **Step 3: Run registration tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_workflow_onboarding.WorkflowOnboardingTests.test_confirmed_registration_is_immutable_and_idempotent tests.test_workflow_onboarding.WorkflowOnboardingTests.test_registration_rejects_source_semantic_inventory_and_confirmation_drift tests.test_workflow_onboarding.WorkflowOnboardingTests.test_registration_rejects_wrong_digest_or_confirmation_without_writing -v
```

Expected: missing `WorkflowOnboarding.register` or equivalent assertion failures; inspection tests remain green.

- [ ] **Step 4: Implement full recheck and confirmed storage**

Add:

```python
def register(
    self,
    path: Path,
    proposal_digest: str,
    confirmation: str,
) -> dict[str, object]:
    if not isinstance(proposal_digest, str) or HEX64.fullmatch(proposal_digest) is None:
        raise ValidationError(
            "invalid_workflow_confirmation",
            "Workflow proposal digest must be 64 lowercase hex characters.",
        )
    current = self.inspect(Path(path))
    if not current["registrable"]:
        raise ConflictError(
            "workflow_proposal_stale",
            "Workflow or current inventory no longer matches a registerable proposal.",
        )
    expected_digest = current["proposal_digest"]
    expected_confirmation = current["confirmation"]
    if proposal_digest != expected_digest:
        raise ConflictError(
            "workflow_proposal_stale",
            "Workflow proposal changed after inspection.",
        )
    if confirmation != expected_confirmation:
        raise ValidationError(
            "invalid_workflow_confirmation",
            "Workflow registration confirmation does not match exact current bytes and proposal.",
        )

    encoded, source_value = read_workflow_source(Path(path))
    if hashlib.sha256(encoded).hexdigest() != current["source_sha256"]:
        raise ConflictError(
            "workflow_proposal_stale",
            "Workflow source bytes changed during registration revalidation.",
        )
    graph = _extract_graph(source_value)
    prepared = self.workflows.prepare_import(
        graph,
        current["binding"],
        [item["backend_model_id"] for item in current["components"]],
    )
    if prepared["workflow_sha256"] != current["workflow_sha256"]:
        raise ConflictError(
            "workflow_proposal_stale",
            "Workflow changed during registration revalidation.",
        )
    stored = self.workflows.store_prepared_import(prepared)
    return {
        "registered_workflow_id": stored["template_id"],
        "template_version": stored["template_version"],
        "source_sha256": current["source_sha256"],
        "workflow_sha256": stored["workflow_sha256"],
        "topology": current["topology"],
        "owned_output": current["owned_output"],
        "components": current["components"],
        "recoverable_next_actions": ["local_gpu_set_model_trust"],
    }
```

Ensure the second read happens before any store and that `store_prepared_import` cannot overwrite a drifted existing copy.

- [ ] **Step 5: Run onboarding and workflow registry suites GREEN**

Run:

```powershell
python -m unittest tests.test_workflow_onboarding tests.test_workflow_templates -v
git diff --check
```

Expected: all tests pass; no whitespace errors; no source paths appear in onboarding results.

- [ ] **Step 6: Check the complexity trigger and commit**

Run:

```powershell
git diff --numstat 838816c -- scripts/local_gpu_imagegen/workflow_onboarding.py scripts/local_gpu_imagegen/workflow_templates.py
```

Expected: onboarding production code remains comfortably below the approximately 500-net-line review trigger. If it is near or above the trigger, stop for design review instead of committing more behavior.

```powershell
git add scripts/local_gpu_imagegen/workflow_onboarding.py tests/test_workflow_onboarding.py
git commit -m "feat: register confirmed workflow proposals"
```

---

### Task 5: Wire Runtime Services And Two Thin MCP Tools

**Files:**
- Modify: `scripts/local_gpu_imagegen/services.py`
- Modify: `scripts/mcp_server.py`
- Modify: `tests/test_runtime_services.py`
- Modify: `tests/test_mcp_server.py`
- Test: `tests/test_runtime_services.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- `RuntimeServices` gains `onboarding: WorkflowOnboarding` immediately after `workflows`.
- `local_gpu_inspect_workflow` input is exactly `{"workflow_path": str}`.
- `local_gpu_register_workflow` input is exactly `{"workflow_path": str, "proposal_digest": lowercase-hex64, "confirmation": str}`.
- MCP handlers call `services.onboarding.inspect(Path(...))` and `.register(Path(...), ..., ...)`; they contain no graph logic.

- [ ] **Step 1: Add service ownership tests**

Add to `RuntimeServicesTests`:

```python
def test_build_services_wires_workflow_onboarding_to_shared_dependencies(self) -> None:
    services = build_services(
        ROOT,
        self.output_root,
        self.state_dir,
        lambda: {"available_backends": []},
        lambda request: {},
    )
    self.assertIs(services.onboarding.workflows, services.workflows)
    self.assertEqual(services.onboarding.inventory_provider(), services.discovery.inventory())
```

- [ ] **Step 2: Add exact tool schema and dispatch tests**

Add to `McpServerTests`:

```python
def test_workflow_onboarding_tools_have_exact_schemas_and_raise_count_to_seventeen(self) -> None:
    tools = mcp_server.tool_schema()
    by_name = {tool["name"]: tool for tool in tools}
    self.assertEqual(len(tools), 17)
    self.assertEqual(
        by_name["local_gpu_inspect_workflow"]["inputSchema"],
        mcp_server._object_schema(
            {"workflow_path": {"type": "string", "minLength": 1}},
            ["workflow_path"],
        ),
    )
    register = by_name["local_gpu_register_workflow"]["inputSchema"]
    self.assertEqual(
        register["required"],
        ["workflow_path", "proposal_digest", "confirmation"],
    )
    self.assertEqual(register["properties"]["proposal_digest"]["pattern"], "^[0-9a-f]{64}$")

def test_workflow_onboarding_dispatch_is_thin(self) -> None:
    services = Mock()
    services.onboarding.inspect.return_value = {
        "status": "diagnostic", "registrable": False, "warnings": []
    }
    with patch.object(mcp_server, "get_runtime_services", return_value=services):
        result = mcp_server.handle_tool_call({
            "name": "local_gpu_inspect_workflow",
            "arguments": {"workflow_path": "workflow.json"},
        })
    self.assertFalse(result["isError"])
    services.onboarding.inspect.assert_called_once_with(Path("workflow.json"))
```

Add the register branch assertion and use `subTest` to pin the four structured
error codes:

```python
def test_workflow_registration_dispatch_is_thin(self) -> None:
    services = Mock()
    services.onboarding.register.return_value = {
        "registered_workflow_id": "imported:" + "a" * 64,
        "template_version": 1,
        "source_sha256": "b" * 64,
        "workflow_sha256": "a" * 64,
        "topology": "single_checkpoint",
        "owned_output": {"node_id": "9"},
        "components": [],
        "recoverable_next_actions": ["local_gpu_set_model_trust"],
    }
    arguments = {
        "workflow_path": "workflow.json",
        "proposal_digest": "c" * 64,
        "confirmation": "register_workflow:" + "b" * 64 + ":" + "c" * 64,
    }
    with patch.object(mcp_server, "get_runtime_services", return_value=services):
        result = mcp_server.handle_tool_call({
            "name": "local_gpu_register_workflow",
            "arguments": arguments,
        })
    self.assertFalse(result["isError"])
    services.onboarding.register.assert_called_once_with(
        Path("workflow.json"),
        "c" * 64,
        arguments["confirmation"],
    )

def test_workflow_onboarding_preserves_structured_error_codes(self) -> None:
    tool_name = "local_gpu_inspect_workflow"
    for code in (
        "unsupported_workflow_envelope",
        "ambiguous_workflow_binding",
        "workflow_proposal_stale",
        "invalid_workflow_confirmation",
    ):
        services = Mock()
        services.onboarding.inspect.side_effect = AssetEngineError(
            code, "bounded failure", "validation"
        )
        with self.subTest(code=code), patch.object(
            mcp_server, "get_runtime_services", return_value=services
        ):
            result = mcp_server.handle_tool_call({
                "name": tool_name,
                "arguments": {"workflow_path": "workflow.json"},
            })
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], code)
```

- [ ] **Step 3: Run service/MCP tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_runtime_services tests.test_mcp_server -v
```

Expected: failures show missing `RuntimeServices.onboarding`, two missing tools, and tool count 15; unrelated MCP tests execute.

- [ ] **Step 4: Wire the shared service**

In `services.py`, import `WorkflowOnboarding`, add the field, construct it after discovery, and use keyword arguments to avoid positional-field drift:

```python
@dataclass(slots=True)
class RuntimeServices:
    discovery: DiscoveryService
    trust: TrustRegistry
    catalog: ModelCatalog
    router: CapabilityRouter
    workflows: WorkflowTemplateRegistry
    onboarding: WorkflowOnboarding
    backends: BackendRegistry
    engine: AssetRunEngine

# inside build_services
onboarding = WorkflowOnboarding(workflows, discovery.inventory)
return RuntimeServices(
    discovery=discovery,
    trust=trust,
    catalog=catalog,
    router=router,
    workflows=workflows,
    onboarding=onboarding,
    backends=backends,
    engine=engine,
)
```

- [ ] **Step 5: Add exact schemas and thin dispatch**

Insert these two tool definitions adjacent to discovery/trust:

```python
{
    "name": "local_gpu_inspect_workflow",
    "description": "Inspect one local ComfyUI API workflow and infer a safe ordinary txt2img binding without writing state.",
    "inputSchema": _object_schema({
        "workflow_path": {"type": "string", "minLength": 1},
    }, ["workflow_path"]),
    "outputSchema": _output_schema({
        "status": {"type": "string", "enum": ["diagnostic", "registerable"]},
        "registrable": {"type": "boolean"},
        "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "workflow_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "topology": {"type": "string", "enum": ["single_checkpoint", "split_model"]},
        "binding": json_object,
        "owned_output": json_object,
        "components": json_array,
        "limitations": {"type": "array", "items": {"type": "string"}},
        "recoverable_next_actions": {"type": "array", "items": {"type": "string"}},
        "proposal_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "confirmation": {"type": "string"},
        "inventory_diagnostics": json_array,
    }, [
        "status", "registrable", "source_sha256", "workflow_sha256", "topology",
        "binding", "owned_output", "components", "limitations", "recoverable_next_actions",
    ]),
},
{
    "name": "local_gpu_register_workflow",
    "description": "Recheck and immutably register one exact previously inspected ComfyUI workflow proposal.",
    "inputSchema": _object_schema({
        "workflow_path": {"type": "string", "minLength": 1},
        "proposal_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "confirmation": {"type": "string", "minLength": 1},
    }, ["workflow_path", "proposal_digest", "confirmation"]),
    "outputSchema": _output_schema({
        "registered_workflow_id": {"type": "string", "pattern": "^imported:[0-9a-f]{64}$"},
        "template_version": {"type": "integer", "minimum": 1},
        "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "workflow_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "topology": {"type": "string", "enum": ["single_checkpoint", "split_model"]},
        "owned_output": json_object,
        "components": json_array,
        "recoverable_next_actions": {"type": "array", "items": {"type": "string"}},
    }, [
        "registered_workflow_id", "template_version", "source_sha256",
        "workflow_sha256", "topology", "owned_output", "components",
        "recoverable_next_actions",
    ]),
},
```

Extend the services dispatch set and branches only:

```python
if name in {
    "local_gpu_discover_models",
    "local_gpu_inspect_workflow",
    "local_gpu_register_workflow",
    "local_gpu_set_model_trust",
    "local_gpu_recommend_models",
}:
    services = get_runtime_services()
    if name == "local_gpu_inspect_workflow":
        data = services.onboarding.inspect(Path(arguments["workflow_path"]))
        return tool_success(_successful_engine_data(data))
    if name == "local_gpu_register_workflow":
        data = services.onboarding.register(
            Path(arguments["workflow_path"]),
            arguments["proposal_digest"],
            arguments["confirmation"],
        )
        return tool_success(_successful_engine_data(data))
```

- [ ] **Step 6: Run focused service/MCP suites GREEN**

Run:

```powershell
python -m unittest tests.test_runtime_services tests.test_mcp_server -v
```

Expected: all tests pass and the schema exposes exactly 17 unique tool names.

- [ ] **Step 7: Commit service and MCP onboarding**

```powershell
git add scripts/local_gpu_imagegen/services.py scripts/mcp_server.py tests/test_runtime_services.py tests/test_mcp_server.py
git commit -m "feat: expose workflow onboarding tools"
```

---

### Task 6: Consume Registered Workflow IDs In Existing Trust

**Files:**
- Modify: `scripts/mcp_server.py`
- Modify: `tests/test_mcp_server.py`
- Test: `tests/test_mcp_server.py`
- Test: `tests/test_model_catalog.py`
- Test: `tests/test_model_router.py`

**Interfaces:**
- `local_gpu_set_model_trust` gains optional `registered_workflow_id` matching `^imported:[0-9a-f]{64}$`.
- Exactly one workflow source may be selected: shipped `workflow_template_id`, registered `registered_workflow_id`, or legacy `workflow_path + workflow_binding`.
- Produces `_registered_id_workflow_binding(services, record, registered_workflow_id, component_identity_tokens) -> tuple[dict[str, object], dict[str, object], dict[str, object] | None]`.
- It calls `services.workflows.load_registered`, never `infer_workflow_binding`, and reuses `_workflow_component_bundle` and current inventory identity checks.

- [ ] **Step 1: Add mutual-exclusion and loading tests**

```python
def test_registered_workflow_id_is_mutually_exclusive_with_other_workflow_inputs(self) -> None:
    tool = next(
        item for item in mcp_server.tool_schema()
        if item["name"] == "local_gpu_set_model_trust"
    )
    base = {
        "action": "inspect_workflow_binding",
        "identity_token": "model:" + "a" * 64,
        "capabilities": {},
        "component_identity_tokens": ["model:" + "b" * 64],
        "registered_workflow_id": "imported:" + "c" * 64,
    }
    cases = (
        {**base, "workflow_template_id": "sd15-txt2img"},
        {**base, "workflow_path": "workflow.json", "workflow_binding": {}},
    )
    for arguments in cases:
        with self.subTest(arguments=arguments):
            error = mcp_server.validate_tool_arguments(tool, arguments)
            self.assertEqual(
                error["structuredContent"]["error"]["code"],
                "invalid_workflow_binding",
            )

def test_registered_id_trust_loads_copy_without_reinferring_or_rewriting(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory)
        workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            state,
        )
        document = json.loads(
            (ROOT / "workflows" / "comfyui" / "sd15-txt2img-v1.json")
            .read_text(encoding="utf-8")
        )
        graph_binding = {**document["bindings"], "output": [document["output_node"]]}
        registered = workflows.store_prepared_import(
            workflows.prepare_import(
                document["graph"], graph_binding, ["model.safetensors"]
            )
        )
        filesystem = {
            "backend": "filesystem",
            "endpoint_identity": "filesystem:test",
            "backend_model_id": "checkpoints/model.safetensors",
            "format": ".safetensors",
            "byte_size": 1024,
            "modified_ns": 1,
            "sha256": "a" * 64,
            "identity_strength": "cryptographic",
            "metadata": {},
        }
        comfy = {
            "backend": "comfyui",
            "endpoint_identity": "http://127.0.0.1:8188",
            "backend_model_id": "model.safetensors",
            "format": "comfyui-choice",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
            },
        }
        discovery = Mock()
        discovery.inventory.return_value = [filesystem, comfy]
        services = SimpleNamespace(discovery=discovery, workflows=workflows)

        with patch.object(
            mcp_server,
            "infer_workflow_binding",
            side_effect=AssertionError("trust must not infer"),
            create=True,
        ):
            binding, registration, bundle = mcp_server._registered_id_workflow_binding(
                services,
                filesystem,
                registered["template_id"],
                [mcp_server.identity_token(filesystem)],
            )

        self.assertEqual(binding["template_id"], registered["template_id"])
        self.assertEqual(registration["source"], "registered")
        self.assertEqual(bundle["workflow"]["sha256"], registered["workflow_sha256"])
```

Add a tampered registered-copy case expecting `workflow_registration_drifted`, and a current inventory mismatch case expecting the existing component identity error with no trust mutation.

- [ ] **Step 2: Add end-to-end model-free trust/routing tests**

For both single-checkpoint and split-model graphs, execute this in-process sequence with temporary state:

```python
proposal = services.onboarding.inspect(source)
registered = services.onboarding.register(
    source, proposal["proposal_digest"], proposal["confirmation"]
)
inspection = mcp_server._trust_call(services, {
    "action": "inspect_workflow_binding",
    "identity_token": primary_token,
    "capabilities": capabilities,
    "registered_workflow_id": registered["registered_workflow_id"],
    "component_identity_tokens": filesystem_tokens,
})
approved = mcp_server._trust_call(services, {
    "action": "approve_private",
    "identity_token": primary_token,
    "confirmation": inspection["confirmations"]["approve_private"],
    "capabilities": capabilities,
    "registered_workflow_id": registered["registered_workflow_id"],
    "component_identity_tokens": filesystem_tokens,
})
self.assertEqual(approved["registered_workflow"]["template_id"], registered["registered_workflow_id"])
```

Then construct `ModelCatalog`/`CapabilityRouter` with the same temporary trust state and assert recommendation resolves that registered template and existing generation-resolution fields. Do not submit to a backend.

- [ ] **Step 3: Run trust tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_mcp_server tests.test_model_catalog tests.test_model_router -v
```

Expected: new schema/exclusivity/loading tests fail because `registered_workflow_id` is unknown; all legacy raw-binding tests continue to run.

- [ ] **Step 4: Add schema, exclusivity, and registered-ID loader**

Add the schema property:

```python
"registered_workflow_id": {
    "type": "string",
    "pattern": "^imported:[0-9a-f]{64}$",
},
```

Replace pairwise exclusivity with one normalized source count while preserving the legacy pair check:

```python
if ("workflow_path" in arguments) != ("workflow_binding" in arguments):
    return tool_error(
        "invalid_workflow_binding",
        "validation",
        "workflow_path and workflow_binding must be provided together.",
        {"fields": ["workflow_path", "workflow_binding"]},
    )
workflow_sources = [
    "workflow_template_id" in arguments,
    "registered_workflow_id" in arguments,
    "workflow_path" in arguments,
]
if sum(workflow_sources) > 1:
    return tool_error(
        "invalid_workflow_binding",
        "validation",
        "Choose one shipped, registered, or legacy imported workflow source.",
        {"fields": [
            "workflow_template_id", "registered_workflow_id",
            "workflow_path", "workflow_binding",
        ]},
    )
```

Implement the loader:

```python
def _registered_id_workflow_binding(
    services: Any,
    record: dict[str, object],
    registered_workflow_id: str,
    component_identity_tokens: list[str] | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object] | None]:
    registered = services.workflows.load_registered(registered_workflow_id)
    if component_identity_tokens is None:
        raise AssetEngineError(
            "invalid_component_bundle",
            "Registered workflow trust requires exact selected component identities.",
            "validation",
        )
    selected, component_bundle = _workflow_component_bundle(
        services,
        record,
        registered["graph"],
        registered,
        component_identity_tokens,
    )
    trust_binding = {
        "backend": "comfyui",
        "endpoint_identity": selected["endpoint_identity"],
        "backend_model_id": selected["backend_model_id"],
        "backend_identity_token": identity_token(selected),
        "template_id": registered["template_id"],
        "template_version": registered["template_version"],
        "workflow_sha256": registered["workflow_sha256"],
        "component_bundle_sha256": component_bundle["bundle_sha256"],
    }
    public_registration = {
        "source": "registered",
        "template_id": registered["template_id"],
        "template_version": registered["template_version"],
        "workflow_sha256": registered["workflow_sha256"],
    }
    return trust_binding, public_registration, component_bundle
```

Add this branch in `_trust_call` before the legacy raw path:

```python
elif "registered_workflow_id" in arguments:
    workflow_binding, registered_workflow, component_bundle = _registered_id_workflow_binding(
        services,
        record,
        arguments["registered_workflow_id"],
        component_tokens,
    )
```

- [ ] **Step 5: Run registered and legacy trust/routing tests GREEN**

Run:

```powershell
python -m unittest tests.test_mcp_server tests.test_model_catalog tests.test_model_router tests.test_trust_registry -v
```

Expected: registered-ID inspect/approval/recommendation tests pass; legacy `workflow_path + workflow_binding`, shipped, regional, and two-stage trust tests remain green.

- [ ] **Step 6: Commit trust consumption**

```powershell
git add scripts/mcp_server.py tests/test_mcp_server.py tests/test_model_catalog.py tests/test_model_router.py
git commit -m "feat: trust registered workflow identities"
```

---

### Task 7: Update Agent Contract, Public Docs, Version, And Packaging

**Files:**
- Modify: `skills/local-gpu-imagegen/SKILL.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/architecture.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/troubleshooting.md`
- Modify: `docs/github-listing.md`
- Modify: `.codex-plugin/plugin.json`
- Modify: `pyproject.toml`
- Modify: `server.json`
- Modify: `scripts/local_gpu_imagegen/__init__.py`
- Modify: `scripts/verify_mcp.py`
- Modify: `tests/test_skill_contract.py`
- Modify: `tests/test_public_docs.py`
- Modify: `tests/test_verify_mcp.py`
- Modify: `tests/test_packaging.py`
- Test: `tests/test_skill_contract.py`
- Test: `tests/test_public_docs.py`
- Test: `tests/test_verify_mcp.py`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Active version is `0.8.0` in all four metadata locations and public active-version checks.
- `PUBLIC_TOOLS`, `EXPECTED_TOOLS`, and `DEFAULT_EXPECTED_TOOLS` include the two onboarding tools and total exactly 17.
- The Skill makes workflow inspection a user-visible, two-message confirmation boundary and never starts ComfyUI or discovery implicitly.

- [ ] **Step 1: Add Skill and public-document contract tests**

Add to `SkillContractTests`:

```python
def test_safe_workflow_onboarding_requires_later_digest_bound_confirmation(self) -> None:
    section = _section(self.text, "## Workflow Onboarding", "## Confirmation Gate")
    _assert_ordered(section, (
        "`local_gpu_inspect_workflow`",
        "display the source SHA-256",
        "workflow SHA-256",
        "inferred binding",
        "component identities",
        "register_workflow:<source_sha256>:<proposal_digest>",
        "stop and wait for a later user message",
        "`local_gpu_register_workflow`",
        "`local_gpu_set_model_trust`",
    ))
    for boundary in (
        "does not start ComfyUI",
        "does not run discovery implicitly",
        "diagnostic",
        "no confirmation",
        "registration does not grant trust or public authority",
        "UI format",
        "developer mode",
    ):
        self.assertIn(boundary, section)
```

Update public doc tests:

```python
PUBLIC_TOOLS |= {
    "local_gpu_inspect_workflow",
    "local_gpu_register_workflow",
}

def test_v080_docs_describe_safe_workflow_onboarding_truthfully(self) -> None:
    public = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md", "docs/architecture.md", "docs/quickstart.md",
            "docs/troubleshooting.md", "docs/github-listing.md",
        )
    )
    for required in (
        "exactly seventeen tools",
        "ordinary `txt2img`",
        "single checkpoint",
        "split model",
        "`source_sha256`",
        "`workflow_sha256`",
        "`registered_workflow_id`",
        "registration does not grant model trust",
        "real-client onboarding evidence is pending",
    ):
        self.assertIn(required, public)
```

Rename the active-version test to v0.8 and assert `0.8.0`, while retaining assertions that all earlier changelog entries and v0.7 evidence filenames remain present.

- [ ] **Step 2: Update verifier and package tests first, then confirm RED**

Add the two names to `EXPECTED_TOOLS` in `tests/test_verify_mcp.py`, update the test name to `test_default_contract_is_exactly_seventeen_tools`, expect package version `0.8.0`, wheel member `local_gpu_imagegen/workflow_onboarding.py`, and installed tool count `17`.

Run:

```powershell
python -m unittest tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp tests.test_packaging -v
```

Expected: failures identify stale Skill/docs, v0.7 metadata, 15-tool verifier, and missing installed module assertion; tests must not fail from malformed JSON/TOML.

- [ ] **Step 3: Teach the Skill the exact bounded flow**

Insert this section before the existing general confirmation gate:

```markdown
## Workflow Onboarding

When the user supplies one existing ComfyUI workflow, call
`local_gpu_inspect_workflow` with only its explicit local path. The tool does
not start ComfyUI and does not run discovery implicitly. If it returns
`diagnostic`, display the inferred topology/binding, limitations, and recovery
action; there is no confirmation and registration must stop.

For a registerable result, display the source SHA-256, workflow SHA-256,
topology, complete inferred binding, owned output, component identities,
limitations, and exact
`register_workflow:<source_sha256>:<proposal_digest>`. Explain that
registration does not grant trust or public authority, then stop and wait for
a later user message containing that exact confirmation.

Only after that later message, call `local_gpu_register_workflow` with the same
path, proposal digest, and exact confirmation. Then use the returned
`registered_workflow_id` in the existing `local_gpu_set_model_trust` flow with
fresh exact component identities. UI format is not converted: direct the user
to enable ComfyUI developer mode and export API format. Never select node IDs,
edit the graph, start a backend, download components, or substitute another
workflow automatically.
```

- [ ] **Step 4: Synchronize version and exact tool inventories**

Change only active metadata:

```toml
# pyproject.toml
version = "0.8.0"
```

```python
# scripts/local_gpu_imagegen/__init__.py
__version__ = "0.8.0"
```

Set `.codex-plugin/plugin.json` top-level version, `server.json` top-level/package versions, and active public examples to `0.8.0`. Add both onboarding names to `scripts/verify_mcp.py::DEFAULT_EXPECTED_TOOLS`. Do not rename or edit retained `codex-v070.json`, `claude-code-v070.json`, v0.7 demo evidence, or historical changelog sections.

- [ ] **Step 5: Add concise public documentation**

Add one outcome-focused README/quickstart sequence:

```text
API-only discovery (when current inventory is absent)
-> local_gpu_inspect_workflow
-> display hashes, inferred binding, components, limitations, confirmation
-> later exact user confirmation
-> local_gpu_register_workflow
-> separate local_gpu_set_model_trust with registered_workflow_id
```

In architecture, document ownership and dual hashes. In troubleshooting, map UI format, unsupported topology, ambiguity, diagnostic inventory, stale proposal, invalid confirmation, and registered-copy drift to bounded recovery. In changelog and GitHub listing, state that v0.8 supports ordinary single/split `txt2img` onboarding but not arbitrary ComfyUI workflows, and that real-client onboarding evidence remains pending until the separate gate.

- [ ] **Step 6: Run contract/docs/verifier/package suites GREEN**

Run:

```powershell
python -m unittest tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp tests.test_packaging -v
```

Expected: exact 17-tool, v0.8, wheel inclusion, installed stdio, Skill ordering, historical-evidence, and truthfulness tests pass.

- [ ] **Step 7: Commit active release surface**

```powershell
git add skills/local-gpu-imagegen/SKILL.md README.md CHANGELOG.md docs/architecture.md docs/quickstart.md docs/troubleshooting.md docs/github-listing.md .codex-plugin/plugin.json pyproject.toml server.json scripts/local_gpu_imagegen/__init__.py scripts/verify_mcp.py tests/test_skill_contract.py tests/test_public_docs.py tests/test_verify_mcp.py tests/test_packaging.py
git commit -m "docs: publish safe workflow onboarding contract"
```

---

### Task 8: Run Model-Free Repository And Exact Wheel Gates

**Files:**
- Modify only if a reproduced defect requires it: files already listed in Tasks 1-7
- Update ignored continuity after verification: `PROJECT_NODES.md`
- Update ignored continuity after verification: `NEXT_SESSION.md`

**Interfaces:**
- Produces one clean model-free verification record for source and installed wheel.
- Does not create real-client evidence or claim end-to-end onboarding.

- [ ] **Step 1: Run focused onboarding, registry, trust, MCP, docs, and package gates**

```powershell
python -m unittest tests.test_workflow_onboarding tests.test_workflow_templates tests.test_runtime_services tests.test_mcp_server tests.test_model_catalog tests.test_model_router tests.test_trust_registry tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp tests.test_packaging -v
```

Expected: all focused tests pass with only documented Windows link/reparse permission skips.

- [ ] **Step 2: Run the complete model-free suite**

```powershell
python -m unittest discover -s tests -v
```

Expected: zero failures/errors; no backend starts, GPU generation, model download, or user trust/client mutation occurs.

- [ ] **Step 3: Verify repository hygiene and frozen workflow bytes**

```powershell
git diff --check
git diff --quiet -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git status --short
```

Expected: `git diff --check` and the explicit workflow diff return exit code 0. The two known worktree `M` status entries may remain checkout/index artifacts, but they must have no content diff and must not be staged.

- [ ] **Step 4: Build one exact wheel and install it into a disposable venv**

Use the project-local Python and a temporary build output outside tracked paths:

```powershell
$gateRoot = Join-Path $env:TEMP ("local-gpu-imagegen-v080-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $gateRoot | Out-Null
python -m pip wheel . --no-deps --wheel-dir $gateRoot
python -m venv (Join-Path $gateRoot "venv")
& (Join-Path $gateRoot "venv\Scripts\python.exe") -m pip install --no-deps (Get-ChildItem $gateRoot\local_gpu_imagegen-0.8.0-*.whl | Select-Object -ExpandProperty FullName)
& (Join-Path $gateRoot "venv\Scripts\local-gpu-imagegen.exe") verify
```

Expected: wheel filename is `local_gpu_imagegen-0.8.0-...whl`; installed verification reports exactly 17 tools and does not depend on the checkout through `PYTHONPATH`.

- [ ] **Step 5: Run installed-package tests against the exact wheel**

Run the repository's package/CLI/client-config tests with the disposable environment or their existing isolated test harness:

```powershell
python -m unittest tests.test_packaging tests.test_cli tests.test_client_setup tests.test_client_configs tests.test_verify_mcp -v
```

Expected: all installed-path checks pass, including the new module and 17-tool stdio contract.

- [ ] **Step 6: Record verified control flow, failures, commands, and limitations**

Append a concise milestone to `PROJECT_NODES.md` containing:

```markdown
### v0.8 model-free safe workflow onboarding

- Control flow: explicit API JSON -> inspect/infer/validate -> exact inventory
  match -> later digest confirmation -> immutable registration -> separate
  registered-ID trust -> existing recommendation/generation resolution.
- Failure modes: unsupported envelope/operation/topology, ambiguous path,
  diagnostic inventory, source/proposal/inventory drift, invalid confirmation,
  registered-copy drift; every pre-registration failure writes nothing.
- Verification: record the literal focused command and its unittest summary;
  record the literal full-suite unittest summary; record the built wheel name
  and the verifier's 17 tool names; record that `git diff --check` exited 0.
- Limitations: ordinary single-checkpoint/split-model txt2img only; no UI
  conversion, custom nodes, graph editing, regional/two-stage onboarding,
  downloads, implicit discovery/backend start, or trust/public authority.
- Open gate: one separately authorized real-client zero-GPU onboarding session
  is still required before an end-to-end claim.
```

Replace angle-bracket result fields with the observed values. Update `NEXT_SESSION.md` to point only to Task 9 and the exact branch/worktree/HEAD; remove stale design-review instructions.

- [ ] **Step 7: Commit any gate-only fixes, otherwise leave implementation HEAD unchanged**

If verification exposed and fixed a defect, first print the exact changed
tracked paths, review them, and stage that explicit path list (never a glob):

```powershell
git status --short
git diff --name-only
git commit -m "fix: close workflow onboarding verification gap"
```

Run `git add -- path/to/file.py tests/test_matching_file.py` with the literal
paths shown by the preceding commands before the commit. If the only status
entries are the two known frozen workflow artifacts, stage nothing.

If no tracked fixes were needed, do not create an empty commit. Never stage the two frozen workflow files.

---

### Task 9: Stop For Separately Authorized Real-Client Zero-GPU Evidence

**Files:**
- Create only after explicit later authority: a sanitized v0.8 client-session record under `docs/evidence/client-sessions/`
- Modify only after explicit later authority: its schema/validator/tests if the approved evidence shape requires it
- Update after validation: `PROJECT_NODES.md`
- Update after validation: `NEXT_SESSION.md`

**Interfaces:**
- Consumes the exact built/installed v0.8 wheel from Task 8, an isolated state directory, one explicit safe local API workflow, and applicable client/backend-start authority.
- Produces genuine MCP JSON calls/results for discovery -> inspect -> later confirmation -> register -> registered-ID trust.
- Performs zero prompt submissions and zero GPU generations.

- [ ] **Step 1: Stop and request the exact later authorities**

Do not proceed unless the user separately authorizes all applicable stateful actions: start or use local ComfyUI for API-only discovery, launch one named real MCP client session, use an isolated state directory, register the exact workflow, mutate trust only inside that isolated state, retain a sanitized evidence record, and commit it.

Expected while authority is absent: Task 9 remains unchecked and public copy continues to say real-client onboarding evidence is pending.

- [ ] **Step 2: Execute only the approved zero-GPU client flow**

The retained transcript must show this exact temporal sequence:

```text
local_gpu_discover_models (API-only, if needed)
local_gpu_inspect_workflow
display exact source_sha256/workflow_sha256/proposal_digest/confirmation
later user confirmation
local_gpu_register_workflow
local_gpu_set_model_trust with registered_workflow_id
```

It must contain no `local_gpu_start_run`, `local_gpu_generate_round`, ComfyUI `/prompt`, model download, private absolute path, credential, or model bytes.

- [ ] **Step 3: Validate, sanitize, and commit the evidence only if truthful**

Run the applicable client-session validator and tests, plus:

```powershell
python -m unittest tests.test_validate_client_sessions tests.test_public_docs -v
python -m unittest discover -s tests -v
git diff --check
```

Expected: the record validates, private values are absent, all tests pass, and the public end-to-end statement is changed only after evidence exists.

Use `git status --short` and `git diff --name-only` to review the generated,
sanitized v0.8 record's literal filename. Stage that literal record path plus
only the schema/validator/test/public-copy files that actually changed, then
commit with `git commit -m "test: retain real workflow onboarding session"`.
Do not use a wildcard, guess an evidence filename, publish, push, tag, release,
or perform GPU generation in this task.

---

## Plan Self-Review

- **Spec coverage:** Tasks 1-4 cover bounded reading, both envelopes, inference, both safe topologies, authoritative validation, ambiguity/exclusions, inventory matching, dual hashes, stateless confirmation, re-read, drift, idempotency, and no-mutation. Tasks 5-6 cover exactly two thin tools, 17-tool count, runtime ownership, registered-ID trust, current identities, recommendation/generation resolution, and legacy compatibility. Tasks 7-8 cover Skill/docs/version/package/repository/frozen-byte gates. Task 9 preserves the separately authorized real-client zero-GPU evidence requirement and blocks end-to-end claims until it passes.
- **Ownership/complexity:** Only `workflow_onboarding.py` is new production code. No engine, run-store, backend, regional, or two-stage changes appear. The explicit line-count stop is checked before service/docs expansion.
- **Placeholder scan:** No `TBD`, `TODO`, “implement later”, “similar to”, or unspecified error-handling step is used. Task 8 result markers are explicitly replaced with observed verification facts, not implementation placeholders. Task 9 filenames remain authority-dependent and are not created during model-free implementation.
- **Type consistency:** `WorkflowOnboarding.inspect/register`, `read_workflow_source`, `prepare_import`, `store_prepared_import`, `registered_workflow_id`, component shapes, `RuntimeServices.onboarding`, and proposal fields use the same names and types in production, tests, schemas, Skill, and trust wiring.
- **Truthfulness:** Registration is authority-neutral; offline inspection cannot confirm; real-client evidence is pending; no GPU quality, performance, arbitrary-workflow compatibility, production readiness, or 800-Star outcome is claimed.
