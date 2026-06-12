"""Tests for embedded image pixel classification heuristics."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from ingestion.image_extractor import _classify_image


def _png_bytes(mode: str, size: tuple[int, int], fill, *, lines: bool = False) -> bytes:
    img = Image.new(mode, size, fill)
    if lines:
        draw = ImageDraw.Draw(img)
        for x in range(0, size[0], 40):
            draw.line([(x, 0), (x, size[1])], fill=(0, 0, 0), width=2)
        for y in range(0, size[1], 40):
            draw.line([(0, y), (size[0], y)], fill=(0, 0, 0), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_black_image_classified_as_skip():
    data = _png_bytes("RGB", (800, 600), (5, 5, 8))
    image_type, _, reason = _classify_image(
        800,
        600,
        800,
        600,
        page_text_chars=10,
        image_data=data,
    )
    assert image_type == "skip"
    assert reason == "black_or_blank"


def test_drawing_with_grid_classified_as_drawing():
    data = _png_bytes("RGB", (1200, 900), (255, 255, 255), lines=True)
    image_type, _, reason = _classify_image(
        1200,
        900,
        1200,
        900,
        page_text_chars=10,
        image_data=data,
    )
    assert image_type == "drawing"
    assert reason in ("drawing", "low_color")


def test_colorful_photo_like_image_on_attachment_page():
    data = _png_bytes("RGB", (800, 600), (120, 80, 40))
    # Add color variation
    img = Image.open(io.BytesIO(data))
    pixels = img.load()
    for x in range(800):
        for y in range(600):
            pixels[x, y] = ((x * 3 + y * 2) % 200 + 40, (x + y) % 180 + 30, (y * 2) % 160 + 20)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    image_type, _, reason = _classify_image(
        800,
        600,
        800,
        600,
        page_text_chars=10,
        image_data=data,
    )
    assert image_type == "site_photo"
    assert reason is None


def test_large_black_on_attachment_page_not_site_photo():
    data = _png_bytes("RGB", (1000, 800), (0, 0, 0))
    image_type, _, _ = _classify_image(
        1000,
        800,
        1000,
        800,
        page_text_chars=5,
        image_data=data,
    )
    assert image_type != "site_photo"
