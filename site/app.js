import {
  groupByDay,
  extractDriveId,
  drivePreviewUrl,
  parseRecordingName,
  formatDayLabel,
  relativeTime,
  isPipelineZip,
  posterUrl,
} from "./lib.js";

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

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/* ---------- Theme ---------- */
function initTheme() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const root = document.documentElement;
  const current = () => root.getAttribute("data-theme") || "dark";
  const paint = () => {
    const light = current() === "light";
    btn.textContent = light ? "\u{1F319}" : "☀️";
    btn.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
  };
  btn.addEventListener("click", () => {
    const next = current() === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem("theme", next);
    } catch (e) {
      /* storage unavailable: theme still applies for this visit */
    }
    paint();
  });
  paint();
}

/* ---------- Cards ---------- */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Render one video entry as a player card.
 * @param {{id: string, name: string, url: string, source_zip: string}} video
 * @returns {HTMLElement}
 */
export function renderVideo(video) {
  const parsed = parseRecordingName(video.name);
  const title = parsed ? parsed.title : video.name || "Untitled video";
  const driveId = extractDriveId(video.url);
  const player = driveId
    ? el("iframe", { src: drivePreviewUrl(driveId), allow: "autoplay", loading: "lazy", title })
    : el("video", {
        controls: true,
        preload: "none",
        playsInline: true,
        src: video.url,
        poster: posterUrl(video),
      });

  // Nothing is fetched until the viewer presses play, so many cards on one
  // page do not compete for connections (the MP4 index lives at the file end).
  const playOverlay = driveId
    ? null
    : el("button", { className: "play-overlay", type: "button", "aria-label": `Play ${title}` }, [
        el("span", { className: "play-icon", text: "▶" }),
      ]);
  if (playOverlay) {
    playOverlay.addEventListener("click", () => {
      playOverlay.remove();
      player.play().catch(() => {});
    });
    player.addEventListener("play", () => playOverlay.remove(), { once: true });
  }

  const chips = el("div", { className: "chips" });
  if (parsed) {
    chips.appendChild(el("span", { className: "chip", text: parsed.time }));
    chips.appendChild(el("span", { className: "chip", text: parsed.session }));
  }
  if (isPipelineZip(video.source_zip)) {
    chips.appendChild(el("span", { className: "chip pipeline", text: "pipeline" }));
  }

  const copyBtn = el("button", { type: "button", className: "action", text: "Copy link" });
  copyBtn.addEventListener("click", async () => {
    const ok = await copyText(video.url);
    copyBtn.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(() => (copyBtn.textContent = "Copy link"), 1800);
  });

  return el("article", { className: "video-card" }, [
    el("div", { className: "player" }, playOverlay ? [player, playOverlay] : [player]),
    el("div", { className: "video-meta" }, [
      el("h3", { className: "video-name", text: title }),
      chips,
      parsed ? el("span", { className: "hash", text: parsed.hash }) : null,
      el("p", { className: "video-source", text: `Source: ${video.source_zip || "unknown"}` }),
      el("div", { className: "actions" }, [
        el("a", { className: "action", href: video.url, download: video.name || "", text: "Download" }),
        copyBtn,
      ]),
    ]),
  ]);
}

/* ---------- Days ---------- */
function renderDay(dayGroup, expanded) {
  const videos = dayGroup.videos || [];
  const grid = el("div", { className: "video-grid", id: `grid-${dayGroup.day}` });
  let rendered = false;
  const section = el("section", { className: "day-section", id: `day-${dayGroup.day}` });
  section.dataset.day = dayGroup.day;

  const toggle = el("button", { type: "button", className: "toggle-btn" });
  toggle.setAttribute("aria-controls", grid.id);

  const setCollapsed = (collapsed) => {
    if (!collapsed && !rendered) {
      grid.replaceChildren(...videos.map(renderVideo));
      rendered = true;
    }
    section.dataset.collapsed = String(collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.textContent = collapsed ? `Show ${plural(videos.length, "video")}` : "Hide videos";
  };
  toggle.addEventListener("click", () => setCollapsed(section.dataset.collapsed !== "true"));
  section.expand = () => setCollapsed(false);

  section.append(
    el("div", { className: "day-head" }, [
      el("h2", { text: formatDayLabel(dayGroup.day) }),
      el("span", { className: "badge", text: plural(videos.length, "video") }),
      toggle,
    ]),
    grid
  );
  setCollapsed(!expanded);
  return section;
}

function renderNav(days, sections) {
  const nav = document.getElementById("day-nav");
  const list = document.getElementById("day-nav-list");
  if (!nav || !list) return;
  const buttons = new Map();

  for (const d of days) {
    const btn = el("button", { type: "button", className: "chip-btn" }, [
      el("span", { text: formatDayLabel(d.day).replace(/^\w+, /, "").replace(/ \d{4}$/, "") }),
      el("span", { className: "count", text: String((d.videos || []).length) }),
    ]);
    btn.addEventListener("click", () => {
      const section = sections.get(d.day);
      if (!section) return;
      section.expand();
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    list.appendChild(el("li", {}, [btn]));
    buttons.set(d.day, btn);
  }
  nav.hidden = false;

  const setCurrent = (day) => {
    for (const [key, btn] of buttons) {
      if (key === day) {
        btn.setAttribute("aria-current", "true");
        btn.scrollIntoView({ block: "nearest", inline: "nearest" });
      } else {
        btn.removeAttribute("aria-current");
      }
    }
  };
  setCurrent(days[0].day);

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length) setCurrent(visible[0].target.dataset.day);
      },
      { rootMargin: "-90px 0px -60% 0px" }
    );
    for (const section of sections.values()) observer.observe(section);
  }
}

/* ---------- Header stats ---------- */
function renderStats(manifest, days) {
  const total = days.reduce((n, d) => n + (d.videos || []).length, 0);
  document.getElementById("stat-days").textContent = String(days.length);
  document.getElementById("stat-videos").textContent = String(total);
  const when = new Date(manifest && manifest.generated_at);
  if (!Number.isNaN(when.getTime())) {
    document.getElementById("stat-updated").textContent = when.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    document.getElementById("stat-updated-rel").textContent = relativeTime(manifest.generated_at, new Date());
  }
}

/* ---------- States ---------- */
function renderEmpty() {
  return el("div", { className: "empty-state" }, [
    el("span", { className: "state-title", text: "No videos yet" }),
    el("span", { text: "The pipeline runs every 30 minutes, so check back soon." }),
  ]);
}

function renderError(message) {
  return el("div", { className: "error-state", role: "alert" }, [
    el("span", { className: "state-title", text: "Could not load videos" }),
    el("span", { text: message }),
  ]);
}

async function loadManifest() {
  const response = await fetch(MANIFEST_URL, { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`manifest request failed with status ${response.status}`);
  }
  return response.json();
}

async function main() {
  initTheme();
  const app = document.getElementById("app");
  if (!app) return;

  try {
    const manifest = await loadManifest();
    const days = groupByDay(manifest);
    app.replaceChildren();
    renderStats(manifest, days);

    if (days.length === 0) {
      app.appendChild(renderEmpty());
      return;
    }

    const sections = new Map();
    days.forEach((day, i) => {
      const section = renderDay(day, i === 0);
      sections.set(day.day, section);
      app.appendChild(section);
    });
    renderNav(days, sections);
  } catch (error) {
    app.replaceChildren();
    app.appendChild(renderError(error instanceof Error ? error.message : String(error)));
  }
}

main();
