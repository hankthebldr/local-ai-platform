from __future__ import annotations

import json
import re
import subprocess
import time

from ..models import TriageVerdict, Severity

MARKER = "<!-- fp:{fp} -->"
_FP_RE = re.compile(r"<!-- fp:([0-9a-f]+) -->")
_SEVERITY_ORDER = {Severity.critical: 0, Severity.high: 1, Severity.medium: 2, Severity.low: 3}


class GitHubIssueEmitter:
    """Files deduplicated GitHub issues while staying well under GitHub API rate limits:
    ONE `issue list` per run (core REST, never the 30/min search API), in-memory
    fingerprint dedup, a per-run issue cap, throttling between writes, and a hard stop
    on the first API error (no retry storm)."""

    def __init__(
        self,
        *,
        repo: str | None = None,
        dry_run: bool = False,
        runner=None,
        max_issues: int = 10,
        throttle_s: float = 1.0,
    ):
        self.repo = repo
        self.dry_run = dry_run
        self.max_issues = max_issues
        self.throttle_s = throttle_s
        self._run = runner or self._default_run

    def _default_run(self, args: list[str]) -> str:
        return subprocess.run(args, capture_output=True, text=True, check=True).stdout

    def _gh(self, *args: str) -> str:
        cmd = ["gh", *args]
        if self.repo:
            cmd += ["--repo", self.repo]
        return self._run(cmd)

    def emit(self, verdicts: list[TriageVerdict]) -> None:
        deduped = self._dedupe(verdicts)
        if self.dry_run:
            for v in deduped:
                print(f"[dry-run] would emit issue for fp={v.event.fingerprint} ({v.severity.value})")
            return
        existing = self._existing_map()  # ONE list call — never per-fingerprint search
        ranked = sorted(deduped, key=lambda v: _SEVERITY_ORDER.get(v.severity, 9))
        capped, suppressed = ranked[: self.max_issues], ranked[self.max_issues :]
        for i, v in enumerate(capped):
            try:
                self._emit_one(v, existing)
            except Exception as exc:  # rate limit / API failure → stop, don't retry-storm
                print(
                    f"::warning::triage issue emit stopped after {i} issue(s) (GitHub API error: {exc})"
                )
                return
            if self.throttle_s and i < len(capped) - 1:
                time.sleep(self.throttle_s)
        if suppressed:
            fps = ", ".join(v.event.fingerprint for v in suppressed)
            print(
                f"::warning::{len(suppressed)} more distinct failures not filed this run "
                f"(cap={self.max_issues}, avoids GitHub rate limits): {fps}"
            )

    def _dedupe(self, verdicts: list[TriageVerdict]) -> list[TriageVerdict]:
        by_fp: dict[str, TriageVerdict] = {}
        for v in verdicts:
            fp = v.event.fingerprint
            if fp in by_fp:
                by_fp[fp].seen_count += 1
            else:
                by_fp[fp] = v
        return list(by_fp.values())

    def _existing_map(self) -> dict[str, int]:
        out = self._gh(
            "issue",
            "list",
            "--label",
            "triage:auto",
            "--state",
            "open",
            "--json",
            "number,body",
            "--limit",
            "100",
        )
        mapping: dict[str, int] = {}
        for issue in json.loads(out or "[]"):
            m = _FP_RE.search(issue.get("body") or "")
            if m:
                mapping[m.group(1)] = issue["number"]
        return mapping

    def _emit_one(self, v: TriageVerdict, existing: dict[str, int]) -> None:
        fp = v.event.fingerprint
        if fp in existing:
            self._gh("issue", "comment", str(existing[fp]), "--body", self._recurrence_body(v))
        else:
            self._gh(
                "issue",
                "create",
                "--title",
                self._title(v),
                "--body",
                self._body(v),
                "--label",
                self._labels(v),
            )

    def _title(self, v: TriageVerdict) -> str:
        return f"[{v.severity.value}] {v.category.value}: {v.event.message[:80]}"

    def _labels(self, v: TriageVerdict) -> str:
        return f"bug,triage:auto,severity:{v.severity.value},category:{v.category.value}"

    def _recurrence_body(self, v: TriageVerdict) -> str:
        run = v.event.env.get("run_url", "a recent run")
        return f"Recurred in {run}. Severity `{v.severity.value}`."

    def _body(self, v: TriageVerdict) -> str:
        ev = v.event
        enr = ""
        if v.enriched:
            enr = f"\n**Likely cause:** {v.likely_cause}\n**First check:** {v.first_check}\n"
        return (
            f"{MARKER.format(fp=ev.fingerprint)}\n\n"
            f"### Description\nAuto-filed by triage. {v.rule_summary}\n{enr}\n"
            f"### Location\n`{ev.test_id or ev.route or '—'}` ({ev.file or '?'}:{ev.line or '?'})\n\n"
            f"### Environment\n```\n{ev.env}\n```\n\n"
            f"### Logs\n```\n{(ev.traceback or '')[-2000:]}\n```\n"
        )
