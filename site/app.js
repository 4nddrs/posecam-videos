import { groupByDay, extractDriveId, drivePreviewUrl } from "./lib.js";

const MANIFEST_URL = "./manifest.json";

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "text") {
      node.textContent = value;
    } else if (key in node) {
      node[key] = value;
    } else {
      node.setAttribute(key, value);
    }
  }
  for (const child of children) {
    if (child) node.appendChild(child);
  }
  return node;
}

/**
 * Render one video entry as a player card, including its name and source zip.
 * @param {{id: string, name: string, url: string, source_zip: string}} video
 * @returns {HTMLElement}
 */
export function renderVideo(video) {
  const driveId = extractDriveId(video.url);
  const player = driveId
    ? el("iframe", {
        src: drivePreviewUrl(driveId),
        allow: "autoplay",
        loading: "lazy",
        title: video.name || "Video",
      })
    : el("video", {
        controls: true,
        preload: "metadata",
        src: video.url,
      });

  return el("article", { className: "video-card" }, [
    player,
    el("div", { className: "video-meta" }, [
      el("div", { className: "video-name", text: video.name || "Untitled video" }),
      el("div", { className: "video-source", text: `Source: ${video.source_zip || "unknown"}` }),
    ]),
  ]);
}

/**
 * Render one day section, with its videos in a collapsible details block.
 * @param {{day: string, videos: any[]}} dayGroup
 * @returns {HTMLElement}
 */
function renderDay(dayGroup) {
  const grid = el(
    "div",
    { className: "video-grid" },
    (dayGroup.videos || []).map(renderVideo)
  );

  const summary = el("summary", {}, [el("h2", { text: dayGroup.day })]);

  return el("details", { className: "day-section", open: true }, [summary, grid]);
}

function renderEmpty() {
  return el("p", { className: "empty-state", text: "No videos have been published yet." });
}

function renderError(message) {
  return el("p", { className: "error-state", text: `Could not load videos: ${message}` });
}

async function loadManifest() {
  const response = await fetch(MANIFEST_URL);
  if (!response.ok) {
    throw new Error(`manifest request failed with status ${response.status}`);
  }
  return response.json();
}

async function main() {
  const app = document.getElementById("app");
  if (!app) return;

  try {
    const manifest = await loadManifest();
    const days = groupByDay(manifest);
    app.replaceChildren();

    if (days.length === 0) {
      app.appendChild(renderEmpty());
      return;
    }

    for (const day of days) {
      app.appendChild(renderDay(day));
    }
  } catch (error) {
    app.replaceChildren();
    app.appendChild(renderError(error instanceof Error ? error.message : String(error)));
  }
}

main();
