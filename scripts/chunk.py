"""Phase 2, step 6: cut the parsed text into chunks for search.

Starting guesses from the build plan: ~800 tokens per chunk, ~100 overlap.
Both get tuned later against the eval set; nothing here is final.

Every chunk keeps the location its eval questions cite, so a citation can
point back at the user's own file:

  PDF   page range       ("p. 10", "pp. 10-11")
  TXT   line range       ("lines 24-35")
  DOCX  heading only     (the Word file has no page numbers to give)
  PNG   the whole image  (its Diagram description, from describe_images.py)

The spreadsheet is NOT chunked. Its answers are cell addresses
(`Income Statement!C13`), so it stays in DuckDB for the SQL route.
The two PNGs are chunked through their Diagram descriptions (step 5); a
chunk of one cites the image file, never the description.

How a chunk is built:
  1. Split each file into blocks: a paragraph, a list, a heading, or a whole
     table. A table is never cut mid-row - half a table answers nothing.
  2. Pack blocks in order until the next one would pass MAX_TOKENS.
  3. Close a chunk early (once it is past SOFT_FLOOR of the max) when the next
     block opens a new section, so a chunk tends to hold one exam question or
     one section rather than the tail of one and the head of the next.
  4. Start the next chunk with whole blocks from the end of the previous one,
     up to OVERLAP_TOKENS. Overlap is whole blocks only, never a cut sentence,
     so a long final block means less overlap rather than a broken one.

Tokens are counted with cl100k_base, the tokenizer text-embedding-3-small uses.

Output: parsed/chunks.jsonl (one chunk per line) and parsed/chunks_report.json.
"""
import json
import pathlib
import re

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "parsed"

MAX_TOKENS = 800
OVERLAP_TOKENS = 100
SOFT_FLOOR = 0.6

ENC = tiktoken.get_encoding("cl100k_base")
SEP_TOKENS = 1  # the blank line ("\n\n") that joins two blocks in a chunk

SOURCES = [
    ("MidtermSampleSolutions.pdf", "PDF", "MidtermSampleSolutions__pdf.pages.md"),
    ("IS114 AY26-T1 Course Content, Student Edition.pdf", "PDF",
     "IS114_AY26-T1_Course_Content_Student_Edition__pdf.pages.md"),
    ("IS114 AY26-T1 Course Content, Student Edition.docx", "Word",
     "IS114_AY26-T1_Course_Content_Student_Edition__docx.md"),
    ("week12hints.txt", "Text", "week12hints__txt.lines.txt"),
    ("IS114_eLearn_Quizzes_tab.png", "Image", "IS114_eLearn_Quizzes_tab__png.md"),
    ("IS114_Academic_Violation_Reporting_Procedure.png", "Image",
     "IS114_Academic_Violation_Reporting_Procedure__png.md"),
]

# An exam question opens a new section even though Docling does not mark it as
# a heading: "Q11) ..." in the midterm.
# Docling sometimes reads one as a list item: "- Q9) ...", "- Q14) ...".
QUESTION = re.compile(r"^(?:[-*]\s+)?Q(\d+)\)")
# Section lines in the plain-text file: "Week 12: Mission 3 Hints", "Task 1: ..."
TXT_SECTION = re.compile(r"^(Week|Task|Step|Part)\s*\d+\s*:")


def ntok(s):
    return len(ENC.encode(s))


def compact_table(text):
    """Drop the padding Docling adds to line up markdown columns.

    Lossless for meaning, and it matters: padding made the IS114 sections table
    869 tokens, over MAX_TOKENS, so it was split by rows and G11 landed alone in
    the next chunk - the near-miss trap (Q22 asks about G12) in miniature.
    """
    rows = []
    for line in text.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            cells = ["---"] * len(cells)
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def blocks_from_markdown(md, paged):
    """Blocks from Docling markdown. Pages come from '## page N' markers."""
    blocks, page = [], None
    section, question = None, None
    buf, buf_kind = [], None

    def flush():
        nonlocal buf, buf_kind
        if buf:
            text = "\n".join(buf).strip()
            if buf_kind == "table":
                text = compact_table(text)
            if text:
                blocks.append({"text": text, "kind": buf_kind, "page": page,
                               "heading": " > ".join(x for x in (question, section) if x)})
        buf, buf_kind = [], None

    for line in md.splitlines():
        if paged and (m := re.match(r"^## page (\d+)\s*$", line)):
            flush()
            page = int(m.group(1))
            continue
        if paged and line.startswith("# ") and page is None:
            continue  # the file-name title pages.md adds; not document text
        if m := re.match(r"^(#{1,6})\s+(.*)", line):
            flush()
            section = m.group(2).strip()
            blocks.append({"text": line.strip(), "kind": "heading", "page": page,
                           "heading": " > ".join(x for x in (question, section) if x),
                           "opens_section": True})
            continue
        if m := QUESTION.match(line):
            flush()
            question, section = f"Q{m.group(1)}", None
        is_table = line.lstrip().startswith("|")
        kind = "table" if is_table else "text"
        if not line.strip():
            if buf_kind != "table":
                flush()
            continue
        if buf and buf_kind != kind:
            flush()
        buf_kind = kind
        buf.append(line)
    flush()

    # Mark question starts as section openers for the soft break.
    for b in blocks:
        if QUESTION.match(b["text"]):
            b["opens_section"] = True
    return blocks


def blocks_from_lines(numbered):
    """Blocks from the line-numbered text file: runs of non-blank lines."""
    blocks, buf, section = [], [], None

    def flush():
        nonlocal buf
        if buf:
            blocks.append({
                "text": "\n".join(t for _, t in buf),
                "kind": "text", "line_start": buf[0][0], "line_end": buf[-1][0],
                "heading": section or "",
                "opens_section": bool(TXT_SECTION.match(buf[0][1])),
            })
        buf = []

    for raw in numbered.splitlines():
        m = re.match(r"^\s*(\d+)  ?(.*)$", raw)
        if not m:
            continue
        no, text = int(m.group(1)), m.group(2)
        if not text.strip():
            flush()
            continue
        if TXT_SECTION.match(text):
            flush()
            section = text.strip()
        buf.append((no, text))
    flush()
    return blocks


def split_oversized(block):
    """A block bigger than MAX_TOKENS: tables by rows (header repeated),
    anything else by lines. Not hit by the current eval Library, kept so a
    user's long table cannot silently become one giant chunk."""
    if block["tokens"] <= MAX_TOKENS:
        return [block]
    lines = block["text"].split("\n")
    head = lines[:2] if block["kind"] == "table" else []
    body = lines[2:] if head else lines
    parts, cur = [], list(head)
    for ln in body:
        if ntok("\n".join(cur + [ln])) > MAX_TOKENS and len(cur) > len(head):
            parts.append(cur)
            cur = list(head)
        cur.append(ln)
    parts.append(cur)
    out = []
    for p in parts:
        b = dict(block, text="\n".join(p))
        b["tokens"] = ntok(b["text"])
        out.append(b)
    return out


def pack(blocks):
    """Greedy packing with soft section breaks and whole-block overlap."""
    chunks, cur, cur_tok = [], [], 0
    for b in blocks:
        b_tok = b["tokens"] + SEP_TOKENS
        too_big = cur and cur_tok + b_tok > MAX_TOKENS
        soft = (cur and b.get("opens_section")
                and cur_tok >= SOFT_FLOOR * MAX_TOKENS)
        if too_big or soft:
            # Never end a chunk on a heading: carry it into the next one.
            carry = []
            while cur and cur[-1]["kind"] == "heading":
                carry.insert(0, cur.pop())
            if cur:
                chunks.append(cur)
            overlap, o_tok = [], 0
            for prev in reversed(cur):
                if o_tok + prev["tokens"] + SEP_TOKENS > OVERLAP_TOKENS:
                    break
                overlap.insert(0, dict(prev, overlap=True))
                o_tok += prev["tokens"] + SEP_TOKENS
            cur = overlap + carry
            cur_tok = sum(x["tokens"] + SEP_TOKENS for x in cur)
        cur.append(b)
        cur_tok += b_tok
    if cur:
        chunks.append(cur)
    return chunks


def location(blocks, fmt):
    pages = sorted({b["page"] for b in blocks if b.get("page")})
    lines = [b for b in blocks if b.get("line_start")]
    if pages:
        lo, hi = pages[0], pages[-1]
        return {"page_start": lo, "page_end": hi,
                "loc": f"p. {lo}" if lo == hi else f"pp. {lo}-{hi}"}
    if lines:
        lo, hi = lines[0]["line_start"], lines[-1]["line_end"]
        return {"line_start": lo, "line_end": hi, "loc": f"lines {lo}-{hi}"}
    return {"loc": None}


def main():
    all_chunks, report = [], {}
    for fname, fmt, rel in SOURCES:
        body = (OUT / rel).read_text(encoding="utf-8")
        if fmt == "Text":
            blocks = blocks_from_lines(body)
        else:
            blocks = blocks_from_markdown(body, paged=(fmt == "PDF"))
        for b in blocks:
            b["tokens"] = ntok(b["text"])
        blocks = [p for b in blocks for p in split_oversized(b)]

        packed = pack(blocks)
        for i, group in enumerate(packed, 1):
            text = "\n\n".join(b["text"] for b in group)
            headings = list(dict.fromkeys(b["heading"] for b in group if b["heading"]))
            new = [b for b in group if not b.get("overlap")]
            all_chunks.append({
                # Keep the __pdf/__docx suffix: the IS114 PDF and Word file share
                # a basename and hold different content.
                "chunk_id": f"{rel.split('.')[0]}#{i:03d}",
                "file": fname,
                "format": fmt,
                **location(group, fmt),
                "heading": (new[0] if new else group[0])["heading"],
                "headings": headings,
                "tokens": ntok(text),
                "overlap_tokens": sum(b["tokens"] for b in group if b.get("overlap")),
                "has_table": any(b["kind"] == "table" for b in group),
                "text": text,
            })
        mine = [c for c in all_chunks if c["file"] == fname]
        report[fname] = {
            "blocks": len(blocks),
            "chunks": len(mine),
            "tokens_total": sum(b["tokens"] for b in blocks),
            "chunk_tokens_min": min(c["tokens"] for c in mine),
            "chunk_tokens_max": max(c["tokens"] for c in mine),
            "largest_block": max(b["tokens"] for b in blocks),
        }

    with (OUT / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    settings = {"max_tokens": MAX_TOKENS, "overlap_tokens": OVERLAP_TOKENS,
                "soft_floor": SOFT_FLOOR, "tokenizer": "cl100k_base"}
    (OUT / "chunks_report.json").write_text(
        json.dumps({"settings": settings, "files": report}, indent=2), encoding="utf-8")

    print(json.dumps(settings))
    for fname, r in report.items():
        print(f"{r['chunks']:>3} chunks  {r['tokens_total']:>5} tokens  "
              f"(chunk {r['chunk_tokens_min']}-{r['chunk_tokens_max']}, "
              f"largest block {r['largest_block']})  {fname}")
    print(f"{len(all_chunks):>3} chunks total -> parsed/chunks.jsonl")


if __name__ == "__main__":
    main()
