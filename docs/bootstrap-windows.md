# Windows NVIDIA Guided Bootstrap Contract

Status: frozen for the current local-gpu-imagegen 0.8.3 candidate on
2026-08-05. The planned 0.9.0 target is future release scope, not this
published package.

This contract covers one Windows x64 path. It is not a general ComfyUI or model
installer. Planning is read-only apart from its own user-local plan record, and
downloads require a later exact confirmation that binds the sources, licenses,
byte ceilings, hashes, destinations, and disk effects shown below.

## Existing Or Zero Environment

Use `bootstrap status` for an existing environment: only a verified portable
layout, exact checkpoint metadata, and a ready loopback endpoint can take the
reuse fast path. A zero-environment install is guided by `bootstrap plan`, then
`bootstrap apply` after an explicit confirmation. Download state is resumable;
interrupted work is retained for retry, and failed promotion rolls back bounded
staging without deleting a pre-existing install. Docker is not required.

## Supported System

The exact supported scope is Windows 10/11 x64 with NVIDIA only.

- Windows 10 22H2 build 19045 or Windows 11, x64.
- NVIDIA RTX 20 series or newer.
- An NVIDIA driver that can run the portable package's bundled PyTorch CUDA
  13.0 runtime. ComfyUI's pinned README does not publish a numeric Windows
  driver floor and instructs users to update the driver if startup fails.
- At least 10 GiB VRAM for the frozen SDXL workflow contract.
- At least 30 GiB free on the selected install volume before a new install.
- Loopback ComfyUI and the shipped `sdxl-txt2img` workflow only.

Unsupported OS, architecture, GPU vendor or generation returns a structured
unsupported result. It does not select another archive, CPU mode, a smaller
model, or an unapproved mirror.

## Frozen Sources

### ComfyUI

- Project: `Comfy-Org/ComfyUI`
- Release: `v0.30.0`, published `2026-08-03T03:48:40Z`
- Tag commit: `b1693ecba9f5b65f8c80ab36b195ab963ec92413`
- Asset: `ComfyUI_windows_portable_nvidia.7z`
- Source: <https://github.com/Comfy-Org/ComfyUI/releases/download/v0.30.0/ComfyUI_windows_portable_nvidia.7z>
- Bytes: `2110797220`
- SHA-256: `f4353d069dd7342e3bef421f07f003cca53ca84168102705cfc83f66449f5ae5`
- License: GPL-3.0, <https://github.com/Comfy-Org/ComfyUI/blob/v0.30.0/LICENSE>
- License blob: `f288702d2fa16d3cdf0035b15a9fcbc552cd88e7`

The normal NVIDIA archive is intentional: the pinned upstream README says it
supports NVIDIA 20 series and above and contains Python 3.13 with PyTorch CUDA
13.0. The alternative `cu126` archive is for NVIDIA 10 series and older and is
outside the planned 0.9.0 target; it is not part of the current 0.8.3
candidate contract.

### Default checkpoint

- Repository: `stabilityai/stable-diffusion-xl-base-1.0`
- Revision: `462165984030d82259a11f4367a4eed129e94a7b`
- File: `sd_xl_base_1.0.safetensors`
- Source: <https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/462165984030d82259a11f4367a4eed129e94a7b/sd_xl_base_1.0.safetensors>
- Bytes: `6938078334`
- SHA-256: `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`
- License: CreativeML Open RAIL++-M, <https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/462165984030d82259a11f4367a4eed129e94a7b/LICENSE.md>
- Destination: `ComfyUI_windows_portable/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors`

The model license contains use restrictions. The bootstrap must display the
license identity and URL before confirmation. The project does not grant new
rights in the model or its output and does not silently accept the license for
the user.

## Download And Disk Effects

The exact new-download ceiling is `9048875554` bytes (about 8.43 GiB):
`2110797220` bytes for ComfyUI plus `6938078334` bytes for the checkpoint. The
30 GiB disk floor leaves room for retained verified downloads, staged portable
extraction, final model placement, plan state, and bounded rollback without
deleting a pre-existing install.

Only `github.com` and `huggingface.co` are approved production source hosts.
URLs are HTTPS and revision-pinned. Redirects must remain inside the later
downloader's explicit host policy. If Hugging Face is unreachable, the command
must retain resumable state and recommend configuring a working VPN or HTTPS
proxy before retrying. The current 0.8.3 candidate does not silently switch to
a mirror; the planned 0.9.0 target inherits the same boundary.

## Extraction Choice

The official archive is 7z. Python 3.11 and 3.12 cannot extract 7z with the
standard library, and Windows 10 does not provide one uniform built-in 7z
contract. The implementation therefore pins the Python `py7zr` `1.1.3`
library as an application dependency. Its upstream release was published on
2026-06-19 and its repository license is LGPL-2.1:
<https://github.com/miurahr/py7zr/releases/tag/v1.1.3> and
<https://github.com/miurahr/py7zr/blob/v1.1.3/LICENSE>. Before extraction,
project code must independently reject absolute paths, drive paths, traversal,
links, reparse-like entries,
device names, alternate data streams, duplicate or case-colliding paths,
excessive entry counts, and excessive expanded bytes. Extraction occurs only
in a new plan-owned staging directory and is followed by a second containment
and layout check before an atomic rename.

This choice does not authorize a dependency, portable, or model transfer by
itself. Dependency metadata and packaging are handled in the downloader task;
real portable and model bytes remain behind the exact bootstrap confirmation.

## Existing Install Reuse

The planner may reuse an existing portable only after validating its expected
embedded Python and `ComfyUI/main.py` layout. It may reuse the default model
only after exact size and SHA-256 verification. A running compatible loopback
endpoint can be reported as ready without a download. Other files, models,
configuration, and global Python environments are never modified or removed.

## Evidence And Limits

The ComfyUI release metadata, asset digest, tag commit, README support wording,
and license blob were read from the official GitHub API. The checkpoint size,
SHA-256, revision, embedded metadata, license identity, and ComfyUI loader
binding are retained in `docs/evidence/sdxl-checkpoint-source-audit.json`.

This source freeze is not install, startup, GPU, generation, quality, latency,
or public-user evidence. Those claims remain gated by later implementation and
fresh acceptance runs.
