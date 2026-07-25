# GitHub Conversion Release-Gate Design

> **Status:** Superseded on 2026-07-25 by
> [`2026-07-25-post-release-star-measurement-design.md`](2026-07-25-post-release-star-measurement-design.md).
> The 100-Star objective is now a post-release 30-day net-new goal, not a pre-release publication gate. The text below is retained as historical
> planning context and must not be applied as current release policy.

**Date:** 2026-07-24

**Status:** Approved

**Branch:** `feature/v061-launch-readiness`

**Parent design:** `2026-07-24-800-star-release-mainline-design.md`

## Decision

Adopt a conversion-first close for `0.7.0`. The repository itself must be able
to explain, prove, and convert the product even when external video promotion
delivers no traffic. Bilibili, Douyin, and other creator distribution remain
useful upside, but they contribute zero guaranteed reach to the pessimistic
release forecast unless later evidence establishes a defensible floor.

The user-added publication rule is binding:

> 悲观状态下至少要有首月100星的成绩才允许发布。

For planning, "pessimistic" means a documented conservative scenario, similar
to a lower-quartile planning case, rather than a mathematical worst case. The
scenario must still estimate at least 100 GitHub Stars in the first 30 days.
Midpoint or upside estimates do not pass. No Star count is guaranteed or
presented as a product claim.

## Evidence Baseline

The approved parent design already establishes the positioning brief:

- **User:** a developer or technical creator who already runs ComfyUI,
  AUTOMATIC1111/Forge, or a local Diffusers environment.
- **Offer:** connect Codex or Claude Code to that existing image stack through
  an installable MCP path.
- **Differentiator:** explicit model authority, no silent downloads or route
  switches, bounded generation, durable review, and byte-bound finalization.
- **Strategic tension:** high first-run simplicity and high verifiable
  reliability.

Read-only GitHub API inspection on 2026-07-24 found that the public repository
had zero Stars, zero forks, no topics, no homepage, and Discussions disabled.
Its prepared release files already contain an outcome-first description and
eight relevant topics, but those remote metadata changes remain unapplied.

The scoped competitor set is deliberately narrower than ComfyUI or broad local
AI platforms:

- **Direct:** `artokun/comfyui-mcp`, `joenorton/comfyui-mcp-server`,
  `ATH-MaaS/Pixelle-MCP`, `iconben/z-image-studio`,
  `filliptm/ComfyUI_FL-MCP`, and `Ichigo3766/image-gen-mcp`.
- **Adjacent:** `jau123/MeiGen-AI-Design-MCP`, `shinpr/mcp-image`, and
  `zhongweili/nanobanana-mcp-server`.
- **Aspirational:** `MiniMax-AI/MiniMax-MCP` for packaging and distribution,
  not product-scope parity.

Observed current Star counts across the direct set ranged from 41 to 1,091,
with multiple projects above 100. High-visibility repositories commonly place
an image or branded visual near the top, expose a clearly labeled Quick Start,
offer a package-manager command, name supported clients, and provide an
external documentation or community path. These observations establish market
capacity and presentation patterns, not first-month causality.

GitHub's unauthenticated stargazer endpoint did not expose `starred_at`, and a
public Star History endpoint was unavailable. Therefore, no first-30-day
competitor count is recorded from this scan. A later forecast must label this
historical-data gap rather than converting current totals into launch-month
facts.

## Goal

Make the exact `0.7.0` candidate easy to understand, try, trust, and share from
the GitHub repository alone. A qualified visitor should be able to answer
these questions without reading the full architecture:

1. What does this project let my Agent do?
2. Does it reuse the backend and models I already run?
3. What are the shortest verified commands?
4. What genuine output proves the path works?
5. What safety and authority boundaries distinguish it from a thin wrapper?
6. Where do I report a first-run failure or request support?

The design improves controllable conversion factors. It does not claim that
repository presentation alone guarantees 100 Stars.

## Non-Goals

- No MCP tool, schema, generation-plan, trust, run-store, or backend change.
- No new model, dependency, runtime, ComfyUI node, or download.
- No second golden run, visual-quality repair, or experimental-route work.
- No web application or standalone documentation site.
- No public Star promise, comparative-quality claim, production-readiness
  claim, or fabricated adoption evidence.
- No remote topic, Discussions, push, tag, release, Registry, directory, or
  social-platform mutation without its later explicit authority.
- No Chinese full-README translation or video production in this first phase.
  Those remain a second-stage distribution layer after the repository converts
  on its own.

## Conversion Architecture

### 1. Evidence-first README viewport

After the existing golden candidate is separately finalized and its public
export validates, the README first viewport will use this order:

1. Literal product name and outcome-first promise.
2. Genuine finalized ordinary-route image, sourced from
   `docs/demo/real/final.png`.
3. Shortest installed verification and Codex setup commands.
4. One literal natural-language request a user can give the Agent.
5. One compact boundary statement: existing backend required, no bundled
   model, no silent download or model switch.

The genuine image must appear before the simulated protocol GIF. The README
must not show a private, reviewed-only, rejected, transformed, or unvalidated
artifact. Until Task 11 export succeeds, the current pending-evidence wording
stays in place.

### 2. Five-minute first-run path

Create a compact `docs/quickstart.md` for the target user who already has a
supported backend. It will contain:

- explicit prerequisites and the supported Python versions;
- installed `verify`, client `setup --apply`, and `doctor` commands;
- the required client restart/reload boundary;
- one readiness checkpoint after each state transition;
- a minimal existing-model discovery/trust/generation outline without copying
  a private route or promising automatic model selection;
- the exact rollback/removal command for each client setup path;
- links to focused troubleshooting rather than duplicating the full reference.

"Five-minute" describes the documentation path for a user whose backend and
model are already running. It does not include installing ComfyUI, downloading
weights, or generating on unusually slow hardware. If this bounded path cannot
be verified from the installed candidate, remove the time label and keep the
release gate blocked.

### 3. Trust proof after the first run

The reliability controls remain prominent but move after the shortest path.
The first explanatory section will summarize:

- discovery does not load model weights;
- trust and route identities are explicit;
- successful-round budgets are bounded;
- review uses the original-resolution artifact;
- finalization is bound to exact image bytes;
- runs retain recoverable state.

Detailed tool and evidence references stay available below. Reliability is the
reason to choose the project, not a wall a new visitor must cross before seeing
the product.

### 4. Shareable repository visual

Prepare one 1280x640 GitHub social-preview candidate only from the validated
public demo image and repository-owned text. It will show:

- `Local GPU Imagegen`;
- the literal existing-backend promise in a short form;
- the genuine final image without misrepresenting it as a UI screenshot;
- `Codex + Claude Code` and `ComfyUI / Forge / Diffusers` as compact support
  signals.

The asset must be readable at thumbnail size, contain no personal path or
private evidence, and preserve the source image's aspect without distortion.
Creating the file does not authorize uploading it as remote repository
metadata. If the final image is not exported, the preview is not built.

### 5. GitHub conversion metadata

Keep the prepared repository description outcome-first. At the separately
authorized remote-metadata gate, apply the already prepared topics:

`mcp-server`, `local-ai`, `image-generation`, `comfyui`, `automatic1111`,
`stable-diffusion`, `agent-tools`, and `python`.

Enable Discussions only at that same explicit remote gate. Discussions will
handle setup experiences, backend recipes, and show-and-tell; Issues remain for
reproducible defects and feature requests. README calls to action will ask
visitors to try the verified path, report first-run blockers, and Star the
repository only if it is useful. They will not pressure users or imply that a
Star is required for support.

## Benchmark And Forecast Method

The benchmark reports dimensions separately rather than hiding trade-offs in
one score:

1. positioning clarity;
2. first-viewport visual proof;
3. shortest install path;
4. client and backend legibility;
5. evidence and claim discipline;
6. documentation and troubleshooting depth;
7. community and distribution surfaces;
8. repository freshness and maintainer responsiveness;
9. the two strategic-tension poles, first-run simplicity and verifiable
   reliability, scored separately.

The pre-release forecast will include three scenarios:

- **Pessimistic:** conservative qualified exposure and conversion assumptions,
  with unproven video reach set to zero.
- **Base:** planned GitHub, Registry, directory, and creator distribution with
  ordinary conversion assumptions.
- **Upside:** one or more external communities or videos materially amplifies
  discovery.

Every nonzero exposure input requires a named, available channel and a reason
it should deliver that floor. Every conversion input must cite the scoped
benchmark or an observed pre-launch signal. Unknown inputs remain zero or are
shown as unresolved. The formal release may be requested only when the
pessimistic 30-day estimate is at least 100 Stars and all parent-design
technical and authority gates also pass.

## Data Flow

```text
eligible reviewed candidate
  -> later exact finalization token
  -> byte-identical final.png
  -> separately authorized public evidence export
  -> validated showcase manifest and client records
  -> README genuine-result block + quickstart + social-preview candidate
  -> public-doc, evidence, packaging, and repository-hygiene tests
  -> scoped benchmark + three-scenario forecast
  -> pessimistic scenario >= 100
  -> request remote publication authorities
```

No later stage may synthesize facts that the previous retained artifact does
not establish.

## Files

Expected tracked changes are limited to:

- `README.md`
- `docs/quickstart.md`
- `docs/github-listing.md`
- `docs/release-checklist.md`
- `docs/demo/real/` only through the existing authorized export flow
- one repository-owned social-preview source/output path selected in the
  implementation plan
- `tests/test_public_docs.py`
- focused asset or link tests only when needed for deterministic verification

Benchmark data, forecast assumptions, and private launch planning belong in
ignored continuity or a user-facing output report, not in package metadata or
README marketing claims.

## Verification

### Deterministic document checks

Tests will require, when validated real evidence exists:

- the genuine image before the simulated GIF;
- the exact validated image SHA-256 and ordinary workflow ID;
- installed verification and client setup commands in the first viewport;
- one literal natural-language generation request;
- a local link to the five-minute first-run document;
- the existing-backend and no-silent-download/switch boundary;
- no guaranteed Star, quality, speed, VRAM, concurrency, or production claim.

### Quickstart checks

The installed candidate must verify outside the source checkout. The setup
dry-run remains read-only; `--apply` delegates to the official client command.
The document must name restart/reload and rollback steps and must not include a
personal absolute path, private model identity, endpoint, or generated token.

### Visual asset checks

The social-preview candidate must be exactly 1280x640, structurally valid, and
derived only from the validated public final image plus repository-owned text.
Its source and output hashes are recorded locally. A human inspects it at full
size and thumbnail scale before any upload request.

### Existing release gates

Run the parent plan's full public-document, evidence, client-session,
packaging, compilation, unit-test, JSON, hygiene, and `git diff --check` gates.
This addendum cannot weaken or replace them.

## Failure Policy

- If the golden candidate is not exactly finalized, retain pending README copy
  and do not build the social preview.
- If public export is not authorized or does not validate, do not copy the
  image or derive claims from private evidence.
- If the five-minute path cannot be reproduced for the stated target user,
  remove the time claim and treat onboarding as a release blocker.
- If local links, asset dimensions, evidence hashes, or public claims disagree,
  fail the document gate.
- If competitor first-month history remains unavailable, say so; do not infer
  it from current Star totals.
- If the pessimistic forecast remains below 100 or depends on unproven video
  traffic, the formal release remains blocked.
- If remote metadata or publication lacks explicit authority, stop after
  preparing local materials.

## Delivery Order

1. Complete the existing byte-bound finalization gate after the exact user
   token.
2. Complete the existing separately authorized demo export and named-client
   evidence gates.
3. Add deterministic tests for the conversion contract.
4. Implement the evidence-first README and five-minute first-run document.
5. Build and inspect the social-preview candidate from public evidence.
6. Run the complete local release gate at one exact commit.
7. Produce the evidence-backed competitor benchmark and three-scenario
   forecast.
8. Request publication authority only if the pessimistic estimate is at least
   100 Stars.
9. Treat Chinese Quickstart and creator-video assets as the next distribution
   layer; their uncertain traffic is upside, not release-gate evidence.

## Resolved Decisions

- GitHub conversion is the first optimization layer; creator distribution is
  second.
- Use the conversion-first close rather than a minimal patch or a full docs
  site/community build.
- Keep MCP architecture and the approved golden workflow unchanged.
- Use only validated real evidence in the first viewport and social preview.
- Keep the public promise outcome-first and the trust controls immediately
  after the shortest path.
- Require a conservative first-month forecast of at least 100 Stars before
  formal release while never guaranteeing that outcome publicly.
