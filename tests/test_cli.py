import json
from datetime import datetime, timezone

from autoapply.cli import build_parser, format_status, load_listings
from autoapply.state import with_status
from scraper.models import Listing

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)

LISTING = Listing(
    id="a" * 40,
    company="Acme",
    title="SWE Intern, Summer 2027",
    category="swe",
    locations=["San Francisco, CA"],
    url="https://boards.greenhouse.io/acme/jobs/111",
    ats="greenhouse",
    source="greenhouse:acme",
    first_seen=NOW,
)


def test_parser_has_three_subcommands():
    parser = build_parser()
    for command in ("init", "run", "status"):
        args = parser.parse_args([command])
        assert args.command == command


def test_load_listings(tmp_path):
    path = tmp_path / "listings.json"
    path.write_text(json.dumps([LISTING.model_dump(mode="json")]))
    listings = load_listings(path)
    assert listings[0].company == "Acme"


def test_format_status_counts():
    state = with_status({}, "a" * 40, "submitted", NOW)
    output = format_status([LISTING], state)
    assert "submitted: 1" in output
    assert "pending: 0" in output
