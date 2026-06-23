# Known Issues

## Resolved

### 1. Broad exception swallowing in deduplication
Narrowed `except Exception` to `except ElementNotFound` in `_dedupe_books` (shelves.py). Programming bugs (`AssertionError`, `TypeError`, etc.) now propagate instead of being silently swallowed.

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
