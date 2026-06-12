"""RFI upload and extraction crosscheck API (pattern from FullStack_RAG pdf routes)."""
from __future__ import annotations

import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path

from ingestion.extract_service import process_rfi_pdf_bytes, rebuild_rfi_extraction
from ingestion.inspecto_csv import lookup_inspecto_metadata
from ingestion.storage import load_metadata, pdf_path, upload_dir
from schemas.api import RfiBatchExtractionResponse, RfiBatchItemError, RfiExtractionResponse

router = APIRouter(tags=["rfi"])

_MAX_BATCH_FILES = 100


def _require_pdf(filename: str | None) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "A .pdf file is required.")


def _parse_fail_fast(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


@router.post("/api/rfi/extract", response_model=RfiExtractionResponse)
async def rfi_extract(file: UploadFile = File(...)):
    """Upload one RFI PDF and return extraction crosscheck."""
    _require_pdf(file.filename)
    raw = await file.read()
    filename = file.filename or "upload.pdf"
    try:
        return process_rfi_pdf_bytes(raw, filename=filename)
    except ValueError as exc:
        raise HTTPException(422, detail={"type": "pdf_parse_error", "message": str(exc)}) from exc


@router.post("/api/rfi/extract-batch", response_model=RfiBatchExtractionResponse)
async def rfi_extract_batch(
    files: list[UploadFile] = File(...),
    fail_fast: str | None = Form(None),
):
    """
    Upload multiple RFI PDFs (folder or multi-select).
    Processes each file; by default continues on errors unless fail_fast=true.
    """
    if not files:
        raise HTTPException(400, "At least one file is required.")

    pdf_files = [f for f in files if (f.filename or "").lower().endswith(".pdf")]
    if not pdf_files:
        raise HTTPException(400, "No .pdf files in upload.")

    if len(pdf_files) > _MAX_BATCH_FILES:
        raise HTTPException(400, f"Too many files (max {_MAX_BATCH_FILES}).")

    stop_on_error = _parse_fail_fast(fail_fast)
    t0 = time.perf_counter()
    results: list[RfiExtractionResponse] = []
    errors: list[RfiBatchItemError] = []

    for upload in pdf_files:
        filename = upload.filename or "upload.pdf"
        try:
            raw = await upload.read()
            result = process_rfi_pdf_bytes(raw, filename=filename)
            results.append(result)
        except ValueError as exc:
            err = RfiBatchItemError(filename=filename, message=str(exc))
            errors.append(err)
            if stop_on_error:
                break
        except Exception as exc:
            err = RfiBatchItemError(filename=filename, message=str(exc))
            errors.append(err)
            if stop_on_error:
                break

    complete_count = sum(1 for r in results if r.crosscheck.complete)
    duration_ms = (time.perf_counter() - t0) * 1000
    return RfiBatchExtractionResponse(
        ok=len(errors) == 0,
        count=len(pdf_files),
        succeeded=len(results),
        failed=len(errors),
        complete_count=complete_count,
        results=results,
        errors=errors,
        duration_ms=round(duration_ms, 1),
    )


def _with_inspecto(result: RfiExtractionResponse) -> RfiExtractionResponse:
    inspecto = lookup_inspecto_metadata(filename=result.filename)
    if not inspecto:
        return result
    return result.model_copy(update={"inspecto": inspecto})


@router.get("/api/rfi/{upload_id}/extraction", response_model=RfiExtractionResponse)
async def rfi_get_extraction(upload_id: str):
    """Load crosscheck results for a previously extracted upload."""
    try:
        return _with_inspecto(rebuild_rfi_extraction(upload_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/api/rfi/{upload_id}/file")
async def rfi_pdf_file(upload_id: str):
    """Inline PDF preview (same pattern as FullStack_RAG GET /api/pdf/{id}/file)."""
    path = pdf_path(upload_id)
    if not path.is_file():
        raise HTTPException(404, "Upload not found.")
    meta = load_metadata(upload_id) or {}
    filename = meta.get("filename") or "document.pdf"
    return FileResponse(path, media_type="application/pdf", filename=filename, content_disposition_type="inline")


@router.get("/api/rfi/{upload_id}/images/{image_filename}")
async def rfi_image_file(upload_id: str, image_filename: str):
    path = upload_dir(upload_id) / "images" / Path(image_filename).name
    if not path.is_file():
        raise HTTPException(404, "Image not found.")
    ext = path.suffix.lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext.lstrip('.')}"
    return FileResponse(path, media_type=media)
