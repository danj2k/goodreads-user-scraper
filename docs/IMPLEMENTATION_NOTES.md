# Implementation Notes

## Exclusive shelf detection

Goodreads classifies certain shelves as "exclusive" (read, to-read, currently-reading, did-not-finish). A book can only belong to one exclusive shelf at a time. The detection works by examining `<li>` elements in the `&print=true` shelf page's `<ul class="shelves">` list: those with class `exclusive` identify exclusive shelves.

Detection happens inside `collect_shelf_rows` on the first page of each shelf, which avoids a redundant re-fetch (the same `<ul class="shelves">` is present on every page). The sets from all shelves are merged in `get_all_shelves` after collection completes.

The `exclusive_shelf` value written to each book's JSON is derived from the intersection of the book's actual shelves and the exclusive shelf set, taking the first alphabetically when there's ambiguity.

## Shelf row extraction

Shelf pages are HTML tables. Book IDs are extracted from the "title" column's `<a>` href. Ratings come from the `data-rating` attribute on a `div.stars` element (0 means unrated, stored as `None`). Dates are extracted from `div.date_row` elements within the "date_read" column, filtering out "not set" entries.

## Deduplication across shelves

Books appear on multiple shelves (e.g., "read" and "fiction"). The `_dedupe_books` function deduplicates by book ID, merging shelf lists. The first occurrence's rating and read dates are kept; subsequent occurrences only add new shelf names. This is safe because rating and read dates are the same regardless of which shelf the row was extracted from.

Error handling during deduplication catches only `ElementNotFound` (from `scraper.parse`). A shelf row with missing expected DOM elements is skipped silently — this is a known possibility when Goodreads serves slightly different HTML for some books. Any other exception (`AssertionError`, `TypeError`, etc.) indicates a programming bug and is allowed to propagate.

## Incremental book updates

When a book's JSON file already exists, `process_book` reads it and only appends new shelf names from the current shelf data. The book's detailed metadata (title, description, genres, etc.) is not re-fetched. This means metadata changes on Goodreads won't be reflected without deleting the book file first.

## Scrapling logging redirect

Scrapling logs verbosely to stderr by default. The `_redirect_scrapling_logging` function removes StreamHandlers from the "scrapling" logger and routes output depending on mode:

- **Interactive mode** (default): adds a FileHandler writing to `scrapling_fetch.log`. This keeps the user's terminal clean while preserving debug information for troubleshooting.
- **Quiet mode** (`--quiet`): adds a StreamHandler writing to stdout with a timestamped format (`%(asctime)s %(name)s %(levelname)s: %(message)s`). This ensures scrapling's logs are captured by whatever redirection is used (e.g. cron output capture).

## Output abstraction module

The `scraper/output.py` module provides a thin abstraction over terminal output, selected at startup via `output.init(quiet=...)`. It exposes:

- `log()`, `log_info()`, `log_warn()`, `log_error()` — plain-text messages in quiet mode (with `[INFO]`/`[WARN]`/`[ERROR]` prefixes), rich-styled messages in interactive mode.
- `status(msg)` — context manager; yields immediately in quiet mode (after printing one log line), shows a rich spinner in interactive mode.
- `Progress(description, total)` — context manager; simple counter in quiet mode, rich progress bar with spinner in interactive mode.

This module is imported by `__main__.py`, `user.py`, and `shelves.py`. In quiet mode, no *rich* objects are created, so the entire rich dependency is effectively unused — making the output safe for piping to files, cron logs, or other non-terminal consumers.

## Scrapling `.text` vs BeautifulSoup `.text`

During the conversion from BeautifulSoup to scrapling, a subtle difference in `.text` behaviour was discovered. BeautifulSoup's `.text` recursively concatenates all descendant text nodes. Scrapling's `Selector.text` only returns the element's *direct* text (the first text node), which is empty when content lives inside child tags.

The `get_text()` helper in `scraper/parse.py` bridges this gap by delegating to lxml's `text_content()`, which recursively collects all text — matching the BeautifulSoup behaviour that the parser functions depend on. It is used in `get_description` (books.py), `get_author_description` (author.py), and `get_dates_read` (shelves.py) — the three places where elements contain nested markup. All other `.text` usages in the codebase are on leaf elements (text-only spans, headings, etc.) where scrapling's `.text` works correctly.
