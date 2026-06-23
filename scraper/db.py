"""SQLite storage layer for the Goodreads scraper.

Provides schema creation, upsert operations, and incremental-update
checks so that subsequent runs skip expensive book-page fetches when
the shelf, user rating, or read dates haven't changed.

Schema
------

::

    users
      user_id        TEXT PRIMARY KEY
      user_name      TEXT
      num_ratings    INTEGER
      average_rating REAL
      num_reviews    INTEGER

    authors
      author_id          TEXT PRIMARY KEY
      author_id_title    TEXT
      author_name        TEXT
      author_url         TEXT
      author_image       TEXT
      author_description TEXT

    books
      book_id               TEXT PRIMARY KEY
      book_id_title         TEXT
      book_title            TEXT
      book_description      TEXT
      book_url              TEXT
      book_image            TEXT
      book_series_uri       TEXT
      year_first_published  TEXT
      num_pages             INTEGER
      num_ratings           INTEGER
      num_reviews           INTEGER
      average_rating        REAL
      rating                INTEGER   -- user's rating 1-5 or NULL
      exclusive_shelf       TEXT      -- e.g. "read"
      author_id             TEXT REFERENCES authors(author_id)

    book_shelves
      book_id    TEXT REFERENCES books(book_id)
      shelf_name TEXT
      PRIMARY KEY (book_id, shelf_name)

    book_dates_read
      book_id   TEXT REFERENCES books(book_id)
      date_read TEXT
      PRIMARY KEY (book_id, date_read)

    book_genres
      book_id TEXT REFERENCES books(book_id)
      genre   TEXT
      PRIMARY KEY (book_id, genre)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    user_name      TEXT NOT NULL,
    num_ratings    INTEGER,
    average_rating REAL,
    num_reviews    INTEGER
);

CREATE TABLE IF NOT EXISTS authors (
    author_id          TEXT PRIMARY KEY,
    author_id_title    TEXT,
    author_name        TEXT,
    author_url         TEXT,
    author_image       TEXT,
    author_description TEXT
);

CREATE TABLE IF NOT EXISTS books (
    book_id               TEXT PRIMARY KEY,
    book_id_title         TEXT,
    book_title            TEXT,
    book_description      TEXT,
    book_url              TEXT,
    book_image            TEXT,
    book_series_uri       TEXT,
    year_first_published  TEXT,
    num_pages             INTEGER,
    num_ratings           INTEGER,
    num_reviews           INTEGER,
    average_rating        REAL,
    rating                INTEGER,
    exclusive_shelf       TEXT,
    author_id             TEXT REFERENCES authors(author_id)
);

CREATE TABLE IF NOT EXISTS book_shelves (
    book_id    TEXT NOT NULL REFERENCES books(book_id),
    shelf_name TEXT NOT NULL,
    PRIMARY KEY (book_id, shelf_name)
);

CREATE TABLE IF NOT EXISTS book_dates_read (
    book_id   TEXT NOT NULL REFERENCES books(book_id),
    date_read TEXT NOT NULL,
    PRIMARY KEY (book_id, date_read)
);

CREATE TABLE IF NOT EXISTS book_genres (
    book_id TEXT NOT NULL REFERENCES books(book_id),
    genre   TEXT NOT NULL,
    PRIMARY KEY (book_id, genre)
);
"""


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def open_db(path: str | None) -> sqlite3.Connection | None:
    """Open (or create) the database and ensure the schema exists.

    Returns ``None`` when *path* is ``None``, which lets callers treat
    database storage as optional without guarding every call site.
    """
    if path is None:
        return None
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

def upsert_user(conn: sqlite3.Connection, user: dict[str, Any]) -> None:
    conn.execute(
        """\
        INSERT INTO users (user_id, user_name, num_ratings, average_rating, num_reviews)
        VALUES (:user_id, :user_name, :num_ratings, :average_rating, :num_reviews)
        ON CONFLICT(user_id) DO UPDATE SET
            user_name      = excluded.user_name,
            num_ratings    = excluded.num_ratings,
            average_rating = excluded.average_rating,
            num_reviews    = excluded.num_reviews
        """,
        user,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Author
# ---------------------------------------------------------------------------

def upsert_author(conn: sqlite3.Connection, author: dict[str, Any]) -> None:
    conn.execute(
        """\
        INSERT INTO authors
            (author_id, author_id_title, author_name, author_url, author_image, author_description)
        VALUES
            (:author_id, :author_id_title, :author_name, :author_url, :author_image, :author_description)
        ON CONFLICT(author_id) DO UPDATE SET
            author_id_title    = excluded.author_id_title,
            author_name        = excluded.author_name,
            author_url         = excluded.author_url,
            author_image       = excluded.author_image,
            author_description = excluded.author_description
        """,
        author,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Book — upsert
# ---------------------------------------------------------------------------

def _upsert_book_row(conn: sqlite3.Connection, book: dict[str, Any]) -> None:
    """Insert or update the main ``books`` row (without child tables)."""
    conn.execute(
        """\
        INSERT INTO books (
            book_id, book_id_title, book_title, book_description,
            book_url, book_image, book_series_uri, year_first_published,
            num_pages, num_ratings, num_reviews, average_rating,
            rating, exclusive_shelf, author_id
        ) VALUES (
            :book_id, :book_id_title, :book_title, :book_description,
            :book_url, :book_image, :book_series_uri, :year_first_published,
            :num_pages, :num_ratings, :num_reviews, :average_rating,
            :rating, :exclusive_shelf, :author_id
        )
        ON CONFLICT(book_id) DO UPDATE SET
            book_id_title         = excluded.book_id_title,
            book_title            = excluded.book_title,
            book_description      = excluded.book_description,
            book_url              = excluded.book_url,
            book_image            = excluded.book_image,
            book_series_uri       = excluded.book_series_uri,
            year_first_published  = excluded.year_first_published,
            num_pages             = excluded.num_pages,
            num_ratings           = excluded.num_ratings,
            num_reviews           = excluded.num_reviews,
            average_rating        = excluded.average_rating,
            rating                = excluded.rating,
            exclusive_shelf       = excluded.exclusive_shelf,
            author_id             = excluded.author_id
        """,
        {
            "book_id": book["book_id"],
            "book_id_title": book.get("book_id_title"),
            "book_title": book.get("book_title"),
            "book_description": book.get("book_description"),
            "book_url": book.get("book_url"),
            "book_image": book.get("book_image"),
            "book_series_uri": book.get("book_series_uri"),
            "year_first_published": book.get("year_first_published"),
            "num_pages": book.get("num_pages"),
            "num_ratings": book.get("num_ratings"),
            "num_reviews": book.get("num_reviews"),
            "average_rating": book.get("average_rating"),
            "rating": book.get("rating"),
            "exclusive_shelf": book.get("exclusive_shelf"),
            "author_id": book.get("author", {}).get("author_id") if isinstance(book.get("author"), dict) else None,
        },
    )


def _replace_child_table(
    conn: sqlite3.Connection,
    table: str,
    book_id: str,
    column: str,
    values: list[str] | None,
) -> None:
    """Delete existing rows for *book_id* and insert fresh values."""
    conn.execute(f"DELETE FROM {table} WHERE book_id = ?", (book_id,))
    if values:
        conn.executemany(
            f"INSERT INTO {table} (book_id, {column}) VALUES (?, ?)",
            [(book_id, v) for v in values],
        )


def upsert_book(conn: sqlite3.Connection, book: dict[str, Any]) -> None:
    """Insert or update a complete book record including child tables.

    *book* is the dict produced by ``books.scrape_book`` with the
    additional ``shelves``, ``rating``, ``dates_read``, and
    ``exclusive_shelf`` keys added by ``shelves.process_book``.
    """
    _upsert_book_row(conn, book)
    _replace_child_table(conn, "book_shelves", book["book_id"], "shelf_name", book.get("shelves"))
    _replace_child_table(conn, "book_dates_read", book["book_id"], "date_read", book.get("dates_read"))
    _replace_child_table(conn, "book_genres", book["book_id"], "genre", book.get("genres"))
    conn.commit()


# ---------------------------------------------------------------------------
# Book — incremental check
# ---------------------------------------------------------------------------

def _fetch_book_state(
    conn: sqlite3.Connection, book_id: str
) -> dict[str, Any] | None:
    """Return the current shelf/rating/date state for *book_id*, or None."""
    row = conn.execute(
        "SELECT rating, exclusive_shelf FROM books WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    if row is None:
        return None

    shelves = {
        r[0]
        for r in conn.execute(
            "SELECT shelf_name FROM book_shelves WHERE book_id = ?",
            (book_id,),
        ).fetchall()
    }
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT date_read FROM book_dates_read WHERE book_id = ?",
            (book_id,),
        ).fetchall()
    ]
    return {"rating": row[0], "exclusive_shelf": row[1], "shelves": shelves, "dates_read": dates}


def needs_scrape(conn: sqlite3.Connection, book_id: str, shelf_data: dict[str, Any]) -> bool:
    """Return True if *book_id* is missing from the DB or its shelf data changed.

    *shelf_data* is the entry from ``_dedupe_books``::

        {"shelves": ["read", "fiction"], "rating": 4, "dates_read": ["May 19, 2026"]}

    The comparison covers exactly the three fields that shelf-page
    extraction can produce: shelf membership, user rating, and read
    dates.  Book metadata (title, description, etc.) is *not*
    compared — it's only set during the expensive page scrape.
    """
    state = _fetch_book_state(conn, book_id)
    if state is None:
        return True  # new book — full scrape needed

    if state["shelves"] != set(shelf_data["shelves"]):
        return True

    if state["rating"] != shelf_data["rating"]:
        return True
    if state["dates_read"] != shelf_data["dates_read"]:
        return True
    return False


# ---------------------------------------------------------------------------
# Book — update shelf data only (no re-scrape)
# ---------------------------------------------------------------------------

def update_book_shelf(
    conn: sqlite3.Connection,
    book_id: str,
    shelf_data: dict[str, Any],
    exclusive_shelf: str | None = None,
) -> None:
    """Update only shelf membership, rating, and dates without touching metadata.

    Called when the book already exists in the DB and the shelf data has
    changed.  This is a fast DB-only operation — no HTTP request needed.
    """
    conn.execute(
        "UPDATE books SET rating = ?, exclusive_shelf = ? WHERE book_id = ?",
        (shelf_data["rating"], exclusive_shelf, book_id),
    )
    _replace_child_table(conn, "book_shelves", book_id, "shelf_name", shelf_data.get("shelves"))
    _replace_child_table(conn, "book_dates_read", book_id, "date_read", shelf_data.get("dates_read"))
    conn.commit()
