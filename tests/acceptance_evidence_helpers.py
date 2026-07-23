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
TWO_STAGE_TEMPLATE_ID = "sdxl-two-stage-copy-subject"


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
        "component_bundle": None,
        "component_bundle_sha256": None,
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


def rgb_png_bytes(width: int, height: int, pixels: bytes) -> bytes:
    if len(pixels) != width * height * 3:
        raise ValueError("RGB fixture byte count does not match dimensions")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row_size = width * 3
    scanlines = b"".join(
        b"\x00" + pixels[offset:offset + row_size]
        for offset in range(0, len(pixels), row_size)
    )
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


def two_stage_layout() -> dict[str, object]:
    return {
        "mode": "copy-subject-two-stage-v1",
        "canvas": {"width": 640, "height": 320},
        "copy_protected_rect": {"x": 0, "y": 0, "width": 224, "height": 320},
        "subject_mask_rect": {"x": 304, "y": 16, "width": 320, "height": 288},
        "feather_pixels": 0,
        "vae_grow_mask_by": 0,
    }


def passing_stage_checks() -> dict[str, object]:
    observations = {
        "base_copy_space": "Left copy space is dark and low-detail.",
        "base_subject_absent": "No telescope or focal machinery appears in the base.",
        "final_subject_inside_mask": "One complete telescope stays inside the mask.",
        "final_safe_margins": "All telescope edges and tripod feet remain visible.",
        "final_forbidden_content": "No text, people, controls, or anatomy artifacts appear.",
        "feather_transition": "The mask boundary is visually coherent.",
        "pixel_preservation": "Machine report records zero mismatches.",
    }
    return {
        name: {"status": "pass", "observation": observation}
        for name, observation in observations.items()
    }


def build_two_stage_run_source(
    root: Path,
    brief: dict[str, object],
) -> tuple[Path, dict[str, object], dict[str, object]]:
    from local_gpu_imagegen.model_identity import build_component_bundle
    from local_gpu_imagegen.png_pixels import compare_protected_pixels, validate_saved_soft_mask
    from local_gpu_imagegen.two_stage_layout import build_control_identity

    run_dir = build_run_source(root, brief)
    layout = two_stage_layout()
    width = int(layout["canvas"]["width"])
    height = int(layout["canvas"]["height"])
    subject = layout["subject_mask_rect"]

    base_pixels = bytearray(b"\x18\x30\x48" * (width * height))
    final_pixels = bytearray(base_pixels)
    mask_pixels = bytearray(width * height * 3)
    for y in range(int(subject["y"]), int(subject["y"]) + int(subject["height"])):
        for x in range(int(subject["x"]), int(subject["x"]) + int(subject["width"])):
            offset = (y * width + x) * 3
            final_pixels[offset:offset + 3] = b"\xa0\x70\x38"
            mask_pixels[offset:offset + 3] = b"\xff\xff\xff"

    stage_bytes = {
        "round-01-base.png": rgb_png_bytes(width, height, bytes(base_pixels)),
        "round-01-mask.png": rgb_png_bytes(width, height, bytes(mask_pixels)),
        "round-01.png": rgb_png_bytes(width, height, bytes(final_pixels)),
        "final.png": rgb_png_bytes(width, height, bytes(final_pixels)),
    }
    for name, data in stage_bytes.items():
        (run_dir / name).write_bytes(data)

    workflow = {
        "template_id": TWO_STAGE_TEMPLATE_ID,
        "template_version": 1,
        "sha256": "d" * 64,
    }
    identity = {
        "role": "primary_model",
        "loader_class": "CheckpointLoaderSimple",
        "loader_input": "ckpt_name",
        "backend_model_id": "approved-local-model.safetensors",
        "filesystem_identity_token": "model:" + "b" * 64,
        "sha256": MODEL_SHA256,
        "byte_size": 100,
    }
    bundle = build_component_bundle([identity], workflow)
    control_sha256 = build_control_identity(layout, workflow["sha256"], "base-subject-v1")
    route = {
        **locked_route(),
        "backend": "comfyui",
        "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
        "workflow_template_version": 1,
        "prompt_compiler_id": "natural-v1",
        "component_bundle": bundle,
        "component_bundle_sha256": bundle["bundle_sha256"],
        "control_sha256": control_sha256,
    }

    def artifact(path: str) -> dict[str, object]:
        return _artifact(path, stage_bytes[path], "image/png") | {
            "width": width,
            "height": height,
        }

    base = artifact("round-01-base.png")
    mask = artifact("round-01-mask.png")
    stage_final = artifact("round-01.png")
    accepted_final = artifact("final.png")
    pixel_report = compare_protected_pixels(
        run_dir / "round-01-base.png",
        run_dir / "round-01.png",
        layout,
    )
    validate_saved_soft_mask(run_dir / "round-01-mask.png", layout)

    manifest = read_json(run_dir / "manifest.json")
    manifest["request"].update({
        "backend": "comfyui",
        "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
        "constraints": {"two_stage_layout": layout},
        "route": route,
    })
    manifest["stage_budget"] = {"maximum": 4, "consumed": 2}
    round_value = manifest["rounds"][0]
    round_value.update({
        "backend": "comfyui",
        "seed": 42,
        "backend_result": {
            "backend": "comfyui",
            "model": MODEL_ID,
            "path": "round-01.png",
            "subject_seed": 43,
            "control_sha256": control_sha256,
            "component_bundle_sha256": bundle["bundle_sha256"],
        },
        "image": stage_final,
        "stages": [
            {"role": "base", "seed": 42, "image": base},
            {"role": "subject", "seed": 43, "image": stage_final},
        ],
        "mask_artifact": mask,
        "pixel_preservation": pixel_report,
        "stage_units": 2,
    })
    manifest["reviews"][0]["stage_checks"] = passing_stage_checks()
    manifest["final"].update({"path": "final.png", "image": accepted_final})
    write_json(run_dir / "manifest.json", manifest)
    write_json(run_dir / "mcp-final-result.json", {
        "run_id": manifest["run_id"],
        "state": "finalized",
        "final": copy.deepcopy(manifest["final"]),
    })

    authority = approved_authority()
    authority["backend"] = {"type": "comfyui", "implementation": "ComfyUI", "local": True}
    authority["models"][0].update({
        "components": [{
            **identity,
            "source": "https://models.example/approved-local-model.safetensors",
            "license_id": "example-model-license",
            "license_url": "https://models.example/license",
            "output_redistribution_status": "approved",
        }],
        "workflow": workflow,
        "component_bundle_sha256": bundle["bundle_sha256"],
    })
    metadata = observed_metadata(str(brief["id"]))
    metadata["backend"] = {
        "type": "comfyui",
        "implementation": "ComfyUI",
        "version": "observed",
        "local": True,
    }
    return run_dir, authority, metadata


def add_second_two_stage_round(run_dir: Path) -> None:
    from local_gpu_imagegen.png_pixels import compare_protected_pixels, validate_saved_soft_mask
    from local_gpu_imagegen.two_stage_layout import derive_subject_seed

    manifest = read_json(run_dir / "manifest.json")
    layout = manifest["request"]["constraints"]["two_stage_layout"]
    width = int(layout["canvas"]["width"])
    height = int(layout["canvas"]["height"])
    subject = layout["subject_mask_rect"]

    base_pixels = bytearray(b"\x20\x38\x50" * (width * height))
    final_pixels = bytearray(base_pixels)
    mask_pixels = bytearray(width * height * 3)
    for y in range(int(subject["y"]), int(subject["y"]) + int(subject["height"])):
        for x in range(int(subject["x"]), int(subject["x"]) + int(subject["width"])):
            offset = (y * width + x) * 3
            final_pixels[offset:offset + 3] = b"\xb0\x80\x48"
            mask_pixels[offset:offset + 3] = b"\xff\xff\xff"

    stage_bytes = {
        "round-02-base.png": rgb_png_bytes(width, height, bytes(base_pixels)),
        "round-02-mask.png": rgb_png_bytes(width, height, bytes(mask_pixels)),
        "round-02.png": rgb_png_bytes(width, height, bytes(final_pixels)),
        "round-02-preview.jpg": jpeg_bytes(),
        "final.png": rgb_png_bytes(width, height, bytes(final_pixels)),
    }
    for name, data in stage_bytes.items():
        (run_dir / name).write_bytes(data)

    def artifact(path: str, mime_type: str = "image/png") -> dict[str, object]:
        return _artifact(path, stage_bytes[path], mime_type) | {
            "width": width,
            "height": height,
        }

    base_seed = 100
    subject_seed = derive_subject_seed(base_seed)
    base = artifact("round-02-base.png")
    mask = artifact("round-02-mask.png")
    stage_final = artifact("round-02.png")
    preview = artifact("round-02-preview.jpg", "image/jpeg")
    accepted_final = artifact("final.png")
    pixel_report = compare_protected_pixels(
        run_dir / "round-02-base.png",
        run_dir / "round-02.png",
        layout,
    )
    validate_saved_soft_mask(run_dir / "round-02-mask.png", layout)
    control_sha256 = manifest["request"]["route"]["control_sha256"]
    component_bundle_sha256 = manifest["request"]["route"]["component_bundle_sha256"]

    manifest["rounds"].append({
        "round_number": 2,
        "status": "generated",
        "seed": base_seed,
        "backend": "comfyui",
        "backend_result": {
            "backend": "comfyui",
            "model": MODEL_ID,
            "path": "round-02.png",
            "subject_seed": subject_seed,
            "control_sha256": control_sha256,
            "component_bundle_sha256": component_bundle_sha256,
        },
        "image": stage_final,
        "preview": preview,
        "warnings": [],
        "stages": [
            {"role": "base", "seed": base_seed, "image": base},
            {"role": "subject", "seed": subject_seed, "image": stage_final},
        ],
        "mask_artifact": mask,
        "pixel_preservation": pixel_report,
        "stage_units": 2,
    })
    second_review = copy.deepcopy(manifest["reviews"][0])
    second_review["round_number"] = 2
    manifest["reviews"].append(second_review)
    manifest["attempts"].append({
        "status": "completed",
        "started_at": TIMESTAMP,
        "round_number": 2,
    })
    manifest["stage_budget"]["consumed"] = 4
    manifest["final"].update({
        "round_number": 2,
        "path": "final.png",
        "image": accepted_final,
    })
    write_json(run_dir / "manifest.json", manifest)
    write_json(run_dir / "mcp-final-result.json", {
        "run_id": manifest["run_id"],
        "state": "finalized",
        "final": copy.deepcopy(manifest["final"]),
    })


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
