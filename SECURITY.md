# Security

## Supported Status

This project is pre-release. Security fixes target the latest source state only until versioned releases exist.

## Reporting A Vulnerability

After the repository is published, use GitHub's private security-advisory flow instead of a public issue. Include a minimal reproduction, affected component, impact, and suggested mitigation when known. Do not include real credentials or private images.

## Security Boundaries

- The default WebUI URL is loopback. Exposing a WebUI API to a LAN or the internet requires authentication, network controls, and a separate threat assessment.
- Loopback WebUI/ComfyUI endpoints are accepted as local. Each LAN endpoint requires exact prompt/image transmission confirmation; public internet endpoints, URL credentials, DNS aliases, non-root paths, and redirects to another origin are rejected.
- Discovery defaults to `api_only`. `selected_folders`, `common_locations`, and `full_drive` require an unchanged, unexpired displayed plan and exact confirmation. `index` reads bounded metadata; `fingerprint` hashes only selected candidates. Discovery never follows symlinks/junctions/reparse points or loads `.ckpt` payloads.
- Trust state is user-local, atomic, excluded from Git, and overridable with `LOCAL_GPU_IMAGEGEN_STATE_DIR`. Credentials are rejected recursively. `backend_binding` is private-only; `public_evidence` candidacy requires a cryptographic SHA-256 and source/license/redistribution metadata but still does not replace acceptance authority.
- Confirmed runs freeze backend, endpoint, model identity, workflow, compiler, operation, and dimensions. Identity drift fails before backend work, and root/child runs enforce no silent model switch.
- ComfyUI runs only the shipped `sd15-txt2img-v1` workflow or a normalized imported copy that passes the node/input allowlist. Shell, Python/script/process, command, network/download/webhook/fetch behavior, unknown custom nodes, traversal, unbound parameters, and resource overruns are rejected.
- A caller can request reads from input-image paths and writes to output paths available to the MCP process. Run the server with least-privilege OS permissions.
- Diffusers model and LoRA downloads are denied by default; explicit permission does not verify the remote artifact's license or integrity.
- `disable_safety_checker` is off by default and should remain an explicit user choice.
- Generated images and prompts may be sensitive even when no cloud API is used. Apply ordinary local data-retention and access-control practices.
