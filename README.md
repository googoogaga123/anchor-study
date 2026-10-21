# Anchor: ask your course materials anything

Anchor answers questions from your own course files. Every answer quotes the
exact words it rests on, links to where they came from, and says plainly when
your materials don't cover something.

- **Live:** https://anchor-study.vercel.app (press **Try Anchor** to open the app)
- **Demo clips:** on the front page, recorded from the live app

---

## 1. Problem statement

A student's course material is spread across PDFs, Word documents, slides,
screenshots, text notes and spreadsheets. Finding one rule ("How many quizzes
do I need for full marks?", "What can I bring into the exam?") means digging
through several files, often the night before a deadline.

General chatbots don't help much here. They don't know your course, and they
answer confidently anyway. In our test on a real course, the same AI model on
its own answered **6 of 21** course questions correctly and made claims the
course files don't back. A wrong deadline, mark weighting or exam rule costs
real marks, so students need answers they can check, not answers they have to
trust.

## 2. Solution overview

You add your course files to a private **Library** and ask questions in plain
words. Anchor finds the relevant passages, answers **only from them**, and
shows its working:

- each step of the answer quotes the words it rests on, with a link to the PDF
  page, the line in your notes or the spreadsheet cell;
- if your files don't cover the question, it says so instead of guessing; if
  they cover only part of it, you get that part plus a note on what's missing;
- a second check confirms every quote really is in the file and supports the
  step; if not, the answer is marked **Unsure** and says which check failed.

On the same 21 questions, Anchor answered **21 of 21** correctly with **0**
unsupported claims.

## 3. Key features

- **Explained answers:** numbered steps, each with its quote and a Source
  button that opens the excerpt with the quoted words marked.
- **Honest about gaps:** "Not found in your materials", or a partial answer
  that names what the materials don't say.
- **Unsure label** whenever a quote can't be found or doesn't support its step.
- **Reads pictures:** flowcharts, graphs and screenshots are described when a
  file is added; an answer that rests on a picture shows it beside the answer,
  with a note to check it.
- **Numbers from spreadsheets:** questions about figures are answered from the
  exact cell, which the answer names.
- **Scan printed pages with a phone:** photos are cropped and straightened on
  the server (OpenCV), blurry or empty ones are flagged, and each page is
  read by OCR (Docling with RapidOCR, both local and free) while the student
  reviews it. "Check text" shows what was read beside the photo, so any
  misread word can be fixed before saving; the checked text is what gets
  indexed. Scanned PDFs from a phone's own scanner app are read by the same
  OCR when added.
- **Follow-up questions** ("and how much is each one worth?") understood from
  the conversation.
- **Private Libraries:** drag files into the chat (PDF, Word, text, pictures,
  spreadsheets); nothing is shared between users; deleting a file removes it
  everywhere.
- **Streamed answers**, a Sources panel, and a searchable Library.
- **Demo limits:** members get 1 file (up to 50 pages) and 3 questions; a
  spending cap protects the demo budget.

## 4. AI integration

AI does the reading, finding, routing, answering and judging; plain code does
the checking around them.

| Step | What happens | AI used |
| --- | --- | --- |
| Reading files | Layout, tables and formulas extracted from PDFs and Word files | Docling (layout and formula models) |
| Describing pictures | Each picture described in text; its arrows read 3 times, keeping only connections 2 of 3 readings agree on | GPT-5.6 Luna (vision) |
| Finding passages | Keyword search and meaning search combined, then re-ranked | `text-embedding-3-small`, `bge-reranker-v2-m3` |
| Routing | The question's kind is tagged; number questions go to the spreadsheets, where the model writes one read-only SQL query, with search as the fallback | GPT-5.6 Luna |
| Answering | Answer from the excerpts only, quoting each step word for word; answer, partial answer or "not found", decided in that order | GPT-5.6 Luna |
| Checking | Code confirms each quote is in its excerpt; the model judges whether the quote supports the step | GPT-5.6 Luna |
| Follow-ups | A follow-up is rewritten to stand on its own | GPT-5.6 Luna |

It was built as a **Comparison ladder**, each rung measured on the same
questions before the next was added:

| Setup (21 practice questions) | Correct | Unsupported claims |
| --- | --- | --- |
| The model alone | 6 of 21 | 1 of 21 |
| + vector search | 19 of 21 | 0 of 21 |
| + hybrid search and reranking | 18 of 21* | 0 of 21 |
| **Anchor (routed)** | **21 of 21** | **0 of 21** |

\* One miss is a scoring miss: a correct refusal worded in a way the scorer
didn't recognise. Counts are from one run each (18 Oct 2026).

**On 9 held-back questions** (the Test set, locked away while building and
run once, on 21 Oct 2026), Anchor answered **9 of 9** correctly with **0 of 9**
unsupported claims: 3 of 3 lookups, 3 of 3 number questions, and 3 of 3
questions the files can't answer refused instead of guessed.

**Tried and dropped: worked solutions** (stretch rung S4: a new problem solved
with the course's methods, every calculation run as code, and a second,
independent solve that must agree). On 7 practice questions with new numbers
(21 Oct 2026), Anchor with worked solutions got **5 of 7**; without them, **6 of 7**.
Of the 2 questions that reached worked solutions, it solved 1. Both were
flagged Unsure, the wrong one and one correct answer whose second solve
disagreed. It is not used. Anchor without it was then run once on the 3
held-back test questions of this kind: **2 of 3** correct, both flagged Unsure;
the miss asked about a spreadsheet (see Known limits).

## 5. External tools and datasets

- **Models and APIs:** OpenAI API (GPT-5.6 Luna for answering, routing,
  checking and picture descriptions; `text-embedding-3-small` for embeddings);
  Google Gemini 3.5 Flash Lite (two screenshot descriptions in the test
  Library, after every OpenAI model misread an arrow); BAAI
  `bge-reranker-v2-m3` (runs locally); PP-OCRv6 through RapidOCR (reads
  scanned pages, locally).
- **Libraries:** Docling, PostgreSQL with pgvector, DuckDB, FastAPI and
  uvicorn, pypdfium2, openpyxl, sentence-transformers, tiktoken, OpenCV
  (straightening scanned pages), Pillow.
- **Services:** WorkOS AuthKit (sign-in), Vercel (front page), Tailscale
  Funnel (serving the app), Fontshare and Google Fonts.
- **Demo clips:** Playwright and ffmpeg, recording the live app.
- **Dataset:** a sample course Library from Singapore Management University
  (IS114 course content, a microeconomics sample midterm with solutions, an
  accounting worksheet, lab hints, two screenshots) and 43 hand-written
  questions with answers checked against the files. **Not published:** the
  files are the university's material and list teaching staff's contact
  details. One staff name in `scripts/near_miss.json` reads `[redacted]`.

## 6. Installation and setup

You need Python 3.13, PostgreSQL with the pgvector extension, and an OpenAI
API key. On macOS:

```
# 1. Get the code
git clone https://github.com/googoogaga123/anchor-study.git && cd anchor-study

# 2. Python packages (Docling and the reranker download their models on first use)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Postgres with pgvector
brew install postgresql@17 pgvector && brew services start postgresql@17
createdb ailodge
psql -d ailodge -c "CREATE EXTENSION IF NOT EXISTS vector"

# 4. Your key
cp .env.example .env        # put your OpenAI key in OPENAI_API_KEY; leave the WorkOS lines empty for local use

# 5. Run
OWNER_EMAIL=you@example.com DEMO_EVAL_LIBRARY=0 .venv/bin/uvicorn web.app:app --port 8000
```

Open http://localhost:8000, press **Try Anchor**, sign in with the email you
gave as `OWNER_EMAIL` (the local development sign-in), drag your course files
into the chat, and ask. Without WorkOS keys the development sign-in is used;
never put that version online.

## 7. AI safety and limitations

**Guardrails in place**

- **Answers only from your files.** The model sees only the retrieved
  excerpts and must quote each step word for word; a step whose quote isn't in
  its excerpt, or doesn't support it, makes the answer Unsure.
- **Refuses instead of guessing.** On 7 practice questions the files can't
  answer, Anchor declined all 7.
- **Pictures are shown, not just described.** A picture description can be
  wrong, so any answer resting on one shows the picture with a note to check it.
- **Scanned pages are shown too.** An OCR misread would match its own quote,
  so the checker can't catch it; any answer resting on a scanned page shows
  that page ("Read by OCR from p. 3 ... check the page"), and adds
  "corrected by you" when the student edited that page's text. A file that
  yields no text fails with a plain message instead of sitting empty in the
  Library.
- **Spreadsheet queries are locked down:** a read-only connection, one SELECT
  only, anything else refused.
- **Privacy:** each Library is private; every search is filtered by its owner;
  delete removes a file everywhere. Files are sent to OpenAI to be read and
  answered.
- **Abuse and cost:** sign-in required, per-member limits, a spending cap.

**Testing done**

- The Comparison ladder above: every rung scored on the same questions by an
  automatic grader that checks each claim against the whole course Library.
- The grader was tested with planted false claims before it was trusted.
- The checker was compared with separate labels on 30 sampled answers: it agreed on 25,
  missed 2 bad answers (the limit set in advance was 2) and wrongly flagged 3.
- 9 held-back test questions, kept unopened while building, were run once on
  21 Oct 2026: 9 of 9 correct, 0 unsupported claims, 0 Unsure.
- 3 more held-back questions, new problems to work out, were run once on
  21 Oct 2026: 2 of 3 correct, 1 unsupported claim, 2 Unsure.
- **Scanning (20 Oct 2026):**
  - **OCR on clean pages:** the IS114 handout's 10 pages, rendered as images,
    gave back 1,921 of the original's 1,989 words, with both tables' rows and
    the page numbers, at 8.5 s a page.
  - **From phone-like photos:** 10 synthetic photos of the same pages (tilted
    on a desk) were all cropped. The 7 practice questions answered from that
    PDF came out 6 of 7 correct from the scan and 7 of 7 from the original.
  - **The one miss** was the deliberately ambiguous quiz question (A10). It
    was read from the same words in both, so it is run-to-run variation, not
    the OCR.

**Known limits**

- **Unchecked arithmetic.** The checker verifies quotes, not sums or dates
  worked out from them. In a live test Anchor said a quiz closes on 31/8 when
  the files imply Sunday 30/8, and it wasn't flagged.
- **A new problem about a spreadsheet isn't read from it.** Only number
  questions go to the spreadsheets; a problem to work out from one is
  answered from searched files instead and can come back "Not found".
- **Stretched conclusions can pass.** Both checker misses quoted real text but
  concluded more than it said (for example, applying one exam question's
  numbers to another).
- **"Your materials don't say" can be wrong** when search misses the passage:
  it describes the excerpts found, not the whole Library.
- **Slow:** about 30 seconds per answer that searches your files, because the
  reranker runs on a laptop processor.
- **Small test set, one run each:** results can move by a question or two
  between runs.
- **Scans: printed pages only, tested on synthetic photos.** Handwriting,
  maths and real phone photos (glare, curled pages, cluttered backgrounds) are
  not measured yet. Auto-crop needs the page to stand out from its background;
  otherwise the photo is kept as taken. Reading takes about 6 s a page.
- **A corrected page is trusted as typed.** Answers quote the student's
  corrected text, and the checker checks quotes against it, not against the
  photo, so a wrong correction would pass. The page is still shown beside
  the answer, marked "corrected by you".
