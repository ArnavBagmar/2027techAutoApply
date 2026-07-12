from datetime import datetime

from scraper.filters import categorize, is_internship, is_us, matches_summer_2027
from scraper.models import Company, Listing, listing_id


def build_listing(
    company: Company, title: str, locations: list[str], url: str, now: datetime
) -> Listing:
    return Listing(
        id=listing_id(url),
        company=company.name,
        title=title,
        category=categorize(title, company.category_hint),
        locations=locations,
        url=url,
        ats=company.ats,
        source=f"{company.ats}:{company.board}",
        first_seen=now,
    )


def keep(company: Company, title: str, locations: list[str], url: str) -> bool:
    return bool(
        url
        and is_internship(title)
        and matches_summer_2027(title, company.season_agnostic)
        and is_us(locations)
    )
