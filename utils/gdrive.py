"""Upload files to Google Drive using OAuth2 user credentials.

Required env vars:
  GDRIVE_FOLDER_ID  — ID of the Drive folder to upload into
                      (last part of https://drive.google.com/drive/folders/<ID>)
  GDRIVE_TOKEN      — path to token.json (default: /home/ritual_parser/token.json)
                      Generated once by setup_gdrive_auth.py

Setup (one-time):
  1. In Google Cloud Console, enable Drive API.
  2. Create OAuth2 Client ID (Desktop app), download client_secrets.json.
  3. Run: python setup_gdrive_auth.py client_secrets.json
  4. Upload the generated token.json to server at GDRIVE_TOKEN path.
  5. Set GDRIVE_FOLDER_ID in .env.
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_TOKEN = "/home/ritual_parser/token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_service():
    """Build authenticated Drive service using OAuth2 refresh token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = os.getenv("GDRIVE_TOKEN", _DEFAULT_TOKEN)
    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"[gdrive] token.json not found: {token_path}. "
            "Run setup_gdrive_auth.py first."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                f"[gdrive] token expired or missing refresh_token. "
                "Re-run setup_gdrive_auth.py to reauthorize."
            )

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_file(local_path: str, folder_id: str | None = None) -> str | None:
    """Upload a local file to Google Drive.

    Returns the web view URL on success, None on failure.
    Updates existing file with same name in folder, or creates new.
    """
    folder_id = folder_id or os.getenv("GDRIVE_FOLDER_ID", "")
    if not folder_id:
        print("[gdrive] GDRIVE_FOLDER_ID not set — skipping upload")
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        service = _get_service()
        file_name = Path(local_path).name

        if local_path.endswith(".xlsx"):
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            mime = "text/csv"

        existing = (
            service.files()
            .list(
                q=f"name='{file_name}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
            .get("files", [])
        )

        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        if existing:
            file_id = existing[0]["id"]
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            meta = {"name": file_name, "parents": [folder_id]}
            result = service.files().create(
                body=meta, media_body=media, fields="id"
            ).execute()
            file_id = result["id"]

        link = f"https://drive.google.com/file/d/{file_id}/view"
        print(f"[gdrive] uploaded: {file_name} → {link}")
        return link

    except Exception as e:
        print(f"[gdrive] upload error for {local_path}: {e}")
        return None
