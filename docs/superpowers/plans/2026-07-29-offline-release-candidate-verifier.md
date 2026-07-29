# Offline Release-Candidate Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one offline, fail-closed maintainer command that proves an exact wheel, checkout commit, installed CLI, PyPI metadata, and MCP Registry descriptor agree before any publication action.

**Architecture:** Keep pure candidate inspection in a non-packaged helper module and expose it through a thin standalone validator script. Static checks run before any subprocess installation; installed checks use a temporary Python 3.12 `venv` outside the checkout and the exact supplied wheel. Every check returns a bounded structured result, and the CLI prints or atomically records one sanitized JSON report without rebuilding, downloading, or publishing anything.

**Tech Stack:** Python 3.11-compatible source, Python 3.12 release environment, standard library (`argparse`, `email`, `hashlib`, `json`, `pathlib`, `subprocess`, `tempfile`, `tomllib`, `venv`, `zipfile`), `unittest`, Git CLI.

## Global Constraints

- Keep Local GPU Imagegen at version `0.8.0`, MCP protocol `2024-11-05`, and exactly 17 tools.
- The validator consumes one already-built `local_gpu_imagegen-0.8.0-py3-none-any.whl`; it never builds or publishes an artifact.
- Candidate verification is offline: no Python, package, dependency, model, or workflow download.
- Installation must use `python -m pip install --no-index --no-deps --no-cache-dir --disable-pip-version-check` against the exact wheel.
- PyPI publication, MCP Registry publication, push, tag, GitHub Release, metadata changes, and directory submissions remain separate authority gates.
- Normal tests must not use a GPU, backend, model, network, or real client configuration.
- Reports must not expose credentials, personal absolute paths, private model paths, private run paths, or tracebacks.
- Follow RED/GREEN TDD and commit each independently reviewable task.

---

## File Map

- Create `scripts/release_candidate_checks.py`: pure static/archive checks, installed-environment orchestration, result assembly, and atomic report writing.
- Create `scripts/validate_release_candidate.py`: argument parsing, repository-root selection, bounded exception handling, JSON output, and exit status.
- Create `tests/test_release_candidate_checks.py`: focused unit tests for checkout, wheel, metadata, archive, subprocess, sanitization, and atomicity behavior.
- Create `tests/test_validate_release_candidate.py`: CLI JSON/exit-code tests with injected validation boundaries.
- Modify `tests/test_packaging.py`: one real wheel integration through the validator library after the package wheel already exists.
- Create `docs/publication-runbook.md`: exact offline verification and later separately authorized publication sequence.
- Modify `docs/launch-playbook.md`: link the operator runbook and require a passed candidate report.
- Modify `docs/release-checklist.md`: add the local verifier command/report as an unchecked exact-candidate gate until it passes.
- Modify `tests/test_public_docs.py`: pin the runbook command, offline boundary, and separate publication gates.
- Modify `PROJECT_NODES.md` and `NEXT_SESSION.md` after exact-commit verification; these files remain ignored and local.

---

### Task 1: Static Checkout, Wheel, And Registry Contract

**Files:**
- Create: `scripts/release_candidate_checks.py`
- Create: `tests/test_release_candidate_checks.py`

**Interfaces:**
- Consumes: repository root `Path`, wheel `Path`, expected 40-character commit, expected 64-character lowercase SHA-256, and an injectable subprocess runner.
- Produces: `inspect_checkout(...) -> tuple[list[dict[str, object]], dict[str, object]]`, `inspect_wheel(...) -> tuple[list[dict[str, object]], dict[str, object]]`, and `blocked_check(check_id, code) -> dict[str, object]`.

- [ ] **Step 1: Write failing input and checkout tests**

Add tests that create a temporary Git repository and require exact lower-case
hash syntax, exact `HEAD`, clean tracked/index state, and bounded reporting of
untracked files:

```python
def make_git_checkout(self) -> tuple[Path, str]:
    root = self.temp / f"checkout-{uuid.uuid4().hex}"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    (root / "tracked.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    return root, commit


def test_checkout_requires_exact_head_and_clean_tracked_state(self) -> None:
    root, commit = self.make_git_checkout()
    checks, facts = checks.inspect_checkout(root, commit)
    self.assertTrue(all(item["status"] == "passed" for item in checks))
    self.assertEqual(facts["commit"], commit)

    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    failed, _ = checks.inspect_checkout(root, commit)
    self.assertIn("tracked_worktree_dirty", self.codes(failed))

def test_checkout_reports_untracked_without_blocking(self) -> None:
    root, commit = self.make_git_checkout()
    (root / ".codex").mkdir()
    (root / ".codex" / "config.toml").write_text("local = true\n", encoding="utf-8")
    results, facts = checks.inspect_checkout(root, commit)
    self.assertNotIn("untracked_files", self.blocked_ids(results))
    self.assertEqual(facts["untracked_count"], 1)
```

- [ ] **Step 2: Run the checkout tests and verify RED**

Run:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateStaticTests -v
```

Expected: import failure because `scripts/release_candidate_checks.py` does not
exist.

- [ ] **Step 3: Implement result primitives and checkout inspection**

Create these fixed primitives and fail-closed Git checks:

```python
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def passed_check(check_id: str, **observation: object) -> dict[str, object]:
    return {"id": check_id, "status": "passed", "observation": observation}


def blocked_check(check_id: str, code: str) -> dict[str, object]:
    return {"id": check_id, "status": "blocked", "code": code}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        timeout=30, check=False,
    )


def inspect_checkout(
    root: Path, expected_commit: str
) -> tuple[list[dict[str, object]], dict[str, object]]:
    # Validate expected_commit before invoking Git. Require rev-parse HEAD,
    # git diff --quiet, git diff --cached --quiet, and status --porcelain=v1.
    # Only non-?? status lines block. Report untracked_count and at most 20
    # normalized repository-relative names.
```

Git stderr must map to `git_checkout_unavailable`; mismatched `HEAD` maps to
`candidate_commit_mismatch`; tracked or staged changes map to
`tracked_worktree_dirty` and `index_dirty`.

- [ ] **Step 4: Run checkout tests and verify GREEN**

Run the command from Step 2.

Expected: checkout tests pass with no network or external state mutation.

- [ ] **Step 5: Write failing wheel and descriptor tests**

Create synthetic wheels with `zipfile.ZipFile` and test:

```python
def make_release_root(self) -> Path:
    root = self.temp / f"release-{uuid.uuid4().hex}"
    root.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copy2(ROOT / "server.json", root / "server.json")
    return root


def make_wheel(self, root: Path, *, extra_entry: str | None = None) -> Path:
    wheel = root / "local_gpu_imagegen-0.8.0-py3-none-any.whl"
    metadata = (
        "Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
        "Requires-Python: >=3.11\n\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("local_gpu_imagegen/__init__.py", '__version__ = "0.8.0"\n')
        archive.writestr("local_gpu_imagegen-0.8.0.dist-info/METADATA", metadata)
        archive.writestr("local_gpu_imagegen-0.8.0.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
        archive.writestr("local_gpu_imagegen-0.8.0.dist-info/RECORD", "")
        if extra_entry is not None:
            archive.writestr(extra_entry, "fixture")
    return wheel


def sha(self, path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_wheel_binds_hash_metadata_and_registry_descriptor(self) -> None:
    root = self.make_release_root()
    wheel = self.make_wheel(root)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    results, facts = checks.inspect_wheel(root, wheel, digest)
    self.assertEqual(self.blocked_ids(results), set())
    self.assertEqual(facts["version"], "0.8.0")
    self.assertEqual(facts["registry_identifier"], "local-gpu-imagegen")

def test_wheel_rejects_traversal_link_weights_and_private_entries(self) -> None:
    for entry in (
        "../escape.py",
        "C:/absolute.py",
        "models/private.safetensors",
        "outputs/runs/private.json",
    ):
        with self.subTest(entry=entry):
            root = self.make_release_root()
            wheel = self.make_wheel(root, extra_entry=entry)
            results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
            self.assertIn("unsafe_wheel_entry", self.codes(results))
```

Also test wrong filename, wrong expected hash, duplicate/missing `.dist-info`,
wrong `Requires-Python`, nonempty `Requires-Dist`, `pyproject.toml` drift,
`server.json` drift, ZIP symlink attributes, backslashes, oversized entry count,
oversized uncompressed bytes, and embedded `C:\\Users\\` or `/home/` paths.

- [ ] **Step 6: Run wheel tests and verify RED**

Run:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests -v
```

Expected: failures because `inspect_wheel` and archive policies are absent.

- [ ] **Step 7: Implement bounded wheel and metadata inspection**

Implement:

```python
EXPECTED_WHEEL = "local_gpu_imagegen-0.8.0-py3-none-any.whl"
EXPECTED_VERSION = "0.8.0"
EXPECTED_REQUIRES_PYTHON = ">=3.11"
MAX_ENTRIES = 256
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


def inspect_wheel(
    root: Path, wheel: Path, expected_sha256: str
) -> tuple[list[dict[str, object]], dict[str, object]]:
    # lstat and reject non-regular files/reparse links; stream SHA-256;
    # validate normalized PurePosixPath entries, ZIP mode, size ceilings,
    # one local_gpu_imagegen-0.8.0.dist-info set, METADATA/WHEEL/RECORD;
    # parse METADATA through email.parser.BytesParser;
    # parse pyproject.toml and server.json with strict type checks;
    # return sanitized facts only.
```

Require `server.json` to contain one PyPI package with identifier
`local-gpu-imagegen`, version `0.8.0`, `runtimeHint: uvx`, positional `serve`,
and `transport.type: stdio`. Read archive text only under the size ceiling and
scan for credential markers and personal absolute-path patterns without
returning matched content.

- [ ] **Step 8: Run all static tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

Expected: all static tests pass.

- [ ] **Step 9: Commit the static contract**

```powershell
git add scripts/release_candidate_checks.py tests/test_release_candidate_checks.py
git commit -m "feat: validate release candidate statically"
```

---

### Task 2: Checkout-External Installed-Wheel Verification

**Files:**
- Modify: `scripts/release_candidate_checks.py`
- Modify: `tests/test_release_candidate_checks.py`

**Interfaces:**
- Consumes: `run_installed_checks(wheel: Path, python: Path, *, runner=subprocess.run) -> tuple[list[dict[str, object]], dict[str, object]]`.
- Produces: installed version, protocol, ordered tool names/count, doctor exit/readiness, Codex/Claude dry-run states, and compiled-source count without retaining the temporary environment.

- [ ] **Step 1: Write failing subprocess-boundary tests**

Patch `venv.EnvBuilder.create` and the module subprocess runner to verify exact
commands, environment, cwd, timeout, and failure mappings:

```python
class RecordingRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[str]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(kwargs)))
        if not self.responses:
            raise AssertionError(f"unexpected subprocess: {command}")
        return self.responses.pop(0)


def test_install_uses_exact_offline_wheel_and_scrubbed_environment(self) -> None:
    runner = RecordingRunner(self.valid_completed_processes())
    checks.run_installed_checks(self.wheel, self.python, runner=runner)
    install = next(command for command, _ in runner.calls if "install" in command)
    self.assertIn("--no-index", install)
    self.assertIn("--no-deps", install)
    install_call = next(call for call in runner.calls if "install" in call[0])
    self.assertIn("--no-cache-dir", install_call[0])
    self.assertNotIn("PYTHONPATH", install_call[1]["env"])
    self.assertNotEqual(Path(install_call[1]["cwd"]), ROOT)

def test_installed_contract_requires_exact_version_protocol_and_tools(self) -> None:
    responses = self.valid_responses()
    responses["verify"]["tools"] = responses["verify"]["tools"][:-1]
    runner = RecordingRunner(self.completed_processes(responses))
    results, _ = checks.run_installed_checks(self.wheel, self.python, runner=runner)
    self.assertIn("installed_tool_contract_mismatch", self.codes(results))
```

Test pip failure, malformed JSON, timeout, wrong CLI version/protocol/tool order,
doctor exit/readiness mismatch, setup mutation, marker creation, compile failure,
and cleanup after exceptions.

- [ ] **Step 2: Run installed-boundary tests and verify RED**

Run:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateInstalledTests -v
```

Expected: failures because `run_installed_checks` is absent.

- [ ] **Step 3: Implement temporary environment and command helpers**

Add:

```python
EXPECTED_TOOLS = (
    "local_gpu_branch_run",
    "local_gpu_cleanup_run",
    "local_gpu_confirm_mask",
    "local_gpu_discover_models",
    "local_gpu_finalize_run",
    "local_gpu_generate_image",
    "local_gpu_generate_round",
    "local_gpu_get_run",
    "local_gpu_imagegen_check",
    "local_gpu_inspect_workflow",
    "local_gpu_list_profiles",
    "local_gpu_prepare_mask",
    "local_gpu_recommend_models",
    "local_gpu_record_review",
    "local_gpu_register_workflow",
    "local_gpu_set_model_trust",
    "local_gpu_start_run",
)


def _run_json(
    command: list[str], *, cwd: Path, env: dict[str, str], expected_exit: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    completed = runner(
        command, cwd=cwd, env=env, capture_output=True, text=True,
        timeout=60, check=False,
    )
    # Reject the wrong exit, empty/oversized output, malformed/non-object JSON,
    # and stderr that contains a traceback.


def run_installed_checks(
    wheel: Path, python: Path, *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    # Require Python 3.12; TemporaryDirectory outside the checkout;
    # venv.EnvBuilder(with_pip=True); exact no-index installation;
    # fake Codex/Claude binaries; verify, doctor, setup dry-runs, compileall.
```

Before creating the environment, invoke the supplied interpreter with
`-c "import json,sys; print(json.dumps(list(sys.version_info[:2])))"` and require
exact output `[3, 12]`. A missing interpreter, malformed output, timeout, or any
other version maps to `release_python_312_required` without creating a venv.

Use an environment copied from `os.environ` with `PYTHONPATH`, `PYTHONHOME`,
`PIP_INDEX_URL`, and `PIP_EXTRA_INDEX_URL` removed. Set
`PIP_NO_INDEX=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1`,
`LOCAL_GPU_IMAGEGEN_WEBUI_URL=http://127.0.0.1:1`, and
`LOCAL_GPU_IMAGEGEN_COMFYUI_URL=http://127.0.0.1:1`.

Create fake client commands in a temporary `fake-bin`: `--version` succeeds,
`mcp get` reports absent, and `mcp add` writes a marker. Invoke only setup
without `--apply`; require `status: planned`, `applied: false`, and no marker.

- [ ] **Step 4: Run installed-boundary tests and verify GREEN**

Run the command from Step 2.

Expected: all installed-boundary tests pass.

- [ ] **Step 5: Extend the existing real packaging integration**

In `tests/test_packaging.py`, import the helper module from `scripts` and reuse
the wheel built in `setUpClass`:

```python
def test_release_candidate_installed_checks_pass_for_real_wheel(self) -> None:
    results, facts = release_candidate_checks.run_installed_checks(
        self.wheel, Path(sys.executable)
    )
    self.assertFalse(
        [item for item in results if item["status"] == "blocked"],
        results,
    )
    self.assertEqual(facts["version"], "0.8.0")
    self.assertEqual(facts["protocol"], "2024-11-05")
    self.assertEqual(facts["tool_count"], 17)
```

Use the current test Python instead of a global interpreter. Mark this new
integration with `@unittest.skipUnless(sys.version_info[:2] == (3, 12),
"release verifier requires Python 3.12")`, so Windows and Ubuntu Python 3.12
exercise the exact release contract while Python 3.11 continues to prove the
supported runtime through the existing installed-wheel tests.

- [ ] **Step 6: Run packaging and helper tests**

```powershell
python -m unittest tests.test_release_candidate_checks tests.test_packaging -v
```

Expected: all tests pass; no backend, client state, or network is used.

- [ ] **Step 7: Commit installed verification**

```powershell
git add scripts/release_candidate_checks.py tests/test_release_candidate_checks.py tests/test_packaging.py
git commit -m "feat: verify installed release wheel offline"
```

---

### Task 3: Fail-Closed CLI And Atomic JSON Report

**Files:**
- Modify: `scripts/release_candidate_checks.py`
- Create: `scripts/validate_release_candidate.py`
- Create: `tests/test_validate_release_candidate.py`
- Modify: `tests/test_release_candidate_checks.py`

**Interfaces:**
- Consumes: the four required CLI arguments from the approved design.
- Produces: `validate_candidate(...) -> dict[str, object]`, `canonical_report(report) -> bytes`, `atomic_write_report(path, encoded) -> None`, stdout JSON, and exit `0` for `passed` or `1` for `blocked`.

- [ ] **Step 1: Write failing orchestration and report tests**

```python
def test_candidate_runs_static_checks_before_installed_checks(self) -> None:
    with patch.object(checks, "run_installed_checks") as installed:
        report = checks.validate_candidate(
            root=self.root,
            wheel=self.wheel,
            expected_commit="0" * 40,
            expected_wheel_sha256=self.sha(self.wheel),
            python=Path(sys.executable),
        )
    self.assertEqual(report["status"], "blocked")
    installed.assert_not_called()

def test_atomic_report_failure_preserves_existing_file(self) -> None:
    destination = self.root / "report.json"
    destination.write_bytes(b"original\n")
    with patch("release_candidate_checks.os.replace", side_effect=OSError("failed")):
        with self.assertRaises(OSError):
            checks.atomic_write_report(destination, b"replacement\n")
    self.assertEqual(destination.read_bytes(), b"original\n")
```

Also require sorted unique check IDs, `status: passed` only when every check
passes, canonical ASCII JSON, bounded error codes, and no exception text or
absolute path leakage.

- [ ] **Step 2: Run orchestration tests and verify RED**

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateReportTests -v
```

Expected: failures because orchestration and atomic reporting are absent.

- [ ] **Step 3: Implement orchestration and atomic report writing**

```python
def canonical_report(report: dict[str, object]) -> bytes:
    return (
        json.dumps(
            report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
        )
        + "\n"
    ).encode("ascii")


def atomic_write_report(destination: Path, encoded: bytes) -> None:
    # Require an existing regular parent, reject a symlink/reparse destination,
    # create an exclusive same-directory pending file, flush and fsync it,
    # then os.replace. Remove only the owned pending file on failure.


def validate_candidate(
    *, root: Path, wheel: Path, expected_commit: str,
    expected_wheel_sha256: str, python: Path
) -> dict[str, object]:
    # Run input/checkout/wheel checks first. Skip installed work if any block.
    # Otherwise run installed checks. Return schema_version, status, candidate,
    # checks, and next_action with sanitized values only.


def blocked_runtime_report(code: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "blocked",
        "candidate": None,
        "checks": [blocked_check("runtime", code)],
        "next_action": "fix_candidate_validation_and_rerun",
    }
```

- [ ] **Step 4: Run report tests and verify GREEN**

Run the command from Step 2.

Expected: report tests pass.

- [ ] **Step 5: Write failing CLI tests**

Patch only `validate_candidate` and assert the real parser/output boundary:

```python
def test_cli_returns_zero_and_identical_stdout_and_report_for_pass(self) -> None:
    exit_code, stdout = self.run_main(self.passed_report(), report_path=self.report)
    self.assertEqual(exit_code, 0)
    self.assertEqual(stdout, self.report.read_bytes())

def test_cli_returns_bounded_blocked_json_without_traceback(self) -> None:
    exit_code, stdout = self.run_main(
        side_effect=OSError("C:\\Users\\private\\secret")
    )
    self.assertEqual(exit_code, 1)
    report = json.loads(stdout)
    self.assertEqual(report["status"], "blocked")
    self.assertNotIn(b"C:\\Users", stdout)
```

Define the in-process CLI harness explicitly:

```python
class StdoutCapture:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


def run_main(
    self,
    report: dict[str, object] | None = None,
    *,
    report_path: Path | None = None,
    side_effect: BaseException | None = None,
) -> tuple[int, bytes]:
    arguments = [
        "validate_release_candidate.py",
        "--wheel", str(self.wheel),
        "--expected-commit", "a" * 40,
        "--expected-wheel-sha256", "b" * 64,
        "--python", sys.executable,
    ]
    if report_path is not None:
        arguments.extend(["--report", str(report_path)])
    capture = StdoutCapture()
    validator = patch.object(
        cli,
        "validate_candidate",
        return_value=report,
        side_effect=side_effect,
    )
    with validator, patch.object(sys, "argv", arguments), patch.object(sys, "stdout", capture):
        exit_code = cli.main()
    return exit_code, capture.buffer.getvalue()
```

Test malformed hashes before work, missing/nonfile Python, report destination
failure, and unknown arguments.

- [ ] **Step 6: Run CLI tests and verify RED**

```powershell
python -m unittest tests.test_validate_release_candidate -v
```

Expected: import or file-not-found failure because the CLI does not exist.

- [ ] **Step 7: Implement the thin CLI**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-wheel-sha256", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = validate_candidate(
            root=root,
            wheel=args.wheel,
            expected_commit=args.expected_commit,
            expected_wheel_sha256=args.expected_wheel_sha256,
            python=args.python,
        )
        encoded = canonical_report(report)
        if args.report is not None:
            atomic_write_report(args.report, encoded)
    except (OSError, ValueError, subprocess.SubprocessError):
        report = blocked_runtime_report("candidate_validation_failed")
        encoded = canonical_report(report)
    sys.stdout.buffer.write(encoded)
    return 0 if report["status"] == "passed" else 1
```

Do not print raw exception strings. Argument-parser errors retain argparse exit
`2`; validation failures return structured JSON and exit `1`.

- [ ] **Step 8: Run all focused verifier tests and verify GREEN**

```powershell
python -m unittest tests.test_release_candidate_checks tests.test_validate_release_candidate tests.test_packaging -v
python -m compileall -q scripts tests
```

Expected: all focused tests pass and compilation is silent.

- [ ] **Step 9: Commit the CLI**

```powershell
git add scripts/release_candidate_checks.py scripts/validate_release_candidate.py tests/test_release_candidate_checks.py tests/test_validate_release_candidate.py
git commit -m "feat: add offline release candidate command"
```

---

### Task 4: Operator Runbook And Public Contract

**Files:**
- Create: `docs/publication-runbook.md`
- Modify: `docs/launch-playbook.md`
- Modify: `docs/release-checklist.md`
- Modify: `tests/test_public_docs.py`

**Interfaces:**
- Consumes: `validate_release_candidate.py` JSON contract and the separately authorized publication sequence.
- Produces: one copyable PowerShell verification path and explicit stop points before push, PyPI, Registry, tag, Release, metadata, and directory actions.

- [ ] **Step 1: Write failing public-document assertions**

Add `PUBLICATION_RUNBOOK = ROOT / "docs" / "publication-runbook.md"` and require:

```python
def test_publication_runbook_binds_exact_offline_candidate_before_remote_actions(self) -> None:
    runbook = PUBLICATION_RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "validate_release_candidate.py",
        "--expected-commit",
        "--expected-wheel-sha256",
        "--python",
        '"status": "passed"',
        "does not build",
        "does not download",
        "does not publish",
        "separate approval",
        "PyPI",
        "MCP Registry",
    ):
        self.assertIn(required, runbook)
```

Require the launch playbook to link the runbook and the checklist to keep the
candidate report unchecked until a final exact commit passes.

- [ ] **Step 2: Run the public-document tests and verify RED**

```powershell
python -m unittest tests.test_public_docs -v
```

Expected: failures for the absent runbook and contract references.

- [ ] **Step 3: Write the bounded runbook and active links**

The runbook must provide this copyable offline flow:

```powershell
$python312 = uv python find 3.12 --no-python-downloads
$commit = $env:RELEASE_CANDIDATE_COMMIT
$expectedWheelSha256 = $env:RELEASE_CANDIDATE_WHEEL_SHA256
if ($commit -notmatch '^[0-9a-f]{40}$') { throw 'Missing frozen release commit' }
if ($expectedWheelSha256 -notmatch '^[0-9a-f]{64}$') { throw 'Missing frozen wheel SHA-256' }
$wheel = Resolve-Path .\dist\local_gpu_imagegen-0.8.0-py3-none-any.whl
python .\scripts\validate_release_candidate.py `
  --wheel $wheel `
  --expected-commit $commit `
  --expected-wheel-sha256 $expectedWheelSha256 `
  --python $python312 `
  --report .\outputs\release-candidate-validation\candidate-report.json
```

Explain that the two environment variables come from the separately frozen
candidate record, not from the artifact being checked. List each remote action
as a later separate approval and prohibit rebuilding between PyPI and Registry
publication.

- [ ] **Step 4: Run public-document tests and verify GREEN**

Run the command from Step 2.

Expected: all public-document tests pass.

- [ ] **Step 5: Commit the operator contract**

```powershell
git add docs/publication-runbook.md docs/launch-playbook.md docs/release-checklist.md tests/test_public_docs.py
git commit -m "docs: add offline publication preflight"
```

---

### Task 5: Exact Candidate Freeze And Repository Verification

**Files:**
- Modify locally/ignored: `PROJECT_NODES.md`
- Modify locally/ignored: `NEXT_SESSION.md`
- Generate ignored: `outputs/release-candidate-validation/candidate-report.json`
- Generate outside checkout: two wheel build directories and one install environment.

**Interfaces:**
- Consumes: final exact commit, fixed commit epoch, Python 3.12.12, and all verifier/tests.
- Produces: byte-identical wheels, one passed sanitized candidate report, full verification evidence, and accurate continuation state.

- [ ] **Step 1: Run focused and full model-free verification**

```powershell
python -m unittest tests.test_release_candidate_checks tests.test_validate_release_candidate tests.test_packaging tests.test_public_docs -v
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
python .\scripts\verify_mcp.py
python .\scripts\verify_client_configs.py
python .\scripts\validate_real_demo.py docs\demo\real --expected-server-version 0.7.0
python .\scripts\validate_acceptance_evidence.py
git diff --check
git diff --cached --check
```

Expected: all tests and model-free validators pass; MCP exposes exactly 17
tools; non-strict acceptance remains truthful; diff checks are silent.

- [ ] **Step 2: Commit any final test-derived correction**

Only if Step 1 exposed a reproducible defect, add the smallest tested correction
and commit it. Otherwise make no empty commit.

- [ ] **Step 3: Build twice from the exact commit with one fixed epoch**

```powershell
$python312 = uv python find 3.12 --no-python-downloads
$commit = git rev-parse HEAD
$env:SOURCE_DATE_EPOCH = git show -s --format=%ct $commit
$base = Join-Path ([System.IO.Path]::GetTempPath()) "local-gpu-imagegen-$($commit.Substring(0,7))-candidate"
if (Test-Path -LiteralPath $base) { throw "Refusing to overwrite $base" }
New-Item -ItemType Directory -Path (Join-Path $base 'a'),(Join-Path $base 'b') | Out-Null
uv build --wheel --offline --no-python-downloads --python $python312 --out-dir (Join-Path $base 'a')
uv build --wheel --offline --no-python-downloads --python $python312 --out-dir (Join-Path $base 'b')
$wheelA = Get-ChildItem (Join-Path $base 'a') -Filter *.whl -File
$wheelB = Get-ChildItem (Join-Path $base 'b') -Filter *.whl -File
$hashA = (Get-FileHash -LiteralPath $wheelA.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$hashB = (Get-FileHash -LiteralPath $wheelB.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hashA -ne $hashB) { throw 'Fixed-epoch wheel builds differ' }
```

Expected: exactly one wheel in each directory and identical SHA-256 values.

- [ ] **Step 4: Run the new verifier against the frozen wheel**

```powershell
New-Item -ItemType Directory -Force -Path '.\outputs\release-candidate-validation' | Out-Null
$report = Resolve-Path '.\outputs\release-candidate-validation' | ForEach-Object { Join-Path $_ 'candidate-report.json' }
python .\scripts\validate_release_candidate.py `
  --wheel $wheelA.FullName `
  --expected-commit $commit `
  --expected-wheel-sha256 $hashA `
  --python $python312 `
  --report $report
$validated = Get-Content -Raw $report | ConvertFrom-Json
if ($validated.status -ne 'passed') { throw 'Release candidate is blocked' }
```

Expected: exit `0`, `status: passed`, version `0.8.0`, protocol
`2024-11-05`, 17 tools, fail-closed doctor, dry-run setup, and no unsafe wheel
entries.

- [ ] **Step 5: Update ignored continuity files**

Record the exact commit, wheel size/hash/entry count, candidate report hash,
test counts, expected skips, control flow, failure modes, verification commands,
and remaining authority gates in `PROJECT_NODES.md`. Point `NEXT_SESSION.md` to
Milestone 2's existing-run review gate and explicitly state that no GPU,
finalization, export, push, PyPI, Registry, tag, Release, or metadata action has
been authorized by this milestone.

- [ ] **Step 6: Final hygiene check**

```powershell
git status --short --branch
git diff --check
git diff --cached --check
```

Expected: the candidate branch is clean. Root `main` remains unchanged except
for the user's existing untracked `.codex/`; ignored continuity/output files do
not enter the public commit.
