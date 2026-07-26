# Agent Runner Launch Repositioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make supported ComfyUI API workflow execution from Codex or Claude Code the repository's primary launch path while adding a narrow semantic-fidelity quality guardrail.

**Architecture:** Reuse the existing 17-tool MCP surface, safe workflow onboarding implementation, installed-client evidence, and retained public image. Change only public contracts, documentation, metadata, the Agent Skill policy, and the derived social preview unless a failing first-run test proves production code is necessary.

**Tech Stack:** Markdown, JSON, Python 3.11/3.12 `unittest`, existing HTML social-preview source, existing Pillow/Playwright-capable local tooling, Git.

## Global Constraints

- Work only in `.worktrees/v081-agent-runner-launch` on `codex/v081-agent-runner-launch`; do not modify `main`.
- Add no production module, dependency, model, custom node, GPU submission, or remote mutation.
- Keep version `0.8.0` and the exact 17-tool MCP surface unchanged.
- Use "supported ordinary ComfyUI API workflows", never "any workflow".
- Keep onboarding evidence and generation evidence explicitly separate.
- Keep regional and two-stage workflow worktree and cached diffs empty before and after every task.
- Do not mutate real trust, client configuration, backend, model, or remote state.
- Preserve ignored and untracked user files.
- Each task ends with focused verification and one independent commit.

---

### Task 1: Freeze The Launch Copy Contract In Tests

**Files:**
- Modify: `tests/test_public_docs.py`
- Modify: `tests/test_social_preview.py`

**Interfaces:**
- Produces the exact public-copy and quality-boundary contract used by Tasks 2-4.
- Does not modify production or public documentation.

- [ ] **Step 1: Reconfirm branch and frozen workflow diffs**

Run:

```powershell
git status --short --branch
git diff -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
```

Expected: the launch branch is active and both workflow commands print nothing.

- [ ] **Step 2: Replace the first-viewport promise assertion**

In `test_readme_leads_with_literal_offer_and_installed_path`, require this exact
promise:

```python
promise = (
    "Run the ComfyUI API workflows you already trust from Codex or Claude Code, "
    "locally, reproducibly, and without silent downloads or model switches."
)
```

Also require `Bring Your Own ComfyUI Workflow` in the first 70 README lines and
assert the promise appears before that heading.

- [ ] **Step 3: Add a primary-onboarding and evidence-separation test**

Add:

```python
def test_launch_docs_lead_with_supported_workflow_onboarding(self) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = QUICKSTART.read_text(encoding="utf-8")
    for required in (
        "supported ordinary ComfyUI API workflow",
        "Save (API Format)",
        "local_gpu_inspect_workflow",
        "local_gpu_register_workflow",
        "registration does not grant model trust",
    ):
        self.assertIn(required, readme + "\n" + quickstart)
    self.assertLess(
        quickstart.index("local_gpu_inspect_workflow"),
        quickstart.index("Profile-Driven Run"),
    )
    self.assertIn("did not submit a prompt", readme)
    self.assertIn("separate retained Codex generation", readme)
```

- [ ] **Step 4: Add a semantic-fidelity quality contract test**

Add `QUALITY_CONTROL = ROOT / "docs" / "image-quality-control.md"` and:

```python
def test_quality_control_rejects_semantic_substitution(self) -> None:
    quality = QUALITY_CONTROL.read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "local-gpu-imagegen" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "semantic substitution",
        "product medium",
        "failed constraint",
        "MODEL_QUALITY_LIMIT",
        "FAIL_WORKFLOW_REGRESSION",
    ):
        self.assertIn(required, quality + "\n" + skill)
```

- [ ] **Step 5: Update the social-preview copy test**

Replace the old headline with:

```python
"Run your ComfyUI workflows from your Agent"
```

Keep assertions for product name, clients, backends, retained image source, and
1280x640 dimensions.

- [ ] **Step 6: Run the red tests**

Run:

```powershell
python -m unittest tests.test_public_docs tests.test_social_preview
```

Expected: failures identify the old README promise, missing primary onboarding
copy, missing quality-control document, and old social-preview headline.

- [ ] **Step 7: Commit the red contract**

```powershell
git add tests/test_public_docs.py tests/test_social_preview.py
git diff --cached --check
git commit -m "test: define agent workflow launch contract"
```

---

### Task 2: Reposition README And Public Metadata

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `server.json`
- Modify: `.codex-plugin/plugin.json`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes Task 1's exact literal offer.
- Produces one coherent public description without changing runtime behavior.

- [ ] **Step 1: Rewrite the README first viewport**

Use the exact offer from Task 1. Keep the retained image and SHA-256, installed
commands, quickstart link, backend/model precondition, and truthfulness boundary.
Add a `Bring Your Own ComfyUI Workflow` block in the first 70 lines with this
flow:

```text
Export API JSON -> inspect bindings and hashes -> confirm registration
-> trust the exact local components -> run with a frozen route
```

State that the retained onboarding session did not submit a prompt and that the
displayed image comes from a separate retained Codex generation.

- [ ] **Step 2: Trim the visible value list**

Lead `Why This Project` with existing-workflow reuse, Agent execution,
reproducibility, and no silent changes. Keep detailed acceptance, revisions,
profiles, and safety below those user-visible outcomes. Do not remove tool
names or historical truthfulness text required by current tests.

- [ ] **Step 3: Synchronize metadata descriptions**

Use these bounded descriptions:

```toml
description = "Run supported local ComfyUI workflows from Codex or Claude Code with explicit routes and no silent downloads."
```

```json
"description": "Run supported local ComfyUI workflows from Codex or Claude Code with explicit routes and no silent downloads."
```

Update plugin short/long descriptions consistently while preserving the
existing backend compatibility and evidence limitations.

- [ ] **Step 4: Record the repositioning in Unreleased**

Add a Changed entry stating that supported ComfyUI API workflow execution is
now the primary launch path and built-in prompt workflows make no quality
superiority claim.

- [ ] **Step 5: Run focused tests**

```powershell
python -m unittest tests.test_public_docs tests.test_client_configs tests.test_client_setup
```

Expected: first-viewport and metadata assertions pass; onboarding and quality
tests remain red until Tasks 3 and 4.

- [ ] **Step 6: Commit**

```powershell
git add README.md pyproject.toml server.json .codex-plugin/plugin.json CHANGELOG.md
git diff --cached --check
git commit -m "docs: lead with existing ComfyUI workflows"
```

---

### Task 3: Make Safe Workflow Onboarding The Quickstart

**Files:**
- Modify: `docs/quickstart.md`
- Modify: `docs/demo/README.md`
- Modify: `docs/github-listing.md`
- Create: `docs/demo/workflow-onboarding.md`

**Interfaces:**
- Consumes the retained `codex-v080-workflow-onboarding.json` session.
- Produces a public-safe primary onboarding path and explicit evidence map.

- [ ] **Step 1: Rewrite quickstart steps 4 and 5**

After setup and `doctor`, instruct the user to enable ComfyUI Developer mode and
use `Save (API Format)`. Provide this Agent request:

```text
Inspect my supported ordinary ComfyUI API workflow at
<path-to-workflow-api.json>. Show its source hash, semantic workflow hash,
inferred bindings, components, limitations, and exact registration
confirmation. Do not register, trust, download, or run anything until I confirm
each displayed boundary.
```

Then show the exact tool sequence. Keep the existing profile-driven lighthouse
request under `## Profile-Driven Run` as a secondary path. Keep rollback and
first-run troubleshooting unchanged.

- [ ] **Step 2: Add the retained onboarding evidence note**

Create `docs/demo/workflow-onboarding.md` with the six retained calls, session
purpose, installed Codex version, wheel version, source/workflow hash evidence,
sanitization boundary, and the explicit statement that it did not submit a
prompt or prove generated-image quality.

- [ ] **Step 3: Update demo index and GitHub listing**

Link the onboarding note before the generated-image evidence. Keep the separate
generation proof and its limitations. Change listing title to:

```text
v0.8.0 Preview - Run existing ComfyUI workflows from your Agent
```

State the 30-day 50-Star target only as a measurement goal if mentioned; do not
call it a floor, guarantee, or release blocker.

- [ ] **Step 4: Run focused tests**

```powershell
python -m unittest tests.test_public_docs tests.test_validate_client_sessions
```

Expected: primary onboarding and evidence-separation tests pass; quality test
remains red.

- [ ] **Step 5: Commit**

```powershell
git add docs/quickstart.md docs/demo/README.md docs/demo/workflow-onboarding.md docs/github-listing.md
git diff --cached --check
git commit -m "docs: make workflow onboarding the quickstart"
```

---

### Task 4: Add The Semantic-Fidelity Quality Guardrail

**Files:**
- Create: `docs/image-quality-control.md`
- Modify: `skills/local-gpu-imagegen/SKILL.md`
- Modify: `README.md`

**Interfaces:**
- Produces an Agent review policy using existing constraint results and user
  authority; adds no engine schema or production code.

- [ ] **Step 1: Write the quality-control document**

Define semantic fidelity, product medium, intended asset slot, hard defects,
model limits, paired no-regression evaluation, and the frozen 2026-07-26
negative result. State that semantic substitution is a failed constraint even
when visual polish improves.

- [ ] **Step 2: Add the Agent Skill rule**

Under `Review Evidence`, add:

```text
Before scoring polish, compare the full-resolution image with the frozen intent.
A change to the requested product medium, subject, practical use, or asset slot
is semantic substitution. Record it as a failed constraint and do not finalize
that round, even when the substitute is cleaner or has fewer rendering defects.
```

The rule must use existing review fields and must not invent a new MCP schema.

- [ ] **Step 3: Link the boundary from README**

Add a short `Image Quality Boundary` section stating that model and workflow
quality remain user supplied, linking the quality-control report and frozen gate.

- [ ] **Step 4: Run the green focused suite**

```powershell
python -m unittest tests.test_public_docs tests.test_social_preview
```

Expected: all tests pass except the social-preview source/output hash until Task
5 regenerates the derived PNG.

- [ ] **Step 5: Commit**

```powershell
git add docs/image-quality-control.md skills/local-gpu-imagegen/SKILL.md README.md
git diff --cached --check
git commit -m "docs: reject semantic drift in visual review"
```

---

### Task 5: Refresh Launch Preview And Verify The Branch

**Files:**
- Modify: `docs/assets/github-social-preview.html`
- Modify generated: `docs/assets/github-social-preview.png`
- Modify generated: `docs/assets/github-social-preview.json`
- Modify: `PROJECT_NODES.md`
- Modify: `NEXT_SESSION.md`

**Interfaces:**
- Produces the final local release candidate and continuity record.

- [ ] **Step 1: Change social-preview copy**

Use `Run your ComfyUI workflows from your Agent`, retain `Codex + Claude Code`,
`ComfyUI / Forge / Diffusers`, and the genuine image source. Do not imply that
the image came from the onboarding session.

- [ ] **Step 2: Render and inspect 1280x640 output**

Render the local HTML using an already-installed browser runtime. Do not install
or download browser packages. Verify the PNG dimensions and inspect it visually
for clipping, overlap, legibility, and correct source image.

- [ ] **Step 3: Record the derived manifest**

```powershell
python scripts/validate_social_preview.py --record
python scripts/validate_social_preview.py
```

Expected: `ok: true`, source hash unchanged, output hash updated.

- [ ] **Step 4: Update continuity documents**

Record the launch positioning, exact branch/worktree, commits, verification,
quality boundary, no-remote state, and immediate next decision. Keep
`NEXT_SESSION.md` focused on reviewing and locally integrating this branch
before any separately approved publication action.

- [ ] **Step 5: Run full verification**

```powershell
python -m unittest discover -s tests
python -m compileall -q scripts tests
python scripts/verify_mcp.py
python scripts/verify_client_configs.py
git diff --check
git diff -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
git diff --cached -- workflows/comfyui/sdxl-regional-txt2img-v1.json workflows/comfyui/sdxl-two-stage-copy-subject-v1.json
```

Expected: 797 existing tests plus the new documentation tests pass with seven
expected Windows skips; compileall and both verifiers pass; frozen workflow
diffs remain empty.

- [ ] **Step 6: Commit final assets and continuity**

```powershell
git add docs/assets/github-social-preview.html docs/assets/github-social-preview.png docs/assets/github-social-preview.json PROJECT_NODES.md NEXT_SESSION.md
git diff --cached --check
git commit -m "docs: prepare agent workflow launch preview"
```

- [ ] **Step 7: Confirm no remote mutation**

Run `git status --short --branch` and `git log -6 --oneline`. Preserve the
worktree and branch. Do not push, merge, tag, publish, or update remote metadata.
