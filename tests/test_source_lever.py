import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Company
from scraper.sources import lever

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="lever", board="acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_keeps_only_internships():
    listings = lever.parse(load_fixture("lever_postings.json"), ACME, NOW)
    assert [item.url for item in listings] == ["https://jobs.lever.co/acme/abc-123"]


def test_parse_maps_fields():
    listing = lever.parse(load_fixture("lever_postings.json"), ACME, NOW)[0]
    assert listing.title == "Software Engineering Intern (Summer 2027)"
    assert listing.locations == ["New York, NY"]
    assert listing.source == "lever:acme"
