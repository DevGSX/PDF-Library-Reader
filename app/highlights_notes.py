"""Builds a standalone reading-notes file (Markdown) from a book's saved
highlights -- like Kindle's "My Clippings.txt", but for actually reading
back what you highlighted, not for moving your library around (that's what
the archive export/import is for; highlights ride along there too, but
gated behind whether that export includes personal reading data).

Plain string in, plain string out -- no Qt or database dependency -- so
it's testable without a running GUI.
"""
from datetime import datetime


def build_highlights_notes(book_title, highlights):
    """highlights: a list of dicts shaped like Database.get_highlights()'s
    output (page_number, label, color, text, created_date), already
    sorted however the caller wants them to appear -- typically by page.
    Returns the complete Markdown document as a string."""
    lines = [f"# Highlights \u2014 {book_title}", "", f"_Exported {datetime.now().strftime('%Y-%m-%d')}_", ""]
    if not highlights:
        lines.append("_No highlights saved for this book yet._")
        return "\n".join(lines)

    lines.append("---")
    for h in highlights:
        label = h.get("label") or f"Page {h['page_number'] + 1}"
        lines.append("")
        lines.append(f"### {label}")
        lines.append("")
        text = (h.get("text") or "").strip()
        if text:
            # Blockquote each line of the highlighted passage separately,
            # so a highlight spanning a paragraph break still renders as
            # one clean blockquote in Markdown instead of getting cut off
            # at the first blank line.
            for para in text.split("\n\n"):
                for line in para.strip().splitlines() or [""]:
                    lines.append(f"> {line}")
                lines.append(">")
            if lines[-1] == ">":
                lines.pop()
        else:
            lines.append("_(no text captured)_")
        lines.append("")
        lines.append("---")
    return "\n".join(lines)
