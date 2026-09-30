"""Backfill `uploader` (and a missing `category`) for videos already in the manifest.

Usage: python -m ingest.uploaders

Lists the configured Drive sources (read-only), matches every manifest
video's `source_zip` to a Drive file (a trailing " (N)" copy counter is
ignored) and stores the Drive owner display name as `uploader`. Videos
without a category get "Black/White pipes". Only display names are stored; the
manifest is public. Nothing is uploaded and no video is downloaded.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ingest.adapters.drive import build_drive_source_with_api_key, normalize_zip_name
from ingest.main import (
    DriveSource,
    MultiZipSource,
    load_dotenv_file,
    parse_drive_sources,
)
from ingest.manifest import DEFAULT_CATEGORY
from ingest.ports import ZipSource


def backfill_uploaders(manifest_path: Path, source: ZipSource) -> dict:
    """Fill missing `uploader`/`category` in the manifest; returns counts."""
    manifest_path = Path(manifest_path)
    data = json.loads(manifest_path.read_text())

    owners: dict[str, str] = {}
    for entry in source.list_zips():
        if entry.uploader:
            owners.setdefault(normalize_zip_name(entry.name), entry.uploader)

    total = filled = unmatched = categorized = 0
    for day in data.get("days", []):
        for video in day.get("videos", []):
            total += 1
            if not video.get("category"):
                video["category"] = DEFAULT_CATEGORY
                categorized += 1
            if video.get("uploader"):
                continue
            owner = owners.get(normalize_zip_name(video.get("source_zip") or ""))
            video["uploader"] = owner
            if owner:
                filled += 1
            else:
                unmatched += 1

    manifest_path.write_text(json.dumps(data, indent=2))
    return {
        "videos": total,
        "uploader_filled": filled,
        "uploader_unmatched": unmatched,
        "category_set": categorized,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv_file(repo_root / ".env", os.environ)
    env = os.environ
    sources = parse_drive_sources(env.get("DRIVE_SOURCES"))
    if not sources and env.get("DRIVE_FOLDER_ID"):
        sources = (DriveSource(env["DRIVE_FOLDER_ID"], DEFAULT_CATEGORY),)
    api_key = env.get("GOOGLE_API_KEY")
    if not sources or not api_key:
        print("Missing DRIVE_SOURCES (or DRIVE_FOLDER_ID) and GOOGLE_API_KEY", file=sys.stderr)
        raise SystemExit(1)

    source = MultiZipSource(
        [build_drive_source_with_api_key(s.folder_id, api_key, category=s.category) for s in sources]
    )
    report = backfill_uploaders(Path(env.get("MANIFEST_PATH", "site/manifest.json")), source)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
