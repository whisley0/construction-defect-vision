"""Test data download tracking API."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from ingestion.inspecto_csv import get_inspecto_status, import_inspecto_csv
from ingestion.test_data import (
    build_compare,
    build_status,
    clear_extractions,
    clear_session,
    extract_pending_files,
    get_auth_status,
    get_job,
    probe_sharepoint,
    re_extract_all,
    scan_local_folder,
    set_local_dir,
    set_session_cookie,
    start_download,
    start_remote_refresh,
    test_session_cookie,
)
from schemas.test_data import (
    AuthStatusResponse,
    CompareResponse,
    DownloadRequest,
    DownloadResponse,
    InspectoImportResponse,
    InspectoMetadataStatus,
    JobStatusResponse,
    SessionUpdate,
    TestDataClearExtractionsResponse,
    TestDataConfigUpdate,
    TestDataExtractRequest,
    TestDataExtractResponse,
    TestDataReExtractRequest,
    TestDataReExtractResponse,
    TestDataScanResponse,
    TestDataStatusResponse,
)

router = APIRouter(tags=["test-data"])


@router.get("/api/test-data/status", response_model=TestDataStatusResponse)
def test_data_status():
    return build_status()


@router.get("/api/test-data/auth/status", response_model=AuthStatusResponse)
def test_data_auth_status():
    return AuthStatusResponse(**get_auth_status())


@router.put("/api/test-data/session")
def test_data_set_session(body: SessionUpdate):
    try:
        return set_session_cookie(body.cookie)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/test-data/session/test")
def test_data_test_session(body: SessionUpdate):
    try:
        return test_session_cookie(body.cookie)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/test-data/auth/sign-out")
def test_data_auth_sign_out():
    clear_session()
    return {"ok": True}


@router.put("/api/test-data/config")
def test_data_set_config(body: TestDataConfigUpdate):
    local_dir = body.local_dir.strip()
    if not local_dir:
        raise HTTPException(400, "local_dir is required.")
    saved = set_local_dir(local_dir)
    return {"ok": True, "local_dir": saved}


@router.post("/api/test-data/scan", response_model=TestDataScanResponse)
def test_data_scan():
    return scan_local_folder()


@router.post("/api/test-data/remote/refresh", response_model=DownloadResponse)
def test_data_remote_refresh():
    auth = get_auth_status()
    if not auth["authenticated"]:
        raise HTTPException(401, "Paste your SharePoint browser cookie first.")
    return start_remote_refresh()


@router.get("/api/test-data/remote/probe")
def test_data_remote_probe():
    auth = get_auth_status()
    if not auth["authenticated"]:
        raise HTTPException(401, "Paste your SharePoint browser cookie first.")
    return probe_sharepoint()


@router.get("/api/test-data/compare", response_model=CompareResponse)
def test_data_compare(
    sync_status: str | None = Query(None, pattern="^(downloaded|missing|local_only)$"),
    local_status: str | None = Query(None, pattern="^(downloaded|extracted|error)$"),
    has_local: bool = Query(False),
    extracted_first: bool = Query(False),
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    return build_compare(
        sync_status=sync_status,
        local_status=local_status,
        has_local=has_local,
        extracted_first=extracted_first,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post("/api/test-data/download", response_model=DownloadResponse)
def test_data_download(body: DownloadRequest):
    auth = get_auth_status()
    if not auth["authenticated"]:
        raise HTTPException(401, "Paste your SharePoint browser cookie first.")
    try:
        return start_download(
            body.relative_paths,
            download_all_missing=body.download_all_missing,
            limit=min(body.limit, 200),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/test-data/jobs/{job_id}", response_model=JobStatusResponse)
def test_data_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


@router.post("/api/test-data/extract", response_model=TestDataExtractResponse)
def test_data_extract(body: TestDataExtractRequest | None = None):
    req = body or TestDataExtractRequest()
    paths = req.relative_paths or None
    return extract_pending_files(paths, limit=min(req.limit, 500))


@router.post("/api/test-data/clear-extractions", response_model=TestDataClearExtractionsResponse)
def test_data_clear_extractions():
    cleared, deleted = clear_extractions()
    status = build_status()
    return TestDataClearExtractionsResponse(
        ok=True,
        cleared_count=cleared,
        deleted_uploads=deleted,
        message=f"Cleared {cleared} extraction(s) and deleted {deleted} upload folder(s).",
        status=status,
    )


@router.post("/api/test-data/re-extract", response_model=TestDataReExtractResponse)
def test_data_re_extract(body: TestDataReExtractRequest | None = None):
    req = body or TestDataReExtractRequest()
    result = re_extract_all(limit=min(req.limit, 500))
    return TestDataReExtractResponse(**result)


@router.get("/api/test-data/inspecto-metadata/status", response_model=InspectoMetadataStatus)
def test_data_inspecto_status():
    return InspectoMetadataStatus(**get_inspecto_status())


@router.post("/api/test-data/inspecto-metadata/upload", response_model=InspectoImportResponse)
async def test_data_inspecto_upload(file: UploadFile = File(...)):
    filename = file.filename or "inspecto.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "A .csv file is required.")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file.")
    try:
        result = import_inspecto_csv(raw, source_filename=filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return InspectoImportResponse(
        status=InspectoMetadataStatus(**get_inspecto_status()),
        **result,
    )
