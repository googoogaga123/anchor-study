"""Record the front page's demo clips from the real app (Playwright + ffmpeg).

    createdb ailodge_rec
    WEB_PGDATABASE=ailodge_rec OWNER_EMAIL=demo@example.com .venv/bin/uvicorn web.app:app --port 8001
    DEMO_BASE=http://localhost:8001 WEB_PGDATABASE=ailodge_rec caffeinate -i .venv/bin/python scripts/record_demos.py [hero upload ...]

Every answer in a clip is live: the clip types a real question into the app
and the real pipeline answers it, streamed. Each question costs about $0.002.
The demo owner has the eval Library; the upload clip uses a fresh Member
(upload-demo@example.com) whose earlier upload is deleted first.

Only the waits are shortened (the front page says so): while Anchor reads
(question sent -> first words) a clip plays at most READ_SECONDS, and while it
checks, at most CHECK_SECONDS; reading an uploaded file, at most
UPLOAD_SECONDS. The answer being written plays at real speed.

Privacy (owner's call, 18 Oct): only questions whose answers show no personal
details. At every step the visible page text is scanned for an email
address, an @handle or a phone number; one found stops the recording and no
clip is saved. Excerpts an answer doesn't cite stay closed in the Sources
panel, so their text is never on screen.

The scan clip (phone size) signs in as a fresh Member, scans IS114 pp. 1, 3
and 4 - pages checked to hold no personal details - and asks about them. Its
"photos" are stand-ins for camera shots, which a browser recording cannot
take: each page rendered and placed, tilted, on a dark desk. They go through
"Choose photos", and straightening, reading and answering are the app's own.

The upload clip draws a file window and a pointer over the page - a stand-in
for the desktop, which a browser recording cannot show. The file dropped is
the real week12hints.txt, through a real drop event; uploading, reading and
indexing it are the app's own.

Output: web/static/demos/<clip>.mp4. Needs: requirements-dev.txt (Playwright
and its Chromium) and ffmpeg.
"""
import base64
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
import db  # noqa: E402

BASE = os.environ.get("DEMO_BASE", "http://localhost:8000")
EMAIL, UPLOADER, SCANNER = "demo@example.com", "upload-demo@example.com", "scan-demo@example.com"
OUT = ROOT / "web" / "static" / "demos"
WIDE, PHONE = {"width": 1440, "height": 900}, {"width": 412, "height": 915}
READ_SECONDS, CHECK_SECONDS, UPLOAD_SECONDS = 2.0, 1.0, 2.0
UPLOAD_FILE = ROOT / "eval set" / "week12hints.txt"
SCAN_PDF = ROOT / "eval set" / "IS114 AY26-T1 Course Content, Student Edition.pdf"
SCAN_PAGES = (1, 3, 4)   # never p. 2 (the sections table: staff names and emails) or p. 9
STRAIGHTEN_SECONDS = 2.5   # straightening and reading the pages, as shown
MISREAD = "oIt's"          # a bullet read as a letter on p. 3; fixed on camera when the OCR makes it

# clip -> (who, viewport, Library shown, steps). Steps: ("ask", question); ("source", n) opens the
# n-th step's Source in the last answer; ("open",) follows the open excerpt's "Open in the file";
# ("drop",) drags UPLOAD_FILE into the chat; ("scan",) scans SCAN_PAGES; ("show", selector) scrolls
# it into view; ("pause", seconds).
CLIPS = {
    "hero": (EMAIL, WIDE, False, [
        ("ask", "How many IS114 revision quizzes do I need to complete to get full marks?"), ("pause", 2.5),
        ("ask", "And how much is each one worth?"), ("pause", 3.5)]),
    "citations": (EMAIL, WIDE, False, [
        ("ask", "In IS114 Mission 3, which tool should I use to check the state of the ports before and after starting each HTTP server?"),
        ("pause", 1.5), ("source", 1), ("pause", 3), ("open",), ("pause", 3.5)]),
    "gaps": (EMAIL, WIDE, False, [
        ("ask", "Is there a time limit once I open an IS114 revision quiz?"), ("pause", 3),
        ("ask", "What is the passing mark for IS114?"), ("pause", 3.5)]),
    "pictures": (EMAIL, WIDE, False, [
        ("ask", "In the academic violation reporting procedure, what are the first two things the school does after discovering a violation?"),
        ("pause", 4.5)]),
    "spreadsheet": (EMAIL, WIDE, False, [
        ("ask", "What is Eagle Soccer Academy's net profit for December (pre-IFRS 18 format)?"), ("pause", 1.5),
        ("source", 1), ("pause", 2.5), ("open",), ("pause", 3.5)]),
    "upload": (UPLOADER, WIDE, True, [
        ("pause", 1.2), ("drop",), ("pause", 1.5),
        ("ask", "Which tool do I use to copy the images folder from my computer to the EC2 server?"), ("pause", 1.5),
        ("source", 1), ("pause", 3.5)]),
    "phone": (EMAIL, PHONE, False, [
        ("ask", "Which week is the IS114 recess week?"), ("pause", 2), ("source", 1), ("pause", 3.5)]),
    "scan": (SCANNER, PHONE, False, [
        ("pause", 1.2), ("scan",), ("pause", 1.2),
        ("ask", "How many IS114 revision quizzes do I need to complete to get full marks?"), ("pause", 1.5),
        ("show", ".turn:last-child figure"), ("pause", 3), ("source", 1), ("pause", 3)]),
}


def scan_photos(folder):
    """Stand-in camera photos of SCAN_PAGES (see the module docstring), after checking
    that the pages' own text holds nothing personal."""
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image
    pdf, rng, out = pdfium.PdfDocument(str(SCAN_PDF)), np.random.default_rng(3), []
    for n in SCAN_PAGES:
        if PRIVATE.search(pdf[n - 1].get_textpage().get_text_range()):
            sys.exit(f"p. {n} of {SCAN_PDF.name} holds what looks like personal details; not scanning it")
        page = np.asarray(pdf[n - 1].render(scale=150 / 72).to_pil().convert("RGB"))
        ph, pw = page.shape[:2]
        W, H = 3000, 4000
        canvas = np.empty((H, W, 3), np.uint8)
        canvas[:] = (62, 47, 36)
        canvas = np.clip(canvas.astype(int) + rng.integers(-12, 12, canvas.shape), 0, 255).astype(np.uint8)
        j = rng.integers(-70, 70, 8)
        corners = np.float32([[420 + j[0], 520 + j[1]], [2580 + j[2], 380 + j[3]], [2700 + j[4], 3560 + j[5]], [300 + j[6], 3420 + j[7]]])
        M = cv2.getPerspectiveTransform(np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]]), corners)
        mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), M, (W, H))
        canvas[mask > 0] = cv2.warpPerspective(page, M, (W, H))[mask > 0]
        path = pathlib.Path(folder) / f"IMG_{4100 + n}.jpg"
        Image.fromarray(cv2.GaussianBlur(canvas, (3, 3), 0)).save(path, "JPEG", quality=88)
        out.append(str(path))
    return out

PRIVATE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+|(?<![\w/])@[A-Za-z0-9_]{3,}|(?<!\d)[689]\d{3}\s?\d{4}(?!\d)")


def guard(page, where):
    """Stop before anything personal reaches a clip (see the module docstring)."""
    found = PRIVATE.findall(page.evaluate("document.body.innerText"))
    if found:
        sys.exit(f"stopped at {where}: the screen shows what looks like personal details ({len(found)} match(es)); no clip saved")


def reset(email):
    name = os.environ.get("WEB_PGDATABASE")
    if not name or name == os.environ.get("PGDATABASE", "ailodge"):
        sys.exit("Set WEB_PGDATABASE to a recording database (e.g. ailodge_rec): this clears the demo users' history.")
    user = db.one("SELECT * FROM users WHERE email = %s", (email,))
    if not user:
        return
    if user["library_id"] != "eval":
        import ingest
        for f in db.all_("SELECT * FROM files WHERE library_id = %s", (user["library_id"],)):
            ingest.delete(f)
    db.run("DELETE FROM messages WHERE user_id = %s", (user["id"],))
    db.run("UPDATE users SET questions_used = 0, files_used = 0, pages_used = 0 WHERE id = %s", (user["id"],))


# The stand-in desktop for the upload clip: a pointer that follows the mouse, and a file window.
PROPS = """
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #rec-pointer { position: fixed; z-index: 99; width: 22px; height: 22px; pointer-events: none; left: -40px; top: -40px; transition: transform .12s; }
    #rec-files { position: fixed; z-index: 98; right: 44px; top: 150px; width: 330px; border-radius: 14px; overflow: hidden; pointer-events: none;
      background: #1f1f23; color: #e4e4e7; font: 13px/1.4 -apple-system, system-ui, sans-serif; box-shadow: 0 24px 60px rgba(2,6,23,.35); transition: opacity .4s; }
    #rec-files .bar { display: flex; align-items: center; gap: 7px; padding: 11px 13px; background: #2a2a2f; font-weight: 600; }
    #rec-files .bar i { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
    #rec-files .row { display: flex; align-items: center; gap: 9px; padding: 7px 14px; }
    #rec-files .row.sel { background: #2563eb; color: #fff; }
    #rec-files .ico { width: 14px; height: 17px; border-radius: 2px; background: #a1a1aa; flex: none; }
    #rec-ghost { position: fixed; z-index: 99; pointer-events: none; display: none; align-items: center; gap: 8px; padding: 7px 11px;
      background: rgba(255,255,255,.92); border: 1px solid #cbd5e1; border-radius: 10px; font: 600 13px/1 -apple-system, system-ui, sans-serif;
      color: #0f172a; box-shadow: 0 10px 30px rgba(2,6,23,.25); }`;
  document.head.appendChild(css);
  const p = document.createElement('div'); p.id = 'rec-pointer';
  p.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 2l16 11-7 1-4 7z" fill="#111" stroke="#fff" stroke-width="1.5"/></svg>';
  const w = document.createElement('div'); w.id = 'rec-files';
  w.innerHTML = '<div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i>&nbsp; IS114</div>'
    + ['Week 11 slides.pdf', 'week12hints.txt', 'Mission 3 brief.docx', 'Quiz scores.xlsx']
      .map(n => `<div class="row ${n === 'week12hints.txt' ? 'sel' : ''}"><span class="ico"></span>${n}</div>`).join('');
  const g = document.createElement('div'); g.id = 'rec-ghost'; g.innerHTML = '<span style="background:#e2e8f0;border-radius:4px;padding:3px 5px;font-size:10px">TXT</span>week12hints.txt';
  document.body.append(w, g, p);
  addEventListener('mousemove', e => { p.style.left = e.clientX + 'px'; p.style.top = e.clientY + 'px';
    g.style.left = (e.clientX + 14) + 'px'; g.style.top = (e.clientY + 10) + 'px'; }, true);
})()
"""

DROP = """
async ([b64, name]) => {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const dt = new DataTransfer();
  dt.items.add(new File([bytes], name, {type: 'text/plain'}));
  const at = document.querySelector('#ask');
  for (const type of ['dragenter', 'dragover']) document.body.dispatchEvent(new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true}));
  await new Promise(r => setTimeout(r, 650));
  at.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
}
"""


def record(browser, name, tmp):
    who, size, library, steps = CLIPS[name]
    reset(who)
    ctx = browser.new_context(viewport=size, record_video_dir=tmp, record_video_size=size,
                              is_mobile=size is PHONE, has_touch=size is PHONE)
    ctx.add_init_script(f"try {{ localStorage.setItem('anchor-lib', '{'open' if library else 'closed'}'); "
                        "localStorage.setItem('anchor-src', 'open'); } catch (e) {}")
    r = ctx.request.post(f"{BASE}/api/dev-login", data={"email": who, "name": "Demo student"})
    if not r.ok:
        sys.exit(f"sign-in failed: {r.status}")
    page = ctx.new_page()
    t0 = time.monotonic()
    now = lambda: time.monotonic() - t0  # noqa: E731
    page.goto(f"{BASE}/app", wait_until="networkidle")
    page.wait_for_timeout(800)
    start = now()
    squeeze = []  # (from, to, seconds it may take in the clip)
    answers = 0
    state = "document.querySelectorAll('.turn')[{n}]?.dataset.state"
    for step in steps:
        kind, arg = step[0], (step[1] if len(step) > 1 else None)
        if kind == "ask":
            page.click("#question")
            page.keyboard.type(arg, delay=26)
            page.wait_for_timeout(350)
            page.keyboard.press("Enter")
            sent = now()
            n = answers
            answers += 1
            page.wait_for_function(f"['writing', 'checking', 'done', 'error'].includes({state.format(n=n)})", timeout=180_000, polling=50)
            if page.evaluate(state.format(n=n)) == "error":
                sys.exit(f"{name}: the app showed an error for {arg!r} (see the server log); no clip saved")
            writing = now()
            page.wait_for_function(f"['checking', 'done'].includes({state.format(n=n)})", timeout=180_000, polling=50)
            checking = now()
            page.wait_for_function(f"{state.format(n=n)} === 'done'", timeout=180_000, polling=50)
            done = now()
            squeeze += [(sent + 0.5, writing, READ_SECONDS), (checking, done, CHECK_SECONDS)]
            page.wait_for_timeout(900)
            guard(page, f"answer {answers} of {name}")
        elif kind == "source":
            btn = page.locator(".turn").last.locator(".ans-src").nth(arg - 1)
            btn.scroll_into_view_if_needed()
            btn.hover()
            page.wait_for_timeout(500)
            btn.click()
            page.wait_for_timeout(700)
            guard(page, f"sources in {name}")
        elif kind == "open":
            link = page.locator("#sources .xc-open").first
            link.evaluate("a => a.target = '_self'")
            link.hover()
            page.wait_for_timeout(600)
            link.click()
            page.wait_for_load_state("networkidle")
            guard(page, f"the opened file in {name}")
        elif kind == "drop":
            page.evaluate(PROPS)
            page.mouse.move(700, 450)
            page.wait_for_timeout(700)
            row = page.locator("#rec-files .row.sel").bounding_box()
            page.mouse.move(row["x"] + 60, row["y"] + row["height"] / 2, steps=18)
            page.wait_for_timeout(400)
            page.evaluate("document.getElementById('rec-ghost').style.display = 'inline-flex'")
            box = page.locator("#ask").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 40, steps=40)
            page.evaluate(DROP, [base64.b64encode(UPLOAD_FILE.read_bytes()).decode(), UPLOAD_FILE.name])
            page.evaluate("document.getElementById('rec-ghost').style.display = 'none'; document.getElementById('rec-files').style.opacity = '0'")
            dropped = now()
            page.wait_for_selector(".up small.ok", timeout=300_000)
            squeeze.append((dropped + 0.8, now() - 0.2, UPLOAD_SECONDS))
            page.wait_for_timeout(1000)
            page.evaluate("document.getElementById('rec-pointer').remove()")
            guard(page, f"the upload in {name}")
        elif kind == "scan":
            page.click("#scan-btn")
            page.wait_for_selector("#scan[open]")
            page.wait_for_timeout(1300)
            with page.expect_file_chooser() as chooser:
                page.click("#scan-choose")
            chooser.value.set_files(scan_photos(tmp))
            chosen = now()
            page.wait_for_function("() => document.querySelectorAll('#scan-pages .pg').length && !document.querySelector('#scan-pages .spin')",
                                   timeout=120_000, polling=50)
            squeeze.append((chosen + 0.6, now(), STRAIGHTEN_SECONDS))
            page.wait_for_timeout(1800)
            # Check page 2's text, and fix the misread if the OCR made it.
            page.click("#scan-pages .pg[data-i='1'] button[data-a='text']")
            page.wait_for_timeout(1800)
            at = page.locator("#edit-area").evaluate(f"""a => {{ const i = a.value.indexOf({MISREAD!r});
                if (i < 0) return -1; a.focus(); a.setSelectionRange(i, i + 2);
                a.blur(); a.focus(); a.setSelectionRange(i, i + 2); return i; }}""")
            if at >= 0:
                page.wait_for_timeout(900)
                page.keyboard.type("I", delay=150)
                page.wait_for_timeout(1600)
            page.click("#edit-done")
            page.wait_for_timeout(1300)
            page.locator("#scan .body").evaluate("b => b.scrollTo({top: b.scrollHeight, behavior: 'smooth'})")
            page.wait_for_timeout(1100)
            page.click("#scan-save")
            saved = now()
            page.wait_for_selector(".up small.ok", timeout=300_000)
            squeeze.append((saved + 1.0, now() - 0.2, UPLOAD_SECONDS))
            page.wait_for_timeout(1200)
            guard(page, f"the scan in {name}")
        elif kind == "show":
            page.locator(arg).scroll_into_view_if_needed()
            page.wait_for_timeout(400)
        elif kind == "pause":
            page.wait_for_timeout(int(arg * 1000))
    end = now()
    video = page.video.path()
    ctx.close()
    return video, start, end, squeeze


def encode(src, dest, start, end, squeeze):
    """Real speed, except each squeezed stretch, which is sped up to fit its seconds."""
    cuts, t = [], start
    for a, b, fit in sorted(squeeze):
        if b - a > fit:
            cuts += [(t, a, 1.0), (a, b, (b - a) / fit)]
            t = b
    cuts.append((t, end, 1.0))
    cuts = [c for c in cuts if c[1] - c[0] > 0.04]
    parts = [f"[0:v]trim=start={a:.2f}:end={b:.2f},setpts=(PTS-STARTPTS)/{s:.3f}[v{i}]" for i, (a, b, s) in enumerate(cuts)]
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(cuts))) + f"concat=n={len(cuts)}:v=1:a=0[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", graph, "-map", "[out]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "slow", "-r", "30",
                    "-movflags", "+faststart", "-an", str(dest)], check=True)
    return sum(min(b - a, fit) for a, b, fit in squeeze), sum(b - a for a, b, _ in squeeze)


def main():
    names = sys.argv[1:] or list(CLIPS)
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch()
        # One unrecorded question first: a fresh server loads the reranker on its first search (~40 s).
        warm = browser.new_context()
        warm.request.post(f"{BASE}/api/dev-login", data={"email": EMAIL, "name": "Demo student"})
        warm.request.post(f"{BASE}/api/ask", data={"question": "Which week is the IS114 recess week?"}, timeout=180_000)
        warm.close()
        for name in names:
            video, start, end, squeeze = record(browser, name, tmp)
            dest = OUT / f"{name}.mp4"
            shown, waited = encode(video, dest, start, end, squeeze)
            print(f"{name}: {end - start:.0f} s recorded; {waited:.0f} s of waiting shown as {shown:.1f} s "
                  f"-> {dest.relative_to(ROOT)}, {dest.stat().st_size // 1024} KB", flush=True)
        browser.close()
    for who in (EMAIL, UPLOADER, SCANNER):
        reset(who)


if __name__ == "__main__":
    main()
