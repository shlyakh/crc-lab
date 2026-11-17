// Source validation page: everything shown comes from data/inventory.json, which is generated
// by `python -m data_source_check.build`. Nothing is computed here beyond counting and filtering.

const TIERS = ["exploration", "verification", "validation"];
const ST_CLASS = { "assessed": "assessed", "in progress": "progress", "not possible": "impossible" };

const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v; else if (k === "text") node.textContent = v; else node.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) node.append(kid);
  return node;
};
const status = (value) => el("span", { class: `st ${ST_CLASS[value] || ""}`, text: value });
const kv = (pairs) => {
  const dl = el("dl", { class: "kv" });
  for (const [k, v] of pairs) if (v != null && v !== "") dl.append(el("dt", { text: k }), el("dd", {}, v));
  return dl;
};
const chips = (values, done = []) => {
  const box = el("span", { class: "chips" });
  for (const v of values) box.append(el("span", { class: `chip ${done.includes(v) ? "done" : ""}`, text: v }));
  return box;
};
const codes = (values) => {
  const box = el("span", { class: "chips" });
  for (const v of values) box.append(el("code", { text: v }));
  return box;
};

function detail(source, findings) {
  const pairs = [
    ["Purpose", source.purpose],
    ["Publisher", source.publisher],
    ["Original", source.original],
    ["Entry points", codes(source.entry_points)],
    ["Tier", source.tier == null ? "not applicable" : source.tier_reason],
  ];
  for (const [name, values] of Object.entries(source.options || {})) {
    pairs.push([`Options: ${name}`, chips(values, (source.assessed_options || {})[name] || [])]);
  }
  if (source.explorer) pairs.push(["On the map", el("a", { href: source.explorer, text: "Open this source in the CRC data explorer" })]);
  if (source.notes) pairs.push(["Notes", source.notes]);
  if (source.records) pairs.push(["Assessment", el("a", { class: "jumpto", href: `#assessment-${source.id}`, text: "Go to this source's assessment on this page" })]);
  if (findings.length) {
    const list = el("span", {});
    findings.forEach((f, i) => { if (i) list.append("; "); list.append(el("a", { class: "jumpto", href: `#finding-${f.id}`, text: f.id }), ` ${f.title}`); });
    pairs.push(["Findings", list]);
  }
  if (source.drafted_by) pairs.push(["Drafted by", source.drafted_by]);
  pairs.push(["Review", source.draft ? "Draft: not yet reviewed" : `Reviewed by ${source.reviewed_by}, ${source.reviewed_on}`]);
  return kv(pairs);
}

function renderInventory(data, filters) {
  const body = document.querySelector("#inventory tbody");
  body.replaceChildren();
  const bySource = {};
  for (const f of data.findings) (bySource[f.source] ||= []).push(f);
  const rows = data.sources.filter((s) => (!filters.kind || s.kind === filters.kind) && (!filters.tier || String(s.tier) === filters.tier));
  for (const s of rows) {
    const mine = bySource[s.id] || [];
    const row = el("tr", { class: "row", tabindex: "0", "aria-expanded": "false" },
      el("td", { class: "l" }, el("div", { text: s.title }), el("div", { class: "id", text: s.id })),
      el("td", { class: "l", text: s.kind }),
      el("td", { text: s.tier == null ? "n/a" : String(s.tier) }),
      ...TIERS.map((t) => el("td", { class: "l" }, status(s.status[t]))),
      el("td", { text: String(mine.length) }));
    const more = el("tr", { hidden: "" }, el("td", { class: "detail", colspan: "7" }, detail(s, mine)));
    const toggle = () => {
      const open = row.getAttribute("aria-expanded") === "true";
      row.setAttribute("aria-expanded", String(!open));
      more.toggleAttribute("hidden", open);
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    body.append(row, more);
  }
  if (!rows.length) body.append(el("tr", {}, el("td", { class: "l empty", colspan: "7", text: "No source matches the filters." })));
}

// Layers of the map explorer that show a finding (registry: a layer names its `finding`), by finding id.
let mapped = {}, mappedSources = new Set();
async function loadMapped() {
  try {
    const r = await fetch("../layers.json"); if (!r.ok) return;
    const registry = await r.json(); const by = {};
    for (const l of registry.layers) for (const id of (l.finding || "").split(/,\s*/).filter(Boolean)) (by[id] ||= []).push(l);
    mapped = by;
  } catch { /* the map explorer is optional for this page */ }
}
// One link per area for a finding the map shows; a note for the other findings of a source that has such layers.
function mapLinks(f) {
  const layers = mapped[f.id];
  if (!layers) return mappedSources.has(f.source) ? "Not a finding with a place on the map." : null;
  const first = new Map(); for (const l of layers) if (!first.has(l.group)) first.set(l.group, l);
  const box = el("span", {});
  [...first.values()].forEach((l, i) => { if (i) box.append(" · "); box.append(el("a", { class: "maplink", href: `explore/#tab=crc&layer=${l.id}`, text: l.group })); });
  box.append(el("span", { class: "mute small", text: ` (${layers.length} layers in the CRC data explorer)` }));
  return box;
}

function renderFindings(data, filters) {
  const box = document.getElementById("findings");
  box.replaceChildren();
  const titles = Object.fromEntries(data.sources.map((s) => [s.id, s.title]));
  const list = data.findings.filter((f) => !filters.status || f.status === filters.status);
  for (const f of list) {
    const where = f.source === "framework" ? "All gridded sources" : titles[f.source] || f.source;
    const statusText = f.status === "fixed" ? `fixed in ${f.fixed_in}` : f.status;
    box.append(el("details", { class: "finding", id: `finding-${f.id}` },
      el("summary", {},
        el("span", { class: "fid", text: f.id }),
        el("span", {}, el("b", { text: f.title }), el("div", { class: "mute small", text: where })),
        el("span", { class: "meta" },
          el("span", { class: `tag ${f.kind === "defect" ? "defect" : ""}`, text: f.kind }), " · ",
          el("span", { class: `tag ${f.status === "fixed" ? "fixed" : "open"}`, text: statusText }))),
      el("div", { class: "body" }, kv([
        ["Documented", f.documented || "The documentation is silent."],
        ["Observed", f.observed],
        ["Consequence", f.consequence],
        ["Evidence", codes(f.evidence)],
        ["Basis", f.basis],
        ["On the map", mapLinks(f)],
        ["Reported", f.upstream_ref],
        ["Found", `${f.found_on}, at ${data.framework} ${f.framework_version}`],
      ]))));
  }
  if (!list.length) box.append(el("p", { class: "empty", text: "No finding matches the filter." }));
}

function renderGaps(data) {
  const box = document.getElementById("gaps");
  const g = data.gaps;
  const real = data.sources.filter((s) => s.kind !== "user data").length;
  const pairs = [
    ["Entry points with no inventory entry", g.unclaimed_symbols.length ? codes(g.unclaimed_symbols) : "None: every entry point found in the installed version has an entry."],
    ["Option values new upstream", g.new_options.length ? chips(g.new_options.map((o) => `${o.source}: ${o.option} = ${o.value}`)) : "None."],
    ["Sources with no assessment", `${g.unassessed_sources.length} of ${real}`],
    ["Option values not assessed", `${g.unassessed_options.length} (recipes, datasets, versions; open a source above to see which)`],
  ];
  if (g.could_not_enumerate.length) pairs.push(["Could not be read from the framework", g.could_not_enumerate.join("; ")]);
  box.replaceChildren(kv(pairs));
}

const fmt = (n) => (typeof n === "number" ? n.toLocaleString("en-US") : String(n ?? ""));
const OUT_CLASS = { "confirmed": "ok", "differs": "bad", "not checked": "none", "not applicable": "none" };
const outcome = (value) => el("span", { class: `out ${OUT_CLASS[value] || "none"}`, text: value });
const table = (head, rows, cls = "") => el("div", { class: "scroll" }, el("table", { class: `data plain ${cls}` },
  el("thead", {}, el("tr", {}, ...head.map((h, i) => el("th", { class: i === 0 ? "l" : "", text: h })))),
  el("tbody", {}, ...rows.map((r) => el("tr", {}, ...r.map((c, i) => el("td", { class: i === 0 || (c instanceof Node) ? "l" : "" }, c instanceof Node ? c : String(c))))))));

// One series per chart, so no legend; the heading names it. Bars carry a hover readout.
function barChart(pairs, unit, xName, readout) {
  const W = 1000, H = 150, top = 8, bottom = 18, left = 34;
  const max = Math.max(...pairs.map((p) => p[1])) > 0 ? Math.max(...pairs.map((p) => p[1])) : 1;
  const step = (W - left) / pairs.length;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "chart"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${unit} by ${xName.toLowerCase()}, ${pairs.length} bars from ${pairs[0][0]} to ${pairs[pairs.length - 1][0]}; the tables give the numbers`);
  const add = (name, attrs, text) => { const n = document.createElementNS(ns, name); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text != null) n.textContent = text; svg.append(n); return n; };
  const y = (v) => top + (H - top - bottom) * (1 - v / max);
  for (const v of [0, max / 2, max]) {
    add("line", { x1: left, x2: W, y1: y(v), y2: y(v), class: "grid" });
    add("text", { x: left - 4, y: y(v) + 3, class: "tick", "text-anchor": "end" }, max < 10 ? String(Number(v.toFixed(max < 1 ? 2 : 1))) : fmtShort(v));
  }
  const numeric = pairs.every((p) => typeof p[0] === "number");
  const every = Math.max(1, Math.ceil(pairs.length / 9 / 10) * 10);
  pairs.forEach(([x0, count], i) => {
    const x = left + i * step;
    if (numeric ? x0 % every === 0 : pairs.length <= 18) add("text", { x: x + step / 2, y: H - 4, class: "tick", "text-anchor": "middle" }, String(x0));
    add("rect", { x: x + Math.min(1, step * 0.15), y: y(count), width: Math.max(step - Math.min(2, step * 0.3), 0.5), height: y(0) - y(count), class: "bar" });
    const hit = add("rect", { x, y: top, width: step, height: H - top - bottom, class: "hit" });
    hit.addEventListener("pointerenter", () => { readout.textContent = `${xName} ${x0}: ${fmt(count)} ${unit}`; });
  });
  const idle = `Point at a bar for its ${xName.toLowerCase()} and count.`;
  readout.textContent = idle;
  svg.addEventListener("pointerleave", () => { readout.textContent = idle; });
  return svg;
}

// Where the numbers of a table or chart come from (the same three origins as on the map explorer).
const ORIGINS = { "crc-sdk": ["crc-sdk output", "#2a78d6"], publisher: ["Publisher's files, read by us", "#b3620a"], evidence: ["Outside evidence", "#1a7a55"] };
const originTag = (id) => (ORIGINS[id] ? el("span", { class: "ptag", style: `--c:${ORIGINS[id][1]}`, text: ORIGINS[id][0] }) : null);
const fmtShort = (v) => (v >= 1e6 ? `${Number((v / 1e6).toFixed(1))}M` : v >= 1e4 ? `${Math.round(v / 1e3)}k` : String(Math.round(v)));
// Ranked values, largest first: one row per name with a bar and the number (plain HTML, read by a screen reader as a list).
function rankChart(pairs, unit) {
  const max = Math.max(...pairs.map((p) => p[1]), 0) || 1;
  return el("ol", { class: "rank", "aria-label": `Ranked, ${unit}` }, ...pairs.map(([name, v]) =>
    el("li", {}, el("span", { class: "name", text: name }), el("span", { class: "track" }, el("i", { style: `width:${((100 * v) / max).toFixed(1)}%` })), el("span", { class: "num", text: `${fmt(v)} ${unit}` }))));
}
function chartBlock(chart) {
  const names = Object.keys(chart.series);
  const pick = el("select", { "aria-label": `${chart.select} shown in the chart` }, ...names.map((f) => el("option", { text: f })));
  pick.value = chart.default;
  const readout = el("span", { class: "mute small", "aria-live": "polite" });
  const holder = el("div", { class: "chart-box" });
  const draw = () => holder.replaceChildren(chart.ranked ? rankChart(chart.series[pick.value], chart.unit) : barChart(chart.series[pick.value], chart.unit, chart.x, readout));
  pick.addEventListener("change", draw); draw();
  return [el("div", { class: "chart-head" }, el("b", { text: chart.title }), chart.finding ? el("span", { class: "tag", text: chart.finding }) : null, originTag(chart.origin),
    names.length > 1 ? el("label", {}, `${chart.select} `, pick) : null, chart.ranked ? null : el("span", { class: "mute small", text: chart.unit }), chart.ranked ? null : readout), holder];
}

function renderAssessment(source, rec, findings, watch) {
  const checks = rec.checks;
  const box = el("details", { class: "assessment", open: "", id: `assessment-${source.id}` },
    el("summary", {}, el("b", { text: source.title }),
      el("span", { class: "meta" }, el("span", { class: `tag ${source.draft ? "defect" : "fixed"}`, text: source.draft ? "draft, not reviewed" : `reviewed by ${source.reviewed_by}, ${source.reviewed_on}` }),
        ` · run of ${rec.run_at.slice(0, 10)}`)));
  const body = el("div", { class: "body" });
  body.append(el("div", { class: "tiles" }, ...(rec.headline || []).map(([n, label]) => el("div", { class: "tile" }, el("b", { text: fmt(n) }), el("span", { text: label })))));

  const long = (t) => t.rows.length > 12;
  for (const t of rec.tables || []) {
    const made = table(t.head, t.rows.map((r) => r.map((c) => (typeof c === "number" ? fmt(c) : c))));
    if (long(t)) body.append(el("details", { class: "fold" }, el("summary", {}, `${t.title} (${t.rows.length} rows) `, originTag(t.origin)), t.note ? el("p", { class: "mute small", text: t.note }) : null, made));
    else body.append(el("h3", {}, `${t.title} `, originTag(t.origin)), t.note ? el("p", { class: "mute small", text: t.note }) : null, made);
  }
  if (rec.chart) body.append(...chartBlock(rec.chart));
  if (rec.charts && rec.charts.length) {
    body.append(el("h3", { text: "Charts for reviewing the findings" }));
    for (const chart of rec.charts) body.append(...chartBlock(chart));
  }
  if (rec.comparisons && rec.comparisons.length) {
    body.append(el("h3", {}, "Comparisons with outside evidence (no verdict) ", originTag("evidence")),
      el("p", { class: "mute small", text: "Numbers set beside data from other publishers, with their limits. They are not checks: they have no outcome and are not counted above. They describe the publisher's maps, not the framework's fidelity." }));
    for (const c of rec.comparisons) {
      const inner = el("div", { class: "comparison" },
        el("p", { class: "small", text: c.method }),
        table(["Number", "Value"], c.numbers.map(([k, v]) => [k, v === null ? "none" : typeof v === "number" ? fmt(v) : v])),
        c.table ? el("details", { class: "fold" }, el("summary", { text: `${c.table.title} (${c.table.rows.length} rows)` }), table(c.table.head, c.table.rows.map((r) => r.map((x) => (x === null ? "" : typeof x === "number" ? fmt(x) : x))))) : null,
        el("p", { class: "small" }, el("b", { text: "Limits. " }), c.limits.join(" ")),
        el("p", { class: "mute small", text: `Evidence: ${c.evidence.name}; ${fmt(c.evidence.features)} records, retrieved ${c.evidence.retrieved_at.slice(0, 10)}; ${c.evidence.licence}.${c.evidence.panel_effective_dates ? ` Map panels effective ${c.evidence.panel_effective_dates}.` : ""}` }));
      body.append(el("details", { class: "fold comparison-fold" }, el("summary", { text: c.title }), inner));
    }
  }
  if (source.notes) body.append(el("p", { class: "small", text: source.notes }));

  body.append(el("h3", { text: "What the framework does, step by step" }));
  body.append(table(["Step", "What the framework does", "Code", "Outcome"],
    source.statement.map((s) => [s.id, el("span", { text: s.text.replaceAll("`", "") }), el("code", { text: s.code_ref }),
      el("span", {}, outcome(s.outcome), s.note ? el("div", { class: "mute small", text: s.note }) : null)]), "statement"));

  body.append(el("h3", { text: "Checks behind the outcomes" }));
  const kinds = [...new Set(checks.map((c) => c.check.split("[")[0]))];
  const variants = [...new Set(checks.filter((c) => c.check.includes("[")).map((c) => c.check.split("[")[1].slice(0, -1)))];
  const cell = (kind, v) => { const c = checks.find((x) => x.check === `${kind}[${v}]`); return c ? el("span", { title: c.summary || c.note || "" }, outcome(c.outcome)) : ""; };
  const single = kinds.filter((k) => checks.some((c) => c.check === k));
  body.append(table(["Check", "What is compared", ...variants],
    kinds.filter((k) => !single.includes(k)).map((k) => [k, el("span", { class: "method", text: checks.find((c) => c.check.startsWith(`${k}[`)).method }), ...variants.map((v) => cell(k, v))]), "matrix"));
  for (const k of single) {
    const c = checks.find((x) => x.check === k);
    body.append(el("p", { class: "small" }, el("b", { text: `${k}: ` }), outcome(c.outcome), ` ${c.method} ${c.summary || ""}.`));
  }
  body.append(el("details", { class: "fold" }, el("summary", { text: `The numbers of each check (${checks.length})` }),
    table(["Check", "Outcome", "Result"], checks.map((c) => [c.check, outcome(c.outcome), el("span", { text: c.summary || c.note || "" })]))));
  const skipped = Object.entries(rec.subsets_skipped || {});
  const open = Object.entries(source.options || {}).flatMap(([n, vs]) => vs.filter((v) => !((source.assessed_options || {})[n] || []).includes(v)).map((v) => `${n} = ${v}`));
  body.append(kv([
    ["Not assessed", open.length ? open.join(", ") : "Every option offered was assessed."],
    ["Skipped in this run", skipped.map(([n, why]) => `${n}: ${why}`).join("; ")],
    ["Findings", findings.length ? findings.map((f) => `${f.id} ${f.title}`).join("; ") : "None."],
    ["Monitoring", watch ? `${watch.stale ? "Stale: " + watch.reasons.join("; ") : "Current"} (${watch.files} publisher files asked on ${watch.asked.slice(0, 10)}).` : ""],
    ["Versions", Object.entries(rec.versions).map(([k, v]) => `${k} ${v}`).join(", ")],
    ["Limits", "A confirmed outcome holds for these files, options and versions. It says nothing about whether the publisher's values are right."],
  ]));
  box.append(body);
  return box;
}

async function renderAssessments(data) {
  const withRecords = data.sources.filter((s) => s.records);
  if (!withRecords.length) return;
  const box = document.getElementById("assessments");
  let monitor = null;
  try { const r = await fetch("data/monitor.json"); if (r.ok) monitor = await r.json(); } catch { /* monitoring is optional */ }
  for (const source of withRecords) {
    const response = await fetch(`data/${source.records}`);
    if (!response.ok) throw new Error(`records of ${source.id}: HTTP ${response.status}`);
    box.append(renderAssessment(source, await response.json(), data.findings.filter((f) => f.source === source.id),
      monitor ? { ...(monitor.sources.find((x) => x.source === source.id) || {}), asked: monitor.run_at } : null));
  }
  document.getElementById("assessments-section").hidden = false;
}

function renderTiles(data) {
  const real = data.sources.filter((s) => s.kind !== "user data");
  const verified = real.filter((s) => s.status.verification === "assessed").length;
  const open = data.findings.filter((f) => f.status === "open" || f.status === "reported upstream").length;
  const tiles = [
    [real.length, "sources in the inventory"],
    [`${verified} of ${real.length}`, "verified against the original"],
    [open, "findings open"],
    [data.findings.filter((f) => f.basis === "reproduced").length, "findings reproduced on data"],
  ];
  document.getElementById("tiles").replaceChildren(...tiles.map(([n, label]) => el("div", { class: "tile" }, el("b", { text: String(n) }), el("span", { text: label }))));
}

// The page is long: a bar of links to its parts, and addresses that open one finding or one assessment.
function renderJump(data) {
  const withRecords = data.sources.filter((s) => s.records);
  const link = (href, text) => el("a", { class: "jumpto", href, text });
  const bar = document.getElementById("jump");
  bar.replaceChildren(el("span", { class: "label", text: "On this page" }), link("#inventory-section", `Inventory (${data.sources.length} sources)`));
  if (withRecords.length) bar.append(el("span", { class: "group" }, "Assessments: ", ...withRecords.flatMap((s, i) => [i ? " · " : "", link(`#assessment-${s.id}`, `${s.title}${s.draft ? " (draft)" : ""}`)])));
  bar.append(link("#findings-section", `Findings (${data.findings.length})`), link("#gaps-section", "Not yet assessed"));
  if (data.preview) {
    const note = document.getElementById("preview-note"); const s = data.sources.find((x) => x.id === data.preview.source);
    note.replaceChildren(el("b", { text: "Draft preview. " }), `This is a throwaway copy of the page that also shows the draft assessment of ${s ? s.title : data.preview.source}; the real page does not. `, link(`#assessment-${data.preview.source}`, "Go to the draft"), ".");
    note.hidden = false; document.body.dataset.preview = data.preview.source;
  }
}
function goToHash() {
  const id = decodeURIComponent(location.hash.slice(1)); if (!id) return;
  const node = document.getElementById(id); if (!node) return;
  if (node.tagName === "DETAILS") node.open = true;
  node.scrollIntoView({ block: "start" }); node.classList.add("target"); setTimeout(() => node.classList.remove("target"), 2500);
  document.body.dataset.target = id;
}

async function main() {
  let data;
  try {
    const response = await fetch("data/inventory.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
  } catch (error) {
    document.getElementById("notice").textContent = `The inventory could not be loaded (${error.message}).`;
    document.body.dataset.error = error.message;
    return;
  }
  await loadMapped();
  // sources with a finding on the map: "framework" findings shown through a source count for that source
  mappedSources = new Set(data.findings.filter((f) => mapped[f.id]).map((f) => f.source));
  document.body.dataset.mapped = Object.keys(mapped).sort().join(" ");
  document.getElementById("framework").textContent = data.framework;
  const pins = Object.entries(data.versions).map(([k, v]) => `${k} ${v}`).join(", ");
  document.getElementById("stamp").textContent = `Generated ${data.generated.slice(0, 10)} against ${pins}. Record format ${data.schema}.`;
  const assessed = data.sources.some((s) => TIERS.some((t) => s.status[t] !== "not assessed"));
  if (!assessed) document.getElementById("notice").textContent = "No source has been assessed yet. This page shows the inventory and the findings known from reading the code.";

  const filters = { kind: "", tier: "", status: "" };
  const fill = (id, values) => { const s = document.getElementById(id); for (const v of values) s.append(el("option", { text: v })); };
  fill("f-kind", [...new Set(data.sources.map((s) => s.kind))]);
  fill("f-status", [...new Set(data.findings.map((f) => f.status))]);
  for (const [id, key, fn] of [["f-kind", "kind", renderInventory], ["f-tier", "tier", renderInventory], ["f-status", "status", renderFindings]]) {
    document.getElementById(id).addEventListener("change", (e) => { filters[key] = e.target.value; fn(data, filters); });
  }
  renderTiles(data); renderInventory(data, filters); renderFindings(data, filters); renderGaps(data);
  try { await renderAssessments(data); } catch (error) { document.getElementById("notice").textContent = `An assessment could not be loaded (${error.message}).`; document.body.dataset.error = error.message; return; }
  renderJump(data); goToHash(); window.addEventListener("hashchange", goToHash);
  document.body.dataset.ready = "1";
}
main();
