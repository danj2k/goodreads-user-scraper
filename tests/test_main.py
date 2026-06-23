import json
import sqlite3
import sys
from argparse import Namespace

import pytest

from scraper import __main__, __version__, http

# resolve_cookie precedence: --cookie > GOODREADS_COOKIE env > --cookie_file.


def test_resolve_cookie_prefers_cli_arg(monkeypatch):
    monkeypatch.setenv("GOODREADS_COOKIE", "env-cookie")
    args = Namespace(cookie="cli-cookie", cookie_file=None)
    assert __main__.resolve_cookie(args) == "cli-cookie"


def test_resolve_cookie_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("GOODREADS_COOKIE", "env-cookie")
    args = Namespace(cookie=None, cookie_file=None)
    assert __main__.resolve_cookie(args) == "env-cookie"


def test_resolve_cookie_reads_file_and_strips(tmp_path, monkeypatch):
    monkeypatch.delenv("GOODREADS_COOKIE", raising=False)
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("  file-cookie\n")
    args = Namespace(cookie=None, cookie_file=str(cookie_file))
    assert __main__.resolve_cookie(args) == "file-cookie"


def test_resolve_cookie_none_when_unset(monkeypatch):
    monkeypatch.delenv("GOODREADS_COOKIE", raising=False)
    args = Namespace(cookie=None, cookie_file=None)
    assert __main__.resolve_cookie(args) is None


def test_resolve_cookie_exits_when_file_missing(monkeypatch):
    monkeypatch.delenv("GOODREADS_COOKIE", raising=False)
    args = Namespace(cookie=None, cookie_file="/no/such/cookie/file")
    with pytest.raises(SystemExit):
        __main__.resolve_cookie(args)


# End-to-end CLI: argument parsing through file output.
# These tests pass --db "" to disable database mode and test the JSON path.


def _run_cli(monkeypatch, *argv):
    monkeypatch.delenv("GOODREADS_COOKIE", raising=False)
    monkeypatch.setattr(sys, "argv", ["scraper", *argv])
    __main__.main()


def test_cli_version_prints_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["goodreads-user-scraper", "--version"])
    with pytest.raises(SystemExit) as exc:
        __main__.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().endswith(__version__)


def test_cli_writes_user_json(tmp_path, monkeypatch, mock_get_soup):
    mock_get_soup({"user/show": "profile.html"})
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--skip_shelves",
        "--db", "",
    )

    data = json.loads((tmp_path / "user.json").read_text())
    assert data["user_id"] == "54739262"
    assert data["user_name"] == "Yash Totale"


def test_cli_skip_user_info_writes_nothing(tmp_path, monkeypatch):
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--skip_user_info",
        "--skip_shelves",
        "--db", "",
    )

    assert not (tmp_path / "user.json").exists()


def test_cli_full_run_writes_user_and_books(tmp_path, monkeypatch, mock_get_soup):
    # A cookie enables shelves. Only the "read" shelf has content; every other
    # shelf page resolves to the empty terminator.
    mock_get_soup(
        {
            "user/show": "profile.html",
            "shelf=read&page=1": "shelf_read.html",
            "page=": "shelf_empty.html",
            "book/show": "book.html",
        }
    )
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--cookie", "fake-cookie",
        "--skip_authors",
        "--db", "",
    )

    user_data = json.loads((tmp_path / "user.json").read_text())
    assert user_data["user_name"] == "Yash Totale"

    # Field-level parsing is pinned by the parser and process_book tests; here we
    # only confirm the pipeline produced the book record from the right shelf.
    book_path = tmp_path / "books" / "211721806.json"
    book = json.loads(book_path.read_text())
    assert book["book_title"] == "Dungeon Crawler Carl"
    assert book["shelves"] == ["read"]


def test_cli_invalid_cookie_exits_cleanly(tmp_path, monkeypatch, soup):
    # An expired cookie returns the sign-in wall during shelf fetches; main() must exit with a clean ❌, not a traceback.
    profile = soup("profile.html")

    async def fake(url):
        if "review/list" in url:
            raise http.AuthError()
        return profile

    monkeypatch.setattr("scraper.http.get_soup", fake)

    with pytest.raises(SystemExit) as exc:
        _run_cli(
            monkeypatch,
            "--user_id", "54739262",
            "--output_dir", str(tmp_path),
            "--cookie", "fake-cookie",
            "--skip_authors",
            "--db", "",
        )

    assert "Cookie appears invalid or expired" in str(exc.value.code)


def test_cli_finishes_then_fails_when_book_fetches_are_exhausted(
    tmp_path, monkeypatch, mock_get_soup, capsys
):
    # Every book fetch is exhausted. The run must finish the whole shelf (reach
    # the "Saved to" line), then exit non-zero with an "incomplete" message —
    # not abort on the first failure.
    mock_get_soup(
        {
            "user/show": "profile.html",
            "shelf=read&page=1": "shelf_read.html",
            "page=": "shelf_empty.html",
        }
    )

    async def boom(book_id, args):
        raise http.FetchError("https://www.goodreads.com/book/show/" + book_id)

    monkeypatch.setattr("scraper.books.scrape_book", boom)

    with pytest.raises(SystemExit) as exc:
        _run_cli(
            monkeypatch,
            "--user_id", "54739262",
            "--output_dir", str(tmp_path),
            "--cookie", "fake-cookie",
            "--skip_authors",
            "--db", "",
        )

    assert exc.value.code != 0
    assert "incomplete" in str(exc.value.code)
    assert (tmp_path / "user.json").exists()
    assert "Saved to" in capsys.readouterr().out  # the run reached the end


# ---------------------------------------------------------------------------
# Database mode tests
# ---------------------------------------------------------------------------


def test_cli_writes_user_to_database(tmp_path, monkeypatch, mock_get_soup):
    mock_get_soup({"user/show": "profile.html"})
    db_path = str(tmp_path / "test.db")
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--skip_shelves",
        "--db", db_path,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT user_name, num_ratings FROM users WHERE user_id = ?", ("54739262",)).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "Yash Totale"
    assert row[1] == 81


def test_cli_full_run_writes_to_database(tmp_path, monkeypatch, mock_get_soup):
    """End-to-end: shelves + books go into the database, not JSON files."""
    mock_get_soup(
        {
            "user/show": "profile.html",
            "shelf=read&page=1": "shelf_read.html",
            "page=": "shelf_empty.html",
            "book/show": "book.html",
        }
    )
    db_path = str(tmp_path / "test.db")
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--cookie", "fake-cookie",
        "--skip_authors",
        "--db", db_path,
    )

    conn = sqlite3.connect(db_path)

    # User record
    user = conn.execute("SELECT user_name FROM users WHERE user_id = ?", ("54739262",)).fetchone()
    assert user is not None
    assert user[0] == "Yash Totale"

    # Book record
    books = conn.execute("SELECT book_id, book_title FROM books").fetchall()
    assert len(books) >= 1
    book_ids = {r[0] for r in books}
    assert "211721806" in book_ids

    # Book shelves
    shelves = conn.execute("SELECT shelf_name FROM book_shelves").fetchall()
    shelf_names = {r[0] for r in shelves}
    assert "read" in shelf_names

    # Book dates
    dates = conn.execute("SELECT date_read FROM book_dates_read").fetchall()
    assert len(dates) >= 1

    conn.close()


def test_cli_db_incremental_skip(tmp_path, monkeypatch, mock_get_soup, capsys):
    """When books are already in the DB with unchanged shelf data, they are skipped."""
    mock_get_soup(
        {
            "user/show": "profile.html",
            "shelf=read&page=1": "shelf_read.html",
            "page=": "shelf_empty.html",
            "book/show": "book.html",
        }
    )
    db_path = str(tmp_path / "test.db")

    # First run — populates the database.
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--cookie", "fake-cookie",
        "--skip_authors",
        "--db", db_path,
    )

    conn = sqlite3.connect(db_path)
    first_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    conn.close()
    assert first_count >= 1

    # Second run — same shelves, books should be skipped.
    mock_get_soup(
        {
            "user/show": "profile.html",
            "shelf=read&page=1": "shelf_read.html",
            "page=": "shelf_empty.html",
            "book/show": "book.html",
        }
    )
    scrape_calls = []
    original_scrape = None

    import scraper.books as books_mod
    original_scrape = books_mod.scrape_book

    async def counting_scrape(book_id, args):
        scrape_calls.append(book_id)
        return await original_scrape(book_id, args)

    monkeypatch.setattr("scraper.books.scrape_book", counting_scrape)

    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--cookie", "fake-cookie",
        "--skip_authors",
        "--db", db_path,
    )

    # No books should have been scraped on the second run.
    assert scrape_calls == []


def test_cli_db_empty_string_disables(tmp_path, monkeypatch, mock_get_soup):
    """Passing --db '' disables database storage; JSON is written instead."""
    mock_get_soup({"user/show": "profile.html"})
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--output_dir", str(tmp_path),
        "--skip_shelves",
        "--db", "",
    )

    # JSON file exists, database does not.
    assert (tmp_path / "user.json").exists()
    assert not (tmp_path / "goodreads-library.db").exists()


def test_cli_db_default_path(tmp_path, monkeypatch, mock_get_soup):
    """Without --db flag, default database path is goodreads-library.db."""
    mock_get_soup({"user/show": "profile.html"})
    monkeypatch.chdir(tmp_path)
    _run_cli(
        monkeypatch,
        "--user_id", "54739262",
        "--skip_shelves",
    )

    # Default database file created in cwd.
    assert (tmp_path / "goodreads-library.db").exists()
    # JSON NOT created (db mode is active).
    assert not (tmp_path / "user.json").exists()
