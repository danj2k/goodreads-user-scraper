"""Tests for scraper.db — SQLite storage layer."""

import json
import sqlite3

import pytest

from scraper import db


@pytest.fixture
def conn(tmp_path):
    """Open an in-memory-like database (backed by tmp_path for persistence)."""
    c = db.open_db(str(tmp_path / "test.db"))
    assert c is not None
    yield c  # type: ignore[misc]
    c.close()


@pytest.fixture
def sample_book():
    """A minimal book dict matching the scrape_book output shape."""
    return {
        "book_id": "211721806",
        "book_id_title": "211721806-dungeon-crawler-carl",
        "book_title": "Dungeon Crawler Carl",
        "book_description": "The apocalypse will be televised!",
        "book_url": "https://www.goodreads.com/book/show/211721806",
        "book_image": "https://m.media-amazon.com/images/test.jpg",
        "book_series_uri": "https://www.goodreads.com/series/309211",
        "year_first_published": "2020",
        "num_pages": 450,
        "num_ratings": 396420,
        "num_reviews": 53589,
        "average_rating": 4.46,
        "rating": 4,
        "exclusive_shelf": "read",
        "author": {
            "author_id": "999015",
            "author_id_title": "999015.Matt_Dinniman",
            "author_name": "Matt Dinniman",
            "author_url": "https://www.goodreads.com/author/show/999015.Matt_Dinniman",
            "author_image": "https://images.gr-assets.com/authors/test.jpg",
            "author_description": "Matt Dinniman writes things.",
        },
        "shelves": ["read", "fiction"],
        "dates_read": ["May 19, 2026"],
        "genres": ["Fantasy", "Science Fiction"],
    }


@pytest.fixture
def sample_user():
    return {
        "user_id": "54739262",
        "user_name": "Yash Totale",
        "num_ratings": 81,
        "average_rating": 4.12,
        "num_reviews": 3,
    }


def _insert_book_with_author(conn, book):
    """Insert author + book together to satisfy FK constraints."""
    author = book.get("author")
    if isinstance(author, dict):
        db.upsert_author(conn, author)
    db.upsert_book(conn, book)


# ---------------------------------------------------------------------------
# open_db
# ---------------------------------------------------------------------------


def test_open_db_returns_none_for_none_path():
    assert db.open_db(None) is None


def test_open_db_creates_schema(tmp_path):
    conn = db.open_db(str(tmp_path / "test.db"))
    assert conn is not None
    # Verify all tables exist.
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"users", "authors", "books", "book_shelves", "book_dates_read", "book_genres"} <= tables
    conn.close()


def test_open_db_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn1 = db.open_db(path)
    conn1.close()
    conn2 = db.open_db(path)
    # No errors, schema still intact.
    tables = {
        r[0]
        for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "books" in tables
    conn2.close()


# ---------------------------------------------------------------------------
# upsert_user
# ---------------------------------------------------------------------------


def test_upsert_user_insert(conn, sample_user):
    db.upsert_user(conn, sample_user)
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", ("54739262",)).fetchone()
    assert row is not None
    assert row[1] == "Yash Totale"
    assert row[2] == 81


def test_upsert_user_updates(conn, sample_user):
    db.upsert_user(conn, sample_user)
    sample_user["user_name"] = "Yash T."
    db.upsert_user(conn, sample_user)
    row = conn.execute("SELECT user_name FROM users WHERE user_id = ?", ("54739262",)).fetchone()
    assert row[0] == "Yash T."


# ---------------------------------------------------------------------------
# upsert_author
# ---------------------------------------------------------------------------


def test_upsert_author_insert(conn):
    author = {
        "author_id": "999015",
        "author_id_title": "999015.Matt_Dinniman",
        "author_name": "Matt Dinniman",
        "author_url": "https://www.goodreads.com/author/show/999015",
        "author_image": "https://img.jpg",
        "author_description": "Writes books.",
    }
    db.upsert_author(conn, author)
    row = conn.execute("SELECT author_name FROM authors WHERE author_id = ?", ("999015",)).fetchone()
    assert row[0] == "Matt Dinniman"


def test_upsert_author_updates(conn):
    author = {
        "author_id": "999015",
        "author_id_title": "999015.Matt_Dinniman",
        "author_name": "Matt Dinniman",
        "author_url": "https://url",
        "author_image": None,
        "author_description": None,
    }
    db.upsert_author(conn, author)
    author["author_name"] = "M. Dinniman"
    db.upsert_author(conn, author)
    row = conn.execute("SELECT author_name FROM authors WHERE author_id = ?", ("999015",)).fetchone()
    assert row[0] == "M. Dinniman"


# ---------------------------------------------------------------------------
# upsert_book
# ---------------------------------------------------------------------------


def test_upsert_book_insert(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    row = conn.execute("SELECT book_title, rating FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] == "Dungeon Crawler Carl"
    assert row[1] == 4


def test_upsert_book_stores_shelves(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    rows = conn.execute("SELECT shelf_name FROM book_shelves WHERE book_id = ?", ("211721806",)).fetchall()
    assert {r[0] for r in rows} == {"read", "fiction"}


def test_upsert_book_stores_dates(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    rows = conn.execute("SELECT date_read FROM book_dates_read WHERE book_id = ?", ("211721806",)).fetchall()
    assert [r[0] for r in rows] == ["May 19, 2026"]


def test_upsert_book_stores_genres(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    rows = conn.execute("SELECT genre FROM book_genres WHERE book_id = ?", ("211721806",)).fetchall()
    assert {r[0] for r in rows} == {"Fantasy", "Science Fiction"}


def test_upsert_book_stores_author_fk(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    row = conn.execute("SELECT author_id FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] == "999015"


def test_upsert_book_updates_on_conflict(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    sample_book["rating"] = 5
    sample_book["shelves"] = ["read"]
    _insert_book_with_author(conn, sample_book)
    row = conn.execute("SELECT rating FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] == 5
    # Shelves replaced, not appended.
    shelves = conn.execute("SELECT shelf_name FROM book_shelves WHERE book_id = ?", ("211721806",)).fetchall()
    assert len(shelves) == 1
    assert shelves[0][0] == "read"


def test_upsert_book_with_no_author(conn, sample_book):
    sample_book["author"] = None
    _insert_book_with_author(conn, sample_book)
    row = conn.execute("SELECT author_id FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] is None


def test_upsert_book_with_no_genres(conn, sample_book):
    sample_book["genres"] = None
    _insert_book_with_author(conn, sample_book)
    rows = conn.execute("SELECT COUNT(*) FROM book_genres WHERE book_id = ?", ("211721806",)).fetchone()
    assert rows[0] == 0


def test_upsert_book_with_no_dates(conn, sample_book):
    sample_book["dates_read"] = []
    _insert_book_with_author(conn, sample_book)
    rows = conn.execute("SELECT COUNT(*) FROM book_dates_read WHERE book_id = ?", ("211721806",)).fetchone()
    assert rows[0] == 0


# ---------------------------------------------------------------------------
# needs_scrape
# ---------------------------------------------------------------------------


def test_needs_scrape_new_book(conn):
    shelf_data = {"shelves": ["read"], "rating": 4, "dates_read": ["May 19, 2026"]}
    assert db.needs_scrape(conn, "99999", shelf_data) == db.ScrapeStatus.MISSING


def test_needs_scrape_unchanged(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["read", "fiction"], "rating": 4, "dates_read": ["May 19, 2026"]}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CURRENT


def test_needs_scrape_shelf_changed(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["read"], "rating": 4, "dates_read": ["May 19, 2026"]}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CHANGED


def test_needs_scrape_rating_changed(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["read", "fiction"], "rating": 5, "dates_read": ["May 19, 2026"]}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CHANGED


def test_needs_scrape_dates_changed(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["read", "fiction"], "rating": 4, "dates_read": []}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CHANGED


def test_needs_scrape_dates_added(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["read", "fiction"], "rating": 4, "dates_read": ["May 19, 2026", "Jun 1, 2026"]}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CHANGED


def test_needs_scrape_shelf_order_ignored(conn, sample_book):
    """Shelf comparison is set-based; order doesn't matter."""
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["fiction", "read"], "rating": 4, "dates_read": ["May 19, 2026"]}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CURRENT


# ---------------------------------------------------------------------------
# update_book_shelf
# ---------------------------------------------------------------------------


def test_update_book_shelf_changes_rating(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    db.update_book_shelf(conn, "211721806", {"rating": 5, "shelves": ["read"], "dates_read": []})
    row = conn.execute("SELECT rating FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] == 5


def test_update_book_shelf_changes_shelves(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    db.update_book_shelf(conn, "211721806", {"rating": 4, "shelves": ["to-read"], "dates_read": []})
    shelves = {r[0] for r in conn.execute("SELECT shelf_name FROM book_shelves WHERE book_id = ?", ("211721806",)).fetchall()}
    assert shelves == {"to-read"}


def test_update_book_shelf_preserves_metadata(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    db.update_book_shelf(conn, "211721806", {"rating": 5, "shelves": ["read"], "dates_read": []})
    row = conn.execute("SELECT book_title, num_pages FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] == "Dungeon Crawler Carl"
    assert row[1] == 450


def test_update_book_shelf_sets_exclusive(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    db.update_book_shelf(conn, "211721806", {"rating": 4, "shelves": ["read"], "dates_read": []}, exclusive_shelf="read")
    row = conn.execute("SELECT exclusive_shelf FROM books WHERE book_id = ?", ("211721806",)).fetchone()
    assert row[0] == "read"


# ---------------------------------------------------------------------------
# Full round-trip: insert → needs_scrape → update → needs_scrape
# ---------------------------------------------------------------------------


def test_round_trip_no_scrape_needed(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    shelf_data = {"shelves": ["read", "fiction"], "rating": 4, "dates_read": ["May 19, 2026"]}
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CURRENT

    # Simulate a second run with the same data — still no scrape needed.
    assert db.needs_scrape(conn, "211721806", shelf_data) == db.ScrapeStatus.CURRENT


def test_round_trip_scrape_after_shelf_change(conn, sample_book):
    _insert_book_with_author(conn, sample_book)
    # User moves book to a different shelf.
    new_shelf_data = {"shelves": ["to-read"], "rating": None, "dates_read": []}
    assert db.needs_scrape(conn, "211721806", new_shelf_data) == db.ScrapeStatus.CHANGED

    # After updating shelf data, no scrape needed.
    db.update_book_shelf(conn, "211721806", new_shelf_data)
    assert db.needs_scrape(conn, "211721806", new_shelf_data) == db.ScrapeStatus.CURRENT
