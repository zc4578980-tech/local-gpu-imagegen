#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path


def build_showcase(before: Path, after: Path, output: Path) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("showcase_requires_existing_local_pillow") from exc

    frames = []
    with Image.open(before) as first, Image.open(after) as second:
        for source in (first, second):
            converted = source.convert("RGB")
            try:
                frames.append(ImageOps.fit(converted, (960, 540)))
            finally:
                converted.close()
    try:
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=(1400, 1400),
            loop=0,
            optimize=True,
        )
    finally:
        for frame in frames:
            frame.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Encode a genuine before/after showcase GIF.")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_showcase(args.before, args.after, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
