from __future__ import annotations

import base64
import binascii
import copy
import json
import os
import re
import stat
from pathlib import Path

from ..errors import ArtifactError, ConflictError, ValidationError
from ..model_identity import identity_token, validate_discovery_record
from .base import BoundedJsonClient


MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_WEBUI_RESPONSE_BYTES = 48 * 1024 * 1024
MAX_WEBUI_REQUEST_BYTES = 128 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MODES = frozenset({"txt2img", "img2img", "inpaint"})


class WebUIAdapter:
    backend_id = "webui"

    def __init__(
        self,
        base_url: str,
        *,
        lan_confirmation: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.client = BoundedJsonClient(
            base_url,
            lan_confirmation=lan_confirmation,
            timeout=timeout,
            max_bytes=MAX_WEBUI_RESPONSE_BYTES,
            max_request_bytes=MAX_WEBUI_REQUEST_BYTES,
        )
        self.base_url = self.client.base_url
        self.endpoint_identity = self.client.endpoint_identity

    def probe(self) -> dict[str, object]:
        options = self.client.get_json("/sdapi/v1/options")
        version_value = self.client.get_json("/sdapi/v1/version")
        if not isinstance(options, dict) or not isinstance(version_value, (dict, str)):
            raise ArtifactError(
                "invalid_backend_response",
                "WebUI probe returned an invalid response.",
            )
        if isinstance(version_value, dict):
            version = version_value.get("version")
        else:
            version = version_value
        if version is not None and not isinstance(version, str):
            raise ArtifactError(
                "invalid_backend_response",
                "WebUI version must be a string or null.",
            )
        implementation = (
            "Forge"
            if "forge" in json.dumps(version_value, sort_keys=True).lower()
            else "AUTOMATIC1111"
        )
        return {
            "backend": self.backend_id,
            "implementation": implementation,
            "version": version,
            "endpoint_identity": self.endpoint_identity,
            "endpoint_class": self.client.endpoint_class,
            "loaded_model": options.get("sd_model_checkpoint"),
            "ready": True,
        }

    def discover(self) -> list[dict[str, object]]:
        value = self.client.get_json("/sdapi/v1/sd-models")
        if not isinstance(value, list):
            raise ArtifactError(
                "invalid_backend_response",
                "WebUI model inventory must be an array.",
            )
        records: list[dict[str, object]] = []
        for item in value:
            records.append(self._discovery_record(item))
        records.sort(key=lambda record: str(record["backend_model_id"]))
        return records

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        normalized = _validate_generation_request(request, self.endpoint_identity)
        requested_model = normalized["model"]
        assert isinstance(requested_model, dict)
        requested_token = requested_model.get("identity_token")
        if not isinstance(requested_token, str):
            raise ConflictError(
                "backend_model_mismatch",
                "Confirmed WebUI model identity token is missing.",
            )

        inventory = self.discover()
        selected = next(
            (
                record
                for record in inventory
                if record["backend_model_id"]
                == requested_model["backend_model_id"]
            ),
            None,
        )
        if (
            selected is None
            or selected["identity_token"] != requested_token
            or identity_token(requested_model) != requested_token
        ):
            raise ConflictError(
                "backend_model_mismatch",
                "Confirmed WebUI model is not currently available with the same identity.",
            )

        options = self.client.get_json("/sdapi/v1/options")
        if not isinstance(options, dict) or not isinstance(
            options.get("sd_model_checkpoint"), str
        ):
            raise ArtifactError(
                "invalid_backend_response",
                "WebUI loaded-model response is invalid.",
            )
        payload = _generation_payload(normalized, selected)
        endpoint = (
            "/sdapi/v1/txt2img"
            if normalized["mode"] == "txt2img"
            else "/sdapi/v1/img2img"
        )
        response = self.client.post_json(endpoint, payload)
        image_bytes, info = _validated_response(response, selected, normalized["seed"])
        output_path = Path(str(normalized["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return {
            "ok": True,
            "path": str(output_path.resolve()),
            "backend": self.backend_id,
            "mode": normalized["mode"],
            "webui_url": self.base_url,
            "model": selected["backend_model_id"],
            "endpoint_identity": self.endpoint_identity,
            "model_identity_token": selected["identity_token"],
            "identity_strength": selected["identity_strength"],
            "workflow_template_id": None,
            "workflow_template_version": None,
            "prompt_compiler_id": normalized["prompt_compiler_id"],
            "prompt_compiler_version": normalized["prompt_compiler_version"],
            "width": normalized["width"],
            "height": normalized["height"],
            "steps": normalized["steps"],
            "guidance_scale": normalized["guidance_scale"],
            "strength": normalized["strength"],
            "seed": info.get("seed", normalized["seed"]),
        }

    def cancel_or_query(
        self,
        job_id: str,
        *,
        cancel: bool = False,
    ) -> dict[str, object]:
        del cancel
        return {
            "job_id": job_id,
            "state": "unsupported",
            "cancel_supported": False,
        }

    def _discovery_record(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ArtifactError(
                "invalid_backend_response",
                "WebUI model entry must be an object.",
            )
        title = value.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ArtifactError(
                "invalid_backend_response",
                "WebUI model entry requires a title.",
            )
        digest_value = value.get("sha256")
        digest = (
            digest_value.lower()
            if isinstance(digest_value, str)
            and SHA256_PATTERN.fullmatch(digest_value.lower()) is not None
            else None
        )
        backend_hash = value.get("hash")
        model_name = value.get("model_name")
        filename = value.get("filename")
        file_format = Path(filename).suffix.lower() if isinstance(filename, str) else Path(title.split(" [", 1)[0]).suffix.lower()
        byte_size = value.get("size")
        if type(byte_size) is not int or byte_size < 0:
            byte_size = None
        record = validate_discovery_record({
            "backend": self.backend_id,
            "endpoint_identity": self.endpoint_identity,
            "backend_model_id": title.strip(),
            "format": file_format or "unknown",
            "byte_size": byte_size,
            "modified_ns": None,
            "sha256": digest,
            "identity_strength": "cryptographic" if digest is not None else "backend_binding",
            "metadata": {
                "model_name": model_name.strip()
                if isinstance(model_name, str) and model_name.strip()
                else title.split(" [", 1)[0],
                "backend_hash": backend_hash
                if isinstance(backend_hash, str) and backend_hash
                else None,
            },
        })
        record["identity_token"] = identity_token(record)
        return record


def _validate_generation_request(
    value: object,
    endpoint_identity: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("invalid_backend_request", "WebUI generation request must be an object.")
    required = {
        "backend",
        "model",
        "mode",
        "positive_prompt",
        "negative_prompt",
        "width",
        "height",
        "steps",
        "guidance_scale",
        "sampler",
        "seed",
        "source_path",
        "mask_path",
        "strength",
        "output_path",
        "prompt_compiler_id",
        "prompt_compiler_version",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValidationError(
            "invalid_backend_request",
            "WebUI generation request is incomplete.",
            {"fields": missing},
        )
    if value["backend"] != "webui":
        raise ValidationError("invalid_backend_request", "WebUI adapter requires backend webui.")
    model = value["model"]
    if not isinstance(model, dict):
        raise ValidationError("invalid_backend_request", "WebUI model must be an identity object.")
    validated_model = validate_discovery_record(model)
    if validated_model["endpoint_identity"] != endpoint_identity:
        raise ConflictError(
            "backend_model_mismatch",
            "Confirmed model belongs to a different backend endpoint.",
        )
    mode = value["mode"]
    if mode not in MODES:
        raise ValidationError("invalid_backend_request", "WebUI generation mode is unsupported.")
    for field in ("positive_prompt", "negative_prompt", "sampler", "output_path", "prompt_compiler_id"):
        if not isinstance(value[field], str) or (field not in {"negative_prompt"} and not value[field].strip()):
            raise ValidationError("invalid_backend_request", f"WebUI {field} is invalid.")
    for field in ("width", "height"):
        dimension = value[field]
        if type(dimension) is not int or not 256 <= dimension <= 1536 or dimension % 8:
            raise ValidationError("invalid_backend_request", f"WebUI {field} is invalid.")
    if type(value["steps"]) is not int or not 1 <= value["steps"] <= 80:
        raise ValidationError("invalid_backend_request", "WebUI steps are invalid.")
    if (
        not isinstance(value["guidance_scale"], (int, float))
        or isinstance(value["guidance_scale"], bool)
        or not 0 <= value["guidance_scale"] <= 20
    ):
        raise ValidationError("invalid_backend_request", "WebUI guidance scale is invalid.")
    if value["seed"] is not None and type(value["seed"]) is not int:
        raise ValidationError("invalid_backend_request", "WebUI seed must be an integer or null.")
    if type(value["prompt_compiler_version"]) is not int or value["prompt_compiler_version"] < 1:
        raise ValidationError("invalid_backend_request", "Prompt compiler version is invalid.")
    strength = value["strength"]
    if mode == "txt2img":
        if value["source_path"] is not None or value["mask_path"] is not None or strength is not None:
            raise ValidationError("invalid_backend_request", "txt2img cannot include edit inputs.")
    else:
        if not isinstance(value["source_path"], str) or not value["source_path"]:
            raise ValidationError("invalid_backend_request", "Edit mode requires a source image.")
        if not isinstance(strength, (int, float)) or isinstance(strength, bool) or not 0 <= strength <= 1:
            raise ValidationError("invalid_backend_request", "Edit strength is invalid.")
        if mode == "inpaint" and (not isinstance(value["mask_path"], str) or not value["mask_path"]):
            raise ValidationError("invalid_backend_request", "Inpaint mode requires a mask image.")
        if mode == "img2img" and value["mask_path"] is not None:
            raise ValidationError("invalid_backend_request", "img2img cannot include a mask image.")
    result = copy.deepcopy(value)
    result["model"] = validated_model
    return result


def _generation_payload(
    request: dict[str, object],
    selected: dict[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt": request["positive_prompt"],
        "negative_prompt": request["negative_prompt"],
        "width": request["width"],
        "height": request["height"],
        "steps": request["steps"],
        "cfg_scale": request["guidance_scale"],
        "sampler_name": request["sampler"],
        "seed": request["seed"] if request["seed"] is not None else -1,
        "batch_size": 1,
        "n_iter": 1,
        "save_images": True,
        "override_settings": {
            "sd_model_checkpoint": selected["backend_model_id"],
        },
        "override_settings_restore_afterwards": True,
    }
    if request["mode"] != "txt2img":
        payload["init_images"] = [_condition_image(str(request["source_path"]))]
        payload["denoising_strength"] = request["strength"]
    if request["mode"] == "inpaint":
        payload["mask"] = _condition_image(str(request["mask_path"]))
        payload["inpainting_fill"] = 1
        payload["inpaint_full_res"] = True
    return payload


def _condition_image(path_value: str) -> str:
    path = Path(path_value)
    try:
        path_stat = os.stat(path, follow_symlinks=False)
        if _link_like(path) or not stat.S_ISREG(path_stat.st_mode) or path_stat.st_size > MAX_IMAGE_BYTES:
            raise OSError("unsafe image")
        data = path.read_bytes()
    except OSError as error:
        raise ValidationError(
            "invalid_condition_image",
            "Condition image must be a bounded regular non-link file.",
        ) from error
    if not data:
        raise ValidationError("invalid_condition_image", "Condition image cannot be empty.")
    return base64.b64encode(data).decode("ascii")


def _validated_response(
    value: object,
    selected: dict[str, object],
    expected_seed: object,
) -> tuple[bytes, dict[str, object]]:
    if not isinstance(value, dict):
        raise ArtifactError("invalid_backend_response", "WebUI generation response must be an object.")
    images = value.get("images")
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
        raise ArtifactError("invalid_backend_response", "WebUI must return exactly one image.")
    encoded = images[0].split(",", 1)[-1]
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise ArtifactError("backend_response_too_large", "WebUI image exceeded its byte limit.")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ArtifactError("invalid_backend_response", "WebUI returned invalid base64 image data.") from error
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ArtifactError("invalid_backend_response", "WebUI returned an empty or oversized image.")

    info_value = value.get("info", {})
    if isinstance(info_value, str):
        try:
            info_value = json.loads(info_value) if info_value else {}
        except json.JSONDecodeError as error:
            raise ArtifactError("invalid_backend_response", "WebUI generation info is malformed.") from error
    if not isinstance(info_value, dict):
        raise ArtifactError("invalid_backend_response", "WebUI generation info must be an object.")
    expected_name = selected["metadata"].get("model_name")
    actual_name = info_value.get("sd_model_name")
    if not isinstance(expected_name, str) or not isinstance(actual_name, str) or not _same_model_name(actual_name, expected_name, str(selected["backend_model_id"])):
        raise ConflictError(
            "backend_model_mismatch",
            "WebUI reported a different model for the generated image.",
        )
    backend_hash = selected["metadata"].get("backend_hash")
    actual_hash = info_value.get("sd_model_hash")
    if isinstance(backend_hash, str) and isinstance(actual_hash, str) and backend_hash.lower() != actual_hash.lower():
        raise ConflictError(
            "backend_model_mismatch",
            "WebUI reported a different model hash for the generated image.",
        )
    seed = info_value.get("seed", expected_seed)
    if type(seed) is not int or expected_seed is not None and seed != expected_seed:
        raise ConflictError(
            "backend_seed_mismatch",
            "WebUI reported a different seed for the generated image.",
        )
    return image_bytes, copy.deepcopy(info_value)


def _same_model_name(actual: str, expected: str, backend_model_id: str) -> bool:
    normalized_actual = actual.strip().lower()
    normalized_expected = expected.strip().lower()
    normalized_id = backend_model_id.split(" [", 1)[0].replace("\\", "/").lower()
    return (
        normalized_actual == normalized_expected
        or normalized_actual == normalized_id
        or normalized_id.endswith("/" + normalized_actual)
        or Path(normalized_id).stem == normalized_actual
    )


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    path_stat = os.lstat(path)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)
