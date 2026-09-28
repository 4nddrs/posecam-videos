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
- Video storage backend is behind a port (`VideoPublisher`); the concrete adapter (Drive public folder vs object bucket) is an open decision.
- TDD: strict (session config, runner `python -m pytest` from repo root). Observe RED before GREEN.
- Route per task: delegated writer when 2+ non-trivial files (writer trigger).

## Tasks
- [x] T1 Ingest core with ports: `ZipSource`, `VideoPublisher`, `StateStore`; `unzip` extractor; `manifest` builder; `run_ingest` use case. Tests with fixture zips. (delegated, writer trigger)
- [x] T2 Google Drive adapter for `ZipSource` (list folder, download by id). Tests with fake Drive service. (delegated)
- [ ] T3 Static site `site/` reading `manifest.json`, grouped by day, inline player. (delegated)
- [ ] T4 GitHub Actions: cron ingest + Pages deploy; docs for secrets and setup. (inline or delegated)
- [ ] T5 `VideoPublisher` concrete adapter, pending storage decision.

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
