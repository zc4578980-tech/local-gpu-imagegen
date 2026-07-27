# Codex-First Workflow Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a configured Codex user run one supported existing ComfyUI API `txt2img` workflow through exactly one preparation decision and one execution decision while preserving inspected workflow defaults and making no pre-approval state change.

**Architecture:** `WorkflowOnboarding` remains the sole owner of graph extraction, binding inference, inventory matching, and default observation. `mcp_server.py` keeps the existing 17-tool surface, consumes an in-memory prepared workflow for raw-path trust inspection, and declares the bounded `workflow_defaults` output schema; the Agent Skill maps those defaults into the existing trust capability and route/run contracts without adding orchestration code. All implementation and evidence before the separately approved live gate are model-free.

**Tech Stack:** Python 3.11/3.12 standard library, JSON-RPC MCP schemas, ComfyUI API-format JSON, `unittest`, Markdown contract tests.

## Global Constraints

- Work only in the existing `.worktrees/codex-first-workflow-runner` linked worktree on `codex/codex-first-workflow-runner`, based exactly on `main@3fb45163ec61189c2d2c89a7c183612a55cb6058`.
- Production changes are limited to `scripts/local_gpu_imagegen/workflow_onboarding.py`, `scripts/mcp_server.py`, and the approved imported-route branch in `scripts/local_gpu_imagegen/model_catalog.py`, with approximately 75-150 net new production lines across all three files.
- Adaptive Quality remains paused; this slice makes no image-quality improvement claim and adds no quality benchmark or multi-round GPU evaluation.
- Budget two to four focused implementation days and never exceed the user's five-focused-day hard ceiling without a new design review.
- Add no production module, dependency, MCP tool, profile, model, workflow, backend, state store, generic graph abstraction, custom-node support, UI-format conversion, process control, or download path.
- Keep the MCP surface at exactly 17 tools and preserve strict `additionalProperties: false` schemas.
- Support only a bare API graph or one graph under `prompt`, ordinary `txt2img`, one unambiguous sampler/latent/decoder/owned output, and either one `CheckpointLoaderSimple` or the reviewed split-model topology.
- Treat `source_sha256`, `workflow_sha256`, component identities, endpoint identity, trust confirmation, route token, and successful-round budget as fail-closed boundaries.
- Everything before the displayed preparation decision is read-only. The first workflow-state write is the later approved `local_gpu_register_workflow` call.
- Use the exact `workflow_defaults` object observed from validated bindings; never substitute a repository profile or product preset for width, height, seed, steps, guidance, sampler, scheduler, or prompt values.
- The user sees exactly two decisions: one preparation decision covering immutable registration plus private trust, and one execution decision covering one frozen route and one successful-round budget.
- The model-free phase starts no backend, uses no GPU, changes no trust/client state, downloads nothing, and performs no remote action.
- A later live gate requires a fresh Codex session, a newly displayed exact route, and a new user confirmation. It permits one accepted ComfyUI prompt ID and at most one successful image, with no retry, recovery attempt, quality comparison, model switch, CPU fallback, or download.
- Stop for design review if implementation needs a fourth production owner, more than about 150 net production lines, a new tool or dependency, duplicated graph/hash extraction in transport, or a weakened confirmation/drift boundary. The third owner was approved on 2026-07-27 after the Task 3 route test proved imported registrations were otherwise unroutable.

## File Structure

- Modify `scripts/local_gpu_imagegen/workflow_onboarding.py`: prepare raw-path trust input in memory, extract validated workflow defaults, and return them from `inspect`.
- Modify `scripts/mcp_server.py`: use the in-memory onboarding path for legacy raw-path trust inspection and expose the exact nested `workflow_defaults` schema.
- Modify `scripts/local_gpu_imagegen/model_catalog.py`: resolve `imported:` workflow IDs through the existing registered-workflow path while retaining shipped inspection for all shipped templates.
- Modify `tests/test_workflow_onboarding.py`: prove exact/default-order behavior and fail-closed malformed defaults.
- Modify `tests/test_mcp_server.py`: prove raw-path inspection is read-only, the schema is strict, trust stores the same defaults, routing echoes them, and the tool count stays 17.
- Modify `skills/local-gpu-imagegen/SKILL.md`: define the Codex-first two-decision recipe, exact default mapping, inert-registration recovery, one-round behavior, and no-fallback rules.
- Modify `tests/test_skill_contract.py`: make the Agent sequence and stop conditions executable documentation.
- Modify `README.md` and `docs/quickstart.md`: lead with the literal Codex offer and one ready-to-use request.
- Create `docs/alternatives.md`: record dated, source-linked alternatives without volatile Star claims or hostile ranking.
- Modify `tests/test_public_docs.py`: enforce first-viewport copy, supported-scope language, alternatives, and truthfulness boundaries.
- Modify `docs/architecture.md`: record the in-memory preparation path and authoritative defaults flow.
- Update root-local `PROJECT_NODES.md` and `NEXT_SESSION.md` after model-free verification; these continuity files are not part of the branch commit.

---

### Task 1: Make Pre-Approval Trust Inspection Actually Read-Only

**Files:**
- Modify: `tests/test_workflow_onboarding.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `scripts/local_gpu_imagegen/workflow_onboarding.py`
- Modify: `scripts/mcp_server.py`

**Interfaces:**
- Consumes: `WorkflowOnboarding.inspect(path: Path) -> dict[str, object]`, inferred bindings, and the onboarding inventory provider.
- Produces: `WorkflowOnboarding.prepare_trust_binding(path: Path, binding: object) -> dict[str, object]`, an in-memory prepared registration document with no filesystem mutation.
- Preserves: `_registered_workflow_binding(...) -> tuple[trust_binding, public_registration, component_bundle]` and the existing raw-path MCP input shape.

- [ ] **Step 1: Add the red onboarding test for an in-memory preparation**

Add this method to `WorkflowOnboardingTests`:

```python
def test_prepare_trust_binding_is_read_only_and_matches_inspection(self) -> None:
    self.use_exact_single_inventory()
    inspected = self.onboarding.inspect(self.single_path)

    prepared = self.onboarding.prepare_trust_binding(
        self.single_path,
        inspected["binding"],
    )

    self.assertEqual(prepared["template_id"], f"imported:{inspected['workflow_sha256']}")
    self.assertEqual(prepared["workflow_sha256"], inspected["workflow_sha256"])
    self.assertEqual(prepared["bindings"], {
        key: value
        for key, value in inspected["binding"].items()
        if key != "output"
    })
    self.assertFalse((self.state_dir / "workflows").exists())
```

- [ ] **Step 2: Run the onboarding test and verify the missing interface**

Run:

```shell
python -m unittest tests.test_workflow_onboarding.WorkflowOnboardingTests.test_prepare_trust_binding_is_read_only_and_matches_inspection -v
```

Expected: FAIL with `AttributeError: 'WorkflowOnboarding' object has no attribute 'prepare_trust_binding'`.

- [ ] **Step 3: Add the red MCP regression test for the legacy raw-path branch**

Import `WorkflowOnboarding` in `tests/test_mcp_server.py`:

```python
from local_gpu_imagegen.workflow_onboarding import WorkflowOnboarding  # noqa: E402
```

Replace the existing raw-path helper test with this explicit read-only contract:

```python
def test_raw_path_trust_inspection_prepares_without_registering(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state_dir = root / "state"
        source = root / "sd15.json"
        document = json.loads(
            (ROOT / "workflows" / "comfyui" / "sd15-txt2img-v1.json").read_text(
                encoding="utf-8"
            )
        )
        source.write_text(json.dumps(document["graph"]), encoding="utf-8")
        graph_binding = {**document["bindings"], "output": [document["output_node"]]}
        record = {
            "backend": "comfyui",
            "endpoint_identity": "endpoint:comfyui",
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
        discovery.inventory.return_value = [record]
        workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            state_dir,
        )
        services = SimpleNamespace(
            discovery=discovery,
            workflows=workflows,
            onboarding=WorkflowOnboarding(workflows, lambda: discovery.inventory()),
        )

        trust_binding, prepared, bundle = mcp_server._registered_workflow_binding(
            services,
            record,
            str(source),
            graph_binding,
        )

        self.assertEqual(trust_binding["backend_model_id"], record["backend_model_id"])
        self.assertEqual(
            trust_binding["backend_identity_token"],
            mcp_server.identity_token(record),
        )
        self.assertTrue(prepared["template_id"].startswith("imported:"))
        self.assertIsNone(bundle)
        self.assertFalse((state_dir / "workflows").exists())
```

- [ ] **Step 4: Run the MCP regression and verify that current code writes**

Run:

```shell
python -m unittest tests.test_mcp_server.McpServerUnitTests.test_raw_path_trust_inspection_prepares_without_registering -v
```

Expected: FAIL because `_registered_workflow_binding` calls `register_import` and creates `state/workflows`.

- [ ] **Step 5: Refactor onboarding preparation without duplicating graph logic**

In `WorkflowOnboarding`, extract the common source preparation and add the public in-memory trust method:

```python
def _prepare_source(
    self,
    path: Path,
) -> tuple[bytes, dict[str, object], dict[str, object]]:
    encoded, source_value = read_workflow_source(Path(path))
    graph = _extract_graph(source_value)
    inferred = infer_workflow_binding(graph)
    prepared = self.workflows.prepare_import(
        graph,
        inferred["binding"],
        _component_model_names(inferred["components"]),
    )
    if prepared["operation"] != "txt2img":
        _reject(
            "unsupported_workflow_operation",
            "Workflow onboarding supports ordinary txt2img only.",
        )
    return encoded, inferred, prepared

def prepare_trust_binding(
    self,
    path: Path,
    binding: object,
) -> dict[str, object]:
    _encoded, inferred, prepared = self._prepare_source(Path(path))
    if binding != inferred["binding"]:
        _reject(
            "invalid_workflow_binding",
            "Workflow trust binding differs from the current inferred binding.",
        )
    _matched, failures = self._match_inventory(inferred["components"])
    if failures:
        _reject(
            "workflow_model_binding_ambiguous",
            "Workflow trust preparation requires exact current component identities.",
            {"inventory_diagnostics": failures},
        )
    return prepared
```

Change `inspect` to start with:

```python
encoded, inferred, prepared = self._prepare_source(Path(path))
```

Remove its former duplicate read/extract/infer/prepare/operation block. Keep result, inventory, digest, and confirmation behavior unchanged.

- [ ] **Step 6: Route raw-path trust inspection through onboarding**

In `mcp_server._registered_workflow_binding`, remove the now-unused `available_models` collection and replace:

```python
registered = services.workflows.register_import(Path(path), binding, available_models)
```

with:

```python
registered = services.onboarding.prepare_trust_binding(Path(path), binding)
```

Do not add a fallback to `register_import` when `onboarding` is absent; runtime services own the onboarding service, and tests must construct that dependency.

- [ ] **Step 7: Run the two focused files**

```shell
python -m unittest tests.test_workflow_onboarding tests.test_mcp_server -v
```

Expected: PASS, including both read-only tests; no backend process and no GPU activity.

- [ ] **Step 8: Commit the read-only correction**

```shell
git add scripts/local_gpu_imagegen/workflow_onboarding.py scripts/mcp_server.py tests/test_workflow_onboarding.py tests/test_mcp_server.py
git commit -m "fix: keep workflow trust inspection read only"
```

### Task 2: Extract Exact Workflow Defaults And Expose A Strict Schema

**Files:**
- Modify: `tests/test_workflow_onboarding.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `scripts/local_gpu_imagegen/workflow_onboarding.py`
- Modify: `scripts/mcp_server.py`

**Interfaces:**
- Consumes: validated `prepared["graph"]` and `prepared["bindings"]`.
- Produces: required `workflow_defaults` with `positive_prompt`, `negative_prompt`, `width`, `height`, `seed`, `steps`, `guidance_scale`, `sampler_name`, and `scheduler`.
- Mapping boundary: `sampler_name` observes ComfyUI `sampler_name` through internal binding key `sampler`; `guidance_scale` observes ComfyUI `cfg`.

- [ ] **Step 1: Add exact single/split and randomized-ID red tests**

Add this helper near `comfy_record`:

```python
def expected_defaults(
    *,
    width: int,
    height: int,
    steps: int,
    guidance_scale: float,
    sampler_name: str,
    scheduler: str,
) -> dict[str, object]:
    return {
        "positive_prompt": "",
        "negative_prompt": "",
        "width": width,
        "height": height,
        "seed": 0,
        "steps": steps,
        "guidance_scale": guidance_scale,
        "sampler_name": sampler_name,
        "scheduler": scheduler,
    }
```

Add to `WorkflowOnboardingTests`:

```python
def test_inspection_returns_exact_single_and_split_workflow_defaults(self) -> None:
    cases = (
        (self.single_graph, self.single_path, expected_defaults(
            width=512, height=512, steps=20, guidance_scale=7.0,
            sampler_name="euler", scheduler="normal",
        )),
        (self.split_graph, self.split_path, expected_defaults(
            width=768, height=768, steps=8, guidance_scale=1.0,
            sampler_name="res_multistep", scheduler="simple",
        )),
    )
    for graph, path, expected in cases:
        self.inventory[:] = [
            comfy_record(
                component["backend_model_id"],
                component["loader_class"],
                component["loader_input"],
            )
            for component in workflow_component_bindings(graph)
        ]
        with self.subTest(path=path.name):
            self.assertEqual(
                self.onboarding.inspect(path)["workflow_defaults"],
                expected,
            )

def test_workflow_defaults_ignore_node_ids_and_json_key_order(self) -> None:
    self.inventory[:] = [
        comfy_record(
            component["backend_model_id"],
            component["loader_class"],
            component["loader_input"],
        )
        for component in workflow_component_bindings(self.split_graph)
    ]
    expected = expected_defaults(
        width=768, height=768, steps=8, guidance_scale=1.0,
        sampler_name="res_multistep", scheduler="simple",
    )
    for seed in range(10):
        path = self.write_json(
            f"split-{seed}.json",
            remap_graph(self.split_graph, seed),
            compact=bool(seed % 2),
        )
        with self.subTest(seed=seed):
            self.assertEqual(
                self.onboarding.inspect(path)["workflow_defaults"],
                expected,
            )
```

- [ ] **Step 2: Add fail-closed red tests for missing, boolean, and invalid defaults**

```python
def test_missing_boolean_or_invalid_workflow_defaults_fail_closed(self) -> None:
    self.use_exact_single_inventory()
    binding = infer_workflow_binding(self.single_graph)["binding"]
    cases = (
        ("missing_scheduler", binding["scheduler"], None),
        ("boolean_steps", binding["steps"], True),
        ("boolean_guidance", binding["guidance_scale"], True),
        ("numeric_prompt", binding["positive_prompt"], 7),
        ("empty_sampler", binding["sampler"], ""),
    )
    for label, path, replacement in cases:
        graph = copy.deepcopy(self.single_graph)
        node_id, section, field = path
        if replacement is None:
            del graph[node_id][section][field]
        else:
            graph[node_id][section][field] = replacement
        source = self.write_json(f"{label}.json", graph)
        with self.subTest(label=label), self.assertRaises(AssetEngineError):
            self.onboarding.inspect(source)
        self.assertFalse((self.state_dir / "workflows").exists())
```

- [ ] **Step 3: Run the defaults tests and verify the missing output**

```shell
python -m unittest tests.test_workflow_onboarding.WorkflowOnboardingTests.test_inspection_returns_exact_single_and_split_workflow_defaults tests.test_workflow_onboarding.WorkflowOnboardingTests.test_workflow_defaults_ignore_node_ids_and_json_key_order tests.test_workflow_onboarding.WorkflowOnboardingTests.test_missing_boolean_or_invalid_workflow_defaults_fail_closed -v
```

Expected: the first two tests FAIL with `KeyError: 'workflow_defaults'`; malformed-value subtests remain fail-closed.

- [ ] **Step 4: Add one bounded default extractor**

Add in `workflow_onboarding.py`:

```python
WORKFLOW_DEFAULT_BINDINGS = (
    ("positive_prompt", "positive_prompt"),
    ("negative_prompt", "negative_prompt"),
    ("width", "width"),
    ("height", "height"),
    ("seed", "seed"),
    ("steps", "steps"),
    ("guidance_scale", "guidance_scale"),
    ("sampler_name", "sampler"),
    ("scheduler", "scheduler"),
)


def _workflow_defaults(
    graph: dict[str, object],
    binding: dict[str, object],
) -> dict[str, object]:
    values: dict[str, object] = {}
    try:
        for public_name, binding_name in WORKFLOW_DEFAULT_BINDINGS:
            node_id, section, field = binding[binding_name]
            values[public_name] = copy.deepcopy(graph[node_id][section][field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError(
            "invalid_workflow_defaults",
            "Workflow default bindings do not resolve to exact current values.",
        ) from error
    if any(type(values[name]) is not int for name in ("width", "height", "seed", "steps")):
        _reject("invalid_workflow_defaults", "Workflow integer defaults have invalid types.")
    guidance = values["guidance_scale"]
    if not isinstance(guidance, (int, float)) or isinstance(guidance, bool):
        _reject("invalid_workflow_defaults", "Workflow guidance default must be numeric.")
    for name in ("positive_prompt", "negative_prompt"):
        if not isinstance(values[name], str):
            _reject("invalid_workflow_defaults", "Workflow prompt defaults must be strings.")
    for name in ("sampler_name", "scheduler"):
        if not isinstance(values[name], str) or not values[name].strip():
            _reject(
                "invalid_workflow_defaults",
                "Workflow sampler defaults must be non-empty strings.",
            )
    return values
```

In `WorkflowOnboarding.inspect`, add after `owned_output`:

```python
"workflow_defaults": _workflow_defaults(
    prepared["graph"],
    prepared["bindings"],
),
```

Do not add a second extraction path. The semantic hash covers `prepared["graph"]`, and `proposal_digest` covers `workflow_sha256`.

- [ ] **Step 5: Run the onboarding file**

```shell
python -m unittest tests.test_workflow_onboarding -v
```

Expected: PASS.

- [ ] **Step 6: Add the strict nested MCP schema red test**

Extend `test_workflow_onboarding_tools_have_exact_schemas_and_raise_count_to_seventeen`:

```python
inspect_output = by_name["local_gpu_inspect_workflow"]["outputSchema"]["oneOf"][0]
defaults = inspect_output["properties"]["workflow_defaults"]
self.assertIn("workflow_defaults", inspect_output["required"])
self.assertFalse(defaults["additionalProperties"])
self.assertEqual(
    set(defaults["properties"]),
    {
        "positive_prompt", "negative_prompt", "width", "height", "seed",
        "steps", "guidance_scale", "sampler_name", "scheduler",
    },
)
self.assertEqual(set(defaults["required"]), set(defaults["properties"]))
self.assertEqual(len(tools), 17)
```

- [ ] **Step 7: Run the schema test and verify it fails**

```shell
python -m unittest tests.test_mcp_server.McpServerUnitTests.test_workflow_onboarding_tools_have_exact_schemas_and_raise_count_to_seventeen -v
```

Expected: FAIL because `workflow_defaults` is absent from the success schema.

- [ ] **Step 8: Define and attach the schema without changing dispatch**

Inside `tool_schema()`, define:

```python
workflow_defaults = _object_schema({
    "positive_prompt": {"type": "string"},
    "negative_prompt": {"type": "string"},
    "width": {"type": "integer", "minimum": 256, "maximum": 1536, "multipleOf": 8},
    "height": {"type": "integer", "minimum": 256, "maximum": 1536, "multipleOf": 8},
    "seed": {"type": "integer", "minimum": 0, "maximum": 2**64 - 1},
    "steps": {"type": "integer", "minimum": 1, "maximum": 80},
    "guidance_scale": {"type": "number", "exclusiveMinimum": 0, "maximum": 30},
    "sampler_name": {"type": "string", "minLength": 1},
    "scheduler": {"type": "string", "minLength": 1},
}, [
    "positive_prompt", "negative_prompt", "width", "height", "seed",
    "steps", "guidance_scale", "sampler_name", "scheduler",
])
```

Add `"workflow_defaults": workflow_defaults` to inspect output properties and `"workflow_defaults"` to its required list. Do not change `handle_tool_call`; it already forwards the onboarding result.

- [ ] **Step 9: Run focused schema and dispatch coverage**

```shell
python -m unittest tests.test_mcp_server tests.test_workflow_onboarding -v
python scripts/verify_mcp.py
```

Expected: both commands PASS; `verify_mcp.py` reports `"ok": true` and exactly 17 tools.

- [ ] **Step 10: Commit the defaults contract**

```shell
git add scripts/local_gpu_imagegen/workflow_onboarding.py scripts/mcp_server.py tests/test_workflow_onboarding.py tests/test_mcp_server.py
git commit -m "feat: expose imported workflow defaults"
```

### Task 3: Prove One Frozen Default Set Reaches Trust And Routing

**Files:**
- Modify: `scripts/local_gpu_imagegen/model_catalog.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_skill_contract.py`
- Modify: `skills/local-gpu-imagegen/SKILL.md`

**Interfaces:**
- Consumes: `workflow_defaults` and existing `local_gpu_set_model_trust.capabilities`.
- Produces: an Agent-owned mapping where `guidance_scale -> guidance`, `sampler_name -> sampler`, and `width/height -> resolution`.
- Preserves: the identical capabilities object between `inspect_workflow_binding` and `approve_private`, then `route["recommended_settings"]`.

- [ ] **Step 1: Add the test-only exact capability mapping**

Add near the top-level helpers in `tests/test_mcp_server.py`:

```python
def workflow_capabilities(defaults: dict[str, object]) -> dict[str, object]:
    return {
        "model_family": "unknown",
        "prompt_dialect": "natural-v1",
        "operations": ["txt2img"],
        "minimum_dimension": 256,
        "maximum_dimension": 1536,
        "minimum_vram_gb": 0,
        "negative_prompt": "supported",
        "affinity": ["illustration"],
        "recommended": {
            "resolution": {"width": defaults["width"], "height": defaults["height"]},
            "steps": defaults["steps"],
            "guidance": defaults["guidance_scale"],
            "sampler": defaults["sampler_name"],
            "scheduler": defaults["scheduler"],
        },
    }
```

This is test glue for Agent behavior, not production orchestration.

- [ ] **Step 2: Add a model-free inspect/register/trust/route integration test**

Add to `McpServerUnitTests`:

```python
def test_imported_workflow_defaults_are_frozen_through_private_route(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "workflow.json"
        document = json.loads(
            (ROOT / "workflows" / "comfyui" / "sd15-txt2img-v1.json").read_text(
                encoding="utf-8"
            )
        )
        source.write_text(json.dumps(document["graph"]), encoding="utf-8")
        filesystem = {
            "backend": "filesystem",
            "endpoint_identity": "filesystem:test",
            "backend_model_id": "model.safetensors",
            "format": ".safetensors",
            "byte_size": 1024,
            "modified_ns": 1,
            "sha256": "a" * 64,
            "identity_strength": "cryptographic",
            "metadata": {},
        }
        comfy = {
            "backend": "comfyui",
            "endpoint_identity": "endpoint:comfyui",
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
        inventory = [filesystem, comfy]
        discovery = Mock()
        discovery.inventory.return_value = inventory
        workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            root / "workflow-state",
        )
        onboarding = WorkflowOnboarding(workflows, lambda: discovery.inventory())
        trust = TrustRegistry(root / "trust-state")
        services = SimpleNamespace(
            discovery=discovery,
            workflows=workflows,
            onboarding=onboarding,
            trust=trust,
        )
        inspected = onboarding.inspect(source)
        defaults = inspected["workflow_defaults"]
        registered = onboarding.register(
            source,
            inspected["proposal_digest"],
            inspected["confirmation"],
        )
        capabilities = workflow_capabilities(defaults)
        base = {
            "identity_token": mcp_server.identity_token(filesystem),
            "capabilities": capabilities,
            "registered_workflow_id": registered["registered_workflow_id"],
            "component_identity_tokens": [mcp_server.identity_token(filesystem)],
        }

        with patch.object(mcp_server, "get_runtime_services", return_value=services):
            trust_inspection = mcp_server.handle_tool_call({
                "name": "local_gpu_set_model_trust",
                "arguments": {**base, "action": "inspect_workflow_binding"},
            })
            self.assertFalse(trust_inspection["isError"])
            confirmation = trust_inspection["structuredContent"]["confirmations"][
                "approve_private"
            ]
            approved = mcp_server.handle_tool_call({
                "name": "local_gpu_set_model_trust",
                "arguments": {
                    **base,
                    "action": "approve_private",
                    "confirmation": confirmation,
                },
            })
            self.assertFalse(approved["isError"])

        record = TrustRegistry(root / "trust-state").list_records()[0]
        self.assertEqual(record["capabilities"], capabilities)
        models_root = root / "models"
        models_root.mkdir()
        catalog = ModelCatalog(
            models_root,
            lambda: inventory,
            TrustRegistry(root / "trust-state"),
            lambda: {"available_backends": ["comfyui"]},
            workflows,
        )
        router = CapabilityRouter(catalog, PromptCompilerRegistry())
        recommendation = router.recommend({
            "authorization_scope": "private",
            "operation": "txt2img",
            "profile": "standalone-illustration",
            "style": None,
            "width": defaults["width"],
            "height": defaults["height"],
            "affinity_tags": ["illustration"],
            "required_vram_gb": 0,
            "preferred_model_id": None,
        })

        self.assertEqual(len(recommendation["routes"]), 1)
        self.assertEqual(
            recommendation["routes"][0]["recommended_settings"],
            capabilities["recommended"],
        )
```

- [ ] **Step 3: Run the integration test**

```shell
python -m unittest tests.test_mcp_server.McpServerUnitTests.test_imported_workflow_defaults_are_frozen_through_private_route -v
```

Expected during implementation: FAIL with zero routes because the catalog sends an `imported:` ID to shipped-only inspection. Stop for design review, then after approval select the existing imported resolver in `model_catalog.py` and rerun this test plus shipped regional/two-stage routing regressions.

- [ ] **Step 4: Add red Agent contract tests**

Add to `tests/test_skill_contract.py`:

```python
def test_codex_first_runner_has_exactly_two_post_display_decisions(self) -> None:
    section = _section(self.text, "## Codex-First Workflow Runner", "## Adaptive Brief")
    _assert_ordered(section, (
        "`local_gpu_discover_models`",
        "`local_gpu_inspect_workflow`",
        "`inspect_workflow_binding`",
        "display one preparation proposal",
        "stop and wait for a later user message",
        "`local_gpu_register_workflow`",
        "`approve_private`",
        "`local_gpu_recommend_models`",
        "display one execution route",
        "stop and wait for a later user message",
        "`local_gpu_start_run`",
        "`local_gpu_get_run`",
        "`local_gpu_generate_round`",
        "generated / unreviewed",
    ))
    for required in (
        "exactly two user decisions",
        "same `capabilities` object",
        "`guidance_scale` to `recommended.guidance`",
        "`sampler_name` to `recommended.sampler`",
        "`max_rounds: 1`",
        "`upscale_policy: off`",
        "inert registration",
        "no automatic retry",
        "no model switch",
        "no CPU fallback",
        "no workflow fallback",
        "no download",
    ):
        with self.subTest(required=required):
            self.assertIn(required, section)

def test_codex_first_runner_preserves_defaults_except_explicit_overrides(self) -> None:
    section = _section(self.text, "## Codex-First Workflow Runner", "## Adaptive Brief")
    for field in (
        "`positive_prompt`", "`negative_prompt`", "`width`", "`height`",
        "`seed`", "`steps`", "`guidance_scale`", "`sampler_name`", "`scheduler`",
    ):
        with self.subTest(field=field):
            self.assertIn(field, section)
    self.assertIn("only fields explicitly overridden by the user may differ", section)
    self.assertIn("changed or expired route", section)
```

- [ ] **Step 5: Run the Skill tests and verify the missing section**

```shell
python -m unittest tests.test_skill_contract.SkillContractTests.test_codex_first_runner_has_exactly_two_post_display_decisions tests.test_skill_contract.SkillContractTests.test_codex_first_runner_preserves_defaults_except_explicit_overrides -v
```

Expected: FAIL because `## Codex-First Workflow Runner` does not exist.

- [ ] **Step 6: Add the Codex-first recipe before Adaptive Brief**

Insert this section in `skills/local-gpu-imagegen/SKILL.md`:

```markdown
## Codex-First Workflow Runner

Use this golden path when the user supplies one existing supported ComfyUI API
workflow and asks Codex to run it. The user sees exactly two user decisions:
one preparation decision and one execution decision. Internal confirmation
tokens are copied by the Agent only after the matching proposal has been
displayed and approved in a later user message.

Before the preparation decision, call `local_gpu_discover_models` in
`api_only` mode when inventory is absent, call
`local_gpu_inspect_workflow`, then call `local_gpu_set_model_trust` with
`action: inspect_workflow_binding`, the raw `workflow_path`, the exact inferred
binding and component identities, and one capability object. These calls are
read-only. Build `capabilities.recommended` only from `workflow_defaults`: map
`width` and `height` into `recommended.resolution`, `steps` unchanged,
`guidance_scale` to `recommended.guidance`, `sampler_name` to
`recommended.sampler`, and `scheduler` unchanged. Use the same `capabilities`
object for later `approve_private`. Never substitute Profile or repository
defaults.

Display one preparation proposal containing the source and workflow hash
prefixes, topology, owned output, endpoint, all component identities, all nine
workflow defaults, requested prompt overrides, limitations, both exact
confirmations, and the statement that no model, node, or runtime download will
occur. Then stop and wait for a later user message. A natural-language
approval permits `local_gpu_register_workflow` with the stored registration
confirmation and then `local_gpu_set_model_trust` with `action:
approve_private`, the registered workflow ID, the same component identities,
the same `capabilities` object, and the stored trust confirmation.

Registration and trust approval are sequential. If registration succeeds and
trust approval fails, report the immutable copy as an inert registration and
stop. Do not delete it, weaken identity, repeat approval, recommend a route, or
start a run.

After successful private trust, call `local_gpu_recommend_models` for the exact
imported route. Display one execution route containing the endpoint,
registered workflow, model identity, positive and negative prompts, width,
height, seed, steps, guidance, sampler, scheduler, and every field that differs
from `workflow_defaults`. State `max_rounds: 1`, `upscale_policy: off`, no
automatic retry, no model switch, no CPU fallback, no workflow fallback, and
no download. Only fields explicitly overridden by the user may differ from the
inspected defaults. A changed or expired route must be displayed again. Then
stop and wait for a later user message.

After approval, call `local_gpu_start_run`, immediately call
`local_gpu_get_run`, construct the existing complete frozen generation plan,
and call `local_gpu_generate_round` once with `action: initial`. A backend
failure remains attached to the recoverable run ID and never triggers an
automatic retry or fallback. On success, return the original image, actual
workflow/model/parameter summary, durable `run_id`, and evidence location
labeled `generated / unreviewed`. Review and finalization are optional follow-up
work; they do not block the first result.
```

Keep the general Adaptive Brief and advanced revision sections after this golden path.

- [ ] **Step 7: Run Skill and route tests**

```shell
python -m unittest tests.test_skill_contract tests.test_mcp_server -v
```

Expected: PASS.

- [ ] **Step 8: Commit the Agent contract**

```shell
git add scripts/local_gpu_imagegen/model_catalog.py skills/local-gpu-imagegen/SKILL.md tests/test_skill_contract.py tests/test_mcp_server.py docs/superpowers/specs/2026-07-27-codex-first-workflow-runner-design.md docs/superpowers/plans/2026-07-27-codex-first-workflow-runner.md
git commit -m "docs: define Codex-first workflow runner"
```

### Task 4: Lead Public Documentation With The Bounded Codex Offer

**Files:**
- Modify: `tests/test_public_docs.py`
- Modify: `README.md`
- Modify: `docs/quickstart.md`
- Create: `docs/alternatives.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Produces: one literal first-viewport offer, one install command, one copy-ready request, explicit prerequisites, and no implication that the live gate has run.
- Preserves: setup rollback, 17-tool reference, image-quality non-claim, retained evidence labels, and private-path exclusions.

- [ ] **Step 1: Add red public-document tests**

Add `ALTERNATIVES = ROOT / "docs" / "alternatives.md"` beside the document constants, then add:

```python
def test_codex_first_viewport_states_literal_offer_and_ready_request(self) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first_viewport = readme[:3500]
    for required in (
        "Run a supported ComfyUI workflow from Codex without modifying your setup.",
        "uvx local-gpu-imagegen setup codex --apply",
        "Run this supported ComfyUI API workflow from Codex: <path>.",
        "Use this prompt: <prompt>. Preserve every other workflow setting.",
        "Python 3.11 or 3.12",
        "already-running local ComfyUI",
        "already-installed model",
        "ordinary `txt2img` API workflow",
    ):
        with self.subTest(required=required):
            self.assertIn(required, first_viewport)
    for forbidden in ("any workflow", "arbitrary workflow", "better image quality", "production ready"):
        with self.subTest(forbidden=forbidden):
            self.assertNotIn(forbidden, first_viewport.lower())

def test_quickstart_uses_two_decisions_and_one_successful_round(self) -> None:
    quickstart = QUICKSTART.read_text(encoding="utf-8")
    _assert_ordered(quickstart, (
        "Preparation decision",
        "local_gpu_inspect_workflow",
        "local_gpu_register_workflow",
        "Execution decision",
        "local_gpu_recommend_models",
        "local_gpu_start_run",
        "local_gpu_generate_round",
        "generated / unreviewed",
    ))
    for required in (
        "one successful round", "no retry", "no model switch", "no download",
        "UI-format conversion", "custom nodes",
    ):
        self.assertIn(required, quickstart)

def test_alternatives_are_dated_source_linked_and_non_hostile(self) -> None:
    alternatives = ALTERNATIVES.read_text(encoding="utf-8")
    for required in (
        "Checked 2026-07-27",
        "https://github.com/artokun/comfyui-mcp",
        "https://github.com/joenorton/comfyui-mcp-server",
        "https://github.com/filliptm/ComfyUI_FL-MCP",
    ):
        with self.subTest(required=required):
            self.assertIn(required, alternatives)
    lowered = alternatives.lower()
    for category in ("broad control plane", "lightweight relay", "bounded codex runner"):
        self.assertIn(category, lowered)
    self.assertNotIn(" Stars", alternatives)
    self.assertNotIn("better than", alternatives.lower())
```

If `tests/test_public_docs.py` lacks `_assert_ordered`, add:

```python
def _assert_ordered(text: str, values: tuple[str, ...]) -> None:
    positions = [text.index(value) for value in values]
    if positions != sorted(positions):
        raise AssertionError(f"Values are out of order: {values}")
```

- [ ] **Step 2: Run the new documentation tests**

```shell
python -m unittest tests.test_public_docs.PublicDocumentationTests.test_codex_first_viewport_states_literal_offer_and_ready_request tests.test_public_docs.PublicDocumentationTests.test_quickstart_uses_two_decisions_and_one_successful_round tests.test_public_docs.PublicDocumentationTests.test_alternatives_are_dated_source_linked_and_non_hostile -v
```

Expected: FAIL on the missing literal offer, two-decision labels, and `docs/alternatives.md`.

- [ ] **Step 3: Replace the README first viewport**

Make the first section begin with:

````markdown
# Local GPU Imagegen

Run a supported ComfyUI workflow from Codex without modifying your setup.

```shell
uvx local-gpu-imagegen setup codex --apply
```

Ask Codex:

```text
Run this supported ComfyUI API workflow from Codex: <path>.
Use this prompt: <prompt>. Preserve every other workflow setting.
```

This path requires Python 3.11 or 3.12, Codex, an already-running local
ComfyUI instance, an already-installed model, and one ordinary `txt2img` API
workflow using the supported built-in topology. It does not install a backend,
download a model, convert UI-format JSON, or run custom nodes.

[Five-minute Quickstart](docs/quickstart.md) | [Alternatives](docs/alternatives.md)
````

Retain the genuine existing showcase and its evidence caveats below this block. Do not imply the new live gate has already run.

- [ ] **Step 4: Rewrite the quickstart workflow section around two decisions**

Keep verification, setup, reload, doctor, rollback, and troubleshooting. Replace the workflow sequence with:

````markdown
## 5. Run One Supported Workflow

Ask Codex:

```text
Run this supported ComfyUI API workflow from Codex: <path>.
Use this prompt: <prompt>. Preserve every other workflow setting.
```

### Preparation decision

Codex performs API-only discovery when needed, inspects the workflow and exact
component binding without writing state, then displays workflow hashes,
defaults, endpoint, components, requested overrides, limitations, and the two
stored confirmations. Approve only after that complete proposal is visible.
Registration writes one immutable copy and private trust binds the same
workflow, endpoint, and components. A trust failure leaves an inert
registration and stops.

### Execution decision

Codex resolves and displays one exact route, all prompt and generation values,
the fields changed from imported defaults, and a one successful round budget.
Approve only after that route is visible. The run uses no retry, no model
switch, no CPU or workflow fallback, and no download.

A successful first round returns the original image and durable run evidence
as `generated / unreviewed`. Review and finalization are optional follow-up
work; they do not block the first result.
````

Keep the unsupported boundary for UI-format conversion, custom nodes, img2img, inpaint, regional/two-stage onboarding, backend startup, and model installation.

- [ ] **Step 5: Create the dated alternatives document**

Create `docs/alternatives.md`:

```markdown
# Alternatives

Checked 2026-07-27. Project scope and activity can change; inspect each source
before choosing.

## Broad control plane

[artokun/comfyui-mcp](https://github.com/artokun/comfyui-mcp) is a better fit
when the goal is broad ComfyUI control, workflow discovery, model operations,
and generation management from an MCP client.

[ComfyUI_FL-MCP](https://github.com/filliptm/ComfyUI_FL-MCP) is a better fit
when the goal is a ComfyUI-integrated panel, live graph editing, and explicit
approval controls.

## Lightweight relay

[joenorton/comfyui-mcp-server](https://github.com/joenorton/comfyui-mcp-server)
is a better fit when a small workflow runner and asset bridge are more
important than a strongly bounded onboarding and evidence path.

## Bounded Codex runner

Local GPU Imagegen is intended for a user who already has Codex, local
ComfyUI, installed model components, and one supported API-format `txt2img`
workflow. It emphasizes an unchanged graph, exact defaults, two visible
decisions, deterministic route binding, and recoverable local evidence. It is
not a general graph editor, model manager, custom-node installer, or
image-quality enhancer.

Adjacent projects such as
[Pixelle-MCP](https://github.com/ATH-MaaS/Pixelle-MCP) and
[MeiGen-AI-Design-MCP](https://github.com/jau123/MeiGen-AI-Design-MCP) may fit
multi-provider or design-automation needs outside this bounded local path.
```

- [ ] **Step 6: Record the architecture flow**

Add a `Codex-first imported workflow` subsection to `docs/architecture.md`:

```text
read-only source preparation
-> inferred binding + exact workflow_defaults
-> preparation display and later approval
-> immutable registration + private trust
-> route recommended_settings from the same defaults
-> execution display and later approval
-> one successful unreviewed round
```

State that raw-path trust inspection uses `WorkflowOnboarding.prepare_trust_binding` and does not create the workflow state directory.

- [ ] **Step 7: Run documentation and Skill tests**

```shell
python -m unittest tests.test_public_docs tests.test_skill_contract -v
```

Expected: PASS.

- [ ] **Step 8: Commit the presentation**

```shell
git add README.md docs/quickstart.md docs/alternatives.md docs/architecture.md tests/test_public_docs.py
git commit -m "docs: lead with Codex workflow runner"
```

### Task 5: Verify The Model-Free Slice And Stop Before GPU

**Files:**
- Modify: `PROJECT_NODES.md` in the project root continuity worktree
- Modify: `NEXT_SESSION.md` in the project root continuity worktree
- No production or test file changes in this task

**Interfaces:**
- Consumes: the four reviewed commits from Tasks 1-4.
- Produces: reproducible model-free verification, exact line accounting, a clean branch, and a fresh authority boundary for the later live gate.

- [ ] **Step 1: Run the focused slice**

```shell
python -m unittest tests.test_workflow_onboarding tests.test_mcp_server tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp -v
```

Expected: PASS with no model download, backend process, or GPU use.

- [ ] **Step 2: Run the repository gate**

```shell
python -m unittest discover -s tests -v
python -m compileall scripts
python scripts/verify_mcp.py
git diff --check
```

Expected:

- all tests pass with only documented Windows permission/link skips;
- compileall succeeds;
- MCP verification returns `ok: true` and exactly 17 tools;
- `git diff --check` emits no output.

- [ ] **Step 3: Verify frozen workflow artifacts**

```shell
python -m unittest tests.test_workflow_templates.WorkflowTemplateTests.test_existing_sdxl_workflow_files_remain_byte_identical -v
```

Expected: PASS. No workflow JSON bytes or hashes changed.

- [ ] **Step 4: Enforce ownership and line budget**

```shell
git diff main@3fb45163ec61189c2d2c89a7c183612a55cb6058 --name-only
git diff --numstat main@3fb45163ec61189c2d2c89a7c183612a55cb6058 -- scripts/local_gpu_imagegen/workflow_onboarding.py scripts/mcp_server.py scripts/local_gpu_imagegen/model_catalog.py
```

Expected: the only production paths are `workflow_onboarding.py`, `mcp_server.py`, and the approved imported-route branch in `model_catalog.py`; their combined net production increase is approximately 75-150 lines. Stop for design review rather than trim tests or weaken validation if the ceiling is exceeded.

- [ ] **Step 5: Review branch history and worktree**

```shell
git status --short --branch
git log --oneline main@3fb45163ec61189c2d2c89a7c183612a55cb6058..HEAD
```

Expected: the branch contains the design, read-only correction, defaults, Agent contract, and public-document commits; no unrelated file is changed.

- [ ] **Step 6: Update continuity without claiming the live gate**

Append to root `PROJECT_NODES.md`:

- control flow: read-only prepare -> two confirmations displayed -> registration/trust -> route display -> one round;
- failure modes: unsupported graph, malformed defaults, inventory drift, inert registration after trust failure, expired route, retained backend failure;
- verification commands and exact pass/skip counts;
- exact production file and net-line counts;
- open limitation: no fresh Codex/ComfyUI prompt or image retained for this slice;
- authority boundary: no push, merge, publication, GPU, download, model switch, or remote mutation authorized.

Rewrite root `NEXT_SESSION.md` with the owned worktree, final model-free commit, results, and pending live-gate route-display approval.

- [ ] **Step 7: Stop and request the separate live-gate decision**

Do not start ComfyUI, mutate Codex client state, call generation, or reuse an earlier route token or prompt ID. Report model-free results and request a fresh route display for:

- one already-running ComfyUI endpoint;
- one already-installed model/component binding;
- one supported API workflow and prompt;
- `max_rounds: 1` and one accepted prompt ID;
- no retry, recovery, quality comparison, fallback, model switch, CPU use, or download;
- identity-bound shutdown only for a process started by the gate.

The live gate is a separate checkpoint. Two consecutive infrastructure failures stop it; a third attempt is outside this plan.
