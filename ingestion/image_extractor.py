"""Extract embedded images from PDF pages and classify for training eligibility."""
from __future__ import annotations

import hashlib
import io
import statistics
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from schemas.image import ImageRecord, ImageType

MIN_IMAGE_PX = 80
LOGO_MAX_PX = 120
DRAWING_MIN_PX = 900
SAMPLE_MAX_PX = 128
MAX_PIXELS_FOR_ANALYSIS = 24_000_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _analyze_pixels(data: bytes, *, width: int = 0, height: int = 0) -> dict[str, float]:
    """Sample embedded image pixels for brightness, color, and texture cues."""
    if width > 0 and height > 0 and (width * height) > MAX_PIXELS_FOR_ANALYSIS:
        return {}

    try:
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", (SAMPLE_MAX_PX, SAMPLE_MAX_PX))
    except Exception:
        return {}

    try:
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        sample = img.copy()
        sample.thumbnail((SAMPLE_MAX_PX, SAMPLE_MAX_PX), Image.Resampling.BILINEAR)
    except Exception:
        return {}
    pixels = list(sample.getdata())
    if not pixels:
        return {}

    brightness: list[float] = []
    saturations: list[float] = []
    for pixel in pixels:
        r, g, b = pixel[0], pixel[1], pixel[2]
        brightness.append((r + g + b) / 3.0)
        mx = max(r, g, b)
        mn = min(r, g, b)
        saturations.append((mx - mn) / mx if mx > 0 else 0.0)

    n = len(brightness)
    mean_b = sum(brightness) / n
    std_b = statistics.pstdev(brightness) if n > 1 else 0.0
    dark_frac = sum(1 for b in brightness if b < 35) / n
    white_frac = sum(1 for b in brightness if b > 235) / n
    mid_frac = sum(1 for b in brightness if 60 <= b <= 200) / n
    mean_sat = sum(saturations) / n

    return {
        "mean_brightness": mean_b,
        "std_brightness": std_b,
        "dark_frac": dark_frac,
        "white_frac": white_frac,
        "mid_frac": mid_frac,
        "mean_saturation": mean_sat,
    }


def _is_black_or_blank(stats: dict[str, float]) -> bool:
    if not stats:
        return False
    mean_b = stats.get("mean_brightness", 128)
    std_b = stats.get("std_brightness", 50)
    dark_frac = stats.get("dark_frac", 0)
    white_frac = stats.get("white_frac", 0)

    if dark_frac >= 0.88:
        return True
    if mean_b < 28 and std_b < 22:
        return True
    if white_frac >= 0.96 and std_b < 12:
        return True
    return False


def _is_drawing_like(stats: dict[str, float], *, max_dim: int, page_cover: float) -> bool:
    if not stats:
        return False
    white_frac = stats.get("white_frac", 0)
    mean_sat = stats.get("mean_saturation", 0)
    std_b = stats.get("std_brightness", 0)
    mid_frac = stats.get("mid_frac", 0)
    dark_frac = stats.get("dark_frac", 0)

    # Technical drawing: mostly white/light background, dark linework, low color.
    if white_frac >= 0.45 and mean_sat < 0.14 and std_b >= 18 and dark_frac >= 0.02:
        return True
    if max_dim >= DRAWING_MIN_PX and page_cover > 0.4 and mean_sat < 0.12 and white_frac >= 0.35:
        return True
    # Grayscale schematic with sparse mid-tones (not a natural photo).
    if mean_sat < 0.08 and white_frac >= 0.3 and mid_frac < 0.35 and std_b >= 25:
        return True
    return False


def _is_photo_like(stats: dict[str, float]) -> bool:
    if not stats:
        return True
    mean_sat = stats.get("mean_saturation", 0)
    std_b = stats.get("std_brightness", 0)
    white_frac = stats.get("white_frac", 0)
    dark_frac = stats.get("dark_frac", 0)
    mid_frac = stats.get("mid_frac", 0)

    if dark_frac >= 0.5 or white_frac >= 0.85:
        return False
    if mean_sat >= 0.1 and std_b >= 22:
        return True
    if mid_frac >= 0.35 and std_b >= 28:
        return True
    return mean_sat >= 0.07 and std_b >= 20


def _classify_image(
    width: int,
    height: int,
    page_width: float,
    page_height: float,
    *,
    page_text_chars: int = 0,
    image_data: bytes | None = None,
) -> tuple[ImageType, float, str | None]:
    """Heuristic routing: site photo vs drawing vs logo vs skip."""
    max_dim = max(width, height)
    min_dim = min(width, height)
    if max_dim < MIN_IMAGE_PX:
        return "logo", 0.9, "too_small"

    if max_dim <= LOGO_MAX_PX:
        return "logo", 0.85, "logo"

    stats = _analyze_pixels(image_data, width=width, height=height) if image_data else {}

    if _is_black_or_blank(stats):
        return "skip", 0.92, "black_or_blank"

    page_cover = 0.0
    if page_width > 0 and page_height > 0:
        page_cover = (width * height) / (page_width * page_height)

    if _is_drawing_like(stats, max_dim=max_dim, page_cover=page_cover):
        return "drawing", 0.82, "drawing"

    if max_dim >= DRAWING_MIN_PX and page_cover > 0.55 and page_text_chars > 200:
        return "drawing", 0.75, "drawing"

    # Attachment pages: only treat as site photo when pixels look photographic.
    if page_text_chars < 80 and max_dim >= 400 and _is_photo_like(stats):
        return "site_photo", 0.8, None

    if min_dim < 200 and page_cover < 0.15:
        return "stamp", 0.7, "stamp"

    if _is_photo_like(stats):
        return "site_photo", 0.65, None

    if max_dim >= 400 and not stats:
        return "drawing", 0.55, "large_image"

    if max_dim >= 400:
        return "drawing", 0.55, "low_color"

    return "unknown", 0.5, "unclassified"


def extract_images_from_pdf(
    pdf_bytes: bytes,
    *,
    output_dir: Path,
    inspection_id: str | None,
    prefix: str = "img",
) -> list[ImageRecord]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[ImageRecord] = []
    seen_hashes: set[str] = set()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_index, page in enumerate(doc, start=1):
            page_rect = page.rect
            page_text_chars = len((page.get_text("text") or "").strip())
            for img_index, img in enumerate(page.get_images(full=True), start=1):
                xref = img[0]
                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    continue
                data = extracted.get("image") or b""
                if not data:
                    continue
                digest = _sha256(data)
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)

                width = int(extracted.get("width") or 0)
                height = int(extracted.get("height") or 0)
                ext = extracted.get("ext") or "png"
                image_type, confidence, filter_reason = _classify_image(
                    width,
                    height,
                    float(page_rect.width),
                    float(page_rect.height),
                    page_text_chars=page_text_chars,
                    image_data=data,
                )
                image_id = f"{prefix}_p{page_index}_{img_index}"
                filename = f"{image_id}.{ext}"
                path = output_dir / filename
                path.write_bytes(data)

                records.append(
                    ImageRecord(
                        image_id=image_id,
                        inspection_id=inspection_id,
                        page_number=page_index,
                        source_ref=f"page:{page_index}/xref:{xref}",
                        image_path=str(path),
                        image_type=image_type,
                        width=width,
                        height=height,
                        routing_confidence=confidence,
                        hash=digest,
                        filter_reason=filter_reason,
                    )
                )
    finally:
        doc.close()

    return records
