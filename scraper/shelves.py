from argparse import Namespace
import asyncio
import json
from pathlib import Path
import re
from typing import Any

from scrapling.parser import Selector
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from scraper import books, http
from scraper.parse import ElementNotFound, find_tag

PER_PAGE = 100
console = Console()


def detect_exclusive_shelves(soup: Selector) -> set[str]:
    """Determine which shelves are "exclusive" from a ``&print=true`` shelf page.

    On the print-view shelf page, a ``<ul>`` with class ``shelves`` lists
    every shelf.  ``<li>`` elements that carry the class ``exclusive``
    belong to the exclusive shelf group (e.g. ``to-read``,
    ``currently-reading``, ``read``, ``did-not-finish``).

    Returns an empty set when the ``ul.shelves`` element is absent.
    """
    shelves_list = soup.find("ul", {"class": "shelves"})
    if shelves_list is None:
        return set()

    exclusive: set[str] = set()
    for li in shelves_list.find_all("li"):
        classes = li.attrib.get("class", "")
        if "exclusive" in classes.split():
            exclusive.add(li.attrib.get("alt",""))

    return exclusive


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


async def fetch_shelf_page(user_id: str, shelf: str, page: int) -> Selector:
    url = (
        f"https://www.goodreads.com/review/list/{user_id}"
        f"?shelf={shelf}&page={page}&per_page={PER_PAGE}&print=true"
    )
    return await http.get_soup(url)


def get_id(book_row: Selector) -> str:
    cell = find_tag(book_row, "td", {"class": "field title"})
    title_href = find_tag(find_tag(cell, "div", {"class": "value"}), "a")
    href = title_href.attrib.get("href")
    assert isinstance(href, str)
    return href.split("/")[-1]


def get_rating(book_row: Selector) -> int | None:
    cell = find_tag(book_row, "td", {"class": "field rating"})
    stars = cell.find("div", {"class": "stars"})
    if stars is None:
        return None
    value = stars.attrib.get("data-rating")
    return (int(value) or None) if isinstance(value, str) else None


def get_dates_read(book_row: Selector) -> list[str]:
    cell = find_tag(book_row, "td", {"class": "field date_read"})
    dates = find_tag(cell, "div", {"class": "value"}).find_all(
        "div", {"class": "date_row"}
    )
    date_arr = []
    for date in dates:
        date_text = date.text.strip().split("\n")[0].strip()
        if date_text and date_text != "not set":
            date_arr += [date_text]
    return date_arr


async def collect_shelf_rows(
    user_id: str, shelf: str
) -> tuple[list[Selector], set[str]]:
    """Fetch every page of *shelf* and return (rows, exclusive_shelves).

    The first page of every Goodreads shelf contains a ``<ul class="shelves">``
    that flags which shelves are exclusive (``read``, ``to-read``, etc.).
    We detect that once here so callers don't need a redundant re-fetch.
    """
    rows: list[Selector] = []
    exclusive: set[str] = set()
    page = 1
    while True:
        soup = await fetch_shelf_page(user_id, shelf, page)
        if page == 1:
            exclusive = detect_exclusive_shelves(soup)
        if soup.find("div", {"class": "greyText nocontent stacked"}):
            break
        body = find_tag(soup, "tbody", {"id": "booksBody"})
        rows.extend([child for child in body.children if child.tag == "tr"])
        page += 1
    return rows, exclusive


def _dedupe_books(
    shelf_rows: list[tuple[str, list[Selector]]],
) -> dict[str, dict[str, Any]]:
    books_by_id: dict[str, dict[str, Any]] = {}
    for shelf, page_rows in shelf_rows:
        for row in page_rows:
            try:
                book_id = get_id(row)
                entry = books_by_id.get(book_id)
                if entry is None:
                    entry = {
                        "shelves": [],
                        "rating": get_rating(row),
                        "dates_read": get_dates_read(row),
                    }
                    books_by_id[book_id] = entry
            except ElementNotFound:
                continue  # skip a malformed row (missing expected DOM elements)
            if shelf not in entry["shelves"]:
                entry["shelves"].append(shelf)
    return books_by_id


async def process_book(
    book_id: str, info: dict[str, Any], args: Namespace, output_dir: Path, exclusive_shelves: set[str] | None = None
) -> bool:
    """Scrape or update one book. Returns True if exhausted retries skipped it."""
    try:
        file_path = output_dir / f"{book_id}.json"
        if file_path.exists():
            with open(file_path, "r") as file:
                book = json.load(file)
            new_shelves = [s for s in info["shelves"] if s not in book["shelves"]]
            if new_shelves:
                book["shelves"].extend(new_shelves)
        else:
            book = await books.scrape_book(book_id, args)
            book["rating"] = info["rating"]
            book["dates_read"] = info["dates_read"]
            book["shelves"] = info["shelves"]

        # Determine the exclusive shelf for this book.
        if exclusive_shelves is not None:
            book_shelf_set = set(info.get("shelves", book.get("shelves", [])))
            matched = book_shelf_set & exclusive_shelves
            book["exclusive_shelf"] = sorted(matched)[0] if matched else None
        elif "exclusive_shelf" not in book:
            book["exclusive_shelf"] = None

        with open(file_path, "w") as file:
            json.dump(book, file, indent=2)
        return False
    except http.AuthError:
        raise  # a bad cookie dooms the whole run, not just this book
    except Exception as e:
        console.print(f"🟡  Skipped {book_id}: {e}")
        return isinstance(e, http.FetchError)


async def get_all_shelves(args: Namespace, profile: Selector | None = None) -> int:
    if args.skip_shelves:
        return 0

    if not http.has_cookie():
        print(
            "🟡  Skipping shelves: Goodreads requires login to view shelf data.\n"
            "    To scrape shelves, provide your Goodreads session cookie via one of:\n"
            '      --cookie "<cookie string>"\n'
            "      GOODREADS_COOKIE=<cookie string>   (environment variable)\n"
            "      --cookie_file <path-to-file>\n"
            "    See the README for how to grab the cookie from your browser.\n"
            "    Pass --skip_shelves to suppress this message."
        )
        return 0

    user_id: str = args.user_id
    output_dir = args.output_dir / "books"
    if profile is None:
        url = "https://www.goodreads.com/user/show/" + user_id
        profile = await http.get_soup(url)
    output_dir.mkdir(parents=True, exist_ok=True)

    shelf_links = find_tag(profile, "div", {"id": "shelves"}).find_all("a")
    shelf_names = []
    for link in shelf_links:
        href = link.attrib.get("href")
        assert isinstance(href, str)
        match = re.search(r"\?shelf=([^&]+)", href)
        assert match is not None
        shelf_names.append(match.group(1))

    with make_progress() as progress:
        task = progress.add_task("Finding shelves", total=len(shelf_names))

        async def collect(shelf: str) -> tuple[str, list[Selector], set[str]]:
            rows, exclusive = await collect_shelf_rows(user_id, shelf)
            progress.advance(task)
            return shelf, rows, exclusive

        per_shelf = await asyncio.gather(*(collect(shelf) for shelf in shelf_names))
    console.print(f"📚  {len(shelf_names)} shelves")

    books_by_id = _dedupe_books([(shelf, rows) for shelf, rows, _ in per_shelf])

    # Merge exclusive shelf sets detected during collection (from the first
    # page of each shelf, which contains a <ul class="shelves"> listing
    # every shelf with exclusive flags).  No re-fetch needed.
    all_exclusive: set[str] = set()
    for _, _, exclusive in per_shelf:
        all_exclusive.update(exclusive)
    exclusive_shelves: set[str] | None = all_exclusive or None
    if exclusive_shelves:
        console.print(
            f"🔒  Exclusive shelves: {', '.join(sorted(exclusive_shelves))}"
        )

    with make_progress() as progress:
        task = progress.add_task("Scraping books", total=len(books_by_id))

        async def run(book_id: str, info: dict[str, Any]) -> bool:
            failed = await process_book(
                book_id, info, args, output_dir, exclusive_shelves=exclusive_shelves
            )
            progress.advance(task)
            return failed

        results = await asyncio.gather(
            *(run(book_id, info) for book_id, info in books_by_id.items())
        )

    console.print(f"📖  {len(books_by_id)} books")
    return sum(results)
