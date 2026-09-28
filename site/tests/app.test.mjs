import { test } from "node:test";
import assert from "node:assert/strict";
import { extractDriveId, sortDaysDesc } from "../lib.js";

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
