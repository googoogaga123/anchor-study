---
marp: true
paginate: true
title: "Anchor: answers you can check"
---

# Anchor
## Answers you can check, from your own course files

A Hybrid Routed RAG system, built and measured step by step

<!-- Speaker notes: Anchor answers questions from a student's own course files.
Every answer quotes the files it rests on, and says plainly when the files
don't cover the question. This talk walks through every part of it and how
we measured each one. -->

---

## The problem

- Course rules are spread across PDFs, Word files, slides, screenshots and
  spreadsheets.
- General chatbots don't know your course, and answer confidently anyway.
- On 21 real course questions, the same AI model on its own got **6 of 21**
  right.
- A wrong deadline, weighting or exam rule costs real marks.

**Goal:** answers that come only from your files, show where each step came
from, and say "not found" instead of guessing.

---

## How Anchor works, in one picture

```
READING A FILE (once, when it is added)
  file -> parsing -> pictures described -> chunks -> embeddings + keyword index
  photo of a page -> straightened -> OCR -> checked by the student -> as above
  spreadsheet -> every cell into a small database (DuckDB)

ANSWERING A QUESTION (every time)
  question -> follow-up rewritten -> router
     numbers   -> Text-to-SQL on the spreadsheet  (falls back to search)
     the rest  -> hybrid search: keyword + vector -> RRF -> reranker
  -> top 5 passages -> answer, quoting each step -> checker -> shown, with sources
```

RAG ("retrieval-augmented generation") means finding the right passages in
your files and handing only those to the model with the question.

---

# Part 1: Reading your files

---

## Parsing

**What it is:** turning PDFs, Word files, slides and spreadsheets into clean
text and tables.

**What Anchor uses:** Docling, an open-source parser that runs on our own
server.

- It keeps page numbers, headings and table structure, so answers can cite
  "p. 10".
- **Equation reading is on.** In the sample midterm, one answer ($6,500) only
  existed inside an equation; with the default settings it vanished.
- **Table repair.** One table header sat over the wrong column. Anchor fixes it
  using the PDF's own word positions.

**Why it matters:** bad parsing is the most common cause of wrong answers.

---

## OCR: reading scans and phone photos

**What it is:** reading the text out of an image of a page.

**What Anchor uses:** RapidOCR (PP-OCRv6 models) inside Docling, running
locally and free.

- **Scan with your phone.** Each photo is cropped and straightened (OpenCV),
  and blurry or empty photos are flagged.
- **Check and fix.** The student sees the text that was read beside the photo
  and can fix any misread word before saving.
- **Measured:** on 10 course pages as images, OCR got back **1,921 of 1,989**
  words, with all table rows kept.
- **Safety net:** an answer from a scanned page shows that page beside it.

---

## Pictures: Diagram descriptions

**Problem:** flowcharts, graphs and screenshots have no text to search, and
their meaning is often in the arrows.

**What Anchor does:**
- An AI vision model writes a text description of each picture: what it is,
  all its text, and a chart's axes and lines.
- **Arrows are read 3 times**, and only connections 2 of the 3 readings agree
  on are kept.
- The description is searched like normal text.
- **An answer that rests on a picture shows the picture**, with "based on a
  computer reading - check the picture".

In the sample course: **15 pictures** described (2 picture files, 13 inside
PDFs).

<!-- Notes: the checker can't catch an error inside a description, because the
error is in the evidence itself. A person spots it in a second, which is why
the picture is always shown. -->

---

## Chunks

**What it is:** a piece of a document, the unit that gets found and cited.

**How Anchor cuts them:**
- About **800 tokens** each, with about **100 tokens of overlap**.
- Whole paragraphs, lists and tables only: **a table is never split mid-row**,
  because half a table answers nothing.
- A chunk ends early at a new section or exam question, so one chunk tends to
  hold one topic.
- Every chunk keeps its **file and page, slide or line range**.

Sample course: **35 chunks** from 6 files (159 to 785 tokens each). The
spreadsheet isn't chunked; it goes to the database instead.

---

## Embeddings

**What it is:** a list of numbers representing a chunk's meaning, so
passages can be found by meaning, not exact words.

**What Anchor uses:** OpenAI `text-embedding-3-small`: **1,536 numbers per
chunk**, with the file name and page added to the chunk first.

- **Compared against `bge-m3`** (self-hosted): they tied on every answer.
  3-small was chosen because it's cheaper and needs no server memory.
- Cost: embedding 200 pages is under $0.01.

---

## Keyword search (BM25-style)

**What it is:** classic word matching. It catches exact terms that meaning
search misses: codes, names, numbers ("G7", "port 7001").

**What Anchor uses:** Postgres full-text search on the same table as the
embeddings.

- The question's words are stemmed, with common words dropped, and joined with
  OR (a question rarely has every word in one chunk).
- Ranked by Postgres `ts_rank_cd`, which rewards how often and how close
  together the words appear. It is BM25-like, not BM25's exact formula.

---

## Spreadsheets into a database

- Every populated cell goes into **DuckDB**, opened **read-only**.
- **Two tables:**
  - `cells`: the cell's value and formula (the ground truth);
  - `labeled`: each cell with its row label and column header, so a query can
    ask for "Net Profit" rather than "C13".
- Sample course: **475 cells** across 7 sheets.
- **Why not chunk it:** cutting an accounting sheet into text loses which
  number sits under which header.

---

# Part 2: Answering a question

---

## Follow-ups and the router

**Follow-ups.** "And how much is each one worth?" is rewritten using the
conversation into a question that stands on its own.

**The router** is one cheap model call that tags what *kind* of answer the
question wants:

| Tag | Example | Goes to |
| --- | --- | --- |
| numeric | "How much is Assignment 2 worth?" | Text-to-SQL, then search if that fails |
| lookup | "Which tool copies files to EC2?" | hybrid search |
| relationship, overview, solve | "How do X and Y relate?" | hybrid search (for now) |

**Measured:** the right tag for **21 of 21** practice questions (the target
was 19).

---

## Text-to-SQL

**What it is:** the model writes a database query; the database finds the
numbers.

1. The model sees the sheet's layout and labels, **but not the number values**.
2. It writes **one read-only SELECT** returning the cells the answer needs,
   with each cell's address. **No arithmetic in SQL:** sums happen in the
   answer's steps, where the checker can see them.
3. Anything but a single SELECT is refused. On an error it gets one retry;
   then the question falls back to search.

**Measured:** the exact number for **7 of 7** numeric practice questions (the
target was 6). Each answer cites the cell, e.g. `Income Statement!C13 = 14000`.

---

## Vector search

**What it is:** finding the chunks whose embeddings are closest to the
question's.

- Good for paraphrased questions: "Can I miss class if I'm sick?" finds "I
  can't attend a lesson due to a valid reason (medical reasons, …)", with no
  word in common but "I".
- Weak on exact codes, names and numbers.
- Anchor uses pgvector (cosine distance) inside Postgres, filtered to the
  asking user's own Library.

---

## Hybrid search and RRF

**Hybrid search** runs keyword search and vector search, each returning up to
150 chunks, and merges the two lists.

**RRF (reciprocal rank fusion)** does the merging. Each chunk scores, for each
list it appears in:

```
1 / (60 + its rank in that list)
```

and the scores are added up. Only ranks count, so a keyword score and a
meaning score (different scales) never have to be compared. 60 is the
constant from the original RRF paper.

In Anthropic's tests, embeddings plus BM25 cut retrieval failures by 49%.

---

## Reranker

**What it is:** a second model that reads the question and each candidate
**together**, and scores how well that chunk answers it.

**What Anchor uses:** `bge-reranker-v2-m3`, self-hosted. The **top 5** go to
the answering model.

- In Anthropic's tests, hybrid search plus reranking cut failures by 67%.
- **Our trade-off:** it is the slow part, 21-34 s per question on a laptop
  processor.
- **Measured:** we tried three faster settings. None handed the model the
  same top 5 on all 34 practice questions, so we kept the current one.

---

## Answering

The model sees **only the 5 passages**, never the whole web, and must:

1. **Quote each step word for word** from one passage, and name it.
2. Decide, in this order:
   - the passages answer it: **answer**;
   - they answer part of it: **that part, plus what's missing**;
   - they answer none of it: **"Not found in your materials"**.
3. Not open with "Yes" or "No" unless the passages settle it.

The answer **streams** onto the screen as it is written, and each step has a
**Source** button that opens the passage with the quote highlighted.

---

## The checker

Every answer is checked **before it's trusted**:

1. **Quotes, by code (free):** every quote must appear word for word in the
   passage it cites.
2. **Support, by the model:** is each step actually supported by the
   passages?

If any check fails, or can't be run, the answer is labelled **Unsure** and
says which check failed. **It fails closed.**

Plus the safety nets the checker can't provide:
- the **picture** an answer rests on is shown;
- the **scanned page** an answer rests on is shown.

---

# Part 3: Proving it works

---

## The eval set

- **30 real course questions**, written before any code, each with its correct
  answer, file and page.
  - **3 kinds,** 10 each: lookups, numbers, and questions the files can't
    answer.
  - **5 file formats:** PDF, Word, spreadsheet, text, image.
- **21 practice (Build) questions,** used freely while building.
- **9 Test questions,** locked and never opened while building, run once at
  the end.
- **13 added Build questions,** to test harder without touching the Test set.

**Why:** without an eval set, there is no way to know whether a change helped.

---

## The Comparison ladder

The same 21 questions, the same model and the same scoring; each rung adds one
thing:

| Setup | Correct | Unsupported claims |
| --- | --- | --- |
| The model alone | 6 of 21 | 1 of 21 |
| + vector search | 19 of 21 | 0 of 21 |
| + hybrid search and reranker | 18 of 21* | 0 of 21 |
| **Anchor (routed)** | **21 of 21** | **0 of 21** |

- **When only 1 passage is handed over:** hybrid 19 of 21, vector 16 of 21.
- **On the 13 added questions:** hybrid 13 of 13, vector 12 of 13.
- **On the 9 locked Test questions (run once, 21 Oct): Anchor 9 of 9, with 0
  unsupported claims.**
- **On 3 locked new-problem questions (run once, 21 Oct):** 2 of 3; the miss
  needed a spreadsheet.

\* A correct refusal worded in a way the scorer didn't recognise. One run per
result.

---

## Checking the checkers

An AI judging an AI needs its own test:

- **The grader** marks each claim against the **whole** course, not just what
  was found.
  - It caught **21 of 21** made-up sentences planted on purpose.
  - It gave **0 false alarms** on the real answer key.
- **The checker** was compared with separate labels on 30 answers:
  - **25 of 30** agreed;
  - **2 misses** (the limit set in advance was 2);
  - **3 false alarms**.
- **Scans:** from photo-like scans of a 10-page handout, **6 of 7** practice
  questions came out right, against 7 of 7 from the original file. The one
  miss was read from the same words in both.

---

## What it runs on

| Part | What |
| --- | --- |
| AI model | OpenAI GPT-5.6 Luna: routing, answering, checking, reading pictures |
| Search | `text-embedding-3-small`, Postgres + pgvector, `bge-reranker-v2-m3` (self-hosted) |
| Files | Docling, RapidOCR, OpenCV, DuckDB |
| Website | FastAPI app, sign-in with WorkOS |
| Hosting | Front pages on Vercel; the app on a Mac, shared by Tailscale Funnel |
| Cost | About $0.002-0.003 per answer (estimated from token counts); a $5 demo budget |

**Privacy:** each user's Library is private, and every search is filtered to
its owner. Deleting a file removes it from every index.

---

## Known limits

- **Arithmetic isn't checked:** a date worked out by the model can be wrong
  and still pass.
- **"Your materials don't say"** describes the passages found, so it's wrong
  when search misses one.
- **Slow:** about 30 seconds per answer, mostly the reranker.
- **Small numbers, one run each:** results can move by a question or two.
- **Scans:** printed pages only; handwriting isn't read reliably yet.

---

# In the build plan, but not used (yet)

---

## Is there a knowledge graph? No.

**What it is:** an AI extracts the entities in your files (people, topics,
rules) and the links between them, then answers by walking those links.

**What it helps with:**
- "How is A connected to C?"
- "What are the main themes of this course?"

These are questions where the answer is spread across many places, not
sitting in one passage.

**Why not now:**
- **It was stretch rung S1** (LightRAG), to be kept only if it beat hybrid
  search on those question types.
- **No eval questions** for "relationship" or "overview" have been written
  yet.
- **Studies show graphs don't help simple lookups;** they tie or lose to plain
  passages there.

The router already tags these questions, so a graph route can be added later.

---

## Other parts of the plan, not used

| Not used | What it helps with |
| --- | --- |
| **Multi-hop loop** (S2) | Search, note what's still missing, search again (up to 3 rounds), for answers spread across several places |
| **Tree navigation (PageIndex)** (S3) | The model reads a long PDF's table of contents and drills into the right section; strong on long, structured documents |
| **Worked solutions** (S4) | Solving new problems with every calculation run as code and an independent re-solve. Tried 21 Oct and dropped: 5 of 7 practice questions correct with it, 6 of 7 without |
| **Web answers** (S5) | Offered after "Not found in your materials", from cited web pages and checked the same way |
| **OCRmyPDF** | Adds a text layer to scanned PDFs; replaced by Docling's built-in OCR |

---

## Other parts of the plan, not used (continued)

| Not used | What it helps with |
| --- | --- |
| **`bge-m3` embeddings** | Self-hosted meaning search with no per-use cost; tested, tied with 3-small, not chosen |
| **Voyage (`voyage-4`, `rerank-3`)** | A paid fallback if the server lacks memory for the self-hosted reranker; not needed |
| **Reranking 150 down to 20** | The plan for real-size Libraries; Anchor still hands over 5, which suits small Libraries |
| **A trained router** (Adaptive-RAG) | A small classifier, trained on logged questions, picking how much searching a question needs |
| **Ready-made frameworks** (LightRAG, RAGFlow, R2R, LlamaIndex, LangGraph) | Faster setup; we built each step ourselves, to measure it |
| **A free cloud server** | Always-on hosting; the free tier was too small, so the app runs on a Mac for now |

---

# Thank you

**Anchor:** answers from your own files, with every step quoted, every source
one click away, and "not found" instead of a guess.

Try it: anchor-study.vercel.app
