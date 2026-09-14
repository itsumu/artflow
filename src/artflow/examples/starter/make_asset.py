"""Build and verify a tiny RGBA PNG sprite using only Python's standard library."""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def parse_color(value: str) -> bytes:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    try:
        return bytes.fromhex(value[1:]) + b"\xff"
    except ValueError as error:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}") from error


def load_recipe(path: Path) -> tuple[int, int, int, dict[str, bytes], list[str]]:
    recipe = json.loads(path.read_text(encoding="utf-8"))
    pixels = recipe.get("pixels")
    scale = recipe.get("scale")
    canvas = recipe.get("canvas")
    palette = recipe.get("palette")
    if not isinstance(pixels, list) or not pixels or not all(isinstance(row, str) for row in pixels):
        raise ValueError("pixels must be a non-empty array of strings")
    source_width = len(pixels[0])
    if not source_width or any(len(row) != source_width for row in pixels):
        raise ValueError("every pixel row must have the same non-zero width")
    if type(scale) is not int or not 1 <= scale <= 32:
        raise ValueError("scale must be an integer from 1 to 32")
    width, height = source_width * scale, len(pixels) * scale
    if canvas != [width, height]:
        raise ValueError(f"canvas must match the scaled pixel grid: {[width, height]}")
    if not isinstance(palette, dict):
        raise ValueError("palette must map one-character symbols to #RRGGBB colors")
    colors = {}
    for symbol, value in palette.items():
        if not isinstance(symbol, str) or len(symbol) != 1 or symbol == ".":
            raise ValueError("palette keys must be one character; '.' is reserved for transparency")
        colors[symbol] = parse_color(value)
    unknown = sorted({symbol for row in pixels for symbol in row if symbol != "." and symbol not in colors})
    if unknown:
        raise ValueError("pixels use symbols missing from palette: " + ", ".join(unknown))
    return width, height, scale, colors, pixels


def build(recipe_path: Path, output: Path) -> None:
    width, height, scale, colors, pixels = load_recipe(recipe_path)
    transparent = b"\x00\x00\x00\x00"
    scanlines = []
    for row in pixels:
        expanded = b"".join((transparent if symbol == "." else colors[symbol]) * scale for symbol in row)
        scanlines.extend(b"\x00" + expanded for _ in range(scale))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = PNG_SIGNATURE + png_chunk(b"IHDR", header)
    png += png_chunk(b"IDAT", zlib.compress(b"".join(scanlines), level=9))
    png += png_chunk(b"IEND", b"")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(png)
    temporary.replace(output)
    print(f"Created {output.name}: {width}x{height} RGBA PNG", flush=True)


def verify(path: Path) -> None:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    cursor = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        length = struct.unpack(">I", data[cursor:cursor + 4])[0]
        kind = data[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        payload_end = payload_start + length
        checksum_end = payload_end + 4
        if checksum_end > len(data):
            raise ValueError("truncated PNG payload")
        expected = struct.unpack(">I", data[payload_end:checksum_end])[0]
        actual = zlib.crc32(kind)
        actual = zlib.crc32(data[payload_start:payload_end], actual) & 0xFFFFFFFF
        if actual != expected:
            raise ValueError(f"bad CRC in {kind.decode('ascii', errors='replace')} chunk")
        chunks.append((kind, data[payload_start:payload_end]))
        cursor = checksum_end
        if kind == b"IEND":
            break
    if not chunks or chunks[0][0] != b"IHDR" or chunks[-1][0] != b"IEND" or cursor != len(data):
        raise ValueError("PNG must contain IHDR through IEND with no trailing data")
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if depth != 8 or color_type != 6 or (compression, filtering, interlace) != (0, 0, 0):
        raise ValueError("expected an 8-bit, non-interlaced RGBA PNG")
    raw = zlib.decompress(b"".join(payload for kind, payload in chunks if kind == b"IDAT"))
    stride = 1 + width * 4
    if len(raw) != height * stride or any(raw[row * stride] != 0 for row in range(height)):
        raise ValueError("unexpected PNG scanline layout")
    alpha = b"".join(raw[row * stride + 4:(row + 1) * stride:4] for row in range(height))
    if not any(value == 0 for value in alpha) or not any(value == 255 for value in alpha):
        raise ValueError("sprite must contain both transparent and opaque pixels")
    print(f"Verified {path.name}: {width}x{height}, hard-alpha RGBA", flush=True)


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "build":
        build(Path(argv[2]), Path(argv[3]))
        return 0
    if len(argv) == 3 and argv[1] == "verify":
        verify(Path(argv[2]))
        return 0
    raise SystemExit("Usage: make_asset.py build <recipe.json> <output.png> | verify <output.png>")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
