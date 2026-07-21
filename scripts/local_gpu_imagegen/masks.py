from __future__ import annotations

import copy
import math
import os
import re
from pathlib import Path

from .artifacts import ensure_within, sha256_file, validate_mask_png, validate_png
from .errors import ArtifactError, AssetEngineError, ConflictError, StateError, ValidationError
from .preview import PreviewResult, create_preview
from .run_store import RunStore, utc_now


MASK_ID_PATTERN = re.compile(r"^mask-(?P<number>[0-9]{2,})$")


class MaskService:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def prepare(
        self,
        arguments: dict[str, object],
    ) -> tuple[dict[str, object], PreviewResult | None]:
        normalized = _validate_prepare_arguments(arguments)
        run_id = normalized["run_id"]
        assert isinstance(run_id, str)
        run_root = self.store.run_root(run_id)
        created_paths: list[Path] = []
        result_box: dict[str, object] = {}
        preview_box: list[PreviewResult] = []

        def create_mask(manifest: dict[str, object]) -> None:
            source_record, source_path = _revision_source(manifest, run_root)
            image_module, image_draw, image_filter = _load_pillow()
            mask = _render_mask(
                image_module,
                image_draw,
                image_filter,
                normalized,
                source_record["width"],
                source_record["height"],
            )
            try:
                _validate_selection(mask)
                masks = manifest.get("masks")
                if not isinstance(masks, list) or not all(isinstance(item, dict) for item in masks):
                    raise ArtifactError("corrupt_manifest", "Manifest masks must be an array of objects.")
                mask_id = _next_mask_id(masks)
                masks_root = ensure_within(run_root, run_root / "masks")
                masks_root.mkdir(parents=True, exist_ok=True)
                mask_path = ensure_within(masks_root, masks_root / f"{mask_id}.png")
                mask_pending = ensure_within(masks_root, masks_root / f".{mask_id}.pending.png")
                overlay_path = ensure_within(masks_root, masks_root / f"{mask_id}-overlay.jpg")
                overlay_pending = ensure_within(masks_root, masks_root / f".{mask_id}-overlay.pending.png")
                created_paths.extend((mask_path, mask_pending, overlay_path, overlay_pending))

                mask.save(mask_pending, format="PNG", optimize=False)
                mask_metadata = validate_mask_png(
                    mask_pending,
                    source_record["width"],
                    source_record["height"],
                )
                os.replace(mask_pending, mask_path)

                _save_overlay(
                    image_module,
                    source_path,
                    mask,
                    overlay_pending,
                )
                preview = create_preview(overlay_pending, overlay_path)
                try:
                    overlay_pending.unlink()
                except FileNotFoundError:
                    pass
                if preview.path is None or preview.warning is not None:
                    raise ArtifactError(
                        "mask_overlay_unavailable",
                        "Mask overlay could not be encoded for explicit confirmation.",
                        {"warning": preview.warning},
                    )

                record = {
                    "mask_id": mask_id,
                    "source": "geometry" if "geometry" in normalized else "user",
                    "source_image_sha256": source_record["sha256"],
                    "mask_sha256": mask_metadata["sha256"],
                    "geometry": copy.deepcopy(normalized.get("geometry")),
                    "feather_pixels": normalized["feather_pixels"],
                    "mask_path": mask_path.relative_to(run_root).as_posix(),
                    "overlay_path": overlay_path.relative_to(run_root).as_posix(),
                    "confirmed": False,
                    "confirmed_at": None,
                }
                masks.append(record)
                result_box.update(_external_record(record, run_root))
                preview_box.append(preview)
            finally:
                mask.close()

        try:
            self.store.update(run_id, create_mask)
        except Exception:
            _remove_paths(created_paths)
            raise
        if not result_box or not preview_box:
            raise ArtifactError("mask_prepare_failed", "Mask preparation produced no result.")
        return copy.deepcopy(result_box), preview_box[0]

    def confirm(self, arguments: dict[str, object]) -> dict[str, object]:
        if not isinstance(arguments, dict) or set(arguments) != {"run_id", "mask_id"}:
            raise ValidationError(
                "invalid_mask_confirmation",
                "Mask confirmation requires only run_id and mask_id.",
            )
        run_id = arguments["run_id"]
        mask_id = arguments["mask_id"]
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValidationError("invalid_run_id", "run_id must be a non-empty string.")
        if not isinstance(mask_id, str) or MASK_ID_PATTERN.fullmatch(mask_id) is None:
            raise ValidationError("invalid_mask_id", "mask_id has an invalid format.")
        run_root = self.store.run_root(run_id)
        result_box: dict[str, object] = {}

        def confirm_mask(manifest: dict[str, object]) -> None:
            try:
                source_record, source_path = _revision_source(manifest, run_root)
            except AssetEngineError as error:
                if error.code not in {"invalid_generated_image", "mask_changed_since_prepare"}:
                    raise
                raise ConflictError(
                    "mask_changed_since_prepare",
                    "Source image or mask bytes changed after the overlay was prepared.",
                    {"mask_id": mask_id},
                ) from error
            masks = manifest.get("masks")
            if not isinstance(masks, list) or not all(isinstance(item, dict) for item in masks):
                raise ArtifactError("corrupt_manifest", "Manifest masks must be an array of objects.")
            record = next((item for item in masks if item.get("mask_id") == mask_id), None)
            if record is None:
                raise StateError("mask_not_found", "Prepared mask does not exist.", {"mask_id": mask_id})
            if _mask_changed(
                record,
                run_root,
                source_path,
                source_record["width"],
                source_record["height"],
            ):
                raise ConflictError(
                    "mask_changed_since_prepare",
                    "Source image or mask bytes changed after the overlay was prepared.",
                    {"mask_id": mask_id},
                )
            if record.get("confirmed") is not True:
                record["confirmed"] = True
                record["confirmed_at"] = utc_now()
            result_box.update(_external_record(record, run_root))

        self.store.update(run_id, confirm_mask)
        return copy.deepcopy(result_box)

    def confirmed_for_generation(self, run_id: str, mask_id: str) -> dict[str, object]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValidationError("invalid_run_id", "run_id must be a non-empty string.")
        if not isinstance(mask_id, str) or MASK_ID_PATTERN.fullmatch(mask_id) is None:
            raise ValidationError("invalid_mask_id", "mask_id has an invalid format.")
        manifest = self.store.get(run_id)
        run_root = self.store.run_root(run_id)
        source_record, source_path = _revision_source(manifest, run_root)
        masks = manifest.get("masks")
        if not isinstance(masks, list) or not all(isinstance(item, dict) for item in masks):
            raise ArtifactError("corrupt_manifest", "Manifest masks must be an array of objects.")
        record = next((item for item in masks if item.get("mask_id") == mask_id), None)
        if record is None:
            raise StateError("mask_not_found", "Prepared mask does not exist.", {"mask_id": mask_id})
        if record.get("confirmed") is not True:
            raise StateError(
                "mask_not_confirmed",
                "Prepared mask requires explicit confirmation before inpaint generation.",
                {"mask_id": mask_id},
            )
        if _mask_changed(
            record,
            run_root,
            source_path,
            source_record["width"],
            source_record["height"],
        ):
            raise ConflictError(
                "mask_changed_since_prepare",
                "Source image or mask bytes changed after the overlay was prepared.",
                {"mask_id": mask_id},
            )
        return _external_record(record, run_root)


def _validate_prepare_arguments(arguments: object) -> dict[str, object]:
    allowed = {"run_id", "user_mask_path", "geometry", "feather_pixels"}
    if not isinstance(arguments, dict) or "run_id" not in arguments or not set(arguments) <= allowed:
        raise ValidationError(
            "invalid_mask_arguments",
            "Mask preparation accepts run_id, one mask source, and optional feather_pixels only.",
        )
    run_id = arguments["run_id"]
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValidationError("invalid_run_id", "run_id must be a non-empty string.")
    has_user = "user_mask_path" in arguments
    has_geometry = "geometry" in arguments
    if has_user == has_geometry:
        raise ValidationError(
            "invalid_mask_source",
            "Provide exactly one of user_mask_path or geometry.",
        )
    feather = arguments.get("feather_pixels", 0)
    if type(feather) is not int or not 0 <= feather <= 64:
        raise ValidationError("invalid_feather_pixels", "feather_pixels must be an integer from 0 to 64.")
    normalized: dict[str, object] = {"run_id": run_id.strip(), "feather_pixels": feather}
    if has_user:
        user_path = arguments["user_mask_path"]
        if not isinstance(user_path, str) or not user_path.strip():
            raise ValidationError("invalid_user_mask", "user_mask_path must be a non-empty path string.")
        normalized["user_mask_path"] = user_path
    else:
        normalized["geometry"] = _validate_geometry(arguments["geometry"])
    return normalized


def _validate_geometry(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("invalid_mask_geometry", "geometry must be a non-empty list.")
    normalized: list[dict[str, object]] = []
    for shape in value:
        if not isinstance(shape, dict) or not isinstance(shape.get("type"), str):
            raise ValidationError("invalid_mask_geometry", "Each geometry entry requires a type.")
        if shape["type"] == "rectangle":
            if set(shape) != {"type", "x", "y", "width", "height"}:
                raise ValidationError("invalid_mask_geometry", "Rectangle fields are invalid.")
            x = _coordinate(shape["x"])
            y = _coordinate(shape["y"])
            width = _coordinate(shape["width"])
            height = _coordinate(shape["height"])
            if width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
                raise ValidationError(
                    "geometry_out_of_bounds",
                    "Rectangle extents must remain within normalized image bounds.",
                )
            normalized.append({
                "type": "rectangle",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            })
            continue
        if shape["type"] == "polygon":
            if set(shape) != {"type", "points"} or not isinstance(shape["points"], list):
                raise ValidationError("invalid_mask_geometry", "Polygon fields are invalid.")
            points: list[tuple[float, float]] = []
            for point in shape["points"]:
                if not isinstance(point, dict) or set(point) != {"x", "y"}:
                    raise ValidationError("invalid_mask_geometry", "Polygon points require x and y.")
                points.append((_coordinate(point["x"]), _coordinate(point["y"])))
            if len(points) < 3 or len(set(points)) < 3 or _signed_area(points) == 0:
                raise ValidationError(
                    "invalid_polygon",
                    "Polygon requires at least three distinct points with non-zero area.",
                )
            if _self_intersects(points):
                raise ValidationError("self_intersecting_polygon", "Polygon cannot self-intersect.")
            normalized.append({
                "type": "polygon",
                "points": [{"x": x, "y": y} for x, y in points],
            })
            continue
        raise ValidationError("invalid_geometry_type", "Geometry type must be rectangle or polygon.")
    return normalized


def _coordinate(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValidationError("geometry_out_of_bounds", "Geometry coordinates must be finite values from 0 to 1.")
    return float(value)


def _signed_area(points: list[tuple[float, float]]) -> float:
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    ) / 2


def _self_intersects(points: list[tuple[float, float]]) -> bool:
    count = len(points)
    for first in range(count):
        a1 = points[first]
        a2 = points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or first == (second + 1) % count:
                continue
            b1 = points[second]
            b2 = points[(second + 1) % count]
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


def _segments_intersect(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> bool:
    def orientation(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    values = (
        orientation(a1, a2, b1),
        orientation(a1, a2, b2),
        orientation(b1, b2, a1),
        orientation(b1, b2, a2),
    )
    if values[0] == 0 and _on_segment(a1, b1, a2):
        return True
    if values[1] == 0 and _on_segment(a1, b2, a2):
        return True
    if values[2] == 0 and _on_segment(b1, a1, b2):
        return True
    if values[3] == 0 and _on_segment(b1, a2, b2):
        return True
    return (values[0] > 0) != (values[1] > 0) and (values[2] > 0) != (values[3] > 0)


def _on_segment(
    start: tuple[float, float],
    point: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    return (
        min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
        and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def _load_pillow() -> tuple[object, object, object]:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError as error:
        raise StateError(
            "mask_dependency_unavailable",
            "Pillow is required only when preparing an inpaint mask.",
        ) from error
    return Image, ImageDraw, ImageFilter


def _revision_source(
    manifest: dict[str, object],
    run_root: Path,
) -> tuple[dict[str, object], Path]:
    if not isinstance(manifest.get("parent"), dict):
        raise StateError("mask_requires_revision_run", "Masks can be prepared only for child revision runs.")
    revision = manifest.get("revision")
    if not isinstance(revision, dict) or revision.get("edit_mode") != "inpaint":
        raise StateError("mask_requires_inpaint_revision", "Masks require a child run using inpaint edit mode.")
    source = revision.get("source_image")
    if not isinstance(source, dict):
        raise ArtifactError("corrupt_manifest", "Revision source image metadata is missing.")
    path_value = source.get("path")
    width = source.get("width")
    height = source.get("height")
    stored_hash = source.get("sha256")
    if (
        not isinstance(path_value, str)
        or Path(path_value).is_absolute()
        or type(width) is not int
        or width <= 0
        or type(height) is not int
        or height <= 0
        or not isinstance(stored_hash, str)
    ):
        raise ArtifactError("corrupt_manifest", "Revision source image metadata is invalid.")
    source_path = ensure_within(run_root, run_root / path_value)
    validated = validate_png(source_path, width, height)
    if validated["sha256"] != stored_hash:
        raise ConflictError(
            "mask_changed_since_prepare",
            "Revision source image no longer matches its retained hash.",
        )
    return copy.deepcopy(source), source_path


def _render_mask(
    image_module: object,
    image_draw: object,
    image_filter: object,
    normalized: dict[str, object],
    width: int,
    height: int,
) -> object:
    if "user_mask_path" in normalized:
        try:
            with image_module.open(normalized["user_mask_path"]) as source:
                source.load()
                mask = source.convert("L")
        except (OSError, ValueError) as error:
            raise ValidationError("invalid_user_mask", "User mask cannot be decoded as an image.") from error
        if mask.size != (width, height):
            resized = mask.resize((width, height), image_module.Resampling.NEAREST)
            mask.close()
            mask = resized
    else:
        mask = image_module.new("L", (width, height), 0)
        draw = image_draw.Draw(mask)
        for shape in normalized["geometry"]:
            if shape["type"] == "rectangle":
                x0 = _pixel(shape["x"], width)
                y0 = _pixel(shape["y"], height)
                x1 = _pixel(shape["x"] + shape["width"], width)
                y1 = _pixel(shape["y"] + shape["height"], height)
                draw.rectangle((x0, y0, x1, y1), fill=255)
            else:
                points = [(_pixel(point["x"], width), _pixel(point["y"], height)) for point in shape["points"]]
                draw.polygon(points, fill=255)
    feather = normalized["feather_pixels"]
    if feather:
        blurred = mask.filter(image_filter.GaussianBlur(radius=feather))
        mask.close()
        mask = blurred
    return mask


def _pixel(value: float, dimension: int) -> int:
    return min(round(value * dimension), dimension - 1)


def _validate_selection(mask: object) -> None:
    minimum, maximum = mask.getextrema()
    if maximum == 0:
        raise ValidationError("empty_mask", "Mask must select at least one editable pixel.")
    if minimum > 0:
        raise ValidationError("full_image_mask", "Mask must retain at least one fully protected pixel.")


def _save_overlay(
    image_module: object,
    source_path: Path,
    mask: object,
    destination: Path,
) -> None:
    with image_module.open(source_path) as source:
        source.load()
        base = source.convert("RGB")
    tint = image_module.new("RGB", base.size, (255, 0, 0))
    alpha = mask.point(lambda value: round(value * 0.45))
    try:
        overlay = image_module.composite(tint, base, alpha)
        try:
            overlay.save(destination, format="PNG", optimize=False)
        finally:
            overlay.close()
    finally:
        alpha.close()
        tint.close()
        base.close()


def _next_mask_id(masks: list[dict[str, object]]) -> str:
    highest = 0
    for record in masks:
        mask_id = record.get("mask_id")
        if not isinstance(mask_id, str):
            raise ArtifactError("corrupt_manifest", "Stored mask ID is invalid.")
        match = MASK_ID_PATTERN.fullmatch(mask_id)
        if match is None:
            raise ArtifactError("corrupt_manifest", "Stored mask ID is invalid.")
        highest = max(highest, int(match.group("number")))
    return f"mask-{highest + 1:02d}"


def _mask_changed(
    record: dict[str, object],
    run_root: Path,
    source_path: Path,
    source_width: int,
    source_height: int,
) -> bool:
    mask_path = _record_path(record, "mask_path", run_root)
    try:
        if sha256_file(source_path) != record.get("source_image_sha256"):
            return True
        metadata = validate_mask_png(mask_path, source_width, source_height)
        return metadata["sha256"] != record.get("mask_sha256")
    except AssetEngineError:
        return True
    except OSError:
        return True
def _record_path(record: dict[str, object], field: str, run_root: Path) -> Path:
    value = record.get(field)
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ArtifactError("corrupt_manifest", f"Stored {field} is invalid.")
    candidate = run_root / value
    return ensure_within(run_root, candidate)


def _external_record(record: dict[str, object], run_root: Path) -> dict[str, object]:
    value = copy.deepcopy(record)
    for field in ("mask_path", "overlay_path"):
        stored = value.get(field)
        if isinstance(stored, str):
            value[field] = str(ensure_within(run_root, run_root / stored))
    return value


def _remove_paths(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
