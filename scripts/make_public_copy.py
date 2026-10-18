"""Build the public copy of this repo: code, docs and the website, without the course material.

    .venv/bin/python scripts/make_public_copy.py <empty output folder>

This private repo holds the university's course files and text copied from
them, including teaching staff's names, emails and Telegram handles. The
public repo (owner's call, 18 Oct) gets a fresh history built from the
current commit with:

  left out   the course files (eval set/), everything parsed from them
             (parsed/), run files with their excerpts (runs/), the Phase 7
             sample and labels (phase7/), and the question sets
             (eval_set*.csv/.xlsx, router_labels.csv)
  blanked    any staff name, email address or Telegram handle from the course's
             sections table that still appears in what is left, plus any
             university email address -> "[redacted]"

The website's saved answers and demo clips stay: they were chosen to show no
personal details, and record_demos.py stops if a screen shows an email or handle.
It copies the last commit (HEAD), never uncommitted edits, prints every
blanked file, then fails if any staff detail is still found.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEAVE_OUT = ("eval set/", "parsed/", "runs/", "phase7/", "eval_set.csv", "eval_set.xlsx",
             "eval_set_added.csv", "router_labels.csv")
SECTIONS = ROOT / "parsed" / "IS114_AY26-T1_Course_Content_Student_Edition__pdf.md"
EMAIL = re.compile(r"[\w.+-]+@(?:[\w-]+\.)*smu\.edu\.sg", re.I)


def staff_details():
    """Names, emails and handles from the sections table (Lecturer, Instructor, TA, TA Email, Telegram)."""
    found = set()
    for line in SECTIONS.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 10 and re.fullmatch(r"G\d+", cells[0]):
            found.update(c for c in cells[5:10] if c and c != "-")
    if len(found) < 10:
        sys.exit("The sections table was not found where expected - refusing to guess what to blank.")
    return found


def main():
    out = pathlib.Path(sys.argv[1]).resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    deny = sorted(staff_details(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(d) for d in deny) + "|" + EMAIL.pattern, re.I)

    files = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "HEAD"], cwd=ROOT, capture_output=True,
                           check=True).stdout.decode().split("\0")
    kept = [f for f in files if f and not f.startswith(LEAVE_OUT)]
    blanked = {}
    for f in kept:
        dest = out / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        # From the last commit, not the working tree: another session may be mid-edit.
        data = subprocess.run(["git", "show", f"HEAD:{f}"], cwd=ROOT, capture_output=True, check=True).stdout
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            dest.write_bytes(data)  # pictures, clips: checked by hand when chosen
            continue
        new, n = pattern.subn("[redacted]", text)
        if n:
            blanked[f] = n
        dest.write_text(new, encoding="utf-8")

    left = [f for f in kept if (out / f).is_file() and pattern.search((out / f).read_bytes().decode("utf-8", "ignore"))]
    print(f"{len(kept)} files copied, {len(files) - 1 - len(kept)} left out")
    for f, n in sorted(blanked.items()):
        print(f"  blanked {n:>3} in {f}")
    if left:
        sys.exit(f"still found staff details in: {left}")


if __name__ == "__main__":
    main()
