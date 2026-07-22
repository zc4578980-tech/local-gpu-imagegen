# v0.6.1 Launch Readiness Design

**Status:** Approved approach; written specification awaiting user review
**Date:** 2026-07-22
**Target:** A defensible preview release with the evidence and distribution needed to pursue 800+ GitHub stars. Star count is a market outcome, not a release claim or guarantee.

## 1. Objective

Release `v0.6.1` as an installable, agent-native control plane for local image generation. The release must prove five launch items at their original market-facing standard:

1. legal and repository hygiene;
2. low-friction installation and guided client setup;
3. a genuine local-GPU generation and immutable hot-revision demo;
4. retained real sessions from two named MCP clients;
5. release and distribution packaging backed by green public CI.

The existing public `v0.6.0` tag remains an unreleased candidate. It is not moved or presented as the launch release.

## 2. Non-Goals

- Do not complete the full 9+3 public acceptance matrix for this preview.
- Do not add a frontend panel, model training, automatic segmentation, or a new backend.
- Do not download or silently switch image models.
- Do not change shared/global Python or `<local-ai-root>\envs\pytorch-vla`.
- Do not claim that the control plane improves the underlying model's visual intelligence.
- Do not guarantee stars, production readiness, latency, concurrency, or VRAM behavior.

## 3. Release Evidence Matrix

| Launch item | Completion evidence | Evidence that does not count |
|---|---|---|
| Legal and repository hygiene | MIT license, public-safe tracked tree, contribution templates, path/credential scan, exact release provenance | A local clean status alone |
| Install and setup | Clean Windows and Linux installs; `uvx`/PyPI command after publication; guided Codex and Claude Code setup; installed server exposes 15 tools | Clone-only instructions or config text that was never used by a host |
| Genuine demo | Public-rights SDXL bytes, root and immutable child manifests, before/after PNGs, structured review, preserve/change results, sanitized real transcript, short visual demo | The existing simulated protocol GIF |
| Two named clients | One retained Codex CLI session and one retained Claude Code session, each launching the installed MCP server and making a real tool call | Parsing TOML/JSON or launching an equivalent subprocess outside the named client |
| Release and distribution | Four green GitHub Actions jobs, wheel and hashes, GitHub prerelease, topics, PyPI package, valid MCP Registry metadata, directory submission artifacts | A local wheel or unsubmitted listing copy |

## 4. Architecture

The standard-library MCP core and fifteen-tool surface remain unchanged. Launch work adds only thin release-facing layers:

```text
uvx / installed CLI
  -> setup planner
     -> official Codex or Claude Code MCP configuration command
  -> local-gpu-imagegen serve
     -> existing stdio MCP server (15 tools)
     -> existing discovery, trust, run, review, revision, and finalization services

real demo
  -> installed client session
  -> public-candidate SDXL / reviewed ComfyUI workflow
  -> root run + reviewed parent PNG
  -> immutable prompt-refine child run
  -> reviewed/finalized revised PNG
  -> sanitized public manifest and visual demo
```

Private trust state, endpoints, absolute paths, failed runs, and unapproved model outputs never enter public artifacts.

## 5. Low-Friction Install And Setup

### 5.1 CLI surface

Add `setup` beside `serve`, `doctor`, `verify`, and `config`.

```text
local-gpu-imagegen setup codex [--apply]
local-gpu-imagegen setup claude-code [--apply]
```

Default behavior is read-only. It reports:

- detected client and version;
- exact MCP server command and arguments;
- backend readiness without loading a model;
- the mutation that `--apply` would request;
- recovery/removal command.

`--apply` is explicit authorization to call the named client's official `mcp add` command. The project does not edit client configuration files directly, does not inject credentials, and does not hide the resulting command. Re-running setup must be idempotent or return an actionable existing-entry result.

### 5.2 Installation paths

Before PyPI publication, acceptance uses the built wheel in an isolated Python 3.12 environment. The public release path is:

```shell
uvx local-gpu-imagegen verify
uvx local-gpu-imagegen setup codex --apply
```

PyPI publication is required before these commands and official MCP Registry publication are claimed. A Git-tag URL remains a documented fallback, not the primary first-run path.

## 6. Public Genuine Demo

### 6.1 Subject and route

Use the already authorized official SDXL 1.0 Base ComfyUI route. The main case is a non-human, text-free, 16:9 UI hero / presentation background. It must include a useful composition-safe area and an observable visual motif that can be preserved across revision.

The exact route, prompt compiler, dimensions, successful-round budgets, download policy, seed policy, and upscale policy are displayed again immediately before generation. A new user confirmation is still required by the shipped Skill.

### 6.2 Demonstrated workflow

1. A real named client turns the natural-language request into one confirmed route.
2. The root run generates at most two successful rounds and receives a full-resolution structured review.
3. The selected parent records what must remain: composition, primary motif, and safe area.
4. An immutable `prompt-refine` child changes only the approved palette/lighting direction, with at most two successful rounds.
5. Preservation results and all required non-human visual checks are recorded.
6. A candidate is shown with its byte-bound finalization token. Only a later user message may finalize it.

### 6.3 Public artifacts

Create a public-safe showcase under `docs/demo/real/`:

- `before.png` and `after.png` from the retained model bytes;
- bounded web previews;
- `showcase.gif` or `showcase.webp` showing the real before/after and actual control steps;
- `showcase-manifest.json` with model source, license, workflow/bundle hashes, image hashes, run lineage, client/version, and explicit limitations;
- `transcript.md` containing only sanitized observable events and tool results, never hidden reasoning;
- `README.md` explaining reproduction and the difference from the simulated protocol demo.

Generated-output rights and exact component authority must remain valid at export time. A visually failed or uncertain result is retained privately and never promoted to the README.

## 7. Named Client Acceptance

Use installed release-candidate bytes, not source-path substitution.

### Codex CLI

- Record version `0.144.5` or the actual version at execution.
- Launch a fresh, non-persistent session with only the release-candidate MCP config.
- Require a real call to `local_gpu_imagegen_check` and at least one run-lifecycle tool.
- Prefer Codex as the client that drives the genuine demo.

### Claude Code

- Record version `2.1.195` or the actual version at execution.
- Use `--mcp-config` plus `--strict-mcp-config` in a fresh non-persistent session.
- Cap paid model spend for the acceptance prompt and make no unrelated tool calls.
- Require a real call to the installed MCP server and retrieval of the retained run or profile catalog.

Each public acceptance record includes host name/version, server version, protocol version, exact tool called, sanitized JSON result, start/end time, and artifact hash. It explicitly excludes prompts, account identifiers, tokens, machine paths, and unrelated client configuration.

## 8. CI And Packaging

The current public failure is reproduced: a clean runner has `pip` but lacks the declared `setuptools` build backend while the packaging test disables build isolation.

Fix the workflow by installing the declared build requirement before tests. Add a regression test that checks the public CI workflow performs build-backend setup before the packaging suite. Do not skip the installed-wheel test.

Required matrix:

- Windows latest / Python 3.11;
- Windows latest / Python 3.12;
- Ubuntu latest / Python 3.11;
- Ubuntu latest / Python 3.12.

Every job compiles sources, runs the full model-free suite, builds and installs the wheel outside the checkout, verifies exactly fifteen tools, and validates named-client configuration artifacts. The release gate waits for all four public jobs to be green.

## 9. Release And Distribution

### Repository release

- Bump package, MCP, plugin, docs, and tests to `0.6.1`.
- Keep the public `v0.6.0` tag unchanged and unreleased.
- Publish an annotated `v0.6.1` tag only after public CI is green.
- Attach the wheel, SHA-256 file, genuine demo assets, limitations, and install commands to a GitHub prerelease.
- Apply the approved description and eight repository topics.

### PyPI and official MCP Registry

The official MCP Registry hosts metadata, not Python artifacts. Therefore:

1. publish `local-gpu-imagegen==0.6.1` to PyPI using a user-authorized account or trusted publisher;
2. include the required `mcp-name` ownership marker in the package README;
3. add a schema-valid `server.json` using the current `2025-12-11` schema and `io.github.zc4578980-tech/local-gpu-imagegen` namespace;
4. validate with the official `mcp-publisher`;
5. authenticate with GitHub and publish only after explicit external-publication approval;
6. verify the live Registry API result.

### Directories

- Prepare the alphabetized one-line entry and PR body for `punkpeye/awesome-mcp-servers`.
- Prepare the Glama Add Server fields and verify any automatic listing after official Registry publication.
- Do not open third-party PRs, contact maintainers, or submit forms until the user approves the final exact public text and target.

## 10. Failure Handling

- Any red public CI job blocks the release.
- Missing PyPI or Registry authority blocks those distribution claims but does not silently fall back to a fake listing.
- A named client that merely sees configuration but does not call the server fails acceptance.
- A model run that lacks public output authority, full-resolution review, or preservation evidence cannot become the showcase.
- Network or backend failures do not consume successful-round budget and do not authorize a route switch.
- The simulated demo remains clearly labeled and moves below the genuine showcase in the README.

## 11. Test Strategy

Implementation follows test-first changes:

1. CI regression test fails against the missing build-backend setup, then passes after workflow repair.
2. CLI tests define read-only setup plans, explicit apply behavior, idempotency, unsupported clients, missing executables, and subprocess failures.
3. Packaging tests prove `setup` is present in an installed wheel and all immutable assets resolve outside the checkout.
4. Client-evidence tests reject config-only records, private values, mismatched server/tool versions, and missing real tool results.
5. Demo-evidence tests reject simulated images, missing model/workflow hashes, broken lineage, unreviewed outputs, and private paths.
6. Public documentation tests require the genuine demo and retain every limitation.
7. Final verification repeats the full suite, clean install, compilation, JSON parsing, secret/path scan, demo hash checks, client evidence validation, and `git diff --check`.

## 12. Completion Rule

The five items are complete only when all evidence in Section 3 exists and validates. Local tests, honest disclaimers, or prepared copy cannot substitute for missing public CI, real image bytes, named-client tool calls, or live distribution state.
