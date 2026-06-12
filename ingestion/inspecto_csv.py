"""Import Inspecto export CSV as supplemental metadata keyed by PDF filename."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
TEST_DATA_DIR = DATA_ROOT / "test-data"
INSPECTO_METADATA_PATH = TEST_DATA_DIR / "inspecto_metadata.json"
PDF_URL_COLUMN = "pdf_url"

_store_cache: dict | None = None
_store_cache_mtime: float | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def invalidate_inspecto_cache() -> None:
    global _store_cache, _store_cache_mtime
    _store_cache = None
    _store_cache_mtime = None


def parse_pdf_url_field(value: str) -> tuple[str, str]:
    """
    First CSV column: URL and filename joined by comma.
    Returns (pdf_url, filename).
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Empty pdf_url value.")
    if "," not in raw:
        raise ValueError(f"pdf_url must contain a comma-separated filename: {raw[:80]}")
    url, filename = raw.split(",", 1)
    filename = filename.strip()
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"Expected .pdf filename after comma, got: {filename[:80]}")
    return url.strip(), filename


def _norm_filename(name: str) -> str:
    return PurePosixPath(name.replace("\\", "/")).name.lower()


def _load_store() -> dict:
    if INSPECTO_METADATA_PATH.is_file():
        return json.loads(INSPECTO_METADATA_PATH.read_text(encoding="utf-8"))
    return {
        "source_file": None,
        "imported_at": None,
        "record_count": 0,
        "records": {},
    }


def _get_store() -> dict:
    global _store_cache, _store_cache_mtime
    if not INSPECTO_METADATA_PATH.is_file():
        return _load_store()
    mtime = INSPECTO_METADATA_PATH.stat().st_mtime
    if _store_cache is not None and _store_cache_mtime == mtime:
        return _store_cache
    _store_cache = _load_store()
    _store_cache_mtime = mtime
    return _store_cache


def get_inspecto_records() -> dict[str, dict]:
    return _get_store().get("records", {})


def _save_store(store: dict) -> None:
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    INSPECTO_METADATA_PATH.write_text(json.dumps(store, indent=2, default=str), encoding="utf-8")
    invalidate_inspecto_cache()


def import_inspecto_csv(raw: bytes, *, source_filename: str) -> dict:
    from ingestion.dataset_query import invalidate_dataset_cache

    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or PDF_URL_COLUMN not in reader.fieldnames:
        raise ValueError(f"CSV must include a '{PDF_URL_COLUMN}' column.")

    records: dict[str, dict] = {}
    duplicates = 0
    skipped = 0

    for row in reader:
        pdf_url_raw = row.get(PDF_URL_COLUMN, "")
        if not pdf_url_raw:
            skipped += 1
            continue
        try:
            pdf_url, filename = parse_pdf_url_field(pdf_url_raw)
        except ValueError:
            skipped += 1
            continue

        key = _norm_filename(filename)
        payload = {
            "pdf_filename": filename,
            "pdf_url": pdf_url,
            **{k: (v if v is not None else "") for k, v in row.items() if k != PDF_URL_COLUMN},
        }
        if key in records:
            duplicates += 1
        records[key] = payload

    if not records:
        raise ValueError("No valid rows found in CSV.")

    store = {
        "source_file": source_filename,
        "imported_at": _utc_now(),
        "record_count": len(records),
        "records": records,
    }
    _save_store(store)
    invalidate_dataset_cache()
    return {
        "ok": True,
        "message": f"Imported {len(records)} Inspecto record(s) from {source_filename}.",
        "record_count": len(records),
        "duplicate_keys": duplicates,
        "skipped_rows": skipped,
    }


def get_inspecto_status() -> dict:
    store = _get_store()
    return {
        "imported": bool(store.get("records")),
        "source_file": store.get("source_file"),
        "imported_at": store.get("imported_at"),
        "record_count": store.get("record_count", 0),
    }


def lookup_inspecto_metadata(
    *,
    filename: str | None = None,
    relative_path: str | None = None,
    records: dict[str, dict] | None = None,
) -> dict | None:
    table = records if records is not None else get_inspecto_records()
    if not table:
        return None

    candidates: list[str] = []
    if filename:
        candidates.append(_norm_filename(filename))
    if relative_path:
        candidates.append(_norm_filename(relative_path))
        candidates.append(_norm_filename(PurePosixPath(relative_path).name))

    for key in candidates:
        if key in table:
            return table[key]
    return None


def clear_inspecto_metadata() -> None:
    if INSPECTO_METADATA_PATH.is_file():
        INSPECTO_METADATA_PATH.unlink()
    invalidate_inspecto_cache()
