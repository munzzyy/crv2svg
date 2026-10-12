// Drives the real page in headless Chromium. argv: <page url> <folder of .crv inputs> <scratch folder> [chromium path]
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const [PAGE, INPUTS, SCRATCH, CHROMIUM = "/usr/bin/chromium"] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail = "") {
  results.push(ok);
  console.log((ok ? "PASS " : "FAIL ") + name + (ok ? "" : "  " + detail));
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let id = 0;
    const waiting = new Map();
    const listeners = [];
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && waiting.has(m.id)) {
        const w = waiting.get(m.id);
        waiting.delete(m.id);
        if (m.error) w.rej(new Error(m.error.message));
        else w.res(m.result);
      } else if (m.method) listeners.forEach((l) => l(m));
    };
    ws.onopen = () => resolve({
      send: (method, params = {}) => new Promise((res, rej) => {
        const n = ++id;
        waiting.set(n, { res, rej });
        ws.send(JSON.stringify({ id: n, method, params }));
      }),
      on: (fn) => listeners.push(fn),
      close: () => ws.close(),
    });
    ws.onerror = reject;
  });
}

const port = 9800 + Math.floor(Math.random() * 150);
const profile = fs.mkdtempSync(path.join(SCRATCH, "profile-"));
const downloads = path.join(SCRATCH, "downloads");
fs.rmSync(downloads, { recursive: true, force: true });
fs.mkdirSync(downloads, { recursive: true });
const proc = spawn(CHROMIUM, [
  "--headless=new", "--remote-debugging-port=" + port, "--user-data-dir=" + profile, "--no-first-run",
  "--disable-extensions", "--disable-background-networking", "--hide-scrollbars",
  // Hosted runners do not let Chromium set up its sandbox.
  ...(process.env.CI ? ["--no-sandbox"] : []), "about:blank",
], { stdio: "ignore" });

async function ready() {
  for (let i = 0; i < 100; i++) {
    try { return await (await fetch("http://127.0.0.1:" + port + "/json/version")).json(); } catch { await sleep(100); }
  }
  throw new Error("chromium did not start");
}

const version = await ready();
const browser = await connect(version.webSocketDebuggerUrl);
await browser.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloads, eventsEnabled: false });

async function open({ width = 1366, height = 800, scheme = "light" } = {}) {
  const t = await (await fetch("http://127.0.0.1:" + port + "/json/new?about:blank", { method: "PUT" })).json();
  const page = await connect(t.webSocketDebuggerUrl);
  const log = { requests: [], problems: [] };
  page.on((m) => {
    if (m.method === "Network.requestWillBeSent") log.requests.push(m.params.request.url);
    if (m.method === "Runtime.exceptionThrown") log.problems.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300));
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") log.problems.push(m.params.entry.text);
  });
  for (const d of ["Runtime", "Page", "Network", "Log"]) await page.send(d + ".enable");
  await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await page.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
  await page.send("Page.navigate", { url: PAGE });
  await sleep(700);
  page.log = log;
  page.targetId = t.id;
  return page;
}

async function ev(page, expression) {
  const r = await page.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result.value;
}

async function until(page, expression, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if (await ev(page, expression)) return true; } catch { /* page still starting */ }
    await sleep(80);
  }
  return false;
}

async function drop(page, names, fakeFolders = []) {
  const items = names.map((n) => ({ name: n, b64: fs.readFileSync(path.join(INPUTS, n)).toString("base64") }));
  return ev(page, `(async () => {
    const dt = new DataTransfer();
    for (const it of ${JSON.stringify(items)}) {
      dt.items.add(new File([Uint8Array.from(atob(it.b64), (c) => c.charCodeAt(0))], it.name, { type: "application/octet-stream" }));
    }
    const folders = ${JSON.stringify(fakeFolders)};
    if (folders.length) {
      const fake = { types: ["Files"], files: [], items: folders.map((name) => ({ kind: "file", webkitGetAsEntry: () => ({ isDirectory: true, name }), getAsFile: () => null })) };
      const e = new Event("drop", { bubbles: true, cancelable: true });
      Object.defineProperty(e, "dataTransfer", { value: fake });
      document.body.dispatchEvent(e);
      return folders.length;
    }
    for (const type of ["dragenter", "dragover", "drop"]) {
      document.body.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
    }
    return dt.files.length;
  })()`);
}

const SETTLED = "!document.querySelector('.file[data-state=busy]') && !document.getElementById('work').hidden";
async function load(page, names) {
  await drop(page, names);
  await until(page, SETTLED);
  await until(page, "document.getElementById('docBody').hidden || (document.getElementById('paperImg').complete && document.getElementById('paperImg').naturalWidth > 0)");
  await sleep(250);
}

const text = (page, sel) => ev(page, `(document.querySelector(${JSON.stringify(sel)}) || {}).innerText || ""`);

async function key(page, k) {
  const code = { Tab: 9, Enter: 13 }[k];
  await page.send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k, windowsVirtualKeyCode: code, text: k === "Enter" ? "\r" : undefined });
  await page.send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k, windowsVirtualKeyCode: code });
}

async function saved(before) {
  for (let i = 0; i < 80; i++) {
    const now = fs.readdirSync(downloads).filter((f) => !before.has(f) && !f.endsWith(".crdownload"));
    if (now.length) return now;
    await sleep(100);
  }
  return [];
}

const contrast = `(() => {
  const lum = (c) => { const v = c.map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const rgb = (s) => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number);
  const el = document.querySelector('.layer.none .layer-name');
  if (!el) return 0;
  const a = lum(rgb(getComputedStyle(el).color)), b = lum(rgb(getComputedStyle(el.closest('.panel')).backgroundColor));
  const opacity = Number(getComputedStyle(el).opacity) * Number(getComputedStyle(el.closest('label')).opacity);
  return opacity < 1 ? 0 : (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
})()`;

try {
  // units: a label change must say it is not a conversion
  let page = await open();
  await load(page, ["single.crv"]);
  await ev(page, "(() => { const s = document.getElementById('units'); s.value = 'in'; s.dispatchEvent(new Event('change', { bubbles: true })); })()");
  await sleep(300);
  const sizeNote = await text(page, "#sizeNote");
  check("units: the size note admits the numbers were not converted", !/from the file\.?$/.test(sizeNote) && /nothing was resized/.test(sizeNote), sizeNote);
  check("units: a warning explains the relabel", /unit label was changed/.test(await text(page, "#notices")));
  check("units: the control says what it does", /numbers in this file are in/.test(await text(page, "label[for=units]")) && /Only changes the label/.test(await text(page, "#unitsHelp")));
  check("page makes no request beyond its own origin", page.log.requests.every((u) => u.startsWith(new URL(PAGE).origin) || u.startsWith("blob:") || u.startsWith("data:") || u.startsWith("file:")), page.log.requests.join(" "));
  check("no script errors on the happy path", page.log.problems.length === 0, page.log.problems.join(" | "));

  // dropping a second file shows it, a broken one shows its error
  await drop(page, ["three-sheets.crv"]);
  await until(page, SETTLED);
  await sleep(300);
  check("drop: the newly dropped file is the one on screen", await text(page, "#docTitle") === "three-sheets.crv");
  await drop(page, ["junk.crv"]);
  await until(page, SETTLED);
  await sleep(300);
  check("drop: a file that cannot be read shows its message", await text(page, "#docTitle") === "junk.crv" && /not a Vectric project file/.test(await text(page, "#docState")));
  await drop(page, ["zero.crv"]);
  await until(page, SETTLED);
  await sleep(300);
  check("drop: an empty file says it is empty", /file is empty/.test(await text(page, "#docState")) && !/not a Vectric/.test(await text(page, "#docState")), await text(page, "#docState"));
  await drop(page, [], ["some-folder"]);
  await sleep(300);
  check("drop: a folder says it is a folder", await text(page, "#docTitle") === "some-folder" && /folder/.test(await text(page, "#docState")), await text(page, "#docState"));
  page.close();

  // a narrow screen must not clip the main buttons
  page = await open({ width: 320, height: 700 });
  await load(page, ["three-sheets.crv"]);
  const clipped = await ev(page, "[...document.querySelectorAll('.btn')].filter((b) => b.offsetWidth && b.scrollWidth > b.clientWidth).map((b) => b.id + ':' + b.scrollWidth + '>' + b.clientWidth)");
  check("320px: no button label is clipped", clipped.length === 0, clipped.join(" "));
  check("320px: the page does not scroll sideways", await ev(page, "document.documentElement.scrollWidth <= innerWidth"));
  page.close();

  // mostly-3D and empty files get a plain word
  page = await open();
  await load(page, ["heavy.crv", "single.crv"]);
  check("heavy: says the 3D data was skipped", /mostly 3D model or picture data/.test(await text(page, "#notices")), await text(page, "#notices"));
  check("heavy: the file list flags it instead of a plain ready", await ev(page, "document.querySelectorAll('.file[data-state=attention]').length") === 1);
  page.close();

  page = await open();
  await load(page, ["empty-layers.crv"]);
  const note = await text(page, "#dlNote");
  check("empty file: does not tell you to turn on a layer that is not there", /no 2D drawing/.test(note) && !/Turn on a layer/.test(note), note);
  check("empty file: a notice says why", /no 2D drawing/.test(await text(page, "#notices")));
  page.close();

  // layers: ones with a drawing come first, empty ones fold away
  page = await open();
  await load(page, ["many-empty.crv"]);
  const firstRows = await ev(page, "[...document.querySelectorAll('#layerList li')].slice(0, 4).map((li) => li.innerText.replace(/\\s+/g, ' '))");
  check("layers: the ones with a drawing come first", firstRows.slice(0, 3).every((t) => /segments?$/.test(t)) && /19 empty layers/.test(firstRows[3]), JSON.stringify(firstRows));
  check("layers: empty ones are not listed until asked", await ev(page, "document.querySelectorAll('.layer.none').length") === 0);
  await ev(page, "document.querySelector('.layer-fold').click()");
  await sleep(150);
  check("layers: expanding shows all of them", await ev(page, "document.querySelectorAll('.layer.none').length") === 19);
  check("layers: dimmed names still pass contrast", await ev(page, contrast) >= 4.5, String(await ev(page, contrast)));
  page.close();

  // messages in plain words
  page = await open();
  await load(page, ["unknown.crv"]);
  const err = await text(page, "#docState");
  check("error: no developer wording", !/record name/i.test(err) && /does not support yet \(vcCadSpline\)/.test(err) && /Copy details/.test(err), err);
  page.close();

  page = await open();
  await load(page, ["old-text2.crv"]);
  const warnTitle = await text(page, "#notices .notice strong");
  check("warnings: plural agrees", /^2 pieces of text from an older release are left out/.test(warnTitle), warnTitle);
  const veil = await ev(page, "(() => { const s = getComputedStyle(document.getElementById('veil')); return [s.opacity, s.backgroundColor]; })()");
  check("drop veil hides what is behind it", veil[0] === "1" && !/rgba\(.*,\s*0?\.\d+\)$/.test(veil[1]), veil.join(" "));
  page.close();

  // keyboard focus survives a save, and the page says what it saved
  page = await open();
  await load(page, ["three-sheets.crv"]);
  for (const id of ["dlDxf", "dlAllSvg", "dlAllDxf", "dlSvg"]) {
    await ev(page, `document.getElementById(${JSON.stringify(id)}).focus()`);
    const before = new Set(fs.readdirSync(downloads));
    await key(page, "Enter");
    const got = await saved(before);
    await sleep(900);
    check("keyboard: " + id + " saves and keeps focus", got.length === 1 && await ev(page, "document.activeElement.id") === id, got.join(",") + " focus=" + await ev(page, "document.activeElement.id"));
    check("saved: " + id + " leaves a visible line", /^Saved /.test(await text(page, "#dlSaved")), await text(page, "#dlSaved"));
  }
  page.close();

  // download everything names the files it left out
  page = await open();
  await drop(page, ["single.crv", "junk.crv"]);
  await until(page, SETTLED);
  await sleep(300);
  const before = new Set(fs.readdirSync(downloads));
  await ev(page, "document.getElementById('everything').click()");
  const got = await saved(before);
  await sleep(500);
  const line = await text(page, "#everyNote");
  check("everything: the page names the file it left out", got.length === 1 && /junk\.crv/.test(line) && /could not be read/.test(line) && /^Saved /.test(line), line);
  page.close();

  // an export too large to build is refused cleanly and the reader keeps working
  page = await open();
  await load(page, ["bezier-heavy.crv"]);
  await ev(page, "document.getElementById('dlDxf').click()");
  const refused = await until(page, "/too large to save/.test(document.getElementById('notices').innerText)", 60000);
  check("too large: the DXF is refused with a message", refused, await text(page, "#notices"));
  check("too large: the button works again", await ev(page, "!document.getElementById('dlDxf').disabled"));
  const again = new Set(fs.readdirSync(downloads));
  await ev(page, "document.getElementById('dlSvg').click()");
  check("too large: the SVG still saves from the same reader", (await saved(again)).length === 1);
  page.close();
} finally {
  try { await browser.send("Browser.close"); } catch { /* already gone */ }
  setTimeout(() => { try { process.kill(proc.pid); } catch { /* gone */ } fs.rmSync(profile, { recursive: true, force: true }); process.exit(results.every(Boolean) ? 0 : 1); }, 800);
}
