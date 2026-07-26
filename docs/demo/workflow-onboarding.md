# Retained Codex Workflow-Onboarding Evidence

This note summarizes the sanitized
`docs/evidence/client-sessions/codex-v080-workflow-onboarding.json` record. The
machine-readable record remains authoritative.

## Session

- Client: Codex CLI 0.144.5 in an ephemeral installed-client session
- Server: Local GPU Imagegen 0.8.0 from an installed wheel
- Purpose: ordinary ComfyUI API workflow onboarding
- Duration: 6.5 seconds
- Prompt submission: none
- GPU generation: none
- Generated image: none

The session retained six observable MCP calls:

1. `local_gpu_discover_models` found the target model in current ComfyUI
   API-only inventory.
2. `local_gpu_inspect_workflow` inferred a single-checkpoint topology and
   returned a registerable proposal with separate source and semantic workflow
   hashes.
3. `local_gpu_discover_models` fingerprinted exactly one selected checkpoint and
   matched its byte size and full SHA-256.
4. `local_gpu_register_workflow` stored the confirmed immutable workflow as
   `imported:f314f0219fb9da189cad0a81a1f390d543e572c23a6da631964dcc4203efbc47`.
5. `local_gpu_set_model_trust` inspected the registered workflow binding and
   returned an exact component-bundle digest and later confirmation boundary.
6. `local_gpu_set_model_trust` applied that later exact private confirmation to
   the same cryptographic model and registered workflow identity.

The registered source SHA-256 was
`3c856060552c4ff286f30a50612fc234953d973454d950b399dec797965e7305`.
The semantic workflow SHA-256 was
`f314f0219fb9da189cad0a81a1f390d543e572c23a6da631964dcc4203efbc47`.
The bound component-bundle SHA-256 was
`3f3759079974e594985ee1b8e50f4edeaef7814e0e68bef69594073f27290e63`.

## Evidence Boundary

The retained record omits prompts, credentials, account identifiers, machine
paths, and raw hidden transcript content. It proves one installed Codex client
could complete the bounded onboarding and trust-binding protocol against an
already-running local backend.

It did not submit a prompt, generate an image, measure quality or performance,
or prove Claude Code generation. The separately retained
`docs/demo/real/final.png` came from another Codex generation session through a
reviewed ordinary route. It must not be presented as output from this imported
workflow session.
