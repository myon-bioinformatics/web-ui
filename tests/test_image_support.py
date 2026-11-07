"""Independent decode checks for the stdlib PNG fixture writer."""
import io, subprocess, sys
from pathlib import Path

import pytest
from PIL import Image
from tool.image_support.png import rgb_png


@pytest.mark.parametrize("size,color,rectangles", [
    ((1, 1), (0, 0, 0), []),
    ((64, 48), (200, 80, 40), []),
    ((64, 48), (13, 17, 23), [((8, 8, 24, 24), (255, 0, 0))]),
    ((40, 40), (0, 0, 255), [((0, 20, 20, 40), (255, 0, 0))]),
    ((5, 3), (1, 2, 3), [((0, 0, 5, 3), (255, 255, 255)), ((1, 1, 4, 3), (4, 5, 6))]),
])
def test_png_pixels_match_independent_pillow_decode(size, color, rectangles):
    image = Image.open(io.BytesIO(rgb_png(*size, color, rectangles=rectangles)))
    image.load()
    assert image.format == "PNG" and image.mode == "RGB" and image.size == size
    for y in range(size[1]):
        for x in range(size[0]):
            expected = color
            for (left, top, right, bottom), fill in rectangles:
                if left <= x < right and top <= y < bottom:
                    expected = fill
            assert image.getpixel((x, y)) == expected


def test_png_writer_works_without_site_packages():
    result = subprocess.run([sys.executable, "-S", "-c",
        "import sys; from tool.image_support.png import rgb_png; "
        "sys.stdout.buffer.write(rgb_png(64, 48, (200, 80, 40)))"],
        cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True)
    image = Image.open(io.BytesIO(result.stdout))
    image.load()
    assert image.size == (64, 48) and image.getpixel((63, 47)) == (200, 80, 40)


@pytest.mark.parametrize("args,kwargs", [
    ((0, 1, (0, 0, 0)), {}), ((True, 1, (0, 0, 0)), {}),
    ((4097, 1, (0, 0, 0)), {}), ((1, 1, (256, 0, 0)), {}),
    ((1, 1, (True, 0, 0)), {}), ((1, 1, (0, 0)), {}),
    ((2, 2, (0, 0, 0)), {"rectangles": [((-1, 0, 1, 1), (0, 0, 0))]}),
    ((2, 2, (0, 0, 0)), {"rectangles": [((0, 0, 3, 1), (0, 0, 0))]}),
    ((2, 2, (0, 0, 0)), {"rectangles": [((0, 0, 1), (0, 0, 0))]}),
])
def test_png_writer_rejects_invalid_input(args, kwargs):
    with pytest.raises(ValueError):
        rgb_png(*args, **kwargs)
