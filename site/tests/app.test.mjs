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
