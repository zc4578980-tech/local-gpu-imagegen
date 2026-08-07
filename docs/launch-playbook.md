# First-Month Launch Playbook

`100 net-new GitHub Stars` is the minimum acceptable first-month outcome and
the planning floor, not the target. The operating target is to exceed that
floor. This threshold is not a guarantee and not a substitute for release
correctness. It is a post-release adoption goal and planning floor; it
does not block publication or replace engineering and evidence gates.

## Local Readiness

Before any remote action:

- Freeze one exact commit after the model-free suite, compilation, document
  checks, and repository hygiene pass.
- Build one exact verified wheel and install it outside the source checkout.
- Follow the [publication runbook](publication-runbook.md) and require its
  `candidate-report.json` to contain `"status": "passed"` before any remote
  action.
- Require `verify` to report version `0.9.0`, protocol `2024-11-05`, and exactly
  seventeen tools; require `doctor` to fail closed when no backend is selected.
- Keep the validated historical SDXL showcase ahead of the simulated protocol
  animation. Do not promote the two private, reviewed, ineligible current-v0.8
  runs or their fail-closed local development evidence into public evidence.
- Keep ComfyUI's role and the product boundary explicit: ComfyUI generates the
  pixels; Local GPU Imagegen controls authority, reproducibility, review, and
  recovery.
- Retain forecasts as planning evidence for channel and response-capacity
  decisions. Do not treat an unmeasured forecast as release proof or as a
  substitute for the post-release observation campaign.

## Publication Status

Each remote mutation needs separate approval unless the user explicitly bundles
named actions. For `v0.8.3`, the exact release commit passed four green CI jobs,
the exact verified wheel reached PyPI, and tag `v0.8.3` plus the public GitHub
Release were published. The official MCP Registry record is active, and the
repository description plus all eight prepared topics are applied. Remote
social-preview metadata, `awesome-mcp-servers`, and Glama remain pending.

For subsequent releases, preserve this order so every public record points to
the same verified state:

1. Push the exact release commit and require four green CI jobs across Windows,
   Ubuntu, Python 3.11, and Python 3.12.
2. Publish the exact verified wheel to PyPI without rebuilding it.
3. Publish the MCP Registry record and verify that it resolves the same PyPI
   version and stdio command.
4. Create the tag and GitHub Release with the reviewed social preview, truthful
   limitations, install commands, and rollback commands.
5. Apply repository topics and social-preview metadata.
6. Submit the prepared `awesome-mcp-servers` and Glama entries only through
   their separately approved actions.

Stop if a digest, version, CI result, package URL, Registry record, or release
copy differs from the frozen candidate. Do not silently rebuild, relabel local
development evidence, or substitute another model or image.

## Conversion Assets

Use one consistent outcome-first message:

> Run a supported ComfyUI workflow from Codex through cryptographic model
> identity, explicit approvals, and durable local evidence, without silent
> downloads or model switches.

The launch set should contain the five-minute Quickstart, validated SDXL image,
trust proof, protocol animation with its simulation label, concise comparison
page, and one short demo video only after its source assets and claims are
reviewed. Tool count is supporting evidence, not the headline.

## Thirty-Day Cadence

- `T+0`: record the append-only baseline within five minutes of the formal
  GitHub Release when possible.
- `Days 1-3`: publish the same evidence-backed message to approved MCP, Codex,
  ComfyUI, and local-AI channels; answer first-run failures before adding scope.
- `Days 4-10`: turn repeated install questions into Quickstart or troubleshooting
  fixes and publish verified patch releases through the same gates.
- `Days 11-21`: add user-owned workflow examples only with reproducible setup,
  rights-safe assets, and explicit limitations.
- `Days 22-29`: refresh the comparison page and prioritize conversion blockers
  supported by issue or installation evidence.
- `T+30`: record the repository Star total in the inclusive observation window,
  validate the hash chain, and report `goal_met`, `goal_missed`, or
  `measurement_incomplete` without interpolation.

An actual T+30 result below the 100-Star floor is `goal_missed`, not a partial
success: continue iteration on positioning, onboarding, evidence, and channels
until the floor is met. The existing `goal_met` status means that the floor was
met, not that the higher operating target was achieved. A miss does not justify
inflated claims, unsolicited promotion, Star exchanges, or weaker approval and
identity controls.
