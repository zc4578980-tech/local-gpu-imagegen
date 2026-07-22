from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path


MODEL_ID = "local:1a4a27ae037d08ad44e98772"
MODEL_TOKEN = "model:1a4a27ae037d08ad44e987720d07df0910fff0e1d3210378e6a4886cfc4f97a5"
MODEL_SHA256 = "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"
WORKFLOW_SHA256 = "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e"
BUNDLE_SHA256 = "ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62"
WIDTH = 1280
HEIGHT = 720
TIMESTAMP = "2026-07-22T10:00:00Z"
PRESERVE_TARGETS = ("composition", "primary_motif", "left_safe_area")
RUBRIC = {
    name: {"critical": True, "weight": 2}
    for name in (
        "dimensions",
        "aspect_ratio",
        "crop_tolerance",
        "palette_compatibility",
        "style_system_consistency",
        "layout_composability",
        "edge_quality",
    )
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def png_bytes(red: int, green: int, blue: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    scanline = b"\x00" + bytes((red, green, blue)) * WIDTH
    scanlines = scanline * HEIGHT
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


def jpeg_bytes(label: str) -> bytes:
    return b"\xff\xd8\xff\xe0" + label.encode("ascii") + b"\xff\xd9"


def artifact(path: str, data: bytes, mime_type: str, width: int, height: int) -> dict[str, object]:
    return {
        "path": path,
        "sha256": sha256_bytes(data),
        "width": width,
        "height": height,
        "mime_type": mime_type,
    }


def route() -> dict[str, object]:
    return {
        "authorization_scope": "public_evidence",
        "backend": "comfyui",
        "endpoint_identity": "endpoint:private-test",
        "identity_strength": "cryptographic",
        "identity_token": MODEL_TOKEN,
        "model_id": MODEL_ID,
        "sha256": MODEL_SHA256,
        "workflow_template_id": "sdxl-txt2img",
        "workflow_template_version": 1,
        "component_bundle": {
            "bundle_sha256": BUNDLE_SHA256,
            "workflow": {
                "template_id": "sdxl-txt2img",
                "template_version": 1,
                "sha256": WORKFLOW_SHA256,
            },
        },
        "component_bundle_sha256": BUNDLE_SHA256,
        "prompt_compiler_id": "natural-v1",
        "prompt_compiler_version": 1,
        "route_token": "route:private-test",
        "width": WIDTH,
        "height": HEIGHT,
        "recommended_settings": {
            "steps": 30,
            "guidance": 7.0,
            "sampler": "dpmpp_2m",
            "scheduler": "karras",
        },
    }


def request() -> dict[str, object]:
    return {
        "authorization_scope": "public_evidence",
        "available_backends": ["comfyui"],
        "backend": "comfyui",
        "constraints": {
            "width": WIDTH,
            "height": HEIGHT,
            "generated_text": False,
        },
        "endpoint_identity": "endpoint:private-test",
        "identity_strength": "cryptographic",
        "intent": "private natural-language brief omitted from public evidence",
        "max_rounds": 2,
        "merged_profile": {"rubric": RUBRIC},
        "model_choice": MODEL_ID,
        "model_identity_token": MODEL_TOKEN,
        "profile": "ui-visual-asset",
        "prompt_compiler_id": "natural-v1",
        "prompt_compiler_version": 1,
        "route": route(),
        "route_token": "route:private-test",
        "style": None,
        "subtype": "hero",
        "upscale_policy": "off",
        "workflow_template_id": "sdxl-txt2img",
        "workflow_template_version": 1,
    }


def visual_checks() -> dict[str, object]:
    return {
        "full_resolution_inspected": True,
        "prominent_human": False,
        "limb_separation": {"status": "not_applicable", "observation": "No human is present."},
        "feet_and_contact": {"status": "not_applicable", "observation": "No human is present."},
        "hands_and_held_objects": {"status": "not_applicable", "observation": "No human is present."},
        "text_and_watermarks": {"status": "pass", "observation": "No text or watermark is visible."},
    }


def review(round_number: int, *, child: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "constraint_results": {
            "generated_text": {"status": "pass", "observation": "No generated text is visible."}
        },
        "critique": "Full-resolution review passed the retained public-demo boundary.",
        "hard_failures": [],
        "next_action": "finalize",
        "reviewed_at": TIMESTAMP,
        "round_number": round_number,
        "scores": {name: 4 for name in RUBRIC},
        "visual_checks": visual_checks(),
    }
    if child:
        value["preservation_results"] = [
            {
                "target": target,
                "status": "preserved",
                "observation": f"{target} remains visibly consistent with the parent.",
            }
            for target in PRESERVE_TARGETS
        ]
    return value


def round_record(
    image: dict[str, object],
    preview: dict[str, object],
    *,
    seed: int,
) -> dict[str, object]:
    return {
        "action": "initial",
        "backend": "comfyui",
        "backend_result": {
            "backend": "comfyui",
            "endpoint_identity": "endpoint:private-test",
            "guidance_scale": 7.0,
            "height": HEIGHT,
            "mode": "txt2img",
            "model": MODEL_ID,
            "model_identity_token": MODEL_TOKEN,
            "ok": True,
            "path": image["path"],
            "prompt_compiler_id": "natural-v1",
            "prompt_compiler_version": 1,
            "sampler": "dpmpp_2m",
            "scheduler": "karras",
            "seed": seed,
            "steps": 30,
            "width": WIDTH,
            "workflow_job_id": "private-job-id",
            "workflow_template_id": "sdxl-txt2img",
            "workflow_template_version": 1,
        },
        "compiled_prompt": {"positive": "private", "negative": "private"},
        "generation_plan": {
            "positive_prompt": "private",
            "negative_prompt": "private",
            "parameters": {"steps": 30, "guidance_scale": 7.0},
        },
        "idempotency_key": "private-key",
        "image": image,
        "preview": preview,
        "round_number": 1,
        "seed": seed,
        "status": "generated",
    }


def client_session() -> dict[str, object]:
    def call(sequence: int, name: str, result: dict[str, object]) -> dict[str, object]:
        encoded = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return {
            "sequence": sequence,
            "name": name,
            "result": result,
            "result_sha256": hashlib.sha256(encoded).hexdigest(),
        }

    return {
        "schema_version": "1.0",
        "evidence_class": "named_client_session",
        "client": {
            "name": "codex",
            "version": "codex-cli 0.144.5",
            "session_mode": "ephemeral",
        },
        "installed_wheel": True,
        "hosted_client_session": True,
        "server": {
            "name": "local-gpu-imagegen",
            "version": "0.6.1",
            "protocol_version": "2024-11-05",
            "wheel_sha256": "a" * 64,
        },
        "started_at": TIMESTAMP,
        "completed_at": "2026-07-22T10:02:00Z",
        "tool_calls": [
            call(1, "local_gpu_imagegen_check", {"ready": True, "backend": "comfyui"}),
            call(2, "local_gpu_get_run", {"run_id": "child-run", "state": "finalized"}),
        ],
        "sanitization": {
            "prompts_omitted": True,
            "account_identifiers_omitted": True,
            "credentials_omitted": True,
            "machine_paths_omitted": True,
            "raw_transcript_retained": False,
        },
    }


def authority() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "approved",
        "approved_at": TIMESTAMP,
        "backend": {"type": "comfyui", "implementation": "ComfyUI", "local": True},
        "models": [
            {
                "id": MODEL_ID,
                "source": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
                "sha256": MODEL_SHA256,
                "license_id": "CreativeML Open RAIL++-M",
                "license_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
                "output_redistribution_status": "approved",
                "use_approved": True,
                "download_approved": False,
                "component_bundle_sha256": BUNDLE_SHA256,
                "workflow": {
                    "template_id": "sdxl-txt2img",
                    "template_version": 1,
                    "sha256": WORKFLOW_SHA256,
                },
            }
        ],
        "repository_license": "MIT",
        "copyright_holder": "Capricorn",
        "installation_or_download": {"approved": False, "items": []},
    }


def write_source_fixture(base: Path) -> tuple[Path, Path, Path, Path, Path]:
    root_run = base / "private" / "root-run"
    child_run = base / "private" / "child-run"
    docs = base / "docs"
    client_path = docs / "evidence" / "client-sessions" / "codex-v061.json"
    authority_path = base / "authority.json"
    destination = docs / "demo" / "real"

    before = png_bytes(24, 72, 96)
    after = png_bytes(160, 88, 72)
    before_preview = jpeg_bytes("before-preview")
    after_preview = jpeg_bytes("after-preview")
    root_image = artifact("round-01.png", before, "image/png", WIDTH, HEIGHT)
    root_preview = artifact("round-01-preview.jpg", before_preview, "image/jpeg", 768, 432)
    child_image = artifact("round-01.png", after, "image/png", WIDTH, HEIGHT)
    child_preview = artifact("round-01-preview.jpg", after_preview, "image/jpeg", 768, 432)

    root_run.mkdir(parents=True)
    (root_run / "round-01.png").write_bytes(before)
    (root_run / "round-01-preview.jpg").write_bytes(before_preview)
    (root_run / "unrelated.tmp").write_text("must not export", encoding="utf-8")
    root_manifest = {
        "schema_version": 1,
        "manifest_revision": 4,
        "run_id": "root-run",
        "state": "reviewed",
        "parent": None,
        "request": request(),
        "rounds": [round_record(root_image, root_preview, seed=4242)],
        "reviews": [review(1, child=False)],
        "final": None,
    }
    write_json(root_run / "manifest.json", root_manifest)

    child_run.mkdir(parents=True)
    (child_run / "round-01.png").write_bytes(after)
    (child_run / "round-01-preview.jpg").write_bytes(after_preview)
    (child_run / "final.png").write_bytes(after)
    child_manifest = {
        "schema_version": 1,
        "manifest_revision": 6,
        "run_id": "child-run",
        "state": "finalized",
        "parent": {
            "run_id": "root-run",
            "round": 1,
            "image_sha256": root_image["sha256"],
        },
        "revision": {
            "contract": {
                "preserve": [
                    {"target": target, "strength": "hard"}
                    for target in PRESERVE_TARGETS
                ],
                "change": ["palette_and_lighting"],
            },
            "edit_mode": "prompt-refine",
            "denoising_strength": None,
            "source_image": {
                **root_image,
                "path": "parent-source.png",
            },
        },
        "request": request(),
        "rounds": [round_record(child_image, child_preview, seed=4242)],
        "reviews": [review(1, child=True)],
        "final": {
            "round_number": 1,
            "summary": "Accepted after direct full-resolution review.",
            "finalized_at": "2026-07-22T10:03:00Z",
            "quality_status": "accepted",
            "path": "final.png",
            "image": {**child_image, "path": "final.png"},
        },
    }
    write_json(child_run / "manifest.json", child_manifest)
    write_json(client_path, client_session())
    write_json(authority_path, authority())
    return root_run, child_run, client_path, authority_path, destination


def fake_showcase(before: Path, after: Path, output: Path) -> None:
    output.write_bytes(
        b"GIF89a" + hashlib.sha256(before.read_bytes() + after.read_bytes()).digest()
    )
