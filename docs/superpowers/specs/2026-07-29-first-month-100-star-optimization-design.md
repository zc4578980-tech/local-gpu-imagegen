# First-Month 100-Star Optimization Design

Date: 2026-07-29

Status: ready for user review

## Capability

The release operator can freeze one exact Local GPU Imagegen candidate, prove
that its PyPI wheel and MCP Registry descriptor are coherent and installable,
retain one truthful current-v0.8 public generation artifact, and make an
evidence-backed first-month adoption decision. `100 net-new GitHub Stars` is
the minimum acceptable outcome and planning floor, not the operating target or
a guarantee.

## Fixed Policy

- Keep the MCP server at exactly 17 tools. Release verification is a maintainer
  script, not a user-facing MCP tool.
- Consume an already-built wheel. The verifier must never rebuild or publish it.
- Keep all verification offline by default. No model, dependency, Python, or
  package download is permitted during candidate verification.
- Treat PyPI publication, MCP Registry publication, push, tag, GitHub Release,
  metadata changes, and directory submissions as separate authority gates.
- Keep the current-v0.8 private image private unless full-resolution review,
  candidate derivation, byte-bound finalization, public rights, sanitization,
  and explicit export authority all succeed.
- A new GPU round requires a separately displayed cost, time, route, prompt,
  seed, round budget, stop condition, and later exact approvals. No fallback,
  silent model switch, download, or reuse of an old route/run/approval is
  allowed.
- Forecast inputs must be cited. Unknown reach is zero; overlapping audiences
  are deduplicated; a value below 100 is never rounded up.

## Delivery Sequence

The work is divided into three independently verifiable milestones. A failed
milestone stops its dependent work without undoing already verified local
results.

1. Offline release-candidate verification.
2. Current-v0.8 public evidence gate.
3. Evidence-backed 30-day adoption forecast.

The final repository verification and continuity update occur only after all
locally authorized work has reached either `passed` or an explicit fail-closed
state.

## Milestone 1: Offline Release-Candidate Verification

### Surface

Add `scripts/validate_release_candidate.py`. It accepts:

```text
--wheel <path>
--expected-commit <40-hex-sha>
--expected-wheel-sha256 <64-hex-sha>
--python <python-3.12-path>
--report <optional-output-json>
```

The command writes one JSON result to stdout and, when requested, atomically
writes the same canonical JSON to `--report`. It returns zero only when every
required check passes.

### Static Checks

- The checkout `HEAD` equals `--expected-commit`, and tracked working and index
  state are clean. Ignored or untracked operator-local files are reported but
  do not silently become release content.
- The wheel is a regular file, has the expected SHA-256, uses the expected
  `local_gpu_imagegen-0.8.0-py3-none-any.whl` identity, and contains one closed
  distribution metadata set.
- Wheel metadata agrees with `pyproject.toml`, `server.json`, the CLI package
  version, Python `>=3.11`, and the dependency-free runtime contract.
- `server.json` resolves `local-gpu-imagegen==0.8.0` through PyPI, `uvx`, stdio,
  and the positional `serve` argument.
- Archive entries reject absolute paths, parent traversal, links, model-weight
  extensions, private run/output directories, credentials, and known personal
  absolute paths. Entry count is reported, not hard-coded as product behavior.

### Installed Checks

The verifier creates a temporary environment outside the checkout with the
provided Python 3.12 standard-library `venv` and its bundled `ensurepip`, then
installs only the exact wheel through `python -m pip install --no-index
--no-deps`. If the interpreter cannot create that offline environment, the
candidate is blocked; the verifier never downloads a replacement. It removes
the temporary environment on completion. From that environment it requires:

- `local-gpu-imagegen verify` returns `ok: true`, version `0.8.0`, protocol
  `2024-11-05`, and exactly 17 named tools;
- `doctor`, with both backend endpoints pinned to unused loopback port `1`,
  returns exit code `1` and `ready: false`;
- Codex and Claude Code setup dry-runs remain `planned` and `applied: false`
  when bounded fake client executables are supplied;
- installed Python sources compile successfully;
- no subprocess runs from the source checkout or inherits `PYTHONPATH`.

### Result States

The top-level status is `passed` or `blocked`. Every check records an ID,
status, and bounded observation. Failures contain sanitized operator actions
and no traceback by default. The report includes candidate commit, wheel name,
size, SHA-256, package version, protocol, tool count, and check results, but no
credentials or private absolute model/run paths.

## Milestone 2: Current-v0.8 Public Evidence Gate

### Existing-Run Review First

Run `20260729T111010Z-3f2a96a5d440` remains `generated / unreviewed`. Review its
original PNG at full resolution against the existing visual and semantic
rubric. The known missing directional beacon beam and unrequested red
crescent-like object must be evaluated as prompt-constraint evidence, not
explained away as style.

Possible transitions are:

```text
generated/unreviewed -> reviewed/ineligible -> retained private negative evidence
generated/unreviewed -> reviewed/eligible -> candidate -> explicit finalize approval
```

No review status alone grants finalization, export, public rights, or release
authority.

### Bounded Replacement Run

If the existing image is ineligible, prepare one fresh managed-MCP proposal
using the already authorized exact SDXL file only after revalidating current
process, model, workflow, and route identity. Display the complete cost and
execution boundary, then stop for approval. The default design ceiling is two
successful rounds in one fresh run, with one explicit review between rounds,
no parallel candidates, and immediate stop after the first eligible candidate
or exhausted budget.

The second round may change only review-identified prompt fields and must retain
the approved model, workflow topology, dimensions, and no-download/no-fallback
policy. A different model, route, workflow, seed policy, or budget requires a
new proposal.

### Public Artifact Contract

An accepted release artifact must retain the original finalized PNG, sanitized
MCP result, exact model/workflow/route/run/image hashes, full-resolution review,
public rights statement, named-client binding, limitations, and a portable
manifest validated by the existing public evidence tooling. A current-v0.8
artifact replaces no historical bytes; the historical v0.7 demo remains
clearly labeled.

## Milestone 3: Evidence-Backed Adoption Forecast

### Benchmark Input

Perform read-only, timestamped research over a bounded set of direct MCP image
generation projects, adjacent ComfyUI integrations, and aspirational local-AI
developer tools. Record current Stars, repository age, recent activity,
first-viewport offer, visual proof, Quickstart, package/Registry availability,
named clients/backends, and evidence discipline. Current totals are not treated
as first-month history when historical observations are unavailable.

Store raw benchmark facts and calculations only under ignored
`outputs/v080-launch-private/`. Do not publish competitor rankings or
unsupported superiority claims.

### Channel Input

A pessimistic channel receives nonzero exposure only when it has:

- one named owner;
- one available and authorized launch action;
- one timing window;
- one defensible unique qualified-exposure floor;
- one cited reason that floor is reachable.

MCP Registry, PyPI, GitHub, directories, and communities are deduplicated when
their audiences overlap. Algorithmic discovery, uncommitted placements,
unmeasured social reach, Bilibili, and Douyin remain zero until measured.

### Formula And Decision

For each channel and scenario:

```text
expected_stars = unique_qualified_exposures * repository_visit_rate * star_conversion_rate
scenario_total = sum(deduplicated expected_stars)
```

Produce pessimistic, base, and upside scenarios with citations and confidence
labels. The release decision is exactly one of:

```text
PASS: pessimistic 30-day estimate is at least 100 net-new GitHub Stars;
technical and authority gates remain independently required.
```

```text
BLOCKED: pessimistic 30-day estimate is below 100 net-new GitHub Stars or
depends on an unproven reach floor; formal release is prohibited.
```

Only a supported `PASS` may check the forecast item in
`docs/release-checklist.md`. A `BLOCKED` result must name the smallest next
prelaunch experiment, observation window, success metric, maximum cost, and
stop condition. Forecast numbers remain private and are never presented as a
public guarantee.

## Testing

- Follow RED/GREEN TDD for the release-candidate verifier.
- Unit-test malformed hashes, dirty tracked state, wrong commit, wheel path and
  ZIP attacks, metadata/Registry drift, unsafe entries, subprocess failures,
  report atomicity, and output sanitization.
- Add one real offline wheel integration test reusing existing packaging
  fixtures; normal tests must not access a network, GPU, model, or real client
  configuration.
- Re-run the focused tests, full model-free suite, compilation, 17-tool MCP
  verifier, client setup contracts, public evidence validators, strict JSON
  parsing, and all diff checks at the final exact commit.
- Evidence review and forecast calculations use structured validators or
  independently recomputed formulas where available; they never become unit
  tests for subjective image quality or future user behavior.

## Failure And Recovery

- Candidate verification failure produces `blocked`, preserves the wheel, and
  performs no publication action. The operator fixes the source mismatch and
  builds a new candidate rather than relabeling the old artifact.
- Image-review failure retains the raw artifact privately and consumes no
  finalization or publication authority. A replacement run starts from fresh
  identity and approval state.
- Forecast failure blocks formal release but does not weaken engineering,
  evidence, or authority gates. It creates one measurable conversion
  experiment instead of adding speculative channels.
- Interrupted temporary installation is safe to remove because it owns no
  source, trust, model, workflow, or publication state.

## Non-Goals

- No eighteenth MCP tool, backend installer, model download, model switch,
  custom-node support, UI-workflow conversion, quality-superiority claim,
  performance claim, or concurrency claim.
- No automatic PyPI upload, Registry publication, GitHub push/tag/Release,
  metadata mutation, directory submission, or community post.
- No public forecast guarantee and no manipulation or purchase of Stars.

## Acceptance

The optimization is locally complete when:

1. One exact candidate passes the offline release-candidate verifier and its
   report is reproducible and sanitized.
2. The current-v0.8 evidence lane ends in either a fully validated publishable
   artifact or an explicit review/GPU/authority blocker with no false claim.
3. The forecast lane produces a cited `PASS` or `BLOCKED` result using the
   fixed floor and transparent formula.
4. All model-free verification passes at one exact commit, continuity files
   record remaining authority gates, and no remote mutation occurred.

## Implementation Handoff

Implement Milestone 1 first through TDD. Stop after displaying any exact GPU,
finalization, export, or publication proposal required by Milestone 2. Perform
Milestone 3 only against the latest verified conversion surface, and keep its
private evidence ignored. Do not combine remote authority gates.
