import re
from datetime import datetime
from typing import Any

import requests

from scraper.filters import categorize, is_internship, is_us
from scraper.models import Listing, listing_id

# The season field is repo-year-scoped: these repos only track one cycle,
# so season == "Summer" means Summer 2027. SimplifyJobs-format repos use
# terms == ["Summer 2027"] instead; both are supported.
COMMUNITY_SOURCES: dict[str, str] = {
    "vanshb03/Summer2027-Internships": (
        "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships"
        "/dev/.github/scripts/listings.json"
    ),
}

# Belt-and-suspenders against upstream scope drift: season == "Summer" is
# trusted only while the title names no other year.
OTHER_YEAR_RE = re.compile(r"\b(202[0-6]|202[89]|203\d)\b")


def parse(payload: list[dict[str, Any]], repo: str, now: datetime) -> list[Listing]:
    listings = []
    for entry in payload:
        title = entry.get("title") or ""
        url = entry.get("url") or ""
        locations = entry.get("locations") or []
        if not entry.get("active", True):
            continue
        is_summer_2027 = entry.get("season") == "Summer" or "Summer 2027" in (
            entry.get("terms") or []
        )
        if not is_summer_2027:
            continue
        if OTHER_YEAR_RE.search(title) and "2027" not in title:
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
