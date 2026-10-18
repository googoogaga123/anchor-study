# 0003 gpt-5-mini through the apiyi relay for every model call — superseded by 0005

Supersedes 0002.

All model calls — routing, answering, checking, Diagram descriptions, graph
building, PageIndex — use `gpt-5-mini`, reached through apiyi
(`https://api.apiyi.com/v1`), an OpenAI-compatible relay. Search embeddings
stay `text-embedding-3-small`, through the same relay.

The owner's key is an apiyi key, not an OpenAI one: `api.openai.com` rejects it
(401). The relay offers 17 models and GPT-5.6 Luna is not among them. Of the
OpenAI models on offer, `gpt-5-mini` is the closest to 0002's intent — cheap,
takes images, and keeps LightRAG on a model family it supports directly.
Chosen by the owner, 16 Oct 2026. The relay answers as
`gpt-5-mini-2025-08-07`.

Consequences:

- Users' uploaded material passes through apiyi as well as OpenAI. 0001 puts
  privacy over cost; a public launch should say so to users, or move to a
  direct OpenAI key.
- Prices are set by the relay, not OpenAI's price list; costs in HANDOFF.md
  were estimated for Luna and need re-checking against apiyi's.
- `gpt-5-mini` is a reasoning model: it bills hidden reasoning tokens (74
  output tokens to reply "ok"). Each call sets `reasoning_effort` deliberately.
- Known weakness, found in Phase 2: on the eLearn screenshot it read the pink
  arrow as pointing down-left at "Assignments" in 7 of 7 runs; it points
  down-right at "Quizzes" (Q07). See makendra.md.

## Exception: Diagram descriptions use gemini-3.5-flash-lite

Approved by the owner, 16 Oct 2026, after testing every vision model on the
relay with the same production prompt on both eval images:

| Model | Q07 arrow target | Flowchart connectors |
| --- | --- | --- |
| gpt-5-mini | Assignments, 7 of 7 runs (wrong) | best of the four; misses the "minor" arrow's source |
| gemini-3.5-flash-lite | Quizzes, 5 of 5 runs | varies run to run; one run skipped "Conduct disciplinary proceedings" on the main path |
| claude-haiku-4-5 | Assignments (wrong) | minor/major paths garbled |
| qwen3.6-flash | Assignments (wrong) | 16,684 output tokens for one image |

Gemini is also cheaper per image (~0.4-1.5k output tokens, no hidden
reasoning, against gpt-5-mini's 2.4-6.7k). No model on the relay reads
connectors reliably in one pass, so a Diagram description no longer relies on
one: arrows are read three times and kept by majority vote
(`scripts/diagram_connections.py`), five Gemini calls per image in all - still
well under a cent. With that, both eval images read correctly.
