# Codex-First Workflow Runner Design

**Date:** 2026-07-27

**Status:** Approved by the user; planning-audit correction recorded below

**Branch:** `codex/codex-first-workflow-runner`

**Baseline:** `main@3fb45163ec61189c2d2c89a7c183612a55cb6058`

## Planning-Audit Correction

The implementation-plan audit found that the legacy raw-path branch in
`mcp_server._registered_workflow_binding` calls
`WorkflowTemplateRegistry.register_import`. That helper persists an imported
workflow, so the current branch is not actually read-only even when the trust
action is `inspect_workflow_binding`.

The approved behavior remains unchanged: everything before the preparation
decision must be read-only. The implementation must first add an in-memory
preparation path owned by `workflow_onboarding.py` and make raw-path trust
inspection consume that prepared document without storing it. A focused test
must prove that no workflow state directory exists after the inspection. The
later approved `local_gpu_register_workflow` call remains the first workflow
write.

The initial correction remained inside two production owners. On 2026-07-27,
the Task 3 route test proved that `ModelCatalog` validated every workflow as a
shipped template, which made registered imported workflows unroutable. After
the required design stop, the user approved one bounded third-owner change in
`model_catalog.py`. It adds no tool, module, dependency, state, or user
decision and remains inside the approximately 150-line production ceiling.

On 2026-07-28, the user approved
`scripts/local_gpu_imagegen/backends/comfyui.py` as the fourth production
owner after the stopped pre-acceptance live attempt exposed the empty-negative
default mismatch. The correction is net `+4` production lines; the combined
production net is `113`, still within the approximate `75-150` ceiling.

## Objective

Turn the existing safe ComfyUI workflow-onboarding capability into a narrow,
credible first-run product for Codex users:

> Run a supported ComfyUI workflow from Codex without modifying your setup.

The launch path serves users who already have Codex, a running local ComfyUI,
an installed model, and one supported ComfyUI API-format `txt2img` workflow. It
optimizes for quick setup, workflow fidelity, reliability, and recovery. Safety
and reproducibility remain enforced underneath the experience, but they are
evidence for the product promise rather than the headline product category.

This milestone does not continue Adaptive Quality work. It does not compete on
workflow editing, model installation, custom-node management, or diffusion
quality.

## Market Decision

The broad "ComfyUI plus MCP" category is already occupied. The decision is not
to build another general ComfyUI control plane.

The verified direct set on 2026-07-27 includes:

- [`artokun/comfyui-mcp`](https://github.com/artokun/comfyui-mcp), a broad
  Codex-capable control plane with workflow execution, model management,
  generation tracking, and workflow locks;
- [`joenorton/comfyui-mcp-server`](https://github.com/joenorton/comfyui-mcp-server),
  a lightweight local bridge with custom workflow discovery and asset
  provenance; and
- [`filliptm/ComfyUI_FL-MCP`](https://github.com/filliptm/ComfyUI_FL-MCP), a
  ComfyUI-integrated panel with Codex support, live graph editing, approvals,
  and safety gates.

Adjacent products include
[`ATH-MaaS/Pixelle-MCP`](https://github.com/ATH-MaaS/Pixelle-MCP) and
[`jau123/MeiGen-AI-Design-MCP`](https://github.com/jau123/MeiGen-AI-Design-MCP).
They validate demand for workflow-to-tool and multi-backend image generation,
but they are not the product shape selected here.

A bounded review of 20 relevant competitor issues found 13 opened by external
users. The dominant problems were installation, connection, Windows stability,
workflow/model compatibility, and long-running operation feedback. Explicit
demand for a security product was weak. This evidence is directional rather
than a market census, but it is sufficient to reject security-first
positioning.

The selected competitive reference is the lightweight runner, not the broad
control plane. Local GPU Imagegen must be easier to understand than its current
17-tool internal workflow while remaining more deterministic and recoverable
than a thin relay.

## Product Position

The first public viewport will use this literal offer:

> Run a supported ComfyUI workflow from Codex without modifying your setup.

Supporting copy may state:

> Your ComfyUI, model, and API workflow stay in control. Local GPU Imagegen
> does not silently download a model, switch the route, or edit the graph.

Public copy must use "supported ComfyUI API workflow" or "ordinary `txt2img`
API workflow." It must never say "any workflow," "arbitrary workflow," "secure
ComfyUI," "production ready," or "better image quality."

## Audience And Preconditions

The golden path is for a user who has:

- Python 3.11 or 3.12;
- Codex installed and authenticated;
- a reachable local ComfyUI instance;
- all required model components already installed; and
- an exported API-format JSON workflow within the supported topology set.

Backend installation, model download, custom-node installation, and ComfyUI UI
automation are not first-run responsibilities. The product diagnoses a missing
precondition and stops.

## Supported Scope

The existing safe workflow-onboarding contract remains authoritative:

- a bare API graph or one graph under `prompt`;
- ordinary `txt2img` only;
- one unambiguous sampler, latent source, decoder, and owned image output;
- either one `CheckpointLoaderSimple` or the reviewed split-model topology;
- only the existing imported-workflow safe-node and safe-input allowlist; and
- exact current ComfyUI inventory matches for every bound component.

The golden path explicitly excludes:

- UI-format conversion from `nodes`, `links`, and `widgets_values`;
- custom nodes or new node classes;
- `img2img`, inpainting, video, audio, regional, and two-stage onboarding;
- graph editing, repair, manual node selection, or automatic fallback;
- model, LoRA, custom-node, or runtime downloads;
- ComfyUI process control or canvas editing; and
- an image-quality improvement claim.

Unsupported input returns a structured diagnostic. It is not rewritten into a
different graph and is never sent to ComfyUI.

## Golden-Path User Experience

Setup remains one installed command:

```shell
uvx local-gpu-imagegen setup codex --apply
```

After Codex reloads the MCP server, the user supplies a path and outcome in one
request:

```text
Run this supported ComfyUI API workflow from Codex: <path>.
Use this prompt: <prompt>. Preserve every other workflow setting.
```

Codex may use several existing MCP tools internally. The user sees only two
decision points.

### Decision 1: Prepare

Codex performs API-only discovery, workflow inspection, and workflow-binding
trust inspection. All three actions are read-only. It then shows one concise
summary containing:

- source and semantic workflow hash prefixes;
- topology and owned output;
- exact backend endpoint and bound model components;
- current workflow defaults;
- the requested prompt overrides;
- the supported-scope limitations; and
- a statement that no model, node, or runtime download will occur.

The summary is backed by both the existing registration confirmation and the
existing private-trust confirmation. The user does not have to copy long hash
tokens. A later unambiguous natural-language approval of the displayed single
proposal permits the Agent to pass the exact stored confirmation values to the
two MCP calls.

After approval, Codex registers the immutable workflow and grants private trust
to the exact current workflow/component binding. Registration grants no GPU
authority, public-evidence authority, or model-download permission.

### Decision 2: Execute

Codex resolves one exact route and shows:

- backend endpoint, registered workflow, and model identity;
- positive and negative prompt values;
- width, height, seed, steps, guidance, sampler, and scheduler;
- exactly which fields differ from the imported workflow; and
- a one-successful-round budget with downloads and model switching disabled.

A later approval of this displayed route permits `local_gpu_start_run` and one
`local_gpu_generate_round`. An expired or changed route must be redisplayed and
approved again.

### Result

The first successful round returns:

- the original output image;
- a concise actual workflow/model/parameter summary;
- the durable `run_id`; and
- the existing machine-readable run evidence location.

The result is labeled `generated / unreviewed`. Review, refinement, child-run
revision, and byte-bound finalization remain available when the user asks for
them, but they do not block the first result.

## Internal Data Flow

```text
Codex setup
  -> API-only discovery
  -> local_gpu_inspect_workflow
  -> local_gpu_set_model_trust(action=inspect_workflow_binding,
       workflow_path + inferred binding)
  -> display one preparation proposal
  -> later preparation approval
  -> local_gpu_register_workflow
  -> local_gpu_set_model_trust(action=approve_private)
  -> local_gpu_recommend_models
  -> display one exact execution route
  -> later execution approval
  -> local_gpu_start_run
  -> local_gpu_get_run
  -> local_gpu_generate_round(action=initial)
  -> image + durable run evidence
```

The existing raw-path trust-inspection interface makes pre-registration trust
inspection possible. No new MCP tool or trust state is required.

## Workflow Defaults Contract

`WorkflowOnboarding.inspect` will return a bounded `workflow_defaults` object
whose values are read from the already inferred and validated binding paths:

- `positive_prompt`;
- `negative_prompt`;
- `width` and `height`;
- `seed`;
- `steps`;
- `guidance_scale` from the bound ComfyUI `cfg` value;
- `sampler_name`; and
- `scheduler`.

The values are observations of the inspected graph, not model recommendations.
Their source graph is already covered by `source_sha256`, `workflow_sha256`,
and `proposal_digest`; a changed default invalidates the prior preparation
proposal through the existing hash contract.

Codex preserves every default except a field the user explicitly overrides.
An unsupported type, missing binding target, or ambiguous current value makes
the workflow diagnostic rather than inventing a default.

The read-only trust inspection and later private approval must use the same
capability object, with its recommended generation settings derived from these
exact workflow defaults. Route recommendation must echo that frozen default
set before applying any explicit user override. The approved catalog change
uses the existing registered-workflow resolver only for `imported:` IDs while
retaining shipped inspection for standard, regional, and two-stage templates.

The MCP response schema exposes `workflow_defaults` without duplicating any
extraction or hash logic in the transport layer.

## Module Ownership

Production changes are limited to four existing owners:

- `scripts/local_gpu_imagegen/workflow_onboarding.py` extracts and returns the
  bounded defaults from authoritative inferred bindings.
- `scripts/mcp_server.py` describes the additional bounded output object and
  continues thin dispatch.
- `scripts/local_gpu_imagegen/model_catalog.py` selects the existing imported
  resolver for `imported:` IDs while preserving shipped-template validation.
- `scripts/local_gpu_imagegen/backends/comfyui.py` accepts an empty string for
  the validated ComfyUI negative-prompt default while retaining non-string
  rejection.

Non-production changes are limited to:

- `skills/local-gpu-imagegen/SKILL.md` for the two-decision Codex path;
- README and quickstart presentation;
- a dated `docs/alternatives.md` with source-linked competitive context; and
- focused tests, including `tests/test_comfyui_adapter.py`, and retained
  evidence documentation.

The discovery service, trust registry, router, engine, run store,
backend adapters, workflow templates, profiles, and 17-tool MCP surface retain
their responsibilities. No new module, dependency, tool, model, workflow, or
state store is added.

## Failure And Recovery Policy

### Before preparation approval

All activity is read-only. UI format, unsupported nodes or operations,
ambiguous paths, missing inventory, and malformed defaults return diagnostics
without a confirmation or mutation.

### During preparation

Registration and trust approval are sequential, not falsely described as an
atomic transaction. Both operations fully revalidate their inputs.

If registration succeeds and trust approval fails, the immutable registered
copy remains as an inert record with no execution authority. The Agent reports
the exact drift or missing identity and stops. It does not delete the record,
weaken identity, repeat approval, or continue to route resolution.

Any change to workflow bytes, semantic graph, component identity, or endpoint
invalidates the displayed preparation proposal and requires a fresh read-only
inspection.

### During route and execution

An expired route or any change to model, endpoint, workflow, compiler, prompts,
settings, dimensions, seed, policy, or budget invalidates the prior execution
approval. The new route must be displayed before another approval.

A backend failure is retained against the durable run without consuming a
successful round. The golden path does not automatically retry, change seed,
switch model, switch backend, use CPU, or choose another workflow. It returns
the recoverable run ID and waits for the user.

A successful but unreviewed image is not accepted, finalized, published, or
described as visually verified.

## TDD Verification Strategy

Implementation follows red-green-refactor. Model-free coverage must prove:

1. defaults are extracted for single-checkpoint and split-model imports;
2. randomized node IDs and JSON order do not change extraction;
3. public names and types match the existing generation-plan contract;
4. missing, ambiguous, boolean-as-number, or invalid defaults fail closed;
5. source-byte, semantic workflow, component, and endpoint drift invalidate
   preparation;
6. registration success plus trust failure leaves an inert registration and
   never recommends or starts a route;
7. the initial plan preserves every workflow default except explicit user
   overrides;
8. an expired or drifted displayed route cannot start a run;
9. the first path spends at most one successful round and retains backend
   failure evidence without automatic retry;
10. downloads, model switching, CPU fallback, and workflow fallback remain
    disabled;
11. MCP exposes exactly 17 tools and strict installed-package verification
    agrees; and
12. unsupported workflow families retain their current structured failures.

The focused tests cover onboarding, MCP schemas, trust binding, route/start
gates, Skill behavior, and documentation truthfulness. The repository gate is:

```text
python -m unittest discover -s tests -v
python -m compileall scripts
git diff --check
```

Frozen regional and two-stage workflow bytes and hashes must remain unchanged.
Model-free implementation starts no backend and requires no GPU.

## One-Run Real Codex Gate

The launch experience receives one separately confirmed real-client gate after
model-free implementation passes:

- one already-running local ComfyUI instance;
- one already-installed model route;
- one supported ordinary API workflow;
- one fresh Codex session and isolated task state;
- one accepted ComfyUI prompt ID and at most one successful image;
- no recovery, retry, quality comparison, download, or model switch; and
- identity-bound shutdown only for any process started by the gate.

The usability clock begins when a configured Codex session receives the path
and prompt. It ends when ComfyUI accepts the prompt. The target is at most five
minutes. Package network fetch, Codex installation/login, backend/model setup,
and image-generation latency are reported separately and are not hidden inside
the measurement.

The evidence retains the genuine MCP JSON calls/results, two user approvals,
workflow and component identities, accepted prompt ID, image hash, run state,
and timings. Private absolute paths, model licenses, images not approved for
publication, credentials, and local trust state remain private.

One successful run proves only that bounded local path. It does not prove broad
workflow compatibility, production readiness, image-quality superiority, or a
five-minute reliability distribution.

The gate requires a later exact route display and user confirmation before GPU
submission. Two consecutive infrastructure failures stop the gate. No third
attempt is authorized by this design.

## Public Repository Presentation

The first README viewport contains:

1. the literal Codex-first offer;
2. `uvx local-gpu-imagegen setup codex --apply`;
3. one ready-to-use Codex request containing a workflow path;
4. the prerequisites and supported-workflow boundary; and
5. a link to the measured real-client walkthrough when it exists.

The primary demonstration is the real Codex path from workflow request through
the returned image. A secondary trust demonstration shows that workflow-byte,
component, and endpoint drift are rejected. The trust demonstration is proof,
not the headline.

`docs/alternatives.md` records dated, source-linked alternatives rather than a
hostile feature matrix. It explains when a broad control plane, a lightweight
relay, or this bounded runner is the better fit. Volatile Star counts are not
used as permanent product claims.

No telemetry is added. External success is observed through package download
data, opt-in Issue/Discussion reports, and normal user feedback.

## Release And Star Stop-Loss

This branch prepares local release assets only. Push, merge, PyPI/MCP Registry
publication, GitHub Release creation, repository metadata mutation, community
posting, and all other remote actions remain separately authorized.

After an authorized launch and meaningful distribution:

- by day 14, continue only if the repository has at least 15 new Stars and
  three externally reported successful golden-path users;
- by day 30, continue active development only if it has at least 30 new Stars
  or five confirmable external successful users; and
- below those thresholds, move the project to maintenance or archive it rather
  than add speculative features.

If the thresholds are met, installation and compatibility failures take
priority. Custom-node support or image-quality control requires a new design
based on explicit user feedback. Neither is implied by this milestone.

The internal planning estimate of 30-70 first-month Stars under competent
distribution is not a public claim or engineering guarantee.

## Complexity And Cost Boundaries

- four existing production files at most;
- `113` combined net new production lines, within the approximately `75-150`
  ceiling;
- no new production module, dependency, MCP tool, model, workflow, profile,
  backend, state store, or generic graph abstraction;
- no quality benchmark or multi-round GPU evaluation;
- one accepted live prompt and image maximum in the later real-client gate;
  and
- two to four focused engineering days for implementation, evidence, and local
  release preparation.

Implementation stops for design review if it needs a fifth production owner or
more than about 150 net production lines, a new tool or dependency, custom-node
execution, UI-format conversion, another GPU attempt after two infrastructure
failures, or a weakened drift/confirmation boundary.

## Acceptance Criteria

1. A configured Codex user can request one supported API workflow without
   learning the 17-tool internal sequence.
2. The user sees exactly one preparation decision and one execution decision
   before the first GPU submission.
3. Workflow defaults are exact observations of the validated graph and remain
   unchanged unless the user explicitly overrides them.
4. Registration and private trust bind the same source, semantic graph,
   component identities, and endpoint shown before preparation approval.
5. Route/start/generation preserve the displayed model, endpoint, workflow,
   settings, seed, policies, and one-round budget.
6. Unsupported, ambiguous, stale, expired, or failed cases stop with a
   structured recoverable result and no silent fallback.
7. The first successful result returns an image plus durable run evidence and
   is labeled unreviewed.
8. The MCP surface remains exactly 17 tools and all model-free repository gates
   pass from the exact baseline.
9. One separately confirmed Codex/ComfyUI run retains honest timing and JSON
   evidence before a measured golden-path claim is made.
10. Public documentation leads with convenience and reliability, states the
    narrow workflow boundary, and makes no security, quality, compatibility,
    or production-readiness overclaim.

## Resolved Decisions

- Codex is the primary launch client; Claude Code compatibility remains but
  does not require equal first-release generation evidence.
- The product competes as a bounded reliable runner, not a general ComfyUI
  control plane.
- Safety is an enforced property and secondary proof, not the headline market.
- Two user decisions are acceptable; three independent registration, trust,
  and route confirmations are not the golden path.
- Existing raw-path trust inspection is reused before registration, so no new
  MCP tool is necessary.
- The user approves the displayed proposal in natural language; the Agent
  supplies exact digest-bound values to the MCP calls only after that later
  approval.
- Registration and trust are sequential and fail closed; an inert immutable
  registration may remain after a trust failure.
- Existing workflow values, not product presets, are the default starting
  point.
- One successful unreviewed image completes the first-run outcome.
- Advanced review, revision, and finalization remain available but secondary.
- Arbitrary workflows, custom nodes, UI conversion, and quality improvement are
  explicitly deferred.
- One bounded live Codex run is sufficient local launch evidence; it is not a
  broad reliability claim.
- Remote publication and distribution remain separately authorized.
