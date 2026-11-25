// Headless check of the source validation page (Chrome DevTools protocol, no npm dependencies).
//   python3 -m http.server 8770 --bind 127.0.0.1 --directory site   (in another shell)
//   node tools/smoke-validation.mjs <out dir> [url]
// Exits 1 on a failed check, a console message or a script error; writes screenshots to <out dir>.
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [S, URL = "http://127.0.0.1:8770/validation/"] = process.argv.slice(2);
const port = Number(process.env.CDP_PORT) || 9337; mkdirSync(S, { recursive: true });
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-sandbox", `--remote-debugging-port=${port}`, `--user-data-dir=${S}/cdp-profile`, "about:blank"], { stdio: "ignore" });
process.on("exit", () => chrome.kill());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets; for (let i = 0; i < 50 && !targets; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { await sleep(200); } }
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map(); const messages = [];
ws.onmessage = (ev) => { const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.consoleAPICalled" && m.params.type !== "debug") messages.push(`${m.params.type}: ${m.params.args.map((a) => a.value ?? a.description).join(" ").slice(0, 300)}`);
  if (m.method === "Runtime.exceptionThrown") messages.push((m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 300));
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error" && !/favicon/.test(m.params.entry.text + m.params.entry.url)) messages.push(`${m.params.entry.source}: ${m.params.entry.text} ${m.params.entry.url || ""}`); };
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); return r.result?.result?.value ?? r.result?.exceptionDetails?.exception?.description; };
await send("Runtime.enable"); await send("Page.enable"); await send("Log.enable"); await send("Network.enable"); await send("Network.setCacheDisabled", { cacheDisabled: true });
const size = (width, height) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
const shot = async (name) => { const s = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); writeFileSync(`${S}/${name}.png`, Buffer.from(s.result.data, "base64")); };
const open = async () => { await send("Page.navigate", { url: URL }); for (let i = 0; i < 60; i++) { await sleep(200); if (await ev("document.body.dataset.ready || document.body.dataset.error || ''")) break; } await sleep(300); };
const failures = []; const check = (name, ok, got) => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${ok ? "" : ` — got ${JSON.stringify(got)}`}`); if (!ok) failures.push(name); };

const data = JSON.parse(readFileSync(new globalThis.URL("../site/validation/data/inventory.json", import.meta.url)));
await size(1440, 900); await open();
check("page loaded", (await ev("document.body.dataset.ready")) === "1", await ev("document.body.dataset.error"));
const rows = await ev("document.querySelectorAll('#inventory tr.row').length");
check("one row per source", rows === data.sources.length, rows);
const cards = await ev("document.querySelectorAll('#findings .finding').length");
check("one card per finding", cards === data.findings.length, cards);
check("versions are shown", (await ev("document.getElementById('stamp').textContent")).includes(`crc-sdk ${data.versions["crc-sdk"]}`));
const assessed = data.sources.some((s) => Object.values(s.status).some((v) => v !== "not assessed"));
check("an unassessed inventory says so", assessed || /No source has been assessed yet/.test(await ev("document.getElementById('notice').textContent")));
await ev("document.querySelector('#inventory tr.row').click()");
check("a row opens its details", await ev("(() => { const r = document.querySelector('#inventory tr.row'); return r.getAttribute('aria-expanded') === 'true' && !r.nextElementSibling.hidden && r.nextElementSibling.innerText.includes('Purpose'); })()"));
await ev("document.querySelector('#findings .finding').open = true");
check("a finding shows documented and observed", await ev("(() => { const t = document.querySelector('#findings .finding .body').innerText; return t.includes('Documented') && t.includes('Observed') && t.includes('Evidence'); })()"));
await ev("(() => { const s = document.getElementById('f-tier'); s.value = '1'; s.dispatchEvent(new Event('change')); })()");
const tier1 = await ev("document.querySelectorAll('#inventory tr.row').length");
check("the tier filter works", tier1 === data.sources.filter((s) => s.tier === 1).length, tier1);
check("mapped sources link to the data explorer, and the header links to the other pages", (await ev("document.querySelectorAll('#inventory a[href^=\"explore/#tab=crc&source=\"]').length")) === data.sources.filter((s) => s.explorer && s.tier === 1).length /* the tier filter is on */ && data.sources.filter((s) => s.explorer).length >= 5 && (await ev("[...document.querySelectorAll('.top nav a')].map((a) => a.getAttribute('href')).slice(0, 3).join()")) === "../,explore/,../hail/");
await ev("(() => { const s = document.getElementById('f-tier'); s.value = ''; s.dispatchEvent(new Event('change')); })()");
const withRecords = data.sources.filter((s) => s.records);
const blocks = await ev("document.querySelectorAll('#assessments .assessment').length");
check("one assessment block per source with records", blocks === withRecords.length, blocks);
if (withRecords.length) {
  const src = withRecords[0];
  const steps = await ev("document.querySelector('#assessments .assessment table.statement tbody').rows.length");
  check("every statement step is listed with an outcome", steps === src.statement.length && (await ev("[...document.querySelectorAll('#assessments .assessment table.statement .out')].every((n) => n.textContent.length > 0)")), steps);
  const differs = await ev("document.querySelectorAll('#assessments .assessment table.statement .out.bad').length");
  check("steps that differ are marked", differs === withRecords.flatMap((x) => x.statement).filter((s) => s.outcome === "differs").length, differs);
  check("the draft state is shown", /draft, not reviewed/.test(await ev("document.querySelector('#assessments .assessment summary').textContent")) === src.draft);
  const bars = await ev("document.querySelectorAll('#assessments svg.chart rect.bar').length");
  check("the chart draws its bars", bars > 20, bars);
  await ev("(() => { const s = document.querySelector('#assessments .chart-head select'); if (s && [...s.options].some((o) => o.value === 'NA')) { s.value = 'NA'; s.dispatchEvent(new Event('change')); } })()");
  const barsNA = await ev("document.querySelectorAll('#assessments svg.chart rect.bar').length");
  // from crc-sdk 1.0 IBTrACS is one file, so the chart may have nothing to select
  const hasNA = await ev("(() => { const s = document.querySelector('#assessments .chart-head select'); return !!s && [...s.options].some((o) => o.value === 'NA'); })()");
  check("the chart follows the file selector where there is one", !hasNA || (barsNA > 20 && barsNA !== bars), barsNA);
}
check("findings the map shows link to it, one link per area; the source's other findings say so", await ev(`(() => {
  const body = (id) => { const d = [...document.querySelectorAll('#findings details.finding')].find((x) => x.querySelector('.fid').textContent === id); return d ? d.querySelector('.body') : null; };
  const links = [...body('CRC-014-JRC').querySelectorAll('a.maplink')].map((a) => a.getAttribute('href'));
  return links.length === 5 && links[0] === 'explore/#tab=crc&layer=jrc_review_glofas_tx_no_curve_share' && body('CRC-013-FWK').querySelectorAll('a.maplink').length === 5
    && body('CRC-018-JRC').textContent.includes('Not a finding with a place on the map') && !body('CRC-010-IBT').textContent.includes('On the map');
})()`), (await ev("document.body.dataset.mapped")));
check("every assessment opens with a summary: what is added, how it is compared, the result, two bars", await ev(`(() => [...document.querySelectorAll('#assessments .assessment')].every((a) => { const s = a.querySelector('.summary'); const t = s ? s.innerText : ''; return s && a.querySelector('.body').firstElementChild === s && /What the framework adds/.test(t) && /How it is compared/.test(t) && /does what it states in \\d+ of the \\d+ steps/.test(t) && s.querySelectorAll('.obar').length === 2; }))()`));
check("an assessment names the records kept from the earlier version", await ev(`(() => { const a = document.getElementById('assessment-jrc-flood'); const link = a && a.querySelector('.previous a'); return !!link && link.getAttribute('href') === 'data/records/0.11.2/jrc-flood.json'; })()`));
check("a bar of links leads to each part of the page, and each assessment by name", await ev(`(() => { const a = [...document.querySelectorAll('#jump a')].map((x) => x.getAttribute('href')); return a[0] === '#inventory-section' && a.includes('#findings-section') && a.filter((h) => h.startsWith('#assessment-')).length === document.querySelectorAll('#assessments .assessment').length && a.every((h) => document.getElementById(h.slice(1))) && document.getElementById('preview-note').hidden; })()`));
await ev("location.hash = '#finding-CRC-014-JRC'"); await sleep(400);
check("an address that names a finding opens it and brings it into view", await ev(`(() => { const d = document.getElementById('finding-CRC-014-JRC'); const r = d.getBoundingClientRect(); return d.open && r.top >= 0 && r.top < innerHeight && document.body.dataset.target === 'finding-CRC-014-JRC'; })()`));
await shot("validation-finding");
await ev("history.replaceState(null, '', location.pathname); scrollTo(0, 0)"); await sleep(200);
await shot("validation-1440");
await size(390, 844); await open();
const overflow = await ev("document.documentElement.scrollWidth - document.documentElement.clientWidth");
check("no sideways scroll of the page at phone width", overflow <= 0, overflow);
await ev("document.querySelector('#findings .finding').open = true");
await shot("validation-390");
check("no console messages or script errors", messages.length === 0, messages);
ws.close(); chrome.kill();
if (failures.length) { console.error(`${failures.length} check(s) failed`); process.exit(1); }
