"""Query extracted images joined with RFI metadata and source folder paths."""
from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath

from ingestion.dataset_labels import effective_image_type, is_trainable, label_source, update_image_label
from ingestion.inspecto_csv import INSPECTO_METADATA_PATH, get_inspecto_records, lookup_inspecto_metadata
from ingestion.rfi_revision_chain import build_revision_counts
from ingestion.storage import load_extraction_index
from schemas.dataset import (
    DatasetDistributions,
    DatasetImageItem,
    DatasetImagesResponse,
    DatasetSummaryResponse,
    DistributionSegment,
)
from schemas.image import ImageType

_items_cache: list[DatasetImageItem] | None = None
_cache_token: tuple | None = None
_build_lock = threading.Lock()
_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "test-data" / "manifest.json"


def _get_local_dir() -> str:
    from ingestion.test_data import get_local_dir

    return get_local_dir()


def invalidate_dataset_cache() -> None:
    global _items_cache, _cache_token
    _items_cache = None
    _cache_token = None
    from ingestion.rfi_revision_chain import invalidate_revision_chain_cache

    invalidate_revision_chain_cache()


def _cache_token_value() -> tuple:
    manifest_mtime = _MANIFEST_PATH.stat().st_mtime if _MANIFEST_PATH.is_file() else 0.0
    inspecto_mtime = INSPECTO_METADATA_PATH.stat().st_mtime if INSPECTO_METADATA_PATH.is_file() else 0.0
    return (manifest_mtime, inspecto_mtime)


def _source_folder(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    parent = PurePosixPath(relative_path).parent
    if str(parent) in (".", ""):
        return ""
    return str(parent)


def _matches_search(item: DatasetImageItem, search: str) -> bool:
    if not search:
        return True
    haystack = " ".join(
        filter(
            None,
            [
                item.image_id,
                item.pdf_filename,
                item.source_relative_path,
                item.source_folder,
                item.inspection_id,
                item.location,
                item.description_of_works,
                item.inspector_comments,
            ],
        )
    ).lower()
    return search.lower() in haystack


def _image_to_item(
    img: dict,
    *,
    upload_id: str,
    inspection: dict,
    pdf_filename: str,
    source_relative_path: str | None,
    source_folder: str | None,
    local_dir: str | None,
    extracted_at: str | None,
    inspecto_records: dict[str, dict],
    revision_counts: dict[str, int],
) -> DatasetImageItem | None:
    image_path = Path(str(img.get("image_path") or ""))
    image_filename = image_path.name
    if not image_filename:
        return None

    auto_type = str(img.get("image_type") or "unknown")
    effective = effective_image_type(img)
    inspecto = lookup_inspecto_metadata(
        filename=pdf_filename,
        relative_path=source_relative_path,
        records=inspecto_records,
    )
    form_no = (inspecto or {}).get("Form No.", "").strip() or None
    revision_count = revision_counts.get(form_no, 1) if form_no else 1
    return DatasetImageItem(
        upload_id=upload_id,
        image_id=str(img.get("image_id") or image_filename),
        image_filename=image_filename,
        image_url=f"/api/rfi/{upload_id}/images/{image_filename}",
        image_type=effective,
        auto_image_type=auto_type,
        label_source=label_source(img),
        width=int(img.get("width") or 0),
        height=int(img.get("height") or 0),
        page_number=int(img.get("page_number") or 0),
        filter_reason=img.get("filter_reason"),
        routing_confidence=img.get("routing_confidence"),
        hash=img.get("hash"),
        trainable=is_trainable(img),
        pdf_filename=pdf_filename,
        source_relative_path=source_relative_path,
        source_folder=source_folder,
        local_dir=local_dir,
        extracted_at=extracted_at,
        inspection_id=inspection.get("inspection_id"),
        location=inspection.get("location"),
        description_of_works=inspection.get("description_of_works"),
        subsequent_work=inspection.get("subsequent_work"),
        inspection_outcome=inspection.get("inspection_outcome") or "unknown",
        inspector_comments=inspection.get("inspector_comments"),
        inspected_by=inspection.get("inspected_by"),
        inspection_date=inspection.get("inspection_date"),
        reference_drawing_nos=inspection.get("reference_drawing_nos"),
        crosscheck_url=f"/crosscheck?upload_id={upload_id}",
        inspecto=inspecto,
        inspecto_form_no=form_no,
        revision_count=revision_count,
    )


def _build_items() -> list[DatasetImageItem]:
    global _items_cache, _cache_token

    token = _cache_token_value()
    if _items_cache is not None and _cache_token == token:
        return _items_cache

    with _build_lock:
        if _items_cache is not None and _cache_token == token:
            return _items_cache

        items = _build_items_uncached()
        _items_cache = items
        _cache_token = token
        return items


def _build_items_uncached() -> list[DatasetImageItem]:
    from ingestion.test_data import STATUS_EXTRACTED, _load_manifest, get_local_dir

    manifest = _load_manifest()
    files = manifest.get("files", {})
    local_dir = get_local_dir()
    inspecto_records = get_inspecto_records()
    revision_counts = build_revision_counts(inspecto_records)
    items: list[DatasetImageItem] = []

    for rel, entry in files.items():
        if entry.get("status") != STATUS_EXTRACTED:
            continue
        upload_id = entry.get("upload_id")
        if not upload_id:
            continue

        index = load_extraction_index(upload_id)
        if not index:
            continue

        inspection = index.get("inspection") or {}
        source_relative_path = index.get("source_relative_path") or entry.get("relative_path") or rel
        source_folder = _source_folder(source_relative_path)
        pdf_filename = index.get("filename") or entry.get("filename") or Path(rel).name
        extracted_at = entry.get("extracted_at")
        stored_local_dir = index.get("local_dir") or local_dir

        for img in index.get("images") or []:
            item = _image_to_item(
                img,
                upload_id=upload_id,
                inspection=inspection,
                pdf_filename=pdf_filename,
                source_relative_path=source_relative_path,
                source_folder=source_folder,
                local_dir=stored_local_dir,
                extracted_at=extracted_at,
                inspecto_records=inspecto_records,
                revision_counts=revision_counts,
            )
            if item:
                items.append(item)

    items.sort(key=lambda row: (row.source_relative_path or "", row.page_number, row.image_id))
    return items


def get_image_item(upload_id: str, image_id: str) -> DatasetImageItem:
    for item in _build_items():
        if item.upload_id == upload_id and item.image_id == image_id:
            return item
    raise ValueError(f"Image not found: {upload_id}/{image_id}")


def set_image_label(upload_id: str, image_id: str, image_type: ImageType | None) -> DatasetImageItem:
    update_image_label(upload_id, image_id, image_type)
    invalidate_dataset_cache()
    return get_image_item(upload_id, image_id)


OUTCOME_DISTRIBUTION_ORDER: list[tuple[str, str]] = [
    ("accepted", "Accepted"),
    ("conditionally_accepted_no_reinspection", "Cond. accepted (no re-inspection)"),
    ("conditionally_accepted_reinspection", "Cond. accepted (re-inspection)"),
    ("rejected", "Rejected"),
]

IMAGE_TYPE_DISTRIBUTION_ORDER: list[tuple[str, str]] = [
    ("site_photo", "Site photo"),
    ("drawing", "Drawing"),
    ("logo", "Logo"),
    ("stamp", "Stamp"),
    ("unknown", "Unknown"),
    ("skip", "Skip"),
]


def _build_distribution(
    items: list[DatasetImageItem],
    attr: str,
    ordered: list[tuple[str, str]],
) -> list[DistributionSegment]:
    total = len(items)
    counts: dict[str, int] = {}
    for item in items:
        key = str(getattr(item, attr) or "unknown")
        counts[key] = counts.get(key, 0) + 1

    segments: list[DistributionSegment] = []
    for key, label in ordered:
        count = counts.pop(key, 0)
        segments.append(
            DistributionSegment(
                key=key,
                label=label,
                count=count,
                percent=round(100.0 * count / total, 1) if total else 0.0,
            )
        )

    if counts:
        unknown_count = counts.pop("unknown", 0) + sum(counts.values())
        if unknown_count:
            segments.append(
                DistributionSegment(
                    key="unknown",
                    label="Unknown",
                    count=unknown_count,
                    percent=round(100.0 * unknown_count / total, 1) if total else 0.0,
                )
            )
    return segments


def build_distributions(items: list[DatasetImageItem]) -> DatasetDistributions:
    return DatasetDistributions(
        total=len(items),
        outcomes=_build_distribution(items, "inspection_outcome", OUTCOME_DISTRIBUTION_ORDER),
        image_types=_build_distribution(items, "image_type", IMAGE_TYPE_DISTRIBUTION_ORDER),
    )


def build_summary() -> DatasetSummaryResponse:
    items = _build_items()
    folders = sorted({item.source_folder or "" for item in items if item.source_relative_path})
    return DatasetSummaryResponse(
        local_dir=_get_local_dir(),
        extracted_pdfs=len({item.upload_id for item in items}),
        total_images=len(items),
        site_photos=sum(1 for item in items if item.image_type == "site_photo"),
        trainable_images=sum(1 for item in items if item.trainable),
        manually_labeled=sum(1 for item in items if item.label_source == "manual"),
        folders=folders,
    )


def query_images(
    *,
    search: str = "",
    image_type: str | None = None,
    inspection_outcome: str | None = None,
    folder: str | None = None,
    trainable_only: bool = False,
    manual_only: bool = False,
    multi_revision_only: bool = False,
    min_revisions: int = 2,
    page: int = 1,
    page_size: int = 48,
) -> DatasetImagesResponse:
    items = _build_items()
    filtered: list[DatasetImageItem] = []

    for item in items:
        if trainable_only and not item.trainable:
            continue
        if manual_only and item.label_source != "manual":
            continue
        if multi_revision_only and item.revision_count < min_revisions:
            continue
        if image_type and item.image_type != image_type:
            continue
        if inspection_outcome and item.inspection_outcome != inspection_outcome:
            continue
        if folder is not None:
            item_folder = item.source_folder or ""
            if item_folder != folder:
                continue
        if not _matches_search(item, search):
            continue
        filtered.append(item)

    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    end = start + page_size
    total_filtered = len(filtered)
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)

    return DatasetImagesResponse(
        local_dir=_get_local_dir(),
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        total_filtered=total_filtered,
        total_images=len(items),
        distributions=build_distributions(filtered),
        images=filtered[start:end],
    )
