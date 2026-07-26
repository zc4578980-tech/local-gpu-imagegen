# v0.8.0 Release Candidate Validation Report

Date: 2026-07-26

Initial audited commit: `058718ad69b1bb90e3771587f8707bf08d256d6c`

Candidate code and public-copy state: `5eb98c5cba925cd1393a80dda82a96e8f8077c93`

Final local candidate: the commit containing this report. The post-commit wheel
rebuild must reproduce the digest recorded below before this report is treated
as complete.

Branch: `codex/v080-release-candidate-validation`

## Verdict

The bounded v0.8 preview gate is locally closed on Python 3.12. The source suite,
historical demo, named-client configuration contracts, deterministic wheel,
checkout-external installation, fail-closed doctor behavior, and installed
17-tool stdio surface pass.

The candidate is not remotely publication-ready until exact-commit Windows and
Ubuntu CI close Python 3.11 and 3.12, the public wheel digest is checked, and
each push, tag, package, Registry, Release, metadata, and directory action is
separately authorized.

The bounded v0.8 preview policy is approved and implemented. The existing
strict 9-root plus 3-revision validator remains unchanged as the
full-acceptance/v1.0 gate.

## Scope And Boundaries

The initial audit was read-only except for ignored artifacts under
`outputs/release-candidate-validation/`. The approved repair changed tests,
release documentation, Git EOL policy, and explicit historical-version
validation. It did not add a production module, dependency, or MCP tool.

It did not:

- start or probe a real image-generation backend;
- submit GPU work or generate an image;
- download a model, dependency, or Python interpreter;
- alter real Codex or Claude Code configuration;
- alter trust state;
- change the 17-tool MCP surface or package version `0.8.0`;
- rewrite the regional or two-stage workflow;
- push, tag, publish, create a Release, or change remote metadata.

Both the working-tree and cached diffs for these frozen files were empty:

- `workflows/comfyui/sdxl-regional-txt2img-v1.json`
- `workflows/comfyui/sdxl-two-stage-copy-subject-v1.json`

## Closed Local Engineering Gates

The following gates are closed for the final local candidate:

- The complete source suite passes 808 tests with seven expected Windows
  permission skips and zero failures in 138.696 seconds.
- Python compilation succeeds for `scripts` and `tests`.
- `scripts/validate_social_preview.py` passes.
- `scripts/verify_mcp.py` reports version `0.8.0` and exactly 17 tools.
- `scripts/verify_client_configs.py` passes the Codex and Claude Code
  configuration-contract and stdio-launch checks.
- Non-strict acceptance validation succeeds structurally with zero retained
  roots, zero retained revisions, and `release_ready: false`.
- Both retained named-client records validate independently against their
  actual server versions:
  - `codex-v070.json` at `0.7.0`;
  - `codex-v080-workflow-onboarding.json` at `0.8.0`.

These results do not establish current-version GPU generation, hosted-client
generation, image-quality superiority, complete acceptance, or publication.

## Final Offline Wheel Result

The audit used an already available uv-managed CPython 3.12.12 interpreter,
resolved locally without downloading it.

A deterministic offline wheel build completed without dependency or interpreter
download. `SOURCE_DATE_EPOCH` is fixed to `1785055416`, the timestamp of the
candidate code/public-copy state, so the post-report rebuild can prove exact
byte reproducibility:

```powershell
$python312 = uv python find 3.12 --no-python-downloads
$env:SOURCE_DATE_EPOCH = '1785055416'
uv build --wheel --offline --no-python-downloads --python $python312
```

Final candidate artifact:

`outputs/release-candidate-validation/final-wheel/local_gpu_imagegen-0.8.0-py3-none-any.whl`

- SHA-256: `b9124cb2749ad04519703bb2390fdec0963c0986ac008b946e2823b3f2f42dbb`
- Size: 246,033 bytes
- Distribution version: `0.8.0`
- Python requirement: `>=3.11`
- Runtime dependencies: none
- Wheel entries: 74

Inspection found no bundled weights, ignored output/build directories, private
absolute paths, or detected credentials.

The post-commit rebuild of these exact bytes was installed into a fresh
checkout-external uv Python 3.12 environment with `--offline --no-index
--no-deps`. From that environment:

- `local-gpu-imagegen verify` returned `ok: true`, version `0.8.0`, 17 tools;
- `doctor`, with both backend URLs forced to `127.0.0.1:1`, failed closed with
  exit code 1 and `ready: false`;
- Codex and Claude Code setup used fake client executables and remained planned
  with `applied: false`;
- all 32 installed Python source files compiled to 32 bytecode files.

The earlier audit wheel at `058718a`, SHA-256
`710a1a98eae4c9c37bd5f4cd6cc294d47f50bd2565bb6814fb8221adda03f119`,
is superseded buildability evidence and must not be published.

## Python 3.11 Limitation

Python 3.11 is not installed locally. The audit did not download or install it.
Therefore the package's declared 3.11 floor remains locally unverified for the
final candidate. Exact-commit Windows and Ubuntu CI on Python 3.11 must close
that gate before publication; Python 3.12 local validation cannot substitute
for it.

## Closed Copy, EOL, And Version-Coherence Gates

### Historical real demo portability

Before repair, running:

```powershell
python scripts\validate_real_demo.py docs\demo\real
```

returned 12 findings:

```text
artifact_sha256_mismatch:README.md
artifact_sha256_mismatch:mcp-result.json
artifact_sha256_mismatch:run-manifest.json
artifact_sha256_mismatch:transcript.md
artifact_size_mismatch:README.md
artifact_size_mismatch:mcp-result.json
artifact_size_mismatch:run-manifest.json
artifact_size_mismatch:transcript.md
client_session_sha256_mismatch
invalid_client_session
mcp_result_sha256_mismatch
server_version_mismatch
```

The repair pins demo/client evidence text to LF checkout bytes and adds an
explicit expected-version argument. This command now returns `ok: true` with no
findings while preserving every historical identity field:

```powershell
python scripts\validate_real_demo.py docs\demo\real --expected-server-version 0.7.0
```

The first eleven findings arise from checkout line-ending drift in hash-bound
text artifacts and the retained client record. The final finding arises because
the validator currently compares an honest historical 0.7 demo with the current
package version 0.8. The repair must pin portable bytes and accept an explicit
expected historical version. It must not replace `0.7.0` with `0.8.0`.

### Stale active release copy

The following active release documents still describe 0.7.0 and/or 15 tools:

- `docs/release-checklist.md`
- `docs/client-compatibility.md`
- `docs/directory-listings.md`

`docs/directory-listings.md` also describes a 0.7 PyPI package as if it were an
available listing target even though no package publication occurred. Prepared
copy must distinguish future publication metadata from current public state.

## Evidence That Cannot Be Relabeled

`docs/evidence/client-sessions/codex-v070.json` is a real historical Codex
generation record for server 0.7.0. It validates when the expected version is
0.7.0. It is not a v0.8 named-client record and cannot be counted as one.

`docs/evidence/client-sessions/codex-v080-workflow-onboarding.json` is a real
v0.8 zero-GPU onboarding record. It validates at 0.8.0, but it intentionally
contains no generated image and cannot be counted as GPU-generation evidence.

Combining those records as one v0.8 release set fails with:

```text
named_client_release_set_required
release_set_server_version_mismatch
server_version_mismatch
```

There is no retained Claude Code session record and no current-v0.8 genuine
generation release set. Documentation must state those facts directly.

## Resolved Acceptance Policy

Non-strict validation currently returns:

```json
{
  "ok": true,
  "strict": false,
  "run_count": 0,
  "revision_count": 0,
  "release_ready": false
}
```

Strict validation fails because all nine roots are absent; all three declared
revisions are also absent. The strict validator is functioning as designed.

The initial conflict was in policy copy:

- v0.8 preview copy truthfully says complete 9+3 evidence is not retained;
- `docs/evidence/README.md` and the old checklist still describe strict 9+3 as
  the immediate release gate.

The approved and implemented resolution is:

1. Preserve `--strict` and its exact 9+3 behavior as the full-acceptance/v1.0
   gate.
2. Define a bounded v0.8 preview gate around exact-commit tests, clean wheel
   install, 17-tool verification, fail-closed doctor behavior, safe named-client
   setup contracts, honest historical 0.7 generation evidence, v0.8 zero-GPU
   onboarding evidence, and explicit limitations.
3. Do not claim current-v0.8 GPU generation, complete named-client generation,
   image-quality improvement, or strict acceptance.

The policy was explicitly approved before public copy adopted it. The strict
validator code and its complete-matrix tests were not weakened.

## Separately Authorized Gates

The following are not part of the no-GPU coherence repair:

- a real Claude Code hosted session;
- a current-v0.8 named-client GPU generation and retained release set;
- any new public image or GPU comparison;
- backend start, model use, trust mutation, or client mutation;
- remote CI reruns, push, tag, GitHub Release, PyPI upload, MCP Registry
  publication, directory submission, or remote metadata change.

Each requires its own authority. Absence of those actions must remain visible in
the release checklist.

## Bounded Delivery Record

The approved local publication cut remained inside the 3-5 focused-day bound:

| Day | Deliverable | Stop condition |
| --- | --- | --- |
| 1 | Freeze v0.8/17-tool and evidence-class contracts in tests | Any need to change the MCP surface or production ownership |
| 1-2 | Repair historical demo EOL portability and explicit version validation | Any proposal to relabel or regenerate historical evidence |
| 2 | Implement the approved preview/full-acceptance policy split | Any weakening of strict 9+3 validation |
| 2-3 | Synchronize checklist, compatibility, evidence, and directory copy | Any unsupported publication or image-quality claim |
| 3-4 | Build the final exact-commit wheel and repeat Python 3.12 validation | Any wheel content, install, or stdio regression |
| 4-5 | Exact-commit Python 3.11/3.12 CI and separately approved publication actions | Any CI failure or public digest mismatch |

No image-quality engineering is included in this cut. Current-v0.8 GPU evidence
can be added later only under separate authority and a bounded evidence budget.

## Publication Decision

The local v0.8 preview candidate may proceed to exact-commit CI. Do not publish
the superseded audit wheel. Do not push or publish the final deterministic wheel
until Python 3.11/3.12 exact-commit CI passes and each remote action receives
separate authority. Current-v0.8 GPU generation, complete named-client
generation, image-quality improvement, and strict 9+3 acceptance remain
unclaimed.
