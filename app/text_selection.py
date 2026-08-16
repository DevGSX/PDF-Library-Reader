"""Reading-order text selection over a rendered PDF page.

The naive approach -- "grab whatever text falls inside the drag
rectangle" (PyMuPDF's page.get_textbox(rect)) -- looks reasonable but is
wrong for anything but a single-line selection: dragging from the middle
of one line to the middle of a line several lines down only grabs text
whose word boxes happen to fall within that rectangle's left/right
bounds, silently dropping the rest of every line in between. Real text
selection follows *reading order*: from the start point to the end of
its line, all of every line in between in full, then from the start of
the last line to the end point.

Everything here is plain data in, plain data out -- no Qt dependency --
so the actual selection logic can be unit tested against synthetic word
lists without a running GUI or real mouse events.

`words` throughout is PyMuPDF's page.get_text("words") output: a list of
(x0, y0, x1, y1, text, block_no, line_no, word_no) tuples, already sorted
in reading order (block, then line, then word position).
"""

X0, Y0, X1, Y1, TEXT, BLOCK, LINE, WORD = range(8)


def word_index_at_point(words, x, y):
    """The index into `words` that a click at PDF-space point (x, y)
    should snap to, for use as a selection endpoint. Returns None if
    `words` is empty.

    Snaps to the closest LINE by vertical distance (so clicking above the
    first line or below the last still gives a sensible answer), then
    within that line, to the word whose horizontal range contains the
    point, or whichever word edge is closest if the point falls in the
    gap between two words or outside the line's own bounds.
    """
    if not words:
        return None

    lines = _group_into_lines(words)

    best_start, best_end, best_dist = None, None, None
    for (ly0, ly1, start, end) in lines:
        if ly0 <= y <= ly1:
            best_start, best_end = start, end
            break
        dist = min(abs(y - ly0), abs(y - ly1))
        if best_dist is None or dist < best_dist:
            best_dist, best_start, best_end = dist, start, end

    for i in range(best_start, best_end + 1):
        w = words[i]
        if w[X0] <= x <= w[X1]:
            return i

    if x <= words[best_start][X0]:
        return best_start
    if x >= words[best_end][X1]:
        return best_end
    for i in range(best_start, best_end):
        if words[i][X1] <= x <= words[i + 1][X0]:
            return i if (x - words[i][X1]) <= (words[i + 1][X0] - x) else i + 1
    return best_end  # pragma: no cover -- defensive fallback, shouldn't be reachable


def _group_into_lines(words):
    """Returns [(y0, y1, start_index, end_index), ...] -- the vertical
    span and word-index range of each (block_no, line_no) run in `words`.
    Assumes `words` is already sorted in reading order."""
    lines = []
    start = 0
    for i in range(1, len(words) + 1):
        if i == len(words) or (words[i][BLOCK], words[i][LINE]) != (words[start][BLOCK], words[start][LINE]):
            y0 = min(w[Y0] for w in words[start:i])
            y1 = max(w[Y1] for w in words[start:i])
            lines.append((y0, y1, start, i - 1))
            start = i
    return lines


def resolve_selection_range(words, point_a, point_b):
    """Given two PDF-space points (in either order -- a drag can go any
    direction), returns (start_index, end_index) into `words` such that
    start_index <= end_index and the range represents forward reading
    order. Returns None if `words` is empty."""
    idx_a = word_index_at_point(words, *point_a)
    idx_b = word_index_at_point(words, *point_b)
    if idx_a is None or idx_b is None:
        return None
    return (idx_a, idx_b) if idx_a <= idx_b else (idx_b, idx_a)


def selected_text(words, start_index, end_index):
    """Reconstructs readable text for words[start_index:end_index+1]:
    words on the same line joined with a single space, a wrapped line
    within the same paragraph (block) also joined with just a space (so
    copied text isn't broken mid-sentence), and a blank line inserted
    between different blocks/paragraphs."""
    selected = words[start_index:end_index + 1]
    if not selected:
        return ""
    parts = [selected[0][TEXT]]
    for prev, cur in zip(selected, selected[1:]):
        if prev[BLOCK] != cur[BLOCK]:
            parts.append("\n\n" + cur[TEXT])
        else:
            parts.append(" " + cur[TEXT])
    return "".join(parts)


def resolve_multi_page_selection(page_word_lists, start_page, start_point, end_page, end_point):
    """Like resolve_selection_range, but for a drag that may span up to two
    side-by-side pages (Two-Page View). This is where the old
    implementation actually broke: it always used the left page's words
    and coordinates, even for a selection made entirely on the right page.

    page_word_lists: {page_index: words} for every currently visible page.
    start_page/end_page: the page index the drag started/ended on.
    start_point/end_point: (x, y) in that respective page's own PDF
    coordinate space (not the combined image's).

    Returns a list of (page_index, start_word_index, end_word_index)
    tuples in left-to-right reading order: one entry for a same-page
    selection, or two when the drag spans both pages of a spread --
    covering everything from the start point to the end of the first
    page, then everything from the start of the second page to the end
    point. Pages with no words (or no selectable text at all) are simply
    omitted rather than producing an empty/bogus entry.
    """
    if start_page > end_page:
        start_page, start_point, end_page, end_point = end_page, end_point, start_page, start_point

    if start_page == end_page:
        words = page_word_lists.get(start_page, [])
        rng = resolve_selection_range(words, start_point, end_point)
        return [(start_page, *rng)] if rng else []

    result = []
    first_words = page_word_lists.get(start_page, [])
    if first_words:
        rng = resolve_selection_range(first_words, start_point, _FAR_POINT)
        if rng:
            result.append((start_page, *rng))
    last_words = page_word_lists.get(end_page, [])
    if last_words:
        rng = resolve_selection_range(last_words, _NEAR_POINT, end_point)
        if rng:
            result.append((end_page, *rng))
    return result


_FAR_POINT = (10 ** 9, 10 ** 9)    # snaps to a page's very last word
_NEAR_POINT = (-10 ** 9, -10 ** 9)  # snaps to a page's very first word


def combined_selected_text(page_word_lists, page_ranges):
    """selected_text() for each (page_index, start, end) in page_ranges
    (as returned by resolve_multi_page_selection), joined with a blank
    line between pages when there's more than one."""
    parts = [
        selected_text(page_word_lists[p], s, e)
        for (p, s, e) in page_ranges
        if page_word_lists.get(p)
    ]
    return "\n\n".join(part for part in parts if part)

def selection_rects(words, start_index, end_index):
    """Bounding rects, one per line, covering words[start_index:end_index+1]
    -- as (x0, y0, x1, y1) tuples in the same PDF-space units as `words`.
    A line fully inside the selection naturally spans its full width
    (every word on that line is in range); the first/last line of a
    multi-line selection naturally spans only the selected portion, since
    only the selected words on that line are included in the range."""
    selected = words[start_index:end_index + 1]
    if not selected:
        return []
    rects = []
    line_start = 0
    for i in range(1, len(selected) + 1):
        if i == len(selected) or (selected[i][BLOCK], selected[i][LINE]) != \
                (selected[line_start][BLOCK], selected[line_start][LINE]):
            chunk = selected[line_start:i]
            rects.append((
                min(w[X0] for w in chunk), min(w[Y0] for w in chunk),
                max(w[X1] for w in chunk), max(w[Y1] for w in chunk),
            ))
            line_start = i
    return rects
