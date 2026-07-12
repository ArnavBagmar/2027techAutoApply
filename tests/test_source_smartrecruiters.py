import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scraper.models import Company
from scraper.sources import smartrecruiters

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="smartrecruiters", board="Acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_builds_apply_url_and_location():
    listings = smartrecruiters.parse(load_fixture("smartrecruiters_postings.json"), ACME, NOW)
    assert [item.url for item in listings] == ["https://jobs.smartrecruiters.com/Acme/744000012345"]
    assert listings[0].locations == ["Santa Clara, CA"]


@pytest.mark.live
def test_fetch_live_smoke():
    listings = smartrecruiters.fetch(
        Company(name="ServiceNow", ats="smartrecruiters", board="ServiceNow"), NOW
    )
    assert isinstance(listings, list)
