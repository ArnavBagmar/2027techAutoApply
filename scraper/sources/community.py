from datetime import datetime
from typing import Any

import requests

from scraper.filters import categorize, is_internship, is_us
from scraper.models import Listing, listing_id

# Verified at implementation time; must point at a machine-readable listings
# file in a community-maintained Summer 2027 internship repo.
COMMUNITY_SOURCES: dict[str, str] = {
    "SimplifyJobs/Summer2027-Internships": (
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships"
        "/dev/.github/scripts/listings.json"
    ),
}


def parse(payload: list[dict[str, Any]], repo: str, now: datetime) -> list[Listing]:
    listings = []
    for entry in payload:
        title = entry.get("title") or ""
        url = entry.get("url") or ""
        locations = entry.get("locations") or []
        terms = entry.get("terms") or []
        if not entry.get("active", True):
            continue
        if "Summer 2027" not in terms:
            continue
        if not (url and is_internship(title) and is_us(locations)):
            continue
        listings.append(
            Listing(
                id=listing_id(url),
                company=entry.get("company_name") or "Unknown",
                title=title,
                category=categorize(title),
                locations=locations,
                url=url,
                ats="community",
                source=f"community:{repo}",
                first_seen=now,
            )
        )
    return listings


def fetch_all(now: datetime, timeout: float = 20.0) -> tuple[list[Listing], set[str]]:
    listings: list[Listing] = []
    ok: set[str] = set()
    for repo, raw_url in COMMUNITY_SOURCES.items():
        try:
            response = requests.get(raw_url, timeout=timeout)
            response.raise_for_status()
            listings.extend(parse(response.json(), repo, now))
            ok.add(f"community:{repo}")
        except Exception as error:
            print(f"community source {repo} failed: {error}")
    return listings, ok
