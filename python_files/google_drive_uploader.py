"""
Google Drive uploader (server-side).

Supports:
1) Service Account upload (preferred): creates folders and uploads directly.
2) Apps Script upload (legacy): posts multipart to a script endpoint.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from pathlib import Path
from datetime import datetime
from http.client import HTTPSConnection, HTTPConnection, HTTPResponse
from urllib.parse import urlparse


def upload_file_to_drive(
    file_path: str,
    file_name: str,
    description: str,
    apps_script_url: str | None = None,
    *,
    parent_folder_id: str | None = None,
    service_account_file: str | None = None,
    username: str | None = None,
    asset_name: str | None = None,
) -> str:
    """
    Upload a local file to Google Drive.

    If service_account_file + parent_folder_id are provided, uses the Drive API
    and creates the path: parent/{username}/{asset_name}.
    Otherwise falls back to the legacy Apps Script endpoint.

    Args:
        file_path: Absolute path to the file on disk.
        file_name: The name to use in Google Drive.
        description: File description metadata.
        apps_script_url: Apps Script URL that accepts multipart form data.
        parent_folder_id: Drive folder ID to store uploads under.
        service_account_file: Service account JSON file path.
        username: Username folder name (optional, required for service account pathing).
        asset_name: Asset folder name (optional, required for service account pathing).

    Returns:
        A direct view URL (https://drive.google.com/uc?export=view&id=FILE_ID).

    Raises:
        RuntimeError: On upload failure or invalid response.
    """
    if parent_folder_id and service_account_file:
        return _upload_via_service_account(
            file_path=file_path,
            file_name=file_name,
            description=description,
            parent_folder_id=parent_folder_id,
            service_account_file=service_account_file,
            username=username,
            asset_name=asset_name,
        )
    if apps_script_url:
        return _upload_via_apps_script(
            file_path=file_path,
            file_name=file_name,
            description=description,
            apps_script_url=apps_script_url,
        )
    raise RuntimeError("No Google Drive upload method configured")


def _upload_via_service_account(
    file_path: str,
    file_name: str,
    description: str,
    parent_folder_id: str,
    service_account_file: str,
    username: str | None,
    asset_name: str | None,
) -> str:
    """Upload using a service account and create username/asset folders."""
    if not os.path.exists(file_path):
        raise RuntimeError(f"File not found: {file_path}")
    if not parent_folder_id:
        raise RuntimeError("Missing Google Drive parent folder id")

    service_account_file = _resolve_path(service_account_file)
    if not os.path.exists(service_account_file):
        raise RuntimeError(f"Service account file not found: {service_account_file}")

    detected_type = _detect_image_type(file_path)
    if detected_type not in ("png", "jpg"):
        raise RuntimeError("Invalid file signature: only PNG/JPG supported")

    if not file_name:
        file_name = os.path.basename(file_path)

    safe_username = _safe_drive_name(username or "uploads")
    safe_asset = _safe_drive_name(asset_name or Path(file_name).stem)

    # Lazy import so the server can boot without Drive deps when not used.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=scopes,
    )
    service = build("drive", "v3", credentials=creds)

    username_folder_id = _ensure_drive_folder(
        service,
        parent_folder_id,
        safe_username,
    )
    asset_folder_id = _ensure_drive_folder(
        service,
        username_folder_id,
        safe_asset,
    )

    mime_type = "image/png" if detected_type == "png" else "image/jpeg"
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    metadata = {
        "name": file_name,
        "parents": [asset_folder_id],
    }
    if description:
        metadata["description"] = description

    uploaded = service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
    ).execute()

    file_id = str(uploaded.get("id", "")).strip()
    if not file_id:
        raise RuntimeError("Drive upload failed: missing file id")

    return f"https://drive.google.com/uc?export=view&id={file_id}"


def _upload_via_apps_script(
    file_path: str,
    file_name: str,
    description: str,
    apps_script_url: str,
) -> str:
    """Upload using a legacy Apps Script endpoint."""
    if not os.path.exists(file_path):
        raise RuntimeError(f"File not found: {file_path}")

    parsed = urlparse(apps_script_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError("Invalid Apps Script URL")

    boundary = f"----AurexBoundary{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    file_size = os.path.getsize(file_path)

    fields = {
        "name": file_name,
        "description": description,
        "timestamp": datetime.now().isoformat(),
    }

    preamble = _encode_fields(fields, boundary)
    file_header = _encode_file_header("file", file_name, mime_type, boundary)
    closing = f"\r\n--{boundary}--\r\n".encode("utf-8")

    content_length = len(preamble) + len(file_header) + file_size + len(closing)
    response = _send_multipart(
        parsed,
        boundary,
        content_length,
        preamble,
        file_header,
        file_path,
        closing,
    )

    response_body = response.read().decode("utf-8", errors="replace")
    response.close()
    if response.status != 200:
        raise RuntimeError(f"Drive upload failed: {response.status} {response.reason}")

    file_id = _extract_file_id(response_body)
    if not file_id:
        raise RuntimeError("Drive upload failed: missing file id in response")

    return f"https://drive.google.com/uc?export=view&id={file_id}"


def _resolve_path(path: str) -> str:
    """Resolve relative paths to this module's directory."""
    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = (Path(__file__).parent / path_obj).resolve()
    return str(path_obj)


def _detect_image_type(file_path: str) -> str:
    """Return 'png' or 'jpg' based on file signature, or empty string."""
    try:
        with open(file_path, "rb") as handle:
            header = handle.read(8)
    except Exception:
        return ""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return ""


def _safe_drive_name(name: str) -> str:
    """Sanitize folder names for Drive."""
    cleaned = (name or "").strip()
    if not cleaned:
        return "unnamed"
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    return cleaned


def _escape_drive_query(value: str) -> str:
    """Escape single quotes in Drive query strings."""
    return value.replace("'", "\\'")


def _ensure_drive_folder(service, parent_id: str, folder_name: str) -> str:
    """Find or create a Drive folder under a parent folder."""
    escaped_name = _escape_drive_query(folder_name)
    query = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{escaped_name}' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=1,
    ).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(
        body=metadata,
        fields="id",
    ).execute()
    folder_id = str(created.get("id", "")).strip()
    if not folder_id:
        raise RuntimeError(f"Failed to create Drive folder: {folder_name}")
    return folder_id


def _send_multipart(
    parsed_url,
    boundary: str,
    content_length: int,
    preamble: bytes,
    file_header: bytes,
    file_path: str,
    closing: bytes,
) -> HTTPResponse:
    """Send a multipart/form-data POST request with streaming file body."""
    conn_cls = HTTPSConnection if parsed_url.scheme == "https" else HTTPConnection
    conn = conn_cls(parsed_url.netloc, timeout=60)

    path = parsed_url.path or "/"
    if parsed_url.query:
        path = f"{path}?{parsed_url.query}"

    conn.putrequest("POST", path)
    conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("Content-Length", str(content_length))
    conn.endheaders()

    conn.send(preamble)
    conn.send(file_header)

    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            conn.send(chunk)

    conn.send(closing)
    return conn.getresponse()


def _encode_fields(fields: dict[str, str], boundary: str) -> bytes:
    """Encode simple text fields for multipart/form-data."""
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    return "".join(parts).encode("utf-8")


def _encode_file_header(field_name: str, file_name: str, mime_type: str, boundary: str) -> bytes:
    """Build the header for a multipart file field."""
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{file_name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")


def _extract_file_id(response_body: str) -> str:
    """Extract a Google Drive file ID from Apps Script response."""
    try:
        payload = json.loads(response_body)
        if isinstance(payload, dict) and "id" in payload:
            return str(payload["id"]).strip()
    except Exception:
        pass

    text = response_body.strip().strip('"')
    if "drive.google.com" in text:
        return _extract_from_drive_url(text)
    if text and len(text) > 10 and " " not in text:
        return text
    return ""


def _extract_from_drive_url(url: str) -> str:
    """Pull a file ID from a Drive share URL if present."""
    marker = "/file/d/"
    if marker in url:
        tail = url.split(marker, 1)[1]
        return tail.split("/", 1)[0]
    return ""
