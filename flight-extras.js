"use strict";
/* Flight view extras: piloting metrics, score, notable moments, airspace check,
 * replay, GPX/KML exports and a shareable image. Uses the helpers of index.html. */

const AIRSPACE_FR_URL = "https://raw.githubusercontent.com/planeur-net/airspace/main/france.txt";
const COMPASS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
const SCORE_COLOR = "#7c3aed";
const extras = {
  layers: {},
  replay: { playing: false, active: false, t: 0, last: 0, raf: 0 },
  frText: null,
  airspaceIntro: $("airspace-result").innerHTML,
};

const compass = (deg) => COMPASS[Math.round(deg / 45) % 8];
const windArrow = (deg) =>
  `<svg class="wind-arrow" width="16" height="16" viewBox="0 0 24 24" style="transform:rotate(${deg + 180}deg)" aria-hidden="true">` +
  `<path d="M12 3v18M12 3l-6 6M12 3l6 6" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>`;

function renderExtras(data) {
  stopReplay();
  extras.replay.active = false;
  $("hud").hidden = true;
  $("replay-pos").value = 0;
  for (const name of ["score", "airspace", "moment"]) {
    extras.layers[name]?.remove();
    extras.layers[name] = L.layerGroup().addTo(state.map);
  }
  renderPiloting(data.metrics);
  renderScores(data.scores);
  renderMoments(data.moments);
  $("airspace-result").innerHTML = extras.airspaceIntro;
}

/* ---------- Piloting ---------- */

function renderPiloting(m) {
  const rows = [
    ["Temps en virage", `${nf(m.circling_pct)} %`],
    ["Virages gauche / droite", `${nf(m.left_turn_pct)} % / ${nf(100 - m.left_turn_pct)} %`],
    ["Montée moy. en thermique", m.avg_thermal_climb != null ? `${nf(m.avg_thermal_climb, 1)} m/s` : "–"],
    ["Finesse sol en transition", m.avg_glide_ratio != null
      ? `${nf(m.avg_glide_ratio, 1)}${m.best_glide_ratio ? ` (max ${nf(m.best_glide_ratio, 1)})` : ""}` : "–"],
    ["Vitesse en transition", m.avg_glide_speed_kmh != null ? `${nf(m.avg_glide_speed_kmh)} km/h` : "–"],
    ["Vent estimé", !m.wind ? "–" : m.wind.speed_kmh < 3 ? "faible"
      : `${windArrow(m.wind.direction_deg)}${nf(m.wind.speed_kmh)} km/h de ${compass(m.wind.direction_deg)}`],
    ["Facteur de charge max", `${nf(m.max_g, 1)} G`],
  ];
  $("piloting").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

/* ---------- Score ---------- */

function renderScores(scores) {
  $("scores").innerHTML = scores.length ? scores.map((s, i) => `
    <li data-i="${i}">
      <span class="main">${s.label}<span class="sub">${nf(s.distance_km, 1)} km${s.kind !== "free" ? ` · fermeture ${nf(s.closing_km, 1)} km` : ""}</span></span>
      <span class="val">${nf(s.points, 1)} pts</span>
    </li>`).join("") : `<li class="empty">Vol trop court pour un score.</li>`;
  $("scores").querySelectorAll("li[data-i]").forEach((li) =>
    li.addEventListener("click", () => selectScore(+li.dataset.i, true)));
  if (scores.length) selectScore(0, false);
}

function selectScore(i, zoom) {
  const s = state.data.scores[i];
  $("scores").querySelectorAll("li").forEach((li) => li.classList.toggle("selected", +li.dataset.i === i));
  const layer = extras.layers.score;
  layer.clearLayers();
  const pts = s.turnpoints;
  const shape = s.kind === "free" ? pts : [...pts, pts[0]];
  L.polyline(shape, { color: SCORE_COLOR, weight: 3, dashArray: "8 6", opacity: 0.95 }).addTo(layer);
  pts.forEach((p, k) => L.circleMarker(p, { radius: 5, color: "#fff", weight: 2, fillColor: SCORE_COLOR, fillOpacity: 1 })
    .bindTooltip(s.kind === "free" ? ["Départ", "Point 1", "Point 2", "Point 3", "Arrivée"][k] || `Point ${k}` : `Sommet ${k + 1}`)
    .addTo(layer));
  if (s.closing) {
    L.polyline(s.closing, { color: SCORE_COLOR, weight: 2, dashArray: "2 6" })
      .bindTooltip(`Fermeture ${nf(s.closing_km, 1)} km`).addTo(layer);
  }
  if (zoom) state.map.flyToBounds(L.latLngBounds(shape), { padding: [40, 40], duration: 0.6 });
}

/* ---------- Notable moments ---------- */

function momentValue(m) {
  switch (m.kind) {
    case "climb": return `+${nf(m.value, 1)} m/s`;
    case "sink": case "spiral": return `${nf(m.value, 1)} m/s`;
    case "speed": return `${nf(m.value)} km/h`;
    case "g": return `${nf(m.value, 1)} G`;
    default: return nf(m.value, 1);
  }
}

function renderMoments(moments) {
  $("moments").innerHTML = moments.map((m, i) => `
    <li data-i="${i}">
      <span class="main">${escapeHtml(m.label)}<span class="sub">${clockAt(m.t)} · ${nf(m.alt)} m${m.duration_s ? ` · ${nf(m.duration_s)} s` : ""}</span></span>
      <span class="val">${momentValue(m)}</span>
    </li>`).join("");
  $("moments").querySelectorAll("li").forEach((li) => li.addEventListener("click", () => {
    const m = state.data.moments[+li.dataset.i];
    $("moments").querySelectorAll("li").forEach((x) => x.classList.toggle("selected", x === li));
    extras.layers.moment.clearLayers();
    L.circleMarker([m.lat, m.lon], { radius: 9, color: "#fff", weight: 3, fillColor: "#dc2626", fillOpacity: 1 })
      .bindTooltip(`${m.label} : ${momentValue(m)}`, { permanent: true, direction: "top", offset: [0, -8] })
      .addTo(extras.layers.moment);
    state.map.flyTo([m.lat, m.lon], 15, { duration: 0.6 });
    drawProfile(indexAt(m.t));
  }));
}

/* ---------- Airspace ---------- */

async function checkAirspace(getText, source) {
  const out = $("airspace-result");
  out.innerHTML = `<span class="spinner" style="display:inline-block;vertical-align:-2px"></span> Vérification des espaces aériens…`;
  try {
    const text = await getText();
    const py = await pythonReady;
    await new Promise((r) => setTimeout(r, 30));
    renderAirspace(JSON.parse(py.airspaceCheck(text, false)), source);
  } catch (e) {
    out.innerHTML = `<span style="color:#dc2626">Impossible de vérifier : ${escapeHtml(String(e.message || e).split("\n").filter(Boolean).pop())}</span>`;
  }
}

function renderAirspace(list, source) {
  const out = $("airspace-result");
  const layer = extras.layers.airspace;
  layer.clearLayers();
  if (!list.length) {
    out.innerHTML = `<span class="ok">✓ Aucune pénétration détectée</span> dans les zones de ${escapeHtml(source)}. Indicatif : vérifie toujours les NOTAM.`;
    return;
  }
  const drawn = new Set();
  for (const a of list) {
    if (drawn.has(a.name)) continue;
    drawn.add(a.name);
    const color = a.uncertain ? "#f59e0b" : "#dc2626";
    L.polygon(a.points, { color, weight: 2, fillOpacity: 0.12 }).bindTooltip(`${a.name} · ${a.floor} → ${a.ceiling}`).addTo(layer);
  }
  out.innerHTML = `${list.length} passage${list.length > 1 ? "s" : ""} dans des zones de ${escapeHtml(source)} :` +
    `<ul>${list.map((a, i) => `
      <li data-i="${i}" class="${a.uncertain ? "uncertain" : ""}">
        ⚠ <b>${escapeHtml(a.name)}</b><br>
        <span class="sub">${escapeHtml(a.label)} · ${escapeHtml(a.floor)} → ${escapeHtml(a.ceiling)} ·
        ${clockAt(a.start_s)}–${clockAt(a.end_s)} · jusqu'à ${nf(a.alt)} m${a.uncertain ? " · limite par rapport au sol : à vérifier" : ""}</span>
      </li>`).join("")}</ul>`;
  out.querySelectorAll("li").forEach((li) => li.addEventListener("click", () => {
    const a = list[+li.dataset.i];
    state.map.flyToBounds(L.latLngBounds(a.points), { padding: [30, 30], duration: 0.6 });
    drawProfile(indexAt(a.start_s));
  }));
}

$("airspace-fr").onclick = () => checkAirspace(async () => {
  if (!extras.frText) {
    const res = await fetch(AIRSPACE_FR_URL);
    if (!res.ok) throw new Error("fichier des espaces aériens indisponible");
    extras.frText = await res.text();
  }
  return extras.frText;
}, "France (planeur-net)");
$("airspace-file").onclick = () => $("airspace-input").click();
$("airspace-input").onchange = (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (file) checkAirspace(() => file.text(), file.name);
};

/* ---------- Replay ---------- */

function groundSpeedAt(i) {
  const { t, lat, lon } = state.data.track;
  const j = Math.max(0, i - 5);
  const dt = t[i] - t[j];
  return dt > 0 ? (distKm(lat[j], lon[j], lat[i], lon[i]) / dt) * 3600 : 0;
}

function setReplayPosition(seconds, follow = true) {
  const { t, lat, lon, alt, vario } = state.data.track;
  const r = extras.replay;
  r.t = Math.min(Math.max(seconds, 0), t.at(-1));
  r.active = true;
  const i = indexAt(r.t);
  const pos = [lat[i], lon[i]];
  state.hoverMarker.setLatLng(pos);
  if (!state.map.hasLayer(state.hoverMarker)) state.hoverMarker.addTo(state.map);
  if (follow) state.map.panInside(pos, { padding: [80, 80] });
  drawProfile(i);
  $("replay-pos").value = Math.round((r.t / (t.at(-1) || 1)) * 1000);
  const v = vario[i];
  $("hud").innerHTML = `<b style="color:${v > 0.2 ? "#4ade80" : v < -1.5 ? "#f87171" : "#fff"}">${v >= 0 ? "+" : ""}${nf(v, 1)}</b> m/s · ${nf(alt[i])} m<br>${clockAt(t[i])} · ${nf(groundSpeedAt(i))} km/h`;
  $("hud").hidden = false;
}

function tick(now) {
  const r = extras.replay;
  if (!r.playing) return;
  const dt = Math.min(0.1, (now - r.last) / 1000);
  r.last = now;
  const end = state.data.track.t.at(-1);
  const next = r.t + dt * +$("replay-speed").value;
  setReplayPosition(Math.min(next, end));
  if (next >= end) return stopReplay();
  r.raf = requestAnimationFrame(tick);
}

function playIcon(playing) {
  $("replay-play").innerHTML = playing
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4v16l13-8z"/></svg>`;
}

function stopReplay() {
  extras.replay.playing = false;
  cancelAnimationFrame(extras.replay.raf);
  playIcon(false);
}

$("replay-play").onclick = () => {
  const r = extras.replay;
  if (r.playing) return stopReplay();
  if (!state.data) return;
  if (r.t >= state.data.track.t.at(-1)) r.t = 0;
  r.playing = true;
  r.last = performance.now();
  playIcon(true);
  setReplayPosition(r.t);
  r.raf = requestAnimationFrame(tick);
};
$("replay-pos").oninput = (e) => {
  if (!state.data) return;
  setReplayPosition((e.target.value / 1000) * state.data.track.t.at(-1));
};
// The profile hover hides the position marker: put it back while a replay is in progress.
$("profile").addEventListener("mouseleave", () => {
  if (extras.replay.active && state.data) setReplayPosition(extras.replay.t, false);
});

/* ---------- Exports ---------- */

function download(content, filename, type) {
  const url = URL.createObjectURL(content instanceof Blob ? content : new Blob([content], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const exportName = (ext) => `vol-${state.data?.date || "flylog"}.${ext}`;
$("export-gpx").onclick = async () => download((await pythonReady).exportGpx(), exportName("gpx"), "application/gpx+xml");
$("export-kml").onclick = async () => download((await pythonReady).exportKml(), exportName("kml"), "application/vnd.google-earth.kml+xml");

/* ---------- Share image ---------- */

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

async function shareImage() {
  const d = state.data;
  if (!d) return;
  await document.fonts.ready;
  const W = 1080, H = 1350;
  const c = Object.assign(document.createElement("canvas"), { width: W, height: H });
  const ctx = c.getContext("2d");

  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#0b2540");
  bg.addColorStop(1, "#0e6b8c");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Header
  ctx.fillStyle = "#fff";
  ctx.font = "700 56px Inter, sans-serif";
  const date = d.date ? new Date(d.date + "T12:00:00Z").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "Mon vol";
  ctx.fillText(date.charAt(0).toUpperCase() + date.slice(1), 60, 110);
  ctx.font = "400 28px Inter, sans-serif";
  ctx.fillStyle = "rgba(255,255,255,.75)";
  ctx.fillText([d.glider, `${clockAt(0)} → ${clockAt(d.track.t.at(-1))}`].filter(Boolean).join("  ·  "), 60, 158);

  // Track
  const box = { x: 60, y: 200, w: W - 120, h: 640 };
  roundRect(ctx, box.x, box.y, box.w, box.h, 28);
  ctx.fillStyle = "rgba(255,255,255,.07)";
  ctx.fill();
  const { lat, lon, vario, alt, t } = d.track;
  const k = Math.cos((lat[0] * Math.PI) / 180);
  const xs = lon.map((v) => v * k), ys = lat;
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = Math.min((box.w - 80) / (x1 - x0 || 1e-6), (box.h - 80) / (y1 - y0 || 1e-6));
  const ox = box.x + (box.w - (x1 - x0) * scale) / 2, oy = box.y + (box.h + (y1 - y0) * scale) / 2;
  const P = (i) => [ox + (xs[i] - x0) * scale, oy - (ys[i] - y0) * scale];
  const step = Math.max(1, Math.floor(t.length / 3000));
  ctx.lineCap = ctx.lineJoin = "round";
  ctx.strokeStyle = "rgba(0,0,0,.35)";
  ctx.lineWidth = 9;
  ctx.beginPath();
  for (let i = 0; i < t.length; i += step) (i ? ctx.lineTo : ctx.moveTo).call(ctx, ...P(i));
  ctx.stroke();
  ctx.lineWidth = 5;
  for (let i = step; i < t.length; i += step) {
    ctx.strokeStyle = VARIO_COLORS[varioBucket(vario[i])];
    ctx.beginPath();
    ctx.moveTo(...P(i - step));
    ctx.lineTo(...P(i));
    ctx.stroke();
  }
  for (const th of d.thermals) {
    const [px, py] = [ox + (th.lon * k - x0) * scale, oy - (th.lat - y0) * scale];
    ctx.beginPath();
    ctx.arc(px, py, 6 + Math.min(14, th.gain_m / 60), 0, Math.PI * 2);
    ctx.fillStyle = "rgba(245,158,11,.85)";
    ctx.fill();
  }
  for (const [i, color] of [[0, "#16a34a"], [t.length - 1, "#dc2626"]]) {
    ctx.beginPath();
    ctx.arc(...P(i), 12, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = 4;
    ctx.strokeStyle = "#fff";
    ctx.stroke();
  }

  // Stats
  const s = d.stats, best = d.scores[0];
  const bestThermal = d.thermals.reduce((a, b) => (b.gain_m > (a?.gain_m ?? -1) ? b : a), null);
  const items = [
    ["Durée", duration(s.duration).replace(/<\/?small>/g, "")],
    ["Distance", `${nf(s.track_distance_km, 1)} km`],
    ["Plafond", `${nf(s.max_alt)} m`],
    ["Gain cumulé", `${nf(s.total_gain_m)} m`],
    [best ? best.label : "Score", best ? `${nf(best.points, 1)} pts` : "–"],
    ["Meilleur thermique", bestThermal ? `+${nf(bestThermal.gain_m)} m` : "–"],
  ];
  const cw = (W - 120 - 2 * 24) / 3, ch = 130;
  items.forEach(([label, value], n) => {
    const x = 60 + (n % 3) * (cw + 24), y = 870 + Math.floor(n / 3) * (ch + 20);
    roundRect(ctx, x, y, cw, ch, 22);
    ctx.fillStyle = "rgba(255,255,255,.1)";
    ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,.7)";
    ctx.font = "600 22px Inter, sans-serif";
    ctx.fillText(label.toUpperCase(), x + 24, y + 44);
    ctx.fillStyle = "#fff";
    ctx.font = "700 44px Inter, sans-serif";
    ctx.fillText(value, x + 24, y + 102);
  });

  // Profile strip
  const py0 = 1175, ph = 90, lo = Math.min(...alt), hi = Math.max(...alt);
  ctx.beginPath();
  for (let i = 0; i < t.length; i += step) {
    const x = 60 + ((W - 120) * t[i]) / t.at(-1), y = py0 + ph - (ph * (alt[i] - lo)) / (hi - lo || 1);
    (i ? ctx.lineTo : ctx.moveTo).call(ctx, x, y);
  }
  ctx.lineTo(W - 60, py0 + ph);
  ctx.lineTo(60, py0 + ph);
  ctx.closePath();
  ctx.fillStyle = "rgba(125,211,252,.35)";
  ctx.fill();

  ctx.fillStyle = "rgba(255,255,255,.7)";
  ctx.font = "500 24px Inter, sans-serif";
  ctx.fillText("FlyLog · elrelook.github.io/flylog", 60, H - 40);

  const blob = await new Promise((r) => c.toBlob(r, "image/png"));
  const file = new File([blob], exportName("png"), { type: "image/png" });
  if (navigator.canShare?.({ files: [file] }) && matchMedia("(pointer: coarse)").matches) {
    try { await navigator.share({ files: [file], title: $("flight-title").textContent }); return; } catch { /* cancelled */ }
  }
  download(blob, exportName("png"), "image/png");
}
$("share-image").onclick = shareImage;
