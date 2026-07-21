from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from pathlib import Path


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "acceptance" / "v1-briefs.json"
MODEL_SHA256 = "a" * 64
MODEL_ID = "approved-local-model"
TIMESTAMP = "2026-07-21T12:00:00Z"


def public_route() -> dict[str, object]:
    return {
        "authorization_scope": "public_evidence",
        "backend": "webui",
        "model_id": MODEL_ID,
        "sha256": MODEL_SHA256,
        "identity_strength": "cryptographic",
        "workflow_template_id": None,
        "workflow_template_version": None,
        "prompt_compiler_id": "sd15-tags-v1",
        "prompt_compiler_version": 1,
    }


def locked_route() -> dict[str, object]:
    return {
        **public_route(),
        "endpoint_identity": "endpoint:private",
        "identity_token": "model:private",
        "route_token": "route:private",
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path: Path, keys: list[str], value: object) -> None:
    document = read_json(path)
    target = document
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    write_json(path, document)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(width: int = 2, height: int = 2) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x33\x66\x99" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(scanlines)) + _chunk(b"IEND", b"")


def jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0acceptance-preview\xff\xd9"


def approved_authority(briefs_path: Path = FIXTURE_PATH) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "approved",
        "approved_at": TIMESTAMP,
        "briefs_sha256": sha256_file(briefs_path),
        "backend": {"type": "webui", "implementation": "Forge", "local": True},
        "models": [{
            "id": MODEL_ID,
            "source": "https://models.example/approved-local-model",
            "sha256": MODEL_SHA256,
            "license_id": "example-model-license",
            "license_url": "https://models.example/license",
            "output_redistribution_status": "approved",
            "expected_storage": "local WebUI checkpoint directory",
            "use_approved": True,
            "download_approved": False,
        }],
        "repository_license": "MIT",
        "copyright_holder": "Approved Holder",
        "installation_or_download": {"approved": False, "items": []},
    }


def observed_metadata(brief_id: str) -> dict[str, object]:
    return {
        "brief_id": brief_id,
        "host": {"name": "Codex", "version": "observed-test-version"},
        "backend": {"type": "webui", "implementation": "Forge", "version": "observed", "local": True},
        "model": {
            "id": MODEL_ID,
            "sha256": MODEL_SHA256,
            "source": "https://models.example/approved-local-model",
            "license_id": "example-model-license",
            "license_url": "https://models.example/license",
        },
        "environment": {
            "os": "Windows observed",
            "python": "3.12 observed",
            "gpu": "observed GPU",
            "cuda": "observed runtime",
        },
        "known_limitations": ["Acceptance records one observed local configuration."],
        "decision_summary": "Selected after an explicit visual review.",
    }


def _artifact(path: str, data: bytes, mime_type: str) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": 2,
        "height": 2,
        "mime_type": mime_type,
    }


def build_run_source(root: Path, brief: dict[str, object], *, revision: bool = False) -> Path:
    run_id = f"real-{'child' if revision else 'parent'}-{brief['id']}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    png = png_bytes()
    jpeg = jpeg_bytes()
    (run_dir / "round-01.png").write_bytes(png)
    (run_dir / "round-01-preview.jpg").write_bytes(jpeg)
    (run_dir / "final.png").write_bytes(png)
    (run_dir / "unrelated.tmp").write_text("must not be exported", encoding="utf-8")

    image = _artifact("round-01.png", png, "image/png")
    preview = _artifact("round-01-preview.jpg", jpeg, "image/jpeg")
    final_image = _artifact("final.png", png, "image/png")
    review: dict[str, object] = {
        "round_number": 1,
        "scores": {"composition": 4},
        "hard_failures": [],
        "constraint_results": {"generated_text": {"status": "pass", "observation": "No text observed."}},
        "critique": "Observed real preview passed the recorded acceptance boundary.",
        "next_action": "finalize",
        "reviewed_at": TIMESTAMP,
    }
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "finalized",
        "last_stable_state": "finalized",
        "parent": None,
        "request": {
            "profile": brief["profile"],
            "style": brief["style"],
            "subtype": brief["subtype"],
            "intent": brief["brief"],
            "model_choice": MODEL_ID,
            "backend": "webui",
            "max_rounds": 2,
            "route": locked_route(),
        },
        "attempts": [{"status": "completed", "started_at": TIMESTAMP, "round_number": 1}],
        "rounds": [{
            "round_number": 1,
            "status": "generated",
            "seed": 42,
            "backend": "webui",
            "backend_result": {"backend": "webui", "model": MODEL_ID, "path": "round-01.png"},
            "image": image,
            "preview": preview,
            "warnings": [],
        }],
        "reviews": [review],
        "masks": [],
        "warnings": [],
        "final": {
            "round_number": 1,
            "summary": "Accepted after direct visual review.",
            "finalized_at": TIMESTAMP,
            "quality_status": "accepted",
            "path": "final.png",
            "image": final_image,
        },
    }
    if revision:
        preserve = [
            {"target": target, "strength": "hard"}
            for target in brief["revision"]["preserve"]
        ]
        manifest["parent"] = {"run_id": f"real-parent-{brief['id']}", "round": 1, "image_sha256": image["sha256"]}
        manifest["revision"] = {
            "contract": {"preserve": preserve, "change": [brief["revision"]["change"]]},
            "edit_mode": "img2img",
            "denoising_strength": 0.25,
            "source_image": copy.deepcopy(image),
        }
        review["preservation_results"] = [
            {"target": item["target"], "status": "preserved", "observation": "Observed as preserved."}
            for item in preserve
        ]
    write_json(run_dir / "manifest.json", manifest)
    write_json(run_dir / "mcp-final-result.json", {
        "run_id": run_id,
        "state": "finalized",
        "final": copy.deepcopy(manifest["final"]),
    })
    return run_dir


def _write_package(package: Path, brief: dict[str, object], *, revision: bool, evidence_root: Path) -> None:
    package.mkdir(parents=True)
    png = png_bytes()
    jpeg = jpeg_bytes()
    (package / "round-01.png").write_bytes(png)
    (package / "round-01-preview.jpg").write_bytes(jpeg)
    (package / "final.png").write_bytes(png)
    image = _artifact("round-01.png", png, "image/png")
    preview = _artifact("round-01-preview.jpg", jpeg, "image/jpeg")
    final_image = _artifact("final.png", png, "image/png")
    run_id = f"real-{'child' if revision else 'parent'}-{brief['id']}"
    review: dict[str, object] = {
        "round_number": 1,
        "scores": {"composition": 4},
        "hard_failures": [],
        "constraint_results": {"generated_text": {"status": "pass", "observation": "No text observed."}},
        "critique": "Direct visual review accepted this retained artifact.",
        "next_action": "finalize",
        "reviewed_at": TIMESTAMP,
    }
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "finalized",
        "parent": None,
        "request": {
            "profile": brief["profile"],
            "style": brief["style"],
            "subtype": brief["subtype"],
            "model_choice": MODEL_ID,
            "backend": "webui",
            "max_rounds": 2,
            "route": public_route(),
        },
        "rounds": [{
            "round_number": 1,
            "status": "generated",
            "seed": 42,
            "backend": "webui",
            "backend_result": {"backend": "webui", "model": MODEL_ID, "path": "round-01.png"},
            "image": image,
            "preview": preview,
            "warnings": [],
        }],
        "reviews": [review],
        "masks": [],
        "warnings": [],
        "final": {
            "round_number": 1,
            "finalized_at": TIMESTAMP,
            "quality_status": "accepted",
            "path": "final.png",
            "image": final_image,
        },
    }
    if revision:
        parent_package = evidence_root / "runs" / str(brief["id"])
        parent_manifest = parent_package / "manifest.json"
        parent_evidence = parent_package / "evidence.json"
        parent_manifest_data = read_json(parent_manifest)
        parent_image = parent_manifest_data["rounds"][0]["image"]
        preserve = [{"target": target, "strength": "hard"} for target in brief["revision"]["preserve"]]
        manifest["parent"] = {
            "run_id": parent_manifest_data["run_id"],
            "round": 1,
            "image_sha256": parent_image["sha256"],
        }
        manifest["revision"] = {
            "contract": {"preserve": preserve, "change": [brief["revision"]["change"]]},
            "edit_mode": "img2img",
            "denoising_strength": 0.25,
            "source_image": copy.deepcopy(parent_image),
        }
        review["preservation_results"] = [
            {"target": item["target"], "status": "preserved", "observation": "Observed as preserved."}
            for item in preserve
        ]
        write_json(package / "parent-evidence.json", {
            "run_id": parent_manifest_data["run_id"],
            "round": 1,
            "image_sha256": parent_image["sha256"],
            "manifest_sha256": sha256_file(parent_manifest),
            "evidence_sha256": sha256_file(parent_evidence),
        })
        if brief["id"] == "presentation-cover":
            (package / "mask-01.png").write_bytes(png)
            (package / "mask-01-overlay.jpg").write_bytes(jpeg)
            manifest["revision"]["edit_mode"] = "inpaint"
            manifest["masks"] = [{
                "mask_id": "mask-01",
                "source": "geometry",
                "source_image_sha256": parent_image["sha256"],
                "mask_sha256": sha256_file(package / "mask-01.png"),
                "geometry": [{"type": "rectangle", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}],
                "feather_pixels": 0,
                "mask_path": "mask-01.png",
                "overlay_path": "mask-01-overlay.jpg",
                "confirmed": True,
                "confirmed_at": TIMESTAMP,
            }]
            manifest["rounds"][0]["mask_id"] = "mask-01"
    write_json(package / "brief.json", brief)
    write_json(package / "manifest.json", manifest)
    write_json(package / "mcp-final-result.json", {"run_id": run_id, "state": "finalized", "final": manifest["final"]})
    metadata = observed_metadata(str(brief["id"]))
    write_json(package / "evidence.json", {
        "schema_version": 1,
        "evidence_class": "real-codex-mcp-run",
        "brief_id": brief["id"],
        "run_id": run_id,
        "host": metadata["host"],
        "profile": brief["profile"],
        "style": brief["style"],
        "backend": metadata["backend"],
        "model": metadata["model"],
        "route": public_route(),
        "environment": metadata["environment"],
        "started_at": TIMESTAMP,
        "completed_at": TIMESTAMP,
        "files": {"brief": "brief.json", "manifest": "manifest.json", "mcp_final_result": "mcp-final-result.json", "final": "final.png"},
        "selected_round": 1,
        "quality_status": "accepted",
        "known_limitations": metadata["known_limitations"],
        "decision_summary": metadata["decision_summary"],
    })


def build_complete_matrix(root: Path, briefs_path: Path = FIXTURE_PATH) -> Path:
    evidence_root = root / "evidence"
    write_json(evidence_root / "acceptance-authority.json", approved_authority(briefs_path))
    briefs = read_json(briefs_path)
    for brief in briefs:
        _write_package(evidence_root / "runs" / brief["id"], brief, revision=False, evidence_root=evidence_root)
    for brief in briefs:
        if "revision" in brief:
            _write_package(evidence_root / "revisions" / brief["id"], brief, revision=True, evidence_root=evidence_root)
    return evidence_root
