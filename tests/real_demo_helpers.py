from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path


MODEL_ID = "local:1a4a27ae037d08ad44e98772"
MODEL_TOKEN = "model:89bf0283e0c284f8f84f8849035374bbdb60491e5a5665f801b3ec10b92d8b23"
FILESYSTEM_MODEL_TOKEN = "model:1a4a27ae037d08ad44e987720d07df0910fff0e1d3210378e6a4886cfc4f97a5"
BACKEND_MODEL_ID = "sd_xl_base_1.0.safetensors"
MODEL_SHA256 = "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"
WORKFLOW_SHA256 = "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e"
BUNDLE_SHA256 = "ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62"
WIDTH = 1024
HEIGHT = 1024
TIMESTAMP = "2026-07-24T10:00:00Z"
POSITIVE_PROMPT = (
    "A solitary white lighthouse on a black basalt sea stack at blue hour, "
    "complete structure visible, no people or lettering."
)
NEGATIVE_PROMPT = "people, text, watermark, cropped lighthouse, duplicate tower"
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
SEMANTIC_FIDELITY = {
    "required": True,
    "requested_medium": "decorative software product hero asset",
    "required_anchors": [
        "one complete lighthouse subject",
        "open copy-safe area for interface compositing",
    ],
    "forbidden_substitutions": ["paper-only planning workspace"],
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


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(scanline * HEIGHT))
        + _chunk(b"IEND", b"")
    )


def jpeg_bytes(label: str) -> bytes:
    return b"\xff\xd8\xff\xe0" + label.encode("ascii") + b"\xff\xd9"


def artifact(
    path: str,
    data: bytes,
    mime_type: str,
    width: int,
    height: int,
) -> dict[str, object]:
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
            "components": [
                {
                    "backend_model_id": BACKEND_MODEL_ID,
                    "byte_size": 6938078334,
                    "filesystem_identity_token": FILESYSTEM_MODEL_TOKEN,
                    "loader_class": "CheckpointLoaderSimple",
                    "loader_input": "ckpt_name",
                    "role": "primary_model",
                    "sha256": MODEL_SHA256,
                }
            ],
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
            "semantic_fidelity": SEMANTIC_FIDELITY,
        },
        "endpoint_identity": "endpoint:private-test",
        "identity_strength": "cryptographic",
        "intent": "private natural-language brief omitted from public evidence",
        "max_rounds": 1,
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
        "limb_separation": {
            "status": "not_applicable",
            "observation": "No human is present.",
        },
        "feet_and_contact": {
            "status": "not_applicable",
            "observation": "No human is present.",
        },
        "hands_and_held_objects": {
            "status": "not_applicable",
            "observation": "No human is present.",
        },
        "text_and_watermarks": {
            "status": "pass",
            "observation": "No text or watermark is visible.",
        },
    }


def review() -> dict[str, object]:
    return {
        "constraint_results": {
            "width": {
                "status": "pass",
                "observation": "The retained image is 1024 pixels wide.",
            },
            "height": {
                "status": "pass",
                "observation": "The retained image is 1024 pixels high.",
            },
            "generated_text": {
                "status": "pass",
                "observation": "No generated text is visible.",
            },
            "semantic_fidelity": {
                "status": "pass",
                "observation": "The decorative software hero retains its subject and compositing area.",
                "anchor_results": [
                    {
                        "anchor": anchor,
                        "status": "pass",
                        "observation": "The required hero anchor is retained.",
                    }
                    for anchor in SEMANTIC_FIDELITY["required_anchors"]
                ],
                "substitution_results": [
                    {
                        "substitution": substitution,
                        "status": "absent",
                        "observation": "The forbidden replacement is absent.",
                    }
                    for substitution in SEMANTIC_FIDELITY["forbidden_substitutions"]
                ],
            },
        },
        "critique": "Full-resolution review passed the retained public-demo boundary.",
        "hard_failures": [],
        "next_action": "finalize",
        "reviewed_at": TIMESTAMP,
        "round_number": 1,
        "scores": {name: 4 for name in RUBRIC},
        "visual_checks": visual_checks(),
    }


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
            "model": BACKEND_MODEL_ID,
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
        "compiled_prompt": {
            "positive_prompt": POSITIVE_PROMPT,
            "negative_prompt": NEGATIVE_PROMPT,
        },
        "generation_plan": {
            "profile": "ui-visual-asset",
            "style": None,
            "intent": "private natural-language brief omitted from public evidence",
            "positive_prompt": POSITIVE_PROMPT,
            "negative_prompt": NEGATIVE_PROMPT,
            "constraints": {
                "width": WIDTH,
                "height": HEIGHT,
                "generated_text": False,
                "semantic_fidelity": SEMANTIC_FIDELITY,
            },
            "parameters": {
                "seed": seed,
                "width": WIDTH,
                "height": HEIGHT,
                "steps": 30,
                "guidance_scale": 7.0,
                "sampler": "dpmpp_2m",
                "scheduler": "karras",
            },
            "max_rounds": 1,
            "upscale_policy": "off",
            "authorization_scope": "public_evidence",
            "route_token": "route:private-test",
            "model_choice": MODEL_ID,
            "backend": "comfyui",
            "endpoint_identity": "endpoint:private-test",
            "model_identity_token": MODEL_TOKEN,
            "identity_strength": "cryptographic",
            "workflow_template_id": "sdxl-txt2img",
            "workflow_template_version": 1,
            "prompt_compiler_id": "natural-v1",
            "prompt_compiler_version": 1,
        },
        "idempotency_key": "private-key",
        "image": image,
        "preview": preview,
        "round_number": 1,
        "seed": seed,
        "status": "generated",
    }


def _tool_call(
    sequence: int,
    name: str,
    result: dict[str, object],
) -> dict[str, object]:
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


def client_session(image_sha256: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "evidence_class": "named_client_session",
        "session_purpose": "golden_generation",
        "client": {
            "name": "codex",
            "version": "codex-cli 0.144.5",
            "session_mode": "ephemeral",
        },
        "installed_wheel": True,
        "hosted_client_session": True,
        "server": {
            "name": "local-gpu-imagegen",
            "version": "0.8.2",
            "protocol_version": "2024-11-05",
            "wheel_sha256": "a" * 64,
        },
        "started_at": TIMESTAMP,
        "completed_at": "2026-07-24T10:02:00Z",
        "tool_calls": [
            _tool_call(
                1,
                "local_gpu_imagegen_check",
                {"ready": True, "backend": "comfyui"},
            ),
            _tool_call(
                2,
                "local_gpu_start_run",
                {"run_id": "root-run", "state": "confirmed"},
            ),
            _tool_call(
                3,
                "local_gpu_generate_round",
                {
                    "run_id": "root-run",
                    "state": "generated",
                    "round_number": 1,
                    "image_sha256": image_sha256,
                },
            ),
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
    run_root = base / "private" / "root-run"
    docs = base / "docs"
    client_path = docs / "evidence" / "client-sessions" / "codex-v070.json"
    mcp_result_path = base / "private" / "mcp-final-result.json"
    authority_path = base / "authority.json"
    destination = docs / "demo" / "real"

    image_bytes = png_bytes(24, 72, 96)
    preview_bytes = jpeg_bytes("final-preview")
    selected_image = artifact("round-01.png", image_bytes, "image/png", WIDTH, HEIGHT)
    selected_preview = artifact(
        "round-01-preview.jpg",
        preview_bytes,
        "image/jpeg",
        768,
        432,
    )
    final_image = {**selected_image, "path": "final.png"}

    run_root.mkdir(parents=True)
    (run_root / "round-01.png").write_bytes(image_bytes)
    (run_root / "round-01-preview.jpg").write_bytes(preview_bytes)
    (run_root / "final.png").write_bytes(image_bytes)
    (run_root / "unrelated.tmp").write_text("must not export", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "manifest_revision": 6,
        "run_id": "root-run",
        "state": "finalized",
        "parent": None,
        "request": request(),
        "rounds": [round_record(selected_image, selected_preview, seed=4242)],
        "reviews": [review()],
        "final": {
            "round_number": 1,
            "summary": "Accepted after direct full-resolution review.",
            "finalized_at": "2026-07-24T10:03:00Z",
            "quality_status": "accepted",
            "path": "final.png",
            "image": final_image,
        },
    }
    write_json(run_root / "manifest.json", manifest)
    write_json(client_path, client_session(selected_image["sha256"]))
    write_json(
        mcp_result_path,
        {
            "ok": True,
            "run_id": "root-run",
            "state": "finalized",
            "final": manifest["final"],
        },
    )
    write_json(authority_path, authority())
    return run_root, client_path, mcp_result_path, authority_path, destination
