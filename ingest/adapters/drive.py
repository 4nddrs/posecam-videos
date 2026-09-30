"""Google Drive adapter implementing the ZipSource port.

The Drive v3 API resource is injected by the caller (duck-typed); this
module never constructs it directly except through the module-level
`build_drive_source` factory, which lazily imports the google client
libraries so tests never need them installed.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from ingest.ports import ZipEntry

_ZIP_MIMES = ("application/zip", "application/x-zip-compressed")
_FOLDER_MIME = "application/vnd.google-apps.folder"
_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

DownloaderFactory = Callable[[Any, Any], Any]


class DriveZipSource:
    """ZipSource adapter backed by a Google Drive v3 API resource."""

    def __init__(
        self,
        service: Any,
        folder_id: str,
        downloader_factory: Optional[DownloaderFactory] = None,
        category: Optional[str] = None,
    ) -> None:
        self._service = service
        self._folder_id = folder_id
        self._category = category
        self._downloader_factory = downloader_factory

    def list_zips(self) -> list[ZipEntry]:
        entries = self._list_zips_in(self._folder_id, day=None, category=self._category)
        for folder in self._list_subfolders():
            folder_day = _parse_day(folder["name"])
            # A dated folder names a day, never a category.
            category = self._category or (None if folder_day else folder["name"].strip())
            entries.extend(
                self._list_zips_in(folder["id"], day=folder_day, category=category)
            )
        return _dedupe_entries(entries)

    def _list_subfolders(self) -> list[dict]:
        query = (
            f"'{self._folder_id}' in parents and trashed = false and "
            f"mimeType = '{_FOLDER_MIME}'"
        )
        return list(self._paginate(query, "nextPageToken, files(id, name)"))

    def _list_zips_in(
        self, parent_id: str, day: Optional[str], category: Optional[str]
    ) -> list[ZipEntry]:
        query = (
            f"'{parent_id}' in parents and trashed = false and "
            "(mimeType = 'application/zip' or "
            "mimeType = 'application/x-zip-compressed' or name contains '.zip')"
        )
        entries: list[ZipEntry] = []
        for file_info in self._paginate(
            query, "nextPageToken, files(id, name, createdTime, mimeType, owners(displayName))"
        ):
            name = file_info["name"]
            # Some uploads lose the extension but keep the zip mime type.
            if not (
                name.lower().endswith(".zip")
                or file_info.get("mimeType") in _ZIP_MIMES
            ):
                continue
            entries.append(
                ZipEntry(
                    id=file_info["id"],
                    name=name,
                    uploaded_at=_parse_created_time(file_info["createdTime"]),
                    day=day_from_zip_name(name) or day,
                    category=category,
                    uploader=_owner_name(file_info),
                )
            )
        return entries

    def _paginate(self, query: str, fields: str):
        page_token = None
        while True:
            response = self._service.files().list(
                q=query, fields=fields, pageSize=100, pageToken=page_token
            ).execute()
            yield from response.get("files", [])
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def download(self, entry: ZipEntry, dest: Path) -> Path:
        request = self._service.files().get_media(fileId=entry.id)
        target_path = dest / entry.name if dest.is_dir() else dest

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


def _parse_day(folder_name: str) -> Optional[str]:
    """Parse a `DD-MM-YYYY` folder name into ISO `YYYY-MM-DD`, or None."""
    try:
        return datetime.strptime(folder_name.strip(), "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


_CAPTURE_RE = re.compile(r"capture-(\d{8})T\d{6}")
_COPY_SUFFIX_RE = re.compile(r" \(\d+\)(?=\.zip$|$)", re.IGNORECASE)


def day_from_zip_name(name: str) -> Optional[str]:
    """Parse `capture-YYYYMMDDTHHMMSS...` into ISO `YYYY-MM-DD`, or None."""
    match = _CAPTURE_RE.search(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def normalize_zip_name(name: str) -> str:
    """Strip a trailing ` (N)` copy counter (before `.zip`, or at the end)."""
    return _COPY_SUFFIX_RE.sub("", name)


def _owner_name(file_info: dict) -> Optional[str]:
    """Display name of the first owner. Emails are never read or stored."""
    for owner in file_info.get("owners") or []:
        name = (owner.get("displayName") or "").strip()
        if name:
            return name
    return None


def _dedupe_entries(entries: list[ZipEntry]) -> list[ZipEntry]:
    """Keep one entry per category and normalized name, preferring the
    un-numbered original."""
    chosen: dict[tuple[Optional[str], str], int] = {}
    result: list[ZipEntry] = []
    for entry in entries:
        normalized = normalize_zip_name(entry.name)
        key = (entry.category, normalized)
        if key not in chosen:
            chosen[key] = len(result)
            result.append(entry)
        elif entry.name == normalized and result[chosen[key]].name != normalized:
            result[chosen[key]] = entry
    return result


def _parse_created_time(created_time: str) -> datetime:
    return datetime.fromisoformat(created_time.replace("Z", "+00:00"))


def build_drive_source(
    folder_id: str, service_account_file: Path, category: Optional[str] = None
) -> DriveZipSource:
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
    return DriveZipSource(service, folder_id=folder_id, category=category)


def build_drive_source_with_api_key(
    folder_id: str, api_key: str, category: Optional[str] = None
) -> DriveZipSource:
    """Build a DriveZipSource using a Google API key (public folders only)."""
    from googleapiclient.discovery import build

    service = build("drive", "v3", developerKey=api_key, cache_discovery=False)
    return DriveZipSource(service, folder_id=folder_id, category=category)
