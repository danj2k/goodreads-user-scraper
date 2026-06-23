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

Scrapling logs verbosely to stderr by default. The `_redirect_scrapling_logging` function removes StreamHandlers from the "scrapling" logger and adds a FileHandler writing to `scrapling_fetch.log`. This keeps the user's terminal clean while preserving debug information for troubleshooting.
