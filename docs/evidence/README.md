# Acceptance Evidence

This directory is the public, machine-verifiable record for real Codex MCP acceptance runs. Normal tests do not generate these files and do not require a GPU, model, network connection, or image library.

## Release gate policy

The current v0.9 preview gate targets version `0.9.0` and requires an exact-commit model-free suite, reproducible clean wheel, exactly seventeen tools, fail-closed `doctor` behavior, safe named-client setup contracts, and explicit disclosure of missing evidence. One local Windows/NVIDIA acceptance finalized a reviewed non-human environment result through managed ComfyUI and the real MCP path, but it remains outside this public directory until separately sanitized, exported, and validated. Two character runs remain private, reviewed, ineligible negative evidence and are not publishable release-set artifacts. Prominent-human anatomy quality, a complete named-client generation release set, and full acceptance are not established.

The existing strict acceptance validator remains the full-acceptance/v1.0 gate. Its exact 9-root plus 3-revision requirement is unchanged. The current incomplete matrix is expected to fail that gate; the failure does not block the separately defined v0.9 preview gate and must not be hidden or presented as a strict pass.

`z-image-component-source-audit.json` is a blocked source audit, not an authority grant. It records exact installed/published hashes, component commit provenance, bounded safetensors-header inspection, upstream license evidence, and unresolved repack/output authority. Partial component evidence never promotes the complete route.

`public-route-shortlist.md` is a read-only comparison and recommendation, not an authority grant. It recommends official SDXL 1.0 Base as the first public-evidence reference route for this host, while retaining Z-Image as the private quality-oriented default. No candidate may be downloaded, installed, trusted, generated with, exported, or published merely because it appears in that document.

`sdxl-checkpoint-source-audit.json` records the separately approved checkpoint transfer, read-only inspection, and later explicit authority decisions. Its status is `public_candidate_authorized`: the exact file size and SHA-256 match the mirror's repository-linked response, the safetensors header declares StabilityAI and CreativeML Open RAIL++-M, and ComfyUI exposes the checkpoint through `CheckpointLoaderSimple`. A dedicated SDXL workflow and exact component bundle passed inspection before the user separately approved the digest-bound public-candidate trust record and SDXL/ComfyUI acceptance authority. Those decisions authorize this exact public-evidence route; they do not authorize generation, evidence export, or publication by themselves.

`acceptance-authority.example.json` is deliberately unapproved. It documents the shape of an authority decision but never authorizes backend/model use, downloads, a repository license, or publication. A real `acceptance-authority.json` is created only after explicit approval and must pin the fixed brief hash, backend, model hashes and licenses, output-redistribution status, repository license, holder, and any named install/download permission. A ComfyUI authority must additionally pin every component role, loader field, backend-visible name, filesystem identity token, byte size, SHA-256, source/license/redistribution decision, reviewed workflow SHA-256, and canonical bundle SHA-256.

Each accepted root package lives under `runs/<brief-id>/`; the three required immutable child packages live under `revisions/<brief-id>/`. Packages retain the original MCP final result, sanitized manifest, fixed brief, image artifacts, reviews, hashes, and observed environment metadata. Paths are relative. Mock/fixture markers, symlinks, private paths, credentials, hidden reasoning, and unrelated output files are forbidden.

The exporter requires the real run ID as an explicit confirmation. It copies bytes without re-encoding images and rejects missing previews, hash changes, reconstructed/mismatched MCP results, unapproved backend/model facts, component/workflow/bundle drift, and existing destinations. Child export additionally binds the parent run, selected round, image hash, parent manifest hash, and parent evidence hash.

Run the non-strict validator during implementation:

```powershell
python .\scripts\validate_acceptance_evidence.py
```

With no approved authority or retained runs it returns `ok: true`, zero counts, and `release_ready: false`. The full-acceptance/v1.0 gate uses `--strict`; that mode requires exactly nine accepted root runs and the three fixture-declared child revisions. Passing proves package consistency and coverage, not objective image quality, performance, compatibility, or production readiness.

## Adoption evidence

Each formal Release campaign owns `docs/evidence/adoption/<campaign_id>/campaign.json` and `docs/evidence/adoption/<campaign_id>/events.jsonl`. The first file fixes the repository, Release ID/tag/publication time, target, and timing policy. The second is canonical append-only JSONL linked by SHA-256.

The historical `v0.8.3-release-364342670` campaign recorded a zero-Star baseline
37 minutes after publication. Validation classifies that observation as
`degraded` and the unfinished campaign as `measurement_incomplete`; it is not
reconstructed publication-time evidence.

Collect and validate with the repository-maintenance scripts:

```powershell
python .\scripts\record_star_observation.py baseline --campaign-id <campaign_id> --repository <owner/repository> --release-tag <tag>
python .\scripts\record_star_observation.py observe --campaign-dir docs\evidence\adoption\<campaign_id> --phase t30
python .\scripts\validate_star_campaign.py docs\evidence\adoption\<campaign_id>
```

The record stores repository-level Star totals only: no stargazer identities, interpolation, traffic attribution, credentials, or raw API bodies. Corrections append a superseding event instead of rewriting history. Validation reports `goal_met`, `goal_missed`, or `measurement_incomplete`. `100 net-new GitHub Stars` is the planning floor and minimum acceptable first-month outcome, not the target. An actual T+30 result below that floor is `goal_missed` and requires the team to continue iteration; it does not retract the Release. The status name `goal_met` means the floor was met, not that the higher operating target was achieved.
