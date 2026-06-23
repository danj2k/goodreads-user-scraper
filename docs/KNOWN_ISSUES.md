# Known Issues

## Bugs

### 1. Redundant HTTP requests for exclusive shelf detection (shelves.py, lines 222–231)

After `collect_shelf_rows` has already fetched all shelf pages, `get_all_shelves` re-fetches a shelf page solely to detect exclusive shelves. This causes every book to be fetched twice from the same shelf URL (once in `collect_shelf_rows`, once here). It wastes bandwidth and risks triggering rate limits.

**Fix:** The exclusive shelf info is already present in the pages fetched by `collect_shelf_rows`. Either capture it there, or detect exclusives from the first page of the first non-empty shelf during the initial collection pass.

### 2. Broad exception swallowing in deduplication (shelves.py, line 130)

In `_dedupe_books`, the `except Exception: continue` silently discards all errors when parsing a shelf row — including unexpected bugs like `TypeError`, `KeyError`, or `ImportError`. Only `ElementNotFound` (from missing expected DOM elements) should be caught here.

**Fix:** Narrow to `except (ElementNotFound, AssertionError, AttributeError):` or similar.

### 3. `get_html()` in http.py is unused

The `get_html()` function (line 162) is defined but never called by any module. It parses HTML into a `Selector` (via `get_soup`) and then immediately returns the raw string — wasting the parsing work.

**Fix:** Remove it, or rewrite to fetch raw HTML directly without parsing.

## Limitations

### Incremental updates don't refresh metadata

Once a book's JSON file exists, `process_book` only updates shelf assignments. Changes to book metadata (title, description, rating, etc.) on Goodreads are not detected. Users must delete the book file to force a re-fetch.

### No review content

The tool extracts read dates, ratings, and shelf assignments but does not scrape the text of user reviews.

### Fragile to Goodreads redesigns

All CSS selectors and data-testid attributes are hardcoded to Goodreads' current HTML structure. A site redesign will break scraping until selectors are updated.

### Cookie expires silently

If the session cookie expires mid-run, subsequent book/author fetches will fail with `AuthError`. There is no proactive cookie validation at startup — the error surfaces only when a protected page is fetched.

### Concurrent requests not bounded

`asyncio.gather` is used for both shelf collection and book processing with no concurrency limit. With hundreds of books, this can overwhelm Goodreads or the local browser, leading to timeouts and rate limiting. A semaphore-based concurrency cap would help.
