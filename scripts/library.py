"""The eval Library as the scoring code sees it.

Two views of the same 7 files:

  chunks()        what a retrieval setup searches: parsed/chunks.jsonl
                  (25 chunks; the spreadsheet is not chunked)
  library_text()  everything, whole, for the eval grader: every parsed file
                  plus the spreadsheet's cell dumps (~17.8k tokens). A
                  Hallucination is a claim not backed by the user's course
                  material, so the grader judges against all of it - not
                  just what a setup happened to retrieve.

Evidence a setup shows its model is a list of {"id", "text"} items: a chunk
(id = chunk_id) or, later, a spreadsheet result (id = "sheet:<Sheet>!<Cell>").
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "parsed"

# Parsed artefact per file, in the form its citations use.
FILES = [
    ("MidtermSampleSolutions.pdf", "MidtermSampleSolutions__pdf.pages.md"),
    ("IS114 AY26-T1 Course Content, Student Edition.pdf",
     "IS114_AY26-T1_Course_Content_Student_Edition__pdf.pages.md"),
    ("IS114 AY26-T1 Course Content, Student Edition.docx",
     "IS114_AY26-T1_Course_Content_Student_Edition__docx.md"),
    ("week12hints.txt", "week12hints__txt.lines.txt"),
    ("IS114_eLearn_Quizzes_tab.png", "IS114_eLearn_Quizzes_tab__png.md"),
    ("IS114_Academic_Violation_Reporting_Procedure.png",
     "IS114_Academic_Violation_Reporting_Procedure__png.md"),
]
SPREADSHEET = "3A-Adjust-Class-Worksheet (Answer Key) (1).xlsx"


def chunks():
    return [json.loads(ln) for ln in (OUT / "chunks.jsonl").read_text().splitlines()]


def as_evidence(chunk):
    loc = chunk.get("loc") or chunk.get("heading") or ""
    return {"id": chunk["chunk_id"], "file": chunk["file"], "loc": loc, "text": chunk["text"]}


def library_text():
    parts = []
    for name, rel in FILES:
        parts.append(f"=== FILE: {name} ===\n{(OUT / rel).read_text(encoding='utf-8').strip()}")
    sheets = sorted((OUT / "sheets").glob("*.txt"))
    parts.append(f"=== FILE: {SPREADSHEET} (one block per sheet; cell=value) ===\n"
                 + "\n\n".join(p.read_text(encoding="utf-8").strip() for p in sheets))
    return "\n\n".join(parts)


def sheet_cell(cell_ref):
    """One spreadsheet cell as evidence, e.g. 'Income Statement!C13'."""
    import duckdb
    con = duckdb.connect(str(OUT / "sheets.duckdb"), read_only=True)
    row = con.execute(
        "SELECT value_text, row_label, col_header FROM labeled WHERE cell_ref = ?",
        [cell_ref]).fetchone()
    con.close()
    if not row:
        return None
    value, label, header = row
    text = f"{cell_ref} = {value}" + (f" (row: {label})" if label else "") + (f" (column: {header})" if header else "")
    return {"id": f"sheet:{cell_ref}", "file": SPREADSHEET, "loc": cell_ref, "text": text}
