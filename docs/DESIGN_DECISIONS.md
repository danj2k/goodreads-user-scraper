# Design Decisions

## Two browser sessions (dynamic + stealthy)

Goodreads applies different levels of bot protection to different page types. Shelf list pages (the `&print=true` view) do not trigger anti-bot measures, so they use a lighter-weight `AsyncDynamicSession`. Individual book and author pages do trigger protection, requiring `AsyncStealthySession` with fingerprint spoofing and Cloudflare bypass. Using two sessions avoids paying the stealth overhead for pages that don't need it.

## Per-entity JSON files instead of one large export

Each book gets its own `books/<id>.json` file. This was chosen because:
- It makes incremental re-runs efficient: existing files are read and only missing shelf data is updated.
- It avoids re-scraping a book's detail page if it was already fetched in a previous run.
- It keeps individual file sizes small and easy to inspect.
- It allows partial exports to be useful even if the run is interrupted.

The trade-off is many small files instead of one searchable export. A single-file export can be produced externally by merging the JSON files.

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
