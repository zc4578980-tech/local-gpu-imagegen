# v0.8.0 Publication Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an honest, exact-commit v0.8.0 preview candidate whose active release copy, historical evidence, validators, wheel, and local verification agree.

**Architecture:** Keep production code, package version, and the 17-tool MCP surface frozen. Repair release coherence in existing tests, validators, Git attributes, and public documentation; preserve historical 0.7 evidence as historical and preserve strict 9+3 validation as the full-acceptance gate. Build the final wheel only after all local coherence commits are complete.

**Tech Stack:** Python 3.11/3.12, standard-library `unittest`, PowerShell, uv, Git attributes, JSON, Markdown.

## Global Constraints

- Work only in a branch/worktree created from local `main@058718a`; never work directly on `main`.
- Keep package version exactly `0.8.0` and the MCP surface exactly 17 tools.
- Do not add a production module, dependency, MCP tool, model, or backend integration.
- Do not start a real backend, submit GPU work, generate an image, download a model/dependency/interpreter, or mutate real trust/client state.
- Do not relabel the historical 0.7 Codex generation or the v0.8 zero-GPU onboarding record.
- Do not weaken, delete, or redefine the existing `--strict` 9-root plus 3-revision validator.
- Stop at Task 3 until the preview/full-acceptance policy is explicitly approved.
- Treat current-v0.8 hosted-client/GPU evidence and every remote action as separately authorized gates.
- Never rewrite or stage `workflows/comfyui/sdxl-regional-txt2img-v1.json` or `workflows/comfyui/sdxl-two-stage-copy-subject-v1.json`.
- Keep both working-tree and cached diffs for those workflows empty before every commit.
- Preserve ignored outputs, root `.codex/`, private evidence, and archive refs.
- Commit each task independently; stage only the files listed by that task.

## File Map

- `tests/test_public_docs.py`: pins current version/tool count, evidence classes, and release-policy wording.
- `tests/test_repository_hygiene.py`: pins LF checkout behavior for hash-bound public evidence.
- `tests/test_validate_real_demo.py`: covers explicit historical-version validation and retained demo portability.
- `scripts/validate_real_demo.py`: accepts an explicit expected version without changing historical bytes.
- `.gitattributes`: prevents Windows checkout drift in hash-bound demo and client-session text.
- `docs/demo/real/*`: retained 0.7 demo bytes and its hash manifest; content identity remains historical.
- `docs/evidence/client-sessions/*.json`: retained named-client evidence with portable LF bytes.
- `docs/release-checklist.md`: bounded v0.8 local/evidence/publication gates.
- `docs/client-compatibility.md`: configuration versus hosted-session and 0.7 versus 0.8 evidence boundaries.
- `docs/evidence/README.md`: v0.8 preview versus full 9+3 acceptance policy.
- `docs/directory-listings.md`: prepared 0.8 listing copy without false publication state.
- `docs/release-candidate-validation-report.md`: audit basis and final disposition update.

---

### Task 1: Freeze The v0.8 Release-Copy And Evidence-Class Contracts

**Files:**
- Modify: `tests/test_public_docs.py`
- Modify: `docs/release-checklist.md`
- Modify: `docs/client-compatibility.md`

**Interfaces:**
- Consumes: package version `0.8.0`, `PUBLIC_TOOLS` with 17 names, retained `codex-v070.json`, retained `codex-v080-workflow-onboarding.json`.
- Produces: regression tests that reject 0.7/15-tool active release copy and reject evidence relabeling.

- [ ] **Step 1: Add failing release-coherence tests**

Add one test that reads the checklist and compatibility guide and requires these
literal current-release facts:

```python
def test_active_release_guides_pin_v080_and_seventeen_tools(self) -> None:
    for path in (RELEASE_CHECKLIST, ROOT / "docs" / "client-compatibility.md"):
        with self.subTest(path=path):
            text = path.read_text(encoding="utf-8")
            self.assertIn("`0.8.0`", text)
            self.assertIn("exactly seventeen tools", text)
            self.assertNotIn("exactly fifteen tools", text)
```

Add a second test that loads both client records and pins their distinct roles:

```python
def test_retained_client_evidence_keeps_historical_and_current_roles(self) -> None:
    root = ROOT / "docs" / "evidence" / "client-sessions"
    historical = json.loads((root / "codex-v070.json").read_text(encoding="utf-8"))
    onboarding = json.loads(
        (root / "codex-v080-workflow-onboarding.json").read_text(encoding="utf-8")
    )
    self.assertEqual(historical["server"]["version"], "0.7.0")
    self.assertEqual(historical["session_purpose"], "golden_generation")
    self.assertEqual(onboarding["server"]["version"], "0.8.0")
    self.assertEqual(onboarding["session_purpose"], "workflow_onboarding")
```

- [ ] **Step 2: Run the tests and confirm the intended red state**

Run:

```powershell
python -m unittest tests.test_public_docs.PublicDocumentationTests.test_active_release_guides_pin_v080_and_seventeen_tools tests.test_public_docs.PublicDocumentationTests.test_retained_client_evidence_keeps_historical_and_current_roles -v
```

Expected: the evidence-class test passes; the release-guide test fails because
the active guides still say 0.7.0 and fifteen tools.

- [ ] **Step 3: Make the minimum undisputed copy update**

Update the checklist and compatibility guide so active package/setup statements
say `0.8.0` and exactly seventeen tools. Keep these explicit boundaries:

```text
The retained Codex 0.7.0 generation is historical evidence and is not a v0.8 release-set record.
The retained Codex 0.8.0 workflow-onboarding session is zero-GPU evidence and is not generation evidence.
No retained Claude Code hosted session or current-v0.8 named-client generation set exists.
```

Do not decide the strict 9+3 policy in this task.

- [ ] **Step 4: Run the focused green tests**

Run:

```powershell
python -m unittest tests.test_public_docs tests.test_client_configs tests.test_repository_hygiene -v
```

Expected: PASS with no failures.

- [ ] **Step 5: Verify frozen workflows and commit**

Run:

```powershell
git diff --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git add tests/test_public_docs.py docs/release-checklist.md docs/client-compatibility.md
git commit -m "test: freeze v080 release evidence contracts"
```

Expected: both workflow checks return 0; one independent commit is created.

### Task 2: Repair Historical Demo Portability Without Relabeling It

**Files:**
- Modify: `.gitattributes`
- Modify: `scripts/validate_real_demo.py`
- Modify: `tests/test_repository_hygiene.py`
- Modify: `tests/test_validate_real_demo.py`
- Normalize: `docs/demo/real/README.md`
- Normalize: `docs/demo/real/mcp-result.json`
- Normalize: `docs/demo/real/run-manifest.json`
- Normalize: `docs/demo/real/showcase-manifest.json`
- Normalize: `docs/demo/real/transcript.md`
- Normalize: `docs/evidence/client-sessions/codex-v070.json`
- Normalize: `docs/evidence/client-sessions/codex-v080-workflow-onboarding.json`

**Interfaces:**
- Consumes: `validate_real_demo(root: Path) -> list[str]`, retained manifest version `0.7.0`, exact hash metadata in `showcase-manifest.json`.
- Produces: `validate_real_demo(root: Path, *, expected_server_version: str = EXPECTED_SERVER_VERSION) -> list[str]` and CLI `--expected-server-version`.

- [ ] **Step 1: Add failing EOL and historical-version tests**

Extend repository hygiene with:

```python
def test_hash_bound_public_evidence_uses_portable_lf_checkout(self) -> None:
    rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    self.assertIn("docs/demo/real/*.json text eol=lf", rules)
    self.assertIn("docs/demo/real/*.md text eol=lf", rules)
    self.assertIn("docs/evidence/client-sessions/*.json text eol=lf", rules)
```

Extend real-demo validation with:

```python
def test_retained_v070_demo_validates_only_with_explicit_historical_version(self) -> None:
    from validate_real_demo import validate_real_demo

    retained = ROOT / "docs" / "demo" / "real"
    self.assertEqual(
        validate_real_demo(retained, expected_server_version="0.7.0"),
        [],
    )
    self.assertIn(
        "server_version_mismatch",
        validate_real_demo(retained, expected_server_version="0.8.0"),
    )
```

- [ ] **Step 2: Run tests and capture the red findings**

Run:

```powershell
$env:PYTHONPATH='scripts'
python -m unittest tests.test_repository_hygiene.RepositoryHygieneTests.test_hash_bound_public_evidence_uses_portable_lf_checkout tests.test_validate_real_demo.ValidateRealDemoTests.test_retained_v070_demo_validates_only_with_explicit_historical_version -v
```

Expected: FAIL because the attributes and keyword argument do not yet exist.

- [ ] **Step 3: Add explicit version plumbing**

Keep `EXPECTED_SERVER_VERSION = __version__` for new exports and default tests,
but change the validator signature and all internal comparisons to use the
argument:

```python
def validate_real_demo(
    root: Path,
    *,
    expected_server_version: str = EXPECTED_SERVER_VERSION,
) -> list[str]:
    ...
```

Add the CLI option:

```python
parser.add_argument(
    "--expected-server-version",
    default=EXPECTED_SERVER_VERSION,
    help="Exact server version retained by this demo.",
)
findings = validate_real_demo(
    args.root,
    expected_server_version=args.expected_server_version,
)
```

Pass `expected_server_version` to `validate_session` and compare the installed
package to it. Do not infer a version from the current package and do not mutate
the retained manifest.

- [ ] **Step 4: Add EOL policy and normalize the retained text bytes**

Add exactly these rules:

```gitattributes
docs/demo/real/*.json text eol=lf
docs/demo/real/*.md text eol=lf
docs/evidence/client-sessions/*.json text eol=lf
```

Normalize only the listed text files to UTF-8 without BOM and LF line endings.
Recompute their byte sizes and SHA-256 values, then update only the corresponding
`artifacts` entries and `client_session.sha256` in
`docs/demo/real/showcase-manifest.json`. Preserve all semantic fields, especially
`installed_package.version: 0.7.0`, run ID, image hash, route, and rights.

- [ ] **Step 5: Verify historical and current evidence independently**

Run:

```powershell
$env:PYTHONPATH='scripts'
python scripts/validate_real_demo.py docs/demo/real --expected-server-version 0.7.0
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 docs/evidence/client-sessions/codex-v070.json
python scripts/validate_client_sessions.py --expected-server-version 0.8.0 docs/evidence/client-sessions/codex-v080-workflow-onboarding.json
python -m unittest tests.test_validate_real_demo tests.test_validate_client_sessions tests.test_repository_hygiene -v
```

Expected: every command exits 0; the demo report contains `"ok": true`; each
client record has no findings.

- [ ] **Step 6: Verify exact staged scope and commit**

Run the frozen workflow checks, stage only Task 2 files, inspect `git diff
--cached --stat` and `git diff --cached`, then commit:

```powershell
git commit -m "fix: preserve historical demo bytes across checkout"
```

Expected: no historical semantic identity changes and no workflow diff.

### Task 3: Approve And Encode The Preview Versus Full-Acceptance Policy

**Files:**
- Modify: `tests/test_public_docs.py`
- Modify: `tests/test_validate_acceptance_evidence.py`
- Modify: `docs/evidence/README.md`
- Modify: `docs/release-checklist.md`

**Interfaces:**
- Consumes: existing `validate_evidence(..., strict=True)` exact 9+3 behavior; audit report recommendation.
- Produces: an approved policy statement that distinguishes the bounded v0.8 preview gate from full acceptance without changing strict validation.

- [ ] **Step 1: Stop and request the policy decision**

Present this exact recommended decision for approval:

```text
For v0.8.0 Preview, require exact-commit model-free tests, clean wheel install,
17-tool verification, fail-closed doctor behavior, safe named-client setup
contracts, a portable historical 0.7 generation demo labeled historical, a
v0.8 zero-GPU onboarding record labeled non-generation, and explicit missing
evidence. Keep --strict 9+3 unchanged as the full-acceptance/v1.0 gate.
```

Do not continue without explicit approval. If rejected, return to design review;
do not invent a replacement gate during implementation.

- [ ] **Step 2: Add failing policy-contract tests after approval**

Add a docs test requiring the phrases `v0.8 preview gate`, `full-acceptance/v1.0
gate`, and `does not establish current-v0.8 GPU generation`. Add or retain a
strict-validator test that builds the complete fixture matrix and asserts:

```python
result = validate_evidence(root, FIXTURE_PATH, strict=True)
self.assertTrue(result["release_ready"])
self.assertEqual(result["run_count"], 9)
self.assertEqual(result["revision_count"], 3)
```

Run the focused tests. Expected: docs test FAIL; strict behavior test PASS.

- [ ] **Step 3: Update policy copy only**

Document the approved preview gate in `docs/evidence/README.md` and
`docs/release-checklist.md`. Keep the exact command and semantics of:

```powershell
python scripts/validate_acceptance_evidence.py --strict
```

State that its current failure is expected for v0.8 preview and blocks a
full-acceptance/v1.0 claim, not the separately defined preview cut.

- [ ] **Step 4: Run policy and validator regression tests**

Run:

```powershell
python -m unittest tests.test_public_docs tests.test_validate_acceptance_evidence -v
python scripts/validate_acceptance_evidence.py
python scripts/validate_acceptance_evidence.py --strict
```

Expected: unit tests PASS; non-strict command exits 0 with zero roots and
`release_ready: false`; strict command exits 1 with `missing_run_evidence`.

- [ ] **Step 5: Commit the policy split independently**

Verify both frozen workflow diffs are empty, stage only the four Task 3 files,
review the staged diff, and commit:

```powershell
git commit -m "docs: separate preview and full acceptance gates"
```

### Task 4: Synchronize Checklist, Compatibility, And Directory Copy

**Files:**
- Modify: `tests/test_public_docs.py`
- Modify: `tests/test_repository_hygiene.py`
- Modify: `docs/release-checklist.md`
- Modify: `docs/client-compatibility.md`
- Modify: `docs/directory-listings.md`
- Modify: `docs/evidence/README.md`

**Interfaces:**
- Consumes: approved Task 3 policy, version `0.8.0`, 17-tool inventory, actual retained evidence classes.
- Produces: mutually consistent active release documents with prepared-only remote copy.

- [ ] **Step 1: Add failing cross-document assertions**

Add a test that requires every active release document to contain `0.8.0`, and
requires checklist/compatibility to contain `exactly seventeen tools`. Add
directory assertions:

```python
self.assertIn("local-gpu-imagegen==0.8.0", listings)
self.assertIn("Status: prepared, not submitted", listings)
self.assertNotIn("local-gpu-imagegen==0.7.0", listings)
self.assertNotIn("Status: submitted", listings)
```

Also require the listing limitations to say that no current-v0.8 hosted-client
generation release set and no complete 9+3 acceptance are claimed.

- [ ] **Step 2: Run the red tests**

Run:

```powershell
python -m unittest tests.test_public_docs tests.test_repository_hygiene -v
```

Expected: FAIL on stale directory and any remaining active copy.

- [ ] **Step 3: Synchronize the four documents**

Use these shared facts everywhere:

```text
Version: 0.8.0
MCP tools: exactly seventeen
Backends: existing ComfyUI, AUTOMATIC1111/Forge, or Diffusers installations
Primary offer: supported ordinary ComfyUI API workflow onboarding and execution
Historical generation: Codex 0.7.0, retained and labeled historical
Current onboarding: Codex 0.8.0, retained, zero-GPU, non-generation
Missing: Claude Code hosted session, current-v0.8 generation release set, full 9+3
Remote state: prepared, not submitted or published by this plan
```

Do not say the PyPI package, Registry record, tag, Release, or directory entry
already exists.

- [ ] **Step 4: Run focused and claim-scanner tests**

Run:

```powershell
python -m unittest tests.test_public_docs tests.test_repository_hygiene tests.test_client_configs -v
python scripts/verify_client_configs.py
```

Expected: all tests PASS and verifier reports `hosted_client_session: false`.

- [ ] **Step 5: Commit synchronized release copy**

Verify frozen workflows, stage only Task 4 files, inspect the staged diff, and
commit:

```powershell
git commit -m "docs: synchronize v080 publication copy"
```

### Task 5: Build And Validate The Final Exact-Commit Wheel

**Files:**
- Modify: `docs/release-candidate-validation-report.md`
- Generate ignored: `outputs/release-candidate-validation/final-wheel/*`
- Generate ignored: `outputs/release-candidate-validation/final-venv/*`

**Interfaces:**
- Consumes: final local candidate commit after Tasks 1-4.
- Produces: one exact wheel digest and checkout-external Python 3.12 verification record.

- [ ] **Step 1: Run the full model-free source verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
python scripts/validate_social_preview.py
python scripts/verify_mcp.py
python scripts/verify_client_configs.py
python scripts/validate_real_demo.py docs/demo/real --expected-server-version 0.7.0
python scripts/validate_acceptance_evidence.py
git diff --check
```

Expected: all commands exit 0; acceptance remains structurally valid with
`release_ready: false`.

- [ ] **Step 2: Build one final wheel offline**

Run from a clean tracked worktree:

```powershell
$python312 = uv python find 3.12 --no-python-downloads
uv build --wheel --offline --no-python-downloads --python $python312 --out-dir outputs/release-candidate-validation/final-wheel
```

Expected: exactly one `local_gpu_imagegen-0.8.0-py3-none-any.whl`.

- [ ] **Step 3: Inspect wheel identity and contents**

Record SHA-256 and size. Require version `0.8.0`, Python `>=3.11`, zero runtime
dependencies, no weights, private paths, credentials, `outputs/`, or build
directories, and the expected package assets.

- [ ] **Step 4: Install exact bytes outside the checkout**

Create a fresh uv Python 3.12 environment under the ignored validation root and
install with `--offline --no-index --no-deps`. From that environment run:

```powershell
local-gpu-imagegen verify
local-gpu-imagegen doctor
local-gpu-imagegen setup codex
local-gpu-imagegen setup claude-code
python -c "import compileall, pathlib, local_gpu_imagegen; root = pathlib.Path(local_gpu_imagegen.__file__).parent; raise SystemExit(0 if compileall.compile_dir(root, quiet=1) else 1)"
```

For `doctor`, override both backend URLs to unused loopback port 1 and require
exit 1 with `ready: false`. For setup, use fake client executables and require
`applied: false`; never invoke a real client executable. Resolve the installed
site-packages path from the fresh environment rather than writing a user path
into tracked files.

- [ ] **Step 5: Update the audit report with final facts**

Replace the preliminary wheel section with final candidate commit, wheel hash,
size, entry count, verification outputs, and the explicit Python 3.11 local
limitation. Do not call the wheel published.

- [ ] **Step 6: Commit the final local validation record**

Verify frozen workflow working/cached diffs, ignored artifact status, and
`git diff --check`. Stage only the report and commit:

```powershell
git commit -m "docs: record final v080 candidate validation"
```

### Task 6: Hold Named-Client, GPU, CI, And Publication Gates

**Files:**
- Modify only after each approved action: `docs/release-checklist.md`
- Create only after formal Release publication: one campaign directory under `docs/evidence/adoption/`
- Append only after observation: that campaign directory's `events.jsonl`

**Interfaces:**
- Consumes: exact final candidate commit and wheel digest from Task 5.
- Produces: separately authorized evidence or publication state; this task does not grant authority itself.

- [ ] **Step 1: Stop for current-v0.8 named-client/GPU evidence authority**

Do not start a backend or mutate a client. Ask separately whether to retain:

```text
1. Claude Code zero-GPU onboarding evidence at the exact candidate commit.
2. A current-v0.8 named-client GPU generation record using an already authorized route.
```

Neither is mandatory under the recommended preview gate unless the approved
Task 3 policy says otherwise.

- [ ] **Step 2: Require exact-commit CI authority and results**

Push only after approval. Require Windows and Ubuntu jobs on Python 3.11 and
3.12 at the exact candidate commit. A Python 3.11 CI failure reopens the local
candidate; do not waive it because local 3.12 passed.

- [ ] **Step 3: Request each publication action separately**

The authority list is:

```text
push candidate commit
publish exact wheel to PyPI without rebuild
verify public PyPI digest
publish MCP Registry record
create tag v0.8.0
create GitHub Preview Release
change GitHub repository metadata/social preview
submit each third-party directory entry
```

Do not combine absence of objection with approval.

- [ ] **Step 4: Revalidate public identity after any approved publication**

Require the public package, Registry, tag, Release, and evidence URLs to resolve
to the exact candidate state. Any digest or version mismatch stops publication.

- [ ] **Step 5: Initialize adoption measurement only after formal Release**

Within five minutes when possible, run the existing baseline command and commit
the append-only campaign evidence. This records repository-level Star totals
only and does not change the release gate.

## Final Verification Gate

Before proposing a fast-forward merge, run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
python scripts/validate_social_preview.py
python scripts/verify_mcp.py
python scripts/verify_client_configs.py
python scripts/validate_real_demo.py docs/demo/real --expected-server-version 0.7.0
python scripts/validate_client_sessions.py --expected-server-version 0.7.0 docs/evidence/client-sessions/codex-v070.json
python scripts/validate_client_sessions.py --expected-server-version 0.8.0 docs/evidence/client-sessions/codex-v080-workflow-onboarding.json
python scripts/validate_acceptance_evidence.py
git diff --check
git diff --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
```

Expected: all commands exit 0, exactly 17 tools, version `0.8.0`, zero frozen
workflow diffs, and non-strict acceptance remains honest with
`release_ready: false`. The separately invoked strict validator must still fail
on the incomplete real 9+3 matrix until that evidence actually exists.
