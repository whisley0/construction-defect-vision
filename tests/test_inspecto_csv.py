"""Tests for Inspecto CSV metadata import."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from ingestion import inspecto_csv as ic
from ingestion import test_data as td


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "test-data"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(td, "TEST_DATA_DIR", data_dir)
    monkeypatch.setattr(ic, "TEST_DATA_DIR", data_dir)
    monkeypatch.setattr(ic, "INSPECTO_METADATA_PATH", data_dir / "inspecto_metadata.json")
    return TestClient(app)


SAMPLE_CSV = """pdf_url,has_internal_photo,Form No.,Status,Inspected Result,Location
"https://inspecto.example/api/risc/pdf/1/99,J3968-Inspection-ARC-000005A_completed.pdf",,J3968/Inspection/ARC/000005A,Completed,Accepted,Depot Roof
"https://inspecto.example/api/risc/pdf/1/100,J3968-Inspection-STR-000001A_completed.pdf",,J3968/Inspection/STR/000001A,Completed,Rejected,Column
"""


def test_parse_pdf_url_field():
    url, filename = ic.parse_pdf_url_field(
        "https://inspecto.example/api/risc/pdf/1/99,J3968-Inspection-ARC-000005A_completed.pdf"
    )
    assert filename == "J3968-Inspection-ARC-000005A_completed.pdf"
    assert url.endswith("/99")


def test_import_and_lookup(client):
    res = client.post(
        "/api/test-data/inspecto-metadata/upload",
        files={"file": ("result 1.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["record_count"] == 2
    assert body["status"]["imported"] is True

    meta = ic.lookup_inspecto_metadata(filename="J3968-Inspection-ARC-000005A_completed.pdf")
    assert meta is not None
    assert meta["Form No."] == "J3968/Inspection/ARC/000005A"
    assert meta["Location"] == "Depot Roof"


def test_compare_includes_inspecto(client, tmp_path, monkeypatch):
    monkeypatch.setattr(td, "MANIFEST_PATH", tmp_path / "data" / "test-data" / "manifest.json")
    monkeypatch.setattr(td, "CONFIG_PATH", tmp_path / "data" / "test-data" / "config.json")
    local = tmp_path / "downloads"
    local.mkdir(parents=True)
    (local / "J3968-Inspection-ARC-000005A_completed.pdf").write_bytes(b"pdf")

    client.post(
        "/api/test-data/inspecto-metadata/upload",
        files={"file": ("result 1.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
    )
    client.put("/api/test-data/config", json={"local_dir": str(local)})
    client.post("/api/test-data/scan")

    res = client.get("/api/test-data/compare", params={"has_local": True})
    row = next(f for f in res.json()["files"] if f["filename"].endswith("000005A_completed.pdf"))
    assert row["inspecto"]["Status"] == "Completed"
