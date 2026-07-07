"""Static-markup regression for pin-as-step + maturity meter + scaffold modal.

The literal "crystallized conversation" payoff: pin chat replies, watch a
maturity meter, convert 2+ pins into a runnable DAG. Pins the markup, the
2-pin gate, source traceability, and that conversion reuses the same
composerLoadDefinition path as BootSequence (so the DAG is genuinely runnable).
"""


def test_pin_markup_anchors_present(index_soup):
    assert index_soup.find(id="pins-meter") is not None, "maturity meter missing"
    assert index_soup.find(id="pm-bar") is not None, "meter bar missing"
    assert index_soup.find(id="pm-convert") is not None, "convert button missing"
    assert index_soup.find(id="scaffold-modal-backdrop") is not None, "modal missing"
    assert index_soup.find(id="sm-steps") is not None, "modal steps slot missing"


def test_pin_modules_present(index_html_text):
    assert "window.Pins" in index_html_text  # module code (phase-2: now in js/main.js)
    assert "window.ScaffoldModal" in index_html_text
    assert 'id="enclave-pins-styles"' in index_html_text


def test_toolbar_has_pin_button(index_html_text):
    # The per-message pin affordance lives in the msg-actions toolbar.
    assert 'class="msg-pin-btn"' in index_html_text
    assert "Pins.toggle(" in index_html_text


def test_two_pin_gate(index_html_text):
    # Convert is gated until 2+ pins exist.
    assert "pins.length < 2" in index_html_text


def test_scaffold_shows_source_traceability(index_html_text):
    assert "pinned from this reply" in index_html_text


def test_convert_reuses_composer_load_definition(index_html_text):
    # Conversion must build a real definition and reuse the shared load path,
    # chaining steps via depends_on, then pivot to canvas — not a bespoke DAG.
    assert "composerLoadDefinition(defn)" in index_html_text
    assert "depends_on" in index_html_text
    assert "'step-' + i" in index_html_text  # sequential chaining
    assert "ComposerSplit.setMode('canvas')" in index_html_text


def test_pins_exposed_for_journey_ladder(index_html_text):
    # The ladder reads window._enclavePins — keep the shared store wired.
    assert "window._enclavePins" in index_html_text
