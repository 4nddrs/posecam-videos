# Feature: video-gallery

## Objective
Public static website where Ryan can watch, grouped by day, the videos Sorabh uploads as zip files to a Google Drive folder.

## Problem
Sorabh uploads zipped recordings to Drive folder `1z6UQzg5l7xgxqf3HTB5Ys2SJnrcU6PiN`. Zips are mandatory. Ryan cannot watch them without downloading and extracting.

## Scope
- Ingest pipeline (Python): detect new zips, download, extract videos, publish videos, write `manifest.json`, keep `state.json` for idempotency.
- Static site (vanilla HTML/JS): read `manifest.json`, list videos grouped by day, play them inline.
- Scheduled run via GitHub Actions cron + deploy to GitHub Pages.

## Constraints
- Site is public (decided 2026-09-28).
- Zips stay as the upload format.
- Video storage backend is behind a port (`VideoPublisher`); storage decided 2026-09-28: Cloudflare R2 public bucket, credentials via .env (never committed).
- TDD: strict (session config, runner `python -m pytest` from repo root). Observe RED before GREEN.
- Route per task: delegated writer when 2+ non-trivial files (writer trigger).

## Tasks
- [x] T1 Ingest core with ports: `ZipSource`, `VideoPublisher`, `StateStore`; `unzip` extractor; `manifest` builder; `run_ingest` use case. Tests with fixture zips. (delegated, writer trigger)
- [x] T2 Google Drive adapter for `ZipSource` (list folder, download by id). Tests with fake Drive service. (delegated)
- [x] T3 Static site `site/` reading `manifest.json`, grouped by day, inline player. (delegated)
- [x] T4 GitHub Actions: cron ingest + Pages deploy; docs for secrets and setup. (inline or delegated)
- [x] T5 `VideoPublisher` adapter for Cloudflare R2 (S3-compatible, boto3) + `ingest/main.py` CLI wiring env vars. (delegated)

## Acceptance
- Running ingest twice on the same zips processes them once.
- Manifest groups videos by upload date of the zip.
- Site renders every manifest entry with a playable element.

## Checks
- `python -m pytest` green per task.
- Site opens locally with a sample manifest.

## Delivery
- Strategy: ask-on-risk. Forecast ~600 authored lines total; slice per task commit.
- RDD: on (global). Assess after each work-unit commit.

## Progress
- 2026-09-28: repo initialized, branch `feat/video-gallery`, scaffold commit 01fc934.
- 2026-09-28: T1 committed 4ea2e99 (delegated writer, TDD RED→GREEN, 10 tests). RDD: medium, consent granted, reliability lens approved, acknowledged (lineage review-b647c221b480fc7c). Reviewed boundary = 4ea2e99.
- 2026-09-28: T2 committed 4a87d40 (delegated writer, TDD, 13 tests). RDD assess: medium, 228 lines, under_budget, pending in slice (base 4ea2e99).
- 2026-09-28: T3 site written (delegated writer, TDD, 6 node tests; `node --test <dir>` fails on Node 26.6, use explicit file path).
- 2026-09-28: T3 committed 552bf6c. RDD on range 4ea2e99..552bf6c (T2+T3): medium, 643 lines, consent granted, reliability lens approved, acknowledged (lineage review-31ee0be15315decb). Reviewed boundary = 552bf6c.
- 2026-09-28: T5 written (delegated writer, TDD, 23 tests total). `.env.example` left uncommitted pending user inspection (writer reported sandbox denied normal writes to `.env*` and used shell redirects).
- 2026-09-28: T5 committed e650138. RDD on range 552bf6c..e650138: medium, 432 lines, consent granted, reliability lens approved, acknowledged (lineage review-b983c03072bb48ef, untracked .env.example excluded). Reviewed boundary = e650138.
- 2026-09-28: T4 written (delegated writer): ingest.yml (cron 30m + Pages deploy), ci.yml, README. Un-ignored ingest/state.json so the workflow can persist it. DRIVE_FOLDER_ID, R2_BUCKET, R2_PUBLIC_BASE_URL are repo variables; the rest are secrets.
- 2026-09-28: T4 committed aa01adf. RDD on range e650138..aa01adf: high (shell in workflow), consent granted, 4 lenses; 4 CRITICAL findings (same root cause: service account JSON interpolated into shell). Corrected in 058b7ce (env + printf, fail fast when empty), targeted validation approved, acknowledged (lineage review-549633f5eb6abad4). Reviewed boundary = 058b7ce.

## Next step
- User inspects and commits `.env.example` (sandbox blocks the agent from reading `.env*`).
- User creates GitHub repo, pushes `feat/video-gallery`, opens PR to `main`.
- User configures secrets/vars listed in README and enables Pages (source: GitHub Actions).
- First real run: `workflow_dispatch` on ingest.yml; verify manifest.json gets committed and site renders.
- 2026-09-28: Follow-up 772618a: accept R2_BUCKET_NAME (alias of R2_BUCKET) and optional R2_ENDPOINT to match the user .env; 29 tests. RDD: high (workflow), consent granted, 4 lenses approved, acknowledged (lineage review-e2be0a0f17954697). Reviewed boundary = 772618a.
- 2026-09-28: Follow-up 3fd23e1: GOOGLE_API_KEY support for the public Drive folder (service account kept as alternative); workflow no longer writes a credentials file; 34 tests. RDD: high, consent granted, 4 lenses approved, acknowledged (lineage review-3b041bed46948e55). Reviewed boundary = 3fd23e1.
