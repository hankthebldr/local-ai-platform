#!/usr/bin/env python3
"""
Enclave v1.1.1 — automated demo recorder.

Records 3 browser-driven segments via Playwright's built-in video capture.
The 4th segment (native Mac DMG first-run) is recorded separately via
ffmpeg/avfoundation by record_demo.sh — Playwright cannot drive pywebview.

Output: dist/demo/seg{1,2,3}_*/<rand>.webm  (one .webm per segment)

Topology (after PR #57 Cortex Console rebrand):
  - The Composer IS the dashboard ("COMPOSER-AS-DASHBOARD"). Sub-views are
    workbench tabs identified by data-bench: steps, agents, mcps, plugins, skills.
  - Top-level data-tab IDs: dashboard, agents, documents, inventory, memory,
    research, workflow-index, workflows.

Run against a running stack on http://127.0.0.1:8000 with auth OFF.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = os.getenv("ENCLAVE_DEMO_BASE", "http://127.0.0.1:8000")
OUT_DIR = Path(os.getenv("ENCLAVE_DEMO_OUT", "dist/demo"))
VIEWPORT = {"width": 1440, "height": 900}


def _wait(page: Page, ms: int) -> None:
    """Visible pause — Playwright recorder runs at viewport framerate."""
    page.wait_for_timeout(ms)


def _switch_tab(page: Page, tab_id: str) -> bool:
    """Click a top-level tab by its data-tab. Returns True if found."""
    loc = page.locator(f'.tab-btn[data-tab="{tab_id}"]').first
    if loc.count() == 0:
        return False
    loc.click()
    return True


def _switch_bench(page: Page, bench_id: str) -> bool:
    """Click a composer workbench sub-tab by its data-bench."""
    loc = page.locator(f'.workbench-tab[data-bench="{bench_id}"]').first
    if loc.count() == 0:
        return False
    loc.click()
    return True


def _record(pw, seg_dir: Path):
    seg_dir.mkdir(parents=True, exist_ok=True)
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport=VIEWPORT,
        record_video_dir=str(seg_dir),
        record_video_size=VIEWPORT,
    )
    return browser, context


def segment_composer_agents(pw) -> Path:
    """Segment 1: Composer-as-dashboard + workbench sub-tabs + Agents.

    PR #53 added agents palette + step-engage. PR #57 made composer the
    default view, with sub-tabs identified by data-bench.
    """
    seg_dir = OUT_DIR / "seg1_composer"
    browser, context = _record(pw, seg_dir)
    page = context.new_page()
    page.goto(f"{BASE}/", wait_until="networkidle")
    _wait(page, 3000)  # let the canvas + workbench paint

    # Show the workbench cycling through Steps → Agents → Skills.
    for bench in ("steps", "agents", "skills"):
        if _switch_bench(page, bench):
            _wait(page, 2500)

    # Hover an OOTB agent if visible (xsiam-analyst from PR #56).
    agent_chip = page.locator('text=xsiam-analyst').first
    if agent_chip.count():
        agent_chip.scroll_into_view_if_needed()
        agent_chip.hover()
        _wait(page, 2000)

    # Back to Steps so the final frame shows the canvas.
    _switch_bench(page, "steps")
    _wait(page, 2000)

    context.close()
    browser.close()
    return seg_dir


def segment_ootb_workflow(pw) -> Path:
    """Segment 2: OOTB XQL/XDM workflow catalogue + a completed run.

    Navigates workflow-index → workflows (runs) → opens a completed run
    so the viewer sees the 5 OOTB workflows + a green pipeline.
    """
    seg_dir = OUT_DIR / "seg2_ootb"
    browser, context = _record(pw, seg_dir)
    page = context.new_page()
    page.goto(f"{BASE}/", wait_until="networkidle")
    _wait(page, 2000)

    # 2a — Workflow Index (the catalogue, PR #56 OOTB visible here).
    _switch_tab(page, "workflow-index")
    _wait(page, 3000)
    page.mouse.wheel(0, 400)
    _wait(page, 2500)
    page.mouse.wheel(0, -200)
    _wait(page, 1500)

    # 2b — Runs tab (workflows). Should list any completed OOTB runs.
    _switch_tab(page, "workflows")
    _wait(page, 3000)
    page.mouse.wheel(0, 300)
    _wait(page, 2500)

    # Try to click the most recent completed run row to expand it.
    run_row = page.locator('.runs-table tr, .run-row, [data-run-id]').first
    if run_row.count():
        try:
            run_row.click()
            _wait(page, 3000)
        except Exception:
            pass

    context.close()
    browser.close()
    return seg_dir


def segment_documents_rag(pw) -> Path:
    """Segment 3: Documents drop-zone (PR #55) + retrieval surface."""
    seg_dir = OUT_DIR / "seg3_documents"
    browser, context = _record(pw, seg_dir)
    page = context.new_page()
    page.goto(f"{BASE}/", wait_until="networkidle")
    _wait(page, 2000)

    # Documents lives under LIBRARY in the Cortex IA.
    if not _switch_tab(page, "documents"):
        # Older naming fallback.
        _switch_tab(page, "memory")
    _wait(page, 3500)

    # Surface the drop-zone via scroll.
    page.mouse.wheel(0, 500)
    _wait(page, 2500)
    page.mouse.wheel(0, -200)
    _wait(page, 1500)

    # Inventory (Models) — quick cameo so the demo shows the LIBRARY family.
    if _switch_tab(page, "inventory"):
        _wait(page, 3000)

    context.close()
    browser.close()
    return seg_dir


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        segments = [
            ("segment 1 — Composer (dashboard) + Agents", segment_composer_agents),
            ("segment 2 — OOTB workflow catalogue + Run", segment_ootb_workflow),
            ("segment 3 — Documents + Inventory", segment_documents_rag),
        ]
        for label, fn in segments:
            t0 = time.time()
            print(f">>> {label}")
            try:
                out = fn(pw)
                elapsed = time.time() - t0
                videos = list(out.glob("*.webm"))
                print(f"    wrote {len(videos)} video(s) to {out} ({elapsed:.1f}s)")
            except Exception as e:
                print(f"    FAILED: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
