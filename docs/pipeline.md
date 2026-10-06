# poseCamData pipeline

How a zip uploaded to Google Drive becomes a playable video on the site, and how the video list reaches other websites. For the full system description (frames step, data contracts, website) see [architecture.md](architecture.md); this document focuses on the ingest process and its operation.

## Contents

1. [End-to-end flow](#1-end-to-end-flow)
2. [Components](#2-components)
3. [Ports and adapters](#3-ports-and-adapters)
4. [manifest.json in R2](#4-manifestjson-in-r2)
5. [CORS](#5-cors)
6. [Known gaps](#6-known-gaps)
7. [Pending zips and draining a backlog](#7-pending-zips-and-draining-a-backlog)
8. [Running locally](#8-running-locally)

---

## 1. End-to-end flow

```
Drive folders (DRIVE_SOURCES)
  -> GitHub Actions (cron every 30 min, or manual dispatch)
  -> download zips
  -> extract videos
  -> ffmpeg: poster + duration
  -> upload to R2 (<day>/<name>)
  -> merge into site/manifest.json
  -> upload manifest.json to R2 (bucket root)
  -> commit manifest + state to main
  -> GitHub Pages deploy
```

1. **Drive folders.** Uploaders drop zips in Drive folders. The folders are listed in the `DRIVE_SOURCES` repository variable, formatted `folderId[=Category],...`. A source without `=Category` uses the subfolder names as categories.
2. **Trigger.** `.github/workflows/ingest.yml` has a `*/30 * * * *` cron. GitHub throttles scheduled workflows, so real runs are less frequent than every 30 minutes. A manual `workflow_dispatch` is the fast path.
3. **Limit per run.** `MAX_ZIPS_PER_RUN` (repository variable, currently 20) caps the zips handled in one run; the rest are reported as `deferred` and picked up by the next run.
4. **Download and extract.** Each new zip is downloaded and its videos are safely extracted.
5. **ffmpeg.** Each video is remuxed (faststart), a poster image is generated and the duration is probed.
6. **Upload to R2.** Video and poster go to the bucket under `<day>/<name>` keys.
7. **Manifest merge.** The videos are merged into `site/manifest.json`, idempotently by video id.
8. **Manifest to R2.** If at least one zip was processed, `manifest.json` is uploaded to the bucket root.
9. **Commit.** The workflow commits `site/manifest.json` and `ingest/state.json` to `main`.
10. **Deploy.** The `deploy` job publishes `site/` to GitHub Pages. A separate `frames` job extracts still frames (see [architecture.md](architecture.md#5-frames-step)).

## 2. Components

| Step | File |
|------|------|
| Config, `.env` loading, wiring, CLI | `ingest/main.py` |
| Use case (the loop over zips) | `ingest/use_case.py` |
| Port interfaces | `ingest/ports.py` |
| Drive listing and download | `ingest/adapters/drive.py` |
| Safe unzip | `ingest/unzip.py` |
| ffmpeg poster, faststart, duration | `ingest/adapters/ffmpeg.py` |
| R2 upload (videos, posters, manifest) | `ingest/adapters/r2.py` |
| Manifest build and merge | `ingest/manifest.py` |
| Processed-zip state | `ingest/state.py`, `ingest/state.json` |
| Poster/duration backfill | `ingest/posters.py` |
| Schedule, commit, deploy | `.github/workflows/ingest.yml` |
| Local end-to-end runner | `scripts/run_pipeline.py` |

## 3. Ports and adapters

The use case (`run_ingest` in `ingest/use_case.py`) depends only on the interfaces in `ingest/ports.py`: `ZipSource`, `VideoProcessor`, `VideoPublisher` and `StateStore`. The adapters implement them for Drive, ffmpeg, R2 and a JSON file. `ingest/main.py` is the composition root: it builds the adapters from the environment and injects them into `run_ingest`. Tests swap in fakes, so no network or ffmpeg is needed. See [architecture.md](architecture.md#4-code-architecture).

## 4. manifest.json in R2

After a run that processed at least one zip, `R2VideoPublisher.publish_manifest` (`ingest/adapters/r2.py`) uploads the merged manifest to the **bucket root** as `manifest.json`, with:

- `ContentType: application/json`
- `Cache-Control: no-cache`

External sites should read `${R2_PUBLIC_BASE_URL}/manifest.json` instead of the copy served by GitHub Pages.

**Why.** Sites used to be coupled to the Pages deploy: the list only changed after the commit and the deploy finished. Also, uploading videos to R2 does not update any list by itself; a site only knows about a video if some manifest mentions it. Publishing the manifest next to the videos keeps the list and the files in the same place, and `no-cache` makes new entries visible without waiting for cache expiry.

## 5. CORS

A browser on another origin can fetch `manifest.json` and the videos only if the R2 bucket (or its custom domain) has a CORS rule that allows that origin (at least `GET`/`HEAD`). That configuration lives in Cloudflare; **the pipeline does not touch bucket settings**. When adding a new site, add its origin to the bucket's CORS rules.

## 6. Known gaps

- **Posters backfill does not publish the manifest.** `ingest/posters.py` rewrites `site/manifest.json` but never uploads it to R2. The R2 copy stays stale until the next ingest run that processes a zip.
- **Manifest upload failure is not retried.** In `run_ingest`, `publish_manifest` runs after the zips are marked processed. If it raises, the error propagates but the zips stay processed, so the upload is not attempted again until new zips arrive.

## 7. Pending zips and draining a backlog

To see what is pending:

1. List the Drive folders using the **CI** `DRIVE_SOURCES` (repository variable). The local `.env` may still have the legacy `DRIVE_FOLDER_ID`, which covers only one folder and would give a wrong picture.
2. Diff the zip ids against the processed ids in `origin/main:ingest/state.json` (for example `git show origin/main:ingest/state.json`). Ids in Drive but not in state are pending.

To drain a backlog, trigger the workflow repeatedly (`workflow_dispatch`, mode `ingest`). Each run handles up to `MAX_ZIPS_PER_RUN` zips, commits the state, and the next run continues with the rest. The run output shows `deferred` until it reaches zero.

## 8. Running locally

```
python scripts/run_pipeline.py
```

Put the variables in `.env` at the repository root (`DRIVE_SOURCES`, `GOOGLE_API_KEY`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_BASE_URL`; `ffmpeg` on `PATH`). The script is a documented wiring layer over the same code CI runs (`python -m ingest.main`); each step is commented with the function that implements it. It uploads to the real bucket and edits `site/manifest.json` and `ingest/state.json` locally. See [architecture.md](architecture.md#9-running-it-locally) for more.
