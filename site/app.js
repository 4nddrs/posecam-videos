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
  videoAnchorId,
  deepLink,
  nextVisibleIndex,
  clampSpeed,
  SPEEDS,
  readDensity,
  writeDensity,
  rowData,
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

/* ---------- Playback state ---------- */
const store = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {
      /* storage unavailable: setting applies for this visit only */
    }
  },
};
const playback = { speed: clampSpeed(store.get("speed")), autoplay: store.get("autoplay") === "1", active: null };

const cardVideo = (card) => (card ? card.querySelector("video") : null);

function setActive(card) {
  if (playback.active && playback.active !== card) playback.active.classList.remove("is-active");
  playback.active = card;
  if (card) card.classList.add("is-active");
}

function paintSpeed() {
  for (const btn of document.querySelectorAll(".speed-btn")) {
    btn.setAttribute("aria-pressed", String(Number(btn.dataset.speed) === playback.speed));
  }
}

function setSpeed(value) {
  playback.speed = clampSpeed(value);
  store.set("speed", String(playback.speed));
  for (const v of document.querySelectorAll(".video-card video")) v.playbackRate = playback.speed;
  paintSpeed();
}

/** Items (cards, or list rows) of the day grid that holds `card`, in display order. */
const ITEM_SELECTOR = ":scope > .video-card, :scope > .video-row";
const itemOf = (card) => (card ? card.closest(".video-row") || card : null);
const siblingItems = (card) => {
  const grid = card ? card.closest(".video-grid") : null;
  return grid ? [...grid.querySelectorAll(ITEM_SELECTOR)] : [];
};
/** A list row mounts its card on demand; a card item is its own card. */
const cardOf = (item) => (item && item.classList.contains("video-row") ? item.mount() : item);
const isPlayable = (item) => (item.classList.contains("video-row") ? item.dataset.playable === "true" : Boolean(cardVideo(item)));

/** Move to the next/previous playable item in the same day and start it. */
function stepFrom(card, direction) {
  const items = siblingItems(card);
  const idx = nextVisibleIndex(items.map(isPlayable), items.indexOf(itemOf(card)), direction);
  if (idx === -1) return false;
  playCard(cardOf(items[idx]));
  return true;
}

function playCard(card) {
  const video = cardVideo(card);
  if (!video) return;
  setActive(card);
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  video.playbackRate = playback.speed;
  video.play().catch(() => {});
}

function initPlayback() {
  // `play`/`ended` do not bubble, so listen in the capture phase once.
  document.addEventListener(
    "play",
    (e) => {
      const video = e.target;
      if (!(video instanceof HTMLVideoElement)) return;
      for (const other of document.querySelectorAll(".video-card video")) {
        if (other !== video && !other.paused) other.pause();
      }
      video.playbackRate = playback.speed;
      setActive(video.closest(".video-card"));
    },
    true
  );
  document.addEventListener(
    "ended",
    (e) => {
      if (!playback.autoplay || !(e.target instanceof HTMLVideoElement)) return;
      stepFrom(e.target.closest(".video-card"), 1);
    },
    true
  );
  document.addEventListener("focusin", (e) => {
    const card = e.target instanceof Element ? e.target.closest(".video-card") : null;
    if (card) setActive(card);
  });

  const toggle = document.getElementById("autoplay-toggle");
  if (toggle) {
    const paint = () => toggle.setAttribute("aria-pressed", String(playback.autoplay));
    toggle.addEventListener("click", () => {
      playback.autoplay = !playback.autoplay;
      store.set("autoplay", playback.autoplay ? "1" : "0");
      paint();
    });
    paint();
  }

  const help = document.getElementById("shortcuts");
  const toggleHelp = (force) => {
    if (!help) return;
    help.hidden = typeof force === "boolean" ? !force : !help.hidden;
  };
  document.getElementById("shortcuts-close")?.addEventListener("click", () => toggleHelp(false));

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t instanceof Element && t.closest("input, textarea, select, [contenteditable='true']")) return;
    const card = playback.active && playback.active.isConnected ? playback.active : null;
    const video = cardVideo(card);
    switch (e.key) {
      case " ": {
        // Buttons, links and native controls already handle Space themselves.
        if (t instanceof Element && t.closest("button, a, video")) return;
        if (!video) return;
        e.preventDefault();
        if (video.paused) {
          video.playbackRate = playback.speed;
          video.play().catch(() => {});
        } else video.pause();
        break;
      }
      case "ArrowRight":
      case "ArrowLeft": {
        if (t instanceof Element && t.closest("video")) return; // native seeking
        e.preventDefault();
        const dir = e.key === "ArrowRight" ? 1 : -1;
        if (card) stepFrom(card, dir);
        else {
          const first = document.querySelector(".video-grid > .video-card, .video-grid > .video-row[data-playable='true']");
          if (first && dir === 1) playCard(cardOf(first));
        }
        break;
      }
      case "f":
      case "F": {
        if (!video) return;
        e.preventDefault();
        if (video.requestFullscreen) video.requestFullscreen().catch(() => {});
        else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
        break;
      }
      case "?":
        e.preventDefault();
        toggleHelp();
        break;
      case "Escape":
        toggleHelp(false);
        break;
      default:
    }
  });
}

/** Expand the day holding the linked card, scroll to it and mark it active (no autoplay). */
function openDeepLink(days, sections) {
  const id = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (!id.startsWith("v-")) return;
  const day = days.find((d) => (d.videos || []).some((v) => videoAnchorId(v) === id));
  if (!day) return;
  const section = sections.get(day.day);
  if (section) section.expand();
  const target = document.getElementById(id);
  if (!target) return;
  const card = cardOf(target);
  setActive(card);
  card.scrollIntoView({ block: "center" });
  card.focus({ preventScroll: true });
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

function copyLinkButton(video, className) {
  const btn = el("button", { type: "button", className, text: "Copy link" });
  btn.addEventListener("click", async () => {
    const ok = await copyText(deepLink(location.origin + location.pathname + location.search, video));
    btn.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(() => (btn.textContent = "Copy link"), 1800);
  });
  return btn;
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

  const copyBtn = copyLinkButton(video, "action");

  const speedGroup = el("div", { className: "speed-group", role: "group", "aria-label": "Playback speed" });
  for (const value of driveId ? [] : SPEEDS) {
    const btn = el("button", { type: "button", className: "speed-btn", text: `${value}×` });
    btn.dataset.speed = String(value);
    btn.setAttribute("aria-pressed", String(value === playback.speed));
    btn.addEventListener("click", () => setSpeed(value));
    speedGroup.appendChild(btn);
  }
  if (!driveId) player.playbackRate = playback.speed;

  return el("article", { className: "video-card", id: videoAnchorId(video), tabIndex: -1 }, [
    el("div", { className: "player" }, playOverlay ? [player, playOverlay] : [player]),
    el("div", { className: "video-meta" }, [
      el("h3", { className: "video-name", text: title }),
      chips,
      parsed ? el("span", { className: "hash", text: parsed.hash }) : null,
      el("p", { className: "video-source", text: `Source: ${video.source_zip || "unknown"}` }),
      driveId ? null : speedGroup,
      el("div", { className: "actions" }, [
        el("a", { className: "action", href: video.url, download: video.name || "", text: "Download" }),
        copyBtn,
      ]),
    ]),
  ]);
}

/**
 * Render one video entry as a compact list row. The full player card is
 * mounted under the row on demand and reuses `renderVideo`.
 * @param {object} video
 * @returns {HTMLElement}
 */
export function renderRow(video) {
  const data = rowData(video);
  const anchor = videoAnchorId(video);
  const row = el("article", { className: "video-row", id: anchor });
  row.dataset.playable = String(data.playable);
  const slot = el("div", { className: "row-player", hidden: true });
  let card = null;

  const playBtn = el("button", { type: "button", className: "action row-play", text: "▶ Play" });
  playBtn.setAttribute("aria-expanded", "false");
  playBtn.setAttribute("aria-label", `${data.playable ? "Play" : "Open"} ${data.name}`);
  const paint = () => {
    const open = !slot.hidden;
    playBtn.setAttribute("aria-expanded", String(open));
    playBtn.textContent = open ? "✕ Close" : data.playable ? "▶ Play" : "▶ Open";
  };

  row.mount = () => {
    if (!card) {
      card = renderVideo(video);
      card.removeAttribute("id"); // the row owns the deep-link anchor
      slot.appendChild(card);
    }
    slot.hidden = false;
    paint();
    return card;
  };
  const close = () => {
    const v = cardVideo(card);
    if (v) v.pause();
    if (playback.active === card) setActive(null);
    slot.hidden = true;
    paint();
  };
  playBtn.addEventListener("click", () => {
    if (!slot.hidden) return close();
    const mounted = row.mount();
    if (data.playable) playCard(mounted);
  });

  row.append(
    el("div", { className: "row-head" }, [
      el("span", { className: "row-time", text: data.time || "—" }),
      el("span", { className: "row-name", text: data.name }),
      el("span", { className: "row-duration", title: "Duration", text: data.duration }),
      playBtn,
      copyLinkButton(video, "action row-copy"),
    ]),
    slot
  );
  return row;
}

/* ---------- Layout density ---------- */
const storage = { getItem: (k) => store.get(k), setItem: (k, v) => store.set(k, v) };
const view = { mode: readDensity(storage) };

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
      grid.classList.toggle("is-list", view.mode === "list");
      grid.replaceChildren(...visible.map(view.mode === "list" ? renderRow : renderVideo));
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
    else {
      // The grid is stale until the next expand repaints it.
      rendered = false;
      toggle.textContent = `Show ${plural(visible.length, "video")}`;
    }
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
  const minValue = document.getElementById("filter-min-value");
  const maxValue = document.getElementById("filter-max-value");
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
    minValue.textContent = a === 0 ? "0 min" : `${a} min`;
    maxValue.textContent = b === top ? "Any" : `${b} min`;
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

function initDensity(sections) {
  const buttons = [...document.querySelectorAll(".density-btn")];
  const paint = () => {
    for (const btn of buttons) btn.setAttribute("aria-pressed", String(btn.dataset.mode === view.mode));
  };
  for (const btn of buttons) {
    btn.addEventListener("click", () => {
      if (btn.dataset.mode === view.mode) return;
      view.mode = btn.dataset.mode;
      writeDensity(storage, view.mode);
      paint();
      setActive(null);
      // refresh() repaints expanded days and marks collapsed ones stale.
      for (const section of sections.values()) section.refresh();
    });
  }
  paint();
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
  initPlayback();
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
      // Every day starts collapsed so the list of available days is visible
      // at a glance; a deep link still expands its own day.
      const section = renderDay(day, false, (d, n, t) => navCounts(d, n, t));
      sections.set(day.day, section);
      app.appendChild(section);
    });
    renderNav(days, sections);
    initToolbar(days, sections);
    initDensity(sections);
    openDeepLink(days, sections);
    window.addEventListener("hashchange", () => openDeepLink(days, sections));
  } catch (error) {
    app.replaceChildren();
    app.appendChild(renderError(error instanceof Error ? error.message : String(error)));
  }
}

main();
