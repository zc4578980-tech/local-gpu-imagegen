# Task 2 Report: Checkout-External Installed-Wheel Verification

## Status

Completed pending the Python 3.12 packaging-environment concern below.

## RED Evidence

Command:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateInstalledTests -v
```

Output summary before implementation:

```text
Ran 5 tests in 0.013s
FAILED (errors=12)
```

The missing `EXPECTED_TOOLS`, temporary-directory support, and
`run_installed_checks` caused the expected subprocess-boundary failures.

## GREEN Evidence

Focused installed-boundary command:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateInstalledTests -v
```

Output summary:

```text
Ran 6 tests in 0.042s
OK
```

Required helper and packaging command:

```powershell
python -m unittest tests.test_release_candidate_checks tests.test_packaging -v
```

Output summary:

```text
Ran 47 tests in 17.569s
OK (skipped=1)
```

The one skip is the new integration test, correctly skipped under the current
Python 3.13 because it requires Python 3.12.

Compilation and whitespace checks:

```powershell
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py tests\test_packaging.py
git diff --check
```

Both completed successfully. Git emitted only the repository's existing
LF-to-CRLF working-copy warnings.

An offline Python 3.12 invocation consumed a locally built wheel through
`run_installed_checks`. It returned no blocked checks and reported version
`0.8.0`, protocol `2024-11-05`, 17 tools, offline doctor exit/readiness
`1`/`false`, planned Codex and Claude dry-runs, and 33 compiled sources.

## Changed Paths

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `tests/test_packaging.py`
- `.superpowers/sdd/task-2-report.md`

## Commit

- `feat: verify installed release wheel` (the report is included in this commit;
  the final Git hash is authoritative)

## Implementation Notes

- Requires the supplied interpreter to report exactly Python 3.12 before a
  virtual environment is created; all preflight failures map to
  `release_python_312_required`.
- Creates the venv, fake Codex/Claude commands, marker, installation, CLI
  calls, and compilation only in a `TemporaryDirectory` outside the checkout.
- Installs only the supplied exact wheel using `pip --no-index --no-deps
  --no-cache-dir --disable-pip-version-check` and a scrubbed environment.
- Validates the exact installed version, protocol, ordered 17-tool contract,
  offline doctor state, non-mutating setup plans, and compileall result.
- Tests cover pip failure, malformed JSON, timeout, wrong version/protocol/tool
  order, doctor mismatch, setup mutation, marker creation, compile failure,
  pre-venv Python failures, and temporary-directory cleanup.

## Self-Review

- No MCP tool surface, package metadata, backend, GPU, model, network, client
  configuration, remote, tag, or publication behavior was changed.
- The passed runner is used for every verifier subprocess. Fake clients are
  prepended to the temporary PATH and their `mcp add` behavior can only write a
  temporary marker.
- Reports return only structured facts and fixed failure codes; they do not
  retain temporary paths or subprocess tracebacks.

## Concerns

- The available offline Python 3.12 interpreter lacks `setuptools.build_meta`,
  so its full `tests.test_packaging` setup cannot build a wheel. The verifier
  itself was separately exercised successfully with that interpreter against a
  locally built wheel. No package was installed or downloaded to repair the
  interpreter.
- A local ignored wheel directory created solely for that direct Python 3.12
  verification could not be removed because the execution environment rejected
  the cleanup command. It is outside tracked changes and contains no client,
  model, credential, or generated-image state.

## Review Fix Evidence

### RED

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateInstalledTests -v
```

Before the supplied-interpreter implementation: `Ran 9 tests in 72.980s`,
`FAILED (failures=7)`. The controller-created venv skipped both the
supplied-interpreter creation command and the created-venv Python 3.12 probe.

### GREEN

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateInstalledTests -v
```

Result: `Ran 9 tests in 0.075s`, `OK`.

```powershell
python -m unittest tests.test_release_candidate_checks tests.test_packaging -v
```

Result: `Ran 50 tests in 18.197s`, `OK (skipped=1)`. The existing
Python-3.12-only packaging integration is skipped when the normal interpreter
is Python 3.13; the direct Python 3.12 run below covers that release contract.

```powershell
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py tests\test_packaging.py
git diff --check
```

Both completed successfully after the review fixes.

### Direct Offline Python 3.12 Evidence

The command used the pre-existing offline Python 3.12 interpreter as
`$python312` and the already-built local wheel. It did not build, download, or
contact a backend, GPU, network endpoint, or real client.

```powershell
& $python312 -c "import json,sys; from pathlib import Path; sys.path.insert(0, 'scripts'); import release_candidate_checks as checks; results, facts = checks.run_installed_checks(Path('build/task2-wheel/local_gpu_imagegen-0.8.0-py3-none-any.whl'), Path(sys.executable)); blocked = [item for item in results if item['status'] == 'blocked']; print(json.dumps({'blocked_count': len(blocked), 'facts': facts}, sort_keys=True)); raise SystemExit(1 if blocked else 0)"
```

Result: exit `0`; `blocked_count` was `0`. Facts reported installed version
`0.8.0`, protocol `2024-11-05`, ordered tool count `17`, offline doctor
`1`/`false`, planned Codex and Claude dry-runs, `33` compiled sources, supplied
Python `[3, 12]`, and independently probed created-venv Python `[3, 12]`.

### Changed Paths

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `.superpowers/sdd/task-2-report.md`

`tests/test_packaging.py` was retained from the original Task 2 implementation;
its Python-3.12-only installed-wheel integration remains applicable and was
included in the required test command.

### Self-Review

- The supplied interpreter now executes the bounded
  `venv.EnvBuilder(with_pip=True).create(sys.argv[1])` script through the
  injected runner, with the same checkout-external cwd, scrubbed environment,
  capture/text/check settings, and 60-second timeout as every verifier call.
- The verifier probes both supplied and created interpreters for exactly
  `[3, 12]` before pip runs. A valid wheel is resolved to its exact absolute
  path before changing cwd, and that resolved path is the final pip argument.
- Tests assert every subprocess boundary, all four scrubbed variables,
  required offline/backend values, ordered tools, doctor readiness, setup
  immutability, JSON failure shapes, timeout handling, facts completeness, and
  result ID sorting/uniqueness.
- No MCP tool, package metadata, backend, GPU, model, network, real client,
  remote, tag, publication, or push behavior changed.

### Concerns

None for this fix. The normal-process Python-3.13 packaging run intentionally
skips its Python-3.12-only integration, while the direct offline Python 3.12
run above exercises the same installed-wheel release contract successfully.

### Commit

```powershell
git commit -m "fix: enforce supplied Python 3.12 venv"
```

The resulting local commit hash is reported by Git and in the task completion
summary.
