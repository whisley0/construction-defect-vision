"""Persist and resolve manual image label overrides in extraction indexes."""
from __future__ import annotations

from datetime import datetime, timezone

from ingestion.storage import load_extraction_index, save_extraction_index
from schemas.image import ImageType

VALID_IMAGE_TYPES: set[str] = {
    "site_photo",
    "drawing",
    "logo",
    "stamp",
    "unknown",
    "skip",
}


def effective_image_type(img: dict) -> str:
    manual = img.get("manual_image_type")
    if manual:
        return str(manual)
    return str(img.get("image_type") or "unknown")


def is_trainable(img: dict) -> bool:
    effective = effective_image_type(img)
    if img.get("manual_image_type"):
        return effective == "site_photo"
    return effective == "site_photo" and not img.get("filter_reason")


def label_source(img: dict) -> str:
    return "manual" if img.get("manual_image_type") else "auto"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_image(index: dict, image_id: str) -> dict | None:
    for img in index.get("images") or []:
        if str(img.get("image_id")) == image_id:
            return img
    return None


def update_image_label(upload_id: str, image_id: str, image_type: ImageType | None) -> dict:
    index = load_extraction_index(upload_id)
    if not index:
        raise ValueError(f"Extraction not found: {upload_id}")

    img = _find_image(index, image_id)
    if not img:
        raise ValueError(f"Image not found: {image_id}")

    auto_type = str(img.get("image_type") or "unknown")
    if image_type is None or image_type == auto_type:
        img.pop("manual_image_type", None)
        img.pop("label_updated_at", None)
    else:
        if image_type not in VALID_IMAGE_TYPES:
            raise ValueError(f"Invalid image type: {image_type}")
        img["manual_image_type"] = image_type
        img["label_updated_at"] = _utc_now()

    save_extraction_index(upload_id, index)
    return img
