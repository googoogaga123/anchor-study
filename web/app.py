"""The website (Phase 9) - DRAFT, local only.

    PGDATABASE=ailodge .venv/bin/uvicorn web.app:app --port 8000      # from the repo root
    then open http://localhost:8000 (the front page; the app is at /app)

Done in this draft: sign-in (development stand-in, auth.py), roles and limits
enforced on the server, one Library per user, asking (Phase 8 route), the
Explained answer with clickable citations, the Unsure label naming the failed
check, pictures shown beside answers that rest on them, chat history with
follow-ups, the Demo budget ledger and its friendly message, and the Admin
actions (promote, reset).

Also done: upload (drag files into the chat; read and indexed by ingest.py),
delete-everywhere, streamed answers, and a Sources panel with each answer's
excerpts. Not yet: "replace or keep both" (a same-name upload is refused for
now), the real login service, the owner email when the budget runs out, Web
answers.

DEMO_EVAL_LIBRARY=1 (default): the first account (the owner) gets the eval
Library, so the site can be tried before upload exists.
"""
import json
import os
import pathlib
import re
import sys

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import auth  # noqa: E402
import db  # noqa: E402
import ingest  # noqa: E402
import pages as public_pages  # noqa: E402
import pipeline  # noqa: E402
import scan  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = pathlib.Path(__file__).resolve().parent / "static"
DEMO_EVAL = os.environ.get("DEMO_EVAL_LIBRARY", "1") == "1"
HISTORY_TURNS = 3  # follow-ups see the last few turns

# The eval Library's files: the name chunks cite, the stored file, the parsed
# text a citation view shows, and a page count (PDF pages; others estimated).
EVAL_FILES = [
    ("MidtermSampleSolutions.pdf", "PDF", "eval set/MidtermSampleSolutions.pdf", None),
    ("IS114 AY26-T1 Course Content, Student Edition.pdf", "PDF",
     "eval set/IS114 AY26-T1 Course Content, Student Edition.pdf", None),
    ("IS114 AY26-T1 Course Content, Student Edition.docx", "Word",
     "eval set/IS114 AY26-T1 Course Content, Student Edition.docx",
     "parsed/IS114_AY26-T1_Course_Content_Student_Edition__docx.md"),
    ("week12hints.txt", "Text", "eval set/week12hints.txt", "parsed/week12hints__txt.lines.txt"),
    ("IS114_eLearn_Quizzes_tab.png", "Image", "eval set/IS114_eLearn_Quizzes_tab.png", None),
    ("IS114_Academic_Violation_Reporting_Procedure.png", "Image",
     "eval set/IS114_Academic_Violation_Reporting_Procedure.png", None),
    ("3A-Adjust-Class-Worksheet (Answer Key) (1).xlsx", "Spreadsheet",
     "eval set/3A-Adjust-Class-Worksheet (Answer Key) (1).xlsx", "parsed/sheets"),
]

app = FastAPI(title="Anchor (draft)")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
db.init()


def _pages(fmt, path):
    if fmt == "PDF":
        import pypdfium2 as pdfium
        return len(pdfium.PdfDocument(str(ROOT / path)))
    return 1  # estimate; the upload pipeline will define pages per format


def _seed_eval(user):
    db.run("UPDATE users SET library_id = 'eval' WHERE id = %s", (user["id"],))
    if not db.one("SELECT 1 AS x FROM files WHERE library_id = 'eval'"):
        for name, fmt, path, _ in EVAL_FILES:
            db.run("INSERT INTO files (user_id, library_id, name, format, pages, path) VALUES (%s, 'eval', %s, %s, %s, %s)",
                   (user["id"], name, fmt, _pages(fmt, path), path))


def limits(user):
    admin = auth.is_admin(user)
    return {
        "role": user["role"], "is_admin": admin,
        "questions_used": user["questions_used"],
        "questions_limit": None if admin else db.MEMBER_QUESTIONS,
        "pages_used": user["pages_used"],
        "pages_limit": db.ADMIN_PAGES if admin else db.MEMBER_PAGES,
        "files_used": user["files_used"],
        "files_limit": None if admin else db.MEMBER_FILES,
    }


@app.get("/", response_class=HTMLResponse)
def front_page():
    """The public front page: saved example answers and demo clips; costs nothing to view."""
    return public_pages.render("landing")


@app.get("/uploads", response_class=HTMLResponse)
def uploads_page():
    return public_pages.render("uploads")


@app.get("/connectors", response_class=HTMLResponse)
def connectors_page():
    return public_pages.render("connectors")


@app.get("/pricing", response_class=HTMLResponse)
def pricing_page():
    return public_pages.render("pricing")


@app.get("/faq", response_class=HTMLResponse)
def faq_page():
    return public_pages.render("faq")


@app.get("/app", response_class=HTMLResponse)
def app_page():
    return (STATIC / "app.html").read_text(encoding="utf-8")


class Login(BaseModel):
    email: str
    name: str | None = None


def _signed_in(resp, request, user, token):
    """Set the session cookie (secure when the browser came over https)."""
    if DEMO_EVAL and user["role"] == "owner" and user["library_id"] != "eval":
        _seed_eval(user)
    https = auth.public_origin(request).startswith("https")
    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", secure=https, max_age=30 * 24 * 3600)
    return resp


@app.get("/api/auth-config")
def auth_config():
    """Which ways in the sign-in page should offer."""
    return {"login_service": auth.LOGIN_SERVICE, "dev_login": auth.DEV_LOGIN}


@app.post("/api/dev-login")
def dev_login(body: Login, request: Request):
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", body.email.strip()):
        raise HTTPException(400, "Enter an email address.")
    user, token = auth.sign_in(body.email, body.name)
    return _signed_in(JSONResponse({"ok": True}), request, user, token)


@app.get("/login")
def login(request: Request):
    """Off to the login service's own sign-in page (WorkOS AuthKit)."""
    if not auth.LOGIN_SERVICE:
        return RedirectResponse("/app")
    import secrets
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(auth.login_url(request, state))
    resp.set_cookie(auth.STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600,
                    secure=auth.public_origin(request).startswith("https"))
    return resp


@app.get("/callback")
def callback(request: Request, code: str = "", state: str = ""):
    """Back from the login service: the state must match the one /login set (no forged sign-ins)."""
    if not auth.LOGIN_SERVICE:
        return RedirectResponse("/app")
    expected = request.cookies.get(auth.STATE_COOKIE)
    if not code or not expected or state != expected:
        return RedirectResponse("/login")
    user, token, sid = auth.finish_login(code)
    resp = _signed_in(RedirectResponse("/app"), request, user, token)
    resp.delete_cookie(auth.STATE_COOKIE)
    if sid:
        resp.set_cookie(auth.SID_COOKIE, sid, httponly=True, samesite="lax", max_age=30 * 24 * 3600,
                        secure=auth.public_origin(request).startswith("https"))
    return resp


@app.post("/api/logout")
def logout(request: Request):
    """Sign out here, and at the login service too (else its page signs you straight back in)."""
    auth.end_session(request.cookies.get(auth.SID_COOKIE))
    resp = JSONResponse({"ok": True, "next": "/"})
    resp.delete_cookie(auth.COOKIE)
    resp.delete_cookie(auth.SID_COOKIE)
    return resp


@app.get("/api/me")
def me(user=Depends(auth.current_user)):
    return {"email": user["email"], "name": user["name"], "limits": limits(user), "is_smu": user.get("is_smu", False),
            "sample_library": user["library_id"] == "eval",  # read-only: the eval's answer key
            "budget_left_usd": round(db.budget_left(), 4), "dev_login": auth.DEV_LOGIN}


@app.get("/api/files")
def files(user=Depends(auth.current_user)):
    return db.all_("SELECT id, name, label, format, pages, status, progress, error, created FROM files "
                   "WHERE library_id = %s ORDER BY created, id", (user["library_id"],))


@app.get("/api/history")
def history(user=Depends(auth.current_user)):
    return db.all_("SELECT id, question, answer, created FROM messages WHERE user_id = %s ORDER BY id",
                   (user["id"],))


class Ask(BaseModel):
    question: str


def _question(body, user):
    """The question, once every limit allows it; and the turns a follow-up needs."""
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "Type a question.")
    if len(q) > 1000:
        raise HTTPException(400, "Please keep questions under 1,000 characters.")
    if not auth.is_admin(user) and user["questions_used"] >= db.MEMBER_QUESTIONS:
        raise HTTPException(403, f"You have used your {db.MEMBER_QUESTIONS} questions. This is a demo to try; "
                                 "an Admin can reset your questions.")
    if db.budget_left() <= 0:
        raise HTTPException(503, "The demo has used up its budget for now - thank you for trying it! "
                                 "The owner has been told.")
    if not db.one("SELECT 1 AS x FROM files WHERE library_id = %s AND status = 'ready'", (user["library_id"],)):
        raise HTTPException(400, "Your Library is empty - add your course files first.")
    turns = db.all_("SELECT question, answer FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                    (user["id"], HISTORY_TURNS))[::-1]
    return q, turns


def _claim_question(user):
    """Count the question before any model call, in one step: closing the browser
    mid-answer, or asking from two tabs at once, can't get a Member past the limit."""
    if auth.is_admin(user):
        db.run("UPDATE users SET questions_used = questions_used + 1 WHERE id = %s", (user["id"],))
    elif not db.one("UPDATE users SET questions_used = questions_used + 1 WHERE id = %s AND questions_used < %s "
                    "RETURNING id", (user["id"], db.MEMBER_QUESTIONS)):
        raise HTTPException(403, f"You have used your {db.MEMBER_QUESTIONS} questions. This is a demo to try; "
                                 "an Admin can reset your questions.")


def _refund_question(user):
    """Answering failed: the question doesn't count."""
    db.run("UPDATE users SET questions_used = GREATEST(questions_used - 1, 0) WHERE id = %s", (user["id"],))


def _save(user, q, answer, spent):
    """The answer into the chat history and its cost into the Demo budget's ledger."""
    tin, tout, usd = spent
    msg = db.one("INSERT INTO messages (user_id, question, answer) VALUES (%s, %s, %s::jsonb) RETURNING id",
                 (user["id"], q, json.dumps(answer)))
    db.run("INSERT INTO spend (user_id, kind, tokens_in, tokens_out, usd) VALUES (%s, 'answer', %s, %s, %s)",
           (user["id"], tin, tout, usd))
    return msg["id"]


@app.post("/api/ask")
def ask(body: Ask, user=Depends(auth.current_user)):
    q, turns = _question(body, user)
    _claim_question(user)
    try:
        answer, spent = pipeline.answer(user["library_id"], q, turns)
    except Exception:
        _refund_question(user)
        raise
    return {"id": _save(user, q, answer, spent), "answer": answer}


@app.post("/api/ask/stream")
def ask_stream(body: Ask, user=Depends(auth.current_user)):
    """The same answer as /api/ask, sent while it is made: one JSON event per line
    (pipeline.stream). The question counts when it is asked; the answer and its cost
    are recorded by the worker when done, even if the browser has gone by then."""
    q, turns = _question(body, user)
    _claim_question(user)
    work = pipeline.stream(user["library_id"], q, turns,
                           on_done=lambda answer, spent: {"id": _save(user, q, answer, spent)},
                           on_error=lambda: _refund_question(user))

    def events():
        for event in work:
            if event["type"] == "done":
                event = {"type": "done", "id": event["id"], "answer": event["answer"]}
            yield json.dumps(event) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _own_file(user, file_id):
    f = db.one("SELECT * FROM files WHERE id = %s AND library_id = %s", (file_id, user["library_id"]))
    if not f:
        raise HTTPException(404, "No such file in your Library.")
    return f


@app.get("/api/files/{file_id}/raw")
def raw(file_id: int, user=Depends(auth.current_user)):
    f = _own_file(user, file_id)
    return FileResponse(ROOT / f["path"], filename=f["name"], content_disposition_type="inline")


@app.get("/api/files/{file_id}/view", response_class=HTMLResponse)
def view(file_id: int, loc: str = "", q: str = "", user=Depends(auth.current_user)):
    """A readable copy of a file that has no pages to jump to, with the cited place marked:
    the line holding the step's quote (`q`) when it is found, else the start of `loc`."""
    import html as H
    f = _own_file(user, file_id)
    parsed = next((p for n, _, _, p in EVAL_FILES if n == f["name"]), None) if f["library_id"] == "eval" else f.get("parsed")
    if f["format"] == "Image" and f["library_id"] != "eval":
        parsed = None  # a picture opens as itself (raw); its description is what answers quote
    if not parsed:
        raise HTTPException(404, "No readable copy for this file yet.")
    src = ROOT / parsed
    if src.is_dir():  # spreadsheet: one dump per sheet ("# <sheet>" then "C13=14000 | ..."); mark the cited cell
        sheet, _, cell = loc.partition("!")
        parts = []
        for dump in sorted(src.glob("*.txt")):
            part = H.escape(dump.read_text(encoding="utf-8"))
            if cell and part.startswith(f"# {H.escape(sheet)}\n"):
                part = re.sub(rf"\b({re.escape(cell)}=[^|\n]*)", r"<mark id='here'>\1</mark>", part, count=1)
            parts.append(part)
        body = "\n\n".join(parts)
    else:
        lines = src.read_text(encoding="utf-8").splitlines()
        squash = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()  # noqa: E731
        key = squash(q)[:60]
        first = next((i for i, line in enumerate(lines, 1) if key and key in squash(line)), None)
        if first is None and f["format"] == "Text":
            m = re.search(r"(\d+)", loc)
            first = int(m.group(1)) if m else None
        out = []
        for i, line in enumerate(lines, 1):
            esc = H.escape(line)
            out.append(f"<mark id='here'>{esc}</mark>" if first and i == first else esc)
        body = "\n".join(out)
    return (f"<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{H.escape(f['name'])}</title>"
            "<link rel='stylesheet' href='https://api.fontshare.com/v2/css?f[]=clash-display@500,600&display=swap'>"
            "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600&display=swap'>"
            "<link rel='stylesheet' href='/static/anchor.css'>"
            "<style>.src{max-width:960px;margin:0 auto;padding:28px 20px 60px}.src h1{font-size:28px;margin:6px 0 4px;overflow-wrap:anywhere}"
            ".src .where{color:var(--mute-2);margin-bottom:18px}.src pre{background:var(--panel);border:1px solid var(--line);border-radius:18px;"
            "padding:20px;white-space:pre-wrap;overflow-wrap:anywhere;font:13.5px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;box-shadow:var(--shadow-card)}"
            "mark{background:#fde68a;color:var(--ink-strong);border-radius:4px;padding:1px 2px;box-shadow:0 0 0 3px #fde68a}</style>"
            f"<div class='src'><div style='color:var(--mute);font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>Source</div>"
            f"<h1>{H.escape(f['name'])}</h1><div class='where'>{H.escape(loc) or 'Whole file'}"
            f"{' · the cited place is marked' if 'here' in body else ''}</div><pre>{body}</pre></div>"
            "<script>const h=document.getElementById('here');if(h)h.scrollIntoView({block:'center'})</script>")


@app.get("/api/picture")
def picture(path: str, user=Depends(auth.current_user)):
    """A picture an answer rests on - only one that belongs to the user's own Library."""
    lib = pipeline.Library(user["library_id"])
    if path not in {p["image"] for p in lib.pictures()}:
        raise HTTPException(404, "No such picture in your Library.")
    return FileResponse(ROOT / path)


# ---- Admin -------------------------------------------------------------------

def _admin(user=Depends(auth.current_user)):
    if not auth.is_admin(user):
        raise HTTPException(403, "Admins only.")
    return user


@app.get("/api/admin/users")
def admin_users(user=Depends(_admin)):
    return db.all_("SELECT id, email, name, role, questions_used, files_used, pages_used, created FROM users ORDER BY id")


class Target(BaseModel):
    user_id: int
    what: str | None = None


@app.post("/api/admin/promote")
def promote(body: Target, user=Depends(_admin)):
    if user["role"] != "owner":
        raise HTTPException(403, "Only the owner can make Admins.")
    if db.one("SELECT count(*) AS n FROM users WHERE role IN ('owner', 'admin')")["n"] >= db.MAX_ADMINS:
        raise HTTPException(400, f"There are already {db.MAX_ADMINS} Admins.")
    db.run("UPDATE users SET role = 'admin' WHERE id = %s AND role = 'member'", (body.user_id,))
    return {"ok": True}


@app.post("/api/admin/reset")
def reset(body: Target, user=Depends(_admin)):
    if body.what == "questions":
        db.run("UPDATE users SET questions_used = 0 WHERE id = %s", (body.user_id,))
    elif body.what == "upload":
        db.run("UPDATE users SET files_used = 0, pages_used = 0 WHERE id = %s", (body.user_id,))
    else:
        raise HTTPException(400, "Reset 'questions' or 'upload'.")
    return {"ok": True}


def _add_file(user, name, fmt, data, scanned=False, beside=None):
    """One file into the user's own Library, once every limit allows it: stored,
    then read and indexed in the background (ingest.py); /api/files shows progress."""
    if user["library_id"] == "eval":
        raise HTTPException(403, "The sample Library is read-only: it is the eval's answer key.")
    admin = auth.is_admin(user)
    if not admin and user["files_used"] >= db.MEMBER_FILES:
        raise HTTPException(403, f"You have added your {db.MEMBER_FILES} file. This is a demo to try; "
                                 "an Admin can reset your upload.")
    if db.budget_left() <= 0:
        raise HTTPException(503, "The demo has used up its budget for now - thank you for trying it!")
    if db.one("SELECT 1 AS x FROM files WHERE library_id = %s AND name = %s", (user["library_id"], name)):
        raise HTTPException(409, f"{name} is already in your Library. Delete it first to add it again.")
    if len(data) > ingest.MAX_BYTES:
        raise HTTPException(413, f"Files can be up to {ingest.MAX_BYTES // 2**20} MB.")
    lib = ingest.lib_dir(user["library_id"])
    row = db.one("INSERT INTO files (user_id, library_id, name, format, pages, path, status, progress, scanned) "
                 "VALUES (%s, %s, %s, %s, 0, '', 'processing', 'Uploading', %s) RETURNING id",
                 (user["id"], user["library_id"], name, fmt, scanned))
    dest = lib / "files" / str(row["id"]) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    for extra, content in (beside or {}).items():  # e.g. a scan's checked text, read by ingest.py
        (dest.parent / extra).write_bytes(content)
    try:
        pages = ingest.count_pages(dest, fmt)
    except Exception:
        pages = None
    limit = db.MEMBER_PAGES if not admin else db.ADMIN_PAGES - user["pages_used"]
    if pages is None or pages > limit:
        f = db.one("SELECT * FROM files WHERE id = %s", (row["id"],))
        ingest.delete(f | {"path": str(dest.relative_to(ROOT))})
        if pages is None:
            raise HTTPException(400, f"{name} could not be opened. Is it a valid {fmt} file?")
        raise HTTPException(403, f"{name} has {pages} pages; you can add up to {limit} more "
                                 f"{'pages in all' if admin else 'pages per file'} on this demo.")
    db.run("UPDATE files SET path = %s, pages = %s WHERE id = %s", (str(dest.relative_to(ROOT)), pages, row["id"]))
    db.run("UPDATE users SET files_used = files_used + 1, pages_used = pages_used + %s WHERE id = %s", (pages, user["id"]))
    ingest.start(row["id"])
    return db.one("SELECT id, name, label, format, pages, status, progress, error, created FROM files WHERE id = %s", (row["id"],))


@app.post("/api/upload")
def upload(file: UploadFile = File(...), user=Depends(auth.current_user)):
    name = pathlib.Path(file.filename or "").name.strip()
    fmt = ingest.fmt_of(name)
    if not name or not fmt:
        raise HTTPException(400, "Anchor reads PDF, Word (.docx), PowerPoint (.pptx), text (.txt, .md), "
                                 "pictures (.png, .jpg, .webp) and spreadsheets (.xlsx).")
    return _add_file(user, name, fmt, file.file.read(ingest.MAX_BYTES + 1))


# ---- Scanning printed pages (scan.py) ---------------------------------------

SCAN_PHOTO_BYTES = 10 * 2**20
SCAN_MAX_PAGES = 50
# Page checks and reads per account per hour: each takes 1-6 s of this server's CPU, and a
# read holds Docling's lock, so an unlimited loop could stall every upload and scan. A
# 50-page scan uses 100 (a check and a read per page), with room for retakes.
SCAN_CALLS_PER_HOUR = 150
_scan_calls, _scan_calls_lock = {}, __import__("threading").Lock()


def _scan_allowed(user):
    """Refuse scan work the account couldn't save anyway, or more than SCAN_CALLS_PER_HOUR."""
    import time
    from collections import deque
    if user["library_id"] == "eval":
        raise HTTPException(403, "The sample Library is read-only: it is the eval's answer key.")
    if not auth.is_admin(user) and user["files_used"] >= db.MEMBER_FILES:
        raise HTTPException(403, f"You have added your {db.MEMBER_FILES} file. This is a demo to try; "
                                 "an Admin can reset your upload.")
    now = time.monotonic()
    with _scan_calls_lock:
        calls = _scan_calls.setdefault(user["id"], deque())
        while calls and now - calls[0] > 3600:
            calls.popleft()
        if len(calls) >= SCAN_CALLS_PER_HOUR:
            raise HTTPException(429, "You've checked a lot of pages in the last hour. Please wait a little, then try again.")
        calls.append(now)


def _photo(file):
    data = file.file.read(SCAN_PHOTO_BYTES + 1)
    if len(data) > SCAN_PHOTO_BYTES:
        raise HTTPException(413, "A photo can be up to 10 MB.")
    return data


@app.post("/api/scan/page")
def scan_page(photo: UploadFile = File(...), user=Depends(auth.current_user)):
    """One photo of a page, straightened and checked. Nothing is stored: the
    pages stay in the browser until the student saves the scan."""
    _scan_allowed(user)
    import base64
    try:
        page, cropped = scan.crop_page(_photo(photo))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "That photo could not be opened. Please take it again.")
    return {"page": base64.b64encode(page).decode(), "cropped": cropped, "check": scan.readability(page)}


SCAN_TEXT_CHARS = 20_000  # per page


@app.post("/api/scan/read")
def scan_read(page: UploadFile = File(...), user=Depends(auth.current_user)):
    """One straightened page's text, read now so the student can check and correct it
    before saving. Nothing is stored."""
    _scan_allowed(user)
    try:
        text = ingest.read_scan_page(_photo(page))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "This page could not be read. Please take it again.")
    return {"text": text[:SCAN_TEXT_CHARS], "words": len(text.split())}


@app.post("/api/scan")
def scan_save(pages: list[UploadFile] = File(...), name: str = Form(""), texts: str = Form(""),
              user=Depends(auth.current_user)):
    """The straightened pages, in order, saved as one PDF in the Library. `texts`, when
    given, is each page's checked text ([{"text", "edited"}], from /api/scan/read and the
    student's corrections): it is indexed as it stands. Without it the pages are read by OCR."""
    if not pages:
        raise HTTPException(400, "Take a photo of at least one page.")
    if len(pages) > SCAN_MAX_PAGES:
        raise HTTPException(400, f"A scan can have up to {SCAN_MAX_PAGES} pages.")
    checked = None
    if texts:
        try:
            checked = [{"text": str(t["text"])[:SCAN_TEXT_CHARS], "edited": bool(t.get("edited"))} for t in json.loads(texts)]
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, "The pages' text could not be read. Please try saving again.")
        if len(checked) != len(pages):
            raise HTTPException(400, "Each page needs its text. Please try saving again.")
        if not any(t["text"].strip() for t in checked):
            raise HTTPException(400, "None of these pages has any text. Retake them, or type the text in.")
    import datetime
    title = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", name).strip()[:80].removesuffix(".pdf").strip()
    title = title or "Scan " + datetime.datetime.now().strftime("%-d %b, %H.%M")
    try:
        pdf = scan.assemble_pdf([_photo(p) for p in pages])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "The pages could not be put together. Please take them again.")
    beside = {"pages.json": json.dumps(checked).encode()} if checked else None
    return _add_file(user, f"{title}.pdf", "PDF", pdf, scanned=True, beside=beside)


@app.delete("/api/files/{file_id}")
def delete_file(file_id: int, user=Depends(auth.current_user)):
    """Delete-everywhere: the file leaves every index (chunks, spreadsheet cells,
    pictures) and its stored copies are removed. It still counts toward a Member's 1 file."""
    f = _own_file(user, file_id)
    if f["library_id"] == "eval":
        raise HTTPException(403, "The sample Library is read-only: it is the eval's answer key.")
    if f["status"] == "processing":
        raise HTTPException(409, "This file is still being read. Delete it once it is ready.")
    ingest.delete(f)
    return {"ok": True}
