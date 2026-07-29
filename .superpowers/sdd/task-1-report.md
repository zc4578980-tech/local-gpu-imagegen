# Task 1 Report: Static Checkout, Wheel, And Registry Contract

## Status

Completed and committed as `2d8fd7d feat: validate release candidate statically`.

## RED Evidence

Command:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateStaticTests -v
```

Output summary before the module existed:

```text
ERROR: test_release_candidate_checks
ModuleNotFoundError: No module named 'release_candidate_checks'
Ran 1 test in 0.000s
FAILED (errors=1)
```

Additional RED feedback during archive hardening: the unsafe-backslash entry
test failed because `zipfile` normalizes `ZipInfo.filename`. The implementation
was corrected to reject a backslash in `ZipInfo.orig_filename`, which preserves
the original central-directory spelling.

## GREEN Evidence

Checkout command:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateStaticTests -v
```

Output summary:

```text
Ran 4 tests in 4.285s
OK
```

Full static commands:

```powershell
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py
```

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

```powershell
git diff --check
```

Output summary:

```text
Ran 10 tests in 4.671s
OK
```

## Files Changed

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`

## Commit

- `2d8fd7d feat: validate release candidate statically`

## Self-Review

- Validates lower-case fixed-length commit and SHA-256 inputs before Git or
  wheel processing.
- Uses an injectable Git runner and fail-closed checkout checks for unavailable
  Git, mismatched HEAD, worktree changes, and staged changes; untracked names
  are bounded to 20 and do not block.
- Uses `lstat` and streaming SHA-256; it never installs, builds, downloads, or
  unpacks the wheel to disk.
- Rejects unsafe paths, symlinks, model/output entries, oversized archives,
  malformed or drifting wheel metadata, sensitive path/credential markers, and
  descriptor/project drift.
- Confirms the registry descriptor remains one PyPI `uvx` package with
  positional `serve` and stdio transport. No MCP tools or existing 17-tool
  surface were modified.

## Concerns

- This milestone intentionally performs static inspection only. Installed
  environment validation, the verifier CLI, documentation, GPU work, and every
  remote action remain out of scope.

---

## Review Fix Evidence (2026-07-29)

### Changed Files

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `.superpowers/sdd/task-1-report.md`

### RED Evidence

Command:

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

Output summary before the fix:

```text
Ran 14 tests in 5.231s
FAILED (failures=4)
```

The new focused cases failed for non-`??` porcelain output, duplicate ZIP
members, and `//` / `./` ZIP member spellings.

### GREEN Evidence

Commands:

```powershell
python -m unittest tests.test_release_candidate_checks -v
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py
git diff --check
```

Output summary:

```text
Ran 15 tests in 5.619s
OK
```

`py_compile` and `git diff --check` completed with exit code 0.

### Commit

- `d78c9590003adc2b05f9ac4a519c574db2e8ec30 fix: harden release candidate checks`

### Self-Review

- Every non-`??` porcelain line is now interpreted as index/worktree dirtiness
  or blocked as malformed status output.
- Git runner, executable, timeout, and wheel hash-read errors return sanitized
  blocked results instead of escaping.
- Archive count, per-entry, and total-size breaches skip all archive content
  reads; static entry spelling checks still use central-directory metadata.
- Duplicate member names are rejected before `.dist-info` validation, and
  `WHEEL` fields are parsed as headers with the exact expected `Tag` value.
- Focused tests cover runner exceptions, porcelain output, total-only size
  overflow, duplicate members, malformed headers, non-normalized spellings,
  and hash-read failure.

### Concerns

- The duplicate-member fixture emits Python `zipfile`'s expected local
  `UserWarning`; the test passes and no production behavior is affected.
- This remains static offline validation only. No wheel was built or consumed,
  and no MCP, GPU, network, client-state, or publication action was performed.

---

## Re-Review Fix Evidence (2026-07-29)

### Changed Files

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `.superpowers/sdd/task-1-report.md`

### RED Evidence

Command:

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

Output summary before the fix:

```text
Ran 17 tests in 6.295s
FAILED (failures=4, errors=1)
```

The failures proved raw untracked names were returned, duplicate/conflicting
`Wheel-Version` headers were accepted, and an encrypted archive read
`RuntimeError` escaped with its error text.

### GREEN Evidence

Commands:

```powershell
python -m unittest tests.test_release_candidate_checks -v
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py
git diff --check
```

Output summary:

```text
Ran 17 tests in 6.310s
OK
```

`py_compile` and `git diff --check` completed with exit code 0.

### Commit

- `c54b51b4e4f6174b0cc324845ea54efe6d5c1d0d fix: sanitize release check reports`

### Self-Review

- Checkout facts retain only the untracked item count and never return raw
  untracked path names.
- Supported archive read failures, including encrypted members and unsupported
  compression, now return a sanitized `wheel_archive_invalid` block.
- `WHEEL` validation requires exactly one `Wheel-Version: 1.0` and exactly one
  `Tag: py3-none-any` field.
- Focused tests cover private untracked paths, archive read errors without
  error-text leakage, and duplicate/conflicting `Wheel-Version` fields.

### Concerns

- The duplicate-member fixture still emits Python `zipfile`'s expected local
  `UserWarning`; it is contained to the test fixture.
- This remains static offline validation only. No wheel was built or consumed,
  and no MCP, GPU, network, client-state, or publication action was performed.
