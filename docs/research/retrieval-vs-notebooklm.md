# Retrieval and chunking changes vs NotebookLM

Research note, 22 Oct 2026. The question: which retrieval or chunking changes would make Anchor better than Google NotebookLM (renamed **Gemini Notebook** on 16 July 2026, see below), ranked by benefit against risk and time with the deadline today, and how to measure "better than NotebookLM".

How this was done: web research on primary sources (papers, model cards, official docs, Google's own blog and help centre). I also read the code (`scripts/chunk.py`, `hybrid.py`, `store.py`, `router.py`, `setups.py`, `answering.py`, `web/pipeline.py`), read the saved practice (Build) runs in `runs/`, and ran two free local checks: the reranker over the 35 chunks, and a token count of the spreadsheet cells. **No OpenAI calls, no code changes, and no held-back (Test) question was opened.** Labels used below: **[measured]** means a count from Anchor's own runs or my local check, **[source]** means a cited document says it, and **[guess]** means my estimate.

---

## Short answer

- **Chunking is not Anchor's problem.** Fact questions score 21 of 21, 13 of 13 and 9 of 9 (Test, locked), with 0 unsupported claims. No chunking method in the literature can raise that score, and every one of them would mean re-running everything. **Leave chunking as it is today.**
- **S05 (practice) is a router coin-flip, and a one-line code change fixes it.** The same question was tagged `numeric` in 2 of the 3 saved practice runs. Both times it went to the SQL route and got the right answer, $22,000. The one time it was tagged `solve`, it went to hybrid search, which cannot see spreadsheet cells, and answered "Not found in your materials" [measured]. **Today: send `solve` to the SQL route too when the Library has spreadsheets.** It still falls back to hybrid search, the same way `numeric` does.
- **S10 (practice) is not a routing miss. Search cut it off by one place.** The chunk holding the schedule (the row "| 3 | 31/8 | Filesystems |", PDF p. 1) is ranked **6th** by the reranker, and only the top 5 reach the model. The scores are 0.2971 against 0.2983 for 5th place [measured]. Tagging it `solve` would not have helped, because `solve` uses the same hybrid search. **Today: raise k from 5 to 8.** `score.py --k 8` tests this without changing code. Anthropic's tests found that handing over 20 chunks did better than 5 or 10 [source].
- **The well-supported bigger change is putting the whole Library in the prompt while it fits.** The eval Library is about 19,400 tokens of chunks plus about 12,200 tokens of spreadsheet cells [measured]. GPT-5.6 Luna accepts 922,000 input tokens [source]. This one change would fix both kinds of miss, and the quote checker would keep working. Studies find that long context beats RAG on average when it fits [source]. But it changes every answer, and no one has published how well Luna handles long prompts. **Only try it after the two small fixes, and only keep it if the practice scores hold.**
- **What Google says publicly about NotebookLM:** its chat uses Gemini's full 1-million-token context window. Google's own diagram calls it "a RAG model" with a "Retrieval and Ranking process (intermediate questions)". Since June 2026 it runs on "Gemini 3.5", and it can now run code against your sources on some plans [source]. Google does not say how it chunks or ranks, or whether a small notebook goes into the prompt whole.
- **Not retrieval, but measured:** the Unsure false alarms come from the checker, not from search. No retrieval change will fix them.

---

## What the measured misses actually are (new findings from the saved runs)

| Question | What happened | Root cause | Evidence |
|---|---|---|---|
| **S05** (practice): "if December's service revenue had been $80,000 … net profit?" | Runs `routed__solve__20261021T114108Z` and `routed_s4__solve__20261021T114109Z`: tagged `numeric`, went to the SQL route, answered "$22,000" (correct). Run `routed__solve__20261021T164951Z`: tagged `solve`, went to hybrid search, answered "Not found in your materials". | The router gives different tags to the same question on different runs, and only the `numeric` tag reaches the spreadsheet. | [measured] `runs/*.jsonl`, field `result.route` |
| **S10** (practice): "revision quiz released in week 3 … when does it close?" | Tagged `lookup` in all 3 runs. The top 5 chunks were always pdf#003, #002, #004, docx#002, #005, so the answer said the materials don't give the date. | It is a two-step question: the rule ("two weeks later on Sunday") is in one chunk and the week-3 start date ("31/8") is in another, `…__pdf#001`. My local rerank of all 35 chunks puts pdf#001 **6th**, with a score of 0.2971 against 0.2983 for 5th. | [measured] local run of `BAAI/bge-reranker-v2-m3` on `parsed/chunks.jsonl` with the same chunk header as `embed.chunk_input` |
| S06 (Test, not opened here) | Its one run (`routed__solve__20261021T122525Z`) was tagged `solve`, went to hybrid search and got "Not found" | The same cause as S05's miss: only `numeric` reaches the spreadsheet | [measured] that run's `result.route`. It cannot be re-checked: the Test set has been used |

A side finding from the code: **with only 35 chunks, keyword search, vector search and the RRF merge have no effect on what the model sees.** `store.vector()` returns every chunk, because LIMIT 150 is more than 35, so all 35 chunks are candidates, and `hybrid.rerank()` re-sorts them by reranker score alone [measured, `scripts/hybrid.py` lines 50–53, `scripts/store.py` lines 97–107]. On today's Library, "hybrid search" in practice means "the reranker reads the whole Library". The reranker is also the slow part of the search step.

---

## Ranked table

Ranked by benefit against risk and time **for today**. Items 1–2 are the "do today" list, items 3–4 are "only if time is left and the practice scores hold", and items 5–12 are "leave".

| # | Change | Fixes which measured failure | Expected benefit | Risk | Time to build | How to measure on Anchor's eval |
|---|---|---|---|---|---|---|
| 1 | Send `solve` to the SQL route as well as `numeric` when the Library has spreadsheets. It still falls back to hybrid search. The condition changes in two places: `web/pipeline.py` line 214 and `scripts/setups.py` line 147. | S05 (and probably S06 in Test) | About +1 of 7 practice solve questions: S05 was right both times it reached SQL [measured] | Low. Solve questions that aren't about the spreadsheet get one extra planning call before falling back (a few seconds [guess]). The SQL route might answer a method question from cells alone. | 15 min plus runs | `score.py routed --group solve`, run twice (the router varies). Check S01, S02 and S07–S09 still pass, then run `routed` and `routed --group added` once. |
| 2 | Raise k from 5 to 8 (also try 10). Change `setups.K` and `web/pipeline.py` K. | S10 | About +1 of 7 practice solve questions, if the model then does the date sum. The number check already re-checks dates. | Low to medium. 3 more chunks (about 1,700 tokens) for the model and checker to read. Could change some of the 34 fact answers that are correct now. | 5 min plus runs | First, with no code change: `score.py routed --k 8`, `--group added --k 8`, `--group solve --k 8`. Keep the change only if fact questions stay at 21/21 and 13/13 with 0 unsupported claims. |
| 3 | Self-Route-style retry: when the answer is "Not found" (or a partial "your materials don't say …"), ask once more with the whole Library in the prompt | S05/S10-type misses, plus the known "Not found can be wrong" limit | Catches the retrieval misses the eval hasn't found yet | Medium. The 11 practice "not in docs" questions and the 1 partial question all get a second, longer call (slower). More context might stretch a correct refusal into a guess. Detecting "partial" by string match is fragile. | 1–2 h | The 11 `not_in_docs` practice questions must stay refused, and the solve and fact sets must not drop. |
| 4 | Whole Library in the prompt for every question while it fits under a token budget (for example 100k), RAG above that. The quote checker stays as it is. | S05 (with the spreadsheet cells included), S10, and the reranker's 3–16 s | Removes routing and retrieval as causes of failure for every Library the product allows today: 1 file of at most 50 pages | Medium to high **today**. It changes every answer. Luna is a small, "cost-sensitive" model with no published long-context results. The support checker reads about 32k tokens. A planted instruction in any file is always in the prompt (re-check pentest A2). | 2–3 h plus full runs | All three practice sets, twice, plus timing. Adopt only if nothing drops and unsupported claims stay at 0. |
| 5 | Speed up the reranker: set `max_length=512`, or switch to a smaller model | Latency only (search 3–16 s) | In my one timing test, truncating to 512 tokens roughly halved rerank time (67.5 s down to 35.6 s, machine possibly busy) [measured, one run] | Medium. Chunks over 512 tokens get cut, which changes the ranking for every question. | 10 min plus runs | Full practice sets plus the `timing` lines from the web log |
| 6 | Contextual retrieval (an LLM-written context added to each chunk) | None directly. It *might* lift the schedule chunk for S10. | Small on a 35-chunk Library [guess] | Medium. Re-embeds and re-ranks everything. Costs an LLM call per chunk at upload. | 1–2 h | Full practice sets |
| 7 | Semantic chunking, or Docling HybridChunker in place of `chunk.py` | None | None expected. `chunk.py` is already structure-aware | Medium: every chunk and every location changes | 1–2 h | Full practice sets |
| 8 | Parent-child (small-to-big) retrieval | None | None expected at 35 chunks | Medium | 1–2 h | Full practice sets |
| 9 | Query rewriting, HyDE, multi-query, decomposition | S10 (decomposition would find both hops) | Less than item 2 achieves for free | Medium: an extra model call per question (slower) | 1–2 h | Solve set |
| 10 | Late chunking | None | Needs a different embedding model | High | Half a day | — |
| 11 | RAPTOR | None measured (the eval has no overview questions) | Unknown | High | Half a day | Would need new overview questions |
| 12 | ColBERT / late interaction | None | None at 35 chunks | High | Half a day | — |

---

## 1. Contextual retrieval (Anthropic)

**What it is.** Before indexing, a model reads each chunk together with its whole document and writes a short context (50–100 tokens) that "situates this chunk within the overall document". That context goes in front of the chunk for both the embedding ("contextual embeddings") and the keyword index ("contextual BM25") ([Anthropic](https://www.anthropic.com/news/contextual-retrieval)).

**Evidence.** Measured across codebases, fiction, arXiv papers and science papers, as 1 − recall@20 ([Anthropic](https://www.anthropic.com/news/contextual-retrieval)):
- contextual embeddings: 35% fewer top-20 retrieval failures (5.7% down to 3.7%);
- plus contextual BM25: 49% fewer (down to 2.9%);
- plus a reranker (Cohere's, top 150 reranked down to 20): 67% fewer (down to 1.9%).
- One-time cost of about $1.02 per million document tokens with Claude 3 Haiku and prompt caching.
- The same post says that a knowledge base under about 200,000 tokens can simply be put in the prompt whole, with no RAG.

**Would it fix Anchor's failures?** Not reliably. Anchor already puts a light header (`file | page or heading`) in front of every chunk for both the embedding and the keyword index (`scripts/embed.py` `chunk_input`, `scripts/store.py` tsv column). The only retrieval miss, S10, missed the top 5 by 0.0012 in reranker score. A context line saying "this is the IS114 weekly schedule" *might* lift it [guess], but raising k is certain and free. Anthropic's own advice for a Library this small is the long-context option (section 9).

**Cost, latency, risk.** One model call per chunk at upload, a re-embed, and a full re-run. It changes the ranking of all 35 chunks for all questions.

**Verdict for Anchor: leave.** Real benefits at scale, but the Library (about 19k tokens of chunks, about 32k with the spreadsheet cells) is about 6 to 10 times smaller than the size at which Anthropic says to stop using RAG.

## 2. Late chunking (Jina)

**What it is.** A long-context embedding model reads the whole document once. The token vectors are then pooled per chunk, so each chunk's vector "knows" its neighbours ([Günther et al., arXiv 2409.04701](https://arxiv.org/abs/2409.04701)).

**Evidence.** On four small BeIR datasets with three embedding models, it averaged about +1.5 to +1.9 nDCG@10 points over chunking first. Some gains were tiny (FiQA +0.5) or flat. It helped most with small chunks and long documents, and it did not help when the surrounding text was unrelated. Overlap showed no clear advantage ([paper, v3](https://arxiv.org/html/2409.04701v3)).

**Would it fix Anchor's failures?** No. It also isn't possible with Anchor's current embedder: it needs a model's per-token outputs, and the OpenAI embeddings API returns one vector per input string ([OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)). Adopting it means switching to a self-hosted long-context model and re-running everything.

**Verdict for Anchor: leave.**

## 3. Semantic and structure-aware chunking, and chunk size and overlap

**What it is.** Docling's **HierarchicalChunker** makes one chunk per document element and attaches headings and captions. Its **HybridChunker** splits elements that are too long for the tokenizer and merges small neighbours that share a heading (`merge_peers`, on by default). It can repeat table headers when a table is split ([Docling chunking docs](https://docling-project.github.io/docling/concepts/chunking/)). "Semantic" chunking cuts wherever the topic changes, judged by embeddings.

**Evidence on whether it matters.**
- Semantic chunking's extra cost was "not justified by consistent performance gains" over fixed-size chunks ([Qu et al., arXiv 2410.13070](https://arxiv.org/abs/2410.13070)).
- Chroma's own study: the choice of method moved recall by up to about 9 points. Smaller chunks (200 tokens) gave much better *precision* (fewer wasted tokens) with similar recall. The OpenAI Assistants default (800 tokens, 400 overlap) had the lowest efficiency. The authors warn that the dataset is small and the queries were written by an LLM ([Chroma research](https://www.trychroma.com/research/evaluating-chunking)).
- NVIDIA: one chunk per page had the best average answer accuracy (0.648) and the least spread. Extremes (128 and 2,048 tokens) did worse. Factoid questions favoured 256–512 tokens, analytical ones 1,024 tokens or a page. 15% overlap did best in their one test ([NVIDIA technical blog](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)).
- The best size depends on the dataset and the embedder: 64–128 tokens for short-fact datasets, 512–1,024 for questions that need context ([Bhat et al., arXiv 2505.21700](https://arxiv.org/abs/2505.21700)).

**Would it fix Anchor's failures?** No. `chunk.py` is already a custom structure-aware chunker: Docling blocks, whole tables (split by rows only when oversized, and padding removed), section and exam-question boundaries, whole-block overlap, and page and line locations kept. Chroma's efficiency argument (smaller is tighter) matters when token budgets are tight, which a 35-chunk Library isn't. Smaller chunks would also make the S10-type two-hop problem *worse*, because more pieces would compete for the 5 places [guess].

**Verdict for Anchor: leave.** 800 tokens with whole-block overlap sits in the mid-range that NVIDIA and Bhat et al. found safe.

## 4. Parent-child (small-to-big) retrieval

**What it is.** Small "child" chunks are searched, and their larger "parent" is handed to the model. LangChain's ParentDocumentRetriever, for example, uses 400-token children and 2,000-token parents ([LangChain docs](https://python.langchain.com/docs/how_to/parent_document_retriever)). LlamaIndex's auto-merging retriever swaps leaves (128 tokens) for their parent once enough of the leaves are retrieved ([LlamaIndex docs](https://developers.llamaindex.ai/python/examples/retrievers/auto_merging_retriever/)). A related idea indexes atomic "propositions" ([Chen et al., Dense X Retrieval, arXiv 2312.06648](https://arxiv.org/abs/2312.06648)).

**Evidence.** The framework docs describe the pattern but give no benchmark. Dense X reports that finer units retrieve better than passages, on open-domain QA over Wikipedia.

**Would it fix Anchor's failures?** No. Neither miss was "found the right sentence but not enough context around it".

**Verdict for Anchor: leave.**

## 5. RAPTOR

**What it is.** Chunks are clustered and summarised, then the summaries are clustered and summarised again, building a tree. Questions are answered by retrieving at any level of the tree ([Sarthi et al., ICLR 2024](https://openreview.net/forum?id=GN921JHCRw); [arXiv 2401.18059](https://arxiv.org/abs/2401.18059)).

**Evidence.** With GPT-4, it improved the best published QuALITY result (long-document multiple-choice) by 20 points of absolute accuracy ([abstract](https://arxiv.org/abs/2401.18059)).

**Would it fix Anchor's failures?** No. It targets "overview" and whole-document questions, and the eval has no measured overview questions. For a Library this small, putting the whole Library in the prompt (section 9) covers overviews without a summary tree.

**Verdict for Anchor: leave.**

## 6. Query rewriting, HyDE, multi-query and decomposition

**What they are and the evidence.**
- **Rewrite-Retrieve-Read:** a trained rewriter improves the search query, with "consistent" gains on open-domain and multiple-choice QA ([Ma et al., EMNLP 2023](https://arxiv.org/abs/2305.14283)).
- **HyDE:** the model writes a pretend answer, and that is embedded to search with. It beat Contriever and matched fine-tuned retrievers zero-shot ([Gao et al., ACL 2023](https://aclanthology.org/2023.acl-long.99/)).
- **Multi-query:** several rephrasings are searched and the results merged ([LangChain MultiQueryRetriever](https://python.langchain.com/v0.2/docs/how_to/MultiQueryRetriever/)). RAG-Fusion adds RRF on top of this. It was evaluated by hand at Infineon, and some answers "strayed off topic" ([Rackauckas, arXiv 2402.03367](https://arxiv.org/abs/2402.03367)).
- **Decomposition:** Self-Ask splits a question into follow-up questions, each of which can be searched separately. It narrows the "compositionality gap" on multi-hop questions ([Press et al., Findings of EMNLP 2023](https://arxiv.org/abs/2210.03350)).

**Would it fix Anchor's failures?** Decomposition is the textbook fix for S10: it would search "when does week 3 start?" separately. But k = 8 gets the same chunk in for free, with no extra model call. Anchor already rewrites follow-up questions so they stand alone (`condense` in `web/pipeline.py`). Google says NotebookLM uses "intermediate questions" in its retrieval (see the NotebookLM section).

**Verdict for Anchor: leave for today.** Revisit decomposition if Libraries grow past "fits in the prompt".

## 7. Late interaction (ColBERT, ColBERTv2)

**What it is.** It keeps one vector per token and scores a query against a passage by matching tokens. That gets close to cross-encoder quality while letting passages be indexed ahead of time. ColBERT was reported as "two orders-of-magnitude faster" than BERT cross-encoders ([Khattab & Zaharia, SIGIR 2020](https://arxiv.org/abs/2004.12832)). ColBERTv2 cut storage 6–10× with state-of-the-art quality ([Santhanam et al., NAACL 2022](https://arxiv.org/abs/2112.01488)).

**Would it fix Anchor's failures?** No. Its advantage is speed at the scale of millions of passages, while Anchor has 35 chunks. It would be a new index, a new model and a full re-run.

**Verdict for Anchor: leave.**

## 8. Rerankers: is one needed at 35 chunks, and are there faster ones?

**The current model.** `BAAI/bge-reranker-v2-m3`: about 0.6B parameters, based on bge-m3 (XLM-RoBERTa), multilingual, Apache-2.0. The card calls it "lightweight … with fast inference" and notes that fp16 speeds it up with a slight quality loss ([model card](https://huggingface.co/BAAI/bge-reranker-v2-m3)). The card's examples truncate inputs at 512 tokens, but the cached tokenizer config allows 8,192, so Anchor's CrossEncoder reads whole chunks [measured, local `tokenizer_config.json`].

**Is reranking needed?** Anchor's own ladder says the reranker matters when very few chunks are handed over: with 1 chunk, hybrid+rerank scored 19 of 21 against 16 of 21 for vector search. With 5 chunks it made no difference (18 against 19, and the 1 was a scoring miss). On a 35-chunk Library the reranker *is* the whole search (see the side finding above). If the whole Library goes into the prompt (section 9), no reranker is needed for Libraries that fit.

**Faster or hosted alternatives.**
- `cross-encoder/ms-marco-MiniLM-L6-v2`: listed at 1,800 docs/sec (hardware not stated), English, trained on MS MARCO ([Sentence Transformers docs](https://sbert.net/docs/cross_encoder/pretrained_models.html)). Much smaller, but it would change the rankings, so it needs a full re-run.
- Hosted: Cohere Rerank (v3.5, v4.0 fast/pro, v5.0 fast/pro) ([Cohere docs](https://docs.cohere.com/docs/rerank-overview)), and Voyage `rerank-2.5` / `rerank-2.5-lite` (32k-token context, up to 1,000 documents per call) ([Voyage docs](https://docs.voyageai.com/docs/reranker)). Either adds a new account and key, sends Library text to another company, and adds network time.
- The cheapest tweak is `max_length=512`. In my one local test it roughly halved rerank time (67.5 s down to 35.6 s, possibly on a busy machine; the app logs say 3–16 s for the whole search step), and it happened to move the S10 schedule chunk from 6th to 4th. That is one question, **not evidence**: truncation cuts the end off every chunk over 512 tokens, and the median chunk is 564 cl100k tokens.

**Verdict for Anchor: keep the reranker today.** Speed it up only together with a full practice re-run, or drop it for small Libraries if section 9 is adopted.

## 9. Long context instead of RAG for small Libraries

**Evidence.**
- Li et al. compared RAG with long context (LC) on LongBench and ∞Bench. Averages: Gemini-1.5-Pro LC 49.70 against RAG 37.33; GPT-4O LC 48.67 against RAG 32.60; GPT-3.5-Turbo LC 32.07 against RAG 30.33. Their **Self-Route** (try RAG, and if the model says it can't answer, use LC) scored 46.41, 48.89 and 35.32 respectively, using 38–61% of LC's tokens. About 63% of questions got identical answers either way. The RAG failures they found were mostly **multi-step**, general, long or implicit questions. Their RAG used 300-word chunks and top-5 ([arXiv 2407.16833, EMNLP 2024 industry track](https://arxiv.org/html/2407.16833v2)). S10 is exactly a multi-step miss under top-5.
- Anthropic: under about 200,000 tokens, "just include the entire knowledge base in the prompt" ([Anthropic](https://www.anthropic.com/news/contextual-retrieval)).
- Cautions:
  - Models use information in the middle of a long input less well than at its start or end ([Lost in the Middle, TACL 2023](https://arxiv.org/abs/2307.03172)).
  - Of 17 long-context models tested in 2024, only about half stayed good at 32K tokens, even though all claimed 32K or more ([RULER, COLM 2024](https://arxiv.org/abs/2404.06654)).
  - Neither approach always wins. It depends on the model's size and long-context skill, the context length and the task ([LaRA, arXiv 2502.09977](https://arxiv.org/abs/2502.09977)).

**Does it fit?**
- GPT-5.6 Luna: 1,050,000-token context window, 922,000 max input tokens, $0.20 per million input tokens ($0.02 cached), $1.20 per million output tokens. A request over 272K input tokens is billed at 2× the input rate and 1.5× the output rate for the whole request ([OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna.md)).
- Caching is automatic from 1,024 tokens. Reads cost 0.1× and writes 1.25× for 30 minutes ([OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)).
- The eval Library is 19,430 tokens of chunks plus about 12,200 tokens for all 475 spreadsheet cells written as `ref = value (row: …) (column: …)` [measured]. That is about 32k tokens, about $0.006 per call uncached, and about $0.013 per question if the checker's support call also reads it all [guess, ignoring output and reasoning tokens]. A 50-page upload is probably 25–40k tokens [guess]. So **every Library the product allows today fits** with a lot of room, and stays well under the 272K price step.

**How it would sit in Anchor.** Pass every chunk (and every spreadsheet cell) as an excerpt with its existing id to the same `ask_with_docs` prompt. The "quote exact words from one excerpt" rule and the word-for-word quote check stay unchanged, because excerpt ids and texts are the same objects. Above a token budget (for example 100k), fall back to today's RAG. Self-Route (table item 3) is the more cautious version: keep RAG, and use the whole Library only when RAG says "Not found".

**Risks.**
- Luna is described as built for "cost-sensitive, high-volume workloads". No public long-context results were found for it [could not verify].
- The support checker would read 32k tokens per answer, so the number of Unsure answers could change.
- A planted "instruction" in any file is always in the prompt. Re-run the pentest A2 check.
- Speed: it removes the 3–16 s search step but adds time to read the longer prompt [guess: a few seconds; time it].

**Verdict for Anchor: the strongest-evidence change, but not first today.** Build it behind a flag after items 1–2. Keep it only if all three practice sets hold, with 0 unsupported claims.

## 10. Routing fixes (the actual failure)

**Literature.** Adaptive-RAG trains a small classifier (T5-Large) to send each question to no retrieval, single-step or multi-step retrieval. With GPT-3.5 it matched multi-step accuracy (F1 50.91 against 50.87) at under half the time. But its classifier was right only 54.52% of the time, and a perfect classifier would have scored F1 62.80 ([Jeong et al., NAACL 2024](https://arxiv.org/html/2403.14403v2)). The lesson for Anchor: **expect the router to be wrong sometimes, and design so that a wrong tag costs little.**

**Anchor's overlap.** The router sees only the question, not the Library (`scripts/router.py`). A spreadsheet "what if" is honestly both `numeric` and `solve`, so the tag flips between runs (S05). Today only `numeric` can reach the spreadsheet.

**Simplest fix.** Choose the route by *what the Library has* as well as by the tag: `if tag in ("numeric", "solve") and lib.has_sheets():` in `web/pipeline.py` line 214, and the same in `scripts/setups.py` line 147, so that the eval measures what the site does. The SQL route already says "not answerable" and falls back to hybrid search, so solve questions that aren't about the spreadsheet still reach the PDFs. That costs one extra planning call. Rewording the router prompt is less reliable, because the router still can't see the Library and the flip is between two honest readings. Putting the whole Library in the prompt (section 9) removes the problem altogether.

**Verdict for Anchor: do today.** One condition, in two places.

---

## NotebookLM (now "Gemini Notebook"): what is public and what is not

### Publicly stated by Google
- **Renamed** "Gemini Notebook" on 16 July 2026. Google says it is still a standalone research tool, and old links redirect ([Google blog, 16 Jul 2026](https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/); [Workspace Updates](https://workspaceupdates.googleblog.com/2026/07/notebooklm-now-gemini-notebook.html)).
- **Model.** "Gemini 1.5 Pro" from June 2024 ([Google blog, 6 Jun 2024](https://blog.google/technology/ai/notebooklm-goes-global-support-for-websites-slides-fact-check/)). In June 2026 Google wrote "we're upgrading NotebookLM to run on Gemini 3.5 and Antigravity" ([Google blog, 8 Jun 2026](https://blog.google/innovation-and-ai/products/notebooklm/better-research-notebooklm/)). The July 2026 rename post names no model.
- **Context window and retrieval.**
  - "Starting today, we're enabling the full 1 million token context window of Gemini in NotebookLM chat across all plans."
  - It "automatically explores your sources from multiple angles, going beyond your initial prompt."
  - The post's diagram is captioned "a RAG model" with a "NotebookLM Retrieval and Ranking process (intermediate questions)".
  - It reports "a 50% improvement in user satisfaction with responses that use larger amounts of sources", without saying how this was measured.
  - All from the [Google blog, 29 Oct 2025](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-custom-personas-engine-upgrade/).
- The help centre says: "When your notebook contains many sources, Gemini Notebook retrieves the most relevant information based on your question". Sources are "always used in either the entire set or the subset you select" ([FAQ](https://support.google.com/notebooklm/answer/16269187?hl=en)).
- **Grounding and citations.**
  - "Chat responses in Gemini Notebook only use data from your sources."
  - It "uses direct quotes, text, and images from your sources as citations". Hovering shows the quote and clicking jumps to it.
  - "Gemini Notebook can make mistakes … Be sure to double check it."
  - All from [Use chat](https://support.google.com/gemininotebook/answer/16179559?hl=en). A very short source is cited as a whole document ([Add sources](https://support.google.com/gemininotebook/answer/16215270?hl=en&co=GENIE.Platform%3DDesktop)).
- **Limits and file types.**
  - Up to 500,000 words or 200 MB per source, and 50 sources per notebook on the free plan ([Add sources](https://support.google.com/gemininotebook/answer/16215270?hl=en&co=GENIE.Platform%3DDesktop)). Paid plans allow more ([plans](https://support.google.com/notebooklm/answer/16213268?hl=en)).
  - Upload types: docx, txt, md, pdf, **csv**, pptx, images and audio. **xlsx is not listed.** Google Sheets imports are limited to 100k tokens, and Slides to 100 slides (same page).
- **Code execution.**
  - "Each notebook is now equipped with a secure cloud computer, enabling NotebookLM to write and run code" ([8 Jun 2026](https://blog.google/innovation-and-ai/products/notebooklm/better-research-notebooklm/)).
  - Available now to Google AI Ultra users, rolling out "to all Pro users on the web over the coming weeks" ([16 Jul 2026](https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/)).
  - Its new **output** formats include csv, json and xlsx (8 Jun 2026 post).
- **Privacy.** Your data "is not used to train Gemini Notebook unless you provide feedback"; it supports 80+ languages ([Learn about](https://support.google.com/notebooklm/answer/16164461)).

### Not public (anything below is a guess and labelled so)
- How it chunks, which embedder or ranker it uses, and how many passages reach the model. Google's own long article on building it doesn't say ([Google blog, Jul 2025](https://blog.google/innovation-and-ai/products/developing-notebooklm/)).
- Whether a small notebook (like Anchor's 7 files) goes into the 1M-token prompt whole, or is still retrieved. **[guess]** The 1M window suggests it could, but the help centre says it retrieves "when your notebook contains many sources". Google doesn't say where "many" starts.
- Whether citations are checked by code. **[guess]** Nothing public says so. Anchor's checks (word-for-word quote match, support judge, number re-check, "Unsure") are publicly documented only for Anchor.
- No published accuracy benchmark for NotebookLM's chat answers was found [could not verify any].

What this means for the comparison **[guess]:** on spreadsheet "what if" questions, a tester on a plan with code execution may see NotebookLM compute answers that Anchor's hybrid route cannot. Record which plan was used.

---

## How to measure "better than NotebookLM"

There is already a sheet for this: **`runs/notebooklm_scoring.csv`**. It has 41 practice rows (21 original, 13 added, 7 solve). Anchor's answer and scores are filled in, and the `notebooklm_*` columns are empty. Use it as follows.

1. **Same files.** Make a new notebook and add the 7 files in `eval set/`. The xlsx is not an upload type, so add it from Google Drive as a Google Sheet (or as CSV, one tab per file), and note that difference. Check that all sources are ticked. Record the date and the plan (Free, Pro or Ultra), and whether code execution was on.
2. **Same questions, no carry-over.** Paste each `question` exactly. Start a fresh chat for each question (chats now save, and memory is "more than sixfold" longer [source above]), because Anchor answers each eval question on its own. Copy the answer and note whether it cites something.
3. **Same rubric, the existing columns:**
   - `correct`: graded against `correct_answer`, the same way Anchor is graded.
   - `unsupported_claim`: does the answer state something the files don't support? Hover its citations to check.
   - `refused`: did it decline? For the 11 `not_in_docs` questions, refusing is correct. For the rest, refusing is wrong.
   - NotebookLM has **no "Unsure" label**, so compare **confidently wrong** answers: wrong, and not labelled Unsure (for NotebookLM, every wrong answer counts). Anchor's column already exists.
   - Grade blind if you can: hide which system wrote each answer, or have a second person grade.
4. **Report counts by group**, for example "original: Anchor 21 of 21, NotebookLM x of 21". Report correct, unsupported claims, right refusals out of 11, wrong refusals, and confidently wrong. Add a stopwatch time for a few questions on each (Anchor takes about 30 s).
5. **Compare pairs, not totals.** List the questions where exactly one system was right. With 41 questions, small gaps are noise. For a two-sided 5% sign test you need, for example, 6 of 6, 8 of 9, 9 of 10 or 10 of 12 of those questions going the same way [computed]. Fewer than about 6 such questions means **call it a tie**. Pairing on the same questions is the standard way to reduce noise ([Miller, "Adding Error Bars to Evals", arXiv 2411.00640](https://arxiv.org/abs/2411.00640)).
6. **Run twice where you can.** S05 shows that Anchor can give different answers on different runs. NotebookLM may too.
7. **Claims you can honestly make.** Make them where the numbers back them. For example: "on the same 41 practice questions, Anchor made x unsupported claims and NotebookLM y". Also state the design differences that are publicly documented: Anchor checks every quote word for word and says "Unsure", while Google's pages describe citations but no automatic check. Don't call a gap of 1–3 questions "better".
8. **Held-back Test questions (optional, for the owner only).** Anchor's Test results are locked (9 of 9 facts, 2 of 3 solve). Running NotebookLM once on those same 12 questions gives a fair, untouched comparison, **as long as nothing in Anchor is changed afterwards because of what you saw**. I did not open them.

---

## Reminder: what can be checked today

The held-back Test set has been used once. **Any change made today can only be checked on the practice (Build) questions:** 21 original, 13 added and 7 solve. Of the solve misses, only S05 and S10 are practice questions, and S06 cannot be re-checked. A change that fixes S05 and S10 has been tuned to those two questions, so report it as "practice: 7 of 7 after the fix", not as a new Test result.

---

## Retrieval-plan completeness check

Each standard part is listed with where it stands; none is left silently missing.

| Part | Status |
|---|---|
| Parsing | Docling for PDF, Word and PowerPoint; vision descriptions for pictures; spreadsheets to DuckDB (in place, `parsed/parse_report.md`). OCR text is trusted (known limit). |
| Chunking | 800 tokens, whole-block overlap up to 100, page/line and heading kept (in place). No change recommended. |
| Lexical / vector / fusion | Postgres full-text + text-embedding-3-small + RRF (in place). No effect at 35 chunks (side finding). |
| Reranker | bge-reranker-v2-m3 on CPU (in place). See section 8. |
| Structured data route | SQL route over DuckDB (in place, read-only, pentested). Item 1 widens who reaches it. |
| Graph / multi-document route | Not built. `relationship` goes to hybrid search, and no relationship failure was measured. Whole-Library mode would cover cross-file questions for small Libraries. |
| Structure-aware tree navigation | Not built. Not needed under a 50-page upload cap (section 9). |
| Multi-hop loop | Not built. S10 is a two-hop miss, handled by k = 8 now and Self-Route or whole-Library later. |
| Router + accuracy | In place (`router_labels.csv`, `scripts/router_check.py`). The S05 flip shows the tag is unstable between runs, so item 1 makes a wrong tag cheap. |
| Baseline | Vector, hybrid and rerank ladder already measured. |
| Eval set | Build / Test split, tagged by type (in place). |
| Answer checker / citations | Quote, support and number checks; file and page shown (in place). Unsure false alarms are a checker issue, not a retrieval one. |
| Cost / latency | About 30 s per answer now; section 9 gives estimates for whole-Library mode [guess]. |
| Updates | Upload re-ingests a Library (`web/ingest.py`). Unaffected by items 1–2. |
| Access / security | Every query filters on Library id (record 0001); pentest done. Re-check the planted-instruction test if whole-Library mode is adopted. |

---

## Checked again (22 Oct 2026)

These claims were re-checked against the runs and sources before the README used them:
- **S05:** tagged `numeric` and correct in 2 of 3 runs; tagged `solve` and "Not found" in 1 (`runs/`).
- **S10:** the same 5 chunks reached the model in all 3 runs. The schedule chunk `…__pdf#001` holds "| 3 | 31/8 | Filesystems |". Re-running the app's own `hybrid.rerank` over the 35 chunks put it 6th, at 0.2971 against 0.2983 for 5th, the same scores as above.
- **Google's 16 Jul 2026 post:** says "We're renaming NotebookLM to Gemini Notebook". Code execution is available now on Google AI Ultra and Workspace plans, and coming to Pro users "over the coming weeks".
- **Gemini Notebook upload types:** .xlsx is not listed; CSV and Google Sheets (limited to 100k tokens) are.
- **OpenAI's Luna page:** 1,050,000 context window and 922,000 max input tokens.
- **Anthropic's post:** under 200,000 tokens, include the whole knowledge base; top-20 chunks beat top-10 and top-5; failure-rate cuts of 35%, 49% and 67%.

## Could not verify

- How well GPT-5.6 Luna handles long prompts. OpenAI's model page gives limits and prices, not long-context benchmarks.
- NotebookLM's internals: chunking, ranker, how many passages it uses, whether a small notebook goes into the prompt whole, and any accuracy benchmark.
- What "50% improvement in user satisfaction" measures (Google gives no method).
- Rerank speed. My one local timing (67.5 s for all 35 chunks) is much slower than the app's logged 3–16 s, probably because the machine was busy. Treat only the ratio (about half with `max_length=512`) as indicative.

---

## Sources

Papers
- Günther et al., *Late Chunking*, arXiv 2409.04701 — https://arxiv.org/abs/2409.04701 (results: https://arxiv.org/html/2409.04701v3)
- Qu, Tu, Bao, *Is Semantic Chunking Worth the Computational Cost?*, arXiv 2410.13070 — https://arxiv.org/abs/2410.13070
- Bhat et al., *Rethinking Chunk Size for Long-Document Retrieval*, arXiv 2505.21700 — https://arxiv.org/abs/2505.21700
- Chen et al., *Dense X Retrieval*, arXiv 2312.06648 — https://arxiv.org/abs/2312.06648
- Sarthi et al., *RAPTOR*, ICLR 2024 — https://openreview.net/forum?id=GN921JHCRw ; https://arxiv.org/abs/2401.18059
- Ma et al., *Query Rewriting for Retrieval-Augmented LLMs*, EMNLP 2023 — https://arxiv.org/abs/2305.14283
- Gao et al., *Precise Zero-Shot Dense Retrieval without Relevance Labels* (HyDE), ACL 2023 — https://aclanthology.org/2023.acl-long.99/
- Rackauckas, *RAG-Fusion*, arXiv 2402.03367 — https://arxiv.org/abs/2402.03367
- Press et al., *Measuring and Narrowing the Compositionality Gap* (Self-Ask), Findings of EMNLP 2023 — https://arxiv.org/abs/2210.03350
- Khattab & Zaharia, *ColBERT*, SIGIR 2020 — https://arxiv.org/abs/2004.12832
- Santhanam et al., *ColBERTv2*, NAACL 2022 — https://arxiv.org/abs/2112.01488
- Li et al., *Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach* (Self-Route), EMNLP 2024 industry — https://arxiv.org/abs/2407.16833 (tables: https://arxiv.org/html/2407.16833v2)
- Liu et al., *Lost in the Middle*, TACL 2023 — https://arxiv.org/abs/2307.03172
- Hsieh et al., *RULER*, COLM 2024 — https://arxiv.org/abs/2404.06654
- Li et al., *LaRA: Benchmarking RAG and Long-Context LLMs*, arXiv 2502.09977 — https://arxiv.org/abs/2502.09977
- Jeong et al., *Adaptive-RAG*, NAACL 2024 — https://arxiv.org/abs/2403.14403 (details: https://arxiv.org/html/2403.14403v2)
- Miller, *Adding Error Bars to Evals*, arXiv 2411.00640 — https://arxiv.org/abs/2411.00640

Company engineering pages, docs and model cards
- Anthropic, *Introducing Contextual Retrieval* (19 Sep 2024) — https://www.anthropic.com/news/contextual-retrieval
- Chroma, *Evaluating Chunking Strategies for Retrieval* — https://www.trychroma.com/research/evaluating-chunking
- NVIDIA Technical Blog, *Finding the Best Chunking Strategy for Accurate AI Responses* (18 Jun 2025) — https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/
- Docling, *Chunking* — https://docling-project.github.io/docling/concepts/chunking/
- LangChain, *Parent document retriever* — https://python.langchain.com/docs/how_to/parent_document_retriever ; *MultiQueryRetriever* — https://python.langchain.com/v0.2/docs/how_to/MultiQueryRetriever/
- LlamaIndex, *Auto Merging Retriever* — https://developers.llamaindex.ai/python/examples/retrievers/auto_merging_retriever/
- BAAI, *bge-reranker-v2-m3* model card — https://huggingface.co/BAAI/bge-reranker-v2-m3
- Sentence Transformers, *Pretrained Cross-Encoders* — https://sbert.net/docs/cross_encoder/pretrained_models.html
- Cohere, *Rerank overview* — https://docs.cohere.com/docs/rerank-overview
- Voyage AI, *Rerankers* — https://docs.voyageai.com/docs/reranker
- OpenAI, *GPT-5.6 Luna* model page — https://developers.openai.com/api/docs/models/gpt-5.6-luna.md
- OpenAI, *Prompt caching* — https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI, *Embeddings* — https://developers.openai.com/api/docs/guides/embeddings

Google (NotebookLM / Gemini Notebook)
- *NotebookLM is now Gemini Notebook* (16 Jul 2026) — https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/
- Workspace Updates, rename (16 Jul 2026) — https://workspaceupdates.googleblog.com/2026/07/notebooklm-now-gemini-notebook.html
- *Do your best research with NotebookLM* (8 Jun 2026) — https://blog.google/innovation-and-ai/products/notebooklm/better-research-notebooklm/
- *Chat in NotebookLM: a powerful, goal-focused AI research partner* (29 Oct 2025) — https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-custom-personas-engine-upgrade/
- *The inside story of building NotebookLM* (29 Jul 2025) — https://blog.google/innovation-and-ai/products/developing-notebooklm/
- *NotebookLM goes global with Slides support and better ways to fact-check* (6 Jun 2024) — https://blog.google/technology/ai/notebooklm-goes-global-support-for-websites-slides-fact-check/
- Help: FAQ — https://support.google.com/notebooklm/answer/16269187?hl=en
- Help: Add or discover new sources — https://support.google.com/gemininotebook/answer/16215270?hl=en&co=GENIE.Platform%3DDesktop
- Help: Use chat — https://support.google.com/gemininotebook/answer/16179559?hl=en
- Help: Learn about — https://support.google.com/notebooklm/answer/16164461
- Help: Plans — https://support.google.com/notebooklm/answer/16213268?hl=en

---

## Result of the comparison (22 Oct 2026)

Run as planned above: the 41 practice questions, the same files (the spreadsheet as one CSV per sheet), Gemini Notebook's free plan, and one run each. Both systems were scored by `grader.py`, and every answer the grader flagged was then checked by eye (`runs/notebooklm_scoring.csv`, `notes` column).

- **Correct:** Anchor 39 of 41, Gemini Notebook 40 of 41. Only Anchor was right on Q26; only Gemini Notebook was right on S05 and S10, the two misses this note diagnosed (a router flip and a k=5 cut-off). Sign test p = 1.00, a tie.
- **Unsupported claims:** Anchor 1 (S10), Gemini Notebook 6. Of those 6, 4 are clear (Q15, Q26, A03, A11) and 2 borderline (A02, A04); 1 more (Q09) was a grader false alarm. p = 0.12, suggestive only.
- **Refusals:** Gemini Notebook refused 10 of the 11 questions the files can't answer, against 11 for Anchor. The first grading missed 3 of its refusals, because they were worded "the sources do not list…" or "there is no Q17…". They were corrected by eye, and the patterns now cover that wording.
