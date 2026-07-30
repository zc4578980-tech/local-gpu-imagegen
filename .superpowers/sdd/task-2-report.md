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
