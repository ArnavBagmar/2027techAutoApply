import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal, NamedTuple
from urllib.parse import urlsplit

import requests

from scraper.models import Listing

Verdict = Literal["alive", "dead", "unknown"]

DEAD_THRESHOLD = 2
TIMEOUT = 10.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Conservative: extend only with wording verified on a real dead job page.
TOMBSTONE_RE = re.compile(
    r"job not found"
    r"|no longer accepting applications"
    r"|posting is no longer available"
    r"|this position has been filled"
    r"|this job is no longer active",
    re.IGNORECASE,
)

WORKDAY_HOST_RE = re.compile(r"^[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com$", re.IGNORECASE)


def workday_cxs_url(url: str) -> str | None:
    """Translate a public Workday job URL to its CxS JSON endpoint.

    Workday job pages are JS-rendered, so raw HTML is identical for live and
    dead jobs; the CxS endpoint 404s when the posting is gone.
    """
    parts = urlsplit(url)
    if not WORKDAY_HOST_RE.match(parts.netloc):
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if "job" not in segments:
        return None
    job_index = segments.index("job")
    if job_index == 0 or job_index == len(segments) - 1:
        return None
    tenant = parts.netloc.split(".")[0]
    site = segments[job_index - 1]
    rest = "/".join(segments[job_index + 1 :])
    return f"https://{parts.netloc}/wday/cxs/{tenant}/{site}/job/{rest}"


def classify_response(status: int, body: str) -> Verdict:
    if status in (404, 410):
        return "dead"
    if status == 200:
        return "dead" if TOMBSTONE_RE.search(body) else "alive"
    return "unknown"


def check_url(url: str, timeout: float = TIMEOUT) -> Verdict:
    target = workday_cxs_url(url) or url
    try:
        response = requests.get(
            target,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        return classify_response(response.status_code, response.text)
    except Exception:  # any failure is inconclusive, never "dead"
        return "unknown"


MAX_WORKERS = 8


class LivenessStats(NamedTuple):
    checked: int
    dead: int
    archived: int


def _apply_verdict(listing: Listing, verdict: Verdict, is_new: bool, now: datetime) -> Listing:
    if verdict != "dead":
        return listing.model_copy(update={"dead_checks": 0})
    checks = DEAD_THRESHOLD if is_new else listing.dead_checks + 1
    if checks >= DEAD_THRESHOLD:
        return listing.model_copy(update={"dead_checks": checks, "active": False, "closed_at": now})
    return listing.model_copy(update={"dead_checks": checks})


def run_liveness(
    listings: list[Listing],
    previous_ids: set[str],
    now: datetime,
    check: Callable[[str], Verdict] = check_url,
) -> tuple[list[Listing], LivenessStats]:
    targets = [item for item in listings if item.active and item.source.startswith("community:")]
    if not targets:
        return listings, LivenessStats(checked=0, dead=0, archived=0)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        verdicts = dict(
            zip([item.id for item in targets], pool.map(lambda item: check(item.url), targets))
        )
    updated = [
        _apply_verdict(item, verdicts[item.id], item.id not in previous_ids, now)
        if item.id in verdicts
        else item
        for item in listings
    ]
    archived = sum(
        1 for before, after in zip(listings, updated) if before.active and not after.active
    )
    dead = sum(1 for verdict in verdicts.values() if verdict == "dead")
    return updated, LivenessStats(checked=len(targets), dead=dead, archived=archived)
