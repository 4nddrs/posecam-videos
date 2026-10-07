import { test } from "node:test";
import assert from "node:assert/strict";
import {
  extractDriveId,
  sortDaysDesc,
  chipScrollLeft,
  groupByDay,
  parseRecordingName,
  formatDayLabel,
  relativeTime,
  isPipelineZip,
  posterUrl,
  sidecarLinks,
  sidecarFilename,
  durationBucket,
  durationHistogram,
  bucketAxisLabel,
  daySummary,
  formatTotalDuration,
  BUCKET_COUNT,
  matchesFilters,
  formatDuration,
  parseFilterQuery,
  filterQuery,
  videoAnchorId,
  deepLink,
  nextVisibleIndex,
  clampSpeed,
  DENSITY_KEY,
  parseDensity,
  readDensity,
  writeDensity,
  rowData,
  DEFAULT_CATEGORY,
  categoryOf,
  uploaderOf,
  listCategories,
  daysForCategory,
  categoryOfVideoId,
  chooseCategory,
  readCategory,
  writeCategory,
  CATEGORY_KEY,
  CATEGORY_ORDER,
} from "../lib.js";

test("extractDriveId extracts id from /d/<id> form", () => {
  const url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing";
  assert.equal(extractDriveId(url), "1AbCdEfGhIjKlMnOp");
});

test("extractDriveId extracts id from id=<id> form", () => {
  const url = "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp";
  assert.equal(extractDriveId(url), "1AbCdEfGhIjKlMnOp");
});

test("extractDriveId returns null for a non-Drive URL", () => {
  const url = "https://example.com/videos/clip.mp4";
  assert.equal(extractDriveId(url), null);
});

test("sortDaysDesc returns days sorted newest first", () => {
  const days = [
    { day: "2026-09-20", videos: [] },
    { day: "2026-09-28", videos: [] },
    { day: "2026-09-25", videos: [] },
  ];
  const sorted = sortDaysDesc(days);
  assert.deepEqual(
    sorted.map((d) => d.day),
    ["2026-09-28", "2026-09-25", "2026-09-20"]
  );
});

test("sortDaysDesc does not mutate the input array", () => {
  const days = [{ day: "2026-09-20", videos: [] }, { day: "2026-09-28", videos: [] }];
  const copy = [...days];
  sortDaysDesc(days);
  assert.deepEqual(days, copy);
});

test("sortDaysDesc handles an empty or missing list", () => {
  assert.deepEqual(sortDaysDesc([]), []);
  assert.deepEqual(sortDaysDesc(undefined), []);
});

test("groupByDay orders videos within each day newest first", () => {
  const manifest = {
    days: [
      {
        day: "2026-09-27",
        videos: [
          { name: "RGB_2026-09-27-10_43_11-aaaaaa-s1.mp4" },
          { name: "RGB_2026-09-27-14_47_45-bbbbbb-s2.mp4" },
          { name: "RGB_2026-09-27-12_00_00-cccccc-s1.mp4" },
        ],
      },
    ],
  };
  const [day] = groupByDay(manifest);
  assert.deepEqual(
    day.videos.map((v) => v.name),
    [
      "RGB_2026-09-27-14_47_45-bbbbbb-s2.mp4",
      "RGB_2026-09-27-12_00_00-cccccc-s1.mp4",
      "RGB_2026-09-27-10_43_11-aaaaaa-s1.mp4",
    ]
  );
  assert.equal(manifest.days[0].videos[0].name, "RGB_2026-09-27-10_43_11-aaaaaa-s1.mp4");
});

test("parseRecordingName parses a valid recording filename", () => {
  assert.deepEqual(parseRecordingName("RGB_2026-09-25-08_35_52-f74bef-s1.mp4"), {
    title: "Recording 08:35:52",
    time: "08:35:52",
    session: "s1",
    hash: "f74bef",
  });
});

test("parseRecordingName returns null for unknown patterns", () => {
  assert.equal(parseRecordingName("clip.mp4"), null);
  assert.equal(parseRecordingName(undefined), null);
});

test("formatDayLabel renders a human date", () => {
  assert.equal(formatDayLabel("2026-09-25"), "Fri, Sep 25 2026");
  assert.equal(formatDayLabel("garbage"), "garbage");
});

test("relativeTime covers minutes, hours and days", () => {
  const now = new Date("2026-09-28T12:00:00Z");
  assert.equal(relativeTime("2026-09-28T11:59:40Z", now), "just now");
  assert.equal(relativeTime("2026-09-28T11:55:00Z", now), "5 minutes ago");
  assert.equal(relativeTime("2026-09-28T11:00:00Z", now), "1 hour ago");
  assert.equal(relativeTime("2026-09-28T09:00:00Z", now), "3 hours ago");
  assert.equal(relativeTime("2026-09-26T12:00:00Z", now), "2 days ago");
  assert.equal(relativeTime("not a date", now), "");
});

test("isPipelineZip detects pipeline zips", () => {
  assert.equal(isPipelineZip("capture-20260925T140552-f74bef-pipeline.zip"), true);
  assert.equal(isPipelineZip("capture-20260925T140552-f74bef.zip"), false);
  assert.equal(isPipelineZip(undefined), false);
});

test("posterUrl returns the poster string when present", () => {
  assert.equal(posterUrl({ poster: "https://example.com/p.jpg" }), "https://example.com/p.jpg");
});

test("posterUrl returns null for null, missing, empty or non-string posters", () => {
  assert.equal(posterUrl({ poster: null }), null);
  assert.equal(posterUrl({}), null);
  assert.equal(posterUrl({ poster: "" }), null);
  assert.equal(posterUrl({ poster: 42 }), null);
  assert.equal(posterUrl(undefined), null);
});

test("sidecarLinks returns both sidecar URLs when present", () => {
  const v = { metadata: { txt: "https://cdn.example/a.txt", json: "https://cdn.example/a.json" } };
  assert.deepEqual(sidecarLinks(v), {
    txt: "https://cdn.example/a.txt",
    json: "https://cdn.example/a.json",
  });
});

test("sidecarLinks returns null for a missing sidecar", () => {
  assert.deepEqual(sidecarLinks({ metadata: { txt: "https://cdn.example/a.txt" } }), {
    txt: "https://cdn.example/a.txt",
    json: null,
  });
  assert.deepEqual(sidecarLinks({ metadata: { json: "https://cdn.example/a.json" } }), {
    txt: null,
    json: "https://cdn.example/a.json",
  });
});

test("sidecarLinks returns both null when metadata is absent", () => {
  assert.deepEqual(sidecarLinks({}), { txt: null, json: null });
  assert.deepEqual(sidecarLinks({ metadata: null }), { txt: null, json: null });
  assert.deepEqual(sidecarLinks(undefined), { txt: null, json: null });
});

test("sidecarLinks ignores empty and non-string values", () => {
  assert.deepEqual(sidecarLinks({ metadata: { txt: "", json: 42 } }), { txt: null, json: null });
});

test("sidecarFilename builds the download name from the video name stem", () => {
  assert.equal(sidecarFilename({ name: "clip.mp4" }, "txt"), "clip.txt");
  assert.equal(sidecarFilename({ name: "RGB_2026-09-25-08_35_52-f74bef-s1.mp4" }, "json"), "RGB_2026-09-25-08_35_52-f74bef-s1.json");
});

test("sidecarFilename appends the extension when the name has none", () => {
  assert.equal(sidecarFilename({ name: "clip" }, "txt"), "clip.txt");
});

test("sidecarFilename falls back to download.<ext> for a missing name", () => {
  assert.equal(sidecarFilename({}, "txt"), "download.txt");
  assert.equal(sidecarFilename(undefined, "json"), "download.json");
  assert.equal(sidecarFilename({ name: "" }, "txt"), "download.txt");
});

const rec = (h, m, duration) => ({
  name: `RGB_2026-09-25-${String(h).padStart(2, "0")}_${m}_00-abc123-s1.mp4`,
  duration,
});

test("durationBucket maps seconds to 30 s buckets with a final 5 min+ bucket", () => {
  assert.equal(BUCKET_COUNT, 11);
  assert.equal(durationBucket(0), 0);
  assert.equal(durationBucket(29.9), 0);
  assert.equal(durationBucket(30), 1);
  assert.equal(durationBucket(60), 2);
  assert.equal(durationBucket(299), 9);
  assert.equal(durationBucket(300), 10);
  assert.equal(durationBucket(9999), 10);
  assert.equal(durationBucket(null), null);
  assert.equal(durationBucket(undefined), null);
  assert.equal(durationBucket(-3), null);
  assert.equal(durationBucket(NaN), null);
});

test("durationHistogram counts per bucket and reports unknown durations", () => {
  const h = durationHistogram([rec(1, "00", 4), rec(1, "01", 20), rec(1, "02", 70), rec(1, "03", 334), rec(1, "04", null), { name: "x" }]);
  assert.equal(h.buckets.length, 11);
  assert.equal(h.buckets[0].count, 2);
  assert.equal(h.buckets[2].count, 1);
  assert.equal(h.buckets[10].count, 1);
  assert.equal(h.unknown, 2);
  assert.deepEqual([h.buckets[2].startSec, h.buckets[2].endSec], [60, 90]);
  assert.deepEqual([h.buckets[10].startSec, h.buckets[10].endSec], [300, null]);
  const empty = durationHistogram(undefined);
  assert.equal(empty.buckets.length, 11);
  assert.equal(empty.buckets.reduce((a, b) => a + b.count, 0), 0);
  assert.equal(empty.unknown, 0);
});

test("formatTotalDuration renders seconds, minutes and hours", () => {
  assert.equal(formatTotalDuration(45), "45 s");
  assert.equal(formatTotalDuration(0), "0 s");
  assert.equal(formatTotalDuration(23 * 60 + 10), "23 min");
  assert.equal(formatTotalDuration(3599), "1 h 0 min");
  assert.equal(formatTotalDuration(72 * 60), "1 h 12 min");
  assert.equal(formatTotalDuration(2 * 3600), "2 h 0 min");
  assert.equal(formatTotalDuration(null), "");
  assert.equal(formatTotalDuration(-1), "");
});

test("daySummary aggregates count, total, average, range and uploaders", () => {
  const vids = [
    { duration: 60, uploader: "Ann" },
    { duration: 120, uploader: "Bob" },
    { duration: 30, uploader: "Ann" },
    { duration: null, uploader: "" },
  ];
  const s = daySummary(vids);
  assert.equal(s.count, 4);
  assert.equal(s.unknown, 1);
  assert.equal(s.totalSec, 210);
  assert.equal(s.avgSec, 70);
  assert.equal(s.minSec, 30);
  assert.equal(s.maxSec, 120);
  assert.deepEqual(s.uploaders, [{ name: "Ann", count: 2 }, { name: "Bob", count: 1 }]);
});

test("daySummary tolerates empty and duration-less input", () => {
  const e = daySummary(undefined);
  assert.equal(e.count, 0);
  assert.equal(e.avgSec, null);
  assert.equal(e.minSec, null);
  assert.deepEqual(e.uploaders, []);
  const s = daySummary([{ name: "a" }]);
  assert.equal(s.count, 1);
  assert.equal(s.unknown, 1);
  assert.equal(s.totalSec, 0);
  assert.equal(s.avgSec, null);
});

test("matchesFilters applies duration range inclusively", () => {
  const v = rec(9, "00", 120);
  assert.equal(matchesFilters(v, { minSec: 60, maxSec: 600 }), true);
  assert.equal(matchesFilters(v, { minSec: 120, maxSec: 120 }), true);
  assert.equal(matchesFilters(v, { minSec: 121, maxSec: null }), false);
  assert.equal(matchesFilters(v, { minSec: null, maxSec: 119 }), false);
});

test("matchesFilters treats null duration as matching only when unfiltered", () => {
  const v = rec(9, "00", null);
  assert.equal(matchesFilters(v, { minSec: null, maxSec: null }), true);
  assert.equal(matchesFilters(v, { minSec: 0, maxSec: null }), false);
  assert.equal(matchesFilters(v, { minSec: null, maxSec: 600 }), false);
  assert.equal(matchesFilters({ name: v.name }, { minSec: null, maxSec: null }), true);
});

test("matchesFilters composes the duration bucket with the range (AND)", () => {
  const v = rec(14, "10", 70);
  assert.equal(matchesFilters(v, { bucket: 2 }), true);
  assert.equal(matchesFilters(v, { bucket: 3 }), false);
  assert.equal(matchesFilters(v, { minSec: 100, bucket: 2 }), false);
  assert.equal(matchesFilters(v, { minSec: 60, maxSec: 90, bucket: 2 }), true);
  assert.equal(matchesFilters(rec(14, "10", null), { bucket: 0 }), false);
  assert.equal(matchesFilters(rec(14, "10", 400), { bucket: 10 }), true);
  assert.equal(matchesFilters(v, { bucket: null }), true);
  assert.equal(matchesFilters(v, {}), true);
});

test("parseFilterQuery ignores the retired hour key", () => {
  assert.deepEqual(parseFilterQuery("?hour=14&min=1"), { minSec: 60, maxSec: null });
  assert.equal(filterQuery({ minSec: null, maxSec: null, hour: 14 }), "");
});

test("formatDuration renders m:ss and h:mm:ss", () => {
  assert.equal(formatDuration(293), "4:53");
  assert.equal(formatDuration(5), "0:05");
  assert.equal(formatDuration(3723), "1:02:03");
  assert.equal(formatDuration(292.6), "4:53");
  assert.equal(formatDuration(null), "");
  assert.equal(formatDuration(-1), "");
});

test("parseFilterQuery reads min/max minutes as seconds", () => {
  assert.deepEqual(parseFilterQuery("?min=2&max=10"), { minSec: 120, maxSec: 600 });
  assert.deepEqual(parseFilterQuery("?min=2"), { minSec: 120, maxSec: null });
  assert.deepEqual(parseFilterQuery(""), { minSec: null, maxSec: null });
  assert.deepEqual(parseFilterQuery("?min=abc&max=-3"), { minSec: null, maxSec: null });
});

test("filterQuery serializes minutes and omits unset bounds", () => {
  assert.equal(filterQuery({ minSec: 120, maxSec: 600 }), "?min=2&max=10");
  assert.equal(filterQuery({ minSec: null, maxSec: 90 }), "?max=1.5");
  assert.equal(filterQuery({ minSec: null, maxSec: null }), "");
});

test("videoAnchorId is unique per manifest id, falling back to the name", () => {
  assert.equal(
    videoAnchorId({ id: "2026-09-25/RGB_2026-09-25-14_03_22-a1B2c3-s1.mp4", name: "RGB_2026-09-25-14_03_22-a1B2c3-s1.mp4" }),
    "v-2026-09-25-rgb-2026-09-25-14-03-22-a1b2c3-s1-mp4",
  );
  assert.notEqual(
    videoAnchorId({ id: "d/RGB_2026-09-25-14_03_22-a1B2c3-s1.mp4" }),
    videoAnchorId({ id: "d/RGB_2026-09-25-14_03_22-a1B2c3-s2.mp4" }),
  );
  assert.equal(videoAnchorId({ name: "My Clip (final).mp4" }), "v-my-clip-final-mp4");
  assert.equal(videoAnchorId({}), "v-video");
  assert.equal(videoAnchorId(null), "v-video");
});

test("deepLink appends the anchor and drops any existing hash", () => {
  const v = { id: "d/clip-1.mp4", name: "clip-1.mp4" };
  assert.equal(deepLink("https://x.io/site/?min=2", v), "https://x.io/site/?min=2#v-d-clip-1-mp4");
  assert.equal(deepLink("https://x.io/site/#v-old", v), "https://x.io/site/#v-d-clip-1-mp4");
});

test("nextVisibleIndex finds the next/previous visible entry without wrapping", () => {
  const list = [true, false, true, false, true];
  assert.equal(nextVisibleIndex(list, 0, 1), 2);
  assert.equal(nextVisibleIndex(list, 2, 1), 4);
  assert.equal(nextVisibleIndex(list, 4, 1), -1);
  assert.equal(nextVisibleIndex(list, 4, -1), 2);
  assert.equal(nextVisibleIndex(list, 0, -1), -1);
  assert.equal(nextVisibleIndex([false, false], 0, 1), -1);
  assert.equal(nextVisibleIndex([], 0, 1), -1);
  assert.equal(nextVisibleIndex(list, -1, 1), 0);
});

test("clampSpeed accepts only the allowed set, default 1", () => {
  assert.equal(clampSpeed(2), 2);
  assert.equal(clampSpeed("1.5"), 1.5);
  assert.equal(clampSpeed(4), 4);
  assert.equal(clampSpeed(3), 1);
  assert.equal(clampSpeed(null), 1);
  assert.equal(clampSpeed("abc"), 1);
});

test("parseDensity accepts only cards or list, default cards", () => {
  assert.equal(parseDensity("list"), "list");
  assert.equal(parseDensity("cards"), "cards");
  assert.equal(parseDensity("grid"), "cards");
  assert.equal(parseDensity(null), "cards");
  assert.equal(parseDensity(undefined), "cards");
});

test("readDensity reads the stored mode and falls back to cards", () => {
  assert.equal(readDensity({ getItem: (k) => (k === DENSITY_KEY ? "list" : null) }), "list");
  assert.equal(readDensity({ getItem: () => null }), "cards");
  assert.equal(readDensity({ getItem: () => "bogus" }), "cards");
  assert.equal(readDensity(undefined), "cards");
});

test("readDensity survives a storage that throws", () => {
  assert.equal(readDensity({ getItem: () => { throw new Error("denied"); } }), "cards");
});

test("writeDensity stores a valid mode and reports failure without throwing", () => {
  const data = {};
  const ok = { setItem: (k, v) => { data[k] = v; } };
  assert.equal(writeDensity(ok, "list"), true);
  assert.equal(data[DENSITY_KEY], "list");
  assert.equal(writeDensity(ok, "bogus"), false);
  assert.equal(data[DENSITY_KEY], "list");
  assert.equal(writeDensity({ setItem: () => { throw new Error("full"); } }, "list"), false);
  assert.equal(writeDensity(undefined, "list"), false);
});

test("rowData exposes the time, name and duration shown in list rows", () => {
  const v = { id: "d/x.mp4", name: "RGB_2026-09-25-08_35_52-f74bef-s1.mp4", url: "https://cdn.example/x.mp4", duration: 293 };
  assert.deepEqual(rowData(v), {
    time: "08:35:52",
    name: "RGB_2026-09-25-08_35_52-f74bef-s1.mp4",
    duration: "4:53",
    playable: true,
    uploader: "",
  });
});

test("rowData tolerates unparsed names, missing duration and Drive-only urls", () => {
  assert.deepEqual(rowData({ name: "clip.mp4", url: "https://cdn.example/clip.mp4" }), {
    time: "",
    name: "clip.mp4",
    duration: "",
    playable: true,
    uploader: "",
  });
  const drive = rowData({ url: "https://drive.google.com/file/d/abc123/view" });
  assert.equal(drive.name, "Untitled video");
  assert.equal(drive.playable, false);
  assert.equal(rowData(null).name, "Untitled video");
});

const catManifest = () => ({
  days: [
    {
      day: "2026-09-30",
      videos: [
        { id: "d30/a", name: "b-1.mp4", category: "White Pipes", uploader: "Ann" },
        { id: "d30/b", name: "b-2.mp4", category: "Black Pipes" },
      ],
    },
    {
      day: "2026-09-28",
      videos: [
        { id: "d28/a", name: "r-1.mp4", category: "Black/White Pipes", uploader: "Zed" },
        { id: "d28/b", name: "r-2.mp4" },
      ],
    },
  ],
});

test("categoryOf falls back to Black/White Pipes and uploaderOf omits blanks", () => {
  assert.equal(DEFAULT_CATEGORY, "Black/White Pipes");
  assert.equal(categoryOf({ category: "White Pipes" }), "White Pipes");
  assert.equal(categoryOf({}), "Black/White Pipes");
  assert.equal(categoryOf({ category: "  " }), "Black/White Pipes");
  assert.equal(categoryOf(null), "Black/White Pipes");
  assert.equal(uploaderOf({ uploader: " Ann " }), "Ann");
  assert.equal(uploaderOf({ uploader: null }), "");
  assert.equal(uploaderOf({}), "");
  assert.equal(uploaderOf(undefined), "");
});

test("listCategories counts videos, fixed order first, uncategorized counts as Black/White Pipes", () => {
  assert.deepEqual(listCategories(catManifest().days), [
    { name: "Black/White Pipes", count: 2 },
    { name: "Black Pipes", count: 1 },
    { name: "White Pipes", count: 1 },
  ]);
  assert.deepEqual(listCategories(undefined), []);
});

test("listCategories puts known categories in CATEGORY_ORDER, then others newest first", () => {
  assert.deepEqual(CATEGORY_ORDER, ["Black/White Pipes", "Black Pipes", "White Pipes"]);
  const days = [
    { day: "2026-09-30", videos: [{ name: "a", category: "Extra" }, { name: "b", category: "White Pipes" }] },
    { day: "2026-09-29", videos: [{ name: "c", category: "Old" }, { name: "d", category: "Black Pipes" }] },
    { day: "2026-09-28", videos: [{ name: "e" }] },
  ];
  assert.deepEqual(listCategories(days).map((c) => c.name), ["Black/White Pipes", "Black Pipes", "White Pipes", "Extra", "Old"]);
  assert.deepEqual(listCategories([days[0]]).map((c) => c.name), ["White Pipes", "Extra"]);
});

test("listCategories ties on newest video break by name and recency uses day then name", () => {
  const days = [
    { day: "2026-09-30", videos: [{ name: "a", category: "B" }, { name: "z", category: "A" }] },
    { day: "2026-09-29", videos: [{ name: "q", category: "C" }] },
  ];
  assert.deepEqual(listCategories(days).map((c) => c.name), ["A", "B", "C"]);
});

test("daysForCategory keeps only that category's videos and drops empty days", () => {
  const days = catManifest().days;
  const mix = daysForCategory(days, "Black/White Pipes");
  assert.deepEqual(mix.map((d) => d.day), ["2026-09-28"]);
  assert.deepEqual(mix[0].videos.map((v) => v.id), ["d28/a", "d28/b"]);
  const white = daysForCategory(days, "White Pipes");
  assert.deepEqual(white.map((d) => [d.day, d.videos.length]), [["2026-09-30", 1]]);
  assert.deepEqual(daysForCategory(days, "Nope"), []);
  assert.equal(days[0].videos.length, 2);
});

test("categoryOfVideoId maps a v- anchor to its category", () => {
  const days = catManifest().days;
  assert.equal(categoryOfVideoId(days, videoAnchorId({ id: "d30/b" })), "Black Pipes");
  assert.equal(categoryOfVideoId(days, videoAnchorId({ id: "d28/b" })), "Black/White Pipes");
  assert.equal(categoryOfVideoId(days, "v-missing"), null);
  assert.equal(categoryOfVideoId(days, ""), null);
});

test("chooseCategory prefers a deep link, then a stored known choice, then the first category", () => {
  const cats = [{ name: "Black/White Pipes" }, { name: "White Pipes" }];
  assert.equal(chooseCategory(cats, { linked: "Black/White Pipes", stored: "White Pipes" }), "Black/White Pipes");
  assert.equal(chooseCategory(cats, { linked: null, stored: "Black/White Pipes" }), "Black/White Pipes");
  assert.equal(chooseCategory(cats, { linked: null, stored: "Gone" }), "Black/White Pipes");
  assert.equal(chooseCategory(cats, { linked: null, stored: "Remaining" }), "Black/White Pipes");
  assert.equal(chooseCategory(cats, { linked: null, stored: "Mix" }), "Black/White Pipes");
  assert.equal(chooseCategory(cats, {}), "Black/White Pipes");
  assert.equal(chooseCategory([], {}), null);
});

test("readCategory and writeCategory never throw", () => {
  assert.equal(readCategory({ getItem: (k) => (k === CATEGORY_KEY ? "White Pipes" : null) }), "White Pipes");
  assert.equal(readCategory({ getItem: () => null }), null);
  assert.equal(readCategory({ getItem: () => { throw new Error("denied"); } }), null);
  assert.equal(readCategory(undefined), null);
  const data = {};
  assert.equal(writeCategory({ setItem: (k, v) => { data[k] = v; } }, "Black Pipes"), true);
  assert.equal(data[CATEGORY_KEY], "Black Pipes");
  assert.equal(writeCategory({ setItem: () => { throw new Error("full"); } }, "x"), false);
  assert.equal(writeCategory(undefined, "x"), false);
  assert.equal(writeCategory({ setItem: () => {} }, ""), false);
});

test("rowData includes the uploader, empty when unknown", () => {
  assert.equal(rowData({ name: "x.mp4", url: "https://cdn.example/x.mp4", uploader: "Ann" }).uploader, "Ann");
  assert.equal(rowData({ name: "x.mp4", url: "https://cdn.example/x.mp4" }).uploader, "");
});

test("chipScrollLeft keeps the chip bar still when the chip is fully visible", () => {
  const bar = { left: 0, right: 300, width: 300 };
  assert.equal(chipScrollLeft(bar, { left: 100, right: 160, width: 60 }, 40), null);
});

test("chipScrollLeft centres a chip that is cut off on either side", () => {
  const bar = { left: 0, right: 300, width: 300 };
  // Chip past the right edge: move it to the centre (left at 120).
  assert.equal(chipScrollLeft(bar, { left: 280, right: 340, width: 60 }, 40), 200);
  // Chip before the left edge, never scrolls below 0.
  assert.equal(chipScrollLeft(bar, { left: -30, right: 30, width: 60 }, 20), 0);
});

test("bucketAxisLabel gives a short label for every bucket", () => {
  const labels = durationHistogram([]).buckets.map(bucketAxisLabel);
  assert.equal(labels.length, BUCKET_COUNT);
  assert.deepEqual(labels.slice(0, 3), ["0:00", "0:30", "1:00"]);
  assert.equal(labels[BUCKET_COUNT - 1], "5:00+");
});

test("bucketAxisLabel gives a short label for every bucket", () => {
  const labels = durationHistogram([]).buckets.map(bucketAxisLabel);
  assert.equal(labels.length, BUCKET_COUNT);
  assert.deepEqual(labels.slice(0, 3), ["0:00", "0:30", "1:00"]);
  assert.equal(labels[BUCKET_COUNT - 1], "5:00+");
});
