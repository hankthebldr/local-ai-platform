# Prompt Output CI/CD — Design Proposal

> **Status:** draft · 2026-05-18 · author: live-demo prep · target: 1.3.x
>
> **Audience:** Henry; contributors writing workflows, agents, and prompts.
>
> **Goal:** prevent "the prompt change that broke the XDM rule generator from
> a year ago" by treating prompts (system prompts, agent YAML, workflow YAML)
> as **versioned artifacts with eval-gated promotion**. Same discipline as
> source code: PR → eval suite → reviewer signoff → merge → production.

---

## 1. What we're solving

The Enclave system today has *generative* artifacts everywhere:
- Workflow YAMLs (`workflows/*.yaml`)
- Agent definitions (`agents/*.yaml`)
- Role prompts (`prompts/roles/*.md`)
- Skills (`plugins/<name>/skills/*.md`)
- Output-parser configs (per step)
- Quality-gate definitions (per step)

A change to any of these can silently degrade the quality of every downstream
output. There's no test gate: a contributor can edit the
`xql-data-model-engineer` system prompt, push to master, and ship a regression
that only shows up days later when someone's actually generating an XDM rule.

Worse — there's no way to compare *what the agent produces today* against
*what it produced last week* without manually re-running and eyeballing.

This proposal adds **three things** parallel to the source-code CI:

1. **Golden cases** — pinned inputs + expected output shapes per agent/workflow.
2. **Eval runner** — executes a prompt/agent/workflow against its golden cases,
   scores the output via deterministic + LLM-judge checks.
3. **PR gate** — on every PR that touches a generative artifact, run the
   relevant golden cases and post the eval delta as a PR comment.

---

## 2. The "what changed in the output" problem

Today if you change `xql-snippet-curator.yaml`:

```diff
- temperature: 0.2
+ temperature: 0.4
```

You don't know:
- Whether the agent's existing 17 golden test cases still pass
- Whether the new temperature improves or degrades the structured output
- Whether the change costs more tokens on average
- Whether response times changed materially

The reviewer's only signal is "the agent's YAML changed; does it still work?"
Manual sampling is unreliable; nobody runs all 17 cases by hand.

CI for prompts means: every diff to `agents/*.yaml`, `workflows/*.yaml`,
`prompts/roles/*.md`, or `plugins/*/skills/*.md` triggers a fresh eval run.
The PR comment shows the delta.

---

## 3. Golden case format

Per-agent golden cases live at `agents/<id>.eval.yaml`:

```yaml
# agents/xql-data-model-engineer.eval.yaml
agent: xql-data-model-engineer
cases:
  - id: cisco-asa-failed-auth
    description: Cisco ASA failed-auth syslog → XDM rule with all canonical paths
    seed:
      messages:
        - role: user
          content: |
            <46>Apr 18 14:23:11 fw-01-edge ASA-6-113005: AAA user authentication
            Rejected : reason = Invalid password : server = 10.20.30.5 :
            user = "alice" : user IP = 198.51.100.42 : NAS IP = 10.20.30.1
    expects:
      # Deterministic regex/string checks — fast, free, no LLM judge.
      contains:
        - "[MODEL: xdm_auth_event]"
        - "xdm.auth.outcome"
        - "xdm.source.user.username"
        - "xdm.source.ipv4"
        - "regextract"
      excludes:
        - "xdm.foo.bar"          # invented paths must NEVER appear
        - "TODO"
        - "I'm sorry"             # refusal patterns
      min_length: 400
      max_length: 4000
      # LLM-judge checks — slow but catches structural correctness.
      judge:
        - prompt: |
            Does this XQL data model rule extract the user, source IP, target
            host, and outcome from the input log? Answer yes or no, then a
            one-sentence explanation.
          expect: yes
        - prompt: |
            Are all xdm.* paths the canonical ones from XDM v3? Answer yes or no.
          expect: yes
    budget:
      max_tokens_completion: 1024
      max_wall_seconds: 180
```

Per-workflow golden cases at `workflows/<id>.eval.yaml`:

```yaml
workflow: xsiam-data-model-rules
cases:
  - id: vmware-vcenter-login
    description: vCenter login event → 5-step pipeline produces complete pack
    seed:
      vendor: vmware-vcenter
      sample_log: <verbatim raw log>
      existing_packs: []
    expects:
      # Step-by-step assertions — each step's output is checked.
      steps:
        analyze_source:
          contains: ["vCenter", "vmware"]
          excludes: ["unknown", "I don't know"]
        normalize_xdm:
          contains: ["xdm.event.type", "xdm.source.user.username"]
        generate_rules:
          contains: ["[MODEL:", "filter", "alter"]
          min_length: 500
      # Final state-of-the-world check.
      final:
        all_steps_completed: true
        no_quality_gate_failures: true
```

---

## 4. Eval runner

A standalone CLI + library:

```
scripts/eval-prompts.sh xql-data-model-engineer       # one agent
scripts/eval-prompts.sh --workflow xsiam-data-model-rules
scripts/eval-prompts.sh --changed-only                # only what git diff touched
scripts/eval-prompts.sh --baseline=main               # compare against another ref
```

Output (always `data/evals/runs/<timestamp>/`):

```
results.json          — machine-readable scorecard
report.md             — human-readable summary
diffs/                — per-case input + expected + actual
```

`results.json` shape:

```json
{
  "ref": "fix/composer-chat-agent-response-shape@8889eae",
  "started_at": "2026-05-18T19:30:00Z",
  "agent_results": {
    "xql-data-model-engineer": {
      "pass": 14,
      "fail": 3,
      "cases": [
        {
          "id": "cisco-asa-failed-auth",
          "status": "pass",
          "deterministic_score": 5,
          "judge_score": 2,
          "tokens_completion": 387,
          "wall_seconds": 92.3,
          "diff_vs_baseline": null
        }
      ]
    }
  },
  "regression_summary": {
    "newly_failing": ["xql-data-model-engineer/zscaler-deny-action"],
    "newly_passing": [],
    "judge_score_delta": -0.4,
    "token_count_delta": +120
  }
}
```

---

## 5. PR gate (GitHub Actions)

`.github/workflows/eval-prompts.yml`:

```yaml
name: Eval Prompts
on:
  pull_request:
    paths:
      - 'agents/**'
      - 'workflows/**'
      - 'prompts/**'
      - 'plugins/*/skills/**'
      - 'docs/seed/**'    # grounding-corpus changes are also prompt-affecting

jobs:
  eval:
    runs-on: self-hosted  # needs Ollama + the model registry
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Identify what changed
        id: changed
        run: |
          git diff --name-only origin/${{ github.base_ref }}...HEAD \
            | grep -E '^(agents|workflows|prompts|plugins/.+/skills|docs/seed)/' \
            > changed.txt
      - name: Run eval suite on the changed artifacts
        run: scripts/eval-prompts.sh --paths-file=changed.txt --baseline=origin/${{ github.base_ref }}
      - name: Post results as PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const md = fs.readFileSync('data/evals/runs/latest/report.md', 'utf-8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: md
            });
      - name: Fail on regression
        run: |
          if [ "$(jq '.regression_summary.newly_failing | length' data/evals/runs/latest/results.json)" -gt 0 ]; then
            echo "::error::Prompt change regressed existing golden cases"
            exit 1
          fi
```

**Self-hosted runner** is needed because the eval calls real Ollama. Cloud
runners don't have GPU + the model registry. The MS-01 / Blackwell workstation
is the natural runner.

---

## 6. PR comment example

The comment posted to PRs that touch prompts:

```
## Prompt eval — `fix/xql-tweaks` vs `master`

| Agent | Pass / Total | Δ vs baseline | Avg tokens | Avg wall |
|---|---|---|---|---|
| xql-data-model-engineer | 14 / 17 | **🟡 -1** | 387 (+12) | 92.3 s (+4.1) |
| xql-snippet-curator     | 22 / 22 |  0       | 156       | 31.0 s   |

### ⚠ Newly failing
- `xql-data-model-engineer/zscaler-deny-action`
  - Expected `contains: ["xdm.auth.outcome"]`
  - Actual: missing `xdm.auth.outcome` (used `xdm.event.outcome` only)
  - [Diff →](https://link/to/case/diff)

### 🟢 Improvements
- 3 cases now produce shorter output (-50 to -120 tokens)
- xql-snippet-curator wall-clock down 8% (warmer model? double-check)

🤖 Generated by eval-prompts.sh · `data/evals/runs/2026-05-18T19:30:00/`
```

Regressions block merge. Improvements show as 🟢. Reviewer signs off knowing
exactly what changed.

---

## 7. Three eval check types

| Type | Speed | Cost | When useful |
|---|---|---|---|
| **Deterministic** | <1ms per check | $0 | Regex / contains / excludes / length. Catches structural failures fast. The default for every case. |
| **LLM judge** | 5-15s per check | tokens | "Is this XQL semantically correct?" The expensive but most valuable check. Run on PR, not on every commit. |
| **Diff vs baseline** | <100ms | $0 | Byte-for-byte comparison against the last passing run. Catches drift the judges miss. Stored at `data/evals/baselines/<artifact>/<case>.txt`. |

Deterministic checks gate `scripts/eval-prompts.sh --quick` for pre-commit
hooks. The full suite (judges + diffs) runs in the PR gate only.

---

## 8. Implementation phases

**Phase 1 (≈2 days):** runner + golden case format
- `scripts/eval-prompts.sh` (Python wrapper around `api/services/eval.py`)
- `api/services/eval.py` — case loader, deterministic check runner
- Golden cases for the 5 existing agents (~10 cases each = 50 cases)
- Output: `data/evals/runs/<ts>/results.json` + `report.md`

**Phase 2 (≈1 day):** judge integration
- Hook in `OllamaService.chat()` for judge calls (use a separate model
  pinned to `JUDGE_MODEL=llama3.2:3b` env var)
- Add `judge:` sections to the highest-value cases
- Cache judge results per (case, content-hash) so re-running with the same
  agent output is free

**Phase 3 (≈1 day):** PR gate
- GitHub Action above
- Self-hosted runner setup doc (target: BD790i or Blackwell workstation)
- Reviewer guide: how to read the comment, when to override the gate

**Phase 4 (≈2 days):** baselines + drift detection
- `data/evals/baselines/` populated by every merge to master
- `--baseline` flag enables byte-level diffing
- Drift report when output changes meaningfully but all checks still pass

**Total:** ~6 dev days. Phase 1 alone gates regressions on contributor PRs.

---

## 9. Cross-cutting concerns

**Determinism.** LLM outputs are stochastic. The eval runner pins
`temperature=0` and `seed=42` per case (when the model supports it). Judges
also run with temperature=0. Goldens drift over time as models change; that's
expected — the `--update-baseline` flag refreshes the stored baseline when
the reviewer accepts intentional drift.

**Cost.** Running 50 cases × 5 judges × ~2k tokens each = ~500k tokens per
PR run. On a self-hosted runner with `llama3.2:3b` (free, local), that's just
wall-clock cost — about 8-12 min per PR for a thorough run.

**Local-first.** The whole eval suite runs offline on the operator's box.
No cloud APIs, no telemetry. Matches the existing privacy stance.

**Composability with the trace system** (the *other* design doc). Every eval
case run emits the same NDJSON trace events as a production run. The eval
runner's report can link directly to the trace explorer UI — "this case took
92.3 s; here's the flame chart" → click → trace view.

---

## 10. Open questions for Henry

- Should goldens for `xsiam-detection-engineering`-style workflows ship in the
  public repo, or live in `workflows-private/.evals/` (since the methodology
  is high-value)? Public goldens give CI value to contributors; private
  goldens protect the IP.
- Do we want a `LICENSE_KEY` env-var gate on the LLM-judge calls so
  contributors without a model can still run the deterministic suite?
- For the judge model: pin to one (`llama3.2:3b`) for determinism, or rotate
  among a small pool (`llama3.2:3b`, `qwen2.5:3b`, `phi3.5:3.8b`) and majority-
  vote? Pool is more robust but ~3x cost.
- Should baseline files be committed to git (`.txt` diffable) or stored
  out-of-band (S3 / private repo)? Committed is simpler; OOB scales better to
  large outputs.
