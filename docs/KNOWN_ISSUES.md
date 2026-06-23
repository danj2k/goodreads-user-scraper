# Known Issues

## Bugs

### 1. Broad exception swallowing in deduplication (shelves.py, line 141)

In `_dedupe_books`, the `except Exception: continue` silently discards all errors when parsing a shelf row — including unexpected bugs like `TypeError`, `KeyError`, or `ImportError`. Only `ElementNotFound` (from missing expected DOM elements) should be caught here.

**Fix:** Narrow to `except (ElementNotFound, AssertionError, AttributeError):` or similar.

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
