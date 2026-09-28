"""Backfill posters and faststart remux for videos already in R2.

Usage: python -m ingest.posters

Reads site/manifest.json, and for every video without a poster downloads
it from R2, remuxes it (faststart), generates a poster, uploads both and
updates the manifest. MAX_ZIPS_PER_RUN caps the videos handled per run.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ingest import manifest as manifest_mod
from ingest.adapters.ffmpeg import build_processor
from ingest.main import load_dotenv_file
from ingest.ports import VideoProcessor


def run_posters(
    manifest_path: Path,
    bucket: str,
    client: Any,
    processor: VideoProcessor,
    public_base_url: str,
    workdir: Path,
    max_items: int = 10,
) -> dict:
    manifest_path = Path(manifest_path)
    workdir = Path(workdir)
    base = public_base_url.rstrip("/")
    data = json.loads(manifest_path.read_text())
    pending = [
        v for d in data.get("days", []) for v in d.get("videos", [])
        if not v.get("poster") or v.get("duration") is None
    ]
    updated: list[str] = []
    durations: list[str] = []
    failed: dict[str, str] = {}

    for video in pending[:max_items]:
        key = video["id"]
        item_dir = workdir / f"item-{len(updated) + len(durations) + len(failed)}"
        try:
            item_dir.mkdir(parents=True, exist_ok=True)
            local = item_dir / Path(key).name
            client.download_file(bucket, key, str(local))
            if video.get("poster"):
                video["duration"] = processor.probe(local)
                manifest_mod.save(manifest_mod.Manifest.from_dict(data), manifest_path)
                if video["duration"] is None:
                    raise RuntimeError("no duration produced")
                durations.append(key)
                continue
            result = processor.process(local, item_dir)
            if result.poster_path is None:
                raise RuntimeError("no poster produced")
            client.upload_file(
                str(result.video_path), bucket, key,
                ExtraArgs={"ContentType": "video/mp4"},
            )
            poster_key = f"{key.rsplit('/', 1)[0]}/{Path(key).stem}.jpg" \
                if "/" in key else f"{Path(key).stem}.jpg"
            client.upload_file(
                str(result.poster_path), bucket, poster_key,
                ExtraArgs={"ContentType": "image/jpeg"},
            )
            video["duration"] = result.duration_seconds
            video["poster"] = f"{base}/{quote(poster_key)}"
            manifest_mod.save(manifest_mod.Manifest.from_dict(data), manifest_path)
            updated.append(key)
        except Exception as exc:  # noqa: BLE001 - keep processing others
            failed[key] = str(exc)
        finally:
            shutil.rmtree(item_dir, ignore_errors=True)

    return {
        "updated": updated,
        "durations": durations,
        "failed": failed,
        "remaining": len(pending) - len(updated) - len(durations),
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv_file(repo_root / ".env", os.environ)
    env = os.environ
    bucket = env.get("R2_BUCKET_NAME") or env.get("R2_BUCKET")
    missing = [
        n for n in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                    "R2_PUBLIC_BASE_URL") if not env.get(n)
    ]
    if not bucket:
        missing.append("R2_BUCKET_NAME")
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}",
              file=sys.stderr)
        raise SystemExit(1)

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=env.get("R2_ENDPOINT")
        or f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    workdir = Path(env.get("WORKDIR") or tempfile.mkdtemp(prefix="posters-"))
    report = run_posters(
        manifest_path=Path(env.get("MANIFEST_PATH", "site/manifest.json")),
        bucket=bucket,
        client=client,
        processor=build_processor(),
        public_base_url=env["R2_PUBLIC_BASE_URL"],
        workdir=workdir,
        max_items=int(env.get("MAX_ZIPS_PER_RUN") or 10),
    )
    print(json.dumps(report))
    if report["failed"] and not report["updated"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
