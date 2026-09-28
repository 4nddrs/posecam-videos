"""Ingest use case: download new zips, extract, publish, and record a manifest."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ingest.manifest import Manifest, save
from ingest.ports import StateStore, VideoPublisher, ZipSource
from ingest.unzip import extract_videos


@dataclass
class IngestReport:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def run_ingest(
    source: ZipSource,
    publisher: VideoPublisher,
    state: StateStore,
    manifest_path: Path,
    workdir: Path,
) -> IngestReport:
    manifest_path = Path(manifest_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    report = IngestReport()
    already_processed = state.processed_ids()

    for entry in source.list_zips():
        if entry.id in already_processed:
            report.skipped.append(entry.id)
            continue

        try:
            entry_workdir = workdir / entry.id
            entry_workdir.mkdir(parents=True, exist_ok=True)
            zip_path = entry_workdir / entry.name
            source.download(entry, zip_path)

            extract_dir = entry_workdir / "videos"
            video_paths = extract_videos(zip_path, extract_dir)

            day = entry.uploaded_at.date().isoformat()
            manifest = Manifest()
            for video_path in video_paths:
                published = publisher.publish(video_path, day)
                manifest.add(day, entry.name, published)

            save(manifest, manifest_path)
        except Exception as exc:  # noqa: BLE001 - recorded per zip, not re-raised
            report.failed[entry.id] = str(exc)
            continue

        state.mark_processed(entry.id)
        report.processed.append(entry.id)

    return report
