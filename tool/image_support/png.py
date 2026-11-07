"""Small stdlib-only RGB PNG fixtures, not a general image-processing API.

Rectangles use half-open (left, top, right, bottom) coordinates. This module
writes non-interlaced, 8-bit RGB PNGs; it does not decode screenshots or GIFs.
"""
from __future__ import annotations

import struct, zlib


def _rgb(color):
    if not isinstance(color, (tuple, list)) or len(color) != 3 or any(
        type(channel) is not int or not 0 <= channel <= 255 for channel in color
    ):
        raise ValueError("color must contain three integer channels from 0 to 255")
    return bytes(color)


def rgb_png(width, height, color, *, rectangles=()):
    """Return a PNG filled with color and optional (box, color) rectangles."""
    if any(type(n) is not int or not 1 <= n <= 4096 for n in (width, height)):
        raise ValueError("dimensions must be integers from 1 to 4096")
    pixels = bytearray(_rgb(color) * (width * height))
    for box, fill in rectangles:
        if not isinstance(box, (tuple, list)) or len(box) != 4 or any(type(n) is not int for n in box):
            raise ValueError("rectangle must contain four integer coordinates")
        left, top, right, bottom = box
        if not (0 <= left <= right <= width and 0 <= top <= bottom <= height):
            raise ValueError("rectangle must be inside the image")
        row = _rgb(fill) * (right - left)
        for y in range(top, bottom):
            start = (y * width + left) * 3
            pixels[start:start + len(row)] = row

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    stride = width * 3
    scanlines = b"".join(b"\0" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))
