"""Regression: the dataviz family is fully implemented (5/5 canonical atoms).

The canonical design system defines Sparkline, TrendStat, UtilChart, GaugeStat,
StatRange. The first three shipped earlier; GaugeStat + StatRange were the
validation gaps. This pins all five present + the two new ones wired into real
surfaces (CPU/MEM gauges in the Runs perf band; duration/token ranges in the
Run lens).
"""


def test_all_five_dataviz_atoms_defined(index_html_text):
    for fn in (
        "enclSparkline",
        "enclTrendStat",
        "enclUtilChart",
        "enclGaugeStat",
        "enclStatRange",
    ):
        assert f"function {fn}(" in index_html_text, f"{fn} not defined"


def test_gauge_calm_meter_contract(index_html_text):
    # Linear meter with fill + optional warn tick, honest scale.
    assert ".encl-gauge-fill" in index_html_text
    assert ".encl-gauge-warn" in index_html_text
    assert ".encl-gauge-track" in index_html_text


def test_statrange_distribution_contract(index_html_text):
    # min/avg/max stats + range span + avg marker + latest dot.
    for cls in (".encl-range-span", ".encl-range-avg", ".encl-range-cur"):
        assert cls in index_html_text, f"{cls} missing"


def test_gauge_wired_into_perf_band(index_html_text):
    assert 'id="runs-perf-gauges"' in index_html_text
    assert "enclGaugeStat({ label: 'CPU'" in index_html_text
    assert "enclGaugeStat({ label: 'MEM'" in index_html_text


def test_statrange_wired_into_run_lens(index_html_text):
    assert 'id="rl-ranges"' in index_html_text
    assert "enclStatRange({ label: 'step duration'" in index_html_text


def test_dataviz_atoms_use_no_undefined_ramp_tokens(index_html_text):
    # The gauge spec originally used --ink-700 (not defined); ensure the
    # gauge track uses a defined surface token instead.
    i = index_html_text.index(".encl-gauge-track")
    block = index_html_text[i : i + 200]
    assert "--ink-700" not in block, "gauge track references undefined --ink-700"
    assert "--surface-raised" in block
