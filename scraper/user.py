from argparse import Namespace
import json
import re
import sqlite3

from scrapling.parser import Selector

from scraper import http, output
from scraper.parse import find_tag


def get_user_name(soup: Selector) -> str:
    return (
        find_tag(soup, id="profileNameTopHeading").text.strip().split("\n")[0].strip()
    )


def get_num_ratings(soup: Selector) -> int:
    container = find_tag(soup, "div", attrs={"class": "profilePageUserStatsInfo"})
    return int(re.findall(r"\d+", find_tag(container, "a").text)[0])


def get_avg_rating(soup: Selector) -> float:
    container = find_tag(soup, "div", attrs={"class": "profilePageUserStatsInfo"})
    return float(re.findall(r"\d*\.?\d+", container.find_all("a")[1].text)[0])


def get_num_reviews(soup: Selector) -> int:
    container = find_tag(soup, "div", attrs={"class": "profilePageUserStatsInfo"})
    return int(re.findall(r"\d+", container.find_all("a")[2].text)[0])


async def get_user_info(args: Namespace) -> Selector | None:
    if args.skip_user_info:
        return None

    user_id: str = args.user_id
    url = "https://www.goodreads.com/user/show/" + user_id
    with output.status("Finding user\u2026"):
        soup = await http.get_soup(url)

    data = {
        "user_id": user_id,
        "user_name": get_user_name(soup),
        "num_ratings": get_num_ratings(soup),
        "average_rating": get_avg_rating(soup),
        "num_reviews": get_num_reviews(soup),
    }

    # Write to database if available, otherwise write JSON.
    db_conn: sqlite3.Connection | None = getattr(args, "db_conn", None)
    if db_conn is not None:
        from scraper.db import upsert_user
        upsert_user(db_conn, data)
    else:
        output_file = args.output_dir / "user.json"
        with open(output_file, "w") as file:
            json.dump(data, file, indent=2)

    output.log(
        f"\U0001f464  {data['user_name']} \u00b7 {data['num_ratings']} ratings "
        f"\u00b7 {data['num_reviews']} reviews",
        markup=False,
    )

    if not args.skip_shelves:
        output.log("")

    return soup
