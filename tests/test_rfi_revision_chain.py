"""Tests for RFI revision chain ordering from Inspecto metadata."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from ingestion import inspecto_csv as ic
from ingestion import test_data as td
from ingestion.rfi_revision_chain import get_revision_chain
from ingestion.storage import save_extraction_index


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "test-data"
    downloads = data_dir / "downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setattr(td, "TEST_DATA_DIR", data_dir)
    monkeypatch.setattr(ic, "TEST_DATA_DIR", data_dir)
    monkeypatch.setattr(ic, "INSPECTO_METADATA_PATH", data_dir / "inspecto_metadata.json")
    monkeypatch.setattr(td, "MANIFEST_PATH", data_dir / "manifest.json")
    monkeypatch.setattr(td, "CONFIG_PATH", data_dir / "config.json")

    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True)
    import ingestion.storage as storage

    monkeypatch.setattr(storage, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(storage, "DATA_ROOT", tmp_path / "data")
    return TestClient(app)


def _seed_revision_chain(tmp_path, monkeypatch):
    records = {
        "rev-a.pdf": {
            "pdf_filename": "rev-a.pdf",
            "Form No.": "J3968/Inspection/ARC/000100A",
            "Previous Risc No.": "J3968/Inspection/ARC/000100A",
            "Is Last Revision": "N",
            "Inspected Date": "2026-01-01",
            "Inspected Result": "Rejected",
        },
        "rev-b.pdf": {
            "pdf_filename": "rev-b.pdf",
            "Form No.": "J3968/Inspection/ARC/000100B",
            "Previous Risc No.": "J3968/Inspection/ARC/000100A",
            "Is Last Revision": "N",
            "Inspected Date": "2026-01-10",
            "Inspected Result": "Rejected",
        },
        "rev-c.pdf": {
            "pdf_filename": "rev-c.pdf",
            "Form No.": "J3968/Inspection/ARC/000100C",
            "Previous Risc No.": "J3968/Inspection/ARC/000100B",
            "Is Last Revision": "Y",
            "Inspected Date": "2026-01-20",
            "Inspected Result": "Accepted",
        },
    }
    ic.INSPECTO_METADATA_PATH.write_text(
        json.dumps({"records": records, "record_count": 3}),
        encoding="utf-8",
    )
    ic.invalidate_inspecto_cache()

    manifest = {"source_id": "test", "files": {}}
    for idx, (filename, form) in enumerate(
        [
            ("rev-a.pdf", "J3968/Inspection/ARC/000100A"),
            ("rev-b.pdf", "J3968/Inspection/ARC/000100B"),
            ("rev-c.pdf", "J3968/Inspection/ARC/000100C"),
        ],
        start=1,
    ):
        upload_id = f"upload-{idx}"
        rel = filename
        manifest["files"][rel] = {
            "relative_path": rel,
            "filename": filename,
            "size_bytes": 10,
            "modified_at": "2026-01-01T00:00:00+00:00",
            "status": "extracted",
            "upload_id": upload_id,
            "extracted_at": "2026-01-01T00:00:00+00:00",
        }
        save_extraction_index(
            upload_id,
            {
                "upload_id": upload_id,
                "filename": filename,
                "source_relative_path": rel,
                "inspection": {"inspection_outcome": "unknown"},
                "images": [
                    {
                        "image_id": f"img_{idx}",
                        "image_path": str(tmp_path / "data" / "uploads" / upload_id / "images" / f"img_{idx}.png"),
                        "image_type": "site_photo",
                        "page_number": idx,
                        "width": 100,
                        "height": 100,
                    }
                ],
            },
        )
        image_dir = tmp_path / "data" / "uploads" / upload_id / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / f"img_{idx}.png").write_bytes(b"png")

    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")


def test_get_revision_chain_orders_oldest_first(tmp_path, monkeypatch):
    _seed_revision_chain(tmp_path, monkeypatch)
    records = ic.get_inspecto_records()
    chain = get_revision_chain("J3968/Inspection/ARC/000100C", records)
    assert chain == [
        "J3968/Inspection/ARC/000100A",
        "J3968/Inspection/ARC/000100B",
        "J3968/Inspection/ARC/000100C",
    ]


def test_dataset_multi_revision_filter(client, tmp_path, monkeypatch):
    _seed_revision_chain(tmp_path, monkeypatch)
    from ingestion import dataset_query as dq

    dq.invalidate_dataset_cache()

    all_res = client.get("/api/dataset/images")
    assert all_res.status_code == 200
    assert all_res.json()["total_filtered"] >= 3

    filtered = client.get("/api/dataset/images", params={"multi_revision_only": True})
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total_filtered"] >= 3
    assert all(img["revision_count"] >= 2 for img in body["images"])

    single = client.get("/api/dataset/images", params={"multi_revision_only": False})
    assert single.json()["total_filtered"] >= body["total_filtered"]


def test_dataset_rfi_chain_api(client, tmp_path, monkeypatch):
    _seed_revision_chain(tmp_path, monkeypatch)

    res = client.get("/api/dataset/rfi-chain", params={"upload_id": "upload-2"})
    assert res.status_code == 200
    body = res.json()
    assert body["revision_count"] == 3
    assert [step["form_no"] for step in body["revisions"]] == [
        "J3968/Inspection/ARC/000100A",
        "J3968/Inspection/ARC/000100B",
        "J3968/Inspection/ARC/000100C",
    ]
    assert body["revisions"][1]["is_current"] is True
    assert body["revisions"][2]["is_last_revision"] is True
    assert len(body["revisions"][0]["images"]) == 1
