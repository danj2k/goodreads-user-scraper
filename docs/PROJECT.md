# Project

## Purpose

A CLI tool that exports a Goodreads user's reading data — profile, shelves, books, and authors — to local JSON files.

## Goals

- Scrape all shelves a user has, including per-book shelf assignments, ratings, and read dates.
- Scrape detailed metadata for each book (title, description, genres, ratings, series, etc.).
- Optionally scrape author biographies and images.
- Be resilient against Goodreads rate limiting via automatic retries and exponential back-off.
- Support incremental re-runs: existing book JSON files are updated rather than re-fetched.

## Non-goals

- Not a general-purpose Goodreads API client; it only scrapes a single user's public profile and shelves.
- Does not scrape reviews, comments, or social features.
- Does not support multiple users in a single run.

## Constraints

- Requires a Goodreads session cookie for shelf scraping (Goodreads requires login to view shelf data).
- Goodreads pages have bot protection on individual book/author pages, requiring a stealth browser session.
- Goodreads has no public API; this tool scrapes HTML directly, so it is fragile to site redesigns.
- Python >=3.10 required (uses `str | None` union syntax throughout).

## Entry point

`goodreads-user-scraper` CLI command, defined in `scraper/__main__.py` via `pyproject.toml`'s `[project.scripts]`.
