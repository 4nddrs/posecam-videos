"""Backfill per-video sidecar files (`.txt`/`.json`) that live inside Drive zips.

Usage: python -m ingest.sidecars [--dry-run] [--no-manifest] [--force] [--zip NAME]

Reads site/manifest.json, lists the configured Drive sources, downloads the
zips that produced the manifest videos, extracts their `.txt`/`.json`
sidecars and uploads each one to the deterministic R2 key beside its video
(`<day>/<stem><suffix>`). The public URL is stored under
`video["metadata"]["<suffix>"]` (e.g. `metadata.txt`, `metadata.json`) and the
manifest is re-uploaded.

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


def _stem(name: str) -> str:
    return Path(name).stem


def _plan_zips(
    entries: list, index: dict[str, list[tuple[str, dict]]],
    max_zips: int | None, only_zip: str | None,
) -> tuple[list, list[str]]:
    """Keep entries that own indexed videos, optionally filtered and capped."""
    kept = [entry for entry in entries if entry.name in index]
    if only_zip is not None:
        kept = [entry for entry in kept if entry.name == only_zip]
    if max_zips is not None:
        deferred = [entry.name for entry in kept[max_zips:]]
        return kept[:max_zips], deferred
    return kept, []


def _match_video(
    stem: str,
    by_stem: dict[str, list[tuple[str, dict]]],
    no_zip_videos: list[tuple[str, dict]],
) -> tuple[tuple[str, dict] | None, str | None]:
    """Resolve one sidecar stem to a single `(day, video)` inside its zip.

    Videos without a `source_zip` are matched by a whole-manifest stem search,
    but only when exactly one candidate exists. Returns `(match, reason)`;
    `reason` is set when the stem is ambiguous or matches nothing.
    """
    matches = by_stem.get(stem)
    if not matches:
        fallback = [pair for pair in no_zip_videos if _stem(pair[1]["name"]) == stem]
        if len(fallback) > 1:
            return None, "ambiguous stem"
        if not fallback:
            return None, "no matching video"
        matches = fallback
    if len(matches) > 1:
        return None, "ambiguous stem"
    return matches[0], None


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
    no_zip_videos: list[tuple[str, dict]] = []
    for day_entry in data.get("days", []):
        day = day_entry["day"]
        for video in day_entry.get("videos", []):
            zip_name = video.get("source_zip")
            if zip_name:
                index.setdefault(zip_name, []).append((day, video))
            else:
                no_zip_videos.append((day, video))

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
        source.list_zips(), index, max_zips, only_zip
    )
    report["deferred"] = deferred

    for entry in entries:
        zip_workdir = workdir / Path(entry.name).name
        try:
            zip_workdir.mkdir(parents=True, exist_ok=True)
            zip_path = source.download(entry, zip_workdir)
            sidecars = extract_sidecars(zip_path, zip_workdir / "sidecars")

            zip_videos = index.get(entry.name, [])
            by_stem: dict[str, list[tuple[str, dict]]] = {}
            for day, video in zip_videos:
                by_stem.setdefault(_stem(video["name"]), []).append((day, video))

            matched_ids: set[str] = set()
            for sidecar in sidecars:
                stem = _stem(sidecar.name)
                suffix = Path(sidecar.name).suffix.lower()
                content_type = _CONTENT_TYPES.get(suffix)
                if content_type is None:
                    report["unmatched"].append({
                        "zip": entry.name,
                        "sidecar": sidecar.name,
                        "reason": "unsupported sidecar type",
                    })
                    continue

                match, reason = _match_video(stem, by_stem, no_zip_videos)
                if match is None:
                    report["unmatched"].append({
                        "zip": entry.name,
                        "sidecar": sidecar.name,
                        "reason": reason,
                    })
                    continue

                day, video = match
                matched_ids.add(video["id"])
                key = f"{day}/{stem}{suffix}"
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
