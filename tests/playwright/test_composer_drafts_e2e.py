"""DR-1 e2e — durable Composer draft round-trip in a real Chromium.

Companion to tests/test_composer_drafts.py (backend store/router units, incl.
the In-Progress list projection + scope gating). Proves the frontend keystone
the store can't see on its own:

  1. Build a ralph+seed canvas -> reload (F5) -> the canvas is restored
     LOSSLESSLY (per-node ports/positions + composite `_sub_of` proxy edges,
     dfNodeData identical, EXACTLY ONE seed). This is the `dfEditor.import()`
     round-trip the DR-1 prototype proved, exercised through the real WAL +
     boot-restore path.
  2. Publish (Save) FREEZES the draft — the WAL is cleared, single identity.

These assert on the localStorage WAL + the live canvas (deterministic, rate-
limit-immune: dfFlushDraft writes the WAL BEFORE its best-effort server POST).
Server persistence + In-Progress rendering are covered by the backend units.

Auto-skips when the stack is down (conftest `_require_stack`). Point
ENCLAVE_PLAYWRIGHT_BASE_URL at the dev port (:8001).
"""

from __future__ import annotations

import json

import requests

_WAL = "enclave.composer.draft.wal"

# Logical-id fingerprint: connection targets normalize to the target's stable
# dfNodeData step id, or '__anchor__' for the decorative begin/end brackets
# (regenerated from topology every restore, so their raw drawflow id drifts by
# design and is NOT a fidelity signal).
_FP = r"""
() => {
  const ed = window.dfEditor;
  const h = ed.export().drawflow.Home.data;
  const nd = window.dfNodeData || {};
  const realIds = Object.keys(nd);
  const logical = (tid) => (nd[tid] && nd[tid].id) ? nd[tid].id : '__anchor__';
  const o = {};
  realIds.sort((a,b)=>a-b).forEach(id => {
    const n = h[id]; if (!n) return;
    const outs = {};
    Object.keys(n.outputs||{}).forEach(k =>
      outs[k] = (n.outputs[k].connections||[]).map(c=>logical(c.node)+'>'+c.output).sort());
    o[nd[id].id] = {name:n.name, nIn:Object.keys(n.inputs||{}).length,
                    nOut:Object.keys(n.outputs||{}).length, outs, px:n.pos_x, py:n.pos_y};
  });
  const seeds = realIds.filter(k => nd[k] && nd[k].is_seed);
  const subOf = realIds.filter(k => nd[k] && nd[k]._sub_of != null);
  return {fp:o, seedCount:seeds.length, subOfCount:subOf.length,
          nodeData: JSON.parse(JSON.stringify(nd))};
}
"""


def _clear_server_drafts(base_url):
    try:
        r = requests.get(f"{base_url}/api/composer/drafts", timeout=5)
        if r.status_code == 200 and isinstance(r.json(), list):
            for d in r.json():
                requests.delete(
                    f"{base_url}/api/composer/drafts/{d['draft_id']}", timeout=5
                )
    except Exception:
        pass


def _reset_slate(page, base_url):
    """Clean-slate a test: drop the WAL + server drafts, then RELOAD so boot
    starts with no queued draft (the reload tears down any pending reconcile
    timer from a prior test and resets the module's _dfActiveDraftId)."""
    page.evaluate(f"() => localStorage.removeItem('{_WAL}')")
    _clear_server_drafts(base_url)
    page.reload()
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=15000)
    page.wait_for_timeout(800)


def _wal(page):
    raw = page.evaluate(f"() => localStorage.getItem('{_WAL}')")
    return json.loads(raw) if raw else None


def test_ralph_canvas_survives_reload_losslessly(signed_in_page, base_url):
    page = signed_in_page
    _reset_slate(page, base_url)

    # Build a ralph+seed canvas (composite sub-DAG with _sub_of proxy edges).
    page.evaluate(
        "() => { window.dfRefreshAnchors();"
        " window.dfScaffoldPattern('ralph_loop', 340, 220);"
        " window.dfRefreshAnchors(); }"
    )
    page.wait_for_timeout(700)
    before = page.evaluate(_FP)
    assert before["seedCount"] == 1, before
    assert before["subOfCount"] > 0, "ralph must scaffold composite sub-DAG proxies"
    assert len(before["fp"]) > 1

    # The debounced flush writes the WAL (crash-safe, before any server POST);
    # the reload's beforeunload also flushes it. Either way the WAL is present.
    page.wait_for_timeout(4600)
    assert _wal(page), "editing the canvas must write a durable WAL draft"

    # RELOAD (F5) — boot restores from the WAL.
    page.reload()
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=15000)
    page.wait_for_timeout(2500)

    after = page.evaluate(_FP)
    assert after["seedCount"] == 1, "restore must leave EXACTLY ONE seed"
    assert after["subOfCount"] == before["subOfCount"], "composite proxies lost"
    assert json.dumps(after["fp"]) == json.dumps(
        before["fp"]
    ), "canvas fingerprint (ports/positions/connections) not lossless"
    assert json.dumps(after["nodeData"]) == json.dumps(
        before["nodeData"]
    ), "dfNodeData not restored byte-for-byte"

    # cleanup so the WAL doesn't bleed into the next test
    page.evaluate(f"() => localStorage.removeItem('{_WAL}')")
    _clear_server_drafts(base_url)


def test_publish_freezes_the_draft(signed_in_page, base_url):
    page = signed_in_page
    _reset_slate(page, base_url)

    page.evaluate(
        """() => {
          window.dfRefreshAnchors();
          window.dfAddNodeFromTemplate('analyzer', 360, 220);
          document.getElementById('df-wf-id').value = 'dr1-e2e-publish';
          document.getElementById('df-wf-name').value = 'DR1 E2E Publish';
          const nid = Object.keys(window.dfNodeData).find(k => !window.dfNodeData[k].is_seed);
          if (nid) window.dfUpdateNodeData(nid, 'name', 'Analyzer', {commit:true});
        }"""
    )
    # debounced flush writes the WAL (deterministic — precedes the server POST)
    page.wait_for_timeout(4600)
    assert _wal(page), "a draft WAL should exist before publish"

    # Publish. dfSave persists the workflow then freezes the draft (clears the
    # WAL + releases the single identity). The workflow-save POST can 429 under
    # the shared limiter (freeze only runs on resp.ok) — retry past the window.
    frozen = False
    for _ in range(5):
        page.evaluate("() => window.dfSave()")
        page.wait_for_timeout(1500)
        if _wal(page) is None:
            frozen = True
            break
        page.wait_for_timeout(3500)
    assert frozen, "publish must FREEZE the draft — WAL cleared"

    # best-effort cleanup of the published workflow artifact
    requests.delete(f"{base_url}/api/workflows/dr1-e2e-publish", timeout=5)
    _clear_server_drafts(base_url)
