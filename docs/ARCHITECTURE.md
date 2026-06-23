# Architecture

## Overview

A single-process async Python CLI. Two Playwright browser sessions are launched at startup — one standard, one anti-bot — and shared across all HTTP requests. Each scraped entity is written as an individual JSON file.

## Components

### `scraper/__main__.py` — Entry point
CLI argument parsing (`--quiet` / `-q` for non-interactive mode), cookie resolution (CLI flag, env var, or file), orchestration of user-info and shelf scraping, and top-level error handling.

### `scraper/output.py` — Output abstraction
Bridges interactive and non-interactive (quiet) modes. In interactive mode, delegates to *rich* for progress bars, spinners, and styled output. In quiet mode, prints plain text with `[INFO]`/`[WARN]`/`[ERROR]` prefixes suitable for cron jobs and log-file redirection. Also controls whether scrapling's verbose logs go to a file (interactive) or stdout (quiet).

### `scraper/http.py` — HTTP layer
Manages the two `scrapling` async browser sessions. Provides `get_soup()` (parsed HTML). Handles retry with exponential back-off, Retry-After parsing, auth-failure detection, and redirects scrapling's verbose logging to a file (interactive) or stdout (quiet mode).

### `scraper/parse.py` — DOM helpers
Thin wrappers around scrapling's `Selector.find()` that narrow `Selector | None` to `Selector` with a clear error on miss (`ElementNotFound`). Also handles the `class` → `class_` keyword mapping.

### `scraper/user.py` — User profile
Scrapes the user profile page for name, rating count, average rating, and review count. Writes `user.json`.

### `scraper/shelves.py` — Shelf orchestration
The most complex module. Discovers all shelves from the user profile, fetches every shelf page (concurrently via `asyncio.gather`), detects exclusive shelves during collection, deduplicates books across shelves, and coordinates per-book scraping. Each book is written as `books/<book_id>.json`.

### `scraper/books.py` — Book details
Scrapes an individual book page for title, description, genres, series, publication year, page count, ratings, reviews, average rating, and cover image. Optionally delegates to the author module.

### `scraper/author.py` — Author details
Scrapes an author page for name, description, and image. Uses a shared-task cache (`_tasks` dict) so multiple books referencing the same author only trigger one fetch.

## Data flow

```
CLI (args + cookie)
  → init_session (two browser sessions)
  → user.get_user_info  →  user.json
  → shelves.get_all_shelves
      → discover shelf names from profile page
      → collect_shelf_rows (concurrent per shelf)
          → fetch_shelf_page (paginated, &print=true)
          → detect_exclusive_shelves (from first page's <ul class="shelves">)
          → extract book IDs, ratings, dates from HTML table
      → _dedupe_books (merge across shelves)
      → merge exclusive shelf sets from collection
      → process_book (concurrent per book)
          → books.scrape_book (stealthy session)
              → author.scrape_author (shared task cache)
          → write books/<id>.json
      → return fetch_failure_count
  → close_session
  → exit(1) if failures occurred
```

## Output structure

```
goodreads-data/
  user.json
  books/
    <book_id>.json   (one per unique book)
```

## Dependencies

- **scrapling[all]** — Playwright-based web scraper with anti-bot stealth mode.
- **rich** — Terminal UI (progress bars, status spinners, styled output). Only used in interactive mode; quiet mode produces plain text without rich.
- **stdlib** — asyncio, argparse, json, re, pathlib, logging, email.utils.
