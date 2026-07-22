#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


WIDTH = 720
HEIGHT = 405
PALETTE = (
    (11, 15, 20),
    (21, 27, 35),
    (244, 247, 250),
    (139, 150, 165),
    (45, 212, 168),
    (77, 163, 255),
    (245, 184, 61),
    (255, 107, 107),
    (42, 52, 65),
    (25, 84, 74),
    (36, 67, 99),
    (87, 65, 24),
    (97, 43, 46),
    (190, 202, 216),
    (56, 69, 84),
    (255, 255, 255),
)


FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    " ": ("00000",) * 7,
}


class Canvas:
    def __init__(self) -> None:
        self.pixels = bytearray([0]) * (WIDTH * HEIGHT)

    def rect(self, x: int, y: int, width: int, height: int, color: int) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(WIDTH, x + width), min(HEIGHT, y + height)
        for row in range(y0, y1):
            start = row * WIDTH + x0
            self.pixels[start : start + (x1 - x0)] = bytes([color]) * (x1 - x0)

    def text(self, x: int, y: int, value: str, color: int = 2, scale: int = 2) -> None:
        cursor = x
        for character in value.upper():
            glyph = FONT.get(character, FONT[" "])
            for row, bits in enumerate(glyph):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        self.rect(cursor + column * scale, y + row * scale, scale, scale, color)
            cursor += 6 * scale


STEPS = ("BRIEF", "ROUTE", "ROUND 1", "REVIEW", "CANDIDATE")
FRAMES = (
    {
        "label": "Brief boundaries",
        "state": "brief_confirmed",
        "title": "NATURAL LANGUAGE BRIEF",
        "accent": 5,
        "lines": ("16:9 ILLUSTRATION", "2 SUCCESSFUL ROUNDS", "NO DOWNLOADS"),
        "note": "HIGH IMPACT BOUNDARIES ARE EXPLICIT",
    },
    {
        "label": "Exact route confirmation",
        "state": "route_confirmed",
        "title": "EXACT ROUTE CONFIRMED",
        "accent": 4,
        "lines": ("BACKEND: COMFYUI", "MODEL: TRUSTED LOCAL ROUTE", "BUDGET: 2 ROUNDS"),
        "note": "NO SILENT MODEL OR BACKEND SWITCH",
    },
    {
        "label": "First successful round",
        "state": "round_retained",
        "title": "ROUND 1 RETAINED",
        "accent": 6,
        "lines": ("FULL IMAGE HASHED", "ORIGINAL READY FOR REVIEW", "BUDGET USED: 1 / 2"),
        "note": "BACKEND FAILURES DO NOT SPEND A ROUND",
    },
    {
        "label": "Structured rejection and revision",
        "state": "revision_confirmed",
        "title": "REVIEW REJECTS ROUND 1",
        "accent": 7,
        "lines": ("FAIL: HAND DETAIL UNCLEAR", "PRESERVE: THEME + COMPOSITION", "CHANGE: HAND DETAIL"),
        "note": "REVISION IS BOUNDED AND AUDITABLE",
    },
    {
        "label": "Candidate awaits user decision",
        "state": "candidate",
        "title": "ROUND 2 IS A CANDIDATE",
        "accent": 4,
        "lines": ("SEED AND LINEAGE RECORDED", "IMAGE BYTES BOUND TO TOKEN", "WAITING FOR USER DECISION"),
        "note": "THE AGENT CANNOT ACCEPT ITS OWN OUTPUT",
    },
)


def _draw_frame(index: int, frame: dict[str, object]) -> bytes:
    canvas = Canvas()
    canvas.rect(0, 0, WIDTH, 54, 1)
    canvas.rect(0, 53, WIDTH, 1, 8)
    canvas.text(28, 17, "LOCAL GPU IMAGEGEN", 2, 2)
    canvas.text(504, 19, "PROTOCOL LOOP", 3, 1)

    canvas.rect(28, 79, 164, 266, 1)
    canvas.text(47, 96, "BOUNDED FLOW", 13, 1)
    for step_index, step in enumerate(STEPS):
        y = 131 + step_index * 42
        if step_index < index:
            color = 4
        elif step_index == index:
            color = int(frame["accent"])
        else:
            color = 14
        canvas.rect(48, y, 13, 13, color)
        if step_index < len(STEPS) - 1:
            canvas.rect(54, y + 13, 2, 29, 8)
        canvas.text(74, y + 1, step, 2 if step_index <= index else 3, 1)

    accent = int(frame["accent"])
    canvas.rect(218, 79, 474, 266, 1)
    canvas.rect(218, 79, 6, 266, accent)
    canvas.text(252, 105, str(frame["title"]), 2, 2)
    canvas.rect(252, 139, 402, 1, 8)
    for line_index, line in enumerate(frame["lines"]):
        y = 166 + line_index * 42
        canvas.rect(252, y - 4, 388, 29, 0)
        canvas.rect(252, y - 4, 4, 29, accent)
        canvas.text(271, y + 3, str(line), 13, 1)
    canvas.text(252, 307, str(frame["note"]), accent, 1)

    canvas.rect(0, 374, WIDTH, 31, 1)
    canvas.text(28, 385, "SIMULATED PROTOCOL DEMO - NOT MODEL OUTPUT", 6, 1)
    canvas.text(624, 385, f"{index + 1} / {len(FRAMES)}", 3, 1)
    return bytes(canvas.pixels)


def _pack_fixed_codes(codes: list[int], width: int = 5) -> bytes:
    output = bytearray()
    buffer = 0
    bits = 0
    for code in codes:
        buffer |= code << bits
        bits += width
        while bits >= 8:
            output.append(buffer & 0xFF)
            buffer >>= 8
            bits -= 8
    if bits:
        output.append(buffer & 0xFF)
    return bytes(output)


def _literal_lzw(pixels: bytes) -> bytes:
    clear_code = 16
    end_code = 17
    codes: list[int] = []
    for offset in range(0, len(pixels), 12):
        codes.append(clear_code)
        codes.extend(pixels[offset : offset + 12])
    codes.append(end_code)
    encoded = _pack_fixed_codes(codes)
    blocks = bytearray([4])
    for offset in range(0, len(encoded), 255):
        block = encoded[offset : offset + 255]
        blocks.append(len(block))
        blocks.extend(block)
    blocks.append(0)
    return bytes(blocks)


def _subblocks(payload: bytes) -> bytes:
    blocks = bytearray()
    for offset in range(0, len(payload), 255):
        block = payload[offset : offset + 255]
        blocks.append(len(block))
        blocks.extend(block)
    blocks.append(0)
    return bytes(blocks)


def _encode_gif(frames: list[bytes]) -> bytes:
    output = bytearray(b"GIF89a")
    output.extend(struct.pack("<HHBBB", WIDTH, HEIGHT, 0xF3, 0, 0))
    for red, green, blue in PALETTE:
        output.extend((red, green, blue))
    output.extend(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")
    comment = b"Simulated protocol demonstration; not model output."
    output.extend(b"\x21\xfe" + _subblocks(comment))
    for pixels in frames:
        output.extend(b"\x21\xf9\x04\x00" + struct.pack("<H", 115) + b"\x00\x00")
        output.extend(b"\x2c" + struct.pack("<HHHHB", 0, 0, WIDTH, HEIGHT, 0))
        output.extend(_literal_lzw(pixels))
    output.append(0x3B)
    return bytes(output)


def build_demo(output_dir: Path) -> dict[str, object]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gif = _encode_gif([_draw_frame(index, frame) for index, frame in enumerate(FRAMES)])
    gif_path = output_dir / "preview-loop.gif"
    gif_path.write_bytes(gif)
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "demo_kind": "simulated_protocol",
        "model_output": False,
        "quality_evidence": False,
        "generator": "scripts/build_demo.py",
        "dimensions": {"width": WIDTH, "height": HEIGHT},
        "frames": [
            {"number": index + 1, "label": frame["label"], "state": frame["state"]}
            for index, frame in enumerate(FRAMES)
        ],
        "gif": {
            "path": "preview-loop.gif",
            "bytes": len(gif),
            "sha256": hashlib.sha256(gif).hexdigest(),
        },
        "disclaimer": "Deterministic simulated protocol demonstration. It is not model output or image-quality evidence.",
    }
    (output_dir / "demo-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic model-free protocol demo.")
    parser.add_argument("--output-dir", type=Path, default=Path("docs") / "demo")
    args = parser.parse_args()
    manifest = build_demo(args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
