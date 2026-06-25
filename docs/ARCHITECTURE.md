# Architecture

## Overview

A single-process async Python CLI. Two Playwright browser sessions are launched at startup — one standard, one anti-bot — and shared across all HTTP requests. Scraped data is stored in a SQLite database by default, with optional JSON file output.

## Components

### `scraper/__main__.py` — Entry point
CLI argument parsing (`--quiet` / `-q` for non-interactive mode, `--db` for database path), cookie resolution (CLI flag, env var, or file), orchestration of user-info and shelf scraping, and top-level error handling.

### `scraper/output.py` — Output abstraction
Bridges interactive and non-interactive (quiet) modes. In interactive mode, delegates to *rich* for progress bars, spinners, and styled output. In quiet mode, prints plain text with `[INFO]`/`[WARN]`/`[ERROR]` prefixes suitable for cron jobs and log-file redirection. Also controls whether scrapling's verbose logs go to a file (interactive) or stdout (quiet).

### `scraper/http.py` — HTTP layer
Manages the two `scrapling` async browser sessions. Provides `get_soup()` (parsed HTML). Handles retry with exponential back-off, Retry-After parsing, auth-failure detection, and redirects scrapling's verbose logging to a file (interactive) or stdout (quiet mode).

### `scraper/parse.py` — DOM helpers
Thin wrappers around scrapling's `Selector.find()` that narrow `Selector | None` to `Selector` with a clear error on miss (`ElementNotFound`). Also handles the `class` → `class_` keyword mapping. Provides `get_text()` for recursive text extraction — scrapling's `.text` only returns direct text content, which is empty for elements with nested tags like `<b>` or `<span>`. `get_text()` uses lxml's `text_content()` to match the recursive behaviour callers expect from BeautifulSoup.

### `scraper/user.py` — User profile
Scrapes the user profile page for name, rating count, average rating, and review count. Writes to the database (when `--db` is active) or `user.json` (legacy JSON mode).

### `scraper/shelves.py` — Shelf orchestration
The most complex module. Discovers all shelves from the user profile, fetches every shelf page (concurrently via `asyncio.gather` with an `asyncio.Semaphore(5)`), detects exclusive shelves during collection, deduplicates books across shelves, and coordinates per-book scraping (also capped at 5 concurrent). Each book is written to the database (when `--db` is active) or `books/<id>.json` (legacy JSON mode).

### `scraper/books.py` — Book details
Scrapes an individual book page for title, description, genres, series, publication year, page count, ratings, reviews, average rating, and cover image. Optionally delegates to the author module.

### `scraper/author.py` — Author details
Scrapes an author page for name, description, and image. Uses a shared-task cache (`_tasks` dict) so multiple books referencing the same author only trigger one fetch.

### `scraper/db.py` — SQLite storage layer
Creates and manages the SQLite database. Provides:
- Schema creation (6 tables: `users`, `authors`, `books`, `book_shelves`, `book_dates_read`, `book_genres`)
- Upsert operations for users, authors, and books (including child tables)
- Incremental update checks: `needs_scrape()` compares shelf/rating/dates against the database to skip expensive page fetches
- Shelf-only updates: `update_book_shelf()` modifies shelf data without touching book metadata

## Data flow

```
CLI (args + cookie)
  → init_session (two browser sessions)
  → user.get_user_info  →  upsert_user (DB) or user.json
  → shelves.get_all_shelves
      → discover shelf names from profile page
      → collect_shelf_rows (concurrent per shelf)
          → fetch_shelf_page (paginated, &print=true)
          → detect_exclusive_shelves (from first page's <ul class="shelves">)
          → extract book IDs, ratings, dates from HTML table
      → _dedupe_books (merge across shelves, normalise IDs to numeric prefix)
      → merge exclusive shelf sets from collection
      → [DB mode] needs_scrape check per book
          → skip if shelf/rating/dates unchanged (fast path)
          → update_book_shelf if only shelf data changed (DB-only, no HTTP)
          → scrape_book + upsert_book if book is new (full HTTP fetch)
      → [JSON mode] process_book per book (original file-based logic)
      → return fetch_failure_count
  → close_session
  → exit(1) if failures occurred
```

## Database schema

See `scraper/db.py` docstring for the full schema. Key tables:

- **`users`** — one row per scraped user (name, rating count, average, review count)
- **`authors`** — one row per author (name, description, image URL)
- **`books`** — one row per book with full metadata plus user's rating, exclusive shelf, and FK to author
- **`book_shelves`** — many-to-many: book ↔ shelf name
- **`book_dates_read`** — one row per read date per book
- **`book_genres`** — many-to-many: book ↔ genre

## Output structure

### Database mode (default)
```
goodreads-library.db   (SQLite, WAL journal mode)
```

### JSON mode (`--db ""`)
```
goodreads-data/
  user.json
  books/
    <book_id>.json   (one per unique book)
```
