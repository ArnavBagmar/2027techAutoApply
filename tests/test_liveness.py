from datetime import datetime, timezone

import pytest
import requests

from scraper import liveness
from scraper.liveness import (
    DEAD_THRESHOLD,
    LivenessStats,
    check_url,
    classify_response,
    run_liveness,
    workday_cxs_url,
)
from scraper.models import Listing


class FakeResponse:
    def __init__(self, status_code: int, text: str = "job page"):
        self.status_code = status_code
        self.text = text


@pytest.mark.parametrize(
    ("status", "body", "verdict"),
    [
        (404, "", "dead"),
        (410, "", "dead"),
        (200, "Apply now to this role", "alive"),
        (200, "Sorry, Job Not Found", "dead"),
        (200, "This posting is no longer available.", "dead"),
        (200, "We are no longer accepting applications", "dead"),
        (200, "This position has been filled", "dead"),
        (200, "this job is no longer active", "dead"),
        (403, "", "unknown"),
        (429, "", "unknown"),
        (500, "", "unknown"),
        (503, "", "unknown"),
        (301, "", "unknown"),
    ],
)
def test_classify_response(status, body, verdict):
    assert classify_response(status, body) == verdict


def test_check_url_returns_verdict(monkeypatch):
    monkeypatch.setattr(liveness.requests, "get", lambda url, **kwargs: FakeResponse(404))
    assert check_url("https://example.com/job/1") == "dead"


def test_check_url_timeout_is_unknown(monkeypatch):
    def boom(url, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(liveness.requests, "get", boom)
    assert check_url("https://example.com/job/1") == "unknown"


def test_check_url_any_exception_is_unknown(monkeypatch):
    def boom(url, **kwargs):
        raise ValueError("weird")

    monkeypatch.setattr(liveness.requests, "get", boom)
    assert check_url("https://example.com/job/1") == "unknown"


def test_check_url_sends_browser_user_agent(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse(200)

    monkeypatch.setattr(liveness.requests, "get", fake_get)
    check_url("https://example.com/job/1")
    assert "Mozilla" in captured["headers"]["User-Agent"]
    assert captured["timeout"] == 10.0


def test_workday_url_is_translated_to_cxs(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse(200, "{}")

    monkeypatch.setattr(liveness.requests, "get", fake_get)
    check_url(
        "https://leidos.wd5.myworkdayjobs.com/External/job/Chantilly-VA/Software-Engineer-Intern_R-00183714"
    )
    assert captured["url"] == (
        "https://leidos.wd5.myworkdayjobs.com/wday/cxs/leidos/External"
        "/job/Chantilly-VA/Software-Engineer-Intern_R-00183714"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/McLean-VA/Program_R246020-1",
            "https://capitalone.wd12.myworkdayjobs.com/wday/cxs/capitalone/Capital_One"
            "/job/McLean-VA/Program_R246020-1",
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/en-US/External/job/Boston-MA/SWE-Intern_R1",
            "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/job/Boston-MA/SWE-Intern_R1",
        ),
        ("https://boards.greenhouse.io/acme/jobs/1", None),
        ("https://acme.wd1.myworkdayjobs.com/External", None),
    ],
)
def test_workday_cxs_url(url, expected):
    assert workday_cxs_url(url) == expected


NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)


def make_listing(id_: str, **overrides) -> Listing:
    defaults = dict(
        id=id_,
        company="Acme",
        title="SWE Intern, Summer 2027",
        category="swe",
        locations=["San Francisco, CA"],
        url=f"https://example.com/job/{id_}",
        ats="community",
        source="community:org/repo",
        first_seen=NOW,
        active=True,
        closed_at=None,
        dead_checks=0,
    )
    return Listing(**{**defaults, **overrides})


def test_only_active_community_listings_are_checked():
    ats = make_listing("ats1", ats="greenhouse", source="greenhouse:acme")
    inactive = make_listing("old1", active=False, closed_at=NOW)
    community = make_listing("com1")
    checked_urls = []

    def check(url):
        checked_urls.append(url)
        return "alive"

    _, stats = run_liveness([ats, inactive, community], {"ats1", "old1", "com1"}, NOW, check)
    assert checked_urls == [community.url]
    assert stats == LivenessStats(checked=1, dead=0, archived=0)


def test_new_dead_listing_is_archived_immediately():
    listing = make_listing("new1")
    updated, stats = run_liveness([listing], set(), NOW, lambda url: "dead")
    assert updated[0].active is False
    assert updated[0].closed_at == NOW
    assert updated[0].dead_checks == DEAD_THRESHOLD
    assert stats == LivenessStats(checked=1, dead=1, archived=1)


def test_existing_dead_listing_needs_two_strikes():
    listing = make_listing("com1")
    first, stats1 = run_liveness([listing], {"com1"}, NOW, lambda url: "dead")
    assert first[0].active is True
    assert first[0].dead_checks == 1
    assert stats1 == LivenessStats(checked=1, dead=1, archived=0)

    second, stats2 = run_liveness(first, {"com1"}, NOW, lambda url: "dead")
    assert second[0].active is False
    assert second[0].closed_at == NOW
    assert second[0].dead_checks == DEAD_THRESHOLD
    assert stats2 == LivenessStats(checked=1, dead=1, archived=1)


def test_alive_resets_dead_checks():
    listing = make_listing("com1", dead_checks=1)
    updated, _ = run_liveness([listing], {"com1"}, NOW, lambda url: "alive")
    assert updated[0].dead_checks == 0
    assert updated[0].active is True


def test_unknown_never_counts_toward_archival():
    listing = make_listing("com1", dead_checks=1)
    updated, stats = run_liveness([listing], {"com1"}, NOW, lambda url: "unknown")
    assert updated[0].dead_checks == 0
    assert updated[0].active is True
    assert stats == LivenessStats(checked=1, dead=0, archived=0)


def test_run_liveness_does_not_mutate_inputs():
    listing = make_listing("com1", dead_checks=1)
    run_liveness([listing], {"com1"}, NOW, lambda url: "dead")
    assert listing.dead_checks == 1
    assert listing.active is True


def test_run_liveness_preserves_order():
    listings = [
        make_listing("b", ats="greenhouse", source="greenhouse:acme"),
        make_listing("a"),
        make_listing("c"),
    ]
    updated, _ = run_liveness(listings, {"a", "b", "c"}, NOW, lambda url: "alive")
    assert [item.id for item in updated] == ["b", "a", "c"]
