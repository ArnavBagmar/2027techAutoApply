from datetime import datetime, timezone

from scraper.models import Company, Listing, canonical_url, listing_id


def test_canonical_url_strips_tracking_and_lowercases_host():
    url = "https://Boards.Greenhouse.io/stripe/jobs/123?gh_src=abc#app"
    assert canonical_url(url) == "https://boards.greenhouse.io/stripe/jobs/123"


def test_listing_id_is_stable_across_tracking_params():
    a = listing_id("https://boards.greenhouse.io/stripe/jobs/123?gh_src=a")
    b = listing_id("https://boards.greenhouse.io/stripe/jobs/123")
    assert a == b
    assert len(a) == 40


def test_listing_roundtrips_through_json():
    listing = Listing(
        id="x" * 40,
        company="Stripe",
        title="SWE Intern, Summer 2027",
        category="swe",
        locations=["San Francisco, CA"],
        url="https://boards.greenhouse.io/stripe/jobs/123",
        ats="greenhouse",
        source="greenhouse:stripe",
        first_seen=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    assert Listing.model_validate(listing.model_dump(mode="json")) == listing


def test_company_defaults():
    company = Company(name="Stripe", ats="greenhouse", board="stripe")
    assert company.category_hint == "swe"
    assert company.season_agnostic is False
