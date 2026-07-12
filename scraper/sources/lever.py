from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://api.lever.co/v0/postings/{board}?mode=json"


def parse(payload: list[dict[str, Any]], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for posting in payload:
        title = posting.get("text") or ""
        url = posting.get("hostedUrl") or ""
        location = (posting.get("categories") or {}).get("location") or "Unknown"
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
