"""API models for querying extracted images and metadata."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.image import ImageType
from schemas.inspection import InspectionOutcome


class DatasetImageItem(BaseModel):
    upload_id: str
    image_id: str
    image_filename: str
    image_url: str
    image_type: ImageType
    auto_image_type: ImageType
    label_source: Literal["auto", "manual"] = "auto"
    width: int = 0
    height: int = 0
    page_number: int = 0
    filter_reason: str | None = None
    routing_confidence: float | None = None
    hash: str | None = None
    trainable: bool = False
    pdf_filename: str
    source_relative_path: str | None = None
    source_folder: str | None = None
    local_dir: str | None = None
    extracted_at: str | None = None
    inspection_id: str | None = None
    location: str | None = None
    description_of_works: str | None = None
    subsequent_work: str | None = None
    inspection_outcome: InspectionOutcome = "unknown"
    inspector_comments: str | None = None
    inspected_by: str | None = None
    inspection_date: str | None = None
    reference_drawing_nos: str | None = None
    crosscheck_url: str
    inspecto: dict | None = None
    inspecto_form_no: str | None = None
    revision_count: int = 1


class ImageLabelUpdate(BaseModel):
    image_type: ImageType | None = None


class ImageLabelUpdateResponse(BaseModel):
    ok: bool = True
    image: DatasetImageItem


class DistributionSegment(BaseModel):
    key: str
    label: str
    count: int = 0
    percent: float = 0.0


class DatasetDistributions(BaseModel):
    total: int = 0
    outcomes: list[DistributionSegment] = Field(default_factory=list)
    image_types: list[DistributionSegment] = Field(default_factory=list)


class DatasetSummaryResponse(BaseModel):
    local_dir: str | None = None
    extracted_pdfs: int = 0
    total_images: int = 0
    site_photos: int = 0
    trainable_images: int = 0
    manually_labeled: int = 0
    folders: list[str] = Field(default_factory=list)


class DatasetImagesResponse(BaseModel):
    local_dir: str | None = None
    page: int = 1
    page_size: int = 48
    total_pages: int = 1
    total_filtered: int = 0
    total_images: int = 0
    distributions: DatasetDistributions = Field(default_factory=DatasetDistributions)
    images: list[DatasetImageItem] = Field(default_factory=list)


class RfiRevisionImage(BaseModel):
    upload_id: str
    image_id: str
    image_filename: str
    image_url: str
    image_type: str
    page_number: int = 0
    width: int = 0
    height: int = 0


class RfiRevisionStep(BaseModel):
    position: int
    form_no: str
    upload_id: str | None = None
    pdf_filename: str | None = None
    is_last_revision: bool = False
    is_current: bool = False
    previous_risc_no: str | None = None
    inspected_date: str | None = None
    inspected_result: str | None = None
    images: list[RfiRevisionImage] = Field(default_factory=list)


class RfiRevisionTimelineResponse(BaseModel):
    current_upload_id: str
    current_form_no: str
    revision_count: int = 0
    revisions: list[RfiRevisionStep] = Field(default_factory=list)
