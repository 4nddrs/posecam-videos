import {
  groupByDay,
  extractDriveId,
  drivePreviewUrl,
  parseRecordingName,
  formatDayLabel,
  relativeTime,
  isPipelineZip,
  posterUrl,
  histogram,
  matchesFilters,
  formatDuration,
  parseFilterQuery,
  filterQuery,
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
  const durationText = formatDuration(video.duration);
  if (durationText) {
    chips.appendChild(el("span", { className: "chip duration", title: "Duration", text: `⏱ ${durationText}` }));
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
const filters = { minSec: null, maxSec: null };

function renderHistogram(videos, state, onChange) {
  const counts = histogram(videos);
  const peak = Math.max(1, ...counts);
  const wrap = el("div", { className: "hour-hist", role: "group", "aria-label": "Recordings by start hour" });
  const bars = counts.map((n, h) => {
    const hh = String(h).padStart(2, "0");
    const next = String((h + 1) % 24).padStart(2, "0");
    const btn = el("button", {
      type: "button",
      className: "hour-bar",
      title: `${hh}:00–${next}:00, ${plural(n, "recording")}`,
      "aria-label": `${hh}:00, ${plural(n, "recording")}`,
      disabled: n === 0,
    });
    btn.setAttribute("aria-pressed", "false");
    btn.appendChild(el("span", { className: "hour-fill" }));
    btn.firstChild.style.height = n ? `${Math.max(12, Math.round((n / peak) * 100))}%` : "2px";
    btn.appendChild(el("span", { className: "hour-label", text: h % 6 === 0 ? hh : "" }));
    btn.addEventListener("click", () => {
      state.hour = state.hour === h ? null : h;
      onChange();
    });
    return btn;
  });
  const clear = el("button", { type: "button", className: "hour-clear", text: "×", title: "Clear hour filter", hidden: true });
  clear.setAttribute("aria-label", "Clear hour filter");
  clear.addEventListener("click", () => {
    state.hour = null;
    onChange();
  });
  wrap.append(...bars, clear);
  wrap.sync = () => {
    bars.forEach((b, h) => b.setAttribute("aria-pressed", String(state.hour === h)));
    clear.hidden = state.hour === null;
  };
  return wrap;
}

function renderDay(dayGroup, expanded, onCount) {
  const videos = dayGroup.videos || [];
  const state = { hour: null };
  const grid = el("div", { className: "video-grid", id: `grid-${dayGroup.day}` });
  const empty = el("div", { className: "empty-state filter-empty", hidden: true }, [
    el("span", { className: "state-title", text: "No recordings match" }),
    el("span", { text: "Try widening the duration range or clearing the hour filter." }),
  ]);
  let rendered = false;
  let visible = videos;
  const section = el("section", { className: "day-section", id: `day-${dayGroup.day}` });
  section.dataset.day = dayGroup.day;

  const toggle = el("button", { type: "button", className: "toggle-btn" });
  toggle.setAttribute("aria-controls", grid.id);
  const badge = el("span", { className: "badge" });

  const paint = () => {
    const collapsed = section.dataset.collapsed === "true";
    if (!collapsed) {
      grid.replaceChildren(...visible.map(renderVideo));
      rendered = true;
    }
    empty.hidden = collapsed || visible.length > 0;
    toggle.textContent = collapsed ? `Show ${plural(visible.length, "video")}` : "Hide videos";
  };

  const hist = renderHistogram(videos, state, () => section.refresh());

  section.refresh = () => {
    visible = videos.filter((v) => matchesFilters(v, { ...filters, hour: state.hour }));
    const text =
      visible.length === videos.length ? plural(videos.length, "video") : `${visible.length} of ${videos.length}`;
    badge.textContent = text;
    hist.sync();
    onCount(dayGroup.day, visible.length, videos.length);
    if (section.dataset.collapsed !== "true") paint();
    else toggle.textContent = `Show ${plural(visible.length, "video")}`;
  };

  const setCollapsed = (collapsed) => {
    section.dataset.collapsed = String(collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    if (!collapsed && rendered) {
      empty.hidden = visible.length > 0;
      toggle.textContent = "Hide videos";
    } else paint();
  };
  toggle.addEventListener("click", () => setCollapsed(section.dataset.collapsed !== "true"));
  section.expand = () => setCollapsed(false);

  section.append(
    el("div", { className: "day-head" }, [
      el("h2", { text: formatDayLabel(dayGroup.day) }),
      badge,
      toggle,
    ]),
    hist,
    grid,
    empty
  );
  section.dataset.collapsed = String(!expanded);
  toggle.setAttribute("aria-expanded", String(expanded));
  section.refresh();
  return section;
}

/* ---------- Duration filter toolbar ---------- */
function initToolbar(days, sections) {
  const bar = document.getElementById("filter-bar");
  if (!bar) return;
  const maxDur = Math.max(0, ...days.flatMap((d) => (d.videos || []).map((v) => (Number.isFinite(v.duration) ? v.duration : 0))));
  const top = Math.max(1, Math.ceil(maxDur / 60));
  const lo = document.getElementById("filter-min");
  const hi = document.getElementById("filter-max");
  const readout = document.getElementById("filter-readout");
  const reset = document.getElementById("filter-reset");
  for (const input of [lo, hi]) {
    input.min = "0";
    input.max = String(top);
    input.step = "1";
  }
  const clamp = (n) => Math.min(top, Math.max(0, Math.round(n)));
  const initial = parseFilterQuery(location.search);
  lo.value = String(initial.minSec === null ? 0 : clamp(initial.minSec / 60));
  hi.value = String(initial.maxSec === null ? top : clamp(initial.maxSec / 60));

  const apply = (changed) => {
    let a = Number(lo.value);
    let b = Number(hi.value);
    if (a > b) {
      if (changed === lo) { b = a; hi.value = String(b); } else { a = b; lo.value = String(a); }
    }
    filters.minSec = a === 0 ? null : a * 60;
    filters.maxSec = b === top ? null : b * 60;
    const any = filters.minSec === null && filters.maxSec === null;
    readout.textContent = any ? "Any duration" : `${a} min – ${b === top ? `${top}+ min` : `${b} min`}`;
    reset.disabled = any;
    const q = filterQuery(filters);
    try {
      history.replaceState(null, "", `${location.pathname}${q}${location.hash}`);
    } catch (e) {
      /* history unavailable: filter still applies */
    }
    for (const section of sections.values()) section.refresh();
  };
  lo.addEventListener("input", () => apply(lo));
  hi.addEventListener("input", () => apply(hi));
  reset.addEventListener("click", () => {
    lo.value = "0";
    hi.value = String(top);
    apply(null);
  });
  bar.hidden = false;
  apply(null);
}

let navCounts = () => {};

function renderNav(days, sections) {
  const counts = new Map();
  const nav = document.getElementById("day-nav");
  const list = document.getElementById("day-nav-list");
  if (!nav || !list) return;
  const buttons = new Map();

  for (const d of days) {
    const btn = el("button", { type: "button", className: "chip-btn" }, [
      el("span", { text: formatDayLabel(d.day).replace(/^\w+, /, "").replace(/ \d{4}$/, "") }),
      el("span", { className: "count", text: String((d.videos || []).length) }),
    ]);
    counts.set(d.day, btn.lastChild);
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
  navCounts = (day, shown, total) => {
    const node = counts.get(day);
    if (node) node.textContent = shown === total ? String(total) : `${shown} of ${total}`;
  };
  for (const [day, section] of sections) section.refresh();

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
      const section = renderDay(day, i === 0, (d, n, t) => navCounts(d, n, t));
      sections.set(day.day, section);
      app.appendChild(section);
    });
    renderNav(days, sections);
    initToolbar(days, sections);
  } catch (error) {
    app.replaceChildren();
    app.appendChild(renderError(error instanceof Error ? error.message : String(error)));
  }
}

main();
