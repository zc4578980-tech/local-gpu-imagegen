# Public-Evidence Model Route Shortlist

Status: read-only recommendation recorded on 2026-07-22. This document grants no download, installation, trust, generation, evidence-export, or publication authority.

The separately approved first-stage transfer later completed through `hf-mirror.com` because the current shell could not reach Hugging Face directly. The retained checkpoint is exactly 6,938,078,334 bytes with SHA-256 `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`; its bounded safetensors header declares StabilityAI and CreativeML Open RAIL++-M. `sdxl-checkpoint-source-audit.json` records the result as `downloaded_untrusted`. No trust, generation, public authority, evidence export, or publication followed from the transfer.

## Decision Context

The public reference route must have an official source, complete license terms for the exact executable components, explicit enough output-use terms for retained examples, a supported local runtime, and a credible path on the verified 12 GB GPU and 31 GB system-RAM host. The private Comfy-Org Z-Image route remains the higher-quality local default, but its quantized primary model and text encoder do not have sufficient repack-bound authority for public evidence.

Scores use `1` (poor) through `5` (strong). `Authority simplicity` rewards fewer independently sourced or repacked components. Quality scores are expectations from model capability and ecosystem evidence, not measurements from this project.

| Candidate | License completeness | Output terms | 12 GB fit | Runtime maturity | Storage efficiency | Expected quality | Authority simplicity | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Official SDXL 1.0 Base | 5 | 5 | 5 | 5 | 5 | 3 | 5 | **33/35** |
| Official FLUX.1-schnell | 5 | 4 | 2 | 4 | 2 | 4 | 3 | **24/35** |
| Official Qwen-Image | 2 | 3 | 1 | 3 | 1 | 5 | 1 | **16/35** |

## Recommendation

Use `stabilityai/stable-diffusion-xl-base-1.0` as the first public-evidence reference route.

- The official `sd_xl_base_1.0.safetensors` is a single approximately 6.9 GB checkpoint, avoiding the unresolved multi-source quantized-component chain that blocked Z-Image.
- CreativeML Open RAIL++-M explicitly says the licensor claims no rights in generated output, subject to the license and its use restrictions.
- SDXL is natively supported by mature ComfyUI and AUTOMATIC1111 runtimes and is practical on 12 GB VRAM without relying on a third-party quantized repack.
- Its expected image quality is below newer Z-Image, FLUX, and Qwen routes. That is acceptable for a reproducible public reference: the project's differentiator is governed natural-language orchestration, BYOM routing, review, hot revision, and evidence integrity rather than ownership of the image model.
- Keep the current private Z-Image route as the quality-oriented default for this machine. The public and private routes demonstrate the intended BYOM separation instead of pretending one checkpoint is optimal for every scope.

## Deferred Alternatives

`black-forest-labs/FLUX.1-schnell` is the second choice. Its official weights are Apache-2.0 and the model is a stronger quality candidate, but the approximately 33 GB full component set is tight against 31 GB system RAM. Sequential CPU offload can lower VRAM demand at a large latency cost. Exact text-encoder and VAE authority would still need to be pinned before public evidence.

`Qwen/Qwen-Image` is not the first public route on this host. The official model is Apache-2.0 and has native ComfyUI support, but its 20B diffusion model plus 8.3B text encoder make the official BF16 component set larger than 50 GB. A practical 12 GB route depends on FP8 or GGUF repacks and custom loaders, recreating the component-provenance problem this work is intended to avoid.

## Approved Transfer Boundary

The separately approved and completed first stage was limited to the following boundary:

- Download the official `sd_xl_base_1.0.safetensors` checkpoint from the Stability AI Hugging Face repository.
- Place it under the existing project-local ComfyUI deployment at `runtime/ComfyUI_windows_portable/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors`; do not alter shared or global Python environments.
- Expect approximately 6.9 GB of model storage and reserve at least 10 GB for transfer and verification headroom.
- Do not install custom nodes or additional runtimes.
- After download, hash and inspect the exact local bytes, bind the checkpoint and reviewed workflow, and present the resulting authority facts before any trust mutation.
- Require a separate confirmed route and successful-round budget before generation. Public evidence export and publication remain separately gated.

## Primary Sources

- [SDXL official model card](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [SDXL CreativeML Open RAIL++-M license](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md)
- [Official ComfyUI SDXL example](https://comfyanonymous.github.io/ComfyUI_examples/sdxl/)
- [FLUX.1-schnell official model card](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
- [FLUX.1-schnell Apache-2.0 license](https://huggingface.co/black-forest-labs/FLUX.1-schnell/blob/main/LICENSE.md)
- [Qwen-Image official model card](https://huggingface.co/Qwen/Qwen-Image)
- [Qwen-Image Apache-2.0 license](https://huggingface.co/Qwen/Qwen-Image/blob/main/LICENSE)
- [Official ComfyUI Qwen-Image tutorial](https://docs.comfy.org/tutorials/image/qwen/qwen-image)
