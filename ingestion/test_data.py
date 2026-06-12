"""Track test data downloaded from SharePoint into a local folder."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ingestion.extract_service import process_rfi_pdf_bytes
from ingestion.inspecto_csv import get_inspecto_records, lookup_inspecto_metadata
from ingestion.storage import UPLOADS_DIR, load_extraction_index, purge_all_uploads
from ingestion.sharepoint_rest import (
    discover_remote_pdfs,
    download_file,
    normalize_browser_cookie,
    probe_all_sources,
    site_url_for_server_path,
    verify_session,
)
from schemas.api import RfiExtractionResponse
from schemas.test_data import (
    CompareFileRecord,
    CompareResponse,
    DownloadResponse,
    JobStatusResponse,
    SharePointSourceInfo,
    TestDataExtractItemError,
    TestDataExtractResponse,
    TestDataFileRecord,
    TestDataScanResponse,
    TestDataStatusResponse,
)

SHAREPOINT_SOURCE = SharePointSourceInfo(
    id="j3968-risc-export",
    name="J3968 RISC Export",
    share_url=(
        "https://gammon-my.sharepoint.com/my?remoteItem=%7B%22mp%22%3A%7B%22webAbsoluteUrl%22%3A%22"
        "https%3A%2F%2Fgammon%2Dmy%2Esharepoint%2Ecom%2Fpersonal%2Fedwardlam%5Fgammonconstruction%5Fcom%22%2C"
        "%22listFullUrl%22%3A%22https%3A%2F%2Fgammon%2Dmy%2Esharepoint%2Ecom%2Fpersonal%2Fedwardlam%5F"
        "gammonconstruction%5Fcom%2FDocuments%22%2C%22rootFolder%22%3A%22%2Fpersonal%2Fedwardlam%5F"
        "gammonconstruction%5Fcom%2FDocuments%2FJamie%20Yuk%20Chi%20Wan%27s%20files%20%2D%20J3968%5FRISC%5F"
        "Export%22%7D%2C%22rsi%22%3A%7B%22webAbsoluteUrl%22%3A%22https%3A%2F%2Fgammon%2Dmy%2Esharepoint%2E"
        "com%2Fpersonal%2Fjamiewan%5Fgammonconstruction%5Fcom%22%2C%22listFullUrl%22%3A%22https%3A%2F%2F"
        "gammon%2Dmy%2Esharepoint%2Ecom%2Fpersonal%2Fjamiewan%5Fgammonconstruction%5Fcom%2FDocuments%22%2C"
        "%22rootFolder%22%3A%22%2Fpersonal%2Fjamiewan%5Fgammonconstruction%5Fcom%2FDocuments%2FJ3968%5F"
        "RISC%5FExport%22%7D%7D"
    ),
    owner_site="https://gammon-my.sharepoint.com/personal/jamiewan_gammonconstruction_com",
    folder_path="/personal/jamiewan_gammonconstruction_com/Documents/J3968_RISC_Export",
    synced_folder_name="Jamie Yuk Chi Wan's files - J3968_RISC_Export",
    rest_site_url="https://gammon-my.sharepoint.com/personal/edwardlam_gammonconstruction_com",
    rest_folder_path=(
        "/personal/edwardlam_gammonconstruction_com/Documents/"
        "Jamie Yuk Chi Wan's files - J3968_RISC_Export"
    ),
)

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
TEST_DATA_DIR = DATA_ROOT / "test-data"
DEFAULT_LOCAL_DIR = TEST_DATA_DIR / "downloads"
MANIFEST_PATH = TEST_DATA_DIR / "manifest.json"
CONFIG_PATH = TEST_DATA_DIR / "config.json"

STATUS_DOWNLOADED = "downloaded"
STATUS_EXTRACTED = "extracted"
STATUS_ERROR = "error"

SYNC_DOWNLOADED = "downloaded"
SYNC_MISSING = "missing"
SYNC_LOCAL_ONLY = "local_only"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invalidate_dataset_cache() -> None:
    from ingestion.dataset_query import invalidate_dataset_cache

    invalidate_dataset_cache()


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lower()


def _default_local_dir() -> str:
    env_dir = os.environ.get("CDV_TEST_DATA_DIR", "").strip()
    if env_dir:
        return str(Path(env_dir).expanduser())
    return str(DEFAULT_LOCAL_DIR)


def _ensure_dirs() -> None:
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_LOCAL_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    _ensure_dirs()
    if CONFIG_PATH.is_file():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def _save_config(config: dict) -> None:
    _ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _load_manifest() -> dict:
    _ensure_dirs()
    if MANIFEST_PATH.is_file():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "source_id": SHAREPOINT_SOURCE.id,
        "last_scan_at": None,
        "remote_inventory_at": None,
        "remote_files": {},
        "files": {},
    }


def _save_manifest(manifest: dict) -> None:
    _ensure_dirs()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")


def get_local_dir() -> str:
    config = _load_config()
    local_dir = config.get("local_dir") or _default_local_dir()
    return str(Path(local_dir).expanduser())


def set_local_dir(local_dir: str) -> str:
    path = Path(local_dir).expanduser()
    config = _load_config()
    config["local_dir"] = str(path)
    _save_config(config)
    return str(path)


def get_session_cookie() -> str | None:
    config = _load_config()
    env_cookie = os.environ.get("CDV_SHAREPOINT_COOKIE", "").strip()
    cookie = env_cookie or config.get("sharepoint_cookie", "").strip()
    return cookie or None


def set_session_cookie(cookie: str) -> dict:
    try:
        cleaned = normalize_browser_cookie(cookie)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not cleaned:
        raise ValueError("Cookie is required.")

    sites = [
        SHAREPOINT_SOURCE.rest_site_url,
        "https://gammon-my.sharepoint.com/personal/jamiewan_gammonconstruction_com",
    ]
    last_error: ValueError | None = None
    account: str | None = None
    for site_url in sites:
        try:
            account = verify_session(site_url, cleaned)
            break
        except ValueError as exc:
            last_error = exc
    if not account:
        raise last_error or ValueError("SharePoint session invalid.")

    config = _load_config()
    config["sharepoint_cookie"] = cleaned
    config["sharepoint_account"] = account
    _save_config(config)
    return {"ok": True, "account": account}


def clear_session() -> None:
    config = _load_config()
    config.pop("sharepoint_cookie", None)
    config.pop("sharepoint_account", None)
    _save_config(config)


def get_auth_status() -> dict:
    cookie = get_session_cookie()
    if not cookie:
        return {
            "authenticated": False,
            "account": None,
            "message": "Paste your browser Cookie from SharePoint (see instructions below).",
            "cookie_saved": False,
        }
    config = _load_config()
    account = config.get("sharepoint_account")
    return {
        "authenticated": True,
        "account": account,
        "message": f"Session saved{f' for {account}' if account else ''}. Refresh if downloads fail.",
        "cookie_saved": True,
    }


def test_session_cookie(cookie: str) -> dict:
    account = verify_session(SHAREPOINT_SOURCE.rest_site_url, cookie.strip())
    return {"ok": True, "account": account}


def probe_sharepoint() -> dict:
    cookie = get_session_cookie()
    if not cookie:
        raise ValueError("SharePoint session not configured.")
    return {"ok": True, "sources": probe_all_sources(cookie)}


def _iter_pdf_files(root: Path) -> list[tuple[str, Path]]:
    pdfs: list[tuple[str, Path]] = []
    if not root.is_dir():
        return pdfs
    for path in sorted(root.rglob("*.pdf")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        pdfs.append((rel, path))
    return pdfs


def _file_record_from_disk(rel: str, path: Path, existing: dict | None) -> dict:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    base = {
        "relative_path": rel,
        "filename": path.name,
        "size_bytes": stat.st_size,
        "modified_at": modified_at,
    }
    if existing:
        merged = {**existing, **base}
        if merged.get("status") == STATUS_EXTRACTED and merged.get("upload_id"):
            return merged
        if merged.get("status") == STATUS_ERROR:
            merged["status"] = STATUS_DOWNLOADED
            merged["error"] = None
        else:
            merged["status"] = STATUS_DOWNLOADED
        return merged
    return {**base, "status": STATUS_DOWNLOADED, "upload_id": None, "extracted_at": None, "error": None}


def _local_path_set(root: Path) -> dict[str, str]:
    return {_norm_path(rel): rel for rel, _ in _iter_pdf_files(root)}


def _remote_map(manifest: dict) -> dict[str, dict]:
    return manifest.get("remote_files", {})


def _compare_sets(manifest: dict, root: Path | None) -> dict[str, int]:
    remote = _remote_map(manifest)
    local_norm: dict[str, str] = _local_path_set(root) if root and root.is_dir() else {}
    remote_norm = {_norm_path(k): k for k in remote}
    remote_keys = set(remote_norm)
    local_keys = set(local_norm)
    downloaded = remote_keys & local_keys
    missing = remote_keys - local_keys
    local_only = local_keys - remote_keys
    return {
        "remote_total": len(remote_keys),
        "local_total": len(local_keys),
        "downloaded_count": len(downloaded),
        "missing_count": len(missing),
        "local_only_count": len(local_only),
    }


def reconcile_extracted_manifest(manifest: dict | None = None) -> int:
    """Re-link extracted upload folders back into manifest file records."""
    manifest = manifest if manifest is not None else _load_manifest()
    local_dir = Path(get_local_dir())
    files = manifest.setdefault("files", {})
    linked = 0

    if not UPLOADS_DIR.is_dir():
        return 0

    for upload_dir in sorted(UPLOADS_DIR.iterdir()):
        if not upload_dir.is_dir():
            continue
        index = load_extraction_index(upload_dir.name)
        if not index:
            continue
        rel = index.get("source_relative_path")
        if not rel or rel not in files:
            continue

        entry = dict(files[rel])
        disk_path = local_dir / Path(rel)
        if disk_path.is_file():
            stat = disk_path.stat()
            entry["size_bytes"] = stat.st_size
            entry["modified_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        entry.update(
            {
                "relative_path": rel,
                "filename": index.get("filename") or Path(rel).name,
                "status": STATUS_EXTRACTED,
                "upload_id": upload_dir.name,
                "extracted_at": entry.get("extracted_at") or index.get("extracted_at"),
                "error": None,
            }
        )
        files[rel] = entry
        linked += 1

    if linked:
        _save_manifest(manifest)
        _invalidate_dataset_cache()
    return linked


def scan_local_folder() -> TestDataScanResponse:
    local_dir = get_local_dir()
    root = Path(local_dir)
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest()
    existing_files: dict[str, dict] = manifest.get("files", {})
    discovered = _iter_pdf_files(root)
    updated: dict[str, dict] = {}

    for rel, path in discovered:
        updated[rel] = _file_record_from_disk(rel, path, existing_files.get(rel))

    manifest["files"] = updated
    manifest["last_scan_at"] = _utc_now()
    manifest["source_id"] = SHAREPOINT_SOURCE.id
    reconcile_extracted_manifest(manifest)
    _save_manifest(manifest)
    _invalidate_dataset_cache()

    status = build_status()
    return TestDataScanResponse(
        ok=True,
        message=f"Found {len(updated)} PDF(s) in {local_dir}",
        status=status,
    )


def build_status() -> TestDataStatusResponse:
    local_dir = get_local_dir()
    local_path = Path(local_dir)
    manifest = _load_manifest()
    files = manifest.get("files", {})
    counts = _compare_sets(manifest, local_path if local_path.is_dir() else None)
    records: list[TestDataFileRecord] = []

    for rel in sorted(files):
        entry = files[rel]
        records.append(
            TestDataFileRecord(
                relative_path=entry.get("relative_path") or rel,
                filename=entry.get("filename") or Path(rel).name,
                size_bytes=int(entry.get("size_bytes") or 0),
                modified_at=entry.get("modified_at") or "",
                status=entry.get("status", STATUS_DOWNLOADED),
                upload_id=entry.get("upload_id"),
                extracted_at=entry.get("extracted_at"),
                error=entry.get("error"),
            )
        )

    extracted = sum(1 for r in records if r.status == STATUS_EXTRACTED)
    pending_extract = sum(1 for r in records if r.status == STATUS_DOWNLOADED)
    errors = sum(1 for r in records if r.status == STATUS_ERROR)

    return TestDataStatusResponse(
        source=SHAREPOINT_SOURCE,
        local_dir=local_dir,
        local_dir_exists=local_path.is_dir(),
        last_scan_at=manifest.get("last_scan_at"),
        remote_inventory_at=manifest.get("remote_inventory_at"),
        remote_total=counts["remote_total"],
        total_files=len(records),
        downloaded_count=counts["downloaded_count"] if counts["remote_total"] else len(records),
        missing_count=counts["missing_count"],
        local_only_count=counts["local_only_count"],
        extracted_count=extracted,
        pending_extract_count=pending_extract,
        error_count=errors,
        files=records[:200],
    )


def _local_status_sort_key(local_status: str | None) -> tuple[int, str]:
    """Extracted first for crosscheck review; not-yet-extracted PDFs last."""
    order = {
        STATUS_EXTRACTED: 0,
        STATUS_ERROR: 1,
        STATUS_DOWNLOADED: 2,
    }
    return (order.get(local_status or STATUS_DOWNLOADED, 3), "")


def build_compare(
    *,
    sync_status: str | None = None,
    local_status: str | None = None,
    has_local: bool = False,
    extracted_first: bool = False,
    search: str = "",
    page: int = 1,
    page_size: int = 100,
) -> CompareResponse:
    local_dir = get_local_dir()
    root = Path(local_dir)
    manifest = _load_manifest()
    remote = _remote_map(manifest)
    local_files = manifest.get("files", {})
    local_norm = {_norm_path(rel): rel for rel in local_files}
    if root.is_dir():
        for norm, rel in _local_path_set(root).items():
            local_norm.setdefault(norm, rel)

    rows: list[CompareFileRecord] = []
    all_paths = set(remote) | set(local_norm.values())

    for rel in sorted(all_paths, key=str.lower):
        norm = _norm_path(rel)
        in_remote = rel in remote or norm in {_norm_path(k) for k in remote}
        remote_key = rel if rel in remote else next((k for k in remote if _norm_path(k) == norm), None)
        in_local = norm in local_norm
        if in_remote and in_local:
            status = SYNC_DOWNLOADED
        elif in_remote:
            status = SYNC_MISSING
        else:
            status = SYNC_LOCAL_ONLY

        if sync_status and status != sync_status:
            continue
        if has_local and status == SYNC_MISSING:
            continue

        remote_entry = remote.get(remote_key, {}) if remote_key else {}
        local_entry = local_files.get(local_norm.get(norm, rel), {})
        entry_local_status = local_entry.get("status")
        if local_status and entry_local_status != local_status:
            continue

        haystack = rel.lower()
        if search and search.lower() not in haystack:
            continue

        rows.append(
            CompareFileRecord(
                relative_path=rel,
                filename=Path(rel).name,
                size_bytes=remote_entry.get("size_bytes") or local_entry.get("size_bytes"),
                modified_at=remote_entry.get("modified_at") or local_entry.get("modified_at"),
                sync_status=status,
                local_status=local_entry.get("status"),
                upload_id=local_entry.get("upload_id"),
                item_id=remote_entry.get("item_id"),
                inspecto=lookup_inspecto_metadata(
                    relative_path=rel,
                    filename=Path(rel).name,
                    records=get_inspecto_records(),
                ),
            )
        )

    if extracted_first:
        rows.sort(
            key=lambda row: (
                _local_status_sort_key(row.local_status)[0],
                row.relative_path.lower(),
            )
        )
    else:
        rows.sort(key=lambda row: row.relative_path.lower())

    counts = _compare_sets(manifest, root if root.is_dir() else None)
    total_filtered = len(rows)
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)

    return CompareResponse(
        remote_total=counts["remote_total"],
        local_total=counts["local_total"],
        downloaded_count=counts["downloaded_count"],
        missing_count=counts["missing_count"],
        local_only_count=counts["local_only_count"],
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        total_filtered=total_filtered,
        files=page_rows,
    )


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.setdefault(job_id, {"job_id": job_id})
        job.update(fields)


def get_job(job_id: str) -> JobStatusResponse | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return None
    return JobStatusResponse(**{k: job.get(k) for k in JobStatusResponse.model_fields})


def start_remote_refresh() -> DownloadResponse:
    job_id = str(uuid.uuid4())
    _set_job(
        job_id,
        kind="remote_refresh",
        status="running",
        message="Starting SharePoint scan…",
        total=0,
        completed=0,
        failed=0,
        error=None,
    )

    def run() -> None:
        try:
            cookie = get_session_cookie()
            if not cookie:
                raise ValueError("SharePoint session not configured.")

            def progress(msg: str, count: int) -> None:
                _set_job(job_id, message=msg, completed=count)

            remote_list, source_label = discover_remote_pdfs(cookie, progress_cb=progress)
            manifest = _load_manifest()
            manifest["remote_list_source"] = source_label
            manifest["remote_files"] = {
                rf.relative_path: {
                    "relative_path": rf.relative_path,
                    "filename": rf.filename,
                    "server_relative_url": rf.server_relative_url,
                    "site_url": rf.site_url,
                    "size_bytes": rf.size_bytes,
                    "modified_at": rf.modified_at,
                }
                for rf in remote_list
            }
            manifest["remote_inventory_at"] = _utc_now()
            _save_manifest(manifest)
            msg = f"Indexed {len(remote_list)} PDF(s) from SharePoint ({source_label})."
            if not remote_list:
                msg = "No PDFs found. Check that the SharePoint folder contains .pdf files you can see in the browser."
            _set_job(
                job_id,
                status="done" if remote_list else "error",
                message=msg,
                total=len(remote_list),
                completed=len(remote_list),
                error=None if remote_list else msg,
            )
        except Exception as exc:
            _set_job(job_id, status="error", error=str(exc), message=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return DownloadResponse(ok=True, job_id=job_id, message="SharePoint scan started.")


def start_download(relative_paths: list[str] | None = None, *, download_all_missing: bool = False, limit: int = 50) -> DownloadResponse:
    local_dir = get_local_dir()
    root = Path(local_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    remote = _remote_map(manifest)
    if not remote:
        raise ValueError("Refresh SharePoint file list first.")

    local_norm = _local_path_set(root)
    targets: list[str] = []

    if download_all_missing:
        for rel in sorted(remote):
            if _norm_path(rel) not in local_norm:
                targets.append(rel)
                if len(targets) >= limit:
                    break
    else:
        for rel in relative_paths or []:
            if rel in remote:
                targets.append(rel)

    if not targets:
        raise ValueError("No files selected to download.")

    job_id = str(uuid.uuid4())
    _set_job(
        job_id,
        kind="download",
        status="running",
        message=f"Downloading {len(targets)} file(s)…",
        total=len(targets),
        completed=0,
        failed=0,
        error=None,
    )

    def run() -> None:
        try:
            cookie = get_session_cookie()
            if not cookie:
                raise ValueError("SharePoint session not configured.")
            succeeded = 0
            failed = 0
            files = manifest.get("files", {})
            for rel in targets:
                entry = remote[rel]
                dest = root / Path(rel)
                try:
                    site = entry.get("site_url") or site_url_for_server_path(entry["server_relative_url"])
                    download_file(
                        site_url=site,
                        server_relative_url=entry["server_relative_url"],
                        dest=dest,
                        cookie=cookie,
                    )
                    files[rel] = _file_record_from_disk(rel, dest, files.get(rel))
                    succeeded += 1
                except Exception as exc:
                    failed += 1
                    files[rel] = {
                        "relative_path": rel,
                        "filename": entry["filename"],
                        "size_bytes": entry.get("size_bytes", 0),
                        "modified_at": entry.get("modified_at", _utc_now()),
                        "status": STATUS_ERROR,
                        "error": str(exc),
                    }
                _set_job(
                    job_id,
                    message=f"Downloaded {succeeded}/{len(targets)} — {rel}",
                    completed=succeeded + failed,
                    failed=failed,
                )

            manifest["files"] = files
            manifest["last_scan_at"] = _utc_now()
            _save_manifest(manifest)
            _set_job(
                job_id,
                status="done" if failed == 0 else "error",
                message=f"Downloaded {succeeded}/{len(targets)} file(s).",
                completed=succeeded + failed,
                failed=failed,
                error=None if failed == 0 else f"{failed} download(s) failed",
            )
        except Exception as exc:
            _set_job(job_id, status="error", error=str(exc), message=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return DownloadResponse(ok=True, job_id=job_id, message=f"Downloading {len(targets)} file(s)…")


def clear_extractions() -> tuple[int, int]:
    """Reset extracted manifest entries and delete all upload folders. Returns (cleared, deleted)."""
    manifest = _load_manifest()
    files: dict[str, dict] = manifest.get("files", {})
    cleared = 0

    for entry in files.values():
        if entry.get("status") not in (STATUS_EXTRACTED, STATUS_ERROR):
            continue
        entry["status"] = STATUS_DOWNLOADED
        entry["upload_id"] = None
        entry["extracted_at"] = None
        entry["error"] = None
        cleared += 1

    manifest["files"] = files
    _save_manifest(manifest)
    deleted = purge_all_uploads()
    _invalidate_dataset_cache()
    return cleared, deleted


def re_extract_all(*, limit: int = 500) -> dict:
    """Clear prior extractions, rescan local folder, and extract again with updated pipeline."""
    cleared, deleted = clear_extractions()
    scan = scan_local_folder()
    batch_size = max(1, min(limit, 500))
    total_attempted = 0
    total_succeeded = 0
    total_failed = 0
    all_errors: list[TestDataExtractItemError] = []
    status = scan.status

    while True:
        extract = extract_pending_files(limit=batch_size)
        status = extract.status
        total_attempted += extract.attempted
        total_succeeded += extract.succeeded
        total_failed += extract.failed
        all_errors.extend(extract.errors)
        if extract.attempted == 0:
            break

    return {
        "cleared_count": cleared,
        "deleted_uploads": deleted,
        "scanned_files": scan.status.total_files,
        "attempted": total_attempted,
        "succeeded": total_succeeded,
        "failed": total_failed,
        "errors": all_errors,
        "status": status,
        "ok": total_failed == 0,
        "message": (
            f"Cleared {cleared} extraction(s), deleted {deleted} upload folder(s), "
            f"rescanned {scan.status.total_files} PDF(s), extracted {total_succeeded}/{total_attempted}."
        ),
    }


def extract_pending_files(
    relative_paths: list[str] | None = None,
    *,
    limit: int = 100,
) -> TestDataExtractResponse:
    local_dir = get_local_dir()
    root = Path(local_dir)
    if not root.is_dir():
        status = build_status()
        return TestDataExtractResponse(
            ok=False,
            attempted=0,
            succeeded=0,
            failed=0,
            errors=[TestDataExtractItemError(relative_path="", message=f"Local folder not found: {local_dir}")],
            status=status,
            results=[],
        )

    manifest = _load_manifest()
    files: dict[str, dict] = manifest.get("files", {})
    if relative_paths:
        pending = [rel for rel in relative_paths if files.get(rel, {}).get("status") in (STATUS_DOWNLOADED, STATUS_ERROR)]
    else:
        pending = [rel for rel, entry in files.items() if entry.get("status") == STATUS_DOWNLOADED]
    pending = pending[: max(1, min(limit, 500))]

    succeeded = 0
    failed = 0
    errors: list[TestDataExtractItemError] = []
    results: list[RfiExtractionResponse] = []

    for rel in pending:
        path = root / Path(rel)
        if not path.is_file():
            entry = files.get(rel, {})
            entry["status"] = STATUS_ERROR
            entry["error"] = "File missing on disk."
            failed += 1
            errors.append(TestDataExtractItemError(relative_path=rel, message="File missing on disk."))
            continue

        try:
            raw = path.read_bytes()
            result = process_rfi_pdf_bytes(
                raw,
                filename=path.name,
                source_relative_path=rel,
                local_dir=local_dir,
            )
            entry = files[rel]
            entry["status"] = STATUS_EXTRACTED
            entry["upload_id"] = result.upload_id
            entry["extracted_at"] = _utc_now()
            entry["error"] = None
            succeeded += 1
            results.append(result)
        except Exception as exc:
            entry = files.get(rel, {"relative_path": rel, "filename": path.name})
            entry["status"] = STATUS_ERROR
            entry["error"] = str(exc)
            files[rel] = entry
            failed += 1
            errors.append(TestDataExtractItemError(relative_path=rel, message=str(exc)))

    manifest["files"] = files
    _save_manifest(manifest)
    _invalidate_dataset_cache()

    return TestDataExtractResponse(
        ok=failed == 0,
        attempted=len(pending),
        succeeded=succeeded,
        failed=failed,
        errors=errors,
        status=build_status(),
        results=results,
    )
