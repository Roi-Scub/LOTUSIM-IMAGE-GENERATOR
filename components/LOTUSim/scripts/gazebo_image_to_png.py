#!/usr/bin/env python3
"""Save a Gazebo RGB Image JSON message as PNG, without changing its pixels."""

import argparse
import base64
import json
from pathlib import Path
import struct
import zlib


def rgb_message_to_png(message):
    if message.get("pixelFormatType") != "RGB_INT8":
        raise ValueError("Expected Gazebo pixelFormatType RGB_INT8")
    width, height = int(message["width"]), int(message["height"])
    step = int(message["step"])
    if width <= 0 or height <= 0 or step < width * 3:
        raise ValueError("Invalid image dimensions or RGB row stride")
    pixels = base64.b64decode(message["data"], validate=True)
    if len(pixels) != step * height:
        raise ValueError("Image data length does not match step * height")

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    # Filter 0 keeps each RGB row unchanged; remove only transport row padding.
    rows = b"".join(
        b"\x00" + pixels[y * step:y * step + width * 3]
        for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message", type=Path, help="gz topic --json-output -n 1 output")
    parser.add_argument("output", type=Path, help="New PNG file (existing files are preserved)")
    args = parser.parse_args()
    try:
        message = json.loads(args.message.read_text(encoding="utf-8"))
        png = rgb_message_to_png(message)
        with args.output.open("xb") as output:
            output.write(png)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Cannot export image: {error}\n")
    print(f"Saved {args.output}: {message['width']} x {message['height']} RGB")


if __name__ == "__main__":
    main()
