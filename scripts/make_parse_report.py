"""Phase 2, step 4: build parsed/parse_report.md for the owner to check.

Re-runnable: run it again after any parsing change and the counts update.
It does not judge the images - those need the owner's eye, so it lays out
what to compare and leaves the boxes unticked.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "parsed"
PY = ROOT / ".venv" / "bin" / "python"


def excerpt(path, start, n=14):
    p = OUT / path
    if not p.exists():
        return f"_(missing: parsed/{path})_"
    lines = p.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if start.lower() in ln.lower():
            return "\n".join(lines[i:i + n])
    return "\n".join(lines[:n])


def main():
    check = subprocess.run([str(PY), str(ROOT / "scripts" / "check_ceiling.py")],
                           capture_output=True, text=True)
    docs = json.loads((OUT / "docs_report.json").read_text())
    sheets = json.loads((OUT / "sheets_report.json").read_text())

    L = []
    w = L.append
    w("# Phase 2 parse report")
    w("")
    w("What came out of the 7 eval files, and whether every eval answer is still")
    w("findable in it. Parsing sets a ceiling on every later phase: an answer")
    w("missing here can never be retrieved, reranked or routed to in phases 4-9.")
    w("")
    w("Regenerate with `.venv/bin/python scripts/make_parse_report.py`.")
    w("")
    w("## Parse ceiling")
    w("")
    w("```")
    w(check.stdout.strip())
    w("```")
    w("")
    w("## What was extracted")
    w("")
    w("| File | Format | Extracted |")
    w("| --- | --- | --- |")
    for name, d in docs.items():
        if "pages" in d:
            w(f"| `{name}` | {'PDF' if name.endswith('.pdf') else 'Word'} | "
              f"{d['pages']} pages, {d['tables']} tables, {d['markdown_chars']:,} chars |")
        else:
            w(f"| `{name}` | Text | {d['lines']} lines, {d['chars']:,} chars |")
    tot = sum(s["populated_cells"] for s in sheets["sheets"].values())
    w(f"| `{sheets['file']}` | Spreadsheet | {len(sheets['sheets'])} sheets, {tot} populated cells |")
    w("")
    for sheet, s in sheets["sheets"].items():
        w(f"- **{sheet}** - {s['populated_cells']} cells, {s['formulas']} formulas, grid {s['dims']}")
    w("")
    if sheets["cached_values_missing"]:
        w(f"> **Warning:** formulas with no cached value in {sheets['cached_values_missing']}.")
    else:
        w("> Every formula has a cached value, so the computed numbers are readable.")
    w("")
    w("## For you to check by eye")
    w("")
    w("### 1. The hardest table - midterm p. 10, Q11 willingness-to-pay")
    w("")
    w("Q17 asks for the combined WTP of consumers A, B and C for their first cup")
    w("(**$28**). That is a SUM the model must compute, so no string test is honest -")
    w("what matters is that the table's rows survived intact.")
    w("")
    w("The first-cup row reads 12, 10, 6, which sums to the correct $28.")
    w("")
    w("**The header is repaired automatically.** Docling parsed it as")
    w("`|  | Consumer | A Consumer B | Consumer C |` - the \"A\" pulled one column")
    w("right - which the owner flagged on review. No Docling setting fixes it")
    w("(`do_cell_matching=False` drops the header row entirely), so")
    w("`scripts/repair_tables.py` now runs on every PDF at parse time: it places")
    w("each header word over the column whose body cells it sits above, using the")
    w("PDF's own word positions, and only when that lines up clearly better than")
    w("Docling did. It changed this header and nothing else in the eval Library.")
    w("")
    w("```")
    w(excerpt("MidtermSampleSolutions__pdf.pages.md", "## page 10", 24))
    w("```")
    w("")
    w("### 2. The schedule table - IS114 PDF p. 1")
    w("")
    w("All 10 `not_in_docs` questions are near-misses on this file, so these tables")
    w("must be right or the system refuses for the wrong reason.")
    w("")
    w("```")
    w(excerpt("IS114_AY26-T1_Course_Content_Student_Edition__pdf.pages.md", "## Schedule", 20))
    w("```")
    w("")
    w("### 3. The sections table - IS114 PDF p. 2 (must list G1-G11 and no G12)")
    w("")
    w("```")
    w(excerpt("IS114_AY26-T1_Course_Content_Student_Edition__pdf.pages.md", "## Sections", 18))
    w("```")
    w("")
    w("### 4. The two images - not done yet")
    w("")
    w("- [ ] `IS114_eLearn_Quizzes_tab.png` (Q07): the answer is a pink **arrow**, not text.")
    w("- [ ] `IS114_Academic_Violation_Reporting_Procedure.png` (Q08, Q09, Q10): a flowchart")
    w("      whose meaning depends on which way the arrows run, plus footnotes 2 and 3.")
    w("")
    w("Both need a Diagram description from a vision model (step 5), which needs your")
    w("OpenAI key and a few cents of the Testing budget. OCR alone cannot answer either.")
    w("")
    w("## Where things are")
    w("")
    w("- `parsed/*.pages.md` - per-page markdown for the PDFs (page-numbered citations)")
    w("- `parsed/*.md` - full markdown per file")
    w("- `parsed/*.json` - the full DoclingDocument, input to chunking in step 6")
    w("- `parsed/week12hints__txt.lines.txt` - the txt with line numbers (its answers cite lines)")
    w("- `parsed/sheets.duckdb` - `cells` (ground truth, cell-level) and `labeled` (row label + header)")
    w("- `parsed/sheets/*.txt` - readable cell dumps per sheet")
    w("")

    (OUT / "parse_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(check.stdout)
    print(f"-> parsed/parse_report.md ({len('\n'.join(L))} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
