"""Tests for SharePoint test data download tracking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from ingestion import test_data as td


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
    monkeypatch.setattr(td, "UPLOADS_DIR", uploads)
    return TestClient(app)


def _write_pdf(path: Path, text: str = "sample") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def test_status_has_default_local_dir(client):
    res = client.get("/api/test-data/status")
    assert res.status_code == 200
    body = res.json()
    assert body["source"]["id"] == "j3968-risc-export"
    assert body["local_dir"]
    assert body["total_files"] == 0


def test_scan_and_track_pdfs(client, tmp_path):
    local = tmp_path / "sharepoint-sync"
    _write_pdf(local / "a.pdf")
    _write_pdf(local / "nested/b.pdf")

    res = client.put("/api/test-data/config", json={"local_dir": str(local)})
    assert res.status_code == 200

    res = client.post("/api/test-data/scan")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["status"]["total_files"] == 2
    assert body["status"]["pending_extract_count"] == 2

    res = client.get("/api/test-data/status")
    files = {f["relative_path"]: f for f in res.json()["files"]}
    assert set(files) == {"a.pdf", "nested/b.pdf"}
    assert all(f["status"] == "downloaded" for f in files.values())


def test_compare_missing_and_downloaded(client, tmp_path):
    local = tmp_path / "downloads"
    _write_pdf(local / "have.pdf")

    manifest = {
        "source_id": "j3968-risc-export",
        "remote_files": {
            "have.pdf": {
                "relative_path": "have.pdf",
                "filename": "have.pdf",
                "server_relative_url": "/personal/edwardlam/file/have.pdf",
                "size_bytes": 10,
                "modified_at": "2026-01-01T00:00:00+00:00",
            },
            "need.pdf": {
                "relative_path": "need.pdf",
                "filename": "need.pdf",
                "server_relative_url": "/personal/edwardlam/file/need.pdf",
                "size_bytes": 20,
                "modified_at": "2026-01-01T00:00:00+00:00",
            },
        },
        "files": {},
    }
    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")
    client.put("/api/test-data/config", json={"local_dir": str(local)})
    client.post("/api/test-data/scan")

    res = client.get("/api/test-data/compare")
    assert res.status_code == 200
    body = res.json()
    assert body["remote_total"] == 2
    assert body["downloaded_count"] == 1
    assert body["missing_count"] == 1

    res = client.get("/api/test-data/compare", params={"sync_status": "missing"})
    missing = {f["relative_path"] for f in res.json()["files"]}
    assert missing == {"need.pdf"}


def test_compare_has_local_excludes_missing(client, tmp_path):
    local = tmp_path / "downloads"
    _write_pdf(local / "have.pdf")

    manifest = {
        "source_id": "j3968-risc-export",
        "remote_files": {
            "have.pdf": {"relative_path": "have.pdf", "filename": "have.pdf"},
            "need.pdf": {"relative_path": "need.pdf", "filename": "need.pdf"},
        },
        "files": {},
    }
    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")
    client.put("/api/test-data/config", json={"local_dir": str(local)})
    client.post("/api/test-data/scan")

    res = client.get("/api/test-data/compare", params={"has_local": True})
    paths = {f["relative_path"] for f in res.json()["files"]}
    assert paths == {"have.pdf"}


def test_compare_extracted_first_sort(client, tmp_path):
    local = tmp_path / "downloads"
    _write_pdf(local / "a.pdf")
    _write_pdf(local / "b.pdf")
    _write_pdf(local / "c.pdf")

    client.put("/api/test-data/config", json={"local_dir": str(local)})
    client.post("/api/test-data/scan")
    manifest = json.loads(td.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["files"]["b.pdf"]["status"] = "extracted"
    manifest["files"]["b.pdf"]["upload_id"] = "u1"
    manifest["files"]["c.pdf"]["status"] = "error"
    manifest["files"]["c.pdf"]["upload_id"] = "u2"
    manifest["files"]["c.pdf"]["error"] = "parse failed"
    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")

    res = client.get("/api/test-data/compare", params={"has_local": True, "extracted_first": True})
    statuses = [f["local_status"] for f in res.json()["files"]]
    assert statuses[0] == "extracted"
    assert statuses[1] == "error"
    assert statuses[2] == "downloaded"


def test_clear_extractions_and_re_extract(client, tmp_path, monkeypatch):
    local = tmp_path / "sync"
    pdf = local / "doc.pdf"
    _write_pdf(pdf, "pdf-content")

    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    import ingestion.storage as storage

    monkeypatch.setattr(storage, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(td, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(storage, "DATA_ROOT", tmp_path / "data")

    client.put("/api/test-data/config", json={"local_dir": str(local)})
    client.post("/api/test-data/scan")

    manifest = json.loads(td.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["files"]["doc.pdf"]["status"] = "extracted"
    manifest["files"]["doc.pdf"]["upload_id"] = "old-upload"
    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")
    old_dir = uploads / "old-upload"
    old_dir.mkdir()
    (old_dir / "source.pdf").write_bytes(b"old")

    res = client.post("/api/test-data/clear-extractions")
    assert res.status_code == 200
    body = res.json()
    assert body["cleared_count"] == 1
    assert body["deleted_uploads"] == 1
    assert not old_dir.exists()
    entry = json.loads(td.MANIFEST_PATH.read_text(encoding="utf-8"))["files"]["doc.pdf"]
    assert entry["status"] == "downloaded"
    assert entry["upload_id"] is None


def test_rescan_preserves_extracted_upload_id(client, tmp_path):
    local = tmp_path / "sync"
    pdf = local / "done.pdf"
    _write_pdf(pdf)

    client.put("/api/test-data/config", json={"local_dir": str(local)})
    client.post("/api/test-data/scan")

    manifest = json.loads(td.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["files"]["done.pdf"]["status"] = "extracted"
    manifest["files"]["done.pdf"]["upload_id"] = "abc-123"
    manifest["files"]["done.pdf"]["extracted_at"] = "2026-01-01T00:00:00+00:00"
    td.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")

    client.post("/api/test-data/scan")
    entry = json.loads(td.MANIFEST_PATH.read_text(encoding="utf-8"))["files"]["done.pdf"]
    assert entry["status"] == "extracted"
    assert entry["upload_id"] == "abc-123"
