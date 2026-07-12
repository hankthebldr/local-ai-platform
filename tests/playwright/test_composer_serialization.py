"""GP-1b — serializer fidelity + run-launch seed residue (residual P0s).

P0-4  a per-step model pin + StepConfig temperature/max_tokens must survive
      save → reload → save (they used to drop back to the role-based resolver
      / workflow defaults because the llm emitter never wrote them).
P0-5  bench-dragged tool refs are stored in the CANONICAL dotted form ToolRef
      requires (`mcp:server.tool` / `plugin.tool`) at the DROP handler — the
      old `mcp__srv__tool` / `pid__tid` forms 422'd on the very next Save.
P0-6  a loaded seed-consuming workflow gets a LIVE seed node with per-key VALUE
      inputs, and those values feed the run payload; wfi.run prompts for them.

Drops are simulated with a synthetic DragEvent carrying a real DataTransfer
(HTML5 drag is flaky headless), matching test_composer_patterns' evaluate style.
"""

from __future__ import annotations

import json

SEED_SEL = "#drawflow-canvas .df-seed-node"


def _wait_canvas(page):
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.wait_for_function(
        "() => typeof window.dfAddNodeFromTemplate === 'function'"
        " && typeof window.dfComposeYamlString === 'function'"
        " && typeof window.composerLoadDefinition === 'function'"
        " && !!window.jsyaml",
        timeout=10_000,
    )


# ── P0-4 — model + sampling pins round-trip ────────────────────────────────


def test_model_and_sampling_pins_survive_reload(signed_in_page):
    """A model pin + temperature/max_tokens set on an llm step serialize into
    the step (model + config block) and are restored intact on reload — the
    round-trip is byte-stable, not silently collapsed to the defaults."""
    page = signed_in_page
    _wait_canvas(page)
    res = page.evaluate(
        """() => {
            const yaml = window.jsyaml;
            const nid = window.dfAddNodeFromTemplate('custom', 320, 220, { autoChain: false });
            const d = window.dfNodeData[nid];
            d.id = 'analyze'; d.name = 'Analyze'; d.role = 'reasoning';
            d.system_prompt = 'do the thing'; d.outputs = ['result'];
            d.model = 'hermes3:8b'; d.temperature = 0.25; d.max_tokens = 1536;
            document.getElementById('df-wf-id').value = 'rt-pins';
            document.getElementById('df-wf-name').value = 'RT Pins';
            const yaml1 = window.dfExportYaml();
            const defn1 = yaml.load(yaml1);
            window.composerLoadDefinition(defn1);
            const defn2 = yaml.load(window.dfExportYaml());
            const pick = (defn) => {
                const s = (defn.steps || []).find(x => x && x.id === 'analyze');
                return s ? { model: s.model, t: s.config && s.config.temperature, m: s.config && s.config.max_tokens } : null;
            };
            return { yaml1, s1: pick(defn1), s2: pick(defn2) };
        }"""
    )
    assert res["s1"] == {"model": "hermes3:8b", "t": 0.25, "m": 1536}, res
    assert res["s2"] == res["s1"], f"model/sampling pins lost on reload: {res}"
    # The emitted YAML actually carries the fields (not just parsed back).
    assert "model: hermes3:8b" in res["yaml1"]
    assert "temperature: 0.25" in res["yaml1"]
    assert "max_tokens: 1536" in res["yaml1"]


def test_pinned_definition_validates(signed_in_page):
    """The emitted definition (model + StepConfig) is a VALID WorkflowDefinition
    — POST /validate constructs the full model, so a malformed config/model
    field would 422 here."""
    page = signed_in_page
    _wait_canvas(page)
    result = page.evaluate(
        """async () => {
            const nid = window.dfAddNodeFromTemplate('custom', 320, 220, { autoChain: false });
            const d = window.dfNodeData[nid];
            d.id = 'analyze'; d.name = 'Analyze'; d.role = 'reasoning';
            d.system_prompt = 'do the thing'; d.outputs = ['result'];
            d.model = 'hermes3:8b'; d.temperature = 0.4; d.max_tokens = 900;
            document.getElementById('df-wf-id').value = 'rt-pins-valid';
            document.getElementById('df-wf-name').value = 'RT Pins Valid';
            const defn = window.jsyaml.load(window.dfExportYaml());
            const r = await fetch('/api/workflows/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ definition: defn }),
            });
            return { status: r.status, body: await r.json().catch(() => null) };
        }"""
    )
    assert result["status"] == 200, result
    assert result["body"] and result["body"].get("valid") is True, result


# ── P0-5 — canonical tool-ref normalization at the drop handler ─────────────


def test_mcp_and_plugin_drop_store_canonical_refs(signed_in_page):
    """Dropping an MCP bench tool (`srv::tool`) and a plugin bench tool
    (`pid__tid`) onto a step stores the CANONICAL dotted refs
    (`mcp:srv.tool`, `pid.tid`), the YAML emitter routes them to
    `mcp:`/`plugin:`, and the refs are STABLE across save→reload→save (the old
    `mcp__srv__tool` / `pid__tid` forms would have emitted a bogus non-dotted
    `plugin:` and 422'd)."""
    page = signed_in_page
    _wait_canvas(page)
    res = page.evaluate(
        """() => {
            const yaml = window.jsyaml;
            const nid = window.dfAddNodeFromTemplate('custom', 320, 220, { autoChain: false });
            const d = window.dfNodeData[nid];
            d.id = 'act'; d.name = 'Act'; d.role = 'reasoning';
            d.system_prompt = 'use tools'; d.outputs = ['result'];
            const nodeEl = document.getElementById('node-' + nid);
            const inner = nodeEl.querySelector('.drawflow_content_node') || nodeEl;
            const drop = (mime, val) => {
                const dt = new DataTransfer();
                dt.setData(mime, val);
                const ev = new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt });
                inner.dispatchEvent(ev);
            };
            drop('application/df-mcp', 'github::create_issue');
            drop('application/df-tool', 'acme__deploy');
            const stored = (window.dfNodeData[nid].tools || []).slice();
            document.getElementById('df-wf-id').value = 'rt-tools';
            document.getElementById('df-wf-name').value = 'RT Tools';
            const yaml1 = window.dfExportYaml();
            const defn1 = yaml.load(yaml1);
            window.composerLoadDefinition(defn1);
            const defn2 = yaml.load(window.dfExportYaml());
            const toolsOf = (defn) => {
                const s = (defn.steps || []).find(x => x && x.id === 'act');
                return s ? (s.tools || []) : [];
            };
            return { stored, yaml1, t1: toolsOf(defn1), t2: toolsOf(defn2) };
        }"""
    )
    # Drop handler stored the canonical dotted forms — not the old delimiters.
    assert "mcp:github.create_issue" in res["stored"], res
    assert "acme.deploy" in res["stored"], res
    assert not any("mcp__" in t for t in res["stored"]), res
    # Emitter routed them to the right keys.
    assert 'mcp: "github.create_issue"' in res["yaml1"], res["yaml1"]
    assert 'plugin: "acme.deploy"' in res["yaml1"], res["yaml1"]
    assert "mcp__github__create_issue" not in res["yaml1"], res["yaml1"]
    # Parsed tool refs are dotted (what ToolRef requires) and stable on reload.
    assert res["t1"] == [{"mcp": "github.create_issue"}, {"plugin": "acme.deploy"}], res
    assert res["t2"] == res["t1"], f"tool refs not stable across round-trip: {res}"


# ── P0-6 — live seed node on load + per-key values feed the run ─────────────


def test_loaded_workflow_gets_live_seed_node(signed_in_page):
    """Loading a seed-consuming workflow recreates exactly ONE live, editable
    seed node carrying the declared schema (not the decorative __start__ ghost),
    so the operator can supply values."""
    page = signed_in_page
    _wait_canvas(page)
    res = page.evaluate(
        """() => {
            const defn = {
                id: 'seed-load', name: 'Seed Load', version: '1.0',
                context: { inputs: [{ key: 'topic', description: 'the topic' },
                                    { key: 'audience', description: '' }] },
                defaults: { role: 'general' },
                steps: [{
                    id: 'draft', name: 'Draft', role: 'reasoning',
                    system_prompt: 'write', inputs: ['seed.topic', 'seed.audience'],
                    outputs: ['draft'], depends_on: [],
                }],
            };
            window.composerLoadDefinition(defn);
            const seeds = Object.values(window.dfNodeData || {}).filter(d => d && d.is_seed);
            return {
                seedCount: seeds.length,
                keys: seeds.length ? (seeds[0].seed_schema || []).map(s => s.key) : [],
            };
        }"""
    )
    assert res["seedCount"] == 1, f"expected exactly one live seed node: {res}"
    assert set(res["keys"]) == {"topic", "audience"}, res


def test_seed_values_feed_live_run(signed_in_page):
    """Per-key seed VALUES typed into the seed config are POSTed as the run
    seed by dfRunWorkflowLive (the values are otherwise dead UI)."""
    page = signed_in_page
    _wait_canvas(page)
    page.route(
        "**/api/workflows/run-async",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"run_id":"r-seedval"}'
        ),
    )
    with page.expect_request("**/api/workflows/run-async") as reqinfo:
        page.evaluate(
            """() => {
                const nid = window.dfAddNodeFromTemplate('custom', 320, 220, { autoChain: false });
                const d = window.dfNodeData[nid];
                d.id = 'draft'; d.name = 'Draft'; d.role = 'reasoning';
                d.system_prompt = 'write'; d.outputs = ['draft'];
                const seed = Object.values(window.dfNodeData).find(x => x && x.is_seed);
                seed.seed_schema = [{ key: 'topic', description: '' }, { key: 'audience', description: '' }];
                seed.seed_values = { topic: 'local llms', audience: 'execs' };
                document.getElementById('df-wf-id').value = 'rt-seedval';
                document.getElementById('df-wf-name').value = 'RT SeedVal';
                window.dfRunWorkflowLive();
            }"""
        )
    body = json.loads(reqinfo.value.post_data)
    assert body.get("seed") == {"topic": "local llms", "audience": "execs"}, body


def test_wfi_run_prompts_for_seed_values(signed_in_page):
    """The Library Run ▶ path derives the workflow's seed keys, shows an
    editable value per key, and POSTs the collected seed to run-async — a
    loaded seed workflow used to launch with an empty, un-editable seed."""
    page = signed_in_page
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=10_000)
    page.route(
        "**/api/workflows/seed-demo",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": "seed-demo",
                    "name": "Seed Demo",
                    "context": {
                        "inputs": [
                            {"key": "topic", "description": "the topic"},
                            {"key": "depth", "description": ""},
                        ]
                    },
                    "steps": [
                        {
                            "id": "s1",
                            "inputs": ["seed.topic", "seed.depth"],
                            "outputs": ["out"],
                        }
                    ],
                }
            ),
        ),
    )
    page.route(
        "**/api/workflows/run-async",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"run_id":"r-1"}'
        ),
    )
    # Fire-and-forget: run() awaits the modal promise, so returning it to
    # evaluate would block until the modal resolves. Block body → undefined.
    page.evaluate("() => { window.WorkflowIndex.run('seed-demo'); }")
    page.wait_for_selector(
        '.wfi-seed-in[data-seed-key="topic"]', state="visible", timeout=5_000
    )
    assert page.locator(".wfi-seed-in").count() == 2
    page.fill('.wfi-seed-in[data-seed-key="topic"]', "local llms")
    page.fill('.wfi-seed-in[data-seed-key="depth"]', "deep")
    with page.expect_request("**/api/workflows/run-async") as reqinfo:
        page.locator(".wfi-seed-go").click()
    body = json.loads(reqinfo.value.post_data)
    assert body.get("workflow_id") == "seed-demo", body
    assert body.get("seed") == {"topic": "local llms", "depth": "deep"}, body
