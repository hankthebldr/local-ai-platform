"""Static-markup regression for the Library cluster:
the model-compare grid and the 4-phase install wizard.

Pins the markup, that compare reuses the real catalog/enrichment endpoints
with a per-row win highlight ending in seed-a-chat, and that the wizard walks
source→configure→verify→land wrapping the real pull endpoints, verifying by
conversation at the end.
"""


def test_library_markup_present(index_soup):
    assert index_soup.find(id="cmp-tray") is not None, "compare tray missing"
    assert index_soup.find(id="cmp-modal-backdrop") is not None, "compare modal missing"
    assert index_soup.find(id="iw-backdrop") is not None, "install wizard missing"
    assert index_soup.find(id="iw-phases") is not None, "wizard phase rail missing"


def test_library_modules_present(index_html_text):
    assert (
        "window.Compare" in index_html_text
    )  # module code (phase-2: now in js/main.js)
    assert "window.InstallWizard" in index_html_text
    assert 'id="enclave-library-styles"' in index_html_text


def test_assetpeek_offers_compare_and_guided_install(index_html_text):
    # The model deep-dive wires both new entry points.
    assert "Compare.add(" in index_html_text
    assert "InstallWizard.open(" in index_html_text


def test_compare_uses_real_data_and_win_highlight(index_html_text):
    assert "/api/inventory/catalog" in index_html_text
    assert "/api/inventory/enrichment" in index_html_text
    assert ".cmp-grid td.win" in index_html_text  # per-row winner highlight
    # Compare ends in the design's terminal action.
    assert "Compare.closeModal();AssetPeek.seedChat(" in index_html_text


def test_install_wizard_has_four_phases(index_html_text):
    assert "['Source', 'Configure', 'Verify', 'Land']" in index_html_text


def test_install_wizard_wraps_real_pull_and_verifies_by_chat(index_html_text):
    # Verify phase wraps the real pull + progress endpoints.
    assert "/api/inventory/pull" in index_html_text
    assert "/api/inventory/pull-progress/" in index_html_text
    # Land phase verifies by conversation.
    assert "InstallWizard.land()" in index_html_text
    assert "AssetPeek.seedChat(m)" in index_html_text
