"""Google Drive adapter implementing the ZipSource port.

The Drive v3 API resource is injected by the caller (duck-typed); this
module never constructs it directly except through the module-level
`build_drive_source` factory, which lazily imports the google client
libraries so tests never need them installed.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from ingest.ports import ZipEntry

_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

DownloaderFactory = Callable[[Any, Any], Any]


class DriveZipSource:
    """ZipSource adapter backed by a Google Drive v3 API resource."""

    def __init__(
        self,
        service: Any,
        folder_id: str,
        downloader_factory: Optional[DownloaderFactory] = None,
    ) -> None:
        self._service = service
        self._folder_id = folder_id
        self._downloader_factory = downloader_factory

    def list_zips(self) -> list[ZipEntry]:
        query = (
            f"'{self._folder_id}' in parents and trashed = false and "
            "(mimeType = 'application/zip' or name contains '.zip')"
        )
        entries: list[ZipEntry] = []
        page_token = None
        while True:
            response = self._service.files().list(
                q=query,
                fields="nextPageToken, files(id, name, createdTime)",
                pageSize=100,
                pageToken=page_token,
            ).execute()

            for file_info in response.get("files", []):
                name = file_info["name"]
                if not name.lower().endswith(".zip"):
                    continue
                entries.append(
                    ZipEntry(
                        id=file_info["id"],
                        name=name,
                        uploaded_at=_parse_created_time(file_info["createdTime"]),
                    )
                )

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return entries

    def download(self, entry: ZipEntry, dest: Path) -> Path:
        request = self._service.files().get_media(fileId=entry.id)
        target_path = dest / entry.name

        downloader_factory = self._downloader_factory
        if downloader_factory is None:
            from googleapiclient.http import MediaIoBaseDownload

            downloader_factory = MediaIoBaseDownload

        with open(target_path, "wb") as fh:
            downloader = downloader_factory(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        return target_path


def _parse_created_time(created_time: str) -> datetime:
    return datetime.fromisoformat(created_time.replace("Z", "+00:00"))


def build_drive_source(folder_id: str, service_account_file: Path) -> DriveZipSource:
    """Build a DriveZipSource backed by a real Drive v3 service.

    Imports google client libraries lazily so callers that only need
    the protocol/tests do not require them installed.
    """
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_file(
        str(service_account_file), scopes=[_DRIVE_READONLY_SCOPE]
    )
    service = build("drive", "v3", credentials=credentials)
    return DriveZipSource(service, folder_id=folder_id)


def build_drive_source_with_api_key(folder_id: str, api_key: str) -> DriveZipSource:
    """Build a DriveZipSource using a Google API key (public folders only)."""
    from googleapiclient.discovery import build

    service = build("drive", "v3", developerKey=api_key, cache_discovery=False)
    return DriveZipSource(service, folder_id=folder_id)
