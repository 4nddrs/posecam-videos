# poseCamData

Daily video gallery: ingests zipped recordings from a Google Drive folder, extracts the videos, publishes them and renders a static site grouped by day.

## Overview

Sorabh uploads zipped recordings to a shared Google Drive folder. The ingest pipeline detects new zips, downloads and extracts them, publishes the videos to public storage, and writes a `site/manifest.json` that the static site reads to list every video grouped by upload day, playable inline. A scheduled GitHub Actions workflow runs the ingest step and deploys the site to GitHub Pages.

## Architecture

The ingest pipeline follows a ports-and-adapters (hexagonal) style: the use case (`run_ingest`) depends only on small port interfaces (`ZipSource`, `VideoPublisher`, `StateStore`), and concrete adapters plug into them. This keeps the core logic testable without real Drive or storage access.

- `ingest/ports.py` — `ZipSource`, `VideoPublisher` port interfaces.
- `ingest/use_case.py` — `run_ingest`, the ingest orchestration logic.
- `ingest/unzip.py` — zip extraction.
- `ingest/manifest.py` — builds `site/manifest.json`.
- `ingest/state.py` — `JsonStateStore`, idempotency tracking (`ingest/state.json`).
- `ingest/adapters/drive.py` — Google Drive adapter for `ZipSource`.
- `ingest/adapters/r2.py` — Cloudflare R2 adapter for `VideoPublisher`.
- `ingest/posters.py` — backfill command: `python -m ingest.posters`.
- `ingest/main.py` — CLI entry point; wires adapters from environment variables and runs the use case.
- `site/` — static site (vanilla HTML/JS) that reads `manifest.json` and renders the gallery.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env  # fill in the values described in Configuration
python -m ingest.main
python3 -m http.server -d site 8000
```

Then open `http://localhost:8000`.

To create the Google API key: in the Google Cloud Console, enable the Google Drive API for a project, then go to APIs & Services → Credentials → Create credentials → API key, and put it in `.env` as `GOOGLE_API_KEY`. Share the Drive folder as "anyone with the link".

## Tests

```bash
python -m pytest -q
node --test site/tests/app.test.mjs
```

## Configuration

Environment variables, loaded from `.env` at the repository root if present (existing environment variables always take precedence):

| Name | Required | Meaning |
|------|----------|---------|
| `DRIVE_SOURCES` | yes, unless `DRIVE_FOLDER_ID` is set | Comma-separated list of `folderId[=Category]`. Each folder is scanned for zips (root and one level of subfolders). The category is the label after `=`, or else the zip's immediate subfolder name (e.g. `White pipes`); videos never mix categories in the site. Example: `1w_VFQ...=,1z6UQ...=Remaining` (an empty label means "use subfolder names"). |
| `DRIVE_FOLDER_ID` | legacy | Single Drive folder id, used only when `DRIVE_SOURCES` is empty. Its videos get the category `Remaining`. |
| `GOOGLE_API_KEY` | yes, unless `GOOGLE_SERVICE_ACCOUNT_FILE` is set | Google API key used to read the Drive folder. The folder must be shared as "anyone with the link". |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | no | Alternative to `GOOGLE_API_KEY`: path to a Google service account JSON key file (used only when no API key is set). |
| `R2_ACCOUNT_ID` | yes | Cloudflare account id that owns the R2 bucket. |
| `R2_ACCESS_KEY_ID` | yes | R2 S3-compatible access key id. |
| `R2_SECRET_ACCESS_KEY` | yes | R2 S3-compatible secret access key. |
| `R2_BUCKET_NAME` | yes | R2 bucket name videos are published to (preferred; the legacy `R2_BUCKET` is also accepted). |
| `R2_ENDPOINT` | no | Overrides the S3 API endpoint; defaults to `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`. |
| `R2_PUBLIC_BASE_URL` | yes | Public base URL the bucket is served from (used to build playable video URLs). It is the bucket's public domain (r2.dev subdomain or custom domain), not the S3 API endpoint. |
| `MANIFEST_PATH` | no | Output path for the manifest (default `site/manifest.json`). |
| `STATE_PATH` | no | Path to the idempotency state file (default `ingest/state.json`). |
| `MAX_ZIPS_PER_RUN` | no | Maximum number of new zips processed per run, oldest first (default `10`; also the max videos per `ingest.posters` run). The rest are reported as `deferred` and picked up by later runs. |
| `FFMPEG_BIN` | no | ffmpeg binary (default `ffmpeg`). If missing, posters and faststart are skipped. |
| `WORKDIR` | no | Working directory for downloads/extraction (default a fresh temp directory). |

## Deployment

Configured via GitHub Actions (`.github/workflows/ingest.yml` and `ci.yml`):

- Create these repository secrets: `GOOGLE_API_KEY`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
- Create these repository (or environment) variables: `DRIVE_SOURCES` (or the legacy `DRIVE_FOLDER_ID`), `R2_BUCKET_NAME`, `R2_PUBLIC_BASE_URL`.
- In repository Settings → Pages, set the source to "GitHub Actions".
- The R2 bucket must be configured for public access; `R2_PUBLIC_BASE_URL` is its public domain.
- The Drive folder must be shared as "anyone with the link" (viewer) so the API key can read it.

## Operations

- `ingest/state.json` tracks which zip ids have already been processed, so running the ingest twice on the same zips processes them once (idempotency).
- The Drive folder holds `DD-MM-YYYY` date subfolders containing the zips; the subfolder name sets the video's day. Each run processes at most `MAX_ZIPS_PER_RUN` new zips (oldest first), so the initial backfill happens over several runs; the remaining zips appear as `deferred` in the printed report. Each zip's download and extracted files are deleted after it is processed.
- Zips are detected by extension or by the `application/zip` mime type, so uploads that lost the `.zip` extension still work. The day comes from the `capture-YYYYMMDD` timestamp in the zip name. Each video records its `category` and the Drive owner display name as `uploader` (emails are never stored; the manifest is public).
- To reprocess a zip, remove its id from `ingest/state.json` and re-run the ingest; the zip will be downloaded and published again.

## Posters and faststart

ffmpeg is required for this step (the workflow installs it; locally install it or set `FFMPEG_BIN`). Every published video is remuxed to faststart (`-c copy -movflags +faststart`, no re-encode) and gets a JPG poster (`<day>/<name>.jpg`), so browsers can preview it without stalling.

To backfill videos published before this existed:

```bash
python -m ingest.posters
```

It downloads each video without a `poster` from R2, remuxes it, uploads the video back to the same key plus the poster, and updates `site/manifest.json` after each video. At most `MAX_ZIPS_PER_RUN` videos are handled per run; the printed JSON report `{"updated": [...], "failed": {...}, "remaining": n}` shows what is left. It exits 1 only if nothing could be processed and there were failures.

In GitHub Actions, run the workflow manually (workflow_dispatch) with `mode` set to `posters`; the default `ingest` mode is the normal ingest.
