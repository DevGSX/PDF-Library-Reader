# PDF Library Reader

A desktop PDF reader for Linux, built for reading books: a library view of all
your PDFs plus a reader with bookmarks, adjustable text size, dark/light mode,
and a distraction-free "simple text" reading mode.

## Features

- **Library / main menu** — every PDF you add, shown with title, file size,
  page count and last-read date.
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
  where you can edit Title, Author, Series, Language and a free-text
  Annotation, and set its reading status. Saving updates the library
  immediately. Kept off a plain click on purpose, so browsing your library
  doesn't keep popping the panel open.
- **Filename stays in sync with Title / Author / Series** — saving details
  renames the actual file on disk to `Title * Author * Series.pdf` (empty
  parts are just dropped, e.g. `Title.pdf` if there's no author or series
  yet). That way the metadata travels with the file itself — copy your
  library folder to another device and the titles/authors/series are right
  there in the filenames, no re-entering anything by hand. Illegal filename
  characters are stripped automatically, and a name that would collide with
  an existing file gets a "(2)" appended instead of overwriting it.
- **Search suggestions** — start typing in the filter box and a preview
  drops down grouping matches into **Titles**, **Authors**, and **Series**
  (e.g. typing "herbert" shows "Frank Herbert (3 books)" under Authors).
  Click any suggestion to jump straight to all matching books.
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
- **Alphabetical grouping** — in Image Preview, sorting by Title (A-Z or Z-A)
  groups covers under letter headers (A, B, C... with "#" for titles starting
  with a number or symbol), like a bookshelf sorted by author initial.
- **Bookmarks** — save a bookmark (with an optional label) on any page inside
  a book, jump back to it later, remove it when you're done.
- **Text size** — A+ / A- controls zoom in normal view and font size in
  simple text mode. Your last setting is remembered.
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
| ← / →          | Previous / next page (also works via mouse scroll, and Ctrl+scroll zooms) |
| Ctrl + =       | Increase text size / zoom in  |
| Ctrl + -       | Decrease text size / zoom out |
| Ctrl + D       | Add a bookmark on this page   |

## Book details panel

Right-click a book (its row, or its cover thumbnail) and choose **Details**
to open the panel. From there you can:
- Edit **Title**, **Author**, **Series**, **Language**, and a free-text
  **Annotation** (your own notes about the book)
- Set its **Status** directly (Unread / Reading / Finished)
- Toggle **Favorite**
- Jump straight into **Open Book**

Changes only take effect once you click **Save**. Saving also renames the
file on disk to match Title/Author/Series (see above) — if that rename
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
