from datetime import datetime, timedelta, timezone

from scraper.models import Listing
from scraper.render import inject_section, render_archived, render_listings

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)


def make(id_: str, **overrides) -> Listing:
    defaults = dict(
        id=id_,
        company="Acme",
        title="SWE Intern, Summer 2027",
        category="swe",
        locations=["San Francisco, CA"],
        url=f"https://example.com/{id_}",
        ats="greenhouse",
        source="greenhouse:acme",
        first_seen=NOW - timedelta(days=3),
        active=True,
        closed_at=None,
    )
    return Listing(**{**defaults, **overrides})


def test_new_listing_gets_marker_and_apply_link():
    section = render_listings([make("a", first_seen=NOW - timedelta(hours=2))], NOW)
    assert "🆕" in section
    assert "[Apply](https://example.com/a)" in section


def test_old_listing_has_no_marker():
    section = render_listings([make("a")], NOW)
    assert "🆕" not in section


def test_inactive_listings_only_in_archive():
    active = make("a")
    closed = make("b", active=False, closed_at=NOW)
    assert "example.com/b" not in render_listings([active, closed], NOW)
    archived = render_archived([active, closed])
    assert "example.com/b" in archived
    assert "example.com/a" not in archived


def test_inject_section_replaces_between_markers():
    text = "intro\n<!-- LISTINGS:START -->\nOLD\n<!-- LISTINGS:END -->\noutro"
    result = inject_section(text, "NEW")
    assert "OLD" not in result
    assert "NEW" in result
    assert result.startswith("intro")
    assert result.endswith("outro")
