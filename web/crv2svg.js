/* crv2svg in JavaScript: the same reader and writers as the Python package, line for line.
 * The output is held byte for byte to the Python by tests/test_web_parity.py.
 * GPL-3.0-or-later. */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.crv2svg = factory();
    root.crv2svg.factorySource = factory.toString();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";


  class CrvError extends Error {
    constructor(message) {
      super(message);
      this.name = "CrvError";
    }
  }

  class UnsupportedError extends CrvError {
    constructor(message, partial) {
      super(message);
      this.name = "UnsupportedError";
      this.partial = partial === undefined ? null : partial;
    }
  }


  const f64 = new DataView(new ArrayBuffer(8));

  function decompose(x) {
    f64.setFloat64(0, x);
    const hi = f64.getUint32(0);
    const lo = f64.getUint32(4);
    const neg = hi >>> 31 === 1;
    const ex = (hi >>> 20) & 0x7ff;
    const frac = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
    if (ex === 0) return { neg, m: frac, e: -1074 };
    return { neg, m: frac | (1n << 52n), e: ex - 1075 };
  }

  function bitLen(n) {
    if (n === 0n) return 0;
    const h = n.toString(16);
    return (h.length - 1) * 4 + (32 - Math.clz32(parseInt(h[0], 16)));
  }

  function ldexp(x, n) {
    while (n > 1000) { x *= 2 ** 1000; n -= 1000; }
    while (n < -1000) { x *= 2 ** -1000; n += 1000; }
    return x * 2 ** n;
  }

  function toDouble(neg, N, e, sticky) {
    if (N === 0n) return neg ? -0 : 0;
    let shift = bitLen(N) - 53;
    if (e + shift < -1074) shift = -1074 - e;
    let q = N;
    if (shift > 0) {
      const s = BigInt(shift);
      q = N >> s;
      const rem = N & ((1n << s) - 1n);
      const half = 1n << (s - 1n);
      if (rem > half || (rem === half && (sticky || (q & 1n) === 1n))) q += 1n;
    } else if (shift < 0) {
      q = N << BigInt(-shift);
    }
    const v = ldexp(Number(q), e + shift);
    return neg ? -v : v;
  }

  function isqrt(n) {
    if (n < 2n) return n;
    let x = 1n << BigInt((bitLen(n) + 1) >> 1);
    for (;;) {
      const y = (x + n / x) >> 1n;
      if (y >= x) return x;
      x = y;
    }
  }

  function hypot(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      if (Math.abs(x) === Infinity || Math.abs(y) === Infinity) return Infinity;
      return NaN;
    }
    x = Math.abs(x);
    y = Math.abs(y);
    if (x === 0) return y;
    if (y === 0) return x;
    const a = decompose(x);
    const b = decompose(y);
    const e = Math.min(a.e, b.e);
    const X = a.m << BigInt(a.e - e);
    const Y = b.m << BigInt(b.e - e);
    const S = X * X + Y * Y;
    let sh = Math.max(0, 240 - bitLen(S));
    if (sh % 2) sh += 1;
    const T = S << BigInt(sh);
    const r = isqrt(T);
    return toDouble(false, r, e - sh / 2, r * r !== T);
  }

  const P = 160n;
  const ONE = 1n << P;

  function fixedOf(x) {
    const d = decompose(x);
    const shift = d.e + Number(P);
    const v = shift >= 0 ? d.m << BigInt(shift) : d.m >> BigInt(-shift);
    return d.neg ? -v : v;
  }

  function fixedToDouble(F) {
    return toDouble(F < 0n, F < 0n ? -F : F, -Number(P), false);
  }

  function atanSeries(num, den, guard) {
    const one = 1n << (P + guard);
    const z = (num * one) / den;
    const z2 = (z * z) / one;
    let term = z;
    let sum = z;
    for (let k = 1; term !== 0n; k++) {
      term = (term * z2) / one;
      const t = term / BigInt(2 * k + 1);
      sum += k % 2 ? -t : t;
    }
    return sum;
  }

  let piCache = null;
  function piFixed() {
    if (piCache === null) {
      const g = 64n;
      const v = 16n * atanSeries(1n, 5n, g) - 4n * atanSeries(1n, 239n, g);
      piCache = v >> g;
    }
    return piCache;
  }

  function atanFixed(z) {
    if (z > ONE) return (piFixed() >> 1n) - atanFixed((ONE * ONE) / z);
    const G = 32n;
    let w = z << G;
    const one = ONE << G;
    for (let i = 0; i < 3; i++) {
      const root = isqrt(one * one + w * w);
      w = (w * one) / (one + root);
    }
    const w2 = (w * w) / one;
    let term = w;
    let sum = w;
    for (let k = 1; term !== 0n; k++) {
      term = (term * w2) / one;
      const t = term / BigInt(2 * k + 1);
      sum += k % 2 ? -t : t;
    }
    return (sum * 8n) >> G;
  }

  function atan(x) {
    if (!Number.isFinite(x)) return Math.atan(x);
    if (Math.abs(x) < 2 ** -30) return x;
    const r = atanFixed(fixedOf(Math.abs(x)));
    return fixedToDouble(x < 0 ? -r : r);
  }

  function atan2(y, x) {
    if (!Number.isFinite(x) || !Number.isFinite(y) || x === 0 || y === 0) return Math.atan2(y, x);
    const ay = decompose(Math.abs(y));
    const ax = decompose(Math.abs(x));
    const ratioExp = ay.e - ax.e;
    if (x > 0 && Math.abs(y) < Math.abs(x) * 2 ** -30) {
      const num = ay.m << 200n;
      const quo = num / ax.m;
      const v = toDouble(false, quo, ratioExp - 200, quo * ax.m !== num);
      return y < 0 ? -v : v;
    }
    const ratio = (a, b, exp) => {
      const sh = exp + Number(P);
      return sh >= 0 ? (a << BigInt(sh)) / b : a / (b << BigInt(-sh));
    };
    const z = ratio(ay.m, ax.m, ratioExp);
    let angle = z > ONE
      ? (piFixed() >> 1n) - atanFixed(ratio(ax.m, ay.m, -ratioExp))
      : atanFixed(z);
    if (x < 0) angle = piFixed() - angle;
    return fixedToDouble(y < 0 ? -angle : angle);
  }

  function sinCosFixed(r) {
    const G = 32n;
    const one = ONE << G;
    const w = r << G;
    const w2 = (w * w) / one;
    let s = w;
    let tS = w;
    let c = one;
    let tC = one;
    for (let k = 1; tS !== 0n || tC !== 0n; k++) {
      tC = (-tC * w2) / one / BigInt((2 * k - 1) * (2 * k));
      tS = (-tS * w2) / one / BigInt((2 * k) * (2 * k + 1));
      c += tC;
      s += tS;
    }
    return [s >> G, c >> G];
  }

  function reduce(x) {
    const k = Math.round(x / (Math.PI / 2));
    const r = fixedOf(x) - BigInt(k) * (piFixed() >> 1n);
    return [((k % 4) + 4) % 4, r];
  }

  function trigFixed(x) {
    const [quad, r] = reduce(x);
    const [s, c] = sinCosFixed(r);
    return { quad, s, c };
  }

  function sin(x) {
    if (!Number.isFinite(x) || Math.abs(x) > 2 ** 20) return Math.sin(x);
    if (Math.abs(x) < 2 ** -30) return x;
    const { quad, s, c } = trigFixed(x);
    return fixedToDouble([s, c, -s, -c][quad]);
  }

  function cos(x) {
    if (!Number.isFinite(x) || Math.abs(x) > 2 ** 20) return Math.cos(x);
    const { quad, s, c } = trigFixed(x);
    return fixedToDouble([c, -s, -c, s][quad]);
  }

  function tan(x) {
    if (!Number.isFinite(x) || Math.abs(x) > 2 ** 20) return Math.tan(x);
    if (Math.abs(x) < 2 ** -30) return x;
    const { quad, s, c } = trigFixed(x);
    const [n, d] = quad % 2 === 0 ? [s, c] : [c, -s];
    if (d === 0n) return Math.tan(x);
    return fixedToDouble((n << P) / d);
  }

  function pyMod(a, b) {
    let m = a % b;
    if (m !== 0) {
      if (b < 0 !== m < 0) m += b;
    } else {
      m = b < 0 ? -0 : 0;
    }
    return m;
  }

  const pyMin = (a, b) => (b < a ? b : a);
  const pyMax = (a, b) => (b > a ? b : a);


  const scales = new Map();
  function scaleOf(digits) {
    let s = scales.get(digits);
    if (s === undefined) {
      s = 10n ** BigInt(digits);
      scales.set(digits, s);
    }
    return s;
  }

  function fmt(value, digits) {
    if (!Number.isFinite(value)) throw new CrvError("a number in this file is too large to write");
    if (value === 0) return "0";
    const d = decompose(value);
    const scale = scaleOf(digits);
    let q;
    if (d.e >= 0) {
      q = (d.m << BigInt(d.e)) * scale;
    } else {
      const num = d.m * scale;
      const sh = BigInt(-d.e);
      q = num >> sh;
      if ((num & ((1n << sh) - 1n)) * 2n >= 1n << sh) q += 1n;
    }
    if (q === 0n) return "0";
    let text = q.toString();
    if (digits > 0) {
      text = text.padStart(digits + 1, "0");
      text = text.slice(0, text.length - digits) + "." + text.slice(text.length - digits);
      text = text.replace(/0+$/, "").replace(/\.$/, "");
    }
    return (d.neg ? "-" : "") + text;
  }


  function uniqueName(base, used, key) {
    let candidate = base;
    let n = used.has(key(base)) ? used.get(key(base)) : 1;
    while (used.has(key(candidate))) {
      n += 1;
      candidate = base + "_" + n;
    }
    used.set(key(base), n);
    used.set(key(candidate), 1);
    return candidate;
  }

  const CP1252 = [
    0x20ac, 0xfffd, 0x201a, 0x0192, 0x201e, 0x2026, 0x2020, 0x2021, 0x02c6, 0x2030, 0x0160, 0x2039,
    0x0152, 0xfffd, 0x017d, 0xfffd, 0xfffd, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014,
    0x02dc, 0x2122, 0x0161, 0x203a, 0x0153, 0xfffd, 0x017e, 0x0178,
  ];

  function fromUnits(units) {
    let out = "";
    for (let i = 0; i < units.length; i += 8192) {
      out += String.fromCharCode.apply(null, units.slice(i, i + 8192));
    }
    return out;
  }

  function decodeCp1252(bytes) {
    const units = new Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) {
      const b = bytes[i];
      units[i] = b >= 0x80 && b < 0xa0 ? CP1252[b - 0x80] : b;
    }
    return fromUnits(units);
  }

  function decodeAscii(bytes) {
    const units = new Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) units[i] = bytes[i] < 0x80 ? bytes[i] : 0xfffd;
    return fromUnits(units);
  }

  function decodeUtf16le(bytes) {
    const units = [];
    const n = bytes.length;
    let i = 0;
    while (i + 1 < n) {
      const u = bytes[i] | (bytes[i + 1] << 8);
      if (u >= 0xd800 && u < 0xdc00) {
        if (i + 3 >= n) {
          units.push(0xfffd);
          return fromUnits(units);
        }
        const v = bytes[i + 2] | (bytes[i + 3] << 8);
        if (v >= 0xdc00 && v < 0xe000) {
          units.push(u, v);
          i += 4;
        } else {
          units.push(0xfffd);
          i += 2;
        }
      } else if (u >= 0xdc00 && u < 0xe000) {
        units.push(0xfffd);
        i += 2;
      } else {
        units.push(u);
        i += 2;
      }
    }
    if (i < n) units.push(0xfffd);
    return fromUnits(units);
  }

  const PY_SPACE = new Set([9, 10, 11, 12, 13, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
    0x2028, 0x2029, 0x202f, 0x205f, 0x3000]);
  function isPySpace(code) {
    return PY_SPACE.has(code) || (code >= 0x2000 && code <= 0x200a);
  }

  function pyStrip(s) {
    let a = 0;
    let b = s.length;
    while (a < b && isPySpace(s.charCodeAt(a))) a++;
    while (b > a && isPySpace(s.charCodeAt(b - 1))) b--;
    return s.slice(a, b);
  }

  const hex = (n, width) => n.toString(16).padStart(width, "0");
  const NOT_PRINTABLE = /^[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]$/u;

  function reprStr(s) {
    const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
    let out = quote;
    for (const ch of s) {
      const cp = ch.codePointAt(0);
      if (ch === quote || ch === "\\") out += "\\" + ch;
      else if (ch === "\t") out += "\\t";
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (cp < 0x20 || cp === 0x7f) out += "\\x" + hex(cp, 2);
      else if (cp < 0x7f) out += ch;
      else if (!NOT_PRINTABLE.test(ch)) out += ch;
      else if (cp < 0x100) out += "\\x" + hex(cp, 2);
      else if (cp < 0x10000) out += "\\u" + hex(cp, 4);
      else out += "\\U" + hex(cp, 8);
    }
    return out + quote;
  }

  function reprBytes(bytes) {
    let hasSingle = false;
    let hasDouble = false;
    for (const b of bytes) {
      if (b === 0x27) hasSingle = true;
      if (b === 0x22) hasDouble = true;
    }
    const quote = hasSingle && !hasDouble ? 0x22 : 0x27;
    let out = "b" + String.fromCharCode(quote);
    for (const b of bytes) {
      if (b === quote || b === 0x5c) out += "\\" + String.fromCharCode(b);
      else if (b === 9) out += "\\t";
      else if (b === 10) out += "\\n";
      else if (b === 13) out += "\\r";
      else if (b < 0x20 || b >= 0x7f) out += "\\x" + hex(b, 2);
      else out += String.fromCharCode(b);
    }
    return out + String.fromCharCode(quote);
  }

  const reprName = (name) => (name === null ? "None" : reprStr(name));

  function codePointCompare(a, b) {
    const x = Array.from(a);
    const y = Array.from(b);
    const n = Math.min(x.length, y.length);
    for (let i = 0; i < n; i++) {
      const d = x[i].codePointAt(0) - y[i].codePointAt(0);
      if (d !== 0) return d;
    }
    return x.length - y.length;
  }


  const JOIN_TOLERANCE = 1e-6;
  const MAX_CURVE_STEPS = 16384;
  const MAX_OUTPUT = 100 * 1024 * 1024;
  const MIN_BULGE = 1e-9;

  function makeSpan(start, end, bulge, control) {
    return { start, end, bulge: bulge === undefined ? 0 : bulge, control: control === undefined ? null : control };
  }

  const isCurve = (span) => span.control !== null;
  const isArc = (span) =>
    span.control === null && Math.abs(span.bulge) > MIN_BULGE &&
    !(span.start[0] === span.end[0] && span.start[1] === span.end[1]);

  function radius(span) {
    const chord = hypot(span.end[0] - span.start[0], span.end[1] - span.start[1]);
    return (chord * (1 + span.bulge * span.bulge)) / (4 * Math.abs(span.bulge));
  }

  const same = (a, b, tol) => Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol;

  function runsOf(path) {
    const out = [];
    let run = [];
    for (const span of path.spans) {
      if (run.length && !same(run[run.length - 1].end, span.start, path.tolerance)) {
        out.push(run);
        run = [];
      }
      run.push(span);
    }
    if (run.length) out.push(run);
    return out;
  }

  function runIsClosed(run, tolerance) {
    return run.length > 0 && same(run[run.length - 1].end, run[0].start, tolerance) &&
      (run.length > 1 || isArc(run[0]) || isCurve(run[0]));
  }

  const makeItem = (kind, paths) => ({ kind, paths: paths || [], tabs: 0, sheet: 0, parts: [] });

  const noSheet = (sheet) => sheet === undefined || sheet === null;

  function layerPaths(layer, sheet) {
    const out = [];
    for (const item of layer.items) {
      if (noSheet(sheet) || item.sheet === sheet) for (const p of item.paths) out.push(p);
    }
    return out;
  }

  function sheetsOf(doc) {
    const seen = [];
    for (const layer of drawingLayers(doc, false)) {
      for (const item of layer.items) {
        if (item.paths.length && !seen.includes(item.sheet)) seen.push(item.sheet);
      }
    }
    const numbered = seen.filter((s) => typeof s === "number").sort((a, b) => a - b);
    const out = numbered.concat(seen.filter((s) => typeof s !== "number"));
    return out.length ? out : [0];
  }

  function drawingLayers(doc, includePreviews) {
    return doc.layers.filter((l) => includePreviews || !l.isPreview);
  }

  const QUARTERS = [];
  function axisTrig(k) {
    if (QUARTERS[k] === undefined) {
      const angle = (k * Math.PI) / 2;
      QUARTERS[k] = [cos(angle), sin(angle)];
    }
    return QUARTERS[k];
  }

  function spanExtent(span) {
    if (span._extent) return span._extent;
    const out = spanExtentUncached(span);
    Object.defineProperty(span, "_extent", { value: out, enumerable: false });
    return out;
  }

  function spanExtentUncached(span) {
    const x1 = span.start[0];
    const y1 = span.start[1];
    const x2 = span.end[0];
    const y2 = span.end[1];
    const pts = [[x1, y1], [x2, y2]];
    if (isCurve(span)) return pts.concat([span.control[0].slice(), span.control[1].slice()]);
    if (!isArc(span) || !Number.isFinite(span.bulge)) return pts;
    const b = span.bulge;
    const chord = hypot(x2 - x1, y2 - y1);
    const r = radius(span);
    const h = (chord * (1 - b * b)) / (4 * b);
    const cx = (x1 + x2) / 2 - (h * (y2 - y1)) / chord;
    const cy = (y1 + y2) / 2 + (h * (x2 - x1)) / chord;
    const a1 = atan2(y1 - cy, x1 - cx);
    const sweep = 4 * atan(b);
    const turn = 2 * Math.PI;
    for (let k = 0; k < 4; k++) {
      const angle = (k * Math.PI) / 2;
      const delta = sweep > 0 ? pyMod(angle - a1, turn) : pyMod(a1 - angle, turn);
      if (delta < Math.abs(sweep)) {
        const [c, s] = axisTrig(k);
        pts.push([cx + r * c, cy + r * s]);
      }
    }
    return pts;
  }

  function bounds(doc, includePreviews, sheet) {
    let box = null;
    for (const layer of drawingLayers(doc, includePreviews)) {
      for (const path of layerPaths(layer, sheet)) {
        for (const span of path.spans) {
          for (const [x, y] of spanExtent(span)) {
            if (!(Number.isFinite(x) && Number.isFinite(y))) continue;
            if (box === null) {
              box = [x, y, x, y];
            } else {
              box = [pyMin(x, box[0]), pyMin(y, box[1]), pyMax(x, box[2]), pyMax(y, box[3])];
            }
          }
        }
      }
    }
    return box;
  }

  function page(doc, includePreviews, sheet) {
    const box = bounds(doc, includePreviews, sheet);
    const mat = doc.material;
    if (mat && mat.every(Number.isFinite) && mat[2] > 0 && mat[3] > 0) {
      const rect = [mat[0], mat[1], mat[0] + mat[2], mat[1] + mat[3]];
      const slack = 1e-6 * pyMax(mat[2], mat[3]);
      if (box === null || (box[0] >= rect[0] - slack && box[1] >= rect[1] - slack &&
          box[2] <= rect[2] + slack && box[3] <= rect[3] + slack)) {
        return rect;
      }
    }
    if (box === null) return [0, 0, 1, 1];
    const pad = 0.02 * pyMax(box[2] - box[0], box[3] - box[1]) || 1;
    return [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad];
  }

  function flattenCurve(span, tolerance) {
    const p0 = span.start;
    const c1 = span.control[0];
    const c2 = span.control[1];
    const p3 = span.end;
    const dd = pyMax(
      hypot(p0[0] - 2 * c1[0] + c2[0], p0[1] - 2 * c1[1] + c2[1]),
      hypot(c1[0] - 2 * c2[0] + p3[0], c1[1] - 2 * c2[1] + p3[1]));
    let steps = 1;
    if (tolerance > 0 && dd > 0) {
      steps = Math.max(1, Math.min(MAX_CURVE_STEPS, Math.ceil(Math.sqrt((0.75 * dd) / tolerance))));
    }
    const out = [];
    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      const u = 1 - t;
      const a = u * u * u;
      const b = 3 * u * u * t;
      const c = 3 * u * t * t;
      const d = t * t * t;
      out.push([a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0],
                a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1]]);
    }
    out[out.length - 1] = [p3[0], p3[1]];
    return out;
  }


  function arcToCurves(span) {
    const x1 = span.start[0];
    const y1 = span.start[1];
    const x2 = span.end[0];
    const y2 = span.end[1];
    const sweep = 4 * atan(span.bulge);
    const chord = hypot(x2 - x1, y2 - y1);
    const h = (chord * (1 - span.bulge * span.bulge)) / (4 * span.bulge);
    const cx = (x1 + x2) / 2 - (h * (y2 - y1)) / chord;
    const cy = (y1 + y2) / 2 + (h * (x2 - x1)) / chord;
    const r = radius(span);
    const a0 = atan2(y1 - cy, x1 - cx);
    const steps = Math.max(1, Math.ceil(Math.abs(sweep) / (Math.PI / 2) - 1e-9));
    const step = sweep / steps;
    const k = (4 / 3) * tan(step / 4);
    const out = [];
    let p0 = [x1, y1, 0];
    for (let i = 0; i < steps; i++) {
      const t0 = a0 + i * step;
      const t1 = a0 + (i + 1) * step;
      const p3 = i === steps - 1 ? [x2, y2, 0] : [cx + r * cos(t1), cy + r * sin(t1), 0];
      const c1 = [p0[0] - k * r * sin(t0), p0[1] + k * r * cos(t0)];
      const c2 = [p3[0] + k * r * sin(t1), p3[1] - k * r * cos(t1)];
      out.push(makeSpan(p0, p3, 0, [c1, c2]));
      p0 = p3;
    }
    return out;
  }

  function layoutText(matrix, lines, base, padded) {
    let any = false;
    for (const line of lines) for (const g of line) if (g[1].length) any = true;
    if (!any) return [[], null];
    if (lines.length !== 1) return [[], "text with " + lines.length + " lines"];
    if (base === null || base.spans.length !== 1 || isArc(base.spans[0]) || isCurve(base.spans[0])) {
      return [[], "text on a curve"];
    }
    const start = base.spans[0].start;
    const end = base.spans[0].end;
    const length = hypot(end[0] - start[0], end[1] - start[1]);
    if (length <= 0) return [[], "text with an empty base line"];
    const ux = (end[0] - start[0]) / length;
    const uy = (end[1] - start[1]) / length;

    const placed = [];
    let pen = 0;
    let inkLeft = null;
    let inkRight = null;
    for (const [advance, outlines, metrics] of lines[0]) {
      const origin = pen + metrics[0];
      for (const path of outlines) {
        for (const span of path.spans) {
          for (const [x] of spanExtent(span)) {
            if (inkLeft === null || origin + x < inkLeft) inkLeft = origin + x;
            if (inkRight === null || origin + x > inkRight) inkRight = origin + x;
          }
        }
      }
      placed.push([origin, metrics[1], outlines]);
      pen += advance;
    }
    if (inkLeft === null || inkLeft === 0) inkLeft = 0;
    if (padded) inkLeft -= (length - ((inkRight === null || inkRight === 0 ? 0 : inkRight) - inkLeft)) / 2;

    const m = (matrix || [1, 0, 0, 0, 1, 0, 0, 0, 1]).slice(0, 6);
    const [a, b, tx, c, d, ty] = m;
    const scale = Math.max(Math.abs(a), Math.abs(b), Math.abs(c), Math.abs(d), 1e-300);
    const rotation = Math.abs(a - d) <= 1e-9 * scale && Math.abs(b + c) <= 1e-9 * scale;
    const reflection = Math.abs(a + d) <= 1e-9 * scale && Math.abs(b - c) <= 1e-9 * scale;
    const similar = rotation || reflection;
    const mirrored = a * d - b * c < 0;

    const point = (origin, lift, p) => {
      const along = origin - inkLeft + p[0];
      const up = lift + p[1];
      const x = start[0] + ux * along - uy * up;
      const y = start[1] + uy * along + ux * up;
      const px = a * x + b * y + tx;
      const py = c * x + d * y + ty;
      if (!(Math.abs(px) < COORD_LIMIT && Math.abs(py) < COORD_LIMIT)) {
        throw new CrvError("text lands at a position that is not a usable number");
      }
      return [px, py, 0];
    };

    const paths = [];
    for (const [origin, lift, outlines] of placed) {
      for (const path of outlines) {
        const out = { spans: [], tolerance: JOIN_TOLERANCE };
        for (const span of path.spans) {
          const pieces = similar || !isArc(span) ? [span] : arcToCurves(span);
          for (const piece of pieces) {
            let control = null;
            if (isCurve(piece)) {
              control = piece.control.map((p) => point(origin, lift, p).slice(0, 2));
            }
            const bulge = mirrored ? -piece.bulge : piece.bulge;
            out.spans.push(makeSpan(point(origin, lift, piece.start), point(origin, lift, piece.end), bulge, control));
          }
        }
        paths.push(out);
      }
    }
    return [paths, null];
  }


  const CFB_MAGIC = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
  const END_OF_CHAIN = 0xfffffffe;
  const NO_STREAM = 0xffffffff;
  const MAX_STREAM = 512 * 1024 * 1024;
  const MAX_ENTRIES = 4096;

  function concat(parts) {
    let total = 0;
    for (const p of parts) total += p.length;
    const out = new Uint8Array(total);
    let at = 0;
    for (const p of parts) {
      out.set(p, at);
      at += p.length;
    }
    return out;
  }

  function readStreams(data) {
    if (data.length < 512 || !CFB_MAGIC.every((b, i) => data[i] === b)) {
      throw new CrvError("not a compound file, so not a CRV project");
    }
    try {
      return readCompound(data);
    } catch (exc) {
      if (exc instanceof CrvError) throw exc;
      throw new CrvError("compound file is truncated or corrupt");
    }
  }

  function readCompound(data) {
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const sectorShift = view.getUint16(30, true);
    const miniShift = view.getUint16(32, true);
    if ((sectorShift !== 9 && sectorShift !== 12) || miniShift !== 6) {
      throw new CrvError("compound file has an unsupported sector size");
    }
    const ssz = 2 ** sectorShift;
    const msz = 2 ** miniShift;
    const dirStart = view.getUint32(48, true);
    const cutoff = view.getUint32(56, true);
    const miniStart = view.getUint32(60, true);
    const difatStart = view.getUint32(68, true);
    const difatCount = view.getUint32(72, true);
    const totalSectors = Math.max(Math.floor(data.length / ssz) - 1, 0);
    const perSector = ssz / 4;

    const sector = (n) => {
      if (n >= totalSectors) throw new CrvError("compound file points past its own end");
      const off = (n + 1) * ssz;
      return data.subarray(off, off + ssz);
    };
    const words = (bytes) => {
      const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      const out = new Array(bytes.length >> 2);
      for (let i = 0; i < out.length; i++) out[i] = v.getUint32(i * 4, true);
      return out;
    };

    const difat = [];
    for (let i = 0; i < 109; i++) {
      const x = view.getUint32(76 + 4 * i, true);
      if (x < END_OF_CHAIN) difat.push(x);
    }
    let nxt = difatStart;
    let hops = 0;
    while (nxt < END_OF_CHAIN) {
      hops += 1;
      if (hops > difatCount + 1 || hops > totalSectors) {
        throw new CrvError("compound file has a looping allocation table");
      }
      const vals = words(sector(nxt));
      for (let i = 0; i < vals.length - 1; i++) if (vals[i] < END_OF_CHAIN) difat.push(vals[i]);
      nxt = vals[vals.length - 1];
    }
    if (difat.length > totalSectors) {
      throw new CrvError("compound file allocation table is larger than the file");
    }
    const fat = [];
    for (const s of difat) for (const w of words(sector(s))) fat.push(w);

    const chain = (start, table) => {
      const out = [];
      let n = start;
      while (n < END_OF_CHAIN) {
        if (n >= table.length || out.length > table.length) {
          throw new CrvError("compound file has a broken sector chain");
        }
        out.push(n);
        n = table[n];
      }
      return out;
    };

    const big = (start, size) => {
      let sectors = chain(start, fat);
      if (size !== undefined) sectors = sectors.slice(0, Math.floor((size + ssz - 1) / ssz));
      const blob = concat(sectors.map(sector));
      return size === undefined ? blob : blob.subarray(0, size);
    };

    const dirdata = big(dirStart);
    const dv = new DataView(dirdata.buffer, dirdata.byteOffset, dirdata.byteLength);
    const entries = [];
    for (let i = 0; i < Math.min(dirdata.length, MAX_ENTRIES * 128) - 127; i += 128) {
      const nameLen = dv.getUint16(i + 64, true);
      const name = decodeUtf16le(dirdata.subarray(i, i + Math.max(Math.min(nameLen, 64) - 2, 0)));
      entries.push({
        name,
        kind: dirdata[i + 66],
        left: dv.getUint32(i + 68, true),
        right: dv.getUint32(i + 72, true),
        child: dv.getUint32(i + 76, true),
        start: dv.getUint32(i + 116, true),
        size: Number(dv.getBigUint64(i + 120, true)),
      });
    }
    if (!entries.length || entries[0].kind !== 5) throw new CrvError("compound file has no root entry");

    const root = entries[0];
    const ministream = root.start < END_OF_CHAIN ? big(root.start, root.size) : new Uint8Array(0);
    let minifat = [];
    if (miniStart < END_OF_CHAIN) {
      const raw = big(miniStart);
      minifat = words(raw.subarray(0, raw.length - (raw.length % 4)));
    }

    const stream = (entry) => {
      const { start, size } = entry;
      if (size > MAX_STREAM || size > data.length) {
        throw new CrvError("compound file stream is larger than the file");
      }
      if (size === 0) return new Uint8Array(0);
      if (size < cutoff) {
        const parts = chain(start, minifat).map((n) => ministream.subarray(n * msz, (n + 1) * msz));
        return concat(parts).subarray(0, size);
      }
      return big(start, size);
    };

    const out = new Map();
    const seen = new Set();
    let budget = data.length;
    const todo = [[root.child, ""]];
    while (todo.length) {
      const [idx, prefix] = todo.pop();
      if (idx === NO_STREAM || idx >= entries.length || seen.has(idx)) continue;
      seen.add(idx);
      const e = entries[idx];
      todo.push([e.left, prefix]);
      todo.push([e.right, prefix]);
      if (e.kind === 2) {
        budget -= e.size;
        if (budget < 0) throw new CrvError("compound file streams add up to more than the file");
        out.set(prefix + e.name, stream(e));
      }
      else if (e.kind === 1) todo.push([e.child, prefix + e.name + "/"]);
    }
    return out;
  }


  const NEW_CLASS = 0xffff;
  const BIG_TAG = 0x7fff;
  const CLASS_BIT = 0x8000;

  class Archive {
    constructor(data) {
      this.data = data;
      this.view = new DataView(data.buffer, data.byteOffset, data.byteLength);
      this.pos = 0;
      this.table = [null];
      this.warnings = [];
      this.approximateText = false;
      this.sheet = null;
      this.sheets = [];
      this.progress = null;
    }

    need(size) {
      if (this.pos + size > this.data.length) {
        throw new CrvError("vector data ends in the middle of a record");
      }
    }

    u8() { this.need(1); return this.data[this.pos++]; }
    u16() { this.need(2); const v = this.view.getUint16(this.pos, true); this.pos += 2; return v; }
    u32() { this.need(4); const v = this.view.getUint32(this.pos, true); this.pos += 4; return v; }
    i32() { this.need(4); const v = this.view.getInt32(this.pos, true); this.pos += 4; return v; }
    f64() { this.need(8); const v = this.view.getFloat64(this.pos, true); this.pos += 8; return v; }

    raw(size) {
      if (size < 0 || this.pos + size > this.data.length) {
        throw new CrvError("vector data ends in the middle of a record");
      }
      const out = this.data.subarray(this.pos, this.pos + size);
      this.pos += size;
      return out;
    }

    expectU32(allowed, what) {
      const value = this.u32();
      if (!allowed.includes(value)) {
        throw new UnsupportedError(
          what + " has version " + value + ", this reader knows " + allowed.join("/") +
          " (offset " + (this.pos - 4) + ")");
      }
      return value;
    }

    count(what, each) {
      const n = this.u32();
      if (n * (each === undefined ? 1 : each) > this.data.length - this.pos) {
        throw new CrvError(what + " count " + n + " does not fit in the file");
      }
      return n;
    }

    string() {
      let n = this.u8();
      let wide = false;
      if (n === 0xff) {
        n = this.u16();
        if (n === 0xfffe) {
          wide = true;
          n = this.u8();
          if (n === 0xff) {
            n = this.u16();
            if (n === 0xffff) n = this.u32();
          }
        } else if (n === 0xffff) {
          n = this.u32();
        }
      }
      if (wide) return decodeUtf16le(this.raw(n * 2));
      return decodeCp1252(this.raw(n));
    }

    objectHeader() {
      const tag = this.u16();
      let name;
      if (tag === NEW_CLASS) {
        this.u16();
        name = decodeAscii(this.raw(this.u16()));
        this.table.push(["class", name]);
      } else {
        let isClass;
        let index;
        if (tag === BIG_TAG) {
          const ref = this.u32();
          isClass = ref >= 0x80000000;
          index = ref % 0x80000000;
        } else {
          isClass = (tag & CLASS_BIT) !== 0;
          index = tag & 0x7fff;
        }
        if (!isClass) {
          if (index === 0) return null;
          throw new UnsupportedError("shared object reference at offset " + this.pos);
        }
        if (index >= this.table.length || this.table[index] === null || this.table[index][0] !== "class") {
          throw new CrvError("object refers to a class that was never defined (offset " + this.pos + ")");
        }
        name = this.table[index][1];
      }
      this.table.push(["object", name]);
      return name;
    }
  }


  const VECTOR_STREAM = "VectorData/2dDataV2";
  const PREVIEW_LAYER = "Toolpath Previews";
  const SPAN_LINE = 0, SPAN_ARC = 1, SPAN_BEZIER = 2, SPAN_TAB_LINE = 3, SPAN_TAB_ARC = 4, SPAN_POINT = -1;
  const COORD_LIMIT = 1e9;
  const PARAM_SIZE = new Map([[0, 8], [1, 4], [2, 1]]);
  const PARAM_STRING = 3;
  const MAX_NESTING = 64;
  const DEFAULT_JOIN = 1e-6;
  const MAX_JOIN = 0.01;
  const BULGE_LIMIT = 1e6;
  const SPAN_CLASSES = new Map([
    ["vdLineSpan", SPAN_LINE], ["vdArcSpan", SPAN_ARC], ["vdBezierSpan", SPAN_BEZIER],
    ["vdTabLineSpan", SPAN_TAB_LINE], ["vdTabArcSpan", SPAN_TAB_ARC], ["vdSpan", SPAN_POINT],
  ]);

  function makeDocument() {
    const doc = {
      layers: [], product: "", version: "", material: null, units: null,
      previewGif: new Uint8Array(0), warnings: [],
    };
    Object.defineProperty(doc, "sheets", { get: () => sheetsOf(doc) });
    return doc;
  }

  function toBytes(input) {
    if (input instanceof Uint8Array) return input;
    if (input instanceof ArrayBuffer) return new Uint8Array(input);
    throw new CrvError("expected the bytes of a file");
  }

  function readBytes(input, approximateText, onProgress) {
    const data = toBytes(input);
    let streams;
    try {
      streams = readStreams(data);
    } catch (exc) {
      throw wrapUnexpected(exc);
    }
    const empty = new Uint8Array(0);
    const doc = makeDocument();
    [doc.product, doc.version] = readVersion(streams.get("VersionData/Version") || empty);
    doc.previewGif = streams.get("PreviewData/Preview2D_GIF") || empty;
    [doc.units, doc.material] = readMaterial(streams.get("VectorData/MaterialSize") || empty);
    if (!streams.has(VECTOR_STREAM)) {
      const names = Array.from(streams.keys()).sort(codePointCompare).join(", ") || "none";
      throw new UnsupportedError(
        "no " + VECTOR_STREAM + " stream in this file (found: " + names + "). It may come from a Vectric " +
        "release this reader has not seen.");
    }
    const ar = new Archive(streams.get(VECTOR_STREAM));
    ar.approximateText = !!approximateText;
    ar.progress = typeof onProgress === "function" ? onProgress : null;
    doc.warnings = ar.warnings;
    try {
      readVectors(ar, doc);
    } catch (exc) {
      if (exc instanceof UnsupportedError) {
        exc.partial = doc;
        throw exc;
      }
      if (exc instanceof CrvError) throw new UnsupportedError(exc.message, doc);
      throw wrapUnexpected(exc);
    }
    return doc;
  }

  function wrapUnexpected(exc) {
    if (exc instanceof CrvError) return exc;
    if (exc instanceof RangeError && /call stack/i.test(exc.message)) {
      return new CrvError("objects are nested too deeply to read");
    }
    return new CrvError("this file could not be read");
  }

  function readVersion(raw) {
    const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    const parts = [];
    let pos = 4;
    while (parts.length < 2 && pos + 4 <= raw.length &&
           raw[pos] === 0xff && raw[pos + 1] === 0xfe && raw[pos + 2] === 0xff) {
      let n = raw[pos + 3];
      pos += 4;
      if (n === 0xff) {
        if (pos + 2 > raw.length) break;
        n = view.getUint16(pos, true);
        pos += 2;
      }
      parts.push(pyStrip(decodeUtf16le(raw.subarray(pos, pos + 2 * n))));
      pos += 2 * n;
    }
    parts.push("", "");
    return [parts[0], parts[1]];
  }

  function readMaterial(raw) {
    if (raw.length < 54) return [null, null];
    const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    const head = view.getUint32(0, true);
    if (head !== 5 && head !== 7 && head !== 8) return [null, null];
    const units = raw[4] === 0 ? "in" : raw[4] === 1 ? "mm" : null;
    const x0 = view.getFloat64(6, true);
    const y0 = view.getFloat64(14, true);
    const x1 = view.getFloat64(30, true);
    const y1 = view.getFloat64(38, true);
    if (![x0, y0, x1, y1].every((v) => Math.abs(v) < COORD_LIMIT) || x1 <= x0 || y1 <= y0) {
      return [units, null];
    }
    return [units, [x0, y0, x1 - x0, y1 - y0]];
  }

  function readVectors(ar, doc) {
    ar.u32();
    ar.u32();
    for (let i = ar.count("layer", 2); i > 0; i--) {
      const name = ar.objectHeader();
      if (name !== "vcCadLayer") {
        throw new UnsupportedError("expected a layer, found " + reprName(name) + " (offset " + ar.pos + ")");
      }
      doc.layers.push(readLayer(ar));
    }
  }

  function readLayer(ar) {
    ar.expectU32([4], "layer");
    ar.raw(16);
    const layer = { name: ar.string(), color: [0, 0, 0], items: [], isPreview: false };
    const rgb = ar.u32();
    layer.color = [rgb & 0xff, (rgb >>> 8) & 0xff, (rgb >>> 16) & 0xff];
    ar.raw(6);
    for (let i = ar.count("object", 2); i > 0; i--) {
      layer.items.push(readItem(ar));
      if (ar.progress) ar.progress(ar.pos / ar.data.length);
    }
    ar.raw(3);
    layer.isPreview = layer.items.length > 0 && layer.items.every((i) => i.kind === "preview");
    if (!layer.items.length && layer.name === PREVIEW_LAYER) layer.isPreview = true;
    return layer;
  }

  function readItem(ar, depth) {
    const item = readItemBody(ar, depth || 0);
    item.sheet = ar.sheets.pop();
    return item;
  }

  function readItemBody(ar, depth) {
    if (depth > MAX_NESTING) {
      throw new UnsupportedError("objects are nested more than " + MAX_NESTING + " deep (offset " + ar.pos + ")");
    }
    const name = ar.objectHeader();
    if (name === "vcCadContour") {
      readItemBase(ar);
      ar.expectU32([2], "contour object");
      const item = makeItem("contour", [readContour(ar)]);
      item.tabs = readTabs(ar);
      return item;
    }
    if (name === "vcCadPolyline") {
      readItemBase(ar);
      ar.expectU32([2], "polyline object");
      const item = makeItem("polyline", [readContour(ar)]);
      item.tabs = readTabs(ar);
      ar.u32();
      return item;
    }
    if (name === "vcCadToolpathPreview") {
      readItemBase(ar);
      ar.expectU32([4], "toolpath preview");
      ar.raw(16);
      if (ar.objectHeader() !== "vdContourGroup") {
        throw new UnsupportedError("toolpath preview without a contour group (offset " + ar.pos + ")");
      }
      ar.expectU32([3], "contour group");
      const paths = [];
      for (let i = ar.count("contour", 2); i > 0; i--) paths.push(readContour(ar));
      ar.raw(32);
      return makeItem("preview", paths);
    }
    if (name === "vcCadObjectGroup") {
      readItemBase(ar);
      ar.expectU32([1], "object group");
      const group = makeItem("group");
      for (let i = ar.count("grouped object", 2); i > 0; i--) {
        for (const p of readItem(ar, depth + 1).paths) group.paths.push(p);
      }
      return group;
    }
    if (name === "txtBlock") return readTextBlock(ar);
    if (name === "vcCadLinearDimensioningObject") {
      readItemBase(ar);
      ar.expectU32([1], "dimension");
      ar.raw(5);
      const dimension = makeItem("dimension");
      for (let i = ar.count("dimension part", 2); i > 0; i--) {
        const part = readItem(ar, depth + 1);
        for (const p of part.paths) dimension.paths.push(p);
        dimension.parts.push(part);
      }
      ar.expectU32([2], "dimension style");
      ar.raw(4 + 1);
      ar.string();
      ar.string();
      ar.raw(1 + 8 + 8 + 4 + 8 + 1);
      ar.string();
      ar.string();
      ar.raw(1 + 4 + 10 * 8);
      return dimension;
    }
    if (name === "vcActiveComponentPreview") {
      readItemBase(ar);
      ar.raw(4);
      return makeItem("picture");
    }
    if (name === "vcCadBitmap" || name === "vcCadModelPreview") {
      const start = ar.pos;
      readItemBase(ar);
      const header = ar.view.getUint32(start, true);
      const version = ar.u32();
      if (version === 6) {
        ar.raw(11 * 8);
        readItem(ar, depth + 1);
        ar.raw(4);
        ar.string();
        if (name === "vcCadBitmap") {
          ar.raw(2 + 4);
          ar.raw(ar.count("image data"));
        } else {
          ar.raw(2 + 4 + 4 + 4);
          ar.raw(ar.count("coder settings"));
          ar.raw(ar.count("image data"));
          ar.raw(ar.count("image data"));
          ar.raw(4 + 16);
        }
      } else if (version === 5 && header <= 7) {
        ar.raw(1);
        readItem(ar, depth + 1);
        ar.raw(1 + 4 + 4 + 4);
        ar.raw(ar.count("coder settings"));
        ar.raw(ar.count("image data"));
        ar.raw(1024 + 4 + 4);
        ar.string();
        ar.raw(4 + 1);
        if (name === "vcCadModelPreview") ar.raw(4 + 16);
      } else {
        throw new UnsupportedError(
          "this file embeds a picture or 3D model preview in a layout this reader " +
          "cannot step over yet (offset " + ar.pos + ")");
      }
      return makeItem("picture");
    }
    throw new UnsupportedError(
      "this file has a " + reprName(name) + " object, which this reader cannot decode yet (offset " + ar.pos + ")");
  }

  function finite(ar, value) {
    if (!(Math.abs(value) < COORD_LIMIT)) {
      throw new CrvError("text record has a value that is not a usable number (offset " + ar.pos + ")");
    }
    return value;
  }

  function readTextBlock(ar) {
    readItemBase(ar);
    const blockVersion = ar.expectU32([4, 6], "text block");
    const lines = [];
    for (let li = ar.count("text line", 2); li > 0; li--) {
      if (ar.objectHeader() !== "txtLine") {
        throw new UnsupportedError("text block holds an unknown record (offset " + ar.pos + ")");
      }
      ar.expectU32([1, 2], "text line");
      const glyphs = [];
      for (let wi = ar.count("word", 2); wi > 0; wi--) {
        if (ar.objectHeader() !== "txtWord") {
          throw new UnsupportedError("text line holds an unknown record (offset " + ar.pos + ")");
        }
        ar.expectU32([1], "word");
        for (let ci = ar.count("character", 2); ci > 0; ci--) {
          if (ar.objectHeader() !== "txtChar") {
            throw new UnsupportedError("word holds an unknown record (offset " + ar.pos + ")");
          }
          const charVersion = ar.expectU32([3, 4], "character");
          ar.u32();
          ar.string();
          const advance = finite(ar, ar.f64());
          if (ar.objectHeader() !== "vdContourGroup") {
            throw new UnsupportedError("character without outlines (offset " + ar.pos + ")");
          }
          ar.expectU32([3], "contour group");
          const outlines = [];
          for (let oi = ar.count("contour", 2); oi > 0; oi--) outlines.push(readContour(ar));
          ar.raw(4 + 13);
          const metrics = [];
          for (let mi = charVersion >= 4 ? 8 : 7; mi > 0; mi--) metrics.push(finite(ar, ar.f64()));
          glyphs.push([advance, outlines, metrics]);
        }
      }
      ar.raw(8);
      ar.string();
      ar.raw((blockVersion >= 6 ? 5 : 4) * 8);
      lines.push(glyphs);
    }
    ar.raw(2 * 8 + 4);
    let base = null;
    const name = ar.objectHeader();
    if (name === "txtBaseCurve") {
      ar.expectU32([1], "text base curve");
      base = readContour(ar);
    } else if (name !== null) {
      throw new UnsupportedError("text block carries a " + reprName(name) + " record (offset " + ar.pos + ")");
    }
    ar.raw(9);
    const matrix = [];
    for (let i = 0; i < 9; i++) matrix.push(finite(ar, ar.f64()));
    ar.raw(9 * 8 + (blockVersion >= 6 ? 16 : 8));
    const item = makeItem("text");
    let problem;
    if (blockVersion >= 6) {
      [item.paths, problem] = layoutText(matrix, lines, base);
    } else if (ar.approximateText) {
      [item.paths, problem] = layoutText(matrix, lines, base, true);
      if (!problem && item.paths.length) {
        ar.warnings.push("placed text from a release before version 9 by estimate, " +
          "check where it sits before cutting");
      }
    } else {
      problem = "text saved by a release before version 9";
    }
    if (problem) ar.warnings.push("left out " + problem + ", which this reader cannot place yet");
    return item;
  }

  function readItemBase(ar) {
    const matrix = readItemHeader(ar);
    ar.sheets.push(ar.sheet);
    return matrix;
  }

  function readItemHeader(ar) {
    const version = ar.expectU32([5, 6, 7, 8, 9, 10], "drawing object");
    ar.raw(16 + 16 + 20);
    if (ar.i32() !== -1) {
      throw new UnsupportedError("drawing object header is not the known layout (offset " + ar.pos + ")");
    }
    const name = ar.objectHeader();
    if (name === "utParameterList") {
      ar.expectU32([1], "parameter list");
      for (let i = ar.count("parameter", 2); i > 0; i--) {
        if (ar.objectHeader() !== "utParameter") {
          throw new UnsupportedError("parameter list holds an unknown record (offset " + ar.pos + ")");
        }
        ar.expectU32([2], "parameter");
        ar.string();
        const kind = ar.u32();
        if (kind === PARAM_STRING) {
          ar.string();
        } else if (PARAM_SIZE.has(kind)) {
          ar.raw(PARAM_SIZE.get(kind));
        } else {
          throw new UnsupportedError("parameter of type " + kind + " (offset " + ar.pos + ")");
        }
      }
    } else if (name !== null) {
      throw new UnsupportedError("drawing object carries a " + reprName(name) + " record (offset " + ar.pos + ")");
    }
    ar.sheet = version < 10 ? ar.u32() : null;
    if (version === 5) return;
    ar.raw(4 + 8 + 8);
    if (version <= 7) {
      ar.raw(version === 7 ? 4 : 0);
      return;
    }
    taggedVersion(ar, [1]);
    ar.raw(ar.count("id text"));
    if (version === 8) return;
    const hasTransform = ar.u32();
    if (hasTransform === 1) {
      ar.raw(4 * 8);
      for (let i = 0; i < 9; i++) ar.f64();
    } else if (hasTransform !== 0) {
      throw new UnsupportedError("drawing object transform flag " + hasTransform + " (offset " + ar.pos + ")");
    }
    if (version >= 10) {
      taggedVersion(ar, [1]);
      ar.sheet = decodeAscii(ar.raw(ar.count("sheet id text")));
    }
  }

  const VERSION_LABEL = "Vectric__Version";

  function taggedVersion(ar, allowed) {
    const label = ar.raw(ar.count("version label"));
    const ok = label.length === VERSION_LABEL.length &&
      label.every((b, i) => b === VERSION_LABEL.charCodeAt(i));
    if (!ok) {
      throw new UnsupportedError(
        "expected a version label, found " + reprBytes(label.subarray(0, 24)) + " (offset " + ar.pos + ")");
    }
    return ar.expectU32(allowed, "labelled record");
  }

  function readTabs(ar) {
    const n = ar.count("tab", 2);
    for (let i = 0; i < n; i++) {
      if (ar.objectHeader() !== "vcToolpathTab") {
        throw new UnsupportedError("unknown record after a contour (offset " + ar.pos + ")");
      }
      ar.expectU32([1], "tab");
      ar.raw(16);
    }
    return n;
  }

  function readContour(ar) {
    const name = ar.objectHeader();
    if (name !== "vdContour") {
      throw new UnsupportedError("expected contour geometry, found " + reprName(name) + " (offset " + ar.pos + ")");
    }
    const version = ar.expectU32([3, 4, 6, 7], "contour");
    ar.raw(4);
    const tolerance = ar.f64();
    ar.raw(1 + 8 + 1);
    const path = { spans: [], tolerance: JOIN_TOLERANCE };
    if (DEFAULT_JOIN < tolerance && tolerance <= MAX_JOIN) path.tolerance = tolerance;
    for (let i = ar.count("span", 50); i > 0; i--) {
      let kind;
      if (version >= 6) {
        kind = ar.u8();
        if (kind > SPAN_TAB_ARC) {
          throw new UnsupportedError("span type " + kind + " is not decoded yet (offset " + ar.pos + ")");
        }
      } else {
        const cls = ar.objectHeader();
        if (cls === null || !SPAN_CLASSES.has(cls)) {
          throw new UnsupportedError(reprName(cls) + " spans are not decoded yet (offset " + ar.pos + ")");
        }
        kind = SPAN_CLASSES.get(cls);
      }
      path.spans.push(readSpan(ar, kind));
    }
    ar.raw(16 + 4);
    if (version >= 4) ar.raw(16 * ar.u16());
    return path;
  }

  function readSpan(ar, kind) {
    ar.expectU32([2], "span");
    ar.u32();
    const start = [ar.f64(), ar.f64(), ar.f64()];
    const end = [ar.f64(), ar.f64(), ar.f64()];
    const limited = [start[0], start[1], end[0], end[1]];
    if (!limited.every((v) => Math.abs(v) < COORD_LIMIT)) {
      throw new CrvError("span has a coordinate that is not a usable number (offset " + ar.pos + ")");
    }
    let bulge = 0;
    let control = null;
    if (kind === SPAN_POINT) return makeSpan(start, end);
    if (kind === SPAN_LINE) {
      const d = ar.data;
      if (ar.pos + 4 <= d.length && d[ar.pos] === 1 && d[ar.pos + 1] === 0 && d[ar.pos + 2] === 0 && d[ar.pos + 3] === 0) {
        ar.raw(4);
      }
      return makeSpan(start, end);
    }
    ar.expectU32([1], "span detail");
    if (kind === SPAN_ARC || kind === SPAN_TAB_ARC) {
      bulge = ar.f64();
      if (!(Math.abs(bulge) < BULGE_LIMIT)) {
        throw new CrvError("arc has a bulge that is not a usable number (offset " + ar.pos + ")");
      }
    } else if (kind === SPAN_BEZIER) {
      control = [[ar.f64(), ar.f64()], [ar.f64(), ar.f64()]];
      if (!control.every((p) => p.every((v) => Math.abs(v) < COORD_LIMIT))) {
        throw new CrvError("curve has a control point that is not a usable number (offset " + ar.pos + ")");
      }
    }
    if (kind === SPAN_TAB_LINE || kind === SPAN_TAB_ARC) {
      ar.expectU32([1, 2], "tab detail");
      ar.raw(24);
    }
    return makeSpan(start, end, bulge, control);
  }


  const escapeXml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function quoteattr(data) {
    data = escapeXml(data).replace(/\n/g, "&#10;").replace(/\r/g, "&#13;").replace(/\t/g, "&#9;");
    if (data.includes('"')) {
      if (data.includes("'")) return '"' + data.replace(/"/g, "&quot;") + '"';
      return "'" + data + "'";
    }
    return '"' + data + '"';
  }

  const svgNum = (v) => fmt(v, 6);

  function stroke(color) {
    const [r, g, b] = color;
    if (Math.min(r, g, b) > 230) return "#000000";
    return "#" + hex(r, 2) + hex(g, 2) + hex(b, 2);
  }

  function uniqueId(name, used) {
    let base = name.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "layer";
    if (!/^[A-Za-z]/.test(base)) base = "layer_" + base;
    return uniqueName(base, used, (text) => text);
  }

  const NOT_XML = /[^\t\n\r\x20-\ud7ff\ue000-\ufffd\u{10000}-\u{10ffff}]/gu;
  const cleanXml = (text) => text.replace(NOT_XML, "\ufffd");

  function pathData(path, x0, yTop) {
    const parts = [];
    for (const run of runsOf(path)) {
      let sx = svgNum(run[0].start[0] - x0);
      let sy = svgNum(yTop - run[0].start[1]);
      parts.push("M" + sx + " " + sy);
      const closed = runIsClosed(run, path.tolerance);
      run.forEach((span, i) => {
        const ex = svgNum(span.end[0] - x0);
        const ey = svgNum(yTop - span.end[1]);
        const last = i === run.length - 1;
        if (isCurve(span)) {
          const [[ax, ay], [bx, by]] = span.control;
          parts.push("C" + svgNum(ax - x0) + " " + svgNum(yTop - ay) + " " + svgNum(bx - x0) + " " +
            svgNum(yTop - by) + " " + ex + " " + ey);
        } else if (isArc(span)) {
          const chord = hypot(parseFloat(ex) - parseFloat(sx), parseFloat(ey) - parseFloat(sy));
          const b2 = span.bulge * span.bulge;
          const r = chord ? fmt((chord * (1 + b2)) / (4 * Math.abs(span.bulge)), 9) : svgNum(radius(span));
          parts.push("A" + r + " " + r + " 0 " + (Math.abs(span.bulge) > 1 ? 1 : 0) + " " +
            (span.bulge > 0 ? 0 : 1) + " " + ex + " " + ey);
        } else if (!(closed && last)) {
          parts.push("L" + ex + " " + ey);
        }
        sx = ex;
        sy = ey;
      });
      if (closed) parts.push("Z");
    }
    return parts.join(" ");
  }

  function toSvg(doc, opts) {
    opts = opts || {};
    const units = opts.units || doc.units;
    const includePreviews = !!opts.includePreviews;
    const wanted = opts.layers == null ? null : new Set(opts.layers);
    const [x0, y0, x1, y1] = page(doc, includePreviews, opts.sheet);
    void y0;
    const width = x1 - x0;
    const height = y1 - y0;
    const suffix = units === "in" ? "in" : units === "mm" ? "mm" : "";
    const out = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<svg xmlns="http://www.w3.org/2000/svg" ' +
      'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" ' +
      'width="' + svgNum(width) + suffix + '" height="' + svgNum(height) + suffix +
      '" viewBox="0 0 ' + svgNum(width) + " " + svgNum(height) + '">',
    ];
    const used = new Map();
    let size = 0;
    for (const layer of drawingLayers(doc, includePreviews)) {
      if (wanted !== null && !wanted.has(layer.name)) continue;
      out.push(
        "<g id=" + quoteattr(uniqueId(layer.name, used)) + ' inkscape:groupmode="layer" inkscape:label=' +
        quoteattr(cleanXml(layer.name)) + ' fill="none" stroke="' + stroke(layer.color) +
        '" stroke-width="1" vector-effect="non-scaling-stroke">');
      out.push("<title>" + escapeXml(cleanXml(layer.name)) + "</title>");
      for (const path of layerPaths(layer, opts.sheet)) {
        const d = pathData(path, x0, y1);
        size += d.length;
        if (size > MAX_OUTPUT) throw new CrvError("this drawing is too large to save");
        if (d) out.push('<path vector-effect="non-scaling-stroke" d="' + d + '"/>');
      }
      out.push("</g>");
    }
    out.push("</svg>");
    return out.join("\n") + "\n";
  }

  const ACI = [[1, [255, 0, 0]], [2, [255, 255, 0]], [3, [0, 255, 0]], [4, [0, 255, 255]],
    [5, [0, 0, 255]], [6, [255, 0, 255]], [7, [0, 0, 0]]];

  function aci(color) {
    const hi = Math.max(color[0], color[1], color[2]);
    const lo = Math.min(color[0], color[1], color[2]);
    if (hi - lo < 40) return hi >= 70 && hi <= 200 ? 8 : 7;
    let best = 0;
    let bestDist = Infinity;
    for (const [key, rgb] of ACI) {
      const dist = (rgb[0] - color[0]) ** 2 + (rgb[1] - color[1]) ** 2 + (rgb[2] - color[2]) ** 2;
      if (dist < bestDist) {
        best = key;
        bestDist = dist;
      }
    }
    return best;
  }

  function dxfLayerName(name, used) {
    const base = name.replace(/[^A-Za-z0-9_$-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 28) || "LAYER";
    return uniqueName(base, used, (text) => text.toUpperCase());
  }

  function dxfNum(value) {
    const text = fmt(value, 9);
    return text.includes(".") ? text : text + ".0";
  }

  function toDxf(doc, opts) {
    opts = opts || {};
    const includePreviews = !!opts.includePreviews;
    const wanted = opts.layers == null ? null : new Set(opts.layers);
    const tolerance = opts.curveTolerance == null
      ? (doc.units === "mm" ? 0.01 : 0.0005) : opts.curveTolerance;
    const chosen = drawingLayers(doc, includePreviews).filter((l) => wanted === null || wanted.has(l.name));
    const names = [];
    const used = new Map();
    chosen.forEach((layer, i) => { names[i] = dxfLayerName(layer.name, used); });
    const chunks = [];
    let out = [];
    let size = 0;
    const emit = (code, value) => {
      const a = String(code).padStart(3, " ");
      const b = String(value);
      size += a.length + b.length + 2;
      if (size > MAX_OUTPUT) throw new CrvError("this drawing is too large to save");
      out.push(a, b);
      if (out.length >= 262144) {
        chunks.push(out.join("\n"));
        out = [];
      }
    };
    const vertex = (layer, point, bulge) => {
      emit(0, "VERTEX"); emit(8, layer);
      emit(10, dxfNum(point[0])); emit(20, dxfNum(point[1])); emit(30, "0.0");
      if (bulge !== 0) emit(42, dxfNum(bulge));
    };

    emit(0, "SECTION"); emit(2, "HEADER");
    emit(9, "$ACADVER"); emit(1, "AC1009");
    if (doc.units) {
      emit(9, "$MEASUREMENT"); emit(70, doc.units === "mm" ? 1 : 0);
    }
    emit(0, "ENDSEC");
    emit(0, "SECTION"); emit(2, "TABLES");
    emit(0, "TABLE"); emit(2, "LAYER"); emit(70, chosen.length);
    chosen.forEach((layer, i) => {
      emit(0, "LAYER"); emit(2, names[i]); emit(70, 0);
      emit(62, aci(layer.color)); emit(6, "CONTINUOUS");
    });
    emit(0, "ENDTAB"); emit(0, "ENDSEC");
    emit(0, "SECTION"); emit(2, "ENTITIES");
    chosen.forEach((layer, index) => {
      for (const path of layerPaths(layer, opts.sheet)) {
        for (const run of runsOf(path)) {
          const closed = runIsClosed(run, path.tolerance);
          emit(0, "POLYLINE"); emit(8, names[index]); emit(66, 1);
          emit(10, "0.0"); emit(20, "0.0"); emit(30, "0.0");
          emit(70, closed ? 1 : 0);
          for (const span of run) {
            vertex(names[index], span.start, isArc(span) ? span.bulge : 0);
            if (isCurve(span)) {
              const pts = flattenCurve(span, tolerance);
              for (let i = 0; i < pts.length - 1; i++) vertex(names[index], pts[i], 0);
            }
          }
          if (!closed) vertex(names[index], run[run.length - 1].end, 0);
          emit(0, "SEQEND"); emit(8, names[index]);
        }
      }
    });
    emit(0, "ENDSEC");
    emit(0, "EOF");
    chunks.push(out.join("\n"));
    return chunks.join("\n") + "\n";
  }

  function warningLines(doc) {
    const counts = new Map();
    for (const w of doc.warnings) counts.set(w, (counts.get(w) || 0) + 1);
    return Array.from(counts.keys()).sort(codePointCompare).map((w) => w + " (x" + counts.get(w) + ")");
  }

  return {
    readBytes,
    toSvg,
    toDxf,
    warningLines,
    drawingLayers: (doc, includePreviews) => drawingLayers(doc, !!includePreviews),
    layerPaths,
    sheetsOf,
    pageOf: (doc, includePreviews, sheet) => page(doc, !!includePreviews, sheet),
    strokeColor: stroke,
    CrvError,
    UnsupportedError,
    numfmt: { fmt },
    _math: { hypot, atan, atan2, sin, cos, tan, decodeUtf16le, decodeCp1252, pyStrip, reprStr, reprBytes },
  };
});
