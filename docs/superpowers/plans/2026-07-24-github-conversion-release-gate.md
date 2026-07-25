# GitHub Conversion Release-Gate Implementation Plan

> **Status:** Superseded on 2026-07-25 by
> [`2026-07-25-post-release-star-measurement-design.md`](../specs/2026-07-25-post-release-star-measurement-design.md).
> The 100-Star objective is now a post-release 30-day net-new goal, not a pre-release publication gate. The text below is retained as historical
> planning context and must not be applied as current release policy.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the exact Local GPU Imagegen `0.7.0` candidate into an evidence-first, five-minute GitHub onboarding surface, while preserving byte-bound evidence gates and blocking publication unless the pessimistic first-30-day forecast reaches at least 100 Stars.

**Architecture:** Keep the fifteen-tool MCP core unchanged. First repair the stale `1280x720` public-demo assumption so the exporter validates the finalized run's actual dimensions end to end, then consume finalization and public-export authority as separate ordered runtime gates. Build the conversion layer from the validated public evidence only: deterministic documentation tests, a concise Quickstart, an evidence-first README, a genuine-image-derived social preview, and a private three-scenario demand forecast.

**Tech Stack:** Python 3.11/3.12 standard library, `unittest`, JSON Schema, Markdown, HTML/CSS, browser screenshot tooling used only to render the repository asset, PowerShell verification, Git.

## Global Constraints

- Work only in `.worktrees/v061-launch-readiness` on `feature/v061-launch-readiness`; do not modify `main`.
- Keep the public MCP surface at exactly fifteen tools and make no MCP, backend, route, generation-plan, trust, run-store, or model-selection change.
- Add no package or runtime dependency. The social-preview source may be rendered with the existing browser tooling, but browser tooling must not enter `pyproject.toml` or the wheel.
- Do not download a model, switch models, restart ComfyUI, generate another round, upscale, or use regional/two-stage routing under this plan.
- The retained run is `20260724T083007Z-187ad21f4678`, round `1`, original size `1024x1024`, image SHA-256 `36b5de509a2da8c75571aac436d45d8a31a7a8efc77439abee9e0918191572f4`.
- The user's approval of dynamic dimensions authorizes Task 1 only. It does not authorize finalization, evidence export, remote metadata, push, tag, release, publication, or directory submission.
- Finalization requires a later user message containing exactly `finalize:20260724T083007Z-187ad21f4678:1:36b5de509a2da8c75571aac436d45d8a31a7a8efc77439abee9e0918191572f4`.
- Public export requires a later, separately displayed authorization after finalization. Never infer it from finalization.
- The README must retain pending-evidence copy until `docs/demo/real/` validates. A reviewed-only, private, transformed, rejected, or unvalidated image must never appear as public proof.
- The five-minute claim applies only to a user who already has a supported backend and model running; it excludes backend installation, model download, generation time, and unusually slow hardware.
- Bilibili, Douyin, and other unproven creator traffic contribute zero to the pessimistic forecast.
- No formal release request is allowed unless the documented pessimistic first-30-day estimate is at least `100 GitHub Stars`; never present any Star estimate as a guarantee.
- Never place credentials, endpoint details, private route tokens, model paths, account data, private prompts, hidden reasoning, or personal absolute paths in tracked files.
- Run `python -m unittest discover -s tests -v` after relevant changes and the complete release gate before claiming readiness.

---

### Task 1: Bind Public Evidence To The Finalized Run Dimensions

**Files:**
- Modify: `scripts/export_real_demo.py:133-164, 405-465, 590-615`
- Modify: `scripts/validate_real_demo.py:280-307, 390-420, 630-666`
- Modify: `docs/evidence/schemas/real-demo.schema.json:60-105`
- Modify: `tests/real_demo_helpers.py:15-19, 179-187`
- Modify: `tests/test_export_real_demo.py`
- Modify: `tests/test_validate_real_demo.py`

**Interfaces:**
- Consumes: the finalized manifest's route, selected backend result, selected image metadata, and final image metadata.
- Produces: `_valid_dimension(value: object) -> bool` in `validate_real_demo.py`; public evidence whose generation and final dimensions may vary but must be integers from 256 through 1536, divisible by 8, and identical across route, generation, final metadata, PNG IHDR, and exported manifest.
- Preserves: byte-for-byte `final.png`, exact SHA-256 binding, ordinary `sdxl-txt2img` route, and all existing path/symlink/private-data defenses.

- [ ] **Step 1: Change the synthetic ordinary-route fixture to the approved square dimensions**

In `tests/real_demo_helpers.py`, replace the stale observatory fixture constants and dimension observations with:

```python
WIDTH = 1024
HEIGHT = 1024
TIMESTAMP = "2026-07-24T10:00:00Z"
POSITIVE_PROMPT = (
    "A solitary white lighthouse on a black basalt sea stack at blue hour, "
    "complete structure visible, no people or lettering."
)
NEGATIVE_PROMPT = "people, text, watermark, cropped lighthouse, duplicate tower"
```

```python
"width": {
    "status": "pass",
    "observation": "The retained image is 1024 pixels wide.",
},
"height": {
    "status": "pass",
    "observation": "The retained image is 1024 pixels high.",
},
```

This makes every existing exporter/validator success test exercise `1024x1024` rather than preserving the stale `1280x720` assumption.

- [ ] **Step 2: Add explicit cross-layer dimension failure tests**

Add focused tests that mutate one layer at a time while retaining a valid `1024x1024` PNG:

```python
def test_export_rejects_final_dimension_metadata_drift(self) -> None:
    from export_real_demo import export_real_demo

    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        run_root, client, mcp_result, authority, output = write_source_fixture(base)
        manifest = read_json(run_root / "manifest.json")
        manifest["final"]["image"]["width"] = 1280
        write_json(run_root / "manifest.json", manifest)

        with self.assertRaisesRegex(ValueError, "invalid_finalization"):
            export_real_demo(
                run_root,
                output,
                client,
                mcp_result,
                authority_path=authority,
            )
```

```python
def test_validator_rejects_generation_dimension_drift(self) -> None:
    from validate_real_demo import validate_real_demo

    with tempfile.TemporaryDirectory() as directory:
        root = self._export(Path(directory))
        manifest_path = root / "showcase-manifest.json"
        manifest = read_json(manifest_path)
        manifest["generation"]["width"] = 1280
        write_json(manifest_path, manifest)

        self.assertIn("invalid_generation", validate_real_demo(root))
```

Use the test classes' existing setup helpers and field names; do not introduce another fixture builder.

- [ ] **Step 3: Run the focused tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_export_real_demo tests.test_validate_real_demo -v
```

Expected: the existing success cases fail because the implementation still demands `1280x720`; the new drift cases must also fail for the named contract reason after implementation. Do not commit the red state.

- [ ] **Step 4: Validate dimensions once and reuse the validated pair in the exporter**

Add this private helper near `_safe_artifact` in `scripts/export_real_demo.py`:

```python
def _validated_dimensions(width: object, height: object) -> tuple[int, int]:
    values = (width, height)
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 256 <= value <= 1536
        or value % 8 != 0
        for value in values
    ):
        raise ValueError("invalid_finalization")
    return width, height
```

In `_finalized_root`, derive the dimensions from `final_image`, require them to match `selected_image`, then pass them into `_safe_artifact`:

```python
width, height = _validated_dimensions(
    final_image.get("width"),
    final_image.get("height"),
)
if (
    selected_image.get("width") != width
    or selected_image.get("height") != height
):
    raise ValueError("invalid_finalization")
image_path = _safe_artifact(
    run_root,
    final_image,
    mime_type="image/png",
    expected_width=width,
    expected_height=height,
)
```

Populate the public final summary with the validated integers, not unchecked metadata:

```python
"width": width,
"height": height,
```

After `_public_route` and `_generation_provenance` return, reject any mismatch before creating the destination:

```python
if (
    generation.get("width") != final["width"]
    or generation.get("height") != final["height"]
):
    raise ValueError("invalid_generation_provenance")
```

`_generation_provenance` already requires backend dimensions to equal the frozen source route dimensions, so this comparison completes the route -> backend -> public generation -> final image chain without adding dimensions to the sanitized public route identity object.

Replace the staging check with:

```python
validate_png(staging / "final.png", final["width"], final["height"])
```

- [ ] **Step 5: Generalize semantic validation without weakening equality checks**

Add in `scripts/validate_real_demo.py`:

```python
def _valid_dimension(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 256 <= value <= 1536
        and value % 8 == 0
    )
```

In `_valid_generation`, replace the two constants with:

```python
and _valid_dimension(value.get("width"))
and _valid_dimension(value.get("height"))
```

Pass the already parsed public `final` object into `_validate_artifacts`, and validate `final.png` using its dimensions:

```python
if not isinstance(final, dict):
    findings.add("invalid_final")
else:
    try:
        validated = validate_png(path, final["width"], final["height"])
    except (ArtifactError, KeyError, OSError, ValueError):
        findings.add("invalid_final_png")
```

Replace the final `1280`/`720` constants with `_valid_dimension`, while retaining the existing check that `final.width/height == generation.width/height`.

- [ ] **Step 6: Generalize only the JSON Schema dimension values**

Add a reusable dimension definition under `$defs`:

```json
"dimension": {
  "maximum": 1536,
  "minimum": 256,
  "multipleOf": 8,
  "type": "integer"
}
```

Replace all four `const` dimension schemas in `final` and `generation` with:

```json
"height": {"$ref": "#/$defs/dimension"},
"width": {"$ref": "#/$defs/dimension"}
```

Do not relax exact model, workflow, route, rights, finalization, artifact, or client-session constants.

- [ ] **Step 7: Run the complete evidence contract gate**

Run:

```powershell
python -m unittest tests.test_export_real_demo tests.test_validate_real_demo tests.test_validate_client_sessions tests.test_packaging -v
python -m compileall -q scripts/export_real_demo.py scripts/validate_real_demo.py tests/real_demo_helpers.py tests/test_export_real_demo.py tests/test_validate_real_demo.py
git diff --check
```

Expected: all tests pass with `1024x1024` synthetic evidence, all drift mutations are rejected, compilation is silent, and `git diff --check` reports nothing.

- [ ] **Step 8: Commit the approved evidence-contract correction**

```powershell
git add scripts/export_real_demo.py scripts/validate_real_demo.py docs/evidence/schemas/real-demo.schema.json tests/real_demo_helpers.py tests/test_export_real_demo.py tests/test_validate_real_demo.py
git commit -m "fix(evidence): bind demo dimensions to finalized run"
```

---

### Task 2: Consume The Existing Candidate Finalization Gate Exactly Once

**Files:**
- Modify privately through MCP only: retained run manifest under the ignored run root.
- Create privately/ignored: exact `local_gpu_finalize_run` result JSON under `outputs/v070-golden-private/`.
- Modify after verification: `PROJECT_NODES.md` and `NEXT_SESSION.md` in the project root.
- Do not modify tracked public evidence files.

**Interfaces:**
- Consumes only the later exact finalization token stated in Global Constraints.
- Produces one finalized byte-identical `final.png` and a retained raw MCP result for Task 3.

- [ ] **Step 1: Stop unless the exact token arrives in a later user message**

Design approval, Task 1 approval, previous review authority, or a paraphrase is insufficient. Display the retained original, four recorded limitations, SHA-256, and exact token; wait if the user's message is not byte-for-byte identical.

- [ ] **Step 2: Revalidate the candidate before mutation**

Read the run through `local_gpu_get_run` and independently inspect `manifest.json`. Require:

```text
state = reviewed
revision = 6
reviews = exactly 1
hard failures = 0
final = absent
candidate round = 1
candidate SHA-256 = 36b5de509a2da8c75571aac436d45d8a31a7a8efc77439abee9e0918191572f4
```

Run `Get-FileHash -Algorithm SHA256` on the original `round-01.png`. Stop on any mismatch; do not repair or regenerate.

- [ ] **Step 3: Finalize exactly once**

Call `local_gpu_finalize_run` with run ID, round 1, the exact confirmation, and a truthful summary that accepts the image while retaining these limitations:

```text
red-purple moonlit palette rather than clear blue hour
no distinct directional beacon beam
one small extra navigation beacon
minor railing/cliff-ladder artifacts
```

Do not start ComfyUI; finalization is byte-preserving and backend-free.

- [ ] **Step 4: Verify and stop**

Require the returned state to be `finalized`, the final round to be `1`, and `final.png` to hash to the exact candidate SHA-256. Save the complete raw tool result privately. Stop and request separate export authority; do not run the exporter.

---

### Task 3: Export And Commit The Validated Public Evidence

**Files:**
- Create through `scripts/export_real_demo.py`: `docs/demo/real/final.png`
- Create through exporter: `docs/demo/real/preview.jpg`
- Create through exporter: `docs/demo/real/run-manifest.json`
- Create through exporter: `docs/demo/real/mcp-result.json`
- Create through exporter: `docs/demo/real/transcript.md`
- Create through exporter: `docs/demo/real/showcase-manifest.json`
- Create through exporter: `docs/demo/real/README.md`
- Create after validation: `docs/evidence/client-sessions/codex-v070.json`

**Interfaces:**
- Consumes: separately authorized finalized source run, approved public-rights file, sanitized Codex golden-generation record, and raw final MCP result.
- Produces: exactly seven files under `docs/demo/real/`, one validated Codex record, and no private path or endpoint disclosure.

- [ ] **Step 1: Display the export disclosure and request new authority**

Display the public rights, exact final SHA-256, destination `docs/demo/real`, seven-file allowlist, retained public fields, omitted private fields, known limitations, and the fact that `final.png` remains `1024x1024` and byte-identical. Wait for a new user authorization that explicitly names public export.

- [ ] **Step 2: Build and validate the closed public Codex session record**

The existing `task9-registered-appserver-draft-public-session.json` is a private generation summary, not a valid public client-session document. Recheck its client version, wheel digest, raw session digest, exact generated result, start/end timestamps, and run/round/image identifiers against the retained raw files. Then use `apply_patch` to create `docs/evidence/client-sessions/codex-v070.json` with this closed document; the three `result_sha256` values are SHA-256 over canonical ASCII JSON with sorted keys and separators `(',', ':')`:

```json
{
  "schema_version": "1.0",
  "evidence_class": "named_client_session",
  "session_purpose": "golden_generation",
  "client": {
    "name": "codex",
    "version": "0.146.0-alpha.3.1",
    "session_mode": "ephemeral"
  },
  "installed_wheel": true,
  "hosted_client_session": true,
  "server": {
    "name": "local-gpu-imagegen",
    "version": "0.7.0",
    "protocol_version": "2024-11-05",
    "wheel_sha256": "83ba9a8bc078f488d69b006e73f5dd2c89e7fe6e78b3302961d750beb5acc1a8"
  },
  "started_at": "2026-07-24T08:28:50.289Z",
  "completed_at": "2026-07-24T08:31:11.768Z",
  "tool_calls": [
    {
      "sequence": 1,
      "name": "local_gpu_start_run",
      "result": {
        "run_id": "20260724T083007Z-187ad21f4678",
        "state": "confirmed"
      },
      "result_sha256": "94c2a42b079c560e05a1ec44f7b42201bfbc8baa947422c15d119ea531dd276e"
    },
    {
      "sequence": 2,
      "name": "local_gpu_generate_round",
      "result": {
        "run_id": "20260724T083007Z-187ad21f4678",
        "state": "generated",
        "round_number": 1,
        "image_sha256": "36b5de509a2da8c75571aac436d45d8a31a7a8efc77439abee9e0918191572f4"
      },
      "result_sha256": "001ff0e0d377ed0bde270cfc73c10e454c771f2bbc671c7de30a0130ab5d7520"
    },
    {
      "sequence": 3,
      "name": "local_gpu_get_run",
      "result": {
        "run_id": "20260724T083007Z-187ad21f4678",
        "state": "generated"
      },
      "result_sha256": "be8c10a4c8bbe10e84e9acd4230ce9aead1050e733f3817bde09321125c74c36"
    }
  ],
  "sanitization": {
    "prompts_omitted": true,
    "account_identifiers_omitted": true,
    "credentials_omitted": true,
    "machine_paths_omitted": true,
    "raw_transcript_retained": false
  }
}
```

The three calls are a sanitized observable subset of the retained 11-call hosted session, not a claim that the session contained only three calls. Do not include discovery results because their endpoint, filesystem identity, and route fields are intentionally private.

Run:

```powershell
python scripts/validate_client_sessions.py docs/evidence/client-sessions/codex-v070.json
```

Expected: no findings, version `0.7.0`, `session_purpose` equal to `golden_generation`, and a retained `local_gpu_generate_round` result bound to the exact run/round/hash. Scan the finished record for personal paths, endpoint values, route tokens, account data, credentials, hidden reasoning, and oversized payloads.

- [ ] **Step 3: Run the exporter once into an absent destination**

Resolve the private source paths only in the current shell and run:

```powershell
python scripts/export_real_demo.py $privateRunRoot docs/demo/real docs/evidence/client-sessions/codex-v070.json $privateMcpResult --authority docs/evidence/acceptance-authority.json
```

Expected: exactly seven files, schema `2.0`, dimensions `1024x1024`, no findings. If the destination exists or validation fails, preserve the source, remove only a newly created incomplete destination after verifying its absolute path is inside this worktree, and diagnose before retrying.

- [ ] **Step 4: Prove byte identity and public cleanliness**

Run:

```powershell
python scripts/validate_real_demo.py docs/demo/real
Get-FileHash -Algorithm SHA256 docs/demo/real/final.png
python -m unittest tests.test_export_real_demo tests.test_validate_real_demo tests.test_validate_client_sessions tests.test_repository_hygiene -v
git diff --check
```

Expected: no validator findings; exported SHA-256 equals `36b5de509a2da8c75571aac436d45d8a31a7a8efc77439abee9e0918191572f4`; all tests pass; no private root is tracked.

- [ ] **Step 5: Inspect the exported image at original resolution**

Open `docs/demo/real/final.png` at full `1024x1024`, verify it is the reviewed lighthouse and has not been transformed, and confirm the four limitations remain truthfully recorded. This inspection does not authorize image editing.

- [ ] **Step 6: Commit only validated public evidence**

```powershell
git add docs/demo/real docs/evidence/client-sessions/codex-v070.json
git commit -m "docs(evidence): publish validated ordinary-route demo"
```

---

### Task 4: Make The Repository's First Viewport Convert From Genuine Evidence

**Files:**
- Create: `docs/quickstart.md`
- Modify: `README.md:1-55`
- Modify: `docs/github-listing.md`
- Modify: `docs/release-checklist.md`
- Modify: `docs/demo/README.md`
- Modify: `tests/test_public_docs.py`

**Interfaces:**
- Consumes: validated `docs/demo/real/showcase-manifest.json` and `final.png` from Task 3.
- Produces: an evidence-first first viewport, a bounded five-minute installed-user path, truthful GitHub listing copy, and deterministic checks that derive hashes and route identity from the manifest rather than duplicating mutable constants.

- [ ] **Step 1: Add failing conversion-contract tests**

Add helpers and tests to `tests/test_public_docs.py`:

```python
REAL_DEMO = ROOT / "docs" / "demo" / "real"
QUICKSTART = ROOT / "docs" / "quickstart.md"


def real_showcase() -> dict[str, object]:
    return json.loads(
        (REAL_DEMO / "showcase-manifest.json").read_text(encoding="utf-8")
    )
```

```python
def test_readme_first_viewport_uses_validated_evidence(self) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first_viewport = "\n".join(readme.splitlines()[:55])
    showcase = real_showcase()
    image_sha256 = showcase["final"]["image_sha256"]

    required = (
        "docs/demo/real/final.png",
        image_sha256,
        "`sdxl-txt2img`",
        "uvx local-gpu-imagegen verify",
        "uvx local-gpu-imagegen setup codex --apply",
        "docs/quickstart.md",
        "existing local image backend",
        "no silent model downloads or switches",
    )
    for value in required:
        with self.subTest(value=value):
            self.assertIn(value, first_viewport)
    self.assertLess(
        readme.index("docs/demo/real/final.png"),
        readme.index("docs/demo/preview-loop.gif"),
    )
```

```python
def test_quickstart_is_bounded_reversible_and_private_value_free(self) -> None:
    quickstart = QUICKSTART.read_text(encoding="utf-8")
    required = (
        "Python 3.11 or 3.12",
        "backend and model are already running",
        "uvx local-gpu-imagegen verify",
        "uvx local-gpu-imagegen setup codex --apply",
        "uvx local-gpu-imagegen setup claude-code --apply",
        "uvx local-gpu-imagegen doctor",
        "Restart or reload",
        "codex mcp remove local-gpu-imagegen",
        "claude mcp remove --scope user local-gpu-imagegen",
        "local_gpu_discover_models",
        "local_gpu_set_model_trust",
        "local_gpu_recommend_models",
        "local_gpu_generate_round",
    )
    for value in required:
        with self.subTest(value=value):
            self.assertIn(value, quickstart)
    forbidden = ("D:\\", "C:\\Users\\", "route:", "model:")
    for value in forbidden:
        with self.subTest(value=value):
            self.assertNotIn(value, quickstart)
```

Extend the unsupported-claim scan with `README.md`, `docs/quickstart.md`, and `docs/github-listing.md`, and reject guaranteed Star, speed, VRAM, concurrency, quality-superiority, or production-readiness wording.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
python -m unittest tests.test_public_docs -v
```

Expected: failures identify the absent Quickstart and old pending-evidence first viewport. Do not commit the red state.

- [ ] **Step 3: Write the bounded Quickstart**

Create `docs/quickstart.md` with this exact section order:

```markdown
# Five-Minute Quickstart

This path is for Python 3.11 or 3.12 users whose supported backend and model are already running. It excludes backend installation, model downloads, and generation time.

## 1. Verify The Installed Server
## 2. Add It To Codex Or Claude Code
## 3. Restart Or Reload The Client
## 4. Check Backend Readiness
## 5. Ask For One Bounded Image
## Roll Back Client Setup
## First-Run Problems
```

Under the sections, use only these installed commands:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
uvx local-gpu-imagegen setup claude-code --apply
uvx local-gpu-imagegen doctor
codex mcp remove local-gpu-imagegen
claude mcp remove --scope user local-gpu-imagegen
```

After each state transition, state the observable checkpoint: verify JSON has `ok: true` and fifteen tools; setup JSON has `applied: true`; the client is restarted/reloaded and lists `local-gpu-imagegen`; doctor reports the selected backend reachable; the Agent displays discovery/trust/recommendation and exact route before generation. Use this literal request:

> Create one complete lighthouse environment illustration with no people, text, logo, or watermark. Reuse my existing local backend and model, keep downloads and model switching disabled, use at most two successful rounds, and ask me before finalization.

Link first-run failures to `docs/troubleshooting.md` and deeper client details to `docs/client-compatibility.md`; do not duplicate their full reference material.

- [ ] **Step 4: Replace the README pending block with the evidence-first viewport**

Keep the literal H1 and approved promise. Immediately after them, place:

1. `![A solitary lighthouse generated through the validated ordinary local SDXL route](docs/demo/real/final.png)`;
2. a compact caption naming ordinary `sdxl-txt2img`, exact SHA-256 read from the showcase manifest, `1024x1024`, original finalized PNG, and link to `docs/demo/real/showcase-manifest.json`;
3. the two installed commands already present;
4. a link labeled `Five-minute Quickstart` to `docs/quickstart.md`;
5. the literal lighthouse request from Step 3;
6. one boundary sentence saying an existing local image backend/model is required and there are no silent model downloads or switches.

Move the simulated GIF below the first trust-proof section. Keep its simulated/model-free disclaimer adjacent to it. Follow the Quickstart link with a compact trust proof covering discovery without loading weights, explicit trust/route identity, bounded successful rounds, original-resolution review, byte-bound finalization, and recoverable run state.

- [ ] **Step 5: Synchronize listing, demo index, and release gates**

In `docs/github-listing.md`, replace the pending-golden sentence with a truthful validated-evidence summary naming one ordinary SDXL/ComfyUI result and its limitations. Keep regional/two-stage routes experimental and keep all publication-dependent URLs described as pending.

In `docs/demo/README.md`, replace the pending paragraph with links to `real/final.png`, `real/showcase-manifest.json`, and `real/README.md`, while preserving the distinction from the simulated GIF.

In `docs/release-checklist.md`, check only the evidence items actually satisfied by Tasks 2-4. Add unchecked items for social-preview review, pessimistic forecast `>=100`, and explicit remote-metadata/publication authority. Do not check Claude Code, CI, PyPI, Registry, tag, or release items without later evidence.

- [ ] **Step 6: Run documentation and evidence gates**

```powershell
python -m unittest tests.test_public_docs tests.test_repository_hygiene tests.test_validate_real_demo -v
python scripts/validate_real_demo.py docs/demo/real
git diff --check
```

Expected: all pass; the genuine image precedes the simulated GIF; the first viewport contains the manifest-derived hash and ordinary workflow; Quickstart contains restart and rollback; no unsupported claim or private value appears.

- [ ] **Step 7: Commit the conversion-first documentation**

```powershell
git add README.md docs/quickstart.md docs/github-listing.md docs/release-checklist.md docs/demo/README.md tests/test_public_docs.py
git commit -m "docs: lead with validated local generation"
```

---

### Task 5: Build And Review The Genuine-Image Social Preview

**Files:**
- Create: `docs/assets/github-social-preview.html`
- Create: `docs/assets/github-social-preview.png`
- Create: `docs/assets/github-social-preview.json`
- Create: `scripts/validate_social_preview.py`
- Create: `tests/test_social_preview.py`
- Modify: `docs/release-checklist.md`

**Interfaces:**
- Consumes: validated `docs/demo/real/final.png` and its SHA-256 from `showcase-manifest.json`.
- Produces: one exact `1280x640` PNG, a repository-owned HTML/CSS source, a hash manifest, and a standard-library validator. The PNG is a repository preview candidate, not a UI screenshot or remote metadata mutation.

- [ ] **Step 1: Write the failing asset validator tests**

Create `tests/test_social_preview.py`:

```python
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_social_preview import validate_social_preview


class SocialPreviewTests(unittest.TestCase):
    def test_social_preview_is_bound_to_validated_public_image(self) -> None:
        self.assertEqual(validate_social_preview(ROOT), [])

    def test_social_preview_copy_names_product_clients_and_backends(self) -> None:
        source = (
            ROOT / "docs" / "assets" / "github-social-preview.html"
        ).read_text(encoding="utf-8")
        for text in (
            "Local GPU Imagegen",
            "Codex + Claude Code",
            "ComfyUI / Forge / Diffusers",
            "Use the image models you already run locally",
            "../demo/real/final.png",
        ):
            with self.subTest(text=text):
                self.assertIn(text, source)

        manifest = json.loads(
            (ROOT / "docs" / "assets" / "github-social-preview.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["width"], 1280)
        self.assertEqual(manifest["height"], 640)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement the standard-library validator**

Create `scripts/validate_social_preview.py` with this implementation:

```python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_FIELDS = {
    "schema_version",
    "source",
    "source_sha256",
    "output",
    "output_sha256",
    "width",
    "height",
}
REQUIRED_COPY = (
    "Local GPU Imagegen",
    "Use the image models you already run locally",
    "Codex + Claude Code",
    "ComfyUI / Forge / Diffusers",
    "../demo/real/final.png",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid_json_object")
    return value


def png_dimensions(path: Path) -> tuple[int, int]:
    encoded = path.read_bytes()
    if encoded[:8] != b"\x89PNG\r\n\x1a\n" or encoded[12:16] != b"IHDR":
        raise ValueError("invalid_png")
    return struct.unpack(">II", encoded[16:24])


def record_social_preview(root: Path) -> dict[str, object]:
    source = root / "docs" / "demo" / "real" / "final.png"
    output = root / "docs" / "assets" / "github-social-preview.png"
    width, height = png_dimensions(output)
    manifest = {
        "schema_version": "1.0",
        "source": "docs/demo/real/final.png",
        "source_sha256": _sha256(source),
        "output": "docs/assets/github-social-preview.png",
        "output_sha256": _sha256(output),
        "width": width,
        "height": height,
    }
    path = root / "docs" / "assets" / "github-social-preview.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_social_preview(root: Path) -> list[str]:
    findings: set[str] = set()
    assets = root / "docs" / "assets"
    source = root / "docs" / "demo" / "real" / "final.png"
    output = assets / "github-social-preview.png"
    html = assets / "github-social-preview.html"
    try:
        manifest = _read_json(assets / "github-social-preview.json")
        showcase = _read_json(
            root / "docs" / "demo" / "real" / "showcase-manifest.json"
        )
        source_sha256 = _sha256(source)
        output_sha256 = _sha256(output)
        dimensions = png_dimensions(output)
        source_text = html.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return ["invalid_social_preview_files"]
    if set(manifest) != MANIFEST_FIELDS or manifest.get("schema_version") != "1.0":
        findings.add("invalid_social_preview_manifest")
    if manifest.get("source") != "docs/demo/real/final.png":
        findings.add("invalid_social_preview_source")
    if manifest.get("output") != "docs/assets/github-social-preview.png":
        findings.add("invalid_social_preview_output")
    if manifest.get("source_sha256") != source_sha256:
        findings.add("social_preview_source_sha256_mismatch")
    if manifest.get("output_sha256") != output_sha256:
        findings.add("social_preview_output_sha256_mismatch")
    if not SHA256_RE.fullmatch(str(manifest.get("source_sha256", ""))):
        findings.add("invalid_social_preview_source_sha256")
    if not SHA256_RE.fullmatch(str(manifest.get("output_sha256", ""))):
        findings.add("invalid_social_preview_output_sha256")
    if dimensions != (1280, 640):
        findings.add("invalid_social_preview_dimensions")
    if (manifest.get("width"), manifest.get("height")) != dimensions:
        findings.add("social_preview_dimension_mismatch")
    final = showcase.get("final")
    if not isinstance(final, dict) or final.get("image_sha256") != source_sha256:
        findings.add("social_preview_not_bound_to_showcase")
    for required in REQUIRED_COPY:
        if required not in source_text:
            findings.add(f"social_preview_copy_missing:{required}")
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.record:
        record_social_preview(root)
    findings = validate_social_preview(root)
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Create the exact 1280x640 HTML/CSS source**

Build one unrounded full-bleed `1280x640` canvas. Use a two-column composition with the genuine lighthouse occupying the right 54 percent through `object-fit: cover`; use a neutral near-black left field, white title, restrained green proof accent, and no gradient, orb, decorative card, mock window chrome, or fabricated UI. Include only:

```html
<main id="preview" aria-label="Local GPU Imagegen social preview">
  <section class="message">
    <p class="label">LOCAL GPU IMAGEGEN</p>
    <h1>Use the image models<br>you already run locally</h1>
    <p class="clients">Codex + Claude Code</p>
    <p class="backends">ComfyUI / Forge / Diffusers</p>
  </section>
  <figure>
    <img src="../demo/real/final.png" alt="Validated lighthouse generation">
    <figcaption>GENUINE LOCAL GPU RESULT</figcaption>
  </figure>
</main>
```

Use fixed pixel dimensions and fixed typography, not viewport-scaled font sizes. Preserve readable contrast and ensure the longest line does not overlap the image.

- [ ] **Step 4: Render the PNG without adding a project dependency**

Use the available browser tooling to open the local HTML, set the viewport to exactly `1280x640`, wait for `document.fonts.ready` and the image's `complete && naturalWidth > 0`, then capture only `#preview` to `docs/assets/github-social-preview.png`. Do not install or record Playwright, Node, Pillow, ImageMagick, or browser packages in project metadata.

Generate the closed hash manifest from the finished tracked files and run the validator immediately:

```powershell
python scripts/validate_social_preview.py --record
python scripts/validate_social_preview.py
```

- [ ] **Step 5: Perform full-size and thumbnail visual review**

Inspect the PNG at `1280x640` and at a downscaled `320x160` view. Require: genuine lighthouse visible; product name and promise readable; no text clipping; no aspect distortion; no overlap; no personal/private content; no implication that the image is a UI screenshot; no unsupported quality or performance claim. Record the review and hashes privately under `outputs/v070-launch-private/social-preview-review.json`.

- [ ] **Step 6: Run asset, document, and hygiene tests**

```powershell
python -m unittest tests.test_social_preview tests.test_public_docs tests.test_repository_hygiene -v
python scripts/validate_social_preview.py
git diff --check
```

Expected: no findings and all tests pass. Then check only the social-preview local-review item in `docs/release-checklist.md`; leave remote upload unchecked.

- [ ] **Step 7: Commit the preview candidate**

```powershell
git add docs/assets/github-social-preview.html docs/assets/github-social-preview.png docs/assets/github-social-preview.json scripts/validate_social_preview.py tests/test_social_preview.py docs/release-checklist.md
git commit -m "docs: add validated GitHub social preview"
```

---

### Task 6: Verify The Five-Minute Installed Path And Freeze Local Release Evidence

**Files:**
- Modify only on reproduced documentation mismatch: `docs/quickstart.md`, `README.md`, or their focused test.
- Create privately/ignored: `outputs/v070-launch-private/quickstart-verification.json`
- Modify after verification: `PROJECT_NODES.md` and `NEXT_SESSION.md`.

**Interfaces:**
- Consumes: exact previously built `0.7.0` wheel SHA-256 `83ba9a8bc078f488d69b006e73f5dd2c89e7fe6e78b3302961d750beb5acc1a8` and the installed commands documented in Task 4.
- Produces: timestamped evidence that the bounded path works outside the checkout for an already-running backend user, or removes the five-minute label and keeps release blocked.

- [ ] **Step 1: Verify the exact wheel outside the checkout**

Create a fresh temporary directory and Python 3.12 virtual environment outside the source tree. Install the existing exact wheel without rebuilding and without dependencies, then verify its SHA-256 before installation. Run:

```powershell
local-gpu-imagegen verify
local-gpu-imagegen setup codex
local-gpu-imagegen setup claude-code
local-gpu-imagegen doctor
```

Expected: verify returns `ok: true`, version `0.7.0`, protocol `2024-11-05`, exactly fifteen tools; both setup calls are read-only and return `status: planned`; doctor returns valid JSON even if some nonselected backends are unavailable.

- [ ] **Step 2: Validate apply and rollback with disposable client state**

Use the existing fake-client test harness or an isolated disposable client configuration. Confirm both `setup codex --apply` and `setup claude-code --apply` invoke the official client command and do not directly edit a configuration file. Confirm the documented remove commands reverse only the `local-gpu-imagegen` registration. Do not touch the user's real client configuration during this test.

- [ ] **Step 3: Record timing and scope honestly**

Record command, exit code, elapsed wall time, wheel digest, Python version, and observed checkpoint in `outputs/v070-launch-private/quickstart-verification.json`. The timed path ends at backend readiness and excludes backend/model startup and generation. If the documented path itself exceeds five minutes or needs an undisclosed prerequisite, change the title to `Quickstart`, remove all five-minute wording from public files/tests, and retain the release blocker.

- [ ] **Step 4: Run the complete local release gate**

```powershell
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
Get-ChildItem -Recurse -File -Filter *.json | ForEach-Object { Get-Content -Raw $_.FullName | ConvertFrom-Json | Out-Null }
python scripts/validate_real_demo.py docs/demo/real
python scripts/validate_client_sessions.py docs/evidence/client-sessions/codex-v070.json
python scripts/validate_social_preview.py
git diff --check
git status --short
```

Expected: all tests pass, compilation is silent, all JSON parses as strict UTF-8, all validators report no findings, diff check is empty, and only intended continuity/private ignored files remain outside the clean tracked worktree.

- [ ] **Step 5: Freeze the exact local commit**

Record `git rev-parse HEAD`, wheel SHA-256, evidence manifest SHA-256, final image SHA-256, social-preview SHA-256, and all verification results in `PROJECT_NODES.md`. Keep `NEXT_SESSION.md` limited to unresolved Claude Code evidence, remote CI/publication gates, and the demand forecast.

---

### Task 7: Produce The Evidence-Backed 30-Day Star Forecast

**Files:**
- Create privately/ignored: `outputs/v070-launch-private/github-benchmark.json`
- Create privately/ignored: `outputs/v070-launch-private/github-conversion-forecast.md`
- Modify: `docs/release-checklist.md` only if the pessimistic gate passes with cited evidence.
- Modify after decision: `PROJECT_NODES.md` and `NEXT_SESSION.md`.

**Interfaces:**
- Consumes: current read-only GitHub repository/competitor observations, verified repository conversion surface, named reachable channels, and measurable prelaunch signals.
- Produces: pessimistic/base/upside first-30-day Star scenarios with explicit formulas, deduplicated exposure assumptions, citations, confidence labels, and a release decision.

- [ ] **Step 1: Refresh the scoped benchmark read-only**

Record timestamped public facts for the approved direct, adjacent, and aspirational repository set. For each repository capture current Stars, age, last update, first-viewport visual presence, labeled Quick Start, install command, named clients/backends, docs/community path, and evidence discipline. Keep the historical-data limitation explicit: current totals are not first-month counts, and unavailable `starred_at` history remains unknown rather than inferred.

- [ ] **Step 2: Inventory only channels with defensible reach floors**

For the pessimistic case, include a channel only when it has a named owner, available launch action, timing, nonzero defensible qualified-exposure floor, and a reason that floor is reachable. Treat Bilibili, Douyin, uncommitted directory placements, algorithmic discovery, and unverified community amplification as zero. Deduplicate audiences across GitHub, MCP Registry, package pages, directories, and communities before summing.

- [ ] **Step 3: Calculate three scenarios with one transparent formula**

For every channel and scenario use:

```text
expected_stars = unique_qualified_exposures * repository_visit_rate * star_conversion_rate
scenario_total = sum(expected_stars by deduplicated channel)
```

Each nonzero input must cite either a measured prelaunch signal or a scoped benchmark observation. Show raw, deduplicated, and converted values; state uncertainty and do not round a value below 100 upward to pass.

- [ ] **Step 4: Apply the hard release decision**

Write one of these exact outcomes in the private forecast:

```text
PASS: pessimistic 30-day estimate is at least 100 Stars; technical and authority gates remain independently required.
```

```text
BLOCKED: pessimistic 30-day estimate is below 100 Stars or depends on an unproven reach floor; formal release is prohibited.
```

Only for `PASS`, check the forecast item in `docs/release-checklist.md`. Never add forecast numbers or a Star guarantee to README, package metadata, GitHub listing copy, or the social preview.

- [ ] **Step 5: Record the next conversion experiment if blocked**

If blocked, name one smallest measurable prelaunch experiment, its channel, observation window, success metric, maximum cost, and stop condition. Prefer repository-native or already-authorized distribution evidence. Video creation can be scheduled as upside, but its reach stays zero in the pessimistic case until measured.

- [ ] **Step 6: Commit only a changed tracked checklist**

If and only if the forecast passes and changes `docs/release-checklist.md`:

```powershell
git add docs/release-checklist.md
git commit -m "docs: record pessimistic demand gate"
```

Keep benchmark inputs and forecast calculations ignored and private regardless of outcome.

---

### Task 8: Stop At The Remote Authority Boundary

**Files:**
- No local file change unless a final verification exposes a reproducible defect.

**Interfaces:**
- Consumes: clean exact commit, all local technical gates, validated evidence and assets, named-client/CI/package/Registry status, and Task 7 decision.
- Produces: a precise authority request, not a remote mutation.

- [ ] **Step 1: Reconcile every remaining release gate**

Require the checklist to distinguish local proof from still-pending Claude Code, four-platform CI, exact PyPI artifact, MCP Registry, remote topics, Discussions, social-preview upload, push, tag, release, directory submission, and first-30-day forecast. No pending item may be described as complete.

- [ ] **Step 2: Stop if the pessimistic forecast is below 100**

Report the blocked state and the next measurable experiment. Do not ask for publication authority, push, tag, create a release, or apply remote metadata.

- [ ] **Step 3: If all independent gates pass, request narrowly scoped remote authorities**

Request explicit authority separately for: push; repository topics and social-preview upload; Discussions enablement; PyPI publication; MCP Registry publication; tag/release; and each directory/community submission. A response authorizing one action cannot be reused for another.

---

## Self-Review

- Spec coverage: Tasks 1-3 preserve and export genuine evidence; Task 4 implements the evidence-first viewport, five-minute path, trust proof, and conversion copy; Task 5 produces the shareable visual; Task 6 proves the installed path; Task 7 implements the benchmark/forecast gate; Task 8 preserves remote authority boundaries.
- Scope discipline: no MCP architecture, tool, backend, model, workflow, download, or package dependency change is planned.
- Evidence discipline: the real image remains private until exact finalization and separately authorized export; every public claim is derived from validated tracked evidence.
- Demand discipline: unproven video traffic remains zero in the pessimistic case, and publication remains prohibited below 100.
- Placeholder scan: runtime hashes are computed from retained artifacts and must be written as actual lowercase digests before commit; no guessed value is accepted.
- Type consistency: dimensions are integers `256..1536`, divisible by 8, and must match route, generation, final metadata, PNG IHDR, and public manifest.
