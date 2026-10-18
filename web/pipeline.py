"""Answering a question in the website: the Phase 8 route, scoped to one Library.

  1. Follow-ups   with chat history, one Luna call rewrites the question to
                  stand alone ("and for G8?" -> "Who is the TA for G8?").
  2. Router       numeric -> the SQL route over this Library's spreadsheets,
                  falling back to hybrid search; every other tag -> hybrid.
  3. Answer       the same Explained-answer prompt the eval scores (answering.py),
                  streamed: the page shows each step and the final answer as
                  they are written (stream() below).
  4. Checker      quotes + support against what was retrieved; failures make
                  the answer Unsure, naming the failed check.
  5. Pictures     any picture the answer rests on comes back with a note and
                  its image, to be shown beside the answer (must).

Every query filters on the Library id (store.py), so one user's question never
reaches another user's material (record 0001). Costs are estimated from the
tokens each call reports, for the Demo budget.
"""
import pathlib
import queue
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import partial_json  # noqa: E402  (web/, beside this file)
import checker  # noqa: E402
import hybrid  # noqa: E402
import library as L  # noqa: E402
import pictures as P  # noqa: E402
import router  # noqa: E402
import sql_route  # noqa: E402
from answering import ask_with_docs  # noqa: E402
from openai_client import ask_json, client  # noqa: E402

K = 5  # chunks per answer; k scales with Library size (build plan) - 5 suits a small Library
# Estimated prices, USD per million tokens (HANDOFF.md "Rough costs"). Verify on
# the OpenAI pricing page before the public launch.
PRICE_IN, PRICE_OUT = 0.20, 1.20

CONDENSE = """\
A student is asking follow-up questions about their course materials. Rewrite
their latest message as one question that stands on its own, using the earlier
turns only to fill in what it refers to. If it already stands alone, return it
unchanged. Do not answer it.

EARLIER TURNS (oldest first)
{history}

LATEST MESSAGE
{question}

Reply with JSON only: {{"question": "<the standalone question>"}}
"""

_client = None


def _c():
    global _client
    if _client is None:
        _client = client()
    return _client


class Library:
    """Where one Library's material lives. The eval Library uses the repo's own
    parsed files; uploaded Libraries live under libraries/<id>/ (ingest.py)."""

    def __init__(self, library_id):
        self.id = library_id
        if library_id == "eval":
            self.root = ROOT
            self.sheets_db = L.OUT / "sheets.duckdb"
            self.spreadsheet = L.SPREADSHEET
        else:
            self.root = ROOT / "libraries" / library_id
            self.sheets_db = self.root / "sheets.duckdb"
            self.spreadsheet = None
            if self.sheets_db.exists():  # the SQL route's prompt names the spreadsheet(s)
                import duckdb
                con = duckdb.connect(str(self.sheets_db), read_only=True)
                names = [r[0] for r in con.execute("SELECT DISTINCT file FROM cells ORDER BY file").fetchall()]
                con.close()
                self.spreadsheet = ", ".join(names) or None

    def has_sheets(self):
        return self.sheets_db.exists() and (self.id == "eval" or bool(self.spreadsheet))


    def cell(self, ref):
        if self.id == "eval":
            return L.sheet_cell(ref)
        import duckdb
        con = duckdb.connect(str(self.sheets_db), read_only=True)
        row = con.execute("SELECT value_text, row_label, col_header, file FROM labeled WHERE cell_ref = ?",
                          [ref]).fetchone()
        con.close()
        if not row:
            return None
        value, label, header, file = row
        text = f"{ref} = {value}" + (f" (row: {label})" if label else "") + (f" (column: {header})" if header else "")
        return {"id": f"sheet:{ref}", "file": file, "loc": ref, "text": text}

    def pictures(self):
        if self.id == "eval":
            return P.pictures()
        import json
        index = self.root / "pictures.json"
        return json.loads(index.read_text()) if index.exists() else []


def cost(usages):
    us = [u for u in usages if u]
    tin = sum(u.get("prompt_tokens", 0) for u in us)
    tout = sum(u.get("completion_tokens", 0) for u in us)
    return tin, tout, tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT


def condense(question, history):
    if not history:
        return question, None
    turns = "\n".join(f"Student: {h['question']}\nAssistant: {h['answer'].get('final_answer', '')}"
                      for h in history)
    reply, usage = ask_json(_c(), CONDENSE.format(history=turns, question=question), effort="low",
                            valid=lambda v: isinstance(v.get("question"), str) and v["question"].strip())
    return reply["question"].strip(), usage


def _excerpts(evidence):
    """What the answering model was given to read, in rank order, for the page's Sources panel."""
    return [{"id": e["id"], "file": e["file"], "loc": e.get("loc") or "", "text": e["text"]} for e in evidence or []]


def _steps(steps, source):
    """Steps as the page shows them: each source id becomes {id, file, loc}."""
    out = []
    for s in steps or []:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str):
            continue
        ev = source(s.get("source")) if isinstance(s.get("source"), str) else None
        out.append({"text": s["text"], "quote": s.get("quote") if isinstance(s.get("quote"), str) else None,
                    "source": {"id": ev["id"], "file": ev["file"], "loc": ev["loc"]} if ev else None})
    return out


class _Drafts:
    """Turns the reply so far into a draft answer for the page while it is being
    written: at most one draft every DRAFT_EVERY seconds, and only when it changed.
    A step's citation appears once its source id is complete."""

    DRAFT_EVERY = 0.06

    def __init__(self, emit, source, base):
        self.emit, self.source, self.base = emit, source, base
        self.text, self.last, self.sent = "", 0.0, None

    def __call__(self, text):
        self.text = text
        if time.monotonic() - self.last >= self.DRAFT_EVERY:
            self.flush()

    def flush(self):
        obj = partial_json.parse(self.text)
        if not obj:
            return
        draft = self.base | {"final_answer": obj.get("final_answer") if isinstance(obj.get("final_answer"), str) else "",
                             "not_found": obj.get("not_found") is True,
                             "steps": _steps(obj.get("steps"), self.source)}
        if draft != self.sent:
            self.sent, self.last = draft, time.monotonic()
            self.emit({"type": "draft", "answer": draft})


def answer(library_id, question, history=(), emit=None):
    """Everything the page shows for one question, plus the cost of making it.
    emit(event), if given, hears how it is going (see stream())."""
    emit = emit or (lambda event: None)
    lib = Library(library_id)
    c = _c()
    usages, timing, t0 = [], {}, time.monotonic()

    def lap(name):
        nonlocal t0
        timing[name] = round(time.monotonic() - t0, 1)
        t0 = time.monotonic()

    emit({"type": "stage", "stage": "reading"})
    standalone, u = condense(question, list(history))
    usages.append(u)
    lap("condense")
    tag, u = router.route(c, standalone)
    usages.append(u)
    lap("router")
    route = {"tag": tag, "path": "hybrid"}
    base = {"question": question, "standalone": standalone, "route": route}
    cells = {}

    def sheet_source(sid):
        if sid.startswith("sheet:") and sid not in cells:
            cells[sid] = lib.cell(sid.removeprefix("sheet:"))
        return cells.get(sid)

    result = None
    if tag == "numeric" and lib.has_sheets():
        drafts = _Drafts(emit, sheet_source, base | {"route": {"tag": tag, "path": "sql"}})
        result, trace = sql_route.answer(c, standalone, db=lib.sheets_db, spreadsheet=lib.spreadsheet, cell=lib.cell,
                                         on_text=drafts,
                                         on_evidence=lambda ev: emit({"type": "excerpts", "excerpts": _excerpts(ev)}))
        usages += trace.get("plan_usage", [])
        route["path"] = "sql" if result else "sql -> hybrid"
        lap("sql")
        if result:
            drafts.flush()
        else:
            emit({"type": "stage", "stage": "reading"})  # back to searching: drop the spreadsheet draft
    if result is None:
        hits = hybrid.search(standalone, K, library=lib.id)
        lap("search")
        evidence = [L.as_evidence(h) for h in hits]
        emit({"type": "excerpts", "excerpts": _excerpts(evidence)})
        by_id = {e["id"]: e for e in evidence}
        drafts = _Drafts(emit, by_id.get, base)
        result = ask_with_docs(c, standalone, evidence, on_text=drafts)
        drafts.flush()
        timing["first_text"] = (result.get("usage") or {}).get("first_text_seconds")
        lap("answer")
    usages.append(result.get("usage"))
    emit({"type": "stage", "stage": "checking"})
    result["pictures"] = P.relied_on(result, lib.pictures())
    checked, u = checker.check(c, standalone, result)
    usages.append(u)
    lap("check")
    tin, tout, usd = cost(usages)
    print(f"[answer] {route['path']}: " + ", ".join(f"{k} {v}s" for k, v in timing.items()), flush=True)

    by_id = {e["id"]: e for e in result.get("retrieved", [])}
    return base | {
        "final_answer": result["final_answer"], "not_found": bool(result.get("not_found")),
        "steps": _steps(result.get("steps"), by_id.get),
        "unsure": checked["unsure"], "unsure_reasons": checked["unsure_reasons"],
        "pictures": result["pictures"], "excerpts": _excerpts(result.get("retrieved")),
    }, (tin, tout, usd)


def stream(library_id, question, history=()):
    """answer(), as events while it happens, for the website's streamed answers:

      {"type": "stage", "stage": "reading"}    rewriting the question, routing, searching
      {"type": "excerpts", "excerpts": [...]}  what was found, before the answer is written
      {"type": "draft", "answer": {...}}       the answer so far, as the model writes it
      {"type": "stage", "stage": "checking"}   written; the checker is running
      {"type": "done", "answer": {...}, "cost": (tokens in, tokens out, usd)}
      {"type": "error", "message": "..."}

    A draft is shown before it is checked; the page says so until "done"."""
    events = queue.Queue()

    def work():
        try:
            final, spent = answer(library_id, question, history, emit=events.put)
            events.put({"type": "done", "answer": final, "cost": spent})
        except Exception as e:  # the page shows a plain message; the server log keeps the detail
            import traceback
            traceback.print_exc()
            events.put({"type": "error", "message": f"Something went wrong while answering ({type(e).__name__})."})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (event := events.get()) is not None:
        yield event
