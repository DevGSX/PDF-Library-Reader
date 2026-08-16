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

    PyMuPDF's own block order generally follows the PDF's content stream,
    not necessarily visual reading order -- for a normal single-column
    page these are almost always the same thing, but for a two-column
    layout (a common academic-paper style) they can genuinely differ: a
    PDF generator is free to write the right column's text before the
    left column's, and MuPDF doesn't reorder for that. So this also runs
    the result through _reorder_for_columns(), which detects a clean
    two-column split by looking for a real horizontal gap between two
    clusters of content and, only when it finds one, reorders so the
    left column reads fully before the right column. It leaves everything
    else (including ordinary single-column pages, which are the vast
    majority) completely untouched."""
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
    return _reorder_for_columns(chars)


def _merge_x_ranges(ranges):
    """Sorted, non-overlapping x-interval bands covering `ranges` (a list
    of (x0, x1) tuples) -- the classic interval-merge, used here to find
    how many distinct horizontal "clusters" of content a page's blocks
    fall into."""
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged = [list(ranges[0])]
    for (x0, x1) in ranges[1:]:
        if x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return [tuple(r) for r in merged]


def _reorder_for_columns(chars):
    """Reorders `chars` so a genuine two-column layout reads left column
    fully, then right column fully -- rather than whatever order PyMuPDF's
    blocks happen to come in. Works at the LINE level rather than the
    block level: PyMuPDF's own block grouping isn't reliably column-aware
    either -- it can lump both columns' lines into a single block even
    though each individual line's position clearly belongs to one side or
    the other -- so anchoring to blocks would miss exactly the cases that
    matter most here.

    Detection is deliberately conservative: a full-width line (like a
    title or header spanning both columns) is set aside from the
    left/right split and reinserted in its natural top-to-bottom position
    -- before the columns if it sits above them, after if it sits below.
    If the remaining lines don't cleanly separate into two clearly-gapped
    horizontal bands with real content in both, `chars` is returned
    completely unchanged: forcing a column split onto an ordinary
    single-column page (the vast majority of PDFs) would do more harm
    than good, and getting an ambiguous or genuinely more complex layout
    wrong is worse than leaving PyMuPDF's own order alone.

    A synthetic block/line numbering is assigned to the reordered output
    so downstream paragraph-break logic (in selected_text()) still makes
    sense: each of the four groups below (content above the columns, left
    column, right column, content below) always starts a fresh "block",
    with further breaks inside a group wherever the original block number
    changes -- so paragraph structure is preserved within a column even
    though PyMuPDF's own grouping didn't keep the columns apart."""
    if not chars:
        return chars

    lines = _group_into_lines(chars)  # (y0, y1, x0, x1, start, end)
    if len(lines) < 4:
        return chars

    info = []  # (y0, start, end, x0, x1, original_block_no)
    for (y0, _y1, x0, x1, s, e) in lines:
        info.append((y0, s, e, x0, x1, chars[s][BLOCK]))

    page_x0 = min(li[3] for li in info)
    page_x1 = max(li[4] for li in info)
    page_width = page_x1 - page_x0
    if page_width <= 0:
        return chars

    narrow = [li for li in info if (li[4] - li[3]) <= 0.5 * page_width]
    wide = [li for li in info if (li[4] - li[3]) > 0.5 * page_width]
    if len(narrow) < 2:
        return chars

    bands = _merge_x_ranges([(li[3], li[4]) for li in narrow])
    if len(bands) != 2:
        return chars
    (lo0, lo1), (ro0, ro1) = bands
    if ro0 - lo1 < 12:
        return chars  # not a convincing gutter -- could just be uneven paragraph widths

    left_center, right_center = (lo0 + lo1) / 2, (ro0 + ro1) / 2
    left_lines, right_lines = [], []
    for li in narrow:
        cx = (li[3] + li[4]) / 2
        (left_lines if abs(cx - left_center) <= abs(cx - right_center) else right_lines).append(li)
    if not left_lines or not right_lines:
        return chars  # everything narrow landed on one side -- not really two columns

    left_lines.sort(key=lambda li: li[0])
    right_lines.sort(key=lambda li: li[0])
    columns_top_y = min(li[0] for li in left_lines + right_lines)

    before_columns = sorted((li for li in wide if li[0] < columns_top_y), key=lambda li: li[0])
    after_columns = sorted((li for li in wide if li[0] >= columns_top_y), key=lambda li: li[0])

    new_chars = []
    new_block_no = -1
    for group in (before_columns, left_lines, right_lines, after_columns):
        prev_orig_block = object()  # always start a fresh "block" at a group boundary
        new_line_no = -1
        for (_y0, s, e, _x0, _x1, orig_block) in group:
            new_line_no += 1
            if orig_block != prev_orig_block:
                new_block_no += 1
                new_line_no = 0
                prev_orig_block = orig_block
            for i in range(s, e + 1):
                c = chars[i]
                new_chars.append((c[X0], c[Y0], c[X1], c[Y1], c[CHAR], new_block_no, new_line_no))
    return new_chars


def char_index_at_point(chars, x, y):
    """The index into `chars` that a click at PDF-space point (x, y)
    should snap to, for use as a selection endpoint. Returns None if
    `chars` is empty.

    Snaps to the closest LINE using the point's full 2D distance to each
    line's bounding box -- not just vertical distance -- since a
    two-column layout routinely has two lines (one per column) sitting at
    nearly the same y; picking by y alone would frequently resolve a
    click in one column to a line in the other. Then, within the chosen
    line, snaps to the character whose horizontal range contains the
    point, or whichever character edge is closest if the point falls in a
    gap or outside the line's own bounds.
    """
    if not chars:
        return None

    lines = _group_into_lines(chars)
    best_start, best_end = _closest_line(lines, x, y)

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
    """Returns [(y0, y1, x0, x1, start_index, end_index), ...] -- the
    bounding box and index range of each (block_no, line_no) run in
    `chars`. Assumes `chars` is already sorted in reading order."""
    lines = []
    start = 0
    for i in range(1, len(chars) + 1):
        if i == len(chars) or (chars[i][BLOCK], chars[i][LINE]) != (chars[start][BLOCK], chars[start][LINE]):
            chunk = chars[start:i]
            y0 = min(c[Y0] for c in chunk)
            y1 = max(c[Y1] for c in chunk)
            x0 = min(c[X0] for c in chunk)
            x1 = max(c[X1] for c in chunk)
            lines.append((y0, y1, x0, x1, start, i - 1))
            start = i
    return lines


def _closest_line(lines, x, y):
    """The (start_index, end_index) of whichever line in `lines` a given
    point (x, y) most plausibly belongs to, using the point's actual 2D
    distance to each line's bounding box (0 if the point falls inside it)
    as the primary criterion -- not vertical distance alone. This is what
    makes selecting within one column of a multi-column layout reliable:
    two lines from different columns routinely sit at nearly the same y
    (rows naturally line up across columns in a real 2-column document),
    so a click squarely inside one column's line must not lose out to the
    other column's same-row line just because their y-centers happen to
    be marginally closer -- the horizontal distance has to count too.
    Ties (both lines equally close in 2D, e.g. two vertically-overlapping
    lines in the SAME column under tight leading) are broken by closeness
    to each line's own vertical center, same as before."""
    best_key = None
    best_range = None
    for (ly0, ly1, lx0, lx1, start, end) in lines:
        dx = max(lx0 - x, 0.0, x - lx1)
        dy = max(ly0 - y, 0.0, y - ly1)
        dist_sq = dx * dx + dy * dy
        center_dist = abs(y - (ly0 + ly1) / 2)
        key = (dist_sq, center_dist)
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
