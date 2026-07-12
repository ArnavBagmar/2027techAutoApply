import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.sources import community

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_keeps_active_summer_2027_only():
    listings = community.parse(load_fixture("community_listings.json"), "org/repo", NOW)
    assert [item.url for item in listings] == ["https://boards.greenhouse.io/acme/jobs/999"]


def test_parse_tags_source_and_ats():
    listing = community.parse(load_fixture("community_listings.json"), "org/repo", NOW)[0]
    assert listing.source == "community:org/repo"
    assert listing.ats == "community"
    assert listing.company == "Acme"
