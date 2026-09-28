"""Manifest builder: groups published videos by day, merges idempotently."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.ports import PublishedVideo


class Manifest:
    def __init__(self) -> None:
        # day -> video id -> video record
        self._days: dict[str, dict[str, dict]] = {}

    def add(self, day: str, source_zip: str, video: PublishedVideo) -> None:
        day_videos = self._days.setdefault(day, {})
        day_videos[video.id] = {
            "id": video.id,
            "name": video.name,
            "url": video.url,
            "poster": video.poster_url,
            "duration": video.duration_seconds,
            "source_zip": source_zip,
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
                day_videos[video["id"]] = {"duration": None, **video}
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
