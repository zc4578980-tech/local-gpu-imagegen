# Fresh-Process File Verification Authorization Design

**Date:** 2026-07-28
**Status:** Design and bounded budget amendment approved in conversation
**Parent slice:** Codex-first workflow runner (`codex/codex-first-workflow-runner`)
**Current branch base:** `7ccda6c`

## Problem And Root Cause

The Codex-first workflow runner promises a fresh MCP process can perform
API-only discovery, inspect one supported ComfyUI API workflow, and display a
complete preparation proposal. The implementation does not satisfy that
composition: API-only ComfyUI discovery emits `backend_binding` identities,
while workflow trust inspection requires a primary and selected component
identity with `backend == filesystem` and `identity_strength == cryptographic`.

The earlier live preparation succeeded because it performed selected-folder
indexing and full-file fingerprinting before API-only discovery. Model-free
tests also pre-seeded a filesystem record in the in-memory inventory. Neither
behavior is represented in the published first-run path. The result is a
fresh-process failure before the preparation proposal, usually
`invalid_component_bundle` or `component_primary_identity_required`.

## Goals

- Preserve cryptographic filesystem identity as the authority for ComfyUI
  component bundles and public evidence.
- Keep the MCP surface at exactly 17 tools and keep the MCP layer thin.
- Make first use three explicit decisions: exact model-file verification,
  registration/private trust, and execution-route approval.
- Persist authorization to re-read one exact local model path, while requiring
  a fresh full SHA-256 verification in every later MCP process that uses it.
- Make later use of a new workflow on the same verified model require only
  registration/private trust and execution. A previously registered and
  un-drifted workflow requires only execution.
- Keep all verification local, bounded, reversible, and model-free until the
  later separately approved live gate.

## Non-Goals And Hard Boundaries

- No private backend-bound downgrade for this workflow path.
- No new MCP tool, model, workflow, backend, downloader, GPU behavior, or
  image-quality claim.
- No broad directory scan when an exact model file can be named.
- No UNC/network roots, symlinks, junctions, reparse points, directories, or
  ambiguous file matches.
- No automatic trust, registration, route issuance, prompt submission, model
  switch, CPU fallback, or download.
- No reuse of the spent route or run from the stopped 2026-07-28 gate.
- The new slice has a hard ceiling of 350 net production lines. If the
  implementation exceeds it, stop for design review instead of weakening a
  verification boundary.

## Architecture

### Ownership

The new `scripts/local_gpu_imagegen/file_verification.py` owns the persistent
authorization record, schema validation, atomic writes, exact-path lookup,
drift state, and revocation. `discovery.py` owns the bounded exact-file plan
and execution and uses the registry only through its narrow interface.
`services.py` constructs the registry and injects it into discovery. The MCP
server extends the existing discovery schema and dispatch only; it does not
hash files or duplicate identity logic. The Agent Skill owns the three-step
conversation and the later automatic revalidation sequence.

### First-use control flow

```text
API-only discovery
  -> inspect workflow and observe loader/model binding
  -> exact_file/verify plan (stat only, no full read)
  -> display exact path, model name, byte count, cost warning, drift boundary
  -> later user approval
  -> exact full-file SHA-256 + before/after file-identity checks
  -> persist FileVerificationRegistry authorization
  -> add cryptographic filesystem record to current inventory
  -> inspect workflow trust bundle using filesystem + API identities
  -> display registration/private-trust proposal
  -> later user approval
  -> immutable registration + private trust
  -> display fresh execution route
  -> later user approval
  -> one bounded run
```

The exact model root and include are supplied when no unique authorization can
be resolved. The plan accepts exactly one root and one file, resolves both,
rejects path escape and link-like entries, and binds the expected backend model
name observed from the workflow. It never scans neighboring files.

### Later-process control flow

```text
API-only discovery
  -> inspect workflow
  -> exact_file/verify plan resolves one active authorization by model name
  -> stat-only plan displays exact path and full-read cost
  -> execute without a new user confirmation under the persisted path scope
  -> full SHA-256 and file-identity revalidation
  -> restore cryptographic filesystem record in current inventory
  -> continue existing trust/route flow
```

Automatic revalidation occurs only when a requested workflow references the
model. It never hashes all authorized files at process startup. If more than
one authorization matches the model name, the Agent asks for an exact root and
file rather than guessing.

## Persistent Authorization

The registry lives under the user-local `LOCAL_GPU_IMAGEGEN_STATE_DIR` and is
never part of the repository, public evidence, or a route token. Its strict
schema is:

```json
{
  "schema_version": 1,
  "records": [
    {
      "authorization_id": "verification:<opaque-id>",
      "local_path": "<normalized local path>",
      "resolved_root": "<normalized local root>",
      "backend_model_id": "<workflow loader name>",
      "sha256": "<64 lowercase hex>",
      "byte_size": 0,
      "modified_ns": 0,
      "status": "active",
      "created_at": "<UTC timestamp>",
      "last_verified_at": "<UTC timestamp>"
    }
  ]
}
```

Only `active`, `drifted`, and `revoked` records are valid statuses. A failed
first hash writes no record. A drifted record retains the last approved digest
but does not expose a new digest as trusted; the new observation remains
transient until a later verification decision. Revocation is an atomic status
change and never deletes model files, workflow state, or trust records.

All writes use the existing atomic JSON pattern. Unknown fields, credentials,
non-local paths, invalid digests, duplicate authorization IDs, and malformed
records fail closed as corrupt local state.

## MCP Contract

`local_gpu_discover_models` remains the only affected tool and the total tool
count remains 17. Existing modes and stages retain their behavior. The strict
schema gains:

- mode `exact_file`;
- stages `verify` and `revoke`;
- optional `expected_backend_model_id`;
- optional `authorization_id`.

`exact_file/verify` planning requires exactly one root and one explicit include
when no active authorization is resolved. It performs only stat and safety
checks. A reusable authorization produces a plan marked
`confirmation_required: false`; the server, not the caller, decides whether
the persisted authorization permits execution. A first authorization or a
drifted authorization produces a displayed confirmation bound to the frozen
path, expected stat, model name, and plan digest.

`exact_file/verify` execution performs the full hash, validates file identity
before and after the read, persists a successful new authorization when
required, and returns a normal cryptographic filesystem discovery record. The
current process inventory receives the record only after every check passes.

`exact_file/revoke` always requires a plan confirmation. It changes only the
selected authorization status and returns no model bytes.

The MCP validator may accept a missing confirmation only for an exact-file plan
whose server-side state is already bound to an active persisted authorization.
All other discovery executions retain the existing confirmation requirement.

## Error And Recovery Contract

- Missing, ambiguous, or mismatched exact files stop before hashing and return a
  structured recovery action requiring a new exact path or root.
- Link-like, network, non-regular, unreadable, or escaped paths are rejected
  without inventory or registry mutation.
- A pre-hash stat mismatch, mid-read identity change, or post-hash mismatch
  returns `model_identity_drifted`; no new authorization is written.
- A changed SHA-256 marks the old authorization `drifted`, refuses to restore
  the inventory, and requires the next model-verification decision.
- Registry corruption stops the request and never falls back to API binding.
- Endpoint, workflow, component bundle, trust, and route drift continue to use
  their existing fail-closed errors and confirmation boundaries.
- No verification error retries, broadens scanning, changes models, invokes a
  backend, uses CPU generation, downloads, or submits a prompt.

## TDD And Acceptance

RED tests must precede production changes. The focused tests will cover:

1. exact-file plan shape, one-root/one-file enforcement, model-name binding,
   cost display, and stat-only behavior;
2. first-use confirmation, successful hash persistence, atomic failure, and
   current-inventory insertion only after success;
3. active authorization reuse without a new confirmation, full rehash, and
   same-SHA restoration;
4. path, file-ID, stat, and SHA drift; no inventory restoration after drift;
5. unsafe paths, ambiguity, model mismatch, expired plan, revoked records,
   duplicate IDs, corrupt JSON, and credential rejection;
6. MCP strict schemas, exactly 17 tools, exact-file dispatch, and no mutation
   on read-only plan calls;
7. fresh-process composition: API binding plus restored filesystem identity
   reaches the trust proposal, while API-only inventory alone fails closed;
8. Skill/quickstart/troubleshooting contracts for three first-use decisions,
   two later decisions, and one decision for an already trusted unchanged
   workflow.

Acceptance requires all focused tests, the full repository suite with only
documented Windows skips, `compileall`, the 17-tool MCP verifier, frozen
workflow byte identity, `git diff --check`, and exact production line
accounting. The later live gate may hash one newly authorized installed model
file at most once; it still permits one fresh route approval, one accepted
ComfyUI prompt ID, and one successful image maximum.

## Cost, Timeline, And Stop Conditions

The implementation target is two to three focused engineering days inside the
overall three-to-five-day boundary. The new production slice must remain at or
below 350 net lines across the new registry and integration changes. Stop for
design review if it needs another MCP tool, a second verification store, a
backend-bound downgrade, broader filesystem scanning, or more than 350 net
 production lines. No image-quality benchmark or Adaptive Quality work is part
of this slice.

## Open Limitations

- Full-file revalidation may read several gigabytes on a later fresh process;
  the plan must display that cost before execution, even when no new user
  confirmation is required.
- A user who has multiple files with the same ComfyUI loader name must provide
  an exact root/file selection; the Agent never picks one.
- The design proves route identity and workflow fidelity, not image quality or
  end-to-end generation. Those remain separate live-gate evidence.
