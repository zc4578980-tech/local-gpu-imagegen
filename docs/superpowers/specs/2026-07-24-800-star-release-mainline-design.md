# 800-Star Release Mainline Design

**Date:** 2026-07-24

**Status:** Approved in conversation; written-spec review pending

**Branch:** `feature/v061-launch-readiness`

## Capability

Local GPU Imagegen 0.7.0 will give a Codex or Claude Code user a short,
installable path from an existing local ComfyUI, AUTOMATIC1111/Forge, or
Diffusers backend to one trusted, reviewable image result. The product will
lead with the user outcome: connect an Agent to an existing local image stack
without a source clone, silent model downloads, or silent model switches. Its
auditable route, budget, review, provenance, and finalization controls remain
the defensible reason to trust that path.

The 800-Star objective is a product and distribution target, not a release
claim or deterministic acceptance criterion.

## Positioning

### Target user

A developer or technical creator who already runs a local image-generation
backend and wants Codex or Claude Code to use it without surrendering model
selection, download authority, review control, or artifact provenance.

### Public promise

> Connect Codex or Claude Code to the image models you already run locally,
> with one installable command path and no silent model downloads or switches.

### Strategic tension

The target position is high first-run simplicity and high verifiable
reliability. The current project already has strong reliability controls but
does not yet make the shortest successful path or a genuine visual result
prominent enough. This milestone closes the simplicity and proof gap without
weakening the existing trust boundary.

### Messaging order

1. Outcome: the Agent can use the user's existing local image backend.
2. First run: verify, configure, and start through the installed CLI.
3. Proof: show a genuine retained image and the bounded evidence behind it.
4. Differentiation: no silent downloads, no silent route changes, explicit
   budgets, durable review, and byte-bound finalization.
5. Depth: discovery, trust, revisions, recovery, Profiles, and experimental
   composition controls.

## Product Scope

### In scope

- Publishable `uvx local-gpu-imagegen` verification, setup, doctor, and MCP
  serving paths that do not require a source clone or personal absolute path.
- Existing model discovery, explicit trust, deterministic recommendation,
  confirmed run budgets, generation, original-resolution review, and
  byte-bound finalization.
- One required public-rights golden demo with a genuine MCP request/result,
  original PNG, SHA-256, review, later user confirmation, finalization, and
  reproducible evidence export.
- Codex and Claude Code installed-command setup and stdio compatibility
  evidence, with at least one retained real-client generation session.
- Outcome-first README, genuine showcase material, synchronized GitHub/PyPI/MCP
  Registry metadata, release notes, and prepared directory listings.
- Existing model-free verification, packaging, evidence, and repository
  truthfulness gates.

### Experimental but retained

The `sdxl-two-stage-copy-subject` workflow, layout validation, mask checks,
protected-pixel checks, recovery behavior, tests, and negative evidence remain
in the repository. The route is not part of the golden path, is not
automatically selected without its exact layout requirements, and is described
only as experimental. Its technically successful but visually rejected run is
not a demo, candidate, release blocker, or quality claim.

### Non-goals

- Repairing or redesigning two-stage visual quality during this milestone.
- Adding MCP tools, broad workflow authoring, a ComfyUI graph editor, or a web
  application.
- Downloading or installing new models, LoRAs, runtimes, or ComfyUI nodes.
- Completing the full 9-root plus 3-revision visual acceptance matrix before
  the preview release.
- Claiming measured latency, VRAM savings, concurrency, production readiness,
  superior model quality, model training, or a custom diffusion algorithm.
- Publishing, pushing, tagging, uploading to PyPI or MCP Registry, or
  contacting third-party directory maintainers without separate authority.

## Architecture And Ownership

### Stable MCP core

The fifteen-tool MCP surface remains unchanged. Existing protocol, schema,
backend, run-store, trust, evidence, and finalization boundaries are reused.
Implementation changes in these modules are allowed only when the installed
golden path exposes a reproducible blocker. No architecture refactor is
performed for presentation alone.

### Installation surface

The installed package owns these user-facing commands:

```text
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
uvx local-gpu-imagegen setup claude-code --apply
uvx local-gpu-imagegen doctor
uvx local-gpu-imagegen serve
```

Without `--apply`, setup remains read-only. With `--apply`, it invokes the
official client command rather than writing client configuration directly.

### Golden workflow

```text
installed CLI and stdio verification
  -> official client setup
  -> local backend readiness
  -> bounded existing-model discovery
  -> exact trust and route display
  -> later user confirmation
  -> ordinary txt2img run
  -> retained original-resolution PNG
  -> structured review
  -> byte-bound candidate display
  -> later user confirmation
  -> finalization
  -> validated public evidence export
```

The golden workflow uses an ordinary, already supported route. It does not
request a regional or two-stage layout and has no fallback to one.

The initial public-demo candidate is the already installed official SDXL 1.0
Base checkpoint through the ordinary `sdxl-txt2img` ComfyUI workflow. The
implementation must rediscover and display the exact current cryptographic
model, endpoint, workflow, component, compiler, and route identities before
requesting GPU authority. Identity drift or an unavailable ordinary route
stops the gate; it never substitutes another model or workflow.

### Evidence surface

The public golden demo binds:

- installed package version and exact wheel identity;
- client and MCP protocol/tool-call record;
- backend, route, model identity, workflow, compiler, prompt, seed, dimensions,
  and budget;
- retained PNG path, byte size, dimensions, MIME type, and SHA-256;
- original-resolution visual checks, scores, constraint results, critique, and
  hard failures;
- byte-bound candidate and later finalization confirmation;
- final public artifact and validation result;
- explicit limitations and public-rights authority.

Existing validators and showcase builders consume this retained evidence.
README material must be derived from validated public evidence rather than
manually reinterpreting a private or rejected run.

### Release surface

The README, CHANGELOG, release checklist, GitHub listing, directory listings,
package metadata, plugin metadata, `server.json`, PyPI record, MCP Registry
record, and release notes must describe the same version, tool count, supported
backends, golden path, and limitations.

## Failure And Recovery Policy

- If an ordinary route cannot produce a visually eligible public demo within
  its separately approved bounded GPU plan, stop and diagnose that route.
  Do not expand into two-stage repair, a new model, or a download.
- If a clean environment cannot install and launch the exact candidate without
  a source clone, installation is the release blocker.
- If Codex or Claude Code setup would require direct configuration-file
  mutation, retain the official-command boundary and fail the gate.
- If a public claim cannot be traced to retained evidence, remove or narrow the
  claim before release.
- If any required model-free test, JSON parse, repository hygiene check,
  packaging check, client check, evidence validator, CI job, or link check
  fails, the release remains blocked.
- If a step requires a model or dependency download, shared-Python mutation,
  remote push, tag, publication, Registry submission, or maintainer contact,
  stop and request the corresponding authority.
- A failure in the experimental two-stage route does not block the ordinary
  golden path. Work on that route is explicitly out of scope for this
  milestone.

## Verification Strategy

### Model-free gate

Run the repository's complete unit-test discovery, Python compilation, strict
UTF-8 JSON parsing, public-document truthfulness tests, repository-hygiene
tests, packaging tests, and `git diff --check`. Tests must not download a
model or require a GPU unless they are explicitly separated as integration
evidence.

### Installed-package gate

Build the final wheel into a new temporary directory without overwriting the
retained 0.6.1 artifact. Install it into fresh Python 3.11 and 3.12
environments, verify version 0.7.0, protocol `2024-11-05`, and exactly fifteen
tools, then exercise read-only setup and equivalent stdio launches.

### Real-client gate

Retain Codex and Claude Code installed-command setup/session evidence that
passes the public validator. At least one real client session must perform the
golden generation path and retain its genuine MCP JSON result and image.

### Visual gate

The required golden demo must receive original-resolution inspection and all
applicable structured checks. A failed or uncertain required check cannot
produce a candidate. The Agent must display the exact retained image hash and
wait for a later user message before finalization.

### Publication gate

Four Windows/Linux and Python 3.11/3.12 CI jobs must pass at the exact release
commit. The exact verified wheel must become the PyPI artifact, Registry
metadata must resolve to that package, the release tag must point to that
commit, and public URLs must resolve. Each remote mutation remains separately
authorized.

## Acceptance Criteria

The implementation milestone is ready to request publication authority only
when all of the following are true:

1. The final model-free and installed-package gates pass at one exact commit.
2. The installed CLI path works without a source clone or personal path.
3. Codex and Claude Code compatibility evidence validates.
4. At least one genuine public-rights golden demo is visually eligible,
   finalized by a later byte-bound user confirmation, and exported through the
   public validator.
5. The README first viewport leads with the literal product and offer, includes
   a genuine result, and exposes the shortest install path.
6. Simulated protocol material remains clearly labeled and secondary.
7. Two-stage composition is labeled experimental and absent from headline
   quality claims and release blockers.
8. All public metadata and release materials agree on version, capabilities,
   evidence, and limitations.
9. No private artifact, credential, trust state, model weight, personal
   absolute path, or rejected image is staged for publication.
10. Push, tag, PyPI, Registry, directory submissions, and release publication
    have not occurred without their explicit approvals.

## Primary Files

Expected productization work is concentrated in:

- `README.md`
- `CHANGELOG.md`
- `docs/demo/`
- `docs/release-checklist.md`
- `docs/github-listing.md`
- `docs/directory-listings.md`
- packaging, CLI, client verification, evidence export, and their tests only
  when the golden path reveals a concrete defect

Unrelated refactors are excluded.

## Delivery Sequence

1. Align public positioning and experimental-feature boundaries.
2. Verify and repair only concrete installed golden-path blockers.
3. Prepare a bounded ordinary-route GPU plan and request exact authority.
4. Generate, inspect, review, confirm, finalize, and export the genuine demo.
5. Build the outcome-first README and synchronized release materials from that
   evidence.
6. Re-run the complete local and installed-package gates.
7. Request separate remote-publication authorities in release order.
8. Observe public adoption before selecting the next capability investment.

The exact demo brief, negative prompt, seed, dimensions, sampling settings,
successful-round budget, and route token are deliberately authority-bound
runtime decisions. They are not granted by this design. A later implementation
step must present one bounded plan with explicit stop conditions and wait for a
new user confirmation before creating a run or submitting a GPU job.

## Post-Release Decision Points

- At 7 days, prioritize installation blockers and repeated user confusion.
- At 30 days, fewer than 50 Stars directs work toward first-run clarity, demo
  quality, and distribution rather than more control-plane features.
- At 90 days, 100 to 300 Stars indicates useful adoption and is sufficient to
  choose between a two-stage 0.8 milestone, reusable asset templates, or wider
  existing-model support from observed demand.
- The 800-Star target is pursued through multiple truthful release waves. It is
  not promised by 0.7.0 and does not weaken release evidence requirements.

## Reasoning And Cost Staging

- Product boundary, evidence policy, architecture changes, and irreversible
  release decisions use `xhigh`.
- After this spec and the implementation plan are frozen, coding, tests, and
  bounded local GPU verification normally use `high`.
- CI, packaging, metadata synchronization, and mechanical documentation
  normally use `medium`.
- Any new architecture conflict, evidence-integrity failure, or safety-boundary
  failure returns to `xhigh`.
- After the written spec and implementation plan are frozen, update
  `PROJECT_NODES.md` and `NEXT_SESSION.md` and recommend a new task before
  implementation when the current conversation is long. The new task must
  start by reading those files and the exact spec and plan.

## Resolved Decisions

- The 0.7.0 preview follows the core-first release approach.
- Two-stage composition is retained as experimental and is not repaired in
  this milestone.
- One genuine public-rights golden demo is required; a three-Profile gallery is
  desirable but not blocking.
- Complete 9+3 visual acceptance remains post-preview work.
- Reliability constraints remain intact while messaging becomes
  outcome-first.
- Publication remains separately gated from implementation readiness.
