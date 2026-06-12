"""Tests for SharePoint REST helpers."""
from ingestion.sharepoint_rest import (
    _cells_to_dict,
    _normalize_row,
    _parse_sp_date,
    _relative_path,
    _row_filename,
    _row_is_folder,
    normalize_browser_cookie,
    path_to_server_relative,
)


def test_parse_sp_date():
    assert _parse_sp_date("/Date(1700000000000)/").startswith("2023-")


def test_normalize_stream_row_with_name_suffix():
    row = _normalize_row(
        {
            "FSObjType": "0",
            "FileLeafRef.name": "report.pdf",
            "FileLeafRef.url": "https://gammon-my.sharepoint.com/x/report.pdf",
            "FileRef": "/personal/x/report.pdf",
        }
    )
    assert _row_filename(row) == "report.pdf"
    assert not _row_is_folder(row)


def test_normalize_set_cookie_paste():
    raw = """
    rtFa=abc123; domain=sharepoint.com; expires=Tue, 16-Jun-2026 03:38:39 GMT; path=/; secure; HttpOnly
    set-cookie
    FedAuth=xyz789; expires=Tue, 16-Jun-2026 03:38:39 GMT; path=/; secure; HttpOnly
    """
    result = normalize_browser_cookie(raw)
    assert result == "FedAuth=xyz789; rtFa=abc123"


def test_normalize_request_cookie_header():
    raw = "Cookie: FedAuth=aaa; rtFa=bbb; SIMI=ccc"
    assert normalize_browser_cookie(raw) == "FedAuth=aaa; rtFa=bbb; SIMI=ccc"


def test_path_to_server_relative():
    url = "https://gammon-my.sharepoint.com/personal/jamiewan/Documents/J3968/file.pdf"
    assert path_to_server_relative(url) == "/personal/jamiewan/Documents/J3968/file.pdf"


def test_relative_path():
    root = "/personal/jamiewan/Documents/J3968_RISC_Export"
    server = "/personal/jamiewan/Documents/J3968_RISC_Export/sub/a.pdf"
    assert _relative_path(root, server, "a.pdf") == "sub/a.pdf"


def test_search_cells_to_dict():
    row = {"Cells": [{"Key": "Filename", "Value": "a.pdf"}, {"Key": "Size", "Value": "1234"}]}
    assert _cells_to_dict(row)["Filename"] == "a.pdf"
