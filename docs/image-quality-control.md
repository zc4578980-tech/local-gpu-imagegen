# Image Quality Control Boundary

Local GPU Imagegen does not improve diffusion algorithms, model weights,
samplers, or ComfyUI nodes. Image quality comes primarily from the user's model,
workflow, prompt, and review decisions. The project can make execution explicit,
bounded, reproducible, and reviewable; it cannot turn a weak or unsuitable image
route into a strong one by adding control-plane code.

## Review Order

Review practical correctness before visual polish:

1. Compare the full-resolution image with the frozen intent.
2. Check the requested subject, product medium, practical use, and asset slot.
3. Check explicit prohibitions, safe areas, text, anatomy, and object coherence.
4. Only then score appeal, composition, detail, defect absence, slot fitness, and
   public readiness.

A visually cleaner output that changes the requested product medium, subject,
practical use, or asset slot is **semantic substitution**. Record it as a failed
constraint and do not finalize that round. Fewer rendering defects do not make a
semantically wrong asset useful.

For example, a digital project-planning product cannot be represented only by a
generic paper notebook and design desk when the requested use requires the image
to communicate software. A blank or deliberately defocused device screen with
real UI composed later may satisfy the medium; replacing the software product
with stationery does not.

## Hard Stops

The following findings prevent finalization when they violate the frozen brief:

- semantic substitution;
- baked text, logos, watermarks, or generated slide chrome;
- malformed UI or invented interface content;
- an unusable title, copy, or responsive-crop safe area;
- severe anatomy, malformed objects, or an obvious workflow artifact;
- a required subject, product, or compositional element that is absent;
- a hard preserve target changed in a revision.

Use the existing review `constraint_results` and `hard_failures` fields. This
policy adds no new MCP schema and does not let the Agent accept its own output.
The user still provides later byte-bound finalization authority.

## Model Limits And Workflow Regression

Model weakness and workflow regression are separate outcomes:

- `MODEL_QUALITY_LIMIT` means neither lane produced a publishable candidate.
- A workflow still regresses when it performs worse than the same-model,
  same-settings, same-seed raw baseline.
- Model weakness never excuses workflow regression.
- A visually improved but semantically substituted result is not application
  value and cannot support an image-quality claim.

## Frozen 2026-07-26 Gate

The retained six-pair gate used the same Z-Image model, sampler, scheduler,
steps, guidance, dimensions, paired seeds, and twelve-submission ceiling across
raw ComfyUI and project-workflow lanes.

| Case | Workflow minus raw | Result |
|---|---:|---|
| Anime | +2 | No measured regression, but no publishable candidate |
| Frontend | +7 | Fewer visible defects, but post-reveal review found semantic substitution and no publishable candidate |
| Presentation | -3 | Workflow regression |

All three cases had `MODEL_QUALITY_LIMIT`. Presentation crossed the frozen
two-point regression threshold, so the overall decision remains
`FAIL_WORKFLOW_REGRESSION`.

The post-reveal frontend semantic finding does not rewrite the frozen blinded
scores. It corrects the product interpretation: the +7 visual score cannot be
used as proof that the workflow produced a better software-product asset.

See the [full factual gate report](quality-feasibility-gate-report.md) for
candidate hashes, prompts, scores, accounting, and limitations.

## Future Quality Claims

A future quality claim requires a separately approved paired gate with:

- one literal application brief shared across lanes;
- the same model, graph topology, dimensions, seed, steps, guidance, sampler,
  scheduler, and GPU budget;
- no prompt change after output inspection;
- full-resolution blind review and explicit user authority;
- semantic fidelity and asset-slot fitness checked before polish;
- no regressed case; and
- at least one publishable candidate that needs no editing or explanatory excuse.

Until such a gate passes, public positioning remains supported local workflow
execution from Agents, not image-quality enhancement.
