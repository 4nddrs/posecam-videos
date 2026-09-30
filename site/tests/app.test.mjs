import { test } from "node:test";
import assert from "node:assert/strict";
import {
  extractDriveId,
  sortDaysDesc,
  parseRecordingName,
  formatDayLabel,
  relativeTime,
  isPipelineZip,
  posterUrl,
  hourOf,
  histogram,
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

const rec = (h, m, duration) => ({
  name: `RGB_2026-09-25-${String(h).padStart(2, "0")}_${m}_00-abc123-s1.mp4`,
  duration,
});

test("hourOf returns the start hour or null", () => {
  assert.equal(hourOf(rec(8, "35")), 8);
  assert.equal(hourOf(rec(23, "01")), 23);
  assert.equal(hourOf({ name: "clip.mp4" }), null);
  assert.equal(hourOf(undefined), null);
});

test("histogram returns 24 counts by start hour", () => {
  const h = histogram([rec(0, "01"), rec(14, "05"), rec(14, "40"), { name: "x" }]);
  assert.equal(h.length, 24);
  assert.equal(h[0], 1);
  assert.equal(h[14], 2);
  assert.equal(h.reduce((a, b) => a + b, 0), 3);
  assert.deepEqual(histogram(undefined), new Array(24).fill(0));
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

test("matchesFilters composes hour with duration", () => {
  const v = rec(14, "10", 300);
  assert.equal(matchesFilters(v, { minSec: null, maxSec: null, hour: 14 }), true);
  assert.equal(matchesFilters(v, { minSec: null, maxSec: null, hour: 13 }), false);
  assert.equal(matchesFilters(v, { minSec: 600, maxSec: null, hour: 14 }), false);
  assert.equal(matchesFilters(v, {}), true);
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
  });
});

test("rowData tolerates unparsed names, missing duration and Drive-only urls", () => {
  assert.deepEqual(rowData({ name: "clip.mp4", url: "https://cdn.example/clip.mp4" }), {
    time: "",
    name: "clip.mp4",
    duration: "",
    playable: true,
  });
  const drive = rowData({ url: "https://drive.google.com/file/d/abc123/view" });
  assert.equal(drive.name, "Untitled video");
  assert.equal(drive.playable, false);
  assert.equal(rowData(null).name, "Untitled video");
});
