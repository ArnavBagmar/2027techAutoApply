from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=100"
APPLY_URL = "https://jobs.smartrecruiters.com/{board}/{posting_id}"


def _location(raw: dict[str, Any]) -> str:
    parts = [raw.get("city"), raw.get("region")]
    return ", ".join(part for part in parts if part) or "Unknown"


def parse(payload: dict[str, Any], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for posting in payload.get("content", []):
        title = posting.get("name") or ""
        posting_id = posting.get("id") or ""
        url = APPLY_URL.format(board=company.board, posting_id=posting_id) if posting_id else ""
        location = _location(posting.get("location") or {})
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
