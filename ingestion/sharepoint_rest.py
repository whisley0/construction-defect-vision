"""SharePoint Online access via browser session cookie (SharePoint REST API)."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_COOKIE_NAMES = ("FedAuth", "rtFa", "SIMI", "SPOIDCRL")
SHAREPOINT_HOST = "https://gammon-my.sharepoint.com"
_SEARCH_PAGE_SIZE = 500

LIST_SOURCES: list[dict[str, str]] = [
    {
        "label": "Jamie site folder",
        "site_url": f"{SHAREPOINT_HOST}/personal/jamiewan_gammonconstruction_com",
        "list_path": "/personal/jamiewan_gammonconstruction_com/Documents",
        "root_folder": "/personal/jamiewan_gammonconstruction_com/Documents/J3968_RISC_Export",
    },
    {
        "label": "Edward synced folder",
        "site_url": f"{SHAREPOINT_HOST}/personal/edwardlam_gammonconstruction_com",
        "list_path": "/personal/edwardlam_gammonconstruction_com/Documents",
        "root_folder": (
            "/personal/edwardlam_gammonconstruction_com/Documents/"
            "Jamie Yuk Chi Wan's files - J3968_RISC_Export"
        ),
    },
]


@dataclass
class RemoteFile:
    relative_path: str
    filename: str
    server_relative_url: str
    site_url: str
    size_bytes: int
    modified_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_browser_cookie(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    lower = text.lower()
    if "fedauth=" in lower and "domain=" not in lower and "set-cookie" not in lower:
        return text.splitlines()[0].strip()
    if "fedauth=" not in lower and "rtfa=" not in lower:
        return text.splitlines()[0].strip()

    pairs: list[str] = []
    for name in _COOKIE_NAMES:
        marker = f"{name}="
        idx = text.find(marker)
        if idx < 0:
            idx = text.lower().find(marker.lower())
            if idx < 0:
                continue
            marker = text[idx : idx + len(name) + 1]
        start = idx + len(marker)
        rest = text[start:]
        end = len(rest)
        for sep in ("; domain=", "; expires=", "; path=", "; SameSite=", "; secure", "; HttpOnly"):
            pos = rest.find(sep)
            if pos >= 0:
                end = min(end, pos)
        value = rest[:end].strip()
        if value:
            pairs.append(f"{name}={value}")

    if not pairs:
        raise ValueError("Could not find FedAuth or rtFa in pasted text.")
    if not any(p.startswith("FedAuth=") for p in pairs):
        raise ValueError("FedAuth cookie is required.")
    if not any(p.startswith("rtFa=") for p in pairs):
        raise ValueError("rtFa cookie is required.")
    return "; ".join(pairs)


def _parse_sp_date(raw: str | None) -> str:
    if not raw:
        return _utc_now()
    match = re.search(r"/Date\((-?\d+)\)/", str(raw))
    if match:
        ms = int(match.group(1))
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).isoformat()
    except ValueError:
        return _utc_now()


def _parse_size_display(raw: str | None) -> int:
    if not raw:
        return 0
    if str(raw).isdigit():
        return int(raw)
    raw = str(raw).strip().upper().replace(",", "")
    match = re.match(r"([\d.]+)\s*(B|KB|MB|GB)?", raw)
    if not match:
        return 0
    val = float(match.group(1))
    unit = match.group(2) or "B"
    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
    return int(val * mult)


def _escape_sp_path(path: str) -> str:
    return path.replace("'", "''")


def _headers(cookie: str, *, digest: str | None = None) -> dict[str, str]:
    hdrs = {
        "Accept": "application/json;odata=verbose",
        "Cookie": cookie.strip(),
        "User-Agent": BROWSER_UA,
    }
    if digest is not None:
        hdrs["X-RequestDigest"] = digest
        hdrs["Content-Type"] = "application/json;odata=verbose"
    return hdrs


def site_url_for_server_path(server_relative_url: str) -> str:
    parts = server_relative_url.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "personal":
        return f"{SHAREPOINT_HOST}/personal/{parts[1]}"
    return SHAREPOINT_HOST


def path_to_server_relative(path: str) -> str:
    if path.startswith("http"):
        return urlparse(unquote(path)).path
    return path if path.startswith("/") else f"/{path}"


def _relative_path(root_folder: str, server_relative_url: str, filename: str) -> str:
    root = root_folder.rstrip("/")
    url = server_relative_url
    if url.lower().startswith(root.lower() + "/"):
        return url[len(root) + 1 :]
    return filename


def _is_throttled(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "spquerythrottledexception" in msg or "list view threshold" in msg


def _is_pdf_name(name: str) -> bool:
    return name.lower().endswith(".pdf")


def _file_extension(name: str) -> str:
    if "." not in name:
        return "(no ext)"
    return name.rsplit(".", 1)[-1].lower()


def _get_json(client: httpx.Client, url: str, cookie: str) -> dict:
    resp = client.get(url, headers=_headers(cookie))
    if resp.status_code in (401, 403):
        raise ValueError("SharePoint session expired or invalid. Copy a fresh Cookie from your browser.")
    if resp.status_code >= 400:
        raise ValueError(f"SharePoint request failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def _post_json(client: httpx.Client, url: str, cookie: str, body: dict, *, digest: str) -> dict:
    resp = client.post(url, json=body, headers=_headers(cookie, digest=digest))
    if resp.status_code in (401, 403):
        raise ValueError("SharePoint session expired. Paste a fresh browser cookie.")
    if resp.status_code >= 400:
        raise ValueError(f"SharePoint request failed ({resp.status_code}): {resp.text[:300]}")
    if not resp.text.strip():
        return {}
    return resp.json()


def _get_request_digest(client: httpx.Client, site_url: str, cookie: str) -> str:
    url = f"{site_url.rstrip('/')}/_api/contextinfo"
    resp = client.post(url, headers=_headers(cookie))
    if resp.status_code >= 400:
        raise ValueError(f"Could not get SharePoint context ({resp.status_code}).")
    return resp.json()["d"]["GetContextWebInformation"]["FormDigestValue"]


def verify_session(site_url: str, cookie: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        data = _get_json(client, f"{site_url.rstrip('/')}/_api/web/currentuser", cookie)
    user = data.get("d") or {}
    return str(user.get("Title") or user.get("Email") or "SharePoint user")


def _normalize_row(row: dict | list) -> dict[str, str]:
    if isinstance(row, list):
        out: dict[str, str] = {}
        for item in row:
            if not isinstance(item, dict):
                continue
            k = str(item.get("FieldName") or item.get("Key") or "")
            v = item.get("FieldValue") if item.get("FieldValue") is not None else item.get("Value")
            if k:
                out[k] = "" if v is None else str(v)
        return out
    return {str(k): "" if v is None else str(v) for k, v in row.items()}


def _row_filename(row: dict[str, str]) -> str:
    for key, val in row.items():
        if not val:
            continue
        kl = key.lower()
        if kl in ("fileleafref", "linkfilename", "name", "title") or kl.endswith(".name"):
            name = val.split("/")[-1].strip()
            if name and name != ".":
                return name
    return ""


def _row_file_ref(row: dict[str, str]) -> str:
    for key, val in row.items():
        if not val:
            continue
        kl = key.lower()
        if kl in ("fileref", "serverurl") or ("fileref" in kl and "url" in kl):
            return path_to_server_relative(val)
    return ""


def _row_is_folder(row: dict[str, str]) -> bool:
    if str(row.get("FSObjType", "")).strip() == "1":
        return True
    for key in ("ContentType", "HTML_x0020_File_x0020_Type", "DocIcon"):
        val = row.get(key, "")
        if val and "folder" in val.lower():
            return True
    return False


def _rows_from_list_data(data: dict) -> list[dict[str, str]]:
    list_data = data.get("ListData") or data.get("d", {}).get("RenderListDataAsStream", {}).get("ListData") or {}
    rows = list_data.get("Row") or []
    if rows is None:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [_normalize_row(r) for r in rows]


def _next_url(site_url: str, data: dict) -> str | None:
    list_data = data.get("ListData") or {}
    nxt = list_data.get("NextHref")
    if not nxt:
        return None
    if nxt.startswith("http"):
        return nxt
    return urljoin(site_url.rstrip("/") + "/", nxt.lstrip("/"))


def _stream_list_url(site_url: str, list_path: str, root_folder: str) -> str:
    base = site_url.rstrip("/")
    list_q = quote(list_path, safe="")
    root_q = quote(root_folder, safe="")
    return (
        f"{base}/_api/web/GetListUsingPath(DecodedUrl=@a1)/RenderListDataAsStream"
        f"?@a1='{list_q}'&RootFolder={root_q}&TryNewExperienceSingle=TRUE"
    )


def _browser_stream_body(folder_path: str) -> dict[str, Any]:
    """Match the SharePoint web UI request body (no custom ViewXml)."""
    return {
        "parameters": {
            "AddRequiredFields": True,
            "AllowMultipleValueFilterForTaxonomyFields": True,
            "DatesInUtc": True,
            "ExpandGroups": True,
            "FolderServerRelativeUrl": folder_path,
            "RenderOptions": 4096,
        }
    }


def get_folder_item_count(site_url: str, folder_path: str, cookie: str) -> int | None:
    escaped = _escape_sp_path(folder_path)
    url = (
        f"{site_url.rstrip('/')}/_api/web/GetFolderByServerRelativeUrl('{escaped}')"
        "?$select=ItemCount,Name"
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            data = _get_json(client, url, cookie)
        return int((data.get("d") or {}).get("ItemCount") or 0)
    except Exception:
        return None


def _fetch_stream_page(
    client: httpx.Client,
    *,
    site_url: str,
    list_path: str,
    folder_path: str,
    cookie: str,
    digest: str,
    url: str | None = None,
) -> tuple[list[dict[str, str]], dict, str | None]:
    body = _browser_stream_body(folder_path)
    post_url = url or _stream_list_url(site_url, list_path, folder_path)
    data = _post_json(client, post_url, cookie, body, digest=digest)
    rows = _rows_from_list_data(data)
    return rows, data, _next_url(site_url, data)


def _search_rows(data: dict) -> tuple[list[dict], int]:
    if "d" in data and isinstance(data["d"], dict):
        inner = data["d"]
        if "postquery" in inner:
            data = inner["postquery"]
        elif "query" in inner:
            data = inner["query"]
        else:
            data = inner
    relevant = data.get("PrimaryQueryResult", {}).get("RelevantResults", {})
    table = relevant.get("Table", {})
    rows = table.get("Rows") or []
    if isinstance(rows, dict):
        rows = [rows]
    total = int(relevant.get("TotalRows") or relevant.get("RowCount") or 0)
    return rows, total


def _cells_to_dict(row: dict) -> dict[str, str]:
    cells = row.get("Cells") or []
    if isinstance(cells, dict):
        cells = [cells]
    return {str(c.get("Key", "")): str(c.get("Value", "")) for c in cells}


def _search_queries(folder_url: str) -> list[str]:
    return [
        f'Path:"{folder_url}*" AND FileExtension:pdf',
        f'Path:"{folder_url}*" AND (FileExtension:pdf OR FileExtension:PDF)',
        f'path:"{folder_url}*" AND IsDocument:1',
        f'"{folder_url}"',
    ]


def list_pdfs_via_list_items(
    *,
    site_url: str,
    list_path: str,
    root_folder: str,
    cookie: str,
    progress_cb: Callable[[str, int], None] | None = None,
) -> list[RemoteFile]:
    """
    Page through library list items by ID — bypasses the 5000-item list view threshold.
    Works when a folder contains thousands of files in flat or nested layout.
    """
    root_folder = root_folder.rstrip("/")
    list_q = quote(list_path, safe="")
    files: list[RemoteFile] = []
    seen: set[str] = set()
    last_id = 0

    with httpx.Client(timeout=180.0) as client:
        while True:
            filt = quote(f"ID gt {last_id}", safe="")
            url = (
                f"{site_url.rstrip('/')}/_api/web/GetListUsingPath(DecodedUrl=@a1)/Items"
                f"?@a1='{list_q}'&$filter={filt}&$orderby=ID asc&$top=500"
                f"&$select=Id,FileLeafRef,FileDirRef,FSObjType,File_x0020_Type,Modified,FileRef"
            )
            if progress_cb:
                progress_cb(f"Listing items after ID {last_id}…", len(files))
            data = _get_json(client, url, cookie)
            results = data.get("d", {}).get("results", [])
            if not results:
                break

            for item in results:
                dir_ref = item.get("FileDirRef") or ""
                if not dir_ref.startswith(root_folder):
                    continue
                if str(item.get("FSObjType")) != "0":
                    continue
                name = item.get("FileLeafRef") or ""
                if not _is_pdf_name(name):
                    continue
                file_ref = item.get("FileRef") or f"{dir_ref}/{name}"
                server_url = path_to_server_relative(str(file_ref))
                if server_url in seen:
                    continue
                seen.add(server_url)
                files.append(
                    RemoteFile(
                        relative_path=_relative_path(root_folder, server_url, name),
                        filename=name,
                        server_relative_url=server_url,
                        site_url=site_url_for_server_path(server_url),
                        size_bytes=0,
                        modified_at=_parse_sp_date(item.get("Modified")),
                    )
                )

            last_id = int(results[-1]["Id"])
            if progress_cb and len(files) % 500 == 0 and files:
                progress_cb(f"Found {len(files)} PDFs…", len(files))
            if len(results) < 500:
                break

    return files


def list_pdfs_via_search(
    *,
    site_url: str,
    root_folder: str,
    cookie: str,
    progress_cb: Callable[[str, int], None] | None = None,
) -> list[RemoteFile]:
    root_folder = root_folder.rstrip("/")
    folder_url = site_url.rstrip("/") + root_folder
    files: list[RemoteFile] = []
    seen: set[str] = set()

    with httpx.Client(timeout=180.0) as client:
        digest = _get_request_digest(client, site_url, cookie)
        for query in _search_queries(folder_url):
            if files:
                break
            search_url = f"{site_url.rstrip('/')}/_api/search/postquery"
            startrow = 0
            while True:
                if progress_cb:
                    progress_cb(f"Search ({query[:40]}…) row {startrow}", len(files))
                body = {
                    "request": {
                        "Querytext": query,
                        "RowLimit": _SEARCH_PAGE_SIZE,
                        "StartRow": startrow,
                        "SelectProperties": {
                            "results": ["Path", "Filename", "LastModifiedTime", "Size", "OriginalPath", "FileExtension"],
                        },
                        "TrimDuplicates": False,
                    }
                }
                data = _post_json(client, search_url, cookie, body, digest=digest)
                rows, total = _search_rows(data)
                if not rows:
                    break
                for row in rows:
                    cells = _cells_to_dict(row)
                    raw_path = cells.get("OriginalPath") or cells.get("Path") or ""
                    if not raw_path:
                        continue
                    server_url = path_to_server_relative(raw_path)
                    if server_url in seen:
                        continue
                    name = cells.get("Filename") or Path(server_url).name
                    ext = (cells.get("FileExtension") or _file_extension(name)).lower()
                    if ext != "pdf" and not _is_pdf_name(name):
                        continue
                    seen.add(server_url)
                    files.append(
                        RemoteFile(
                            relative_path=_relative_path(root_folder, server_url, name),
                            filename=name,
                            server_relative_url=server_url,
                            site_url=site_url_for_server_path(server_url),
                            size_bytes=_parse_size_display(cells.get("Size")),
                            modified_at=_parse_sp_date(cells.get("LastModifiedTime")),
                        )
                    )
                startrow += len(rows)
                if len(rows) < _SEARCH_PAGE_SIZE or (total and startrow >= total):
                    break
    return files


def _rows_to_files(
    rows: list[dict[str, str]],
    *,
    root_folder: str,
    folder_path: str,
    rel_prefix: str,
    folders: list[str],
    pdf_only: bool,
) -> list[RemoteFile]:
    files: list[RemoteFile] = []
    for row in rows:
        if _row_is_folder(row):
            sub = _row_file_ref(row)
            if not sub:
                name = _row_filename(row)
                if name:
                    sub = f"{folder_path.rstrip('/')}/{name}"
            if sub:
                folders.append(sub)
            continue

        name = _row_filename(row)
        if not name:
            continue
        if pdf_only and not _is_pdf_name(name):
            continue
        server_url = _row_file_ref(row) or f"{folder_path.rstrip('/')}/{name}"
        server_url = path_to_server_relative(server_url)
        rel = f"{rel_prefix}{name}" if rel_prefix else name
        files.append(
            RemoteFile(
                relative_path=rel,
                filename=name,
                server_relative_url=server_url,
                site_url=site_url_for_server_path(server_url),
                size_bytes=_parse_size_display(row.get("FileSizeDisplay") or row.get("File_x0020_Size")),
                modified_at=_parse_sp_date(row.get("Modified")),
            )
        )
    return files


def list_pdfs_via_folder_stream_bfs(
    *,
    site_url: str,
    list_path: str,
    root_folder: str,
    cookie: str,
    progress_cb: Callable[[str, int], None] | None = None,
) -> list[RemoteFile]:
    root_folder = root_folder.rstrip("/")
    files: list[RemoteFile] = []
    folders = [root_folder]

    with httpx.Client(timeout=180.0) as client:
        digest = _get_request_digest(client, site_url, cookie)
        while folders:
            folder_path = folders.pop()
            rel_prefix = ""
            if folder_path != root_folder:
                rel_prefix = folder_path[len(root_folder) :].lstrip("/")
                if rel_prefix:
                    rel_prefix += "/"

            if progress_cb:
                progress_cb(f"Scanning {rel_prefix or 'root'}", len(files))

            try:
                url: str | None = None
                while True:
                    page_rows, _, url = _fetch_stream_page(
                        client,
                        site_url=site_url,
                        list_path=list_path,
                        folder_path=folder_path,
                        cookie=cookie,
                        digest=digest,
                        url=url,
                    )
                    files.extend(
                        _rows_to_files(
                            page_rows,
                            root_folder=root_folder,
                            folder_path=folder_path,
                            rel_prefix=rel_prefix,
                            folders=folders,
                            pdf_only=True,
                        )
                    )
                    if not url:
                        break
            except Exception as exc:
                if _is_throttled(exc):
                    if progress_cb:
                        progress_cb(f"Skipped throttled folder {rel_prefix or 'root'}", len(files))
                    continue
                raise
    return files


def _folder_api_url(site_url: str, folder_path: str, resource: str) -> str:
    escaped = _escape_sp_path(folder_path)
    base = site_url.rstrip("/")
    select = "$select=Name,Length,TimeLastModified,ServerRelativeUrl"
    return f"{base}/_api/web/GetFolderByServerRelativeUrl('{escaped}')/{resource}?{select}&$top=500"


def list_pdfs_via_folder_api(
    *,
    site_url: str,
    root_folder_path: str,
    cookie: str,
    progress_cb: Callable[[str, int], None] | None = None,
) -> list[RemoteFile]:
    root_folder_path = root_folder_path.rstrip("/")
    files: list[RemoteFile] = []
    folders = [root_folder_path]

    with httpx.Client(timeout=120.0) as client:
        while folders:
            folder_path = folders.pop()
            rel_prefix = ""
            if folder_path != root_folder_path:
                rel_prefix = folder_path[len(root_folder_path) :].lstrip("/")
                if rel_prefix:
                    rel_prefix += "/"

            if progress_cb:
                progress_cb(f"Scanning {rel_prefix or 'root'}", len(files))

            try:
                folder_data = _get_json(client, _folder_api_url(site_url, folder_path, "Folders"), cookie)
                for sub in folder_data.get("d", {}).get("results", []):
                    folders.append(sub["ServerRelativeUrl"])

                files_data = _get_json(client, _folder_api_url(site_url, folder_path, "Files"), cookie)
                for item in files_data.get("d", {}).get("results", []):
                    name = item.get("Name", "")
                    if not _is_pdf_name(name):
                        continue
                    server_url = item["ServerRelativeUrl"]
                    rel = f"{rel_prefix}{name}" if rel_prefix else name
                    files.append(
                        RemoteFile(
                            relative_path=rel,
                            filename=name,
                            server_relative_url=server_url,
                            site_url=site_url,
                            size_bytes=int(item.get("Length") or 0),
                            modified_at=_parse_sp_date(item.get("TimeLastModified")),
                        )
                    )
            except Exception as exc:
                if _is_throttled(exc):
                    continue
                raise
    return files


def probe_sharepoint_source(source: dict[str, str], cookie: str) -> dict[str, Any]:
    """Diagnose why listing might return empty."""
    site = source["site_url"]
    root = source["root_folder"]
    list_path = source["list_path"]
    result: dict[str, Any] = {"label": source["label"], "site_url": site, "root_folder": root}

    result["folder_item_count"] = get_folder_item_count(site, root, cookie)

    try:
        with httpx.Client(timeout=60.0) as client:
            list_q = quote(list_path, safe="")
            url = (
                f"{site.rstrip('/')}/_api/web/GetListUsingPath(DecodedUrl=@a1)/Items"
                f"?@a1='{list_q}'&$filter=ID%20gt%200&$orderby=ID%20asc&$top=20"
                f"&$select=Id,FileLeafRef,FileDirRef,FSObjType"
            )
            data = _get_json(client, url, cookie)
            sample_items = data.get("d", {}).get("results", [])
            pdf_names = [
                i.get("FileLeafRef")
                for i in sample_items
                if str(i.get("FSObjType")) == "0"
                and (i.get("FileDirRef") or "").startswith(root)
                and _is_pdf_name(i.get("FileLeafRef") or "")
            ]
            result["list_items_sample"] = pdf_names[:5]
            result["list_items_sample_count"] = len(pdf_names)
    except Exception as exc:
        result["list_items_error"] = str(exc)

    with httpx.Client(timeout=60.0) as client:
        digest = _get_request_digest(client, site, cookie)
        rows, raw, _ = _fetch_stream_page(
            client, site_url=site, list_path=list_path, folder_path=root, cookie=cookie, digest=digest
        )
        result["stream_row_count"] = len(rows)
        result["stream_sample_keys"] = sorted(rows[0].keys())[:20] if rows else []
        result["stream_sample_row"] = {k: rows[0][k] for k in list(rows[0].keys())[:8]} if rows else {}

        ext_counts: Counter[str] = Counter()
        folder_count = 0
        file_count = 0
        for row in rows:
            if _row_is_folder(row):
                folder_count += 1
                continue
            name = _row_filename(row)
            if name:
                file_count += 1
                ext_counts[_file_extension(name)] += 1
        result["stream_folder_rows"] = folder_count
        result["stream_file_rows"] = file_count
        result["stream_extensions"] = dict(ext_counts.most_common(10))

        list_data = raw.get("ListData") or {}
        result["stream_last_row"] = list_data.get("LastRow")
        result["stream_next_href"] = bool(list_data.get("NextHref"))

        search_url = f"{site.rstrip('/')}/_api/search/postquery"
        folder_url = site.rstrip("/") + root
        body = {
            "request": {
                "Querytext": f'path:"{folder_url}*"',
                "RowLimit": 5,
                "StartRow": 0,
                "SelectProperties": {"results": ["Path", "Filename", "FileExtension"]},
            }
        }
        try:
            sdata = _post_json(client, search_url, cookie, body, digest=digest)
            srows, stotal = _search_rows(sdata)
            result["search_total_rows"] = stotal
            result["search_sample"] = [_cells_to_dict(r) for r in srows[:3]]
        except Exception as exc:
            result["search_error"] = str(exc)

    return result


def probe_all_sources(cookie: str) -> list[dict[str, Any]]:
    return [probe_sharepoint_source(src, cookie) for src in LIST_SOURCES]


def discover_remote_pdfs(
    cookie: str,
    *,
    progress_cb: Callable[[str, int], None] | None = None,
) -> tuple[list[RemoteFile], str]:
    errors: list[str] = []
    probes: list[dict[str, Any]] = []

    for source in LIST_SOURCES:
        label = source["label"]
        site = source["site_url"]
        root = source["root_folder"]
        list_path = source["list_path"]

        try:
            probes.append(probe_sharepoint_source(source, cookie))
        except Exception as exc:
            probes.append({"label": label, "probe_error": str(exc)})

        for method_name, fn, kwargs in (
            (
                "list items",
                list_pdfs_via_list_items,
                {"site_url": site, "list_path": list_path, "root_folder": root},
            ),
            ("search", list_pdfs_via_search, {"site_url": site, "root_folder": root}),
            (
                "folder stream",
                list_pdfs_via_folder_stream_bfs,
                {"site_url": site, "list_path": list_path, "root_folder": root},
            ),
            ("folder API", list_pdfs_via_folder_api, {"site_url": site, "root_folder_path": root}),
        ):
            try:
                if progress_cb:
                    progress_cb(f"Trying {label} ({method_name})…", 0)
                files = fn(cookie=cookie, progress_cb=progress_cb, **kwargs)
                if files:
                    return files, f"{label} ({method_name})"
                errors.append(f"{label} {method_name}: 0 PDFs")
            except Exception as exc:
                errors.append(f"{label} {method_name}: {exc}")

    hint = _format_probe_hint(probes)
    detail = "; ".join(errors) if errors else "no sources tried"
    raise ValueError(f"No PDFs found on SharePoint. {detail}.{hint}")


def _format_probe_hint(probes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for p in probes:
        label = p.get("label", "?")
        if p.get("probe_error"):
            parts.append(f" {label}: probe failed ({p['probe_error']}).")
            continue
        count = p.get("folder_item_count")
        stream_files = p.get("stream_file_rows", 0)
        list_pdfs = p.get("list_items_pdf_count")
        exts = p.get("stream_extensions") or {}
        if count is not None:
            parts.append(f" {label}: folder reports {count} item(s).")
        if list_pdfs is not None:
            parts.append(f" List-item scan found {list_pdfs} PDF(s).")
        if list_pdfs == 0 and count and int(count) > 5000:
            parts.append(" Folder exceeds SharePoint 5000-item view limit — list-item paging is required.")
    if not parts:
        return " Try POST /api/test-data/remote/probe for details."
    return "".join(parts)


def list_remote_pdfs(
    *,
    site_url: str,
    root_folder_path: str,
    cookie: str,
    progress_cb: Callable[[str, int], None] | None = None,
) -> list[RemoteFile]:
    del site_url, root_folder_path
    files, _ = discover_remote_pdfs(cookie, progress_cb=progress_cb)
    return files


def _file_download_url(site_url: str, server_relative_url: str) -> str:
    escaped = _escape_sp_path(server_relative_url)
    return f"{site_url.rstrip('/')}/_api/web/GetFileByServerRelativeUrl('{escaped}')/$value"


def download_file(*, site_url: str, server_relative_url: str, dest: Path, cookie: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    site = site_url or site_url_for_server_path(server_relative_url)
    url = _file_download_url(site, server_relative_url)
    with httpx.Client(timeout=300.0, follow_redirects=True) as client:
        with client.stream("GET", url, headers=_headers(cookie)) as resp:
            if resp.status_code in (401, 403):
                raise ValueError("SharePoint session expired. Paste a fresh browser cookie.")
            if resp.status_code >= 400:
                raise ValueError(f"Download failed ({resp.status_code})")
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    fh.write(chunk)
