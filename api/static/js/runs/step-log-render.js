// runs/step-log-render.js — shared per-step log render core (Operate U7).
//
// Composer's Logs pane and the Runs step-expand row historically re-derived
// the same three artefacts — a metadata chip, the strategy strip, and an
// expand/collapse text block — in two hand-maintained copies. This module is
// the single source, exported to both callers (imported, never window-bridged).
//
// F4 resolution: the two surfaces do NOT share one grammar. Composer joins
// Input/Output into single blocks (mode 'joined'); Runs drills each workspace
// key / prompt part into its own `run-step-output*` row (mode 'per-key'). The
// modes render the SAME information in each surface's NATIVE markup — the Runs
// per-key markup and its `run-step-output*` classes are byte-preserved here.
//
// opts (all optional): esc, expanded, keyFor, toggleAction. `expanded` may be
// a Set or a predicate(key)->bool. Chip durations tolerate duration_ms AND
// duration_seconds.
import { esc as _esc } from '../core/dom.js';

// ── expansion-state helper ───────────────────────────────────────────────
// `expanded` is whatever the caller keeps its open-block state in: the two
// callers pass their existing Set (composer _expandedLogs / runs
// _expandedOutputs) directly; a predicate is also accepted.
function _isOpen(expanded, key) {
  if (!expanded) return false;
  if (typeof expanded === 'function') return !!expanded(key);
  if (typeof expanded.has === 'function') return expanded.has(key);
  return false;
}

// Chip duration: prefer persisted milliseconds, fall back to seconds.
function _ms(x) {
  const c = x || {};
  if (c.duration_ms != null) return Math.round(c.duration_ms) + 'ms';
  if (c.duration_seconds != null) return Math.round(c.duration_seconds * 1000) + 'ms';
  return '0ms';
}

// ── logChip ──────────────────────────────────────────────────────────────
// One metadata pill: name · duration · status. Red when status !== 'ok'.
export function logChip(name, duration, status, opts = {}) {
  const esc = opts.esc || _esc;
  const bad = status && status !== 'ok';
  return `<span class="df-tag" style="${bad ? 'color:var(--red, #e5484d);' : ''}font-size:0.56rem">`
    + esc(name) + ' · ' + esc(duration) + ' · ' + esc(status) + '</span>';
}

// ── stepChips ──────────────────────────────────────────────────────────────
// The strategy strip: metadata-only chips derived from a step's
// mcp_calls / plugin_tools_called / skills_activated telemetry. Tool-call
// args/bodies are never persisted, so this is name · timing · status only.
// Returns '' when the step invoked nothing (callers interpolate it directly).
export function stepChips(step, opts = {}) {
  const s = step || {};
  const chips = []
    .concat((s.mcp_calls || []).map(c =>
      logChip(c.server_id + '·' + c.tool_name, _ms(c), c.status || 'ok', opts)))
    .concat((s.plugin_tools_called || []).map(p =>
      logChip(p.plugin_id + '__' + p.tool_id, _ms(p), p.status || 'ok', opts)))
    .concat((s.skills_activated || []).map(k =>
      logChip(k.plugin_id + '::' + k.skill_id, (k.injected_chars || 0) + 'ch', k.trigger || 'keyword', opts)));
  if (!chips.length) return '';
  return `<div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:3px 0 0">
            <span style="font-size:0.52rem;color:var(--text-faint);text-transform:uppercase;letter-spacing:0.08em">strategy · metadata-only</span>
            ${chips.join('')}
          </div>`;
}

// ── logBlock ──────────────────────────────────────────────────────────────
// An expand/collapse text block. `mode` selects the surface's native grammar:
//   'joined'  — Composer: one block per Input/Output; toggle key stepId:which;
//               data-log-key attr; ws-run-action button.
//   'per-key' — Runs: one row per prompt-part / workspace key; toggle key
//               stepId::key; data-step-id + data-key attrs; run-step-output*
//               markup (byte-preserved).
export function logBlock(opts = {}) {
  return opts.mode === 'per-key' ? _perKeyBlock(opts) : _joinedBlock(opts);
}

// Composer joined block. Fields: stepId, which, label, text, captured.
function _joinedBlock(opts) {
  const esc = opts.esc || _esc;
  const keyFor = opts.keyFor || ((sid, which) => sid + ':' + which);
  const toggleAction = opts.toggleAction || 'wslogs.output-toggle';
  const key = keyFor(opts.stepId, opts.which);
  const label = opts.label;
  const text = opts.text;
  if (!opts.captured) {
    return `<div style="padding:2px 0">
        <span style="font-size:0.54rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em">${esc(label)}</span>
        <span style="font-size:0.62rem;color:var(--text-faint);font-style:italic;margin-left:6px">${esc(text)}</span>
      </div>`;
  }
  const open = _isOpen(opts.expanded, key);
  return `<div style="padding:2px 0">
      <button type="button" class="ws-run-action ghost" data-action="${toggleAction}"
              data-log-key="${esc(key)}" style="font-size:0.54rem;text-transform:uppercase;letter-spacing:0.08em"
              title="Expand / collapse">${open ? '▾' : '▸'} ${esc(label)}</button>
      <div style="font-size:0.62rem;color:var(--text-muted);white-space:pre-wrap;word-break:break-word;
                  ${open ? 'max-height:220px;overflow:auto' : 'max-height:2.6em;overflow:hidden'};
                  padding:2px 0 0 14px">${esc(text)}</div>
    </div>`;
}

// Runs per-key block. Fields: stepId, key, label, preview, meta, full.
// `meta` is inserted verbatim (callers pre-escape or pass a numeric string);
// `preview` is escaped here. Markup + run-step-output* classes are preserved
// exactly as the pre-extraction _renderStepPrompt/_renderStepOutputs emitted.
function _perKeyBlock(opts) {
  const esc = opts.esc || _esc;
  const keyFor = opts.keyFor || ((sid, k) => sid + '::' + k);
  const toggleAction = opts.toggleAction || 'runs.output-toggle';
  const open = _isOpen(opts.expanded, keyFor(opts.stepId, opts.key));
  return `<div class="run-step-output${open ? ' open' : ''}">
        <button type="button" class="btn-unstyled run-step-output-head" style="width:100%" aria-expanded="${open}" data-action="${toggleAction}" data-step-id="${esc(opts.stepId)}" data-key="${esc(opts.key)}">
          <span class="run-step-caret">${open ? '▾' : '▸'}</span>
          <span class="ctx-field-k">${esc(opts.label)}</span>
          ${open ? '' : `<span class="ctx-field-v">${esc(opts.preview)}</span>`}
          <span style="flex:1"></span>
          <span class="run-step-output-meta">${opts.meta}</span>
        </button>
        ${open ? `<pre class="run-step-output-full">${esc(opts.full)}</pre>` : ''}
      </div>`;
}
