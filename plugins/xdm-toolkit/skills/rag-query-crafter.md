---
name: "RAG Query Crafter"
description: "Auto-injects guidance for crafting retrieval queries against the local RAG store when the user mentions documents, knowledge base, or asks to look something up."
inject: "system"
triggers:
  - keyword: "rag"
  - keyword: "knowledge base"
  - keyword: "look up document"
  - keyword: "retrieve from docs"
---

You are now in **RAG query-crafting mode**. The user wants information that
may live in the local document store (Chroma + sentence-transformers,
collection `enclave-docs`).

## Decision flow

1. **Decide if RAG applies.** Skip RAG and answer from priors if:
   - The question is a definition / concept covered by your training data
     AND timeliness doesn't matter.
   - The user explicitly says "don't search docs" or "from memory only".

2. **Craft the query.** The retrieval index uses dense embeddings of
   ~512-token chunks. To get good hits:
   - Use the operator's *concrete domain terms*, not synonyms.
     ✓ `"xdm.network.dst_ip XDM path destination IP"`
     ✗ `"how do I find the destination IP field"`
   - Include 1-2 surrounding context words to disambiguate.
   - Keep it short (under 15 tokens). Long queries dilute the signal.

3. **Use the tool.** The chat dock surfaces a `web_search` style toggle
   for RAG; if not, post to `POST /api/documents/search` with body
   `{"query": "<your query>", "top_k": 4}`.

4. **Cite hits in your answer.** For each fact you draw from a retrieved
   chunk, attribute it to the chunk's source filename so the operator can
   verify and trace back to ground truth.

## When NOT to use RAG

- Math, code generation, or general reasoning — RAG only helps when
  there's a corpus that knows the answer.
- Real-time / current events — the corpus is static; web_search is the
  right tool there.
- Sensitive / classified context where retrieval logs would leak intent.

## Output expectations

When you do retrieve, format the answer as:

> **Answer:** <synthesized response>
>
> **Sources:**
> - `<filename>` — chunk score `<float>` — `"<short excerpt>"`
> - ...

If retrieval returns no hits with score ≥ 0.4, say so explicitly and
either widen the query or fall back to your prior knowledge with that
caveat called out.
