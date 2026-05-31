from __future__ import annotations

import json

from triage.emitters.github_issues import GitHubIssueEmitter, MARKER
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v(fp="abc123", sev=Severity.high):
    ev = FailureEvent(
        source="ci",
        exception_type="AssertionError",
        message="boom",
        test_id="t::a",
        fingerprint=fp,
    )
    return TriageVerdict(
        event=ev, severity=sev, category=Category.assertion, rule_summary="regression"
    )


class FakeGh:
    """Records gh calls. `existing` maps fingerprint -> issue number (pre-existing open issues)."""

    def __init__(self, existing=None):
        self.calls = []
        self._existing = existing or {}

    def __call__(self, args):
        self.calls.append(args)
        if "list" in args:
            return json.dumps(
                [
                    {"number": n, "body": MARKER.format(fp=fp)}
                    for fp, n in self._existing.items()
                ]
            )
        return ""


def test_lists_once_then_creates_no_per_fingerprint_search():
    gh = FakeGh(existing={})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit([_v()])
    assert sum(1 for c in gh.calls if "list" in c) == 1
    assert not any("--search" in c for c in gh.calls)
    create = [c for c in gh.calls if "create" in c]
    assert len(create) == 1 and "--label" in create[0]


def test_recurrence_comments_not_duplicates():
    gh = FakeGh(existing={"abc123": 7})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit([_v()])
    assert any("comment" in c for c in gh.calls)
    assert not any("create" in c for c in gh.calls)


def test_dedupe_collapses_same_fingerprint_to_one_create():
    gh = FakeGh(existing={})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit(
        [_v(fp="dup"), _v(fp="dup"), _v(fp="dup")]
    )
    assert sum(1 for c in gh.calls if "create" in c) == 1


def test_caps_issues_per_run_and_warns(capsys):
    gh = FakeGh(existing={})
    verdicts = [_v(fp=f"fp{i}") for i in range(5)]
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0, max_issues=2).emit(verdicts)
    assert sum(1 for c in gh.calls if "create" in c) == 2
    assert "3 more distinct failures not filed" in capsys.readouterr().out


def test_api_error_stops_without_retry_storm(capsys):
    class BoomGh(FakeGh):
        def __call__(self, args):
            if "create" in args:
                self.calls.append(args)
                raise RuntimeError("API rate limit exceeded")
            return super().__call__(args)

    gh = BoomGh(existing={})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit(
        [_v(fp="a"), _v(fp="b")]
    )
    assert sum(1 for c in gh.calls if "create" in c) == 1
    assert "stopped" in capsys.readouterr().out


def test_dry_run_emits_nothing(capsys):
    gh = FakeGh()
    GitHubIssueEmitter(repo="o/r", dry_run=True, runner=gh).emit([_v()])
    assert gh.calls == []
    assert "dry-run" in capsys.readouterr().out
