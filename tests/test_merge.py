from datetime import datetime, timedelta, timezone

from scraper.merge import dedupe, merge
from scraper.models import Listing

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=3)


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
        first_seen=EARLIER,
        active=True,
        closed_at=None,
    )
    return Listing(**{**defaults, **overrides})


def test_new_listing_is_added():
    merged = merge([], [make("a", first_seen=NOW)], NOW, {"greenhouse:acme"})
    assert merged[0].first_seen == NOW
    assert merged[0].active is True


def test_existing_listing_keeps_original_first_seen():
    merged = merge([make("a")], [make("a", first_seen=NOW)], NOW, {"greenhouse:acme"})
    assert merged[0].first_seen == EARLIER


def test_missing_listing_from_healthy_source_is_closed():
    merged = merge([make("a")], [], NOW, {"greenhouse:acme"})
    assert merged[0].active is False
    assert merged[0].closed_at == NOW


def test_missing_listing_from_failed_source_is_untouched():
    merged = merge([make("a")], [], NOW, sources_ok=set())
    assert merged[0].active is True
    assert merged[0].closed_at is None


def test_reappearing_listing_is_revived():
    previous = [make("a", active=False, closed_at=EARLIER)]
    merged = merge(previous, [make("a", first_seen=NOW)], NOW, {"greenhouse:acme"})
    assert merged[0].active is True
    assert merged[0].closed_at is None
    assert merged[0].first_seen == EARLIER


def test_dedupe_keeps_first_occurrence():
    ats = make("a")
    community = make("a", source="community:org/repo")
    assert dedupe([ats, community]) == [ats]


def test_merge_does_not_mutate_inputs():
    previous = [make("a")]
    merge(previous, [], NOW, {"greenhouse:acme"})
    assert previous[0].active is True


def test_dead_linked_listing_is_never_resurrected():
    previous = [
        make(
            "a",
            source="community:org/repo",
            ats="community",
            active=False,
            closed_at=EARLIER,
            dead_checks=2,
        )
    ]
    fetched = [make("a", source="community:org/repo", ats="community", first_seen=NOW)]
    merged = merge(previous, fetched, NOW, {"community:org/repo"})
    assert merged[0].active is False
    assert merged[0].closed_at == EARLIER
    assert merged[0].dead_checks == 2


def test_merge_preserves_dead_checks_on_update():
    previous = [make("a", source="community:org/repo", ats="community", dead_checks=1)]
    fetched = [make("a", source="community:org/repo", ats="community", first_seen=NOW)]
    merged = merge(previous, fetched, NOW, {"community:org/repo"})
    assert merged[0].active is True
    assert merged[0].dead_checks == 1
