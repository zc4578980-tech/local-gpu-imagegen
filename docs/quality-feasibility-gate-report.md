# Workflow No-Regression Feasibility Gate

**Date:** 2026-07-26
**Decision:** `FAIL_WORKFLOW_REGRESSION`

## Question

This bounded local experiment tested one question: under the same installed
model, dimensions, sampler, scheduler, steps, guidance, paired seeds, and GPU
submission budget, does the complete project workflow degrade output relative
to a direct raw-ComfyUI submission?

Model capability was evaluated separately. Weak output in both lanes is
reported as `MODEL_QUALITY_LIMIT` and does not excuse workflow regression.
This experiment is not a general model benchmark or a GitHub Star guarantee.

## Frozen Method

- Definition SHA-256: `f24dd7c32063c3d2f97fab4673bba66ad102a95b82020a19cefbf477a9b2b3d5`
- Shipped workflow SHA-256: `41805e330a0bf750e14107834c29b5b9986bdbc37fc0aff283509796475f1115`
- Model: `z_image_turbo_nvfp4.safetensors`
- Model identity: `local:adf893945632c8955b2b801a`
- Workflow: `z-image-turbo-txt2img` version 1
- ComfyUI: 0.28.0 on one NVIDIA GeForce RTX 5070 Ti Laptop GPU
- Settings: 8 steps, CFG 1.0, `res_multistep`, `simple`
- Negative conditioning: zeroed by the Z-Image graph in both lanes
- Dimensions: anime 768x1024; frontend and presentation 1280x720
- Budget: three cases, two seeds, two lanes, twelve accepted submissions maximum

The raw lane deep-copied and bound the shipped Z-Image API graph, then posted it
directly to ComfyUI. It bypassed MCP, `AssetRunEngine`, prompt compilation, and
project run orchestration. The workflow lane used discovery, routing,
`AssetRunEngine`, `natural-v1` prompt compilation, the retained run manifest,
and the same shipped workflow. Candidate bytes were retained without
postprocessing.

The prompts came from the already-frozen ordinary and initial-workflow
showcase arguments. No prompt or setting was changed after an output was seen.

### Anime prompts

Raw positive:

> An original adult anime woman standing on a seaside observation deck at blue
> hour, full-body key art, dark wavy hair, teal technical jacket, calm confident
> expression, cinematic anime illustration, detailed face and hands, no text.

Raw negative: empty.

Workflow positive:

> Original adult anime heroine, one clearly adult woman, full-body three-quarter
> standing pose on a quiet seaside observation deck at blue hour, both arms
> separated from the torso, both hands naturally visible and relaxed, both legs
> clearly separated, complete shoes grounded on the deck, dark shoulder-length
> wavy hair moving coherently in the sea breeze, teal technical jacket over
> charcoal clothing, calm determined expression, refined 2D anime key art,
> precise eyes and facial features, deliberate fabric seams, cool ocean cyan
> with restrained warm signal-light accents, cinematic rim light, clean depth
> layers, polished promotional illustration, no lettering or symbols.

Workflow negative:

> child, young-looking, school uniform, sexualized pose, cleavage, extra person,
> duplicate body, extra limbs, fused limbs, missing fingers, extra fingers,
> malformed hands, hidden hands, cropped feet, floating feet, broken joints,
> twisted spine, incoherent hair, text, logo, watermark, signature, frame, low
> detail, blurry face

### Frontend prompts

Raw positive:

> A wide hero image for a modern productivity app, creative workspace at dawn,
> room for text on the left, premium editorial photography, teal and yellow
> accents, no text or logo.

Raw negative: empty.

Workflow positive:

> Text-free 16:9 editorial hero photograph for a focused project-planning
> product named Fieldnote, a tactile design studio at first light with paper
> prototypes, material samples, a precise metal ruler and one open notebook
> arranged on a long worktable, no readable writing, visual activity concentrated
> in the right 45 percent, left 45 percent calm dark-cyan wall and soft window
> light reserved for white HTML headline, restrained saffron object accent,
> realistic materials, quiet professional atmosphere, crisp focal plane,
> believable natural light, useful negative space, crop-safe at desktop and
> narrow mobile widths.

Workflow negative:

> text, letters, numbers, logo, watermark, fake user interface, dashboard,
> floating screen, laptop text, phone screen, human hands, person, clutter across
> the left side, centered subject, neon cyberpunk, purple gradient, stock photo
> smile, excessive blur, rounded card graphics, illustration, 3D render

### Presentation prompts

Raw positive:

> Wide clean-energy strategy presentation cover image, offshore wind farm at
> sunrise, room for title on the left, editorial photography, no text.

Raw negative: empty.

Workflow positive:

> Text-free 16:9 Swiss editorial documentary photograph for a clean-energy
> market strategy presentation, offshore wind maintenance vessel moving through
> calm steel-blue water toward three clearly separated turbines at first light,
> vessel and turbines contained in the central-right 60 percent, broad low-detail
> mist and open sky on the left for HTML title overlay, one restrained
> safety-orange detail, precise industrial realism, strong horizon, high clarity,
> calm credible business tone, no generated slide chrome.

Workflow negative:

> text, letters, numbers, logo, watermark, chart, infographic, slide border,
> title box, fake UI, excessive turbines, fused turbine blades, impossible
> vessel, storm, disaster, neon, purple gradient, cartoon, 3D render, crowded
> left side

## Accounting

| Lane | Started | Accepted | Completed | Failed | Publishable | Rejected |
|---|---:|---:|---:|---:|---:|---:|
| Raw ComfyUI | 6 | 6 | 6 | 0 | 0 | 6 |
| Project workflow | 6 | 6 | 6 | 0 | 0 | 6 |
| Total | 12 | 12 | 12 | 0 | 0 | 12 |

Maximum consecutive failures was zero. All six paired comparisons completed.

## Blinded Evidence

Scores are ordered as appeal / composition / coherence / defect absence / slot
fitness / public readiness. The maximum total is 30. Lane assignments were
concealed until all scores and preferences were frozen by the user.

| Case | Label | Revealed lane | Seed | Scores | Total | Hard defects | Publishable | Candidate SHA-256 |
|---|---|---|---:|---|---:|---|---|---|
| Anime | C | raw | 2026072601 | 3/3/4/3/2/3 | 18 | none | no | `ad08378332b2e7c55a921c5796c39b013e24d9f0e1e8f57a1466d1c677caa05e` |
| Anime | D | workflow | 2026072601 | 3/4/4/4/4/3 | 22 | none | no | `85e87acf878e6d88822ecc442d032793f2ec2ce361f0f02cf5c4c4c1a3fdc09b` |
| Anime | A | raw | 2026072602 | 3/3/4/4/3/3 | 20 | none | no | `08911f39c5fef48f129f965e2a66551360bae960954f2caed63039d907e52b4f` |
| Anime | B | workflow | 2026072602 | 3/4/4/4/4/3 | 22 | none | no | `7fc5f9c53a194dfd9104173033aff86fcbf0ac67bfee8e89a56fbc78700d9bdf` |
| Frontend | C | raw | 2026072603 | 2/3/2/1/1/1 | 10 | baked text, malformed UI | no | `1da7292cae939742360e5a105129dcf9f693352a7e48a7d9017c2450d0b423a4` |
| Frontend | A | workflow | 2026072603 | 3/4/4/2/2/2 | 17 | baked text | no | `ff1bbf31b7ea5562495949601d24b15dc30d6f6d29a1e442878fbb3cab594775` |
| Frontend | B | raw | 2026072604 | 2/3/2/1/1/1 | 10 | baked text, malformed UI | no | `473499ce09cd3951e92d8db5220991ce20f3eb0877abf88d268cbb766bfef986` |
| Frontend | D | workflow | 2026072604 | 3/4/4/2/2/2 | 17 | baked text | no | `e89b5459854010a47c47790fcabca7a4bf44e3280dbebe6eb01722979479b83d` |
| Presentation | B | raw | 2026072605 | 4/5/4/2/2/2 | 19 | baked text | no | `8d2322bda71ddd059b46c023b6578a5d897d2484f39721d75bbbadf4011c5177` |
| Presentation | C | workflow | 2026072605 | 3/4/4/1/2/2 | 16 | baked text | no | `b87f1ced1e0d2fc9453725f2810d1639bafdaccc7b627d4f885e41432cb38a70` |
| Presentation | A | raw | 2026072606 | 4/4/4/2/2/2 | 18 | baked text | no | `d7769c13648ce4cee583fa88611baab95e65be1c4713b95e45bebc2bc3207c45` |
| Presentation | D | workflow | 2026072606 | 3/3/4/1/1/1 | 13 | baked text | no | `4d84566b94b0a17bd5e50feb2d942fa29dc81a7dadcb1e9eae212f65ed291145` |

Frozen pair preferences were anime `D > C` and `B > A`, frontend `A > C`
and `D > B`, and presentation `B > C` and `A > D`.

The blind-map SHA-256 was
`e1af7f16439dd96c6d98cbca5d531ec901d3fad9232b59f32a949e2677f72024`.
The user-frozen review SHA-256 was
`82d456d64d98e704c18973b792fc167d44ea77ef0e1bd4617336aa6f673cee04`.

## Graph and Route Evidence

Every raw candidate used the same reviewed Z-Image graph topology with only
the frozen prompt, dimensions, seed, settings, and filename bindings changed.
The bound graph hashes were:

| Case | Seed | Raw graph SHA-256 |
|---|---:|---|
| Anime | 2026072601 | `237beb63efc6f6481900b4f0298ef368c3ce4d1400eda1013e0ae1e29c64d90f` |
| Anime | 2026072602 | `929741f8b7296db28c65bc0dac4b6e51592f388cc4b472c02bbf98912a582bc5` |
| Frontend | 2026072603 | `a517aed96849603d114380a7210eb412e0678339e46018deaed4b48c10d1f042` |
| Frontend | 2026072604 | `971f421723450a1d8ec3de4b21326eedf471fd1ac3bcd243b83f6acad01c088a` |
| Presentation | 2026072605 | `9ca5b105f2c925b991caaad3a0b3546dd3fafbdd018066805333efc4edb60368` |
| Presentation | 2026072606 | `bdee52cef156e5b63c82e27463022db2278fa46579138a5555cfd65f37db4d49` |

Every workflow candidate retained a project run manifest identifying the same
model and workflow version, the `natural-v1` compiler, and the same qualified
loopback backend binding. The route was discovered and recommended through the
project services rather than inserted directly.

## Decision

| Case | Best raw | Best workflow | Workflow minus raw | Regression | Model limit |
|---|---:|---:|---:|---|---|
| Anime | 20 (`A`) | 22 (`D`) | +2 | no | yes |
| Frontend | 10 (`C`) | 17 (`A`) | +7 | no | yes |
| Presentation | 19 (`B`) | 16 (`C`) | -3 | **yes** | yes |

Selected best candidate hashes:

| Case | Raw SHA-256 | Workflow SHA-256 |
|---|---|---|
| Anime | `08911f39c5fef48f129f965e2a66551360bae960954f2caed63039d907e52b4f` | `85e87acf878e6d88822ecc442d032793f2ec2ce361f0f02cf5c4c4c1a3fdc09b` |
| Frontend | `1da7292cae939742360e5a105129dcf9f693352a7e48a7d9017c2450d0b423a4` | `ff1bbf31b7ea5562495949601d24b15dc30d6f6d29a1e442878fbb3cab594775` |
| Presentation | `8d2322bda71ddd059b46c023b6578a5d897d2484f39721d75bbbadf4011c5177` | `b87f1ced1e0d2fc9453725f2810d1639bafdaccc7b627d4f885e41432cb38a70` |

The presentation workflow regressed because its best candidate scored three
points below the best raw candidate. The all-cases no-regression requirement
therefore failed even though the workflow scored higher in anime and frontend.

All three cases independently received `MODEL_QUALITY_LIMIT`: no candidate met
the publishability contract. The anime outputs were coherent but generic. Every
frontend candidate contained baked text, and both raw candidates also contained
malformed UI. Every presentation candidate contained baked text. This model
finding does not alter the presentation workflow-regression finding.

Final workflow decision: **`FAIL_WORKFLOW_REGRESSION`**.

Per the approved stop rule, this result ends the current quality/100-Star
launch direction. It does not authorize a quality engine, model download, or
additional image-engineering phase.

## Integrity and Limits

- No production code, tests, dependencies, models, custom nodes, tracked
  workflows, trust state, client state, or remote state changed.
- No model was downloaded and no remote repository operation was performed.
- The twelve-submission ceiling and sequential frozen order were respected.
- There were no backend, identity, route, or accounting failures.
- The task-owned ComfyUI process was stopped only after PID, executable hash,
  executable path, and arguments matched the retained identity; port 8188 then
  closed.
- The frozen regional and two-stage workflow diffs remained empty.
- Candidate images, private blind mapping, logs, and run artifacts remain local
  ignored evidence and are not included in this report.
- This is a six-pair local comparison on one installed model. It is sufficient
  for the frozen go/no-go rule but does not generalize to every model, prompt,
  GPU, or ComfyUI installation.

## Repository Verification

- `python -m unittest discover -s tests`: 797 passed, seven expected Windows
  skips, zero failures.
- `python -m compileall -q scripts tests`: passed.
- `git diff --check`: passed.
- Working-tree and cached diffs for the frozen regional and two-stage workflows:
  empty.
- Final pre-commit status contained only this untracked factual report; ignored
  local evidence remained unstaged.
