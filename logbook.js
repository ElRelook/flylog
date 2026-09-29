"use strict";
/* Logbook view: a whole folder of flights (e.g. Documents\Syride), all on one map.
 * Uses the helpers of index.html ($, state, pythonReady, nf, duration, …). */

const lb = {
  flights: {},   // id -> { entry, track }  (persisted in IndexedDB)
  files: {},     // id -> () => Promise<File>  (only for this session)
  handle: null,  // FileSystemDirectoryHandle, remembered between visits (Chrome / Edge)
  source: "",
  syncedAt: null,
  version: null,
  sort: { key: "date", dir: -1 },
  selected: new Set(), // flights ticked for comparison
  map: null,
  layer: null,
  tracks: {},    // id -> Leaflet polyline
};
const canPickDirectory = "showDirectoryPicker" in window;
const TRACK_STYLE = { color: "#e8590c", weight: 2.5, opacity: 0.75 };
const TRACK_HOVER = { color: "#1d4ed8", weight: 5, opacity: 1 };

/* ---------- Small helpers ---------- */

const idb = (() => {
  let db;
  const open = () => (db ??= new Promise((resolve, reject) => {
    const req = indexedDB.open("flylog", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("kv");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  }));
  const run = async (mode, fn) => {
    const store = (await open()).transaction("kv", mode).objectStore("kv");
    return new Promise((resolve, reject) => {
      const req = fn(store);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  };
  // Storage can be unavailable (private window, blocked site data): never break the page.
  return {
    get: (k) => run("readonly", (s) => s.get(k)).catch(() => undefined),
    set: (k, v) => run("readwrite", (s) => s.put(v, k)).catch(() => {}),
    del: (k) => run("readwrite", (s) => s.delete(k)).catch(() => {}),
  };
})();

const hm = (s) => {
  const total = Math.round(s / 60);
  return `${Math.floor(total / 60)}h${String(total % 60).padStart(2, "0")}`;
};
const flightDate = (e) => new Date(e.takeoff_time + "Z"); // IGC times are UTC
const fmtDate = (e) => flightDate(e).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
const fmtTime = (e) => flightDate(e).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
const entries = () => Object.values(lb.flights).map((f) => f.entry);

function distKm(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * r) / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

async function sha1(buffer) {
  // Same id as the Python logbook (sha1 of the file, 16 hex chars).
  const digest = await crypto.subtle.digest("SHA-1", buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

function lbStatus(text, kind = "") {
  $("lb-status").className = kind;
  $("lb-status").textContent = text;
}

function showView(name) {
  $("hero").hidden = name !== "hero";
  $("results").hidden = name !== "results";
  $("logbook").hidden = name !== "logbook";
  $("compare").hidden = name !== "compare";
  $("new-flight").hidden = name === "hero";
  $("to-logbook").hidden = !((name === "results" || name === "compare") && Object.keys(lb.flights).length);
  window.scrollTo(0, 0);
}

/* ---------- Finding .igc files ---------- */

async function fromHandle(dir, prefix = "", out = []) {
  for await (const [name, handle] of dir.entries()) {
    if (handle.kind === "directory") await fromHandle(handle, `${prefix}${name}/`, out);
    else if (/\.igc$/i.test(name)) out.push({ path: prefix + name, getFile: () => handle.getFile() });
  }
  return out;
}

async function fromEntry(entry, prefix, out) {
  if (entry.isFile) {
    if (/\.igc$/i.test(entry.name)) {
      out.push({ path: prefix + entry.name, getFile: () => new Promise((ok, ko) => entry.file(ok, ko)) });
    }
    return;
  }
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise((ok, ko) => reader.readEntries(ok, ko));
    if (!batch.length) break;
    for (const child of batch) await fromEntry(child, `${prefix}${entry.name}/`, out);
  }
}

const fromFileList = (files) => [...files]
  .filter((f) => /\.igc$/i.test(f.name))
  .map((f) => ({ path: f.webkitRelativePath || f.name, getFile: async () => f }));

/* ---------- Connect & sync ---------- */

async function rememberHandle(handle) {
  lb.handle = handle;
  await idb.set("dirHandle", handle);
}

async function connectFolder() {
  if (!canPickDirectory) return $("dir").click(); // Firefox / Safari: plain folder input
  let handle;
  try {
    handle = await window.showDirectoryPicker({ id: "flylog-syride", mode: "read", startIn: "documents" });
  } catch {
    return; // picker cancelled
  }
  await rememberHandle(handle);
  await syncFrom(await fromHandle(handle), handle.name);
}

async function resync() {
  if (!lb.handle) return connectFolder();
  try {
    const opts = { mode: "read" };
    if ((await lb.handle.queryPermission(opts)) !== "granted" &&
        (await lb.handle.requestPermission(opts)) !== "granted") {
      lbStatus("Accès au dossier refusé : clique sur « Synchroniser » et autorise la lecture.", "error");
      return;
    }
    await syncFrom(await fromHandle(lb.handle), lb.handle.name);
  } catch {
    lbStatus("Le dossier n'est plus accessible (déplacé ou supprimé ?) : choisis-le à nouveau.", "error");
    await idb.del("dirHandle");
    lb.handle = null;
  }
}

async function syncFrom(sources, sourceName) {
  showView("logbook");
  lbStatus("");
  $("lb-progress").hidden = false;
  $("lb-bar").style.width = "0";
  $("lb-progress-text").textContent = "Chargement de Python…";

  let py;
  try {
    py = await pythonReady;
  } catch (e) {
    $("lb-progress").hidden = true;
    lbStatus(e.message, "error");
    return;
  }
  if (lb.version !== py.version) lb.flights = {}; // the analysis changed: recompute everything
  lb.version = py.version;

  let added = 0;
  const errors = [];
  for (let i = 0; i < sources.length; i++) {
    const src = sources[i];
    $("lb-bar").style.width = `${(i / sources.length) * 100}%`;
    $("lb-progress-text").textContent = `Vol ${i + 1} / ${sources.length} · ${src.path}`;
    try {
      const buffer = await (await src.getFile()).arrayBuffer();
      const id = await sha1(buffer);
      lb.files[id] = src.getFile;
      if (lb.flights[id]) continue;
      await new Promise((r) => setTimeout(r, 0)); // let the progress bar paint
      lb.flights[id] = JSON.parse(py.logbookEntry(new TextDecoder().decode(buffer), id, src.path));
      added++;
    } catch {
      errors.push(src.path);
    }
  }

  lb.source = sourceName;
  lb.syncedAt = new Date().toISOString();
  await idb.set("logbook", { version: lb.version, source: lb.source, syncedAt: lb.syncedAt, flights: lb.flights });
  $("lb-progress").hidden = true;

  const known = sources.length - added - errors.length;
  lbStatus(sources.length
    ? `${added} nouveau${added > 1 ? "x" : ""} vol${added > 1 ? "s" : ""}, ${known} déjà dans le carnet` +
      (errors.length ? `, ${errors.length} fichier(s) illisible(s)` : "") + "."
    : "Aucun fichier .igc trouvé dans ce dossier.");
  renderLogbook();
}

async function openFlight(id) {
  if (!lb.files[id]) {
    // Carnet restored from a previous visit: we need the folder again to read the track.
    if (!lb.handle) {
      lbStatus("Pour ouvrir ce vol, resélectionne ton dossier de vols.", "error");
      return connectFolder();
    }
    await resync();
    if (!lb.files[id]) return;
  }
  try {
    await analyzeText(await (await lb.files[id]()).text());
  } catch {
    lbStatus("Impossible de lire ce fichier : il a peut-être été déplacé. Synchronise à nouveau.", "error");
  }
}

function onDrop(e) {
  const items = [...(e.dataTransfer?.items || [])];
  const entriesDropped = items.map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
  if (!entriesDropped.length || (entriesDropped.length === 1 && entriesDropped[0].isFile)) {
    return readFile(e.dataTransfer.files[0]);
  }
  // Must be requested synchronously, during the drop event.
  const handlePromise = entriesDropped.length === 1 && items[0].getAsFileSystemHandle
    ? items[0].getAsFileSystemHandle() : null;

  (async () => {
    const handle = await handlePromise?.catch(() => null);
    if (handle?.kind === "directory") {
      await rememberHandle(handle);
      return syncFrom(await fromHandle(handle), handle.name);
    }
    const sources = [];
    for (const entry of entriesDropped) await fromEntry(entry, "", sources);
    syncFrom(sources, entriesDropped.length === 1 ? entriesDropped[0].name : "fichiers déposés");
  })();
}

/* ---------- Rendering ---------- */

function renderLogbook() {
  const list = entries();
  updateResume();
  const synced = lb.syncedAt
    ? new Date(lb.syncedAt).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" }) : "";
  $("lb-meta").textContent = [lb.source && `Dossier « ${lb.source} »`, synced && `synchronisé le ${synced}`]
    .filter(Boolean).join(" · ");
  $("lb-count").textContent = `${list.length} vol${list.length > 1 ? "s" : ""}`;
  renderLbCards(list);
  renderLbMap();
  renderMonthChart(list);
  renderLbTable(list);
  renderLogbookExtras(list); // logbook-extras.js
}

function takeoffSites(list) {
  const sites = [];
  for (const e of list) {
    const site = sites.find((s) => distKm(s.lat, s.lon, e.takeoff_lat, e.takeoff_lon) < 1);
    if (site) site.n++;
    else sites.push({ lat: e.takeoff_lat, lon: e.takeoff_lon, alt: e.takeoff_alt, n: 1 });
  }
  return sites;
}

function renderLbCards(list) {
  if (!list.length) { $("lb-cards").innerHTML = ""; return; }
  const sum = (k) => list.reduce((a, e) => a + e[k], 0);
  const maxBy = (k) => list.reduce((a, e) => (e[k] > a[k] ? e : a));
  const first = list.reduce((a, e) => (e.takeoff_time < a.takeoff_time ? e : a));
  const [alt, longest, farthest, thermal] = ["max_alt", "duration_s", "distance_km", "best_thermal_m"].map(maxBy);
  const sites = takeoffSites(list).length;

  const cards = [
    ["Vols", nf(list.length), `depuis le ${fmtDate(first)}`],
    ["Heures de vol", duration(sum("duration_s")), `${hm(sum("duration_s") / list.length)} en moyenne`],
    ["Distance totale", `${nf(sum("distance_km"))}<small>km</small>`, `${sites} site${sites > 1 ? "s" : ""} de déco`],
    ["Gain cumulé", `${nf(sum("gain_m"))}<small>m</small>`, `${nf(sum("thermals"))} thermiques`],
    ["Plafond record", `${nf(alt.max_alt)}<small>m</small>`, `le ${fmtDate(alt)}`],
    ["Plus long vol", duration(longest.duration_s), `le ${fmtDate(longest)}`],
    ["Plus grande distance", `${nf(farthest.distance_km, 1)}<small>km</small>`, `le ${fmtDate(farthest)}`],
    ["Meilleur thermique", `+${nf(thermal.best_thermal_m)}<small>m</small>`, `le ${fmtDate(thermal)}`],
  ];
  $("lb-cards").innerHTML = cards.map(([l, v, sub]) =>
    `<div class="card"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`).join("");
}

function renderLbMap() {
  if (!lb.map) {
    const esri = (s) => `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`;
    const topo = L.tileLayer(esri("World_Topo_Map"), { attribution: "Tiles © Esri", maxZoom: 19 });
    const sat = L.tileLayer(esri("World_Imagery"), { attribution: "Tiles © Esri", maxZoom: 19 });
    // An initial view matters: Leaflet only re-measures its container once it has one.
    lb.map = L.map("lb-map", { preferCanvas: true, layers: [topo], center: [45.3, 5.9], zoom: 9 });
    lb.layersControl = L.control.layers({ "Topo": topo, "Satellite": sat }, null, { position: "topright" }).addTo(lb.map);
  }
  if (lb.layer) lb.layer.remove();
  lb.layer = L.layerGroup().addTo(lb.map);
  lb.tracks = {};

  const flights = Object.values(lb.flights);
  if (!flights.length) { lb.bounds = null; return; }

  const bounds = L.latLngBounds([]);
  for (const { entry: e, track } of flights) {
    const line = L.polyline(track, TRACK_STYLE)
      .bindTooltip(`<b>${fmtDate(e)}</b> · ${hm(e.duration_s)} · ${nf(e.distance_km, 1)} km · plafond ${nf(e.max_alt)} m`, { sticky: true })
      .on("mouseover", () => highlight(e.id, true))
      .on("mouseout", () => highlight(e.id, false))
      .on("click", () => openFlight(e.id))
      .addTo(lb.layer);
    lb.tracks[e.id] = line;
    bounds.extend(line.getBounds());
  }
  for (const s of takeoffSites(flights.map((f) => f.entry))) {
    const icon = L.divIcon({ className: "", html: `<div class="site-pin">${s.n}</div>`, iconSize: [22, 22] });
    L.marker([s.lat, s.lon], { icon })
      .bindTooltip(`Déco · ${s.n} vol${s.n > 1 ? "s" : ""} · ${nf(s.alt)} m`)
      .addTo(lb.layer);
  }
  lb.bounds = bounds;
  fitLbMap();
}

// Fit once the map really has a size (it may be laid out after rendering).
function fitLbMap() {
  if (!$("lb-map").clientWidth || !lb.bounds?.isValid()) { lb.needsFit = true; return; }
  lb.map.invalidateSize();
  lb.map.fitBounds(lb.bounds, { padding: [24, 24] });
  lb.needsFit = false;
}
const lbResize = new ResizeObserver(() => {
  if (lb.map && lb.needsFit) fitLbMap();
  if (lb.needsChart) renderMonthChart(entries());
});
lbResize.observe($("lb-map"));
lbResize.observe($("month-chart"));

function highlight(id, on) {
  const line = lb.tracks[id];
  if (line) {
    line.setStyle(on ? TRACK_HOVER : TRACK_STYLE);
    if (on) line.bringToFront();
  }
  document.querySelector(`#lb-table tr[data-id="${id}"]`)?.classList.toggle("hover", on);
}

function renderMonthChart(list) {
  const svg = $("month-chart");
  if (!list.length || $("logbook").hidden) { svg.innerHTML = ""; return; }

  const monthKey = (d) => d.getFullYear() * 12 + d.getMonth();
  const keys = list.map((e) => monthKey(flightDate(e)));
  const k0 = Math.min(...keys), k1 = Math.max(...keys, monthKey(new Date()));
  const months = Array.from({ length: k1 - k0 + 1 }, (_, i) => ({ k: k0 + i, hours: 0, n: 0 }));
  list.forEach((e, i) => { const m = months[keys[i] - k0]; m.hours += e.duration_s / 3600; m.n++; });

  const W = svg.clientWidth, H = svg.clientHeight;
  const pad = { l: 38, r: 6, t: 10, b: 38 };
  if (W <= pad.l + pad.r) { lb.needsChart = true; return; } // not laid out yet
  lb.needsChart = false;
  const step = niceStep(Math.max(...months.map((m) => m.hours), 1) / 4);
  const top = Math.ceil(Math.max(...months.map((m) => m.hours), 1) / step) * step;
  const band = (W - pad.l - pad.r) / months.length;
  const bw = Math.max(2, Math.min(28, band - 4)); // >= 2px gap between bars
  const y = (h) => pad.t + (1 - h / top) * (H - pad.t - pad.b);
  const base = y(0);

  let out = "";
  for (let v = 0; v <= top + 1e-9; v += step) {
    out += `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}"/>` +
      `<text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${nf(v)} h</text>`;
  }
  months.forEach((m, i) => {
    const cx = pad.l + band * (i + 0.5);
    const year = Math.floor(m.k / 12), month = m.k % 12;
    const date = new Date(year, month, 1);
    let bar = "";
    if (m.hours > 0) {
      const top = y(m.hours), x = cx - bw / 2, r = Math.min(4, bw / 2, base - top);
      bar = `<path class="bar" d="M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${base}Z"/>`;
    }
    const label = band >= 30 ? date.toLocaleDateString("fr-FR", { month: "short" }).replace(".", "")
      : date.toLocaleDateString("fr-FR", { month: "narrow" });
    const showLabel = band >= 14 || month % 3 === 0;
    out += `<g class="col" data-i="${i}">` +
      `<rect class="hit" x="${cx - band / 2}" y="${pad.t}" width="${band}" height="${base - pad.t}"/>${bar}` +
      (showLabel ? `<text x="${cx}" y="${base + 14}" text-anchor="middle">${label}</text>` : "") +
      (month === 0 || i === 0 ? `<text class="year" x="${cx}" y="${base + 30}" text-anchor="middle">${year}</text>` : "") +
      `</g>`;
  });
  svg.innerHTML = out;

  const tip = $("month-tip");
  svg.querySelectorAll(".col").forEach((g) => {
    g.addEventListener("mouseenter", () => {
      const m = months[+g.dataset.i];
      const name = new Date(Math.floor(m.k / 12), m.k % 12, 1).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
      tip.innerHTML = `<b>${name}</b> · ${m.n ? `${m.n} vol${m.n > 1 ? "s" : ""} · ${hm(m.hours * 3600)}` : "aucun vol"}`;
      tip.style.left = `${12 + pad.l + band * (+g.dataset.i + 0.5)}px`;
      tip.style.top = `${12 + (m.hours ? y(m.hours) : base) - 6}px`;
      tip.hidden = false;
    });
    g.addEventListener("mouseleave", () => { tip.hidden = true; });
  });
}

const COLUMNS = [
  ["date", "Date", (e) => e.takeoff_time, fmtDate],
  ["time", "Déco", (e) => fmtTime(e), fmtTime],
  ["duration", "Durée", (e) => e.duration_s, (e) => hm(e.duration_s)],
  ["distance", "Distance", (e) => e.distance_km, (e) => `${nf(e.distance_km, 1)} km`],
  ["alt", "Plafond", (e) => e.max_alt, (e) => `${nf(e.max_alt)} m`],
  ["gain", "Gain", (e) => e.gain_m, (e) => `${nf(e.gain_m)} m`],
  ["thermals", "Thermiques", (e) => e.thermals, (e) => nf(e.thermals)],
  ["best", "Meilleur therm.", (e) => e.best_thermal_m, (e) => (e.best_thermal_m ? `+${nf(e.best_thermal_m)} m` : "–")],
  ["score", "Score", (e) => e.score_points || 0, (e) => (e.score_points ? `${nf(e.score_points, 1)} pts` : "–")],
];

function renderLbTable(list) {
  const [, , sortValue] = COLUMNS.find(([k]) => k === lb.sort.key);
  const rows = [...list].sort((a, b) => {
    const va = sortValue(a), vb = sortValue(b);
    return (va < vb ? -1 : va > vb ? 1 : 0) * lb.sort.dir;
  });
  const arrow = lb.sort.dir > 0 ? "↑" : "↓";
  $("lb-table").innerHTML =
    `<thead><tr><th class="check"></th>${COLUMNS.map(([k, label]) =>
      `<th data-key="${k}" class="${k === lb.sort.key ? "sorted" : ""}">${label}${k === lb.sort.key ? " " + arrow : ""}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((e) =>
      `<tr data-id="${e.id}"><td class="check"><input type="checkbox" aria-label="Comparer ce vol" ${lb.selected.has(e.id) ? "checked" : ""}></td>` +
      `${COLUMNS.map(([, , , fmt]) => `<td>${fmt(e)}</td>`).join("")}</tr>`).join("")}</tbody>`;

  $("lb-table").querySelectorAll("th[data-key]").forEach((th) => th.addEventListener("click", () => {
    const key = th.dataset.key;
    lb.sort = { key, dir: lb.sort.key === key ? -lb.sort.dir : -1 };
    renderLbTable(entries());
  }));
  $("lb-table").querySelectorAll("tbody tr").forEach((tr) => {
    const box = tr.querySelector("input[type=checkbox]");
    box.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (box.checked) lb.selected.add(tr.dataset.id); else lb.selected.delete(tr.dataset.id);
      // Keep at most two: untick the oldest choice.
      while (lb.selected.size > 2) lb.selected.delete(lb.selected.values().next().value);
      renderLbTable(entries());
    });
    tr.addEventListener("click", () => openFlight(tr.dataset.id));
    tr.addEventListener("mouseenter", () => highlight(tr.dataset.id, true));
    tr.addEventListener("mouseleave", () => highlight(tr.dataset.id, false));
  });
  updateCompareButton();
}

function updateCompareButton() {
  const n = lb.selected.size;
  $("compare-btn").disabled = n !== 2;
  $("compare-btn").textContent = n === 2 ? "Comparer les 2 vols" : `Comparer (${n}/2)`;
}

function updateResume() {
  const n = Object.keys(lb.flights).length;
  $("resume").hidden = !n;
  $("resume").innerHTML = `Mon carnet <span class="count">${n} vol${n > 1 ? "s" : ""}</span>`;
}

/* ---------- Events ---------- */

$("connect").onclick = connectFolder;
$("dir").onchange = (e) => {
  const files = e.target.files;
  const name = (files[0]?.webkitRelativePath || "").split("/")[0] || "dossier";
  const sources = fromFileList(files);
  e.target.value = "";
  syncFrom(sources, name);
};
$("resume").onclick = () => { showView("logbook"); lbStatus(""); renderLogbook(); };
$("to-logbook").onclick = () => {
  showView("logbook");
  if (lb.map) fitLbMap();
  renderMonthChart(entries());
};
$("lb-sync").onclick = resync;
$("lb-change").onclick = connectFolder;
$("lb-forget").onclick = async () => {
  if (!confirm("Supprimer le carnet enregistré dans ce navigateur ?\nTes fichiers .igc ne sont pas touchés.")) return;
  await idb.del("logbook");
  await idb.del("dirHandle");
  Object.assign(lb, { flights: {}, files: {}, handle: null, source: "", syncedAt: null });
  updateResume();
  showView("hero");
};
window.addEventListener("resize", () => renderMonthChart(entries()));

// Restore the logbook saved during a previous visit.
(async () => {
  const saved = await idb.get("logbook");
  if (saved?.flights) Object.assign(lb, saved);
  lb.handle = (await idb.get("dirHandle")) || null;
  updateResume();
})();
