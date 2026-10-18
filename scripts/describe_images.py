"""Phase 2, step 5: one Diagram description per image, written by a vision model.

OCR is not enough for these files. In the eLearn screenshot the answer IS a
pink arrow - there is no text saying "click Quizzes". In the flowchart, which
step follows which depends on the direction of arrows and on whether a line is
solid or dashed. So the description has to put arrows, lines and annotations
into words, not just transcribe labels.

The prompt is the production one, not tuned to the eval questions: it is the
same instruction a user's uploaded diagram would get, and it never mentions
what the eval set asks. A prompt that hinted at the answers would make the
image questions pass for the wrong reason.

Model: gemini-3.5-flash-lite through the apiyi relay - the one exception to
gpt-5-mini for every model call (docs/adr/0003). On the eLearn screenshot
gpt-5-mini said the pink arrow points down-left at "Assignments" in 7 of 7
runs; it points down-right at "Quizzes". Gemini named Quizzes in 4 of 4.
Claude Haiku 4.5 and Qwen 3.6 Flash also said Assignments.

Output, under parsed/:
  <stem>__png.md         the Diagram description, with a short header
  images_report.json     model, tokens used, seconds, per image
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from diagram_connections import ask, connections, keep_sections  # noqa: E402
from openai_client import VISION_MODEL, client  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "eval set"
OUT = ROOT / "parsed"

IMAGES = [
    "IS114_eLearn_Quizzes_tab.png",
    "IS114_Academic_Violation_Reporting_Procedure.png",
]

PROMPT_VERSION = "4"  # v4: free text limited to what-it-is + verbatim text; connections voted
# This pass is trusted only for what the image is and the text on it. Arrows,
# lines and annotations are read separately, three times, and voted on
# (diagram_connections.py) - an earlier version of this prompt also asked for
# them, and its single reading contradicted the vote (an arrow "pointing
# upwards" that runs down; boxes numbered "Step 7, Step 8" out of flow order).
PROMPT = """\
You are writing part of a Diagram description: a text version of one image
from a student's course material. It will be searched and quoted instead of
the image, so any text the image shows but you leave out can never be found.
Arrows, lines and annotations are recorded separately - do not describe them.

Write Markdown with exactly these two sections:

## What it is
One or two sentences: the kind of image (flowchart, screenshot, chart, table,
photo of a whiteboard, ...) and its subject. Do not say what any arrow,
highlight or annotation points at.

## All text, verbatim
Every piece of visible text, exactly as written, including titles, labels,
menu items, footnotes and their numbers, and superscripts (write a superscript
as e.g. "school^1", "2^nd"). Group it by where it sits in the image (top,
bottom-left, ...) and mention an icon or colour where it helps tell elements
apart. Text printed beside a line goes under "Labels beside lines", without
saying which way the line runs. Do not number elements as steps, do not
describe arrows or lines, and do not correct, summarise or translate the text.
"""


def stem_for(name):
    p = pathlib.Path(name)
    return f"{p.stem}{p.suffix.replace('.', '__')}"


def describe(c, path):
    return ask(c, VISION_MODEL, path, PROMPT)


def main():
    c = client()
    report = {"prompt_version": PROMPT_VERSION, "images": {}}
    only = set(sys.argv[1:])
    for name in IMAGES:
        if only and name not in only:
            continue
        print(f"describing {name} ...", flush=True)
        text, usage = describe(c, SRC / name)
        # The free-text pass is trusted for what the image is and its text; the
        # connections are re-read three times and voted on (diagram_connections.py).
        conn_md, audit, conn_usage = connections(c, VISION_MODEL, SRC / name)
        body = keep_sections(text) + "\n" + conn_md
        header = (f"<!-- Diagram description of {name} | model {usage['model']} | "
                  f"prompt v{PROMPT_VERSION} -->\n\n")
        (OUT / f"{stem_for(name)}.md").write_text(header + body.strip() + "\n", encoding="utf-8")
        (OUT / f"{stem_for(name)}.edges.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        usages = [usage] + conn_usage
        report["images"][name] = {
            "model": usage["model"], "calls": len(usages),
            "prompt_tokens": sum(u["prompt_tokens"] for u in usages),
            "completion_tokens": sum(u["completion_tokens"] for u in usages),
            "seconds": round(sum(u["seconds"] for u in usages), 1),
            "agreed_connections": len(audit["agreed"]),
            "unconfirmed_connections": len(audit["unconfirmed"]),
        }
        print(f"  -> {report['images'][name]}", flush=True)

    path = OUT / "images_report.json"
    if path.exists() and only:
        old = json.loads(path.read_text())
        old["images"].update(report["images"])
        report = old
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
