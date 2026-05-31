from __future__ import annotations

from pathlib import Path

from triage.__main__ import main

FIX = Path(__file__).parent.parent / "fixtures" / "junit"


def test_ci_annotations_and_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "sum.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = main(
        [
            "ci",
            "--junit",
            str(FIX / "single_failure.xml"),
            "--emit",
            "annotations,summary",
            "--repo-root",
            "/repo",
        ]
    )
    assert rc == 0
    assert "::error" in capsys.readouterr().out
    assert "| Severity |" in summary.read_text()


def test_fail_on_critical_returns_nonzero(monkeypatch):
    rc = main(
        [
            "ci",
            "--junit",
            str(FIX / "mass_failure.xml"),
            "--emit",
            "annotations",
            "--fail-on",
            "critical",
        ]
    )
    assert rc == 2


def test_fork_pr_skips_issues(monkeypatch, capsys):
    monkeypatch.setenv("TRIAGE_FORK_PR", "true")
    rc = main(["ci", "--junit", str(FIX / "single_failure.xml"), "--emit", "issues"])
    assert rc == 0
    assert "fork PR" in capsys.readouterr().out
