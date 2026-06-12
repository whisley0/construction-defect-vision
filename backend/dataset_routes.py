"""Dataset browser API for extracted images and metadata."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ingestion.dataset_query import build_summary, query_images, set_image_label
from ingestion.rfi_revision_chain import get_rfi_revision_timeline
from schemas.dataset import (
    DatasetImagesResponse,
    DatasetSummaryResponse,
    ImageLabelUpdate,
    ImageLabelUpdateResponse,
    RfiRevisionTimelineResponse,
)

router = APIRouter(tags=["dataset"])


@router.get("/api/dataset/summary", response_model=DatasetSummaryResponse)
def dataset_summary():
    return build_summary()


@router.get("/api/dataset/images", response_model=DatasetImagesResponse)
def dataset_images(
    search: str = Query(""),
    image_type: str | None = Query(None),
    inspection_outcome: str | None = Query(None),
    folder: str | None = Query(None),
    trainable_only: bool = Query(False),
    manual_only: bool = Query(False),
    multi_revision_only: bool = Query(False),
    min_revisions: int = Query(2, ge=2),
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
):
    return query_images(
        search=search,
        image_type=image_type,
        inspection_outcome=inspection_outcome,
        folder=folder,
        trainable_only=trainable_only,
        manual_only=manual_only,
        multi_revision_only=multi_revision_only,
        min_revisions=min_revisions,
        page=page,
        page_size=page_size,
    )


@router.get("/api/dataset/rfi-chain", response_model=RfiRevisionTimelineResponse)
def dataset_rfi_chain(upload_id: str):
    try:
        return get_rfi_revision_timeline(upload_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put(
    "/api/dataset/images/{upload_id}/{image_id}/label",
    response_model=ImageLabelUpdateResponse,
)
def dataset_update_image_label(upload_id: str, image_id: str, body: ImageLabelUpdate):
    try:
        image = set_image_label(upload_id, image_id, body.image_type)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ImageLabelUpdateResponse(image=image)
