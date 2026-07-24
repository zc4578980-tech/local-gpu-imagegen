# v0.7.0 800-Star Release Mainline Implementation Plan

> **For the implementing agent:** Execute this plan sequentially in
> `.worktrees/v061-launch-readiness` on `feature/v061-launch-readiness`. Do not
> begin implementation until the user approves this plan. Check off each step
> as it completes, run its stated verification, and commit only the listed
> files. Use `high` reasoning for normal implementation and return to `xhigh`
> for an architecture, evidence-integrity, or authority-boundary conflict.

**Goal:** Make `0.7.0` an installable, truthful, outcome-first release mainline
that connects Codex or Claude Code to an existing local image backend and is
backed by one genuine public-rights ordinary-route golden result.

**Architecture:** Keep the standard-library MCP core, fifteen-tool surface,
twenty-field generation plan, backend adapters, run store, trust boundary, and
byte-bound finalization unchanged. Concentrate code changes in the public
evidence layer: replace the unreleased hot-revision-only showcase contract with
a finalized ordinary-root contract, strengthen named-client evidence so one
retained session demonstrably performs generation, and derive public copy from
validated evidence. Keep regional and two-stage composition implemented and
tested but explicitly experimental, outside recommendation fallback, the
golden path, headline quality claims, and release blockers.

**Tech Stack:** Python 3.11/3.12 standard library, `unittest`, JSON and JSON
Schema documents, MCP JSON-RPC `2024-11-05` over stdio, `uv` 0.11+, existing
Codex and Claude Code CLIs, the already installed official SDXL 1.0 Base
checkpoint, the reviewed `sdxl-txt2img` ComfyUI workflow, GitHub Actions, PyPI,
and official MCP Registry metadata.

**Estimated Time:** 15 implementation tasks, approximately 6-10 engineering
hours plus separately authorized GPU/client runs and external CI/publication
waits. Stop rather than spending beyond the budgets in Tasks 8-10.

## Prerequisites

- [ ] `git status --short --branch` in the linked worktree prints only
  `## feature/v061-launch-readiness` before implementation begins.
- [ ] Read `AGENTS.md`, `PROJECT_NODES.md`, `NEXT_SESSION.md`, the approved
  design, this plan, `.superpowers/sdd/progress.md`, and
  `.superpowers/sdd/task-10-report.md` in that order.
- [ ] Keep the current user-selected model. Use `high` only after plan approval;
  use `medium` only for mechanical packaging/metadata work after reminding the
  user, and return to `xhigh` on a new contract conflict.
- [ ] Use an existing Python 3.12 interpreter. For the local Python 3.11 gate,
  set `LOCAL_GPU_IMAGEGEN_PY311` to an already installed 3.11 interpreter; do
  not let `uv` download one and do not mutate the interpreter's environment.
- [ ] Confirm `uv --version`, `codex --version`, and `claude --version` without
  updating any tool. Current observed versions are `uv 0.11.16`,
  `codex-cli 0.144.5`, and Claude Code `2.1.195`; later evidence records the
  versions actually used.
- [ ] Do not overwrite or rebuild the retained
  `dist/local_gpu_imagegen-0.6.1-py3-none-any.whl` whose recorded SHA-256 is
  `33ed4bc1564a92e3252b80f79cf1a7dd91f726774045801fd617bf9d0ef02655`.
- [ ] No current authority permits a dependency/model/node/interpreter
  download, GPU submission, trust mutation, client configuration write,
  finalization, public evidence export, push, tag, package publication,
  Registry publication, directory submission, or maintainer contact. Each
  authority gate below must receive a later, scope-specific user confirmation.

## Frozen Boundaries

- The public promise is: "Connect Codex or Claude Code to the image models you
  already run locally, with one installable command path and no silent model
  downloads or switches."
- The installed commands are `uvx local-gpu-imagegen verify`,
  `uvx local-gpu-imagegen setup codex --apply`,
  `uvx local-gpu-imagegen setup claude-code --apply`,
  `uvx local-gpu-imagegen doctor`, and `uvx local-gpu-imagegen serve`.
- Setup without `--apply` is read-only. Setup with `--apply` delegates to the
  official client command; project code never edits client config directly.
- MCP remains exactly fifteen tools. Do not add a release, demo, or evidence
  tool. Do not change the exact twenty-field generation-plan contract.
- The first golden candidate is the already installed official SDXL 1.0 Base
  checkpoint through ordinary ComfyUI `sdxl-txt2img` v1. Known expected
  identities are checkpoint SHA-256
  `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`,
  filesystem token
  `model:1a4a27ae037d08ad44e987720d07df0910fff0e1d3210378e6a4886cfc4f97a5`,
  workflow SHA-256
  `05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e`,
  and component-bundle SHA-256
  `ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62`.
  Rediscover every current identity before requesting GPU authority; do not
  reuse a stale route token.
- The ordinary route must not request regional or two-stage layout data and
  must never fall back to either route. Identity drift, route absence, or
  visual ineligibility stops the gate.
- `sdxl-regional-txt2img` and `sdxl-two-stage-copy-subject` remain experimental
  and retained with their tests and negative evidence. Do not repair, delete,
  automatically select, or present them as positive quality evidence here.
- One genuine ordinary-route golden result is release-blocking. A three-Profile
  gallery and complete 9+3 acceptance remain post-preview work.
- An eligible image requires original-resolution structured review. A failed
  or uncertain required check cannot produce a candidate. Route/GPU approval
  never implies review, finalization, export, or publication approval.
- The 800-Star number is a growth target evaluated over later release waves,
  never a promise, release claim, deterministic acceptance criterion, or test.

## File Map

- `tests/test_public_docs.py`: outcome-first first-viewport, experimental-route,
  evidence-presence, and synchronized-release assertions.
- `tests/public_contract_helpers.py`: unsupported-claim and active-version
  scanning only if new wording exposes a concrete false positive/negative.
- `README.md`: literal product/offer, shortest installed path, genuine result
  before simulated material, evidence-derived facts, and honest limitations.
- `.codex-plugin/plugin.json`, `pyproject.toml`, `server.json`: synchronized
  product description, version `0.7.0`, package/Registry identity, and scope.
- `CHANGELOG.md`, `docs/demo/README.md`, `docs/github-listing.md`,
  `docs/directory-listings.md`, `docs/client-compatibility.md`, and
  `docs/release-checklist.md`: matching release facts and explicit
  experimental/publication boundaries.
- `docs/evidence/schemas/client-session.schema.json`,
  `scripts/validate_client_sessions.py`, and
  `tests/test_validate_client_sessions.py`: distinguish compatibility sessions
  from one real installed-wheel golden-generation session and validate the
  two-client release set.
- `docs/evidence/schemas/real-demo.schema.json`,
  `scripts/export_real_demo.py`, `scripts/validate_real_demo.py`,
  `tests/real_demo_helpers.py`, `tests/test_export_real_demo.py`, and
  `tests/test_validate_real_demo.py`: finalized ordinary-root export, retained
  MCP-result binding, prompt/settings provenance, exact PNG identity, public
  rights, and private-value rejection.
- `tests/test_packaging.py`, `tests/test_cli.py`, `tests/test_client_setup.py`,
  `tests/test_client_configs.py`, and `tests/test_ci_workflow.py`: installed
  CLI/setup/stdio/four-job gates. Modify only for a reproduced installed-path
  defect or to pin the new evidence resource shape.
- `docs/evidence/client-sessions/codex-v070.json` and
  `docs/evidence/client-sessions/claude-code-v070.json`: sanitized records
  created only from real installed-wheel sessions.
- `docs/demo/real/`: validated original PNG, preview, public run/MCP result,
  sanitized transcript, README, and showcase manifest created only after all
  runtime authorities succeed.
- `PROJECT_NODES.md` and `NEXT_SESSION.md`: ignored project continuity updated
  after every verified milestone and before a new task handoff.

---

### Task 1: Pin The Outcome-First And Experimental Public Contract

**Files:**
- Modify: `tests/test_public_docs.py`
- Test: `tests/test_public_docs.py`

**Interfaces:**
- Produces failing tests for the approved messaging order without changing
  product code or public copy.
- Treats `docs/demo/real/final.png` plus `showcase-manifest.json` as the only
  condition that allows a genuine-image claim.

- [ ] **Step 1: Add the first-viewport regression test**

Add this test to `PublicDocumentationTests`:

```python
def test_readme_leads_with_literal_offer_and_installed_path(self) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first_viewport = "\n".join(readme.splitlines()[:45])
    promise = (
        "Connect Codex or Claude Code to the image models you already run locally, "
        "with one installable command path and no silent model downloads or switches."
    )
    self.assertIn("# Local GPU Imagegen", first_viewport)
    self.assertIn(promise, first_viewport)
    self.assertIn("uvx local-gpu-imagegen verify", first_viewport)
    self.assertIn("uvx local-gpu-imagegen setup codex --apply", first_viewport)
    self.assertLess(first_viewport.index(promise), first_viewport.index("Why This Project"))
```

- [ ] **Step 2: Add the experimental-route regression test**

```python
def test_release_mainline_keeps_composition_routes_experimental(self) -> None:
    public = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "CHANGELOG.md", "docs/github-listing.md")
    ).lower()
    self.assertIn("ordinary `sdxl-txt2img`", public)
    self.assertIn("experimental", public)
    self.assertIn("not part of the golden path", public)
    self.assertIn("does not establish a visual-quality improvement", public)
    self.assertNotIn("regional control for local image generation", public)
```

- [ ] **Step 3: Update the conditional evidence filenames in the existing test**

In `test_unretained_real_evidence_is_not_presented_as_complete`, change the
ready checks to:

```python
real_demo_ready = all(
    (demo_root / name).is_file()
    for name in ("final.png", "mcp-result.json", "showcase-manifest.json")
)
named_clients_ready = all(
    (client_root / name).is_file()
    for name in ("codex-v070.json", "claude-code-v070.json")
)
if real_demo_ready:
    self.assertIn("docs/demo/real/final.png", readme)
    self.assertLess(
        readme.index("docs/demo/real/final.png"),
        readme.index("docs/demo/preview-loop.gif"),
    )
else:
    self.assertIn("Genuine local-GPU result: release gate pending", readme)
```

- [ ] **Step 4: Run the test and confirm RED for approved copy, not a syntax error**

Run:

```powershell
python -m unittest tests.test_public_docs -v
```

Expected: the new outcome-first/experimental tests fail against stale regional
headline copy. Existing truthfulness/version tests continue to execute.

- [ ] **Step 5: Do not commit a red-only state**

Continue directly to Task 2; commit Tasks 1 and 2 together only after the
focused public-document suite is green.

---

### Task 2: Align Positioning, First Run, And Experimental Boundaries

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `.codex-plugin/plugin.json`
- Modify: `pyproject.toml`
- Modify: `server.json`
- Modify: `docs/demo/README.md`
- Modify: `docs/github-listing.md`
- Modify: `docs/directory-listings.md`
- Modify: `docs/client-compatibility.md`
- Modify: `docs/release-checklist.md`
- Modify: `tests/test_public_docs.py`
- Test: `tests/test_public_docs.py`
- Test: `tests/test_repository_hygiene.py`

**Interfaces:**
- Public order is outcome -> installed first run -> genuine proof or explicit
  pending gate -> reliability differentiators -> deeper/experimental controls.
- Metadata agrees on product, version, fifteen tools, three backends, ordinary
  golden path, and limitations.

- [ ] **Step 1: Replace the README first viewport with the approved offer**

Use this exact opening structure while the evidence directory is absent:

```markdown
# Local GPU Imagegen

<!-- mcp-name: io.github.zc4578980-tech/local-gpu-imagegen -->

Connect Codex or Claude Code to the image models you already run locally, with one installable command path and no silent model downloads or switches.

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```

`setup` is read-only without `--apply`. The apply path delegates to the client's official `mcp add` command; Local GPU Imagegen does not edit client configuration files directly or download a model.

> **Genuine local-GPU result: release gate pending.** `docs/demo/real/final.png` becomes release evidence only after the ordinary SDXL route, original PNG, full-resolution review, later byte-bound finalization, retained MCP result, public rights, and exported hashes validate.
```

Do not yet claim the pending file exists. Keep the simulated GIF below the
genuine section and preserve its explicit simulation disclaimer.

- [ ] **Step 2: Reorder README benefits and status**

Lead `Why This Project` with existing-backend reuse, installed CLI, no silent
downloads/switches, structured evidence, and review/finalization. Move regional
and two-stage bullets under an `Experimental Composition Controls` subsection
that contains all of these literal boundaries:

```text
ordinary `sdxl-txt2img`
experimental
not part of the golden path
does not establish a visual-quality improvement
no fallback
```

Retain the full tool reference and recovery material. Narrow stale status copy:
real ordinary-route MCP generation has negative local evidence, but no eligible
public result, generated named-client session, measured performance/VRAM,
production-readiness claim, or complete 9+3 acceptance exists yet.

- [ ] **Step 3: Synchronize package, plugin, Registry, and listing descriptions**

Use this concise package description in `pyproject.toml`:

```toml
description = "Connect Agents to trusted local image-generation backends without silent downloads or switches."
```

Use a Registry description no longer than 100 characters in `server.json`:

```json
"description": "Trusted local image generation for Codex and Claude Code, with explicit routes and review."
```

Update `.codex-plugin/plugin.json`, `docs/github-listing.md`, and
`docs/directory-listings.md` to the same outcome-first order. The GitHub release
title must be `v0.7.0 Preview - Trusted local image generation for Agents`, not
a regional-quality headline. Keep directory status exactly
`Status: prepared, not submitted`.

- [ ] **Step 4: Reset the release checklist to the approved gates**

Replace stale 584-test/regional-demo completion claims with unchecked sections
for: final model-free gate; isolated 3.11 and 3.12 installed-wheel gate; Codex
and Claude Code release-set validation; one finalized ordinary-route demo;
README evidence placement; experimental boundaries; metadata synchronization;
four exact green CI jobs; exact wheel publication; Registry/tag/release URL
verification. Do not write future counts or hashes.

- [ ] **Step 5: Update changelog and demo/client docs without claiming evidence**

Under `Unreleased`, describe the core-first release mainline and classify both
composition routes as experimental. `docs/demo/README.md` must describe one
ordinary finalized root, not a mandatory hot revision.
`docs/client-compatibility.md` must distinguish verified setup/stdio contracts
from still-pending hosted client sessions until Task 11 succeeds.

- [ ] **Step 6: Run focused truthfulness and metadata tests**

Run:

```powershell
python -m unittest tests.test_public_docs tests.test_repository_hygiene tests.test_ci_workflow -v
git diff --check
```

Expected: all focused tests pass; no unsupported quality, performance,
production-readiness, publication, client-session, or star claim is present.

- [ ] **Step 7: Commit positioning and contract tests**

```powershell
git add README.md CHANGELOG.md .codex-plugin/plugin.json pyproject.toml server.json docs/demo/README.md docs/github-listing.md docs/directory-listings.md docs/client-compatibility.md docs/release-checklist.md tests/test_public_docs.py
git commit -m "docs: align 0.7.0 release mainline"
```

---

### Task 3: Distinguish Compatibility And Golden-Generation Client Sessions

**Files:**
- Modify: `docs/evidence/schemas/client-session.schema.json`
- Modify: `scripts/validate_client_sessions.py`
- Modify: `tests/test_validate_client_sessions.py`
- Test: `tests/test_validate_client_sessions.py`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Adds required `session_purpose` with values `compatibility` and
  `golden_generation`.
- Produces `validate_release_set(documents, *, expected_server_version) ->
  list[str]`.
- CLI flag `--require-release-set` requires one Codex record, one Claude Code
  record, a shared server version, and at least one real generation-purpose
  record. It does not require both clients to spend GPU budget.

- [ ] **Step 1: Extend the test fixture and write RED purpose tests**

Change `valid_session` to accept `purpose: str = "compatibility"` and include:

```python
"session_purpose": purpose,
```

For `golden_generation`, use sanitized observable calls with exact result
hashes:

```python
document["tool_calls"] = [
    tool_call(1, "local_gpu_imagegen_check", {"ready": True, "backend": "comfyui"}),
    tool_call(2, "local_gpu_start_run", {"run_id": "public-demo-run", "state": "confirmed"}),
    tool_call(
        3,
        "local_gpu_generate_round",
        {
            "run_id": "public-demo-run",
            "state": "generated",
            "round_number": 1,
            "image_sha256": "b" * 64,
        },
    ),
]
```

Add tests that reject `golden_generation` without both start/generate calls,
duplicate client names, missing one named client, no golden session, mixed
server versions, and malformed purpose values.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_validate_client_sessions -v
```

Expected: failures show missing `session_purpose`, missing release-set function,
and missing aggregate enforcement.

- [ ] **Step 3: Update the closed JSON Schema**

Add this required top-level property and keep every object closed:

```json
"session_purpose": {
  "enum": ["compatibility", "golden_generation"],
  "type": "string"
}
```

Add `session_purpose` to the top-level `required` array. Keep sanitized result
objects flexible, because each MCP tool has a different public-safe summary;
semantic validation still hashes every exact sanitized result.

- [ ] **Step 4: Implement per-session generation coverage**

Add constants and logic equivalent to:

```python
GOLDEN_GENERATION_TOOLS = {
    "local_gpu_start_run",
    "local_gpu_generate_round",
}

purpose = document.get("session_purpose")
if purpose not in {"compatibility", "golden_generation"}:
    findings.add("invalid_session_purpose")
elif purpose == "golden_generation" and not GOLDEN_GENERATION_TOOLS <= observed_tools:
    findings.add("missing_golden_generation_calls")
```

For every sanitized `local_gpu_generate_round` result in a golden session,
require non-empty `run_id`, positive integer `round_number`, and a 64-lowercase
hex `image_sha256`; otherwise add `invalid_golden_generation_result`.

- [ ] **Step 5: Implement aggregate release-set validation**

Use this exact signature and result codes:

```python
def validate_release_set(
    documents: list[object],
    *,
    expected_server_version: str,
) -> list[str]:
    findings: set[str] = set()
    valid_documents: list[dict[str, object]] = []
    for document in documents:
        session_findings = validate_session(
            document,
            expected_server_version=expected_server_version,
        )
        findings.update(session_findings)
        if isinstance(document, dict):
            valid_documents.append(document)
    names = [
        document.get("client", {}).get("name")
        for document in valid_documents
        if isinstance(document.get("client"), dict)
    ]
    if sorted(names) != ["claude-code", "codex"]:
        findings.add("named_client_release_set_required")
    if not any(
        document.get("session_purpose") == "golden_generation"
        for document in valid_documents
    ):
        findings.add("golden_generation_session_required")
    versions = {
        document.get("server", {}).get("version")
        for document in valid_documents
        if isinstance(document.get("server"), dict)
    }
    if versions != {expected_server_version}:
        findings.add("release_set_server_version_mismatch")
    return sorted(findings)
```

Add `--require-release-set` to the CLI. When set, run aggregate validation after
reading all files and include `release_set_findings` in the JSON report.

- [ ] **Step 6: Run schema, semantic, CLI, and packaging tests**

```powershell
python -m unittest tests.test_validate_client_sessions tests.test_packaging -v
python -m compileall -q scripts/validate_client_sessions.py tests/test_validate_client_sessions.py
git diff --check
```

Expected: all pass; the wheel still contains the updated closed schema and
validator. No client process or GPU is invoked by these tests.

- [ ] **Step 7: Commit client evidence semantics**

```powershell
git add docs/evidence/schemas/client-session.schema.json scripts/validate_client_sessions.py tests/test_validate_client_sessions.py
git commit -m "feat(evidence): distinguish generation sessions"
```

---

### Task 4: Define The Finalized Ordinary-Root Demo Contract

**Files:**
- Modify: `docs/evidence/schemas/real-demo.schema.json`
- Modify: `tests/real_demo_helpers.py`
- Modify: `tests/test_export_real_demo.py`
- Modify: `tests/test_validate_real_demo.py`
- Test: `tests/test_export_real_demo.py`
- Test: `tests/test_validate_real_demo.py`

**Interfaces:**
- Replaces unreleased `real_local_gpu_hot_revision` with
  `real_local_gpu_generation` schema version `2.0`.
- The public export contains exactly `final.png`, `preview.jpg`,
  `run-manifest.json`, `mcp-result.json`, `transcript.md`,
  `showcase-manifest.json`, and `README.md`.
- A source root must be ordinary `sdxl-txt2img`, parentless, eligible,
  finalized after the exact candidate confirmation, and accompanied by the
  retained genuine `local_gpu_finalize_run` JSON result.

- [ ] **Step 1: Replace fixture file expectations**

Use:

```python
EXPECTED_FILES = {
    "final.png",
    "preview.jpg",
    "run-manifest.json",
    "mcp-result.json",
    "transcript.md",
    "showcase-manifest.json",
    "README.md",
}
```

Change `write_source_fixture` to create one finalized parentless run, a valid
golden-generation Codex session, an authority document, and a separate raw
MCP final result. The raw result must include `ok: true`, matching `run_id`,
`state: finalized`, and the exact `final` object copied from the manifest.

- [ ] **Step 2: Write the finalized-root exporter tests**

The primary test must call the new interface:

```python
manifest = export_real_demo(
    run_root,
    output,
    client,
    mcp_result,
    authority_path=authority,
)
self.assertEqual(
    (output / "final.png").read_bytes(),
    (run_root / "final.png").read_bytes(),
)
self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)
self.assertEqual(manifest["demo_kind"], "real_local_gpu_generation")
self.assertEqual(manifest["final"]["quality_status"], "accepted")
self.assertEqual(
    manifest["mcp_result"]["source_sha256"],
    sha256_file(mcp_result),
)
```

Add fail-closed tests for a child run, missing final, altered final bytes,
ineligible/uncertain review, wrong confirmation, non-ordinary workflow,
mismatched MCP result, missing public rights, destination already present, and
an unrelated source file that must not be copied.

- [ ] **Step 3: Write validator tests for every public binding**

Keep existing byte/private-value tests and add failures for:

```python
manifest["installed_package"]["version"] = "0.6.1"
manifest["mcp_result"]["source_sha256"] = "0" * 64
manifest["generation"]["positive_prompt"] = ""
manifest["final"]["finalization_verified"] = False
manifest["route"]["workflow_template_id"] = "sdxl-two-stage-copy-subject"
```

Expected findings are respectively `server_version_mismatch`,
`mcp_source_sha256_invalid`, `invalid_generation_provenance`,
`invalid_finalization`, and `invalid_public_route`.

- [ ] **Step 4: Replace the closed schema shape**

Require these top-level keys and set `additionalProperties: false`:

```json
[
  "schema_version",
  "demo_kind",
  "model_output",
  "installed_package",
  "public_rights",
  "route",
  "generation",
  "final",
  "client_session",
  "mcp_result",
  "artifacts",
  "known_limitations"
]
```

Pin `schema_version` to `2.0`, `demo_kind` to
`real_local_gpu_generation`, `model_output` to `true`, backend to `comfyui`,
workflow to `sdxl-txt2img` v1, authorization scope to `public_evidence`, and
`final.quality_status` to `accepted`. Require exact wheel SHA-256, prompt,
negative prompt, seed, dimensions, sampling settings, original PNG metadata,
full-resolution visual checks, exact confirmation, finalization verification,
client binding, sanitized MCP-result binding, artifacts, and at least three
known limitations.

- [ ] **Step 5: Run tests and confirm RED against the old implementation**

```powershell
python -m unittest tests.test_export_real_demo tests.test_validate_real_demo -v
```

Expected: failures are caused by the old two-run function signature and old
schema/demo shape. Continue immediately to Task 5; do not commit red tests.

---

### Task 5: Implement Ordinary Golden-Demo Export And Validation

**Files:**
- Modify: `scripts/export_real_demo.py`
- Modify: `scripts/validate_real_demo.py`
- Modify: `docs/evidence/schemas/real-demo.schema.json`
- Modify: `tests/real_demo_helpers.py`
- Modify: `tests/test_export_real_demo.py`
- Modify: `tests/test_validate_real_demo.py`
- Modify if resource assertions change: `tests/test_packaging.py`

**Interfaces:**
- `export_real_demo(run_root, destination, client_session, mcp_result,
  *, authority_path) -> dict[str, object]`.
- `validate_real_demo(root) -> list[str]`.
- CLI positional order:
  `python scripts/export_real_demo.py RUN_ROOT DESTINATION CLIENT_SESSION
  MCP_RESULT --authority AUTHORITY_JSON`.

- [ ] **Step 1: Replace hot-revision constants with ordinary-root constants**

In `validate_real_demo.py`, import `__version__` and set:

```python
EXPECTED_SERVER_VERSION = __version__
EXPECTED_FILES = {
    "final.png",
    "preview.jpg",
    "run-manifest.json",
    "mcp-result.json",
    "transcript.md",
    "showcase-manifest.json",
    "README.md",
}
ARTIFACT_FILES = EXPECTED_FILES - {"showcase-manifest.json"}
```

Keep the exact official SDXL model/workflow/bundle/public-rights constants.
Delete mandatory preserve/change/revision constants from this validator only;
do not alter revision support in the MCP core.

- [ ] **Step 2: Implement one-root source validation**

The exporter must, in this order:

1. reject an existing destination;
2. validate approved public authority;
3. read the source manifest and require `parent is None`;
4. require `state == "finalized"` and a complete `final` object;
5. locate the selected generated round and its structured review;
6. re-derive `finalization_candidate` and require its confirmation;
7. require `final.image.sha256` to equal the candidate and selected image;
8. re-open and validate the original PNG and preview under the run root;
9. validate the exact ordinary public route and generation provenance;
10. validate the named-client document as `golden_generation`;
11. validate the raw MCP result against the source manifest and final bytes;
12. only then create the destination.

Do not accept `sdxl-regional-txt2img`,
`sdxl-two-stage-copy-subject`, a child run, a private/backend-bound route, an
absolute/escaping artifact path, a symlink/reparse point, or a mock marker.

- [ ] **Step 3: Bind prompt, settings, installed wheel, and raw MCP result**

Create the public generation summary with exact source fields:

```python
generation = {
    "positive_prompt": selected["generation_plan"]["positive_prompt"],
    "negative_prompt": selected["generation_plan"]["negative_prompt"],
    "seed": selected["seed"],
    "width": route["width"],
    "height": route["height"],
    "steps": route["steps"],
    "guidance_scale": route["guidance_scale"],
    "sampler": route["sampler"],
    "scheduler": route["scheduler"],
}
```

Reject empty prompts, extra generation-plan fields that contradict the locked
route, and seed/settings mismatch with `backend_result`.

Sanitize the genuine final tool result into `mcp-result.json`:

```python
public_mcp_result = {
    "schema_version": "1.0",
    "tool": "local_gpu_finalize_run",
    "source_sha256": sha256_file(mcp_result),
    "ok": True,
    "run_id": final_summary["run_id"],
    "state": "finalized",
    "final": {
        "round_number": final_summary["round_number"],
        "quality_status": "accepted",
        "image_sha256": final_summary["image_sha256"],
    },
}
```

The source JSON remains private evidence. The public file retains its canonical
source digest and identity fields without paths, endpoints, prompts duplicated
inside a client transcript, account data, or hidden reasoning.

- [ ] **Step 4: Export an exact allowlist and self-validate atomically**

Copy only `final.png` and the selected preview, write one sanitized run
manifest, public MCP result, transcript, README, and showcase manifest, hash
every public artifact, then call `validate_real_demo(destination)`. On any
exception, remove only the newly created destination and re-raise. Never touch
the source run.

The generated `README.md` must state that `final.png` is the original finalized
PNG, name SDXL 1.0 Base and ordinary `sdxl-txt2img`, point to the manifest for
hashes/prompts/settings/review, list limitations, and distinguish the separate
simulated GIF in the parent directory.

- [ ] **Step 5: Implement semantic validation for all relationships**

`validate_real_demo` must reject missing/extra files, invalid schema/demo kind,
wrong package version or wheel digest, wrong rights, wrong exact route, empty
prompt/settings, failed/uncertain visual checks, wrong finalize confirmation,
unverified finalization, changed final bytes, changed preview/public JSON/MD
bytes, mismatched raw MCP digest shape, invalid client binding, absolute or
escaping paths, private values, and fewer than three limitations.

The exact confirmation remains:

```python
f"finalize:{run_id}:{round_number}:{image_sha256}"
```

- [ ] **Step 6: Run focused, packaging, and complete evidence tests**

```powershell
python -m unittest tests.test_export_real_demo tests.test_validate_real_demo tests.test_validate_client_sessions tests.test_packaging -v
python -m compileall -q scripts/export_real_demo.py scripts/validate_real_demo.py tests/real_demo_helpers.py tests/test_export_real_demo.py tests/test_validate_real_demo.py
git diff --check
```

Expected: all pass with synthetic/model-free bytes; no model, backend, network,
GPU, client, or optional Pillow process runs.

- [ ] **Step 7: Commit the ordinary demo evidence contract**

```powershell
git add docs/evidence/schemas/real-demo.schema.json scripts/export_real_demo.py scripts/validate_real_demo.py tests/real_demo_helpers.py tests/test_export_real_demo.py tests/test_validate_real_demo.py tests/test_packaging.py
git commit -m "feat(evidence): export ordinary golden demos"
```

If `tests/test_packaging.py` did not change, omit it from `git add`.

---

### Task 6: Prove The Existing Installed Golden Path Has No Code Blocker

**Files:**
- Modify only on a reproduced defect: the narrow CLI/client/packaging module
  that owns that defect and its focused test.
- Do not modify by default: `scripts/mcp_server.py`, engine, run store,
  backends, router, trust registry, generation plan, or tool schemas.

**Interfaces:**
- Proves source and installed CLI surfaces before any GPU request.
- A concrete failure may authorize a minimal local fix under the approved spec;
  an architecture/tool-surface change requires returning to `xhigh` and plan
  amendment before editing.

- [ ] **Step 1: Run focused installed-path tests**

```powershell
python -m unittest tests.test_cli tests.test_client_setup tests.test_client_configs tests.test_packaging tests.test_verify_mcp -v
python scripts/verify_mcp.py
python scripts/verify_client_configs.py
```

Expected: version `0.7.0`, protocol `2024-11-05`, exactly fifteen tools,
read-only setup contracts for Codex and Claude Code, and installed execution
outside the checkout.

- [ ] **Step 2: Run setup dry-runs only**

```powershell
$savedTaskPythonPath = $env:PYTHONPATH
try {
  $env:PYTHONPATH = (Resolve-Path -LiteralPath scripts).Path
  python -m local_gpu_imagegen.cli setup codex
  python -m local_gpu_imagegen.cli setup claude-code
} finally {
  $env:PYTHONPATH = $savedTaskPythonPath
}
```

Expected: JSON with `applied: false`; no official `mcp add` call runs. A missing
client binary is an environment finding, not permission to write config.

- [ ] **Step 3: Classify any failure before changing code**

- A packaging/resource/CLI defect: write one failing focused test, implement
  the minimal owning-module fix, rerun this task, and commit with a specific
  `fix(...)` message.
- A missing client, stopped backend, absent Python 3.11, or unavailable official
  setup command: record an environment blocker; do not edit product code.
- A need for tool 16, direct config mutation, route fallback, or MCP-core
  refactor: stop and return to `xhigh`; the approved spec does not authorize it.

- [ ] **Step 4: Record the verified control flow in continuity**

Update ignored `PROJECT_NODES.md` with installed CLI -> read-only setup ->
stdio -> exact tool surface, observed commands/results, failure modes, and open
limitations. Do not commit continuity yet.

---

### Task 7: Build And Verify The Installed Execution Candidate

**Files:**
- Create in a new temporary directory only: one `0.7.0` wheel, two isolated
  venvs, and `SHA256SUMS`.
- Modify after observed results: `docs/release-checklist.md`
- Never overwrite: `dist/local_gpu_imagegen-0.6.1-py3-none-any.whl`

**Interfaces:**
- Produces the exact installed wheel identity used by the later real client
  generation session and golden demo.
- Does not authorize generation, setup apply, trust changes, or publication.

- [ ] **Step 1: Run the complete model-free pre-build gate**

```powershell
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
python scripts/verify_mcp.py
python scripts/verify_client_configs.py
git diff --check
```

Expected: zero failures; only known Windows link-privilege skips are allowed.
Record actual test/skip counts rather than copying historical counts.

- [ ] **Step 2: Build offline into a unique temporary directory**

```powershell
$candidateRoot = Join-Path $env:TEMP ("local-gpu-imagegen-v070-exec-" + [guid]::NewGuid().ToString("N"))
$wheelRoot = Join-Path $candidateRoot "wheel"
New-Item -ItemType Directory -Path $wheelRoot | Out-Null
$env:UV_PYTHON_DOWNLOADS = "never"
uv build --offline --wheel --out-dir $wheelRoot
$wheel = @(Get-ChildItem -LiteralPath $wheelRoot -Filter 'local_gpu_imagegen-0.7.0-*.whl')
if ($wheel.Count -ne 1) { throw "expected exactly one 0.7.0 wheel" }
$wheelHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheel[0].FullName).Hash.ToLowerInvariant()
"$wheelHash  $($wheel[0].Name)" | Set-Content -Encoding ascii (Join-Path $candidateRoot "SHA256SUMS")
```

Expected: no network transfer and no file written to `dist/`.

- [ ] **Step 3: Verify under existing Python 3.12 outside the checkout**

```powershell
$venv312 = Join-Path $candidateRoot "py312"
uv venv --python 3.12 --no-project $venv312
uv pip install --offline --python (Join-Path $venv312 "Scripts\python.exe") --no-deps $wheel[0].FullName
$cli312 = Join-Path $venv312 "Scripts\local-gpu-imagegen.exe"
Push-Location $candidateRoot
try {
  & $cli312 verify
  & $cli312 setup codex
  & $cli312 setup claude-code
  & $cli312 doctor
} finally { Pop-Location }
```

Expected: verify reports `0.7.0`, protocol `2024-11-05`, and exactly fifteen
tools; both setup results have `applied: false`. `doctor` may truthfully report
`ready: false` without making package verification fail.

- [ ] **Step 4: Verify under an already installed Python 3.11 without download**

```powershell
$python311 = [Environment]::GetEnvironmentVariable("LOCAL_GPU_IMAGEGEN_PY311")
if (-not $python311 -or -not (Test-Path -LiteralPath $python311 -PathType Leaf)) {
  throw "existing Python 3.11 required; download is not authorized"
}
$version311 = & $python311 --version
if ($version311 -notmatch '^Python 3\.11\.') { throw "LOCAL_GPU_IMAGEGEN_PY311 is not Python 3.11" }
$venv311 = Join-Path $candidateRoot "py311"
uv venv --python $python311 --no-project $venv311
uv pip install --offline --python (Join-Path $venv311 "Scripts\python.exe") --no-deps $wheel[0].FullName
$cli311 = Join-Path $venv311 "Scripts\local-gpu-imagegen.exe"
Push-Location $candidateRoot
try { & $cli311 verify } finally { Pop-Location }
```

Expected: the same server/protocol/fifteen-tool result. If no existing 3.11 is
available, stop; do not invoke an implicit `uv` interpreter download.

- [ ] **Step 5: Exercise the publishable uvx shape from the local wheel**

```powershell
Push-Location $candidateRoot
try { uvx --offline --from $wheel[0].FullName local-gpu-imagegen verify } finally { Pop-Location }
```

Expected: the same installed result without a source clone or personal
workspace path. This does not claim the un-published command
`uvx local-gpu-imagegen verify` resolves from PyPI yet.

- [ ] **Step 6: Inspect the wheel and record exact identity**

Require packaged CLI modules, all six workflow JSON files, both evidence
schemas, the Agent Skill, no `outputs/`, no `docs/evidence/runs/`, no model
weights, no personal path, and no credential-shaped value. Record wheel path,
byte size, SHA-256, Python versions, commands, and results in
`PROJECT_NODES.md`. Mark only observed local checklist items.

- [ ] **Step 7: Commit only the observed checklist update**

```powershell
git add docs/release-checklist.md
git commit -m "docs: record installed 0.7.0 execution gate"
```

Keep the temporary wheel immutable after its digest is bound to client/demo
evidence.

---

### Task 8: Prepare And Display One Bounded Ordinary SDXL Demo Plan

**Files:**
- Create privately/ignored only: route-discovery transcript and bounded runtime
  proposal under `outputs/v070-golden-private/` or another ignored output root.
- Modify after the read-only gate: `PROJECT_NODES.md`
- Do not modify tracked source.

**Interfaces:**
- Read-only discovery -> exact cryptographic identity -> ordinary
  `sdxl-txt2img` recommendation -> displayed brief/settings/budget -> stop for
  a later user message.

- [ ] **Step 1: Announce cost and stop conditions before any paid/GPU work**

Tell the user: one bounded client session, at most two successful ordinary
SDXL rounds, expected GPU wall time per observed local round but no benchmark
claim, no download/switch/upscale/fallback, no more than the confirmed budget,
and stop on identity drift, route absence, OOM/timeout, visual ineligibility,
or context growth beyond the sanitized discovery boundary. Do not run a paid
client or GPU yet.

- [ ] **Step 2: Re-run only the bounded read-only identity sequence**

In one fresh installed-wheel MCP process:

1. selected-folder `index` for the already approved checkpoint root and exact
   include;
2. require exactly one indexed candidate with expected filename and byte size;
3. selected-candidate `fingerprint` for that file only;
4. API-only ComfyUI discovery;
5. read-only `inspect_workflow_binding` for ordinary `sdxl-txt2img`;
6. `public_evidence` recommendation with no regional/two-stage request.

Do not scan unrelated roots, trust/mutate, call `/prompt`, or accept
`backend_binding`/`private` downgrade. Require current endpoint, checkpoint,
filesystem/execution identities, workflow, bundle, compiler, and route token to
match the approved ordinary boundary.

- [ ] **Step 3: Choose a first-pass-friendly public brief without freezing it silently**

Prepare one non-human, generated-text-free brief with one visually unambiguous
subject or environment, ordinary txt2img only, no precise copy/subject split,
no tiny anatomy, no typography, and no requirement known to have failed the
regional/two-stage experiments. Resolve exact positive/negative prompts, seed,
dimensions, steps, CFG, sampler, scheduler, successful-round budget (maximum
two), and upscale policy from the current profile/route. These are a proposal,
not authority.

- [ ] **Step 4: Display the complete frozen proposal**

Display:

```text
installed wheel: path-neutral filename, byte size, SHA-256, version 0.7.0
profile/subtype and natural-language intent
positive and negative prompts
backend and current endpoint identity
catalog, filesystem, and execution model identities
checkpoint, workflow, and component-bundle SHA-256 values
workflow/compiler IDs and versions
width, height, seed, steps, CFG, sampler, scheduler, upscale policy
max successful rounds and idempotency policy
downloads/model switch/upscale/regional/two-stage/fallback: disabled
stop conditions: identity drift, unavailable ordinary route, technical failure,
or no eligible image inside budget
```

Then stop. Ask for a later exact confirmation bound to the newly displayed
route token and budget. Plan approval is not this confirmation.

- [ ] **Step 5: Record the unconsumed proposal**

Write the read-only identities, control flow, exact verification calls, and
open limitations to ignored continuity/private output. Do not put endpoint,
route token, local paths, or private prompts into tracked files.

---

### Task 9: Execute The Confirmed Golden Generation Through A Real Client

**Files:**
- Create privately/ignored: raw Codex JSONL, exact MCP result JSON, run
  artifacts, and a draft sanitized session record.
- Do not create public demo files yet.

**Interfaces:**
- Consumes only the later exact Task 8 confirmation.
- Produces one retained real Codex installed-wheel session and at most the
  confirmed ordinary-route successful-round budget.

- [ ] **Step 1: Recheck authority and identities immediately before launch**

Verify the user confirmation matches the displayed route/budget, the execution
wheel digest is unchanged, the ordinary route reissues exactly in the same
process, and GPU headroom/backend readiness are sufficient. Any mismatch stops
before `local_gpu_start_run` or `/prompt`.

- [ ] **Step 2: Launch Codex without model override or config write**

Create path-neutral command/args overrides to the isolated installed CLI and
run one ephemeral JSON session:

```powershell
$cliPath = ($cli312 -replace '\\','/')
$commandOverride = 'mcp_servers.local-gpu-imagegen.command="' + $cliPath + '"'
$argsOverride = 'mcp_servers.local-gpu-imagegen.args=["serve"]'
$rawCodex = Join-Path $candidateRoot "codex-golden.jsonl"
codex exec --ephemeral --ignore-user-config --ignore-rules --strict-config --json --sandbox read-only -c $commandOverride -c $argsOverride --cd $candidateRoot "Use only local-gpu-imagegen MCP tools. Revalidate the displayed ordinary SDXL route, start exactly the confirmed run, read it back, construct the exact twenty-field generation plan, generate within the confirmed successful-round budget, and stop after retaining the image/result. Do not finalize, export, switch models, download, use regional/two-stage routing, or edit files." | Tee-Object -FilePath $rawCodex
```

Do not pass `--model` and do not use any bypass flag. If Codex requires an
approval unavailable in non-interactive mode, stop and request an interactive
user-approved client invocation; do not bypass sandbox/approval controls.

- [ ] **Step 3: Enforce exact tool and backend budgets**

Allow only the displayed discovery/recommendation/start/get/generate flow.
Require the Skill to call `local_gpu_get_run` after start and construct all
twenty fields from persisted state. A backend failure does not consume a
successful round; a retained PNG does. Do not exceed two successful rounds,
submit a regional/two-stage graph, retry after exhaustion, or change model.

- [ ] **Step 4: Retain genuine result bytes and draft the session record**

Retain raw JSONL privately, the complete MCP generate result, original PNG,
preview, manifest, wheel identity, timestamps, client version, and canonical
result digests. Produce a draft public session with
`session_purpose: golden_generation`, sanitized result summaries, and no raw
prompt/path/endpoint/account/credential/hidden-reasoning value. Do not delete
private source evidence until the public validator succeeds.

- [ ] **Step 5: Stop after generation**

Generation authority does not permit review, finalization, export, or public
commit. Display exact run/round/image SHA-256 and request a later review-bound
confirmation.

---

### Task 10: Review, Finalize, And Authorize Export In Separate Gates

**Files:**
- Modify privately: source run manifest through MCP review/finalization only.
- Create privately: raw `local_gpu_finalize_run` result JSON.
- Do not create tracked public files until export authority is granted.

**Interfaces:**
- Later review confirmation -> original-resolution inspection -> one truthful
  review -> candidate display -> later exact finalize token -> finalization ->
  separate public-export confirmation.

- [ ] **Step 1: Consume only a later byte-bound review confirmation**

Rehash the original PNG and preview. Open the original PNG at full resolution,
not only the preview. Record every profile constraint, rubric score, critique,
hard failure, and applicable visual check. For a non-human image, anatomy checks
are `not_applicable`; text/watermark remains required. Never infer a pass from
technical PNG validity.

- [ ] **Step 2: Record one truthful review and fail closed**

Call `local_gpu_record_review` only for the confirmed bytes. If any required
check is failed/uncertain or the score/hard-failure contract is ineligible,
record that result. Spend only a remaining confirmed generation round when the
recorded next action and budget allow it; otherwise stop and diagnose the
ordinary route. Never fall back to experimental composition or a new model.

- [ ] **Step 3: Display an eligible candidate and stop again**

When MCP returns `quality_status: candidate`, display the original image,
limitations, run ID, round number, exact SHA-256, and exact token:

```text
finalize:<run_id>:<round_number>:<image_sha256>
```

Wait for a later user message containing that exact token. Praise, route
approval, review approval, or plan approval is not finalization authority.

- [ ] **Step 4: Finalize only the exact candidate and retain the raw result**

After the later exact token, call `local_gpu_finalize_run` once. Retain the
complete genuine JSON result privately. Rehash `round-NN.png` and `final.png`;
require byte identity and matching manifest/MCP result metadata. If the result
contains a different run/round/hash/path, stop and do not sanitize/export it.

- [ ] **Step 5: Request separate public evidence export authority**

Display public rights, exact final PNG SHA-256, proposed destination
`docs/demo/real`, the seven-file export allowlist, fields retained (prompt,
settings, route, review, wheel/client/MCP hashes), fields omitted (local paths,
endpoint, account data, credentials, hidden reasoning), and limitations. Wait
for later confirmation before calling `export_real_demo.py`.

---

### Task 11: Export And Validate The Genuine Ordinary-Route Demo

**Files:**
- Create: `docs/demo/real/final.png`
- Create: `docs/demo/real/preview.jpg`
- Create: `docs/demo/real/run-manifest.json`
- Create: `docs/demo/real/mcp-result.json`
- Create: `docs/demo/real/transcript.md`
- Create: `docs/demo/real/showcase-manifest.json`
- Create: `docs/demo/real/README.md`
- Create: `docs/evidence/client-sessions/codex-v070.json`

**Interfaces:**
- Consumes exact Task 10 export authority, source run, authority JSON,
  golden-generation Codex record, and raw final MCP result.
- Produces only the validated seven-file public allowlist plus the Codex record.

- [ ] **Step 1: Validate the Codex record before binding it**

```powershell
$privateCodexRecord = Join-Path $candidateRoot "codex-v070.sanitized.json"
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 $privateCodexRecord
```

Expected: no findings. Manually scan the public JSON for endpoint, local paths,
prompt fields, email/account values, tokens, and hidden reasoning. Copy it to
`docs/evidence/client-sessions/codex-v070.json` only after the scan passes.

- [ ] **Step 2: Run the exporter once into an absent destination**

```powershell
$privateRunRoot = [Environment]::GetEnvironmentVariable("LOCAL_GPU_IMAGEGEN_GOLDEN_RUN_ROOT")
$privateMcpResult = [Environment]::GetEnvironmentVariable("LOCAL_GPU_IMAGEGEN_GOLDEN_MCP_RESULT")
if (-not $privateRunRoot -or -not (Test-Path -LiteralPath $privateRunRoot -PathType Container)) {
  throw "private golden run root is missing"
}
if (-not $privateMcpResult -or -not (Test-Path -LiteralPath $privateMcpResult -PathType Leaf)) {
  throw "private golden MCP result is missing"
}
python scripts/export_real_demo.py $privateRunRoot docs/demo/real docs/evidence/client-sessions/codex-v070.json $privateMcpResult --authority docs/evidence/acceptance-authority.json
```

The two environment-variable values are private runtime paths resolved and
displayed at execution; they must not be copied into tracked docs or shell
history intended for publication. Expected: exporter creates exactly seven
files and reports a schema `2.0` manifest with no findings. If destination
exists or validation fails, stop; do not merge partial output.

- [ ] **Step 3: Run public validators and byte checks**

```powershell
python scripts/validate_real_demo.py docs/demo/real
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 docs/evidence/client-sessions/codex-v070.json
git status --short
```

Recompute every artifact SHA-256 and require `final.png` to equal the finalized
source bytes. Open the exported original at full detail once more to ensure the
nominated visual was not swapped or transformed. No optional GIF/upscale is
needed for the ordinary one-image showcase.

- [ ] **Step 4: Commit only validated public evidence**

```powershell
git add docs/demo/real docs/evidence/client-sessions/codex-v070.json
git diff --cached --name-only
git commit -m "docs(demo): add genuine ordinary SDXL result"
```

The staged list must contain no private run, raw transcript, endpoint, trust
state, `outputs/`, model weight, or rejected image.

---

### Task 12: Retain Claude Code Compatibility And Validate The Release Set

**Files:**
- Create: `docs/evidence/client-sessions/claude-code-v070.json`
- Modify only if digest binding requires regeneration:
  `docs/demo/real/showcase-manifest.json`

**Interfaces:**
- Uses the exact installed execution wheel without GPU work.
- Produces one real Claude Code compatibility session plus an aggregate release
  set containing Codex, Claude Code, and one golden-generation session.

- [ ] **Step 1: Announce and enforce the paid-client budget**

Use one Claude Code print session, maximum `$0.25`, no model override, no
generation, no filesystem edit, no browsing, no setup apply, and exactly
readiness plus `get_run` for the finalized public run. Stop on an approval or
context problem; do not expand the budget silently.

- [ ] **Step 2: Create a temporary strict MCP config for the installed CLI**

The private temporary JSON contains only:

```powershell
$privateMcpConfig = Join-Path $candidateRoot "claude-mcp.private.json"
$privateConfigDocument = @{
  mcpServers = @{
    "local-gpu-imagegen" = @{
      command = $cli312
      args = @("serve")
    }
  }
}
$privateConfigDocument | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $privateMcpConfig
```

Resolve the private absolute command at runtime; never track this config.

- [ ] **Step 3: Run one no-persistence Claude Code session**

```powershell
$finalizedRunId = [Environment]::GetEnvironmentVariable("LOCAL_GPU_IMAGEGEN_GOLDEN_RUN_ID")
if (-not $finalizedRunId) { throw "finalized golden run ID is missing" }
claude --print --no-session-persistence --strict-mcp-config --mcp-config $privateMcpConfig --output-format stream-json --max-budget-usd 0.25 --permission-mode dontAsk --allowedTools "mcp__local-gpu-imagegen__local_gpu_imagegen_check,mcp__local-gpu-imagegen__local_gpu_get_run" "Call local_gpu_imagegen_check once and local_gpu_get_run once for finalized run $finalizedRunId. Return only a short result. Do not generate, finalize, edit, browse, or call another tool."
```

If the installed CLI exposes a different exact MCP tool qualifier, discover it
without widening to other tools. Do not use `--dangerously-skip-permissions`.

- [ ] **Step 4: Sanitize and validate the compatibility record**

Set `session_purpose: compatibility`, actual client/wheel/server facts, exact
canonical result hashes, and required omission flags. Validate:

```powershell
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 docs/evidence/client-sessions/claude-code-v070.json
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 --require-release-set docs/evidence/client-sessions/codex-v070.json docs/evidence/client-sessions/claude-code-v070.json
python scripts/validate_real_demo.py docs/demo/real
```

Expected: both individual records pass, release-set findings are empty, and the
demo/client binding remains valid.

- [ ] **Step 5: Remove only private temporary client material**

Delete the specifically resolved temp config/raw Claude transcript only after
the public record validates. Preserve required private provenance according to
the evidence plan; never delete a broad scratch/workspace root.

- [ ] **Step 6: Commit the Claude record**

```powershell
git add docs/evidence/client-sessions/claude-code-v070.json docs/demo/real/showcase-manifest.json
git diff --cached --name-only
git commit -m "docs(evidence): retain 0.7.0 client sessions"
```

Omit `showcase-manifest.json` from `git add` if its bytes did not change.

---

### Task 13: Derive README And Release Materials From Validated Evidence

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `.codex-plugin/plugin.json`
- Modify: `pyproject.toml`
- Modify: `server.json`
- Modify: `docs/demo/README.md`
- Modify: `docs/client-compatibility.md`
- Modify: `docs/github-listing.md`
- Modify: `docs/directory-listings.md`
- Modify: `docs/release-checklist.md`
- Modify: `tests/test_public_docs.py`
- Test: `tests/test_public_docs.py`
- Test: `tests/test_repository_hygiene.py`

**Interfaces:**
- Public claims are derived from the validated manifest and session records,
  not manually inferred from private runs.
- Simulated material remains labeled and secondary.

- [ ] **Step 1: Add evidence-derived README assertions**

When `docs/demo/real` exists, tests must require:

```python
manifest = json.loads(
    (ROOT / "docs/demo/real/showcase-manifest.json").read_text(encoding="utf-8")
)
readme = (ROOT / "README.md").read_text(encoding="utf-8")
self.assertIn("docs/demo/real/final.png", readme)
self.assertIn(manifest["final"]["image_sha256"], readme)
self.assertIn(manifest["route"]["workflow_template_id"], readme)
self.assertLess(
    readme.index("docs/demo/real/final.png"),
    readme.index("docs/demo/preview-loop.gif"),
)
```

Add synchronized assertions for exactly `0.7.0`, fifteen tools, three backends,
ordinary golden route, two experimental routes, two named clients, and pending
9+3/performance/VRAM/production-readiness limitations.

- [ ] **Step 2: Replace the pending README block with the genuine image**

Use the literal path and manifest-derived hash, route, settings, review status,
client, wheel identity, rights, and limitations. Show:

```markdown
![Genuine ordinary-route SDXL result](docs/demo/real/final.png)
```

Do not claim comparative quality, speed, VRAM, concurrency, production
readiness, or general success rates. Keep the simulated GIF below this section
with its disclaimer.

- [ ] **Step 3: Synchronize every release surface**

Update changelog, demo/client docs, GitHub copy, directory listings, package
description, plugin metadata, Registry description, and checklist from exact
validated facts. All must agree on version `0.7.0`, fifteen tools, supported
backends, ordinary SDXL proof, named-client scope, experimental composition,
and open limitations. Do not mark push, CI, PyPI, Registry, tag, release, or
directory submission complete.

- [ ] **Step 4: Run truthfulness, evidence, JSON, and hygiene gates**

```powershell
python -m unittest tests.test_public_docs tests.test_repository_hygiene tests.test_packaging tests.test_validate_real_demo tests.test_validate_client_sessions -v
python scripts/validate_real_demo.py docs/demo/real
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 --require-release-set docs/evidence/client-sessions/codex-v070.json docs/evidence/client-sessions/claude-code-v070.json
$ErrorActionPreference = 'Stop'
$trackedJson = @(git ls-files '*.json')
foreach ($file in $trackedJson) {
  $text = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $file))
  $null = $text | ConvertFrom-Json
}
git diff --check
```

Expected: all pass and every tracked JSON file parses as strict UTF-8.

- [ ] **Step 5: Commit synchronized public materials**

```powershell
git add README.md CHANGELOG.md .codex-plugin/plugin.json pyproject.toml server.json docs/demo/README.md docs/client-compatibility.md docs/github-listing.md docs/directory-listings.md docs/release-checklist.md tests/test_public_docs.py
git commit -m "docs: synchronize 0.7.0 release evidence"
```

---

### Task 14: Freeze The Exact Commit, Build The Final Wheel, And Run The Local Gate

**Files:**
- Create temporarily only: final wheel, two fresh venvs, `SHA256SUMS`, wheel
  entry report, and local gate report.
- Modify: `docs/release-checklist.md`
- Modify ignored: `PROJECT_NODES.md`, `NEXT_SESSION.md`

**Interfaces:**
- Produces one exact final wheel at one exact local commit.
- This task completes implementation readiness only; it does not publish.

- [ ] **Step 1: Run the complete pre-freeze gate**

Run:

```powershell
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
python scripts/verify_mcp.py
python scripts/verify_client_configs.py
python scripts/validate_real_demo.py docs/demo/real
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 --require-release-set docs/evidence/client-sessions/codex-v070.json docs/evidence/client-sessions/claude-code-v070.json
git diff --check
```

Expected: zero failures and only documented Windows link skips. Record actual
counts and outputs without copying historical values.

- [ ] **Step 2: Mark observed local checklist facts before the final freeze**

Update `docs/release-checklist.md` with the just-observed pass/fail facts. Do
not embed a future commit ID or wheel digest. Dynamic identity facts belong in
ignored `PROJECT_NODES.md` and the later `SHA256SUMS`, which avoids changing a
tracked build input after final verification.

- [ ] **Step 3: Commit the checklist and freeze the exact candidate commit**

```powershell
git add docs/release-checklist.md
git commit -m "docs: record 0.7.0 local release gate"
git status --short --branch
$releaseCommit = git rev-parse HEAD
```

Require no tracked changes after the commit. Untracked/ignored private evidence
may exist but must not be staged. From this point through publication
readiness, do not make another tracked change without invalidating and
restarting Steps 3-7.

- [ ] **Step 4: Build final wheel offline from the frozen commit**

Repeat Task 7's build using prefix `local-gpu-imagegen-v070-final-`, then
install and verify from outside the checkout under the existing 3.11 and 3.12
interpreters. Run installed `verify`, both setup dry-runs, `doctor`, and local
wheel `uvx --offline --from ... verify`. Do not run `--apply`.

- [ ] **Step 5: Bind and compare wheel identities truthfully**

Record the final byte size/SHA-256. Compare it to the execution wheel used by
the genuine generation session:

- If identical, record one wheel identity for execution and release.
- If different, record both identities and the exact changed packaged inputs;
  do not claim the execution session used the final wheel.
- If runtime code, schemas, workflows, Skill, or package metadata changed after
  the execution wheel, the final wheel needs a fresh non-GPU installed/client
  verification and plan review. A new GPU run is not inferred automatically.

- [ ] **Step 6: Scan tracked files, index, and wheel contents**

Require no private path, endpoint, credential, raw transcript, trust file,
private/rejected image, `outputs/`, `docs/evidence/runs/`, model weight, or
temporary config in tracked/indexed/wheel entries. Require only the validated
public demo/session artifacts. Recheck `git rev-parse HEAD` equals
`$releaseCommit` and `git status --short` contains no tracked change.

- [ ] **Step 7: Repeat final validators at the frozen commit**

Repeat Step 1 after the final wheel build, plus installed 3.11/3.12 checks.
Any failure blocks the release and invalidates the frozen candidate.

- [ ] **Step 8: Record dynamic identity facts only in ignored continuity**

Update `PROJECT_NODES.md` with exact commit, test counts, Python versions,
wheel bytes and SHA-256, fifteen-tool/protocol result, evidence validators,
control flow, failure modes, and open limitations. Replace `NEXT_SESSION.md`
with the exact publication-readiness handoff and authority boundaries. Write
`SHA256SUMS` beside the temporary wheel. Do not commit another tracked file.

- [ ] **Step 9: Start a new task before publication work**

The conversation will be long and continuity is sufficient. Recommend a new
task at `medium` reasoning for mechanical release preparation, with startup
instruction to read `AGENTS.md`, `PROJECT_NODES.md`, `NEXT_SESSION.md`, the
approved spec, and this plan. Return to `xhigh` for any evidence or authority
conflict.

---

### Task 15: Publish Only Through Separately Authorized, Ordered Gates

**Files:**
- Modify only after observed remote facts: `docs/release-checklist.md`
- Modify ignored: `PROJECT_NODES.md`, `NEXT_SESSION.md`
- Append through `obsidian-evolution`: the current Obsidian daily Codex log.

**Interfaces:**
- Produces public branch/commit, four green CI jobs, exact PyPI artifact,
  official MCP Registry record, immutable tag, GitHub prerelease, verified URLs,
  and optionally later directory submissions.
- Every external mutation below requires explicit authority; one approval does
  not authorize another service/action.

- [ ] **Step 1: Recheck credentials and request GitHub push authority**

Verify the stale deploy key is absent using an authenticated read-only method.
If no safe credential exists, stop and request one bounded flow. Do not install
GitHub CLI without authority. Display branch, commit, staged-file scan, and
remote target before requesting push authority.

- [ ] **Step 2: Push the candidate without tag or release**

After exact GitHub authority, push only the approved branch/commit. Integrate
into `main` only through the separately approved method. Do not move historical
tag `v0.6.0`.

- [ ] **Step 3: Require four green jobs at the exact release commit**

Wait for Windows 3.11, Windows 3.12, Ubuntu 3.11, and Ubuntu 3.12. Cancelled,
skipped, neutral, stale, or red is blocking. Each job must run compile, complete
unit/packaging suite, MCP verify, and named-client config verify. Record exact
run/job URLs and commit.

- [ ] **Step 4: Request and execute PyPI authority separately**

Display exact wheel filename, SHA-256, version, target project, and account
boundary. Publish only the exact final verified artifact. Verify PyPI JSON,
artifact digest, a fresh `uvx local-gpu-imagegen verify`, and the package URL.
Never rebuild after selecting the publication artifact.

- [ ] **Step 5: Request and execute official MCP Registry authority separately**

Validate `server.json` using the official publisher already present; if it is
absent, request install/download authority rather than fetching it. Publish and
verify `io.github.zc4578980-tech/local-gpu-imagegen` version `0.7.0` resolves to
the exact PyPI package and stdio command.

- [ ] **Step 6: Request tag/release/topics authority separately**

Create annotated `v0.7.0` at the exact green commit, push it, create a preview
release with the exact wheel and `SHA256SUMS`, outcome-first notes, genuine
image/evidence links, and limitations, then apply the prepared description and
topics. Verify every URL anonymously.

- [ ] **Step 7: Keep directory submissions separately gated**

`awesome-mcp-servers` and Glama copy remains prepared only. Request explicit
authority for each submission/PR/contact after the repository, package,
Registry, tag, and release resolve. Do not infer submission authority from
release publication.

- [ ] **Step 8: Update records only from observed public state**

Mark only verified checklist items. Update continuity with commit, wheel hash,
CI jobs, URLs, limitations, rollback/removal commands, and pending distribution
work. Run `obsidian-evolution` to append a concise daily log with project links
and no secrets/private paths.

- [ ] **Step 9: Run the final truthfulness check**

Re-run local validators against the tagged source and anonymously verify public
URLs. The release is complete only if code, wheel, PyPI, Registry, tag, release,
README image, client records, and claims agree. Star count is observed later at
7/30/90 days and never reported as guaranteed.

## Final Verification Matrix

| Gate | Exact verification | Blocking result |
|---|---|---|
| MCP surface | `python scripts/verify_mcp.py` | version/protocol mismatch or tool count other than 15 |
| Model-free | `python -m unittest discover -s tests -v` | any failure or unexplained skip |
| Compilation | `python -m compileall -q scripts tests` | any compile error |
| Installed package | isolated 3.11 and 3.12 `verify` outside checkout | source-path dependency, wrong version/protocol/tools |
| First run | local-wheel `uvx --offline --from ... verify` and setup dry-runs | source clone required or config write without `--apply` |
| Real client | `validate_client_sessions.py --require-release-set ...` | missing client, missing generation session, private value, digest/version mismatch |
| Golden demo | `validate_real_demo.py docs/demo/real` | non-ordinary route, unfinalized/ineligible image, altered bytes, bad rights/MCP/client binding |
| Public docs | public-doc/hygiene tests and strict UTF-8 JSON parse | unsupported or inconsistent claim, private path/value |
| Repository | `git diff --check`, status, tracked/staged/wheel scans | dirty release input or private/ignored artifact included |
| CI | four exact OS/Python jobs at release commit | anything other than green |
| Publication | PyPI/Registry/tag/release anonymous resolution | wrong/missing artifact, metadata, commit, or URL |

## Spec Coverage Review

| Approved requirement | Plan coverage |
|---|---|
| Outcome-first promise and literal installed path | Tasks 1-2, 13 |
| Thin unchanged fifteen-tool MCP core | Frozen boundaries, Task 6 |
| Ordinary SDXL golden path with no fallback | Tasks 5, 8-11 |
| Genuine MCP result, original PNG, review, later finalization, export | Tasks 9-11 |
| Codex and Claude Code installed evidence, one generation session | Tasks 3, 9, 11-12 |
| Two-stage/regional retained but experimental | Tasks 1-2, 13 |
| Model-free and isolated installed gates | Tasks 6-7, 14 |
| Synchronized README/package/Registry/listing/release facts | Tasks 2, 13-15 |
| No silent download/model switch/config mutation | All runtime and failure boundaries |
| No push/tag/PyPI/Registry/submission without authority | Task 15 |
| 800 Stars treated as strategy, not release claim | Frozen boundaries, Task 15 |

## Implementation Hand-Off

Execute sequentially in the linked worktree. Do not parallelize runtime
authority gates: route display, GPU generation, review, finalization, export,
and publication must remain ordered so a later confirmation cannot be reused
for a different action. Before implementation begins, obtain approval for this
written plan and remind the user to change reasoning from `xhigh` to `high`.
