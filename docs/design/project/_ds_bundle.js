/* @ds-bundle: {"format":3,"namespace":"EnclaveDesignSystem_47ed55","components":[{"name":"ActionChip","sourcePath":"components/console/ActionChip.jsx"},{"name":"EntityCard","sourcePath":"components/console/EntityCard.jsx"},{"name":"FitBar","sourcePath":"components/console/FitBar.jsx"},{"name":"MaturityMeter","sourcePath":"components/console/MaturityMeter.jsx"},{"name":"SeedChip","sourcePath":"components/console/SeedChip.jsx"},{"name":"WizardStepper","sourcePath":"components/console/WizardStepper.jsx"},{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"IconButton","sourcePath":"components/core/IconButton.jsx"},{"name":"Input","sourcePath":"components/core/Input.jsx"},{"name":"Panel","sourcePath":"components/core/Panel.jsx"},{"name":"Select","sourcePath":"components/core/Select.jsx"},{"name":"StatusPip","sourcePath":"components/core/StatusPip.jsx"},{"name":"Toggle","sourcePath":"components/core/Toggle.jsx"},{"name":"Sparkline","sourcePath":"components/dataviz/Sparkline.jsx"},{"name":"TrendStat","sourcePath":"components/dataviz/TrendStat.jsx"},{"name":"UtilChart","sourcePath":"components/dataviz/UtilChart.jsx"},{"name":"MetricStat","sourcePath":"components/workflow/MetricStat.jsx"},{"name":"RoleChip","sourcePath":"components/workflow/RoleChip.jsx"},{"name":"RunStatus","sourcePath":"components/workflow/RunStatus.jsx"},{"name":"WorkflowNode","sourcePath":"components/workflow/WorkflowNode.jsx"}],"sourceHashes":{"components/console/ActionChip.jsx":"0e8b2602b856","components/console/EntityCard.jsx":"b494ee961437","components/console/FitBar.jsx":"4b74be1402c9","components/console/MaturityMeter.jsx":"771c66a727f3","components/console/SeedChip.jsx":"be09d0b4dacd","components/console/WizardStepper.jsx":"14677dcab8d2","components/core/Badge.jsx":"49d54c0b04e5","components/core/Button.jsx":"4e787b0d25e3","components/core/IconButton.jsx":"f7888a1db7d8","components/core/Input.jsx":"62df883d0c93","components/core/Panel.jsx":"3ed1564799f0","components/core/Select.jsx":"1bfe429c33a1","components/core/StatusPip.jsx":"018a6cc5644c","components/core/Toggle.jsx":"a542e2a07204","components/dataviz/Sparkline.jsx":"7f55faaf7838","components/dataviz/TrendStat.jsx":"ec759fe16f1c","components/dataviz/UtilChart.jsx":"6947b0ffed57","components/workflow/MetricStat.jsx":"9a20174f0d6b","components/workflow/RoleChip.jsx":"ed4bbce17802","components/workflow/RunStatus.jsx":"e40fcbba4c4b","components/workflow/WorkflowNode.jsx":"730927771695","ui_kits/console-v2/CanvasMode.jsx":"d36dbc670c8a","ui_kits/console-v2/ChatHome.jsx":"54d437cdb5ac","ui_kits/console-v2/Library2.jsx":"3042fbe92cc9","ui_kits/console-v2/data2.js":"98821720e290","ui_kits/console-v2/parts2.jsx":"be195e96d878","ui_kits/console-v2/shell2.jsx":"aa6fdeaf44f0","ui_kits/console/Composer.jsx":"551c230e9cee","ui_kits/console/data.js":"101cb25520b5","ui_kits/console/primitives.jsx":"5b2a46544bb4","ui_kits/console/views.jsx":"b769f53e7d2f"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.EnclaveDesignSystem_47ed55 = window.EnclaveDesignSystem_47ed55 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/console/ActionChip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave ActionChip — a small mono action/suggestion chip. Two jobs:
 * hover actions on chat messages ("pin as step") and next-best-action
 * nudges above the composer ("convert to a workflow?").
 */

const CSS = `
.encl-actchip { display: inline-flex; align-items: center; gap: 5px; font-family: var(--font-mono);
  font-size: var(--text-2xs); letter-spacing: .04em; padding: 3px 9px; border-radius: var(--radius-pill);
  border: 1px solid var(--border); background: var(--surface-card); color: var(--text-muted); cursor: pointer;
  white-space: nowrap; transition: color var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out); }
.encl-actchip svg { width: 11px; height: 11px; stroke-width: 1.8; }
.encl-actchip:hover { color: var(--accent); border-color: var(--accent-dim); }
.encl-actchip.accent { color: var(--accent); border-color: var(--accent-dim); background: var(--accent-ghost); }
.encl-actchip.accent:hover { background: var(--accent); color: var(--on-accent); }
.encl-actchip.lg { font-size: var(--text-xs); padding: 5px 12px; }
.encl-actchip .x { color: var(--text-faint); margin-left: 2px; }
.encl-actchip .x:hover { color: var(--danger); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function ActionChip({
  icon = null,
  accent = false,
  lg = false,
  onDismiss,
  children,
  className = '',
  ...rest
}) {
  useInjected('encl-actchip-css', CSS);
  return /*#__PURE__*/React.createElement("span", _extends({
    className: `encl-actchip ${accent ? 'accent' : ''} ${lg ? 'lg' : ''} ${className}`.trim()
  }, rest), icon, children, onDismiss ? /*#__PURE__*/React.createElement("span", {
    className: "x",
    onClick: e => {
      e.stopPropagation();
      onDismiss(e);
    },
    "aria-label": "Dismiss"
  }, "\xD7") : null);
}
Object.assign(__ds_scope, { ActionChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/ActionChip.jsx", error: String((e && e.message) || e) }); }

// components/console/EntityCard.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave EntityCard — the unified drill-down card. One anatomy for every
 * entity type: status pip + mono id + type badge, a mono meta line, optional
 * role-fit bars, and a dependents footer. Click opens the peek panel.
 */

const CSS = `
.encl-ecard { background: var(--surface-card); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 14px 15px; cursor: pointer; display: flex; flex-direction: column; gap: 9px;
  transition: border-color var(--t-med) var(--ease-out), transform var(--t-med) var(--ease-out), box-shadow var(--t-med) var(--ease-out); }
.encl-ecard:hover { border-color: var(--accent-dim); transform: translateY(-2px); box-shadow: var(--elev-2); }
.encl-ecard.selected { border-color: var(--accent-dim); box-shadow: var(--glow-accent); }
.encl-ecard-head { display: flex; align-items: center; gap: 8px; }
.encl-ecard-pip { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); flex: none; }
.encl-ecard-pip.online { background: var(--accent); }
.encl-ecard-pip.error { background: var(--danger); }
.encl-ecard-id { font-family: var(--font-mono); font-size: var(--text-sm); font-weight: 600; color: var(--text-strong);
  flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.encl-ecard-type { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500; letter-spacing: .1em;
  text-transform: uppercase; padding: 3px 8px; border-radius: var(--radius-xs); border: 1px solid var(--accent-dim);
  background: var(--accent-ghost); color: var(--accent); white-space: nowrap; }
.encl-ecard-meta { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-muted); }
.encl-ecard-desc { font-size: var(--text-sm); color: var(--text-dim); line-height: 1.45; }
.encl-ecard-fits { display: flex; flex-direction: column; gap: 5px; }
.encl-ecard-fit { display: flex; align-items: center; gap: 8px; }
.encl-ecard-fit .k { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); width: 56px;
  flex: none; letter-spacing: .08em; text-transform: uppercase; }
.encl-ecard-fit .bar { flex: 1; height: 4px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; }
.encl-ecard-fit .bar i { display: block; height: 100%; background: var(--accent); border-radius: var(--radius-pill); }
.encl-ecard-fit .v { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-dim); width: 26px; text-align: right; }
.encl-ecard-foot { display: flex; align-items: center; gap: 7px; margin-top: auto; padding-top: 9px; border-top: 1px solid var(--border-faint); }
.encl-ecard-used { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-muted); flex: 1; min-width: 0; }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function EntityCard({
  id,
  type = 'model',
  status = 'idle',
  meta,
  desc,
  fits,
  usedBy,
  selected,
  actions,
  className = '',
  ...rest
}) {
  useInjected('encl-ecard-css', CSS);
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-ecard ${selected ? 'selected' : ''} ${className}`.trim()
  }, rest), /*#__PURE__*/React.createElement("div", {
    className: "encl-ecard-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: `encl-ecard-pip ${status}`,
    "aria-hidden": "true"
  }), /*#__PURE__*/React.createElement("span", {
    className: "encl-ecard-id"
  }, id), /*#__PURE__*/React.createElement("span", {
    className: "encl-ecard-type"
  }, type)), meta ? /*#__PURE__*/React.createElement("div", {
    className: "encl-ecard-meta"
  }, meta) : null, desc ? /*#__PURE__*/React.createElement("div", {
    className: "encl-ecard-desc"
  }, desc) : null, fits ? /*#__PURE__*/React.createElement("div", {
    className: "encl-ecard-fits"
  }, Object.entries(fits).map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "encl-ecard-fit"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, k), /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.min(100, v) + '%'
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, v)))) : null, usedBy || actions ? /*#__PURE__*/React.createElement("div", {
    className: "encl-ecard-foot"
  }, usedBy ? /*#__PURE__*/React.createElement("span", {
    className: "encl-ecard-used"
  }, usedBy) : /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }), actions) : null);
}
Object.assign(__ds_scope, { EntityCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/EntityCard.jsx", error: String((e && e.message) || e) }); }

// components/console/FitBar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave FitBar — a labeled 0-100 fit/score bar. Used for model role-fit,
 * benchmark scores, and capacity readouts in peek panels and compare views.
 */

const CSS = `
.encl-fitbar { display: flex; align-items: center; gap: 8px; }
.encl-fitbar .k { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); width: 56px;
  flex: none; letter-spacing: .08em; text-transform: uppercase; }
.encl-fitbar .bar { flex: 1; height: 4px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; min-width: 40px; }
.encl-fitbar .bar i { display: block; height: 100%; background: var(--fb, var(--accent)); border-radius: var(--radius-pill);
  transition: width var(--t-med) var(--ease-out); }
.encl-fitbar .v { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-dim); width: 26px; text-align: right; }
.encl-fitbar .hint { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function FitBar({
  label,
  value,
  hint,
  color,
  showValue = true,
  className = '',
  ...rest
}) {
  useInjected('encl-fitbar-css', CSS);
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-fitbar ${className}`.trim(),
    style: color ? {
      '--fb': color
    } : undefined
  }, rest), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, label), /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.min(100, Math.max(0, value)) + '%'
    }
  })), showValue ? /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, value) : null, hint ? /*#__PURE__*/React.createElement("span", {
    className: "hint"
  }, hint) : null);
}
Object.assign(__ds_scope, { FitBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/FitBar.jsx", error: String((e && e.message) || e) }); }

// components/console/MaturityMeter.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave MaturityMeter — the adoption-ladder dots on a thread header.
 * Shows how far a conversation has graduated: seed → shape → chain →
 * formalize → operate.
 */

const CSS = `
.encl-meter { display: inline-flex; align-items: center; gap: 4px; }
.encl-meter i { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--border-strong); display: block; }
.encl-meter i.on { background: var(--accent); border-color: var(--accent); }
.encl-meter i.hot { border-color: var(--accent); box-shadow: var(--glow-accent); }
.encl-meter .lab { font-family: var(--font-mono); font-size: var(--text-2xs); letter-spacing: .1em;
  text-transform: uppercase; color: var(--text-faint); margin-right: 3px; }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
const RUNGS = ['seed', 'shape', 'chain', 'formalize', 'operate'];
function MaturityMeter({
  value,
  total = 5,
  hot = false,
  label,
  className = '',
  ...rest
}) {
  useInjected('encl-meter-css', CSS);
  return /*#__PURE__*/React.createElement("span", _extends({
    className: `encl-meter ${className}`.trim(),
    title: `maturity ${value}/${total} — next: ${RUNGS[Math.min(value, total - 1)]}`
  }, rest), label ? /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, label) : null, Array.from({
    length: total
  }, (_, i) => /*#__PURE__*/React.createElement("i", {
    key: i,
    className: i < value ? 'on' : hot && i === value ? 'hot' : ''
  })));
}
Object.assign(__ds_scope, { MaturityMeter });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/MaturityMeter.jsx", error: String((e && e.message) || e) }); }

// components/console/SeedChip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave SeedChip — a key:value chip describing a thread's seed (role, model,
 * context, plugin, agent). Lives in thread headers and the chat composer.
 */

const CSS = `
.encl-seedchip { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono);
  font-size: var(--text-2xs); padding: 3px 9px; border: 1px solid var(--border); border-radius: var(--radius-pill);
  background: var(--surface-card); color: var(--text-dim); white-space: nowrap; }
.encl-seedchip .k { color: var(--text-faint); letter-spacing: .08em; text-transform: uppercase; }
.encl-seedchip.accent { border-color: var(--accent-dim); color: var(--accent); background: var(--accent-ghost); }
.encl-seedchip.ghost { border-style: dashed; background: transparent; color: var(--text-faint); cursor: pointer; }
.encl-seedchip.ghost:hover { color: var(--text-dim); border-color: var(--border-strong); }
.encl-seedchip .x { cursor: pointer; color: var(--text-faint); margin-left: 1px; }
.encl-seedchip .x:hover { color: var(--danger); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function SeedChip({
  k,
  v,
  tone = 'neutral',
  ghost = false,
  onRemove,
  className = '',
  ...rest
}) {
  useInjected('encl-seedchip-css', CSS);
  return /*#__PURE__*/React.createElement("span", _extends({
    className: `encl-seedchip ${tone === 'accent' ? 'accent' : ''} ${ghost ? 'ghost' : ''} ${className}`.trim()
  }, rest), k ? /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, k) : null, /*#__PURE__*/React.createElement("span", null, v), onRemove ? /*#__PURE__*/React.createElement("span", {
    className: "x",
    onClick: onRemove,
    "aria-label": "Remove"
  }, "\xD7") : null);
}
Object.assign(__ds_scope, { SeedChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/SeedChip.jsx", error: String((e && e.message) || e) }); }

// components/console/WizardStepper.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave WizardStepper — the unified install wizard's phase header.
 * One skeleton for every object type: source → configure → verify → land.
 */

const CSS = `
.encl-wsteps { display: flex; align-items: center; gap: 8px; }
.encl-wstep { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: var(--text-2xs);
  letter-spacing: .1em; text-transform: uppercase; color: var(--text-faint); white-space: nowrap; }
.encl-wstep .n { width: 20px; height: 20px; border-radius: 50%; border: 1.5px solid var(--border-strong); display: inline-flex;
  align-items: center; justify-content: center; font-size: 10px; flex: none; }
.encl-wstep.done { color: var(--text-dim); }
.encl-wstep.done .n { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.encl-wstep.on { color: var(--accent); }
.encl-wstep.on .n { border-color: var(--accent); color: var(--accent); box-shadow: var(--glow-accent); }
.encl-wconn { flex: 1; height: 1px; background: var(--border); min-width: 14px; }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
const DEFAULT_PHASES = ['source', 'configure', 'verify', 'land'];
function WizardStepper({
  phases = DEFAULT_PHASES,
  active = 0,
  className = '',
  ...rest
}) {
  useInjected('encl-wsteps-css', CSS);
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-wsteps ${className}`.trim()
  }, rest), phases.map((p, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: p
  }, i > 0 ? /*#__PURE__*/React.createElement("span", {
    className: "encl-wconn",
    "aria-hidden": "true"
  }) : null, /*#__PURE__*/React.createElement("span", {
    className: `encl-wstep ${i < active ? 'done' : ''} ${i === active ? 'on' : ''}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, i < active ? '✓' : i + 1), p))));
}
Object.assign(__ds_scope, { WizardStepper });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/WizardStepper.jsx", error: String((e && e.message) || e) }); }

// components/core/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Badge — a small status / category pill. Tinted ghost fill + dim
 * border in the semantic hue. Optional leading dot.
 */

const CSS = `
.encl-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: var(--text-2xs);
  font-weight: 500; letter-spacing: 0.10em; text-transform: uppercase;
  padding: 3px 9px; border-radius: var(--radius-pill);
  border: 1px solid var(--_bd, var(--border)); background: var(--_bg, var(--surface-raised)); color: var(--_fg, var(--text-dim));
  line-height: 1.4; white-space: nowrap;
}
.encl-badge.square { border-radius: var(--radius-xs); }
.encl-badge .encl-badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.encl-badge.t-neutral { --_bg: var(--surface-raised); --_fg: var(--text-dim); --_bd: var(--border-strong); }
.encl-badge.t-accent  { --_bg: var(--accent-ghost);   --_fg: var(--accent);   --_bd: var(--accent-dim); }
.encl-badge.t-success { --_bg: var(--success-ghost);  --_fg: var(--success);  --_bd: var(--success-dim); }
.encl-badge.t-warn    { --_bg: var(--warn-ghost);     --_fg: var(--warn);     --_bd: var(--warn-dim); }
.encl-badge.t-danger  { --_bg: var(--danger-ghost);   --_fg: var(--danger);   --_bd: var(--danger-dim); }
.encl-badge.t-info    { --_bg: var(--info-ghost);     --_fg: var(--info);     --_bd: var(--info-dim); }
.encl-badge.t-warm    { --_bg: var(--accent-warm-ghost); --_fg: var(--accent-warm); --_bd: var(--accent-warm-dim); }
.encl-badge.solid.t-accent { --_bg: var(--accent); --_fg: var(--on-accent); --_bd: var(--accent); }
.encl-badge.solid.t-success { --_bg: var(--success); --_fg: #03160f; --_bd: var(--success); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function Badge({
  children,
  tone = 'neutral',
  dot = false,
  square = false,
  solid = false,
  className = '',
  ...rest
}) {
  useInjected('encl-badge-css', CSS);
  const cls = `encl-badge t-${tone} ${square ? 'square' : ''} ${solid ? 'solid' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  return /*#__PURE__*/React.createElement("span", _extends({
    className: cls
  }, rest), dot ? /*#__PURE__*/React.createElement("span", {
    className: "encl-badge-dot",
    "aria-hidden": "true"
  }) : null, children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Button — the primary action control.
 * Self-contained: references design tokens via CSS custom properties and
 * injects its own stylesheet once (so :hover / :active / :focus work).
 */

const CSS = `
.encl-btn {
  --_bg: transparent; --_fg: var(--text); --_bd: var(--border);
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  font-family: var(--font-mono); font-weight: 500; letter-spacing: 0.04em;
  white-space: nowrap; cursor: pointer; user-select: none;
  border: 1px solid var(--_bd); background: var(--_bg); color: var(--_fg);
  border-radius: var(--radius-sm);
  transition: transform var(--t-fast) var(--ease-out),
              background-color var(--t-fast) var(--ease-out),
              border-color var(--t-fast) var(--ease-out),
              color var(--t-fast) var(--ease-out),
              box-shadow var(--t-fast) var(--ease-out);
}
.encl-btn:hover:not(:disabled) { transform: translateY(-1px); }
.encl-btn:active:not(:disabled) { transform: translateY(0.5px); }
.encl-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.encl-btn .encl-btn-ico { display: inline-flex; }
.encl-btn .encl-btn-ico svg { width: 1em; height: 1em; stroke-width: 1.85; }

/* sizes */
.encl-btn.sz-sm { font-size: var(--text-2xs); padding: 5px 10px; }
.encl-btn.sz-md { font-size: var(--text-xs);  padding: 7px 14px; }
.encl-btn.sz-lg { font-size: var(--text-sm);  padding: 10px 20px; }

/* variants */
.encl-btn.v-primary { --_bg: var(--accent); --_fg: var(--on-accent); --_bd: var(--accent); }
.encl-btn.v-primary:hover:not(:disabled) { --_bg: var(--accent-bright); --_bd: var(--accent-bright); box-shadow: var(--glow-accent); }

.encl-btn.v-secondary { --_bg: var(--accent-2-ghost); --_fg: var(--accent-2-bright); --_bd: var(--accent-2-dim); }
.encl-btn.v-secondary:hover:not(:disabled) { --_bg: var(--accent-2); --_fg: var(--on-accent-2); --_bd: var(--accent-2); }

.encl-btn.v-ghost { --_bg: transparent; --_fg: var(--text-dim); --_bd: var(--border); }
.encl-btn.v-ghost:hover:not(:disabled) { --_bg: var(--surface-raised); --_fg: var(--text); --_bd: var(--border-strong); }

.encl-btn.v-warm { --_bg: var(--accent-warm-ghost); --_fg: var(--accent-warm); --_bd: var(--accent-warm-dim); }
.encl-btn.v-warm:hover:not(:disabled) { --_bg: var(--accent-warm); --_fg: #1a0d04; --_bd: var(--accent-warm); }

.encl-btn.v-danger { --_bg: var(--danger-ghost); --_fg: var(--danger); --_bd: var(--danger-dim); }
.encl-btn.v-danger:hover:not(:disabled) { --_bg: var(--danger); --_fg: #1a0605; --_bd: var(--danger); }

.encl-btn-spin { width: 1em; height: 1em; border-radius: 50%;
  border: 1.5px solid currentColor; border-top-color: transparent;
  animation: encl-btn-spin 0.7s linear infinite; }
@keyframes encl-btn-spin { to { transform: rotate(360deg); } }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function Button({
  children,
  variant = 'primary',
  size = 'md',
  icon = null,
  loading = false,
  disabled = false,
  type = 'button',
  className = '',
  ...rest
}) {
  useInjected('encl-btn-css', CSS);
  const cls = `encl-btn v-${variant} sz-${size} ${className}`.trim();
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    className: cls,
    disabled: disabled || loading
  }, rest), loading ? /*#__PURE__*/React.createElement("span", {
    className: "encl-btn-spin",
    "aria-hidden": "true"
  }) : icon ? /*#__PURE__*/React.createElement("span", {
    className: "encl-btn-ico",
    "aria-hidden": "true"
  }, icon) : null, children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/IconButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave IconButton — a square, icon-only control for toolbars and canvas
 * chrome (zoom, fullscreen, close, dock). Quiet by default; teal on hover.
 */

const CSS = `
.encl-iconbtn {
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--surface-card); color: var(--text-dim);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer;
  transition: transform var(--t-fast) var(--ease-out),
              background-color var(--t-fast) var(--ease-out),
              border-color var(--t-fast) var(--ease-out),
              color var(--t-fast) var(--ease-out);
}
.encl-iconbtn:hover:not(:disabled) { color: var(--accent); border-color: var(--accent-dim); background: var(--surface-raised); }
.encl-iconbtn:active:not(:disabled) { transform: scale(0.94); }
.encl-iconbtn:disabled { opacity: 0.4; cursor: not-allowed; }
.encl-iconbtn.active { color: var(--accent); border-color: var(--accent-dim); background: var(--accent-ghost); }
.encl-iconbtn.bare { background: transparent; border-color: transparent; }
.encl-iconbtn.bare:hover:not(:disabled) { background: var(--surface-raised); }
.encl-iconbtn svg { width: 1.05em; height: 1.05em; stroke-width: 1.85; }
.encl-iconbtn.sz-sm { width: 26px; height: 26px; font-size: 13px; }
.encl-iconbtn.sz-md { width: 32px; height: 32px; font-size: 15px; }
.encl-iconbtn.sz-lg { width: 38px; height: 38px; font-size: 17px; }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function IconButton({
  children,
  label,
  size = 'md',
  active = false,
  bare = false,
  disabled = false,
  className = '',
  ...rest
}) {
  useInjected('encl-iconbtn-css', CSS);
  const cls = `encl-iconbtn sz-${size} ${active ? 'active' : ''} ${bare ? 'bare' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    className: cls,
    "aria-label": label,
    title: label,
    disabled: disabled
  }, rest), children);
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/core/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Input — a labelled text field. Mono label above, dark inset field,
 * teal focus ring. Works as text / password / number / search.
 */

const CSS = `
.encl-field { display: flex; flex-direction: column; gap: 5px; }
.encl-field-label {
  font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted);
}
.encl-field-label .req { color: var(--accent); margin-left: 3px; }
.encl-input-wrap { position: relative; display: flex; align-items: center; }
.encl-input-wrap .encl-input-ico { position: absolute; left: 10px; display: inline-flex; color: var(--text-muted); pointer-events: none; }
.encl-input-wrap .encl-input-ico svg { width: 14px; height: 14px; stroke-width: 1.8; }
.encl-input {
  width: 100%; font-family: var(--font-sans); font-size: var(--text-base);
  color: var(--text); background: var(--surface-inset);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 8px 11px; transition: border-color var(--t-fast) var(--ease-out), box-shadow var(--t-fast) var(--ease-out);
}
.encl-input.has-ico { padding-left: 30px; }
.encl-input::placeholder { color: var(--text-faint); }
.encl-input:hover:not(:disabled):not(:focus) { border-color: var(--border-strong); }
.encl-input:focus { outline: none; border-color: var(--accent-dim); box-shadow: 0 0 0 3px var(--accent-ghost); }
.encl-input:disabled { opacity: 0.5; cursor: not-allowed; }
.encl-input.invalid { border-color: var(--danger-dim); }
.encl-input.invalid:focus { box-shadow: 0 0 0 3px var(--danger-ghost); }
.encl-field-hint { font-size: var(--text-sm); color: var(--text-faint); }
.encl-field-hint.error { color: var(--danger); }
.encl-input.mono { font-family: var(--font-mono); font-size: var(--text-sm); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function Input({
  label,
  hint,
  error,
  icon = null,
  required = false,
  mono = false,
  className = '',
  id,
  ...rest
}) {
  useInjected('encl-input-css', CSS);
  const fid = id || (label ? 'in-' + String(label).toLowerCase().replace(/\s+/g, '-') : undefined);
  return /*#__PURE__*/React.createElement("div", {
    className: "encl-field"
  }, label ? /*#__PURE__*/React.createElement("label", {
    className: "encl-field-label",
    htmlFor: fid
  }, label, required ? /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*") : null) : null, /*#__PURE__*/React.createElement("div", {
    className: "encl-input-wrap"
  }, icon ? /*#__PURE__*/React.createElement("span", {
    className: "encl-input-ico",
    "aria-hidden": "true"
  }, icon) : null, /*#__PURE__*/React.createElement("input", _extends({
    id: fid,
    className: `encl-input ${icon ? 'has-ico' : ''} ${mono ? 'mono' : ''} ${error ? 'invalid' : ''} ${className}`.replace(/\s+/g, ' ').trim()
  }, rest))), error ? /*#__PURE__*/React.createElement("span", {
    className: "encl-field-hint error"
  }, error) : hint ? /*#__PURE__*/React.createElement("span", {
    className: "encl-field-hint"
  }, hint) : null);
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Input.jsx", error: String((e && e.message) || e) }); }

// components/core/Panel.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Panel — the signature framed container. A bordered surface with
 * optional corner registration ticks (top-right + bottom-left) and a
 * caps-tracked mono label header. The blueprint frame around everything.
 */

const CSS = `
.encl-panel {
  position: relative;
  background: var(--surface-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--_pad, 16px);
}
.encl-panel.translucent { background: var(--surface-panel); backdrop-filter: blur(var(--blur-panel)); -webkit-backdrop-filter: blur(var(--blur-panel)); }
.encl-panel.flush { border-radius: 0; }
.encl-panel.active { border-color: transparent; box-shadow: var(--glow-accent); }
.encl-panel-corner { position: absolute; width: 9px; height: 9px; pointer-events: none; }
.encl-panel-corner.tr { top: -1px; right: -1px; border-top: 1.5px solid var(--accent); border-right: 1.5px solid var(--accent); }
.encl-panel-corner.bl { bottom: -1px; left: -1px; border-bottom: 1.5px solid var(--accent); border-left: 1.5px solid var(--accent); }
.encl-panel-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.encl-panel-label {
  font-family: var(--font-mono); font-size: var(--text-xs); font-weight: 500;
  letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-muted);
}
.encl-panel-label::before { content: ""; display: inline-block; width: 14px; height: 1px; background: var(--accent); margin-right: 8px; vertical-align: middle; }
.encl-panel-head-extra { margin-left: auto; display: flex; align-items: center; gap: 6px; }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function Panel({
  children,
  label,
  headerExtra = null,
  ticks = true,
  translucent = false,
  flush = false,
  active = false,
  pad,
  className = '',
  style = {},
  ...rest
}) {
  useInjected('encl-panel-css', CSS);
  const cls = `encl-panel ${translucent ? 'translucent' : ''} ${flush ? 'flush' : ''} ${active ? 'active' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  const st = pad != null ? {
    ...style,
    '--_pad': typeof pad === 'number' ? pad + 'px' : pad
  } : style;
  return /*#__PURE__*/React.createElement("div", _extends({
    className: cls,
    style: st
  }, rest), ticks ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    className: "encl-panel-corner tr",
    "aria-hidden": "true"
  }), /*#__PURE__*/React.createElement("span", {
    className: "encl-panel-corner bl",
    "aria-hidden": "true"
  })) : null, label || headerExtra ? /*#__PURE__*/React.createElement("div", {
    className: "encl-panel-head"
  }, label ? /*#__PURE__*/React.createElement("span", {
    className: "encl-panel-label"
  }, label) : /*#__PURE__*/React.createElement("span", null), headerExtra ? /*#__PURE__*/React.createElement("span", {
    className: "encl-panel-head-extra"
  }, headerExtra) : null) : null, children);
}
Object.assign(__ds_scope, { Panel });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Panel.jsx", error: String((e && e.message) || e) }); }

// components/core/Select.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Select — a labelled dropdown matching the Input styling, with a
 * custom caret. Native <select> under the hood for accessibility.
 */

const CSS = `
.encl-select-field { display: flex; flex-direction: column; gap: 5px; }
.encl-select-label {
  font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted);
}
.encl-select-wrap { position: relative; display: flex; align-items: center; }
.encl-select {
  width: 100%; appearance: none; -webkit-appearance: none;
  font-family: var(--font-sans); font-size: var(--text-base); color: var(--text);
  background: var(--surface-inset); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 8px 30px 8px 11px; cursor: pointer;
  transition: border-color var(--t-fast) var(--ease-out), box-shadow var(--t-fast) var(--ease-out);
}
.encl-select:hover:not(:disabled):not(:focus) { border-color: var(--border-strong); }
.encl-select:focus { outline: none; border-color: var(--accent-dim); box-shadow: 0 0 0 3px var(--accent-ghost); }
.encl-select:disabled { opacity: 0.5; cursor: not-allowed; }
.encl-select-caret { position: absolute; right: 11px; color: var(--text-muted); pointer-events: none; font-size: 10px; }
.encl-select option { background: var(--surface-overlay); color: var(--text); }
.encl-select.mono { font-family: var(--font-mono); font-size: var(--text-sm); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function Select({
  label,
  options = [],
  children,
  mono = false,
  className = '',
  id,
  ...rest
}) {
  useInjected('encl-select-css', CSS);
  const fid = id || (label ? 'sel-' + String(label).toLowerCase().replace(/\s+/g, '-') : undefined);
  return /*#__PURE__*/React.createElement("div", {
    className: "encl-select-field"
  }, label ? /*#__PURE__*/React.createElement("label", {
    className: "encl-select-label",
    htmlFor: fid
  }, label) : null, /*#__PURE__*/React.createElement("div", {
    className: "encl-select-wrap"
  }, /*#__PURE__*/React.createElement("select", _extends({
    id: fid,
    className: `encl-select ${mono ? 'mono' : ''} ${className}`.replace(/\s+/g, ' ').trim()
  }, rest), children || options.map(o => {
    const val = typeof o === 'string' ? o : o.value;
    const lbl = typeof o === 'string' ? o : o.label;
    return /*#__PURE__*/React.createElement("option", {
      key: val,
      value: val
    }, lbl);
  })), /*#__PURE__*/React.createElement("span", {
    className: "encl-select-caret",
    "aria-hidden": "true"
  }, "\u25BE")));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Select.jsx", error: String((e && e.message) || e) }); }

// components/core/StatusPip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave StatusPip — a small status dot. When `live`, it breathes with the
 * teal heartbeat (ds-pip-pulse). The signal that something is alive.
 */

const CSS = `
.encl-pip { display: inline-block; border-radius: 50%; background: var(--_c, var(--text-muted)); flex: none; }
.encl-pip.sz-sm { width: 7px; height: 7px; }
.encl-pip.sz-md { width: 9px; height: 9px; }
.encl-pip.sz-lg { width: 11px; height: 11px; }
.encl-pip.c-online  { --_c: var(--accent); }
.encl-pip.c-success { --_c: var(--success); }
.encl-pip.c-warn    { --_c: var(--warn); }
.encl-pip.c-danger  { --_c: var(--danger); }
.encl-pip.c-info    { --_c: var(--info); }
.encl-pip.c-idle    { --_c: var(--text-muted); }
.encl-pip.live { animation: ds-pip-pulse var(--t-pulse) var(--ease-out) infinite; }
.encl-pip.live.c-success { box-shadow: 0 0 0 0 var(--success-dim); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function StatusPip({
  status = 'idle',
  live = false,
  size = 'md',
  className = '',
  ...rest
}) {
  useInjected('encl-pip-css', CSS);
  const colorMap = {
    online: 'online',
    running: 'info',
    success: 'success',
    warn: 'warn',
    danger: 'danger',
    error: 'danger',
    idle: 'idle'
  };
  const c = colorMap[status] || 'idle';
  const cls = `encl-pip sz-${size} c-${c} ${live ? 'live' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  return /*#__PURE__*/React.createElement("span", _extends({
    className: cls,
    role: "status"
  }, rest));
}
Object.assign(__ds_scope, { StatusPip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/StatusPip.jsx", error: String((e && e.message) || e) }); }

// components/core/Toggle.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Toggle — a compact switch. Teal track when on. Optional inline
 * label. Controlled (checked + onChange) or uncontrolled (defaultChecked).
 */

const CSS = `
.encl-toggle { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; user-select: none; }
.encl-toggle.disabled { opacity: 0.5; cursor: not-allowed; }
.encl-toggle-track {
  position: relative; flex: none; width: 34px; height: 19px;
  background: var(--ink-700); border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill); transition: background var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out);
}
.encl-toggle-thumb {
  position: absolute; top: 1.5px; left: 1.5px; width: 14px; height: 14px;
  background: var(--text-dim); border-radius: 50%;
  transition: transform var(--t-fast) var(--ease-snap), background var(--t-fast) var(--ease-out);
}
.encl-toggle.on .encl-toggle-track { background: var(--accent); border-color: var(--accent); }
.encl-toggle.on .encl-toggle-thumb { transform: translateX(15px); background: var(--on-accent); }
.encl-toggle-label { font-family: var(--font-sans); font-size: var(--text-sm); color: var(--text); }
.encl-toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.encl-toggle:focus-within .encl-toggle-track { box-shadow: 0 0 0 3px var(--accent-ghost); }
.encl-toggle.sz-sm .encl-toggle-track { width: 28px; height: 16px; }
.encl-toggle.sz-sm .encl-toggle-thumb { width: 11px; height: 11px; }
.encl-toggle.sz-sm.on .encl-toggle-thumb { transform: translateX(12px); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function Toggle({
  checked,
  defaultChecked,
  onChange,
  label,
  size = 'md',
  disabled = false,
  className = '',
  ...rest
}) {
  useInjected('encl-toggle-css', CSS);
  const isControlled = checked !== undefined;
  const [internal, setInternal] = React.useState(!!defaultChecked);
  const on = isControlled ? checked : internal;
  const handle = e => {
    if (!isControlled) setInternal(e.target.checked);
    onChange && onChange(e);
  };
  return /*#__PURE__*/React.createElement("label", {
    className: `encl-toggle sz-${size} ${on ? 'on' : ''} ${disabled ? 'disabled' : ''} ${className}`.replace(/\s+/g, ' ').trim()
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-toggle-track"
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-toggle-thumb"
  })), /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox",
    checked: on,
    onChange: handle,
    disabled: disabled
  }, rest)), label ? /*#__PURE__*/React.createElement("span", {
    className: "encl-toggle-label"
  }, label) : null);
}
Object.assign(__ds_scope, { Toggle });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Toggle.jsx", error: String((e && e.message) || e) }); }

// components/dataviz/Sparkline.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave Sparkline — a tiny inline time-series. The default unit of data
 * visualization in this system: trends live next to the number they explain,
 * not on a dashboard page.
 */

function Sparkline({
  data = [],
  width = 120,
  height = 28,
  color = 'var(--accent)',
  fill = true,
  strokeWidth = 1.5,
  dot = true,
  max,
  min,
  className = '',
  ...rest
}) {
  const hi = max != null ? max : Math.max(...data, 1);
  const lo = min != null ? min : Math.min(...data, 0);
  const span = hi - lo || 1;
  const pad = 2;
  const pw = width - pad * 2,
    ph = height - pad * 2;
  const pts = data.map((v, i) => [pad + i / Math.max(1, data.length - 1) * pw, pad + ph * (1 - (v - lo) / span)]);
  const line = pts.map(p => p.map(n => +n.toFixed(1)).join(',')).join(' ');
  const area = `${pad},${pad + ph} ${line} ${pad + pw},${pad + ph}`;
  const last = pts[pts.length - 1];
  return /*#__PURE__*/React.createElement("svg", _extends({
    className: className,
    width: width,
    height: height,
    viewBox: `0 0 ${width} ${height}`,
    "aria-hidden": "true"
  }, rest), fill ? /*#__PURE__*/React.createElement("polygon", {
    points: area,
    fill: color,
    opacity: "0.10"
  }) : null, /*#__PURE__*/React.createElement("polyline", {
    points: line,
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinejoin: "round",
    strokeLinecap: "round"
  }), dot && last ? /*#__PURE__*/React.createElement("circle", {
    cx: last[0],
    cy: last[1],
    r: "2",
    fill: color
  }) : null);
}
Object.assign(__ds_scope, { Sparkline });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/dataviz/Sparkline.jsx", error: String((e && e.message) || e) }); }

// components/dataviz/TrendStat.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave TrendStat — a metric with memory: mono label, big mono value,
 * a delta against the previous period, and a sparkline of how it got here.
 * The upgrade path from MetricStat when "now" isn't enough.
 */

const CSS = `
.encl-trend { display: flex; flex-direction: column; gap: 4px; }
.encl-trend-k { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500; letter-spacing: .14em; text-transform: uppercase; color: var(--text-muted); }
.encl-trend-row { display: flex; align-items: baseline; gap: 8px; white-space: nowrap; }
.encl-trend-v { font-family: var(--font-mono); font-size: var(--text-lg); font-weight: 600; color: var(--text-strong); line-height: 1.1; }
.encl-trend-d { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 600; }
.encl-trend-d.up { color: var(--success); }
.encl-trend-d.down { color: var(--accent-warm); }
.encl-trend-d.flat { color: var(--text-faint); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function spark(data, width, height, color) {
  const hi = Math.max(...data, 1),
    lo = Math.min(...data, 0),
    span = hi - lo || 1;
  const pts = data.map((v, i) => [2 + i / Math.max(1, data.length - 1) * (width - 4), 2 + (height - 4) * (1 - (v - lo) / span)]);
  const line = pts.map(p => p.map(n => +n.toFixed(1)).join(',')).join(' ');
  const last = pts[pts.length - 1];
  return /*#__PURE__*/React.createElement("svg", {
    width: width,
    height: height,
    viewBox: `0 0 ${width} ${height}`,
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("polygon", {
    points: `2,${height - 2} ${line} ${width - 2},${height - 2}`,
    fill: color,
    opacity: "0.10"
  }), /*#__PURE__*/React.createElement("polyline", {
    points: line,
    fill: "none",
    stroke: color,
    strokeWidth: "1.5",
    strokeLinejoin: "round",
    strokeLinecap: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: last[0],
    cy: last[1],
    r: "2",
    fill: color
  }));
}
function TrendStat({
  label,
  value,
  delta,
  deltaGood = true,
  data,
  color = 'var(--accent)',
  sparkWidth = 110,
  className = '',
  ...rest
}) {
  useInjected('encl-trend-css', CSS);
  const dir = !delta ? 'flat' : delta.startsWith('-') ? deltaGood ? 'down' : 'up' : deltaGood ? 'up' : 'down';
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-trend ${className}`.trim()
  }, rest), /*#__PURE__*/React.createElement("span", {
    className: "encl-trend-k"
  }, label), /*#__PURE__*/React.createElement("span", {
    className: "encl-trend-row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-trend-v"
  }, value), delta ? /*#__PURE__*/React.createElement("span", {
    className: `encl-trend-d ${dir}`
  }, delta.startsWith('-') ? '▾' : '▴', " ", delta.replace(/^-/, '')) : null), data ? spark(data, sparkWidth, 24, color) : null);
}
Object.assign(__ds_scope, { TrendStat });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/dataviz/TrendStat.jsx", error: String((e && e.message) || e) }); }

// components/dataviz/UtilChart.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave UtilChart — resource utilization / throughput over time. A calm
 * area chart: warm-charcoal ground, hairline grid at 0/50/100, mono axis
 * labels, up to three series, an optional dashed warn threshold.
 */

const CSS = `
.encl-util { display: flex; flex-direction: column; gap: 8px; }
.encl-util-legend { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.encl-util-key { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-dim); }
.encl-util-key .d { width: 7px; height: 7px; border-radius: 50%; background: var(--kc); }
.encl-util-key .v { color: var(--text); font-weight: 600; }
.encl-util-key .u { color: var(--text-faint); }
.encl-util svg text { font-family: var(--font-mono); font-size: 9px; fill: var(--text-faint); }
`;
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
const SERIES_COLORS = ['var(--accent)', 'var(--accent-2)', 'var(--info)'];
function UtilChart({
  series = [],
  width = 560,
  height = 150,
  max = 100,
  unit = '%',
  xlabels = ['-60m', '-30m', 'now'],
  warn,
  className = '',
  ...rest
}) {
  useInjected('encl-util-css', CSS);
  const m = {
    t: 8,
    r: 38,
    b: 16,
    l: 6
  };
  const pw = width - m.l - m.r,
    ph = height - m.t - m.b;
  const y = v => m.t + ph * (1 - Math.min(v, max) / max);
  const path = data => data.map((v, i) => `${(m.l + i / Math.max(1, data.length - 1) * pw).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-util ${className}`.trim()
  }, rest), /*#__PURE__*/React.createElement("div", {
    className: "encl-util-legend"
  }, series.map((s, i) => {
    const c = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
    return /*#__PURE__*/React.createElement("span", {
      key: s.label,
      className: "encl-util-key",
      style: {
        '--kc': c
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "d"
    }), /*#__PURE__*/React.createElement("span", null, s.label), /*#__PURE__*/React.createElement("span", {
      className: "v"
    }, s.data[s.data.length - 1], /*#__PURE__*/React.createElement("span", {
      className: "u"
    }, unit)));
  })), /*#__PURE__*/React.createElement("svg", {
    width: width,
    height: height,
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": series.map(s => s.label).join(', ') + ' over time'
  }, [0, 50, 100].map(g => g <= max ? /*#__PURE__*/React.createElement("g", {
    key: g
  }, /*#__PURE__*/React.createElement("line", {
    x1: m.l,
    x2: m.l + pw,
    y1: y(g * max / 100),
    y2: y(g * max / 100),
    stroke: "var(--border)",
    strokeWidth: "1"
  }), /*#__PURE__*/React.createElement("text", {
    x: m.l + pw + 5,
    y: y(g * max / 100) + 3
  }, Math.round(g * max / 100), unit)) : null), warn != null ? /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("line", {
    x1: m.l,
    x2: m.l + pw,
    y1: y(warn),
    y2: y(warn),
    stroke: "var(--warn)",
    strokeWidth: "1",
    strokeDasharray: "4 4",
    opacity: "0.8"
  }), /*#__PURE__*/React.createElement("text", {
    x: m.l + pw + 5,
    y: y(warn) + 3,
    style: {
      fill: 'var(--warn)'
    }
  }, warn, unit)) : null, series.map((s, i) => {
    const c = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
    const line = path(s.data);
    return /*#__PURE__*/React.createElement("g", {
      key: s.label
    }, /*#__PURE__*/React.createElement("polygon", {
      points: `${m.l},${m.t + ph} ${line} ${m.l + pw},${m.t + ph}`,
      fill: c,
      opacity: "0.08"
    }), /*#__PURE__*/React.createElement("polyline", {
      points: line,
      fill: "none",
      stroke: c,
      strokeWidth: "1.6",
      strokeLinejoin: "round"
    }));
  }), xlabels.map((xl, i) => /*#__PURE__*/React.createElement("text", {
    key: i,
    y: height - 3,
    x: m.l + i / Math.max(1, xlabels.length - 1) * pw,
    textAnchor: i === 0 ? 'start' : i === xlabels.length - 1 ? 'end' : 'middle'
  }, xl))));
}
Object.assign(__ds_scope, { UtilChart });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/dataviz/UtilChart.jsx", error: String((e && e.message) || e) }); }

// components/workflow/MetricStat.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave MetricStat — a compact key/value system metric. Mono caps key,
 * a value in the metric color, optional sub-detail. Used in the system-impact
 * strip (CPU / MEM / Loaded / Version).
 */

const CSS = `
.encl-metric { display: inline-flex; flex-direction: column; gap: 2px; }
.encl-metric.row { flex-direction: row; align-items: baseline; gap: 7px; }
.encl-metric-key { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted); }
.encl-metric-val { font-family: var(--font-mono); font-size: var(--text-base); font-weight: 600; color: var(--_c, var(--text)); line-height: 1.1; }
.encl-metric-sub { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); }
.encl-metric-bar { height: 3px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; margin-top: 3px; }
.encl-metric-fill { height: 100%; background: var(--_c, var(--accent)); border-radius: var(--radius-pill); transition: width var(--t-med) var(--ease-out); }
`;

// pick a color by load: calm teal → amber → coral as it climbs
function loadColor(pct) {
  if (pct == null) return 'var(--text)';
  if (pct >= 85) return 'var(--danger)';
  if (pct >= 65) return 'var(--warn)';
  return 'var(--accent)';
}
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function MetricStat({
  label,
  value,
  sub,
  percent = null,
  color,
  bar = false,
  row = false,
  className = '',
  style = {},
  ...rest
}) {
  useInjected('encl-metric-css', CSS);
  const c = color || (percent != null ? loadColor(percent) : 'var(--text)');
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-metric ${row ? 'row' : ''} ${className}`.trim(),
    style: {
      ...style,
      '--_c': c
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    className: "encl-metric-key"
  }, label), /*#__PURE__*/React.createElement("span", {
    className: "encl-metric-val"
  }, value), sub ? /*#__PURE__*/React.createElement("span", {
    className: "encl-metric-sub"
  }, sub) : null, bar && percent != null ? /*#__PURE__*/React.createElement("span", {
    className: "encl-metric-bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-metric-fill",
    style: {
      width: Math.min(100, percent) + '%'
    }
  })) : null);
}
Object.assign(__ds_scope, { MetricStat });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/workflow/MetricStat.jsx", error: String((e && e.message) || e) }); }

// components/workflow/RoleChip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave RoleChip — a draggable palette item (role / agent / skill / plugin).
 * Drag onto the Composer canvas to add a step. Role-tinted left marker, a
 * mono title, and an optional one-line description.
 */

const CSS = `
.encl-rolechip {
  display: flex; align-items: center; gap: 10px;
  background: var(--surface-card); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 9px 11px; cursor: grab;
  transition: transform var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out);
}
.encl-rolechip:hover { transform: translateX(2px); border-color: var(--accent-dim); background: var(--surface-raised); }
.encl-rolechip:active { cursor: grabbing; }
.encl-rolechip-mark { flex: none; width: 4px; align-self: stretch; border-radius: var(--radius-pill); background: var(--_tint, var(--accent)); }
.encl-rolechip-ico { flex: none; display: inline-flex; color: var(--_tint, var(--accent)); }
.encl-rolechip-ico svg { width: 15px; height: 15px; stroke-width: 1.8; }
.encl-rolechip-text { min-width: 0; flex: 1; }
.encl-rolechip-title { font-family: var(--font-mono); font-size: var(--text-sm); font-weight: 500; color: var(--text); letter-spacing: 0.02em; }
.encl-rolechip-desc { font-family: var(--font-sans); font-size: var(--text-2xs); color: var(--text-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.encl-rolechip-grip { flex: none; color: var(--text-faint); font-size: 11px; letter-spacing: -2px; }
`;
const TINT = {
  reasoning: 'var(--node-reasoning)',
  coding: 'var(--node-coding)',
  fast: 'var(--node-fast)',
  general: 'var(--node-general)',
  uncensored: 'var(--node-uncensored)',
  agent: 'var(--accent)',
  skill: 'var(--accent-2)',
  plugin: 'var(--info)',
  mcp: 'var(--accent-warm)'
};
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function RoleChip({
  title,
  desc,
  kind = 'reasoning',
  icon = null,
  grip = true,
  className = '',
  style = {},
  ...rest
}) {
  useInjected('encl-rolechip-css', CSS);
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-rolechip ${className}`.trim(),
    draggable: true,
    style: {
      ...style,
      '--_tint': TINT[kind] || 'var(--accent)'
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    className: "encl-rolechip-mark",
    "aria-hidden": "true"
  }), icon ? /*#__PURE__*/React.createElement("span", {
    className: "encl-rolechip-ico",
    "aria-hidden": "true"
  }, icon) : null, /*#__PURE__*/React.createElement("span", {
    className: "encl-rolechip-text"
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-rolechip-title"
  }, title), desc ? /*#__PURE__*/React.createElement("span", {
    className: "encl-rolechip-desc"
  }, desc) : null), grip ? /*#__PURE__*/React.createElement("span", {
    className: "encl-rolechip-grip",
    "aria-hidden": "true"
  }, "\u22EE\u22EE") : null);
}
Object.assign(__ds_scope, { RoleChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/workflow/RoleChip.jsx", error: String((e && e.message) || e) }); }

// components/workflow/RunStatus.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave RunStatus — a workflow-run progress strip. A status pip + label, a
 * step counter, and a thin progress bar. Used on the canvas run chip and in
 * the Runs list.
 */

const CSS = `
.encl-runstatus {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono); font-size: var(--text-xs);
  background: var(--surface-panel); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 7px 11px; backdrop-filter: blur(var(--blur-panel));
}
.encl-runstatus-pip { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--_c); }
.encl-runstatus.running .encl-runstatus-pip { animation: ds-pip-pulse var(--t-pulse) var(--ease-out) infinite; }
.encl-runstatus-label { color: var(--_c); letter-spacing: 0.06em; text-transform: uppercase; font-weight: 600; }
.encl-runstatus-current { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }
.encl-runstatus-count { color: var(--text-muted); margin-left: auto; flex: none; }
.encl-runstatus-bar { position: relative; flex: 1; min-width: 60px; height: 4px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; }
.encl-runstatus-fill { position: absolute; inset: 0 auto 0 0; background: var(--_c); border-radius: var(--radius-pill); transition: width var(--t-med) var(--ease-out); }
`;
const STATE = {
  running: {
    c: 'var(--info)',
    label: 'running'
  },
  success: {
    c: 'var(--success)',
    label: 'complete'
  },
  error: {
    c: 'var(--danger)',
    label: 'failed'
  },
  queued: {
    c: 'var(--text-muted)',
    label: 'queued'
  },
  idle: {
    c: 'var(--text-faint)',
    label: 'idle'
  }
};
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function RunStatus({
  state = 'running',
  current = '',
  step = 0,
  total = 0,
  showBar = true,
  className = '',
  style = {},
  ...rest
}) {
  useInjected('encl-runstatus-css', CSS);
  const s = STATE[state] || STATE.idle;
  const pct = total > 0 ? Math.round(step / total * 100) : state === 'success' ? 100 : 0;
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-runstatus ${state} ${className}`.trim(),
    style: {
      ...style,
      '--_c': s.c
    },
    role: "status",
    "aria-live": "polite"
  }, rest), /*#__PURE__*/React.createElement("span", {
    className: "encl-runstatus-pip",
    "aria-hidden": "true"
  }), /*#__PURE__*/React.createElement("span", {
    className: "encl-runstatus-label"
  }, s.label), current ? /*#__PURE__*/React.createElement("span", {
    className: "encl-runstatus-current"
  }, current) : null, showBar ? /*#__PURE__*/React.createElement("span", {
    className: "encl-runstatus-bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-runstatus-fill",
    style: {
      width: pct + '%'
    }
  })) : null, total > 0 ? /*#__PURE__*/React.createElement("span", {
    className: "encl-runstatus-count"
  }, step, "/", total) : null);
}
Object.assign(__ds_scope, { RunStatus });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/workflow/RunStatus.jsx", error: String((e && e.message) || e) }); }

// components/workflow/WorkflowNode.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Enclave WorkflowNode — a single step on the Composer DAG canvas. A compact
 * card with a role-tinted top rule, a title, model + role meta, IO ports, and
 * a run-status pip. The atom of the workflow-first experience.
 */

const CSS = `
.encl-wfnode {
  position: relative; width: 188px;
  background: var(--surface-card); border: 1px solid var(--border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-1);
  font-family: var(--font-sans); cursor: grab;
  transition: transform var(--t-med) var(--ease-out), box-shadow var(--t-med) var(--ease-out), border-color var(--t-med) var(--ease-out);
}
.encl-wfnode:hover { transform: translateY(-2px); box-shadow: var(--elev-2); border-color: var(--accent-dim); }
.encl-wfnode.selected { border-color: transparent; box-shadow: var(--glow-accent); }
.encl-wfnode-rule { height: 3px; border-radius: var(--radius-md) var(--radius-md) 0 0; background: var(--_role, var(--accent)); }
.encl-wfnode-body { padding: 10px 12px 12px; }
.encl-wfnode-top { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; }
.encl-wfnode-role {
  font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase; color: var(--_role, var(--accent));
}
.encl-wfnode-title { font-size: var(--text-base); font-weight: 600; color: var(--text-strong); letter-spacing: -0.01em; line-height: 1.2; }
.encl-wfnode-meta { display: flex; align-items: center; gap: 6px; margin-top: 7px; font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-muted); }
.encl-wfnode-model { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.encl-wfnode-port { position: absolute; top: 50%; width: 11px; height: 11px; border-radius: 50%; background: var(--surface-overlay); border: 1.5px solid var(--border-strong); transform: translateY(-50%); }
.encl-wfnode-port.in { left: -6px; }
.encl-wfnode-port.out { right: -6px; }
.encl-wfnode-port.linked { background: var(--accent); border-color: var(--accent); }
.encl-wfnode-status { margin-left: auto; }
`;
const ROLE_VAR = {
  reasoning: 'var(--node-reasoning)',
  coding: 'var(--node-coding)',
  fast: 'var(--node-fast)',
  general: 'var(--node-general)',
  uncensored: 'var(--node-uncensored)'
};
function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
function WorkflowNode({
  title = 'step',
  role = 'general',
  model = 'auto',
  status = 'idle',
  selected = false,
  inPort = true,
  outPort = true,
  inLinked = false,
  outLinked = false,
  className = '',
  style = {},
  children,
  ...rest
}) {
  useInjected('encl-wfnode-css', CSS);
  const StatusPipLocal = ({
    s
  }) => {
    const map = {
      running: 'var(--info)',
      success: 'var(--success)',
      error: 'var(--danger)',
      idle: 'var(--text-faint)'
    };
    return /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: map[s] || map.idle,
        display: 'inline-block'
      }
    });
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `encl-wfnode ${selected ? 'selected' : ''} ${className}`.trim(),
    style: {
      ...style,
      '--_role': ROLE_VAR[role] || 'var(--accent)'
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    className: "encl-wfnode-rule"
  }), inPort ? /*#__PURE__*/React.createElement("span", {
    className: `encl-wfnode-port in ${inLinked ? 'linked' : ''}`,
    "aria-hidden": "true"
  }) : null, outPort ? /*#__PURE__*/React.createElement("span", {
    className: `encl-wfnode-port out ${outLinked ? 'linked' : ''}`,
    "aria-hidden": "true"
  }) : null, /*#__PURE__*/React.createElement("div", {
    className: "encl-wfnode-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "encl-wfnode-top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "encl-wfnode-role"
  }, role), /*#__PURE__*/React.createElement("span", {
    className: "encl-wfnode-status"
  }, /*#__PURE__*/React.createElement(StatusPipLocal, {
    s: status
  }))), /*#__PURE__*/React.createElement("div", {
    className: "encl-wfnode-title"
  }, title), /*#__PURE__*/React.createElement("div", {
    className: "encl-wfnode-meta"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "box",
    style: {
      width: 11,
      height: 11
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "encl-wfnode-model"
  }, model)), children));
}
Object.assign(__ds_scope, { WorkflowNode });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/workflow/WorkflowNode.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console-v2/CanvasMode.jsx
try { (() => {
/* Enclave Console v2 — in-shell canvas pivot (the Composer, re-entered from a thread).
   Two lenses on one canvas: Design (edit the structure) and Run (inspect a
   recorded run — scrub timeline, metadata plates, recorded-step inspector). */

const NODE_W = 188,
  NODE_H = 78;

/* Deterministic per-run, per-node metrics (mock — stands in for checkpoint data). */
function runMeta(runId, nodes) {
  const h = s => {
    let x = 7;
    for (const c of s) x = (x * 31 + c.charCodeAt(0)) % 997;
    return x;
  };
  const BASE = {
    reasoning: 14,
    coding: 8,
    fast: 3,
    general: 9,
    uncensored: 7
  };
  return nodes.map(n => {
    const jit = h(runId + n.id) % 60 / 10 - 3;
    const dur = Math.max(1.8, (BASE[n.role] || 8) + jit);
    const m = window.ENCLAVE.MODELS.find(x => x.id === n.model) || {
      tps: 30
    };
    const tps = Math.max(4, m.tps + h(n.id + runId) % 9 - 4);
    return {
      dur: +dur.toFixed(1),
      tps
    };
  });
}
function fmtClock(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`;
}
function CanvasMode({
  thread,
  updateThread
}) {
  const D = window.ENCLAVE;
  const nodes = thread.nodes || [];
  const edges = thread.edges || [];

  /* Recent runs of this workflow (mock; failIdx pins the error to a step). */
  const RUNS = React.useMemo(() => [{
    id: 'run-7f3a',
    when: '2m ago',
    state: 'success'
  }, {
    id: 'run-7e91',
    when: '18m ago',
    state: 'success'
  }, {
    id: 'run-7e44',
    when: '1h ago',
    state: 'error',
    failIdx: Math.min(2, Math.max(0, nodes.length - 2)),
    err: 'contract violated — missing required key `_time`'
  }], [nodes.length]);
  const [selId, setSelId] = React.useState((nodes[0] || {}).id || null);
  const [tab, setTab] = React.useState('roles');
  const [zoom, setZoom] = React.useState(1);
  const [run, setRun] = React.useState({
    active: false,
    done: false,
    status: {}
  });
  const [tests, setTests] = React.useState({});
  const [input, setInput] = React.useState('');
  const [lens, setLens] = React.useState(thread.lensRun ? 'run' : 'design');
  const [runId, setRunId] = React.useState(thread.lensRun || RUNS[0].id);
  const [scrub, setScrub] = React.useState(null); // null = derive default
  const timers = React.useRef([]);
  React.useEffect(() => {
    window.refreshIcons();
  });
  React.useEffect(() => () => timers.current.forEach(clearTimeout), []);

  /* Arriving from the Runs view ("inspect on canvas") while already mounted. */
  React.useEffect(() => {
    if (thread.lensRun) {
      setLens('run');
      setRunId(thread.lensRun);
      setScrub(null);
      updateThread(thread.id, t => ({
        ...t,
        lensRun: null
      }));
    }
  }, [thread.lensRun]);
  const sel = nodes.find(n => n.id === selId);
  const selIdx = nodes.findIndex(n => n.id === selId);
  const paletteItems = {
    roles: D.ROLES,
    agents: D.AGENTS,
    skills: D.SKILLS,
    plugins: D.PLUGINS,
    mcps: D.MCPS
  }[tab] || D.ROLES;
  const prevNode = sel ? edges.filter(e => e[1] === sel.id).map(e => nodes.find(n => n.id === e[0]))[0] || null : null;

  /* ── Run lens derivations ── */
  const curRun = RUNS.find(r => r.id === runId) || RUNS[0];
  const meta = React.useMemo(() => runMeta(curRun.id, nodes), [curRun.id, nodes]);
  const isErr = curRun.state === 'error';
  const lastIdx = isErr ? curRun.failIdx : nodes.length; // n = complete
  const pos = scrub == null ? lastIdx : Math.min(scrub, lastIdx);
  const wall = meta.slice(0, isErr ? curRun.failIdx + 1 : meta.length).reduce((a, m) => a + m.dur, 0);
  const runStatus = {};
  if (lens === 'run') nodes.forEach((n, i) => {
    runStatus[n.id] = i < pos ? 'success' : i === pos && pos < nodes.length ? isErr && i === curRun.failIdx ? 'error' : 'running' : undefined;
  });
  const liveStatus = lens === 'run' ? runStatus : run.status;
  function playRun() {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setScrub(0);
    for (let k = 1; k <= lastIdx; k++) timers.current.push(setTimeout(() => setScrub(k), k * 650));
  }
  function patchNodes(fn) {
    updateThread(thread.id, t => ({
      ...t,
      nodes: fn(t.nodes || [])
    }));
  }
  function addNode(item) {
    const isRole = ['reasoning', 'coding', 'fast', 'general', 'uncensored'].includes(item.kind);
    const role = isRole ? item.kind : item.role || 'general';
    const id = 'n' + Math.floor(Math.random() * 1e6);
    const maxX = Math.max(...nodes.map(n => n.x), 0);
    const node = {
      id,
      title: item.title,
      role,
      model: item.model || (D.MODELS.find(m => m.role === role) || {}).id || 'auto',
      x: maxX + 260,
      y: 150,
      prompt: item.desc || 'Describe what this step should do.'
    };
    updateThread(thread.id, t => {
      const last = (t.nodes || [])[t.nodes.length - 1];
      return {
        ...t,
        nodes: [...(t.nodes || []), node],
        edges: last ? [...(t.edges || []), [last.id, id]] : t.edges || []
      };
    });
    setSelId(id);
  }
  function testStep() {
    if (!sel) return;
    setTests(ts => ({
      ...ts,
      [sel.id]: {
        state: 'running'
      }
    }));
    timers.current.push(setTimeout(() => {
      setTests(ts => ({
        ...ts,
        [sel.id]: {
          state: 'done',
          out: RUN_LINES2[sel.title] || 'step complete — output conforms to the prompt contract.',
          meta: `✓ ${(D.MODELS.find(m => m.id === sel.model) || {
            tps: 30
          }).tps} tok/s · 1.2s · fixture: ${prevNode ? prevNode.title + ' output' : 'thread message #2'}`
        }
      }));
    }, 900));
  }
  function startRun() {
    setLens('design');
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setRun({
      active: true,
      done: false,
      status: {}
    });
    updateThread(thread.id, t => ({
      ...t,
      msgs: [...t.msgs, {
        who: 'user',
        text: 'Run the workflow on the latest export.'
      }]
    }));
    let acc = 0;
    nodes.forEach(node => {
      timers.current.push(setTimeout(() => setRun(r => ({
        ...r,
        status: {
          ...r.status,
          [node.id]: 'running'
        }
      })), acc += 250));
      timers.current.push(setTimeout(() => {
        setRun(r => ({
          ...r,
          status: {
            ...r.status,
            [node.id]: 'success'
          }
        }));
        updateThread(thread.id, t => ({
          ...t,
          msgs: [...t.msgs, {
            who: 'bot',
            text: `▸ ${node.title} (${node.model}) — ${RUN_LINES2[node.title] || 'step complete.'}`
          }]
        }));
      }, acc += 850));
    });
    timers.current.push(setTimeout(() => {
      setRun(r => ({
        ...r,
        active: false,
        done: true
      }));
      updateThread(thread.id, t => ({
        ...t,
        msgs: [...t.msgs, {
          who: 'bot',
          text: '✓ Workflow complete — checkpointed as run-7f3a.'
        }]
      }));
    }, acc += 300));
  }
  function send() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    updateThread(thread.id, t => ({
      ...t,
      msgs: [...t.msgs, {
        who: 'user',
        text
      }]
    }));
    setTimeout(() => updateThread(thread.id, t => ({
      ...t,
      msgs: [...t.msgs, {
        who: 'bot',
        text: window.ENCLAVE2.REPLIES[t.msgs.length % window.ENCLAVE2.REPLIES.length]
      }]
    })), 700);
  }
  const doneCount = Object.values(run.status).filter(s => s === 'success').length;
  const test = sel ? tests[sel.id] : null;
  return /*#__PURE__*/React.createElement("div", {
    className: "composer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "wf-header"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pivot"
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => updateThread(thread.id, t => ({
      ...t,
      mode: 'chat'
    }))
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "message-square"
  }), "Chat"), /*#__PURE__*/React.createElement("button", {
    className: "on"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "workflow"
  }), "Canvas")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "wf-id"
  }, "scaffolded from thread"), /*#__PURE__*/React.createElement("div", {
    className: "wf-name"
  }, thread.name)), /*#__PURE__*/React.createElement(Badge, {
    tone: "success",
    sq: true
  }, "workflow"), /*#__PURE__*/React.createElement("div", {
    className: "pivot",
    style: {
      marginLeft: 6
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: lens === 'design' ? 'on' : '',
    onClick: () => setLens('design')
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "pen-line"
  }), "Design"), /*#__PURE__*/React.createElement("button", {
    className: lens === 'run' ? 'on' : '',
    onClick: () => {
      setLens('run');
      setScrub(null);
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "activity"
  }), "Run lens")), /*#__PURE__*/React.createElement("div", {
    className: "wf-header-spacer"
  }), lens === 'design' && (run.active || run.done) ? /*#__PURE__*/React.createElement("div", {
    className: "wf-runchip",
    style: {
      '--rc': run.active ? 'var(--info)' : 'var(--success)'
    }
  }, /*#__PURE__*/React.createElement(Pip, {
    status: run.active ? 'running' : 'success',
    live: run.active
  }), /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, run.active ? 'running' : 'complete'), /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.round(doneCount / Math.max(1, nodes.length) * 100) + '%'
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "cnt"
  }, doneCount, "/", nodes.length)) : null, lens === 'design' && run.done ? /*#__PURE__*/React.createElement(ActChip, {
    icon: "activity",
    acc: true,
    onClick: () => {
      setLens('run');
      setRunId('run-7f3a');
      setScrub(null);
    }
  }, "inspect this run \u2192") : null, lens === 'run' ? /*#__PURE__*/React.createElement("span", {
    className: "runlens-meta"
  }, curRun.id, " \xB7 ", isErr ? `failed at ${nodes[curRun.failIdx] ? nodes[curRun.failIdx].title : 'step'}` : 'complete', " \xB7 ", fmtClock(wall)) : null, /*#__PURE__*/React.createElement(Btn, {
    icon: "file-down",
    sm: true
  }, "Export YAML"), lens === 'design' ? /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "play",
    onClick: startRun
  }, "Run") : /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "rotate-ccw",
    sm: true,
    onClick: startRun
  }, "Re-run")), /*#__PURE__*/React.createElement("div", {
    className: "composer-body"
  }, lens === 'design' ? /*#__PURE__*/React.createElement("div", {
    className: "palette"
  }, /*#__PURE__*/React.createElement("div", {
    className: "palette-tabs"
  }, ['roles', 'agents', 'skills', 'plugins', 'mcps'].map(t => /*#__PURE__*/React.createElement("div", {
    key: t,
    className: `palette-tab ${tab === t ? 'active' : ''}`,
    onClick: () => setTab(t)
  }, t))), /*#__PURE__*/React.createElement("div", {
    className: "palette-hint"
  }, PALETTE_HINT2[tab]), /*#__PURE__*/React.createElement("div", {
    className: "palette-list"
  }, paletteItems.map((it, i) => /*#__PURE__*/React.createElement(RoleChip, {
    key: i,
    item: it,
    onAdd: addNode
  })))) : /*#__PURE__*/React.createElement("div", {
    className: "runrail"
  }, /*#__PURE__*/React.createElement("div", {
    className: "runrail-head"
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Recent runs")), /*#__PURE__*/React.createElement("div", {
    className: "runrail-hint"
  }, "Pick a run to paint it onto the canvas. Segments are sized by wall-clock share."), /*#__PURE__*/React.createElement("div", {
    className: "runrail-list"
  }, RUNS.map(r => {
    const m = runMeta(r.id, nodes);
    const tot = m.reduce((a, x) => a + x.dur, 0) || 1;
    return /*#__PURE__*/React.createElement("div", {
      key: r.id,
      className: `runcard ${r.id === runId ? 'on' : ''}`,
      onClick: () => {
        setRunId(r.id);
        setScrub(null);
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "top"
    }, /*#__PURE__*/React.createElement(Pip, {
      status: r.state
    }), /*#__PURE__*/React.createElement("span", {
      className: "rid"
    }, r.id), /*#__PURE__*/React.createElement("span", {
      className: "rwhen"
    }, r.when)), /*#__PURE__*/React.createElement("div", {
      className: "segbar"
    }, nodes.map((n, i) => /*#__PURE__*/React.createElement("i", {
      key: n.id,
      style: {
        width: m[i].dur / tot * 100 + '%',
        background: r.state === 'error' && i === r.failIdx ? 'var(--danger)' : r.state === 'error' && i > r.failIdx ? 'var(--ink-700)' : 'var(--accent-2)'
      }
    }))));
  })), /*#__PURE__*/React.createElement("div", {
    className: "runrail-foot"
  }, "Inspecting is non-destructive \u2014 the structure stays editable in the Design lens.")), /*#__PURE__*/React.createElement("div", {
    className: "canvas-wrap",
    onClick: () => setSelId(null)
  }, /*#__PURE__*/React.createElement("div", {
    className: "canvas-ctrls",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement(IconBtn, {
    icon: "minus",
    label: "Zoom out",
    onClick: () => setZoom(z => Math.max(0.6, +(z - 0.1).toFixed(2)))
  }), /*#__PURE__*/React.createElement("span", {
    className: "canvas-zoom"
  }, Math.round(zoom * 100), "%"), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "plus",
    label: "Zoom in",
    onClick: () => setZoom(z => Math.min(1.4, +(z + 0.1).toFixed(2)))
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "rotate-ccw",
    label: "Reset",
    onClick: () => setZoom(1)
  })), /*#__PURE__*/React.createElement("div", {
    className: "canvas-stage",
    style: {
      transform: `scale(${zoom})`
    }
  }, /*#__PURE__*/React.createElement("svg", {
    className: "canvas-edges"
  }, edges.map(([a, b], i) => {
    const na = nodes.find(n => n.id === a),
      nb = nodes.find(n => n.id === b);
    if (!na || !nb) return null;
    const sa = liveStatus[a],
      sb = liveStatus[b];
    const flowing = (lens === 'run' || run.active) && sa === 'success' && (sb === 'running' || sb === 'error');
    const done = sa === 'success' && sb === 'success';
    return /*#__PURE__*/React.createElement("path", {
      key: i,
      d: edgePath(na, nb),
      className: flowing ? 'flow' : done ? 'done' : ''
    });
  })), nodes.map(n => /*#__PURE__*/React.createElement(Node, {
    key: n.id,
    node: n,
    selected: n.id === selId,
    status: liveStatus[n.id],
    inLinked: edges.some(e => e[1] === n.id),
    outLinked: edges.some(e => e[0] === n.id),
    onSelect: setSelId
  })), lens === 'run' ? nodes.map((n, i) => {
    const executed = i < pos || isErr && i === curRun.failIdx && pos >= curRun.failIdx;
    if (!executed) return null;
    const bad = isErr && i === curRun.failIdx;
    return /*#__PURE__*/React.createElement("div", {
      key: 'p' + n.id,
      className: `nodeplate ${bad ? 'err' : ''}`,
      style: {
        left: n.x,
        top: n.y + NODE_H + 6
      }
    }, /*#__PURE__*/React.createElement("span", null, meta[i].dur, "s"), /*#__PURE__*/React.createElement("span", null, meta[i].tps, " tok/s"), bad ? /*#__PURE__*/React.createElement("span", null, "\u2715 contract") : null);
  }) : null), lens === 'run' ? /*#__PURE__*/React.createElement("div", {
    className: "scrubber",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "scrub-head"
  }, /*#__PURE__*/React.createElement(IconBtn, {
    icon: "play",
    label: "Replay run",
    onClick: playRun
  }), /*#__PURE__*/React.createElement("span", {
    className: "scrub-lab"
  }, pos >= nodes.length ? 'complete' : `step ${pos + 1}/${nodes.length} — ${nodes[pos] ? nodes[pos].title : ''}`), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), isErr ? /*#__PURE__*/React.createElement(ActChip, {
    icon: "zap",
    acc: true,
    onClick: () => {
      setScrub(curRun.failIdx);
      setSelId(nodes[curRun.failIdx] && nodes[curRun.failIdx].id);
    }
  }, "jump to failure") : null, /*#__PURE__*/React.createElement("span", {
    className: "scrub-lab"
  }, fmtClock(wall), " wall")), /*#__PURE__*/React.createElement("div", {
    className: "scrub-bar"
  }, nodes.map((n, i) => {
    const w = meta[i].dur / (meta.reduce((a, m) => a + m.dur, 0) || 1) * 100;
    const cls = isErr && i === curRun.failIdx ? 'err' : i < pos ? 'done' : i === pos ? 'cur' : '';
    const reach = !isErr || i <= curRun.failIdx;
    return /*#__PURE__*/React.createElement("div", {
      key: n.id,
      className: `scrub-seg ${cls} ${reach ? '' : 'dead'}`,
      style: {
        width: w + '%'
      },
      onClick: () => {
        if (reach) {
          setScrub(i);
          setSelId(n.id);
        }
      },
      title: `${n.title} · ${meta[i].dur}s`
    }, /*#__PURE__*/React.createElement("span", {
      className: "lb"
    }, n.title, " \xB7 ", meta[i].dur, "s"));
  }))) : null), /*#__PURE__*/React.createElement("div", {
    className: "inspector",
    onClick: e => e.stopPropagation()
  }, lens === 'run' && sel ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Recorded \u2014 ", sel.title), /*#__PURE__*/React.createElement("div", {
    className: "runkv"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "run"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, curRun.id), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "status"), /*#__PURE__*/React.createElement("span", {
    className: "v",
    style: {
      color: isErr && selIdx === curRun.failIdx ? 'var(--danger)' : selIdx < pos ? 'var(--success)' : 'var(--text-dim)'
    }
  }, isErr && selIdx === curRun.failIdx ? 'error' : selIdx < pos ? 'success' : selIdx === pos ? 'running' : 'not reached'), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "duration"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, meta[selIdx] ? meta[selIdx].dur + 's' : '—'), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "throughput"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, meta[selIdx] ? meta[selIdx].tps + ' tok/s' : '—'), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "model"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, sel.model))), /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "As executed"), /*#__PURE__*/React.createElement("div", {
    className: "asexec"
  }, /*#__PURE__*/React.createElement("div", {
    className: "px"
  }, sel.prompt), /*#__PURE__*/React.createElement("div", {
    className: "inj"
  }, "+ injected: ", thread.seed.ctx ? `ctx ${thread.seed.ctx} · ` : '', "skill json-strict")), isErr && selIdx === curRun.failIdx ? /*#__PURE__*/React.createElement("div", {
    className: "runerr"
  }, curRun.err, /*#__PURE__*/React.createElement("br", null), "Violated on edge ", nodes[selIdx - 1] ? nodes[selIdx - 1].title : 'input', " \u2192 ", sel.title, ".") : selIdx < pos ? /*#__PURE__*/React.createElement("div", {
    className: "testresult",
    style: {
      marginTop: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "meta"
  }, "output"), /*#__PURE__*/React.createElement("span", {
    className: "out"
  }, RUN_LINES2[sel.title] || 'step complete — output archived in the checkpoint.')) : null, /*#__PURE__*/React.createElement("div", {
    className: "attach-row",
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/React.createElement(ActChip, {
    icon: "pin",
    acc: true
  }, "pin output as fixture"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "message-square",
    onClick: () => updateThread(thread.id, t => ({
      ...t,
      mode: 'chat'
    }))
  }, "open thread here"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "rotate-ccw"
  }, "re-run from this step")))) : sel ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Step \u2014 ", sel.title), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Title"), /*#__PURE__*/React.createElement("input", {
    className: "mono",
    value: sel.title,
    onChange: e => patchNodes(ns => ns.map(n => n.id === sel.id ? {
      ...n,
      title: e.target.value
    } : n))
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Model"), /*#__PURE__*/React.createElement("select", {
    className: "mono",
    value: sel.model,
    onChange: e => patchNodes(ns => ns.map(n => n.id === sel.id ? {
      ...n,
      model: e.target.value
    } : n))
  }, D.MODELS.map(m => /*#__PURE__*/React.createElement("option", {
    key: m.id,
    value: m.id
  }, m.id, " \xB7 ", m.tps, " tok/s")))), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Prompt"), /*#__PURE__*/React.createElement("textarea", {
    className: "mono",
    value: sel.prompt,
    onChange: e => patchNodes(ns => ns.map(n => n.id === sel.id ? {
      ...n,
      prompt: e.target.value
    } : n))
  })), /*#__PURE__*/React.createElement("div", {
    className: "attach-row"
  }, /*#__PURE__*/React.createElement(SeedChip, {
    k: "role",
    v: sel.role
  }), thread.seed.ctx ? /*#__PURE__*/React.createElement(SeedChip, {
    k: "ctx",
    v: thread.seed.ctx,
    acc: true
  }) : null)), /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Test step"), /*#__PURE__*/React.createElement("div", {
    className: "testbench"
  }, /*#__PURE__*/React.createElement("div", {
    className: "fx"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "corner-down-right"
  }), "input \u2190 ", prevNode ? `${prevNode.title} output` : 'thread message', " \xB7 last run"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "play",
    onClick: testStep
  }, test && test.state === 'running' ? 'Testing…' : 'Test this step only')), test && test.state === 'done' ? /*#__PURE__*/React.createElement("div", {
    className: "testresult"
  }, /*#__PURE__*/React.createElement("span", {
    className: "meta"
  }, test.meta), /*#__PURE__*/React.createElement("span", {
    className: "out"
  }, test.out), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement(ActChip, {
    icon: "pin",
    acc: true
  }, "pin as expectation"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "repeat"
  }, "swap model"))) : null))) : /*#__PURE__*/React.createElement("div", {
    className: "insp-empty"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "mouse-pointer-click"
  }), /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, lens === 'run' ? 'Select a step — or a timeline segment — to read the recorded execution.' : 'Select a step to edit and test it.')))), /*#__PURE__*/React.createElement("div", {
    className: "dock"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dock-head"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: "online",
    live: true
  }), /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, thread.name, " \u2014 test surface"), /*#__PURE__*/React.createElement("span", {
    className: "sub"
  }, "same thread, docked"), /*#__PURE__*/React.createElement("div", {
    className: "dock-head-spacer"
  }), /*#__PURE__*/React.createElement("span", {
    className: "sub"
  }, thread.msgs.length, " messages")), /*#__PURE__*/React.createElement("div", {
    className: "dock-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dock-msgs"
  }, thread.msgs.slice(-6).map((m, i) => m.who === 'sys' ? /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "msg sys"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bubble"
  }, m.text)) : /*#__PURE__*/React.createElement("div", {
    key: i,
    className: `msg ${m.who === 'user' ? 'user' : 'bot'}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "who"
  }, m.who === 'user' ? 'you' : 'agent'), /*#__PURE__*/React.createElement("span", {
    className: "bubble"
  }, m.text)))), /*#__PURE__*/React.createElement("div", {
    className: "dock-input"
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: "Exercise the workflow with the conversation that built it\u2026",
    value: input,
    onChange: e => setInput(e.target.value),
    onKeyDown: e => {
      if (e.key === 'Enter') send();
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "zap",
    onClick: send
  }, "Send")))));
}
window.CanvasMode = CanvasMode;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console-v2/CanvasMode.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console-v2/ChatHome.jsx
try { (() => {
/* Enclave Console v2 — chat home (threads rail | thread | structure rail). */

function ThreadRail({
  threads,
  activeId,
  onPick,
  onNew
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "threads"
  }, /*#__PURE__*/React.createElement("div", {
    className: "threads-head"
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Threads"), /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "plus",
    onClick: onNew
  }, "New")), /*#__PURE__*/React.createElement("div", {
    className: "threads-list"
  }, threads.map(t => /*#__PURE__*/React.createElement("div", {
    key: t.id,
    className: `thr ${t.id === activeId ? 'active' : ''}`,
    onClick: () => onPick(t.id)
  }, /*#__PURE__*/React.createElement(Pip, {
    status: t.id === activeId ? 'online' : 'idle'
  }), /*#__PURE__*/React.createElement("span", {
    className: "tx"
  }, /*#__PURE__*/React.createElement("span", {
    className: "tn"
  }, t.name), /*#__PURE__*/React.createElement("span", {
    className: "ts"
  }, t.seed.role, " \xB7 ", t.seed.model)), /*#__PURE__*/React.createElement(Badge, {
    tone: KIND_TONE[t.kind],
    sq: true
  }, t.kind)))));
}
function ChatMsg({
  m,
  i,
  onPin
}) {
  if (m.who === 'sys') return /*#__PURE__*/React.createElement("div", {
    className: "msg sys"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bubble"
  }, m.text));
  return /*#__PURE__*/React.createElement("div", {
    className: `msgwrap ${m.who}`
  }, /*#__PURE__*/React.createElement("div", {
    className: `msg ${m.who === 'user' ? 'user' : 'bot'}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "who"
  }, m.who === 'user' ? 'you' : 'agent'), /*#__PURE__*/React.createElement("span", {
    className: "bubble"
  }, m.text)), m.pinned ? /*#__PURE__*/React.createElement("span", {
    className: "pinmark"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "pin"
  }), "pinned as step \xB7 ", m.pinned) : m.who === 'bot' ? /*#__PURE__*/React.createElement("div", {
    className: "acts"
  }, /*#__PURE__*/React.createElement(ActChip, {
    icon: "pin",
    acc: true,
    onClick: () => onPin(i)
  }, "pin as step"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "scissors"
  }, "save as skill"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "git-branch"
  }, "branch")) : null);
}
function ScaffoldModal({
  thread,
  onClose,
  onConfirm
}) {
  const steps = [...thread.pins, {
    id: 'inf',
    title: 'validate',
    role: 'fast',
    src: 'suggested',
    dash: true
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "scrim",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal-head"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "git-merge",
    style: {
      width: 16,
      color: 'var(--accent)'
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "h"
  }, "Convert \"", thread.name, "\" to a workflow"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "x",
    bare: true,
    label: "Close",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    className: "modal-body"
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Scaffold preview \u2014 derived from this thread"), /*#__PURE__*/React.createElement("div", {
    className: "scaffold"
  }, /*#__PURE__*/React.createElement("div", {
    className: "scaffold-dag"
  }, steps.map((s, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: s.id
  }, i > 0 ? /*#__PURE__*/React.createElement("span", {
    className: "dagarrow"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "arrow-right",
    style: {
      width: 15
    }
  })) : null, /*#__PURE__*/React.createElement(MiniNode, {
    title: s.title,
    role: s.role,
    dash: s.dash
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 7
    }
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Traceability"), steps.map(s => /*#__PURE__*/React.createElement("div", {
    key: s.id,
    className: `tracerow ${s.dash ? 'dash' : ''}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, s.title), /*#__PURE__*/React.createElement("span", {
    className: "s"
  }, "\u2190 ", s.src, s.dash ? '' : ' · pinned'))))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--text-sm)',
      color: 'var(--text-muted)',
      lineHeight: 1.5
    }
  }, "Role, model, context and prompts are inherited from the seed and the pinned replies \u2014 nothing re-entered. The thread stays attached as the test surface.")), /*#__PURE__*/React.createElement("div", {
    className: "modal-foot"
  }, /*#__PURE__*/React.createElement(Btn, {
    onClick: onClose
  }, "Keep chatting instead"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "layout-dashboard",
    onClick: onConfirm
  }, "Edit on canvas"))));
}
function ChatHome({
  threads,
  activeId,
  setActiveId,
  updateThread,
  createThread
}) {
  const D2 = window.ENCLAVE2;
  const thread = threads.find(t => t.id === activeId) || threads[0];
  const [input, setInput] = React.useState('');
  const [scaffold, setScaffold] = React.useState(false);
  const endRef = React.useRef(null);
  React.useEffect(() => {
    window.refreshIcons();
  });
  React.useEffect(() => {
    const el = endRef.current;
    if (el && el.parentElement) {
      el.parentElement.scrollTop = el.parentElement.scrollHeight;
    }
  }, [thread.msgs.length, activeId]);
  const pins = thread.pins;
  const maturity = Math.min(5, 1 + pins.length + (thread.converted ? 1 : 0) + (thread.kind === 'agent' ? 1 : 0));
  function pinMsg(i) {
    const m = thread.msgs[i];
    const title = m.pinAs || `step-${pins.length + 1}`;
    const role = m.pinRole || thread.seed.role;
    updateThread(thread.id, t => ({
      ...t,
      msgs: t.msgs.map((mm, ii) => ii === i ? {
        ...mm,
        pinned: title
      } : mm),
      pins: [...t.pins, {
        id: 'p' + (t.pins.length + 1),
        title,
        role,
        src: `msg #${i + 1}`
      }]
    }));
  }
  function send() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    const ri = thread.ri || 0;
    updateThread(thread.id, t => ({
      ...t,
      msgs: [...t.msgs, {
        who: 'user',
        text
      }],
      ri: ri + 1
    }));
    setTimeout(() => {
      updateThread(thread.id, t => ({
        ...t,
        msgs: [...t.msgs, {
          who: 'bot',
          text: D2.REPLIES[ri % D2.REPLIES.length]
        }]
      }));
    }, 700);
  }
  function confirmConvert() {
    setScaffold(false);
    const steps = [...pins, {
      title: 'validate',
      role: 'fast'
    }];
    const nodes = steps.map((s, i) => ({
      id: 'n' + (i + 1),
      title: s.title,
      role: s.role,
      model: (window.ENCLAVE.MODELS.find(m => m.role === s.role) || {}).id || 'auto',
      x: 40 + i * 260,
      y: i % 2 ? 80 : 170,
      prompt: `Derived from ${s.src || 'thread'} — refine as needed.`
    }));
    const edges = nodes.slice(1).map((n, i) => [nodes[i].id, n.id]);
    updateThread(thread.id, t => ({
      ...t,
      converted: true,
      kind: 'wf',
      mode: 'canvas',
      nodes,
      edges,
      msgs: [...t.msgs, {
        who: 'sys',
        text: `Converted to workflow — ${nodes.length} steps scaffolded from this thread.`
      }]
    }));
  }
  function researchCtx() {
    createThread({
      name: 'xsiam dm research',
      kind: 'chat',
      seed: {
        role: 'reasoning',
        model: 'dolphin-mixtral',
        ctx: null,
        plugin: 'web-search'
      },
      msgs: [{
        who: 'sys',
        text: 'Seeded with web-search — findings can be added to a context bundle.'
      }, {
        who: 'user',
        text: 'Build me context on the XSIAM data model — fields, mappings, gotchas.'
      }]
    });
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "chathome"
  }, /*#__PURE__*/React.createElement(ThreadRail, {
    threads: threads,
    activeId: thread.id,
    onPick: setActiveId,
    onNew: () => createThread({
      name: 'untitled thread',
      kind: 'chat',
      seed: {
        role: 'general',
        model: 'nous-hermes2',
        ctx: null
      },
      msgs: [{
        who: 'sys',
        text: 'Seeded — general · nous-hermes2. Attach context or pick a role to tune the seed.'
      }]
    })
  }), /*#__PURE__*/React.createElement("div", {
    className: "chatpane"
  }, /*#__PURE__*/React.createElement("div", {
    className: "chat-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nm"
  }, thread.name), /*#__PURE__*/React.createElement(SeedChip, {
    k: "role",
    v: thread.seed.role
  }), /*#__PURE__*/React.createElement(SeedChip, {
    k: "model",
    v: thread.seed.model
  }), thread.seed.plugin ? /*#__PURE__*/React.createElement(SeedChip, {
    k: "plugin",
    v: thread.seed.plugin,
    acc: true
  }) : null, thread.seed.ctx ? /*#__PURE__*/React.createElement(SeedChip, {
    k: "ctx",
    v: thread.seed.ctx,
    acc: true
  }) : /*#__PURE__*/React.createElement(SeedChip, {
    ghost: true,
    v: "+ context"
  }), /*#__PURE__*/React.createElement("span", {
    className: "chat-head-spacer"
  }), /*#__PURE__*/React.createElement(Meter, {
    value: maturity,
    hot: pins.length >= 2 && !thread.converted
  }), /*#__PURE__*/React.createElement("div", {
    className: "pivot"
  }, /*#__PURE__*/React.createElement("button", {
    className: "on"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "message-square"
  }), "Chat"), /*#__PURE__*/React.createElement("button", {
    disabled: !thread.converted,
    title: thread.converted ? 'Open the workflow canvas' : 'Convert first — pin 2+ steps',
    onClick: () => updateThread(thread.id, t => ({
      ...t,
      mode: 'canvas'
    }))
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "workflow"
  }), "Canvas")), pins.length >= 2 && !thread.converted ? /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "git-merge",
    onClick: () => setScaffold(true)
  }, "Convert") : null), /*#__PURE__*/React.createElement("div", {
    className: "chat-msgs"
  }, /*#__PURE__*/React.createElement("div", {
    className: "inner"
  }, thread.msgs.map((m, i) => /*#__PURE__*/React.createElement(ChatMsg, {
    key: i,
    m: m,
    i: i,
    onPin: pinMsg
  })), /*#__PURE__*/React.createElement("div", {
    ref: endRef
  }))), /*#__PURE__*/React.createElement("div", {
    className: "nba"
  }, pins.length >= 2 && !thread.converted ? /*#__PURE__*/React.createElement(ActChip, {
    icon: "git-merge",
    acc: true,
    onClick: () => setScaffold(true)
  }, "you've pinned ", pins.length, " steps \u2014 convert to a workflow?") : null, !thread.seed.ctx && !thread.seed.plugin ? /*#__PURE__*/React.createElement(ActChip, {
    icon: "telescope",
    onClick: researchCtx
  }, "no context attached \u2014 research it?") : null, thread.kind === 'chat' && thread.msgs.length > 4 && !thread.converted ? /*#__PURE__*/React.createElement(ActChip, {
    icon: "bot"
  }, "save this persona as an agent?") : null), /*#__PURE__*/React.createElement("div", {
    className: "chatbox"
  }, /*#__PURE__*/React.createElement("div", {
    className: "inner"
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: `Message ${thread.seed.model}…`,
    value: input,
    onChange: e => setInput(e.target.value),
    onKeyDown: e => {
      if (e.key === 'Enter') send();
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "chips"
  }, /*#__PURE__*/React.createElement(SeedChip, {
    ghost: true,
    v: "+ context"
  }), /*#__PURE__*/React.createElement(SeedChip, {
    ghost: true,
    v: "agent \u25BE"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "zap",
    onClick: send
  }, "Send"))))), /*#__PURE__*/React.createElement("div", {
    className: "struct"
  }, /*#__PURE__*/React.createElement("div", {
    className: "struct-head"
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Structure")), /*#__PURE__*/React.createElement("div", {
    className: "struct-hint"
  }, "Pin replies to grow the workflow draft. Each step keeps a trace back to its message."), /*#__PURE__*/React.createElement("div", {
    className: "struct-list"
  }, pins.map((p, i) => /*#__PURE__*/React.createElement("div", {
    key: p.id,
    className: "stepcard"
  }, /*#__PURE__*/React.createElement("div", {
    className: "top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, i + 1), /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, p.title), /*#__PURE__*/React.createElement(Badge, {
    tone: "accent",
    sq: true
  }, p.role)), /*#__PURE__*/React.createElement("span", {
    className: "src"
  }, "\u2190 ", p.src, " \xB7 pinned \u2713"))), /*#__PURE__*/React.createElement("div", {
    className: "stepcard ghost"
  }, /*#__PURE__*/React.createElement("div", {
    className: "top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, "+"), /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, "add a step\u2026")))), /*#__PURE__*/React.createElement("div", {
    className: "struct-foot"
  }, thread.converted ? /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "workflow",
    onClick: () => updateThread(thread.id, t => ({
      ...t,
      mode: 'canvas'
    }))
  }, "Open canvas") : /*#__PURE__*/React.createElement(Btn, {
    variant: pins.length >= 2 ? 'primary' : '',
    icon: "git-merge",
    disabled: pins.length < 2,
    style: pins.length < 2 ? {
      opacity: .5,
      cursor: 'not-allowed'
    } : null,
    onClick: () => pins.length >= 2 && setScaffold(true)
  }, "Convert to workflow"), /*#__PURE__*/React.createElement("span", {
    className: "hint"
  }, thread.converted ? 'Converted — the canvas is one pivot away.' : pins.length < 2 ? `Pin ${2 - pins.length} more ${pins.length === 1 ? 'reply' : 'replies'} to unlock conversion.` : 'Scaffolds a DAG you can refine on the canvas.'))), scaffold ? /*#__PURE__*/React.createElement(ScaffoldModal, {
    thread: thread,
    onClose: () => setScaffold(false),
    onConfirm: confirmConvert
  }) : null);
}
window.ChatHome = ChatHome;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console-v2/ChatHome.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console-v2/Library2.jsx
try { (() => {
/* Enclave Console v2 — Library: unified entity cards, peek panel, compare, install wizard. */

const LIB_TABS = [{
  id: 'models',
  label: 'Models',
  wiz: 'model'
}, {
  id: 'agents',
  label: 'Agents',
  wiz: 'agent'
}, {
  id: 'skills',
  label: 'Skills',
  wiz: 'skill'
}, {
  id: 'plugins',
  label: 'Plugins · MCP',
  wiz: 'plugin'
}, {
  id: 'contexts',
  label: 'Contexts',
  wiz: null
}];
function ECard({
  e,
  sel,
  onPeek
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: `ecard ${sel ? 'sel' : ''}`,
    onClick: onPeek
  }, /*#__PURE__*/React.createElement("div", {
    className: "ehead"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: e.status === 'online' ? 'online' : 'idle',
    live: e.status === 'online'
  }), /*#__PURE__*/React.createElement("span", {
    className: "eid"
  }, e.title || e.id), /*#__PURE__*/React.createElement(Badge, {
    tone: e.type === 'model' ? 'accent' : e.type === 'agent' ? 'info' : e.type === 'mcp' ? 'warm' : 'neutral',
    sq: true
  }, e.type)), /*#__PURE__*/React.createElement("div", {
    className: "emeta"
  }, e.meta), e.fits ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5
    }
  }, /*#__PURE__*/React.createElement(Fit, {
    k: "coding",
    v: e.fits.coding
  }), /*#__PURE__*/React.createElement(Fit, {
    k: "reasoning",
    v: e.fits.reasoning
  }), /*#__PURE__*/React.createElement(Fit, {
    k: "fast",
    v: e.fits.fast
  })) : e.desc ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--text-sm)',
      color: 'var(--text-dim)'
    }
  }, e.desc) : null, /*#__PURE__*/React.createElement("div", {
    className: "efoot"
  }, /*#__PURE__*/React.createElement("span", {
    className: "emeta"
  }, Object.entries(e.usedBy || {}).map(([k, v]) => `${v} ${k}`).join(' · ')), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(ActChip, {
    icon: "chevron-right"
  }, "peek")));
}
function PeekPanel({
  e,
  onClose,
  onSeedChat,
  onCompare
}) {
  const [tab, setTab] = React.useState('overview');
  React.useEffect(() => {
    window.refreshIcons();
  });
  const useRows = Object.entries(e.usedBy || {});
  return /*#__PURE__*/React.createElement("div", {
    className: "peek",
    onClick: ev => ev.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "peek-head"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: e.status === 'online' ? 'online' : 'idle',
    live: e.status === 'online'
  }), /*#__PURE__*/React.createElement("span", {
    className: "eid"
  }, e.title || e.id), /*#__PURE__*/React.createElement(Badge, {
    tone: "accent",
    sq: true
  }, e.type), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), e.type === 'model' ? /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: e.loaded ? 'check' : 'download'
  }, e.loaded ? 'Loaded' : 'Load') : /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "pen-line"
  }, "Edit"), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "x",
    bare: true,
    label: "Close",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    className: "peek-tabs"
  }, ['overview', 'usage', 'history', 'raw'].map(t => /*#__PURE__*/React.createElement("span", {
    key: t,
    className: `peek-tab ${tab === t ? 'on' : ''}`,
    onClick: () => setTab(t)
  }, t))), /*#__PURE__*/React.createElement("div", {
    className: "peek-body"
  }, tab === 'overview' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "emeta",
    style: {
      fontSize: 'var(--text-sm)'
    }
  }, e.meta), e.desc ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--text-sm)',
      color: 'var(--text-dim)',
      lineHeight: 1.5
    }
  }, e.desc) : null, e.fits ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Role fit \u2014 measured on this fleet"), /*#__PURE__*/React.createElement(Fit, {
    k: "coding",
    v: e.fits.coding
  }), /*#__PURE__*/React.createElement(Fit, {
    k: "reasoning",
    v: e.fits.reasoning
  }), /*#__PURE__*/React.createElement(Fit, {
    k: "fast",
    v: e.fits.fast
  })) : null, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Used by"), useRows.map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "userow"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: TYPE_ICON[k.replace(/s$/, '')] || 'box'
  }), /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, v), /*#__PURE__*/React.createElement("span", null, k)))) : null, tab === 'usage' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Dependents"), useRows.length ? useRows.map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "userow"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: TYPE_ICON[k.replace(/s$/, '')] || 'box'
  }), /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, v, " ", k), /*#__PURE__*/React.createElement("span", null, "\u2014 removing this ", e.type, " affects them"))) : /*#__PURE__*/React.createElement("div", {
    className: "emeta"
  }, "No dependents yet.")) : null, tab === 'history' ? /*#__PURE__*/React.createElement("div", {
    className: "emeta",
    style: {
      lineHeight: 2
    }
  }, "last used 2h ago \xB7 31 invocations this week \xB7 added 14d ago") : null, tab === 'raw' ? /*#__PURE__*/React.createElement("div", {
    className: "emeta",
    style: {
      whiteSpace: 'pre',
      lineHeight: 1.7
    }
  }, `id: ${e.id}\ntype: ${e.type}\nstatus: ${e.status}\n# full yaml in the repo`) : null), /*#__PURE__*/React.createElement("div", {
    className: "peek-foot"
  }, /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "message-square",
    onClick: () => onSeedChat(e)
  }, "Test in chat"), e.type === 'model' ? /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "columns-3",
    onClick: onCompare
  }, "Compare") : null, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "maximize-2"
  }, "Open full")));
}
function CompareBar({
  models,
  onClose,
  onSeedChat
}) {
  const win = models.reduce((a, b) => a.fits.coding > b.fits.coding ? a : b);
  return /*#__PURE__*/React.createElement("div", {
    className: "comparebar"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Compare \u2014 best for: coding"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "x",
    bare: true,
    label: "Close",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    className: "comparegrid"
  }, models.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.id,
    className: `comparecol ${m.id === win.id ? 'win' : ''}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "id"
  }, m.id, m.id === win.id ? ' ★' : ''), /*#__PURE__*/React.createElement("span", null, m.loaded ? m.tps + ' tok/s' : 'cold start'), /*#__PURE__*/React.createElement("span", null, m.size, " resident"), /*#__PURE__*/React.createElement(Fit, {
    k: "coding",
    v: m.fits.coding
  }), /*#__PURE__*/React.createElement("span", null, m.loaded ? 'loaded' : 'on disk')))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "zap",
    onClick: () => onSeedChat(win)
  }, "Seed a chat with ", win.id)));
}
function InstallWizard({
  type,
  onClose,
  onSeedChat
}) {
  const W = window.ENCLAVE2.WIZARDS[type];
  const [step, setStep] = React.useState(0);
  const [src, setSrc] = React.useState(0);
  const [verified, setVerified] = React.useState(false);
  React.useEffect(() => {
    window.refreshIcons();
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "scrim",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal",
    style: {
      width: 'min(640px, calc(100vw - 48px))'
    },
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal-head"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: TYPE_ICON[type],
    style: {
      width: 16,
      color: 'var(--accent)'
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "h"
  }, "Install \u2014 new ", type), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "x",
    bare: true,
    label: "Close",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    className: "modal-body"
  }, /*#__PURE__*/React.createElement(WStepper, {
    active: step
  }), step === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, W.sources.map((s, i) => /*#__PURE__*/React.createElement("div", {
    key: s,
    className: `wsource ${src === i ? 'sel' : ''}`,
    onClick: () => setSrc(i)
  }, /*#__PURE__*/React.createElement("span", {
    className: "rad"
  }), /*#__PURE__*/React.createElement("span", null, s), s.includes('★') ? /*#__PURE__*/React.createElement(Badge, {
    tone: "accent",
    sq: true
  }, "the ladder") : null))) : null, step === 1 ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, W.fields.map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "field",
    style: {
      marginBottom: 0
    }
  }, /*#__PURE__*/React.createElement("label", null, k), /*#__PURE__*/React.createElement("input", {
    className: "mono",
    defaultValue: v
  })))) : null, step === 2 ? /*#__PURE__*/React.createElement("div", {
    className: "vchat"
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Verify \u2014 talk to it"), /*#__PURE__*/React.createElement("div", {
    className: "msg user",
    style: {
      alignSelf: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "bubble"
  }, W.verifyPrompt)), verified ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "msg bot",
    style: {
      maxWidth: '92%'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "bubble"
  }, W.verifyReply)), /*#__PURE__*/React.createElement("span", {
    className: "vmeta"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "check",
    style: {
      width: 13
    }
  }), W.verifyMeta)) : /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "play",
    onClick: () => setVerified(true),
    style: {
      alignSelf: 'flex-start'
    }
  }, "Send test prompt")) : null, step === 3 ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--text-base)',
      color: 'var(--text)',
      lineHeight: 1.5
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "check-circle-2",
    style: {
      width: 15,
      color: 'var(--success)',
      verticalAlign: -2,
      marginRight: 7
    }
  }), "Installed. Lands in: ", W.lands), /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Next rung"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(ActChip, {
    icon: "zap",
    acc: true,
    onClick: () => {
      onClose();
      onSeedChat({
        id: W.fields[0][1],
        type
      });
    }
  }, "seed a chat with it"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "workflow"
  }, "add to a workflow"))) : null), /*#__PURE__*/React.createElement("div", {
    className: "modal-foot"
  }, step > 0 && step < 3 ? /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    onClick: () => setStep(s => s - 1)
  }, "Back") : null, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), step < 3 ? /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    icon: "arrow-right",
    onClick: () => setStep(s => s + 1),
    style: step === 2 && !verified ? {
      opacity: .5
    } : null,
    disabled: step === 2 && !verified
  }, step === 2 ? 'Finish' : 'Next') : /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    sm: true,
    onClick: onClose
  }, "Done"))));
}
function Library2({
  onSeedChat,
  onResearch
}) {
  const E = window.ENCLAVE2.ENTITIES;
  const [tab, setTab] = React.useState('models');
  const [peekId, setPeekId] = React.useState(null);
  const [compare, setCompare] = React.useState(false);
  const [wizard, setWizard] = React.useState(null);
  React.useEffect(() => {
    window.refreshIcons();
  });
  const items = E[tab] || [];
  const peek = items.find(e => e.id === peekId) || null;
  const tabDef = LIB_TABS.find(t => t.id === tab);
  return /*#__PURE__*/React.createElement("div", {
    className: "libwrap",
    onClick: () => setPeekId(null)
  }, /*#__PURE__*/React.createElement("div", {
    className: "libscroll"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page",
    style: {
      height: 'auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Library"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Every entity, one card \u2014 peek for depth, push for work."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), tabDef.wiz ? /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "plus",
    onClick: e => {
      e.stopPropagation();
      setWizard(tabDef.wiz);
    }
  }, "Install ", tab.replace(/s$/, '')) : /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "telescope",
    onClick: e => {
      e.stopPropagation();
      onResearch();
    }
  }, "Research a context")), /*#__PURE__*/React.createElement("div", {
    className: "toolbar"
  }, LIB_TABS.map(t => /*#__PURE__*/React.createElement(Btn, {
    key: t.id,
    sm: true,
    onClick: e => {
      e.stopPropagation();
      setTab(t.id);
      setPeekId(null);
      setCompare(false);
    },
    style: t.id === tab ? {
      borderColor: 'var(--accent-dim)',
      color: 'var(--accent)',
      background: 'var(--accent-ghost)'
    } : null
  }, t.label)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "search"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "search"
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: `Search ${tab}…`
  }))), /*#__PURE__*/React.createElement("div", {
    className: "cardgrid"
  }, items.map(e => /*#__PURE__*/React.createElement(ECard, {
    key: e.id,
    e: e,
    sel: peekId === e.id,
    onPeek: ev => {
      ev.stopPropagation();
      setPeekId(e.id);
    }
  }))))), peek ? /*#__PURE__*/React.createElement(PeekPanel, {
    e: peek,
    onClose: () => setPeekId(null),
    onSeedChat: onSeedChat,
    onCompare: () => setCompare(true)
  }) : null, compare ? /*#__PURE__*/React.createElement(CompareBar, {
    models: E.models.filter(m => m.fits).slice(0, 3),
    onClose: () => setCompare(false),
    onSeedChat: onSeedChat
  }) : null, wizard ? /*#__PURE__*/React.createElement(InstallWizard, {
    type: wizard,
    onClose: () => setWizard(null),
    onSeedChat: onSeedChat
  }) : null);
}
window.Library2 = Library2;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console-v2/Library2.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console-v2/data2.js
try { (() => {
/* Enclave Console v2 — chat-led data. Extends window.ENCLAVE (load data.js first). */
(function () {
  const D = window.ENCLAVE;
  if (!D) return; // standalone evaluation guard (e.g. DS compiler sandbox) — this file derives from data.js

  /* Threads — every object is born as a conversation. */
  const THREADS = [{
    id: 't1',
    name: 'xsiam log triage',
    kind: 'chat',
    converted: false,
    mode: 'chat',
    seed: {
      role: 'reasoning',
      model: 'dolphin-mixtral',
      ctx: 'xsiam-docs'
    },
    msgs: [{
      who: 'sys',
      text: 'Seeded — reasoning · dolphin-mixtral · ctx: xsiam-docs (142 chunks).'
    }, {
      who: 'user',
      text: 'Here is a raw CrowdStrike export. Identify the schema and summarize the fields present.'
    }, {
      who: 'bot',
      text: 'Vendor: CrowdStrike Falcon, FDR format. 38 fields detected — event_simpleName, aid, ComputerName, timestamp (epoch ms), 11 network fields, 9 process fields. Schema is consistent across the batch.',
      pinned: 'analyze'
    }, {
      who: 'user',
      text: 'Map those onto the XSIAM data model. Field map only.'
    }, {
      who: 'bot',
      text: 'Field map drafted: 31/38 fields map cleanly (xdm.source.host ← ComputerName, xdm.event.type ← event_simpleName…). 7 vendor-specific fields need a custom mapping block. Want it as YAML?',
      pinAs: 'normalize',
      pinRole: 'coding'
    }],
    pins: [{
      id: 'p1',
      title: 'analyze',
      role: 'reasoning',
      src: 'msg #3'
    }],
    nodes: null,
    edges: null
  }, {
    id: 't2',
    name: 'threat intel notes',
    kind: 'agent',
    converted: false,
    mode: 'chat',
    seed: {
      role: 'reasoning',
      model: 'dolphin-mixtral',
      ctx: 'unit42-feed'
    },
    msgs: [{
      who: 'sys',
      text: 'Saved as agent xsiam-analyst — role, model, prompt and context pinned.'
    }, {
      who: 'user',
      text: 'Summarize today\u2019s Unit42 feed against our watchlist.'
    }, {
      who: 'bot',
      text: '3 overlaps: Scattered Spider TTPs (T1566.004), a new Qakbot loader hash, and infra reuse on 2 watched ASNs. Full notes in the bundle.'
    }],
    pins: [],
    nodes: null,
    edges: null
  }, {
    id: 't3',
    name: 'pr review loop',
    kind: 'wf',
    converted: true,
    mode: 'chat',
    seed: {
      role: 'coding',
      model: 'qwen2.5-coder',
      ctx: null
    },
    msgs: [{
      who: 'sys',
      text: 'Converted to workflow — 3 steps scaffolded from this thread.'
    }, {
      who: 'user',
      text: 'Review PR #214 — the detection rule refactor.'
    }, {
      who: 'bot',
      text: '▸ lint-pass (qwen2.5-coder) — 2 style nits, no logic issues. ▸ security-review — no injected paths. ▸ summarize — approved with comments.'
    }],
    pins: [{
      id: 'p1',
      title: 'lint-pass',
      role: 'coding',
      src: 'msg #2'
    }, {
      id: 'p2',
      title: 'security-review',
      role: 'reasoning',
      src: 'msg #2'
    }, {
      id: 'p3',
      title: 'summarize',
      role: 'fast',
      src: 'msg #3'
    }],
    nodes: [{
      id: 'n1',
      title: 'lint-pass',
      role: 'coding',
      model: 'qwen2.5-coder',
      x: 40,
      y: 150,
      prompt: 'Lint the diff. Style + logic issues, severity-tagged.'
    }, {
      id: 'n2',
      title: 'security-review',
      role: 'reasoning',
      model: 'dolphin-mixtral',
      x: 300,
      y: 80,
      prompt: 'Adversarial review: injection, path traversal, secrets.'
    }, {
      id: 'n3',
      title: 'summarize',
      role: 'fast',
      model: 'llama3.2:3b',
      x: 560,
      y: 150,
      prompt: 'One-paragraph verdict with blocking items first.'
    }],
    edges: [['n1', 'n2'], ['n1', 'n3'], ['n2', 'n3']]
  }, {
    id: 't4',
    name: 'model bake-off',
    kind: 'chat',
    converted: false,
    mode: 'chat',
    seed: {
      role: 'coding',
      model: 'qwen2.5-coder',
      ctx: null
    },
    msgs: [{
      who: 'user',
      text: 'Same normalization prompt against qwen2.5-coder and dolphin-mixtral — compare outputs.'
    }, {
      who: 'bot',
      text: 'qwen2.5-coder: valid YAML, 47 tok/s. dolphin-mixtral: richer field rationale, 12 tok/s. For the normalize step, qwen wins on structure per watt.'
    }],
    pins: [],
    nodes: null,
    edges: null
  }];

  /* Canned assistant replies for the live chat. */
  const REPLIES = ['Validated against the data model: 31 mapped, 7 custom. Two required keys missing on 4% of events — _time and xdm.event.id. I can draft the fallback block.', 'Done. Custom mapping block drafted for the 7 vendor fields — epoch→RFC3339 on _time, aid→xdm.source.agent.id. Re-validated: 0 dropped.', 'Batch normalized: 1,284 events, 0 dropped, 38 tok/s sustained. Emitted as NDJSON to workspace.emit.batch.'];

  /* Library entities — one card anatomy for everything. */
  const FITS = {
    'dolphin-mixtral': {
      coding: 55,
      reasoning: 88,
      fast: 20
    },
    'qwen2.5-coder': {
      coding: 90,
      reasoning: 40,
      fast: 65
    },
    'llama3.2:3b': {
      coding: 35,
      reasoning: 25,
      fast: 95
    },
    'nous-hermes2': {
      coding: 45,
      reasoning: 70,
      fast: 25
    },
    'yi-34b': {
      coding: 45,
      reasoning: 80,
      fast: 18
    },
    'wizardlm-uncensored': {
      coding: 30,
      reasoning: 60,
      fast: 45
    }
  };
  const ENTITIES = {
    models: D.MODELS.map(m => ({
      type: 'model',
      id: m.id,
      status: m.loaded ? 'online' : 'idle',
      meta: `${m.size} · ${m.quant} · ${m.loaded ? m.tps + ' tok/s' : 'cold'}`,
      fits: FITS[m.id],
      usedBy: {
        steps: m.loaded ? 3 : 1,
        agents: m.loaded ? 2 : 0,
        workflows: 1
      },
      tps: m.tps,
      size: m.size,
      loaded: m.loaded,
      role: m.role
    })),
    agents: D.AGENTS.map(a => ({
      type: 'agent',
      id: a.title,
      status: 'online',
      meta: `${a.role} · ${a.model}`,
      desc: a.desc,
      usedBy: {
        steps: 2,
        workflows: 1,
        threads: 3
      },
      role: a.role,
      model: a.model
    })),
    skills: D.SKILLS.map(s => ({
      type: 'skill',
      id: s.title,
      status: 'idle',
      meta: 'auto-injects on trigger',
      desc: s.desc,
      usedBy: {
        steps: 1,
        agents: 1
      }
    })),
    plugins: [...D.PLUGINS.map(p => ({
      ...p,
      t: 'plugin'
    })), ...D.MCPS.map(p => ({
      ...p,
      t: 'mcp'
    }))].map(p => ({
      type: p.t,
      id: p.title,
      status: p.t === 'mcp' ? 'online' : 'idle',
      meta: p.desc,
      usedBy: {
        steps: p.t === 'mcp' ? 2 : 1
      }
    })),
    contexts: [{
      type: 'context',
      id: 'xsiam-docs',
      status: 'online',
      meta: '7 docs · 142 chunks · graph: 41 nodes',
      usedBy: {
        threads: 2,
        agents: 1,
        workflows: 1
      }
    }, {
      type: 'context',
      id: 'unit42-feed',
      status: 'online',
      meta: 'live feed · 89 chunks',
      usedBy: {
        threads: 1,
        agents: 1
      }
    }, {
      type: 'context',
      id: 'detection-rules-q4',
      status: 'idle',
      meta: '3 docs · 56 chunks',
      usedBy: {
        workflows: 1
      }
    }],
    workflows: D.WORKFLOWS.map(w => ({
      type: 'workflow',
      id: w.id,
      title: w.name,
      status: 'idle',
      meta: `${w.steps} steps · ${w.runs} runs · ${w.updated}`,
      usedBy: {
        runs: w.runs
      },
      category: w.category
    }))
  };

  /* Unified install wizard — one stepper skeleton, five payloads. */
  const WIZARDS = {
    model: {
      sources: ['Ollama registry', 'Hugging Face URL', 'Local GGUF file'],
      fields: [['name', 'mistral-nemo:12b'], ['quant', 'Q4_K_M (recommended · ~7 GB)'], ['role mapping', 'general'], ['target box', 'ms-01 · 64 GB']],
      verifyPrompt: 'Summarize the XSIAM data model in one paragraph.',
      verifyReply: 'XSIAM\u2019s data model (XDM) normalizes vendor telemetry into a shared schema — xdm.source.*, xdm.event.*, xdm.network.* — so detections are written once against normalized fields rather than per-vendor formats.',
      verifyMeta: '✓ responds · 41 tok/s · 6.8 GB resident',
      lands: 'Library → Models, with role-fit suggestions computed on first runs.'
    },
    agent: {
      sources: ['From a thread ★', 'Blank persona'],
      fields: [['name', 'xsiam-analyst-2'], ['role', 'reasoning'], ['model', 'dolphin-mixtral'], ['context', 'xsiam-docs'], ['system prompt', 'distilled from thread ✎']],
      verifyPrompt: 'Triage: 40 failed logins, then a success from a new ASN.',
      verifyReply: 'Pattern matches credential stuffing → success. Severity: high. Recommend session revoke + ASN block; checking watchlist overlap next.',
      verifyMeta: '✓ persona holds · 12 tok/s',
      lands: 'Palette → Agents, and offered in every seed strip.'
    },
    skill: {
      sources: ['Markdown file', 'From a pinned reply ★'],
      fields: [['name', 'cite-sources'], ['triggers', 'cite, evidence, source'], ['injection', 'append']],
      verifyPrompt: 'Why is this IP flagged? cite sources.',
      verifyReply: 'Flagged for C2 beaconing [1] and ASN reuse [2]. — [1] unit42-feed §3, [2] xsiam-docs/infra.md',
      verifyMeta: '✓ trigger fired · refs appended',
      lands: 'Auto-injects on trigger; listed in Palette → Skills.'
    },
    plugin: {
      sources: ['MCP catalog', 'Server URL'],
      fields: [['name', 'postgres'], ['permissions', 'query (read-only)'], ['env', 'PGHOST · PGUSER · key from vault']],
      verifyPrompt: 'Dry-run: list tables in the warehouse.',
      verifyReply: 'tool_call: postgres.query → 14 tables (events_raw, events_norm, detections, …). Read-only confirmed.',
      verifyMeta: '✓ tool call round-trip · 80 ms',
      lands: 'Callable from any step; listed in Palette → MCPs.'
    },
    workflow: {
      sources: ['From a thread ★', 'YAML import'],
      fields: [['name', 'xsiam-normalize-v2'], ['map steps to models', 'auto-fit (3/4 local)'], ['schedule', 'manual']],
      verifyPrompt: 'Dry run with sample-batch.json.',
      verifyReply: '4/4 steps green on the sample — 212 events normalized, 0 dropped, 0:38 wall clock.',
      verifyMeta: '✓ dry run pass · 0:38',
      lands: 'Workflows + Composer; first run checkpointed.'
    }
  };

  /* Operator's path — the adoption ladder, tracked. */
  const PATH = [{
    t: 'seed your first chat',
    done: true
  }, {
    t: 'pin a reply as a step',
    done: true
  }, {
    t: 'save a persona as an agent',
    done: true
  }, {
    t: 'convert a thread to a workflow',
    done: false,
    hot: true
  }, {
    t: 'schedule a run on the fleet',
    done: false
  }];

  /* System performance — last hour / last 8 runs (deterministic mock). */
  const UTIL = {
    cpu: [22, 31, 28, 36, 44, 41, 52, 48, 57, 61, 55, 40, 34],
    mem: [38, 38, 41, 48, 48, 59, 64, 64, 73, 81, 81, 76, 69],
    tps: [31, 35, 33, 41, 38, 47, 44, 49, 46, 51, 47, 44, 47],
    dur: [62, 58, 55, 49, 52, 47, 44, 41],
    runs: [3, 5, 4, 7, 6, 9, 8, 11]
  };
  window.ENCLAVE2 = {
    THREADS,
    REPLIES,
    ENTITIES,
    WIZARDS,
    PATH,
    UTIL
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console-v2/data2.js", error: String((e && e.message) || e) }); }

// ui_kits/console-v2/parts2.jsx
try { (() => {
/* Enclave Console v2 — shared atoms (window-exported). Reuses v1 primitives. */

function SeedChip({
  k,
  v,
  acc,
  ghost,
  onClick
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: `seedchip ${acc ? 'acc' : ''} ${ghost ? 'ghost' : ''}`,
    onClick: onClick
  }, k ? /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, k) : null, /*#__PURE__*/React.createElement("span", null, v));
}
function Meter({
  value,
  total = 5,
  hot
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: "rmeter",
    title: `maturity ${value}/${total}`
  }, Array.from({
    length: total
  }, (_, i) => /*#__PURE__*/React.createElement("i", {
    key: i,
    className: i < value ? 'on' : hot && i === value ? 'hot' : ''
  })));
}
function ActChip({
  icon,
  acc,
  children,
  onClick,
  title
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: `actchip ${acc ? 'acc' : ''}`,
    onClick: onClick,
    title: title
  }, icon ? /*#__PURE__*/React.createElement(Ico, {
    n: icon
  }) : null, children);
}
const W_PHASES = ['source', 'configure', 'verify', 'land'];
function WStepper({
  active
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "wsteps"
  }, W_PHASES.map((p, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: p
  }, i > 0 ? /*#__PURE__*/React.createElement("span", {
    className: "wconn"
  }) : null, /*#__PURE__*/React.createElement("span", {
    className: `wstep ${i < active ? 'done' : ''} ${i === active ? 'on' : ''}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, i < active ? '✓' : i + 1), p))));
}
function MiniNode({
  title,
  role,
  dash
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: `minimode ${dash ? 'dash' : ''}`,
    style: {
      '--nr': `var(--node-${role})`
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule"
  }), /*#__PURE__*/React.createElement("div", {
    className: "b"
  }, /*#__PURE__*/React.createElement("div", {
    className: "r"
  }, role), /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, title)));
}
function Fit({
  k,
  v
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "efit"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, k), /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: v + '%'
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, v));
}
const TYPE_ICON = {
  model: 'box',
  agent: 'bot',
  skill: 'scissors',
  plugin: 'plug',
  mcp: 'server',
  context: 'database',
  workflow: 'workflow',
  run: 'circle-play',
  chat: 'message-square'
};
const KIND_TONE = {
  chat: 'accent',
  agent: 'info',
  wf: 'success'
};
const PALETTE_HINT2 = {
  roles: 'Click to add a step with the role\u2019s best-fit local model.',
  agents: 'Saved personas — role + model + prompt + pinned context.',
  skills: 'Markdown prompts that auto-inject on trigger keywords.',
  plugins: 'External tools callable from steps.',
  mcps: 'MCP servers — tools over the Model Context Protocol.'
};
const RUN_LINES2 = {
  'analyze': 'schema identified — CrowdStrike FDR, 38 fields.',
  'normalize': 'field map applied — 31 mapped, 7 custom.',
  'validate': 'required keys present on 100% of events.',
  'emit': 'NDJSON batch written to workspace.emit.batch.',
  'lint-pass': '2 style nits, no logic issues.',
  'security-review': 'no injected paths, no secrets in diff.',
  'summarize': 'verdict: approve with comments.'
};

/* ── Kit-local data viz (cosmetic mirrors of the DS dataviz atoms) ── */
function sparkPts(data, w, h) {
  const hi = Math.max(...data, 1),
    lo = Math.min(...data, 0),
    span = hi - lo || 1;
  return data.map((v, i) => [2 + i / Math.max(1, data.length - 1) * (w - 4), 2 + (h - 4) * (1 - (v - lo) / span)]);
}
function Spark({
  data,
  width = 110,
  height = 24,
  color = 'var(--accent)'
}) {
  const pts = sparkPts(data, width, height);
  const line = pts.map(p => p.map(n => +n.toFixed(1)).join(',')).join(' ');
  const last = pts[pts.length - 1];
  return /*#__PURE__*/React.createElement("svg", {
    width: width,
    height: height,
    viewBox: `0 0 ${width} ${height}`,
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("polygon", {
    points: `2,${height - 2} ${line} ${width - 2},${height - 2}`,
    fill: color,
    opacity: "0.1"
  }), /*#__PURE__*/React.createElement("polyline", {
    points: line,
    fill: "none",
    stroke: color,
    strokeWidth: "1.5",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: last[0],
    cy: last[1],
    r: "2",
    fill: color
  }));
}
function Trend({
  label,
  value,
  delta,
  good = true,
  data,
  color = 'var(--accent)'
}) {
  const down = delta && delta.startsWith('-');
  const col = !delta ? 'var(--text-faint)' : (down ? !good : good) ? 'var(--success)' : 'var(--accent-warm)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-2xs)',
      fontWeight: 500,
      letterSpacing: '.14em',
      textTransform: 'uppercase',
      color: 'var(--text-muted)'
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 8,
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-lg)',
      fontWeight: 600,
      color: 'var(--text-strong)',
      lineHeight: 1.1
    }
  }, value), delta ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-2xs)',
      fontWeight: 600,
      color: col
    }
  }, down ? '▾' : '▴', " ", delta.replace(/^-/, '')) : null), data ? /*#__PURE__*/React.createElement(Spark, {
    data: data,
    color: color
  }) : null);
}
function UtilArea({
  series,
  width = 460,
  height = 130,
  max = 100,
  unit = '%',
  warn,
  xlabels = ['-60m', '-30m', 'now']
}) {
  const m = {
    t: 8,
    r: 36,
    b: 16,
    l: 6
  };
  const pw = width - m.l - m.r,
    ph = height - m.t - m.b;
  const colors = ['var(--accent)', 'var(--accent-2)', 'var(--info)'];
  const y = v => m.t + ph * (1 - Math.min(v, max) / max);
  const path = data => data.map((v, i) => `${(m.l + i / Math.max(1, data.length - 1) * pw).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 16,
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-2xs)',
      color: 'var(--text-dim)'
    }
  }, series.map((s, i) => /*#__PURE__*/React.createElement("span", {
    key: s.label,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: colors[i]
    }
  }), s.label, /*#__PURE__*/React.createElement("b", {
    style: {
      color: 'var(--text)'
    }
  }, s.data[s.data.length - 1], unit)))), /*#__PURE__*/React.createElement("svg", {
    width: width,
    height: height,
    viewBox: `0 0 ${width} ${height}`,
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 9
    }
  }, [0, 50, 100].map(g => /*#__PURE__*/React.createElement("g", {
    key: g
  }, /*#__PURE__*/React.createElement("line", {
    x1: m.l,
    x2: m.l + pw,
    y1: y(g * max / 100),
    y2: y(g * max / 100),
    stroke: "var(--border)",
    strokeWidth: "1"
  }), /*#__PURE__*/React.createElement("text", {
    x: m.l + pw + 5,
    y: y(g * max / 100) + 3,
    fill: "var(--text-faint)"
  }, Math.round(g * max / 100), unit))), warn != null ? /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("line", {
    x1: m.l,
    x2: m.l + pw,
    y1: y(warn),
    y2: y(warn),
    stroke: "var(--warn)",
    strokeWidth: "1",
    strokeDasharray: "4 4",
    opacity: "0.8"
  }), /*#__PURE__*/React.createElement("text", {
    x: m.l + pw + 5,
    y: y(warn) + 3,
    fill: "var(--warn)"
  }, warn, unit)) : null, series.map((s, i) => /*#__PURE__*/React.createElement("g", {
    key: s.label
  }, /*#__PURE__*/React.createElement("polygon", {
    points: `${m.l},${m.t + ph} ${path(s.data)} ${m.l + pw},${m.t + ph}`,
    fill: colors[i],
    opacity: "0.08"
  }), /*#__PURE__*/React.createElement("polyline", {
    points: path(s.data),
    fill: "none",
    stroke: colors[i],
    strokeWidth: "1.6",
    strokeLinejoin: "round"
  }))), xlabels.map((xl, i) => /*#__PURE__*/React.createElement("text", {
    key: i,
    y: height - 3,
    x: m.l + i / Math.max(1, xlabels.length - 1) * pw,
    fill: "var(--text-faint)",
    textAnchor: i === 0 ? 'start' : i === xlabels.length - 1 ? 'end' : 'middle'
  }, xl))));
}
Object.assign(window, {
  SeedChip,
  Meter,
  ActChip,
  WStepper,
  MiniNode,
  Fit,
  TYPE_ICON,
  KIND_TONE,
  PALETTE_HINT2,
  RUN_LINES2,
  W_PHASES,
  Spark,
  Trend,
  UtilArea
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console-v2/parts2.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console-v2/shell2.jsx
try { (() => {
/* Enclave Console v2 — app shell: topbar nav + views + operator's path. */

function WorkflowsView({
  threads,
  onOpenThread
}) {
  const E = window.ENCLAVE2.ENTITIES;
  React.useEffect(() => {
    window.refreshIcons();
  });
  const catTone = {
    security: 'accent',
    code: 'info',
    research: 'warm'
  };
  const wfThread = id => threads.find(t => t.kind === 'wf' && (t.name === 'pr review loop' ? id === 'pr-review' : t.name.startsWith('xsiam') && id === 'xsiam-normalize'));
  return /*#__PURE__*/React.createElement("div", {
    className: "page"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Workflows"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Formalized threads. Each one traces back to the conversation that proved it."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "git-merge"
  }, "Convert a thread")), /*#__PURE__*/React.createElement("div", {
    className: "cardgrid"
  }, E.workflows.map(w => {
    const t = wfThread(w.id);
    return /*#__PURE__*/React.createElement("div", {
      className: "ecard",
      key: w.id,
      style: {
        cursor: 'default'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "ehead"
    }, /*#__PURE__*/React.createElement(Pip, {
      status: "idle"
    }), /*#__PURE__*/React.createElement("span", {
      className: "eid"
    }, w.title), /*#__PURE__*/React.createElement(Badge, {
      tone: catTone[w.category] || 'accent',
      sq: true
    }, w.category)), /*#__PURE__*/React.createElement("div", {
      className: "emeta"
    }, w.meta), t ? /*#__PURE__*/React.createElement("div", {
      className: "emeta",
      style: {
        color: 'var(--accent)'
      }
    }, "born from thread: ", t.name) : null, /*#__PURE__*/React.createElement("div", {
      className: "efoot"
    }, /*#__PURE__*/React.createElement(Btn, {
      sm: true,
      icon: "play"
    }, "Run"), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), t ? /*#__PURE__*/React.createElement(Btn, {
      sm: true,
      icon: "workflow",
      onClick: () => onOpenThread(t.id, 'canvas')
    }, "Open canvas") : /*#__PURE__*/React.createElement(ActChip, {
      icon: "message-square",
      title: "No source thread \u2014 imported from YAML"
    }, "yaml import")));
  })));
}
function RunsView2({
  onOpenThread,
  onInspect,
  threads
}) {
  const D = window.ENCLAVE;
  const [open, setOpen] = React.useState(null);
  React.useEffect(() => {
    window.refreshIcons();
  });
  const barColor = s => s === 'success' ? 'var(--success)' : s === 'error' ? 'var(--danger)' : 'var(--info)';
  const TRACE = ['analyze', 'normalize', 'validate', 'emit'];
  return /*#__PURE__*/React.createElement("div", {
    className: "page"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Runs"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Every execution \u2014 streamed, checkpointed, resumable. Drill into any step."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), /*#__PURE__*/React.createElement(Btn, {
    icon: "refresh-cw",
    sm: true
  }, "Refresh")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 32,
      alignItems: 'flex-start',
      background: 'var(--surface-card)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-md)',
      padding: '16px 20px',
      marginBottom: 18,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(UtilArea, {
    series: [{
      label: 'cpu',
      data: window.ENCLAVE2.UTIL.cpu
    }, {
      label: 'mem',
      data: window.ENCLAVE2.UTIL.mem
    }],
    warn: 85
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      alignSelf: 'stretch',
      background: 'var(--border)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 28,
      flexWrap: 'wrap',
      paddingTop: 4
    }
  }, /*#__PURE__*/React.createElement(Trend, {
    label: "throughput",
    value: "47 tok/s",
    delta: "+12%",
    data: window.ENCLAVE2.UTIL.tps
  }), /*#__PURE__*/React.createElement(Trend, {
    label: "avg run",
    value: "0:41",
    delta: "-9s",
    good: false,
    data: window.ENCLAVE2.UTIL.dur,
    color: "var(--accent-2)"
  }), /*#__PURE__*/React.createElement(Trend, {
    label: "runs / day",
    value: "11",
    delta: "+3",
    data: window.ENCLAVE2.UTIL.runs,
    color: "var(--info)"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "runs-list"
  }, D.RUNS.map(r => /*#__PURE__*/React.createElement(React.Fragment, {
    key: r.id
  }, /*#__PURE__*/React.createElement("div", {
    className: "run-row",
    onClick: () => setOpen(open === r.id ? null : r.id)
  }, /*#__PURE__*/React.createElement(Pip, {
    status: r.state
  }), /*#__PURE__*/React.createElement("div", {
    className: "rmain"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rwf"
  }, r.wf), /*#__PURE__*/React.createElement("div", {
    className: "rid"
  }, r.id, r.err ? ' · ' + r.err : '')), /*#__PURE__*/React.createElement("div", {
    className: "run-bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.round(r.step / r.total * 100) + '%',
      background: barColor(r.state)
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "rmeta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "steps"), r.step, "/", r.total), /*#__PURE__*/React.createElement("div", {
    className: "rmeta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, r.when), r.dur, " \xB7 ", r.tps, " t/s")), open === r.id ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      padding: '4px 16px 12px 42px',
      animation: 'ds-fade-in var(--t-med) var(--ease-out)'
    }
  }, TRACE.slice(0, r.total).map((s, i) => {
    const st = i < r.step ? 'success' : r.state === 'error' && i === r.step - 1 ? 'error' : 'idle';
    return /*#__PURE__*/React.createElement("div", {
      key: s,
      className: "userow",
      style: {
        background: 'transparent'
      }
    }, /*#__PURE__*/React.createElement(Pip, {
      status: st === 'idle' ? 'idle' : st
    }), /*#__PURE__*/React.createElement("span", {
      className: "n"
    }, s), /*#__PURE__*/React.createElement("span", null, st === 'success' ? RUN_LINES2[s] || 'complete' : st === 'error' ? r.err : 'not reached'));
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      paddingTop: 2
    }
  }, /*#__PURE__*/React.createElement(ActChip, {
    icon: "activity",
    acc: true,
    onClick: () => onInspect(r)
  }, "inspect on canvas"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "message-square",
    onClick: () => onOpenThread((threads.find(t => t.kind === 'wf') || threads[0]).id, 'chat')
  }, "open source thread"), /*#__PURE__*/React.createElement(ActChip, {
    icon: "rotate-ccw"
  }, "resume from checkpoint"))) : null))));
}
function PathPop({
  onClose,
  onGo
}) {
  const PATH = window.ENCLAVE2.PATH;
  const done = PATH.filter(p => p.done).length;
  return /*#__PURE__*/React.createElement("div", {
    className: "pathpop",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(MLabel, {
    bare: true
  }, "Operator's path \u2014 ", done, "/", PATH.length), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "x",
    bare: true,
    label: "Close",
    onClick: onClose
  })), PATH.map((p, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: `pathrow ${p.done ? 'done' : ''} ${p.hot ? 'hot' : ''} ${!p.done && !p.hot ? 'dim' : ''}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, p.done ? '✓' : i + 1), /*#__PURE__*/React.createElement("span", null, p.t), p.hot ? /*#__PURE__*/React.createElement(ActChip, {
    acc: true,
    onClick: onGo
  }, "go \u2192") : null)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--text-2xs)',
      color: 'var(--text-faint)',
      lineHeight: 1.5
    }
  }, "The console surfaces each rung when you're ready for it \u2014 never before."));
}
const NAV2 = [{
  id: 'chats',
  icon: 'message-square',
  label: 'Chats'
}, {
  id: 'workflows',
  icon: 'workflow',
  label: 'Workflows'
}, {
  id: 'library',
  icon: 'library',
  label: 'Library'
}, {
  id: 'runs',
  icon: 'circle-play',
  label: 'Runs'
}];
function App2() {
  const D2 = window.ENCLAVE2;
  const [threads, setThreads] = React.useState(() => D2.THREADS.map(t => ({
    ...t,
    msgs: t.msgs.map(m => ({
      ...m
    })),
    pins: t.pins.map(p => ({
      ...p
    }))
  })));
  const [activeId, setActiveId] = React.useState('t1');
  const [view, setView] = React.useState('chats');
  const [pathOpen, setPathOpen] = React.useState(false);
  React.useEffect(() => {
    window.refreshIcons();
  });
  function updateThread(id, fn) {
    setThreads(ts => ts.map(t => t.id === id ? typeof fn === 'function' ? fn(t) : {
      ...t,
      ...fn
    } : t));
  }
  function createThread(partial) {
    const id = 't' + Date.now();
    setThreads(ts => [{
      id,
      kind: 'chat',
      converted: false,
      mode: 'chat',
      pins: [],
      nodes: null,
      edges: null,
      msgs: [],
      ...partial
    }, ...ts]);
    setActiveId(id);
    setView('chats');
    return id;
  }
  function seedChatWith(e) {
    const isModel = e.type === 'model';
    createThread({
      name: `test: ${e.id}`,
      kind: 'chat',
      seed: isModel ? {
        role: e.role || 'general',
        model: e.id,
        ctx: null
      } : {
        role: e.role || 'reasoning',
        model: e.model || 'dolphin-mixtral',
        ctx: null,
        agent: e.id
      },
      msgs: [{
        who: 'sys',
        text: `Seeded from the Library — ${e.type}: ${e.id}. Say something to test it.`
      }]
    });
  }
  function research() {
    createThread({
      name: 'context research',
      kind: 'chat',
      seed: {
        role: 'reasoning',
        model: 'dolphin-mixtral',
        ctx: null,
        plugin: 'web-search'
      },
      msgs: [{
        who: 'sys',
        text: 'Seeded with web-search — findings can be added to a context bundle.'
      }]
    });
  }
  function openThread(id, mode) {
    updateThread(id, t => ({
      ...t,
      mode: mode || t.mode
    }));
    setActiveId(id);
    setView('chats');
  }
  function inspectRun(r) {
    const t = threads.find(x => x.kind === 'wf') || threads[0];
    updateThread(t.id, x => ({
      ...x,
      mode: 'canvas',
      lensRun: ['run-7f3a', 'run-7e91', 'run-7e44'].includes(r.id) ? r.id : 'run-7e44'
    }));
    setActiveId(t.id);
    setView('chats');
  }
  const activeThread = threads.find(t => t.id === activeId) || threads[0];
  const pathDone = D2.PATH.filter(p => p.done).length;
  return /*#__PURE__*/React.createElement("div", {
    className: "encl2-app",
    onClick: () => setPathOpen(false)
  }, /*#__PURE__*/React.createElement("div", {
    className: "topbar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "topbar-logo"
  }, /*#__PURE__*/React.createElement(Logo, {
    size: 30
  })), /*#__PURE__*/React.createElement("div", {
    className: "navtabs"
  }, NAV2.map(n => /*#__PURE__*/React.createElement("div", {
    key: n.id,
    className: `navtab ${view === n.id ? 'active' : ''}`,
    onClick: () => setView(n.id)
  }, /*#__PURE__*/React.createElement(Ico, {
    n: n.icon
  }), n.label, n.id === 'chats' ? /*#__PURE__*/React.createElement("span", {
    className: "cnt"
  }, threads.length) : null))), /*#__PURE__*/React.createElement("div", {
    className: "proj-pick"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "folder"
  }), /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "Q4 Detection Playbooks"), /*#__PURE__*/React.createElement("span", {
    className: "car"
  }, "\u25BE")), /*#__PURE__*/React.createElement("div", {
    className: "topbar-spacer"
  }), /*#__PURE__*/React.createElement("div", {
    className: "sysstrip"
  }, /*#__PURE__*/React.createElement("div", {
    className: "health"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: "online",
    live: true
  }), "API"), /*#__PURE__*/React.createElement("div", {
    className: "health"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: "online",
    live: true
  }), "Ollama"), /*#__PURE__*/React.createElement("span", {
    className: "sep"
  }), /*#__PURE__*/React.createElement(Metric, {
    k: "CPU",
    v: "34%",
    percent: 34
  }), /*#__PURE__*/React.createElement(Metric, {
    k: "MEM",
    v: "18 / 64",
    percent: 28
  }), /*#__PURE__*/React.createElement("span", {
    className: "sep"
  }), /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "signpost",
    onClick: e => {
      e.stopPropagation();
      setPathOpen(o => !o);
    }
  }, "Path ", pathDone, "/5"), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "command",
    bare: true,
    label: "Shortcuts"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "view",
    style: {
      position: 'relative'
    }
  }, view === 'chats' ? activeThread.mode === 'canvas' ? /*#__PURE__*/React.createElement(CanvasMode, {
    thread: activeThread,
    updateThread: updateThread
  }) : /*#__PURE__*/React.createElement(ChatHome, {
    threads: threads,
    activeId: activeId,
    setActiveId: setActiveId,
    updateThread: updateThread,
    createThread: createThread
  }) : null, view === 'workflows' ? /*#__PURE__*/React.createElement(WorkflowsView, {
    threads: threads,
    onOpenThread: openThread
  }) : null, view === 'library' ? /*#__PURE__*/React.createElement(Library2, {
    onSeedChat: seedChatWith,
    onResearch: research
  }) : null, view === 'runs' ? /*#__PURE__*/React.createElement(RunsView2, {
    threads: threads,
    onOpenThread: openThread,
    onInspect: inspectRun
  }) : null), pathOpen ? /*#__PURE__*/React.createElement(PathPop, {
    onClose: () => setPathOpen(false),
    onGo: () => {
      setPathOpen(false);
      openThread('t1', 'chat');
    }
  }) : null);
}
window.App2 = App2;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console-v2/shell2.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console/Composer.jsx
try { (() => {
/* Enclave Console — Composer view (the workflow-first home). */
function Composer({
  sys
}) {
  const D = window.ENCLAVE;
  const [nodes, setNodes] = React.useState(D.WORKFLOW.nodes.map(n => ({
    ...n
  })));
  const [edges, setEdges] = React.useState(D.WORKFLOW.edges.map(e => e.slice()));
  const [selId, setSelId] = React.useState('n2');
  const [tab, setTab] = React.useState('roles');
  const [zoom, setZoom] = React.useState(1);
  const [run, setRun] = React.useState({
    active: false,
    done: false,
    idx: -1,
    status: {}
  });
  const [dockOpen, setDockOpen] = React.useState(true);
  const [msgs, setMsgs] = React.useState([{
    who: 'sys',
    text: 'Composer ready. The canvas above is the design surface — this chat runs the agents you build.'
  }]);
  const timers = React.useRef([]);
  React.useEffect(() => {
    window.refreshIcons();
  });
  React.useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const order = ['n1', 'n2', 'n3', 'n4'].filter(id => nodes.some(n => n.id === id));
  const sel = nodes.find(n => n.id === selId);
  const paletteItems = {
    roles: D.ROLES,
    agents: D.AGENTS,
    skills: D.SKILLS,
    plugins: D.PLUGINS,
    mcps: D.MCPS
  }[tab] || D.ROLES;
  function addNode(item) {
    const isRole = ['reasoning', 'coding', 'fast', 'general', 'uncensored'].includes(item.kind);
    const role = isRole ? item.kind : item.role || 'general';
    const id = 'n' + (nodes.length + 1 + Math.floor(Math.random() * 100));
    const maxX = Math.max(...nodes.map(n => n.x), 0);
    const node = {
      id,
      title: item.title,
      role,
      model: item.model || (D.MODELS.find(m => m.role === role) || {}).id || 'auto',
      x: maxX + 30,
      y: 150,
      prompt: item.desc || 'Describe what this step should do.'
    };
    setNodes(ns => [...ns, node]);
    const last = order[order.length - 1];
    if (last) setEdges(es => [...es, [last, id]]);
    setSelId(id);
  }
  function startRun() {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setRun({
      active: true,
      done: false,
      idx: 0,
      status: {}
    });
    setMsgs(m => [...m, {
      who: 'user',
      text: 'Run the workflow on the latest CrowdStrike export.'
    }]);
    let t = 0;
    order.forEach((id, i) => {
      const node = nodes.find(n => n.id === id);
      timers.current.push(setTimeout(() => {
        setRun(r => ({
          ...r,
          idx: i,
          status: {
            ...r.status,
            [id]: 'running'
          }
        }));
      }, t += 200));
      timers.current.push(setTimeout(() => {
        setRun(r => ({
          ...r,
          status: {
            ...r.status,
            [id]: 'success'
          }
        }));
        setMsgs(m => [...m, {
          who: 'bot',
          text: `▸ ${node.title} (${node.model}) — ${RUN_LINES[node.title] || 'step complete.'}`
        }]);
      }, t += 900));
    });
    timers.current.push(setTimeout(() => {
      setRun(r => ({
        ...r,
        active: false,
        done: true,
        idx: order.length
      }));
      setMsgs(m => [...m, {
        who: 'bot',
        text: '✓ Workflow complete — 1,284 events normalized, 0 dropped. Emitted to workspace.emit.batch.'
      }]);
    }, t += 300));
  }
  const runState = run.active ? 'running' : run.done ? 'success' : 'idle';
  const curNode = order[run.idx] ? nodes.find(n => n.id === order[run.idx]) : null;
  const doneCount = Object.values(run.status).filter(s => s === 'success').length;
  return /*#__PURE__*/React.createElement("div", {
    className: "composer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "wf-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "wf-id"
  }, D.WORKFLOW.id), /*#__PURE__*/React.createElement("div", {
    className: "wf-name"
  }, D.WORKFLOW.name)), /*#__PURE__*/React.createElement("div", {
    className: "wf-desc"
  }, D.WORKFLOW.desc), /*#__PURE__*/React.createElement("div", {
    className: "wf-header-spacer"
  }), run.active || run.done ? /*#__PURE__*/React.createElement("div", {
    className: "wf-runchip",
    style: {
      '--rc': run.active ? 'var(--info)' : 'var(--success)'
    }
  }, /*#__PURE__*/React.createElement(Pip, {
    status: run.active ? 'running' : 'success',
    live: run.active
  }), /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, run.active ? 'running' : 'complete'), curNode && run.active ? /*#__PURE__*/React.createElement("span", {
    className: "cur"
  }, curNode.title) : null, /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.round(doneCount / order.length * 100) + '%'
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "cnt"
  }, doneCount, "/", order.length)) : null, /*#__PURE__*/React.createElement(Btn, {
    icon: "folder-open",
    sm: true
  }, "Load"), /*#__PURE__*/React.createElement(Btn, {
    icon: "file-down",
    sm: true
  }, "Export YAML"), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "play",
    onClick: startRun
  }, "Run")), /*#__PURE__*/React.createElement("div", {
    className: "composer-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "palette"
  }, /*#__PURE__*/React.createElement("div", {
    className: "palette-tabs"
  }, ['roles', 'agents', 'skills', 'plugins', 'mcps'].map(t => /*#__PURE__*/React.createElement("div", {
    key: t,
    className: `palette-tab ${tab === t ? 'active' : ''}`,
    onClick: () => setTab(t)
  }, t))), /*#__PURE__*/React.createElement("div", {
    className: "palette-hint"
  }, PALETTE_HINT[tab]), /*#__PURE__*/React.createElement("div", {
    className: "palette-list"
  }, paletteItems.map((it, i) => /*#__PURE__*/React.createElement(RoleChip, {
    key: i,
    item: it,
    onAdd: addNode
  })))), /*#__PURE__*/React.createElement("div", {
    className: "canvas-wrap",
    onClick: () => setSelId(null)
  }, /*#__PURE__*/React.createElement("div", {
    className: "canvas-ctrls",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement(IconBtn, {
    icon: "minus",
    label: "Zoom out",
    onClick: () => setZoom(z => Math.max(0.6, +(z - 0.1).toFixed(2)))
  }), /*#__PURE__*/React.createElement("span", {
    className: "canvas-zoom"
  }, Math.round(zoom * 100), "%"), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "plus",
    label: "Zoom in",
    onClick: () => setZoom(z => Math.min(1.4, +(z + 0.1).toFixed(2)))
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "rotate-ccw",
    label: "Reset",
    onClick: () => setZoom(1)
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "maximize",
    label: "Fullscreen"
  })), /*#__PURE__*/React.createElement("div", {
    className: "canvas-stage",
    style: {
      transform: `scale(${zoom})`
    }
  }, /*#__PURE__*/React.createElement("svg", {
    className: "canvas-edges"
  }, edges.map(([a, b], i) => {
    const na = nodes.find(n => n.id === a),
      nb = nodes.find(n => n.id === b);
    if (!na || !nb) return null;
    const flowing = run.active && run.status[a] === 'success' && run.status[b] === 'running';
    const done = run.status[a] === 'success' && run.status[b] === 'success';
    return /*#__PURE__*/React.createElement("path", {
      key: i,
      d: edgePath(na, nb),
      className: flowing ? 'flow' : done ? 'done' : ''
    });
  })), nodes.map(n => {
    const inLinked = edges.some(e => e[1] === n.id);
    const outLinked = edges.some(e => e[0] === n.id);
    return /*#__PURE__*/React.createElement(Node, {
      key: n.id,
      node: n,
      selected: selId === n.id,
      status: run.status[n.id],
      inLinked: inLinked,
      outLinked: outLinked,
      hideOut: !outLinked && n.id === 'n4',
      onSelect: setSelId
    });
  }))), /*#__PURE__*/React.createElement("div", {
    className: "inspector"
  }, sel ? /*#__PURE__*/React.createElement(StepConfig, {
    node: sel,
    models: D.MODELS,
    onChange: (k, v) => setNodes(ns => ns.map(n => n.id === sel.id ? {
      ...n,
      [k]: v
    } : n))
  }) : /*#__PURE__*/React.createElement(WorkflowMeta, {
    wf: D.WORKFLOW,
    count: nodes.length
  }))), /*#__PURE__*/React.createElement("div", {
    className: `dock ${dockOpen ? '' : 'collapsed'}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "dock-head"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Agent Chat"), /*#__PURE__*/React.createElement("span", {
    className: "sub"
  }, "workflow interaction surface"), /*#__PURE__*/React.createElement("div", {
    className: "dock-head-spacer"
  }), /*#__PURE__*/React.createElement("select", {
    className: "ctl",
    style: {
      width: 160,
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-xs)',
      background: 'var(--surface-card)',
      border: '1px solid var(--border)',
      color: 'var(--text-dim)',
      borderRadius: 'var(--radius-sm)',
      padding: '5px 8px'
    },
    defaultValue: "xsiam-analyst"
  }, /*#__PURE__*/React.createElement("option", null, "\u2014 no agent \u2014"), /*#__PURE__*/React.createElement("option", null, "xsiam-analyst"), /*#__PURE__*/React.createElement("option", null, "normalizer")), /*#__PURE__*/React.createElement(IconBtn, {
    icon: dockOpen ? 'chevron-down' : 'chevron-up',
    bare: true,
    label: "Toggle dock",
    onClick: () => setDockOpen(o => !o)
  })), /*#__PURE__*/React.createElement("div", {
    className: "dock-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dock-msgs",
    ref: el => {
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, msgs.map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: `msg ${m.who}`
  }, m.who !== 'sys' ? /*#__PURE__*/React.createElement("span", {
    className: "who"
  }, m.who === 'user' ? 'you' : 'agent') : null, /*#__PURE__*/React.createElement("span", {
    className: "bubble"
  }, m.text)))), /*#__PURE__*/React.createElement("div", {
    className: "dock-input"
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: "Message the workflow agents\u2026",
    onKeyDown: e => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        const v = e.target.value;
        e.target.value = '';
        setMsgs(m => [...m, {
          who: 'user',
          text: v
        }, {
          who: 'bot',
          text: 'Queued against the active agent. (demo)'
        }]);
      }
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "send"
  }, "Send")))));
}
const PALETTE_HINT = {
  roles: 'Drag a role onto the canvas to add a step. (Click to add here.)',
  agents: 'Agents spawn a step pre-configured with role, model, and system prompt.',
  skills: 'Skills auto-attach to steps when their triggers match. Drag to pin.',
  plugins: 'Plugin tools become callable from any step.',
  mcps: 'MCP servers expose external tools to steps.'
};
const RUN_LINES = {
  analyze: 'detected CrowdStrike Falcon schema, 42 fields.',
  normalize: 'mapped 42 → 38 XSIAM fields, 4 dropped as vendor-specific.',
  validate: 'all required keys present (_time, _vendor, event_id).',
  emit: 'rendered NDJSON batch.'
};
function StepConfig({
  node,
  models,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Step Config"), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Step ID"), /*#__PURE__*/React.createElement("input", {
    className: "mono",
    value: node.id,
    readOnly: true
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Title"), /*#__PURE__*/React.createElement("input", {
    value: node.title,
    onChange: e => onChange('title', e.target.value)
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Role"), /*#__PURE__*/React.createElement("select", {
    value: node.role,
    onChange: e => onChange('role', e.target.value)
  }, ['reasoning', 'coding', 'fast', 'general', 'uncensored'].map(r => /*#__PURE__*/React.createElement("option", {
    key: r
  }, r)))), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Model"), /*#__PURE__*/React.createElement("select", {
    className: "mono",
    value: node.model,
    onChange: e => onChange('model', e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "auto"
  }, "auto (resolve by role)"), models.map(m => /*#__PURE__*/React.createElement("option", {
    key: m.id,
    value: m.id
  }, m.id))))), /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Prompt"), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("textarea", {
    value: node.prompt,
    onChange: e => onChange('prompt', e.target.value)
  }))), /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Attached"), /*#__PURE__*/React.createElement("div", {
    className: "attach-row"
  }, /*#__PURE__*/React.createElement(Badge, {
    tone: "accent",
    sq: true
  }, "cite-sources"), /*#__PURE__*/React.createElement(Badge, {
    tone: "info",
    sq: true
  }, "web-search"), /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "plus"
  }, "attach"))));
}
function WorkflowMeta({
  wf,
  count
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement(MLabel, null, "Workflow"), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "ID"), /*#__PURE__*/React.createElement("input", {
    className: "mono",
    defaultValue: wf.id
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Name"), /*#__PURE__*/React.createElement("input", {
    defaultValue: wf.name
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Default Role"), /*#__PURE__*/React.createElement("select", {
    defaultValue: wf.role
  }, ['reasoning', 'coding', 'fast', 'general', 'uncensored'].map(r => /*#__PURE__*/React.createElement("option", {
    key: r
  }, r)))), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Category"), /*#__PURE__*/React.createElement("select", {
    defaultValue: wf.category
  }, ['general', 'security', 'devops', 'data', 'code', 'research'].map(r => /*#__PURE__*/React.createElement("option", {
    key: r
  }, r)))), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Description"), /*#__PURE__*/React.createElement("textarea", {
    defaultValue: wf.desc
  }))), /*#__PURE__*/React.createElement("div", {
    className: "insp-sec"
  }, /*#__PURE__*/React.createElement("div", {
    className: "insp-empty"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "mouse-pointer-click"
  }), /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, count, " steps \xB7 select a node to edit its config"))));
}
window.Composer = Composer;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console/Composer.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console/data.js
try { (() => {
/* Enclave Console — mock data for the workflow-first UI kit.
   Plain JS; sets window.ENCLAVE. No backend; everything is fake. */
(function () {
  const MODELS = [{
    id: 'dolphin-mixtral',
    size: '26 GB',
    quant: 'Q4_K_M',
    tps: 12,
    role: 'reasoning',
    loaded: true
  }, {
    id: 'qwen2.5-coder',
    size: '4.7 GB',
    quant: 'Q4_K_M',
    tps: 47,
    role: 'coding',
    loaded: true
  }, {
    id: 'llama3.2:3b',
    size: '2.0 GB',
    quant: 'Q4_K_M',
    tps: 92,
    role: 'fast',
    loaded: true
  }, {
    id: 'nous-hermes2',
    size: '26 GB',
    quant: 'Q5_K_M',
    tps: 11,
    role: 'general',
    loaded: false
  }, {
    id: 'yi-34b',
    size: '20 GB',
    quant: 'Q3_K_M',
    tps: 14,
    role: 'reasoning',
    loaded: false
  }, {
    id: 'wizardlm-uncensored',
    size: '7.4 GB',
    quant: 'Q4_K_M',
    tps: 38,
    role: 'uncensored',
    loaded: false
  }];
  const ROLES = [{
    kind: 'reasoning',
    title: 'reasoning',
    desc: 'Deep analysis · 34B class',
    icon: 'brain'
  }, {
    kind: 'coding',
    title: 'coding',
    desc: 'Code gen + review',
    icon: 'code'
  }, {
    kind: 'fast',
    title: 'fast',
    desc: 'Low-latency triage',
    icon: 'zap'
  }, {
    kind: 'general',
    title: 'general',
    desc: 'Balanced default',
    icon: 'circle'
  }, {
    kind: 'uncensored',
    title: 'uncensored',
    desc: 'Unfiltered persona',
    icon: 'shield-off'
  }];
  const AGENTS = [{
    kind: 'agent',
    title: 'xsiam-analyst',
    desc: 'Security triage persona',
    icon: 'bot',
    role: 'reasoning',
    model: 'dolphin-mixtral'
  }, {
    kind: 'agent',
    title: 'normalizer',
    desc: 'Maps logs to data model',
    icon: 'bot',
    role: 'coding',
    model: 'qwen2.5-coder'
  }, {
    kind: 'agent',
    title: 'red-teamer',
    desc: 'Adversarial probing',
    icon: 'bot',
    role: 'uncensored',
    model: 'wizardlm-uncensored'
  }];
  const SKILLS = [{
    kind: 'skill',
    title: 'concise-writer',
    desc: 'Tightens prose on trigger',
    icon: 'scissors'
  }, {
    kind: 'skill',
    title: 'cite-sources',
    desc: 'Appends evidence refs',
    icon: 'quote'
  }, {
    kind: 'skill',
    title: 'json-strict',
    desc: 'Forces valid JSON out',
    icon: 'braces'
  }];
  const PLUGINS = [{
    kind: 'plugin',
    title: 'web-search',
    desc: 'DuckDuckGo / SearXNG',
    icon: 'globe'
  }, {
    kind: 'plugin',
    title: 'python-exec',
    desc: 'Sandboxed code run',
    icon: 'terminal'
  }];
  const MCPS = [{
    kind: 'mcp',
    title: 'filesystem',
    desc: 'read / write tools',
    icon: 'folder'
  }, {
    kind: 'mcp',
    title: 'postgres',
    desc: 'query the warehouse',
    icon: 'database'
  }];

  // Sample workflow: a DAG laid out on the canvas (x,y in canvas px).
  const WORKFLOW = {
    id: 'xsiam-normalize',
    name: 'XSIAM Log Normalization',
    category: 'security',
    role: 'general',
    desc: 'Ingest raw vendor logs, map to the XSIAM data model, validate, and emit normalized events.',
    nodes: [{
      id: 'n1',
      title: 'analyze',
      role: 'reasoning',
      model: 'dolphin-mixtral',
      x: 40,
      y: 150,
      prompt: 'Identify the log schema and vendor. Summarize fields present.'
    }, {
      id: 'n2',
      title: 'normalize',
      role: 'coding',
      model: 'qwen2.5-coder',
      x: 300,
      y: 80,
      prompt: 'Map each source field to the XSIAM data model. Output a field map.'
    }, {
      id: 'n3',
      title: 'validate',
      role: 'fast',
      model: 'llama3.2:3b',
      x: 300,
      y: 250,
      prompt: 'Check the field map for required keys. Flag gaps.'
    }, {
      id: 'n4',
      title: 'emit',
      role: 'general',
      model: 'nous-hermes2',
      x: 560,
      y: 165,
      prompt: 'Render the normalized event batch as NDJSON.'
    }],
    edges: [['n1', 'n2'], ['n1', 'n3'], ['n2', 'n4'], ['n3', 'n4']]
  };
  const RUNS = [{
    id: 'run-7f3a',
    wf: 'XSIAM Log Normalization',
    state: 'success',
    step: 4,
    total: 4,
    when: '2m ago',
    dur: '0:41',
    tps: 38
  }, {
    id: 'run-7e91',
    wf: 'Threat Intel Enrichment',
    state: 'success',
    step: 6,
    total: 6,
    when: '18m ago',
    dur: '1:12',
    tps: 41
  }, {
    id: 'run-7e44',
    wf: 'XSIAM Log Normalization',
    state: 'error',
    step: 3,
    total: 4,
    when: '1h ago',
    dur: '0:22',
    tps: 35,
    err: 'validate: missing required key `_time`'
  }, {
    id: 'run-7d10',
    wf: 'PR Review Pipeline',
    state: 'success',
    step: 3,
    total: 3,
    when: '3h ago',
    dur: '0:55',
    tps: 47
  }, {
    id: 'run-7c88',
    wf: 'Detection Rule Drafting',
    state: 'success',
    step: 5,
    total: 5,
    when: 'yesterday',
    dur: '2:03',
    tps: 12
  }];
  const WORKFLOWS = [{
    id: 'xsiam-normalize',
    name: 'XSIAM Log Normalization',
    category: 'security',
    steps: 4,
    runs: 31,
    updated: '2m ago'
  }, {
    id: 'ti-enrich',
    name: 'Threat Intel Enrichment',
    category: 'security',
    steps: 6,
    runs: 19,
    updated: '18m ago'
  }, {
    id: 'pr-review',
    name: 'PR Review Pipeline',
    category: 'code',
    steps: 3,
    runs: 64,
    updated: '3h ago'
  }, {
    id: 'detect-draft',
    name: 'Detection Rule Drafting',
    category: 'security',
    steps: 5,
    runs: 8,
    updated: 'yesterday'
  }, {
    id: 'doc-synth',
    name: 'Doc Synthesis',
    category: 'research',
    steps: 4,
    runs: 12,
    updated: '2d ago'
  }, {
    id: 'incident-sum',
    name: 'Incident Summarizer',
    category: 'security',
    steps: 2,
    runs: 27,
    updated: '4d ago'
  }];
  window.ENCLAVE = {
    MODELS,
    ROLES,
    AGENTS,
    SKILLS,
    PLUGINS,
    MCPS,
    WORKFLOW,
    RUNS,
    WORKFLOWS
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console/data.js", error: String((e && e.message) || e) }); }

// ui_kits/console/primitives.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Enclave Console — cosmetic primitives (self-contained; window-exported). */
/* Ico is React-safe: the lucide SVG lives inside a wrapper span whose children
   React never reconciles, so lucide.createIcons() mutation can't crash React. */
const Ico = ({
  n,
  style,
  ...p
}) => {
  const ref = React.useRef(null);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = '<i data-lucide="' + n + '"></i>';
    if (window.lucide) window.lucide.createIcons();
    const svg = el.querySelector('svg');
    if (svg && style && style.width) {
      svg.setAttribute('width', parseInt(style.width, 10));
      svg.setAttribute('height', parseInt(style.height || style.width, 10));
    }
  }, [n]);
  return /*#__PURE__*/React.createElement("span", _extends({
    ref: ref,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      ...style
    }
  }, p));
};
function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}
function Btn({
  variant,
  sm,
  icon,
  children,
  ...p
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    className: `btn ${variant || ''} ${sm ? 'sm' : ''}`
  }, p), icon ? /*#__PURE__*/React.createElement(Ico, {
    n: icon
  }) : null, children);
}
function IconBtn({
  icon,
  active,
  bare,
  label,
  ...p
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    className: `iconbtn ${active ? 'active' : ''} ${bare ? 'bare' : ''}`,
    title: label,
    "aria-label": label
  }, p), typeof icon === 'string' ? /*#__PURE__*/React.createElement(Ico, {
    n: icon
  }) : icon);
}
function Badge({
  tone,
  dot,
  sq,
  children
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: `badge ${tone || ''} ${sq ? 'sq' : ''}`
  }, dot ? /*#__PURE__*/React.createElement("span", {
    className: "d"
  }) : null, children);
}
function Pip({
  status,
  live
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: `pip ${status || 'idle'} ${live ? 'live' : ''}`
  });
}
function MLabel({
  children,
  bare
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: `mlabel ${bare ? 'bare' : ''}`
  }, children);
}
function Metric({
  k,
  v,
  percent,
  color
}) {
  const c = color || (percent == null ? 'var(--text)' : percent >= 85 ? 'var(--danger)' : percent >= 65 ? 'var(--warn)' : 'var(--accent)');
  return /*#__PURE__*/React.createElement("div", {
    className: "metric",
    style: {
      '--mc': c
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, k), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, v), percent != null ? /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.min(100, percent) + '%'
    }
  })) : null);
}
function Logo({
  size = 40
}) {
  return /*#__PURE__*/React.createElement("img", {
    src: "../../assets/logo/enclave-mark-teal.svg",
    width: size,
    height: size,
    alt: "Enclave"
  });
}
function RoleChip({
  item,
  onAdd
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: `rolechip tint-${item.kind}`,
    draggable: true,
    onClick: () => onAdd && onAdd(item),
    title: "Click to add to canvas"
  }, /*#__PURE__*/React.createElement("span", {
    className: "mk"
  }), item.icon ? /*#__PURE__*/React.createElement("span", {
    className: "ic"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: item.icon
  })) : null, /*#__PURE__*/React.createElement("span", {
    className: "tx"
  }, /*#__PURE__*/React.createElement("span", {
    className: "tt"
  }, item.title), /*#__PURE__*/React.createElement("span", {
    className: "dd"
  }, item.desc)), /*#__PURE__*/React.createElement("span", {
    className: "gp"
  }, "\u22EE\u22EE"));
}
const ROLE_STATUS_GLYPH = {
  idle: '',
  running: '',
  success: '',
  error: ''
};
function Node({
  node,
  selected,
  status,
  inLinked,
  outLinked,
  onSelect,
  hideOut
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: `node nr-${node.role} ${selected ? 'selected' : ''} ${status || ''}`,
    style: {
      left: node.x,
      top: node.y
    },
    onClick: e => {
      e.stopPropagation();
      onSelect(node.id);
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule"
  }), /*#__PURE__*/React.createElement("span", {
    className: `port in ${inLinked ? 'linked' : ''}`
  }), !hideOut ? /*#__PURE__*/React.createElement("span", {
    className: `port out ${outLinked ? 'linked' : ''}`
  }) : null, /*#__PURE__*/React.createElement("div", {
    className: "nbody"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ntop"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nrole"
  }, node.role), /*#__PURE__*/React.createElement("span", {
    className: "nstat"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: status === 'running' ? 'running' : status === 'success' ? 'success' : status === 'error' ? 'error' : 'idle',
    live: status === 'running'
  }))), /*#__PURE__*/React.createElement("div", {
    className: "ntitle"
  }, node.title), /*#__PURE__*/React.createElement("div", {
    className: "nmeta"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "box"
  }), /*#__PURE__*/React.createElement("span", {
    className: "mdl"
  }, node.model))));
}

/* Cubic bezier edge between two node boxes (right port -> left port). */
function edgePath(a, b, W = 188, H = 78) {
  const x1 = a.x + W,
    y1 = a.y + H / 2;
  const x2 = b.x,
    y2 = b.y + H / 2;
  const dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}
Object.assign(window, {
  Ico,
  refreshIcons,
  Btn,
  IconBtn,
  Badge,
  Pip,
  MLabel,
  Metric,
  Logo,
  RoleChip,
  Node,
  edgePath
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console/primitives.jsx", error: String((e && e.message) || e) }); }

// ui_kits/console/views.jsx
try { (() => {
/* Enclave Console — secondary views + app shell. */

function RunsView() {
  const D = window.ENCLAVE;
  React.useEffect(() => {
    window.refreshIcons();
  });
  const barColor = s => s === 'success' ? 'var(--success)' : s === 'error' ? 'var(--danger)' : 'var(--info)';
  return /*#__PURE__*/React.createElement("div", {
    className: "page"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Runs"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Every workflow execution \u2014 streamed, checkpointed, resumable."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), /*#__PURE__*/React.createElement(Btn, {
    icon: "refresh-cw",
    sm: true
  }, "Refresh")), /*#__PURE__*/React.createElement("div", {
    className: "toolbar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "search"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "search"
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Filter runs\u2026"
  })), /*#__PURE__*/React.createElement(Btn, {
    sm: true
  }, "All states"), /*#__PURE__*/React.createElement(Btn, {
    sm: true
  }, "Last 24h")), /*#__PURE__*/React.createElement("div", {
    className: "runs-list"
  }, D.RUNS.map(r => /*#__PURE__*/React.createElement("div", {
    className: "run-row",
    key: r.id
  }, /*#__PURE__*/React.createElement(Pip, {
    status: r.state,
    live: false
  }), /*#__PURE__*/React.createElement("div", {
    className: "rmain"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rwf"
  }, r.wf), /*#__PURE__*/React.createElement("div", {
    className: "rid"
  }, r.id, r.err ? ' · ' + r.err : '')), /*#__PURE__*/React.createElement("div", {
    className: "run-bar"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: Math.round(r.step / r.total * 100) + '%',
      background: barColor(r.state)
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "rmeta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "steps"), r.step, "/", r.total), /*#__PURE__*/React.createElement("div", {
    className: "rmeta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, r.when), r.dur, " \xB7 ", r.tps, " t/s")))));
}
function LibraryView({
  onOpen
}) {
  const D = window.ENCLAVE;
  React.useEffect(() => {
    window.refreshIcons();
  });
  const catTone = {
    security: 'accent',
    code: 'info',
    research: 'warm'
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "page"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Library"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Saved workflows. Open one into the Composer."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "plus"
  }, "New Workflow")), /*#__PURE__*/React.createElement("div", {
    className: "toolbar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "search"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "search"
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Search workflows\u2026"
  })), /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "filter"
  }, "security")), /*#__PURE__*/React.createElement("div", {
    className: "cardgrid"
  }, D.WORKFLOWS.map(w => /*#__PURE__*/React.createElement("div", {
    className: "gcard",
    key: w.id,
    onClick: onOpen
  }, /*#__PURE__*/React.createElement("div", {
    className: "gtop"
  }, /*#__PURE__*/React.createElement("div", {
    className: "gico"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "workflow"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "gname"
  }, w.name))), /*#__PURE__*/React.createElement("div", {
    className: "gmeta"
  }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, w.steps), " steps"), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, w.runs), " runs"), /*#__PURE__*/React.createElement("span", null, w.updated)), /*#__PURE__*/React.createElement("div", {
    className: "gfoot"
  }, /*#__PURE__*/React.createElement(Badge, {
    tone: catTone[w.category] || 'accent',
    sq: true
  }, w.category), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Btn, {
    sm: true,
    icon: "play"
  }, "Run"))))));
}
function ModelsView() {
  const D = window.ENCLAVE;
  React.useEffect(() => {
    window.refreshIcons();
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "page"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Models"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Local GGUF models via Ollama. Q4_K_M default."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "download"
  }, "Pull Model")), /*#__PURE__*/React.createElement("table", {
    className: "modeltable"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "Model"), /*#__PURE__*/React.createElement("th", null, "Role"), /*#__PURE__*/React.createElement("th", null, "Quant"), /*#__PURE__*/React.createElement("th", {
    className: "r"
  }, "Size"), /*#__PURE__*/React.createElement("th", {
    className: "r"
  }, "Throughput"), /*#__PURE__*/React.createElement("th", {
    className: "r"
  }, "Status"))), /*#__PURE__*/React.createElement("tbody", null, D.MODELS.map(m => /*#__PURE__*/React.createElement("tr", {
    key: m.id
  }, /*#__PURE__*/React.createElement("td", {
    className: "mid"
  }, m.id), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement(Badge, {
    tone: "accent",
    sq: true
  }, m.role)), /*#__PURE__*/React.createElement("td", {
    className: "num"
  }, m.quant), /*#__PURE__*/React.createElement("td", {
    className: "r num"
  }, m.size), /*#__PURE__*/React.createElement("td", {
    className: "r num"
  }, m.tps, " t/s"), /*#__PURE__*/React.createElement("td", {
    className: "r"
  }, m.loaded ? /*#__PURE__*/React.createElement(Badge, {
    tone: "success",
    dot: true
  }, "loaded") : /*#__PURE__*/React.createElement(Badge, {
    tone: "neutral"
  }, "on disk")))))));
}
function ContextView() {
  React.useEffect(() => {
    window.refreshIcons();
  });
  const docs = [{
    n: 'crowdstrike-falcon-schema.md',
    m: '12 KB · indexed'
  }, {
    n: 'xsiam-data-model.pdf',
    m: '340 KB · indexed'
  }, {
    n: 'detection-rules-q4.yaml',
    m: '8 KB · indexed'
  }, {
    n: 'incident-7f3a-export.json',
    m: '1.2 MB · indexed'
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "page"
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "h"
  }, "Context"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Documents and the knowledge graph your workflows draw on (RAG)."), /*#__PURE__*/React.createElement("div", {
    className: "page-head-spacer"
  }), /*#__PURE__*/React.createElement(Btn, {
    variant: "primary",
    icon: "upload"
  }, "Add Document")), /*#__PURE__*/React.createElement("div", {
    className: "ctx-grid"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(MLabel, null, "Documents"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12
    }
  }, docs.map((d, i) => /*#__PURE__*/React.createElement("div", {
    className: "doc-row",
    key: i
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "file-text"
  }), /*#__PURE__*/React.createElement("span", {
    className: "dn"
  }, d.n), /*#__PURE__*/React.createElement("span", {
    className: "dm"
  }, d.m))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(MLabel, null, "Knowledge Graph"), /*#__PURE__*/React.createElement("div", {
    className: "graph-box",
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/illustrations/art-rag.svg",
    alt: "knowledge graph",
    style: {
      width: '100%',
      height: '100%',
      objectFit: 'cover',
      opacity: 0.9
    }
  })))));
}

/* ── App shell: rail + topbar + router ─────────────────────────────── */
const NAV = [{
  id: 'compose',
  icon: 'workflow',
  label: 'Compose'
}, {
  id: 'runs',
  icon: 'circle-play',
  label: 'Runs'
}, {
  id: 'library',
  icon: 'library',
  label: 'Library'
}, {
  id: 'context',
  icon: 'database',
  label: 'Context'
}, {
  id: 'models',
  icon: 'boxes',
  label: 'Models'
}];
function App() {
  const [view, setView] = React.useState('compose');
  React.useEffect(() => {
    window.refreshIcons();
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "encl-app"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rail"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rail-logo"
  }, /*#__PURE__*/React.createElement(Logo, {
    size: 40
  })), NAV.map(n => /*#__PURE__*/React.createElement("div", {
    key: n.id,
    className: `rail-item ${view === n.id ? 'active' : ''}`,
    onClick: () => setView(n.id)
  }, /*#__PURE__*/React.createElement(Ico, {
    n: n.icon
  }), /*#__PURE__*/React.createElement("span", null, n.label))), /*#__PURE__*/React.createElement("div", {
    className: "rail-spacer"
  }), /*#__PURE__*/React.createElement("div", {
    className: "rail-item"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "settings"
  }), /*#__PURE__*/React.createElement("span", null, "Settings"))), /*#__PURE__*/React.createElement("div", {
    className: "topbar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "topbar-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nm"
  }, NAV.find(n => n.id === view).label), /*#__PURE__*/React.createElement("span", {
    className: "ctx"
  }, "enclave \xB7 sovereign appliance")), /*#__PURE__*/React.createElement("div", {
    className: "proj-pick"
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "folder"
  }), /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "Q4 Detection Playbooks"), /*#__PURE__*/React.createElement("span", {
    className: "car"
  }, "\u25BE")), /*#__PURE__*/React.createElement("div", {
    className: "topbar-spacer"
  }), /*#__PURE__*/React.createElement("div", {
    className: "sysstrip"
  }, /*#__PURE__*/React.createElement("div", {
    className: "health"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: "online",
    live: true
  }), "API"), /*#__PURE__*/React.createElement("div", {
    className: "health"
  }, /*#__PURE__*/React.createElement(Pip, {
    status: "online",
    live: true
  }), "Ollama"), /*#__PURE__*/React.createElement("span", {
    className: "sep"
  }), /*#__PURE__*/React.createElement(Metric, {
    k: "CPU",
    v: "34%",
    percent: 34
  }), /*#__PURE__*/React.createElement(Metric, {
    k: "MEM",
    v: "18 / 64",
    percent: 28
  }), /*#__PURE__*/React.createElement(Metric, {
    k: "Loaded",
    v: "3"
  }), /*#__PURE__*/React.createElement("span", {
    className: "sep"
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "moon",
    bare: true,
    label: "Theme"
  }), /*#__PURE__*/React.createElement(IconBtn, {
    icon: "command",
    bare: true,
    label: "Shortcuts"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "view"
  }, view === 'compose' ? /*#__PURE__*/React.createElement(Composer, null) : view === 'runs' ? /*#__PURE__*/React.createElement(RunsView, null) : view === 'library' ? /*#__PURE__*/React.createElement(LibraryView, {
    onOpen: () => setView('compose')
  }) : view === 'context' ? /*#__PURE__*/React.createElement(ContextView, null) : view === 'models' ? /*#__PURE__*/React.createElement(ModelsView, null) : null));
}
window.App = App;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/console/views.jsx", error: String((e && e.message) || e) }); }

__ds_ns.ActionChip = __ds_scope.ActionChip;

__ds_ns.EntityCard = __ds_scope.EntityCard;

__ds_ns.FitBar = __ds_scope.FitBar;

__ds_ns.MaturityMeter = __ds_scope.MaturityMeter;

__ds_ns.SeedChip = __ds_scope.SeedChip;

__ds_ns.WizardStepper = __ds_scope.WizardStepper;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Panel = __ds_scope.Panel;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.StatusPip = __ds_scope.StatusPip;

__ds_ns.Toggle = __ds_scope.Toggle;

__ds_ns.Sparkline = __ds_scope.Sparkline;

__ds_ns.TrendStat = __ds_scope.TrendStat;

__ds_ns.UtilChart = __ds_scope.UtilChart;

__ds_ns.MetricStat = __ds_scope.MetricStat;

__ds_ns.RoleChip = __ds_scope.RoleChip;

__ds_ns.RunStatus = __ds_scope.RunStatus;

__ds_ns.WorkflowNode = __ds_scope.WorkflowNode;

})();
