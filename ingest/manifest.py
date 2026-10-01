"""Manifest builder: groups published videos by day, merges idempotently."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ingest.ports import PublishedVideo

DEFAULT_CATEGORY = "Black/White pipes"

# Real month names only: "Deck 1" or "Mark 2" must not read as a date.
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DAY = r"(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
_TRAILING_DATE_RE = re.compile(
    rf"[\s\-_,(]+(?:{_DAY}\s+{_MONTH}|{_MONTH}\s+{_DAY})\b(?:,?\s+\d{{4}})?\)?\s*$",
    re.IGNORECASE,
)


def normalize_category(name: object) -> str | None:
    """Drop a trailing date from a category name, or None when it is empty.

    Uploaders create one Drive folder per batch ("Black pipes 1 Oct"); those
    videos belong to the base category ("Black pipes"), and the day comes from
    the recording itself.
    """
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    return _TRAILING_DATE_RE.sub("", cleaned).strip() or cleaned or None


class Manifest:
    def __init__(self) -> None:
        # day -> video id -> video record
        self._days: dict[str, dict[str, dict]] = {}

    def add(
        self,
        day: str,
        source_zip: str,
        video: PublishedVideo,
        category: str | None = None,
        uploader: str | None = None,
    ) -> None:
        day_videos = self._days.setdefault(day, {})
        day_videos[video.id] = {
            "id": video.id,
            "name": video.name,
            "url": video.url,
            "poster": video.poster_url,
            "duration": video.duration_seconds,
            "source_zip": source_zip,
            "category": normalize_category(category) or DEFAULT_CATEGORY,
            "uploader": uploader,
        }

    def to_dict(self) -> dict:
        days = []
        for day in sorted(self._days.keys(), reverse=True):
            videos = sorted(self._days[day].values(), key=lambda v: v["name"])
            days.append({"day": day, "videos": videos})
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": days,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        manifest = cls()
        for day_entry in data.get("days", []):
            day = day_entry["day"]
            for video in day_entry.get("videos", []):
                day_videos = manifest._days.setdefault(day, {})
                record = {"duration": None, **video}
                record["category"] = normalize_category(record.get("category")) or DEFAULT_CATEGORY
                day_videos[video["id"]] = record
        return manifest


def load(path: Path) -> Manifest:
    path = Path(path)
    if not path.exists():
        return Manifest()
    data = json.loads(path.read_text())
    return Manifest.from_dict(data)


def save(manifest: Manifest, path: Path) -> None:
    path = Path(path)
    existing = load(path)
    for day, videos in manifest._days.items():
        merged = existing._days.setdefault(day, {})
        merged.update(videos)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing.to_dict(), indent=2))
