# Implementation Notes

## SQLite database schema

The database uses WAL journal mode for better concurrent read performance and foreign key constraints. Six tables:

- **`users`** — PK `user_id`. Stores profile stats (name, rating count, average, review count).
- **`authors`** — PK `author_id`. Stores author metadata (name, description, image).
- **`books`** — PK `book_id` (numeric prefix only, e.g., "211721806"). FK `author_id → authors`. Stores full book metadata plus the user's `rating`, `exclusive_shelf`, and `book_id_title` (the full slug for reference).
- **`book_shelves`** — Composite PK `(book_id, shelf_name)`. Replaced wholesale on each upsert (not appended).
- **`book_dates_read`** — Composite PK `(book_id, date_read)`. Replaced wholesale on each upsert.
- **`book_genres`** — Composite PK `(book_id, genre)`. Replaced wholesale on each upsert.

All child tables (`book_shelves`, `book_dates_read`, `book_genres`) are deleted and re-inserted on every upsert. This avoids complex diffing logic and is fast for the typical case (< 20 shelves, < 10 dates, < 15 genres per book).

## Incremental update logic

The `needs_scrape()` function in `db.py` is the core of the incremental optimization. It compares three fields:

1. **Shelf membership** — set comparison (`book_shelves` table vs. current shelf list from `_dedupe_books`). Order-independent.
2. **User rating** — integer comparison (`books.rating` vs. current rating from shelf row).
3. **Read dates** — list comparison (`book_dates_read` table vs. current dates from shelf row). Order-dependent (chronological order matters).

If all three match, the book is skipped entirely — no HTTP request, no scraping. This is the fast path for subsequent runs.

If any field changed but the book already exists in the DB, `update_book_shelf()` updates only the shelf-related fields (rating, shelves, dates) without touching book metadata (title, description, genres, etc.). This is a fast DB-only operation.

If the book is new (not in the DB), the full `scrape_book()` is called and the complete record is inserted via `upsert_book()`.

## Exclusive shelf detection

Goodreads classifies certain shelves as "exclusive" (read, to-read, currently-reading, did-not-finish). A book can only belong to one exclusive shelf at a time. The detection works by examining `<li>` elements in the `&print=true` shelf page's `<ul class="shelves">` list: those with class `exclusive` identify exclusive shelves.

Detection happens inside `collect_shelf_rows` on the first page of each shelf, which avoids a redundant re-fetch (the same `<ul class="shelves">` is present on every page). The sets from all shelves are merged in `get_all_shelves` after collection completes.

The `exclusive_shelf` value written to each book is derived from the intersection of the book's actual shelves and the exclusive shelf set, taking the first alphabetically when there's ambiguity.

## Shelf row extraction

Shelf pages are HTML tables. Book IDs are extracted from the "title" column's `<a>` href. Ratings come from the `data-rating` attribute on a `div.stars` element (0 means unrated, stored as `None`). Dates are extracted from `div.date_row` elements within the "date_read" column, filtering out "not set" entries.

## Book ID normalisation

Shelf pages produce full slug IDs (e.g., `211721806-dungeon-crawler-carl`) from the `<a>` href. Book pages and the database use just the numeric prefix (`211721806`). The `_normalize_book_id()` helper in `shelves.py` extracts the numeric portion during deduplication, applied inside `_dedupe_books()` so all downstream code (DB lookups, JSON filenames, scrape URLs) uses the short format consistently.

## Deduplication across shelves

Books appear on multiple shelves (e.g., "read" and "fiction"). The `_dedupe_books` function deduplicates by normalised book ID, merging shelf lists. The first occurrence's rating and read dates are kept; subsequent occurrences only add new shelf names. This is safe because rating and read dates are the same regardless of which shelf the row was extracted from.

Error handling during deduplication catches only `ElementNotFound` (from `scraper.parse`). A shelf row with missing expected DOM elements is skipped silently — this is a known possibility when Goodreads serves slightly different HTML for some books. Any other exception (`AssertionError`, `TypeError`, etc.) indicates a programming bug and is allowed to propagate.

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

## Concurrency control

Both `asyncio.gather` calls in `get_all_shelves()` — shelf collection and book scraping — are wrapped with an `asyncio.Semaphore(_CONCURRENCY)` (default 5). This caps the number of simultaneous Playwright browser fetches. Each fetch opens its own browser page, which consumes significant memory (tens of MB per page). Without the semaphore, a user with 400 books would open 400 pages simultaneously, causing multi-GB RSS growth.

The semaphore is shared across both phases (shelf collection and book processing) by reusing the same instance. With 5 concurrent fetches, the scrape proceeds at a manageable rate while keeping memory bounded. The constant `_CONCURRENCY` in `shelves.py` can be tuned without code changes.

## Playwright timeout handling

The retry loop in `http.get_soup()` catches transient errors to retry with exponential back-off. The original catch list was `(TimeoutError, ConnectionError, OSError)`. However, Playwright raises its own `playwright.async_api.TimeoutError` (e.g. "Page.goto: Timeout 30000ms exceeded"), which is *not* a subclass of Python's built-in `TimeoutError`. Without catching it explicitly, a Playwright timeout would escape the retry loop, propagate up through `scrape_book()`, and be caught by the broad `except Exception` in `process_book()` — leaving the Playwright page open without proper session cleanup.

The fix imports `playwright.async_api.TimeoutError` as `_PlaywrightTimeoutError` (with a graceful `ImportError` fallback for environments where Playwright isn't installed) and catches `_TIMEOUT_ERRORS = (TimeoutError, PlaywrightTimeoutError, ConnectionError, OSError)`.
