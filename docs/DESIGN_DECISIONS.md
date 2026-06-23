# Design Decisions

## Two browser sessions (dynamic + stealthy)

Goodreads applies different levels of bot protection to different page types. Shelf list pages (the `&print=true` view) do not trigger anti-bot measures, so they use a lighter-weight `AsyncDynamicSession`. Individual book and author pages do trigger protection, requiring `AsyncStealthySession` with fingerprint spoofing and Cloudflare bypass. Using two sessions avoids paying the stealth overhead for pages that don't need it.

## SQLite database as default storage

Data is stored in a SQLite database by default (`--db goodreads-library.db`). This was chosen because:

- **Incremental updates**: The database enables a fast-path check — after cheap shelf-page extraction, `needs_scrape()` compares shelf membership, rating, and read dates against the DB. Unchanged books are skipped entirely (no expensive HTTP fetch). This reduces subsequent run times from hours to minutes for large libraries.
- **Single-file export**: One `.db` file instead of thousands of small JSON files. Easier to back up, transfer, and query.
- **Relational integrity**: Foreign keys between books and authors, many-to-many shelves and genres, enforced by the database.
- **Query flexibility**: Users can write SQL queries against their library (e.g., "show all 5-star books in the Fantasy genre read in 2025").

JSON output remains available via `--db ""` for backward compatibility and tooling that expects the original file structure.

### Incremental update strategy

The three fields compared during incremental checks are exactly the ones that shelf-page extraction can produce: shelf membership, user rating, and read dates. Book metadata (title, description, genres, etc.) is *not* compared — it's only set during the expensive page scrape. This means:

- A book moved between shelves → fast DB update (no HTTP)
- A user re-rating a book → fast DB update (no HTTP)
- A book's description changing on Goodreads → not detected (requires deleting the book row to force re-scrape)

### Book ID normalisation

Shelf pages use full slug IDs (e.g., `211721806-dungeon-crawler-carl`) while book pages and the database use just the numeric prefix (`211721806`). The `_normalize_book_id()` helper in `shelves.py` extracts the numeric portion during deduplication, keeping all downstream code (DB lookups, JSON filenames, scrape URLs) consistent.

### Author upsert before book upsert

When inserting a new book, the author record is upserted first to satisfy the `FOREIGN KEY` constraint on `books.author_id`. This ordering is enforced in `_process_book_db()`.

## Print-view shelf pages (`&print=true`)

The shelf list pages are fetched with `&print=true` because the print-view provides a clean HTML table of books per shelf, with shelf metadata (exclusive flags) embedded in the page. This avoids parsing the more complex interactive shelf UI.

## Shared task cache for authors

Multiple books can reference the same author. The `_tasks` dict in `author.py` ensures that if several books trigger author scraping concurrently, only one HTTP request is made per author. Failed tasks are evicted from the cache to allow retries.

## Cookie as optional requirement

Shelf data requires authentication, but the tool can still scrape a public profile without a cookie. The cookie is resolved from three sources in priority order: `--cookie` flag, `GOODREADS_COOKIE` env var, `--cookie_file` path. This layered approach supports both interactive use and CI/automation.

## Retry with jittered exponential back-off

Rate limiting from Goodreads is handled with up to 4 retries, exponential back-off with random jitter (0 to `BACKOFF_BASE * 2^attempt` seconds, capped at 30s), and respect for server-sent `Retry-After` headers. The jitter prevents thundering-herd retries when scraping many books concurrently.

## Output abstraction via `scraper/output.py`

Rather than scattering `if quiet:` checks across every module, a single `output.py` module centralises all terminal output. Each module calls `output.log_info()`, `output.status()`, or `output.Progress()` instead of using `rich.console.Console` directly.

Alternatives considered:
- **Passing a `Console` object through the call chain**: requires threading a parameter through every function, pollutes signatures, and still needs conditional logic for quiet mode.
- **Python `logging` module for scraper messages**: would change the output format and make progress bars awkward. The scraper's own messages are simple print statements, not log events.
- **Conditional rich imports at each call site**: duplicates the mode check everywhere and makes it easy to accidentally create a rich Console in quiet mode (which would emit ANSI escapes into a pipe).

The current approach means `rich` is only imported in interactive mode, quiet output contains no ANSI escapes, and adding new output sites requires a single well-known function call.
