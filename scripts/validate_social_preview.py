from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_FIELDS = {
    "schema_version",
    "source",
    "source_sha256",
    "html",
    "html_sha256",
    "output",
    "output_sha256",
    "width",
    "height",
}
REQUIRED_COPY = (
    "Local GPU Imagegen",
    "Run supported ComfyUI workflows from your Agent",
    "Codex + Claude Code",
    "ComfyUI / Forge / Diffusers",
    "SEPARATE VALIDATED OUTPUT",
    "../demo/real/final.png",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid_json_object")
    return value


def png_dimensions(path: Path) -> tuple[int, int]:
    encoded = path.read_bytes()
    if encoded[:8] != b"\x89PNG\r\n\x1a\n" or encoded[12:16] != b"IHDR":
        raise ValueError("invalid_png")
    return struct.unpack(">II", encoded[16:24])


def record_social_preview(root: Path) -> dict[str, object]:
    source = root / "docs" / "demo" / "real" / "final.png"
    html = root / "docs" / "assets" / "github-social-preview.html"
    output = root / "docs" / "assets" / "github-social-preview.png"
    width, height = png_dimensions(output)
    manifest = {
        "schema_version": "1.0",
        "source": "docs/demo/real/final.png",
        "source_sha256": _sha256(source),
        "html": "docs/assets/github-social-preview.html",
        "html_sha256": _sha256(html),
        "output": "docs/assets/github-social-preview.png",
        "output_sha256": _sha256(output),
        "width": width,
        "height": height,
    }
    path = root / "docs" / "assets" / "github-social-preview.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_social_preview(root: Path) -> list[str]:
    findings: set[str] = set()
    assets = root / "docs" / "assets"
    source = root / "docs" / "demo" / "real" / "final.png"
    output = assets / "github-social-preview.png"
    html = assets / "github-social-preview.html"
    try:
        manifest = _read_json(assets / "github-social-preview.json")
        showcase = _read_json(
            root / "docs" / "demo" / "real" / "showcase-manifest.json"
        )
        source_sha256 = _sha256(source)
        output_sha256 = _sha256(output)
        html_sha256 = _sha256(html)
        dimensions = png_dimensions(output)
        source_text = html.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return ["invalid_social_preview_files"]
    if set(manifest) != MANIFEST_FIELDS or manifest.get("schema_version") != "1.0":
        findings.add("invalid_social_preview_manifest")
    if manifest.get("source") != "docs/demo/real/final.png":
        findings.add("invalid_social_preview_source")
    if manifest.get("html") != "docs/assets/github-social-preview.html":
        findings.add("invalid_social_preview_html")
    if manifest.get("output") != "docs/assets/github-social-preview.png":
        findings.add("invalid_social_preview_output")
    if manifest.get("source_sha256") != source_sha256:
        findings.add("social_preview_source_sha256_mismatch")
    if manifest.get("output_sha256") != output_sha256:
        findings.add("social_preview_output_sha256_mismatch")
    if manifest.get("html_sha256") != html_sha256:
        findings.add("social_preview_html_sha256_mismatch")
    if not SHA256_RE.fullmatch(str(manifest.get("source_sha256", ""))):
        findings.add("invalid_social_preview_source_sha256")
    if not SHA256_RE.fullmatch(str(manifest.get("output_sha256", ""))):
        findings.add("invalid_social_preview_output_sha256")
    if not SHA256_RE.fullmatch(str(manifest.get("html_sha256", ""))):
        findings.add("invalid_social_preview_html_sha256")
    if dimensions != (1280, 640):
        findings.add("invalid_social_preview_dimensions")
    if (manifest.get("width"), manifest.get("height")) != dimensions:
        findings.add("social_preview_dimension_mismatch")
    final = showcase.get("final")
    if not isinstance(final, dict) or final.get("image_sha256") != source_sha256:
        findings.add("social_preview_not_bound_to_showcase")
    for required in REQUIRED_COPY:
        if required not in source_text:
            findings.add(f"social_preview_copy_missing:{required}")
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.record:
        record_social_preview(root)
    findings = validate_social_preview(root)
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
