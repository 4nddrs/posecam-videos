// Pure helpers for the video gallery site. No DOM dependency so they can be
// unit tested with the Node built-in test runner.

/**
 * Extract a Google Drive file id from a Drive URL.
 * Supports the `/d/<id>` path form and the `?id=<id>` query form.
 * Returns null when no id can be found.
 * @param {string} url
 * @returns {string|null}
 */
export function extractDriveId(url) {
  if (typeof url !== "string") return null;
  const pathMatch = url.match(/\/d\/([a-zA-Z0-9_-]+)/);
  if (pathMatch) return pathMatch[1];
  const queryMatch = url.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  if (queryMatch) return queryMatch[1];
  return null;
}

/**
 * Return a new array of day groups sorted by `day` descending (newest first).
 * Defensive: does not mutate the input and tolerates a missing/undefined list.
 * @param {{day: string, videos: any[]}[]|undefined} days
 * @returns {{day: string, videos: any[]}[]}
 */
export function sortDaysDesc(days) {
  if (!Array.isArray(days)) return [];
  return [...days].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
}

/**
 * Group (already-grouped) manifest data by day, defensively re-sorted
 * newest day first.
 * @param {{generated_at?: string, days?: {day: string, videos: any[]}[]}} manifest
 * @returns {{day: string, videos: any[]}[]}
 */
export function groupByDay(manifest) {
  if (!manifest || typeof manifest !== "object") return [];
  return sortDaysDesc(manifest.days);
}

/**
 * Build the embeddable Drive preview URL for a file id.
 * @param {string} id
 * @returns {string}
 */
export function drivePreviewUrl(id) {
  return `https://drive.google.com/file/d/${id}/preview`;
}

const RECORDING_RE = /^RGB_\d{4}-\d{2}-\d{2}-(\d{2})_(\d{2})_(\d{2})-([A-Za-z0-9]+)-(s\d+)\.mp4$/;

/**
 * Parse `RGB_YYYY-MM-DD-HH_MM_SS-<hash>-s<N>.mp4` into display parts.
 * @param {string} name
 * @returns {{title: string, time: string, session: string, hash: string}|null}
 */
export function parseRecordingName(name) {
  if (typeof name !== "string") return null;
  const m = name.match(RECORDING_RE);
  if (!m) return null;
  const time = `${m[1]}:${m[2]}:${m[3]}`;
  return { title: `Recording ${time}`, time, session: m[5], hash: m[4] };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Format `YYYY-MM-DD` as "Fri, Sep 25 2026". Returns the input when invalid.
 * @param {string} isoDay
 * @returns {string}
 */
export function formatDayLabel(isoDay) {
  const m = typeof isoDay === "string" && isoDay.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return String(isoDay ?? "");
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  if (Number.isNaN(d.getTime())) return isoDay;
  return `${WEEKDAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()} ${d.getUTCFullYear()}`;
}

/**
 * Relative time such as "5 minutes ago". Empty string for invalid input.
 * @param {string} isoTimestamp
 * @param {Date} [now]
 * @returns {string}
 */
export function relativeTime(isoTimestamp, now = new Date()) {
  const t = new Date(isoTimestamp).getTime();
  if (Number.isNaN(t)) return "";
  const secs = Math.max(0, Math.floor((now.getTime() - t) / 1000));
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;
  if (secs < 60) return "just now";
  if (secs < 3600) return plural(Math.floor(secs / 60), "minute");
  if (secs < 86400) return plural(Math.floor(secs / 3600), "hour");
  return plural(Math.floor(secs / 86400), "day");
}

/**
 * @param {string} sourceZip
 * @returns {boolean}
 */
export function isPipelineZip(sourceZip) {
  return typeof sourceZip === "string" && sourceZip.includes("-pipeline");
}

/**
 * Poster image URL for a video entry, or null when absent/empty/non-string.
 * @param {{poster?: unknown}|undefined|null} video
 * @returns {string|null}
 */
export function posterUrl(video) {
  const poster = video && video.poster;
  return typeof poster === "string" && poster !== "" ? poster : null;
}

/**
 * Start hour (0-23) of a recording, parsed from its file name; null if unknown.
 * @param {{name?: string}|undefined|null} video
 * @returns {number|null}
 */
export function hourOf(video) {
  const parsed = parseRecordingName(video && video.name);
  return parsed ? Number(parsed.time.slice(0, 2)) : null;
}

/**
 * Count recordings per start hour.
 * @param {any[]|undefined} videos
 * @returns {number[]} 24 counts, index = hour
 */
export function histogram(videos) {
  const counts = new Array(24).fill(0);
  if (!Array.isArray(videos)) return counts;
  for (const v of videos) {
    const h = hourOf(v);
    if (h !== null && h >= 0 && h < 24) counts[h] += 1;
  }
  return counts;
}

const isNum = (n) => typeof n === "number" && Number.isFinite(n);

/**
 * Duration + hour filter. A video with unknown duration only matches when no
 * duration bound is set.
 * @param {{name?: string, duration?: number|null}} video
 * @param {{minSec?: number|null, maxSec?: number|null, hour?: number|null}} filters
 * @returns {boolean}
 */
export function matchesFilters(video, filters = {}) {
  const { minSec = null, maxSec = null, hour = null } = filters || {};
  if (isNum(hour) && hourOf(video) !== hour) return false;
  if (minSec === null && maxSec === null) return true;
  const d = video && video.duration;
  if (!isNum(d)) return false;
  if (isNum(minSec) && d < minSec) return false;
  if (isNum(maxSec) && d > maxSec) return false;
  return true;
}

/**
 * "4:53" or "1:02:03"; empty string for missing/invalid input.
 * @param {number|null|undefined} seconds
 * @returns {string}
 */
export function formatDuration(seconds) {
  if (!isNum(seconds) || seconds < 0) return "";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/**
 * Parse `?min=<minutes>&max=<minutes>` into second bounds (null when unset/invalid).
 * @param {string} search
 * @returns {{minSec: number|null, maxSec: number|null}}
 */
export function parseFilterQuery(search) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  const read = (key) => {
    const raw = params.get(key);
    if (raw === null || raw.trim() === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n * 60 : null;
  };
  return { minSec: read("min"), maxSec: read("max") };
}

/**
 * Inverse of parseFilterQuery; "" when no bound is set.
 * @param {{minSec?: number|null, maxSec?: number|null}} filters
 * @returns {string}
 */
export function filterQuery(filters = {}) {
  const params = new URLSearchParams();
  if (isNum(filters.minSec)) params.set("min", String(filters.minSec / 60));
  if (isNum(filters.maxSec)) params.set("max", String(filters.maxSec / 60));
  const q = params.toString();
  return q ? `?${q}` : "";
}
