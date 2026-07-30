# Publication Runbook

This runbook verifies one already-built release candidate before any remote
action. The verifier does not build, does not download, and does not publish.
It uses only the supplied wheel, checkout, and installed Python 3.12.

## Freeze The Inputs

Record the exact 40-character commit and 64-character wheel SHA-256 when the
candidate is frozen. Set them from that separate candidate record, never by
copying values from the checkout or wheel that is being checked:

```powershell
$env:RELEASE_CANDIDATE_COMMIT = '<frozen-40-character-commit>'
$env:RELEASE_CANDIDATE_WHEEL_SHA256 = '<frozen-64-character-wheel-sha256>'
```

The wheel must already exist at
`dist/local_gpu_imagegen-0.8.0-py3-none-any.whl`. Do not rebuild it during this
verification.

## Run The Offline Verifier

Run from the repository root. Use a new report path for every attempt because
the verifier atomically refuses to overwrite an existing report.

```powershell
$python312 = uv python find 3.12 --no-python-downloads
$commit = $env:RELEASE_CANDIDATE_COMMIT
$expectedWheelSha256 = $env:RELEASE_CANDIDATE_WHEEL_SHA256
if ($commit -notmatch '^[0-9a-f]{40}$') { throw 'Missing frozen release commit' }
if ($expectedWheelSha256 -notmatch '^[0-9a-f]{64}$') { throw 'Missing frozen wheel SHA-256' }
$wheel = Resolve-Path .\dist\local_gpu_imagegen-0.8.0-py3-none-any.whl
$reportRoot = New-Item -ItemType Directory -Force -Path .\outputs\release-candidate-validation
$attemptId = [guid]::NewGuid().ToString('N')
$report = Join-Path $reportRoot.FullName "candidate-report-$attemptId.json"
if (Test-Path -LiteralPath $report) { throw 'Fresh report path already exists' }
python .\scripts\validate_release_candidate.py `
  --wheel $wheel `
  --expected-commit $commit `
  --expected-wheel-sha256 $expectedWheelSha256 `
  --python $python312 `
  --report $report
```

Proceed only when the command exits `0`, stdout is byte-identical to
the new `candidate-report.json` attempt path printed in `$report`, and that
report contains `"status": "passed"`. Any
blocked check, digest mismatch, dirty tracked state, install failure, existing
report path, or malformed output stops the release. Correct the candidate,
freeze it again, and rerun with a new report path.

## Separate Publication Approvals

A passed offline report grants no publication authority. Obtain separate approval
for each action unless the user explicitly bundles named actions:

1. Push the exact verified commit and wait for all required CI jobs.
2. Publish the exact verified wheel to PyPI.
3. Publish the MCP Registry descriptor and verify the resolved package and
   stdio command.
4. Create the `v0.8.0` tag.
5. Create the GitHub Release from the reviewed release copy and assets.
6. Change repository metadata, topics, or social preview.
7. Submit each directory listing.

Do not rebuild or replace the wheel between PyPI and MCP Registry publication.
Stop if any public digest, version, command, URL, or release claim differs from
the passed candidate report.
