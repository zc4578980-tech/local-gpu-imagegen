# Agent Runner Launch Repositioning Design

**Date:** 2026-07-26
**Branch:** `codex/v081-agent-runner-launch`
**Status:** Approved by the user

## Objective

Reposition Local GPU Imagegen around the value already demonstrated by the
repository: running existing local ComfyUI workflows from Codex or Claude Code
with explicit identity, confirmation, recovery, and evidence. Keep image quality
control as a narrow supporting track without presenting the built-in prompt
workflow as a quality enhancer.

The launch target is 50 Stars in the first 30 days. This is a measurement goal,
not a guarantee or publication gate. The implementation must maximize first-run
clarity and truthful conversion rather than add another image engine.

## Product Position

The literal offer is:

> Run the ComfyUI API workflows you already trust from Codex or Claude Code,
> locally, reproducibly, and without silent downloads or model switches.

The safe workflow onboarding path supports ordinary ComfyUI API-format
`txt2img` graphs with either a single checkpoint or reviewed split-model
topology. It does not support arbitrary custom nodes, UI-format graphs, img2img,
inpaint, regional onboarding, or two-stage onboarding. Public copy must say
"supported API workflows" or "ordinary API workflows", never "any workflow".

## Existing Proof

The launch reuses two distinct retained evidence classes:

1. A real installed Codex onboarding session inspected and registered an
   ordinary ComfyUI API workflow, then bound its model components through the
   explicit trust flow without submitting a prompt or using the GPU.
2. A separate real Codex session generated and finalized one SDXL image through
   the ordinary reviewed route with retained hashes, review, rights, and known
   limitations.

These proofs may appear together only when their separation is explicit. The
repository must not imply that the onboarding session generated the retained
image or that workflow onboarding improves image quality.

## Launch Experience

The first README viewport must contain:

- the literal BYOW offer;
- the two installed commands for verification and Codex setup;
- a direct quickstart link;
- the existing validated image or a preview bound to that image;
- one sentence stating that users provide the backend, model, and workflow;
- no quality-superiority claim.

The quickstart must lead with ComfyUI API-format export and safe onboarding.
The existing profile-driven image request remains available as a secondary
path. The onboarding sequence is discovery, inspection, displayed hashes and
bindings, later exact registration confirmation, separate model trust, route
confirmation, and then a bounded run.

## Quality Track

Quality work receives at most 20 percent of this launch cut. It adds no model,
sampler, custom node, dependency, GPU run, or production image-processing code.
It records and enforces an Agent-level semantic-fidelity rule:

- a visually cleaner output that changes the requested product medium, subject,
  or practical use is a failed constraint, not an improvement;
- baked text, malformed UI, unusable safe areas, severe anatomy defects, and
  semantic substitution prevent finalization;
- model quality limits remain separate from workflow regression;
- quality claims require a future same-model, same-settings, paired no-regression
  gate and explicit user visual authority.

The frozen 2026-07-26 gate remains negative evidence. Anime improved modestly,
frontend reduced visible defects but substituted a software product with a
generic physical-workspace interpretation, and presentation regressed. The
overall result remains `FAIL_WORKFLOW_REGRESSION`.

## Public Metadata

README, package metadata, MCP server metadata, plugin metadata, GitHub listing,
quickstart, demo index, changelog, and social preview must describe one coherent
offer. Metadata may identify ComfyUI as the primary BYOW route while retaining
AUTOMATIC1111/Forge and Diffusers as compatibility paths.

The social preview remains bound to the retained public image bytes. Its copy
changes to the Agent-to-ComfyUI workflow offer; it must not claim that the image
came from the imported-workflow onboarding session.

## Distribution Boundary

This work prepares local release assets only. It does not push, merge, publish
to PyPI or MCP Registry, create a GitHub Release, update remote repository
metadata, post to communities, tag, or mutate an external service. Every remote
action still requires separate authority.

Normal commits and meaningful releases do not reset GitHub traffic. The launch
must not delete/recreate the repository, rewrite remote history, manufacture
empty releases, or change positioning during the first campaign.

## Engineering Limits

- Work only in `.worktrees/v081-agent-runner-launch` on
  `codex/v081-agent-runner-launch`.
- Add no production module, dependency, model, custom node, or GPU submission.
- Prefer zero production Python changes; production code requires a failing
  first-run test proving a launch blocker.
- Keep regional and two-stage workflows byte-untouched and unstaged.
- Preserve local trust, client configuration, backend, model, and remote state.
- Reuse retained public evidence; do not manufacture or recombine evidence.
- Keep the 17-tool MCP surface and version 0.8.0 unchanged.
- Run the focused documentation tests after each task and all 797 tests before
  branch completion.

## Success Criteria

- A new visitor can explain the product from the first README viewport.
- A ComfyUI user can find the API-format export and onboarding sequence without
  reading architecture documentation.
- Codex and Claude Code installation commands remain visible and reversible.
- Public metadata describes the same supported-workflow offer.
- The semantic-fidelity rule prevents the Fieldnote-style substitution from
  being described as a quality win.
- Existing truthfulness, evidence, client, packaging, and workflow tests pass.
- No production code, GPU, trust/client state, or remote state changes.
