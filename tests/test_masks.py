from __future__ import annotations

import builtins
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ConflictError, StateError, ValidationError  # noqa: E402
from local_gpu_imagegen.masks import MaskService  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402


PILLOW_AVAILABLE = importlib.util.find_spec("PIL") is not None


@unittest.skipUnless(PILLOW_AVAILABLE, "Pillow not installed")
class MaskServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.output_root = self.root / "output"
        self.store = RunStore(self.output_root)
        child = self.store.create({"profile": "standalone-illustration", "max_rounds": 2})
        self.child_id = str(child["run_id"])
        self.child_root = self.output_root / "runs" / self.child_id
        self.source_path = self.child_root / "parent-source.png"
        Image.new("RGB", (100, 80), (30, 80, 140)).save(self.source_path, format="PNG")
        source_hash = hashlib.sha256(self.source_path.read_bytes()).hexdigest()

        def make_child(manifest: dict[str, object]) -> None:
            manifest["parent"] = {
                "run_id": "20260721T000000Z-000000000000",
                "round": 1,
                "image_sha256": source_hash,
            }
            manifest["revision"] = {
                "contract": {"preserve": [], "change": ["repair the selected region"]},
                "edit_mode": "inpaint",
                "denoising_strength": 0.25,
                "source_image": {
                    "path": "parent-source.png",
                    "sha256": source_hash,
                    "width": 100,
                    "height": 80,
                    "mime_type": "image/png",
                },
            }

        self.store.update(self.child_id, make_child)
        self.service = MaskService(self.store)
        self.black_mask = self.root / "black.png"
        self.white_mask = self.root / "white.png"
        self.partial_mask = self.root / "partial.png"
        Image.new("L", (20, 20), 0).save(self.black_mask, format="PNG")
        Image.new("L", (20, 20), 255).save(self.white_mask, format="PNG")
        partial = Image.new("L", (20, 20), 0)
        for x in range(5, 15):
            for y in range(4, 16):
                partial.putpixel((x, y), 255)
        partial.save(self.partial_mask, format="PNG")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def prepare_rectangle(self, **updates: object):
        rectangle: dict[str, object] = {
            "type": "rectangle",
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        }
        rectangle.update(updates)
        return self.service.prepare({
            "run_id": self.child_id,
            "geometry": [rectangle],
            "feather_pixels": 0,
        })

    def prepare_polygon(self, points: list[tuple[float, float]]):
        return self.service.prepare({
            "run_id": self.child_id,
            "geometry": [{
                "type": "polygon",
                "points": [{"x": x, "y": y} for x, y in points],
            }],
            "feather_pixels": 0,
        })

    def prepare_user_mask(self, path: Path):
        return self.service.prepare({
            "run_id": self.child_id,
            "user_mask_path": str(path),
            "feather_pixels": 0,
        })

    def test_rectangle_mask_uses_normalized_coordinates(self) -> None:
        from PIL import Image

        result, preview = self.prepare_rectangle()

        self.assertFalse(result["confirmed"])
        self.assertEqual(result["source"], "geometry")
        self.assertEqual(preview.mime_type, "image/jpeg")
        self.assertLessEqual(max(preview.width, preview.height), 768)
        with Image.open(result["mask_path"]) as mask:
            self.assertEqual(mask.mode, "L")
            self.assertEqual(mask.size, (100, 80))
            self.assertEqual(mask.getpixel((0, 0)), 0)
            self.assertEqual(mask.getpixel((10, 16)), 255)

        stored = self.store.get(self.child_id)["masks"][0]
        self.assertEqual(stored["mask_path"], "masks/mask-01.png")
        self.assertEqual(stored["overlay_path"], "masks/mask-01-overlay.jpg")
        self.assertEqual(stored["geometry"][0]["x"], 0.1)

    def test_rejects_out_of_range_and_self_intersecting_geometry(self) -> None:
        with self.assertRaisesRegex(ValidationError, "geometry_out_of_bounds"):
            self.prepare_rectangle(x=0.9, width=0.2)
        with self.assertRaisesRegex(ValidationError, "self_intersecting_polygon"):
            self.prepare_polygon([(0.1, 0.1), (0.9, 0.9), (0.1, 0.9), (0.9, 0.1)])

    def test_rejects_empty_or_full_image_mask(self) -> None:
        with self.assertRaisesRegex(ValidationError, "empty_mask"):
            self.prepare_user_mask(self.black_mask)
        with self.assertRaisesRegex(ValidationError, "full_image_mask"):
            self.prepare_user_mask(self.white_mask)

    def test_user_mask_is_resized_without_modifying_source(self) -> None:
        from PIL import Image

        before = self.partial_mask.read_bytes()
        result, preview = self.prepare_user_mask(self.partial_mask)

        self.assertEqual(self.partial_mask.read_bytes(), before)
        self.assertEqual(result["source"], "user")
        self.assertEqual(preview.mime_type, "image/jpeg")
        with Image.open(result["mask_path"]) as mask:
            self.assertEqual(mask.size, (100, 80))

    def test_each_prepare_allocates_a_new_unconfirmed_mask(self) -> None:
        first, _ = self.prepare_rectangle()
        second, _ = self.prepare_rectangle()

        self.assertEqual((first["mask_id"], second["mask_id"]), ("mask-01", "mask-02"))
        self.assertFalse(first["confirmed"])
        self.assertFalse(second["confirmed"])
        self.assertEqual(len(self.store.get(self.child_id)["masks"]), 2)

    def test_confirmation_fails_after_mask_bytes_change(self) -> None:
        prepared, _ = self.prepare_rectangle()
        Path(prepared["mask_path"]).write_bytes(b"changed")

        with self.assertRaisesRegex(ConflictError, "mask_changed_since_prepare"):
            self.service.confirm({"run_id": self.child_id, "mask_id": prepared["mask_id"]})

    def test_confirmation_fails_after_source_bytes_change(self) -> None:
        prepared, _ = self.prepare_rectangle()
        self.source_path.write_bytes(b"changed")

        with self.assertRaisesRegex(ConflictError, "mask_changed_since_prepare"):
            self.service.confirm({"run_id": self.child_id, "mask_id": prepared["mask_id"]})

    def test_confirmation_records_approval_without_changing_hashes(self) -> None:
        prepared, _ = self.prepare_rectangle()

        confirmed = self.service.confirm({"run_id": self.child_id, "mask_id": prepared["mask_id"]})
        repeated = self.service.confirm({"run_id": self.child_id, "mask_id": prepared["mask_id"]})

        self.assertTrue(confirmed["confirmed"])
        self.assertIsNotNone(confirmed["confirmed_at"])
        self.assertEqual(repeated["confirmed_at"], confirmed["confirmed_at"])
        stored = self.store.get(self.child_id)["masks"][0]
        self.assertEqual(stored["mask_sha256"], prepared["mask_sha256"])
        self.assertEqual(stored["source_image_sha256"], prepared["source_image_sha256"])

    def test_mask_operations_require_a_child_run(self) -> None:
        root = self.store.create({"profile": "standalone-illustration", "max_rounds": 1})
        with self.assertRaisesRegex(StateError, "mask_requires_revision_run"):
            self.service.prepare({
                "run_id": root["run_id"],
                "geometry": [{"type": "rectangle", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}],
            })

    def test_invalid_input_union_is_rejected_before_pillow_import(self) -> None:
        original_import = builtins.__import__

        def import_without_pillow(name: str, *args: object, **kwargs: object) -> object:
            if name == "PIL" or name.startswith("PIL."):
                raise AssertionError("Pillow imported before input validation")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_pillow):
            with self.assertRaisesRegex(ValidationError, "invalid_mask_source"):
                self.service.prepare({
                    "run_id": self.child_id,
                    "geometry": [],
                    "user_mask_path": str(self.partial_mask),
                })

    def test_missing_pillow_is_a_structured_dependency_error(self) -> None:
        original_import = builtins.__import__

        def import_without_pillow(name: str, *args: object, **kwargs: object) -> object:
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("Pillow unavailable for test")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_pillow):
            with self.assertRaisesRegex(StateError, "mask_dependency_unavailable"):
                self.prepare_rectangle()


if __name__ == "__main__":
    unittest.main()
