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

---

## Third Review Fix Evidence (2026-07-29)

### Changed Files

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `.superpowers/sdd/task-1-report.md`

### RED And Focused GREEN Evidence

Wheel file byte ceiling:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_oversized_file_before_hash_or_zip_open -v
```

RED: `Ran 1 test in 0.013s`, `FAILED (errors=1)` because
`MAX_WHEEL_BYTES` did not exist. GREEN: `Ran 1 test in 0.074s`, `OK`.

Duplicate/conflicting METADATA identity headers:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_duplicate_or_conflicting_metadata_identity_headers -v
```

RED: `Ran 1 test in 0.071s`, `FAILED (failures=6)`. GREEN:
`Ran 1 test in 0.076s`, `OK`.

Case-insensitive private directories:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_case_insensitive_private_directories -v
```

RED: `Ran 1 test in 0.030s`, `FAILED (failures=2)`. GREEN:
`Ran 1 test in 0.026s`, `OK`.

Unsafe/invalid layout read short-circuit:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_does_not_read_content_after_unsafe_or_invalid_layout -v
```

RED: `Ran 1 test in 0.028s`, `FAILED (failures=2)` with 7 and 3 observed
archive reads. GREEN: `Ran 1 test in 0.025s`, `OK` with zero reads.

Total-size overflow read assertion:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_total_size_overflow_without_reading_entries -v
```

The strengthened `assert_not_called()` coverage was GREEN immediately because
the prior size-limit fix already short-circuited content reads: `Ran 1 test in
0.054s`, `OK`. No production change was needed for this coverage-only finding.

### Final GREEN Evidence

Commands:

```powershell
python -m unittest tests.test_release_candidate_checks -v
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py
git diff --check
```

Output summary after final test organization review:

```text
Ran 21 tests in 5.640s
OK
```

`py_compile` and `git diff --check` completed with exit code 0.

### Commit

- `bb4ba3b4ada70db6f9a21baf17fed7b722ab56ce fix: bound static wheel inspection`

### Self-Review

- A 32 MiB wheel-file ceiling is checked from `lstat` before hashing or opening
  the ZIP. This conservatively permits overhead above the existing 16 MiB
  uncompressed-content ceiling while bounding file and central-directory I/O.
- `Name`, `Version`, and `Requires-Python` each require exactly one expected
  METADATA value; duplicate and conflicting values fail closed.
- Forbidden `models` and `outputs` path components use Unicode case folding for
  Windows-compatible case-insensitive comparison.
- Oversized, unsafe, or ambiguous archives do not call `_archive_bytes` for
  metadata or content scans.
- No MCP files, package metadata, GPU/backend state, client state, network, or
  publication surfaces were touched.

### Concerns

- The duplicate-member fixture emits Python `zipfile`'s expected local
  `UserWarning`; the test remains passing and isolated.
- The total-size no-read assertion was characterization coverage rather than a
  RED defect because the behavior was already correct before that assertion.

---

## Final Gate Fix Evidence (2026-07-29)

### RED Evidence

Command after adding focused tests for all six final-gate findings:

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

Result before production changes:

```text
Ran 30 tests in 6.671s
FAILED (failures=21)
```

The failures covered duplicate and unsorted checkout IDs, the Python
3.12-only teardown API, duplicate JSON keys, path replacement between hash and
ZIP parsing, NUL/normalized/case-colliding names, nonempty directories,
private paths and credential markers, opened-object checks, growth detection,
parser defects, missing explicit `.dist-info` pass, and contradictory late
archive results.

### GREEN Evidence

Required focused suite:

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

```text
Ran 31 tests in 6.716s
OK
```

Required compilation check:

```powershell
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py
```

Result: exit code 0 with no output.

Required whitespace check:

```powershell
git diff --check
```

Result: exit code 0; Git emitted only the repository's existing LF-to-CRLF
working-copy warnings.

An offline Python 3.12 interpreter was available, so the same focused suite was
also run there:

```powershell
py -V:Astral/CPython3.12.12 -m unittest tests.test_release_candidate_checks -v
```

```text
Ran 31 tests in 6.695s
OK
```

No offline Python 3.11 interpreter was installed according to `py -0p`, the
local uv Python directory, and `conda env list`; the known `pytorch-vla`
environment reported Python 3.12.13. No interpreter was installed or
downloaded. A 3.11 grammar check was run as an additional compatibility guard:

```powershell
python -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p, feature_version=(3, 11)) for p in ('scripts/release_candidate_checks.py', 'tests/test_release_candidate_checks.py')]; print('Python 3.11 grammar: OK')"
```

```text
Python 3.11 grammar: OK
```

### Changed Files

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `.superpowers/sdd/task-1-report.md`

### Commit

- `f81baeaf34e1ad21258656b022481e76c048213b fix: close release candidate final gate`

### Self-Review

- Every returned check list is sorted by ID and contains one result per ID;
  blocked results replace earlier passes, including late archive failures.
- Valid and invalid `.dist-info` layouts now return explicit pass/block checks.
- Wheel bytes are opened once, verified with `fstat`, bounded to 32 MiB while
  being hash-streamed into one `BytesIO` snapshot, and that snapshot alone is
  passed to `ZipFile`; growth, truncation, replacement, and over-budget reads
  have focused tests.
- ZIP validation rejects NUL or normalized-name-changing sources,
  case-insensitive collisions, and nonempty directory entries before content
  reads.
- Both email messages reject parser defects, and `server.json` rejects
  duplicate keys through `object_pairs_hook` at every nesting level.
- Sensitive scanning covers any Windows drive with slash or backslash,
  POSIX `/home/` and `/Users/`, and bounded credential assignment/header
  markers without returning matched content.
- Test teardown uses `shutil.rmtree(..., onerror=...)`, which is supported by
  Python 3.11. The duplicate-member fixture warning is now locally suppressed.
- No version, protocol, tool surface, MCP/client/GPU state, metadata, remote,
  candidate artifact, network, or publication behavior was changed.

### Concerns

- Python 3.11 runtime execution could not be performed because no offline 3.11
  interpreter was installed. Python 3.11 grammar compatibility, the 3.11-safe
  teardown API, default Python 3.13, and offline Python 3.12 were verified.
- This remains synthetic, static, offline validation only; no real candidate
  wheel was built or consumed.

---

## Parent Pre-Review Fix Evidence (2026-07-29)

### RED Evidence

Command after adding the three focused tests and before production changes:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_lstat_path_types_before_open tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_identity_change_between_lstat_and_open tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_generic_windows_absolute_paths -v
```

```text
Ran 3 tests in 0.048s
FAILED (failures=5)
```

The five failures proved that mocked non-regular and reparse paths reached
`Path.open`, an opened object with a different identity reached ZIP parsing,
and generic `D:\AI\...` / `E:\models\...` absolute paths were not detected.

### GREEN Evidence

Focused command:

```powershell
python -m unittest tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_lstat_path_types_before_open tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_identity_change_between_lstat_and_open tests.test_release_candidate_checks.ReleaseCandidateWheelTests.test_wheel_rejects_generic_windows_absolute_paths -v
```

```text
Ran 3 tests in 0.044s
OK
```

Required full focused suite:

```powershell
python -m unittest tests.test_release_candidate_checks -v
```

```text
Ran 34 tests in 6.651s
OK
```

Required compilation check:

```powershell
python -m py_compile scripts\release_candidate_checks.py tests\test_release_candidate_checks.py
```

Result: exit code 0 with no output.

Required whitespace check:

```powershell
git diff --check
```

Result: exit code 0; Git emitted only LF-to-CRLF working-copy warnings.

### Changed Files

- `scripts/release_candidate_checks.py`
- `tests/test_release_candidate_checks.py`
- `.superpowers/sdd/task-1-report.md`

### Self-Review

- `inspect_wheel` now rejects unavailable, non-regular, reparse, and oversized
  paths from `lstat` before `Path.open`.
- The first `fstat` must match the `lstat` identity through
  `os.path.samestat`; identity replacement blocks before hashing or `ZipFile`.
- Hashing and ZIP parsing still consume only the one bounded snapshot made
  from the opened file object.
- Focused mocks prove path type failures perform zero opens and zero ZIP
  parses, while identity replacement performs one open and zero ZIP parses.
- Private-path scanning now rejects any alphabetic Windows drive absolute path
  using either slash direction, while retaining `/home/` and `/Users/` checks.
- No real candidate, network, download, MCP/client/GPU state, remote,
  publication, version, protocol, or tool-surface operation was performed.

### Concerns

- None beyond the existing static, synthetic validation boundary.
