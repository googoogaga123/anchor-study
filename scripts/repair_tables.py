"""Repair table headers whose words Docling put in the wrong column.

The case that prompted it - midterm p. 10, Q11's willingness-to-pay table:

    Docling:  |  | Consumer | A Consumer B | Consumer C |
    The PDF:  |  | Consumer A | Consumer B | Consumer C |

The numbers underneath were right; only the header words were misassigned.
TableFormer predicts column boundaries, then slots the PDF's own words into
them, and a boundary that falls between "Consumer" and "A" pushes the "A" one
column right. No Docling setting fixes it: do_cell_matching=False drops the
header row entirely.

The repair uses geometry the PDF already has. Body cells give each column's
horizontal span - from the left edge of its leftmost entry to the right edge of
its rightmost. Every header word is placed in the column whose span contains
the word's centre, or the nearest span when it sits in a gap between columns.
Spans, not centres: in a left-aligned text column (the IS114 "Venue" column of
long room names) the centre sits far right of where the header word starts,
and a centre rule moved "Venue" into the "End" column. Two guards keep it from
damaging a table Docling got right:

  1. The header words read from the PDF text layer must be exactly the words
     in Docling's header, in order. Otherwise (a scan with no text layer, an
     OCR'd page, a mismatch) the table is left alone.
  2. The rebuilt header must sit over its columns clearly better than
     Docling's did: the total distance from each header word to the span of
     the column it is in must drop by at least MIN_GAIN points. A header
     already inside its column's span scores 0 and is never touched.

Headers with a merged cell (one header spanning several columns) are skipped:
a spanning header has no single column to line up with.

This is a fix in the pipeline, not to one file: it runs on every PDF at parse
time (parse_docs.py) and reports what it changed.
"""
import json
import pathlib
import re
import sys

import pypdfium2 as pdfium
from docling_core.types.doc import CoordOrigin, DoclingDocument

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIN_GAIN = 1.0  # points; a page is ~595 wide


def page_words(pdf, page_no):
    """Words on a page as (text, left, right, top, bottom), top-left origin."""
    page = pdf[page_no - 1]
    _, height = page.get_size()
    tp = page.get_textpage()
    words, cur = [], None
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        l, b, r, t = tp.get_charbox(i)
        top, bottom = height - t, height - b
        if not ch.strip():
            if cur:
                words.append(cur)
            cur = None
            continue
        # A gap wider than ~a third of the glyph height ends the word, for PDFs
        # that position words without writing a space character.
        if cur and l - cur[2] <= 0.35 * max(bottom - top, 1):
            cur = [cur[0] + ch, cur[1], r, min(cur[3], top), max(cur[4], bottom)]
        else:
            if cur:
                words.append(cur)
            cur = [ch, l, r, top, bottom]
    if cur:
        words.append(cur)
    return words


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def _gap(x, span):
    """Distance from x to a column span; 0 inside it."""
    lo, hi = span
    return 0.0 if lo <= x <= hi else min(abs(x - lo), abs(x - hi))


def _misalignment(groups, spans):
    """Sum over header words of the distance from the word to its column's span."""
    return sum(_gap((w[1] + w[2]) / 2, spans[col]) for col, ws in groups.items() for w in ws)


def repair_table(table, words, page_height):
    cells = table.data.table_cells
    header = [c for c in cells if c.column_header]
    body = [c for c in cells if not c.column_header and c.bbox is not None]
    if not header or not body or any(c.col_span > 1 for c in header):
        return None

    def tl(bbox):
        return bbox if bbox.coord_origin == CoordOrigin.TOPLEFT else bbox.to_top_left_origin(page_height)

    spans = {}
    for col in range(table.data.num_cols):
        boxes = [tl(c.bbox) for c in body if c.start_col_offset_idx == col and c.col_span == 1]
        if not boxes:
            return None  # a column with no body cells has no span to line up with
        spans[col] = (min(b.l for b in boxes), max(b.r for b in boxes))

    tbox = tl(table.prov[0].bbox)
    changes = []
    for row in sorted({c.start_row_offset_idx for c in header}):
        row_cells = sorted((c for c in header if c.start_row_offset_idx == row),
                           key=lambda c: c.start_col_offset_idx)
        if any(c.bbox is None for c in row_cells):
            continue
        top = min(tl(c.bbox).t for c in row_cells)
        bottom = max(tl(c.bbox).b for c in row_cells)
        in_row = sorted((w for w in words
                         if top - 1 <= (w[3] + w[4]) / 2 <= bottom + 1
                         and tbox.l - 2 <= (w[1] + w[2]) / 2 <= tbox.r + 2),
                        key=lambda w: w[1])
        # Guard 1: the text layer must hold exactly Docling's header words.
        if _norm(" ".join(w[0] for w in in_row)) != _norm(" ".join(c.text for c in row_cells)) \
                or not in_row:
            continue

        def cell_of(w):
            x = (w[1] + w[2]) / 2
            for c in row_cells:
                b = tl(c.bbox)
                if b.l - 0.5 <= x <= b.r + 0.5:
                    return c.start_col_offset_idx
            return None

        before = {c.start_col_offset_idx: [] for c in row_cells}
        for w in in_row:
            col = cell_of(w)
            if col is None:
                break
            before[col].append(w)
        else:
            after = {col: [] for col in spans}
            for w in in_row:
                x = (w[1] + w[2]) / 2
                after[min(spans, key=lambda col: (_gap(x, spans[col]),
                                                  abs(x - sum(spans[col]) / 2)))].append(w)
            if any(ws and col not in before for col, ws in after.items()):
                continue  # would need a header cell Docling did not create
            gain = _misalignment(before, spans) - _misalignment(after, spans)
            # Guard 2: only accept a rebuild that lines up clearly better.
            if gain < MIN_GAIN:
                continue
            old = [c.text for c in row_cells]
            new = [" ".join(w[0] for w in after.get(c.start_col_offset_idx, [])) for c in row_cells]
            if new == old:
                continue  # same words, same columns: nothing to repair
            for c in row_cells:
                c.text = " ".join(w[0] for w in after.get(c.start_col_offset_idx, []))
            changes.append({"row": row, "before": old, "after": [c.text for c in row_cells],
                            "alignment_gain_pt": round(gain, 1)})
    return changes or None


def repair_document(doc, pdf_path):
    """Repair every table in a Docling document. Returns a list of what changed."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    repairs, cache = [], {}
    for i, table in enumerate(doc.tables):
        if not table.prov:
            continue
        pno = table.prov[0].page_no
        if pno not in cache:
            cache[pno] = page_words(pdf, pno)
        changes = repair_table(table, cache[pno], doc.pages[pno].size.height)
        if changes:
            # table.data.grid is rebuilt from table_cells on every read, so
            # editing the cells is enough for the markdown export.
            repairs.append({"table": i, "page": pno, "changes": changes})
    pdf.close()
    return repairs


def main():
    """Repair already-parsed PDFs in place, without re-running Docling."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from parse_docs import DOCS, OUT, SRC, export, stem_for  # noqa: E402

    report_path = OUT / "docs_report.json"
    report = json.loads(report_path.read_text())
    for name in DOCS:
        if not name.endswith(".pdf"):
            continue
        stem = stem_for(name)
        doc = DoclingDocument.model_validate(json.loads((OUT / f"{stem}.json").read_text()))
        repairs = repair_document(doc, SRC / name)
        print(f"{name}: {len(repairs)} table(s) repaired")
        for r in repairs:
            for ch in r["changes"]:
                print(f"  p. {r['page']} table {r['table']}: {ch['before']} -> {ch['after']} "
                      f"(alignment +{ch['alignment_gain_pt']} pt)")
        export(doc, stem, name)
        report[name]["tables_repaired"] = repairs
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
