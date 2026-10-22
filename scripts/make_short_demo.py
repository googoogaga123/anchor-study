"""A 60-second demo video, cut from the front page's real clips (record_demos.py).

    .venv/bin/python scripts/make_short_demo.py      # -> submission/anchor-demo-1min.mp4

Every shot is the real app answering live: nothing is generated or mocked up.
Shots are trimmed, never sped up; the clips already shorten only the waits
(record_demos.py), and a note on screen says so. The scan clip's photos are
stand-ins for camera shots, and its caption says that too.

Captions and cards are drawn with Pillow (this ffmpeg has no text filter) and
laid over the footage. The clips were privacy-checked when recorded: the
recorder stops if a screen shows an email address or a handle.
"""
import pathlib
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIPS = ROOT / "web" / "static" / "demos"
OUT = ROOT / "submission" / "anchor-demo-1min.mp4"
W, H, FPS = 1440, 900, 30
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"  # index 0 regular, 1 bold
BG, INK, MUTE, SOFT = "#f8fafc", "#0f172a", "#64748b", "#94a3b8"
NOTE = "Real app, recorded live · waits shortened"

# (clip, start s, end s, caption); a phone clip is shown in a phone frame with the caption beside it.
SHOTS = [
    ("hero", 0.0, 9.0, "Ask about your course. Every step quotes your files, word for word."),
    ("hero", 15.0, 21.0, "A step that can't be confirmed is flagged Unsure, not passed off as fact."),
    ("citations", 13.0, 19.0, "One click opens the exact line it came from."),
    ("spreadsheet", 9.0, 16.0, "Numbers come straight from your spreadsheet, with the cell cited."),
    ("gaps", 12.5, 18.0, "Not in your files? It says so, instead of guessing."),
    ("pictures", 7.5, 12.5, "It reads diagrams, and shows the picture it used."),
    ("upload", 0.5, 6.5, "Add your own files: PDF, Word, slides, pictures, spreadsheets."),
    ("scan", 5.0, 13.0, "Scan printed pages with your phone, and check the text before it's saved."),
]
TITLE_SECONDS, END_SECONDS = 2.5, 5.0
END_LINES = ["Questions about your files: 33 of 33 practice, 9 of 9 held back",
             "Same accuracy as NotebookLM on 41 questions, fewer made-up claims (1 vs 6)",
             "18 attacks on our own system: holes found, fixed and re-tested"]


def font(size, bold=False):
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def wrap(draw, text, f, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line]


def caption_bar(text, path):
    """A dark bar along the bottom with the caption, and the small honesty note."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 132, W, H], fill=(15, 23, 42, 238))
    d.text((56, H - 108), text, font=font(38, bold=True), fill="white")
    note = font(20)
    d.text((W - 56 - d.textlength(NOTE, font=note), H - 40), NOTE, font=note, fill=SOFT)
    img.save(path)


PHONE_X, PHONE_Y, PHONE_H = 220, 30, 840  # where the phone recording sits (378 x 840 once scaled)


def phone_overlay(text, path):
    """Laid over the phone recording (padded to the page): a phone's bezel around it, and the
    caption on the right. Transparent where the recording shows through."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([PHONE_X - 10, PHONE_Y - 10, PHONE_X + 378 + 10, PHONE_Y + PHONE_H + 10],
                        radius=34, outline=INK, width=12)
    big = font(52, bold=True)
    y = 300
    for line in wrap(d, text, big, 640):
        d.text((700, y), line, font=big, fill=INK)
        y += 66
    d.text((700, y + 24), "Photos in this clip are simulated: a browser recording can't use a camera.",
           font=font(22), fill=MUTE)
    note = font(20)
    d.text((W - 56 - d.textlength(NOTE, font=note), H - 40), NOTE, font=note, fill=SOFT)
    img.save(path)


def title_card(path):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for text, f, y, fill in (("Anchor", font(132, bold=True), 300, INK),
                             ("Answers you can check, from your own course files", font(40), 470, MUTE)):
        d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)
    img.save(path)


def end_card(path):
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    head = font(60, bold=True)
    d.text((120, 190), "Tested, not just built", font=head, fill="white")
    y = 320
    for line in END_LINES:
        d.text((120, y), "•  " + line, font=font(34), fill="#cbd5e1")
        y += 70
    d.text((120, y + 60), "anchor-study.vercel.app", font=font(46, bold=True), fill="white")
    img.save(path)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


ENCODE = ["-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]
FADE = f"fade=t=in:st=0:d=0.25:color=white"


def card_video(png, seconds, out):
    ffmpeg("-loop", "1", "-t", str(seconds), "-i", str(png), "-vf", f"fps={FPS},format=yuv420p", *ENCODE, str(out))


def shot_video(clip, start, end, text, tmp, n):
    src, out, png = CLIPS / f"{clip}.mp4", tmp / f"{n:02d}.mp4", tmp / f"{n:02d}.png"
    seconds = end - start
    if clip in ("scan", "phone"):
        phone_overlay(text, png)
        graph = (f"[0:v]scale=-2:{PHONE_H},setsar=1,pad={W}:{H}:{PHONE_X}:{PHONE_Y}:color={BG},fps={FPS}[v];"
                 f"[v][1:v]overlay=0:0,{FADE}")
        ffmpeg("-ss", str(start), "-t", str(seconds), "-i", str(src), "-i", str(png),
               "-filter_complex", graph, *ENCODE, str(out))
    else:
        caption_bar(text, png)
        graph = f"[0:v]scale={W}:{H},setsar=1,fps={FPS}[v];[v][1:v]overlay=0:0,{FADE}"
        ffmpeg("-ss", str(start), "-t", str(seconds), "-i", str(src), "-i", str(png),
               "-filter_complex", graph, *ENCODE, str(out))
    return out


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    parts = []
    title_card(tmp / "title.png")
    card_video(tmp / "title.png", TITLE_SECONDS, tmp / "00.mp4")
    parts.append(tmp / "00.mp4")
    for n, (clip, start, end, text) in enumerate(SHOTS, 1):
        parts.append(shot_video(clip, start, end, text, tmp, n))
    end_card(tmp / "end.png")
    card_video(tmp / "end.png", END_SECONDS, tmp / "99.mp4")
    parts.append(tmp / "99.mp4")
    (tmp / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c", "copy", "-movflags", "+faststart", str(OUT))
    seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(OUT)],
                                   capture_output=True, text=True, check=True).stdout)
    print(f"{OUT.relative_to(ROOT)}: {seconds:.1f} s, {OUT.stat().st_size / 2**20:.1f} MB (parts in {tmp})")


if __name__ == "__main__":
    main()
