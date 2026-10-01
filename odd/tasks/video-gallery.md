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
- 2026-09-28: Real run findings: Drive root holds DD-MM-YYYY subfolders with zips (~2 GB/day). Adapter now recurses, day parsed from folder name, MAX_ZIPS_PER_RUN cap (default 10), per-zip cleanup. First real ingest with cap 2: 3 videos in R2 under 2026-09-24/, public r2.dev URL serves 206 video/mp4 (Cloudflare blocks non-browser UAs with error 1010; browsers fine). Sample manifest entries removed. 44 tests.
- 2026-09-28: Deployed. Repo 4nddrs/posecam-videos (public), Pages via Actions at https://4nddrs.github.io/posecam-videos/. First CI ingest: 10 processed, 0 failed, manifest committed f5d2e99. Deploy initially failed: github-pages environment branch policy only allowed feat/video-gallery (created by a misrouted first dispatch); fixed via API by allowing main. Site live with 2025-09-25 (7) and 2025-09-24 (3). 33 zips still deferred, 10 per 30-min run.
- 2026-09-28: UI redesign e82bf13 on feat/ui-redesign (dark theme, day nav, readable cards, 11 node tests; verified with headless Chrome at 1280 and 390 px). RDD: medium, consent granted, reliability lens approved, acknowledged (lineage review-7490082e6288e325). Merged to main and deployed.
- 2026-09-28: cd1e787 workflow passes MAX_ZIPS_PER_RUN repo variable (set to 50 for backfill). RDD: high, granted, 4 lenses approved, acknowledged (lineage review-980b9d777d0a3be5). Merged to main.
- 2026-09-28: Backfill run with cap 50 failed after 22 zips: Google Drive returned 403 "Sorry..." (download abuse throttle on the API key); commit step was skipped so those 22 videos in R2 were not recorded. Fix 202b1a7: commit step runs unless cancelled. Cap variable lowered to 12. RDD: high, granted, 4 lenses approved, acknowledged (lineage review-d14e734a698739fc).
- 2026-09-28: Backfill complete: 45/45 zips processed, 50 videos live (26-09: 17, 25-09: 30, 24-09: 3), deferred empty. Cap stays at 12 per 30-min run.
- 2026-09-28: d333a15 videos use preload=none with a play overlay; MP4s from the camera are not faststart (moov at file end, codec H.264), so many simultaneous metadata fetches stalled Firefox-based browsers (Zen). RDD: medium, granted, reliability approved, acknowledged (lineage review-69089b82974637b8). Follow-up idea: ffmpeg -movflags +faststart in ingest.

## Phase 2: posters and faststart (2026-09-28)
User wants per-video thumbnails that work in Firefox-based browsers. Camera MP4s are not faststart, so browser-side previews stall.
- [x] T6 `VideoProcessor` port + ffmpeg adapter: faststart remux (`-c copy -movflags +faststart`) and poster JPG (frame at ~1s, 640px wide). No-op fallback when ffmpeg is missing. Publisher uploads poster; manifest entry gets `poster`. (delegated)
- [x] T7 Site: cards show `poster` with play overlay; fallback to current behaviour when absent. (delegated)
- [x] T8 Workflow installs ffmpeg; `python -m ingest.posters` backfills posters for existing R2 objects (reads from R2, no Drive access) + manual workflow. (delegated)
- 2026-09-28: Phase 2 committed (8189d14 processor, d2193bf CI+backfill, 40a1d91 site). RDD on branch vs main: high, granted, 4 lenses approved, acknowledged (lineage review-6b45c3d982f736c8). Merged to main; poster backfill dispatched via workflow mode=posters.

## Phase 3: review tools (2026-09-28, user request)
- [x] T9 Ingest: `ffprobe` duration in `FfmpegProcessor` → `ProcessedVideo.duration_seconds` → manifest `duration`; posters backfill also fills missing durations. (delegated)
- [x] T10 Site filters: duration range slider + per-day hour histogram (00–23) that filters cards on click. (delegated)
- [x] T11 Site player tools: playlist mode (auto-advance within a day), speed shortcuts (1x/1.5x/2x/4x), keyboard shortcuts (space, arrows, F), deep links `#<video-id>` that open the day and scroll/ready the video; "Copy link" copies that deep link. (delegated)
- Note: item 2 of the request (filename metadata parsing) was already delivered in the UI redesign.
- 2026-09-28: Phase 3 committed (e271d98 duration, 2a8e0ba filters, a1891f1 player tools, fcb0b10 correction). RDD on branch vs main: high, granted, 4 lenses; 1 CRITICAL (stale grid after filter change while collapsed) corrected in fcb0b10; validator first capture malformed (provider), reoffered capture approved; acknowledged (lineage review-79f5ef1bf44bc83e). Posters backfill complete 50/50. Duration backfill dispatched.
- 2026-09-28: Phase 3 merged 95621ac. Duration backfill complete: 50/50 videos with poster and duration. Live at https://4nddrs.github.io/posecam-videos/.
- 2026-09-29: 2d53038 all days collapsed by default; Min/Max labels and per-slider values on the duration filter. RDD: medium (under budget, preflight offered anyway), granted, reliability approved, acknowledged (lineage review-e1c2a4721be5fc72).
- 2026-09-29: Drive reorganized into "Remaining Videos" (undated). Day now parsed from the capture timestamp in the zip name; " (N)" duplicates dropped. Real listing: 122 new zips (27-09: 68, 28-09: 48, 26-09: 6). Cron disabled during the fix.
- 2026-09-29: 8a0ab45 reviewed (medium, granted, reliability approved, lineage review-55accbb7458c70ec). Merged; cron re-enabled; MAX_ZIPS_PER_RUN=20 for the 122-zip backfill.
- 2026-09-29: Backfill of "Remaining Videos" complete: 122 zips, 149 new videos, 0 failures. Live: 28-09 57, 27-09 92, 26-09 17, 25-09 30, 24-09 3 (199 total, all with poster+duration). The six 26-09 evening zips were re-uploaded copies; idempotent R2 keys and manifest dedupe kept the count at 17. MAX_ZIPS_PER_RUN left at 20.

## Phase 4: density toggle (2026-09-30, user request)
- [x] T12 Site: header toggle between the current card grid ("Cards") and a compact list ("List": one row per video with time, file name, duration, play and copy-link; no poster). Choice persisted in localStorage (try/catch), default Cards. Filters, histogram, playlist, keyboard shortcuts and deep links keep working in both modes. Tests in `site/tests/app.test.mjs`. (delegated, writer trigger: index.html + app.js + styles.css + tests)
- 2026-09-30: 054f54b density toggle (delegated writer, TDD, 31 node tests).
- 2026-09-30: T12 reviewed (medium, 288 lines, granted, reliability approved, acknowledged lineage review-006cb6071f1151a8). Advisory only: list-mode DOM paths untested (WARNING); arrow/auto-advance leaves earlier rows open; switch-while-collapsed staleness note. Browser check at 1280/390 px still pending.
- 2026-09-30: 6af7352 layout toggle moved into a sticky bar with the day nav. Reviewed (medium, granted, reliability approved, acknowledged lineage review-14199f00c6b572eb); advisory: list DOM untested, stepping leaves rows open.
- 2026-09-30: videos within each day now newest first (site-side sort in groupByDay; manifest order unchanged). TDD RED 1 fail → GREEN 32 pass. Auto-play/ArrowRight follow display order, so they now step to older recordings.

## Phase 5: categories and uploader (2026-09-30, user request)
New Drive "PoseCam data from Tirth" (1w_VFQjkn0ceieOcG3T2jiMEWGXWKZvgp) has subfolders "White pipes" and "Black pipes" (10 zips each, 30-09). 18 of the 20 files have no `.zip` extension (`PoseCam capture-…-pipeline`, mimeType application/zip). Categories must never mix in the UI. The existing 199 videos become category "Remaining" (user decision). Uploader = Drive owner display name only; never publish emails (public site).
Branch `feat/categories`, stacked on `feat/density-toggle` (unmerged).
- [x] T13 Ingest: multiple Drive sources (`DRIVE_SOURCES` = comma list of `folderId[=Category]`; legacy `DRIVE_FOLDER_ID` → category "Remaining"). Category = source label if given, else the zip's immediate subfolder name. Accept zip mimeType without `.zip` extension; day parsed from `capture-YYYYMMDD` anywhere in the name. `ZipEntry` + manifest entries gain `category` and `uploader`; `from_dict` defaults a missing category to "Remaining". Workflow passes `DRIVE_SOURCES`. (delegated, writer trigger)
- [x] T14 Uploader backfill for existing "Remaining" videos by matching `source_zip` against the old Drive listing (display names only). (delegated)
- [x] T15 Site: category tabs, one category at a time (default: category with the newest video; persisted; deep links select the video's category). Day nav, stats, filters, histogram and playlist are scoped to the active category. Card and list row show uploader. (delegated)
- 2026-09-30: T13 e680d48 (delegated writer, TDD RED collection error -> GREEN, 93 pytest). DRIVE_SOURCES + category/uploader + extensionless zips; workflow passes vars.DRIVE_SOURCES; README updated. `.env.example` NOT updated (agent sandbox denies access): user should add `DRIVE_SOURCES=<folderId>[=Category],...`.
- 2026-09-30: T14 4f996c4 (`python -m ingest.uploaders`, 96 pytest). Real backfill: 199 videos, 158 uploader filled (sourabhkumawat117), 41 unmatched (24-26 Sep zips no longer in Drive), category Remaining set on all 199.
- 2026-09-30: T15 2126962 (category tabs, 40 node tests, node --check ok; headless Chrome check: default tab, deep link switches category).
- 2026-09-30: Phase 5 review. The whole-branch candidate exceeded the lens context budget (1798 lines, mostly manifest.json), so each commit was reviewed separately in a detached worktree. T13 e680d48: high, 4 lenses, approved (lineage review-275741b858852909). T14 4f996c4: medium, approved (review-4e8962692ca5e7ff). T15 2126962: medium, approved (review-c2d64f9bab7720f3). All acknowledged. Advisory follow-ups: one failing Drive source aborts the whole listing (no per-source isolation); duplicate ids across sources overwrite the owner map; uploader display names are public (user-requested, no emails); the category wiring in app.js has no DOM tests. Verified: the new Drive zips contain `RGB_YYYY-MM-DD-HH_MM_SS-…` mp4s, the same format as before.
- Pending (user): add `DRIVE_SOURCES` to `.env.example` (the writer sandbox was denied); set the repo variable `DRIVE_SOURCES=1w_VFQjkn0ceieOcG3T2jiMEWGXWKZvgp,1z6UQzg5l7xgxqf3HTB5Ys2SJnrcU6PiN=Remaining`; push and merge feat/density-toggle and feat/categories.

## Phase 6: Mix category and fixed tab order (2026-09-30, user request)
The "Remaining" videos contain both black and white pipes, so the user renamed the category to "Mix". Tab order is fixed: Mix, Black pipes, White pipes, then any other category, newest first. The default tab is the first one.
Branch `feat/mix-category` from main.
- [x] T16 Rename "Remaining" → "Mix" in the ingest defaults (manifest DEFAULT_CATEGORY, the legacy DRIVE_FOLDER_ID label, uploaders), the site DEFAULT_CATEGORY, README, and tests. Rewrite the existing manifest entries from "Remaining" to "Mix". A stale stored tab ("Remaining") falls back to the default. Fixed tab order in the site (`CATEGORY_ORDER`). (delegated, writer trigger)
- Pending (user): change the repo variable DRIVE_SOURCES label `=Remaining` → `=Mix`.
- Progress: T16 done (commits 615d50a site tab order, 3a290e6 rename). RED: pytest 9 failed, node import failed (no CATEGORY_ORDER). GREEN: pytest 96 passed, node 41 passed, node --check ok, manifest 199 Mix / 11 Black / 10 White / 220, 0 Remaining.
- 2026-09-30: category "Mix" renamed to "Black/White pipes" (user request); first tab and default. TDD RED 7 py + 5 node fails → GREEN 96 + 43. A stale stored "Mix" falls back to the default. Repo variable label must become `=Black/White pipes`.

## Phase 7: per-day duration chart and summary (2026-09-30, user request)
The user wants the per-day bar chart to show video durations instead of start hours, and each day to show the summary details (the per-category table, but per day). Current data: durations are 4 s–334 s, median ~59 s.
Branch `feat/day-duration-summary` from main.
- [x] T17 Replace the per-day hour histogram with a duration histogram: 30 s buckets from 0 to 5 min plus a final "≥ 5 min" bucket, axis labels at 0, 1m, 2m, 3m, 4m, 5m+, and an accessible label/tooltip per bar ("1:00–1:30 · 12 videos"). Clicking a bar filters that day's videos to the bucket (this replaces the hour filter; any `hour` URL/query state migrates or is dropped cleanly). Add a per-day summary under the day heading, for the active category: videos, total duration, average, shortest–longest, and uploaders with counts. Pure logic in lib.js with tests; remove dead hour-histogram code. (delegated, writer trigger)

- Progress: T17 done in 53a950f (47/47 node tests, 96 pytest passed). Duration bar filter ANDs with the min/max slider; bars and summary cover all of the active category's videos for the day; old ?hour= is ignored.
- [x] T18 (user feedback on T17) Make the per-day summary larger and more prominent (stat chips, not small inline text). Make the duration chart clearer: per-bar count labels, bucket axis labels, taller bars, visible empty buckets, stronger contrast in both themes. Remove the "Recording HH:MM:SS" title from each video card; the card keeps an accessible name via aria-label. Use the freed space for larger chips (time, session, duration, uploader, pipeline). (delegated, writer trigger)

- Progress: T18 done in 4a0902c (bucketAxisLabel in lib.js, TDD RED import fail -> GREEN 49/49 node; stat cards, uploader pills, taller labelled bars with visible empty slots, card h3 removed with aria-label, larger chips).

## Phase 8: dated category folders (2026-10-01, user request)

New Drive subfolders "Black pipes 1 Oct" and "White pipes 1 Oct" showed up as their own tabs, because the subfolder name is used verbatim as the category. Those videos belong to "Black pipes" and "White pipes"; the day already comes from the recording name.

- [x] T19 Strip a trailing date from category names (`normalize_category` in ingest/manifest.py, applied in `Manifest.add` and `Manifest.from_dict`, so new uploads and existing entries both land in the base category). Rewrite the 20 existing manifest entries. (inline: one understood module plus its test)

- Progress: T19 TDD RED import error -> GREEN 99 pytest, 49 node. Manifest now: Black/White pipes 199, Black pipes 28, White pipes 12.
