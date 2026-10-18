"""Phase 2, step 2: parse the text-bearing eval files with Docling.

No OCRmyPDF: both PDFs carry a real text layer and there are no scans.

Formula enrichment is ON, and must stay on. Docling's default pipeline emits
`<!-- formula-not-decoded -->` for equations, and in MidtermSampleSolutions.pdf
six answers live inside those equations - including Q18's $6,500 total profit,
which is simply absent from the default parse. Q19's $950 survived only because
that one line happened to be typed as running text. The build plan calls for
equations extracted as text, so this is required, not optional.

Citations must survive parsing, and each format locates things differently,
so each gets the form its eval questions cite:

  PDF   per-page markdown ("p. 10", "p. 11", "p. 20" in the eval set)
  DOCX  one markdown file, headings intact (no page numbers in this file)
  TXT   copied with line numbers ("Line 55", "Lines 25, 35 and 57")

Outputs, all under parsed/:
  <stem>.md         full markdown, pages separated by <!-- page N -->
  <stem>.pages.md   PDFs only: one "## page N" section per page
  <stem>.json       the full DoclingDocument, for chunking in step 6
"""
import json
import pathlib
import sys
import time

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from normalize_formulas import normalize_text  # noqa: E402
from repair_tables import repair_document  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "eval set"
OUT = ROOT / "parsed"

DOCS = [
    "MidtermSampleSolutions.pdf",
    "IS114 AY26-T1 Course Content, Student Edition.pdf",
    "IS114 AY26-T1 Course Content, Student Edition.docx",
]
TXT = ["week12hints.txt"]


def stem_for(name):
    p = pathlib.Path(name)
    # The IS114 PDF and DOCX share a basename and hold different content.
    return f"{p.stem}{p.suffix.replace('.', '__')}".replace(" ", "_").replace(",", "")


def export(doc, stem, name):
    """Write <stem>.md, <stem>.json and, for paged documents, <stem>.pages.md."""
    md = doc.export_to_markdown(page_break_placeholder="\n\n<!-- page break -->\n\n")
    # Decoded LaTeX arrives with a space between every character, which
    # hides its numbers from keyword search. See normalize_formulas.py.
    md, n_norm = normalize_text(md)
    (OUT / f"{stem}.md").write_text(md, encoding="utf-8")
    (OUT / f"{stem}.json").write_text(json.dumps(doc.export_to_dict(), indent=2, default=str), encoding="utf-8")
    if getattr(doc, "pages", None):
        parts = [f"# {name}", ""]
        for pno in sorted(doc.pages):
            page_md, _ = normalize_text(doc.export_to_markdown(page_no=pno))
            parts += [f"## page {pno}", "", page_md, ""]
        (OUT / f"{stem}.pages.md").write_text("\n".join(parts), encoding="utf-8")
    return md, n_norm


def main():
    OUT.mkdir(exist_ok=True)
    # do_formula_enrichment=False is Docling's default and loses any answer
    # that lives inside an equation. See the module docstring.
    pdf_opts = PdfPipelineOptions()
    pdf_opts.do_formula_enrichment = True
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)}
    )
    report = {}

    for name in DOCS:
        src = SRC / name
        t0 = time.time()
        print(f"parsing {name} ...", flush=True)
        doc = conv.convert(src).document
        stem = stem_for(name)
        # Header words Docling put in the wrong column. See repair_tables.py.
        repairs = repair_document(doc, src) if src.suffix == ".pdf" else []
        md, n_norm = export(doc, stem, name)

        n_pages = len(getattr(doc, "pages", {}) or {})
        n_tables = len(getattr(doc, "tables", []) or [])
        report[name] = {
            "stem": stem, "pages": n_pages, "tables": n_tables,
            "markdown_chars": len(md), "formulas_normalized": n_norm,
            "tables_repaired": repairs,
            "seconds": round(time.time() - t0, 1),
        }
        print(f"  -> {n_pages} pages, {n_tables} tables, {len(md)} chars, "
              f"{n_norm} formulas normalized, {report[name]['seconds']}s", flush=True)

    for name in TXT:
        raw = (SRC / name).read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        stem = stem_for(name)
        numbered = "\n".join(f"{i:>4}  {ln}" for i, ln in enumerate(lines, 1))
        (OUT / f"{stem}.lines.txt").write_text(numbered, encoding="utf-8")
        (OUT / f"{stem}.md").write_text(raw, encoding="utf-8")
        report[name] = {"stem": stem, "lines": len(lines), "chars": len(raw)}
        print(f"{name} -> {len(lines)} lines", flush=True)

    (OUT / "docs_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
