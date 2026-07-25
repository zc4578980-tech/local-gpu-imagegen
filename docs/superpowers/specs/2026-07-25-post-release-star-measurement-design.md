# Post-Release Star Measurement Design

**Date:** 2026-07-25

**Status:** Approved

**Branch:** `codex/post-release-star-measurement`

**Supersedes:** The pre-release 100-Star forecast gate in
`2026-07-24-github-conversion-release-gate-design.md`

## Decision

The `100 GitHub Stars` objective is a post-release adoption goal, not a
publication prerequisite. Engineering readiness, truthful evidence, exact
artifact identity, green CI, and explicit authority remain hard release gates.
A forecast or Star count does not replace any of them.

The campaign measures net-new repository Stars during the first 30 days after
the formal GitHub Release is published:

```text
net_new_stars = effective_t30_repository_star_count
                - effective_baseline_repository_star_count
```

The target is `net_new_stars >= 100`. Missing the target does not retract,
hide, or invalidate the Release. It triggers a documented review and the next
bounded product or distribution experiment.

## Goals

- Anchor one adoption campaign to one repository and one formal GitHub
  Release.
- Preserve an append-only, machine-verifiable record of repository-level Star
  count observations.
- Distinguish evidence integrity from campaign outcome.
- Produce exactly one of `goal_met`, `goal_missed`, or
  `measurement_incomplete` without interpolation or hidden correction.
- Keep collection model-free, GPU-free, dependency-free, and outside the MCP
  runtime.

## Non-Goals

- No stargazer identities, account data, follower data, traffic analytics, or
  individual attribution.
- No estimate of when an individual Star was created.
- No interpolation between observations and no reconstruction of unavailable
  historical counts.
- No automatic unstar filtering, bot classification, channel attribution, or
  causal claim.
- No MCP tool, backend behavior, generation route, trust state, client state,
  package runtime dependency, GitHub Action, automatic commit, or automatic
  push.
- No Release, tag, PyPI, MCP Registry, Topics, Discussions, or repository
  metadata mutation under this design.

## Campaign Identity And Time

Each campaign is bound to:

- one `owner/repository` name;
- one numeric GitHub Release ID;
- one exact Release tag;
- one formal Release URL; and
- the Release API's non-null `published_at` timestamp.

Drafts and releases without `published_at` cannot initialize a campaign. The
formal `published_at` value is immutable campaign metadata and defines:

```text
baseline_scheduled_at = release.published_at
t30_scheduled_at = release.published_at + 30 days
t30_window_closes_at = t30_scheduled_at + 24 hours
```

The campaign ID is a filesystem-safe caller-selected slug, normally
`v0.8.0-release-<release_id>`. It must equal the final campaign-directory name.
The recorder rejects reuse of an existing campaign ID for different release or
repository metadata.

## Evidence Ownership

Tracked campaign evidence lives only at:

```text
docs/evidence/adoption/<campaign_id>/campaign.json
docs/evidence/adoption/<campaign_id>/events.jsonl
```

`campaign.json` is created once. It contains the immutable campaign identity,
metric, target, timing policy, event filename, and hash algorithm. It has this
closed logical shape:

```json
{
  "schema_version": "1.0",
  "campaign_id": "v0.8.0-release-123456",
  "repository": "owner/local-gpu-imagegen",
  "release": {
    "id": 123456,
    "tag_name": "v0.8.0",
    "html_url": "https://github.com/owner/local-gpu-imagegen/releases/tag/v0.8.0",
    "published_at": "2026-07-25T12:00:00Z"
  },
  "goal": {
    "metric": "net_new_repository_stars",
    "target": 100,
    "target_days": 30,
    "baseline_grace_seconds": 300,
    "collection_window_hours": 24
  },
  "events_file": "events.jsonl",
  "hash_algorithm": "sha256"
}
```

The public schemas live at:

- `docs/evidence/schemas/star-campaign.schema.json`
- `docs/evidence/schemas/star-event.schema.json`

The schemas document the closed file shapes. The standard-library validator
enforces those shapes and all cross-record semantics without adding a JSON
Schema runtime dependency.

## Append-Only Event Model

Each non-empty `events.jsonl` line is one canonical ASCII JSON object. Events
contain these fields:

```json
{
  "schema_version": "1.0",
  "sequence": 1,
  "event_type": "observation",
  "phase": "baseline",
  "recorded_at": "2026-07-25T12:01:00Z",
  "scheduled_at": "2026-07-25T12:00:00Z",
  "observed_at": "2026-07-25T12:01:00Z",
  "observation_status": "observed",
  "repository_star_count": 7,
  "source": {
    "api_url": "https://api.github.com/repos/owner/local-gpu-imagegen",
    "response_date": "2026-07-25T12:01:00Z",
    "etag": "bounded opaque value or null"
  },
  "failure": null,
  "supersedes_sequence": null,
  "correction_reason": null,
  "previous_event_sha256": null,
  "event_sha256": "64 lowercase hexadecimal characters"
}
```

Allowed values and relationships are:

- `event_type` is `observation` or `correction`.
- `phase` is `baseline` or `t30`.
- `observation_status` is `observed` or `observation_failed`.
- An observed event has a non-negative integer
  `repository_star_count` and null `failure`.
- A failed event has null `repository_star_count` and a bounded failure object
  containing only `kind` and `message`.
- A normal observation has null `supersedes_sequence` and
  `correction_reason`.
- A correction names one earlier event from the same phase, supplies a
  non-empty bounded reason, and becomes that phase's effective event.
- A correction may supersede only the currently effective event for its phase;
  this prevents ambiguous correction branches.
- `source.response_date` and `source.etag` are always present but may be null
  when the corresponding bounded HTTP response header is unavailable.
- Baseline and T+30 counts are independent non-negative integers. A later
  count may be lower than an earlier count.
- Events never contain stargazer lists, logins, IDs, emails, tokens, raw API
  bodies, or request headers.

An API failure after campaign initialization is retained as
`observation_failed`. It is not silently retried away or overwritten. A later
successful observation is another event. Corrections also append; no command
rewrites or deletes an earlier line.

## Hash Chain

Events use a forward SHA-256 chain:

1. The first event has `sequence: 1` and `previous_event_sha256: null`.
2. Every later sequence is exactly the previous sequence plus one and names
   the previous event's `event_sha256`.
3. `event_sha256` is SHA-256 over canonical JSON for that event with the
   `event_sha256` field omitted.
4. Canonical JSON uses sorted keys, separators `,` and `:`, `ensure_ascii=True`,
   `allow_nan=False`, and UTF-8/ASCII bytes.
5. The stored full event line must itself be canonical JSON followed by one
   newline.

This detects edits, deletion, reordering, insertion, and broken links inside
the retained file. It does not claim an external timestamp authority or make a
local repository immune to wholesale replacement. Git history and release
review provide the outer provenance boundary.

## Collection Workflow

### Baseline

The baseline command reads the formal Release through GitHub's REST API,
rejects a draft or missing publication timestamp, creates `campaign.json`, and
then reads the repository endpoint's `stargazers_count`.

The count's `observed_at` is the local UTC time immediately after the complete
repository response is parsed. The recorder also retains the normalized HTTP
`Date` and bounded `ETag` values when present. An observation at or before
`published_at + 5 minutes` has `on_time` quality. A later valid baseline is
`degraded`; it remains usable, but the validator reports the delay and never
pretends the count came from publication time.

If the Release cannot be identified, no campaign is created because there is
no trustworthy anchor. If campaign creation succeeds but repository-count
collection fails, the recorder appends `observation_failed`.

### T+30

The T+30 command reads immutable campaign metadata and queries only the bound
repository. A usable T+30 count must be observed in the inclusive interval:

```text
[release.published_at + 30 days,
 release.published_at + 30 days + 24 hours]
```

Early, late, and failed events remain valid history but cannot determine the
campaign outcome. The recorder does not sleep until the window and does not
schedule itself. A human or separately authorized scheduler invokes it.

### Corrections

The correction command requires the campaign directory, the exact effective
sequence being superseded, the corrected count or failed status, the original
observation time, a source URL, and a concise reason. It displays and appends a
new correction event. The target event remains byte-for-byte unchanged.

A correction cannot change campaign identity, phase, schedule, Release time,
target, or timing policy. It cannot make an out-of-window observation appear
in-window by changing `observed_at` without leaving the supplied reason and
new hash-linked event in history.

## Recorder Boundary

`scripts/record_star_observation.py` is a repository-maintenance CLI, not an
installed package command. It uses only Python 3.11 standard-library modules.

It provides three explicit subcommands:

```text
baseline --campaign-id ... --repository ... --release-tag ...
observe --campaign-dir ... --phase baseline|t30
correct --campaign-dir ... --supersedes-sequence ...
```

The API client performs GET requests only against `api.github.com`, sends a
fixed User-Agent and media type, and uses `GITHUB_TOKEN` only when present in
the process environment. The token is never printed or persisted. Redirects
to another host, oversized responses, malformed JSON, repository mismatch,
and unexpected response shapes fail closed.

Before appending, the recorder validates the complete campaign and chain. It
uses an exclusive temporary lock, writes one canonical line, flushes and
`fsync`s it, then validates again. Existing campaign or event bytes are never
rewritten. The CLI prints a structured JSON summary and never commits or
pushes evidence.

## Validator Boundary

`scripts/validate_star_campaign.py` accepts one campaign directory and returns
a JSON report. It validates:

- strict UTF-8/ASCII JSON and closed field sets;
- campaign ID/directory agreement and immutable Release/goal policy;
- repository, Release URL, timestamp, integer, enum, and bounded-string forms;
- exact event sequence and canonical-line encoding;
- every event hash and previous-hash link;
- phase schedules derived from `published_at`;
- observation/failure nullability rules;
- linear correction references and same-phase ownership;
- absence of stargazer identity fields and credential-like values; and
- effective baseline, effective T+30, timing quality, net-new count, and
  outcome.

`ok` reports structural and integrity validity. The campaign outcome is a
separate field:

- `goal_met`: usable baseline and in-window T+30 exist, and net new Stars are
  at least 100.
- `goal_missed`: usable baseline and in-window T+30 exist, and net new Stars
  are below 100, including a negative result.
- `measurement_incomplete`: no usable observed baseline or no usable in-window
  T+30 observation exists.

An intact campaign may therefore return `ok: true` with
`measurement_incomplete` or `goal_missed`. Neither is a repository-integrity
failure, and neither retracts the Release. Structural findings make `ok: false`
and produce a nonzero CLI exit.

## Active-Document Migration

Current release surfaces must stop describing a pessimistic 100-Star forecast
as a publication blocker:

- `docs/release-checklist.md` moves the target out of the publication gate and
  names it as post-release measurement.
- `docs/github-listing.md` lists only actual technical/evidence/authority
  blockers and states that the 30-day net-new target starts at formal Release
  publication.
- `docs/evidence/README.md` documents the adoption-evidence directory,
  collection commands, privacy boundary, and outcome meanings.

Approved historical design and plan documents are not rewritten. The
following receive a prominent `Superseded` notice linking this design while
retaining their original decision text as history:

- `docs/superpowers/specs/2026-07-24-github-conversion-release-gate-design.md`
- `docs/superpowers/plans/2026-07-24-github-conversion-release-gate.md`

## Failure Policy

- Missing or draft Release metadata prevents campaign creation.
- A repository observation failure after campaign creation is retained as an
  event and leads to `measurement_incomplete` until a usable event exists.
- A baseline delayed more than five minutes is retained, labeled `degraded`,
  and remains usable without interpolation.
- A T+30 count outside the 24-hour window is retained but not used for the
  outcome.
- Hash, canonicalization, sequence, correction, schema, or identity mismatch
  makes validation fail; tooling does not repair it in place.
- A lower T+30 count is accepted and may produce a negative net-new value.
- `goal_missed` triggers review and iteration. It does not retract the Release
  or retroactively change release readiness.
- Network access for a real observation and any later commit or push remain
  distinct human-authorized operations.

## Verification Strategy

Focused model-free tests cover:

- closed campaign and event schemas;
- canonical event hashing and full-chain validation;
- tampering, deletion, reordering, duplicate sequence, and broken links;
- observed/failure nullability and bounded source metadata;
- on-time and degraded baselines;
- early, in-window, and late T+30 events;
- decreasing counts and all three outcomes;
- append-only linear corrections;
- Release/repository API parsing, host and redirect rejection, response-size
  limits, token non-persistence, and retained failures;
- lock contention, pre-append invalid history, atomic append behavior, and
  post-append validation; and
- active-document migration and historical Superseded notices.

The final implementation gate is:

```powershell
python -m unittest tests.test_validate_star_campaign tests.test_record_star_observation tests.test_public_docs -v
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
python -c "import json, pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('docs/evidence/schemas').glob('*.json')]"
git diff --check
git diff --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
```

Tests use temporary directories and mocked HTTP responses. They do not call
GitHub, start a backend, use a GPU, download a model, mutate trust/client
state, or create real campaign evidence.

## Acceptance Criteria

1. The campaign and event schemas are closed and documented.
2. The validator rejects any structural, semantic, canonicalization, or hash
   chain drift and reports the three approved outcomes exactly.
3. The recorder can initialize a formal-Release campaign, append observations,
   retain failures, and append corrections without rewriting history.
4. Only repository-level Star totals and bounded source metadata are stored.
5. Baseline grace, T+30 window, non-monotonic counts, and correction behavior
   match this design.
6. Active release documents no longer make 100 Stars a pre-release blocker.
7. Historical gate documents retain their text under an explicit Superseded
   notice.
8. No MCP/runtime dependency, backend/GPU action, remote mutation, scheduled
   job, automatic commit, or automatic push is introduced.

## Delivery Order

1. Add closed schemas, the semantic/hash-chain validator, and focused tests.
2. Add the append-only recorder and mocked-network tests.
3. Migrate active documents, add historical notices, and run the full
   model-free verification gate.
4. Stop. Real baseline collection requires a separately authorized formal
   GitHub Release and a later explicit observation operation.
