import json
from datetime import datetime, timezone

import scraper.main as main
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

README = "intro\n<!-- LISTINGS:START -->\nold\n<!-- LISTINGS:END -->\n"


def setup_repo(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "companies.yaml").write_text(
        "- name: Acme\n  ats: greenhouse\n  board: acme\n"
    )
    (tmp_path / "README.md").write_text(README)


def test_run_writes_listings_readme_archive(tmp_path, monkeypatch):
    setup_repo(tmp_path)
    monkeypatch.setitem(main.FETCHERS, "greenhouse", lambda company, now: [LISTING])
    monkeypatch.setattr(main.community, "fetch_all", lambda now: ([], set()))

    assert main.run(tmp_path, NOW) == 0

    data = json.loads((tmp_path / "data" / "listings.json").read_text())
    assert len(data) == 1
    readme = (tmp_path / "README.md").read_text()
    assert "[Apply](https://boards.greenhouse.io/acme/jobs/111)" in readme
    assert (tmp_path / "ARCHIVED.md").exists()


def test_run_aborts_when_majority_of_sources_fail(tmp_path, monkeypatch):
    setup_repo(tmp_path)

    def boom(company, now):
        raise RuntimeError("api down")

    monkeypatch.setitem(main.FETCHERS, "greenhouse", boom)
    monkeypatch.setattr(main.community, "fetch_all", lambda now: ([], set()))

    assert main.run(tmp_path, NOW) == 1
    assert not (tmp_path / "data" / "listings.json").exists()


COMMUNITY_LISTING = Listing(
    id="b" * 40,
    company="Beta",
    title="SWE Intern, Summer 2027",
    category="swe",
    locations=["New York, NY"],
    url="https://example.com/job/dead",
    ats="community",
    source="community:org/repo",
    first_seen=NOW,
)


def test_run_blocks_new_dead_community_listing(tmp_path, monkeypatch):
    setup_repo(tmp_path)
    monkeypatch.setitem(main.FETCHERS, "greenhouse", lambda company, now: [LISTING])
    monkeypatch.setattr(
        main.community,
        "fetch_all",
        lambda now: ([COMMUNITY_LISTING], {"community:org/repo"}),
    )
    monkeypatch.setattr(main.liveness, "check_url", lambda url, timeout=10.0: "dead")

    assert main.run(tmp_path, NOW) == 0

    readme = (tmp_path / "README.md").read_text()
    assert "example.com/job/dead" not in readme
    data = {
        entry["id"]: entry
        for entry in json.loads((tmp_path / "data" / "listings.json").read_text())
    }
    assert data["b" * 40]["active"] is False
    assert data["b" * 40]["dead_checks"] == 2
    assert data["a" * 40]["active"] is True  # ATS listing untouched by liveness


def test_run_survives_total_liveness_failure(tmp_path, monkeypatch):
    setup_repo(tmp_path)
    monkeypatch.setitem(main.FETCHERS, "greenhouse", lambda company, now: [LISTING])
    monkeypatch.setattr(
        main.community,
        "fetch_all",
        lambda now: ([COMMUNITY_LISTING], {"community:org/repo"}),
    )

    def boom(listings, previous_ids, now, check=None):
        raise RuntimeError("network meltdown")

    monkeypatch.setattr(main, "run_liveness", boom)

    assert main.run(tmp_path, NOW) == 0
    readme = (tmp_path / "README.md").read_text()
    assert "example.com/job/dead" in readme  # unchecked listing still publishes
