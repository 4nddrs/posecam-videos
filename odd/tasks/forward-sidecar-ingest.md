# Feature: forward-sidecar-ingest

## Objective
Forward ingest (`python -m ingest.main` -> `run_ingest`) must, per zip, upload the video `.mp4` AND its `.txt`/`.json` sidecars to R2 using the same layout the sidecar backfill already uses, and record their URLs in the manifest — so future drains need no separate backfill.

## Problem
`run_ingest` extracts only video files (`extract_videos`) and silently drops `.txt`/`.json`. Sidecars are recovered today only by the separate `ingest.sidecars` backfill. From now on the forward path should do it in one pass.

## Why
User request (2026-10-07): each zip must yield `.txt`, `.json` and `.mp4` in R2 "just as the others are", avoiding a separate backfill per batch.

## Scope
- `ingest/ports.py`: add `publish_sidecar(sidecar_path, day, session) -> str` to the `VideoPublisher` protocol.
- `ingest/adapters/r2.py`: implement it with the existing key/content-type format.
- `ingest/unzip.py`: no change (reuse `extract_sidecars(preserve_dirs=True)`).
- `ingest/use_case.py`: extract sidecars per zip, publish them, attach to the manifest record.
- `ingest/manifest.py`: `Manifest.add(..., metadata=None)` writes `metadata` only when non-empty.
- Tests: `ingest/tests/test_r2_publisher.py`, `test_use_case.py`, `test_manifest.py`.

## Frozen contracts (verified against R2, 2026-10-07 — do NOT change)
- Video R2 key `{day}/RGB_<session>.mp4`; poster `{day}/RGB_<session>.jpg`. Never moved or renamed.
- Sidecar R2 key `{day}/<session>/<filename>`; content types `.txt` -> `text/plain; charset=utf-8`, `.json` -> `application/json`.
- Manifest sidecar URLs live in `video["metadata"]["txt"]` / `video["metadata"]["json"]`; the `metadata` key is omitted when absent.
- Zip inner layout: `<zipstem>/<session>/{RGB_<session>.mp4, AR_Pose_<session>.txt, posecam_export.json}`.
- Categories preserved (Drive subfolder name -> `category`), unchanged.

## Tasks
- [x] T1 ports + r2 adapter + use_case + manifest + tests. Route: delegated writer (writer trigger: 4+ non-trivial files). Commit `aba7c16`.

## Acceptance
- A zip containing mp4+txt+json produces in R2: the video, the poster (if any), `{day}/{session}/AR_Pose_<session>.txt`, `{day}/{session}/posecam_export.json`.
- The manifest record has `metadata.txt` / `metadata.json` URLs pointing at those keys.
- A zip with only a video still works and its record has no `metadata` key.
- `pytest -q` green.

## Checks
- `.venv/bin/python -m pytest -q` (baseline: 185 passed on main).
- TDD strict: observe RED before GREEN. Runner `.venv/bin/python -m pytest -q` from repo root.

## Delivery
- Strategy: ask-on-risk. Forecast ~190 authored lines (well under 400). Branch `feat/forward-sidecar-ingest`; one commit for T1.
- RDD: on (global). Assess after the work-unit commit.

## Progress
- 2026-10-07: verified real R2 format and zip inner layout (Engram: Drive/R2 format discovery). Branch `feat/forward-sidecar-ingest` from main.
- 2026-10-07: T1 committed `aba7c16` (delegated writer, TDD: 6 new tests RED — AttributeError/TypeError/no-publish — then GREEN; 192 passed, +7). Parent spot check: pytest re-run 192 passed; diff reviewed, forbidden files untouched (`sidecars.py`, `unzip.py`, `drive.py`, workflows).
- 2026-10-07: RDD assess on main..aba7c16 (committed-only, untracked excluded): medium (`executable_change`), 245 changed lines, `review_due: false` (`under_budget`). No review this slice; boundary stays pending.

## Verification gaps
- No real R2/Drive write from the forward path in this session (tests use fakes). The first real drain after landing is the end-to-end check.
