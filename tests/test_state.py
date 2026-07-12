from datetime import datetime, timezone

from autoapply.state import load_state, save_state, select_pending, with_status
from scraper.models import Listing

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)


def make_listing(id_: str, active: bool = True) -> Listing:
    return Listing(
        id=id_,
        company="Acme",
        title="SWE Intern, Summer 2027",
        category="swe",
        locations=["San Francisco, CA"],
        url=f"https://example.com/{id_}",
        ats="greenhouse",
        source="greenhouse:acme",
        first_seen=NOW,
        active=active,
    )


def test_with_status_returns_new_dict():
    state = {}
    updated = with_status(state, "a", "submitted", NOW)
    assert state == {}
    assert updated["a"].status == "submitted"
    assert updated["a"].updated_at == NOW


def test_roundtrip_through_file(tmp_path):
    path = tmp_path / "applied.json"
    state = with_status({}, "a", "skipped", NOW)
    save_state(path, state)
    loaded = load_state(path)
    assert loaded["a"].status == "skipped"


def test_load_missing_file_returns_empty(tmp_path):
    assert load_state(tmp_path / "applied.json") == {}


def test_select_pending_skips_done_and_inactive():
    listings = [make_listing("a"), make_listing("b"), make_listing("c", active=False)]
    state = with_status({}, "a", "submitted", NOW)
    assert [item.id for item in select_pending(listings, state)] == ["b"]
