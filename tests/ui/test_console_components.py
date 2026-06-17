"""Static-markup regression for the canonical console atoms that the validation
flagged as missing/partial and were then implemented: SeedChip (was missing)
and WizardStepper (was a border-bottom indicator; now canonical numbered circles).
"""


def test_seedchip_component_present(index_html_text):
    assert "window.SeedChip" in index_html_text
    assert ".encl-seedchip" in index_html_text
    # tone variants + ghost + dismiss per canonical spec
    assert ".encl-seedchip.accent" in index_html_text
    assert ".encl-seedchip.ghost" in index_html_text


def test_seedchip_helper_returns_key_value_chip(index_html_text):
    # Helper builds the canonical k:v structure.
    assert 'class="k"' in index_html_text  # key label
    assert "TONE" in index_html_text  # accent/emerald/warm/info tone map


def test_wizardstepper_canonical_numbered_circles(index_html_text):
    # WizardStepper upgraded from border-bottom to numbered-circle steps.
    assert ".encl-wstep" in index_html_text
    assert ".encl-wstep .n" in index_html_text  # the numbered circle
    assert ".encl-wconn" in index_html_text  # connectors between steps
    # done state fills the circle with accent; on state glows
    assert ".encl-wstep.done .n" in index_html_text
    assert ".encl-wstep.on .n" in index_html_text


def test_install_wizard_renders_canonical_stepper(index_html_text):
    # The install wizard's phase render emits .encl-wstep, not the old .iw-phase.
    assert '"encl-wstep ' in index_html_text
    assert "encl-wconn" in index_html_text
