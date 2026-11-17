// H3 cell layers (CRC Open hazards, ERA5 baseline, hail and gust curves), moved from site/app.js.
import { $, state, api, esc, H3HexagonLayer, layerById, layersOfSource, inRegion, horizonLabel, picked, fileKey, display, unitOf, fmt, fmtTick, quantile, fetchJSON, horizonsOf, ramp, colorAt, gradient, rgbCss, NODATA, kv, openDetail, latLon, ticksBetween } from "./core.js";
import { drawCurve } from "./charts.js";

export async function loadFile(hazard, horizon) {
  const key = fileKey(hazard, horizon);
  if (!state.files.has(key)) {
    const layer = layerById(hazard); const raw = await fetchJSON(layer.file.replace("{horizon}", horizon));
    // a file may hold several value sets over the same cells; a layer then names its `field`
    const f = layer.field ? raw.fields[layer.field] : null; if (layer.field && !f) throw new Error(`${layer.file} has no field ${layer.field}`);
    // such a file may leave out the first return periods (`values_from`); they read as no value
    const pad = Array(raw.values_from || 0).fill(null);
    state.files.set(key, f ? { ...raw, values: pad.length ? f.values.map((r) => pad.concat(r)) : f.values, unit: f.unit, value_semantics: f.semantics } : raw);
  }
  return state.files.get(key);
}
export function buildCellControls() {
  const { catalog } = state; const sel = $("hazard"); sel.innerHTML = "";
  const own = layersOfSource(state.source).filter((l) => l.kind === "h3-cells" && inRegion(l));
  if (state.source === "crc_open") {
    const loaded = own.map((l) => l.id);
    const g1 = document.createElement("optgroup"); g1.label = `Loaded (${loaded.length})`;
    for (const id of loaded) g1.append(new Option(`${layerById(id).title} · ${id}`, id));
    const rest = Object.keys(catalog.hazards).filter((h) => !loaded.includes(h));
    const g2 = document.createElement("optgroup"); g2.label = `In the release, not loaded yet (${rest.length})`;
    for (const id of rest) { const o = new Option(`${id} · ${catalog.hazards[id].value_semantics} (not loaded yet)`, id); o.disabled = true; g2.append(o); }
    sel.append(g1, g2);
  } else if (picked().length) {
    // a source with many layers: first the area, then what to show, then the few layers that are left
    const all = picked(); const now = layerById(state.hazard); const whats = state.registry.whats || {};
    const area = $("area"); area.innerHTML = ""; for (const g of [...new Set(all.map((l) => l.group))]) area.append(new Option(g, g)); area.value = now.group;
    const inArea = all.filter((l) => l.group === now.group);
    const what = $("what"); what.innerHTML = ""; for (const w of [...new Set(inArea.map((l) => l.what))]) what.append(new Option(whats[w] || w, w)); what.value = now.what;
    const groups = new Map();
    for (const l of inArea.filter((x) => x.what === now.what)) {
      if (!l.finding) { sel.append(new Option(l.title, l.id)); continue; }
      if (!groups.has(l.finding)) { const g = document.createElement("optgroup"); g.label = l.finding; groups.set(l.finding, g); sel.append(g); }
      groups.get(l.finding).append(new Option(l.title, l.id));
    }
  } else for (const l of own) sel.append(new Option(l.title, l.id));
  sel.value = state.hazard;
  const grouped = picked().length > 0;
  $("pick-row").classList.toggle("hidden", !grouped); $("layer-steps").classList.toggle("hidden", !grouped || sel.options.length < 2);
  $("hazard-label").firstElementChild.textContent = grouped ? "Layer" : "Hazard";
  $("layer-count").textContent = grouped ? `${[...sel.options].findIndex((o) => o.value === state.hazard) + 1} of ${sel.options.length}` : "";
  const hz = $("horizon"); hz.innerHTML = "";
  for (const y of horizonsOf(layerById(state.hazard))) hz.append(new Option(horizonLabel(layerById(state.hazard), y), y));
  hz.value = state.horizon;
  const rp = $("rp"); rp.innerHTML = "";
  for (const t of state.manifest.return_periods) rp.append(new Option(`1 in ${t} years`, t));
  rp.value = state.rp; $("lock").checked = state.locked;
}
function computeDomain(payload, rpIndex, layer) {
  const vals = payload.values.map((r) => r[rpIndex]).filter((v) => v !== null).map((v) => display(layer, v)).sort((a, b) => a - b);
  let lo = quantile(vals, 0.02), hi = quantile(vals, 0.98);
  if (!(hi > lo)) { lo = vals[0] ?? 0; hi = vals[vals.length - 1] ?? 1; if (!(hi > lo)) hi = lo + 1; }
  return [lo, hi, vals.length];
}
export function cellsLayer(layer, payload) {
  const rpIndex = state.manifest.return_periods.indexOf(state.rp);
  if (!state.locked || !state.domain) state.domain = computeDomain(payload, rpIndex, layer);
  const [lo, hi] = state.domain; const stops = ramp(layer.style);
  const color = (i) => { const v = payload.values[i][rpIndex]; return v === null ? NODATA : colorAt(stops, (display(layer, v) - lo) / (hi - lo)); };
  return new H3HexagonLayer({
    id: "cells", data: payload.values.map((_, i) => i), getHexagon: (i) => payload.cells[i], getFillColor: color,
    filled: true, stroked: false, extruded: false, highPrecision: false, pickable: true, opacity: 1,
    updateTriggers: { getFillColor: [state.hazard, state.horizon, state.rp, lo, hi], getHexagon: [state.hazard, state.horizon] },
    onClick: (info) => { showDetail(info.index); api.drawFrame(); return true; },
  });
}
// Legend for the map: the ramp with numeric ticks in the displayed unit, the period, and what grey means.
export function cellsLegend(layer, payload) {
  const [lo, hi, n] = state.domain; const stops = ramp(layer.style);
  const years = layer.title.match(/\d{4}\s*[–-]\s*\d{4}/);
  const period = layer.period ? layer.period : state.source === "crc_open" ? `Projection for ${state.horizon}, pathway ${payload.pathway}` : years ? `Data period ${years[0]}` : `Horizon ${state.horizon}`;
  const ticks = ticksBetween(lo, hi).map(fmtTick); ticks[0] = `≤ ${ticks[0]}`; ticks[ticks.length - 1] = `≥ ${ticks[ticks.length - 1]}`;
  const none = payload.cells.length - n;
  return {
    title: layer.title.replace(/\s*\((reports, )?\d{4}\s*[–-]\s*\d{4}\)/, ""), unit: `${unitOf(layer, payload)} · ${layer.rp_label ? layer.rp_label.replace("{rp}", state.rp) : `value reached 1 year in ${state.rp}`}`,
    ramps: [{ css: gradient(stops), ticks }], rows: none ? [{ color: rgbCss(NODATA), shape: "box", label: "no value at this return period", n: none }] : [],
    foot: `${period}. ${n.toLocaleString("en-US")} cells; scale spans their 2nd–98th percentile${state.locked ? " (kept from the earlier view)" : ""}. ${layer.foot || "Regional screening."}`,
  };
}
export function cellHover(index) {
  const payload = state.files.get(fileKey(state.hazard, state.horizon)); const layer = layerById(state.hazard);
  const i = state.manifest.return_periods.indexOf(state.rp); const v = payload.values[index][i];
  const kind = payload.kinds[payload.params[index][0]];
  const head = v === null ? `no value <span>(${esc(kind === "no_data" ? payload.params[index][1] : "outside tabulated support")})</span>` : `<b>${fmt(display(layer, v))} ${esc(unitOf(layer, payload))}</b>`;
  return `${head}<br>${esc(layer.title.split(" (")[0])}<br><span>1 in ${state.rp} years · ${esc(horizonLabel(layer, state.horizon))} · cell ${payload.cells[index]} · ${esc(kind)}</span>`;
}
export function showDetail(index) {
  const payload = state.files.get(fileKey(state.hazard, state.horizon)); const layer = layerById(state.hazard);
  state.selected = { hazard: state.hazard, horizon: state.horizon, index };
  state.pick = { kind: "cell", cell: payload.cells[index] };
  const unit = unitOf(layer, payload); const rps = payload.return_periods; const vals = payload.values[index].map((v) => display(layer, v));
  const p = payload.params[index]; const kind = payload.kinds[p[0]];
  const centre = globalThis.h3.cellToLatLng(payload.cells[index]);
  openDetail(layer.title, `${horizonLabel(layer, state.horizon)} · ${layer.source}`);
  const at = vals[rps.indexOf(state.rp)];
  $("detail-meta").innerHTML = kv([[`1 in ${state.rp} years`, `<span class="big">${fmt(at)}</span> <small>${esc(unit)}</small>`], ["Cell", `${payload.cells[index]} <small>H3 r${payload.h3_resolution}</small>`], ["Centre", latLon(centre[0], centre[1])], [layer.kind_label || "Curve kind", esc(kind)], [layer.param_label || "Family / reason", esc(p[1])], ["Pathway", esc(payload.pathway)]], true);
  const params = kind === "fitted" || kind === "hurdle" ? [["location", p[2]], ["scale", p[3]], ["shape", p[4]]] : kind === "point_mass" ? [["value", p[2]]] : kind === "tabulated" ? [["knots", p[2]]] : [];
  if (kind === "hurdle") params.push(["atom probability", p[5]], ["atom location", p[6]]);
  $("detail-params").innerHTML = params.length ? kv([`Raw parameters (${payload.unit}, as shipped)`, ...params.map(([k, v]) => [k, v === null ? "–" : String(v)])]) : "";
  $("detail-table").innerHTML = `<tr><th>Return period</th><th class="num">Non-exceedance</th><th class="num">${esc(unit)}</th></tr>` + rps.map((t, i) => `<tr class="${t === state.rp ? "sel" : ""}"><td>1 in ${t} years</td><td class="num">${payload.probabilities[i]}</td><td class="num">${fmt(vals[i])}</td></tr>`).join("");
  $("detail-foot").textContent = layer.detail_foot || "Regional screening: a cell is an average, not a site. Values are the curve crc-sdk evaluated at these return periods during the data build; the page draws them and interpolates between.";
  drawCurve(rps, vals, unit, ramp(layer.style));
}
