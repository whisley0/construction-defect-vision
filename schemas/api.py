"""API response models for RFI upload crosscheck."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from schemas.image import ImageRecord
from schemas.inspection import ExtractionCrosscheck, InspectionRecord, ParseStatus


class PageTextPreview(BaseModel):
    page_number: int
    text: str
    char_count: int


class RfiExtractionResponse(BaseModel):
    upload_id: str
    filename: str
    inspection: InspectionRecord
    crosscheck: ExtractionCrosscheck
    parse_status: ParseStatus
    images: list[ImageRecord] = Field(default_factory=list)
    page_previews: list[PageTextPreview] = Field(default_factory=list)
    pdf_url: str
    warnings: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    inspecto: dict | None = None


class RfiBatchItemError(BaseModel):
    filename: str
    message: str


class RfiBatchExtractionResponse(BaseModel):
    ok: bool
    count: int
    succeeded: int
    failed: int
    complete_count: int
    results: list[RfiExtractionResponse] = Field(default_factory=list)
    errors: list[RfiBatchItemError] = Field(default_factory=list)
    duration_ms: float | None = None
