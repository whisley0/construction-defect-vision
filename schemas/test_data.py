"""API models for SharePoint / local test data download tracking."""
from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.api import RfiExtractionResponse


class SharePointSourceInfo(BaseModel):
    id: str
    name: str
    share_url: str
    owner_site: str
    folder_path: str
    synced_folder_name: str
    rest_site_url: str
    rest_folder_path: str


class TestDataFileRecord(BaseModel):
    relative_path: str
    filename: str
    size_bytes: int
    modified_at: str
    status: str
    upload_id: str | None = None
    extracted_at: str | None = None
    error: str | None = None


class TestDataStatusResponse(BaseModel):
    source: SharePointSourceInfo
    local_dir: str | None = None
    local_dir_exists: bool = False
    last_scan_at: str | None = None
    remote_inventory_at: str | None = None
    remote_total: int = 0
    total_files: int = 0
    downloaded_count: int = 0
    missing_count: int = 0
    local_only_count: int = 0
    extracted_count: int = 0
    pending_extract_count: int = 0
    error_count: int = 0
    files: list[TestDataFileRecord] = Field(default_factory=list)


class InspectoMetadataStatus(BaseModel):
    imported: bool = False
    source_file: str | None = None
    imported_at: str | None = None
    record_count: int = 0


class InspectoImportResponse(BaseModel):
    ok: bool
    message: str
    record_count: int = 0
    duplicate_keys: int = 0
    skipped_rows: int = 0
    status: InspectoMetadataStatus


class TestDataConfigUpdate(BaseModel):
    local_dir: str


class TestDataScanResponse(BaseModel):
    ok: bool
    message: str
    status: TestDataStatusResponse


class TestDataExtractItemError(BaseModel):
    relative_path: str
    message: str


class TestDataClearExtractionsResponse(BaseModel):
    ok: bool
    cleared_count: int
    deleted_uploads: int
    message: str
    status: TestDataStatusResponse


class TestDataReExtractRequest(BaseModel):
    limit: int = 500


class TestDataReExtractResponse(BaseModel):
    ok: bool
    cleared_count: int
    deleted_uploads: int
    scanned_files: int
    attempted: int
    succeeded: int
    failed: int
    message: str
    status: TestDataStatusResponse
    errors: list[TestDataExtractItemError] = Field(default_factory=list)


class TestDataExtractRequest(BaseModel):
    relative_paths: list[str] = Field(default_factory=list)
    limit: int = 100


class TestDataExtractResponse(BaseModel):
    ok: bool
    attempted: int
    succeeded: int
    failed: int
    errors: list[TestDataExtractItemError] = Field(default_factory=list)
    status: TestDataStatusResponse
    results: list[RfiExtractionResponse] = Field(default_factory=list)


class AuthStatusResponse(BaseModel):
    authenticated: bool
    account: str | None = None
    message: str
    cookie_saved: bool = False


class SessionUpdate(BaseModel):
    cookie: str


class JobStatusResponse(BaseModel):
    job_id: str
    kind: str
    status: str
    message: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    error: str | None = None


class CompareFileRecord(BaseModel):
    relative_path: str
    filename: str
    size_bytes: int | None = None
    modified_at: str | None = None
    sync_status: str
    local_status: str | None = None
    upload_id: str | None = None
    item_id: str | None = None
    inspecto: dict | None = None


class CompareResponse(BaseModel):
    remote_total: int
    local_total: int
    downloaded_count: int
    missing_count: int
    local_only_count: int
    page: int
    page_size: int
    total_pages: int
    total_filtered: int
    files: list[CompareFileRecord] = Field(default_factory=list)


class DownloadRequest(BaseModel):
    relative_paths: list[str] = Field(default_factory=list)
    download_all_missing: bool = False
    limit: int = 50


class DownloadResponse(BaseModel):
    ok: bool
    job_id: str
    message: str
