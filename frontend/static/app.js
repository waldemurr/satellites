/* app.js — логика интерфейса «СПУТНИК·АРКТИК» (редизайн: 3D + exclude-тумблеры + эксперименты).
   Ванильный JS без сборки. Все обращения к API — через api(). */
"use strict";

/* ==================== утилиты ==================== */
const $ = id => document.getElementById(id);

function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = String(Math.floor(sec / 3600)).padStart(2, "0");
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fmtNum(x, digits = 1) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return Number(x).toFixed(digits);
}

function deepCopy(o) { return JSON.parse(JSON.stringify(o)); }

async function api(path, options = {}) {
  const res = await fetch(path, options);
  let body = null;
  try { body = await res.json(); } catch (e) { /* не JSON */ }
  if (!res.ok) {
    const msg = (body && (body.error || (body.errors && body.errors.join("; ")))) ||
      `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

function toast(title, text, kind = "info", list) {
  const el = document.createElement("div");
  el.className = "toast" + (kind === "error" ? " error" : kind === "warn" ? " warn" : "");
  let html = `<div class="toast-title">${title}</div>`;
  if (text) html += `<div>${text}</div>`;
  if (list && list.length) html += "<ul>" + list.map(x => `<li>${x}</li>`).join("") + "</ul>";
  el.innerHTML = html;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "error" ? 12000 : 6000);
}

function showSpinner(text) { $("spinnerText").textContent = text || "Расчёт…"; $("spinner").hidden = false; }
function hideSpinner() { $("spinner").hidden = true; }

function downloadBlob(name, content, mime) {
  const blob = new Blob([content], { type: mime });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/* ==================== состояние ==================== */
const state = {
  files: [],
  file: null,
  scenario: null,
  edited: null,
  dirty: false,
  t: 0,
  horizon: 86400,
  step: 120,
  snapshot: null,
  route: null,
  timeline: null,
  playing: false,
  playTimer: null,
  clients: [],
  gateways: [],
  availability: null,
  mcResult: null,
  excluded: new Set(),   // id выключенных тумблерами спутников
};

let scene = null;
let calcSeq = 0;

const excludeIds = () => Array.from(state.excluded);
const excludeQuery = () => {
  const ids = excludeIds();
  return ids.length ? `&exclude=${encodeURIComponent(ids.join(","))}` : "";
};

/* ==================== сценарии: список / выбор / загрузка ==================== */
async function loadFiles() {
  const data = await api("/api/data/files");
  state.files = data.files || [];
  const sel = $("fileSelect");
  sel.innerHTML = state.files.map(f => `<option value="${f}">${f}</option>`).join("");
  if (!state.files.length) {
    toast("Нет сценариев", "Папки data/ и uploads/ пусты.", "warn");
    return;
  }
  if (!state.file || !state.files.includes(state.file)) state.file = state.files[0];
  sel.value = state.file;
}

async function loadScenario(file) {
  stopPlay();
  state.file = file;
  state.route = null;
  state.timeline = null;
  state.availability = null;
  state.excluded.clear();
  try {
    const scenario = await api(`/api/data/${encodeURIComponent(file)}`);
    state.scenario = scenario;
    state.edited = deepCopy(scenario);
    state.dirty = false;
    const env = scenario.environment;
    state.horizon = env.horizon_s;
    state.step = env.step_s;
    state.t = 0;
    const slider = $("timeSlider");
    slider.max = state.horizon;
    slider.step = state.step;
    slider.value = 0;
    $("timeTotal").textContent = fmtTime(state.horizon);
    populateGroundSelects(scenario);
    renderEditor();
    renderToggleTree();
    updateExcludedUI();
    updateDirtyFlag();
    await calculate(0);
    await loadTimeline();
  } catch (e) {
    toast("Ошибка загрузки сценария", e.message, "error");
  }
}

function populateGroundSelects(scenario) {
  const sites = scenario.ground_sites || [];
  state.clients = sites.filter(g => g.role === "client").map(g => g.id);
  state.gateways = sites.filter(g => g.role === "gateway").map(g => g.id);
  const opts = ids => ids.map(id => `<option value="${id}">${id}</option>`).join("");
  $("routeClient").innerHTML = opts(state.clients);
  $("availClient").innerHTML = opts(state.clients);
  $("routeGateway").innerHTML = opts(state.gateways);
  $("gwOutageGw").innerHTML = opts(state.gateways);
  $("expClient").innerHTML = opts(state.clients);
  const satOpts = (scenario.design.satellites || []).map(s =>
    `<option value="${s.id}">${s.id} (${s.plane_id}, оч. ${s.launch_batch})</option>`).join("");
  $("failSat").innerHTML = satOpts;
  $("targetAvail").textContent = scenario.environment.target_availability;
}

/* ==================== расчёт снапшота ==================== */
function satStatus(sat, t) {
  const inFail = (state.scenario.failures || []).some(
    f => f.satellite_id === sat.id && f.start_s <= t && t < f.end_s);
  if (inFail || state.excluded.has(sat.id)) return "failed";
  return sat.active ? "active" : "inactive";
}

function pushScene() {
  if (!state.snapshot || !scene) return;
  const sats = state.snapshot.satellites.map(s => ({ ...s, status: satStatus(s, state.t) }));
  scene.setSnapshot({
    satellites: sats,
    edges: state.snapshot.edges,
    groundSites: state.scenario.ground_sites,
    routePath: state.route && state.route.connected ? state.route.path : null,
    tS: state.t,
    earthAngle0Deg: state.scenario.environment.earth_angle0_deg,
  });
}

async function calculate(t) {
  if (!state.file) return;
  const seq = ++calcSeq;
  state.t = t;
  $("timeSlider").value = t;
  $("timeDisplay").textContent = fmtTime(t);
  try {
    const data = await api("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: state.file, timestamp: t, exclude: excludeIds() }),
    });
    if (seq !== calcSeq) return;
    state.snapshot = data.result;
    pushScene();
    renderNetStats();
    drawAvailability();
    if ($("routeAuto").checked && state.route) buildRoute();
  } catch (e) {
    if (seq === calcSeq) toast("Ошибка расчёта", e.message, "error");
  }
}

function renderNetStats() {
  const box = $("netStats");
  if (!state.snapshot) { box.innerHTML = '<div class="empty">Нет данных.</div>'; return; }
  const t = state.t;
  const sats = state.snapshot.satellites.map(s => ({ ...s, status: satStatus(s, t) }));
  const active = sats.filter(s => s.status === "active").length;
  const failed = sats.filter(s => s.status === "failed").length;
  const inactive = sats.length - active - failed;
  const satIds = new Set(sats.map(s => s.id));
  const edges = state.snapshot.edges;
  const isl = edges.filter(e => satIds.has(e[0]) && satIds.has(e[1])).length;
  box.innerHTML =
    `Спутников: <b>${sats.length}</b><br>` +
    `активны <span style="color:var(--accent)">${active}</span> · ` +
    `не запущены <span class="muted">${inactive}</span> · ` +
    `отказ/выкл. <span style="color:var(--bad)">${failed}</span><br>` +
    `Связей: <b>${edges.length}</b> · ISL ${isl} · пункт↔КА ${edges.length - isl}` +
    (state.excluded.size ? `<br>Выключено тумблерами: <span style="color:var(--bad)">${state.excluded.size}</span>` : "");
}

/* ==================== инфопанель объекта ==================== */
function bindSceneEvents() {
  scene.onHover = info => renderInfo(info);
  scene.onSelect = info => renderInfo(info);
}

function renderInfo(info) {
  const box = $("satInfo");
  if (!info) {
    box.innerHTML = '<div class="empty">Наведите курсор на спутник или наземный пункт на 3D-модели…</div>';
    return;
  }
  if (info.kind === "ground") {
    const g = info.ref;
    const role = g.role === "gateway" ? "шлюз" : "клиент";
    const offline = (state.scenario.gateway_outages || []).some(
      o => o.gateway_id === g.id && o.start_s <= state.t && state.t < o.end_s);
    box.innerHTML = `<div class="kv">
      <span>Пункт</span><b>${g.id}</b>
      <span>Роль</span><b>${role}</b>
      <span>Широта</span><b>${fmtNum(g.lat_deg, 2)}°</b>
      <span>Долгота</span><b>${fmtNum(g.lon_deg, 2)}°</b>
      <span>Статус</span><b>${offline ? '<span style="color:var(--bad)">недоступен</span>' : "в работе"}</b>
    </div>`;
    return;
  }
  const s = info.ref;
  const design = (state.scenario.design.satellites || []).find(x => x.id === s.id) || {};
  const statusText = s.status === "active" ? '<span style="color:var(--accent)">активен</span>'
    : s.status === "failed"
      ? (state.excluded.has(s.id) ? '<span style="color:var(--bad)">выключен тумблером</span>'
        : '<span style="color:var(--bad)">в отказе</span>')
    : `<span class="muted">не запущен (очередь ${design.launch_batch || "?"})</span>`;
  let elevRows = "";
  if (state.snapshot && state.snapshot.elevation_deg) {
    for (const site of state.clients.concat(state.gateways)) {
      const v = state.snapshot.elevation_deg[site] && state.snapshot.elevation_deg[site][s.id];
      if (v !== undefined) elevRows += `<span>${site}</span><b>${fmtNum(v, 1)}°</b>`;
    }
  }
  box.innerHTML = `<div class="kv">
    <span>Спутник</span><b>${s.id}</b>
    <span>Плоскость</span><b>${design.plane_id || "—"}</b>
    <span>Слот</span><b>${fmtNum(design.slot_deg, 1)}°</b>
    <span>Статус</span><b>${statusText}</b>
    <span>X</span><b>${fmtNum(s.x_km, 0)} км</b>
    <span>Y</span><b>${fmtNum(s.y_km, 0)} км</b>
    <span>Z</span><b>${fmtNum(s.z_km, 0)} км</b>
    ${elevRows ? "<span>Углы места</span>" + elevRows : ""}
  </div>`;
}

/* ==================== маршрутизация ==================== */
async function buildRoute() {
  if (!state.file) return;
  const client = $("routeClient").value;
  const gateway = $("routeGateway").value;
  const strategy = $("routeStrategy").value;
  try {
    const r = await api(`/api/route/${encodeURIComponent(state.file)}/${client}/${gateway}` +
      `?t_s=${state.t}&strategy=${strategy}${excludeQuery()}`);
    state.route = r;
    const box = $("routeResult");
    if (r.connected) {
      const cap = r.bottleneck_capacity !== undefined
        ? `<span>Ёмкость (узкое место)</span><b>${r.bottleneck_capacity} у.е.</b>` : "";
      box.innerHTML = `<div class="route-ok">
        <div class="path">${r.path.join(" → ")}</div>
        <div class="metrics">
          <span>Переходов (ISL)</span><b>${r.hops}</b>
          <span>Задержка</span><b>${fmtNum(r.latency_ms, 2)} мс</b>
          <span>Длина пути</span><b>${fmtNum(r.total_dist_km, 0)} км</b>
          ${cap}
        </div></div>`;
    } else {
      box.innerHTML = `<div class="route-bad fail">
        Связь отсутствует.<br><span class="reason">${r.reason_text || r.reason}</span>
      </div>`;
    }
    pushScene();
  } catch (e) {
    toast("Ошибка маршрутизации", e.message, "error");
  }
}

/* ==================== временная шкала ==================== */
function setTime(t) {
  t = Math.max(0, Math.min(state.horizon, t));
  t = Math.round(t / state.step) * state.step;
  calculate(t);
}

$("timeSlider").addEventListener("input", e => setTime(Number(e.target.value)));
$("btnStepBack").addEventListener("click", () => setTime(state.t - state.step));
$("btnStepFwd").addEventListener("click", () => setTime(state.t + state.step));
$("btnPlay").addEventListener("click", () => (state.playing ? stopPlay() : startPlay()));
$("playSpeed").addEventListener("change", () => { if (state.playing) { stopPlay(); startPlay(); } });

function startPlay() {
  if (!state.file) return;
  state.playing = true;
  $("btnPlay").textContent = "⏸";
  state.playTimer = setInterval(() => {
    let t = state.t + state.step;
    if (t > state.horizon) t = 0;
    calculate(t);
  }, Number($("playSpeed").value));
}

function stopPlay() {
  state.playing = false;
  if (state.playTimer) clearInterval(state.playTimer);
  state.playTimer = null;
  const b = $("btnPlay");
  if (b) b.textContent = "▶";
}

/* ==================== диаграмма доступности ==================== */
async function loadTimeline() {
  if (!state.file || !state.clients.length) return;
  const client = $("availClient").value || state.clients[0];
  const gateway = $("routeGateway").value || state.gateways[0];
  const strategy = $("routeStrategy").value;
  try {
    const tl = await api(`/api/route-timeline/${encodeURIComponent(state.file)}/${client}/${gateway}` +
      `?strategy=${strategy}&step_sample=6${excludeQuery()}`);
    state.timeline = tl;
    drawAvailability();
    renderOutages();
  } catch (e) {
    toast("Ошибка построения диаграммы доступности", e.message, "error");
  }
}

function drawAvailability() {
  const cv = $("availCanvas");
  const tl = state.timeline;
  if (!tl || !cv.clientWidth) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth;
  const h = 70;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const n = tl.steps.length;
  if (!n) return;
  const bw = w / n;
  for (let i = 0; i < n; i++) {
    ctx.fillStyle = tl.steps[i].connected ? "rgba(52, 211, 153, 0.75)" : "rgba(248, 113, 113, 0.9)";
    ctx.fillRect(i * bw, 8, Math.max(1, bw - 0.5), h - 22);
  }
  ctx.fillStyle = "rgba(132, 148, 167, 0.9)";
  ctx.font = "10px Consolas, monospace";
  for (let hh = 0; hh <= 24; hh += 6) {
    const x = (hh * 3600 / state.horizon) * w;
    ctx.fillRect(x, h - 12, 1, 5);
    ctx.fillText(`${String(hh).padStart(2, "0")}:00`, x + 3, h - 4);
  }
  const x = (state.t / state.horizon) * w;
  ctx.fillStyle = "#22d3ee";
  ctx.shadowColor = "#22d3ee"; ctx.shadowBlur = 6;
  ctx.fillRect(x - 1, 2, 2, h - 14);
  ctx.shadowBlur = 0;
  $("availSummary").textContent =
    `доступность ${(tl.availability * 100).toFixed(1)}% · перерывов ${tl.outage_count}` +
    ` · максимум ${fmtNum(tl.max_outage_s, 0)} с` +
    (state.excluded.size ? " · с учётом выключенных КА" : "");
}

const REASON_RU = {
  no_visible_satellite_client: "нет видимого спутника у наземного пункта",
  isl_mesh_disconnected: "разрыв межспутниковой сети (ISL)",
  no_visible_satellite_gateway: "нет видимого спутника у шлюза",
  gateway_offline: "шлюз недоступен (в отказе)",
};

function renderOutages() {
  const tl = state.timeline;
  const box = $("outageList");
  if (!tl) { box.innerHTML = ""; return; }
  if (!tl.outages.length) {
    box.innerHTML = '<div class="muted">Перерывов нет — связь устойчива на всём горизонте.</div>';
    return;
  }
  box.innerHTML = tl.outages.map(o =>
    `<div class="item">${fmtTime(o.start_s)} – ${fmtTime(o.end_s)}` +
    ` (${fmtNum(o.duration_s, 0)} с) · <span class="reason">${REASON_RU[o.reason] || o.reason}</span></div>`
  ).join("");
}

(function bindAvailCanvas() {
  const cv = $("availCanvas");
  let drag = false;
  const seek = e => {
    const rect = cv.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setTime(frac * state.horizon);
  };
  cv.addEventListener("mousedown", e => { drag = true; seek(e); });
  window.addEventListener("mouseup", () => { drag = false; });
  cv.addEventListener("mousemove", e => { if (drag) seek(e); });
})();

/* ==================== тумблеры спутников ==================== */
function renderToggleTree() {
  const box = $("toggleTree");
  if (!state.scenario) { box.innerHTML = ""; return; }
  const sats = state.scenario.design.satellites || [];
  const byPlane = {};
  for (const s of sats) (byPlane[s.plane_id] = byPlane[s.plane_id] || []).push(s);
  box.innerHTML = Object.entries(byPlane).map(([pid, list]) => {
    const body = list.map(s =>
      `<label class="toggle-item ${state.excluded.has(s.id) ? "off" : ""}" title="${s.id} · ${pid} · очередь ${s.launch_batch}">
        <input type="checkbox" data-sat="${s.id}" ${state.excluded.has(s.id) ? "" : "checked"}> ${s.id}
      </label>`).join("");
    return `<div class="toggle-group">
      <div class="tg-head">
        <input type="checkbox" data-plane="${pid}" title="Включить/выключить плоскость целиком">
        <b>${pid}</b><span class="count">${list.length} КА · оч. ${list[0].launch_batch}</span>
      </div>
      <div class="tg-body">${body}</div>
    </div>`;
  }).join("");
}

$("toggleTree").addEventListener("change", e => {
  const sat = e.target.dataset.sat;
  const plane = e.target.dataset.plane;
  if (sat) {
    e.target.checked ? state.excluded.delete(sat) : state.excluded.add(sat);
  } else if (plane) {
    const sats = (state.scenario.design.satellites || []).filter(s => s.plane_id === plane);
    for (const s of sats) e.target.checked ? state.excluded.delete(s.id) : state.excluded.add(s.id);
    renderToggleTree();
  }
  onExcludedChanged();
});

function onExcludedChanged() {
  updateExcludedUI();
  calculate(state.t);
  loadTimeline();
  if (state.route) buildRoute();
  updateReportSummary();
}

function updateExcludedUI() {
  const n = state.excluded.size;
  $("excludedSummary").textContent = n
    ? `Выключено: ${n} аппарат(а). Расчёт выполняется без них.`
    : "Все аппараты включены.";
  const list = $("excludedList");
  list.innerHTML = n
    ? `<span style="color:var(--bad)">${excludeIds().join(", ")}</span>`
    : '<div class="empty">Ничего не выключено.</div>';
  if (state.scenario) {
    // синхронизируем чекбоксы без полной перерисовки дерева
    document.querySelectorAll("#toggleTree input[data-sat]").forEach(cb => {
      cb.checked = !state.excluded.has(cb.dataset.sat);
      cb.closest(".toggle-item").classList.toggle("off", !cb.checked);
    });
    document.querySelectorAll("#toggleTree input[data-plane]").forEach(cb => {
      const sats = (state.scenario.design.satellites || []).filter(s => s.plane_id === cb.dataset.plane);
      cb.checked = sats.every(s => !state.excluded.has(s.id));
    });
  }
}

$("btnEnableAll").addEventListener("click", () => {
  state.excluded.clear();
  renderToggleTree();
  onExcludedChanged();
});

$("btnExcludeFailed").addEventListener("click", () => {
  const t = state.t;
  for (const f of state.scenario.failures || []) {
    if (f.start_s <= t && t < f.end_s) state.excluded.add(f.satellite_id);
  }
  renderToggleTree();
  onExcludedChanged();
});

/* ==================== редактор конфигурации ==================== */
function renderEditor() {
  const ed = state.edited;
  if (!ed) return;
  $("cfgStage").value = String(ed.design.launch_stage);
  $("cfgIsl").value = ed.environment.isl_range_km;
  $("cfgElev").value = ed.environment.min_elevation_deg;
  renderOrbitEditor();
  $("cfgMetaInfo").textContent =
    `${ed.meta && ed.meta.title ? ed.meta.title : ""} · ${ed.design.satellites.length} КА · ` +
    `${ed.design.planes.length} плоскости · горизонт ${ed.environment.horizon_s} с, шаг ${ed.environment.step_s} с`;
  $("planesTable").querySelector("tbody").innerHTML = ed.design.planes.map((p, i) =>
    `<tr><td>${p.id}</td>
     <td><input type="number" min="0" max="359.9" step="0.5" value="${p.raan_deg}" data-plane="${i}" data-field="raan_deg"></td>
     <td><input type="number" min="0" max="359.9" step="0.5" value="${p.phase_deg}" data-plane="${i}" data-field="phase_deg"></td></tr>`
  ).join("");
  $("failuresTable").querySelector("tbody").innerHTML = (ed.failures || []).map((f, i) =>
    `<tr><td>${f.satellite_id}</td><td class="num">${f.start_s}</td><td class="num">${f.end_s}</td>
     <td><button class="btn btn-sm btn-danger" data-delfail="${i}">✕</button></td></tr>`
  ).join("");
  $("gwOutagesTable").querySelector("tbody").innerHTML = (ed.gateway_outages || []).map((o, i) =>
    `<tr><td>${o.gateway_id}</td><td class="num">${o.start_s}</td><td class="num">${o.end_s}</td>
     <td><button class="btn btn-sm btn-danger" data-delgw="${i}">✕</button></td></tr>`
  ).join("");
}

function markDirty() { state.dirty = true; updateDirtyFlag(); }
function updateDirtyFlag() { $("configDirty").hidden = !state.dirty; }

$("cfgStage").addEventListener("change", e => { state.edited.design.launch_stage = Number(e.target.value); markDirty(); });
$("cfgIsl").addEventListener("input", e => { state.edited.environment.isl_range_km = Number(e.target.value); markDirty(); });
$("cfgElev").addEventListener("input", e => { state.edited.environment.min_elevation_deg = Number(e.target.value); markDirty(); });

/* ---------- редактор орбиты ---------- */
const R_EARTH = 6371.0;

function orbitParams(env) {
  // e, перигей/апогей (км) из хранимых altitude_km (большая полуось) + eccentricity
  const ecc = env.orbit_type === "elliptical" ? Number(env.eccentricity || 0) : 0;
  const a = R_EARTH + Number(env.altitude_km);
  return {
    ecc,
    perigee: a * (1 - ecc) - R_EARTH,
    apogee: a * (1 + ecc) - R_EARTH,
    argp: Number(env.arg_perigee_deg || 0),
  };
}

function renderOrbitEditor() {
  const env = state.edited.environment;
  const ell = env.orbit_type === "elliptical";
  $("cfgOrbitType").value = ell ? "elliptical" : "circular";
  $("orbitElliptical").hidden = !ell;
  if (ell) {
    const p = orbitParams(env);
    $("cfgPerigee").value = Math.round(p.perigee);
    $("cfgEcc").value = p.ecc;
    $("cfgArgPerigee").value = p.argp;
    $("cfgOrbitDerived").textContent =
      `Большая полуось: ${Math.round((p.perigee + p.apogee) / 2)} км · апогей: ${Math.round(p.apogee)} км`;
  }
}

function applyOrbitFromUI() {
  const env = state.edited.environment;
  if ($("cfgOrbitType").value !== "elliptical") {
    env.orbit_type = "circular";
    delete env.eccentricity;
    delete env.arg_perigee_deg;
    $("orbitElliptical").hidden = true;
    markDirty();
    return;
  }
  const perigee = Number($("cfgPerigee").value);
  const ecc = Number($("cfgEcc").value);
  const argp = Number($("cfgArgPerigee").value);
  if (!Number.isFinite(perigee) || perigee < 500) {
    toast("Перигей слишком низкий", "Ограничение: перигей не ниже 500 км.", "error");
    renderOrbitEditor();
    return;
  }
  if (!Number.isFinite(ecc) || ecc < 0 || ecc > 0.6) {
    toast("Некорректный эксцентриситет", "Допустимо 0…0.6.", "error");
    renderOrbitEditor();
    return;
  }
  const r_p = R_EARTH + perigee;
  const a = r_p / (1 - ecc); // перигей и e задают большую полуось
  env.orbit_type = "elliptical";
  env.eccentricity = ecc;
  env.arg_perigee_deg = Number.isFinite(argp) ? argp : 0;
  env.altitude_km = Math.round((a - R_EARTH) * 100) / 100;
  $("orbitElliptical").hidden = false;
  renderOrbitEditor();
  markDirty();
}

$("cfgOrbitType").addEventListener("change", applyOrbitFromUI);
$("cfgPerigee").addEventListener("change", applyOrbitFromUI);
$("cfgEcc").addEventListener("change", applyOrbitFromUI);
$("cfgArgPerigee").addEventListener("change", applyOrbitFromUI);

$("planesTable").addEventListener("input", e => {
  const i = e.target.dataset.plane, f = e.target.dataset.field;
  if (i === undefined || !f) return;
  state.edited.design.planes[Number(i)][f] = Number(e.target.value);
  markDirty();
});

$("failuresTable").addEventListener("click", e => {
  const i = e.target.dataset.delfail;
  if (i === undefined) return;
  state.edited.failures.splice(Number(i), 1);
  renderEditor(); markDirty();
});

$("gwOutagesTable").addEventListener("click", e => {
  const i = e.target.dataset.delgw;
  if (i === undefined) return;
  state.edited.gateway_outages.splice(Number(i), 1);
  renderEditor(); markDirty();
});

$("btnAddFailure").addEventListener("click", () => {
  const sat = $("failSat").value;
  const start = Number($("failStart").value), end = Number($("failEnd").value);
  if (!sat || Number.isNaN(start) || Number.isNaN(end) || start < 0 || end <= start || end > state.horizon) {
    toast("Некорректный период", `Нужно 0 ≤ начало < конец ≤ ${state.horizon}.`, "error");
    return;
  }
  state.edited.failures.push({ satellite_id: sat, start_s: start, end_s: end });
  $("failStart").value = ""; $("failEnd").value = "";
  renderEditor(); markDirty();
});

$("btnAddGwOutage").addEventListener("click", () => {
  const gw = $("gwOutageGw").value;
  const start = Number($("gwOutageStart").value), end = Number($("gwOutageEnd").value);
  if (!gw || Number.isNaN(start) || Number.isNaN(end) || start < 0 || end <= start || end > state.horizon) {
    toast("Некорректный период", `Нужно 0 ≤ начало < конец ≤ ${state.horizon}.`, "error");
    return;
  }
  state.edited.gateway_outages.push({ gateway_id: gw, start_s: start, end_s: end });
  $("gwOutageStart").value = ""; $("gwOutageEnd").value = "";
  renderEditor(); markDirty();
});

$("btnResetConfig").addEventListener("click", () => {
  state.edited = deepCopy(state.scenario);
  state.dirty = false;
  renderEditor();
  updateDirtyFlag();
  toast("Изменения сброшены", "В редакторе — исходная конфигурация сценария.");
});

function safeName(base) {
  return base.replace(/[^\w.-]+/g, "_").replace(/^\.+/, "") || "variant";
}

async function uploadScenario(filename, scenario) {
  return api("/api/data/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, scenario }),
  });
}

$("btnApplyVariant").addEventListener("click", async () => {
  if (!state.edited) return;
  const base = safeName((state.edited.meta && state.edited.meta.id) || "scenario");
  const filename = `${base}_mod_${Date.now()}.json`;
  showSpinner("Загрузка варианта и валидация…");
  try {
    const res = await uploadScenario(filename, state.edited);
    hideSpinner();
    if (!res.valid) {
      toast("Вариант не прошёл валидацию", "Исправьте ошибки:", "error", res.errors);
      return;
    }
    toast("Вариант применён", `Сохранён как ${res.filename}. Открыт новый сценарий.`);
    await loadFiles();
    $("fileSelect").value = res.filename;
    await loadScenario(res.filename);
  } catch (e) {
    hideSpinner();
    const errors = e.body && e.body.errors;
    toast("Ошибка загрузки варианта", errors ? "Исправьте ошибки:" : e.message, "error", errors);
  }
});

/* ==================== загрузка / скачивание файлов ==================== */
$("btnUpload").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", e => {
  if (e.target.files[0]) uploadFile(e.target.files[0]);
  e.target.value = "";
});
$("btnDownload").addEventListener("click", () => {
  if (state.file) window.open(`/api/download/${encodeURIComponent(state.file)}`, "_blank");
});

async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  showSpinner(`Загрузка ${file.name}…`);
  try {
    const res = await api("/api/data/upload", { method: "POST", body: fd });
    hideSpinner();
    if (!res.valid) {
      toast("Файл не прошёл валидацию", "Что исправить:", "error", res.errors);
      return;
    }
    toast("Сценарий загружен", res.filename);
    await loadFiles();
    $("fileSelect").value = res.filename;
    await loadScenario(res.filename);
  } catch (e) {
    hideSpinner();
    const errors = e.body && e.body.errors;
    toast("Ошибка загрузки файла", errors ? "Что исправить:" : e.message, "error", errors);
  }
}

(function bindDrop() {
  let depth = 0;
  window.addEventListener("dragenter", e => { e.preventDefault(); depth++; $("dropOverlay").hidden = false; });
  window.addEventListener("dragleave", e => { e.preventDefault(); if (--depth <= 0) { depth = 0; $("dropOverlay").hidden = true; } });
  window.addEventListener("dragover", e => e.preventDefault());
  window.addEventListener("drop", e => {
    e.preventDefault();
    depth = 0;
    $("dropOverlay").hidden = true;
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
})();

$("fileSelect").addEventListener("change", e => loadScenario(e.target.value));

/* ==================== вкладки ==================== */
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-page").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "compare") renderVariantsList();
    if (btn.dataset.tab === "modeling" && scene) scene._resize();
  });
});

document.querySelectorAll(".side-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".side-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".side-page").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $(`side-${btn.dataset.side}`).classList.add("active");
  });
});

/* ==================== сравнение вариантов ==================== */
const VARIANTS_KEY = "bzd_variants";

function getVariants() {
  try { return JSON.parse(localStorage.getItem(VARIANTS_KEY)) || []; }
  catch (e) { return []; }
}
function setVariants(v) { localStorage.setItem(VARIANTS_KEY, JSON.stringify(v)); }

function renderVariantsList() {
  const vs = getVariants();
  const box = $("variantsList");
  $("cmpA").innerHTML = vs.map((v, i) => `<option value="${i}">${v.name}</option>`).join("");
  $("cmpB").innerHTML = vs.map((v, i) => `<option value="${i}">${v.name}</option>`).join("");
  if (vs.length > 1) $("cmpB").value = "1";
  if (!vs.length) {
    box.className = "variants-list muted";
    box.textContent = "Нет сохранённых вариантов.";
    return;
  }
  box.className = "variants-list";
  box.innerHTML = vs.map((v, i) =>
    `<div class="variant-item">
      <span class="v-name">${v.name}</span>
      <span class="v-meta">${v.filename} · stage ${v.scenario.design.launch_stage} · ` +
      `${(v.scenario.failures || []).length} отказов · ${new Date(v.savedAt).toLocaleString("ru-RU")}</span>
      <span class="v-actions">
        <button class="btn btn-sm" data-loadvar="${i}">В редактор</button>
        <button class="btn btn-sm btn-danger" data-delvar="${i}">✕</button>
      </span>
    </div>`).join("");
}

$("variantsList").addEventListener("click", async e => {
  const iLoad = e.target.dataset.loadvar, iDel = e.target.dataset.delvar;
  if (iDel !== undefined) {
    const vs = getVariants();
    vs.splice(Number(iDel), 1);
    setVariants(vs);
    renderVariantsList();
    return;
  }
  if (iLoad !== undefined) {
    const v = getVariants()[Number(iLoad)];
    if (!v) return;
    await loadFiles();
    if (state.files.includes(v.filename)) {
      $("fileSelect").value = v.filename;
      await loadScenario(v.filename);
      document.querySelector('.tab[data-tab="config"]').click();
      toast("Вариант загружен в редактор", v.name);
    } else {
      toast("Файл варианта не найден на сервере", v.filename, "error");
    }
  }
});

$("btnSaveVariant").addEventListener("click", async () => {
  if (!state.edited) return;
  const name = $("variantName").value.trim() || `Вариант ${new Date().toLocaleString("ru-RU")}`;
  const base = safeName((state.edited.meta && state.edited.meta.id) || "scenario");
  const filename = `${base}_${safeName(name)}_${Date.now()}.json`;
  showSpinner("Сохранение варианта: загрузка и расчёт показателей…");
  try {
    const res = await uploadScenario(filename, state.edited);
    if (!res.valid) {
      hideSpinner();
      toast("Вариант не прошёл валидацию", "Исправьте ошибки:", "error", res.errors);
      return;
    }
    const metrics = {};
    const gw = state.gateways[0];
    for (const cid of state.clients) {
      try {
        const tl = await api(`/api/route-timeline/${encodeURIComponent(filename)}/${cid}/${gw}?strategy=hops&step_sample=12`);
        metrics[cid] = {
          availability: tl.availability,
          outage_count: tl.outage_count,
          max_outage_s: tl.max_outage_s,
          meets_target: tl.availability >= state.edited.environment.target_availability,
        };
      } catch (e) { metrics[cid] = null; }
    }
    const vs = getVariants();
    vs.push({
      name, filename, savedAt: Date.now(),
      scenario: deepCopy(state.edited),
      metrics,
      availability: state.availability,
    });
    setVariants(vs);
    hideSpinner();
    $("variantName").value = "";
    renderVariantsList();
    toast("Вариант сохранён", `${name} — теперь его можно сравнивать.`);
  } catch (e) {
    hideSpinner();
    const errors = e.body && e.body.errors;
    toast("Ошибка сохранения варианта", errors ? "Исправьте ошибки:" : e.message, "error", errors);
  }
});

$("btnCompare").addEventListener("click", () => {
  const vs = getVariants();
  const a = vs[Number($("cmpA").value)], b = vs[Number($("cmpB").value)];
  if (!a || !b) { toast("Нужно два варианта", "Сохраните хотя бы два варианта конфигурации.", "warn"); return; }
  renderComparison(a, b);
});

function renderComparison(a, b) {
  const env = s => s.environment, d = s => s.design;
  const rows = [];
  const addRow = (label, va, vb) => rows.push({ label, va, vb, diff: String(va) !== String(vb) });
  addRow("Очередь запуска (launch_stage)", d(a.scenario).launch_stage, d(b.scenario).launch_stage);
  addRow("Дальность ISL, км", env(a.scenario).isl_range_km, env(b.scenario).isl_range_km);
  addRow("Мин. угол места, °", env(a.scenario).min_elevation_deg, env(b.scenario).min_elevation_deg);
  const planesA = d(a.scenario).planes, planesB = d(b.scenario).planes;
  for (let i = 0; i < Math.max(planesA.length, planesB.length); i++) {
    const pa = planesA[i], pb = planesB[i];
    addRow(`Плоскость ${(pa || pb).id} RAAN, °`, pa ? pa.raan_deg : "—", pb ? pb.raan_deg : "—");
    addRow(`Плоскость ${(pa || pb).id} фаза, °`, pa ? pa.phase_deg : "—", pb ? pb.phase_deg : "—");
  }
  addRow("Периодов отказа спутников", (a.scenario.failures || []).length, (b.scenario.failures || []).length);
  addRow("Периодов отказа шлюзов", (a.scenario.gateway_outages || []).length, (b.scenario.gateway_outages || []).length);

  const target = env(a.scenario).target_availability ?? 0.9;
  const clients = Array.from(new Set([...Object.keys(a.metrics || {}), ...Object.keys(b.metrics || {})]));

  let html = `<h3 class="muted" style="margin:10px 0 6px">Различия конфигураций</h3>
  <table class="tbl"><thead><tr><th>Параметр</th><th>${a.name}</th><th>${b.name}</th></tr></thead><tbody>`;
  for (const r of rows) {
    html += `<tr class="${r.diff ? "diff" : ""}"><td>${r.label}</td>
      <td class="num">${r.va}</td><td class="num">${r.vb}</td></tr>`;
  }
  html += `</tbody></table>`;

  html += `<h3 class="muted" style="margin:14px 0 6px">Итоговые показатели (целевая доступность ≥ ${target})</h3>`;
  if (!clients.length) {
    html += `<p class="muted">Нет рассчитанных метрик у сохранённых вариантов — пересохраните их.</p>`;
  } else {
    html += `<table class="tbl"><thead><tr><th>Показатель</th><th>${a.name}</th><th>${b.name}</th></tr></thead><tbody>`;
    for (const cid of clients) {
      const ma = a.metrics && a.metrics[cid], mb = b.metrics && b.metrics[cid];
      if (ma && mb) {
        const bestA = ma.availability >= mb.availability;
        html += `<tr><td>Доступность ${cid}</td>
          <td class="num" style="${bestA ? "color:var(--ok);font-weight:600" : ""}">${(ma.availability * 100).toFixed(1)}% ${ma.meets_target ? "✓" : "✗"}</td>
          <td class="num" style="${!bestA ? "color:var(--ok);font-weight:600" : ""}">${(mb.availability * 100).toFixed(1)}% ${mb.meets_target ? "✓" : "✗"}</td></tr>`;
        html += `<tr><td>Перерывов ${cid}</td><td class="num">${ma.outage_count}</td><td class="num">${mb.outage_count}</td></tr>`;
        html += `<tr><td>Макс. перерыв ${cid}, с</td><td class="num">${fmtNum(ma.max_outage_s, 0)}</td><td class="num">${fmtNum(mb.max_outage_s, 0)}</td></tr>`;
      } else {
        html += `<tr><td>Доступность ${cid}</td><td class="num">${ma ? (ma.availability * 100).toFixed(1) + "%" : "нет данных"}</td>
          <td class="num">${mb ? (mb.availability * 100).toFixed(1) + "%" : "нет данных"}</td></tr>`;
      }
    }
    html += `</tbody></table>`;
  }

  html += `<div class="cmp-reco"><b>Рекомендация.</b> ${buildRecommendation(a, b, clients, target)}</div>`;
  $("cmpResults").innerHTML = html;
}

function buildRecommendation(a, b, clients, target) {
  if (!clients.length) return "Рассчитайте и сохраните варианты повторно — тогда здесь появится обоснование.";
  const valid = clients.filter(c => a.metrics && a.metrics[c] && b.metrics && b.metrics[c]);
  if (!valid.length) return "Недостаточно данных для обоснования.";
  const avgA = valid.reduce((s, c) => s + a.metrics[c].availability, 0) / valid.length;
  const avgB = valid.reduce((s, c) => s + b.metrics[c].availability, 0) / valid.length;
  const win = avgA >= avgB ? a : b;
  const lose = avgA >= avgB ? b : a;
  const avgWin = Math.max(avgA, avgB), avgLose = Math.min(avgA, avgB);
  const allMeet = valid.every(c => win.metrics[c].meets_target);
  const outagesWin = valid.reduce((s, c) => s + win.metrics[c].outage_count, 0);
  const outagesLose = valid.reduce((s, c) => s + lose.metrics[c].outage_count, 0);
  let text = `Вариант «${win.name}» обеспечивает среднюю доступность ${(avgWin * 100).toFixed(1)}% ` +
    `против ${(avgLose * 100).toFixed(1)}% у «${lose.name}» ` +
    `(+${((avgWin - avgLose) * 100).toFixed(1)} п.п.), суммарно ${outagesWin} перерывов против ${outagesLose}. `;
  if (allMeet) {
    text += `Для всех клиентов целевой уровень ${(target * 100).toFixed(0)}% достигается, ` +
      `поэтому рекомендуется конфигурация «${win.name}».`;
  } else {
    const badClients = valid.filter(c => !win.metrics[c].meets_target).join(", ");
    text += `Однако целевой уровень ${(target * 100).toFixed(0)}% не достигается для: ${badClients}. ` +
      `Рекомендуется доработать конфигурацию (состав плоскостей, дальность ISL, очерёдность запуска).`;
  }
  return text;
}

/* ==================== эксперименты ==================== */
$("btnMonteCarlo").addEventListener("click", async () => {
  if (!state.file) return;
  const trials = Number($("mcTrials").value) || 100;
  const mode = $("mcMode").value;
  const k = Number($("mcK").value) || 10;
  showSpinner(`Монте-Карло: ${trials} испытаний…`);
  try {
    const res = await api(`/api/monte-carlo/${encodeURIComponent(state.file)}?trials=${trials}&mode=${mode}&k=${k}`);
    state.mcResult = res;
    let html = `<p class="muted small">${res.n_trials} испытаний, режим «${res.mode === "poisson" ? "Пуассон" : "фиксированное k=" + k}», цель ≥ ${res.target_availability}</p>`;
    for (const [cid, r] of Object.entries(res.clients)) {
      const risk = 1 - r.prob_meets_target;
      html += `<div class="avail-card ${r.prob_meets_target >= 0.5 ? "meets" : "not-meets"}">
        <h3>${cid}<span class="badge ${r.prob_meets_target >= 0.9 ? "ok" : r.prob_meets_target >= 0.5 ? "" : "bad"}">
          риск ниже цели: ${(risk * 100).toFixed(0)}%</span></h3>
        <div class="detail">средняя доступность ${(r.mean_availability * 100).toFixed(1)}%
          (σ ${(r.std_availability * 100).toFixed(2)}) · медиана ${(r.p50_median * 100).toFixed(1)}%
          · 5% квантиль ${(r.p05 * 100).toFixed(1)}% · худший случай ${(r.worst_case * 100).toFixed(1)}%<br>
          перерывов в среднем ${fmtNum(r.mean_outage_count, 1)} · макс. ${fmtNum(r.mean_max_outage_s, 0)} с</div>
      </div>`;
    }
    $("mcResults").innerHTML = html;
  } catch (e) {
    toast("Ошибка Монте-Карло", e.message, "error");
  } finally {
    hideSpinner();
  }
});

$("btnExpTop").addEventListener("click", async () => {
  if (!state.file) return;
  const n = Number($("expTopN").value) || 5;
  showSpinner("Расчёт критичности…");
  try {
    const res = await api(`/api/criticality/${encodeURIComponent(state.file)}?step_sample=6&strategy=hops`);
    const top = res.criticality.slice(0, n).map(c => c.satellite);
    $("expSats").value = top.join(", ");
    toast("Подставлены критичные аппараты", top.join(", "));
  } catch (e) {
    toast("Ошибка анализа критичности", e.message, "error");
  } finally {
    hideSpinner();
  }
});

$("btnExperiment").addEventListener("click", async () => {
  if (!state.file) return;
  const ids = $("expSats").value.split(",").map(s => s.trim()).filter(Boolean);
  if (!ids.length) { toast("Укажите аппараты", "Введите id через запятую или подставьте топ-N.", "warn"); return; }
  const strategy = $("expStrategy").value;
  const gw = state.gateways[0];
  const target = state.scenario.environment.target_availability;
  showSpinner("Эксперимент: пересчёт доступности без выбранных аппаратов…");
  try {
    const rows = [];
    const clients = [$("expClient").value || state.clients[0]];
    for (const cid of clients) {
      const base = await api(`/api/route-timeline/${encodeURIComponent(state.file)}/${cid}/${gw}?strategy=${strategy}&step_sample=12`);
      const excl = await api(`/api/route-timeline/${encodeURIComponent(state.file)}/${cid}/${gw}?strategy=${strategy}&step_sample=12&exclude=${encodeURIComponent(ids.join(","))}`);
      rows.push({ cid, base, excl });
    }
    let html = `<p class="muted small">Отключены: <span style="color:var(--bad)">${ids.join(", ")}</span> · стратегия ${strategy} · шлюз ${gw}</p>
    <table class="exp-table"><thead><tr>
      <th>Клиент</th><th>Доступность до</th><th>после</th><th>Δ</th>
      <th>Перерывов до/после</th><th>Макс. перерыв до/после, с</th><th>Цель ≥ ${target}</th>
    </tr></thead><tbody>`;
    for (const { cid, base, excl } of rows) {
      const delta = (excl.availability - base.availability) * 100;
      const stillMeets = excl.availability >= target;
      html += `<tr><td>${cid}</td>
        <td>${(base.availability * 100).toFixed(1)}%</td>
        <td class="${delta < 0 ? "worse" : "same"}">${(excl.availability * 100).toFixed(1)}%</td>
        <td class="${delta < 0 ? "worse" : "same"}">${delta >= 0 ? "+" : ""}${delta.toFixed(1)} п.п.</td>
        <td>${base.outage_count} / ${excl.outage_count}</td>
        <td>${fmtNum(base.max_outage_s, 0)} / ${fmtNum(excl.max_outage_s, 0)}</td>
        <td class="${stillMeets ? "same" : "worse"}">${stillMeets ? "маршрут сохраняется" : "ниже цели"}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    const worst = rows[0];
    const lostRoutes = worst.base.availability - worst.excl.availability;
    html += `<div class="cmp-reco"><b>Вывод.</b> При отключении ${ids.length} аппаратов доступность ${worst.cid} ` +
      (lostRoutes > 0
        ? `снизилась на ${(lostRoutes * 100).toFixed(1)} п.п. — направление связи затронуто.`
        : "не изменилась — направление связи сохраняется за счёт резервных маршрутов.") +
      ` См. диаграмму доступности на вкладке «Моделирование» для детализации перерывов.</div>`;
    $("expResults").innerHTML = html;
  } catch (e) {
    toast("Ошибка эксперимента", e.message, "error");
  } finally {
    hideSpinner();
  }
});

$("btnCriticality").addEventListener("click", async () => {
  if (!state.file) return;
  showSpinner("Анализ критичности аппаратов…");
  try {
    const res = await api(`/api/criticality/${encodeURIComponent(state.file)}?step_sample=6&strategy=hops`);
    const max = Math.max(1, ...res.criticality.map(c => c.failures_caused));
    let html = `<p class="muted small">Стратегия ${res.strategy}, шаг выборки ${res.step_sample}. Эти аппараты чаще всего разрывают связь — их отказ критичен для сети.</p>`;
    for (const c of res.criticality) {
      const w = (c.failures_caused / max * 100).toFixed(1);
      html += `<div class="bar-row"><span>${c.satellite}</span>
        <div class="bar-track"><div class="bar-fill ${c.failures_caused >= max ? "bad" : "warn"}" style="width:${w}%"></div></div>
        <span class="bar-val">${c.failures_caused}</span></div>`;
    }
    $("critResults").innerHTML = html;
  } catch (e) {
    toast("Ошибка анализа критичности", e.message, "error");
  } finally {
    hideSpinner();
  }
});

/* ==================== отчёты и выгрузки ==================== */
$("btnAvailability").addEventListener("click", async () => {
  if (!state.file) return;
  showSpinner("Полный расчёт доступности (30–60 с)…");
  try {
    const res = await api(`/api/availability/${encodeURIComponent(state.file)}`);
    state.availability = res;
    renderAvailability(res);
    updateReportSummary();
  } catch (e) {
    toast("Ошибка расчёта доступности", e.message, "error");
  } finally {
    hideSpinner();
  }
});

function renderAvailability(res) {
  const target = res.target_availability;
  $("targetAvail").textContent = target;
  let html = "";
  for (const [cid, r] of Object.entries(res.clients)) {
    const pct = (r.availability * 100).toFixed(1);
    const w = Math.min(100, r.availability * 100);
    html += `<div class="avail-card ${r.meets_target ? "meets" : "not-meets"}">
      <h3>${cid}<span class="badge ${r.meets_target ? "ok" : "bad"}">${r.meets_target ? "цель достигнута" : "ниже цели"}</span></h3>
      <div class="bar-row"><span></span>
        <div class="bar-track"><div class="bar-fill ${r.meets_target ? "" : "bad"}" style="width:${w}%"></div>
        <div class="bar-target" style="left:${target * 100}%"></div></div>
        <span class="bar-val">${pct}%</span></div>
      <div class="detail">средняя относительная ёмкость ${(r.avg_relative_capacity * 100).toFixed(1)}% ·
        доступно шагов ${r.up_steps}/${r.total_steps}</div>
    </div>`;
  }
  $("availabilityResults").innerHTML = html;
}

function collectReport() {
  const s = state.scenario || {};
  const report = {
    generated_at: new Date().toISOString(),
    service: "СПУТНИК·АРКТИК — проектирование устойчивой спутниковой группировки",
    scenario_file: state.file,
    meta: s.meta,
    environment: s.environment,
    configuration: {
      launch_stage: s.design && s.design.launch_stage,
      planes: s.design && s.design.planes,
      satellites_count: s.design ? s.design.satellites.length : null,
      failures: s.failures,
      gateway_outages: s.gateway_outages,
      excluded_by_toggles: excludeIds(),
    },
    current_time_s: state.t,
    route_at_t: state.route,
    timeline_current_client: state.timeline ? {
      client: state.timeline.client,
      gateway: state.timeline.gateway,
      strategy: state.timeline.strategy,
      availability: state.timeline.availability,
      outage_count: state.timeline.outage_count,
      max_outage_s: state.timeline.max_outage_s,
      outages: state.timeline.outages,
    } : null,
    availability_full: state.availability,
    monte_carlo: state.mcResult,
  };
  return report;
}

function updateReportSummary() {
  if (!state.scenario) return;
  const s = state.scenario;
  const parts = [];
  parts.push(`<b>Сценарий:</b> ${state.file} — ${s.meta && s.meta.title || ""}. ` +
    `Группировка: ${s.design.satellites.length} КА, ${s.design.planes.length} плоскости, ` +
    `этап развёртывания ${s.design.launch_stage}, высота ${s.environment.altitude_km} км, ` +
    `наклонение ${s.environment.inclination_deg}°, ISL ≤ ${s.environment.isl_range_km} км, ` +
    `мин. угол места ${s.environment.min_elevation_deg}°.`);
  if (state.excluded.size) parts.push(`<b>Выключены тумблерами:</b> ${excludeIds().join(", ")}.`);
  if (state.route) {
    parts.push(state.route.connected
      ? `<b>Маршрут (${state.route.client} → ${state.route.gateway}, t=${fmtTime(state.t)}):</b> ` +
        `${state.route.path.join(" → ")} · ${state.route.hops} переходов · ` +
        `${fmtNum(state.route.latency_ms, 2)} мс · ${fmtNum(state.route.total_dist_km, 0)} км.`
      : `<b>Маршрут (${state.route.client} → ${state.route.gateway}, t=${fmtTime(state.t)}):</b> ` +
        `отсутствует — ${state.route.reason_text}.`);
  }
  if (state.timeline) {
    parts.push(`<b>Доступность ${state.timeline.client}:</b> ` +
      `${(state.timeline.availability * 100).toFixed(1)}%, перерывов ${state.timeline.outage_count}, ` +
      `максимальный ${fmtNum(state.timeline.max_outage_s, 0)} с.`);
  }
  if (state.availability) {
    const rows = Object.entries(state.availability.clients).map(([cid, r]) =>
      `${cid}: ${(r.availability * 100).toFixed(1)}% ${r.meets_target ? "(цель достигнута)" : "(ниже цели)"}`).join("; ");
    parts.push(`<b>Доступность (полный расчёт):</b> ${rows}.`);
  }
  $("reportSummary").innerHTML = parts.map(p => `<p style="margin:6px 0">${p}</p>`).join("");
}

$("btnReportJson").addEventListener("click", () => {
  if (!state.scenario) { toast("Нет данных", "Загрузите сценарий.", "warn"); return; }
  const name = `report_${safeName(state.file || "scenario")}.json`;
  downloadBlob(name, JSON.stringify(collectReport(), null, 2), "application/json");
  toast("Отчёт выгружен", name);
});

$("btnAvailabilityCsv").addEventListener("click", () => {
  if (!state.availability) {
    toast("Нет данных о доступности", "Сначала рассчитайте доступность на этой вкладке.", "warn");
    return;
  }
  const lines = ["client;availability;meets_target;up_steps;total_steps"];
  for (const [cid, r] of Object.entries(state.availability.clients)) {
    lines.push(`${cid};${r.availability};${r.meets_target};${r.up_steps};${r.total_steps}`);
  }
  downloadBlob(`availability_${safeName(state.file || "scenario")}.csv`, lines.join("\n"), "text/csv");
  toast("CSV выгружен", "Доступность по клиентам.");
});

$("btnReportPrint").addEventListener("click", () => {
  if (!state.scenario) { toast("Нет данных", "Загрузите сценарий.", "warn"); return; }
  updateReportSummary();
  window.print();
});

$("btnExportSnapshot").addEventListener("click", () => {
  if (!state.snapshot) { toast("Нет снапшота", "Дождитесь расчёта.", "warn"); return; }
  const payload = {
    file: state.file, t_s: state.t,
    excluded: excludeIds(),
    snapshot: state.snapshot,
  };
  downloadBlob(`snapshot_${safeName(state.file)}_t${state.t}.json`,
    JSON.stringify(payload, null, 2), "application/json");
  toast("Снапшот выгружен", `t = ${fmtTime(state.t)}`);
});

$("btnExportRoute").addEventListener("click", () => {
  if (!state.route) { toast("Нет маршрута", "Постройте маршрут кнопкой «Построить маршрут в момент t».", "warn"); return; }
  downloadBlob(`route_${safeName(state.file)}_t${state.t}.json`,
    JSON.stringify({ file: state.file, ...state.route }, null, 2), "application/json");
  toast("Маршрут выгружен", state.route.connected ? state.route.path.join(" → ") : "связь отсутствует");
});

/* ==================== связывание событий ==================== */
$("btnRoute").addEventListener("click", buildRoute);
$("availClient").addEventListener("change", loadTimeline);
$("routeStrategy").addEventListener("change", loadTimeline);
$("routeClient").addEventListener("change", () => { /* клиент маршрута независим от диаграммы */ });
$("btnResetView").addEventListener("click", () => scene && scene.resetView());
window.addEventListener("resize", () => drawAvailability());

/* ==================== запуск ==================== */
(async function init() {
  scene = new Scene3D($("viewport"));
  bindSceneEvents();
  try {
    const health = await api("/api/health");
    const badge = $("healthBadge");
    if (health.status === "healthy" && health.modules_available) {
      badge.textContent = "бэкенд ✓";
      badge.className = "health ok";
    } else {
      badge.textContent = "модули недоступны";
      badge.className = "health bad";
    }
  } catch (e) {
    const badge = $("healthBadge");
    badge.textContent = "бэкенд недоступен";
    badge.className = "health bad";
    toast("Бэкенд недоступен", "Проверьте, что сервер запущен (порт 5002).", "error");
  }
  try {
    await loadFiles();
    if (state.file) await loadScenario(state.file);
  } catch (e) {
    toast("Ошибка инициализации", e.message, "error");
  }
  updateReportSummary();
})();
