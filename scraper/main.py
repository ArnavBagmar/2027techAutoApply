import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scraper.merge import merge
from scraper.models import Company, Listing
from scraper.render import inject_section, render_archived, render_listings
from scraper.sources import ashby, community, greenhouse, lever, smartrecruiters

FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def load_companies(path: Path) -> list[Company]:
    return [Company.model_validate(entry) for entry in yaml.safe_load(path.read_text())]


def load_previous(path: Path) -> list[Listing]:
    if not path.exists():
        return []
    return [Listing.model_validate(entry) for entry in json.loads(path.read_text())]


def write_outputs(root: Path, listings: list[Listing], now: datetime) -> None:
    payload = [item.model_dump(mode="json") for item in listings]
    (root / "data" / "listings.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    readme_path = root / "README.md"
    readme_path.write_text(
        inject_section(readme_path.read_text(), render_listings(listings, now))
    )
    (root / "ARCHIVED.md").write_text(render_archived(listings))


def report(merged: list[Listing], previous_ids: set[str], failures: list[str]) -> None:
    new = sum(1 for item in merged if item.active and item.id not in previous_ids)
    open_count = sum(1 for item in merged if item.active)
    lines = [
        "## Listings update",
        f"- open: {open_count}, new this run: {new}",
        f"- failed sources: {len(failures)}",
    ] + [f"  - {failure}" for failure in failures]
    text = "\n".join(lines)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as handle:
            handle.write(text + "\n")


def run(root: Path, now: datetime) -> int:
    companies = load_companies(root / "data" / "companies.yaml")
    previous = load_previous(root / "data" / "listings.json")

    fetched: list[Listing] = []
    sources_ok: set[str] = set()
    failures: list[str] = []
    for company in companies:
        source = f"{company.ats}:{company.board}"
        try:
            fetched.extend(FETCHERS[company.ats](company, now))
            sources_ok.add(source)
        except Exception as error:  # one bad source never kills the run
            failures.append(f"{source}: {error}")

    community_listings, community_ok = community.fetch_all(now)
    fetched.extend(community_listings)
    sources_ok |= community_ok

    total = len(companies) + len(community.COMMUNITY_SOURCES)
    if len(sources_ok) * 2 < total:
        print(
            f"Aborting without writing: only {len(sources_ok)}/{total} sources OK",
            file=sys.stderr,
        )
        return 1

    merged = merge(previous, fetched, now, sources_ok)
    write_outputs(root, merged, now)
    report(merged, {item.id for item in previous}, failures)
    return 0


if __name__ == "__main__":
    sys.exit(run(Path.cwd(), datetime.now(timezone.utc)))
