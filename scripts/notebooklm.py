"""Anchor vs NotebookLM (now Gemini Notebook) on the same 41 practice questions.

The owner asks the questions in Gemini Notebook by hand (it has no API to ask
through); this does the rest, so both systems are scored the same way:

  1. prepare   notebooklm_upload/ (gitignored): the 6 course files as they are,
               plus the spreadsheet as one CSV per sheet - Gemini Notebook does
               not take .xlsx (its help page lists CSV and Google Sheets).
  2. collect   in your own terminal: each question is copied to the clipboard;
               paste it into a new chat, copy the answer, press Enter, and the
               answer is read from the clipboard into runs/notebooklm_scoring.csv.
               Saved after every question, so it can be stopped and resumed.
  3. grade     every answer scored by Anchor's own grader (grader.py, against the
               whole Library, as Anchor's answers were): correct, and any claim
               the Library doesn't back. About $0.20. Then the head-to-head:
               counts by group, and the questions only one system got right.

Refusals: grader.py recognises Anchor's wording ("not in your materials").
Gemini Notebook says "the sources don't mention ...", so `grade` also accepts
"sources" wording, and lists every answer to a not-in-the-files question that
it did not count as a refusal, to check by eye.

    .venv/bin/python scripts/notebooklm.py prepare
    .venv/bin/python scripts/notebooklm.py collect      # in Terminal, not in Claude Code
    .venv/bin/python scripts/notebooklm.py grade
"""
import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SHEET = ROOT / "runs" / "notebooklm_scoring.csv"
META = ROOT / "runs" / "notebooklm_meta.json"
UPLOAD = ROOT / "notebooklm_upload"
COURSE = ROOT / "eval set"
XLSX = "3A-Adjust-Class-Worksheet (Answer Key) (1).xlsx"
QUESTION_FILES = {"original": "eval_set.csv", "added": "eval_set_added.csv", "solve": "eval_set_solve.csv"}

# Gemini Notebook's ways of saying it can't answer from the sources, beside grader.NOT_FOUND.
SOURCES_SAY_NOTHING = re.compile(
    r"(sources?|documents?|materials?|notes?|files?|notebook) (provided )?(do not|does not|don't|doesn't) "
    r"(say|state|specify|mention|give|include|contain|provide|cover|have|discuss|address|list)"
    r"|there is no (\w+ )?(q\d+|question|section|g\d+)\b"  # "There is no Q17 in the provided sample midterm" (A09)
    r"|(not|n't) (mentioned|found|included|covered|stated|specified|provided|discussed|addressed) in (the|your|these) "
    r"(provided )?(sources?|documents?|materials?|notes?|files?)"
    r"|no (information|mention|details?) (about|on|of|regarding)", re.I)


def load():
    return list(csv.DictReader(SHEET.open(encoding="utf-8")))


def save(rows):
    tmp = SHEET.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(SHEET)


def prepare():
    import openpyxl
    if UPLOAD.exists():
        shutil.rmtree(UPLOAD)
    UPLOAD.mkdir()
    for src in sorted(COURSE.iterdir()):
        if src.name != XLSX and not src.name.startswith("."):
            shutil.copy2(src, UPLOAD / src.name)
    wb = openpyxl.load_workbook(COURSE / XLSX, data_only=True)  # the values Anchor's spreadsheet route reads
    stem = pathlib.Path(XLSX).stem
    for ws in wb.worksheets:
        with (UPLOAD / f"{stem} - {ws.title}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for row in ws.iter_rows(values_only=True):
                if any(v is not None for v in row):
                    w.writerow(["" if v is None else v for v in row])
    files = sorted(p.name for p in UPLOAD.iterdir())
    print(f"{len(files)} files in {UPLOAD}:")
    for name in files:
        print("  ", name)
    print("\nAdd them all as sources of one new notebook, with every source ticked.")


def collect():
    rows = load()
    meta = json.loads(META.read_text()) if META.exists() else {}
    if not meta:
        meta = {"plan": input("Which Gemini Notebook plan are you on (Free, Pro, Ultra)? ").strip() or "unknown",
                "started": dt.date.today().isoformat(),
                "spreadsheet": "uploaded as one CSV per sheet (notebooklm_upload/)"}
        META.write_text(json.dumps(meta, indent=1))
    todo = [r for r in rows if not r["notebooklm_answer"].strip()]
    print(f"\n{len(rows) - len(todo)} of {len(rows)} answered already; {len(todo)} to go.")
    print("For each: the question is on your clipboard. Paste it into a NEW chat in Gemini Notebook,\n"
          "copy its whole answer (its copy button), then press Enter here.  s = skip, q = quit.\n")
    for n, row in enumerate(todo, 1):
        subprocess.run(["pbcopy"], input=row["question"].encode(), check=True)
        print(f"--- {n}/{len(todo)}  {row['id']} ({row['group']}, {row['kind']}) ---\n{row['question']}\n")
        while True:
            cmd = input("Copied. Enter = save the answer on your clipboard, s = skip, q = quit: ").strip().lower()
            if cmd in ("q", "s"):
                break
            answer = subprocess.run(["pbpaste"], capture_output=True, check=True).stdout.decode("utf-8", "replace").strip()
            if not answer or answer == row["question"].strip():
                print("Your clipboard still holds the question - copy Gemini Notebook's answer first.")
                continue
            # A stale clipboard: the answer already saved for another question (seen 22 Oct on Q07).
            if same := next((r["id"] for r in rows if r is not row and r["notebooklm_answer"].strip() == answer), None):
                print(f"That is the answer you saved for {same} - copy this question's answer first.")
                continue
            row["notebooklm_answer"] = answer
            save(rows)
            print(f"Saved ({len(answer.split())} words).\n")
            break
        if cmd == "q":
            break
    left = sum(not r["notebooklm_answer"].strip() for r in rows)
    print(f"\n{len(rows) - left} of {len(rows)} answered." + (" Run `grade` next." if not left else " Run `collect` again to go on."))


def sign_test(a_only, b_only):
    """Two-sided exact sign test on the questions only one system got right."""
    n, k = a_only + b_only, max(a_only, b_only)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n)


def grade():
    import library as L
    from grader import grade as grade_one
    from openai_client import client
    rows = load()
    missing = [r["id"] for r in rows if not r["notebooklm_answer"].strip()]
    if missing:
        sys.exit(f"{len(missing)} question(s) have no Gemini Notebook answer yet ({', '.join(missing)}). Run `collect` first.")
    questions = {}
    for group, name in QUESTION_FILES.items():
        for q in csv.DictReader((ROOT / name).open(encoding="utf-8")):
            if q["set"] == "Build":
                questions[q["id"]] = q
    c, library = client(), L.library_text()
    usages, check = [], []
    for row in rows:
        q, answer = questions[row["id"]], row["notebooklm_answer"]
        plain = answer.replace("’", "'").replace("‘", "'").replace("*", "")  # curly quotes, **bold** marks
        refused = bool(SOURCES_SAY_NOTHING.search(plain))
        # The answer as its one step too, so the grader always reads it (a step-less refusal skips the model).
        result = {"final_answer": answer, "steps": [{"text": answer}], "not_found": refused}
        verdict, usage = grade_one(c, q, result, library)
        usages.append(usage)
        if q["tag"] == "not_in_docs":
            verdict["correct"] = refused or verdict["correct"]
            if not refused:
                check.append(row["id"])
        row["notebooklm_correct"] = "yes" if verdict["correct"] else "no"
        row["notebooklm_unsupported_claim"] = "yes" if verdict["hallucination"] else "no"
        row["notebooklm_refused"] = "yes" if refused else "no"
        row["notes"] = "; ".join(f"unbacked: {cl['claim']}" for cl in verdict.get("claims", []) if not cl.get("backed"))[:300]
        print(f"{row['id']}  Anchor {'right' if row['anchor_correct'] == 'yes' else 'WRONG'}  "
              f"Gemini Notebook {'right' if verdict['correct'] else 'WRONG'}"
              + ("  (unsupported claim)" if verdict["hallucination"] else ""), flush=True)
    save(rows)
    report(rows, usages, check)


def report(rows, usages, check):
    sys.path.insert(0, str(ROOT / "web"))
    from pipeline import cost  # the website's cost estimate, so the figures match the Demo budget's
    meta = json.loads(META.read_text()) if META.exists() else {}
    yes = lambda rs, col: sum(r[col] == "yes" for r in rs)  # noqa: E731
    lines = [f"Anchor vs Gemini Notebook ({meta.get('plan', 'plan not recorded')} plan, asked {meta.get('started', '?')}; "
             f"spreadsheet {meta.get('spreadsheet', '?')})", "",
             f"{'group':<10}{'questions':>10}{'Anchor right':>14}{'Notebook right':>16}{'Anchor unsupp.':>16}{'Notebook unsupp.':>18}"]
    for group in QUESTION_FILES:
        rs = [r for r in rows if r["group"] == group]
        lines.append(f"{group:<10}{len(rs):>10}{yes(rs, 'anchor_correct'):>14}{yes(rs, 'notebooklm_correct'):>16}"
                     f"{yes(rs, 'anchor_unsupported_claim'):>16}{yes(rs, 'notebooklm_unsupported_claim'):>18}")
    lines.append(f"{'all':<10}{len(rows):>10}{yes(rows, 'anchor_correct'):>14}{yes(rows, 'notebooklm_correct'):>16}"
                 f"{yes(rows, 'anchor_unsupported_claim'):>16}{yes(rows, 'notebooklm_unsupported_claim'):>18}")
    nid = [r for r in rows if r["kind"] == "not_in_docs"]
    lines += ["", f"Not-in-the-files questions refused correctly: Anchor {yes(nid, 'anchor_correct')} of {len(nid)}, "
                  f"Gemini Notebook {yes(nid, 'notebooklm_correct')} of {len(nid)}",
              f"Confidently wrong (wrong, not flagged Unsure): Anchor {yes(rows, 'anchor_confidently_wrong')}, "
              f"Gemini Notebook {sum(r['notebooklm_correct'] == 'no' for r in rows)} (it has no Unsure label)"]
    a_only = [r["id"] for r in rows if r["anchor_correct"] == "yes" and r["notebooklm_correct"] == "no"]
    b_only = [r["id"] for r in rows if r["anchor_correct"] == "no" and r["notebooklm_correct"] == "yes"]
    p = sign_test(len(a_only), len(b_only))
    lines += ["", f"Only Anchor right: {len(a_only)} {a_only}", f"Only Gemini Notebook right: {len(b_only)} {b_only}",
              f"Sign test on those {len(a_only) + len(b_only)}: p = {p:.3f} -> "
              + ("no clear winner on these 41 questions" if p >= 0.05 else
                 ("Anchor" if len(a_only) > len(b_only) else "Gemini Notebook") + " ahead on these 41 questions")]
    if check:
        lines += ["", f"Check by eye - not-in-the-files answers NOT counted as refusals: {check}"]
    tin, tout, usd = cost(usages)
    lines += ["", f"Grading: {sum(1 for u in usages if u)} model calls, about ${usd:.2f}"]
    text = "\n".join(lines)
    print("\n" + text)
    out = ROOT / "runs" / f"notebooklm__{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.txt"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\nsaved runs/{out.name}, and the scores in {SHEET}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "collect", "grade"])
    {"prepare": prepare, "collect": collect, "grade": grade}[ap.parse_args().step]()


if __name__ == "__main__":
    main()
