"""Reading-order, character-level text selection over a rendered PDF page.

The naive approach -- "grab whatever text falls inside the drag
rectangle" (PyMuPDF's page.get_textbox(rect)) -- looks reasonable but is
wrong for anything but a single-line selection: dragging from the middle
of one line to the middle of a line several lines down only grabs text
whose glyph boxes happen to fall within that rectangle's left/right
bounds, silently dropping the rest of every line in between. Real text
selection follows *reading order*: from the start point to the end of
its line, all of every line in between in full, then from the start of
the last line to the end point.

This operates on individual characters (not whole words) so a selection
can start or end mid-word, matching what a desktop PDF viewer like
Adobe Acrobat does -- word-level snapping is layered on top only for
double/triple-click, not for an ordinary drag.

Everything here is plain data in, plain data out -- no Qt or PyMuPDF
dependency in the actual selection logic -- so it can be unit tested
against synthetic character lists without a running GUI or a real PDF.
`chars_from_rawdict` is the one conversion function that understands
PyMuPDF's output shape; everything else only deals with the flat tuple
format below.

`chars` throughout is a list of (x0, y0, x1, y1, char, block_no, line_no)
tuples, one per character, already in reading order (block, then line,
then left-to-right position within the line) -- the shape produced by
chars_from_rawdict() from PyMuPDF's page.get_text("rawdict") output.
"""

X0, Y0, X1, Y1, CHAR, BLOCK, LINE = range(7)

# Characters treated as a candidate "this hyphen only exists because the
# word had to wrap here" marker when found at the very end of a line.
# Deliberately excludes en dash/em dash (\u2013, \u2014): those are
# punctuation, not word-wrap hyphenation, and wrapping mid-word with one
# would be typographically wrong, so a dash there is presumed intentional.
_WRAP_HYPHEN_CHARS = {"-", "\u2010"}


def chars_from_rawdict(rawdict):
    """Flattens PyMuPDF's page.get_text("rawdict") output into the flat
    per-character tuple list every other function in this module expects.
    Blocks/lines/spans/chars are already emitted in reading order, so no
    sorting is needed -- just flattening."""
    chars = []
    for block in rawdict.get("blocks", []):
        block_no = block.get("number", 0)
        if "lines" not in block:
            continue  # an image block, not text
        for line_no, line in enumerate(block["lines"]):
            for span in line["spans"]:
                for ch in span["chars"]:
                    x0, y0, x1, y1 = ch["bbox"]
                    chars.append((x0, y0, x1, y1, ch["c"], block_no, line_no))
    return chars


def char_index_at_point(chars, x, y):
    """The index into `chars` that a click at PDF-space point (x, y)
    should snap to, for use as a selection endpoint. Returns None if
    `chars` is empty.

    Snaps to the closest LINE by vertical distance (so clicking above the
    first line or below the last still gives a sensible answer), then
    within that line, to the character whose horizontal range contains
    the point, or whichever character edge is closest if the point falls
    in a gap or outside the line's own bounds.
    """
    if not chars:
        return None

    lines = _group_into_lines(chars)
    best_start, best_end = _closest_line(lines, y)

    for i in range(best_start, best_end + 1):
        c = chars[i]
        if c[X0] <= x <= c[X1]:
            return i

    if x <= chars[best_start][X0]:
        return best_start
    if x >= chars[best_end][X1]:
        return best_end
    for i in range(best_start, best_end):
        if chars[i][X1] <= x <= chars[i + 1][X0]:
            return i if (x - chars[i][X1]) <= (chars[i + 1][X0] - x) else i + 1
    return best_end  # pragma: no cover -- defensive fallback, shouldn't be reachable


def _group_into_lines(chars):
    """Returns [(y0, y1, start_index, end_index), ...] -- the vertical
    span and index range of each (block_no, line_no) run in `chars`.
    Assumes `chars` is already sorted in reading order."""
    lines = []
    start = 0
    for i in range(1, len(chars) + 1):
        if i == len(chars) or (chars[i][BLOCK], chars[i][LINE]) != (chars[start][BLOCK], chars[start][LINE]):
            y0 = min(c[Y0] for c in chars[start:i])
            y1 = max(c[Y1] for c in chars[start:i])
            lines.append((y0, y1, start, i - 1))
            start = i
    return lines


def _closest_line(lines, y):
    """The (start_index, end_index) of whichever line in `lines` a given
    y most plausibly belongs to. Containment (y within a line's own
    [y0, y1]) always wins over proximity -- but critically, ALL lines are
    checked rather than stopping at the first containing match, with ties
    (including the not-uncommon case of two lines' boxes slightly
    overlapping, e.g. under tight leading) broken by closeness to each
    line's own vertical center. A y that lands in the sliver where two
    lines' boxes overlap should resolve to whichever line it's visually
    closer to the middle of, not just whichever line happens to be
    checked first."""
    best_key = None
    best_range = None
    for (ly0, ly1, start, end) in lines:
        contains = ly0 <= y <= ly1
        dist = 0.0 if contains else min(abs(y - ly0), abs(y - ly1))
        center_dist = abs(y - (ly0 + ly1) / 2)
        key = (dist, center_dist)
        if best_key is None or key < best_key:
            best_key, best_range = key, (start, end)
    return best_range


def resolve_selection_range(chars, point_a, point_b):
    """Given two PDF-space points (in either order -- a drag can go any
    direction), returns (start_index, end_index) into `chars` such that
    start_index <= end_index and the range represents forward reading
    order. Returns None if `chars` is empty."""
    idx_a = char_index_at_point(chars, *point_a)
    idx_b = char_index_at_point(chars, *point_b)
    if idx_a is None or idx_b is None:
        return None
    return (idx_a, idx_b) if idx_a <= idx_b else (idx_b, idx_a)


def word_bounds_at_index(chars, index):
    """The (start, end) index range -- inclusive -- of the word touching
    `chars[index]`, for double-click-to-select-word. A "word" is a run of
    non-whitespace characters on the same line; if the character at
    `index` is itself whitespace, returns the whitespace run instead
    (so double-clicking a gap doesn't crash or do something bizarre)."""
    if not chars:
        return None
    is_space = chars[index][CHAR].isspace()
    block_line = (chars[index][BLOCK], chars[index][LINE])

    start = index
    while start > 0 and (chars[start - 1][BLOCK], chars[start - 1][LINE]) == block_line \
            and chars[start - 1][CHAR].isspace() == is_space:
        start -= 1
    end = index
    while end < len(chars) - 1 and (chars[end + 1][BLOCK], chars[end + 1][LINE]) == block_line \
            and chars[end + 1][CHAR].isspace() == is_space:
        end += 1
    return start, end


def paragraph_bounds_at_index(chars, index):
    """The (start, end) index range -- inclusive -- of the whole paragraph
    (PyMuPDF "block") containing chars[index], for triple-click-to-select-
    paragraph. Spans every line of that block, however many it wraps to."""
    if not chars:
        return None
    block_no = chars[index][BLOCK]
    start = index
    while start > 0 and chars[start - 1][BLOCK] == block_no:
        start -= 1
    end = index
    while end < len(chars) - 1 and chars[end + 1][BLOCK] == block_no:
        end += 1
    return start, end


def selected_text(chars, start_index, end_index):
    """Reconstructs copyable text for chars[start_index:end_index+1].
    Characters are concatenated directly (spaces are already part of the
    stream), a paragraph break (block change) becomes a blank line, and a
    plain line wrap within the same paragraph gets a single joining space
    if one isn't already present. A hyphen at the very end of a line is
    treated as a word-wrap artifact -- dropped, with the word rejoined
    directly -- when the wrap doesn't cross a paragraph break and the
    next line continues in lowercase (the common heuristic for "this
    hyphen only exists because the word had to wrap here"); otherwise
    it's kept as literal text, since it's more likely a genuine hyphenated
    word or a dash that simply happened to land at a line's end."""
    selected = chars[start_index:end_index + 1]
    if not selected:
        return ""

    parts = []
    n = len(selected)
    for i, cur in enumerate(selected):
        is_last = i == n - 1
        at_line_end = is_last or (selected[i + 1][BLOCK], selected[i + 1][LINE]) != (cur[BLOCK], cur[LINE])
        at_block_end = is_last or selected[i + 1][BLOCK] != cur[BLOCK]

        if at_line_end and not is_last and cur[CHAR] in _WRAP_HYPHEN_CHARS:
            next_char = selected[i + 1][CHAR]
            if not at_block_end and next_char.isalpha() and next_char.islower():
                continue  # drop the wrap-hyphen; word continues directly, no separator

        parts.append(cur[CHAR])
        if at_line_end and not is_last:
            if at_block_end:
                parts.append("\n\n")
            elif cur[CHAR] not in (" ", "\t"):
                parts.append(" ")
    return "".join(parts)


def selection_rects(chars, start_index, end_index):
    """Bounding rects, one per line, covering chars[start_index:end_index+1]
    -- as (x0, y0, x1, y1) tuples in the same PDF-space units as `chars`.
    A line fully inside the selection naturally spans its full width
    (every character on that line is in range); the first/last line of a
    multi-line selection naturally spans only the selected portion."""
    selected = chars[start_index:end_index + 1]
    if not selected:
        return []
    rects = []
    line_start = 0
    for i in range(1, len(selected) + 1):
        if i == len(selected) or (selected[i][BLOCK], selected[i][LINE]) != \
                (selected[line_start][BLOCK], selected[line_start][LINE]):
            chunk = selected[line_start:i]
            rects.append((
                min(c[X0] for c in chunk), min(c[Y0] for c in chunk),
                max(c[X1] for c in chunk), max(c[Y1] for c in chunk),
            ))
            line_start = i
    return rects


def resolve_multi_page_selection(page_char_lists, start_page, start_point, end_page, end_point):
    """Like resolve_selection_range, but for a drag that may span up to two
    side-by-side pages (Two-Page View).

    page_char_lists: {page_index: chars} for every currently visible page.
    start_page/end_page: the page index the drag started/ended on.
    start_point/end_point: (x, y) in that respective page's own PDF
    coordinate space (not the combined image's).

    Returns a list of (page_index, start_char_index, end_char_index)
    tuples in left-to-right reading order: one entry for a same-page
    selection, or two when the drag spans both pages of a spread --
    covering everything from the start point to the end of the first
    page, then everything from the start of the second page to the end
    point. Pages with no chars (or no selectable text at all) are simply
    omitted rather than producing an empty/bogus entry.
    """
    if start_page > end_page:
        start_page, start_point, end_page, end_point = end_page, end_point, start_page, start_point

    if start_page == end_page:
        chars = page_char_lists.get(start_page, [])
        rng = resolve_selection_range(chars, start_point, end_point)
        return [(start_page, *rng)] if rng else []

    result = []
    first_chars = page_char_lists.get(start_page, [])
    if first_chars:
        rng = resolve_selection_range(first_chars, start_point, _FAR_POINT)
        if rng:
            result.append((start_page, *rng))
    last_chars = page_char_lists.get(end_page, [])
    if last_chars:
        rng = resolve_selection_range(last_chars, _NEAR_POINT, end_point)
        if rng:
            result.append((end_page, *rng))
    return result


_FAR_POINT = (10 ** 9, 10 ** 9)      # snaps to a page's very last character
_NEAR_POINT = (-10 ** 9, -10 ** 9)   # snaps to a page's very first character


def combined_selected_text(page_char_lists, page_ranges):
    """selected_text() for each (page_index, start, end) in page_ranges
    (as returned by resolve_multi_page_selection), joined with a blank
    line between pages when there's more than one."""
    parts = [
        selected_text(page_char_lists[p], s, e)
        for (p, s, e) in page_ranges
        if page_char_lists.get(p)
    ]
    return "\n\n".join(part for part in parts if part)
