"""Minimal dependency-free PDF writer for the appointment-preparation summary (R32).

Produces a valid multi-page PDF 1.4 with Helvetica text. Input is plain text
lines; typographic punctuation is mapped to its plain form (#215: "0–10" printed as "0?10").

#265: the fonts declare WinAnsiEncoding and text is encoded to cp1252, so accented Latin letters, the degree sign and
the plus-minus sign print as written (without an /Encoding a viewer used StandardEncoding: "tête" printed as "tŒte").
#455: text is NFC-normalised first, so an accent typed as a separate combining mark ("e" + U+0301, as some keyboards
and pastes write it) prints as the WinAnsi letter "é"; and common signs WinAnsi lacks are written out plainly ("≥" as
">="), so "fever ≥ 38°C" keeps its meaning. A character the standard fonts still cannot show (for example non-Latin
scripts) is replaced by a visible "?", and the PDF then says that some characters could not be shown.

#416: lines are wrapped by their drawn width in the font they use (the standard Helvetica and Helvetica-Bold advance
widths of every WinAnsi character), not by a character count, so every line, headings included, stays inside the
56 pt margins. A word longer than a line is split where it reaches the margin; nothing is drawn past it.
"""
from __future__ import annotations

import unicodedata

PAGE_W, PAGE_H, MARGIN, LEADING, FONT_SIZE = 612, 792, 56, 15, 10.5
TEXT_W = PAGE_W - 2 * MARGIN  # 500 pt: no text is drawn right of x = 556
# Size and font of each line style: F1 is Helvetica, F2 Helvetica-Bold.
STYLES = {"h1": (16, "F2"), "h2": (12, "F2"), "p": (FONT_SIZE, "F1")}


# Common typographic characters outside Latin-1 (dashes, curly quotes, ellipsis), as written by the app and the model.
# #455: and signs WinAnsi cannot show at all, written out so the meaning is kept (only characters WinAnsi lacks).
PLAIN = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
                       "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "•": "-",
                       "≥": ">=", "≤": "<=", "≠": "!=", "≈": "~", "→": "->", "←": "<-",
                       "↔": "<->", "⇒": "=>", "′": "'", "″": '"', "℃": "°C",
                       "℉": "°F", "μ": "µ", " ": " ", " ": " ", " ": " ",
                       "​": ""})


ENCODING = "cp1252"  # WinAnsiEncoding
UNSHOWN_NOTE = "Some characters could not be shown in this PDF and are printed as \"?\"."

# #416: advance widths (1/1000 em) of the WinAnsi characters 32-255 in the two standard fonts (Adobe Core 14 font
# metrics; 0 for the five byte values WinAnsi leaves undefined, which the encoder never produces).
HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
    556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
    556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
    556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
    500, 500, 500, 334, 260, 334, 584, 350, 556, 0, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0,
    611, 0, 0, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 0, 500, 667, 278, 333, 556, 556, 556,
    556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365,
    556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722,
    722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889,
    500, 556, 556, 556, 556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556,
    500, 556, 500,
)
HELVETICA_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
    556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722,
    611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556,
    611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778,
    556, 556, 500, 389, 280, 389, 584, 350, 556, 0, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0,
    611, 0, 0, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 0, 500, 667, 278, 333, 556, 556, 556,
    556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365,
    556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722,
    722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889,
    556, 556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611,
    556, 611, 556,
)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(PLAIN)


def _showable(text: str) -> str:
    return _plain(text).encode(ENCODING, "replace").decode(ENCODING)


def has_unshowable(text: str) -> bool:
    try:
        _plain(text).encode(ENCODING)
        return False
    except UnicodeEncodeError:
        return True


def _escape(text: str) -> str:
    return _showable(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_width(text: str, size: float, bold: bool = False) -> float:
    """The drawn width in pt of `text` (as it is printed) at `size` in Helvetica or Helvetica-Bold."""
    widths = HELVETICA_BOLD if bold else HELVETICA
    return sum(widths[b - 32] for b in _showable(text).encode(ENCODING) if b >= 32) * size / 1000


def wrap(text: str, size: float, bold: bool = False, width: float = TEXT_W) -> list[tuple[float, str]]:
    """#416: (indent in pt, line) pairs, each line at most `width` pt wide including its indent. Lines break at
    spaces; a word wider than a line is split where it reaches the edge. The continuation of a list item ("- ...")
    or of an indented line starts under the item's text."""
    body = text.lstrip(" ")
    lead = text[: len(text) - len(body)]
    words = body.split()
    if not words:
        return [(0.0, "")]
    hang = text_width(lead + ("- " if body.startswith("- ") else ""), size, bold)
    hang = hang if hang <= width / 4 else 0.0
    out: list[tuple[float, str]] = []
    line, indent = lead, 0.0
    for word in words:
        while word:
            room = width - indent
            sep = " " if line.strip() else ""
            if text_width(line + sep + word, size, bold) <= room:
                line, word = line + sep + word, ""
                continue
            if line.strip() and text_width(word, size, bold) <= width - hang:
                out.append((indent, line))  # the word fits on the next line
                line, indent = "", hang
                continue
            # A word wider than a whole line: it continues this line and is split where it reaches the edge.
            used, cut = text_width(line + sep, size, bold), 0
            for ch in word:
                used += text_width(ch, size, bold)
                if used > room:
                    break
                cut += 1
            if not cut and line.strip():
                out.append((indent, line))
                line, indent = "", hang
                continue
            cut = max(cut, 1)  # at least one character per line, however narrow
            out.append((indent, line + sep + word[:cut]))
            line, indent, word = "", hang, word[cut:]
    if line or not out:
        out.append((indent, line))
    return out


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def render(lines: list[tuple[str, str]]) -> bytes:
    """lines: (style, text) where style is 'h1', 'h2' or 'p'."""
    lines = [(style, unicodedata.normalize("NFC", text)) for style, text in lines]
    if any(has_unshowable(text) for _, text in lines):
        lines = [*lines[:1], ("p", UNSHOWN_NOTE), *lines[1:]]
    flowed: list[tuple[str, float, str]] = []
    for style, text in lines:
        size, face = STYLES.get(style, STYLES["p"])
        flowed += [(style, indent, line) for indent, line in wrap(text, size, face == "F2")]
    per_page = int((PAGE_H - 2 * MARGIN) // LEADING) - 2
    pages = [flowed[i:i + per_page] for i in range(0, len(flowed), per_page)] or [[]]

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # placeholder, filled below
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_ids = []
    for number, chunk in enumerate(pages, start=1):
        # Each line is placed at its own position (Tm), so a continuation line can start under its item's text.
        ops, y = ["BT"], PAGE_H - MARGIN
        for style, indent, text in chunk:
            size, face = STYLES.get(style, STYLES["p"])
            ops.append(f"/{face} {_num(size)} Tf 1 0 0 1 {_num(MARGIN + indent)} {y} Tm ({_escape(text)}) Tj")
            y -= LEADING
        ops.append(f"/F1 8 Tf 1 0 0 1 {MARGIN} {y} Tm (Page {number} of {len(pages)} - synthetic demo document) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode(ENCODING)
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
            b"/Contents %d 0 R >>" % (pages_obj, PAGE_W, PAGE_H, font, bold, content)))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    return bytes(out)
