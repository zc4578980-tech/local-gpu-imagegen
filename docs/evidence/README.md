# Acceptance Evidence

This directory is the public, machine-verifiable record for real Codex MCP acceptance runs. Normal tests do not generate these files and do not require a GPU, model, network connection, or image library.

`z-image-component-source-audit.json` is a blocked source audit, not an authority grant. It records exact installed/published hashes, component commit provenance, bounded safetensors-header inspection, upstream license evidence, and unresolved repack/output authority. Partial component evidence never promotes the complete route.

`public-route-shortlist.md` is a read-only comparison and recommendation, not an authority grant. It recommends official SDXL 1.0 Base as the first public-evidence reference route for this host, while retaining Z-Image as the private quality-oriented default. No candidate may be downloaded, installed, trusted, generated with, exported, or published merely because it appears in that document.

`sdxl-checkpoint-source-audit.json` records the separately approved checkpoint transfer and read-only inspection. Its status is `downloaded_untrusted`: the exact file size and SHA-256 match the mirror's repository-linked response, the safetensors header declares StabilityAI and CreativeML Open RAIL++-M, and ComfyUI exposes the checkpoint through `CheckpointLoaderSimple`. A dedicated SDXL workflow and exact component bundle have since passed read-only inspection without changing trust. The audit grants no trust or public authority; digest-bound user approval and acceptance authority are still required.

`acceptance-authority.example.json` is deliberately unapproved. It documents the shape of an authority decision but never authorizes backend/model use, downloads, a repository license, or publication. A real `acceptance-authority.json` is created only after explicit approval and must pin the fixed brief hash, backend, model hashes and licenses, output-redistribution status, repository license, holder, and any named install/download permission. A ComfyUI authority must additionally pin every component role, loader field, backend-visible name, filesystem identity token, byte size, SHA-256, source/license/redistribution decision, reviewed workflow SHA-256, and canonical bundle SHA-256.

Each accepted root package lives under `runs/<brief-id>/`; the three required immutable child packages live under `revisions/<brief-id>/`. Packages retain the original MCP final result, sanitized manifest, fixed brief, image artifacts, reviews, hashes, and observed environment metadata. Paths are relative. Mock/fixture markers, symlinks, private paths, credentials, hidden reasoning, and unrelated output files are forbidden.

The exporter requires the real run ID as an explicit confirmation. It copies bytes without re-encoding images and rejects missing previews, hash changes, reconstructed/mismatched MCP results, unapproved backend/model facts, component/workflow/bundle drift, and existing destinations. Child export additionally binds the parent run, selected round, image hash, parent manifest hash, and parent evidence hash.

Run the non-strict validator during implementation:

```powershell
python .\scripts\validate_acceptance_evidence.py
```

With no approved authority or retained runs it returns `ok: true`, zero counts, and `release_ready: false`. The release gate uses `--strict`; that mode requires exactly nine accepted root runs and the three fixture-declared child revisions. Passing proves package consistency and coverage, not objective image quality, performance, compatibility, or production readiness.
