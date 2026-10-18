# Anchor

Ask your course materials anything. Anchor answers from your own files (PDFs,
Word documents, text notes, pictures, spreadsheets), quotes the exact words
each step rests on, links to where they came from, and says plainly when your
materials don't cover something.

Front page: https://anchor-study.vercel.app

Under the hood it is a **Hybrid Routed RAG** demo, built and measured step by
step on a Comparison ladder:

| Rung | What it adds |
| --- | --- |
| 1. The model alone | GPT-5.6 Luna answering with no files |
| 2. Vector search | the 5 closest chunks by embedding (`text-embedding-3-small`, pgvector) |
| 3. Hybrid search | Postgres full-text + vectors, merged (RRF) and reranked (`bge-reranker-v2-m3`) |
| Routed (the app) | a router sends number questions to the spreadsheets (one read-only SQL query on DuckDB), everything else to hybrid search |

Every answer is checked against what was retrieved: a step whose quote can't be
found, or that the quote doesn't support, makes the answer **Unsure**. Pictures
are described when a file is added; an answer resting on one shows the picture.

## Results so far

21 practice (Build) questions on a sample course, one run each, answering
prompt v4, 18 Oct 2026. Counts, not percentages.

| Setup | Correct | Hallucinations |
| --- | --- | --- |
| The model alone | 6 of 21 | 1 of 21 |
| Vector search | 19 of 21 | 0 of 21 |
| Hybrid search | 18 of 21 | 0 of 21 |
| **Routed (the app)** | **21 of 21** | **0 of 21** |

Hybrid's one extra miss is a scoring miss (a correct refusal in words the
refusal check doesn't recognise). The final run on the held-back Test
questions hasn't happened yet.

## What this repo holds

- `scripts/` - the pipeline: parsing (Docling), picture descriptions,
  chunking, storage, search, the router and SQL route, answering, the checker,
  the grader, scoring and the eval tools.
- `web/` - the website: FastAPI app, front page, saved example answers and
  demo clips recorded from the live app.
- `GLOSSARY.md`, `docs/adr/` - the terms used, and the main decisions and
  why.

**The public copy leaves out the course material:** the sample course's files,
everything parsed from them, the run files (they quote the files), and the
question sets. They are the university's material and include teaching staff's
contact details. So the eval can't be re-run from the public copy; the scripts
show how, on your own files. A staff name in `scripts/near_miss.json` reads
`[redacted]`.

## Run the website locally

Python 3.13, Postgres with pgvector, an OpenAI API key.

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then put your OpenAI key in .env
OWNER_EMAIL=you@example.com .venv/bin/uvicorn web.app:app --port 8000
```

Open http://localhost:8000. The website is a draft.
