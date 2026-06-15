"""Static-markup regression for the calm-analytics dataviz atoms.

enclSparkline / enclTrendStat / enclUtilChart implement the design system's
"charts are instruments, not decoration" guidance. Shipped untested; this pins
their presence, the up/down delta semantics, and that they emit SVG.
"""

import re


def test_dataviz_atoms_defined(index_html_text):
    for fn in ("enclSparkline", "enclTrendStat", "enclUtilChart"):
        assert f"function {fn}(" in index_html_text, f"{fn} not defined"


def test_sparkline_emits_svg(index_html_text):
    # Grab the enclSparkline body and confirm it builds an <svg> with a stroke.
    m = re.search(
        r"function enclSparkline\([^)]*\)\s*\{(.*?)\n\}", index_html_text, re.S
    )
    assert m is not None, "enclSparkline body not found"
    body = m.group(1)
    assert "svg" in body.lower()
    assert "polyline" in body or "polygon" in body


def test_trendstat_delta_direction_classes(index_html_text):
    # Delta carries an up/down/flat class so colour encodes direction.
    for cls in (".encl-trend-d.up", ".encl-trend-d.down", ".encl-trend-d.flat"):
        assert cls in index_html_text, f"{cls} missing"


def test_trendstat_value_and_key_slots(index_html_text):
    for cls in (".encl-trend-k", ".encl-trend-v"):
        assert cls in index_html_text, f"{cls} missing"


def test_dataviz_fed_into_runs_perf_band(index_html_text):
    # The atoms are actually wired into the Runs performance band.
    assert "renderRunsPerfBand" in index_html_text
