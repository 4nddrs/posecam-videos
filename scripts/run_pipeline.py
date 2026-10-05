"""Run the whole poseCamData ingest pipeline locally, end to end.

Usage (from the repository root):

    python scripts/run_pipeline.py

WARNING: this talks to the REAL Google Drive folders and the REAL
Cloudflare R2 bucket. It uploads videos, posters and manifest.json to
production, and it rewrites site/manifest.json and ingest/state.json in
your working tree (review and commit them yourself if you want them kept).

Required environment variables (put them in a `.env` file at the repo
root, or export them; real environment variables win over `.env`):

    DRIVE_SOURCES          folderId[=Category],folderId[=Category],...
    GOOGLE_API_KEY         API key for reading the Drive folders
                           (or GOOGLE_SERVICE_ACCOUNT_FILE instead)
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
    R2_BUCKET_NAME         bucket that receives videos/posters/manifest
    R2_PUBLIC_BASE_URL     public URL of the bucket (no trailing slash)

Optional: MAX_ZIPS_PER_RUN (default 10), MANIFEST_PATH, STATE_PATH,
WORKDIR, R2_ENDPOINT. `ffmpeg` and `ffprobe` must be on your PATH.

This script is only a thin, documented wiring layer. It contains no
pipeline logic: every step below calls the existing `ingest` package.
CI (.github/workflows/ingest.yml, job "ingest") runs the same thing
every 30 minutes via `python -m ingest.main`, then commits the manifest
and state to main and deploys GitHub Pages. See docs/pipeline.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make `import ingest` work when running `python scripts/run_pipeline.py`
# (Python puts scripts/ on sys.path, not the repository root).
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ingest.main import load_config, load_dotenv_file, run  # noqa: E402


def main() -> None:
    # STEP 1 - Load .env into os.environ.
    # WHAT: reads KEY=VALUE lines; variables already set in the shell are
    #       never overridden.
    # WHERE: ingest/main.py: load_dotenv_file (parse_dotenv/apply_dotenv).
    load_dotenv_file(REPO_ROOT / ".env", os.environ)

    # STEP 2 - Validate and build the configuration.
    # WHAT: checks the required variables, parses DRIVE_SOURCES
    #       (`folderId[=Category],...`) into Drive sources, and resolves
    #       paths (site/manifest.json, ingest/state.json) and the per-run
    #       zip limit. Lists every missing variable in one error.
    # WHERE: ingest/main.py: load_config, parse_drive_sources.
    try:
        config = load_config(os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    # STEP 3 - Run the pipeline once. `run` wires the adapters and calls
    # the use case, which does, in order:
    #   a. Build the Drive source (one per DRIVE_SOURCES entry, combined by
    #      MultiZipSource) and list the zips.
    #      ingest/main.py: _default_source_builder;
    #      ingest/adapters/drive.py: DriveZipSource.list_zips.
    #   b. Skip zips already recorded in state.json, order the rest by day
    #      and upload time, and keep at most MAX_ZIPS_PER_RUN (the rest are
    #      "deferred" to the next run).
    #      ingest/use_case.py: run_ingest; ingest/state.py: JsonStateStore.
    #   c. For each zip: download it, safely extract the videos.
    #      ingest/adapters/drive.py: DriveZipSource.download;
    #      ingest/unzip.py: extract_videos.
    #   d. Process each video with ffmpeg (faststart remux, poster frame,
    #      duration via ffprobe).
    #      ingest/adapters/ffmpeg.py: build_processor.
    #   e. Upload video and poster to R2 under `<day>/<name>` keys.
    #      ingest/adapters/r2.py: R2VideoPublisher.publish.
    #   f. Merge the videos into site/manifest.json (idempotent by video id).
    #      ingest/manifest.py: Manifest.add, save.
    #   g. Mark the zip as processed in ingest/state.json. A failing zip is
    #      recorded in the report and does not stop the others.
    #      ingest/use_case.py: run_ingest; ingest/state.py: mark_processed.
    #   h. If at least one zip was processed, upload manifest.json to the
    #      bucket root (ContentType application/json, Cache-Control
    #      no-cache) so external sites can read it from R2.
    #      ingest/adapters/r2.py: R2VideoPublisher.publish_manifest.
    report = run(config)

    # STEP 4 - Print the outcome (same JSON shape as `python -m ingest.main`).
    # `report` is an ingest.use_case.IngestReport.
    print(
        json.dumps(
            {
                "processed": report.processed,
                "skipped": report.skipped,
                "failed": report.failed,
                "deferred": report.deferred,
            }
        )
    )

    # STEP 5 - Exit non-zero when any zip failed, like CI does, so a
    # wrapper script or cron job can notice.
    if report.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
