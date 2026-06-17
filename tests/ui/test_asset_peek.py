"""Static-markup regression for the AssetPeek unified deep-dive slide-over.

AssetPeek was shipped with zero coverage. These pin its structure + wiring so a
refactor of the 1MB SPA can't silently drop the panel, its close affordances,
the seed-a-chat action, or the (local, no-phone-home) enrichment fetch.
"""

import re


def test_assetpeek_module_defined(index_html_text):
    assert "window.AssetPeek = (function" in index_html_text


def test_assetpeek_modal_structure_present(index_soup):
    # The slide-over aside + its click-to-close backdrop.
    aside = index_soup.find("aside", id="asset-peek")
    assert aside is not None, "#asset-peek slide-over missing"
    assert aside.get("role") == "dialog"
    assert index_soup.find(id="asset-peek-backdrop") is not None
    # Body + title slots the module fills on open.
    for slot in ("peek-title", "peek-body"):
        assert index_soup.find(id=slot) is not None, f"#{slot} slot missing"


def test_assetpeek_close_is_wired(index_html_text):
    # Both the backdrop and the close button invoke AssetPeek.close().
    assert index_html_text.count("AssetPeek.close()") >= 2


def test_assetpeek_open_close_and_seedchat_exist(index_html_text):
    for fn in ("open", "close", "seedChat"):
        assert (
            re.search(rf"\b{fn}\s*[:(]", index_html_text) is not None
        ), f"AssetPeek.{fn} not found"
    # Every dive ends in 'seed a chat'.
    assert "AssetPeek.seedChat" in index_html_text


def test_assetpeek_opens_for_every_entity_type(index_html_text):
    # Unified across models / agents / plugins.
    for kind in ("model", "agent", "plugin"):
        assert (
            f"AssetPeek.open('{kind}'" in index_html_text
        ), f"AssetPeek.open for '{kind}' missing"


def test_assetpeek_reads_local_enrichment_only(index_html_text):
    # Benchmarks come from the local enrichment endpoint — no external host.
    assert "/api/inventory/enrichment" in index_html_text
    assert "fetch('/api/inventory/enrichment')" in index_html_text.replace('"', "'")
