# v0.6.1 Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current single-agent worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `v0.6.1` as an installable preview whose guided setup, genuine local-GPU hot-revision demo, two named-client sessions, packaging, and public release state are all backed by retained evidence.

**Architecture:** Keep the existing standard-library MCP core and fifteen-tool surface unchanged. Add a thin client setup planner that delegates mutation to official client commands, fail-closed validators for named-client and real-demo evidence, and release metadata for PyPI and the official MCP Registry. Produce the genuine SDXL root/revision artifacts and named-client records only after the code gates pass, then publish only after a separate external-write authority check.

**Tech Stack:** Python 3.11/3.12 standard library, `unittest`, JSON Schema documents, MCP JSON-RPC over stdio, GitHub Actions, `uv`, PyPI, official MCP Registry metadata, existing ComfyUI/SDXL route, optional local Pillow only for showcase encoding.

## Global Constraints

- Keep exactly fifteen MCP tools and preserve all existing run, review, trust, and finalization contracts.
- Keep `v0.6.0` and tag `v0.6.0` unchanged; all corrected active version fields become `0.6.1`.
- Do not modify shared/global Python or `<local-ai-root>\envs\pytorch-vla`.
- Do not download, install, trust, or silently switch a model or runtime.
- Do not publish private trust state, endpoints, prompts, account data, absolute paths, `docs/evidence/runs/`, failed runs, or unapproved output bytes.
- Use the existing SDXL checkpoint SHA-256 `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`, workflow SHA-256 `05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e`, and bundle SHA-256 `ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62`.
- The real demo uses a non-human, generated-text-free, 1280x720 `ui-visual-asset/hero` route with at most two successful root rounds and two successful immutable revision rounds.
- Display the exact route, settings, prompts, budgets, seed policy, download policy, and upscale policy and receive a fresh later confirmation before GPU execution.
- Treat 800+ stars as a launch target, never as a guarantee or release claim.
- Do not contact maintainers, open third-party PRs, submit directory forms, push, tag, create releases, or publish packages without the required explicit external authority.
- Make test-first changes and commit each task independently; never stage retained private runs or local outputs.

## File Map

- `.github/workflows/tests.yml`: install the declared build backend before the no-build-isolation packaging suite.
- `tests/test_ci_workflow.py`: pin CI build-backend ordering and the four required matrix jobs.
- `scripts/local_gpu_imagegen/client_setup.py`: create read-only Codex/Claude Code setup plans and apply them only through official `mcp add` commands.
- `scripts/local_gpu_imagegen/cli.py`: expose `setup codex|claude-code [--apply]` as JSON while preserving existing commands.
- `scripts/check_gpu.py`: separate report collection from printing so setup can include non-generating readiness data.
- `tests/test_client_setup.py`, `tests/test_cli.py`: cover detection, dry-run, apply, idempotency, and failure behavior.
- `tests/test_packaging.py`: prove the installed wheel exposes setup and fifteen tools outside the checkout.
- `tests/test_repository_hygiene.py`: pin MIT/license metadata, public repository templates, ignored private roots, and release provenance boundaries.
- `docs/evidence/schemas/client-session.schema.json`: public shape for a real named-client MCP session.
- `scripts/validate_client_sessions.py`: fail-closed semantic validation and private-value scanning for named-client evidence.
- `tests/test_validate_client_sessions.py`: reject config-only, source-checkout, mismatched, malformed, and private records.
- `docs/evidence/client-sessions/`: sanitized Codex and Claude Code evidence produced after real executions.
- `docs/evidence/schemas/real-demo.schema.json`: public shape for root/revision lineage and showcase artifact hashes.
- `scripts/export_real_demo.py`: copy only nominated image bytes, create sanitized manifests, and bind all exported hashes.
- `scripts/validate_real_demo.py`: verify real model identity, immutable lineage, visual review/finalization, and public-safe paths.
- `scripts/build_showcase.py`: use already available local Pillow to encode a short before/after GIF without adding a runtime dependency.
- `tests/test_export_real_demo.py`, `tests/test_validate_real_demo.py`: exercise export allowlists and fail-closed validation with synthetic PNGs.
- `docs/demo/real/`: genuine before/after images, previews, showcase, sanitized transcript/manifests, and reproduction notes.
- `server.json`: official MCP Registry metadata for the published PyPI artifact.
- `docs/directory-listings.md`: exact prepared awesome-mcp-servers and Glama copy; preparation is not submission.
- `pyproject.toml`, `scripts/local_gpu_imagegen/__init__.py`, `.codex-plugin/plugin.json`, `README.md`, `CHANGELOG.md`, `docs/client-compatibility.md`, `docs/demo/README.md`, `docs/github-listing.md`, `docs/release-checklist.md`: `v0.6.1` release surface and truthful evidence claims.
- `tests/test_mcp_server.py`, `tests/test_public_docs.py`, `tests/public_contract_helpers.py`: active version, registry metadata, demo placement, and claim boundaries.

---

### Task 1: Repair The Public CI Build Backend

**Files:**
- Create: `tests/test_ci_workflow.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: `[build-system].requires = ["setuptools>=68"]` from `pyproject.toml`.
- Produces: a four-job workflow that installs the declared backend before `tests/test_packaging.py` builds with `--no-build-isolation`.

- [ ] **Step 1: Write the failing workflow regression test**

```python
# tests/test_ci_workflow.py
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CiWorkflowTests(unittest.TestCase):
    def test_declared_build_backend_is_installed_before_suite(self) -> None:
        workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        install = 'python -m pip install "setuptools>=68"'
        suite = "python -m unittest discover -s tests -v"
        self.assertIn(install, workflow)
        self.assertLess(workflow.index(install), workflow.index(suite))

    def test_public_matrix_keeps_four_required_jobs(self) -> None:
        workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertIn("os: [windows-latest, ubuntu-latest]", workflow)
        self.assertIn('python-version: ["3.11", "3.12"]', workflow)
        self.assertIn("fail-fast: false", workflow)
```

- [ ] **Step 2: Run the test and verify the reproduced omission**

Run: `python -m unittest tests.test_ci_workflow -v`

Expected: `test_declared_build_backend_is_installed_before_suite` fails because the install command is absent.

- [ ] **Step 3: Add the build-backend step immediately after Python setup**

```yaml
      - name: Install declared build backend
        run: python -m pip install "setuptools>=68"
```

- [ ] **Step 4: Run the focused and packaging tests**

Run: `python -m unittest tests.test_ci_workflow tests.test_packaging -v`

Expected: all tests pass and the wheel still installs outside the checkout.

- [ ] **Step 5: Commit the CI repair**

```shell
git add .github/workflows/tests.yml tests/test_ci_workflow.py
git commit -m "fix(ci): install declared build backend"
```

---

### Task 2: Add Read-Only Guided Client Setup

**Files:**
- Create: `scripts/local_gpu_imagegen/client_setup.py`
- Create: `tests/test_client_setup.py`
- Modify: `scripts/check_gpu.py`
- Modify: `scripts/local_gpu_imagegen/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `build_setup_plan(client: str, *, executable_lookup=shutil.which, runner=subprocess.run) -> dict[str, object]`.
- Produces: `apply_setup_plan(plan: dict[str, object], *, runner=subprocess.run) -> dict[str, object]`.
- Produces: `check_gpu.collect_report() -> dict[str, object]`; `check_gpu.main()` only serializes it and maps `ready` to exit status.
- Setup client names are exactly `codex` and `claude-code`; the server name is exactly `local-gpu-imagegen`.

- [ ] **Step 1: Write failing planner tests**

```python
# tests/test_client_setup.py
def test_codex_plan_is_read_only_and_exact(self) -> None:
    runner = RecordingRunner(get_returncode=1, version="codex-cli 0.144.5")
    plan = build_setup_plan("codex", executable_lookup=lambda _: "C:/bin/codex.exe", runner=runner)
    self.assertFalse(plan["applied"])
    self.assertEqual(plan["add_command"], [
        "C:/bin/codex.exe", "mcp", "add", "local-gpu-imagegen", "--",
        "local-gpu-imagegen", "serve",
    ])
    self.assertEqual(plan["remove_command"], [
        "C:/bin/codex.exe", "mcp", "remove", "local-gpu-imagegen",
    ])
    self.assertNotIn(plan["add_command"], runner.calls)

def test_claude_code_plan_uses_user_scope(self) -> None:
    plan = build_setup_plan(
        "claude-code", executable_lookup=lambda _: "C:/bin/claude.exe",
        runner=RecordingRunner(get_returncode=1, version="2.1.195"),
    )
    self.assertEqual(plan["add_command"], [
        "C:/bin/claude.exe", "mcp", "add", "--scope", "user",
        "local-gpu-imagegen", "--", "local-gpu-imagegen", "serve",
    ])

def test_apply_is_idempotent_and_surfaces_subprocess_failure(self) -> None:
    existing = build_setup_plan("codex", executable_lookup=lambda _: "codex", runner=RecordingRunner(get_returncode=0))
    self.assertEqual(apply_setup_plan(existing, runner=RecordingRunner()), {**existing, "status": "already_configured"})
    with self.assertRaisesRegex(RuntimeError, "client_setup_failed"):
        apply_setup_plan(
            {**existing, "existing": False},
            runner=RecordingRunner(add_returncode=2, stderr="permission denied"),
        )
```

`RecordingRunner` must return deterministic `subprocess.CompletedProcess` values for `--version`, `mcp get`, and `mcp add`, and retain every argv list so the tests prove dry-run behavior.

- [ ] **Step 2: Run the focused tests and verify the missing module failure**

Run: `python -m unittest tests.test_client_setup -v`

Expected: import failure for `local_gpu_imagegen.client_setup`.

- [ ] **Step 3: Implement the exact setup registry and fail-closed subprocess handling**

```python
# scripts/local_gpu_imagegen/client_setup.py
SERVER_NAME = "local-gpu-imagegen"
SERVER_COMMAND = ["local-gpu-imagegen", "serve"]
CLIENTS = {
    "codex": {
        "binary": "codex",
        "get": ["mcp", "get", SERVER_NAME, "--json"],
        "add": ["mcp", "add", SERVER_NAME, "--", *SERVER_COMMAND],
        "remove": ["mcp", "remove", SERVER_NAME],
    },
    "claude-code": {
        "binary": "claude",
        "get": ["mcp", "get", SERVER_NAME],
        "add": ["mcp", "add", "--scope", "user", SERVER_NAME, "--", *SERVER_COMMAND],
        "remove": ["mcp", "remove", "--scope", "user", SERVER_NAME],
    },
}

def _run(runner, argv: list[str]):
    return runner(argv, capture_output=True, text=True, timeout=15, check=False)

def build_setup_plan(client: str, *, executable_lookup=shutil.which, runner=subprocess.run) -> dict[str, object]:
    if client not in CLIENTS:
        raise ValueError(f"unsupported_client:{client}")
    definition = CLIENTS[client]
    executable = executable_lookup(definition["binary"])
    if executable is None:
        raise RuntimeError(f"client_not_found:{definition['binary']}")
    version = _run(runner, [executable, "--version"])
    if version.returncode != 0:
        raise RuntimeError(f"client_version_failed:{client}")
    existing = _run(runner, [executable, *definition["get"]]).returncode == 0
    return {
        "client": client,
        "detected": True,
        "version": version.stdout.strip(),
        "server": {"name": SERVER_NAME, "command": SERVER_COMMAND},
        "existing": existing,
        "add_command": [executable, *definition["add"]],
        "remove_command": [executable, *definition["remove"]],
        "applied": False,
        "status": "already_configured" if existing else "planned",
    }

def apply_setup_plan(plan: dict[str, object], *, runner=subprocess.run) -> dict[str, object]:
    if plan["existing"]:
        return {**plan, "status": "already_configured"}
    completed = _run(runner, list(plan["add_command"]))
    if completed.returncode != 0:
        raise RuntimeError(f"client_setup_failed:{plan['client']}:{completed.stderr.strip()}")
    return {**plan, "applied": True, "status": "configured"}
```

The implementation must return argv arrays as evidence, never use `shell=True`, never edit config files, and truncate subprocess stderr to 500 characters before returning or raising it.

- [ ] **Step 4: Refactor readiness collection without changing `doctor` output**

```python
# scripts/check_gpu.py
def collect_report() -> dict[str, object]:
    report = {  # move the existing report construction here unchanged
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        # existing python_packages, cuda, webui, and comfyui fields
    }
    # preserve the existing backend probes and readiness calculation
    return report

def main() -> int:
    report = collect_report()
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1
```

- [ ] **Step 5: Add `setup` to the CLI and attach readiness without generating**

```python
# scripts/local_gpu_imagegen/cli.py
setup = subparsers.add_parser("setup", help="Plan or apply official MCP client setup.")
setup.add_argument("client", choices=("codex", "claude-code"))
setup.add_argument("--apply", action="store_true")

# in main()
if args.command == "setup":
    import check_gpu
    from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan
    try:
        plan = build_setup_plan(args.client)
        result = apply_setup_plan(plan) if args.apply else plan
        result["backend_readiness"] = check_gpu.collect_report()
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0
```

Update the help test to require `setup`, add CLI subprocess tests proving dry-run does not call `mcp add`, and patch `collect_report` to a model-free fixture.

- [ ] **Step 6: Run setup, CLI, doctor, and existing client-config tests**

Run: `python -m unittest tests.test_client_setup tests.test_cli tests.test_check_gpu tests.test_client_configs -v`

Expected: all tests pass; no client configuration changes occur.

- [ ] **Step 7: Commit guided setup**

```shell
git add scripts/local_gpu_imagegen/client_setup.py scripts/local_gpu_imagegen/cli.py scripts/check_gpu.py tests/test_client_setup.py tests/test_cli.py
git commit -m "feat(cli): add guided MCP client setup"
```

---

### Task 3: Verify Setup From An Installed Wheel

**Files:**
- Modify: `tests/test_packaging.py`
- Modify: `scripts/verify_client_configs.py`
- Modify: `tests/test_client_configs.py`

**Interfaces:**
- Consumes: the Task 2 `setup` command and existing wheel fixture.
- Produces: installed-wheel evidence that setup is present, remains read-only by default, and points to `local-gpu-imagegen serve`.

- [ ] **Step 1: Add the failing installed-wheel setup test**

```python
def test_installed_wheel_exposes_read_only_setup_outside_checkout(self) -> None:
    fake_bin = self.temp / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    write_fake_client(fake_bin, "codex", version="codex-cli test", get_exit=1)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
    completed = subprocess.run(
        [str(self.cli), "setup", "codex"], cwd=self.temp, env=environment,
        capture_output=True, text=True, check=True, timeout=30,
    )
    report = json.loads(completed.stdout)
    self.assertEqual(report["status"], "planned")
    self.assertFalse(report["applied"])
    self.assertEqual(report["server"]["command"], ["local-gpu-imagegen", "serve"])
    self.assertFalse((fake_bin / "add-called").exists())
```

`write_fake_client` must create `.cmd` on Windows and an executable POSIX script on Linux; it records only an actual `mcp add` invocation.

- [ ] **Step 2: Run and verify the pre-change failure**

Run: `python -m unittest tests.test_packaging.PackagingTests.test_installed_wheel_exposes_read_only_setup_outside_checkout -v`

Expected: failure because the wheel test fixture does not yet expose `self.cli`/the setup path.

- [ ] **Step 3: Share the installed environment fixture and update config verification names**

Move wheel installation into `PackagingTests.setUpClass`, assign `cls.python` and `cls.cli`, and keep the exact fifteen-tool assertion. Update `verify_client_configs.py` to validate `codex` and `claude-code` setup command contracts while retaining `claude-desktop` as a clearly labeled legacy render-only template.

- [ ] **Step 4: Run packaging and client-contract tests**

Run: `python -m unittest tests.test_packaging tests.test_client_configs -v`

Expected: all tests pass on the installed wheel outside the checkout.

- [ ] **Step 5: Commit installed-wheel setup coverage**

```shell
git add tests/test_packaging.py scripts/verify_client_configs.py tests/test_client_configs.py
git commit -m "test(packaging): verify installed client setup"
```

---

### Task 4: Add Real Named-Client Evidence Validation

**Files:**
- Create: `docs/evidence/schemas/client-session.schema.json`
- Create: `scripts/validate_client_sessions.py`
- Create: `tests/test_validate_client_sessions.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `validate_session(document: object, *, expected_server_version: str) -> list[str]` and CLI `python scripts/validate_client_sessions.py <json>...`.
- A valid record has `evidence_class: named_client_session`, client `codex` or `claude-code`, `installed_wheel: true`, `hosted_client_session: true`, server name/version/protocol, at least one real tool call with a sanitized JSON result and SHA-256, bounded UTC timestamps, and explicit omission flags.

- [ ] **Step 1: Write failing semantic-validation tests**

```python
def test_accepts_real_installed_named_client_call(self) -> None:
    document = valid_session(client="codex", tool="local_gpu_imagegen_check")
    self.assertEqual(validate_session(document, expected_server_version="0.6.1"), [])

def test_rejects_config_only_source_checkout_and_version_mismatch(self) -> None:
    for mutation in (
        {"hosted_client_session": False},
        {"installed_wheel": False},
        {"server": {"name": "local-gpu-imagegen", "version": "0.6.0", "protocol_version": "2024-11-05"}},
    ):
        document = valid_session(client="claude-code", tool="local_gpu_list_profiles")
        document.update(mutation)
        self.assertTrue(validate_session(document, expected_server_version="0.6.1"))

def test_rejects_private_values_and_unhashed_results(self) -> None:
    document = valid_session(client="codex", tool="local_gpu_get_run")
    document["tool_calls"][0]["result"] = {"path": "C:\\Users\\Capricorn\\private.png"}
    document["tool_calls"][0]["result_sha256"] = "0" * 64
    findings = validate_session(document, expected_server_version="0.6.1")
    self.assertIn("private_value", findings)
    self.assertIn("result_sha256_mismatch", findings)
```

- [ ] **Step 2: Run and verify the missing validator failure**

Run: `python -m unittest tests.test_validate_client_sessions -v`

Expected: import failure for `validate_client_sessions`.

- [ ] **Step 3: Implement schema and semantic validator**

The JSON Schema must set `additionalProperties: false` at every object boundary and require these top-level keys:

```json
[
  "schema_version", "evidence_class", "client", "installed_wheel",
  "hosted_client_session", "server", "started_at", "completed_at",
  "tool_calls", "sanitization"
]
```

The standard-library validator must enforce the constants, parse `Z` timestamps, require `started_at <= completed_at`, canonicalize each `result` as `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`, compare its SHA-256, require tool names from the existing fifteen-tool set, and recursively reject drive paths, user-home paths, localhost URLs, bearer/API tokens, prompts, and account identifiers.

- [ ] **Step 4: Include the schema in the wheel and run tests**

Add `validate_client_sessions` to `[tool.setuptools].py-modules` and add `docs/evidence/schemas/client-session.schema.json` to the wheel data files under `share/local-gpu-imagegen/evidence/schemas`. Run:

`python -m unittest tests.test_validate_client_sessions tests.test_packaging -v`

Expected: all tests pass and the schema is present in the wheel.

- [ ] **Step 5: Commit client evidence validation**

```shell
git add docs/evidence/schemas/client-session.schema.json scripts/validate_client_sessions.py tests/test_validate_client_sessions.py pyproject.toml
git commit -m "feat(evidence): validate named client sessions"
```

---

### Task 5: Add Genuine Hot-Revision Showcase Export And Validation

**Files:**
- Create: `docs/evidence/schemas/real-demo.schema.json`
- Create: `scripts/export_real_demo.py`
- Create: `scripts/validate_real_demo.py`
- Create: `scripts/build_showcase.py`
- Create: `tests/test_export_real_demo.py`
- Create: `tests/test_validate_real_demo.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `export_real_demo(root_run: Path, child_run: Path, destination: Path, client_session: Path) -> dict[str, object]`.
- Produces: `validate_real_demo(root: Path) -> list[str]` and CLI `python scripts/validate_real_demo.py docs/demo/real`.
- Export allowlist is exactly `before.png`, `after.png`, `before-preview.jpg`, `after-preview.jpg`, `root-manifest.json`, `revision-manifest.json`, `transcript.md`, `showcase.gif`, `showcase-manifest.json`, and `README.md`.

- [ ] **Step 1: Write failing exporter tests**

```python
def test_export_copies_only_nominated_bytes_and_sanitizes_manifests(self) -> None:
    root_run, child_run = write_finalized_hot_revision(self.temp)
    client = write_valid_client_session(self.temp / "codex.json")
    manifest = export_real_demo(root_run, child_run, self.output, client)
    self.assertEqual((self.output / "before.png").read_bytes(), (root_run / "final.png").read_bytes())
    self.assertEqual((self.output / "after.png").read_bytes(), (child_run / "final.png").read_bytes())
    self.assertNotIn(str(self.temp), json.dumps(manifest))
    self.assertFalse((self.output / "unrelated.tmp").exists())

def test_export_rejects_non_child_or_unreviewed_bytes(self) -> None:
    root_run, child_run = write_finalized_hot_revision(self.temp)
    child_manifest = read_json(child_run / "manifest.json")
    child_manifest["parent"]["image_sha256"] = "0" * 64
    write_json(child_run / "manifest.json", child_manifest)
    with self.assertRaisesRegex(ValueError, "invalid_revision_lineage"):
        export_real_demo(root_run, child_run, self.output, self.client)
```

- [ ] **Step 2: Write failing demo-validator tests**

```python
def test_valid_real_demo_binds_route_lineage_and_every_artifact(self) -> None:
    write_valid_real_demo(self.demo)
    self.assertEqual(validate_real_demo(self.demo), [])

def test_rejects_simulation_private_paths_and_changed_image_bytes(self) -> None:
    write_valid_real_demo(self.demo)
    manifest = read_json(self.demo / "showcase-manifest.json")
    manifest["model_output"] = False
    manifest["route"]["backend_url"] = "http://127.0.0.1:8188"
    (self.demo / "after.png").write_bytes(b"changed")
    write_json(self.demo / "showcase-manifest.json", manifest)
    findings = validate_real_demo(self.demo)
    self.assertIn("not_real_model_output", findings)
    self.assertIn("private_value", findings)
    self.assertIn("artifact_sha256_mismatch:after.png", findings)
```

- [ ] **Step 3: Run and verify missing module failures**

Run: `python -m unittest tests.test_export_real_demo tests.test_validate_real_demo -v`

Expected: import failures for both new scripts.

- [ ] **Step 4: Implement fail-closed manifest sanitization and export**

The exporter must read both durable manifests, require finalized/candidate-reviewed parent bytes and a finalized child, verify the child's `parent.run_id`, `parent.round`, and `parent.image_sha256`, require a hard preserve contract for `composition`, `primary_motif`, and `left_safe_area`, require review preservation results of `preserved`, and copy bytes only after recomputing their SHA-256. Sanitized manifests retain public route/model/workflow/bundle hashes, round/seed, review results, finalization time, and lineage; they drop output roots, backend URLs, filesystem model names, prompts, idempotency keys, and local errors.

- [ ] **Step 5: Implement the real-demo manifest validator**

Require these constants and relationships:

```python
EXPECTED = {
    "demo_kind": "real_local_gpu_hot_revision",
    "model_output": True,
    "model_sha256": "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
    "workflow_sha256": "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e",
    "bundle_sha256": "ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62",
    "width": 1280,
    "height": 720,
}
```

The validator must reject missing/extra files, absent non-empty limitations, failed/uncertain visual checks, missing finalization confirmation evidence, mismatched client-session digest, simulated demo kinds, altered bytes, non-relative paths, hidden files, and any recursively detected private value.

- [ ] **Step 6: Implement optional local showcase encoding**

```python
# scripts/build_showcase.py
def build_showcase(before: Path, after: Path, output: Path) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("showcase_requires_existing_local_pillow") from exc
    with Image.open(before) as first, Image.open(after) as second:
        frames = [ImageOps.fit(image.convert("RGB"), (960, 540)) for image in (first, second)]
        try:
            frames[0].save(
                output, format="GIF", save_all=True, append_images=frames[1:],
                duration=(1400, 1400), loop=0, optimize=True,
            )
        finally:
            for frame in frames:
                frame.close()
```

Do not add Pillow to runtime dependencies and do not install it. If it is unavailable in the already authorized project-local image environment, stop and retain the two static images until the user approves another encoding route.

- [ ] **Step 7: Include schemas/scripts and run focused tests**

Add `export_real_demo`, `validate_real_demo`, and `build_showcase` to `[tool.setuptools].py-modules`, and add `real-demo.schema.json` beside the client-session schema in packaged data. Run:

`python -m unittest tests.test_export_real_demo tests.test_validate_real_demo tests.test_packaging -v`

Expected: all tests pass; no model or GPU is touched.

- [ ] **Step 8: Commit genuine-demo evidence tooling**

```shell
git add docs/evidence/schemas/real-demo.schema.json scripts/export_real_demo.py scripts/validate_real_demo.py scripts/build_showcase.py tests/test_export_real_demo.py tests/test_validate_real_demo.py pyproject.toml
git commit -m "feat(evidence): validate real hot revision demos"
```

---

### Task 6: Prepare v0.6.1 Repository Hygiene And Distribution Metadata

**Files:**
- Create: `server.json`
- Create: `docs/directory-listings.md`
- Create: `tests/test_repository_hygiene.py`
- Modify: `pyproject.toml`
- Modify: `scripts/local_gpu_imagegen/__init__.py`
- Modify: `.codex-plugin/plugin.json`
- Modify: `scripts/mcp_server.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/client-compatibility.md`
- Modify: `docs/demo/README.md`
- Modify: `docs/github-listing.md`
- Modify: `docs/release-checklist.md`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_public_docs.py`
- Modify: `tests/public_contract_helpers.py`

**Interfaces:**
- Produces: package/server/plugin version `0.6.1`, PyPI ownership marker `mcp-name: io.github.zc4578980-tech/local-gpu-imagegen`, and MCP Registry schema `2025-12-11` metadata for `uvx local-gpu-imagegen serve`.
- Directory copy remains a prepared artifact and must not claim submission.

- [ ] **Step 1: Add repository hygiene and legal regression tests**

```python
# tests/test_repository_hygiene.py
from pathlib import Path
import subprocess
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RepositoryHygieneTests(unittest.TestCase):
    def test_mit_metadata_and_public_templates_are_retained(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        for path in (
            "SECURITY.md", "CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml",
        ):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_private_roots_are_ignored_and_untracked(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("outputs/", ignored)
        self.assertIn("docs/evidence/runs/", ignored)
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.replace("\\", "/").splitlines()
        self.assertFalse(any(path.startswith(("outputs/", "docs/evidence/runs/")) for path in tracked))
```

- [ ] **Step 2: Update version tests to require exact v0.6.1 metadata**

```python
self.assertEqual(project["version"], "0.6.1")
self.assertEqual(plugin["version"], "0.6.1")
self.assertEqual(mcp_server.SERVER_VERSION, "0.6.1")
self.assertIn("mcp-name: io.github.zc4578980-tech/local-gpu-imagegen", readme)
self.assertEqual(server["name"], "io.github.zc4578980-tech/local-gpu-imagegen")
self.assertEqual(server["version"], "0.6.1")
self.assertEqual(server["packages"][0]["registryType"], "pypi")
self.assertEqual(server["packages"][0]["identifier"], "local-gpu-imagegen")
```

Add public-doc assertions that the real showcase, Codex, and Claude Code are described only when their validated files exist, and that the simulated GIF remains labeled and appears after the genuine demo.

- [ ] **Step 3: Run and verify stale-version failures**

Run: `python -m unittest tests.test_repository_hygiene tests.test_packaging tests.test_mcp_server tests.test_public_docs -v`

Expected: failures identify all remaining `0.6.0` active fields and missing `server.json`.

- [ ] **Step 4: Bump active version fields and preserve changelog history**

Set the package, `__version__`, plugin, MCP initialize response, active README snippets, and active tests to `0.6.1`. Add a new `## [0.6.1] - 2026-07-22` changelog section above `0.6.0`; do not rewrite the historical `0.6.0` section or tag.

- [ ] **Step 5: Add schema-valid registry metadata and ownership marker**

Create `server.json` using `$schema: https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`, name `io.github.zc4578980-tech/local-gpu-imagegen`, repository `https://github.com/zc4578980-tech/local-gpu-imagegen`, package registry `pypi`, identifier/version `local-gpu-imagegen`/`0.6.1`, stdio transport, runtime hint `uvx`, and package argument `serve`. Validate against the official publisher before external publication; a local JSON parse is not enough.

- [ ] **Step 6: Write truthful launch and directory copy**

The README quick start becomes:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```

Document `setup claude-code --apply`, removal commands, no direct config edits, the two static real images above the simulated GIF, exact SDXL limitations, and the still-incomplete 9+3 matrix. `docs/directory-listings.md` must contain one exact alphabetized awesome-mcp-servers line and the exact Glama name, repository, package, transport, install, description, and limitations fields, followed by `Status: prepared, not submitted`.

- [ ] **Step 7: Run hygiene, version, and documentation tests**

Run: `python -m unittest tests.test_repository_hygiene tests.test_packaging tests.test_mcp_server tests.test_public_docs -v`

Expected: all pass without claiming live PyPI, Registry, CI, or release state.

- [ ] **Step 8: Commit release metadata**

```shell
git add server.json docs/directory-listings.md pyproject.toml scripts/local_gpu_imagegen/__init__.py .codex-plugin/plugin.json scripts/mcp_server.py README.md CHANGELOG.md docs/client-compatibility.md docs/demo/README.md docs/github-listing.md docs/release-checklist.md tests/test_repository_hygiene.py tests/test_mcp_server.py tests/test_packaging.py tests/test_public_docs.py tests/public_contract_helpers.py
git commit -m "chore(release): prepare v0.6.1 metadata"
```

---

### Task 7: Build And Verify The Local Release Candidate

**Files:**
- Create locally only: `dist/local_gpu_imagegen-0.6.1-py3-none-any.whl`
- Create locally only: `dist/SHA256SUMS`
- Modify only after verification: `docs/release-checklist.md`

**Interfaces:**
- Produces: one wheel hash used by both named-client records and release provenance.

- [ ] **Step 1: Run the complete model-free suite and compile gate**

Run: `python -m compileall -q scripts tests`

Run: `python -m unittest discover -s tests -v`

Expected: zero failures; Windows reparse-point skips remain explicitly reported if the host cannot create them.

- [ ] **Step 2: Build the wheel without changing shared Python**

Run: `uv build --wheel --out-dir dist`

Expected: exactly one `local_gpu_imagegen-0.6.1-py3-none-any.whl`.

- [ ] **Step 3: Install and verify outside the checkout**

```powershell
$rc = '<codex-workspace>\scratch\local-gpu-imagegen-v061-rc'
py -3.12 -m venv $rc
& "$rc\Scripts\python.exe" -m pip install .\dist\local_gpu_imagegen-0.6.1-py3-none-any.whl --no-deps
& "$rc\Scripts\local-gpu-imagegen.exe" verify
& "$rc\Scripts\local-gpu-imagegen.exe" setup codex
```

Expected: verification returns `ok: true` and exactly fifteen tools; setup returns a non-mutating plan.

- [ ] **Step 4: Hash and scan the candidate**

Use `Get-FileHash -Algorithm SHA256` for the wheel, record lowercase hex in `dist/SHA256SUMS`, inspect wheel entries, parse all tracked JSON, run the path/credential scanner, `git diff --check`, and `git status --short`. `docs/evidence/runs/`, `outputs/`, trust files, private images, and absolute paths must be absent from staged/tracked release artifacts.

- [ ] **Step 5: Record the local gate and commit only the checklist**

Do not commit `dist/`. Check only verified local items in `docs/release-checklist.md`, then:

```shell
git add docs/release-checklist.md
git commit -m "docs: record v0.6.1 local release gate"
```

---

### Task 8: Execute The Confirmed Genuine SDXL Root And Hot Revision

**Files:**
- Create privately first: project output root run and immutable child run.
- Create after visual/user acceptance: `docs/demo/real/*` through Task 5 tooling.

**Interfaces:**
- Consumes: exact SDXL authority and the installed `v0.6.1` wheel.
- Produces: genuine public-rights root/revision bytes and a byte-bound user finalization record.

- [ ] **Step 1: Display the exact route and wait for a later confirmation**

Display all of the following without generating:

```text
profile/subtype: ui-visual-asset / hero
backend/workflow: ComfyUI / sdxl-txt2img v1
catalog/filesystem identity: local:1a4a27ae037d08ad44e98772 / model:1a4a27ae037d08ad44e987720d07df0910fff0e1d3210378e6a4886cfc4f97a5
checkpoint SHA-256: 31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b
workflow SHA-256: 05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e
bundle SHA-256: ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62
size/settings: 1280x720, 30 steps, CFG 7.0, dpmpp_2m, karras
root budget: at most 2 successful rounds
revision budget: at most 2 successful rounds
seed policy: root seed frozen after route confirmation; prompt-refine child preserves it
downloads/model switch/upscale: disabled; any later change needs new approval
```

Wait for an exact fresh response such as `确认 SDXL v0.6.1 demo route，root 2 轮、revision 2 轮` before the first GPU call.

- [ ] **Step 2: Run the root through a real Codex MCP session**

Use this natural-language brief:

```text
A refined futuristic astronomical observatory interior overlooking a blue ocean at dawn, wide cinematic composition, a brass telescope and curved glass dome on the right as the primary motif, the left 45 percent kept calm and dark for UI copy, layered depth, physically coherent architecture, premium editorial concept art, subtle mist, no people, no letters, no logos, no UI controls.
```

Negative direction is exactly: `people, human, character, text, letters, logo, watermark, interface, buttons, labels, cluttered left side, distorted architecture, duplicate telescope, low resolution, blurry`.

- [ ] **Step 3: Review full-resolution root bytes and nominate one parent**

Record dimensions, aspect ratio, crop tolerance, palette compatibility, style consistency, layout composability, edge quality, non-human anatomy checks as `not_applicable`, and text/watermark as `pass|fail|uncertain`. Failed or uncertain required checks may spend only the remaining confirmed root round. Do not promote a failed root.

- [ ] **Step 4: Confirm and create the immutable prompt-refine child**

Preserve hard targets `composition`, `primary_motif`, and `left_safe_area`. Change only `palette_and_lighting` to `warmer sunrise coral highlights balanced by cyan ocean light, with slightly brighter glass reflections while retaining dark readable copy space`. Keep the same seed and all route settings; spend at most two successful child rounds.

- [ ] **Step 5: Review, display candidate bytes, and wait for user finalization**

Show the full-resolution child image, limitations, SHA-256, and exact `finalize:<run_id>:<round_number>:<image_sha256>` token. Stop until a later user message contains that exact token. Never infer acceptance from route approval or praise.

- [ ] **Step 6: Finalize, export, encode, and validate public artifacts**

After exact finalization, run `export_real_demo.py`, create previews/showcase with already available local Pillow, write the sanitized transcript and reproduction README, then run:

`python scripts/validate_real_demo.py docs/demo/real`

Expected: no findings; all exported artifact hashes match.

- [ ] **Step 7: Commit only the validated public showcase**

```shell
git add docs/demo/real
git commit -m "docs(demo): add genuine SDXL hot revision showcase"
```

Verify `git diff --cached --name-only` contains no private run directory before committing.

---

### Task 9: Retain Two Minimal Named-Client Sessions

**Files:**
- Create: `docs/evidence/client-sessions/codex-v061.json`
- Create: `docs/evidence/client-sessions/claude-code-v061.json`
- Modify: `docs/demo/real/showcase-manifest.json` if the Codex session digest was not already bound.

**Interfaces:**
- Consumes: the exact Task 7 wheel hash and retained public demo run ID.
- Produces: one real Codex CLI record and one real Claude Code record that pass Task 4 validation.

- [ ] **Step 1: Run a fresh minimal Codex CLI session**

Use `codex exec --ephemeral --json --ignore-user-config --ignore-rules --sandbox read-only` with only an `mcp_servers.local-gpu-imagegen` command override pointing to the isolated installed-wheel CLI. Prompt it to call `local_gpu_imagegen_check` and the required run-lifecycle calls for Task 8, then return only a short completion object. Do not pass `--model`; preserve the configured model. Retain JSONL locally, extract observable MCP calls/results, and discard hidden reasoning and machine paths.

- [ ] **Step 2: Validate and write the Codex record**

Record actual `codex --version`, wheel SHA-256, server/protocol version, call timestamps, and canonical result hashes. Run:

`python scripts/validate_client_sessions.py docs/evidence/client-sessions/codex-v061.json`

Expected: `ok: true` and no private values.

- [ ] **Step 3: Run a fresh bounded Claude Code session**

Create a temporary MCP JSON whose command is the isolated installed-wheel executable and args are `serve`. Run Claude Code with `--print --no-session-persistence --mcp-config <temp> --strict-mcp-config --output-format stream-json --max-budget-usd 0.25 --permission-mode dontAsk`, allow only the local-gpu-imagegen MCP tools, and ask for exactly `local_gpu_imagegen_check` plus `local_gpu_get_run` for the retained public run. Do not request generation, filesystem edits, browsing, or unrelated tools.

- [ ] **Step 4: Validate and write the Claude Code record**

Record actual `claude --version`, the same wheel SHA-256 and protocol details, sanitize observable MCP results, delete the temporary config/raw transcript, and run:

`python scripts/validate_client_sessions.py docs/evidence/client-sessions/claude-code-v061.json`

Expected: `ok: true`; both required real tool results are present.

- [ ] **Step 5: Validate both records and demo binding**

Run: `python scripts/validate_client_sessions.py docs/evidence/client-sessions/*.json`

Run: `python scripts/validate_real_demo.py docs/demo/real`

Expected: both commands report no findings.

- [ ] **Step 6: Commit named-client evidence**

```shell
git add docs/evidence/client-sessions docs/demo/real/showcase-manifest.json
git commit -m "docs(evidence): retain real Codex and Claude sessions"
```

---

### Task 10: Publish Only After Green Public CI

**Files:**
- Modify after live verification: `docs/release-checklist.md`
- Modify: `PROJECT_NODES.md`
- Modify: `NEXT_SESSION.md`
- Append: `<codex-workspace>\obsidian\Codex Logs\2026-07-22.md`

**Interfaces:**
- Produces: public branch, four green jobs, PyPI `0.6.1`, official MCP Registry record, immutable `v0.6.1` tag, GitHub prerelease, topics, and verified URLs.

- [ ] **Step 1: Repeat every local release gate**

Run full tests, compilation, installed-wheel verification, setup dry-runs, both evidence validators, demo hashes, JSON parsing, tracked credential/path scan, `git diff --check`, and staged-file inspection. Any failure blocks publication.

- [ ] **Step 2: Verify remote credential state and obtain fresh write authority**

Confirm the old temporary Deploy Key is removed. If no safe current credential exists, stop and request one bounded credential flow. Separately obtain authority for PyPI and official MCP Registry publication; do not treat GitHub push authority as package-registry authority.

- [ ] **Step 3: Push the candidate branch without tagging**

Push `feature/v061-launch-readiness` or the approved release branch, open/fast-forward the reviewed candidate into `main` as authorized, and record the exact commit SHA. Do not move `v0.6.0`.

- [ ] **Step 4: Wait for all four GitHub Actions jobs**

Require green results for Windows/Python 3.11, Windows/Python 3.12, Ubuntu/Python 3.11, and Ubuntu/Python 3.12 at the exact release commit. A cancelled, skipped, neutral, stale, or red job blocks every later publication claim.

- [ ] **Step 5: Publish and verify PyPI**

Publish exactly the verified wheel/source artifact for `local-gpu-imagegen==0.6.1`, then install it into a fresh directory with `uvx local-gpu-imagegen verify`. Record the live PyPI URL and artifact digest. Never rebuild after the verified hash is chosen.

- [ ] **Step 6: Validate and publish official MCP Registry metadata**

Use the official `mcp-publisher` against `server.json`, authenticate through the user-approved GitHub flow, publish, and verify the live Registry API returns `io.github.zc4578980-tech/local-gpu-imagegen` version `0.6.1` with the PyPI package. Do not submit Glama or awesome-mcp-servers materials.

- [ ] **Step 7: Tag and create the GitHub prerelease**

Create annotated tag `v0.6.1` at the exact green commit, push it, and create a prerelease attaching the already hashed wheel, `SHA256SUMS`, genuine demo assets, limitations, and install commands. Apply the approved description and eight topics from `docs/github-listing.md`.

- [ ] **Step 8: Verify every public URL and update records**

Verify repository, Actions, tag, release assets, PyPI, and MCP Registry URLs anonymously. Mark only observed checklist items complete; update `PROJECT_NODES.md`, `NEXT_SESSION.md`, and the Obsidian daily log with commit, hashes, URLs, limitations, rollback/removal commands, and remaining unsubmitted directory listings.

- [ ] **Step 9: Run final completion review**

Use `verification-before-completion`, then `finishing-a-development-branch`. The five launch items are complete only if genuine bytes, both named clients, four green jobs, PyPI, Registry, tag, and release all resolve and validate; otherwise report the exact remaining blocker without estimating stars as a certainty.
