"""Regression for the interactive workflow drill-down (composer canvas view).

The Workflow Index drill-down (#wf-detail) was a static step-box row. It now
also renders an interactive dagre-laid-out DAG (clickable nodes → open that
step in the Composer with node-bound chat) on the shared dot-grid canvas
surface, plus an "Open in Composer" handoff.
"""

import re


def test_wf_dag_markup_present(index_soup):
    assert index_soup.find(id="wf-dag") is not None, "interactive DAG container missing"
    assert index_soup.find(id="wf-dag-actions") is not None, "DAG actions row missing"


def test_render_and_open_functions(index_html_text):
    assert "function renderWorkflowDag(" in index_html_text
    assert "async function openWorkflowInComposer(" in index_html_text


def test_dag_is_dagre_laid_out_and_clickable(index_html_text):
    fn = index_html_text[index_html_text.index("function renderWorkflowDag") :]
    assert "dagre.graphlib.Graph" in fn  # real graph layout, not a flat row
    assert "rankdir: 'LR'" in fn
    assert (
        "openWorkflowInComposer('${esc(wfId)}','${esc(s.id)}')" in fn
    )  # node click → open+bind


def test_open_in_composer_loads_and_binds(index_html_text):
    fn = index_html_text[
        index_html_text.index("async function openWorkflowInComposer") :
    ]
    assert "composerLoadById(wfId)" in fn  # load into the canvas
    assert "switchTab('dashboard')" in fn  # go to the composer
    assert (
        "composerEnterStepEngage(nid)" in fn
    )  # bind the clicked node (node-bound chat)


def test_drilldown_renders_dag(index_html_text):
    # loadWorkflowDetail invokes the interactive DAG render.
    assert "renderWorkflowDag(defn)" in index_html_text


def test_dag_shares_canvas_background(index_html_text):
    m = re.search(r"\.wf-dag\s*\{[^}]*\}", index_html_text, re.S)
    assert m and "radial-gradient(var(--border) 1px, transparent 1px)" in m.group(0)
