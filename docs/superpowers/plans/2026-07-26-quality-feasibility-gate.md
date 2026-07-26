# One-Day Quality Feasibility Gate Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine with six blinded, budget-matched raw-ComfyUI versus project-workflow pairs whether the current workflow visibly degrades anime, frontend-hero, or presentation-cover output.

**Architecture:** Use the already-installed loopback ComfyUI and the already-trusted Z-Image route. A local ignored operator freezes the common briefs, prior ordinary/workflow prompts, paired seeds, execution order, submission ledger, candidate hashes, and blind labels. The raw lane submits the reviewed Z-Image API graph directly; the project lane uses discovery, routing, `AssetRunEngine`, and the shipped workflow without changing production code or state.

**Tech Stack:** Python 3.11/3.12 standard library, existing Pillow 12.0.0, existing project modules, ComfyUI HTTP API, PowerShell, Git.

## Global Constraints

- Work only in `.worktrees/v081-quality-feasibility-gate` on `codex/v081-quality-feasibility-gate`; do not modify `main`.
- Approved design: `docs/superpowers/specs/2026-07-26-quality-feasibility-gate-design.md` at commit `7045b80`.
- Add zero production lines, zero tests, zero dependencies, zero models, zero custom nodes, and zero tracked workflow files.
- The only tracked execution result is `docs/quality-feasibility-gate-report.md`; local definitions, operator code, logs, images, ledgers, blind maps, and contact sheets remain ignored under `outputs/quality-feasibility-gate/2026-07-26/`.
- Use at most twelve actual GPU submissions: three cases x two seeds x two lanes. A backend submission counts when ComfyUI accepts `/prompt`, even if later execution fails.
- Use the same `z_image_turbo_nvfp4.safetensors`, `qwen_3_4b_fp4_mixed.safetensors`, `ae.safetensors`, graph topology, dimensions, sampler, scheduler, steps, guidance, and paired seed across lanes. Z-Image negative conditioning remains zeroed in both lanes.
- The raw lane bypasses MCP, `AssetRunEngine`, `PromptCompilerRegistry`, and project run orchestration. The project lane uses all of them. Lane prompts differ exactly as frozen from the prior trial; no prompt is rewritten after an output is visible.
- Do not mutate trust, client, global Python, model, workflow, or remote state. Do not download, push, tag, publish, release, change metadata, or start regional/two-stage work.
- Keep exact working-tree and cached diffs for `workflows/comfyui/sdxl-regional-txt2img-v1.json` and `workflows/comfyui/sdxl-two-stage-copy-subject-v1.json` empty before and after every task.
- Start one hidden `127.0.0.1:8188` ComfyUI process only if no compatible listener exists. Stop it only after PID, executable, arguments, and task ownership still match.
- Two consecutive backend or route-identity failures stop the gate. No healthy pair may be skipped because an earlier image looks good or bad.
- Do not inspect `blind-map.private.json` until all candidate scores and pair preferences are written to `blinded-review.json`.

## Local File Map

| File | Responsibility |
|---|---|
| `outputs/quality-feasibility-gate/2026-07-26/gate-definition.json` | Frozen cases, lane prompts, settings, seeds, order, rubric, and source hashes. |
| `outputs/quality-feasibility-gate/2026-07-26/gate_operator.py` | Local-only structured ComfyUI/project runner, ledger writer, hasher, and contact-sheet builder. |
| `outputs/quality-feasibility-gate/2026-07-26/runtime.json` | Listener/process ownership and live ComfyUI identity. |
| `outputs/quality-feasibility-gate/2026-07-26/preflight.json` | Frozen repository, route, model, workflow, Pillow, and budget checks. |
| `outputs/quality-feasibility-gate/2026-07-26/submissions.jsonl` | Append-only before/accepted/completed/failed submission events. |
| `outputs/quality-feasibility-gate/2026-07-26/candidates/<case>/<lane>-<seed>.png` | Authoritative candidate bytes. |
| `outputs/quality-feasibility-gate/2026-07-26/blind-map.private.json` | Opaque label to lane/seed/hash map; concealed until review freezes. |
| `outputs/quality-feasibility-gate/2026-07-26/contact-sheets/<case>.png` | Four opaque-labeled candidates for blinded review. |
| `outputs/quality-feasibility-gate/2026-07-26/blinded-review.json` | Frozen per-label rubric scores, hard defects, publishability, and pair preferences. |
| `outputs/quality-feasibility-gate/2026-07-26/gate-result.json` | Revealed per-case comparison, model limits, accounting, and final decision. |
| `docs/quality-feasibility-gate-report.md` | Public-safe factual report without private paths or unpublished images. |

---

### Task 1: Freeze The Paired Experiment Before Backend Start

**Files:**
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/gate-definition.json`
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/gate_operator.py`

**Interfaces:**
- Produces `gate-definition.json` with exact case IDs `anime`, `frontend`, `presentation`, lane IDs `raw` and `workflow`, and twelve fixed submissions.
- Produces operator commands `preflight`, `run`, `blind`, and `reveal`.
- `run` consumes only the frozen definition and existing project/runtime state.

- [ ] **Step 1: Reconfirm branch and frozen files**

Run:

```powershell
git status --short --branch
git diff -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
```

Expected: branch is `codex/v081-quality-feasibility-gate`; only this plan may be untracked/modified before its commit; both workflow diff commands print nothing.

- [ ] **Step 2: Create the ignored output root and frozen definition**

Create `gate-definition.json` with `schema_version: 1`, `submission_ceiling: 12`, these settings, and no additional keys that can alter generation after freeze:

```json
{
  "model": "z_image_turbo_nvfp4.safetensors",
  "workflow_template_id": "z-image-turbo-txt2img",
  "steps": 8,
  "guidance_scale": 1.0,
  "sampler": "res_multistep",
  "scheduler": "simple",
  "negative_prompt_behavior": "ignored_by_conditioning_zero_out"
}
```

Use these paired seeds and counterbalanced order:

```json
{
  "anime": {"seeds": [2026072601, 2026072602], "order": ["raw", "workflow", "workflow", "raw"]},
  "frontend": {"seeds": [2026072603, 2026072604], "order": ["workflow", "raw", "raw", "workflow"]},
  "presentation": {"seeds": [2026072605, 2026072606], "order": ["raw", "workflow", "workflow", "raw"]}
}
```

Freeze the exact prior-trial ordinary and initial-workflow positive prompts from:

```text
../v080-release-coherence/outputs/showcase-v080/trial/cases/<case>/ordinary/generation-arguments.json
../v080-release-coherence/outputs/showcase-v080/trial/cases/<case>/workflow/generation-arguments-initial.json
```

Store their source relative paths and SHA-256 values beside the extracted prompts. Freeze dimensions `768x1024` for anime and `1280x720` for frontend/presentation. Freeze the six rubric dimensions from the design, each with integer range 1-5.

- [ ] **Step 3: Create the local operator with closed commands**

`gate_operator.py` must reject unknown commands/definition keys and implement these exact boundaries:

```python
COMMANDS = {"preflight", "run", "blind", "reveal"}
EXPECTED_CASES = ("anime", "frontend", "presentation")
EXPECTED_LANES = ("raw", "workflow")
SUBMISSION_CEILING = 12
OUTPUT_NODE = "11"

def append_event(path: Path, event: dict[str, object]) -> None:
    with path.open("a", encoding="ascii", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

Raw generation must deep-copy `workflows/comfyui/z-image-turbo-txt2img-v1.json["graph"]`, bind nodes `4.text`, `5.text`, `7.width/height`, `9.seed/steps/cfg/sampler_name/scheduler`, and `11.filename_prefix`, POST `{"prompt": graph, "client_id": client_id}` to `/prompt`, poll `/history/<prompt_id>`, then fetch the exact node-11 file through `/view`.

Project generation must construct current runtime services, execute one `api_only` ComfyUI discovery plan, recommend the frozen private route, start a one-round run, read its frozen route from the manifest, and call `engine.generate_round` with the frozen workflow prompt and settings. It must copy the retained authoritative PNG to the candidate path without changing bytes.

Before either lane calls `/prompt`, append `submission_started`; immediately after ComfyUI accepts a prompt ID append `submission_accepted`; after the authoritative PNG is copied and validated append `submission_completed`. An error after `submission_started` appends `submission_failed`. Count accepted prompt IDs, not output files, against the ceiling.

- [ ] **Step 4: Validate the frozen definition without backend or GPU**

Run:

```powershell
python outputs/quality-feasibility-gate/2026-07-26/gate_operator.py preflight --offline
```

Expected: exit `0`; report `12` planned submissions, six complete pairs, exact source hashes, unique output names, and no backend call. Any mismatch stops before GPU.

- [ ] **Step 5: Commit the amended approved design and execution plan**

Run:

```powershell
git add -f docs/superpowers/specs/2026-07-26-quality-feasibility-gate-design.md docs/superpowers/plans/2026-07-26-quality-feasibility-gate.md
git diff --cached --check
git commit -m "docs: plan workflow no-regression gate"
```

Expected: one documentation commit; ignored local operator/definition remain unstaged.

---

### Task 2: Qualify And Start The Exact Existing Runtime

**Files:**
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/runtime.json`
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/preflight.json`

**Interfaces:**
- Consumes the frozen definition and existing user-local trust state read-only.
- Produces one exact live endpoint/model/workflow qualification or `NO_QUALIFYING_ROUTE`.

- [ ] **Step 1: Inspect listener and executable identity**

Run `Get-NetTCPConnection` for local port `8188`. If absent, verify these exact existing paths before starting anything:

```text
E:\AI\local-gpu-imagegen\runtime\ComfyUI_windows_portable\python_embeded\python.exe
E:\AI\local-gpu-imagegen\runtime\ComfyUI_windows_portable\ComfyUI\main.py
```

Start hidden with working directory `E:\AI\local-gpu-imagegen\runtime\ComfyUI_windows_portable` and arguments:

```text
-s ComfyUI\main.py --windows-standalone-build --listen 127.0.0.1 --port 8188
```

Record `owned`, PID, executable, arguments, working directory, and start time in `runtime.json`. Do not reuse a non-loopback or identity-mismatched listener.

- [ ] **Step 2: Wait for bounded readiness**

Poll `http://127.0.0.1:8188/system_stats` for at most 180 seconds. Expected: ComfyUI `0.28.0`, one CUDA device, and loopback argv. Timeout or identity mismatch stops with zero submissions.

- [ ] **Step 3: Run live route preflight**

Run:

```powershell
$env:LOCAL_GPU_IMAGEGEN_COMFYUI_URL='http://127.0.0.1:8188'
$env:LOCAL_GPU_IMAGEGEN_OUTPUT_DIR=(Resolve-Path 'outputs/quality-feasibility-gate/2026-07-26/project-runs').Path
python outputs/quality-feasibility-gate/2026-07-26/gate_operator.py preflight
```

Expected `preflight.json` fields: endpoint identity, ComfyUI version, GPU name/VRAM, model/CLIP/VAE availability, shipped workflow SHA-256, source definition SHA-256, current trusted route ID, `planned_submissions: 12`, `accepted_submissions: 0`, and `ok: true`. A missing trusted Z-Image route yields `NO_QUALIFYING_ROUTE`; do not mutate trust.

---

### Task 3: Execute Exactly Six Raw/Workflow Pairs

**Files:**
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/submissions.jsonl`
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/candidates/**/*.png`

**Interfaces:**
- Consumes `gate-definition.json` and passing `preflight.json`.
- Produces exactly twelve completed candidate records unless a frozen stop condition fires.

- [ ] **Step 1: Execute the frozen order sequentially**

Run once:

```powershell
python outputs/quality-feasibility-gate/2026-07-26/gate_operator.py run
```

Expected order:

```text
anime/2026072601/raw
anime/2026072601/workflow
anime/2026072602/workflow
anime/2026072602/raw
frontend/2026072603/workflow
frontend/2026072603/raw
frontend/2026072604/raw
frontend/2026072604/workflow
presentation/2026072605/raw
presentation/2026072605/workflow
presentation/2026072606/workflow
presentation/2026072606/raw
```

Do not rerun a completed submission. Resume may process only a definition-identical missing submission whose ledger has no accepted prompt ID; an accepted but unresolved prompt must be queried by its retained prompt ID rather than resubmitted.

- [ ] **Step 2: Verify accounting and byte integrity before viewing images**

Run the operator's offline preflight again. Expected: accepted submissions `12`, completed candidates `12`, unique SHA-256 per retained file unless ComfyUI deterministically emitted identical bytes, correct dimensions, PNG MIME, no missing pair, no definition drift, and no more than two consecutive failures.

If the accounting is not exact, stop without constructing a favorable subset.

---

### Task 4: Blind The Images And Freeze Human Review

**Files:**
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/blind-map.private.json`
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/contact-sheets/*.png`
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/blinded-review.json`

**Interfaces:**
- Produces opaque labels with no lane/seed information in filenames or visible pixels.
- Requires user confirmation before `reveal` is allowed.

- [ ] **Step 1: Build randomized contact sheets**

Run:

```powershell
python outputs/quality-feasibility-gate/2026-07-26/gate_operator.py blind
```

Expected: one four-image sheet per case, labels independently shuffled with `secrets.SystemRandom`, source hashes retained in private map, and no lane names in sheet metadata or filenames. The operator must refuse to overwrite an existing blind map.

- [ ] **Step 2: Inspect original images and score while lanes remain concealed**

Inspect each sheet and each original opaque-labeled PNG. Write `blinded-review.json` containing for every label:

```json
{
  "scores": {
    "immediate_visual_appeal": 1,
    "composition_and_hierarchy": 1,
    "subject_detail_coherence": 1,
    "absence_of_obvious_defects": 1,
    "asset_slot_fitness": 1,
    "public_readiness": 1
  },
  "hard_defects": [],
  "publishable": false,
  "observation": "Concise full-resolution observation."
}
```

Replace each example `1` with the actual integer score. Add one preference `left`, `right`, or `tie` for each of the six opaque seed pairs without naming lanes. Freeze the file SHA-256.

- [ ] **Step 3: Obtain user visual authority**

Display the three contact sheets and report the blinded scores/preferences without revealing lanes. Ask the user to accept or correct the review. Do not run `reveal` until the user explicitly freezes the blinded review.

---

### Task 5: Reveal, Decide, Stop Owned Runtime, And Report

**Files:**
- Create ignored: `outputs/quality-feasibility-gate/2026-07-26/gate-result.json`
- Create tracked: `docs/quality-feasibility-gate-report.md`

**Interfaces:**
- Consumes the user-frozen review and private blind map.
- Produces exactly one workflow decision and independent model-quality findings.

- [ ] **Step 1: Reveal lanes only after review freeze**

Run:

```powershell
python outputs/quality-feasibility-gate/2026-07-26/gate_operator.py reveal
```

Expected: verify review/map hashes, select each lane's best score, apply the exact two-point/hard-defect regression rule, record `MODEL_QUALITY_LIMIT` independently, and output exactly one of `PASS_WORKFLOW_VALUE`, `PASS_NO_REGRESSION`, or `FAIL_WORKFLOW_REGRESSION`.

- [ ] **Step 2: Stop only an owned unchanged backend**

If `runtime.json.owned` is true, re-read PID executable and command line. Stop only when all recorded identity fields still match. Confirm port `8188` closes. If not owned, leave it running.

- [ ] **Step 3: Write the public-safe factual report**

Create `docs/quality-feasibility-gate-report.md` with exact accounting, sanitized route facts, lane prompts/settings, candidate hashes, blinded scores, reveal, per-case regression, model limits, stop-condition compliance, and final decision. State that this is a local bounded comparison, not a generalized model or Star guarantee.

- [ ] **Step 4: Run final repository verification**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q scripts tests
git diff --check
git diff -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git status --short
```

Expected: 797 tests pass with seven expected Windows skips, compileall succeeds, diff check succeeds, both frozen workflow diffs are empty, and only the factual report is uncommitted.

- [ ] **Step 5: Commit the factual report only**

Run:

```powershell
git add docs/quality-feasibility-gate-report.md
git commit -m "docs: report workflow no-regression gate"
```

Expected: ignored local trial artifacts remain unstaged; no push, merge, tag, release, or remote mutation occurs.
