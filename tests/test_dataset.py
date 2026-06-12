"""Tests for extracted image dataset query API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from ingestion import test_data as td
from ingestion.storage import save_extraction_index


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "test-data"
    downloads = data_dir / "downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setattr(td, "TEST_DATA_DIR", data_dir)
    monkeypatch.setattr(td, "DEFAULT_LOCAL_DIR", downloads)
    monkeypatch.setattr(td, "MANIFEST_PATH", data_dir / "manifest.json")
    monkeypatch.setattr(td, "CONFIG_PATH", data_dir / "config.json")

    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True)
    import ingestion.storage as storage

    monkeypatch.setattr(storage, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(storage, "DATA_ROOT", tmp_path / "data")
    return TestClient(app)


def _seed_extracted(client, tmp_path, *, relative_path: str, upload_id: str) -> None:
    local = tmp_path / "downloads"
    local.mkdir(parents=True, exist_ok=True)
    client.put("/api/test-data/config", json={"local_dir": str(local)})

    manifest = {
        "source_id": "j3968-risc-export",
        "files": {
            relative_path: {
                "relative_path": relative_path,
                "filename": Path(relative_path).name,
                "size_bytes": 10,
                "modified_at": "2026-01-01T00:00:00+00:00",
                "status": "extracted",
                "upload_id": upload_id,
                "extracted_at": "2026-01-01T00:00:00+00:00",
                "error": None,
            }
        },
    }
    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")

    save_extraction_index(
        upload_id,
        {
            "upload_id": upload_id,
            "filename": Path(relative_path).name,
            "source_relative_path": relative_path,
            "local_dir": str(local),
            "inspection": {
                "inspection_id": "J3968-001",
                "location": "Level 3 plant room",
                "description_of_works": "Waterproofing membrane",
                "subsequent_work": "Backfill",
                "inspection_outcome": "accepted",
                "inspector_comments": "OK",
                "inspected_by": "Inspector A",
                "inspection_date": "2026-01-15",
                "reference_drawing_nos": "DWG-01",
                "document_type": "rfi",
                "project_name": None,
                "source_document_refs": [],
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            "images": [
                {
                    "image_id": "att_p1_1",
                    "inspection_id": "J3968-001",
                    "page_number": 1,
                    "source_ref": "page:1/xref:10",
                    "image_path": str(tmp_path / "data" / "uploads" / upload_id / "images" / "att_p1_1.png"),
                    "image_type": "site_photo",
                    "width": 800,
                    "height": 600,
                    "routing_confidence": 0.8,
                    "hash": "abc",
                    "filter_reason": None,
                },
                {
                    "image_id": "att_p2_1",
                    "inspection_id": "J3968-001",
                    "page_number": 2,
                    "source_ref": "page:2/xref:11",
                    "image_path": str(tmp_path / "data" / "uploads" / upload_id / "images" / "att_p2_1.png"),
                    "image_type": "logo",
                    "width": 80,
                    "height": 40,
                    "routing_confidence": 0.9,
                    "hash": "def",
                    "filter_reason": "logo",
                },
            ],
        },
    )

    image_dir = tmp_path / "data" / "uploads" / upload_id / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "att_p1_1.png").write_bytes(b"png")
    (image_dir / "att_p2_1.png").write_bytes(b"png")


def test_update_image_label(client, tmp_path):
    _seed_extracted(client, tmp_path, relative_path="batch/a.pdf", upload_id="upload-1")

    res = client.put(
        "/api/dataset/images/upload-1/att_p1_1/label",
        json={"image_type": "drawing"},
    )
    assert res.status_code == 200
    image = res.json()["image"]
    assert image["image_type"] == "drawing"
    assert image["auto_image_type"] == "site_photo"
    assert image["label_source"] == "manual"
    assert image["trainable"] is False

    res = client.get("/api/dataset/images", params={"manual_only": True})
    assert len(res.json()["images"]) == 1

    res = client.put(
        "/api/dataset/images/upload-1/att_p1_1/label",
        json={"image_type": None},
    )
    assert res.status_code == 200
    image = res.json()["image"]
    assert image["image_type"] == "site_photo"
    assert image["label_source"] == "auto"
    assert image["trainable"] is True


def test_dataset_summary_and_query(client, tmp_path):
    _seed_extracted(client, tmp_path, relative_path="batch/a.pdf", upload_id="upload-1")

    res = client.get("/api/dataset/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["extracted_pdfs"] == 1
    assert body["total_images"] == 2
    assert body["site_photos"] == 1
    assert body["trainable_images"] == 1
    assert body["folders"] == ["batch"]

    res = client.get("/api/dataset/images", params={"image_type": "site_photo"})
    assert res.status_code == 200
    images = res.json()["images"]
    assert len(images) == 1
    assert images[0]["inspection_id"] == "J3968-001"
    assert images[0]["source_relative_path"] == "batch/a.pdf"
    assert images[0]["source_folder"] == "batch"
    assert images[0]["trainable"] is True

    res = client.get("/api/dataset/images", params={"search": "att_p1_1"})
    assert len(res.json()["images"]) == 1

    res = client.get("/api/dataset/images", params={"folder": "batch"})
    assert len(res.json()["images"]) == 2

    res = client.get("/api/dataset/images", params={"trainable_only": True})
    assert len(res.json()["images"]) == 1

    res = client.get("/api/dataset/images")
    dist = res.json()["distributions"]
    assert dist["total"] == 2
    outcomes = {seg["key"]: seg for seg in dist["outcomes"]}
    assert outcomes["accepted"]["count"] == 2
    assert outcomes["accepted"]["percent"] == 100.0
    types = {seg["key"]: seg for seg in dist["image_types"]}
    assert types["site_photo"]["count"] == 1
    assert types["logo"]["count"] == 1
