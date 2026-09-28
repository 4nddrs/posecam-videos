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

## Tests

```bash
python -m pytest -q
node --test site/tests/app.test.mjs
```

## Configuration

Environment variables, loaded from `.env` at the repository root if present (existing environment variables always take precedence):

| Name | Required | Meaning |
|------|----------|---------|
| `DRIVE_FOLDER_ID` | yes | Google Drive folder id to watch for zip uploads. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | yes | Path to the Google service account JSON key file. |
| `R2_ACCOUNT_ID` | yes | Cloudflare account id that owns the R2 bucket. |
| `R2_ACCESS_KEY_ID` | yes | R2 S3-compatible access key id. |
| `R2_SECRET_ACCESS_KEY` | yes | R2 S3-compatible secret access key. |
| `R2_BUCKET` | yes | R2 bucket name videos are published to. |
| `R2_PUBLIC_BASE_URL` | yes | Public base URL the bucket is served from (used to build playable video URLs). |
| `MANIFEST_PATH` | no | Output path for the manifest (default `site/manifest.json`). |
| `STATE_PATH` | no | Path to the idempotency state file (default `ingest/state.json`). |
| `WORKDIR` | no | Working directory for downloads/extraction (default a fresh temp directory). |

## Deployment

Configured via GitHub Actions (`.github/workflows/ingest.yml` and `ci.yml`):

- Create these repository secrets: `GOOGLE_SERVICE_ACCOUNT_JSON` (the full service account key JSON, not a path), `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
- Create these repository (or environment) variables: `DRIVE_FOLDER_ID`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`.
- In repository Settings → Pages, set the source to "GitHub Actions".
- The R2 bucket must be configured for public access; `R2_PUBLIC_BASE_URL` is its public domain.
- The Drive folder must be shared read-only with the service account's email address.

## Operations

- `ingest/state.json` tracks which zip ids have already been processed, so running the ingest twice on the same zips processes them once (idempotency).
- To reprocess a zip, remove its id from `ingest/state.json` and re-run the ingest; the zip will be downloaded and published again.
