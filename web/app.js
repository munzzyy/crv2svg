(function () {
  "use strict";

  const engine = window.crv2svg;
  const MAX_BYTES = 400 * 1024 * 1024;

  /* The reader runs in a worker built from the page's own scripts. This function is turned into
     text and shipped with the engine, so it must not touch anything outside its two arguments. */
  function createHandler(engine, post) {
    const files = new Map();
    let lastTick = 0;

    function segmentCount(layer, key) {
      let n = 0;
      const paths = engine.layerPaths(layer, key);
      for (let i = 0; i < paths.length; i++) n += paths[i].spans.length;
      return n;
    }

    function summarize(f) {
      const doc = f.doc;
      f.sheetKeys = engine.sheetsOf(doc);
      f.origUnits = doc.units;
      const drawing = engine.drawingLayers(doc, false);
      const parts = f.sheetKeys.map(function (key) {
        let n = 0;
        drawing.forEach(function (layer) {
          layer.items.forEach(function (item) { if (item.sheet === key && item.paths.length) n += 1; });
        });
        return n;
      });
      const rows = new Map();
      doc.layers.forEach(function (layer) {
        let row = rows.get(layer.name);
        if (!row) {
          row = {
            name: layer.name, color: engine.strokeColor(layer.color), preview: true, layers: 0,
            objects: 0, total: 0, segments: f.sheetKeys.map(function () { return 0; }),
          };
          rows.set(layer.name, row);
        }
        row.layers += 1;
        row.preview = row.preview && layer.isPreview;
        row.objects += layer.items.length;
        row.total += segmentCount(layer, null);
        f.sheetKeys.forEach(function (key, i) { row.segments[i] += segmentCount(layer, key); });
      });
      const list = Array.from(rows.values());
      const drawn = list.reduce(function (n, r) { return n + (r.preview ? 0 : r.total); }, 0);
      const any = list.reduce(function (n, r) { return n + r.total; }, 0);
      const bytes = f.bytes.byteLength;
      return {
        product: doc.product, version: doc.version, units: doc.units, material: doc.material,
        parts: parts, layers: list, warnings: engine.warningLines(doc),
        bytes: bytes, estimate: f.estimate,
        empty: any === 0, heavy: bytes >= 1048576 && drawn * 4096 < bytes,
      };
    }

    function progressFor(id) {
      return function (fraction) {
        const now = Date.now();
        if (now - lastTick < 60) return;
        lastTick = now;
        post({ t: "progress", id: id, fraction: fraction });
      };
    }

    function failure(id, exc) {
      const known = exc instanceof engine.CrvError;
      const partial = known && exc.partial && exc.partial.layers.length ? exc.partial : null;
      const f = files.get(id);
      if (f) f.partial = partial;
      post({
        t: "failed", id: id, known: known, message: known ? exc.message : "",
        partialLayers: partial ? partial.layers.length : 0,
      });
    }

    function open(m) {
      const f = files.get(m.id);
      if (!f) return;
      try {
        const doc = engine.readBytes(f.bytes, m.estimate, progressFor(m.id));
        f.doc = doc;
        f.estimate = m.estimate;
        f.partial = null;
        post({ t: "opened", id: m.id, summary: summarize(f), partial: false });
      } catch (exc) {
        if (m.keepOnFail && f.doc) {
          post({ t: "estimateFailed", id: m.id, message: exc instanceof engine.CrvError ? exc.message : "" });
        } else {
          failure(m.id, exc);
        }
      }
    }

    function render(m) {
      const f = files.get(m.id);
      const reply = { t: "rendered", id: m.id, rid: m.rid, kind: m.kind };
      if (!f || !f.doc) {
        reply.error = "That file is no longer open.";
        post(reply);
        return;
      }
      try {
        const doc = f.doc;
        doc.units = m.units || f.origUnits;
        const opts = { includePreviews: m.previews, layers: m.layers };
        if (f.sheetKeys.length > 1 && m.sheet !== null) opts.sheet = f.sheetKeys[m.sheet];
        reply.text = m.kind === "svg" ? engine.toSvg(doc, opts) : engine.toDxf(doc, opts);
        reply.page = engine.pageOf(doc, m.previews, opts.sheet);
        const mat = doc.material;
        reply.onMaterial = !!mat && reply.page[0] === mat[0] && reply.page[1] === mat[1] &&
          reply.page[2] === mat[0] + mat[2] && reply.page[3] === mat[1] + mat[3];
      } catch (exc) {
        reply.text = "";
        reply.error = exc instanceof engine.CrvError ? exc.message : "Something went wrong while drawing.";
      }
      post(reply);
    }

    return function (m) {
      if (m.t === "hello") {
        post({ t: "ready", n: m.n });
      } else if (m.t === "load") {
        files.set(m.id, { bytes: new Uint8Array(m.buffer), doc: null, partial: null, estimate: false, sheetKeys: [], origUnits: null });
        open({ id: m.id, estimate: false, keepOnFail: false });
      } else if (m.t === "estimate") {
        open({ id: m.id, estimate: m.estimate, keepOnFail: true });
      } else if (m.t === "keep") {
        const f = files.get(m.id);
        if (f && f.partial) {
          f.doc = f.partial;
          f.estimate = false;
          post({ t: "opened", id: m.id, summary: summarize(f), partial: true });
        }
      } else if (m.t === "render") {
        render(m);
      } else if (m.t === "drop") {
        files.delete(m.id);
      }
    };
  }

  /* small helpers */
  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, kids) {
    const node = document.createElement(tag);
    const keys = Object.keys(attrs || {});
    for (let i = 0; i < keys.length; i++) {
      const key = keys[i];
      if (key === "text") node.textContent = attrs[key];
      else if (key === "class") node.className = attrs[key];
      else node.setAttribute(key, attrs[key]);
    }
    (kids || []).forEach(function (kid) { node.append(kid); });
    return node;
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  function icon(name, extra) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon" + (extra ? " " + extra : ""));
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.append(use);
    return svg;
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function num(n) { return String(Number(n.toFixed(2))); }
  function baseName(name) { return name.replace(/\.[^./\\]+$/, "") || "drawing"; }
  function safeName(name) {
    const cleaned = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").replace(/^[\s.]+|[\s.]+$/g, "");
    return cleaned || "drawing";
  }
  function megabytes(n) {
    return n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + " KB" : (n / 1048576).toFixed(1) + " MB";
  }
  function attempt(promise) {
    promise.catch(function () { announce("Something went wrong. Try the file again."); });
  }

  const statusLine = $("status");
  function announce(text) {
    statusLine.textContent = "";
    setTimeout(function () { statusLine.textContent = text; }, 40);
  }

  /* theme */
  const themeButton = $("themeToggle");
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  function effectiveTheme() {
    const set = document.documentElement.getAttribute("data-theme");
    return set || (darkQuery.matches ? "dark" : "light");
  }
  function paintThemeButton() {
    const mode = effectiveTheme();
    themeButton.dataset.mode = mode;
    themeButton.setAttribute("aria-label", mode === "dark" ? "Switch to the light theme" : "Switch to the dark theme");
  }
  try {
    const stored = localStorage.getItem("crv2svg-theme");
    if (stored === "light" || stored === "dark") document.documentElement.setAttribute("data-theme", stored);
  } catch (exc) { /* storage can be off; the page then follows the system */ }
  themeButton.addEventListener("click", function () {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("crv2svg-theme", next); } catch (exc) { /* ignore */ }
    paintThemeButton();
  });
  if (darkQuery.addEventListener) darkQuery.addEventListener("change", paintThemeButton);
  paintThemeButton();

  /* the reader, in workers when the browser allows it */
  const pending = new Map();
  let poolReady = null;
  let pool = [];
  let inline = null;
  let rid = 0;

  function onReply(m) {
    if (m.t === "ready") return;
    if (m.t === "rendered") {
      const wait = pending.get(m.rid);
      if (wait) {
        pending.delete(m.rid);
        wait.resolve(m);
      }
      return;
    }
    handleFileMessage(m);
  }

  function workerText() {
    return "const crv2svg = (" + engine.factorySource + ")();\n" +
      createHandler.toString() + "\n" +
      "const handle = createHandler(crv2svg, function (m) { postMessage(m); });\n" +
      "onmessage = function (e) { handle(e.data); };\n";
  }

  function startPool() {
    if (poolReady) return poolReady;
    poolReady = new Promise(function (resolve) {
      let made = [];
      let url = null;
      let settled = false;
      function useInline() {
        if (settled) return;
        settled = true;
        made.forEach(function (w) { try { w.terminate(); } catch (exc) { /* gone already */ } });
        if (url) URL.revokeObjectURL(url);
        const handle = createHandler(engine, function (m) { setTimeout(function () { onReply(m); }, 0); });
        inline = { post: function (m) { setTimeout(function () { handle(m); }, 0); } };
        pool = [inline];
        document.documentElement.dataset.reader = "page";
        resolve();
      }
      try {
        url = URL.createObjectURL(new Blob([workerText()], { type: "text/javascript" }));
        const count = Math.max(1, Math.min(3, (navigator.hardwareConcurrency || 2) - 1));
        let answered = 0;
        for (let i = 0; i < count; i++) {
          const w = new Worker(url);
          w.onerror = function (event) {
            if (event && event.preventDefault) event.preventDefault();
            if (!settled) useInline();
            else workerDied(w);
          };
          w.onmessage = function (event) {
            const m = event.data;
            if (m.t === "ready") {
              answered += 1;
              if (answered === count && !settled) {
                settled = true;
                pool = made.map(function (worker) {
                  return { raw: worker, post: function (msg, transfer) { worker.postMessage(msg, transfer || []); } };
                });
                URL.revokeObjectURL(url);
                document.documentElement.dataset.reader = "worker";
                resolve();
              }
              return;
            }
            onReply(m);
          };
          made.push(w);
          w.postMessage({ t: "hello", n: i });
        }
        setTimeout(useInline, 2500);
      } catch (exc) {
        useInline();
      }
    });
    return poolReady;
  }

  function workerDied(worker) {
    pending.forEach(function (wait, id) {
      if (wait.worker && wait.worker.raw === worker) {
        pending.delete(id);
        wait.resolve({ error: "The reader stopped while drawing this file." });
      }
    });
    files.forEach(function (file) {
      if (file.worker && file.worker.raw === worker && file.status !== "failed") {
        fail(file, { known: false, message: "", partialLayers: 0, stopped: true });
      }
    });
  }

  function pickWorker() {
    let best = pool[0];
    pool.forEach(function (w) { if ((w.load || 0) < (best.load || 0)) best = w; });
    best.load = (best.load || 0) + 1;
    return best;
  }

  function renderRequest(file, kind, sheetIndex) {
    const settings = file.settings;
    const layers = visibleRows(file).filter(function (r) { return !settings.off.has(r.name); })
      .map(function (r) { return r.name; });
    return new Promise(function (resolve) {
      const id = ++rid;
      pending.set(id, { resolve: resolve, worker: file.worker });
      file.worker.post({
        t: "render", id: file.id, rid: id, kind: kind, sheet: file.summary.parts.length > 1 ? sheetIndex : null,
        layers: layers, previews: settings.previews, units: settings.units,
      });
    });
  }

  /* files */
  const files = new Map();
  const order = [];
  let current = null;
  let serial = 0;

  function visibleRows(file) {
    return file.summary.layers.filter(function (r) { return file.settings.previews || !r.preview; });
  }

  async function addFiles(list, folders) {
    const picked = Array.from(list);
    const dirs = folders || [];
    if (!picked.length && !dirs.length) return;
    const first = !order.length;
    startPool();
    const added = [];
    dirs.forEach(function (name) {
      const file = makeFile({ name: name, size: 0 });
      file.status = "failed";
      file.error = { known: false, message: "", partialLayers: 0, folder: true };
      added.push(file);
    });
    picked.forEach(function (blob) { added.push(makeFile(blob)); });
    announce("Reading " + plural(added.length, "file", "files"));
    if (!first) current = added[0].id;
    viewer.reset();
    render();
    if (first) focusTitle();
    for (let i = 0; i < added.length; i++) {
      if (added[i].status !== "failed") await startFile(added[i]);
    }
  }

  function makeFile(blob) {
    const file = {
      id: "f" + (++serial), name: blob.name || "file", size: blob.size, status: "queued", fraction: 0,
      summary: null, worker: null, error: null, partial: false,
      settings: { sheet: 0, off: new Set(), previews: false, units: "", estimate: false, showEmpty: false },
      preview: { key: "", textKey: "", rid: 0, text: "", url: "", w: 1, h: 1, onMaterial: false, sheetShown: -1, refit: true },
      shownAt: Date.now(), busy: false, attention: false,
    };
    files.set(file.id, file);
    order.push(file.id);
    if (!current) current = file.id;
    file.blob = blob;
    return file;
  }

  async function startFile(file) {
    if (file.size === 0) {
      fail(file, { known: false, message: "", partialLayers: 0, empty: true });
      return;
    }
    if (file.size > MAX_BYTES) {
      fail(file, { known: false, message: "", partialLayers: 0, tooBig: true });
      return;
    }
    let buffer;
    try {
      buffer = await file.blob.arrayBuffer();
    } catch (exc) {
      fail(file, { known: false, message: "", partialLayers: 0, unreadable: true });
      return;
    }
    await startPool();
    if (!files.has(file.id)) return;
    file.blob = null;
    file.worker = pickWorker();
    file.status = "reading";
    file.shownAt = Date.now();
    render();
    file.worker.post({ t: "load", id: file.id, buffer: buffer }, [buffer]);
  }

  function handleFileMessage(m) {
    const file = files.get(m.id);
    if (!file) return;
    if (m.t === "progress") {
      file.fraction = m.fraction;
      updateProgress(file);
    } else if (m.t === "opened") {
      finish(file, m);
    } else if (m.t === "failed") {
      fail(file, m);
    } else if (m.t === "estimateFailed") {
      file.settings.estimate = false;
      file.busy = false;
      file.notice = "The estimate could not be applied to this file, so the text stays out. " + m.message;
      render();
    }
  }

  function finish(file, m) {
    if (file.worker) file.worker.load = Math.max(0, (file.worker.load || 1) - 1);
    const reopened = !!file.summary;
    file.summary = m.summary;
    file.partial = m.partial;
    file.status = "ready";
    file.error = null;
    file.busy = false;
    file.attention = m.summary.warnings.length > 0 || m.partial || m.summary.empty || m.summary.heavy;
    file.preview.key = "";
    file.preview.textKey = "";
    if (!reopened) {
      const total = m.summary.parts.length;
      announce(file.name + " is ready" + (total > 1 ? ", " + plural(total, "sheet", "sheets") : ""));
    }
    render();
  }

  function fail(file, m) {
    if (file.worker) file.worker.load = Math.max(0, (file.worker.load || 1) - 1);
    file.status = "failed";
    file.error = m;
    file.busy = false;
    announce(file.name + " could not be read");
    render();
  }

  function removeFile(id) {
    const file = files.get(id);
    if (!file) return;
    if (file.preview.url) URL.revokeObjectURL(file.preview.url);
    if (file.worker && file.worker.post) file.worker.post({ t: "drop", id: id });
    const at = order.indexOf(id);
    files.delete(id);
    order.splice(at, 1);
    if (current === id) {
      current = order.length ? order[Math.min(at, order.length - 1)] : null;
      viewer.reset();
    }
    announce("Removed " + file.name);
    render();
  }

  /* messages in plain words */
  function parseWarning(line) {
    const m = /^(.*) \(x(\d+)\)$/.exec(line);
    const text = m ? m[1] : line;
    const n = m ? Number(m[2]) : 1;
    if (text.indexOf("left out text saved by a release before version 9") === 0) return { code: "old-text", n: n };
    if (text.indexOf("placed text from a release before version 9 by estimate") === 0) return { code: "estimated", n: n };
    if (/^left out text with \d+ lines/.test(text)) return { code: "multi-line", n: n };
    if (text.indexOf("left out text on a curve") === 0) return { code: "curve-text", n: n };
    if (text.indexOf("left out text with an empty base line") === 0) return { code: "empty-text", n: n };
    return { code: "other", n: n, text: text };
  }

  function pieces(n) { return n === 1 ? "1 piece of text" : n + " pieces of text"; }
  function isAre(n) { return n === 1 ? "is" : "are"; }

  function explainError(m) {
    const msg = m.message || "";
    const tech = msg;
    const keep = m.partialLayers > 0;
    let what;
    let todo;
    const record = /'([^']{1,80})'/.exec(msg);
    if (m.folder) {
      what = "That is a folder, not a file.";
      todo = "Open the folder and drop the .crv or .crv3d files from inside it.";
    } else if (m.empty) {
      what = "This file is empty. It has no data in it at all.";
      todo = "Copy it again from where it came from. A download or copy that was interrupted can leave an empty file.";
    } else if (m.stopped) {
      what = "The reader stopped while working on this file, so it had to be closed.";
      todo = "Remove it and add it again. If it keeps happening, the drawing may be too large for this page.";
    } else if (m.tooBig) {
      what = "This file is larger than 400 MB, which is more than this page can safely read.";
      todo = "Open it in the original program and save a smaller copy, or use the command-line version of crv2svg.";
    } else if (m.unreadable) {
      what = "Your browser could not read this file from your computer.";
      todo = "Check that the file is still where it was, then drop it here again.";
    } else if (!m.known) {
      what = "Something unexpected stopped the reader.";
      todo = "Try the file again. If it keeps happening, report it at github.com/munzzyy/crv2svg and say which program saved the file.";
    } else if (/^not a compound file/.test(msg)) {
      what = "This is not a Vectric project file. It may have been renamed, or saved in another format.";
      todo = "Check that it ends in .crv or .crv3d and opens in VCarve, Aspire or Cut2D. If it came by email or chat, ask for the original.";
    } else if (/compound file/.test(msg)) {
      what = "The file looks damaged or cut short.";
      todo = "Copy it again from where it came from. A download or transfer that stopped early is the usual cause.";
    } else if (/^no VectorData/.test(msg)) {
      what = "There is no 2D drawing inside this file. It may be a 3D-only project, or saved by a release this page has not seen.";
      todo = "If you expected a drawing, use Copy details and paste it into a report at github.com/munzzyy/crv2svg.";
    } else if (/cannot decode yet|not decoded yet|cannot step over yet/.test(msg)) {
      what = "This file uses a feature this page does not support yet" + (record ? " (" + record[1] + ")." : ".");
      todo = "To get it added, use Copy details and paste it into a report at github.com/munzzyy/crv2svg." + (keep ? " You can also keep what was read before it." : "");
    } else if (/nested more than/.test(msg)) {
      what = "Objects in this file sit inside each other more deeply than this page allows.";
      todo = "In the original program, ungroup the objects and save again." + (keep ? " Or keep what was read before that point." : "");
    } else if (/has version \d+, this reader knows/.test(msg)) {
      what = "Part of this file uses a newer layout than this page knows.";
      todo = "Use Copy details and paste it into a report at github.com/munzzyy/crv2svg so support can be added." + (keep ? " You can keep what was read before it." : "");
    } else {
      what = "The file looks damaged, or it uses a layout this page has not seen.";
      todo = "Try a fresh copy. If that does not help, use Copy details and paste it into a report at github.com/munzzyy/crv2svg." + (keep ? " You can also keep what was read before the problem." : "");
    }
    return { what: what, todo: todo, tech: tech, keep: keep };
  }

  /* the screen */
  const startEl = $("start");
  const workEl = $("work");
  const filesEl = $("files");
  const listEl = $("fileList");
  const docTitle = $("docTitle");
  const docFacts = $("docFacts");
  const docState = $("docState");
  const docBody = $("docBody");
  const tabsEl = $("sheetTabs");
  const noticesEl = $("notices");
  const layerListEl = $("layerList");
  const previewsRow = $("previewsRow");
  const previewsBox = $("previews");
  const unitsSel = $("units");
  const dlSvg = $("dlSvg");
  const dlDxf = $("dlDxf");
  const dlNote = $("dlNote");
  const dlAll = $("dlAll");
  const everything = $("everything");
  const picker = $("picker");

  docTitle.setAttribute("tabindex", "-1");

  function focusTitle() {
    setTimeout(function () { docTitle.focus({ preventScroll: true }); }, 60);
  }

  function currentFile() { return current ? files.get(current) : null; }

  function keepFocus(work) {
    const active = document.activeElement;
    const key = active && active.dataset ? active.dataset.focus : "";
    work();
    if (key) {
      const again = document.querySelector('[data-focus="' + key + '"]');
      if (again && again !== active) again.focus({ preventScroll: true });
    }
  }

  function stateLabel(file) {
    if (file.status === "queued") return "Waiting";
    if (file.status === "reading") return file.fraction > 0 ? "Reading, " + Math.round(file.fraction * 100) + "%" : "Reading";
    if (file.status === "failed") return "Could not be read";
    if (file.partial) return "Partial, check before use";
    const sheets = file.summary.parts.length;
    const base = sheets > 1 ? "Ready, " + plural(sheets, "sheet", "sheets") : "Ready";
    return file.attention ? base + ", has notes" : base;
  }

  function renderList() {
    keepFocus(drawList);
  }

  function drawList() {
    const many = order.length > 1;
    filesEl.hidden = !many;
    workEl.classList.toggle("has-list", many);
    listEl.replaceChildren();
    order.forEach(function (id) {
      const file = files.get(id);
      const stateKey = file.status === "failed" ? "failed" : file.status === "ready" ? (file.attention ? "attention" : "ready") : "busy";
      const glyph = stateKey === "failed" ? "error" : stateKey === "attention" ? "warn" : stateKey === "ready" ? "check" : "spin";
      const state = el("span", { class: "file-state" }, [icon(glyph, stateKey === "busy" ? "spin" : "")]);
      const main = el("button", { type: "button", class: "file-main" }, [
        state, el("span", { class: "file-name", text: file.name }), el("span", { class: "file-sub", text: stateLabel(file) }),
      ]);
      main.setAttribute("aria-current", id === current ? "true" : "false");
      main.dataset.focus = "main-" + id;
      main.addEventListener("click", function () { select(id); });
      const gone = el("button", { type: "button", class: "file-x", "aria-label": "Remove " + file.name }, [icon("x")]);
      gone.dataset.focus = "gone-" + id;
      gone.addEventListener("click", function () { removeFile(id); });
      const row = el("li", { class: "file" }, [main, gone]);
      row.dataset.id = id;
      row.dataset.state = stateKey;
      row.dataset.current = id === current ? "true" : "false";
      listEl.append(row);
    });
    const ready = order.filter(function (id) { return files.get(id).status === "ready"; }).length;
    everything.disabled = ready === 0;
  }

  function updateListState(file) {
    const row = listEl.querySelector('[data-id="' + file.id + '"] .file-sub');
    if (row) row.textContent = stateLabel(file);
  }

  function select(id) {
    if (current === id) return;
    current = id;
    viewer.reset();
    render();
  }

  function render() {
    const any = order.length > 0;
    startEl.hidden = any;
    workEl.hidden = !any;
    $("addMore").hidden = !any;
    document.body.classList.toggle("loaded", any);
    if (!any) return;
    renderList();
    renderDoc();
  }

  function renderDoc() {
    const file = currentFile();
    docTitle.textContent = file.name;
    docFacts.replaceChildren();
    if (file.status !== "ready") {
      docBody.hidden = true;
      const wait = 260 - (Date.now() - file.shownAt);
      if ((file.status === "reading" || file.status === "queued") && wait > 0) {
        docState.hidden = true;
        setTimeout(function () { if (currentFile() === file && file.status !== "ready") render(); }, wait);
        return;
      }
      renderState(file);
      return;
    }
    docState.hidden = true;
    docBody.hidden = false;
    renderFacts(file);
    renderTabs(file);
    renderDownloads(file);
    renderNotices(file);
    renderSize(file);
    renderLayers(file);
    requestPreview(file);
  }

  function renderFacts(file) {
    const s = file.summary;
    const bits = [];
    if (s.parts.length > 1) bits.push(plural(s.parts.length, "sheet", "sheets"));
    bits.push("Written by " + (s.product || "an unknown program") + (s.version ? " " + s.version : ""));
    bits.push(megabytes(file.size || 0));
    bits.forEach(function (text) { docFacts.append(el("span", { text: text })); });
  }

  /* the reading and failure states */
  let meterTimer = 0;
  function renderState(file) {
    docState.hidden = false;
    docState.replaceChildren();
    if (file.status === "queued" || file.status === "reading") {
      const label = file.status === "queued" ? "Waiting for a turn" : "Reading the file";
      const meter = el("div", { class: "meter waiting", role: "progressbar", "aria-label": "Reading " + file.name, "aria-valuemin": "0", "aria-valuemax": "100" }, [el("i")]);
      const line = el("p", { id: "readLine", text: label + ", " + megabytes(file.size || 0) });
      docState.append(el("div", { class: "state-title" }, [icon("spin", "spin"), el("h3", { text: "Reading this file" })]), line, meter);
      docState.dataset.progress = file.id;
      updateProgress(file);
      return;
    }
    const e = explainError(file.error);
    const title = file.error.partialLayers > 0 ? "Read only part of this file" : "Could not read this file";
    const part = file.error.partialLayers > 0;
    docState.append(el("div", { class: "state-title " + (part ? "part" : "bad") }, [icon(part ? "warn" : "error"), el("h3", { text: title })]), el("p", { text: e.what }),
      el("p", { text: file.error.partialLayers > 0 ? "Nothing has been saved. Your original file is untouched." : "Nothing was saved and your original file is untouched." }),
      el("p", { text: e.todo }));
    const actions = el("div", { class: "state-actions" });
    if (e.keep) {
      const keep = el("button", { type: "button", class: "btn primary", text: "Keep what was read (" + plural(file.error.partialLayers, "layer", "layers") + ")" });
      keep.addEventListener("click", function () {
        file.status = "reading";
        file.shownAt = Date.now();
        file.worker.post({ t: "keep", id: file.id });
        render();
      });
      actions.append(keep);
    }
    if (e.tech) {
      const copy = el("button", { type: "button", class: "btn" }, [icon("copy"), document.createTextNode("Copy details")]);
      copy.addEventListener("click", function () { copyText(e.tech, copy); });
      actions.append(copy);
    }
    const remove = el("button", { type: "button", class: "btn", text: "Remove this file" });
    remove.addEventListener("click", function () { removeFile(file.id); });
    actions.append(remove);
    docState.append(actions);
    if (e.tech) {
      docState.append(el("details", {}, [el("summary", { text: "Details for a report" }), el("pre", { text: e.tech })]));
    }
  }

  function updateProgress(file) {
    updateListState(file);
    if (current !== file.id || docState.hidden) return;
    const meter = docState.querySelector(".meter");
    if (meter) {
      const pct = Math.round(file.fraction * 100);
      if (file.fraction > 0) {
        meter.classList.remove("waiting");
        meter.setAttribute("aria-valuenow", String(pct));
        meter.firstChild.style.width = pct + "%";
      }
      const line = $("readLine");
      if (line) line.textContent = "Reading the file, " + megabytes(file.size || 0) + (file.fraction > 0 ? ", " + pct + "%" : "");
    }
  }

  async function copyText(text, button) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (exc) {
      const area = el("textarea", { class: "sr", "aria-hidden": "true" });
      area.value = text;
      document.body.append(area);
      area.select();
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      area.remove();
    }
    announce(ok ? "Details copied" : "Could not copy, select the details and copy them by hand");
    if (ok) {
      const label = button.lastChild;
      const old = label.textContent;
      label.textContent = "Copied";
      setTimeout(function () { label.textContent = old; }, 1600);
    }
  }

  /* sheets */
  function renderTabs(file) {
    keepFocus(function () { drawTabs(file); });
  }

  function drawTabs(file) {
    const parts = file.summary.parts;
    tabsEl.hidden = parts.length < 2;
    tabsEl.replaceChildren();
    $("viewer").removeAttribute("aria-labelledby");
    if (parts.length < 2) return;
    parts.forEach(function (count, i) {
      const tab = el("button", { type: "button", class: "tab", role: "tab", id: "tab" + i, "aria-selected": i === file.settings.sheet ? "true" : "false", "aria-controls": "viewer", tabindex: i === file.settings.sheet ? "0" : "-1" }, [
        el("span", { class: "tab-name", text: "Sheet " + (i + 1) }),
        document.createTextNode(" "),
        el("span", { class: "tab-sub", text: plural(count, "part", "parts") }),
      ]);
      tab.dataset.focus = "tab-" + i;
      tab.addEventListener("click", function () { chooseSheet(file, i); });
      tab.addEventListener("keydown", function (event) {
        let to = -1;
        if (event.key === "ArrowRight") to = (i + 1) % parts.length;
        else if (event.key === "ArrowLeft") to = (i + parts.length - 1) % parts.length;
        else if (event.key === "Home") to = 0;
        else if (event.key === "End") to = parts.length - 1;
        if (to >= 0) {
          event.preventDefault();
          chooseSheet(file, to);
        }
      });
      tabsEl.append(tab);
    });
    $("viewer").setAttribute("aria-labelledby", "tab" + file.settings.sheet);
  }

  function chooseSheet(file, i) {
    if (file.settings.sheet === i) return;
    file.settings.sheet = i;
    viewer.reset();
    renderTabs(file);
    renderDownloads(file);
    renderLayers(file);
    renderNotices(file);
    requestPreview(file);
    announce("Sheet " + (i + 1) + ", " + plural(file.summary.parts[i], "part", "parts"));
  }

  /* downloads */
  function sheetCount(file) { return file.summary.parts.length; }

  function nameFor(file, kind, sheetIndex) {
    const base = safeName(baseName(file.name));
    return base + (sheetCount(file) > 1 ? "-sheet" + (sheetIndex + 1) : "") + "." + kind;
  }

  function drawsAnything(file) {
    const i = file.settings.sheet;
    return visibleRows(file).some(function (r) {
      if (file.settings.off.has(r.name)) return false;
      return (sheetCount(file) > 1 ? r.segments[i] : r.total) > 0;
    });
  }

  function hasContent(file) {
    const i = file.settings.sheet;
    return visibleRows(file).some(function (r) { return (sheetCount(file) > 1 ? r.segments[i] : r.total) > 0; });
  }

  function renderDownloads(file) {
    const ok = drawsAnything(file);
    dlSvg.disabled = !ok || file.busy;
    dlDxf.disabled = !ok || file.busy;
    const multi = sheetCount(file) > 1;
    dlAll.hidden = !multi;
    if (multi) {
      $("dlAllTitle").textContent = "All " + sheetCount(file) + " sheets in one ZIP";
      $("dlAllSvg").disabled = file.busy;
      $("dlAllDxf").disabled = file.busy;
    }
    if (file.summary.empty) dlNote.textContent = "There is no 2D drawing in this file, so there is nothing to save.";
    else if (!ok && !hasContent(file)) dlNote.textContent = sheetCount(file) > 1 ? "This sheet has no drawing on it. Try another sheet." : "There is no drawing on the layers shown.";
    else if (!ok) dlNote.textContent = "Turn on a layer that has something in it to save a drawing.";
    else if (multi) dlNote.textContent = "These two save sheet " + (file.settings.sheet + 1) + " of " + sheetCount(file) + ".";
    else dlNote.textContent = "Saved at real size, with the layers you have switched on.";
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: filename, hidden: "" });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 20000);
  }

  async function fetchText(file, kind, sheetIndex) {
    const key = previewKey(file);
    if (kind === "svg" && sheetIndex === file.settings.sheet && file.preview.textKey === key) return file.preview.text;
    const reply = await renderRequest(file, kind, sheetIndex);
    if (reply.error) throw new Error(reply.error);
    return reply.text;
  }

  /* The clicked button stays enabled so keyboard focus is not dropped; this flag ignores a second click. */
  let saving = false;
  const savedTimers = new Map();

  function setSaving(on) {
    saving = on;
    [dlSvg, dlDxf, $("dlAllSvg"), $("dlAllDxf"), everything].forEach(function (b) {
      if (on) b.setAttribute("aria-busy", "true");
      else b.removeAttribute("aria-busy");
    });
  }

  function say(target, text, ms) {
    clearTimeout(savedTimers.get(target));
    target.textContent = text;
    target.hidden = !text;
    if (text) savedTimers.set(target, setTimeout(function () { target.hidden = true; }, ms || 8000));
  }

  async function downloadOne(kind) {
    const file = currentFile();
    if (!file || file.status !== "ready" || saving) return;
    setSaving(true);
    say($("dlSaved"), "");
    try {
      const text = await fetchText(file, kind, file.settings.sheet);
      const name = nameFor(file, kind, file.settings.sheet);
      saveBlob(new Blob([text], { type: kind === "svg" ? "image/svg+xml;charset=utf-8" : "application/dxf;charset=utf-8" }), name);
      announce("Saving " + name);
      say($("dlSaved"), "Saved " + name);
    } catch (exc) {
      showDownloadError(file, exc);
    }
    setSaving(false);
    if (currentFile() === file) renderDownloads(file);
  }

  function showDownloadError(file, exc) {
    file.notice = "Could not write this file: " + (exc && exc.message ? exc.message.replace(/\.$/, "") : "unknown problem") + ". Nothing was saved.";
    renderNotices(file);
  }

  async function downloadSheets(kind) {
    const file = currentFile();
    if (!file || saving) return;
    setSaving(true);
    say($("dlSaved"), "");
    try {
      const entries = [];
      for (let i = 0; i < sheetCount(file); i++) {
        announce("Preparing sheet " + (i + 1) + " of " + sheetCount(file));
        entries.push({ name: nameFor(file, kind, i), text: await fetchText(file, kind, i) });
      }
      const name = safeName(baseName(file.name)) + "-" + kind + ".zip";
      saveBlob(makeZip(entries), name);
      announce("Saving " + name);
      say($("dlSaved"), "Saved " + name + " with " + plural(entries.length, "file", "files"));
    } catch (exc) {
      showDownloadError(file, exc);
    }
    setSaving(false);
    if (currentFile() === file) renderDownloads(file);
  }

  async function downloadEverything() {
    const ready = order.map(function (id) { return files.get(id); }).filter(function (f) { return f.status === "ready"; });
    if (!ready.length || saving) return;
    setSaving(true);
    say($("everyNote"), "");
    const entries = [];
    const used = new Set();
    try {
      for (let n = 0; n < ready.length; n++) {
        const file = ready[n];
        announce("Preparing " + file.name + ", file " + (n + 1) + " of " + ready.length);
        for (let i = 0; i < sheetCount(file); i++) {
          for (const kind of ["svg", "dxf"]) {
            let name = nameFor(file, kind, i);
            let k = 1;
            while (used.has(name.toLowerCase())) {
              k += 1;
              name = name.replace(/(\.[a-z]+)$/, "-" + k + "$1");
            }
            used.add(name.toLowerCase());
            entries.push({ name: name, text: await fetchText(file, kind, i) });
          }
        }
      }
      saveBlob(makeZip(entries), "crv2svg-drawings.zip");
      const failed = order.filter(function (id) { return files.get(id).status === "failed"; }).map(function (id) { return files.get(id).name; });
      const waiting = order.length - ready.length - failed.length;
      let line = "Saved crv2svg-drawings.zip with " + plural(entries.length, "file", "files") + ".";
      if (failed.length) line += " Left out because they could not be read: " + failed.join(", ") + ".";
      if (waiting) line += " " + plural(waiting, "file was", "files were") + " still being read and " + (waiting === 1 ? "was" : "were") + " left out.";
      announce(line);
      say($("everyNote"), line, failed.length || waiting ? 20000 : 8000);
    } catch (exc) {
      const line = "Could not make the ZIP: " + (exc && exc.message ? exc.message : "unknown problem");
      announce(line);
      say($("everyNote"), line, 20000);
    }
    setSaving(false);
    renderList();
  }

  /* a stored ZIP, written by hand: no compression, no library */
  const CRC_TABLE = (function () {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  function makeZip(entries) {
    const encoder = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;
    entries.forEach(function (entry) {
      const name = encoder.encode(entry.name);
      const data = encoder.encode(entry.text);
      const crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);
      local.setUint16(8, 0, true);
      local.setUint16(10, 0, true);
      local.setUint16(12, 0x21, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, data.length, true);
      local.setUint32(22, data.length, true);
      local.setUint16(26, name.length, true);
      local.setUint16(28, 0, true);
      parts.push(local.buffer, name, data);
      const dir = new DataView(new ArrayBuffer(46));
      dir.setUint32(0, 0x02014b50, true);
      dir.setUint16(4, 20, true);
      dir.setUint16(6, 20, true);
      dir.setUint16(8, 0x0800, true);
      dir.setUint16(10, 0, true);
      dir.setUint16(12, 0, true);
      dir.setUint16(14, 0x21, true);
      dir.setUint32(16, crc, true);
      dir.setUint32(20, data.length, true);
      dir.setUint32(24, data.length, true);
      dir.setUint16(28, name.length, true);
      dir.setUint32(42, offset, true);
      central.push(dir.buffer, name);
      offset += 30 + name.length + data.length;
      if (offset > 0xf0000000) throw new Error("these files add up to more than a ZIP can hold");
    });
    let size = 0;
    central.forEach(function (chunk) { size += chunk.byteLength; });
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, size, true);
    end.setUint32(16, offset, true);
    return new Blob(parts.concat(central, [end.buffer]), { type: "application/zip" });
  }

  /* notices */
  function noticeBox(kind, title, lines, extra) {
    const glyph = kind === "error" ? "error" : kind === "warn" ? "warn" : "info";
    const body = el("div", { class: "notice-body" }, [el("strong", { text: title })]);
    lines.forEach(function (text) { body.append(el("span", { text: text })); });
    if (extra) body.append(extra);
    return el("div", { class: "notice " + kind }, [icon(glyph), body]);
  }

  function estimateSwitch(file) {
    const box = el("input", { type: "checkbox", role: "switch" });
    box.checked = file.settings.estimate;
    box.dataset.focus = "estimate";
    box.addEventListener("change", function () {
      file.settings.estimate = box.checked;
      file.busy = true;
      renderDownloads(file);
      showBusy(true, "Placing text");
      file.worker.post({ t: "estimate", id: file.id, estimate: box.checked });
    });
    return el("label", { class: "switch" }, [box, el("span", { class: "switch-text" }, [
      document.createTextNode("Place older text by estimate"),
      el("small", { text: "Placed by estimate, can be off by about a twentieth of the text's width, check before cutting." }),
    ])]);
  }

  function renderNotices(file) {
    keepFocus(function () { drawNotices(file); });
  }

  function drawNotices(file) {
    noticesEl.replaceChildren();
    const s = file.summary;
    const parsed = s.warnings.map(parseWarning);
    const version = s.version ? "version " + s.version : "an older release";
    let switchPlaced = false;
    if (file.partial) {
      noticesEl.append(noticeBox("warn", "Only part of the file was read",
        ["Reading stopped before the end, so some of the drawing may be missing. Compare the result with the original before you cut anything."]));
    }
    parsed.forEach(function (w) {
      if (w.code === "old-text") {
        const extra = switchPlaced ? null : estimateSwitch(file);
        switchPlaced = true;
        noticesEl.append(noticeBox("warn", pieces(w.n) + " from an older release " + isAre(w.n) + " left out",
          ["This file was saved by " + version + ". Releases before 9 store text in a way this page cannot place exactly. Retype it in your CAM program, or place it by estimate."], extra));
      } else if (w.code === "estimated") {
        const extra = switchPlaced ? null : estimateSwitch(file);
        switchPlaced = true;
        noticesEl.append(noticeBox("warn", pieces(w.n) + " placed by estimate",
          ["It can be off by about a twentieth of the text's width. Check it against the original before cutting."], extra));
      } else if (w.code === "multi-line") {
        noticesEl.append(noticeBox("warn", "Text with more than one line is left out",
          [plural(w.n, "block", "blocks") + " " + isAre(w.n) + " not in the drawing. In the original program, convert the text to curves and save again, or retype it in your CAM program."]));
      } else if (w.code === "curve-text") {
        noticesEl.append(noticeBox("warn", "Text on a curve is left out",
          [plural(w.n, "block", "blocks") + " " + isAre(w.n) + " not in the drawing. Convert the text to curves in the original program and save again, or retype it in your CAM program."]));
      } else if (w.code === "empty-text") {
        noticesEl.append(noticeBox("warn", "Some text is left out",
          [w.n === 1 ? "1 block has no usable line to sit on, so it is not in the drawing." : w.n + " blocks have no usable line to sit on, so they are not in the drawing."]));
      } else {
        noticesEl.append(noticeBox("warn", "Something was left out", [w.text + (w.n > 1 ? " (" + w.n + " times)" : "")]));
      }
    });
    if (file.settings.estimate && !switchPlaced) {
      noticesEl.append(noticeBox("info", "Older text by estimate", ["There is no older text in this file to place."], estimateSwitch(file)));
    }
    if (s.units === null && !file.settings.units) {
      noticesEl.append(noticeBox("info", "The file does not say its units",
        ["The SVG will have no units, and the DXF will not say either. If you know them, pick inches or millimetres under Units."]));
    }
    if (file.settings.units && s.units && file.settings.units !== s.units) {
      noticesEl.append(noticeBox("warn", "The unit label was changed",
        ["The file says " + unitName(s.units) + ". Saved files will say " + unitName(file.settings.units) + " on the same numbers, so nothing is resized or converted. Pick \"As saved\" under Units to undo this."]));
    }
    if (file.notice) noticesEl.append(noticeBox("error", "Something did not work", [file.notice]));
    if (s.empty) {
      noticesEl.append(noticeBox("warn", "There is no 2D drawing in this file",
        [s.bytes >= 1048576
          ? "This file is mostly 3D model or picture data, which this page does not read. There is nothing to save."
          : "The file has layers but nothing drawn on them, so there is nothing to save."]));
    } else if (s.heavy) {
      noticesEl.append(noticeBox("warn", "Most of this file is not 2D drawing",
        ["This file is mostly 3D model or picture data, which this page does not read. Only the 2D vectors were saved, and there are very few of them."]));
    }
    if (!s.empty && !drawsAnything(file)) {
      const sheetHas = hasContent(file);
      noticesEl.append(noticeBox("info", "Nothing to save with these layers",
        [!sheetHas ? (sheetCount(file) > 1 ? "This sheet has no drawing on it. Try another sheet." : "This file has no drawing on the layers shown. Toolpath previews are hidden unless you switch them on.")
          : file.settings.previews ? "Turn on a layer that has something on this sheet." : "Every layer with a drawing on this sheet is switched off."]));
    }
  }

  /* size, units and layers */
  function unitName(units) { return units === "in" ? "inches" : "millimetres"; }
  function unitWord(units) { return units === "in" ? "inches" : units === "mm" ? "mm" : ""; }

  function renderSize(file) {
    const s = file.summary;
    const units = file.settings.units || s.units;
    const word = unitWord(units);
    let big;
    let note;
    const relabelled = !!file.settings.units && file.settings.units !== s.units;
    if (s.material) {
      big = num(s.material[2]) + " by " + num(s.material[3]) + (word ? " " + word : "");
      note = relabelled
        ? "Same numbers as in the file. You changed the unit label, nothing was resized."
        : "Material size, from the file." + (word ? "" : " Units are not stored.");
    } else if (file.preview.text) {
      big = num(file.preview.w) + " by " + num(file.preview.h) + (word ? " " + word : "");
      note = relabelled
        ? "Same numbers as in the file. You changed the unit label, nothing was resized."
        : "The file stores no material size, so this is the size of the drawing.";
    } else {
      big = "Measuring";
      note = "";
    }
    $("sizeBig").textContent = big;
    $("sizeNote").textContent = note;
    unitsSel.replaceChildren(
      el("option", { value: "", text: s.units ? "As saved: " + (s.units === "in" ? "inches" : "millimetres") : "Not stored in the file" }),
      el("option", { value: "in", text: "Inches" }),
      el("option", { value: "mm", text: "Millimetres" }));
    unitsSel.value = file.settings.units;
  }

  function renderLayers(file) {
    const rows = visibleRows(file);
    const i = file.settings.sheet;
    const multi = sheetCount(file) > 1;
    previewsRow.hidden = !file.summary.layers.some(function (r) { return r.preview; });
    previewsBox.checked = file.settings.previews;
    $("layersSub").textContent = multi ? "on sheet " + (i + 1) : "";
    layerListEl.replaceChildren();
    if (!rows.length) {
      layerListEl.append(el("li", { class: "layer-count", text: "No layers with a drawing in this file." }));
      return;
    }
    const count = function (row) { return multi ? row.segments[i] : row.total; };
    const full = rows.filter(function (row) { return count(row) > 0; });
    const empty = rows.filter(function (row) { return count(row) === 0; });
    full.forEach(function (row) { layerListEl.append(layerRow(file, row, count(row))); });
    if (!empty.length) return;
    const open = file.settings.showEmpty || !full.length;
    const toggle = el("button", { type: "button", class: "layer-fold", "aria-expanded": open ? "true" : "false" }, [
      el("span", { text: plural(empty.length, "empty layer", "empty layers") + (multi ? " on this sheet" : "") }),
      el("span", { class: "layer-fold-act", text: open ? "Hide" : "Show" }),
    ]);
    toggle.dataset.focus = "fold";
    toggle.addEventListener("click", function () {
      file.settings.showEmpty = !open;
      keepFocus(function () { renderLayers(file); });
    });
    layerListEl.append(el("li", {}, [toggle]));
    if (open) empty.forEach(function (row) { layerListEl.append(layerRow(file, row, 0)); });
  }

  function layerRow(file, row, n) {
    const box = el("input", { type: "checkbox" });
    box.checked = !file.settings.off.has(row.name);
    const swatch = el("span", { class: "swatch", "aria-hidden": "true" });
    swatch.style.backgroundColor = row.color;
    const name = row.name || "(no name)";
    const label = el("label", { class: "layer" + (n === 0 ? " none" : "") }, [
      box, swatch, el("span", { class: "layer-name", text: name, title: name }),
      el("span", { class: "layer-count", text: n === 0 ? "none here" : plural(n, "segment", "segments") }),
    ]);
    if (row.layers > 1) label.title = row.layers + " layers share this name and switch together";
    box.addEventListener("change", function () {
      if (box.checked) file.settings.off.delete(row.name);
      else file.settings.off.add(row.name);
      renderDownloads(file);
      renderNotices(file);
      requestPreview(file);
    });
    return el("li", {}, [label]);
  }

  previewsBox.addEventListener("change", function () {
    const file = currentFile();
    if (!file) return;
    file.settings.previews = previewsBox.checked;
    renderLayers(file);
    renderDownloads(file);
    renderNotices(file);
    requestPreview(file);
  });

  unitsSel.addEventListener("change", function () {
    const file = currentFile();
    if (!file) return;
    file.settings.units = unitsSel.value;
    renderSize(file);
    renderNotices(file);
    requestPreview(file);
  });

  /* the preview */
  const viewerEl = $("viewer");
  const paperEl = $("paper");
  const paperImg = $("paperImg");
  const chipEl = $("chip");
  const busyEl = $("busy");
  let busyTimer = 0;

  function showBusy(on, label) {
    clearTimeout(busyTimer);
    if (!on) {
      busyEl.hidden = true;
      return;
    }
    busyEl.lastChild.textContent = label || "Drawing";
    busyTimer = setTimeout(function () { busyEl.hidden = false; }, 160);
  }

  function previewKey(file) {
    const s = file.settings;
    const names = visibleRows(file).filter(function (r) { return !s.off.has(r.name); }).map(function (r) { return r.name; });
    return JSON.stringify([file.id, s.sheet, s.previews, s.units, s.estimate, names]);
  }

  let shownUrl = "";

  function applyPreview(file) {
    const p = file.preview;
    paperImg.src = p.url;
    paperImg.alt = "Preview of " + file.name + (sheetCount(file) > 1 ? ", sheet " + (file.settings.sheet + 1) : "");
    viewer.setPage(p.w, p.h, p.refit);
    shownUrl = p.url;
    renderSize(file);
    const mat = file.summary.material;
    const units = unitWord(file.settings.units || file.summary.units);
    chipEl.hidden = false;
    chipEl.textContent = mat && p.onMaterial
      ? "The light area is the material, " + num(mat[2]) + " by " + num(mat[3]) + (units ? " " + units : "") + "."
      : mat ? "The drawing reaches past the material, so the whole drawing is shown." : "The file stores no material size, so the page is cut to the drawing.";
  }

  async function requestPreview(file) {
    const key = previewKey(file);
    const p = file.preview;
    if (p.key === key && p.textKey === key) {
      showBusy(false);
      if (current === file.id && shownUrl !== p.url) applyPreview(file);
      return;
    }
    if (p.key === key) return;
    p.key = key;
    const mine = ++p.rid;
    showBusy(true, "Drawing");
    const reply = await renderRequest(file, "svg", file.settings.sheet);
    if (mine !== p.rid || !files.has(file.id)) return;
    showBusy(false);
    if (reply.error) {
      p.key = "";
      file.notice = "The preview could not be drawn: " + reply.error;
      if (current === file.id) renderNotices(file);
      return;
    }
    file.notice = "";
    if (p.url) URL.revokeObjectURL(p.url);
    p.url = URL.createObjectURL(new Blob([reply.text], { type: "image/svg+xml" }));
    p.text = reply.text;
    p.textKey = key;
    const w = reply.page[2] - reply.page[0];
    const h = reply.page[3] - reply.page[1];
    p.refit = w !== p.w || h !== p.h || p.sheetShown !== file.settings.sheet;
    p.w = w;
    p.h = h;
    p.onMaterial = reply.onMaterial;
    p.sheetShown = file.settings.sheet;
    if (current === file.id) {
      applyPreview(file);
      renderNotices(file);
    }
  }

  /* pan and zoom: the picture is resized once the zoom settles, so lines stay sharp */
  const viewer = (function () {
    const v = { x: 0, y: 0, s: 1, sc: 1, w: 1, h: 1, fit: 1, fitted: true, ready: false };
    const pointers = new Map();
    let settle = 0;
    let pinch = 0;

    function margin() { return Math.min(28, Math.round(viewerEl.clientWidth * 0.06)); }

    function limits() {
      return { min: v.fit * 0.4, max: Math.min(v.fit * 80, 40000 / Math.max(v.w, v.h)) };
    }

    function paint() {
      paperEl.style.transform = "translate(" + v.x + "px," + v.y + "px) scale(" + (v.s / v.sc) + ")";
    }

    function commit() {
      clearTimeout(settle);
      v.sc = v.s;
      paperEl.style.width = v.w * v.sc + "px";
      paperEl.style.height = v.h * v.sc + "px";
      paint();
    }

    function later() {
      clearTimeout(settle);
      settle = setTimeout(commit, 140);
    }

    function fit() {
      const vw = viewerEl.clientWidth;
      const vh = viewerEl.clientHeight;
      const m = margin();
      v.fit = Math.max(1e-9, Math.min((vw - 2 * m) / v.w, (vh - 2 * m) / v.h));
      v.s = v.fit;
      v.x = (vw - v.w * v.s) / 2;
      v.y = (vh - v.h * v.s) / 2;
      v.fitted = true;
      commit();
    }

    function zoomAt(factor, cx, cy) {
      if (!v.ready) return;
      const lim = limits();
      const next = Math.min(lim.max, Math.max(lim.min, v.s * factor));
      const k = next / v.s;
      v.x = cx - (cx - v.x) * k;
      v.y = cy - (cy - v.y) * k;
      v.s = next;
      v.fitted = false;
      touched();
      paint();
      later();
    }

    function touched() { $("hint").hidden = true; }

    function center() { return [viewerEl.clientWidth / 2, viewerEl.clientHeight / 2]; }

    viewerEl.addEventListener("wheel", function (event) {
      if (!v.ready) return;
      event.preventDefault();
      const rect = viewerEl.getBoundingClientRect();
      const lines = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1;
      zoomAt(Math.exp(-event.deltaY * lines * (event.ctrlKey ? 0.01 : 0.0016)), event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });

    viewerEl.addEventListener("pointerdown", function (event) {
      if (event.target.closest(".tools")) return;
      viewerEl.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, [event.clientX, event.clientY]);
      viewerEl.classList.add("dragging");
      pinch = pointers.size === 2 ? distance() : 0;
    });

    function distance() {
      const pts = Array.from(pointers.values());
      return Math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]) || 1;
    }

    viewerEl.addEventListener("pointermove", function (event) {
      const last = pointers.get(event.pointerId);
      if (!last || !v.ready) return;
      const rect = viewerEl.getBoundingClientRect();
      if (pointers.size === 1) {
        v.x += event.clientX - last[0];
        v.y += event.clientY - last[1];
        v.fitted = false;
        touched();
        paint();
      } else if (pointers.size === 2) {
        const before = Array.from(pointers.values());
        const midBefore = [(before[0][0] + before[1][0]) / 2, (before[0][1] + before[1][1]) / 2];
        pointers.set(event.pointerId, [event.clientX, event.clientY]);
        const after = Array.from(pointers.values());
        const midAfter = [(after[0][0] + after[1][0]) / 2, (after[0][1] + after[1][1]) / 2];
        const d = distance();
        v.x += midAfter[0] - midBefore[0];
        v.y += midAfter[1] - midBefore[1];
        zoomAt(d / (pinch || d), midAfter[0] - rect.left, midAfter[1] - rect.top);
        pinch = d;
        return;
      }
      pointers.set(event.pointerId, [event.clientX, event.clientY]);
    });

    function release(event) {
      pointers.delete(event.pointerId);
      pinch = pointers.size === 2 ? distance() : 0;
      if (!pointers.size) viewerEl.classList.remove("dragging");
    }
    viewerEl.addEventListener("pointerup", release);
    viewerEl.addEventListener("pointercancel", release);

    viewerEl.addEventListener("keydown", function (event) {
      if (!v.ready) return;
      const step = 60;
      const c = center();
      let handled = true;
      if (event.key === "+" || event.key === "=") zoomAt(1.25, c[0], c[1]);
      else if (event.key === "-" || event.key === "_") zoomAt(0.8, c[0], c[1]);
      else if (event.key === "0") fit();
      else if (event.key === "ArrowLeft") { v.x += step; v.fitted = false; paint(); }
      else if (event.key === "ArrowRight") { v.x -= step; v.fitted = false; paint(); }
      else if (event.key === "ArrowUp") { v.y += step; v.fitted = false; paint(); }
      else if (event.key === "ArrowDown") { v.y -= step; v.fitted = false; paint(); }
      else handled = false;
      if (handled) {
        event.preventDefault();
        touched();
      }
    });

    $("zoomIn").addEventListener("click", function () { const c = center(); zoomAt(1.4, c[0], c[1]); });
    $("zoomOut").addEventListener("click", function () { const c = center(); zoomAt(1 / 1.4, c[0], c[1]); });
    $("zoomFit").addEventListener("click", function () { if (v.ready) fit(); });

    if (window.ResizeObserver) {
      new ResizeObserver(function () { if (v.ready && v.fitted) fit(); }).observe(viewerEl);
    }

    return {
      setPage: function (w, h, refit) {
        v.w = w;
        v.h = h;
        v.ready = true;
        if (refit || v.fitted) fit();
        else commit();
      },
      reset: function () {
        shownUrl = "";
        v.ready = false;
        v.fitted = true;
        chipEl.hidden = true;
        $("hint").hidden = false;
        paperImg.removeAttribute("src");
      },
      state: v,
    };
  })();

  if (window.matchMedia("(pointer: coarse)").matches) {
    $("hint").textContent = "Pinch to zoom, drag to move";
    document.querySelector(".drop-title").textContent = "Choose your file";
    document.querySelector(".drop-or").hidden = true;
  }

  /* getting files in */
  $("choose").addEventListener("click", function (event) {
    event.stopPropagation();
    picker.click();
  });
  $("drop").addEventListener("click", function () { picker.click(); });
  $("addMore").addEventListener("click", function () { picker.click(); });
  picker.addEventListener("change", function () {
    const picked = Array.from(picker.files);
    picker.value = "";
    attempt(addFiles(picked));
  });

  dlSvg.addEventListener("click", function () { attempt(downloadOne("svg")); });
  dlDxf.addEventListener("click", function () { attempt(downloadOne("dxf")); });
  $("dlAllSvg").addEventListener("click", function () { attempt(downloadSheets("svg")); });
  $("dlAllDxf").addEventListener("click", function () { attempt(downloadSheets("dxf")); });
  everything.addEventListener("click", function () { attempt(downloadEverything()); });

  const veil = $("veil");
  const dropZone = $("drop");
  let dragDepth = 0;
  function hasFiles(event) {
    const types = event.dataTransfer && event.dataTransfer.types;
    return !!types && Array.prototype.indexOf.call(types, "Files") >= 0;
  }
  window.addEventListener("dragenter", function (event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth += 1;
    veil.classList.add("on");
  });
  window.addEventListener("dragover", function (event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dropZone.classList.add("over");
  });
  window.addEventListener("dragleave", function (event) {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) {
      veil.classList.remove("on");
      dropZone.classList.remove("over");
    }
  });
  window.addEventListener("drop", function (event) {
    event.preventDefault();
    dragDepth = 0;
    veil.classList.remove("on");
    dropZone.classList.remove("over");
    const dt = event.dataTransfer;
    if (!dt) return;
    const found = [];
    const dirs = [];
    if (dt.items && dt.items.length) {
      Array.from(dt.items).forEach(function (item) {
        if (item.kind !== "file") return;
        let entry = null;
        try { entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null; } catch (exc) { entry = null; }
        if (entry && entry.isDirectory) dirs.push(entry.name);
        else if (item.getAsFile()) found.push(item.getAsFile());
      });
    } else {
      Array.prototype.push.apply(found, Array.from(dt.files));
    }
    if (found.length || dirs.length) attempt(addFiles(found, dirs));
  });

  render();
})();
