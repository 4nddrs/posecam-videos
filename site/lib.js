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
