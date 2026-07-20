# Security

## Supported Status

This project is pre-release. Security fixes target the latest source state only until versioned releases exist.

## Reporting A Vulnerability

After the repository is published, use GitHub's private security-advisory flow instead of a public issue. Include a minimal reproduction, affected component, impact, and suggested mitigation when known. Do not include real credentials or private images.

## Security Boundaries

- The default WebUI URL is loopback. Exposing a WebUI API to a LAN or the internet requires authentication, network controls, and a separate threat assessment.
- A caller can request reads from input-image paths and writes to output paths available to the MCP process. Run the server with least-privilege OS permissions.
- Diffusers model and LoRA downloads are denied by default; explicit permission does not verify the remote artifact's license or integrity.
- `disable_safety_checker` is off by default and should remain an explicit user choice.
- Generated images and prompts may be sensitive even when no cloud API is used. Apply ordinary local data-retention and access-control practices.
