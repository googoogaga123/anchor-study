"""Which pictures an answer rests on - so the answer can say so and show them.

A Diagram description is a machine's reading of a picture, and it can be wrong
(midterm p. 8 misses a crossing; p. 19 calls dotted guides "crossings"). The
checker cannot catch that: it tests an answer against the retrieved text, and
the error is IN the text. A student looking at the picture can, in a second.
So every answer that rests on a picture carries it (build plan, Website step:
"Answers that rest on a picture (must)").

Decided by code, not by the answering model: a step rests on a picture when
its quote comes from inside that picture's Diagram description -

  - an image file's chunk (the whole chunk is its description), or
  - inside a "[Figure on p. N - Diagram description ...]" ... "[End of figure n]"
    block of a PDF chunk (describe_pdf_figures.py). A block cut by a chunk
    boundary still counts: text before the first "[End of figure" with no
    opening marker, or after an opening marker with no end, is figure text.

Each picture comes back as {file, loc, image, kind, note}; `image` is the
picture to show (the image file, or the crop in parsed/figures/).
"""
import pathlib
import re

from checker import norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "eval set"
OUT = ROOT / "parsed"
FIG = OUT / "figures"

OPEN = re.compile(r"\[Figure on p\. (\d+) - Diagram description[^\]]*\]")
CLOSE = re.compile(r"\[End of figure \d+\]")
KINDS = ("flowchart", "screenshot", "graph", "chart", "diagram", "table", "photo")

_pictures = None


def _kind(description):
    m = re.search(r"## What it is\s*(.+)", description)
    first = (m.group(1) if m else description).lower()
    found = [(first.find(k), k) for k in KINDS if k in first]
    return min(found)[1] if found else "picture"


def pictures():
    """Every described picture in the Library: image files and PDF figures."""
    global _pictures
    if _pictures is None:
        import chunk as CH
        import describe_pdf_figures as F
        out = []
        for name, fmt, rel in CH.SOURCES:
            if fmt == "Image":
                text = (OUT / rel).read_text(encoding="utf-8")
                out.append({"file": name, "loc": "", "image": str((SRC / name).relative_to(ROOT)),
                            "text": norm(text), "kind": _kind(text)})
        for pdf_name, stem in F.PDFS:
            prefix = stem.split("__")[0]
            for md in sorted(FIG.glob(f"{prefix}_p*.md")):
                page = int(re.search(r"_p(\d+)_\d+$", md.stem).group(1))
                text = md.read_text(encoding="utf-8")
                out.append({"file": pdf_name, "loc": f"p. {page}", "image": str(md.with_suffix(".png").relative_to(ROOT)),
                            "text": norm(text), "kind": _kind(text)})
        _pictures = out
    return _pictures


def figure_text(chunk_text):
    """The parts of a PDF chunk that are figure descriptions, as (page or None, text)."""
    spans, pos, inside, page = [], 0, False, None
    # A chunk can open mid-figure: text before an end marker that has no opening.
    first_open, first_close = OPEN.search(chunk_text), CLOSE.search(chunk_text)
    if first_close and (not first_open or first_close.start() < first_open.start()):
        spans.append((None, chunk_text[:first_close.start()]))
        pos = first_close.end()
    while m := OPEN.search(chunk_text, pos):
        end = CLOSE.search(chunk_text, m.end())
        spans.append((int(m.group(1)), chunk_text[m.end():end.start() if end else len(chunk_text)]))
        pos = end.end() if end else len(chunk_text)
    return spans


def _note(p):
    where = f"on {p['loc']} of {p['file']}" if p["loc"] else p["file"]
    return f"Based on a computer reading of the {p['kind']} {where} - check the picture."


def relied_on(result, library_pictures=None):
    """The pictures an answer's steps rest on, each once, in step order.
    `library_pictures`: that Library's pictures (default: the eval Library's)."""
    by_id = {e["id"]: e for e in result.get("retrieved", [])}
    found = []
    for step in result.get("steps", []):
        q, ev = norm(step.get("quote")), by_id.get(step.get("source"))
        if not q or not ev:
            continue
        candidates = [p for p in (library_pictures if library_pictures is not None else pictures())
                      if p["file"] == ev["file"] and q in p["text"]]
        if not candidates:
            continue
        if any(p["loc"] == "" for p in candidates):  # an image file: the chunk is its description
            hit = candidates[0]
        else:
            spans = [(page, norm(t)) for page, t in figure_text(ev["text"])]
            pages = [page for page, t in spans if q in t]
            if not pages:
                continue  # the quote is in the page's own text, not in its figure
            hit = next((p for p in candidates if pages[0] and p["loc"] == f"p. {pages[0]}"), candidates[0])
        if hit not in found:
            found.append(hit)
    return [{"file": p["file"], "loc": p["loc"], "image": p["image"], "kind": p["kind"], "note": _note(p)}
            for p in found]
