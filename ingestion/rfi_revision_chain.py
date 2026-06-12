"""Build chronological RFI revision chains from Inspecto metadata."""
from __future__ import annotations

from pathlib import Path

from ingestion.inspecto_csv import get_inspecto_records, lookup_inspecto_metadata
from ingestion.storage import load_extraction_index
from schemas.dataset import RfiRevisionImage, RfiRevisionStep, RfiRevisionTimelineResponse


def _norm(value: str | None) -> str:
    return (value or "").strip()


def build_form_index(records: dict[str, dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for rec in records.values():
        form = _norm(rec.get("Form No."))
        if form:
            index[form] = rec
    return index


def _revision_sort_key(form_no: str, rec: dict | None) -> tuple:
    date = _norm(rec.get("Inspected Date") if rec else "")
    time = _norm(rec.get("Inspected Time") if rec else "")
    return (date, time, form_no)


def build_children_index(records: dict[str, dict]) -> dict[str, list[str]]:
    by_form = build_form_index(records)
    children: dict[str, list[str]] = {}
    for rec in records.values():
        form = _norm(rec.get("Form No."))
        prev = _norm(rec.get("Previous Risc No."))
        if form and prev and prev != form and form in by_form:
            children.setdefault(prev, []).append(form)
    for prev, forms in children.items():
        children[prev] = sorted(forms, key=lambda f: _revision_sort_key(f, by_form.get(f)))
    return children


def find_root(form_no: str, by_form: dict[str, dict]) -> str:
    current = form_no
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        rec = by_form.get(current)
        if not rec:
            return current
        prev = _norm(rec.get("Previous Risc No."))
        if not prev or prev == current:
            return current
        current = prev
    return current


def build_chain_from_root(root: str, children: dict[str, list[str]]) -> list[str]:
    chain: list[str] = []
    current: str | None = root
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        chain.append(current)
        kids = [kid for kid in children.get(current, []) if kid not in visited]
        if not kids:
            break
        current = kids[0]
    return chain


def get_revision_chain(form_no: str, records: dict[str, dict]) -> list[str]:
    form_no = _norm(form_no)
    if not form_no:
        return []
    by_form = build_form_index(records)
    if form_no not in by_form:
        return []
    children = build_children_index(records)
    root = find_root(form_no, by_form)
    return build_chain_from_root(root, children)


_revision_count_cache: dict[str, int] | None = None
_revision_count_token: tuple | None = None
_form_upload_cache: dict[str, str] | None = None
_form_upload_token: tuple | None = None


def invalidate_revision_chain_cache() -> None:
    global _revision_count_cache, _revision_count_token, _form_upload_cache, _form_upload_token
    _revision_count_cache = None
    _revision_count_token = None
    _form_upload_cache = None
    _form_upload_token = None


def build_revision_counts(records: dict[str, dict] | None = None) -> dict[str, int]:
    """Map Inspecto Form No. -> number of revisions in its chain."""
    global _revision_count_cache, _revision_count_token

    from ingestion.inspecto_csv import INSPECTO_METADATA_PATH

    inspecto_mtime = INSPECTO_METADATA_PATH.stat().st_mtime if INSPECTO_METADATA_PATH.is_file() else 0.0
    token = (inspecto_mtime,)
    if _revision_count_cache is not None and _revision_count_token == token:
        return _revision_count_cache

    table = records if records is not None else get_inspecto_records()
    by_form = build_form_index(table)
    children = build_children_index(table)
    counts: dict[str, int] = {}
    seen_roots: set[str] = set()

    for form in by_form:
        root = find_root(form, by_form)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        chain = build_chain_from_root(root, children)
        chain_len = len(chain)
        for chain_form in chain:
            counts[chain_form] = chain_len

    _revision_count_cache = counts
    _revision_count_token = token
    return counts


def _form_upload_token_value() -> tuple:
    from ingestion.dataset_query import _MANIFEST_PATH

    manifest_mtime = _MANIFEST_PATH.stat().st_mtime if _MANIFEST_PATH.is_file() else 0.0
    return (manifest_mtime,)


def build_form_to_upload_map(records: dict[str, dict] | None = None) -> dict[str, str]:
    global _form_upload_cache, _form_upload_token

    token = _form_upload_token_value()
    if _form_upload_cache is not None and _form_upload_token == token:
        return _form_upload_cache

    from ingestion.test_data import STATUS_EXTRACTED, _load_manifest

    table = records if records is not None else get_inspecto_records()
    manifest = _load_manifest()
    mapping: dict[str, str] = {}

    for rel, entry in manifest.get("files", {}).items():
        if entry.get("status") != STATUS_EXTRACTED:
            continue
        upload_id = entry.get("upload_id")
        if not upload_id:
            continue
        index = load_extraction_index(upload_id)
        if not index:
            continue
        pdf_filename = index.get("filename") or entry.get("filename") or Path(rel).name
        inspecto = lookup_inspecto_metadata(
            filename=pdf_filename,
            relative_path=index.get("source_relative_path") or entry.get("relative_path") or rel,
            records=table,
        )
        if not inspecto:
            continue
        form = _norm(inspecto.get("Form No."))
        if form:
            mapping[form] = upload_id

    _form_upload_cache = mapping
    _form_upload_token = token
    return mapping


def _revision_images(upload_id: str) -> list[RfiRevisionImage]:
    index = load_extraction_index(upload_id)
    if not index:
        return []

    images: list[RfiRevisionImage] = []
    for img in index.get("images") or []:
        image_path = Path(str(img.get("image_path") or ""))
        image_filename = image_path.name
        if not image_filename:
            continue
        image_type = str(img.get("image_type") or "unknown")
        images.append(
            RfiRevisionImage(
                upload_id=upload_id,
                image_id=str(img.get("image_id") or image_filename),
                image_filename=image_filename,
                image_url=f"/api/rfi/{upload_id}/images/{image_filename}",
                image_type=image_type,
                page_number=int(img.get("page_number") or 0),
                width=int(img.get("width") or 0),
                height=int(img.get("height") or 0),
            )
        )
    return images


def get_rfi_revision_timeline(upload_id: str) -> RfiRevisionTimelineResponse:
    index = load_extraction_index(upload_id)
    if not index:
        raise ValueError(f"Extraction not found: {upload_id}")

    records = get_inspecto_records()
    pdf_filename = index.get("filename") or ""
    source_relative_path = index.get("source_relative_path")
    inspecto = lookup_inspecto_metadata(
        filename=pdf_filename,
        relative_path=source_relative_path,
        records=records,
    )
    if not inspecto:
        raise ValueError("No Inspecto metadata for this RFI.")

    current_form = _norm(inspecto.get("Form No."))
    if not current_form:
        raise ValueError("Inspecto record has no Form No.")

    chain_forms = get_revision_chain(current_form, records)
    by_form = build_form_index(records)
    form_to_upload = build_form_to_upload_map(records)

    revisions: list[RfiRevisionStep] = []
    for position, form in enumerate(chain_forms, start=1):
        rec = by_form.get(form, {})
        step_upload_id = form_to_upload.get(form)
        all_images = _revision_images(step_upload_id) if step_upload_id else []
        site_photos = [img for img in all_images if img.image_type == "site_photo"]
        revisions.append(
            RfiRevisionStep(
                position=position,
                form_no=form,
                upload_id=step_upload_id,
                pdf_filename=rec.get("pdf_filename"),
                is_last_revision=_norm(rec.get("Is Last Revision")).upper() == "Y",
                is_current=form == current_form,
                previous_risc_no=_norm(rec.get("Previous Risc No.")) or None,
                inspected_date=_norm(rec.get("Inspected Date")) or None,
                inspected_result=_norm(rec.get("Inspected Result")) or None,
                images=site_photos or all_images,
            )
        )

    return RfiRevisionTimelineResponse(
        current_upload_id=upload_id,
        current_form_no=current_form,
        revision_count=len(revisions),
        revisions=revisions,
    )
