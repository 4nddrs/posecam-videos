"""Hexagonal ports for the ingest use case.

These protocols and value objects define the boundary between the
ingest use case and its adapters (zip source, video publisher, state
store). No adapter implementation lives in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ZipEntry:
    id: str
    name: str
    uploaded_at: datetime
    day: str | None = None


@dataclass(frozen=True)
class PublishedVideo:
    id: str
    name: str
    url: str
    poster_url: str | None = None


@dataclass(frozen=True)
class ProcessedVideo:
    video_path: Path
    poster_path: Path | None


class VideoProcessor(Protocol):
    def process(self, video_path: Path, workdir: Path) -> ProcessedVideo:
        ...


class ZipSource(Protocol):
    def list_zips(self) -> list[ZipEntry]:
        ...

    def download(self, entry: ZipEntry, dest: Path) -> Path:
        ...


class VideoPublisher(Protocol):
    def publish(
        self, video_path: Path, day: str, poster_path: Path | None = None
    ) -> PublishedVideo:
        ...


class StateStore(Protocol):
    def processed_ids(self) -> set[str]:
        ...

    def mark_processed(self, zip_id: str) -> None:
        ...
