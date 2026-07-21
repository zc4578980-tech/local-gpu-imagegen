# BYOM Discovery and Capability Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users safely discover, trust, route to, and generate with existing AUTOMATIC1111/Forge or ComfyUI models while freezing one explainable model boundary for every durable run.

**Architecture:** Backend and filesystem discovery create untrusted inventory records; a user-local atomic trust registry augments them without writing private model facts into Git. `ModelCatalog` merges repository templates, current inventory, trust, and backend readiness, while `CapabilityRouter` deterministically returns one recommendation and at most two alternatives. The run engine accepts only a current route token, freezes its exact endpoint/model/workflow/compiler identity in the manifest, and dispatches through reviewed WebUI or ComfyUI adapters without silent switching.

**Tech Stack:** Python 3.12 standard library (`unittest`, `urllib`, `json`, `hashlib`, `pathlib`, `ipaddress`, `dataclasses`, `typing`), MCP JSON-RPC over stdio, repository JSON profiles/workflows, existing PNG and durable-manifest contracts.

## Global Constraints

- Keep `diffusers` as a compatibility backend; BYOM v1 expands only `webui` (AUTOMATIC1111/Forge) and `comfyui`.
- Use standard-library-only production code and tests. Do not install packages, download models/workflows/custom nodes, or load model weights during discovery.
- Do not modify shared/global Python or `D:\AI\envs\pytorch-vla`.
- Treat loopback endpoints as local; require exact per-endpoint LAN confirmation; reject public Internet endpoints.
- Discovery defaults to `api_only`. Broader scans require a displayed, unchanged, unexpired plan and exact confirmation.
- Never follow symlinks, junctions, or reparse points during discovery. Treat `.ckpt` as opaque and never call `torch.load`, pickle, adjacent Python, or model tooling.
- Private trust and public-evidence eligibility are separate. `backend_binding` may be private-only; public candidates require a cryptographic SHA-256 plus source/license/redistribution metadata and still do not bypass acceptance authority.
- Execute ComfyUI only through a shipped reviewed template or a locally copied imported workflow that passes the same allowlist validator.
- Return one exact route plus at most two alternatives. Never weaken a hard requirement, silently substitute a model, or switch the model/backend in a child revision.
- Preserve existing run, review, immutable revision, idempotency, artifact validation, evidence-export, and failed-attempt retention behavior.
- Resolve a model route before compute-preset resolution. Do not implement the separately approved configurable-budget design in this plan.
- Do not make real ComfyUI, image-quality, performance, release-readiness, or arbitrary-model support claims without retained evidence.
- Do not create a remote, push, tag, release, or publish during implementation.
- Preserve the existing uncommitted `scripts/mcp_server.py` / `tests/test_mcp_server.py` subtype fix and `docs/evidence/runs/`; inspect their diff before editing and never stage unrelated hunks.

## File Map

- `scripts/local_gpu_imagegen/model_identity.py`: endpoint/model identity validation, canonical tokens, drift fields, and selected-file SHA-256.
- `scripts/local_gpu_imagegen/trust_registry.py`: OS user-state location, atomic local trust records, private/public approval, revoke, and observation evidence.
- `scripts/local_gpu_imagegen/backends/base.py`: endpoint policy, bounded JSON HTTP client, adapter protocol, and adapter registry.
- `scripts/local_gpu_imagegen/backends/webui.py`: AUTOMATIC1111/Forge probe, inventory, loaded-model verification, and generation.
- `scripts/local_gpu_imagegen/discovery.py`: short-lived plans, exact scope confirmation, safe two-stage filesystem discovery, progress, and cancellation.
- `scripts/local_gpu_imagegen/workflow_templates.py`: ComfyUI graph allowlist, resource ceilings, bindings, normalization, and template resolution.
- `scripts/local_gpu_imagegen/backends/comfyui.py`: ComfyUI probe/discovery, prompt submission, query/cancel, polling, and bounded output retrieval.
- `scripts/local_gpu_imagegen/model_catalog.py`: merge static templates, inventory, trust, readiness, workflow availability, and drift checks.
- `scripts/local_gpu_imagegen/prompt_compilers.py`: versioned conservative-natural-language and SD1.5-tag compiler registry.
- `scripts/local_gpu_imagegen/model_router.py`: hard filters, deterministic scores, reasons, alternatives, and route tokens.
- `scripts/local_gpu_imagegen/services.py`: one testable runtime composition root used by the thin MCP module.
- `workflows/comfyui/sd15-txt2img-v1.json`: reviewed built-in ComfyUI template and explicit bindings.

---

### Task 1: Model Identity and User-Local Trust

**Files:**
- Create: `scripts/local_gpu_imagegen/model_identity.py`
- Create: `scripts/local_gpu_imagegen/trust_registry.py`
- Create: `tests/test_model_identity.py`
- Create: `tests/test_trust_registry.py`

**Interfaces:**
- Consumes: existing `atomic_write_json(path: Path, value: object)`, `sha256_file(path: Path)`, `ValidationError`, `ConflictError`, and `ArtifactError`.
- Produces: `validate_discovery_record(value: object) -> dict[str, object]`, `identity_token(record: dict[str, object]) -> str`, `fingerprint_selected_file(path: Path, expected: dict[str, object]) -> dict[str, object]`, `default_state_dir(env: Mapping[str, str] | None = None) -> Path`, and `TrustRegistry(state_dir: Path)` with `list_records() -> list[dict[str, object]]`, `approve_private(record, confirmation, *, capabilities, workflow_binding=None, preference=0) -> dict[str, object]`, `approve_public_candidate(record, confirmation, *, metadata, capabilities=None, workflow_binding=None, preference=0) -> dict[str, object]`, `revoke(catalog_id, identity, confirmation) -> dict[str, object]`, and `record_observation(catalog_id, identity, operation, run_id) -> None`.
- Produces trust records keyed by stable catalog ID with `identity_token`, `identity_strength`, `scope`, `capabilities`, `workflow_binding`, `preference`, and evidence entries whose level is only `declared` or `observed`.

- [ ] **Step 1: Write failing identity and trust tests**

```python
# tests/test_model_identity.py
def test_backend_binding_is_private_only_and_token_is_canonical(self) -> None:
    record = discovery_record(identity_strength="backend_binding", sha256=None)
    validated = validate_discovery_record(record)
    self.assertEqual(identity_token(validated), identity_token(dict(reversed(list(record.items())))))
    self.assertFalse(validated["public_evidence_eligible"])

def test_selected_file_fingerprint_rejects_low_cost_drift(self) -> None:
    path = self.root / "model.safetensors"
    path.write_bytes(b"safe-test-bytes")
    expected = {"byte_size": path.stat().st_size + 1, "modified_ns": path.stat().st_mtime_ns}
    with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
        fingerprint_selected_file(path, expected)

# tests/test_trust_registry.py
def test_private_approval_requires_exact_display_confirmation_and_is_atomic(self) -> None:
    registry = TrustRegistry(self.root)
    record = discovery_record(identity_strength="backend_binding", sha256=None)
    confirmation = registry.confirmation_value("approve_private", record)
    approved = registry.approve_private(record, confirmation, capabilities={"operations": ["txt2img"]})
    self.assertEqual(approved["scope"], "private")
    self.assertNotIn("api_key", json.dumps(registry.list_records()))
    self.assertFalse((self.root / "trust.json.tmp").exists())

def test_public_candidate_requires_crypto_source_license_and_redistribution(self) -> None:
    registry = TrustRegistry(self.root)
    record = discovery_record(identity_strength="cryptographic", sha256="a" * 64)
    with self.assertRaisesRegex(ValidationError, "public_metadata_incomplete"):
        registry.approve_public_candidate(record, "wrong", metadata={})

def test_corrupt_registry_fails_closed_without_overwriting_state(self) -> None:
    (self.root / "trust.json").write_text("{", encoding="utf-8")
    with self.assertRaisesRegex(ArtifactError, "corrupt_trust_registry"):
        TrustRegistry(self.root).list_records()
    self.assertEqual((self.root / "trust.json").read_text(encoding="utf-8"), "{")

def discovery_record(*, identity_strength: str, sha256: str | None) -> dict[str, object]:
    return {
        "backend": "webui", "endpoint_identity": "endpoint:test",
        "backend_model_id": "anything-v5.safetensors", "format": ".safetensors",
        "byte_size": 15, "modified_ns": 100, "sha256": sha256,
        "identity_strength": identity_strength, "metadata": {},
    }
```

- [ ] **Step 2: Run the focused tests and verify the missing modules fail**

Run: `python -m unittest tests.test_model_identity tests.test_trust_registry -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.model_identity'`.

- [ ] **Step 3: Implement canonical identity validation and selected-file hashing**

```python
# scripts/local_gpu_imagegen/model_identity.py public contract
IDENTITY_STRENGTHS = frozenset({"cryptographic", "backend_binding"})
DISCOVERY_REQUIRED = frozenset({
    "backend", "endpoint_identity", "backend_model_id", "format", "byte_size",
    "modified_ns", "sha256", "identity_strength", "metadata",
})

def validate_discovery_record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or DISCOVERY_REQUIRED - set(value):
        raise ValidationError("invalid_model_identity", "Discovery identity is incomplete.")
    strength = value["identity_strength"]
    digest = value["sha256"]
    if strength not in IDENTITY_STRENGTHS:
        raise ValidationError("invalid_model_identity", "Identity strength is unsupported.")
    if strength == "cryptographic" and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValidationError("invalid_model_identity", "Cryptographic identity requires lowercase SHA-256.")
    if strength == "backend_binding" and digest is not None:
        raise ValidationError("invalid_model_identity", "Backend binding cannot claim a cryptographic digest.")
    result = copy.deepcopy(value)
    result["public_evidence_eligible"] = strength == "cryptographic"
    return result

def identity_token(record: dict[str, object]) -> str:
    validated = validate_discovery_record(record)
    boundary = {name: validated[name] for name in (
        "backend", "endpoint_identity", "backend_model_id", "format", "byte_size",
        "modified_ns", "sha256", "identity_strength",
    )}
    encoded = json.dumps(boundary, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "model:" + hashlib.sha256(encoded).hexdigest()

def fingerprint_selected_file(path: Path, expected: dict[str, object]) -> dict[str, object]:
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or _link_like(path):
        raise ValidationError("unsafe_model_path", "Selected model must be a regular non-link file.")
    if before.st_size != expected.get("byte_size") or before.st_mtime_ns != expected.get("modified_ns"):
        raise ConflictError("model_identity_drifted", "Selected model changed after indexing.")
    digest = sha256_file(path)
    after = os.stat(path, follow_symlinks=False)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
    ):
        raise ConflictError("model_identity_drifted", "Selected model changed while hashing.")
    return {"sha256": digest, "byte_size": before.st_size, "modified_ns": before.st_mtime_ns}
```

Implement `_link_like` with `Path.is_symlink()`, optional `Path.is_junction()`, and `FILE_ATTRIBUTE_REPARSE_POINT`; do not open model contents beyond the streaming SHA-256 read.

- [ ] **Step 4: Implement the atomic trust registry and OS state directory**

```python
# scripts/local_gpu_imagegen/trust_registry.py public contract
def default_state_dir(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    if values.get("LOCAL_GPU_IMAGEGEN_STATE_DIR"):
        return Path(values["LOCAL_GPU_IMAGEGEN_STATE_DIR"]).expanduser()
    if os.name == "nt":
        return Path(values.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "local-gpu-imagegen"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "local-gpu-imagegen"
    return Path(values.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "local-gpu-imagegen"

class TrustRegistry:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "trust.json"

    def confirmation_value(self, action: str, record: dict[str, object]) -> str:
        return f"{action}:{identity_token(record)}"

    def approve_private(self, record: dict[str, object], confirmation: str, *, capabilities: dict[str, object], workflow_binding: dict[str, object] | None = None, preference: int = 0) -> dict[str, object]:
        return self._approve("private", record, confirmation, capabilities, workflow_binding, preference, None)

    def approve_public_candidate(self, record: dict[str, object], confirmation: str, *, metadata: dict[str, object], capabilities: dict[str, object] | None = None, workflow_binding: dict[str, object] | None = None, preference: int = 0) -> dict[str, object]:
        required = {"source", "license_id", "license_url", "output_redistribution_status"}
        if record.get("identity_strength") != "cryptographic" or any(not metadata.get(name) for name in required):
            raise ValidationError("public_metadata_incomplete", "Public candidates require cryptographic identity and complete source/license metadata.")
        return self._approve("public_candidate", record, confirmation, capabilities or {}, workflow_binding, preference, metadata)

    def revoke(self, catalog_id: str, identity: str, confirmation: str) -> dict[str, object]:
        expected = f"revoke:{catalog_id}:{identity}"
        if confirmation != expected:
            raise ValidationError("trust_confirmation_mismatch", "Trust confirmation does not match the displayed boundary.")
        document = self._read()
        document["records"] = [entry for entry in document["records"] if not (entry["catalog_id"] == catalog_id and entry["identity_token"] == identity)]
        self._write(document)
        return {"catalog_id": catalog_id, "identity_token": identity, "revoked": True}

    def record_observation(self, catalog_id: str, identity: str, operation: str, run_id: str) -> None:
        document = self._read()
        record = next((item for item in document["records"] if item["catalog_id"] == catalog_id and item["identity_token"] == identity), None)
        if record is None:
            raise StateError("trust_record_not_found", "Cannot record evidence for an untrusted identity.")
        evidence = {"level": "observed", "operation": operation, "run_id": run_id}
        if evidence not in record["evidence"]:
            record["evidence"].append(evidence)
            self._write(document)
```

`_approve` must reject credential-shaped keys (`api_key`, `token`, `password`, `secret`, `authorization`), derive `catalog_id` as `local:<first 24 hex chars of identity token>`, require the exact action confirmation, store the same-name-replacement limitation for `backend_binding`, and call `atomic_write_json` only after the complete document validates. `_read` must accept only an object with integer `schema_version: 1` and an array-valued `records` field, and fail closed on corrupt JSON.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_model_identity tests.test_trust_registry -v`

Expected: PASS; no file outside each test's temporary state directory is created.

- [ ] **Step 6: Commit the identity/trust boundary**

```powershell
git add scripts/local_gpu_imagegen/model_identity.py scripts/local_gpu_imagegen/trust_registry.py tests/test_model_identity.py tests/test_trust_registry.py
git commit -m "feat: add local model identity and trust registry"
```

### Task 2: Backend Protocol and WebUI Adapter

**Files:**
- Create: `scripts/local_gpu_imagegen/backends/__init__.py`
- Create: `scripts/local_gpu_imagegen/backends/base.py`
- Create: `scripts/local_gpu_imagegen/backends/webui.py`
- Create: `tests/fake_backend_server.py`
- Create: `tests/test_backend_base.py`
- Create: `tests/test_webui_adapter.py`
- Modify: `scripts/generate_image.py`
- Modify: `tests/test_generate_image.py`

**Interfaces:**
- Consumes: Task 1 `validate_discovery_record` and `identity_token`; existing direct Diffusers functions remain callable.
- Produces: `BackendAdapter` protocol with `probe()`, `discover()`, `generate(request)`, and `cancel_or_query(job_id, cancel=False)`; `EndpointPolicy.resolve(url, lan_confirmation=None) -> dict[str, object]`; `BoundedJsonClient`; `BackendRegistry(adapters, compatibility_runners=None)` with `get`, `probe_all`, `discover_all`, and `generate`; and `WebUIAdapter`.
- `generate(request)` consumes `backend`, `endpoint`, `model`, `mode`, prompts, dimensions, steps, guidance, sampler, seed, optional source/mask/strength, and output path; it returns the normalized backend-result fields plus exact identity fields.

- [ ] **Step 1: Write failing endpoint-policy and WebUI adapter tests**

```python
def test_endpoint_policy_accepts_loopback_rejects_public_and_confirms_lan(self) -> None:
    self.assertEqual(EndpointPolicy.resolve("http://127.0.0.1:7860")["class"], "loopback")
    with self.assertRaisesRegex(ValidationError, "public_endpoint_rejected"):
        EndpointPolicy.resolve("https://8.8.8.8:7860")
    with self.assertRaisesRegex(ValidationError, "lan_confirmation_required"):
        EndpointPolicy.resolve("http://192.168.1.20:7860")
    confirmed = EndpointPolicy.resolve(
        "http://192.168.1.20:7860",
        lan_confirmation="transmit:http://192.168.1.20:7860",
    )
    self.assertEqual(confirmed["class"], "lan")

def test_webui_discovers_full_hash_without_switching_models(self) -> None:
    adapter = WebUIAdapter(self.server.url)
    records = adapter.discover()
    self.assertEqual(records[0]["sha256"], "a" * 64)
    self.assertEqual(records[0]["identity_strength"], "cryptographic")
    self.assertEqual(self.server.posts, [])

def test_webui_generation_rejects_missing_confirmed_checkpoint_before_post(self) -> None:
    adapter = WebUIAdapter(self.server.url)
    with self.assertRaisesRegex(ConflictError, "backend_model_mismatch"):
        adapter.generate(generation_request(self.output, model_id="missing.safetensors"))
    self.assertEqual(self.server.posts, [])

def generation_request(output: Path, *, model_id: str) -> dict[str, object]:
    record = {
        "backend": "webui", "endpoint_identity": "endpoint:test",
        "backend_model_id": model_id, "format": ".safetensors", "byte_size": None,
        "modified_ns": None, "sha256": None, "identity_strength": "backend_binding",
        "metadata": {},
    }
    record["identity_token"] = identity_token(record)
    return {
        "backend": "webui", "model": record, "mode": "txt2img",
        "positive_prompt": "calm sea", "negative_prompt": "artifacts",
        "width": 512, "height": 512, "steps": 20, "guidance_scale": 7.0,
        "sampler": "Euler a", "seed": 42, "source_path": None,
        "mask_path": None, "strength": None, "output_path": str(output),
    }
```

- [ ] **Step 2: Run tests and verify they fail on missing backend package**

Run: `python -m unittest tests.test_backend_base tests.test_webui_adapter -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.backends'`.

- [ ] **Step 3: Implement the protocol, endpoint boundary, and bounded HTTP client**

```python
# scripts/local_gpu_imagegen/backends/base.py
class BackendAdapter(Protocol):
    backend_id: str
    endpoint_identity: str
    def probe(self) -> dict[str, object]:
        raise NotImplementedError
    def discover(self) -> list[dict[str, object]]:
        raise NotImplementedError
    def generate(self, request: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError
    def cancel_or_query(self, job_id: str, *, cancel: bool = False) -> dict[str, object]:
        raise NotImplementedError

class EndpointPolicy:
    @staticmethod
    def resolve(url: str, lan_confirmation: str | None = None) -> dict[str, object]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "http" or parsed.username or parsed.password or not parsed.hostname:
            raise ValidationError("invalid_backend_endpoint", "Backend endpoint must be credential-free HTTP.")
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address("127.0.0.1" if host == "localhost" else host)
        except ValueError as error:
            raise ValidationError("invalid_backend_endpoint", "Backend host must be localhost or an IP literal in v1.") from error
        canonical = f"http://{host}:{parsed.port or 80}"
        if address.is_loopback:
            endpoint_class = "loopback"
        elif address.is_private and not address.is_multicast and not address.is_unspecified:
            if lan_confirmation != f"transmit:{canonical}":
                raise ValidationError("lan_confirmation_required", "LAN use requires exact transmission confirmation.", {"confirmation": f"transmit:{canonical}"})
            endpoint_class = "lan"
        else:
            raise ValidationError("public_endpoint_rejected", "Public Internet generation endpoints are unsupported in v1.")
        return {"base_url": canonical, "class": endpoint_class, "endpoint_identity": "endpoint:" + hashlib.sha256(canonical.encode()).hexdigest()}

class BoundedJsonClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0, max_bytes: int = 8 * 1024 * 1024) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_bytes = max_bytes

    def get_json(self, path: str) -> object:
        return json.loads(self._request(path, None, self.max_bytes).decode("utf-8"))

    def post_json(self, path: str, value: object) -> object:
        body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return json.loads(self._request(path, body, self.max_bytes).decode("utf-8"))

    def get_bytes(self, path: str, *, max_bytes: int) -> bytes:
        return self._request(path, None, max_bytes)

    def _request(self, path: str, body: bytes | None, limit: int) -> bytes:
        if not path.startswith("/") or urllib.parse.urlsplit(path).netloc:
            raise ValidationError("invalid_backend_path", "Backend request path must be relative to the frozen origin.")
        request = urllib.request.Request(self.base_url + path, data=body, headers={"Content-Type": "application/json"} if body is not None else {}, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if urllib.parse.urlsplit(response.geturl()).netloc != urllib.parse.urlsplit(self.base_url).netloc:
                raise StateError("backend_redirect_rejected", "Backend redirected outside the frozen origin.")
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ArtifactError("backend_response_too_large", "Backend response exceeded its byte limit.")
        return data

class BackendRegistry:
    def __init__(self, adapters: Collection[BackendAdapter], compatibility_runners: Mapping[str, Callable[[dict[str, object]], dict[str, object]]] | None = None) -> None:
        self._adapters = {adapter.backend_id: adapter for adapter in adapters}
        self._compatibility_runners = dict(compatibility_runners or {})

    def get(self, backend_id: str) -> BackendAdapter:
        try:
            return self._adapters[backend_id]
        except KeyError as error:
            raise ValidationError("unsupported_backend", "Backend adapter is not registered.", {"backend": backend_id}) from error

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        backend_id = str(request.get("backend", ""))
        if backend_id in self._adapters:
            return self._adapters[backend_id].generate(request)
        if backend_id in self._compatibility_runners:
            return self._compatibility_runners[backend_id](request)
        raise ValidationError("unsupported_backend", "Backend is not registered.", {"backend": backend_id})
```

The client must join only relative paths to the frozen base URL, reject redirects whose origin differs, read at most `max_bytes + 1`, report `backend_response_too_large`, use explicit timeouts, and translate HTTP/JSON failures to structured `StateError` values without response bodies or credentials.

- [ ] **Step 4: Implement `WebUIAdapter` and delegate the existing WebUI CLI path to it**

```python
# scripts/local_gpu_imagegen/backends/webui.py
class WebUIAdapter:
    backend_id = "webui"

    def probe(self) -> dict[str, object]:
        options = self.client.get_json("/sdapi/v1/options")
        version = self.client.get_json("/sdapi/v1/version")
        return {"backend": "webui", "implementation": "Forge" if "forge" in str(version).lower() else "AUTOMATIC1111", "version": version.get("version"), "endpoint_identity": self.endpoint_identity, "ready": True}

    def discover(self) -> list[dict[str, object]]:
        models = self.client.get_json("/sdapi/v1/sd-models")
        return [self._discovery_record(model) for model in models]

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        inventory = {item["backend_model_id"]: item for item in self.discover()}
        selected = inventory.get(request["model"]["backend_model_id"])
        if selected is None or identity_token(selected) != request["model"]["identity_token"]:
            raise ConflictError("backend_model_mismatch", "Confirmed WebUI model is not currently available.")
        payload = self._payload(request)
        payload["override_settings"] = {"sd_model_checkpoint": selected["backend_model_id"]}
        payload["override_settings_restore_afterwards"] = True
        response = self.client.post_json("/sdapi/v1/img2img" if request["mode"] != "txt2img" else "/sdapi/v1/txt2img", payload)
        return self._retain_result(response, request, selected)

    def cancel_or_query(self, job_id: str, *, cancel: bool = False) -> dict[str, object]:
        return {"job_id": job_id, "state": "unsupported", "cancel_supported": False}
```

In `generate_image.py`, keep `generate_with_diffusers` unchanged and make `generate_with_webui(args)` construct the adapter, pass an exact discovered identity, and return its result. Preserve the current CLI flags and direct MCP compatibility behavior.

- [ ] **Step 5: Run adapter and legacy generation tests**

Run: `python -m unittest tests.test_backend_base tests.test_webui_adapter tests.test_generate_image -v`

Expected: PASS, including txt2img/img2img/inpaint payload parity, invalid base64/output bounds, timeout handling, model mismatch before POST, and unchanged Diffusers-local-only behavior.

- [ ] **Step 6: Commit the WebUI adapter extraction**

```powershell
git add scripts/local_gpu_imagegen/backends scripts/generate_image.py tests/fake_backend_server.py tests/test_backend_base.py tests/test_webui_adapter.py tests/test_generate_image.py
git commit -m "refactor: isolate local image backend adapters"
```

### Task 3: Authorized Two-Stage Discovery

**Files:**
- Create: `scripts/local_gpu_imagegen/discovery.py`
- Create: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `BackendRegistry.get(backend_id)`, Task 1 identity functions, and Task 2 endpoint policies.
- Produces: `DiscoveryService(adapters, clock=time.time, ttl_seconds=300)`, `plan(request) -> dict[str, object]`, `execute(plan_id, confirmation, *, cancel=None, progress=None) -> dict[str, object]`, and `inventory() -> list[dict[str, object]]`.
- Plan modes are exactly `api_only`, `selected_folders`, `common_locations`, and `full_drive`; execution confirmation is `scan:<plan_id>:<scope_hash>`.
- Every plan has stage `index` or `fingerprint`. A consumed index plan cannot be reused; selected candidate IDs enter a new displayed fingerprint plan and therefore a new scope hash/confirmation.

- [ ] **Step 1: Write failing discovery-plan and scanner tests**

```python
def test_plan_is_bounded_hashed_and_must_be_confirmed_unchanged(self) -> None:
    plan = self.service.plan({"mode": "selected_folders", "roots": [str(self.models)]})
    self.assertEqual(plan["confirmation"], f"scan:{plan['plan_id']}:{plan['scope_hash']}")
    with self.assertRaisesRegex(ValidationError, "discovery_confirmation_mismatch"):
        self.service.execute(plan["plan_id"], "scan:other")

def test_stage_one_never_hashes_weights_or_follows_links(self) -> None:
    model = self.models / "anime.safetensors"
    model.write_bytes(safetensors_header({"modelspec.title": "Anime"}) + b"weights")
    linked = self.models / "linked"
    create_link_or_skip(self, linked, self.outside)
    with patch("local_gpu_imagegen.discovery.sha256_file", side_effect=AssertionError("stage one hashed")):
        result = self.execute_selected_folder()
    self.assertEqual([item["filename"] for item in result["candidates"]], ["anime.safetensors"])

def test_cancel_retains_incomplete_untrusted_inventory_without_trust(self) -> None:
    plan = self.service.plan({"mode": "selected_folders", "stage": "index", "roots": [str(self.models)]})
    result = self.service.execute(plan["plan_id"], plan["confirmation"], cancel=lambda: True)
    self.assertTrue(result["incomplete"])
    self.assertTrue(all(item["trusted"] is False for item in result["candidates"]))

def test_stage_two_hashes_only_exact_selected_candidate(self) -> None:
    indexed = self.execute_selected_folder()
    selected = indexed["candidates"][0]["candidate_id"]
    fingerprint_plan = self.service.plan({
        "mode": "selected_folders", "stage": "fingerprint",
        "roots": [str(self.models)], "selected_candidates": [selected],
    })
    hashed = self.service.execute(fingerprint_plan["plan_id"], fingerprint_plan["confirmation"])
    self.assertEqual(hashed["candidates"][0]["identity_strength"], "cryptographic")

def safetensors_header(metadata: dict[str, str]) -> bytes:
    encoded = json.dumps({"__metadata__": metadata}, separators=(",", ":")).encode("utf-8")
    return len(encoded).to_bytes(8, "little") + encoded

def create_link_or_skip(test: unittest.TestCase, link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        test.skipTest(f"link privilege unavailable: {error}")
```

Use this test helper so every execution consumes a fresh plan exactly once:

```python
def execute_selected_folder(self) -> dict[str, object]:
    plan = self.service.plan({
        "mode": "selected_folders", "stage": "index", "roots": [str(self.models)],
    })
    self.plan_id = str(plan["plan_id"])
    self.confirmation = str(plan["confirmation"])
    return self.service.execute(self.plan_id, self.confirmation)
```

- [ ] **Step 2: Run the test and verify the service is absent**

Run: `python -m unittest tests.test_discovery -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.discovery'`.

- [ ] **Step 3: Implement immutable short-lived plans and API discovery**

```python
DISCOVERY_MODES = frozenset({"api_only", "selected_folders", "common_locations", "full_drive"})
MODEL_EXTENSIONS = (".safetensors", ".ckpt")
DEFAULT_EXCLUSIONS = ("$Recycle.Bin", "System Volume Information", "Windows", "node_modules", ".git", ".venv", "venv", "site-packages")

class DiscoveryService:
    def plan(self, request: dict[str, object]) -> dict[str, object]:
        normalized = self._normalize_plan_request(request)
        scope_hash = canonical_hash(normalized)
        plan_id = secrets.token_hex(12)
        value = {**normalized, "plan_id": plan_id, "scope_hash": scope_hash, "expires_at": self.clock() + self.ttl_seconds, "confirmation": f"scan:{plan_id}:{scope_hash}"}
        self._plans[plan_id] = copy.deepcopy(value)
        return copy.deepcopy(value)

    def execute(self, plan_id: str, confirmation: str, *, cancel: Callable[[], bool] | None = None, progress: Callable[[dict[str, int]], None] | None = None) -> dict[str, object]:
        plan = self._current_plan(plan_id, confirmation)
        if plan["mode"] == "api_only":
            candidates, incomplete = self._api_candidates(plan), False
        elif plan["stage"] == "index":
            candidates, incomplete = self._filesystem_candidates(plan, cancel, progress)
        else:
            candidates, incomplete = self._fingerprint_selected(plan), False
        del self._plans[plan_id]
        self._inventory = merge_inventory(self._inventory, candidates)
        return {"plan_id": plan_id, "scope_hash": plan["scope_hash"], "incomplete": incomplete, "candidates": copy.deepcopy(candidates), "trusted": False}
```

Plan normalization must display exact stage, adapter IDs/endpoints or resolved roots, selected candidate IDs for fingerprinting, extensions, exclusions, scan mode, network-root status, and cost warning. Recompute the scope hash at execution, reject expiry/reuse/change, and require separate exact root confirmation for a network drive. `common_locations` must derive and display conventional A1111/Forge/ComfyUI roots without scanning until execute. A fingerprint plan must resolve every candidate ID from the retained incomplete-or-complete index inventory and must reject IDs outside its unchanged roots.

- [ ] **Step 4: Implement safe stage-one metadata and selected stage-two hashing**

```python
def index_candidate(path: Path, root: Path) -> dict[str, object]:
    file_stat = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(file_stat.st_mode) or link_like(path):
        raise ValidationError("unsafe_discovery_entry", "Discovery candidate must be a regular non-link file.")
    metadata = read_safetensors_metadata(path) if path.suffix.lower() == ".safetensors" else {}
    sidecar = read_bounded_sidecar(path.with_suffix(".json"), 1024 * 1024)
    relative = path.relative_to(root)
    boundary = {"resolved_root": str(root), "relative_path": str(relative), "byte_size": file_stat.st_size, "modified_ns": file_stat.st_mtime_ns}
    return {**boundary, "candidate_id": "candidate:" + canonical_hash(boundary), "filename": path.name, "format": path.suffix.lower(), "metadata": {**metadata, **sidecar}, "sha256": None, "identity_strength": None, "trusted": False}

def read_safetensors_metadata(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        header_size = int.from_bytes(stream.read(8), "little")
        if not 2 <= header_size <= 16 * 1024 * 1024:
            return {}
        document = json.loads(stream.read(header_size).decode("utf-8"))
    metadata = document.get("__metadata__", {}) if isinstance(document, dict) else {}
    return metadata if isinstance(metadata, dict) else {}
```

Walk each directory with `os.scandir`, never recurse into link-like/reparse entries, resolve and re-check every entry remains under its separately selected root, skip defaults, report visited directory/file counts, and stop promptly on cancellation. `.ckpt` metadata is always `{}`. Convert fingerprint-stage candidates to full `cryptographic` discovery records and call `fingerprint_selected_file` only for IDs frozen in that plan's `selected_candidates`.

- [ ] **Step 5: Run discovery tests**

Run: `python -m unittest tests.test_discovery -v`

Expected: PASS; privilege-dependent symlink/junction cases may skip only when the OS refuses link creation.

- [ ] **Step 6: Commit bounded discovery**

```powershell
git add scripts/local_gpu_imagegen/discovery.py tests/test_discovery.py
git commit -m "feat: add confirmed local model discovery"
```

### Task 4: Reviewed ComfyUI Workflow Templates

**Files:**
- Create: `scripts/local_gpu_imagegen/workflow_templates.py`
- Create: `workflows/comfyui/sd15-txt2img-v1.json`
- Create: `tests/test_workflow_templates.py`

**Interfaces:**
- Consumes: `ValidationError`, `ArtifactError`, and atomic state writes from Task 1.
- Produces: `WorkflowTemplateRegistry(repository_root: Path, state_dir: Path)`, `validate_imported_workflow(graph, binding, available_models) -> dict[str, object]`, `register_import(path, binding, available_models) -> dict[str, object]`, and `resolve(template_id, model_id, operation, parameters) -> dict[str, object]`.
- Returned workflow values contain `template_id`, `template_version`, `workflow_sha256`, `operation`, `model_family`, `output_node`, and a rendered graph; no arbitrary path or unbound field survives normalization.

- [ ] **Step 1: Write failing allowlist, resource, binding, and copy tests**

```python
def test_shipped_template_renders_only_bound_parameters(self) -> None:
    resolved = self.registry.resolve("sd15-txt2img", "anything-v5.safetensors", "txt2img", parameters())
    self.assertEqual(resolved["template_version"], 1)
    self.assertEqual(resolved["graph"]["4"]["inputs"]["ckpt_name"], "anything-v5.safetensors")
    self.assertEqual(resolved["graph"]["3"]["inputs"]["steps"], 24)

def test_rejects_every_unsafe_fixture(self) -> None:
    unsafe = {
        "code": graph_with_node("10", "PythonScript", {"code": "print(1)"}),
        "http": graph_with_node("10", "HTTPDownload", {"url": "http://127.0.0.1/file"}),
        "write": graph_with_save_prefix("C:/outside/result"),
        "unknown": graph_with_node("10", "UnreviewedCustomNode", {}),
        "ambiguous": graph_with_node("10", "SaveImage", {"filename_prefix": "local-gpu-imagegen", "images": ["8", 0]}),
    }
    for name, graph in unsafe.items():
        source = self.state_dir / f"{name}.json"
        source.write_text(json.dumps(graph), encoding="utf-8")
        with self.subTest(name=name), self.assertRaisesRegex(ValidationError, "unsafe_comfy_workflow"):
            self.registry.register_import(source, binding(), ["anything-v5.safetensors"])

def test_import_is_normalized_copied_and_independent_of_source_after_approval(self) -> None:
    registered = self.registry.register_import(self.safe_source, binding(), ["anything-v5.safetensors"])
    copied = Path(registered["local_path"])
    self.assertTrue(copied.is_relative_to(self.state_dir))
    self.safe_source.write_text("{}", encoding="utf-8")
    self.assertEqual(self.registry.load_registered(registered["template_id"])["workflow_sha256"], registered["workflow_sha256"])

def test_tampered_registered_copy_invalidates_unseen_confirmation(self) -> None:
    registered = self.registry.register_import(self.safe_source, binding(), ["anything-v5.safetensors"])
    Path(registered["local_path"]).write_text("{}", encoding="utf-8")
    with self.assertRaisesRegex(ConflictError, "workflow_registration_drifted"):
        self.registry.load_registered(registered["template_id"])

def parameters() -> dict[str, object]:
    return {"positive_prompt": "calm sea", "negative_prompt": "artifacts", "seed": 42, "steps": 24, "guidance_scale": 5.5, "sampler": "euler", "scheduler": "normal", "width": 768, "height": 512}

def binding() -> dict[str, list[str]]:
    return {
        "model": ["4", "inputs", "ckpt_name"], "positive_prompt": ["6", "inputs", "text"],
        "negative_prompt": ["7", "inputs", "text"], "seed": ["3", "inputs", "seed"],
        "steps": ["3", "inputs", "steps"], "guidance_scale": ["3", "inputs", "cfg"],
        "sampler": ["3", "inputs", "sampler_name"], "scheduler": ["3", "inputs", "scheduler"],
        "width": ["5", "inputs", "width"], "height": ["5", "inputs", "height"],
        "output": ["9"],
    }

def graph_with_node(node_id: str, class_type: str, inputs: dict[str, object]) -> dict[str, object]:
    graph = safe_graph()
    graph[node_id] = {"class_type": class_type, "inputs": inputs}
    return graph

def graph_with_save_prefix(prefix: str) -> dict[str, object]:
    graph = safe_graph()
    graph["9"]["inputs"]["filename_prefix"] = prefix
    return graph

def safe_graph() -> dict[str, object]:
    template = json.loads((ROOT / "workflows" / "comfyui" / "sd15-txt2img-v1.json").read_text(encoding="utf-8"))
    return copy.deepcopy(template["graph"])
```

In `setUp`, write `safe_graph()` as JSON to `self.safe_source` before each import-copy assertion.

- [ ] **Step 2: Run tests and verify the registry module is missing**

Run: `python -m unittest tests.test_workflow_templates -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.workflow_templates'`.

- [ ] **Step 3: Add the reviewed SD1.5 txt2img template**

```json
{
  "schema_version": 1,
  "template_id": "sd15-txt2img",
  "template_version": 1,
  "operation": "txt2img",
  "model_families": ["sd15", "unknown"],
  "allowed_node_classes": ["CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage"],
  "output_node": "9",
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
  "graph": {
    "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "local-gpu-imagegen", "images": ["8", 0]}}
  }
}
```

- [ ] **Step 4: Implement workflow validation, rendering, and inert import registration**

```python
SAFE_NODE_CLASSES = frozenset({
    "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "KSampler",
    "VAEDecode", "VAEEncode", "VAEEncodeForInpaint", "LoadImage", "LoadImageMask", "SaveImage",
})
FORBIDDEN_TERMS = ("shell", "python", "script", "process", "download", "http", "webhook", "fetch", "execute", "command")
LIMITS = {"nodes": 64, "steps": 80, "dimension": 1536, "batch": 1, "outputs": 1}

def validate_imported_workflow(graph: object, binding: object, available_models: Collection[str]) -> dict[str, object]:
    if not isinstance(graph, dict) or not 1 <= len(graph) <= LIMITS["nodes"]:
        raise ValidationError("unsafe_comfy_workflow", "Workflow graph size is outside the reviewed limit.")
    output_nodes = []
    for node_id, node in graph.items():
        if not isinstance(node, dict) or node.get("class_type") not in SAFE_NODE_CLASSES:
            raise ValidationError("unsafe_comfy_workflow", "Workflow contains an unknown or unapproved node.", {"node_id": node_id})
        if any(term in str(node.get("class_type", "")).lower() for term in FORBIDDEN_TERMS):
            raise ValidationError("unsafe_comfy_workflow", "Workflow contains an executable or network node.")
        if node.get("class_type") == "SaveImage":
            output_nodes.append(node_id)
    if len(output_nodes) != 1:
        raise ValidationError("unsafe_comfy_workflow", "Workflow must have one unambiguous owned output.")
    normalized_binding = validate_binding(binding, graph, output_nodes[0])
    enforce_resource_limits(graph)
    enforce_model_names(graph, available_models)
    return {"graph": copy.deepcopy(graph), "binding": normalized_binding, "output_node": output_nodes[0]}
```

`validate_binding` must require model, positive/negative prompt, seed, sampler, steps, width, height, and output paths; every path must resolve to an existing scalar input. `enforce_resource_limits` must reject `batch_size > 1`, `steps > 80`, width/height outside 256..1536 or not divisible by 8, multiple output nodes, absolute paths, and `SaveImage.filename_prefix` other than `local-gpu-imagegen`. `register_import` reads at most 2 MiB, validates before writing, stores canonical JSON under `state_dir/workflows/<sha256>.json`, and never executes or imports source content.

- [ ] **Step 5: Run workflow tests**

Run: `python -m unittest tests.test_workflow_templates -v`

Expected: PASS for the shipped template and safe imported graph; all five malicious categories fail with `unsafe_comfy_workflow` before any HTTP call.

- [ ] **Step 6: Commit reviewed workflow support**

```powershell
git add scripts/local_gpu_imagegen/workflow_templates.py workflows/comfyui tests/test_workflow_templates.py
git commit -m "feat: validate reviewed comfyui workflows"
```

### Task 5: ComfyUI Adapter

**Files:**
- Create: `scripts/local_gpu_imagegen/backends/comfyui.py`
- Create: `tests/test_comfyui_adapter.py`
- Modify: `tests/fake_backend_server.py`
- Modify: `scripts/check_gpu.py`
- Modify: `tests/test_check_gpu.py`

**Interfaces:**
- Consumes: `BackendAdapter`, `BoundedJsonClient`, endpoint identity, model identity, and already-resolved Task 4 workflows.
- Produces: `ComfyUIAdapter(base_url, lan_confirmation=None, poll_interval=0.25, timeout=600, clock=time.monotonic, sleep=time.sleep)` with the same four adapter methods and normalized `workflow_job_id` results.
- `check_gpu.py` adds a `comfyui` probe report and `comfyui_ready`; it still avoids importing Torch when any HTTP backend is ready.

- [ ] **Step 1: Write failing ComfyUI lifecycle tests**

```python
def test_discovery_uses_checkpoint_loader_choices_without_mutation(self) -> None:
    records = self.adapter.discover()
    self.assertEqual([item["backend_model_id"] for item in records], ["anything-v5.safetensors"])
    self.assertEqual(self.server.posts, [])

def test_generate_submits_polls_and_retrieves_named_output(self) -> None:
    result = self.adapter.generate(comfy_request(self.output, self.resolved_workflow))
    self.assertEqual(result["backend"], "comfyui")
    self.assertEqual(result["workflow_job_id"], "prompt-1")
    self.assertEqual(Path(result["path"]).read_bytes(), PNG_BYTES)
    self.assertEqual(self.server.paths, ["/prompt", "/history/prompt-1", "/view?filename=result.png&subfolder=&type=output"])

def test_timeout_queries_known_job_before_structured_failure(self) -> None:
    adapter = ComfyUIAdapter(self.server.url, timeout=0, clock=FakeClock([0, 1]))
    with self.assertRaisesRegex(StateError, "comfyui_job_timed_out") as raised:
        adapter.generate(comfy_request(self.output, self.resolved_workflow))
    self.assertEqual(raised.exception.details["job_id"], "prompt-1")
    self.assertIn("/history/prompt-1", self.server.paths)

def test_malformed_or_oversized_output_never_becomes_success(self) -> None:
    self.server.output = b"x" * (32 * 1024 * 1024 + 1)
    with self.assertRaisesRegex(ArtifactError, "backend_response_too_large"):
        self.adapter.generate(comfy_request(self.output, self.resolved_workflow))

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")

class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)
    def __call__(self) -> float:
        return next(self.values)

def comfy_request(output: Path, workflow: dict[str, object]) -> dict[str, object]:
    return {
        "backend": "comfyui", "idempotency_key": "test-attempt", "mode": "txt2img",
        "model": {"backend_model_id": "anything-v5.safetensors", "identity_token": "model:test"},
        "workflow": copy.deepcopy(workflow), "positive_prompt": "calm sea",
        "negative_prompt": "artifacts", "width": 512, "height": 512,
        "steps": 20, "guidance_scale": 7.0, "sampler": "euler",
        "scheduler": "normal", "seed": 42, "output_path": str(output),
        "prompt_compiler_id": "sd15-tags-v1", "prompt_compiler_version": 1,
    }
```

- [ ] **Step 2: Run focused tests and verify ComfyUI support is absent**

Run: `python -m unittest tests.test_comfyui_adapter tests.test_check_gpu -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.backends.comfyui'`.

- [ ] **Step 3: Implement probe, discovery, submit, poll, query/cancel, and output retrieval**

```python
class ComfyUIAdapter:
    backend_id = "comfyui"

    def probe(self) -> dict[str, object]:
        stats = self.client.get_json("/system_stats")
        return {"backend": "comfyui", "implementation": "ComfyUI", "version": nested_version(stats), "endpoint_identity": self.endpoint_identity, "ready": True}

    def discover(self) -> list[dict[str, object]]:
        info = self.client.get_json("/object_info/CheckpointLoaderSimple")
        names = checkpoint_choices(info)
        return [backend_binding_record("comfyui", self.endpoint_identity, name) for name in sorted(names)]

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        verify_resolved_workflow(request["workflow"], request["model"])
        submitted = self.client.post_json("/prompt", {"prompt": request["workflow"]["graph"], "client_id": request["idempotency_key"]})
        job_id = require_job_id(submitted)
        history = self._poll(job_id)
        output = owned_output(history, job_id, request["workflow"]["output_node"])
        image = self.client.get_bytes(view_path(output), max_bytes=32 * 1024 * 1024)
        Path(request["output_path"]).write_bytes(image)
        return normalized_result(request, job_id, output)

    def cancel_or_query(self, job_id: str, *, cancel: bool = False) -> dict[str, object]:
        state = self._query(job_id)
        if cancel and state["state"] == "queued":
            self.client.post_json("/queue", {"delete": [job_id]})
            return {**state, "state": "cancel_requested"}
        if cancel and state["state"] == "running":
            return {**state, "state": "running", "cancel_supported": False}
        return state
```

Validate every response shape, keep one known `prompt_id`, distinguish rejected/disappeared/canceled/timeout/invalid-output codes, never retry submission after an unknown timeout, and query the known job before reporting timeout. Delete only an exact queued job ID; do not call ComfyUI's global `/interrupt` for a running job because it could cancel another user's work. Retrieval must use only the returned filename/subfolder/type triple against the frozen origin and one output node.

- [ ] **Step 4: Extend readiness without introducing a real-ComfyUI claim**

```python
def check_comfyui() -> dict[str, object]:
    base_url = os.environ.get("LOCAL_GPU_IMAGEGEN_COMFYUI_URL", "http://127.0.0.1:8188")
    try:
        adapter = ComfyUIAdapter(base_url)
        return {**adapter.probe(), "available": True, "api_error": None}
    except AssetEngineError as error:
        return {"url": base_url, "available": False, "api_error": error.code}

# main readiness calculation
report["comfyui"] = check_comfyui()
report["comfyui_ready"] = bool(report["comfyui"]["available"])
report["ready"] = report["webui_ready"] or report["comfyui_ready"] or report["diffusers_ready"]
```

- [ ] **Step 5: Run ComfyUI and readiness tests**

Run: `python -m unittest tests.test_comfyui_adapter tests.test_check_gpu -v`

Expected: PASS; fake-server tests cover successful generation, rejection, queue/running query, cancellation, disappearance, timeout, malformed JSON, wrong output node, traversal-shaped output metadata, and size limits.

- [ ] **Step 6: Commit ComfyUI adapter support**

```powershell
git add scripts/local_gpu_imagegen/backends/comfyui.py scripts/check_gpu.py tests/fake_backend_server.py tests/test_comfyui_adapter.py tests/test_check_gpu.py
git commit -m "feat: add bounded comfyui adapter"
```

### Task 6: Merged Catalog, Prompt Compilers, and Deterministic Router

**Files:**
- Create: `scripts/local_gpu_imagegen/model_catalog.py`
- Create: `scripts/local_gpu_imagegen/prompt_compilers.py`
- Create: `scripts/local_gpu_imagegen/model_router.py`
- Create: `tests/test_model_catalog.py`
- Create: `tests/test_prompt_compilers.py`
- Create: `tests/test_model_router.py`
- Modify: `scripts/local_gpu_imagegen/profile_registry.py`
- Modify: `profiles/models/anything-v5.json`
- Modify: `profiles/models/sd-turbo.json`
- Modify: `profiles/schemas/model.schema.json`
- Modify: `tests/test_profile_registry.py`

**Interfaces:**
- Consumes: repository model JSON, discovery inventory, trust records, adapter probes, workflow registry, and identity drift checks.
- Produces: `ModelCatalog(repository_root, inventory_provider, trust_registry, readiness_provider, workflows)`, `list_models(scope) -> list[dict[str, object]]`, `resolve(model_id, scope) -> dict[str, object]`, `verify_locked_route(route) -> dict[str, object]`, and `record_observation(model_id, identity_token, operation, run_id) -> None`.
- Produces: `PromptCompilerRegistry.compile(compiler_id, positive, negative) -> dict[str, str]` with IDs `natural-v1` and `sd15-tags-v1`.
- Produces: `CapabilityRouter(catalog, compilers, clock=time.time, ttl_seconds=300).recommend(requirements) -> dict[str, object]` and `confirm(route_token, model_id) -> dict[str, object]`; issued routes are kept in a process-local five-minute confirmation cache and revalidated against the current catalog at confirmation.

- [ ] **Step 1: Write failing catalog/compiler/router tests**

```python
def test_catalog_separates_private_and_public_candidate_scope(self) -> None:
    private = self.catalog.list_models("private")
    public = self.catalog.list_models("public_evidence")
    self.assertIn("local:backend-bound", ids(private))
    self.assertNotIn("local:backend-bound", ids(public))

def test_catalog_detects_drift_before_route_use(self) -> None:
    route = locked_route(self.crypto_model)
    self.inventory[0]["modified_ns"] += 1
    with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
        self.catalog.verify_locked_route(route)

def test_unknown_family_uses_conservative_natural_language(self) -> None:
    compiled = self.compilers.compile("natural-v1", "A calm sea", "text artifacts")
    self.assertEqual(compiled, {"compiler_id": "natural-v1", "compiler_version": 1, "positive_prompt": "A calm sea", "negative_prompt": "text artifacts"})

def test_router_hard_filters_then_returns_stable_three_maximum(self) -> None:
    result = self.router.recommend(requirements(operation="inpaint", width=1024, height=1024))
    self.assertLessEqual(len(result["routes"]), 3)
    self.assertEqual(result["routes"][0]["model_id"], "model-benchmarked")
    self.assertEqual([route["evidence_level"] for route in result["routes"]], ["benchmarked", "observed", "declared"])

def test_router_returns_no_route_instead_of_weakening_hard_requirement(self) -> None:
    result = self.router.recommend(requirements(operation="inpaint", authorization_scope="public_evidence", required_vram_gb=48))
    self.assertEqual(result["routes"], [])
    self.assertEqual(result["reason"], "no_eligible_model")

def ids(records: list[dict[str, object]]) -> set[str]:
    return {str(record["id"]) for record in records}

def requirements(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "authorization_scope": "private", "operation": "txt2img",
        "profile": "standalone-illustration", "style": "anime",
        "width": 768, "height": 512, "affinity_tags": ["anime", "illustration"],
        "required_vram_gb": 8, "preferred_model_id": None,
    }
    value.update(changes)
    return value

def locked_route(model: dict[str, object]) -> dict[str, object]:
    return {
        "model_id": model["id"], "authorization_scope": "private",
        "identity_token": model["identity_token"], "identity_strength": model["identity_strength"],
        "backend": model["backend"], "endpoint_identity": model["endpoint_identity"],
        "workflow_template_id": model.get("workflow_template_id"),
        "workflow_template_version": model.get("workflow_template_version"),
    }
```

Build router fixtures in `setUp` with three otherwise equal eligible models whose evidence levels are `declared`, `observed`, and `benchmarked`; add one backend-bound private model and one driftable cryptographic inventory record. This isolates each documented ordering/filter rule from unrelated score components.

- [ ] **Step 2: Run tests and verify catalog/router modules are missing**

Run: `python -m unittest tests.test_model_catalog tests.test_prompt_compilers tests.test_model_router -v`

Expected: FAIL with `ModuleNotFoundError` for `local_gpu_imagegen.model_catalog`.

- [ ] **Step 3: Move model eligibility out of `ProfileRegistry` and implement the merged catalog**

```python
class ModelCatalog:
    def list_models(self, scope: str) -> list[dict[str, object]]:
        if scope not in {"private", "public_evidence"}:
            raise ValidationError("invalid_authorization_scope", "Authorization scope must be private or public_evidence.")
        inventory = {identity_token(item): item for item in self.inventory_provider()}
        trusted = self.trust_registry.list_records()
        records = merge_repository_and_local(self._repository_models(), inventory, trusted)
        return [record for record in records if self._eligible(record, scope)]

    def resolve(self, model_id: str, scope: str) -> dict[str, object]:
        matches = [model for model in self.list_models(scope) if model["id"] == model_id]
        if len(matches) != 1:
            raise ValidationError("model_not_eligible", "Model is not currently eligible for the requested scope.", {"model_id": model_id, "scope": scope})
        return copy.deepcopy(matches[0])

    def verify_locked_route(self, route: dict[str, object]) -> dict[str, object]:
        current = self.resolve(str(route["model_id"]), str(route["authorization_scope"]))
        for field in ("identity_token", "identity_strength", "backend", "endpoint_identity", "workflow_template_id", "workflow_template_version"):
            if current.get(field) != route.get(field):
                raise ConflictError("model_identity_drifted", "Confirmed model, endpoint, or workflow changed before generation.", {"field": field})
        return current
```

Remove model loading and `validate_model_choice` from `ProfileRegistry`; it continues to own base/use-case/style composition only. Extend static model JSON/schema with exact fields `model_family`, `prompt_dialect`, `capabilities`, `affinity`, and `evidence`. Mark repository statements as `declared`; do not promote the two current private acceptance images in repository metadata.

```json
{
  "model_family": "sd15",
  "prompt_dialect": "sd15-tags-v1",
  "capabilities": {
    "operations": ["txt2img", "img2img", "inpaint"],
    "minimum_dimension": 256,
    "maximum_dimension": 1536,
    "minimum_vram_gb": 6,
    "negative_prompt": "supported"
  },
  "affinity": ["anime", "illustration", "character", "presentation-safe-area", "ui-visual-assets"],
  "evidence": {"level": "declared", "operations": ["txt2img", "img2img", "inpaint"]}
}
```

Apply that object to `anything-v5.json`. For disabled `sd-turbo.json`, use `model_family: "sd-turbo"`, `prompt_dialect: "natural-v1"`, operations `txt2img`, `img2img`, and `inpaint`, minimum VRAM 4, affinities `illustration` and `fast-draft`, and evidence level `declared`; keep its existing disabled, unapproved, no-download facts unchanged. The JSON schema requires those five fields, constrains operations to the three normalized values, dimensions to 256..1536, evidence to `declared|observed|benchmarked`, and keeps `additionalProperties: false` inside the new nested objects.

- [ ] **Step 4: Implement prompt compilers and deterministic routing**

```python
EVIDENCE_RANK = {"declared": 0, "observed": 1, "benchmarked": 2}

class PromptCompilerRegistry:
    def compile(self, compiler_id: str, positive: str, negative: str) -> dict[str, object]:
        if compiler_id == "natural-v1":
            compiled_positive = " ".join(positive.split())
            compiled_negative = " ".join(negative.split())
        elif compiler_id == "sd15-tags-v1":
            compiled_positive = ", ".join(part.strip() for part in positive.split(",") if part.strip())
            compiled_negative = ", ".join(part.strip() for part in negative.split(",") if part.strip())
        else:
            raise ValidationError("unknown_prompt_compiler", "Prompt compiler is not registered.")
        return {"compiler_id": compiler_id, "compiler_version": 1, "positive_prompt": compiled_positive, "negative_prompt": compiled_negative}

class CapabilityRouter:
    def recommend(self, requirements: dict[str, object]) -> dict[str, object]:
        normalized = normalize_requirements(requirements)
        eligible = [model for model in self.catalog.list_models(normalized["authorization_scope"]) if hard_match(model, normalized)]
        ranked = sorted((score_model(model, normalized) for model in eligible), key=lambda item: (-item["score"], -EVIDENCE_RANK[item["evidence_level"]], -int(item["user_pinned"]), item["model_id"]))
        routes = [self._issue_route(item, normalized) for item in ranked[:3]]
        return {"requirements": normalized, "routes": routes, "reason": None if routes else "no_eligible_model"}

    def _issue_route(self, scored: dict[str, object], requirements: dict[str, object]) -> dict[str, object]:
        boundary = route_boundary(scored, requirements)
        token = "route:" + canonical_hash(boundary)
        route = {**boundary, "route_token": token, "expires_at": self.clock() + self.ttl_seconds}
        self._issued[token] = copy.deepcopy(route)
        return route

    def confirm(self, route_token: str, model_id: str) -> dict[str, object]:
        route = self._issued.get(route_token)
        if route is None or route["model_id"] != model_id or route["expires_at"] < self.clock():
            raise ConflictError("route_confirmation_expired", "The displayed route changed or expired; recommend and confirm again.")
        self.catalog.verify_locked_route(route)
        del self._issued[route_token]
        return copy.deepcopy(route)
```

`hard_match` checks readiness, operation, trust scope, family/backend, dimensions/resolution class, VRAM, negative-prompt behavior, workflow availability/node classes, and cryptographic public scope. `score_model` exposes integer components for profile/style affinities, evidence, observed success, explicit preference/pin, and recommended-settings fit. `route_boundary` includes normalized requirements, limitations, score components, evidence level, identity strength/hash prefix or binding warning, endpoint, workflow/version, compiler/version, dimensions, and recommended settings. The token hashes that boundary without the moving expiry timestamp, and confirmation consumes it exactly once.

- [ ] **Step 5: Run catalog, compiler, router, and registry tests**

Run: `python -m unittest tests.test_model_catalog tests.test_prompt_compilers tests.test_model_router tests.test_profile_registry -v`

Expected: PASS; tie ordering is stable across input permutations, public scope excludes backend bindings, unknown families use `natural-v1`, and no evidence promotion occurs from filenames, marketing metadata, or trust alone.

- [ ] **Step 6: Commit routing core**

```powershell
git add scripts/local_gpu_imagegen/model_catalog.py scripts/local_gpu_imagegen/prompt_compilers.py scripts/local_gpu_imagegen/model_router.py scripts/local_gpu_imagegen/profile_registry.py profiles/models profiles/schemas/model.schema.json tests/test_model_catalog.py tests/test_prompt_compilers.py tests/test_model_router.py tests/test_profile_registry.py
git commit -m "feat: route trusted models by capability evidence"
```

### Task 7: MCP and Durable Run Integration

**Files:**
- Create: `scripts/local_gpu_imagegen/services.py`
- Create: `tests/test_runtime_services.py`
- Modify: `scripts/local_gpu_imagegen/engine.py`
- Modify: `scripts/local_gpu_imagegen/generation_plan.py`
- Modify: `scripts/local_gpu_imagegen/backend_contract.py`
- Modify: `scripts/local_gpu_imagegen/revisions.py`
- Modify: `scripts/mcp_server.py`
- Modify: `scripts/export_acceptance_evidence.py`
- Modify: `scripts/validate_acceptance_evidence.py`
- Modify: `docs/evidence/schemas/run-evidence.schema.json`
- Modify: `tests/test_asset_run_engine.py`
- Modify: `tests/test_generation_plan.py`
- Modify: `tests/test_backend_contract.py`
- Modify: `tests/test_revisions.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_export_acceptance_evidence.py`
- Modify: `tests/test_validate_acceptance_evidence.py`
- Modify: `tests/test_anime_vertical_slice.py`
- Modify: `tests/test_profile_acceptance_matrix.py`

**Interfaces:**
- Consumes: all Tasks 1-6 plus existing `RunStore`, preview, review, revision, mask, postprocess, and structured MCP error contracts.
- Produces: `RuntimeServices` with discovery, trust, catalog, router, workflow, backend registry, and engine; `AssetRunEngine.start_run` requires `authorization_scope`, `route_token`, and exact `model_choice`; engine `list_profiles(scope)` returns merged models.
- Replaces subprocess argument runner with `BackendRunner = Callable[[dict[str, object]], dict[str, object]]`; runtime dispatches WebUI/ComfyUI adapters directly and retains Diffusers through the current local-only CLI wrapper.
- Adds MCP tools `local_gpu_discover_models`, `local_gpu_set_model_trust`, and `local_gpu_recommend_models`; total tool count becomes exactly 15 before configurable budgets.

- [ ] **Step 1: Write failing 15-tool, dispatch, and frozen-route tests**

```python
EXPECTED_TOOLS = {
    "local_gpu_imagegen_check", "local_gpu_generate_image", "local_gpu_list_profiles",
    "local_gpu_discover_models", "local_gpu_set_model_trust", "local_gpu_recommend_models",
    "local_gpu_start_run", "local_gpu_get_run", "local_gpu_branch_run",
    "local_gpu_prepare_mask", "local_gpu_confirm_mask", "local_gpu_generate_round",
    "local_gpu_record_review", "local_gpu_finalize_run", "local_gpu_cleanup_run",
}

def test_start_run_freezes_exact_confirmed_route(self) -> None:
    started = self.engine.start_run(start_arguments(self.route))
    request = self.store.get(started["run_id"])["request"]
    self.assertEqual(request["route"]["identity_token"], self.route["identity_token"])
    self.assertEqual(request["route"]["workflow_template_version"], 1)
    self.assertEqual(request["route"]["prompt_compiler_id"], "sd15-tags-v1")

def test_generation_rechecks_route_and_never_calls_backend_after_drift(self) -> None:
    self.catalog.drift()
    with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
        self.engine.generate_round(generate_arguments(self.run_id, self.route))
    self.backend.assert_not_called()

def test_success_records_actual_identity_and_workflow_job_in_manifest(self) -> None:
    result, _preview = self.engine.generate_round(generate_arguments(self.run_id, self.route))
    retained = self.store.get(result["run_id"])["rounds"][0]["backend_result"]
    self.assertEqual(retained["model_identity_token"], self.route["identity_token"])
    self.assertEqual(retained["workflow_job_id"], "prompt-1")

def test_private_or_backend_binding_route_cannot_enter_public_evidence(self) -> None:
    routes = (
        {"authorization_scope": "private", "identity_strength": "cryptographic", "sha256": "a" * 64},
        {"authorization_scope": "public_evidence", "identity_strength": "backend_binding", "sha256": None},
    )
    for route in routes:
        manifest = read_json(self.run_dir / "manifest.json")
        manifest["request"]["route"] = route
        write_json(self.run_dir / "manifest.json", manifest)
        with self.subTest(route=route), self.assertRaisesRegex(EvidenceExportError, "public_model_evidence_forbidden"):
            self.export()

def start_arguments(route: dict[str, object]) -> dict[str, object]:
    return {
        "intent": "A calm sea at dawn.", "profile": "standalone-illustration",
        "subtype": "environment", "style": "anime",
        "constraints": {"width": 768, "height": 512, "aspect_ratio": "3:2"},
        "model_choice": route["model_id"], "backend": route["backend"],
        "authorization_scope": "private", "route_token": route["route_token"],
        "max_rounds": 2, "upscale_policy": "off",
    }

def generate_arguments(run_id: str, route: dict[str, object]) -> dict[str, object]:
    route_fields = {
        "endpoint_identity": route["endpoint_identity"],
        "model_identity_token": route["identity_token"],
        "identity_strength": route["identity_strength"],
        "workflow_template_id": route["workflow_template_id"],
        "workflow_template_version": route["workflow_template_version"],
        "prompt_compiler_id": route["prompt_compiler_id"],
        "prompt_compiler_version": route["prompt_compiler_version"],
    }
    return {
        "run_id": run_id, "idempotency_key": "round-1", "action": "initial",
        "edit_mode": "txt2img", "seed": 42, "change_summary": "Initial confirmed route.",
        "plan": {
            "profile": "standalone-illustration", "style": "anime",
            "intent": "A calm sea at dawn.", "positive_prompt": "calm sea, dawn",
            "negative_prompt": "artifacts", "constraints": {"width": 768, "height": 512, "aspect_ratio": "3:2"},
            "model_choice": route["model_id"], "backend": route["backend"],
            "parameters": {"width": 768, "height": 512, "steps": 24, "guidance_scale": 5.5},
            "max_rounds": 2, "upscale_policy": "off", **route_fields,
        },
    }
```

The engine test's `FakeCatalog.drift()` changes the current identity token; `verify_locked_route` then raises a `ConflictError` whose code is `model_identity_drifted` and message is `Confirmed model identity changed.`. Its fake backend is a `Mock` returning one complete normalized result, including the same locked route fields and `workflow_job_id: "prompt-1"`.

- [ ] **Step 2: Run integration tests and verify the old 12-tool/route contracts fail**

Run: `python -m unittest tests.test_runtime_services tests.test_mcp_server tests.test_asset_run_engine tests.test_generation_plan tests.test_backend_contract tests.test_revisions -v`

Expected: FAIL because the three BYOM tools, runtime services, `comfyui`, and frozen route fields are not yet registered.

- [ ] **Step 3: Expand generation/backend contracts and freeze route identity in idempotency**

```python
# generation_plan.py required confirmed fields
CONFIRMED_ROUTE_FIELDS = frozenset({
    "authorization_scope", "route_token", "model_choice", "backend", "endpoint_identity",
    "model_identity_token", "identity_strength", "workflow_template_id",
    "workflow_template_version", "prompt_compiler_id", "prompt_compiler_version",
})

# backend_contract.py
SUPPORTED_BACKENDS = frozenset({"webui", "diffusers", "comfyui"})
BACKEND_RESULT_REQUIRED = {
    "ok", "path", "backend", "mode", "seed", "width", "height", "model",
    "endpoint_identity", "model_identity_token", "identity_strength",
    "workflow_template_id", "workflow_template_version", "prompt_compiler_id",
    "prompt_compiler_version",
}
```

Require plan route fields to equal the confirmed request. Include the complete route and compiled prompt result in `attempt_request` before `RunStore.begin_attempt`, so endpoint/model/workflow/compiler changes conflict under the same idempotency key. For Diffusers compatibility, use explicit sentinel values (`workflow_template_id: null`, version `null`, local model identity) rather than omitting fields. Extend backend result validation to ComfyUI and require `workflow_job_id` for ComfyUI only.

- [ ] **Step 4: Compose services and integrate the route with the engine**

```python
@dataclass(slots=True)
class RuntimeServices:
    discovery: DiscoveryService
    trust: TrustRegistry
    catalog: ModelCatalog
    router: CapabilityRouter
    workflows: WorkflowTemplateRegistry
    backends: BackendRegistry
    engine: AssetRunEngine

def build_services(root: Path, output_root: Path, state_dir: Path, capabilities: Callable[[], dict[str, object]], diffusers_runner: Callable[[dict[str, object]], dict[str, object]]) -> RuntimeServices:
    workflows = WorkflowTemplateRegistry(root / "workflows" / "comfyui", state_dir)
    adapters = adapters_from_environment()
    backends = BackendRegistry(adapters, {"diffusers": diffusers_runner})
    trust = TrustRegistry(state_dir)
    discovery = DiscoveryService(backends)
    catalog = ModelCatalog(root / "profiles" / "models", discovery.inventory, trust, capabilities, workflows)
    compilers = PromptCompilerRegistry()
    router = CapabilityRouter(catalog, compilers)
    engine = AssetRunEngine(ProfileRegistry(root / "profiles"), RunStore(output_root), backends.generate, capabilities, catalog=catalog, router=router, compilers=compilers)
    return RuntimeServices(discovery, trust, catalog, router, workflows, backends, engine)
```

In `start_run`, call `router.confirm(route_token, model_choice)`, compare the returned route's profile/style/operation/dimensions with the confirmed start arguments, and store the returned route. In `generate_round`, call `catalog.verify_locked_route`, compile the plan prompts with the locked compiler, resolve the locked workflow, and invoke the selected adapter with an exact model identity/output path. Only after PNG/backend contract retention succeeds, call `catalog.record_observation`. Branching copies the parent route verbatim and rejects route fields in child overrides.

Extend evidence export/validation so `authorization_scope` must be `public_evidence`, identity strength must be `cryptographic`, the full SHA-256/model/backend must match the exact acceptance authority, and no local trust path, backend-visible private name, or LAN endpoint is exported. A `public_candidate` trust record remains insufficient without the existing acceptance-authority match. Preserve byte-for-byte exported images and original MCP result checks.

- [ ] **Step 5: Add exact MCP schemas and thin dispatch for the three BYOM tools**

```python
# schema essentials
DISCOVER_INPUT = {
    "phase": {"type": "string", "enum": ["plan", "execute"]},
    "mode": {"type": "string", "enum": ["api_only", "selected_folders", "common_locations", "full_drive"]},
    "stage": {"type": "string", "enum": ["index", "fingerprint"]},
    "backends": {"type": "array", "items": {"type": "string", "enum": ["webui", "comfyui"]}},
    "roots": {"type": "array", "items": {"type": "string"}},
    "plan_id": {"type": "string"}, "confirmation": {"type": "string"},
    "selected_candidates": {"type": "array", "items": {"type": "string"}},
}
TRUST_INPUT = {
    "action": {"type": "string", "enum": ["approve_private", "approve_public_candidate", "revoke"]},
    "identity_token": {"type": "string"}, "confirmation": {"type": "string"},
    "capabilities": {"type": "object", "additionalProperties": True},
    "public_metadata": {"type": "object", "additionalProperties": False},
    "workflow_path": {"type": "string"}, "workflow_binding": {"type": "object", "additionalProperties": True},
    "preference": {"type": "integer", "minimum": -100, "maximum": 100},
}
RECOMMEND_INPUT = {
    "authorization_scope": {"type": "string", "enum": ["private", "public_evidence"]},
    "operation": {"type": "string", "enum": ["txt2img", "img2img", "inpaint"]},
    "profile": {"type": "string"}, "style": {"type": ["string", "null"]},
    "width": {"type": "integer", "minimum": 256, "maximum": 1536},
    "height": {"type": "integer", "minimum": 256, "maximum": 1536},
    "affinity_tags": {"type": "array", "items": {"type": "string"}},
    "required_vram_gb": {"type": ["number", "null"]}, "preferred_model_id": {"type": ["string", "null"]},
}
```

`local_gpu_discover_models` calls only `services.discovery`; `local_gpu_set_model_trust` resolves the exact current inventory record and validates/copies an imported workflow before trust write; `local_gpu_recommend_models` calls only the router. Add optional `authorization_scope` to `local_gpu_list_profiles`. Require `route_token` and `authorization_scope` on `local_gpu_start_run`. Validate conditional fields per phase/action before service work and return structured errors without private absolute paths in public evidence.

- [ ] **Step 6: Run the integrated contract tests**

Run: `python -m unittest tests.test_runtime_services tests.test_mcp_server tests.test_asset_run_engine tests.test_generation_plan tests.test_backend_contract tests.test_revisions tests.test_export_acceptance_evidence tests.test_validate_acceptance_evidence tests.test_anime_vertical_slice tests.test_profile_acceptance_matrix -v`

Expected: PASS; MCP exposes exactly 15 tools, existing WebUI roots/revisions still use the same durable workflow, ComfyUI results satisfy parity, drift fails before backend invocation, and no failed/invalid backend output consumes a successful round.

- [ ] **Step 7: Inspect and stage only intended hunks, then commit integration**

```powershell
git diff -- scripts/mcp_server.py tests/test_mcp_server.py
git add scripts/local_gpu_imagegen/services.py scripts/local_gpu_imagegen/engine.py scripts/local_gpu_imagegen/generation_plan.py scripts/local_gpu_imagegen/backend_contract.py scripts/local_gpu_imagegen/revisions.py scripts/export_acceptance_evidence.py scripts/validate_acceptance_evidence.py docs/evidence/schemas/run-evidence.schema.json tests/test_runtime_services.py tests/test_asset_run_engine.py tests/test_generation_plan.py tests/test_backend_contract.py tests/test_revisions.py tests/test_export_acceptance_evidence.py tests/test_validate_acceptance_evidence.py tests/test_anime_vertical_slice.py tests/test_profile_acceptance_matrix.py
git add -p scripts/mcp_server.py tests/test_mcp_server.py
git diff --cached --check
git commit -m "feat: integrate confirmed byom routes"
```

Before committing, use `git diff HEAD -- scripts/mcp_server.py tests/test_mcp_server.py` to identify the pre-existing subtype fix and ensure it remains intact. Stage only BYOM hunks with the shown `git add -p`; leave subtype hunks unstaged when they are still intentionally separate.

### Task 8: Skill, Documentation, Regression, and Honest Verification

**Files:**
- Modify: `skills/local-gpu-imagegen/SKILL.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/troubleshooting.md`
- Modify: `SECURITY.md`
- Modify: `CHANGELOG.md`
- Modify: `scripts/verify_mcp.py`
- Modify: `tests/test_skill_contract.py`
- Modify: `tests/test_public_docs.py`
- Modify: `tests/test_verify_mcp.py`
- Modify outside worktree after verification: `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\PROJECT_NODES.md`
- Modify outside worktree after verification: `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\NEXT_SESSION.md`

**Interfaces:**
- Consumes: the exact 15-tool runtime contract and retained test evidence from Tasks 1-7.
- Produces: a Skill state machine of brief -> bounded discovery -> optional trust -> recommendation -> exact route display -> post-display confirmation -> start; opt-in ComfyUI integration instructions; honest contract-tested versus retained-real-evidence labels; current continuity nodes.

- [ ] **Step 1: Write failing documentation and Skill contract assertions**

```python
def test_skill_requires_route_resolution_before_post_display_confirmation(self) -> None:
    ordered = (
        "`local_gpu_discover_models`", "`local_gpu_list_profiles`",
        "`local_gpu_recommend_models`", "display the exact route",
        "receive post-display confirmation", "`local_gpu_start_run`",
    )
    _assert_ordered(self.text, ordered)
    for boundary in ("no silent model switch", "private", "public_evidence", "backend_binding", "cryptographic", "at most two alternatives"):
        self.assertIn(boundary, self.text)

def test_docs_distinguish_contract_tested_comfyui_from_real_evidence(self) -> None:
    public = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in ("README.md", "docs/architecture.md", "docs/troubleshooting.md"))
    self.assertIn("ComfyUI adapter: contract-tested", public)
    self.assertIn("real ComfyUI integration evidence: not retained", public)
    self.assertNotIn("supports arbitrary models", public.lower())

def test_verifier_accepts_extensible_expected_tool_set(self) -> None:
    expected = {
        "local_gpu_imagegen_check", "local_gpu_generate_image", "local_gpu_list_profiles",
        "local_gpu_discover_models", "local_gpu_set_model_trust", "local_gpu_recommend_models",
        "local_gpu_start_run", "local_gpu_get_run", "local_gpu_branch_run",
        "local_gpu_prepare_mask", "local_gpu_confirm_mask", "local_gpu_generate_round",
        "local_gpu_record_review", "local_gpu_finalize_run", "local_gpu_cleanup_run",
    }
    report = verify(expected_tools=expected)
    self.assertEqual(set(report["tools"]), expected)
```

- [ ] **Step 2: Run documentation tests and verify stale 12-tool language fails**

Run: `python -m unittest tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp -v`

Expected: FAIL on the old twelve-tool list and missing BYOM confirmation/risk boundaries.

- [ ] **Step 3: Update the conversational Skill and public documentation**

```text
Required Skill flow:
extract known brief boundaries
-> plan and display any discovery scope broader than api_only
-> receive exact scan confirmation and execute discovery
-> display exact identity/trust limitations before any trust change
-> receive exact trust confirmation when trust is needed
-> list the merged private or public_evidence catalog
-> recommend one exact route and at most two alternatives
-> display model/backend/identity/hash-prefix-or-binding-warning/workflow/compiler/dimensions/budget
-> receive a new post-display confirmation
-> start one frozen route
-> generate/review/revise without silent model switching
```

README and architecture must position the project as an Agent-native local visual-asset control plane, not a superior natural-language prompt translator. Document the four discovery levels, two-stage hashing, state directory override, private/public trust distinction, endpoint transmission warning, routing reasons, shipped `sd15-txt2img` template, rejected ComfyUI node categories, no-download/no-credential/no-silent-switch rules, and the fact that model quality still comes from the user's model. Troubleshooting must include plan expiry/change, scan cancellation, identity drift, no eligible route, LAN rejection, unsafe workflow, ComfyUI timeout/query, VRAM/model-load failure, and normalized-output failure with stable error codes.

- [ ] **Step 4: Run focused and full model-free verification once**

Run: `python -m unittest tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp -v`

Expected: PASS.

Run: `python -m unittest discover -s tests -v`

Expected: PASS with only documented privilege-dependent Windows link skips; no GPU, model download, running backend, or network endpoint is required.

Run: `python -m py_compile scripts/check_gpu.py scripts/generate_image.py scripts/mcp_server.py scripts/local_gpu_imagegen/*.py scripts/local_gpu_imagegen/backends/*.py`

Expected: exit code 0 and no output.

Run: `python scripts/verify_mcp.py`

Expected: JSON with `"ok": true`, stdio transport, and exactly the 15 expected tool names.

Run: `python scripts/validate_acceptance_evidence.py`

Expected: non-strict validation remains truthful: currently retained accepted roots/revisions are reported from real evidence, and `release_ready` remains `false` until the complete 9+3 gate exists.

- [ ] **Step 5: Perform opt-in integration checks only against already-running approved local services**

Run: `python scripts/verify_mcp.py --check-readiness`

Expected: existing loopback WebUI may report ready; ComfyUI may report unavailable. Unavailable ComfyUI is a valid result and must not trigger installation, download, startup, or a readiness claim.

When an already-running ComfyUI endpoint and an explicitly trusted model are available, the documented opt-in command is:

```powershell
$env:LOCAL_GPU_IMAGEGEN_COMFYUI_URL='http://127.0.0.1:8188'
python scripts/verify_mcp.py --check-readiness
```

Do not run a real ComfyUI generation unless the exact model/workflow route receives a new user confirmation. Retain any real result as evidence only after the existing review/export boundaries pass.

- [ ] **Step 6: Commit docs and verifier without staging private evidence**

```powershell
git add skills/local-gpu-imagegen/SKILL.md README.md docs/architecture.md docs/troubleshooting.md SECURITY.md CHANGELOG.md scripts/verify_mcp.py tests/test_skill_contract.py tests/test_public_docs.py tests/test_verify_mcp.py
git diff --cached --check
git commit -m "docs: document safe byom model routing"
```

- [ ] **Step 7: Update continuity nodes outside the worktree**

Append the verified commit IDs, control flow, failure modes, exact test counts/skips, MCP 15-tool result, real backend observations, open limitations, and next step to `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\PROJECT_NODES.md`. Replace stale immediate-continuation text in `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\NEXT_SESSION.md`; preserve the one-main-agent/current-model/no-install/no-download/no-push boundaries and the true 9+3 acceptance counts.

- [ ] **Step 8: Final repository-state audit**

Run: `git status --short --branch`

Expected: implementation commits are clean except the preserved pre-existing subtype fix and `docs/evidence/runs/` if they remain intentionally uncommitted.

Run: `git log --oneline -10`

Expected: eight ordered BYOM commits ending in `docs: document safe byom model routing`; no remote, merge, tag, or release commit exists.

Run: `rg -n "exactly twelve|12 tools|supports arbitrary models|real ComfyUI.*verified|StarSea" README.md CHANGELOG.md SECURITY.md docs skills scripts tests`

Expected: no stale twelve-tool claim, arbitrary-model claim, real-ComfyUI verification claim, or StarSea public-evidence use; any historical wording must be explicitly labeled historical and truthful.
