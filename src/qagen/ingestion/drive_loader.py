"""Load the requirement specification from Google Drive, driven by drive_config.yaml.

Auth modes: service_account | oauth | public_link.  Google client libs are imported lazily
so the rest of the app works without them (e.g. when using local files).
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import ROOT

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
EXPORT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf", "txt": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}


class DriveError(RuntimeError):
    pass


@dataclass
class DriveFile:
    name: str
    data: bytes
    file_id: str


def extract_file_id(value: str) -> str:
    """Accept a raw ID or any drive.google.com / docs.google.com URL."""
    value = (value or "").strip()
    if not value:
        return ""
    for pat in (r"/d/([A-Za-z0-9_-]{10,})", r"[?&]id=([A-Za-z0-9_-]{10,})", r"/folders/([A-Za-z0-9_-]{10,})"):
        m = re.search(pat, value)
        if m:
            return m.group(1)
    return value if re.fullmatch(r"[A-Za-z0-9_-]{10,}", value) else ""


def load_from_drive(cfg: dict) -> DriveFile:
    gd = cfg.get("google_drive", {})
    if not gd.get("enabled", True):
        raise DriveError("Google Drive is disabled in drive_config.yaml (google_drive.enabled: false).")
    mode = gd.get("auth_mode", "service_account")
    file_id = extract_file_id(gd.get("file_id", "")) or extract_file_id(gd.get("file_url", ""))
    folder_id, file_name = extract_file_id(gd.get("folder_id", "")), (gd.get("file_name") or "").strip()
    if not file_id and not (folder_id and file_name):
        raise DriveError("Set google_drive.file_id, google_drive.file_url, or folder_id + file_name in drive_config.yaml.")
    log.info("Drive load: mode=%s file_id=%s folder=%s name=%s", mode, file_id or "-", folder_id or "-", file_name or "-")
    if mode == "public_link":
        if not file_id:
            raise DriveError("public_link mode needs file_id or file_url (folder lookup requires credentials).")
        return _load_public(file_id, gd)
    if mode in {"service_account", "oauth"}:
        return _load_api(gd, mode, file_id, folder_id, file_name)
    raise DriveError(f"Unknown auth_mode '{mode}'. Use service_account, oauth or public_link.")


# ---------------------------------------------------------------- public link
def _load_public(file_id: str, gd: dict) -> DriveFile:
    fmt_doc, fmt_sheet = gd.get("export_format_doc", "docx"), gd.get("export_format_sheet", "xlsx")
    candidates = [
        (f"https://docs.google.com/spreadsheets/d/{file_id}/export?format={fmt_sheet}", f"{file_id}.{fmt_sheet}"),
        (f"https://docs.google.com/document/d/{file_id}/export?format={fmt_doc}", f"{file_id}.{fmt_doc}"),
        (f"https://drive.google.com/uc?export=download&id={file_id}", f"{file_id}"),
    ]
    for url, name in candidates:
        try:
            r = requests.get(url, timeout=60, allow_redirects=True)
        except requests.RequestException as exc:
            raise DriveError(f"Network error reaching Google Drive: {exc}") from exc
        ctype = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "text/html" not in ctype:
            if "." not in name.split("/")[-1][-6:]:
                name = _name_from_headers(r, name)
            return DriveFile(name, r.content, file_id)
    raise DriveError("Could not download the file. Check that sharing is 'Anyone with the link' and the ID is correct.")


def _name_from_headers(r: requests.Response, fallback: str) -> str:
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', r.headers.get("Content-Disposition", ""))
    return m.group(1) if m else fallback


# ---------------------------------------------------------------- API modes
def _credentials(gd: dict, mode: str):
    try:
        if mode == "service_account":
            from google.oauth2 import service_account
            path = ROOT / gd.get("service_account_file", "credentials/service_account.json")
            if not path.exists():
                raise DriveError(f"Service-account key not found: {path}")
            return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        token_path = ROOT / gd.get("token_file", "credentials/token.json")
        client_path = ROOT / gd.get("oauth_client_file", "credentials/oauth_client.json")
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES) if token_path.exists() else None
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            if not client_path.exists():
                raise DriveError(f"OAuth client file not found: {client_path}")
            creds = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES).run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    except ImportError as exc:
        raise DriveError("Google client libraries missing. Run: pip install -r requirements.txt") from exc


def _load_api(gd: dict, mode: str, file_id: str, folder_id: str, file_name: str) -> DriveFile:
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise DriveError("Google client libraries missing. Run: pip install -r requirements.txt") from exc
    svc = build("drive", "v3", credentials=_credentials(gd, mode), cache_discovery=False)
    try:
        if not file_id:
            safe = file_name.replace("'", "\\'")
            q = f"'{folder_id}' in parents and name = '{safe}' and trashed = false"
            res = svc.files().list(q=q, fields="files(id,name)", pageSize=1,
                                   supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            if not res.get("files"):
                raise DriveError(f"'{file_name}' not found in folder {folder_id} (is the folder shared with the account?).")
            file_id = res["files"][0]["id"]
        meta = svc.files().get(fileId=file_id, fields="id,name,mimeType", supportsAllDrives=True).execute()
        name, mime = meta["name"], meta["mimeType"]
        if mime == GOOGLE_SHEET:
            fmt = gd.get("export_format_sheet", "xlsx")
            req, name = svc.files().export_media(fileId=file_id, mimeType=EXPORT_MIME[fmt]), _with_ext(name, fmt)
        elif mime == GOOGLE_DOC:
            fmt = gd.get("export_format_doc", "docx")
            req, name = svc.files().export_media(fileId=file_id, mimeType=EXPORT_MIME[fmt]), _with_ext(name, fmt)
        else:
            req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        log.info("Downloaded '%s' (%d bytes)", name, buf.tell())
        return DriveFile(name, buf.getvalue(), file_id)
    except HttpError as exc:
        status = getattr(exc.resp, "status", "?")
        hint = {404: "File not found, or not shared with this account.", 403: "Permission denied or API not enabled."}.get(status, "")
        raise DriveError(f"Google Drive API error {status}. {hint}") from exc


def _with_ext(name: str, ext: str) -> str:
    return name if name.lower().endswith(f".{ext}") else f"{name}.{ext}"


def load_local(path: str | Path) -> DriveFile:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise DriveError(f"Local file not found: {p}")
    return DriveFile(p.name, p.read_bytes(), "")
