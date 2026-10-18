"""Uploads: one file into one Library, and delete-everywhere.

The eval Library was built by batch scripts (scripts/parse_docs.py, chunk.py,
describe_*.py, parse_sheets.py, embed.py, store.py). This runs the same steps
for one uploaded file, with the same settings, so an upload is read the way
the eval Library was:

  1. Read      PDF, Word, PowerPoint: Docling, formula enrichment on (answers
               can live inside equations), PDF table headers repaired.
               Text: copied with line numbers. Spreadsheet: every cell into the
               Library's DuckDB (cells + labeled, as parse_sheets.py).
  2. Pictures  image files and pictures inside PDFs get a Diagram description:
               one pass for what it is and its text (and a chart's axes and
               lines), plus arrows read 3 times and kept by vote. At most
               MAX_PICTURES per file (build plan); the rest stay undescribed.
               Pictures inside Word and PowerPoint files are not described yet.
  3. Chunk     chunk.py's packing (~800 tokens, whole blocks, ~100 overlap);
               every chunk keeps its page, slide or line range.
  4. Index     text-embedding-3-small vectors + Postgres full-text, in the one
               chunks table, under this Library's id only (record 0001).

Files live under libraries/<library id>/ (gitignored):

  files/<file id>/<name>      the upload itself
  parsed/<file id>.*          its text, as citations show it
  figures/<file id>_p<page>_<n>.png/.md   pictures cropped from a PDF
  sheets.duckdb, sheets/<file id>/        spreadsheets
  pictures.json               every described picture (pipeline.Library.pictures)

Pages, for the limits (Member: 50 per file; Admin: 200 in all): a PDF's
pages, a slide deck's slides, a spreadsheet's sheets, one per picture, and for
Word and text files one per 500 words (a typical printed page).

The eval Library is never changed here: it is the eval's ground truth.
"""
import json
import math
import pathlib
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LIBS = ROOT / "libraries"

import chunk as CH  # noqa: E402
import db  # noqa: E402
import describe_images as DI  # noqa: E402
import describe_pdf_figures as F  # noqa: E402
import embed  # noqa: E402
import store  # noqa: E402
from checker import norm  # noqa: E402
from diagram_connections import CHART_NOTE, ask, connections, keep_sections  # noqa: E402
from normalize_formulas import normalize_text  # noqa: E402
from openai_client import MODEL, VISION_MODEL, client  # noqa: E402
from pictures import _kind  # noqa: E402

FORMATS = {".pdf": "PDF", ".docx": "Word", ".pptx": "Slides", ".txt": "Text", ".md": "Text",
           ".png": "Image", ".jpg": "Image", ".jpeg": "Image", ".webp": "Image", ".xlsx": "Spreadsheet"}
MAX_BYTES = 25 * 1024 * 1024
MAX_PICTURES = 20
WORDS_PER_PAGE = 500
EMBED_PRICE = 0.02  # USD per million tokens, text-embedding-3-small (OpenAI pricing page)

_one_at_a_time = ThreadPoolExecutor(1)  # Docling is heavy: one file is read at a time
_converter, _converter_lock = None, threading.Lock()


def fmt_of(name):
    return FORMATS.get(pathlib.Path(name).suffix.lower())


def lib_dir(library_id):
    if library_id == "eval" or not re.fullmatch(r"[A-Za-z0-9_-]+", library_id):
        raise ValueError("not an uploadable Library")
    return LIBS / library_id


def count_pages(path, fmt):
    """Pages for the limits, read before any processing (see the module docstring)."""
    if fmt == "PDF":
        import pypdfium2 as pdfium
        return len(pdfium.PdfDocument(str(path)))
    if fmt == "Slides":
        from pptx import Presentation
        return max(1, len(Presentation(str(path)).slides))
    if fmt == "Spreadsheet":
        import openpyxl
        return max(1, len(openpyxl.load_workbook(path, read_only=True).sheetnames))
    if fmt == "Image":
        return 1
    if fmt == "Word":
        import docx
        words = sum(len(p.text.split()) for p in docx.Document(str(path)).paragraphs)
    else:
        words = len(path.read_text(encoding="utf-8", errors="replace").split())
    return max(1, math.ceil(words / WORDS_PER_PAGE))


# ---- 1. Read -------------------------------------------------------------------

def _docling():
    global _converter
    with _converter_lock:
        if _converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
            opts = PdfPipelineOptions()
            opts.do_formula_enrichment = True  # see parse_docs.py: answers live inside equations
            _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
        return _converter


def read_document(src, fmt, name, out):
    """Docling -> <out>.md, and for paged formats <out>.pages.md ('## page N' per page or slide)."""
    from repair_tables import repair_document
    doc = _docling().convert(src).document
    if fmt == "PDF":
        repair_document(doc, src)
    md, _ = normalize_text(doc.export_to_markdown(page_break_placeholder="\n\n<!-- page break -->\n\n"))
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    pages_md = None
    if fmt in ("PDF", "Slides") and getattr(doc, "pages", None):
        parts = [f"# {name}", ""]
        for pno in sorted(doc.pages):
            page_md, _ = normalize_text(doc.export_to_markdown(page_no=pno))
            parts += [f"## page {pno}", "", page_md, ""]
        pages_md = out.with_suffix(".pages.md")
        pages_md.write_text("\n".join(parts), encoding="utf-8")
    return doc, pages_md or out.with_suffix(".md")


def read_text(src, out):
    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
    numbered = out.with_suffix(".lines.txt")
    numbered.write_text("\n".join(f"{i:>4}  {ln}" for i, ln in enumerate(lines, 1)), encoding="utf-8")
    return numbered


def read_sheets(src, name, file_id, lib):
    """parse_sheets.py for one workbook, into the Library's DuckDB (with a file column)."""
    import duckdb
    import openpyxl
    from parse_sheets import is_num
    wb_val = openpyxl.load_workbook(src, data_only=True)
    wb_fml = openpyxl.load_workbook(src, data_only=False)
    dumps = lib / "sheets" / str(file_id)
    dumps.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(lib / "sheets.duckdb"))
    try:
        con.execute("CREATE TABLE IF NOT EXISTS cells (file VARCHAR, sheet VARCHAR, cell_ref VARCHAR, row INTEGER, col INTEGER, "
                    "value_text VARCHAR, value_num DOUBLE, formula VARCHAR)")
        con.execute("CREATE TABLE IF NOT EXISTS labeled (file VARCHAR, sheet VARCHAR, cell_ref VARCHAR, row_label VARCHAR, "
                    "col_header VARCHAR, value_text VARCHAR, value_num DOUBLE)")
        taken = {r[0] for r in con.execute("SELECT DISTINCT sheet FROM cells").fetchall()}
        for sheet in wb_val.sheetnames:
            sv, sf = wb_val[sheet], wb_fml[sheet]
            # Two workbooks may both have "Sheet1": the second is cited as "<file> - Sheet1".
            label = sheet if sheet not in taken else f"{pathlib.Path(name).stem} - {sheet}"
            taken.add(label)

            def row_label(r, c):
                for cc in range(c - 1, 0, -1):
                    v = sv.cell(row=r, column=cc).value
                    if isinstance(v, str) and v.strip():
                        return v.strip()

            def col_header(r, c):
                for rr in range(r - 1, max(0, r - 12), -1):
                    v = sv.cell(row=rr, column=c).value
                    if isinstance(v, str) and v.strip():
                        return v.strip()

            cells, labeled, lines = [], [], [f"# {label}", ""]
            for row in sv.iter_rows():
                vals = []
                for cell in row:
                    if cell.value is None:
                        continue
                    ref = f"{label}!{cell.coordinate}"
                    fml = sf[cell.coordinate].value
                    num = float(cell.value) if is_num(cell.value) else None
                    cells.append((name, label, ref, cell.row, cell.column, str(cell.value), num,
                                  fml if isinstance(fml, str) and fml.startswith("=") else None))
                    labeled.append((name, label, ref, row_label(cell.row, cell.column), col_header(cell.row, cell.column),
                                    str(cell.value), num))
                    vals.append(f"{cell.coordinate}={cell.value!r}")
                if vals:
                    lines.append(" | ".join(vals))
            if cells:
                con.executemany("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)", cells)
                con.executemany("INSERT INTO labeled VALUES (?,?,?,?,?,?,?)", labeled)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
            (dumps / f"{safe}.txt").write_text("\n".join(lines), encoding="utf-8")
    finally:
        con.close()
    return dumps


# ---- 2. Pictures ---------------------------------------------------------------

def describe_image(c, path):
    """describe_images.py for one image: what it is and its text, plus voted arrows."""
    text, usage = ask(c, VISION_MODEL, path, DI.PROMPT)
    conn_md, _, conn_usage = connections(c, VISION_MODEL, path)
    return (keep_sections(text) + "\n" + conn_md).strip(), [usage] + conn_usage


def describe_figure(c, path):
    """describe_pdf_figures.py for one PDF picture: chart details too; arrows voted."""
    text, usage = ask(c, MODEL, path, F.FIGURE_PROMPT)
    conn_md, _, conn_usage = connections(c, MODEL, path, CHART_NOTE)
    return (keep_sections(text, F.SECTIONS) + "\n" + conn_md).strip(), [usage] + conn_usage


def pdf_pictures(c, doc, src, file_id, lib, progress):
    """Crop, describe and insert the pictures of one PDF. Returns (pictures.json entries, usages)."""
    import pypdfium2 as pdfium
    pics = doc.export_to_dict().get("pictures", [])
    if not pics:
        return [], [], []
    pdf, figs = pdfium.PdfDocument(str(src)), lib / "figures"
    figs.mkdir(exist_ok=True)
    crops = []
    for i, pic in enumerate(pics):
        prov = pic["prov"][0]
        b, page = prov["bbox"], pdf[prov["page_no"] - 1]
        h = page.get_height()
        box = (int((b["l"] - F.PAD) * F.SCALE), int((h - b["t"] - F.PAD) * F.SCALE),
               int((b["r"] + F.PAD) * F.SCALE), int((h - b["b"] + F.PAD) * F.SCALE))
        path = figs / f"{file_id}_p{prov['page_no']:02d}_{i:02d}.png"
        page.render(scale=F.SCALE).to_pil().crop(box).save(path)
        crops.append((path, prov["page_no"]))
    todo = crops[:MAX_PICTURES]
    progress(f"Reading {len(todo)} picture{'s' if len(todo) != 1 else ''}")
    with ThreadPoolExecutor(4) as pool:
        described = list(pool.map(lambda pp: describe_figure(c, pp[0]), todo))
    usages, bodies = [], []
    for (path, page), (body, us) in zip(todo, described):
        path.with_suffix(".md").write_text(body + "\n", encoding="utf-8")
        usages += us
        bodies.append((path, page, body))
    entries = [{"file": None, "loc": f"p. {page}", "image": str(path.relative_to(ROOT)), "text": norm(body), "kind": _kind(body)}
               for path, page, body in bodies]
    return entries, usages, [(page, body) for _, page, body in bodies] + [(page, None) for _, page in crops[MAX_PICTURES:]]


def insert_figures(path, figures):
    """Replace each '<!-- image -->' placeholder, in order, with its description (describe_pdf_figures.insert)."""
    md = path.read_text(encoding="utf-8")
    parts = md.split(F.PLACEHOLDER)
    if len(parts) - 1 != len(figures):
        return  # Docling's markdown and its picture list disagree: leave the placeholders
    out = parts[0]
    for n, ((page, body), rest) in enumerate(zip(figures, parts[1:]), 1):
        out += (F.as_inline(body, page, n) if body else f"[Picture on p. {page} - not described: over {MAX_PICTURES} per file]") + rest
    path.write_text(out, encoding="utf-8")


# ---- 3. Chunk, 4. Index --------------------------------------------------------

def make_chunks(name, fmt, body_path, file_id):
    body = body_path.read_text(encoding="utf-8")
    if fmt == "Text":
        blocks = CH.blocks_from_lines(body)
    else:
        blocks = CH.blocks_from_markdown(body, paged=fmt in ("PDF", "Slides"))
    for b in blocks:
        b["tokens"] = CH.ntok(b["text"])
    blocks = [p for b in blocks for p in CH.split_oversized(b)]
    chunks = []
    for i, group in enumerate(CH.pack(blocks), 1):
        text = "\n\n".join(b["text"] for b in group)
        new = [b for b in group if not b.get("overlap")]
        loc = CH.location(group, fmt)["loc"]
        if fmt == "Slides" and loc:  # a slide deck's "pages" are its slides
            loc = loc.replace("pp. ", "slides ").replace("p. ", "slide ")
        chunks.append({"chunk_id": f"f{file_id}#{i:03d}", "file": name, "loc": loc,
                       "heading": (new[0] if new else group[0])["heading"], "text": text})
    return [c for c in chunks if c["text"].strip()]


def index(library_id, chunks):
    """Embed and store; returns the embedding tokens used."""
    tokens = 0
    with store.connect() as conn:
        conn.execute(store.SCHEMA)
        for i in range(0, len(chunks), 100):
            batch = chunks[i:i + 100]
            vectors, used = embed.embed_texts(store.EMBED_MODEL, [embed.chunk_input(ch) for ch in batch])
            tokens += used
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO chunks (library_id, chunk_id, file, loc, heading, text, embedding)"
                                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                [(library_id, ch["chunk_id"], ch["file"], ch.get("loc"), ch.get("heading"), ch["text"], v)
                                 for ch, v in zip(batch, vectors)])
    return tokens


def _pictures_json(lib, update):
    path = lib / "pictures.json"
    pics = json.loads(path.read_text()) if path.exists() else []
    pics = update(pics)
    path.write_text(json.dumps(pics, indent=1), encoding="utf-8")


# ---- The whole upload ----------------------------------------------------------

def process(file_id):
    """Read, describe, chunk and index one uploaded file; files.status ends 'ready' or 'failed'."""
    f = db.one("SELECT * FROM files WHERE id = %s", (file_id,))
    lib, name, fmt = lib_dir(f["library_id"]), f["name"], f["format"]
    src = ROOT / f["path"]
    (lib / "parsed").mkdir(parents=True, exist_ok=True)
    out = lib / "parsed" / str(file_id)

    def progress(note):
        db.run("UPDATE files SET progress = %s WHERE id = %s", (note, file_id))

    usages, t0 = [], time.time()
    try:
        c = client()
        pictures, parsed = [], None
        if fmt == "Spreadsheet":
            progress("Reading every cell")
            parsed = read_sheets(src, name, file_id, lib)
            chunks = []
        else:
            if fmt == "Text":
                progress("Reading the text")
                body = parsed = read_text(src, out)
            elif fmt == "Image":
                progress("Reading the picture")
                png = out.with_suffix(".png")
                from PIL import Image
                Image.open(src).convert("RGB").save(png)
                desc, us = describe_image(c, png)
                usages += us
                body = parsed = out.with_suffix(".md")
                body.write_text(desc + "\n", encoding="utf-8")
                pictures = [{"file": name, "loc": "", "image": f["path"], "text": norm(desc), "kind": _kind(desc)}]
            else:
                progress("Reading the text, tables and equations" if fmt == "PDF" else "Reading the text")
                doc, body = read_document(src, fmt, name, out)
                parsed = out.with_suffix(".md")
                if fmt == "PDF":
                    pictures, us, figures = pdf_pictures(c, doc, src, file_id, lib, progress)
                    usages += us
                    for p in pictures:
                        p["file"] = name
                    if figures:
                        for path in {body, parsed}:
                            insert_figures(path, figures)
            progress("Indexing for search")
            chunks = make_chunks(name, fmt, body, file_id)
            embed_tokens = index(f["library_id"], chunks)
            if pictures:
                _pictures_json(lib, lambda pics: [p for p in pics if p["file"] != name] + pictures)
            db.run("INSERT INTO spend (user_id, kind, tokens_in, tokens_out, usd) VALUES (%s, 'upload', %s, 0, %s)",
                   (f["user_id"], embed_tokens, embed_tokens / 1e6 * EMBED_PRICE))
        if usages:
            import pipeline
            tin, tout, usd = pipeline.cost(usages)
            db.run("INSERT INTO spend (user_id, kind, tokens_in, tokens_out, usd) VALUES (%s, 'upload', %s, %s, %s)",
                   (f["user_id"], tin, tout, usd))
        db.run("UPDATE files SET status = 'ready', progress = NULL, parsed = %s WHERE id = %s",
               (str(parsed.relative_to(ROOT)) if parsed else None, file_id))
        print(f"[upload] {name}: {fmt}, {len(chunks)} chunks, {len(pictures)} pictures, {time.time() - t0:.0f} s", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        remove_indexes(f)  # nothing half-indexed stays searchable
        db.run("UPDATE files SET status = 'failed', progress = NULL, error = %s WHERE id = %s",
               (f"{type(e).__name__}: {str(e)[:200]}", file_id))
        db.run("UPDATE users SET files_used = GREATEST(files_used - 1, 0), pages_used = GREATEST(pages_used - %s, 0) "
               "WHERE id = %s", (f["pages"], f["user_id"]))  # a failed upload does not use up the limit


def start(file_id):
    _one_at_a_time.submit(process, file_id)


def remove_indexes(f):
    """Take one file out of every index: chunks, spreadsheet cells, pictures."""
    lib = lib_dir(f["library_id"])
    with store.connect() as conn:
        conn.execute(store.SCHEMA)
        conn.execute("DELETE FROM chunks WHERE library_id = %s AND file = %s", (f["library_id"], f["name"]))
    sheets = lib / "sheets.duckdb"
    if sheets.exists():
        import duckdb
        con = duckdb.connect(str(sheets))
        try:
            for table in ("cells", "labeled"):
                con.execute(f"DELETE FROM {table} WHERE file = ?", [f["name"]])
        finally:
            con.close()
    if (lib / "pictures.json").exists():
        _pictures_json(lib, lambda pics: [p for p in pics if p["file"] != f["name"]])


def delete(f):
    """Delete-everywhere: out of every index, then the stored file and everything made from it."""
    remove_indexes(f)
    lib = lib_dir(f["library_id"])
    shutil.rmtree(lib / "files" / str(f["id"]), ignore_errors=True)
    shutil.rmtree(lib / "sheets" / str(f["id"]), ignore_errors=True)
    for made in [*(lib / "parsed").glob(f"{f['id']}.*"), *(lib / "figures").glob(f"{f['id']}_p*")]:
        made.unlink(missing_ok=True)
    # Saved answers keep the excerpts they were written from (the Sources panel): drop this file's text there too.
    for m in db.all_("SELECT id, answer FROM messages WHERE user_id = %s", (f["user_id"],)):
        excerpts = m["answer"].get("excerpts") or []
        if any(e.get("file") == f["name"] and e.get("text") for e in excerpts):
            m["answer"]["excerpts"] = [e | {"text": "", "deleted": True} if e.get("file") == f["name"] else e for e in excerpts]
            db.run("UPDATE messages SET answer = %s::jsonb WHERE id = %s", (json.dumps(m["answer"]), m["id"]))
    db.run("DELETE FROM files WHERE id = %s", (f["id"],))
