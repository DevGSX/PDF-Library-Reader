# PDF Library Reader

A desktop PDF reader for Linux, built for reading books: a library view of all
your PDFs plus a reader with bookmarks, adjustable text size, dark/light mode,
and a distraction-free "simple text" reading mode.

## Features

- **Library / main menu** — every PDF you add, shown with title, file size,
  page count and last-read date.
- **Title comes from the filename, not the PDF's internal metadata** — when
  you add a book, its Title (and Author/Series/Genre, if present) are read
  from the filename itself, e.g. adding a file named
  `Dune * Frank Herbert * Dune Saga * Science Fiction.pdf` fills in all four
  fields automatically. A plain filename with no `*` separators is used as
  the title as-is. Either way, the PDF's own embedded metadata is ignored,
  since it's often unreliable — many tools stamp it with whatever the
  document's first heading happened to be, not the actual book title.
  Re-scanning a folder you've already added never overwrites metadata you
  edited by hand.
- **Two library views** — **Simple Text**, the detailed list (title, size,
  page count, last read), and **Image Preview**, a grid of page-1 thumbnails
  like a bookshelf. Thumbnails are generated once and cached to disk, so
  later visits load instantly. In Image Preview, double-click a cover to
  open it, or right-click for Open / Toggle Favorite / Remove.
- **Search Text in Library** — searches the actual text content of every
  book, not just titles. Runs in the background so the app stays responsive,
  shows progress while it scans, and lists every match with the book title,
  page number and a snippet of surrounding text. Double-click a result to
  jump straight to that page in that book.
- **Sort / filter** — Title (A-Z / Z-A), Recently Read, or File Size
  (largest/smallest first), plus a live filter box that matches titles (use
  "Search Text" instead to search inside books).
- **Favorites** — star any book; switch to a "Favorites only" view with one
  click.
- **Book details** — right-click a book (its row in Simple Text view, or its
  cover in Image Preview) and choose **Details** to open a preview panel
  where you can edit Title, Author, Series, Genre, Language and a free-text
  Annotation, and set its reading status. Saving updates the library
  immediately. Kept off a plain click on purpose, so browsing your library
  doesn't keep popping the panel open.
- **Filename stays in sync with Title / Author / Series / Genre** — saving
  details renames the actual file on disk to
  `Title * Author * Series * Genre.pdf` (empty parts are just dropped, e.g.
  `Title.pdf` if there's no author/series/genre yet). That way the metadata
  travels with the file itself — copy your library folder to another device
  and the titles/authors/series/genres are right there in the filenames, no
  re-entering anything by hand. Illegal filename characters are stripped
  automatically, and a name that would collide with an existing file gets a
  "(2)" appended instead of overwriting it.
- **Search suggestions** — start typing in the filter box and a preview
  drops down grouping matches into **Titles**, **Authors**, **Series**, and
  **Genres** (e.g. typing "herbert" shows "Frank Herbert (3 books)" under
  Authors). Click any suggestion to jump straight to all matching books.
- **Hover highlight** — hovering a book (its row in Simple Text view, or its
  cover in Image Preview) shows a light blue tint and outline around it.
- **Favorites get a corner star** — a gold star badge appears in the
  bottom-right corner of a favorited book's cover in Image Preview, so
  favorites are visible at a glance without opening anything.
- **Reading status** — opening a book automatically marks it "Reading"; mark
  it "Finished" from the reader toolbar or the details panel. Both statuses
  render the same way: a colored banner across the top of the cover in Image
  Preview (blue "READING" / green "FINISHED"), and a matching chip next to
  the title in Simple Text view.
- **Status filter** — a "Status" dropdown next to the filter box narrows the
  library to None (no filter), Currently Reading, Finished, or Unread —
  combinable with Favorites and the title filter.
- **Alphabetical grouping with a jump-to-letter bar** — in Image Preview,
  sorting by Title (A-Z or Z-A) groups covers under letter headers (A, B,
  C... with "#" for titles starting with a number or symbol), with a
  clickable A-Z index strip pinned above the grid so you can jump straight
  to any letter. Letters with matching books are clickable; letters with
  nothing yet are grayed out. The bar only appears while sorted
  alphabetically.
- **Pagination** — for the non-alphabetical sorts (Recently Read, Oldest
  Read, File Size Largest/Smallest), a "Per page" dropdown next to the sort
  box lets you split the list into pages of 10/25/50/100 instead of showing
  everything at once, with Previous/Next navigation at the bottom. Defaults
  to "All" (today's behavior); not available for Title sort, which uses the
  A-Z index instead. The page resets to 1 whenever you change the search,
  filters, sort, or category, so you never land on an empty page.
- **Categories** — organize your library into your own custom categories,
  shown in a sidebar on the left with a live book count for each (and a
  star for ones you've favorited). Selecting **All Books (None)** shows
  everything as normal; selecting a category filters the list to just its
  books. Right-click a category to **Add Books...** — search by **Title**
  to add one specific book, or by **Author**/**Series** to add every
  matching book at once, with a **Text** / **Image Preview** toggle so title
  matches can show as cover thumbnails — or right-click a category to
  favorite, rename, or delete it (deleting a category never deletes the
  books themselves). Turn on **Select** in the toolbar to multi-select books
  (click to select, click again to deselect, or click empty space to clear
  the whole selection); with Select off, clicking a book does nothing, so
  you can browse normally without ever selecting one by accident. While
  selected, right-click any selected book to add the whole selection to a
  category, or remove them all from the library at once — works in both
  Simple Text and Image Preview. The selection automatically clears itself
  once you've added the books to a category, so it's ready for the next
  thing without an extra click.
- **Bookmarks** — save a bookmark (with an optional label) on any page inside
  a book, jump back to it later, remove it when you're done. The panel has
  its own "Bookmarks" toggle button next to "+ Bookmark" in the toolbar, so
  if you close the panel with its own [x] button, that same toggle brings it
  right back.
- **Text size** — A+ / A- controls zoom in normal view and font size in
  simple text mode. Your last setting is remembered.
- **Click-and-drag panning** — when you've zoomed in past what fits the
  window, left-click and drag the page to move around it, like a normal
  image viewer. The cursor shows an open hand when a page can be panned, and
  a closed hand while actively dragging. Disabled in Simple Text mode (there's
  nothing to pan — text just wraps to fit).
- **Scroll-to-change-page only when it's safe to** — plain mouse scroll turns
  the page while "Fit to Screen" is on, or in Simple Text mode once you hit
  the top/bottom edge. The moment you zoom in manually, plain scroll only
  pans around the page — it never flips pages by accident anymore. Hold the
  **middle mouse button** while scrolling to explicitly turn the page even
  while zoomed in.
- **Fit to Screen** — on by default. Each page is automatically scaled to
  fill the window, recalculated per page, so pages of different sizes within
  the same book (tall, wide, mixed scans...) all display at a sensible size
  without you doing anything. Click A+ / A- at any time to take manual
  control of the zoom instead; click "Fit to Screen" again to go back to
  automatic.
- **Dark Mode and Dark Pages are independent** — "Dark Mode" is the app's own
  theme (toolbars, menus, text mode). A separate "Dark Pages" toggle inverts
  the colors of the rendered page for a proper night-reading mode. Mix and
  match: dark app with normal pages, light app with inverted (dark) pages,
  both, or neither — whatever's comfortable.
- **Simple text mode** — strips away the page layout and shows just the
  extracted text of the page, reflowed to your chosen font size — good for
  text-heavy books, bad for pages that are mostly images/diagrams.
- **Reading progress** — automatically remembers the last page you were on
  for each book, so "Open" picks up where you left off.

## Requirements

- Linux with a desktop environment (X11 or Wayland)
- Python 3.9+

## Install

```bash
chmod +x install.sh   # if it isn't already executable
./install.sh
```

This creates a `.venv` virtual environment in this folder, installs the two
dependencies (PySide6 for the UI, PyMuPDF for PDF rendering), and adds a
"PDF Library Reader" entry to your applications menu.

## Run

Either launch it from your applications menu, or:

```bash
./run.sh
```

## Uninstall

```bash
rm -rf .venv run.sh
rm ~/.local/share/applications/pdf-library-reader.desktop
```

Your library database (list of books, bookmarks, favorites, reading
progress) lives separately at `~/.local/share/pdf-library-reader/library.db`,
and cached cover thumbnails live at
`~/.local/share/pdf-library-reader/thumbnails/` — delete these too if you
want a completely clean slate. Removing a book from the library never
deletes the underlying PDF file.

## Keyboard shortcuts (inside a book)

| Shortcut       | Action                        |
|----------------|--------------------------------|
| ← / →          | Previous / next page          |
| Scroll         | Turn page (when Fit to Screen is on) or pan (when zoomed in) |
| Middle-click + Scroll | Turn page even while zoomed in |
| Ctrl + Scroll  | Zoom in/out                   |
| Ctrl + =       | Increase text size / zoom in  |
| Ctrl + -       | Decrease text size / zoom out |
| Ctrl + D       | Add a bookmark on this page   |
| Click + drag   | Pan around a zoomed-in page   |

## Book details panel

Right-click a book (its row, or its cover thumbnail) and choose **Details**
to open the panel. From there you can:
- Edit **Title**, **Author**, **Series**, **Genre**, **Language**, and a
  free-text **Annotation** (your own notes about the book)
- Set its **Status** directly (Unread / Reading / Finished)
- Toggle **Favorite**
- Jump straight into **Open Book**

Changes only take effect once you click **Save**. Saving also renames the
file on disk to match Title/Author/Series/Genre (see above) — if that rename
fails for some reason (e.g. the file was moved externally), your details
are still saved and you'll get a warning explaining the file itself
couldn't be renamed.

## Notes / limitations

- Dark mode's page inversion is a simple full-page color invert (the common
  "night mode" trick). It looks great for text pages; photos or heavily
  colored pages will look inverted too, not color-corrected.
- Simple text mode works page-by-page, extracting whatever text PyMuPDF can
  find on that page. Scanned/image-only PDFs won't have extractable text.
- "Search Text in Library" opens and scans every book on demand (it doesn't
  keep a permanent search index), so the first search after adding a lot of
  books may take a few seconds. Scanned/image-only PDFs won't have any
  searchable text, same as with simple text mode.
- The app doesn't modify your PDF files — bookmarks, favorites and reading
  progress are stored separately in the local database, not written into the
  files themselves.
