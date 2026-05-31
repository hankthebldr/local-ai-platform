from __future__ import annotations

import argparse
import os
import sys

from .classify import classify
from .collectors.junit import parse_junit
from .emitters.annotations import AnnotationEmitter
from .emitters.github_issues import GitHubIssueEmitter
from .emitters.step_summary import StepSummaryEmitter
from .models import TriageVerdict


def _run_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if run_id else "local run"


def _is_fork_pr() -> bool:
    return os.getenv("TRIAGE_FORK_PR", "false").strip().lower() == "true"


def _run_ci(args) -> int:
    version = os.getenv("ENCLAVE_VERSION", "unknown")
    events, total = parse_junit(args.junit, repo_root=args.repo_root, enclave_version=version)
    run_url = _run_url()
    verdicts: list[TriageVerdict] = []
    for ev in events:
        ev.env["run_url"] = run_url
        sev, cat, summary = classify(ev, total=total, failed=len(events))
        verdicts.append(TriageVerdict(event=ev, severity=sev, category=cat, rule_summary=summary))

    emit = {e.strip() for e in args.emit.split(",") if e.strip()}
    if "annotations" in emit:
        AnnotationEmitter().emit(verdicts)
    if "summary" in emit:
        StepSummaryEmitter().emit(verdicts)
    if "issues" in emit and not args.dry_run:
        if _is_fork_pr():
            print("::notice::fork PR — skipping issue creation (read-only token)")
        else:
            GitHubIssueEmitter(repo=args.repo, max_issues=args.max_issues).emit(verdicts)

    if args.fail_on == "critical" and any(v.severity.value == "critical" for v in verdicts):
        return 2
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="triage")
    sub = p.add_subparsers(dest="cmd", required=True)
    ci = sub.add_parser("ci", help="triage a JUnit XML report")
    ci.add_argument("--junit", required=True)
    ci.add_argument("--emit", default="annotations,summary,issues")
    ci.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    ci.add_argument("--repo-root", default=os.getcwd())
    ci.add_argument("--dry-run", action="store_true")
    ci.add_argument("--fail-on", choices=["none", "critical"], default="none")
    ci.add_argument(
        "--max-issues",
        type=int,
        default=10,
        help="cap issues filed per run (GitHub rate-limit guard)",
    )
    args = p.parse_args(argv)
    if args.cmd == "ci":
        return _run_ci(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
