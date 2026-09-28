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
