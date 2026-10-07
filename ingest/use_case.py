"""Ingest use case: download new zips, extract, publish, and record a manifest."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import shutil
from pathlib import Path

from ingest.manifest import Manifest, save
from ingest.ports import StateStore, VideoProcessor, VideoPublisher, ZipSource
from ingest.unzip import extract_sidecars, extract_videos


@dataclass
class IngestReport:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)


def _group_sidecars_by_session(
    sidecars: list[Path], extract_dir: Path
) -> dict[str, list[Path]]:
    """Group sidecars by their immediate parent folder (the session folder).

    Files extracted directly into `extract_dir` have no session folder and are
    skipped, matching the sidecar backfill's "no session folder" handling.
    """
    by_session: dict[str, list[Path]] = {}
    for sidecar in sidecars:
        if sidecar.parent == extract_dir:
            continue
        by_session.setdefault(sidecar.parent.name, []).append(sidecar)
    return by_session


def _session_for_video(video_path: Path) -> str:
    """Session token for a video: `RGB_<session>.mp4` -> `<session>`."""
    stem = video_path.stem
    return stem[4:] if stem.startswith("RGB_") else stem


def run_ingest(
    source: ZipSource,
    publisher: VideoPublisher,
    state: StateStore,
    manifest_path: Path,
    workdir: Path,
    max_zips: int | None = None,
    processor: VideoProcessor | None = None,
) -> IngestReport:
    manifest_path = Path(manifest_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    report = IngestReport()
    already_processed = state.processed_ids()

    pending = []
    for entry in source.list_zips():
        if entry.id in already_processed:
            report.skipped.append(entry.id)
        else:
            pending.append(entry)

    pending.sort(key=lambda e: (e.day or e.uploaded_at.date().isoformat(), e.uploaded_at))
    if max_zips is not None:
        report.deferred = [e.id for e in pending[max_zips:]]
        pending = pending[:max_zips]

    for entry in pending:
        entry_workdir = workdir / entry.id
        try:
            entry_workdir.mkdir(parents=True, exist_ok=True)
            zip_path = entry_workdir / entry.name
            source.download(entry, zip_path)

            extract_dir = entry_workdir / "videos"
            video_paths = extract_videos(zip_path, extract_dir)
            sidecars_by_session = _group_sidecars_by_session(
                extract_sidecars(zip_path, extract_dir, preserve_dirs=True),
                extract_dir,
            )

            day = entry.day or entry.uploaded_at.date().isoformat()
            manifest = Manifest()
            for video_path in video_paths:
                if processor is not None:
                    processed = processor.process(video_path, entry_workdir)
                    published = publisher.publish(
                        processed.video_path, day, poster_path=processed.poster_path
                    )
                    published = replace(
                        published, duration_seconds=processed.duration_seconds
                    )
                else:
                    published = publisher.publish(video_path, day)

                session = _session_for_video(video_path)
                metadata = {
                    sidecar.suffix.lstrip(".").lower(): publisher.publish_sidecar(
                        sidecar, day, session
                    )
                    for sidecar in sidecars_by_session.get(session, [])
                }
                manifest.add(
                    day, entry.name, published,
                    category=entry.category, uploader=entry.uploader,
                    metadata=metadata or None,
                )

            save(manifest, manifest_path)
        except Exception as exc:  # noqa: BLE001 - recorded per zip, not re-raised
            report.failed[entry.id] = str(exc)
            continue
        finally:
            shutil.rmtree(entry_workdir, ignore_errors=True)

        state.mark_processed(entry.id)
        report.processed.append(entry.id)

    if report.processed:
        publisher.publish_manifest(manifest_path)

    return report
