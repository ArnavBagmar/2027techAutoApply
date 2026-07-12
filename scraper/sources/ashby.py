from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def parse(payload: dict[str, Any], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for job in payload.get("jobs", []):
        if not job.get("isListed", True):
            continue
        title = job.get("title") or ""
        url = job.get("jobUrl") or ""
        location = job.get("location") or "Unknown"
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
