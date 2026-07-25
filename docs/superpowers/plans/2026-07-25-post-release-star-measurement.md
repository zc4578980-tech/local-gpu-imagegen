# Post-Release Star Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add append-only, hash-chained repository Star observations for one formal GitHub Release and measure the post-release 30-day net-new goal without making it a publication gate.

**Architecture:** Keep adoption measurement outside the MCP runtime. A standard-library validator owns the closed campaign/event contract, canonical hash chain, timing semantics, corrections, and outcomes; a separate standard-library recorder performs bounded read-only GitHub API collection and append-only writes. Active release documents adopt the post-release policy, while the prior approved gate documents remain unchanged except for prominent Superseded notices.

**Tech Stack:** Python 3.11/3.12 standard library, `unittest`, JSON Schema documents, Markdown, PowerShell, Git.

## Global Constraints

- Work only in `.worktrees/post-release-star-measurement` on `codex/post-release-star-measurement`; do not modify `main`.
- Parent design: `docs/superpowers/specs/2026-07-25-post-release-star-measurement-design.md` at commit `07017c8`.
- Add exactly two repository-maintenance scripts: `validate_star_campaign.py` and `record_star_observation.py`. Add no MCP tool, installed CLI command, production package module, GitHub Action, scheduler, or dependency.
- Do not add either script to `pyproject.toml` `py-modules`; they are repository-only maintenance tools. The two public schema files may continue to match the existing `docs/evidence/schemas/*.json` package-data rule.
- Evidence stores repository-level `stargazers_count` only. Never request or retain the stargazers collection, account identities, raw API bodies, credentials, traffic analytics, or channel attribution.
- The formal GitHub Release `published_at` is the only campaign clock anchor. Baseline grace is exactly `300` seconds; T+30 is exactly `30` days after publication; the inclusive collection window closes exactly `24` hours later.
- The target is exactly `100` net-new Stars. The only outcomes are `goal_met`, `goal_missed`, and `measurement_incomplete`; none is a publication or retraction decision.
- Existing event lines are never rewritten or deleted. Corrections append and may supersede only the current effective event in the same phase.
- Use canonical JSON with `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`, and `allow_nan=False`. Hash each event without its `event_sha256` field and link every later event to the prior hash.
- All automated tests are temporary-directory and mocked-network tests. Do not call GitHub or create real adoption evidence while implementing.
- Do not start a backend, run GPU generation, download a model, mutate client/trust state, reopen regional/two-stage work, push, tag, publish, release, or mutate remote metadata.
- Do not stage or rewrite `workflows/comfyui/sdxl-regional-txt2img-v1.json` or `workflows/comfyui/sdxl-two-stage-copy-subject-v1.json`; exact working-tree and cached diffs must remain zero.
- Keep the two script implementations focused near the approved approximately 500-line net production-tooling budget. If the two scripts materially exceed it, stop before adding another module and document why the extra code is necessary for the approved integrity or failure policy; the threshold is a design-review trigger, not a license to omit required safety behavior.
- Preserve the three implementation commit boundaries in this plan. Do not squash schema/validator, recorder, and document migration into one commit.

## File Map

| File | Responsibility |
|---|---|
| `docs/evidence/schemas/star-campaign.schema.json` | Closed immutable campaign metadata shape. |
| `docs/evidence/schemas/star-event.schema.json` | Closed observation/correction event shape and field-level constraints. |
| `scripts/validate_star_campaign.py` | Canonical JSON, event hashes, semantic validation, effective observations, timing quality, and outcome report. |
| `tests/test_validate_star_campaign.py` | Schema, chain, correction, timing, outcome, tamper, and CLI tests. |
| `scripts/record_star_observation.py` | Bounded GET-only GitHub client, campaign initialization, lock-protected append, failure retention, corrections, and CLI. |
| `tests/test_record_star_observation.py` | Mocked API, append-only, failure, lock, redirect/size/token, and CLI tests. |
| `tests/test_public_docs.py` | Active-policy and historical-notice regression tests. |
| `docs/evidence/README.md` | Public evidence ownership, commands, privacy, and outcome interpretation. |
| `docs/release-checklist.md` | Technical release gate separated from post-release adoption goal. |
| `docs/github-listing.md` | Accurate remaining blockers and post-release campaign statement. |
| Two 2026-07-24 conversion design/plan files | Historical text retained under a Superseded notice. |

---

### Task 1: Add Closed Schemas And The Hash-Chain Validator

**Files:**
- Create: `docs/evidence/schemas/star-campaign.schema.json`
- Create: `docs/evidence/schemas/star-event.schema.json`
- Create: `scripts/validate_star_campaign.py`
- Create: `tests/test_validate_star_campaign.py`

**Interfaces:**
- Produces: `canonical_json(value: object) -> bytes`.
- Produces: `parse_utc(value: object) -> datetime | None` and `format_utc(value: datetime) -> str`.
- Produces: `scheduled_at(campaign: dict[str, object], phase: str) -> datetime`.
- Produces: `event_sha256(event: dict[str, object]) -> str`.
- Produces: `make_event(*, sequence: int, event_type: str, phase: str, recorded_at: str, scheduled_at_value: str, observed_at: str, observation_status: str, repository_star_count: int | None, source: dict[str, object], failure: dict[str, str] | None, supersedes_sequence: int | None, correction_reason: str | None, previous_event_sha256: str | None) -> dict[str, object]`.
- Produces: `validate_campaign(campaign_dir: Path) -> dict[str, object]` with exact keys `ok`, `findings`, `campaign_id`, `event_count`, `effective_sequences`, `baseline_quality`, `t30_quality`, `baseline_count`, `t30_count`, `net_new_stars`, and `outcome`.
- CLI: `python scripts/validate_star_campaign.py <campaign-dir>` prints the sorted/indented report to stdout when valid, stderr when invalid, and exits `0` only when `ok` is true. `goal_missed` and `measurement_incomplete` remain exit `0` when structurally valid.
- Consumed by Task 2: all six functions above and the exact report shape.

- [ ] **Step 1: Write the failing validator tests and helpers**

Create `tests/test_validate_star_campaign.py`. The module must insert
`scripts/` into `sys.path`, import `CAMPAIGN_FIELDS`, `EVENT_FIELDS`,
`canonical_json`, `event_sha256`, `make_event`, and `validate_campaign`, then
define these helpers with fixed campaign policy:

```python
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

PUBLISHED = "2026-07-25T12:00:00Z"
T30 = "2026-08-24T12:00:00Z"


def campaign_document(campaign_id: str = "v0.8.0-release-123456") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "repository": "owner/local-gpu-imagegen",
        "release": {
            "id": 123456,
            "tag_name": "v0.8.0",
            "html_url": "https://github.com/owner/local-gpu-imagegen/releases/tag/v0.8.0",
            "published_at": PUBLISHED,
        },
        "goal": {
            "metric": "net_new_repository_stars",
            "target": 100,
            "target_days": 30,
            "baseline_grace_seconds": 300,
            "collection_window_hours": 24,
        },
        "events_file": "events.jsonl",
        "hash_algorithm": "sha256",
    }


def source() -> dict[str, object]:
    return {
        "api_url": "https://api.github.com/repos/owner/local-gpu-imagegen",
        "response_date": "2026-07-25T12:01:00Z",
        "etag": '"fixture-etag"',
    }


def write_campaign(root: Path) -> Path:
    directory = root / "v0.8.0-release-123456"
    directory.mkdir()
    (directory / "campaign.json").write_text(
        json.dumps(campaign_document(), indent=2) + "\n", encoding="utf-8"
    )
    (directory / "events.jsonl").write_text("", encoding="ascii")
    return directory


def append_event(directory: Path, **overrides: object) -> dict[str, object]:
    lines = (directory / "events.jsonl").read_text(encoding="ascii").splitlines()
    prior = json.loads(lines[-1]) if lines else None
    values: dict[str, object] = {
        "sequence": len(lines) + 1,
        "event_type": "observation",
        "phase": "baseline" if not lines else "t30",
        "recorded_at": "2026-07-25T12:01:00Z" if not lines else "2026-08-24T12:10:00Z",
        "scheduled_at_value": PUBLISHED if not lines else T30,
        "observed_at": "2026-07-25T12:01:00Z" if not lines else "2026-08-24T12:10:00Z",
        "observation_status": "observed",
        "repository_star_count": 10 if not lines else 110,
        "source": source(),
        "failure": None,
        "supersedes_sequence": None,
        "correction_reason": None,
        "previous_event_sha256": None if prior is None else prior["event_sha256"],
    }
    values.update(overrides)
    event = make_event(**values)
    with (directory / "events.jsonl").open("a", encoding="ascii", newline="\n") as handle:
        handle.write(canonical_json(event).decode("ascii") + "\n")
    return event
```

Add these exact test cases:

```python
def test_empty_valid_campaign_is_measurement_incomplete(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        report = validate_campaign(write_campaign(Path(temporary)))
    self.assertTrue(report["ok"])
    self.assertEqual(report["outcome"], "measurement_incomplete")
    self.assertIsNone(report["net_new_stars"])

def test_reports_goal_met_and_goal_missed_for_non_monotonic_counts(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        met = write_campaign(Path(temporary))
        append_event(met)
        append_event(met)
        met_report = validate_campaign(met)
    self.assertEqual(met_report["outcome"], "goal_met")
    self.assertEqual(met_report["net_new_stars"], 100)
    with tempfile.TemporaryDirectory() as temporary:
        missed = write_campaign(Path(temporary))
        append_event(missed)
        append_event(missed, repository_star_count=7)
        missed_report = validate_campaign(missed)
    self.assertEqual(missed_report["outcome"], "goal_missed")
    self.assertEqual(missed_report["net_new_stars"], -3)

def test_baseline_after_five_minutes_is_degraded_but_usable(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        append_event(directory, observed_at="2026-07-25T12:05:01Z")
        append_event(directory)
        report = validate_campaign(directory)
    self.assertTrue(report["ok"])
    self.assertEqual(report["baseline_quality"], "degraded")
    self.assertEqual(report["outcome"], "goal_met")

def test_early_and_late_t30_are_retained_but_incomplete(self) -> None:
    cases = (
        ("2026-08-24T11:59:59Z", "early"),
        ("2026-08-25T12:00:01Z", "late"),
    )
    for observed_at, quality in cases:
        with self.subTest(quality=quality), tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(directory)
            append_event(directory, observed_at=observed_at)
            report = validate_campaign(directory)
            self.assertTrue(report["ok"])
            self.assertEqual(report["t30_quality"], quality)
            self.assertEqual(report["outcome"], "measurement_incomplete")
            self.assertIsNone(report["t30_count"])

def test_failed_observation_is_valid_history_but_not_a_count(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        append_event(
            directory,
            observation_status="observation_failed",
            repository_star_count=None,
            failure={"kind": "http_error", "message": "GitHub returned HTTP 503"},
        )
        report = validate_campaign(directory)
    self.assertTrue(report["ok"])
    self.assertEqual(report["baseline_quality"], "failed")
    self.assertEqual(report["outcome"], "measurement_incomplete")

def test_correction_must_supersede_current_effective_same_phase_event(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        append_event(directory)
        append_event(
            directory,
            event_type="correction",
            phase="baseline",
            scheduled_at_value=PUBLISHED,
            observed_at="2026-07-25T12:02:00Z",
            repository_star_count=11,
            supersedes_sequence=1,
            correction_reason="Corrected transcription from the same API response.",
        )
        self.assertTrue(validate_campaign(directory)["ok"])
        append_event(
            directory,
            event_type="correction",
            phase="baseline",
            scheduled_at_value=PUBLISHED,
            supersedes_sequence=1,
            correction_reason="Stale correction target.",
        )
        self.assertIn("invalid_correction_target", validate_campaign(directory)["findings"])
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        append_event(directory)
        append_event(
            directory,
            event_type="correction",
            phase="t30",
            supersedes_sequence=1,
            correction_reason="Wrong phase.",
        )
        self.assertIn("correction_phase_mismatch", validate_campaign(directory)["findings"])

def test_rejects_tamper_noncanonical_line_broken_hash_and_bad_sequence(self) -> None:
    def count_tamper(events: list[dict[str, object]]) -> list[dict[str, object]]:
        events[0]["repository_star_count"] = 99
        return events

    def broken_link(events: list[dict[str, object]]) -> list[dict[str, object]]:
        events[1]["previous_event_sha256"] = "0" * 64
        events[1]["event_sha256"] = event_sha256(events[1])
        return events

    def bad_sequence(events: list[dict[str, object]]) -> list[dict[str, object]]:
        events[1]["sequence"] = 3
        events[1]["event_sha256"] = event_sha256(events[1])
        return events

    cases = (
        (count_tamper, "event_sha256_mismatch"),
        (broken_link, "previous_event_sha256_mismatch"),
        (bad_sequence, "invalid_event_sequence"),
    )
    for mutate, finding in cases:
        with self.subTest(finding=finding), tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(directory)
            append_event(directory)
            path = directory / "events.jsonl"
            events = [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]
            path.write_text(
                "".join(canonical_json(event).decode("ascii") + "\n" for event in mutate(events)),
                encoding="ascii",
                newline="\n",
            )
            self.assertIn(finding, validate_campaign(directory)["findings"])
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        append_event(directory)
        path = directory / "events.jsonl"
        path.write_text(path.read_text(encoding="ascii").rstrip("\n") + " \n", encoding="ascii")
        self.assertIn("noncanonical_event_line", validate_campaign(directory)["findings"])

def test_rejects_unknown_fields_identity_keys_bad_campaign_policy_and_path(self) -> None:
    mutations = (
        (lambda document: document.update({"unexpected": True}), "invalid_campaign_fields"),
        (lambda document: document["goal"].update({"target": 99}), "invalid_goal_policy"),
        (lambda document: document["goal"].update({"baseline_grace_seconds": 301}), "invalid_goal_policy"),
        (lambda document: document.update({"events_file": "other.jsonl"}), "invalid_events_file"),
        (lambda document: document.update({"campaign_id": "other"}), "campaign_id_path_mismatch"),
    )
    for mutate, finding in mutations:
        with self.subTest(finding=finding), tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            document = campaign_document()
            mutate(document)
            (directory / "campaign.json").write_text(json.dumps(document) + "\n", encoding="utf-8")
            self.assertIn(finding, validate_campaign(directory)["findings"])
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        event = append_event(directory)
        event["stargazer_login"] = "forbidden"
        event["event_sha256"] = event_sha256(event)
        (directory / "events.jsonl").write_text(
            canonical_json(event).decode("ascii") + "\n", encoding="ascii"
        )
        self.assertIn("identity_field_forbidden", validate_campaign(directory)["findings"])

def test_schema_documents_are_closed_and_parse_as_strict_json(self) -> None:
    for name in ("star-campaign.schema.json", "star-event.schema.json"):
        with self.subTest(name=name):
            schema = json.loads((ROOT / "docs" / "evidence" / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])
    campaign_schema = json.loads((ROOT / "docs" / "evidence" / "schemas" / "star-campaign.schema.json").read_text(encoding="utf-8"))
    event_schema = json.loads((ROOT / "docs" / "evidence" / "schemas" / "star-event.schema.json").read_text(encoding="utf-8"))
    self.assertEqual(set(campaign_schema["required"]), CAMPAIGN_FIELDS)
    self.assertEqual(set(event_schema["required"]), EVENT_FIELDS)
    self.assertFalse(campaign_schema["properties"]["release"]["additionalProperties"])
    self.assertFalse(campaign_schema["properties"]["goal"]["additionalProperties"])
    self.assertFalse(event_schema["properties"]["source"]["additionalProperties"])
    self.assertFalse(event_schema["properties"]["failure"]["additionalProperties"])

def test_cli_returns_zero_for_incomplete_valid_history_and_nonzero_for_tamper(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = write_campaign(Path(temporary))
        valid = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_star_campaign.py"), str(directory)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["outcome"], "measurement_incomplete")
        append_event(directory)
        path = directory / "events.jsonl"
        path.write_text(path.read_text(encoding="ascii").replace('"repository_star_count":10', '"repository_star_count":11'), encoding="ascii")
        invalid = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_star_campaign.py"), str(directory)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(invalid.returncode, 1)
        self.assertFalse(json.loads(invalid.stderr)["ok"])
```

- [ ] **Step 2: Run the validator tests to verify red**

Run:

```powershell
python -m unittest tests.test_validate_star_campaign -v
```

Expected: `ERROR` importing `validate_star_campaign` (or missing schema/file
assertions). No existing test should run in this focused red gate.

- [ ] **Step 3: Add both closed JSON Schema documents**

Create `star-campaign.schema.json` with draft 2020-12, top-level
`additionalProperties: false`, and required fields matching the approved
campaign example. Apply these exact constraints:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/zc4578980-tech/local-gpu-imagegen/blob/main/docs/evidence/schemas/star-campaign.schema.json",
  "title": "Post-release Star campaign",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "campaign_id", "repository", "release", "goal", "events_file", "hash_algorithm"],
  "properties": {
    "schema_version": {"const": "1.0"},
    "campaign_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,99}$"},
    "repository": {"type": "string", "pattern": "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", "maxLength": 200},
    "release": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "tag_name", "html_url", "published_at"],
      "properties": {
        "id": {"type": "integer", "minimum": 1},
        "tag_name": {"type": "string", "minLength": 1, "maxLength": 100},
        "html_url": {"type": "string", "pattern": "^https://github\\.com/", "maxLength": 500},
        "published_at": {"type": "string", "format": "date-time"}
      }
    },
    "goal": {
      "type": "object",
      "additionalProperties": false,
      "required": ["metric", "target", "target_days", "baseline_grace_seconds", "collection_window_hours"],
      "properties": {
        "metric": {"const": "net_new_repository_stars"},
        "target": {"const": 100},
        "target_days": {"const": 30},
        "baseline_grace_seconds": {"const": 300},
        "collection_window_hours": {"const": 24}
      }
    },
    "events_file": {"const": "events.jsonl"},
    "hash_algorithm": {"const": "sha256"}
  }
}
```

Create `star-event.schema.json` with the same draft, a closed top level, the 15
event fields from the design, and closed `source`/`failure` objects. Pin enums,
non-negative integer counts, nullable hashes/references/reasons, lowercase
64-hex hashes, UTC timestamp strings, an `api.github.com/repos/` source URL,
nullable `response_date`/`etag`, and bounded strings (`etag <= 500`, failure
kind `<= 100`, failure message and correction reason `<= 500`). Use `allOf`
branches so `observed` requires an
integer count plus null failure, `observation_failed` requires null count plus
the failure object, `observation` requires null supersession/reason, and
`correction` requires positive supersession plus a non-empty reason.

- [ ] **Step 4: Implement canonicalization, strict loading, and field validation**

Create `scripts/validate_star_campaign.py` with these constants and primitives:

```python
CAMPAIGN_FIELDS = {"schema_version", "campaign_id", "repository", "release", "goal", "events_file", "hash_algorithm"}
RELEASE_FIELDS = {"id", "tag_name", "html_url", "published_at"}
GOAL_FIELDS = {"metric", "target", "target_days", "baseline_grace_seconds", "collection_window_hours"}
EVENT_FIELDS = {"schema_version", "sequence", "event_type", "phase", "recorded_at", "scheduled_at", "observed_at", "observation_status", "repository_star_count", "source", "failure", "supersedes_sequence", "correction_reason", "previous_event_sha256", "event_sha256"}
SOURCE_FIELDS = {"api_url", "response_date", "etag"}
FAILURE_FIELDS = {"kind", "message"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAMPAIGN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
IDENTITY_KEY_RE = re.compile(r"(?i)(stargazer|login|user|account|email|token|authorization)")


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def event_sha256(event: dict[str, object]) -> str:
    payload = {key: value for key, value in event.items() if key != "event_sha256"}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
```

Implement `make_event` with the exact signature in Interfaces. It constructs
all fields except `event_sha256`, computes the hash, adds it, and returns the
event. It must not read or write files.

Strict loaders must reject a BOM, non-UTF-8 campaign JSON, non-ASCII event
bytes, blank event lines, non-object JSON, duplicate JSON keys (use
`object_pairs_hook`), and a non-canonical stored event line. Use finding names
`invalid_campaign_json`, `invalid_event_encoding`, `blank_event_line`,
`duplicate_json_key`, `invalid_event_json`, and `noncanonical_event_line`.

- [ ] **Step 5: Implement chain, correction, timing, and outcome validation**

Implement `scheduled_at` by parsing `release.published_at` and adding zero days
for `baseline` or 30 days for `t30`; unknown phases raise `ValueError`.

`validate_campaign` must never raise for malformed evidence. It accumulates a
sorted unique `findings` list and returns the exact report shape. Validate
campaign field sets and literal policy first. Then process event lines in file
order with these state variables:

```python
prior_hash: str | None = None
events_by_sequence: dict[int, dict[str, object]] = {}
effective: dict[str, dict[str, object]] = {}
```

For every event, require exact sequence, exact previous hash, exact recomputed
hash, campaign-derived schedule, valid timestamps, closed nested fields, and
the observed/failed nullability rules. A normal observation replaces the
effective event for its phase. A correction is accepted only when its
`supersedes_sequence` equals the current effective event sequence for that
same phase; then it replaces that effective event. Add deterministic findings
named in Step 1 rather than stopping at the first error.

Derive qualities exactly:

```python
baseline_quality = None | "on_time" | "degraded" | "failed"
t30_quality = None | "early" | "within_window" | "late" | "failed"
```

An observed baseline is usable at any time and is degraded only when
`observed_at > published_at + 300 seconds`. An observed T+30 event is usable
only inside the inclusive 24-hour interval. Failed effective events are not
usable. If the chain is structurally invalid, leave derived counts/net result
null and outcome `measurement_incomplete`.

When both observations are usable, subtract counts without a monotonicity
check. Return `goal_met` for delta `>= 100`; otherwise return `goal_missed`.

Implement `main()` with one positional `Path`, JSON output using
`indent=2, sort_keys=True`, stdout/stderr routing based only on `ok`, and exit
status based only on `ok`.

- [ ] **Step 6: Run focused tests and inspect line scope**

Run:

```powershell
python -m unittest tests.test_validate_star_campaign -v
(Get-Content scripts\validate_star_campaign.py).Count
git diff --check
```

Expected: all validator tests pass; no whitespace errors. Record the script
line count for the later two-script scope check.

- [ ] **Step 7: Commit schema and validator**

```powershell
git add -- docs/evidence/schemas/star-campaign.schema.json docs/evidence/schemas/star-event.schema.json scripts/validate_star_campaign.py tests/test_validate_star_campaign.py
git diff --cached --check
git commit -m "feat: validate post-release star campaigns"
```

Expected: one commit containing only the four Task 1 files.

---

### Task 2: Add The Append-Only GitHub Observation Recorder

**Files:**
- Create: `scripts/record_star_observation.py`
- Create: `tests/test_record_star_observation.py`
- Reuse unchanged: `scripts/validate_star_campaign.py`

**Interfaces:**
- Consumes: `canonical_json`, `event_sha256`, `format_utc`, `make_event`, `parse_utc`, `scheduled_at`, and `validate_campaign` from Task 1.
- Produces: immutable `ApiResult(document: dict[str, object], response_date: str | None, etag: str | None)`.
- Produces: `ObservationError(kind: str, message: str)` with bounded `kind` and credential-redacted `safe_message`.
- Produces: `GitHubApi(token: str | None = None, timeout_seconds: float = 15.0, max_response_bytes: int = 1_048_576)` and `get_json(url: str) -> ApiResult`.
- Produces: `initialize_campaign(adoption_root: Path, campaign_id: str, repository: str, release_tag: str, *, api: GitHubApi, now: Callable[[], datetime]) -> dict[str, object]`.
- Produces: `record_observation(campaign_dir: Path, phase: str, *, api: GitHubApi, now: Callable[[], datetime]) -> dict[str, object]`.
- Produces: `record_correction(campaign_dir: Path, *, supersedes_sequence: int, observation_status: str, repository_star_count: int | None, observed_at: str, source_url: str, failure_kind: str | None, failure_message: str | None, reason: str, now: Callable[[], datetime]) -> dict[str, object]`.
- Produces: `append_event(campaign_dir: Path, event_values: dict[str, object]) -> dict[str, object]`, protected by `<events.jsonl>.lock` and pre/post validation.
- CLI subcommands: `baseline`, `observe`, and `correct`, exactly as specified below.

- [ ] **Step 1: Write failing recorder tests with a fake API**

Create `tests/test_record_star_observation.py`, insert `scripts/` on
`sys.path`, import the Task 2 interfaces plus `canonical_json` and
`validate_campaign` from Task 1, and use this fake:

```python
class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._stream = io.BytesIO(body)
        self._url = url
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url


class FakeApi:
    def __init__(self, responses: dict[str, ApiResult | Exception]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get_json(self, url: str) -> ApiResult:
        self.urls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


REPOSITORY_URL = "https://api.github.com/repos/owner/local-gpu-imagegen"
RELEASE_URL = REPOSITORY_URL + "/releases/tags/v0.8.0"
BASELINE_NOW = datetime(2026, 7, 25, 12, 1, tzinfo=timezone.utc)
T30_NOW = datetime(2026, 8, 24, 12, 10, tzinfo=timezone.utc)


def release_result(**overrides: object) -> ApiResult:
    document: dict[str, object] = {
        "id": 123456,
        "tag_name": "v0.8.0",
        "html_url": "https://github.com/owner/local-gpu-imagegen/releases/tag/v0.8.0",
        "published_at": "2026-07-25T12:00:00Z",
        "draft": False,
    }
    document.update(overrides)
    return ApiResult(document, "2026-07-25T12:00:30Z", '"release-etag"')


def repository_result(count: int = 10) -> ApiResult:
    return ApiResult(
        {"full_name": "owner/local-gpu-imagegen", "stargazers_count": count},
        "2026-07-25T12:01:00Z",
        '"repository-etag"',
    )


def initialize(root: Path, api: FakeApi | None = None) -> tuple[Path, FakeApi]:
    fake = api or FakeApi(
        {RELEASE_URL: release_result(), REPOSITORY_URL: repository_result()}
    )
    report = initialize_campaign(
        root,
        "v0.8.0-release-123456",
        "owner/local-gpu-imagegen",
        "v0.8.0",
        api=fake,
        now=lambda: BASELINE_NOW,
    )
    if not report["ok"]:
        raise AssertionError(report)
    return root / "v0.8.0-release-123456", fake
```

Add these complete independent tests:

```python
def test_baseline_binds_published_release_and_appends_repository_count(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory, api = initialize(Path(temporary))
        campaign = json.loads((directory / "campaign.json").read_text(encoding="utf-8"))
        stored = (directory / "events.jsonl").read_text(encoding="ascii")
        lines = stored.splitlines()
        report = validate_campaign(directory)
    self.assertEqual(campaign["release"]["published_at"], "2026-07-25T12:00:00Z")
    self.assertEqual(campaign["goal"]["target"], 100)
    self.assertEqual(api.urls, [RELEASE_URL, REPOSITORY_URL])
    self.assertEqual(len(lines), 1)
    self.assertEqual(lines[0], canonical_json(json.loads(lines[0])).decode("ascii"))
    self.assertEqual(report["baseline_count"], 10)
    self.assertEqual(report["baseline_quality"], "on_time")
    for forbidden in ("stargazer_login", "account_id", "email", "token"):
        self.assertNotIn(forbidden, stored.casefold())

def test_baseline_rejects_draft_missing_publication_and_reuse(self) -> None:
    for result in (release_result(draft=True), release_result(published_at=None)):
        with self.subTest(result=result), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = FakeApi({RELEASE_URL: result})
            with self.assertRaises(ObservationError):
                initialize_campaign(
                    root, "v0.8.0-release-123456", "owner/local-gpu-imagegen",
                    "v0.8.0", api=api, now=lambda: BASELINE_NOW,
                )
            self.assertFalse((root / "v0.8.0-release-123456").exists())
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        directory, api = initialize(root)
        original = (directory / "campaign.json").read_bytes()
        with self.assertRaises(ObservationError) as caught:
            initialize_campaign(
                root, directory.name, "owner/local-gpu-imagegen", "v0.8.0",
                api=api, now=lambda: BASELINE_NOW,
            )
        self.assertEqual(caught.exception.kind, "campaign_exists")
        self.assertEqual((directory / "campaign.json").read_bytes(), original)

def test_repository_failure_after_campaign_creation_is_appended(self) -> None:
    failures = (
        ObservationError("http_error", "GitHub returned HTTP 503"),
        ObservationError("repository_mismatch", "Repository identity did not match"),
    )
    for failure in failures:
        with self.subTest(kind=failure.kind), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = FakeApi({RELEASE_URL: release_result(), REPOSITORY_URL: failure})
            report = initialize_campaign(
                root, "v0.8.0-release-123456", "owner/local-gpu-imagegen",
                "v0.8.0", api=api, now=lambda: BASELINE_NOW,
            )
            directory = root / "v0.8.0-release-123456"
            event = json.loads((directory / "events.jsonl").read_text(encoding="ascii"))
            self.assertTrue(report["ok"])
            self.assertEqual(report["outcome"], "measurement_incomplete")
            self.assertEqual(event["observation_status"], "observation_failed")
            self.assertEqual(event["failure"]["kind"], failure.kind)
            self.assertIsNone(event["repository_star_count"])

def test_observe_appends_t30_without_rewriting_prior_bytes(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory, _ = initialize(Path(temporary))
        campaign_before = (directory / "campaign.json").read_bytes()
        events_before = (directory / "events.jsonl").read_bytes()
        report = record_observation(
            directory, "t30", api=FakeApi({REPOSITORY_URL: repository_result(115)}),
            now=lambda: T30_NOW,
        )
        campaign_after = (directory / "campaign.json").read_bytes()
        events_after = (directory / "events.jsonl").read_bytes()
    self.assertEqual(campaign_after, campaign_before)
    self.assertTrue(events_after.startswith(events_before))
    self.assertEqual(len(events_after.splitlines()), 2)
    self.assertEqual(report["net_new_stars"], 105)
    self.assertEqual(report["outcome"], "goal_met")

def test_correction_appends_and_rejects_stale_target(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory, _ = initialize(Path(temporary))
        report = record_correction(
            directory,
            supersedes_sequence=1,
            observation_status="observed",
            repository_star_count=11,
            observed_at="2026-07-25T12:01:00Z",
            source_url=REPOSITORY_URL,
            failure_kind=None,
            failure_message=None,
            reason="Corrected a transcription error against the retained API response.",
            now=lambda: BASELINE_NOW,
        )
        self.assertEqual(report["effective_sequences"]["baseline"], 2)
        before = (directory / "events.jsonl").read_bytes()
        with self.assertRaises(ObservationError) as caught:
            record_correction(
                directory,
                supersedes_sequence=1,
                observation_status="observed",
                repository_star_count=12,
                observed_at="2026-07-25T12:01:00Z",
                source_url=REPOSITORY_URL,
                failure_kind=None,
                failure_message=None,
                reason="Stale target.",
                now=lambda: BASELINE_NOW,
            )
        self.assertEqual(caught.exception.kind, "invalid_correction_target")
        self.assertEqual((directory / "events.jsonl").read_bytes(), before)

def test_append_refuses_invalid_history_and_lock_contention(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory, _ = initialize(Path(temporary))
        events = directory / "events.jsonl"
        events.write_text(
            events.read_text(encoding="ascii").replace(
                '"repository_star_count":10', '"repository_star_count":11'
            ),
            encoding="ascii",
        )
        before = events.read_bytes()
        with self.assertRaises(ObservationError) as caught:
            record_observation(
                directory, "t30", api=FakeApi({REPOSITORY_URL: repository_result(115)}),
                now=lambda: T30_NOW,
            )
        self.assertEqual(caught.exception.kind, "invalid_history")
        self.assertEqual(events.read_bytes(), before)
    with tempfile.TemporaryDirectory() as temporary:
        directory, _ = initialize(Path(temporary))
        lock = directory / "events.jsonl.lock"
        lock.write_text("held", encoding="ascii")
        before = (directory / "events.jsonl").read_bytes()
        with self.assertRaises(ObservationError) as caught:
            record_observation(
                directory, "t30", api=FakeApi({REPOSITORY_URL: repository_result(115)}),
                now=lambda: T30_NOW,
            )
        self.assertEqual(caught.exception.kind, "lock_unavailable")
        self.assertEqual((directory / "events.jsonl").read_bytes(), before)
        self.assertEqual(lock.read_text(encoding="ascii"), "held")

def test_github_api_is_get_only_bounded_and_rejects_redirect_hosts(self) -> None:
    payload = json.dumps(
        {"full_name": "owner/local-gpu-imagegen", "stargazers_count": 10}
    ).encode()
    response = FakeResponse(
        payload,
        url=REPOSITORY_URL,
        headers={"Date": "Sat, 25 Jul 2026 12:01:00 GMT", "ETag": '"etag"'},
    )
    with mock.patch("urllib.request.urlopen", return_value=response) as opened:
        result = GitHubApi().get_json(REPOSITORY_URL)
    request = opened.call_args.args[0]
    self.assertEqual(request.get_method(), "GET")
    self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
    self.assertEqual(request.get_header("User-agent"), "local-gpu-imagegen-star-recorder/1.0")
    self.assertEqual(request.get_header("X-github-api-version"), "2022-11-28")
    self.assertEqual(result.document["stargazers_count"], 10)
    with mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(payload, url="https://example.com/repos/owner/repo"),
    ):
        with self.assertRaises(ObservationError) as caught:
            GitHubApi().get_json(REPOSITORY_URL)
        self.assertEqual(caught.exception.kind, "redirect_host_rejected")
    with mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(b"x" * 9, url=REPOSITORY_URL),
    ):
        with self.assertRaises(ObservationError) as caught:
            GitHubApi(max_response_bytes=8).get_json(REPOSITORY_URL)
        self.assertEqual(caught.exception.kind, "response_too_large")
    with mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(
            b"{}", url=REPOSITORY_URL, headers={"Content-Length": "9"}
        ),
    ):
        with self.assertRaises(ObservationError) as caught:
            GitHubApi(max_response_bytes=8).get_json(REPOSITORY_URL)
        self.assertEqual(caught.exception.kind, "response_too_large")
    for body, kind in ((b"{", "invalid_json"), (b"[]", "invalid_json_object")):
        with self.subTest(kind=kind), mock.patch(
            "urllib.request.urlopen",
            return_value=FakeResponse(body, url=REPOSITORY_URL),
        ):
            with self.assertRaises(ObservationError) as caught:
                GitHubApi().get_json(REPOSITORY_URL)
            self.assertEqual(caught.exception.kind, kind)

def test_environment_token_is_authorization_only_and_never_persisted_or_printed(self) -> None:
    token = "sentinel-secret-token"
    payload = json.dumps({"ok": True}).encode()
    with mock.patch.dict(os.environ, {"GITHUB_TOKEN": token}), mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(payload, url=REPOSITORY_URL),
    ) as opened:
        GitHubApi(token=token).get_json(REPOSITORY_URL)
        error = ObservationError("http_error", f"request failed with {token}")
    request = opened.call_args.args[0]
    self.assertEqual(request.get_header("Authorization"), f"Bearer {token}")
    self.assertNotIn(token, error.safe_message)
    self.assertNotIn(token, repr(error))

def test_cli_baseline_observe_and_correct_emit_json_without_committing(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fake = FakeApi({RELEASE_URL: release_result(), REPOSITORY_URL: repository_result()})
        with mock.patch("record_star_observation.GitHubApi", return_value=fake), mock.patch(
            "record_star_observation.utc_now", return_value=BASELINE_NOW
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            code = main([
                "baseline", "--adoption-root", str(root),
                "--campaign-id", "v0.8.0-release-123456",
                "--repository", "owner/local-gpu-imagegen",
                "--release-tag", "v0.8.0",
            ])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])
        directory = root / "v0.8.0-release-123456"
        with mock.patch(
            "record_star_observation.GitHubApi",
            return_value=FakeApi({REPOSITORY_URL: repository_result(115)}),
        ), mock.patch(
            "record_star_observation.utc_now", return_value=T30_NOW
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            code = main(["observe", "--campaign-dir", str(directory), "--phase", "t30"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["outcome"], "goal_met")
        with mock.patch(
            "record_star_observation.utc_now", return_value=BASELINE_NOW
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            code = main([
                "correct", "--campaign-dir", str(directory),
                "--supersedes-sequence", "1", "--status", "observed",
                "--observed-at", "2026-07-25T12:01:00Z",
                "--source-url", REPOSITORY_URL,
                "--reason", "Corrected transcription.",
                "--repository-star-count", "11",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["effective_sequences"]["baseline"], 3)
        self.assertEqual({path.name for path in root.iterdir()}, {directory.name})
        self.assertFalse(any(path.name == ".git" for path in root.rglob("*")))
```

Use `unittest.mock`, `io`, and temporary directories only; do not open the
network.

- [ ] **Step 2: Run recorder tests to verify red**

Run:

```powershell
python -m unittest tests.test_record_star_observation -v
```

Expected: `ERROR` importing `record_star_observation`.

- [ ] **Step 3: Implement the bounded GET-only API client**

Create `scripts/record_star_observation.py`. Import Task 1 helpers from
`validate_star_campaign`. Define:

```python
@dataclass(frozen=True)
class ApiResult:
    document: dict[str, object]
    response_date: str | None
    etag: str | None


class ObservationError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind[:100]
        self.safe_message = message.replace(os.environ.get("GITHUB_TOKEN", ""), "[redacted]")[:500] if os.environ.get("GITHUB_TOKEN") else message[:500]
        super().__init__(self.safe_message)
```

`GitHubApi.get_json` must:

1. Parse the requested URL and require scheme `https`, hostname
   `api.github.com`, no username/password, and a path beginning `/repos/`.
2. Build `urllib.request.Request` with method `GET`, fixed
   `User-Agent: local-gpu-imagegen-star-recorder/1.0`,
   `Accept: application/vnd.github+json`, and
   `X-GitHub-Api-Version: 2022-11-28`; add `Authorization: Bearer ...` only for
   a non-empty token.
3. Open with the configured timeout, reject a final redirected URL that fails
   the same host checks, reject declared content length above the limit, read
   at most `max_response_bytes + 1`, and reject overflow.
4. Decode strict UTF-8, parse JSON with duplicate-key rejection, require an
   object, normalize HTTP `Date` through `email.utils.parsedate_to_datetime`
   and `format_utc`, and bound `ETag` to 500 characters.
5. Convert HTTP, URL, timeout, size, encoding, and JSON failures into bounded
   `ObservationError` kinds without raw response bodies or credentials.

- [ ] **Step 4: Implement immutable campaign initialization**

Use URL-quoted repository/tag components. `initialize_campaign` fetches:

```text
https://api.github.com/repos/<owner>/<repo>/releases/tags/<tag>
https://api.github.com/repos/<owner>/<repo>
```

Validate release `id` as positive int (not bool), exact `tag_name`, canonical
GitHub release `html_url`, non-null UTC `published_at`, and `draft is False`.
Validate repository `full_name` case-insensitively against the requested name
and `stargazers_count` as a non-negative int (not bool).

After validating the Release anchor, exclusively create the campaign directory
with `mkdir(parents=True, exist_ok=False)`. Convert a collision to
`ObservationError("campaign_exists", ...)`. Write `campaign.json` through an
exclusive temporary file plus `os.replace`, create empty ASCII `events.jsonl`
exclusively, flush both, and clean up only files/directories created by this
attempt if initialization fails before both files form a valid empty campaign.
If repository collection fails after that valid campaign exists, call
`append_event` with `observation_failed` and return its validator report. Do
not remove that evidence.

On success, append the baseline observed event using `now()` immediately after
the parsed repository response. `source.api_url` is the repository endpoint,
and response metadata comes from `ApiResult`.

- [ ] **Step 5: Implement lock-protected observations and corrections**

`append_event` performs this exact order:

```text
exclusive create events.jsonl.lock
  -> validate current campaign
  -> reject if current report is not ok
  -> read last canonical event, derive next sequence/hash
  -> call make_event with caller values plus derived chain values
  -> append one ASCII canonical line, flush, os.fsync
  -> validate complete campaign again
  -> raise post_append_validation_failed if invalid
finally remove only the lock created by this process
```

The caller cannot supply `sequence`, `previous_event_sha256`, or
`event_sha256`; reject those keys. The lock contains no token and is never
committed.

`record_observation` reads campaign identity, accepts only `baseline` or
`t30`, queries only the bound repository endpoint, and appends observed or
failed history. It does not reject an early/late phase; timing remains visible
and the validator decides usability.

`record_correction` loads the superseded event, copies its phase and exact
campaign-derived schedule, validates bounded reason/source/failure arguments,
uses the caller-supplied original `observed_at`, and appends a correction. It
must reject a target that is not the validator's current effective sequence.

- [ ] **Step 6: Implement exact CLI arguments and structured output**

Use `argparse` subparsers with these commands:

```text
baseline --adoption-root docs/evidence/adoption --campaign-id ID --repository OWNER/REPO --release-tag TAG
observe --campaign-dir PATH --phase {baseline,t30}
correct --campaign-dir PATH --supersedes-sequence N --status {observed,observation_failed} --observed-at UTC --source-url URL --reason TEXT [--repository-star-count N] [--failure-kind TEXT] [--failure-message TEXT]
```

`baseline` defaults `--adoption-root` relative to repository root. The other
paths are explicit. Define `main(argv: Sequence[str] | None = None) -> int`,
construct `GitHubApi(token=os.environ.get("GITHUB_TOKEN"))` inside it, use a
UTC `now`, print only the final validation report as
sorted/indented JSON, and send errors as:

```json
{"ok": false, "error": {"kind": "bounded_kind", "message": "bounded safe message"}}
```

to stderr with exit `1`. Do not invoke Git. Do not add packaging metadata.

- [ ] **Step 7: Run focused integration tests and the scope trigger**

Run:

```powershell
python -m unittest tests.test_validate_star_campaign tests.test_record_star_observation -v
$validator=(Get-Content scripts\validate_star_campaign.py).Count
$recorder=(Get-Content scripts\record_star_observation.py).Count
"validator=$validator recorder=$recorder total=$($validator+$recorder)"
python -m compileall -q scripts\validate_star_campaign.py scripts\record_star_observation.py tests\test_validate_star_campaign.py tests\test_record_star_observation.py
git diff --check
```

Expected: all focused tests pass and compilation/diff checks exit `0`. If the
two scripts materially exceed approximately 500 lines, stop before commit,
identify which approved integrity/failure requirements account for the excess,
and obtain design confirmation. Do not solve line pressure by adding a third
module or weakening validation.

- [ ] **Step 8: Commit the recorder**

```powershell
git add -- scripts/record_star_observation.py tests/test_record_star_observation.py
git diff --cached --check
git commit -m "feat: record append-only star observations"
```

Expected: one commit containing only the two Task 2 files.

---

### Task 3: Migrate Active Policy And Mark Historical Gates Superseded

**Files:**
- Modify: `tests/test_public_docs.py`
- Modify: `docs/evidence/README.md`
- Modify: `docs/release-checklist.md`
- Modify: `docs/github-listing.md`
- Modify: `docs/superpowers/specs/2026-07-24-github-conversion-release-gate-design.md`
- Modify: `docs/superpowers/plans/2026-07-24-github-conversion-release-gate.md`

**Interfaces:**
- Consumes: the exact recorder commands and outcomes from Tasks 1-2.
- Produces: active release copy where 100 net-new Stars is post-release only.
- Produces: historical documents whose original text remains intact after a
  leading Superseded notice.
- Preserves: every technical/evidence/authority release gate and all existing
  no-guarantee language.

- [ ] **Step 1: Add failing public-policy regression tests**

Add these constants near the existing public-document constants:

```python
RELEASE_CHECKLIST = ROOT / "docs" / "release-checklist.md"
GITHUB_LISTING = ROOT / "docs" / "github-listing.md"
EVIDENCE_README = ROOT / "docs" / "evidence" / "README.md"
HISTORICAL_STAR_GATE_DOCS = (
    ROOT / "docs" / "superpowers" / "specs" / "2026-07-24-github-conversion-release-gate-design.md",
    ROOT / "docs" / "superpowers" / "plans" / "2026-07-24-github-conversion-release-gate.md",
)
```

Add these complete tests to `PublicDocumentationTests`:

```python
def test_star_goal_is_post_release_measurement_not_publication_gate(self) -> None:
    checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")
    listing = GITHUB_LISTING.read_text(encoding="utf-8")
    evidence = EVIDENCE_README.read_text(encoding="utf-8")
    self.assertNotIn("forecast is at least `100 GitHub Stars`", checklist)
    self.assertNotIn("Publication remains blocked", listing)
    self.assertIn("Post-release adoption measurement", checklist)
    self.assertIn("100 net-new GitHub Stars", checklist)
    self.assertIn("formal GitHub Release publication time", checklist)
    self.assertIn("does not retract the Release", checklist)
    self.assertIn("post-release 30-day net-new Star goal", listing)
    self.assertIn("not a publication blocker", listing)
    for required in (
        "docs/evidence/adoption/<campaign_id>/campaign.json",
        "docs/evidence/adoption/<campaign_id>/events.jsonl",
        "record_star_observation.py",
        "validate_star_campaign.py",
        "repository-level Star totals only",
        "goal_met",
        "goal_missed",
        "measurement_incomplete",
    ):
        with self.subTest(required=required):
            self.assertIn(required, evidence)

def test_historical_star_gate_documents_have_superseded_notice(self) -> None:
    for path in HISTORICAL_STAR_GATE_DOCS:
        with self.subTest(path=path):
            prefix = path.read_text(encoding="utf-8")[:1200]
            self.assertIn("**Status:** Superseded", prefix)
            self.assertIn("2026-07-25-post-release-star-measurement-design.md", prefix)
            self.assertIn("historical", prefix.lower())
            self.assertIn("not a pre-release publication gate", prefix)
```

- [ ] **Step 2: Run the public-document tests to verify red**

Run:

```powershell
python -m unittest tests.test_public_docs.PublicDocumentationTests.test_star_goal_is_post_release_measurement_not_publication_gate tests.test_public_docs.PublicDocumentationTests.test_historical_star_gate_documents_have_superseded_notice -v
```

Expected: two failures because the active blocker wording and notices have not
yet changed.

- [ ] **Step 3: Migrate active release and evidence documents**

In `docs/release-checklist.md`, delete the forecast checkbox from
`Publication gate`. Keep every other publication item. Add this section after
`Publication gate` and before `Still pending after preview`:

```markdown
## Post-release adoption measurement

- [ ] At formal GitHub Release publication time, initialize the append-only campaign baseline under `docs/evidence/adoption/<campaign_id>/` within five minutes when possible.
- [ ] During the inclusive 24-hour T+30 collection window, append the repository-level Star total and validate the complete hash chain.
- [ ] Measure the goal as T+30 total Stars minus baseline total Stars, targeting `100 net-new GitHub Stars` without interpolation or stargazer identities.
- [ ] Record `goal_met`, `goal_missed`, or `measurement_incomplete`; a missed or incomplete adoption goal triggers review and iteration but does not retract the Release.
```

In `docs/github-listing.md`, preserve the factual technical blockers but
replace the sentence beginning `Publication remains blocked` with:

```markdown
Publication still requires a retained Claude Code generation session, four green public CI jobs at the exact release commit, the exact PyPI artifact, the MCP Registry record, reviewed social-preview metadata, synchronized release copy, and later explicit authority for every remote-publication action. The post-release 30-day net-new Star goal begins at formal GitHub Release publication and is not a publication blocker. Publication-dependent URLs remain pending.
```

Append an `Adoption evidence` section to `docs/evidence/README.md` containing:

````markdown
## Adoption evidence

Each formal Release campaign owns `docs/evidence/adoption/<campaign_id>/campaign.json` and `docs/evidence/adoption/<campaign_id>/events.jsonl`. The first file fixes the repository, Release ID/tag/publication time, target, and timing policy. The second is canonical append-only JSONL linked by SHA-256.

Collect and validate with the repository-maintenance scripts:

```powershell
python .\scripts\record_star_observation.py baseline --campaign-id <campaign_id> --repository <owner/repository> --release-tag <tag>
python .\scripts\record_star_observation.py observe --campaign-dir docs\evidence\adoption\<campaign_id> --phase t30
python .\scripts\validate_star_campaign.py docs\evidence\adoption\<campaign_id>
```

The record stores repository-level Star totals only: no stargazer identities, interpolation, traffic attribution, credentials, or raw API bodies. Corrections append a superseding event instead of rewriting history. Validation reports `goal_met`, `goal_missed`, or `measurement_incomplete`. Missing the 100 net-new goal triggers review and iteration; it does not retract the Release.
````

Ensure the nested PowerShell fence is correctly closed in the actual Markdown.

- [ ] **Step 4: Add Superseded notices without rewriting historical decisions**

In each historical design/plan file, leave the title and all existing body text
unchanged. Insert this block immediately after the H1 and before the old status
or plan header:

```markdown
> **Status:** Superseded on 2026-07-25 by
> [`2026-07-25-post-release-star-measurement-design.md`](../specs/2026-07-25-post-release-star-measurement-design.md).
> The 100-Star objective is now a post-release 30-day net-new goal, not a
> pre-release publication gate. The text below is retained as historical
> planning context and must not be applied as current release policy.
```

For the spec file itself, correct the relative link to the same directory:
`[...](2026-07-25-post-release-star-measurement-design.md)`. For the plan file,
use `../specs/...` as shown. Do not edit old forecast calculations, tasks,
resolved decisions, or their original status text.

- [ ] **Step 5: Run focused green tests and scan all active Star language**

Run:

```powershell
python -m unittest tests.test_validate_star_campaign tests.test_record_star_observation tests.test_public_docs -v
Get-ChildItem README.md,CHANGELOG.md,docs -Recurse -File | Select-String -Pattern '100.?Star','forecast.*block','Publication remains blocked' -CaseSensitive:$false
```

Expected: focused tests pass. Search hits in the two historical files are
allowed only beneath their Superseded notices; active files must describe the
target as post-release and non-blocking. Other historical strategy statements
that never imposed a release gate remain unchanged.

- [ ] **Step 6: Run the complete model-free verification gate**

Run exactly:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
python -c "import json, pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('docs/evidence/schemas').glob('*.json')]"
git diff --check
git diff --cached --check
git diff --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git status --short
```

Expected: all tests pass with only the repository's documented Windows
permission/link skips, compilation and JSON parsing exit `0`, both diff checks
exit `0`, both frozen workflow checks produce no output, and status contains
only the six Task 3 files before staging.

- [ ] **Step 7: Commit active-document migration and historical notices**

Because `docs/superpowers/` is ignored, force-add only the two already tracked
historical files by their exact paths after staging the normal files:

```powershell
git add -- tests/test_public_docs.py docs/evidence/README.md docs/release-checklist.md docs/github-listing.md
git add -f -- docs/superpowers/specs/2026-07-24-github-conversion-release-gate-design.md docs/superpowers/plans/2026-07-24-github-conversion-release-gate.md
git diff --cached --check
git diff --cached --name-only
git commit -m "docs: move star goal after release"
```

Expected: exactly the six listed Task 3 files in the commit.

- [ ] **Step 8: Verify the final branch and stop before real collection**

Run:

```powershell
git log --oneline --decorate -5
git status --short --branch
git diff main...HEAD --stat
git diff main...HEAD --check
git diff --exit-code -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
```

Expected: the branch contains the prior design commit plus exactly three
implementation commits, the worktree is clean, frozen workflow diff is zero,
and no real `docs/evidence/adoption/<campaign_id>/` exists. Report test counts,
script line counts, commit IDs, and limitations. Stop and request review; do
not push, publish a Release, or collect a real baseline.

## Spec Coverage Review

| Approved requirement | Plan coverage |
|---|---|
| 100 Stars is post-release, not a publication blocker | Task 3 active-document migration |
| Formal GitHub Release publication is the campaign anchor | Tasks 1-2 campaign validation/initialization |
| Metric is T+30 total minus baseline total | Task 1 derived outcome tests and implementation |
| Five-minute baseline quality boundary | Task 1 on-time/degraded semantics; Task 2 timestamp capture |
| Inclusive 24-hour T+30 collection window | Task 1 early/within/late tests |
| Append-only observations and retained failures | Task 2 lock-protected append and failure tests |
| Corrections append superseding events | Tasks 1-2 linear correction validation/recording |
| Counts need not be monotonic | Task 1 negative-delta goal-missed test |
| No stargazer identities or interpolation | Schemas, validator identity scan, recorder endpoint, docs |
| Hash fields `sequence`, `previous_event_sha256`, `event_sha256` | Task 1 canonical chain |
| Outcomes `goal_met`, `goal_missed`, `measurement_incomplete` | Task 1 report contract |
| Standard-library recorder and validator only | Tasks 1-2; no dependency/package/runtime change |
| No MCP tool, Action, automatic push, or remote mutation | Global constraints and Task 2 CLI boundary |
| Historical plans retained with Superseded notices | Task 3 |
| Regional/two-stage work remains frozen | Global constraints and every final diff gate |

## Self-Review

- **Spec coverage:** Every approved design section maps to a task in the table
  above. Real Release creation and real observation are intentionally outside
  implementation authority and are an explicit final stop.
- **Placeholder scan:** The plan contains no `TBD`, `TODO`, `implement later`,
  comment-only test body, or unnamed error-handling step. Test code names the
  exact setup, behavior, and assertions required during implementation.
- **Type consistency:** Task 2 imports the exact Task 1 function names and
  report keys. `scheduled_at_value` is the `make_event` keyword while stored
  JSON uses `scheduled_at`, avoiding collision with the helper function.
  Campaign/event enum values and outcome strings match the design and schemas.
- **Commit boundaries:** Task 1 commits four schema/validator files; Task 2
  commits two recorder files; Task 3 commits six policy/document files. No
  task stages another task's files.

## Implementation Hand-Off

After this written plan is explicitly approved, execute it sequentially with
the `executing-plans` skill. Use `high` reasoning for the frozen implementation
and tests; return to `xhigh` only if a new architecture conflict, integrity gap,
or scope-trigger review appears. Do not begin Task 1 merely because the plan
file exists.
