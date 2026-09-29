"use strict";
/* Logbook extras: yearly goal, badges, progression charts, thermal hotspots map
 * and side-by-side comparison of two flights. Uses index.html and logbook.js helpers. */

const HOTSPOT_COLORS = ["#fed7aa", "#fdba74", "#fb923c", "#ea580c", "#9a3412"]; // one hue, light → dark
const HOTSPOT_STEPS = [0.8, 1.3, 1.8, 2.5]; // m/s
const CMP_COLORS = ["#e8590c", "#1d4ed8"];

function renderLogbookExtras(list) {
  renderGoal(list);
  renderBadges(list);
  renderProgress(list);
  renderHotspots();
}

/* ---------- Yearly goal ---------- */

function goalHours() {
  try { return +localStorage.getItem("flylog-goal") || 50; } catch { return 50; }
}

function renderGoal(list) {
  const year = new Date().getFullYear();
  const flights = list.filter((e) => flightDate(e).getFullYear() === year);
  const seconds = flights.reduce((a, e) => a + e.duration_s, 0);
  const goal = goalHours();
  const pct = Math.min(100, (seconds / 3600 / goal) * 100);
  $("goal-year").textContent = year;
  $("goal-hours").value = goal;
  $("goal-value").innerHTML = `${hm(seconds)} <small>/ ${nf(goal)} h · ${flights.length} vol${flights.length > 1 ? "s" : ""}</small>`;
  $("goal-bar").style.width = `${pct}%`;
  const left = goal * 3600 - seconds;
  const avg = list.length ? list.reduce((a, e) => a + e.duration_s, 0) / list.length : 0;
  $("goal-hint").textContent = left <= 0
    ? "Objectif atteint 🎉 Tu peux viser plus haut !"
    : `Encore ${hm(left)}` + (avg ? `, soit environ ${Math.ceil(left / avg)} vols de ${hm(avg)} (ta moyenne).` : ".");
}

$("goal-hours").addEventListener("change", (e) => {
  const v = Math.max(1, Math.min(999, Math.round(+e.target.value) || 50));
  try { localStorage.setItem("flylog-goal", v); } catch { /* storage unavailable */ }
  renderGoal(entries());
});

/* ---------- Badges ---------- */

const BADGES = [
  ["🪂", "Premier vol", "ton tout premier vol enregistré", (c) => c.flights >= 1],
  ["🔟", "10 vols", "dix vols au compteur", (c) => c.flights >= 10],
  ["🎯", "50 vols", "cinquante vols", (c) => c.flights >= 50],
  ["⏱️", "10 heures", "10 h de vol cumulées", (c) => c.hours >= 10],
  ["🕐", "50 heures", "50 h de vol cumulées", (c) => c.hours >= 50],
  ["🏅", "100 heures", "100 h de vol cumulées", (c) => c.hours >= 100],
  ["⌛", "Vol de 2 h", "un vol de plus de 2 h", (c, e) => e.duration_s >= 7200],
  ["🌞", "Vol de 3 h", "un vol de plus de 3 h", (c, e) => e.duration_s >= 10800],
  ["⛰️", "2 000 m", "plafond au-dessus de 2 000 m", (c, e) => e.max_alt >= 2000],
  ["🏔️", "3 000 m", "plafond au-dessus de 3 000 m", (c, e) => e.max_alt >= 3000],
  ["🦅", "4 000 m", "plafond au-dessus de 4 000 m", (c, e) => e.max_alt >= 4000],
  ["📏", "50 km", "50 km parcourus en un vol", (c, e) => e.distance_km >= 50],
  ["🚀", "100 km", "100 km parcourus en un vol", (c, e) => e.distance_km >= 100],
  ["🌀", "Thermique +500 m", "un thermique de plus de 500 m", (c, e) => e.best_thermal_m >= 500],
  ["🔥", "Thermique +1 000 m", "un thermique de plus de 1 000 m", (c, e) => e.best_thermal_m >= 1000],
  ["🔺", "Triangle FAI 10 km", "un triangle FAI d'au moins 10 km", (c, e) => e.score_kind === "fai" && e.score_points >= 14],
  ["🏆", "50 points", "un vol à 50 points ou plus", (c, e) => (e.score_points || 0) >= 50],
  ["🧭", "5 sites", "décollé depuis 5 sites différents", (c) => c.sites >= 5],
];

function renderBadges(list) {
  const sorted = [...list].sort((a, b) => (a.takeoff_time < b.takeoff_time ? -1 : 1));
  const earned = new Map();
  const counters = { flights: 0, hours: 0, sites: 0 };
  const sites = [];
  for (const e of sorted) {
    counters.flights++;
    counters.hours += e.duration_s / 3600;
    if (!sites.some((s) => distKm(s[0], s[1], e.takeoff_lat, e.takeoff_lon) < 1)) sites.push([e.takeoff_lat, e.takeoff_lon]);
    counters.sites = sites.length;
    for (const [icon, name, , test] of BADGES) {
      if (!earned.has(name) && test(counters, e)) earned.set(name, e);
    }
  }
  $("badge-count").textContent = `${earned.size} / ${BADGES.length}`;
  $("badges").innerHTML = BADGES.map(([icon, name, desc]) => {
    const e = earned.get(name);
    return `<div class="badge${e ? "" : " locked"}" title="${desc}">
      <span class="ico">${icon}</span>
      <span><b>${name}</b><span class="sub">${e ? `le ${fmtDate(e)}` : desc}</span></span>
    </div>`;
  }).join("");
}

/* ---------- Progression (small multiples, one series each) ---------- */

const PROGRESS = [
  ["avg_thermal_climb", "Montée moyenne en thermique", "m/s", 1],
  ["glide_ratio", "Finesse sol en transition", "", 1],
  ["score_points", "Score", "pts", 0],
];

function renderProgress(list) {
  const sorted = [...list].sort((a, b) => (a.takeoff_time < b.takeoff_time ? -1 : 1));
  const host = $("progress-charts");
  if ($("logbook").hidden || !host.clientWidth) { lb.needsProgress = true; return; }
  lb.needsProgress = false;
  host.innerHTML = PROGRESS.map(([key, title, unit]) =>
    `<figure data-key="${key}"><figcaption>${title} <span>${unit}</span></figcaption><svg></svg><div class="tooltip" hidden></div></figure>`).join("");

  for (const [key, , unit, digits] of PROGRESS) {
    const fig = host.querySelector(`figure[data-key="${key}"]`);
    const svg = fig.querySelector("svg");
    const pts = sorted.map((e, i) => ({ i, e, v: e[key] })).filter((p) => p.v != null && p.v > 0);
    if (pts.length < 2) { svg.outerHTML = `<p class="hint" style="padding:8px">Pas encore assez de vols.</p>`; continue; }
    const W = svg.clientWidth, H = svg.clientHeight, pad = { l: 34, r: 8, t: 10, b: 20 };
    const hi = Math.max(...pts.map((p) => p.v)), step = niceStep(hi / 3), top = Math.ceil(hi / step) * step;
    const x = (i) => pad.l + (i / Math.max(1, sorted.length - 1)) * (W - pad.l - pad.r);
    const y = (v) => pad.t + (1 - v / top) * (H - pad.t - pad.b);
    let out = "";
    for (let v = 0; v <= top + 1e-9; v += step) {
      out += `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${nf(v, step < 1 ? 1 : 0)}</text>`;
    }
    // Moving average over 5 flights.
    const trend = pts.map((p, k) => {
      const win = pts.slice(Math.max(0, k - 4), k + 1);
      return [x(p.i), y(win.reduce((a, q) => a + q.v, 0) / win.length)];
    });
    out += `<polyline class="trend" points="${trend.map((p) => p.join(",")).join(" ")}"/>`;
    out += pts.map((p, k) => `<circle class="dot" data-k="${k}" cx="${x(p.i)}" cy="${y(p.v)}" r="5"/>`).join("");
    out += `<text x="${pad.l}" y="${H - 4}">${fmtDate(pts[0].e)}</text><text x="${W - pad.r}" y="${H - 4}" text-anchor="end">${fmtDate(pts.at(-1).e)}</text>`;
    svg.innerHTML = out;

    const tip = fig.querySelector(".tooltip");
    svg.querySelectorAll(".dot").forEach((dot) => {
      dot.addEventListener("mouseenter", () => {
        const p = pts[+dot.dataset.k];
        tip.innerHTML = `<b>${fmtDate(p.e)}</b> · ${nf(p.v, digits)} ${unit}`;
        tip.style.left = `${dot.getAttribute("cx")}px`;
        tip.style.top = `${+dot.getAttribute("cy") + 14}px`;
        tip.hidden = false;
        highlight(p.e.id, true);
      });
      dot.addEventListener("mouseleave", () => { tip.hidden = true; highlight(pts[+dot.dataset.k].e.id, false); });
      dot.addEventListener("click", () => openFlight(pts[+dot.dataset.k].e.id));
    });
  }
}
new ResizeObserver(() => { if (lb.needsProgress) renderProgress(entries()); }).observe($("progress-charts"));
window.addEventListener("resize", () => { if (!$("logbook").hidden) renderProgress(entries()); });

/* ---------- Thermal hotspots (all flights) ---------- */

function hotspotColor(climb) {
  const k = HOTSPOT_STEPS.findIndex((s) => climb < s);
  return HOTSPOT_COLORS[k === -1 ? HOTSPOT_COLORS.length - 1 : k];
}

function renderHotspots() {
  if (!lb.map) return;
  if (!lb.hotLayer) {
    lb.hotLayer = L.layerGroup();
    lb.layersControl.addOverlay(lb.hotLayer, "Thermiques (tous les vols)");
    lb.hotLegend = L.control({ position: "bottomleft" });
    lb.hotLegend.onAdd = () => {
      const d = L.DomUtil.create("div", "legend");
      d.innerHTML = `Montée moyenne<div class="scale">${HOTSPOT_COLORS.map((c) => `<span style="background:${c}"></span>`).join("")}</div>` +
        `<div class="ends"><span>&lt; 0,8</span><span>&gt; 2,5 m/s</span></div>`;
      return d;
    };
    lb.map.on("overlayadd", (e) => { if (e.layer === lb.hotLayer) lb.hotLegend.addTo(lb.map); });
    lb.map.on("overlayremove", (e) => { if (e.layer === lb.hotLayer) lb.hotLegend.remove(); });
  }
  lb.hotLayer.clearLayers();

  // Bin every thermal of every flight into ~500 m cells.
  const cells = new Map();
  for (const e of entries()) {
    const day = flightDate(e);
    for (const [lat, lon, climb, gain, top, minute] of e.thermal_spots || []) {
      const key = `${Math.round(lat / 0.0045)}:${Math.round((lon * Math.cos((lat * Math.PI) / 180)) / 0.0045)}`;
      const c = cells.get(key) || { n: 0, lat: 0, lon: 0, climb: 0, gain: 0, top: 0, hours: [] };
      const local = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 0, minute));
      Object.assign(c, { n: c.n + 1, lat: c.lat + lat, lon: c.lon + lon, climb: c.climb + climb, gain: c.gain + gain, top: c.top + top });
      c.hours.push(local.getHours() + local.getMinutes() / 60);
      cells.set(key, c);
    }
  }
  const sorted = [...cells.values()].sort((a, b) => a.n - b.n); // biggest on top
  for (const c of sorted) {
    const climb = c.climb / c.n;
    const hours = c.hours.sort((a, b) => a - b);
    const from = Math.floor(hours[Math.floor(hours.length * 0.2)]), to = Math.ceil(hours[Math.floor(hours.length * 0.8)]);
    L.circleMarker([c.lat / c.n, c.lon / c.n], {
      radius: 5 + 3 * Math.sqrt(c.n), color: "#fff", weight: 2, fillColor: hotspotColor(climb), fillOpacity: 0.9,
    }).bindTooltip(
      `<b>${c.n} thermique${c.n > 1 ? "s" : ""}</b> · ${nf(climb, 1)} m/s de moyenne<br>` +
      `plafond moyen ${nf(c.top / c.n)} m · +${nf(c.gain / c.n)} m par thermique<br>` +
      (from === to ? `vers ${from} h` : `surtout entre ${from} h et ${to} h`),
    ).addTo(lb.hotLayer);
  }
}

/* ---------- Comparison of two flights ---------- */

const cmp = { flights: [], map: null, layer: null, markers: [], t: 0, playing: false, last: 0, raf: 0 };

async function openCompare() {
  const ids = [...lb.selected];
  if (ids.length !== 2) return;
  for (const id of ids) {
    if (!lb.files[id]) {
      if (!lb.handle) { lbStatus("Pour comparer, resélectionne ton dossier de vols.", "error"); return connectFolder(); }
      await resync();
      if (!lb.files[id]) return;
    }
  }
  try {
    const py = await pythonReady;
    const flights = [];
    for (const id of ids) flights.push(JSON.parse(py.analyze(await (await lb.files[id]()).text(), 0.5)));
    // Oldest first.
    cmp.flights = flights.sort((a, b) => (a.start < b.start ? -1 : 1));
  } catch (e) {
    lbStatus("Impossible de lire un des deux vols : " + (e.message || e), "error");
    return;
  }
  showView("compare");
  renderCompare();
}
$("compare-btn").onclick = openCompare;

const cmpLabel = (f) => new Date(f.start + "Z").toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });

function renderCompare() {
  const [a, b] = cmp.flights;
  $("cmp-legend").innerHTML = cmp.flights.map((f, k) =>
    `<span><i style="background:${CMP_COLORS[k]}"></i><b>${cmpLabel(f)}</b> ${escapeHtml(f.glider || "")}</span>`).join("");

  if (!cmp.map) {
    const esri = (s) => `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`;
    const topo = L.tileLayer(esri("World_Topo_Map"), { attribution: "Tiles © Esri", maxZoom: 19 });
    const sat = L.tileLayer(esri("World_Imagery"), { attribution: "Tiles © Esri", maxZoom: 19 });
    cmp.map = L.map("cmp-map", { preferCanvas: true, layers: [topo], center: [45.3, 5.9], zoom: 9 });
    L.control.layers({ "Topo": topo, "Satellite": sat }, null, { position: "topright" }).addTo(cmp.map);
  }
  cmp.layer?.remove();
  cmp.layer = L.layerGroup().addTo(cmp.map);
  const bounds = L.latLngBounds([]);
  cmp.markers = cmp.flights.map((f, k) => {
    const pts = f.track.lat.map((la, i) => [la, f.track.lon[i]]);
    L.polyline(pts, { color: "#0f172a", weight: 6, opacity: 0.35 }).addTo(cmp.layer);
    const line = L.polyline(pts, { color: CMP_COLORS[k], weight: 3, opacity: 0.9 }).addTo(cmp.layer);
    bounds.extend(line.getBounds());
    return L.circleMarker(pts[0], { radius: 8, color: "#fff", weight: 3, fillColor: CMP_COLORS[k], fillOpacity: 1 }).addTo(cmp.layer);
  });
  cmp.map.invalidateSize();
  cmp.map.fitBounds(bounds, { padding: [24, 24] });

  const rows = [
    ["Durée", (f) => hm(f.stats.duration)],
    ["Distance", (f) => `${nf(f.stats.track_distance_km, 1)} km`],
    ["Plafond", (f) => `${nf(f.stats.max_alt)} m`],
    ["Gain cumulé", (f) => `${nf(f.stats.total_gain_m)} m`],
    ["Thermiques", (f) => nf(f.thermals.length)],
    ["Montée moy. en thermique", (f) => (f.metrics.avg_thermal_climb != null ? `${nf(f.metrics.avg_thermal_climb, 1)} m/s` : "–")],
    ["Finesse sol en transition", (f) => (f.metrics.avg_glide_ratio != null ? nf(f.metrics.avg_glide_ratio, 1) : "–")],
    ["Temps en virage", (f) => `${nf(f.metrics.circling_pct)} %`],
    ["Score", (f) => (f.scores[0] ? `${nf(f.scores[0].points, 1)} pts (${f.scores[0].label})` : "–")],
  ];
  $("cmp-table").innerHTML = `<thead><tr><th></th>${cmp.flights.map((f, k) =>
    `<th style="color:${CMP_COLORS[k]}">${cmpLabel(f)}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map(([label, fn]) => `<tr><td>${label}</td>${cmp.flights.map((f) => `<td>${fn(f)}</td>`).join("")}</tr>`).join("")}</tbody>`;

  cmpStop();
  cmpSet(0);
}

const cmpDuration = () => Math.max(...cmp.flights.map((f) => f.track.t.at(-1)));

function cmpIndex(f, s) {
  const t = f.track.t;
  let lo = 0, hi = t.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (t[mid] < s) lo = mid + 1; else hi = mid; }
  return lo;
}

function cmpSet(seconds) {
  cmp.t = Math.min(Math.max(0, seconds), cmpDuration());
  const lines = cmp.flights.map((f, k) => {
    const i = cmpIndex(f, cmp.t);
    cmp.markers[k].setLatLng([f.track.lat[i], f.track.lon[i]]);
    const v = f.track.vario[i];
    return { alt: f.track.alt[i], v, k, done: cmp.t > f.track.t.at(-1) };
  });
  $("cmp-pos").value = Math.round((cmp.t / cmpDuration()) * 1000);
  const h = Math.floor(cmp.t / 3600), m = Math.floor((cmp.t % 3600) / 60);
  $("cmp-hud").innerHTML = `<b>${h}h${String(m).padStart(2, "0")}</b> après le déco<br>` + lines.map((l) =>
    `<span style="color:${CMP_COLORS[l.k]}">●</span> ${nf(l.alt)} m · ${l.done ? "posé" : `${l.v >= 0 ? "+" : ""}${nf(l.v, 1)} m/s`}`).join("<br>") +
    `<br>écart : ${lines[1].alt - lines[0].alt >= 0 ? "+" : ""}${nf(lines[1].alt - lines[0].alt)} m`;
  drawCmpProfile();
}

function drawCmpProfile() {
  const c = $("cmp-profile");
  if (!c.clientWidth) return;
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  c.width = w * dpr; c.height = h * dpr;
  const ctx = c.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.font = "11px Inter, sans-serif";
  const all = cmp.flights.flatMap((f) => f.track.alt);
  const step = niceStep((Math.max(...all) - Math.min(...all)) / 4);
  const lo = Math.floor(Math.min(...all) / step) * step, hi = Math.ceil(Math.max(...all) / step) * step;
  const tMax = cmpDuration();
  const x = (s) => 52 + (s / tMax) * (w - 66), y = (a) => 12 + (1 - (a - lo) / (hi - lo || 1)) * (h - 38);
  ctx.strokeStyle = cssVar("--grid"); ctx.fillStyle = cssVar("--muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let a = lo; a <= hi; a += step) {
    ctx.beginPath(); ctx.moveTo(52, y(a)); ctx.lineTo(w - 14, y(a)); ctx.stroke();
    ctx.fillText(`${nf(a)} m`, 44, y(a));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  const tStep = [600, 1800, 3600].find((s) => tMax / s <= 8) || 3600;
  for (let s = 0; s <= tMax; s += tStep) ctx.fillText(`${Math.floor(s / 3600)}h${String((s % 3600) / 60).padStart(2, "0")}`, x(s), h - 20);
  cmp.flights.forEach((f, k) => {
    const { t, alt } = f.track;
    const every = Math.max(1, Math.floor(t.length / (w * 2)));
    ctx.beginPath();
    for (let i = 0; i < t.length; i += every) (i ? ctx.lineTo : ctx.moveTo).call(ctx, x(t[i]), y(alt[i]));
    ctx.strokeStyle = CMP_COLORS[k]; ctx.lineWidth = 2; ctx.stroke();
  });
  ctx.strokeStyle = cssVar("--muted"); ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(x(cmp.t), 12); ctx.lineTo(x(cmp.t), h - 26); ctx.stroke();
  ctx.setLineDash([]);
}

function cmpTick(now) {
  if (!cmp.playing) return;
  const dt = Math.min(0.1, (now - cmp.last) / 1000);
  cmp.last = now;
  const next = cmp.t + dt * +$("cmp-speed").value;
  cmpSet(next);
  if (next >= cmpDuration()) return cmpStop();
  cmp.raf = requestAnimationFrame(cmpTick);
}

function cmpStop() {
  cmp.playing = false;
  cancelAnimationFrame(cmp.raf);
  $("cmp-play").innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4v16l13-8z"/></svg>`;
}

$("cmp-play").onclick = () => {
  if (cmp.playing) return cmpStop();
  if (cmp.t >= cmpDuration()) cmp.t = 0;
  cmp.playing = true;
  cmp.last = performance.now();
  $("cmp-play").innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>`;
  cmp.raf = requestAnimationFrame(cmpTick);
};
$("cmp-pos").oninput = (e) => { if (cmp.flights.length) cmpSet((e.target.value / 1000) * cmpDuration()); };
$("cmp-profile").addEventListener("click", (e) => {
  const r = $("cmp-profile").getBoundingClientRect();
  cmpSet(((e.clientX - r.left - 52) / (r.width - 66)) * cmpDuration());
});
new ResizeObserver(() => { if (cmp.flights.length && !$("compare").hidden) { cmp.map.invalidateSize(); drawCmpProfile(); } })
  .observe($("cmp-profile"));
