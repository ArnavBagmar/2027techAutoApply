import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Company
from scraper.sources import ashby

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="ashby", board="acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_skips_unlisted_and_non_intern():
    listings = ashby.parse(load_fixture("ashby_jobs.json"), ACME, NOW)
    assert [item.url for item in listings] == ["https://jobs.ashbyhq.com/acme/1111"]
    assert listings[0].source == "ashby:acme"
