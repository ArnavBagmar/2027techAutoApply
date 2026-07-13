from datetime import datetime

from scraper.liveness import DEAD_THRESHOLD
from scraper.models import Listing


def dedupe(fetched: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    result: list[Listing] = []
    for listing in fetched:
        if listing.id not in seen:
            seen.add(listing.id)
            result.append(listing)
    return result


def merge(
    previous: list[Listing],
    fetched: list[Listing],
    now: datetime,
    sources_ok: set[str],
) -> list[Listing]:
    fetched_by_id = {listing.id: listing for listing in dedupe(fetched)}
    merged: list[Listing] = []
    for old in previous:
        new = fetched_by_id.pop(old.id, None)
        if new is not None and old.dead_checks >= DEAD_THRESHOLD:
            merged.append(old)  # dead link confirmed; upstream still lists it
        elif new is not None:
            merged.append(
                new.model_copy(
                    update={
                        "first_seen": old.first_seen,
                        "active": True,
                        "closed_at": None,
                        "dead_checks": old.dead_checks,
                    }
                )
            )
        elif old.active and old.source in sources_ok:
            merged.append(old.model_copy(update={"active": False, "closed_at": now}))
        else:
            merged.append(old)
    merged.extend(fetched_by_id.values())
    return sorted(merged, key=lambda item: (item.company.lower(), item.title.lower(), item.id))
