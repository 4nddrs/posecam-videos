"""Backfill per-video sidecar files (`.txt`/`.json`) that live inside Drive zips.

Usage: python -m ingest.sidecars [--dry-run] [--no-manifest] [--force] [--zip NAME]

Reads site/manifest.json, lists the configured Drive sources, downloads the
zips that produced the manifest videos, extracts their `.txt`/`.json`
sidecars and uploads each one into the per-session folder beside its video
(`<day>/<session>/<filename>`). The video's R2 key is never changed. The public
URL is stored under `video["metadata"]["<suffix>"]` (e.g. `metadata.txt`,
`metadata.json`) and the manifest is re-uploaded.

Sidecars are paired to videos by SESSION FOLDER, not by basename: each zip
contains one or more `<session-token>/` folders whose session token also
appears in the video name (`RGB_<session>.mp4`) and in the sidecar names
(`AR_Pose_<session>.txt`, `posecam_export.json`).

Environment variables (reused from the ingest pipeline):
DRIVE_SOURCES (or DRIVE_FOLDER_ID), GOOGLE_API_KEY (or
GOOGLE_SERVICE_ACCOUNT_FILE), R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME (or R2_BUCKET), R2_PUBLIC_BASE_URL,
optionally R2_ENDPOINT, MANIFEST_PATH, WORKDIR and MAX_ZIPS_PER_RUN. Values
already present in the environment win over the repository-root `.env` file.

WARNING: this talks to the REAL Drive and R2 accounts and rewrites the
manifest. Use --dry-run to preview planned keys, and --no-manifest to skip the
manifest save/publish.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ingest import manifest as manifest_mod
from ingest.adapters.r2 import R2VideoPublisher
from ingest.main import _default_source_builder, load_config, load_dotenv_file
from ingest.ports import VideoPublisher, ZipSource
from ingest.unzip import extract_sidecars

_CONTENT_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
}

# Session token shared by the video and sidecar names, e.g.
# `2026-10-06-08_23_23-e6ea35-s1`.
_SESSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}_\d{2}_\d{2}-[0-9a-f]+-s\d+")


def _session_token(text: str) -> str | None:
    """Return the first session token embedded in `text`, or `None`."""
    match = _SESSION_RE.search(text)
    return match.group(0) if match else None


def _zip_done(videos: list[tuple[str, dict]]) -> bool:
    """Return True when every video in `videos` already has non-empty metadata."""
    return bool(videos) and all(
        video.get("metadata") for _day, video in videos
    )


def _plan_zips(
    entries: list, index: dict[str, list[tuple[str, dict]]],
    max_zips: int | None, only_zip: str | None, force: bool = False,
) -> tuple[list, list[str]]:
    """Keep not-yet-done entries that own indexed videos, filtered and capped.

    A zip whose videos are all already backfilled (`_zip_done`) is skipped, so
    it is neither processed nor counted in `deferred`. `force` reprocesses
    every indexed zip regardless of prior metadata.
    """
    kept = [
        entry for entry in entries
        if entry.name in index and (force or not _zip_done(index[entry.name]))
    ]
    if only_zip is not None:
        kept = [entry for entry in kept if entry.name == only_zip]
    if max_zips is not None:
        deferred = [entry.name for entry in kept[max_zips:]]
        return kept[:max_zips], deferred
    return kept, []


def _resolve_video(
    session: str,
    by_session: dict[str, tuple[str, dict]],
    no_token_videos: list[tuple[str, dict]],
    manifest_by_session: dict[str, list[tuple[str, dict]]],
) -> tuple[tuple[str, dict] | None, str | None]:
    """Resolve one session folder to a single `(day, video)`.

    The zip's own videos (indexed by session token) win; if the token is not
    found there, a whole-manifest session-token search is used but only when
    exactly one candidate exists. Videos whose names carry no session token are
    kept in `no_token_videos` and used as a last resort when the folder has no
    token either. Returns `(match, reason)`.
    """
    token = _session_token(session)
    if token is None:
        if len(no_token_videos) > 1:
            return None, "ambiguous session"
        if not no_token_videos:
            return None, "no matching video"
        return no_token_videos[0], None
    match = by_session.get(token)
    if match is not None:
        return match, None
    candidates = manifest_by_session.get(token, [])
    if len(candidates) > 1:
        return None, "ambiguous session"
    if not candidates:
        return None, "no matching video"
    return candidates[0], None


def run_sidecars(
    manifest_path: Path,
    source: ZipSource,
    publisher: VideoPublisher,
    r2_client: Any,
    bucket: str,
    public_base_url: str,
    workdir: Path,
    *,
    max_zips: int | None = None,
    dry_run: bool = False,
    update_manifest: bool = True,
    force: bool = False,
    only_zip: str | None = None,
) -> dict:
    """Recover `.txt`/`.json` sidecars from Drive zips and attach them to videos.

    Returns a JSON-serializable report with `processed`, `uploaded`, `skipped`,
    `planned`, `unmatched`, `missing`, `failed`, `deferred` and `dry_run`.
    """
    manifest_path = Path(manifest_path)
    workdir = Path(workdir)
    base = public_base_url.rstrip("/")
    data = json.loads(manifest_path.read_text())

    # zip name -> [(day, video record), ...]
    index: dict[str, list[tuple[str, dict]]] = {}
    # session token -> [(day, video record), ...] across the whole manifest
    manifest_by_session: dict[str, list[tuple[str, dict]]] = {}
    for day_entry in data.get("days", []):
        day = day_entry["day"]
        for video in day_entry.get("videos", []):
            token = _session_token(video.get("name", ""))
            if token:
                manifest_by_session.setdefault(token, []).append((day, video))
            zip_name = video.get("source_zip")
            if zip_name:
                index.setdefault(zip_name, []).append((day, video))

    report: dict = {
        "processed": [],
        "uploaded": [],
        "skipped": [],
        "planned": [],
        "unmatched": [],
        "missing": [],
        "failed": {},
        "deferred": [],
        "dry_run": dry_run,
    }

    entries, deferred = _plan_zips(
        source.list_zips(), index, max_zips, only_zip, force
    )
    report["deferred"] = deferred

    for entry in entries:
        zip_workdir = workdir / Path(entry.name).name
        try:
            zip_workdir.mkdir(parents=True, exist_ok=True)
            zip_path = source.download(entry, zip_workdir)
            extract_dir = zip_workdir / "sidecars"
            sidecars = extract_sidecars(zip_path, extract_dir, preserve_dirs=True)

            zip_videos = index.get(entry.name, [])
            by_session: dict[str, tuple[str, dict]] = {}
            no_token_videos: list[tuple[str, dict]] = []
            for day, video in zip_videos:
                token = _session_token(video["name"])
                if token:
                    by_session[token] = (day, video)
                else:
                    no_token_videos.append((day, video))

            # Session folder (immediate parent dir name) -> sidecar files in it.
            folders: dict[str, list[Path]] = {}
            for sidecar in sidecars:
                if sidecar.parent == extract_dir:
                    report["unmatched"].append({
                        "zip": entry.name,
                        "sidecar": sidecar.name,
                        "reason": "no session folder",
                    })
                    continue
                folders.setdefault(sidecar.parent.name, []).append(sidecar)

            matched_ids: set[str] = set()
            for session, files in folders.items():
                match, reason = _resolve_video(
                    session, by_session, no_token_videos, manifest_by_session
                )
                if match is None:
                    for sidecar in files:
                        report["unmatched"].append({
                            "zip": entry.name,
                            "sidecar": sidecar.name,
                            "reason": reason,
                        })
                    continue

                day, video = match
                matched_ids.add(video["id"])

                by_suffix: dict[str, list[Path]] = {}
                for sidecar in files:
                    by_suffix.setdefault(sidecar.suffix.lower(), []).append(sidecar)

                for suffix, group in by_suffix.items():
                    content_type = _CONTENT_TYPES.get(suffix)
                    if content_type is None:
                        for sidecar in group:
                            report["unmatched"].append({
                                "zip": entry.name,
                                "sidecar": sidecar.name,
                                "reason": "unsupported sidecar type",
                            })
                        continue

                    # One file per suffix; the extra ones are ambiguous.
                    group = sorted(group, key=lambda path: path.name)
                    for sidecar in group[1:]:
                        report["unmatched"].append({
                            "zip": entry.name,
                            "sidecar": sidecar.name,
                            "reason": "ambiguous sidecar",
                        })
                    sidecar = group[0]

                    key = f"{day}/{session}/{sidecar.name}"
                    metadata = video.setdefault("metadata", {})
                    suffix_key = suffix.lstrip(".")

                    if suffix_key in metadata and not force:
                        report["skipped"].append(key)
                        continue
                    if dry_run:
                        report["planned"].append(key)
                        continue

                    r2_client.upload_file(
                        str(sidecar), bucket, key,
                        ExtraArgs={"ContentType": content_type},
                    )
                    metadata[suffix_key] = f"{base}/{quote(key)}"
                    report["uploaded"].append(key)

            for _day, video in zip_videos:
                if video["id"] not in matched_ids:
                    report["missing"].append(video["id"])
            report["processed"].append(entry.name)
        except Exception as exc:  # noqa: BLE001 - recorded per zip, not re-raised
            report["failed"][entry.name] = str(exc)
        finally:
            shutil.rmtree(zip_workdir, ignore_errors=True)

    if update_manifest and not dry_run:
        manifest_mod.save(manifest_mod.Manifest.from_dict(data), manifest_path)
        publisher.publish_manifest(manifest_path)

    return report


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv_file(repo_root / ".env", os.environ)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="compute and report planned keys without uploading")
    parser.add_argument("--no-manifest", action="store_true",
                        help="skip saving and publishing the manifest")
    parser.add_argument("--force", action="store_true",
                        help="re-upload sidecars whose metadata already exists")
    parser.add_argument("--zip", dest="only_zip", default=None,
                        help="process only this exact zip name")
    args = parser.parse_args()

    try:
        config = load_config(os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=config.r2_endpoint
        or f"https://{config.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=config.r2_access_key_id,
        aws_secret_access_key=config.r2_secret_access_key,
        region_name="auto",
    )
    report = run_sidecars(
        manifest_path=config.manifest_path,
        source=_default_source_builder(config),
        publisher=R2VideoPublisher(client, config.r2_bucket, config.r2_public_base_url),
        r2_client=client,
        bucket=config.r2_bucket,
        public_base_url=config.r2_public_base_url,
        workdir=config.workdir,
        max_zips=config.max_zips_per_run,
        dry_run=args.dry_run,
        update_manifest=not args.no_manifest,
        force=args.force,
        only_zip=args.only_zip,
    )
    print(json.dumps(report))
    if report["failed"] and not report["uploaded"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
