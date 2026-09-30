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
 * newest day first, with each day's videos newest first. Recording names
 * start with their capture timestamp, so name order is time order.
 * Does not mutate the manifest.
 * @param {{generated_at?: string, days?: {day: string, videos: any[]}[]}} manifest
 * @returns {{day: string, videos: any[]}[]}
 */
export function groupByDay(manifest) {
  if (!manifest || typeof manifest !== "object") return [];
  return sortDaysDesc(manifest.days).map((day) => ({
    ...day,
    videos: [...(day.videos || [])].sort((a, b) =>
      a.name < b.name ? 1 : a.name > b.name ? -1 : 0
    ),
  }));
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

/**
 * Stable DOM id / URL fragment for a video: `v-<hash>` from the recording
 * name, else `v-<slug of name>`.
 * @param {{name?: string}|null|undefined} video
 * @returns {string}
 */
export function videoAnchorId(video) {
  // The manifest id is the storage key, unique across days and sessions;
  // the recording hash alone repeats for s1/s2 of the same capture.
  const id = video && typeof video.id === "string" && video.id ? video.id : "";
  const name = video && typeof video.name === "string" ? video.name : "";
  const source = id || name;
  const slug = source.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `v-${slug || "video"}`;
}

/**
 * Shareable link to a video card: the base URL without its fragment plus the anchor.
 * @param {string} baseUrl
 * @param {{name?: string}} video
 * @returns {string}
 */
export function deepLink(baseUrl, video) {
  const base = String(baseUrl ?? "").replace(/#.*$/, "");
  return `${base}#${videoAnchorId(video)}`;
}

/**
 * Index of the next (direction 1) or previous (-1) visible entry, no wrapping.
 * @param {boolean[]} list visibility flags
 * @param {number} current index to move from (may be -1)
 * @param {1|-1} direction
 * @returns {number} -1 when none
 */
export function nextVisibleIndex(list, current, direction) {
  if (!Array.isArray(list)) return -1;
  const step = direction < 0 ? -1 : 1;
  for (let i = current + step; i >= 0 && i < list.length; i += step) {
    if (list[i]) return i;
  }
  return -1;
}

export const SPEEDS = [1, 1.5, 2, 4];

/**
 * @param {unknown} value
 * @returns {number} an allowed playback speed, default 1
 */
export function clampSpeed(value) {
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return SPEEDS.includes(n) ? n : 1;
}

export const DENSITY_KEY = "density";

/**
 * Normalize a stored layout mode: "list" or "cards" (default).
 * @param {unknown} value
 * @returns {"cards"|"list"}
 */
export function parseDensity(value) {
  return value === "list" ? "list" : "cards";
}

/**
 * Read the persisted layout mode. Never throws; unavailable storage yields "cards".
 * @param {{getItem: (key: string) => string|null}|undefined} storage
 * @returns {"cards"|"list"}
 */
export function readDensity(storage) {
  try {
    return parseDensity(storage.getItem(DENSITY_KEY));
  } catch (e) {
    return "cards";
  }
}

/**
 * Persist the layout mode. Returns false (never throws) for an invalid mode or unavailable storage.
 * @param {{setItem: (key: string, value: string) => void}|undefined} storage
 * @param {string} mode
 * @returns {boolean}
 */
export function writeDensity(storage, mode) {
  if (mode !== "cards" && mode !== "list") return false;
  try {
    storage.setItem(DENSITY_KEY, mode);
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Display fields for a compact list row. `time` matches the card's time chip.
 * @param {{name?: string, url?: string, duration?: number|null}|null|undefined} video
 * @returns {{time: string, name: string, duration: string, playable: boolean}}
 */
export function rowData(video) {
  const v = video || {};
  const parsed = parseRecordingName(v.name);
  return {
    time: parsed ? parsed.time : "",
    name: v.name || "Untitled video",
    duration: formatDuration(v.duration),
    playable: !extractDriveId(v.url),
    uploader: uploaderOf(v),
  };
}

export const DEFAULT_CATEGORY = "Mix";
export const CATEGORY_KEY = "category";
/** Fixed leading tab order; any other category follows, newest first. */
export const CATEGORY_ORDER = ["Mix", "Black pipes", "White pipes"];

/**
 * Category of a video; entries without one belong to "Mix".
 * @param {{category?: unknown}|null|undefined} video
 * @returns {string}
 */
export function categoryOf(video) {
  const c = video && typeof video.category === "string" ? video.category.trim() : "";
  return c || DEFAULT_CATEGORY;
}

/**
 * Uploader display name, or "" when unknown (callers omit the label).
 * @param {{uploader?: unknown}|null|undefined} video
 * @returns {string}
 */
export function uploaderOf(video) {
  return video && typeof video.uploader === "string" ? video.uploader.trim() : "";
}

/**
 * Categories with video counts: those in CATEGORY_ORDER first, in that order,
 * then the rest by their newest video (day, then name, both descending; ties
 * by name). The first entry is the default tab.
 * @param {{day: string, videos?: any[]}[]|undefined} days
 * @returns {{name: string, count: number}[]}
 */
export function listCategories(days) {
  if (!Array.isArray(days)) return [];
  const found = new Map();
  for (const d of days) {
    for (const v of d.videos || []) {
      const name = categoryOf(v);
      const key = `${d.day}\u0000${v.name || ""}`;
      const entry = found.get(name) || { name, count: 0, newest: "" };
      entry.count += 1;
      if (key > entry.newest) entry.newest = key;
      found.set(name, entry);
    }
  }
  const rank = (name) => {
    const i = CATEGORY_ORDER.indexOf(name);
    return i < 0 ? CATEGORY_ORDER.length : i;
  };
  return [...found.values()]
    .sort((a, b) => {
      if (rank(a.name) !== rank(b.name)) return rank(a.name) - rank(b.name);
      return a.newest < b.newest ? 1 : a.newest > b.newest ? -1 : a.name < b.name ? -1 : 1;
    })
    .map(({ name, count }) => ({ name, count }));
}

/**
 * Day groups restricted to one category; days left empty are dropped.
 * Does not mutate the input.
 * @param {{day: string, videos?: any[]}[]|undefined} days
 * @param {string} category
 * @returns {{day: string, videos: any[]}[]}
 */
export function daysForCategory(days, category) {
  if (!Array.isArray(days)) return [];
  return days
    .map((d) => ({ ...d, videos: (d.videos || []).filter((v) => categoryOf(v) === category) }))
    .filter((d) => d.videos.length > 0);
}

/**
 * Category of the video whose anchor id (`v-...`) matches, or null.
 * @param {{videos?: any[]}[]|undefined} days
 * @param {string} anchorId
 * @returns {string|null}
 */
export function categoryOfVideoId(days, anchorId) {
  if (!anchorId || !Array.isArray(days)) return null;
  for (const d of days) {
    for (const v of d.videos || []) {
      if (videoAnchorId(v) === anchorId) return categoryOf(v);
    }
  }
  return null;
}

/**
 * Pick the active category: deep-linked video's category, else a stored
 * choice that still exists, else the first category (the default tab).
 * @param {{name: string}[]} categories
 * @param {{linked?: string|null, stored?: string|null}} [hints]
 * @returns {string|null}
 */
export function chooseCategory(categories, hints = {}) {
  const names = (categories || []).map((c) => c.name);
  if (hints.linked && names.includes(hints.linked)) return hints.linked;
  if (hints.stored && names.includes(hints.stored)) return hints.stored;
  return names.length ? names[0] : null;
}

/**
 * Read the persisted category choice. Never throws; null when unavailable.
 * @param {{getItem: (key: string) => string|null}|undefined} storage
 * @returns {string|null}
 */
export function readCategory(storage) {
  try {
    return storage.getItem(CATEGORY_KEY) || null;
  } catch (e) {
    return null;
  }
}

/**
 * Persist the category choice. Returns false (never throws) when it cannot.
 * @param {{setItem: (key: string, value: string) => void}|undefined} storage
 * @param {string} name
 * @returns {boolean}
 */
export function writeCategory(storage, name) {
  if (typeof name !== "string" || !name) return false;
  try {
    storage.setItem(CATEGORY_KEY, name);
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * New horizontal scroll offset for a chip bar so the given chip is visible,
 * or null when it already is. Only the bar scrolls; the page never moves
 * (Element.scrollIntoView would also scroll the page and fight the user).
 * @param {{left: number, right: number, width: number}} bar  bar client rect
 * @param {{left: number, right: number, width: number}} chip chip client rect
 * @param {number} scrollLeft current scrollLeft of the bar
 * @returns {number|null}
 */
export function chipScrollLeft(bar, chip, scrollLeft) {
  if (chip.left >= bar.left && chip.right <= bar.right) return null;
  const centred = chip.left - bar.left - (bar.width - chip.width) / 2;
  return Math.max(0, scrollLeft + centred);
}
