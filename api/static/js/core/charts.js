// core/charts.js — design-system dataviz string builders (phase-2 U8 straggler).
// Sparkline/TrendStat/UtilChart/GaugeStat/StatRange — return HTML/SVG strings.
import { esc } from './dom.js';
import { Net } from './net.js';

export function enclSparkline(data, opts) {
  opts = opts || {};
  const w = opts.width || 110, h = opts.height || 24, color = opts.color || 'var(--accent)';
  if (!Array.isArray(data) || data.length < 2) return '';
  const hi = opts.max != null ? opts.max : Math.max(...data, 1);
  const lo = opts.min != null ? opts.min : Math.min(...data, 0);
  const span = (hi - lo) || 1;
  const px = i => (2 + (i / (data.length - 1)) * (w - 4)).toFixed(1);
  const py = v => (2 + (h - 4) * (1 - (v - lo) / span)).toFixed(1);
  const line = data.map((v, i) => `${px(i)},${py(v)}`).join(' ');
  const lastX = px(data.length - 1), lastY = py(data[data.length - 1]);
  return `<svg width="${w}" height="${h}" aria-hidden="true">
    <polygon points="${px(0)},${h - 2} ${line} ${lastX},${h - 2}" fill="${color}" opacity="0.10"></polygon>
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"></polyline>
    <circle cx="${lastX}" cy="${lastY}" r="2" fill="${color}"></circle>
  </svg>`;
}

export function enclTrendStat(opts) {
  // delta is caller-preformatted ("+12%", "-9s"). 'up' class is ALWAYS the
  // good color and 'down' always ember — deltaGood=false flips which arrow
  // direction counts as good (latency, memory: up is bad).
  const { label, value, delta, deltaGood = true, spark, color = 'var(--accent)' } = opts;
  let deltaHtml = '';
  if (delta) {
    const neg = String(delta).startsWith('-');
    const cls = neg ? (deltaGood ? 'down' : 'up') : (deltaGood ? 'up' : 'down');
    const glyph = neg ? '▾' : '▴';
    deltaHtml = `<span class="encl-trend-d ${cls}">${glyph} ${esc(String(delta).replace(/^-/, ''))}</span>`;
  }
  return `<div class="encl-trend">
    <span class="encl-trend-k">${esc(label)}</span>
    <div class="encl-trend-row"><span class="encl-trend-v">${esc(value)}</span>${deltaHtml}</div>
    ${Array.isArray(spark) && spark.length > 1 ? enclSparkline(spark, { color }) : ''}
  </div>`;
}

export function enclUtilChart(series, opts) {
  opts = opts || {};
  const w = opts.width || 460, h = opts.height || 130, max = opts.max || 100;
  const unit = opts.unit || '%', warn = opts.warn, xlabels = opts.xlabels || [];
  const m = { t: 8, r: 36, b: 16, l: 6 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b;
  const COLORS = ['var(--accent)', 'var(--accent-2)', 'var(--info)'];
  const y = v => (m.t + ph * (1 - Math.min(v, max) / max)).toFixed(1);
  let svg = '';
  for (const g of [0, 50, 100]) {
    const gv = g * max / 100;
    if (gv > max) continue;
    svg += `<line x1="${m.l}" y1="${y(gv)}" x2="${m.l + pw}" y2="${y(gv)}" stroke="var(--border)" stroke-width="1"></line>
            <text x="${m.l + pw + 5}" y="${(+y(gv) + 3).toFixed(1)}">${Math.round(gv)}${unit}</text>`;
  }
  if (warn != null) {
    svg += `<line x1="${m.l}" y1="${y(warn)}" x2="${m.l + pw}" y2="${y(warn)}" stroke="var(--warn)" stroke-width="1" stroke-dasharray="4 4" opacity="0.8"></line>
            <text x="${m.l + pw + 5}" y="${(+y(warn) + 3).toFixed(1)}" fill="var(--warn)">${warn}${unit}</text>`;
  }
  let legend = '';
  series.slice(0, 3).forEach((s, si) => {
    const c = s.color || COLORS[si % 3];
    const n = s.data.length;
    if (n >= 2) {
      const x = i => (m.l + (i / Math.max(1, n - 1)) * pw).toFixed(1);
      const line = s.data.map((v, i) => `${x(i)},${y(v)}`).join(' ');
      svg += `<polygon points="${m.l},${m.t + ph} ${line} ${m.l + pw},${m.t + ph}" fill="${c}" opacity="0.08"></polygon>
              <polyline points="${line}" fill="none" stroke="${c}" stroke-width="1.6" stroke-linejoin="round"></polyline>`;
    }
    const latest = s.data[n - 1];
    legend += `<span class="encl-util-key" style="--kc:${c}"><span class="d"></span>${esc(s.label)}
      <span class="v">${latest != null ? Math.round(latest) : '—'}</span><span class="u">${unit}</span></span>`;
  });
  xlabels.forEach((lb, i) => {
    const anchor = i === 0 ? 'start' : (i === xlabels.length - 1 ? 'end' : 'middle');
    const xx = m.l + (i / Math.max(1, xlabels.length - 1)) * pw;
    svg += `<text x="${xx.toFixed(1)}" y="${h - 3}" text-anchor="${anchor}">${esc(lb)}</text>`;
  });
  return `<div class="encl-util-legend">${legend}</div>
    <svg width="${w}" height="${h}" role="img" aria-label="${esc(series.map(s => s.label).join(', '))} over time">${svg}</svg>`;
}

/* GaugeStat — a single utilization reading as a calm linear meter (design-system
   dataviz). value/max → fill; optional warn tick. Returns an HTML string. */
export function enclGaugeStat(opts) {
  opts = opts || {};
  var max = opts.max || 100, unit = opts.unit == null ? '%' : opts.unit;
  var pct = Math.max(0, Math.min(1, (opts.value || 0) / max)) * 100;
  var over = opts.warn != null && opts.value >= opts.warn;
  var fill = opts.color || (over ? 'var(--warn)' : 'var(--accent)');
  var scale = opts.scale === false ? '' :
    '<div class="encl-gauge-scale"><span>0</span>' +
    (opts.warn != null ? '<span style="color:var(--warn)">' + opts.warn + esc(unit) + '</span>' : '<span>' + Math.round(max / 2) + '</span>') +
    '<span>' + max + esc(unit) + '</span></div>';
  return '<div class="encl-gauge">' +
    '<div class="encl-gauge-top"><span class="encl-gauge-k">' + esc(opts.label || '') + '</span>' +
    (opts.sub ? '<span class="encl-gauge-sub">' + esc(opts.sub) + '</span>' : '') + '</div>' +
    '<span class="encl-gauge-v">' + esc(String(opts.value == null ? '—' : opts.value)) + '<span class="u">' + esc(unit) + '</span></span>' +
    '<div class="encl-gauge-track" role="meter" aria-valuenow="' + (opts.value || 0) + '" aria-valuemin="0" aria-valuemax="' + max + '" aria-label="' + esc(opts.label || '') + '">' +
    '<span class="encl-gauge-fill" style="width:' + pct.toFixed(1) + '%;--gc:' + fill + '"></span>' +
    (opts.warn != null ? '<span class="encl-gauge-warn" style="left:' + (Math.min(opts.warn, max) / max * 100).toFixed(1) + '%"></span>' : '') +
    '</div>' + scale + '</div>';
}

/* StatRange — min/avg/max for a series with a range bar + latest-reading dot
   (design-system dataviz; the distribution companion to TrendStat). */
export function enclStatRange(opts) {
  opts = opts || {};
  var data = opts.data || [];
  var lo = opts.min != null ? opts.min : (data.length ? Math.min.apply(null, data) : 0);
  var hi = opts.max != null ? opts.max : (data.length ? Math.max.apply(null, data) : 0);
  var av = opts.avg != null ? opts.avg : (data.length ? data.reduce(function (a, b) { return a + b; }, 0) / data.length : 0);
  var cur = opts.current != null ? opts.current : (data.length ? data[data.length - 1] : av);
  var f = opts.floor != null ? opts.floor : lo, c = opts.ceil != null ? opts.ceil : hi;
  var span = (c - f) || 1;
  var pos = function (v) { return Math.max(0, Math.min(1, (v - f) / span)) * 100; };
  var fmt = function (n, d) { return Number.isFinite(n) ? (+n.toFixed(d || 0)).toString() : '—'; };
  var u = esc(opts.unit || '');
  return '<div class="encl-range" style="--rc:' + (opts.color || 'var(--accent)') + '">' +
    '<span class="encl-range-k">' + esc(opts.label || '') + '</span>' +
    '<div class="encl-range-stats">' +
    '<span class="encl-range-stat"><span class="l">min</span><span class="n">' + fmt(lo) + u + '</span></span>' +
    '<span class="encl-range-stat avg"><span class="l">avg</span><span class="n">' + fmt(av, 1) + u + '</span></span>' +
    '<span class="encl-range-stat"><span class="l">max</span><span class="n">' + fmt(hi) + u + '</span></span>' +
    '</div>' +
    '<div class="encl-range-track">' +
    '<span class="encl-range-span" style="left:' + pos(lo).toFixed(1) + '%;width:' + (pos(hi) - pos(lo)).toFixed(1) + '%"></span>' +
    '<span class="encl-range-avg" style="left:' + pos(av).toFixed(1) + '%"></span>' +
    '<span class="encl-range-cur" style="left:' + pos(cur).toFixed(1) + '%"></span>' +
    '</div>' +
    '<div class="encl-range-ends"><span>' + fmt(f) + u + '</span><span>' + fmt(c) + u + '</span></div></div>';
}
