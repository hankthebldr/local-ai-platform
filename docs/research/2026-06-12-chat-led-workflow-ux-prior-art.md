# Chat-led workflow creation — prior art, mid-2026 (deep-research report)

> **Feeds:** `feat/chat-led-composer` — chat-primary Composer mode where conversations boot into local agentic workflows ("workflow is crystallized conversation").
> **Provenance:** deep-research workflow run `wf_74fb0e62-c58` (2026-06-12). 5 search angles → 21 sources → 103 extracted claims → 25 verified (3-vote adversarial) → 16 confirmed. Synthesis + 9 verification votes lost to a session-limit outage; see [RESEARCH_LOG.md](./RESEARCH_LOG.md) for resume state and the unverified-claim backlog.

## Bottom line

Every verified system converges on the same shape — **system drafts the structure, human explicitly confirms promotion** — and the one study that tested silent background crystallization found users didn't notice it happening and disliked not controlling it. The Boot Sequence promote affordance is on the right side of the evidence; the gap to close is *visibility during* the conversation. The strongest chat-to-DAG node schema in the literature (ALLOY) maps almost 1:1 onto the existing workflow YAML.

## Verified findings (all 3-0 votes)

### ChatGPT Tasks — [OpenAI help](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)
- Promotion is **chat-inferred**: asking in conversation creates the durable scheduled task; ChatGPT can create tasks for itself.
- The artifact is **flat** — Name / Instructions / Schedule. A prompt plus a trigger, no step graph.
- Round-trip is genuinely **bidirectional**: editable from a Tasks page, schedule changes accepted in the originating conversation, and the editor deep-links back to that conversation.

### Custom GPTs — [OpenAI help](https://help.openai.com/en/articles/8554397-creating-a-gpt)
- **Two parallel build surfaces over one artifact**: conversational builder + field-level Configuration view, both writing the same draft.
- Promotion is an **explicit Create/Update button** over an auto-saved draft — not system-inferred.
- Conversation state lands in a **flat fixed schema**; multi-step logic is prose in the instructions field. OpenAI literally recommends hand-written "When X → do Y" steps — no structured DAG. This is the ceiling Enclave's real DAG clears.

### Claude Skills — [Anthropic engineering blog](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- Promotion is **explicit and user-initiated**: ask Claude in-chat to capture what worked into a skill.
- Autonomous self-crystallization was explicitly framed as **future work** as of Oct 2025.

### ALLOY — [arXiv 2510.10049](https://arxiv.org/abs/2510.10049) (strongest precedent)
- Explicit **"Export Workflow" button**; artifact serializes to JSON, auto-converts to an executable script.
- Interaction trace maps to a **DAG of semantic sub-tasks**: each node carries `{name, parent/child deps, required tools, NL prompt}`; execution is topological (Kahn's algorithm). Nearly isomorphic to Enclave's step model.
- Re-use is **adaptation by NL delta**: 12/12 study participants adapted a saved workflow to a new task variant within two attempts.
- **Key failure mode:** workflow was synthesized incrementally during the session and only 2/12 participants noticed it changing — yet most wanted control over generation as it happened. **Silent crystallization without a control affordance is the documented anti-pattern.**

### Low-code LLM (Microsoft) — [arXiv 2304.08103](https://arxiv.org/abs/2304.08103)
- Planning LLM proposes the workflow → **user confirms/edits in a graphical editor** → Executing LLM runs only the confirmed version.
- Defines a six-operation canvas-edit vocabulary: extend step · add/remove steps · rename/edit descriptions · add/remove conditional jumps · drag-reorder · regenerate.

### Workflow extraction from transcripts — [arXiv 2502.17321](https://arxiv.org/abs/2502.17321)
- Direct academic support for "workflow is crystallized conversation": durable dialog workflows recovered from historical conversations via retrieval + QA-CoT structured generation, rather than authored by hand.

## Unverified (verifiers died on session limit — plausible, worth a cheap manual check)

- **n8n AI Workflow Builder**: generates workflows from NL goals end-to-end (node choice, placement, configuration); refinement continues via chat including an "Execute and refine" loop; **canvas state round-trips into chat context** (full workflow definition + mock execution data sent to the LLM each turn, so manual canvas edits survive chat refinement). Source: docs.n8n.io.
- **Cursor Plan Mode**: hybrid promotion (explicit Shift+Tab entry, but system also suggests plan mode on complex tasks); plan crystallizes to a Markdown file with file paths and code references. Source: cursor.com/blog/plan-mode.
- **PromptChainer** (arXiv 2203.06566): the two core authoring pain points are inter-step data transformation scaffolding and multi-granularity debugging (node vs chain) — both predicted failure modes for auto-converting conversational intent into a DAG.
- Low-code LLM's round-trip being one-directional/lossy (canvas serialized back to NL for the executor).

These bear directly on round-trip design — verify before relying on them.

## UX recommendations for Composer

1. **Keep promotion explicit; make crystallization visible.** The convergent verified pattern is draft-by-system, confirm-by-human. ALLOY sharpens it: don't just put a Promote button at the end — render the forming DAG live (sidebar or ghost-nodes on canvas) *while* the conversation runs, so the user watches structure accrete and can intervene. Visible-but-not-committed is the sweet spot.
2. **Adopt the ALLOY node contract for chat→DAG mapping**: each promoted step gets a name, dependency edges, required tools, and the NL prompt distilled from the conversation segment that spawned it. Promotion can target the real workflow model (steps, `depends_on`, Jinja2 prompts) — no parallel representation needed.
3. **Round-trip via one artifact, two surfaces, plus a back-link.** GPT-builder pattern (conversational builder + direct editor over the same draft) plus the ChatGPT Tasks deep-link from artifact back to originating conversation. Store the source-conversation reference on the promoted workflow so "why does this step exist" is always answerable.
4. **Ship adaptation-by-delta.** "Run this again but for X" as an NL edit on a saved workflow was the single best-performing interaction in the verified literature (ALLOY, 12/12). Natural fit for chat-primary.
5. **Differentiate on structure.** Mainstream assistants crystallize to flat prompt-plus-trigger artifacts — confirmed, not assumed. Real decision points (Low-code LLM's conditional-jump edit ops) on a real DAG is the gap Composer actually fills.

## Sources (21 fetched; quality as graded by the harness)

Primary: help.openai.com (×2) · anthropic.com/engineering · arxiv.org 2502.17321 / 2510.10049 / 2304.08103 / 2203.06566 / 2009.11423 · docs.n8n.io · cursor.com/blog/plan-mode
Secondary: journalofaccountancy.com (Claude Skills walkthrough)
Forum: community.n8n.io · community.zapier.com · community.openai.com (scheduled-tasks failure reports)
Blog (use with care): aifire.co · flowhunt.io · rajveer.rathod1301.medium.com · xray.tech · mem0.ai · annikahelendi.substack.com · hackernoon.com
