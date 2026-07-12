import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scraper.models import Company
from scraper.sources import greenhouse

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="greenhouse", board="acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_keeps_only_matching_us_internships():
    listings = greenhouse.parse(load_fixture("greenhouse_jobs.json"), ACME, NOW)
    assert [item.url for item in listings] == [
        "https://boards.greenhouse.io/acme/jobs/111?gh_src=x"
    ]


def test_parse_maps_fields():
    listing = greenhouse.parse(load_fixture("greenhouse_jobs.json"), ACME, NOW)[0]
    assert listing.company == "Acme"
    assert listing.category == "swe"
    assert listing.locations == ["San Francisco, CA"]
    assert listing.ats == "greenhouse"
    assert listing.source == "greenhouse:acme"
    assert listing.first_seen == NOW


@pytest.mark.live
def test_fetch_live_smoke():
    listings = greenhouse.fetch(Company(name="Stripe", ats="greenhouse", board="stripe"), NOW)
    assert isinstance(listings, list)
