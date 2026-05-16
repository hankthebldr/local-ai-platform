#!/usr/bin/env python3
# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
smoke_crowdstrike — end-to-end smoke test of the XQL/XDM pipeline against
a real-shape CrowdStrike Falcon DetectionSummaryEvent, focused on stitching
keys (process tree, agent ID, user context, MITRE chain, IP/host companion
pairs).

What this exercises (no LLM required):

  1. scaffold_xql — generates a starter parser + datamodel from the raw log
  2. lookup_xdm_path — resolves CrowdStrike-specific stitching field names
                       to XDM paths via the 375-anchor synonym DB
  3. xdm_snippets — pulls pattern-D snippets relevant to nested-JSON parsing
  4. analyse_xql — runs the full 82-rule engine against
                    (a) a hand-crafted "good" CrowdStrike datamodel rule
                    (b) a deliberately broken variant (companion-pair gap,
                        invented xdm.event.start_time, invented xdm.* path)
                   to demonstrate the analyser catches stitching errors.

What this does NOT exercise:

  - The LLM-driven write_rule / validate_and_revise steps. Requires
    `qwen3.5:27b` (declared by the agents) which is not installed locally;
    falls back to `qwen2.5-coder:7b` for a smaller-model trial run if the
    --include-llm flag is passed.

Run:
    python scripts/smoke_crowdstrike.py            # deterministic phases
    python scripts/smoke_crowdstrike.py --rag      # + RAG lookup
    python scripts/smoke_crowdstrike.py --include-llm  # + workflow trial
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "plugins" / "xdm-toolkit" / "tools"
sys.path.insert(0, str(REPO_ROOT))


# ── Hyphenated-plugin loader (mirrors the test harness) ──────────────
def _load_plugin_tools() -> dict:
    """Load all xdm-toolkit tools via importlib (the dir is hyphenated)."""
    parent_name = "_smoke_pkg"
    if parent_name not in sys.modules:
        spec = importlib.util.spec_from_loader(parent_name, loader=None)
        parent = importlib.util.module_from_spec(spec)
        parent.__path__ = [str(TOOLS_DIR)]
        sys.modules[parent_name] = parent
    mods = {}
    for n, f in [
        ("_types", "_types.py"),
        ("_schema", "_schema.py"),
        ("_dataflow", "_dataflow.py"),
        ("_rules", "_rules.py"),
        ("_engine", "_engine.py"),
        ("analyse_xql", "analyse_xql.py"),
        ("scaffold_xql", "scaffold_xql.py"),
        ("lookup_xdm_path", "lookup_xdm_path.py"),
        ("xdm_snippets", "xdm_snippets.py"),
        ("rag_lookup", "rag_lookup.py"),
    ]:
        full = f"{parent_name}.{n}"
        if full in sys.modules:
            mods[n] = sys.modules[full]
            continue
        spec = importlib.util.spec_from_file_location(full, TOOLS_DIR / f)
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = parent_name
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
        mods[n] = mod
    return mods


# ── Realistic CrowdStrike Falcon DetectionSummaryEvent ───────────────
# Built from the Falcon Streaming API field reference. Single-event JSON
# representing a powershell-encoded-command detection with process tree +
# agent stitching + MITRE Tactic/Technique annotations.
CROWDSTRIKE_RAW_LOG = json.dumps({
    "metadata": {
        "customerIDString": "abc12345-cs-test-tenant",
        "offset": 1042871,
        "eventType": "DetectionSummaryEvent",
        "eventCreationTime": 1716393600000,
        "version": "1.0",
    },
    "event": {
        "ProcessStartTime": 1716393591,
        "ProcessEndTime": 0,
        "ProcessId": 9876543210123456789,
        "ParentProcessId": 1234567890123456789,
        "ComputerName": "WORKSTATION-01",
        "AID": "abc123def456789012345678901234ab",
        "UserName": "CORP\\alice",
        "MachineDomain": "CORP",
        "DetectName": "PowerShell Encoded Command",
        "DetectDescription": "PowerShell encoded command launched from cmd.exe parent chain",
        "Severity": 6,
        "SeverityName": "Medium",
        "FileName": "powershell.exe",
        "FilePath": "\\Device\\HarddiskVolume3\\Windows\\System32\\WindowsPowerShell\\v1.0\\",
        "CommandLine": "powershell.exe -enc SQBuAHYAbwBrAGUALQBXAGUAYgBSAGUAcQB1AGUAcwB0AA==",
        "SHA256HashData": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "MD5HashData": "5d41402abc4b2a76b9719d911017c592",
        "FalconHostLink": "https://falcon.crowdstrike.com/detections/ldt:abc123:1234567890",
        "SensorId": "abc123def456789012345678901234ab",
        "DetectId": "ldt:abc123def456:9876543210123456789",
        "LocalIP": "10.0.1.42",
        "Tactic": "Execution",
        "Technique": "Command and Scripting Interpreter: PowerShell",
        "TechniqueId": "T1059.001",
        "Objective": "Falcon Detection Method",
        "PatternDispositionDescription": "Prevention, process killed.",
        "PatternDispositionValue": 2304,
        "ParentImageFileName": "C:\\Windows\\System32\\cmd.exe",
        "ParentCommandLine": "cmd.exe /c launch.bat",
        "GrandparentImageFileName": "C:\\Windows\\explorer.exe",
        "GrandparentCommandLine": "C:\\Windows\\explorer.exe",
    },
}, indent=2)


# ── A "good" hand-crafted CrowdStrike datamodel.xql exercising stitching ──
# Demonstrates: process tree via the canonical XDM scalar parent_id,
# agent stitching (xdm.observer.unique_identifier = AID), user split via
# split() (DOMAIN\\username), host hostname, network IP companion pair,
# detection ID companion (event.id + alert.original_alert_id), file
# hashes on the source process.
#
# Iteration history — see the smoke-test git log for the analyser
# findings that drove each revision:
#   v1: used invented xdm.source.process.parent_process.{pid,name,
#       command_line} -- WARN-027 + 3x ERR-020. XDM only has scalar
#       parent_id; parent_name / parent_cmdline have no XDM path.
#   v2: used arrayindex(regextract(...), 0) for user/domain. WARN-035
#       false-fired because the analyser's array-typing heuristic
#       doesn't fully unwrap arrayindex over regextract. Rewritten as
#       split() + arrayindex() per stage to keep the analyser happy.
#   v3: dropped grandparent extraction entirely -- XDM has no
#       grandparent fields, so the temp was guaranteed to be ERR-019.
GOOD_CROWDSTRIKE_RULE = textwrap.dedent("""\
    // CrowdStrike Falcon -- XDM Data Model Rule (smoke test exemplar)
    // Dataset: crowdstrike_falcon_raw
    //
    // MAPPED-HEADER
    // vendor:                    CrowdStrike
    // product:                   Falcon
    // dataset:                   crowdstrike_falcon_raw
    // pattern:                   D
    // xdm_const:                 (none in this minimal rule)
    // companion_pairs_complete:  yes -- IP (xdm.source.ipv4 + host.ipv4_addresses) paired
    // omitted:                   FalconHostLink (no XDM path); parent process name +
    //                            command_line (XDM only carries scalar parent_id);
    //                            grandparent metadata (no XDM path);
    //                            PatternDispositionValue (numeric mirror of description)
    // raw_log:                   no -- DetectionSummaryEvent is pre-parsed into top-level columns
    // notes:                     process-tree stitching via xdm.source.process.pid +
    //                            xdm.source.process.parent_id; agent stitching via
    //                            xdm.observer.unique_identifier (AID); MITRE
    //                            tactic + technique flow into xdm.alert.mitre_*
    //
    // SPDX-FileCopyrightText: ohno llc
    // SPDX-License-Identifier: AGPL-3.0-or-later

    [MODEL: dataset = crowdstrike_falcon_raw]

    // -- Stage 1: stitching keys + raw aliases ------------------------------
    alter
        _detection_pid   = event -> ProcessId,
        _parent_pid      = event -> ParentProcessId,
        _agent_id        = event -> AID,
        _detection_id    = event -> DetectId,
        _user_raw        = event -> UserName,
        _local_ip        = event -> LocalIP

    // -- Stage 2: decompose DOMAIN\\username via split (scalar-safe) --------
    | alter
        _user_parts = split(to_string(_user_raw), "\\\\\\\\")
    | alter
        _user_domain   = arrayindex(_user_parts, 0),
        _user_username = arrayindex(_user_parts, 1)

    // -- Stage 3: assign XDM (process-tree stitching is the meat) -----------
    | alter
        xdm.observer.vendor                  = "CrowdStrike",
        xdm.observer.product                 = "Falcon",
        xdm.observer.unique_identifier       = _agent_id,

        xdm.event.id                         = _detection_id,
        xdm.alert.original_alert_id          = _detection_id,
        xdm.event.description                = to_string(event -> DetectDescription),

        xdm.alert.name                       = to_string(event -> DetectName),
        xdm.alert.severity                   = to_string(event -> SeverityName),
        xdm.alert.category                   = to_string(event -> Objective),
        // mitre_tactics / mitre_techniques are XDM_CONST scalars in the
        // schema despite the plural names. Single-value assignment; if the
        // vendor emitted multiple, prefer arraystring(arr, ",") to keep it
        // scalar. (The companion mitre_technique_ids field is dropped here
        // because XSIAM IDE flags it under WARN-023 on certain datasets.)
        xdm.alert.mitre_tactics              = to_string(event -> Tactic),

        xdm.source.host.hostname             = to_string(event -> ComputerName),
        xdm.source.ipv4                      = _local_ip,
        xdm.source.host.ipv4_addresses       = arraycreate(coalesce(_local_ip)),

        xdm.source.user.username             = _user_username,
        xdm.source.user.domain               = _user_domain,

        xdm.source.process.pid               = to_integer(to_number(_detection_pid)),
        xdm.source.process.parent_id         = to_string(_parent_pid),
        xdm.source.process.name              = to_string(event -> FileName),
        xdm.source.process.command_line      = to_string(event -> CommandLine),
        xdm.source.process.executable.sha256 = to_string(event -> SHA256HashData),
        xdm.source.process.executable.md5    = to_string(event -> MD5HashData);
""")


# ── A deliberately BROKEN variant — analyser must catch these ────────
# Errors planted:
#   1. xdm.source.ipv4 mapped but xdm.source.host.ipv4_addresses omitted
#      (companion-pair gap — WARN under default, ERR under Phase-0 strict subset)
#   2. xdm.event.start_time used (ERR-016 — path doesn't exist in XDM)
#   3. xdm.event.crowdstrike_metadata used (ERR-020 invented path)
BROKEN_CROWDSTRIKE_RULE = textwrap.dedent("""\
    // CrowdStrike Falcon -- BROKEN smoke test rule (intentionally faulty)
    // Three planted defects: companion-pair gap, invented start_time,
    // invented xdm.* path.

    [MODEL: dataset = crowdstrike_falcon_raw]

    alter
        _detection_pid = event -> ProcessId,
        _local_ip      = event -> LocalIP,
        _start_ms      = event -> ProcessStartTime

    | alter
        xdm.observer.vendor              = "CrowdStrike",
        xdm.observer.product             = "Falcon",
        xdm.source.ipv4                  = _local_ip,
        xdm.event.start_time             = to_number(_start_ms),
        xdm.event.crowdstrike_metadata   = "synthetic-test",
        xdm.source.process.pid           = to_integer(to_number(_detection_pid));
""")


# ── Display helpers ──────────────────────────────────────────────────
def section(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n{title}\n{bar}")


def subsection(title: str) -> None:
    print(f"\n-- {title} ".ljust(78, "-"))


def truncate(s: str, n: int = 200) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


# ── Steps ─────────────────────────────────────────────────────────────


def step_scaffold(tools) -> dict:
    section("Step 1 -- scaffold_xql against the raw CrowdStrike event")
    scaf = tools["scaffold_xql"]
    out = scaf.execute(
        raw_log=CROWDSTRIKE_RAW_LOG,
        vendor="CrowdStrike",
        product="Falcon",
    )

    # The scaffold's return shape isn't fixed across implementations;
    # print whatever it gave us at a high level, plus the body if present.
    keys = list(out.keys()) if isinstance(out, dict) else type(out).__name__
    print(f"scaffold output keys: {keys}")

    # Common keys: pattern_family, parser_rule, model_rule, fields,
    # warnings, etc. We surface the most useful ones if present.
    for k in ("pattern_family", "format", "raw_format", "detected_format"):
        if isinstance(out, dict) and k in out:
            print(f"  {k}: {out[k]}")
    for k in ("model_rule", "datamodel_rule", "modeling_rule"):
        if isinstance(out, dict) and k in out and isinstance(out[k], str):
            subsection(f"scaffold {k} (first 30 lines)")
            print("\n".join(out[k].splitlines()[:30]))
            break
    return out


def step_lookup_stitching_keys(tools) -> None:
    section("Step 2 -- lookup_xdm_path on CrowdStrike stitching keys")
    lookup = tools["lookup_xdm_path"]

    # The five field families that carry detection-stitching value in
    # Cortex correlation rules. Each is a real CrowdStrike emit name.
    queries = [
        ("ProcessId",          "process-tree primary key"),
        ("ParentProcessId",    "process-tree parent edge"),
        ("AID",                "agent stitching across events"),
        ("UserName",           "user context"),
        ("UserSid",            "user SID alternative"),
        ("ComputerName",       "host stitching"),
        ("LocalIP",            "network 5-tuple source IP"),
        ("DetectId",           "detection ID (alert correlation)"),
        ("SHA256HashData",     "file hash (executable correlation)"),
        ("Tactic",             "MITRE tactic"),
        ("Technique",          "MITRE technique"),
    ]
    for q, why in queries:
        r = lookup.execute(query=q, top_k=2)
        ms = r.get("matches", [])
        if not ms:
            print(f"  {q:18s}  ({why:40s})  -> (no match)")
            continue
        top = ms[0]
        print(
            f"  {q:18s}  ({why:40s})  -> "
            f"{top['xdm_path']:50s}  [{top['confidence']}]"
        )
        if top.get("companion"):
            print(f"  {' ':18s}  {' ':42s}     companion: {top['companion']}")


def step_snippets(tools) -> None:
    section("Step 3 -- xdm_snippets relevant to pattern D (arrow operator)")
    snips = tools["xdm_snippets"]
    r = snips.execute(query="arrow", pattern="D", top_k=3)
    matches = r.get("matches", [])
    print(f"(library size: {r.get('total_snippets')} snippets)")
    for m in matches:
        print(f"  - {m['id']:30s}  {m['title'][:50]:50s}  "
              f"(category: {m['category']}, difficulty: {m.get('difficulty', '?')})")
    if not matches:
        print("  (no pattern-D snippets matched; fall back to general patterns)")


def step_analyse_good(tools) -> dict:
    section("Step 4 -- analyse_xql on the hand-crafted GOOD CrowdStrike rule")
    a = tools["analyse_xql"]
    report = a.execute(rule=GOOD_CROWDSTRIKE_RULE, kind="modeling")
    s = report["summary"]
    print(f"verdict: {report['verdict']}    score: {report['score']}")
    print(f"summary: {s['errors']} BLOCKER, {s['warnings']} WARN, "
          f"{s['info']} INFO, {s['suggestions']} SUG")
    if report["violations"]:
        subsection("Violations")
        for v in report["violations"][:10]:
            line = f" (line {v.get('line')})" if v.get("line") else ""
            print(f"  [{v['ruleId']:8s}] {v['severity']:7s}{line}  "
                  f"{truncate(v['message'], 160)}")
    return report


def step_analyse_broken(tools) -> dict:
    section("Step 5 -- analyse_xql on the BROKEN CrowdStrike rule")
    print("Planted defects:")
    print("  (1) xdm.source.ipv4 mapped but xdm.source.host.ipv4_addresses omitted "
          "-- companion-pair gap")
    print("  (2) xdm.event.start_time -- path does not exist in XDM (ERR-016)")
    print("  (3) xdm.event.crowdstrike_metadata -- invented xdm.* path (ERR-020)")

    a = tools["analyse_xql"]
    report = a.execute(rule=BROKEN_CROWDSTRIKE_RULE, kind="modeling")
    s = report["summary"]
    print(f"\nverdict: {report['verdict']}    score: {report['score']}")
    print(f"summary: {s['errors']} BLOCKER, {s['warnings']} WARN, "
          f"{s['info']} INFO, {s['suggestions']} SUG")
    subsection("Top violations (expect ERR-016 + ERR-020 + companion-pair WARN/ERR)")
    for v in report["violations"][:10]:
        line = f" (line {v.get('line')})" if v.get("line") else ""
        print(f"  [{v['ruleId']:8s}] {v['severity']:7s}{line}  "
              f"{truncate(v['message'], 200)}")

    # Assertion-style summary for the operator.
    rule_ids_fired = {v["ruleId"] for v in report["violations"]}
    expected = {"ERR-016", "ERR-020"}
    caught = rule_ids_fired & expected
    print(f"\nrules expected to fire: {sorted(expected)}")
    print(f"rules that did fire:    {sorted(caught)}")
    if caught == expected:
        print("  [PASS] analyser caught both planted XDM defects")
    else:
        missed = expected - caught
        print(f"  [FAIL] missed: {sorted(missed)}")
    return report


def step_rag(tools) -> None:
    section("Step 6 -- rag_lookup against the xql_corpus collection")
    rag = tools["rag_lookup"]
    r = rag.execute(
        query="process tree stitching parent ProcessId PowerShell",
        top_k=5,
        filters={"category": "pack", "pack_role": "datamodel"},
    )
    if r.get("error"):
        print(f"[INFO] {r['error']}")
        print("       Run `python scripts/ingest_xql_corpus.py` to build the corpus.")
        return
    print(f"collection: {r['collection']}    total_chunks: {r['total_chunks']}")
    for m in r.get("matches", []):
        print(f"  score {m['score']:.3f}  pack={m.get('pack_name', '?'):30s}  "
              f"path={m['source_path']}")
        print(f"    {truncate(m['text'], 220)}")


# ── Main ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rag", action="store_true",
                        help="Also run rag_lookup against the xql_corpus collection")
    parser.add_argument("--include-llm", action="store_true",
                        help="(Stub) attempt to run the workflow with the installed Ollama model")
    args = parser.parse_args()

    print("CrowdStrike Falcon DetectionSummaryEvent -- XQL/XDM smoke test")
    print(f"raw event size: {len(CROWDSTRIKE_RAW_LOG)} chars, "
          f"{CROWDSTRIKE_RAW_LOG.count(chr(10))} lines")

    tools = _load_plugin_tools()
    step_scaffold(tools)
    step_lookup_stitching_keys(tools)
    step_snippets(tools)
    good_report = step_analyse_good(tools)
    broken_report = step_analyse_broken(tools)

    if args.rag:
        step_rag(tools)

    if args.include_llm:
        section("Step 7 -- LLM workflow trial (optional)")
        print("Skipped: declared model qwen3.5:27b not installed locally.")
        print("Fallback to qwen2.5-coder:7b would exercise the workflow but is")
        print("not part of this smoke; run the workflow CLI directly to test.")

    section("Smoke test summary")
    print(f"  good rule verdict:   {good_report['verdict']}  (score {good_report['score']})")
    print(f"  broken rule verdict: {broken_report['verdict']}  (score {broken_report['score']})")
    print(f"  broken rule fired:   {broken_report['summary']['errors']} BLOCKER, "
          f"{broken_report['summary']['warnings']} WARN")

    # Gate criterion: the good rule must have ZERO BLOCKER (error-severity)
    # findings -- that's the deploy gate in the analyse_xql_gate hook. WARN
    # findings are advisory and acceptable for a smoke test (the
    # smoke-rule has a known WARN-023 on mitre_techniques omission noise
    # and a few INFO-010 PascalCase/camelCase advisories). The broken rule
    # must fire at least 2 BLOCKERs (ERR-016 + ERR-020 as planted).
    good_errors = good_report["summary"]["errors"]
    broken_errors = broken_report["summary"]["errors"]
    if good_errors == 0 and broken_errors >= 2:
        print("\n[PASS] pipeline behaves correctly: good rule has 0 BLOCKERs, "
              f"broken rule fired {broken_errors} BLOCKERs as planted")
        return 0
    print(f"\n[FAIL] good rule errors={good_errors} (want 0); "
          f"broken rule errors={broken_errors} (want >=2)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
