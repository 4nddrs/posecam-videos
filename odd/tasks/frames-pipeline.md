# Feature: frames-pipeline

## Objective
Run frame extraction as a step of the existing ingest pipeline instead of as the standalone, untracked `extract_frames.py` script.

## Problem
`extract_frames.py` lives outside the `ingest/` package: it is untracked, untested, run by hand, and duplicates the R2 wiring. The pipeline must become one process ahead of the planned migration off GitHub Actions/Pages.

## Why
One pipeline, one schedule. Videos must reach R2 and the site first; frames are a later step that never delays the web.

## Scope
- New pipeline step `python -m ingest.frames`, ported from `extract_frames.py`.
- `FrameExtractor` port plus an ffmpeg adapter, with tests.
- Workflow wiring: a `frames` job that runs after `ingest`, in parallel with `deploy`.
- README section for the new step.

## Constraints
- **Frame storage is frozen** (user, 2026-10-01): do not change keys, names, labels or the index format. Contract to preserve byte for byte:
  - videos: every `.mp4` key (case-insensitive) outside `frames/`, sorted by key;
  - frames: `frames/<video key without extension>/frame_%06d.jpg`, `ContentType: image/jpeg`;
  - marker: `frames/<video key without extension>/index.json`, uploaded last, `ContentType: application/json`, `json.dumps(index, indent=2)` with `video_key`, `fps`, `frame_count`, `duration`, `start_time`, `frames[{key, timestamp(round 6)}]`;
  - ffmpeg: `-vf fps=<fps>,showinfo -vsync passthrough -q:v 3`, default 5 fps;
  - a video is done when its `index.json` exists; a timestamp/frame count mismatch falls back to `start_time + i / fps`.
- Ordering (user, 2026-10-01): videos land in R2 and on the site first; frames start only after that part is done.
- `extract_frames.py` is the user's untracked file: leave it in place, do not delete it.
- TDD: strict (source: user global CLAUDE.md, same as `video-gallery`); runner `.venv/bin/python -m pytest -q` from the repo root. Observe RED before GREEN.
- No AI attribution in commits; Conventional Commits.

## Tasks
- [x] T1 `ingest/frames.py` use case + CLI, `FrameExtractor` port, ffmpeg frame adapter, tests, README section. Route: delegated writer (writer trigger: 4+ non-trivial files).
- [x] T2 `.github/workflows/ingest.yml`: `frames` job after `ingest`, parallel to `deploy`, bounded per run. Route: inline (one already-understood file).

## Acceptance
- `python -m ingest.frames` produces the same R2 keys and the same `index.json` as `extract_frames.py` for the same video.
- A video with an existing `index.json` is skipped; a failed video stays pending and does not stop the run.
- The step needs only the R2 variables, not the Drive ones.
- In CI the site deploy does not wait for frames.

## Checks
- `.venv/bin/python -m pytest -q` green (baseline: 102 passed on main 006b41e).
- Workflow YAML parses.

## Delivery
- Strategy: ask-on-risk. Forecast ~450 authored lines (module ~180, tests ~200, workflow ~50, docs ~20); one commit per task. No PR is opened in this session; push and PR stay with the user.
- RDD: on (global). Assess after each work-unit commit; first boundary is the branch point 006b41e.

## Progress
- 2026-10-01: branch `feat/frames-pipeline` from main 006b41e; baseline 102 passed.
- 2026-10-01: T1 committed a7754dc (delegated writer, TDD: RED observed as import-level collection errors per test file, then GREEN; 142 passed, +40). Parent spot check: pytest re-run 142 passed, plus a differential run of `extract_frames.py` against `ingest.frames` with a fake ffmpeg and a fake S3 client: identical ffprobe/ffmpeg argv, frame keys, bytes, ExtraArgs, `index.json` key/body/content type, index uploaded last, with and without the timestamp fallback.
- 2026-10-01: T2 committed 4eb0967 (inline). Workflow YAML parses; jobs `ingest`, `frames`, `deploy`; `deploy` still needs only `ingest`. `frames` limited to `MAX_FRAME_VIDEOS_PER_RUN` (default 10) and 25 minutes.
- 2026-10-01: authored lines 1028 for T1 (556 of them tests) and 54 for T2, above the ~450 forecast because of test volume.

## Verification gaps
- No real ffmpeg run: ffmpeg/ffprobe are not installed on the development machine, so the adapter was verified against the original script with a fake runner only.
- `python -m ingest.frames` was not run against the real R2 bucket.
- The `frames` workflow job has not run in GitHub Actions (nothing pushed).

## Review
- RDD on (global). Assess on 006b41e..4eb0967: high (`process_boundary`, `ingest/adapters/frames.py`), `review_due` true (`high_risk`). Outcome: candidate consent pending with the user.

## Next step
User decisions: candidate review consent; push / PR; run `python -m ingest.frames --dry-run` where ffmpeg and the R2 credentials are available.
