"""Make Docling's decoded formulas searchable.

Docling's CodeFormula model emits LaTeX with a space between every character:

    $$( 1 4 - 6 ) \\cdot 5 0 0 + ( 8 - 3 ) \\cdot 5 0 0 = 6 , 5 0 0 .$$

The answer to eval Q18 is in there ($6,500) but "6,500" is not: keyword search
cannot match it, embeddings see noise, and a citation quoting "6 , 5 0 0" looks
broken. It also decodes a dollar sign as \\S, so "$700" arrives as "\\S 7 0 0".

This collapses the per-character spacing inside $$...$$ only, leaving prose
untouched, so the formula stays valid LaTeX AND contains findable numbers.
A real space inside a formula is emitted by the model as "\\ ", which is kept.
"""
import re

# A real space in the model's output, as opposed to its per-character padding.
_HARD_SPACE = "\x00"


def normalize_formula(latex: str) -> str:
    s = latex.replace("\\ ", _HARD_SPACE)
    # Every remaining single space is padding between characters.
    s = re.sub(r"(?<=\S) (?=\S)", "", s)
    # \S is a mis-decoded dollar sign. Must run before the command spacing
    # below, which would otherwise split it into "\S 700" and hide the digit.
    s = re.sub(r"\\S(?=\d)", r"\\$", s)
    # Re-separate LaTeX command names from what follows: \cdot500 -> \cdot 500
    s = re.sub(r"(\\[a-zA-Z]+)(?=[\d(\\])", r"\1 ", s)
    s = s.replace(_HARD_SPACE, " ")
    return s.strip()


_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)


def normalize_text(md: str) -> tuple[str, int]:
    n = 0

    def repl(m):
        nonlocal n
        before = m.group(1)
        after = normalize_formula(before)
        n += before != after
        return f"$${after}$$"

    return _BLOCK.sub(repl, md), n


if __name__ == "__main__":
    import pathlib
    import sys

    paths = [pathlib.Path(p) for p in sys.argv[1:]]
    for p in paths:
        md = p.read_text(encoding="utf-8")
        out, n = normalize_text(md)
        if n:
            p.write_text(out, encoding="utf-8")
        print(f"{p.name}: {n} formulas normalized")
