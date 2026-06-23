# Known Issues

## Resolved

### 1. Broad exception swallowing in deduplication
Narrowed `except Exception` to `except ElementNotFound` in `_dedupe_books` (shelves.py). Programming bugs (`AssertionError`, `TypeError`, etc.) now propagate instead of being silently swallowed.

### 2. Scrapling `.text` returning empty for nested content
The BS4→scrapling conversion introduced a latent bug: scrapling's `.text` only returns direct text content (first text node), which is empty for elements with nested tags like `<b>` or `<span>`. Fixed by adding `get_text()` helper in `parse.py` (delegates to lxml's `text_content()`). Affected functions: `get_description` (books.py), `get_author_description` (author.py), `get_dates_read` (shelves.py).

### 3. Test suite broken by scrapling conversion
All 100 tests now pass after converting the test infrastructure from BeautifulSoup to scrapling:
- `conftest.py`: fixture helper now returns `Selector` objects, `mock_get_soup` accepts `stealthy` kwarg
- `test_parse.py`: uses `Selector(content=html)` instead of `BeautifulSoup`
- `test_http.py`: fake session is now async, `_FakeResponse.css()` returns `.first`-compatible stub, fixed 404 test to expect `FetchError`
- `test_shelves.py`: `_make_row` wraps cells in `<tr>`, uses children iteration instead of `find_all(recursive=False)`
- `test_author.py` / `test_books.py`: fake functions accept `**kwargs` for `stealthy` parameter

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
