# Community-Listing Liveness Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify community-sourced listing URLs are live before they appear on the README, and automatically archive ones that die later — without ever archiving a live job on a transient error.

**Architecture:** A new `scraper/liveness.py` module classifies a URL as `alive`/`dead`/`unknown` (with a Workday JSON-endpoint special case) and applies verdicts to merged listings: 2 consecutive `dead` verdicts archive a listing; a `dead` verdict on a brand-new listing blocks it from ever being published. `merge()` is changed to never resurrect a listing whose `dead_checks` hit the threshold. The step runs inside `scraper.main` between `merge()` and `write_outputs()` — no new workflow.

**Tech Stack:** Python 3.11+, requests, pydantic v2, pytest (mocked HTTP via monkeypatch — no live network in tests).

**Spec:** `docs/superpowers/specs/2026-07-12-listing-liveness-design.md`

## Global Constraints

- Only community listings are checked: `listing.source.startswith("community:")` and `listing.active` is true.
- Verdicts: HTTP 404/410 → `dead`; HTTP 200 + tombstone pattern → `dead`; HTTP 200 otherwise → `alive`; 403/429/5xx/timeout/connection error/any exception → `unknown`.
- `unknown` NEVER increments `dead_checks`; both `alive` and `unknown` reset it to 0.
- `DEAD_THRESHOLD = 2`, defined in `scraper/liveness.py`.
- All Listing updates via `model_copy` — never mutate.
- A total liveness-step failure must log and leave listings unchanged; it can never block the publish.
- ruff line-length is 100; run `ruff format` and `ruff check` before each commit.
- Tests must not hit the network.

---

### Task 1: Add `dead_checks` field to Listing

**Files:**
- Modify: `scraper/models.py` (Listing class, ~line 20-31)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Listing.dead_checks: int` (default 0), serialized in `listings.json`. Later tasks read and `model_copy`-update this field.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_listing_dead_checks_defaults_to_zero():
    listing = Listing(
        id="a" * 40,
        company="Acme",
        title="SWE Intern, Summer 2027",
        category="swe",
        locations=["San Francisco, CA"],
        url="https://example.com/job/1",
        ats="community",
        source="community:org/repo",
        first_seen=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    assert listing.dead_checks == 0
    assert listing.model_dump(mode="json")["dead_checks"] == 0
```

Check the imports at the top of `tests/test_models.py` — ensure `from datetime import datetime, timezone` and `from scraper.models import Listing` are present (add whichever is missing; keep existing imports).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_listing_dead_checks_defaults_to_zero -v`
Expected: FAIL with `AttributeError: 'Listing' object has no attribute 'dead_checks'` (or KeyError on the dump).

- [ ] **Step 3: Write minimal implementation**

In `scraper/models.py`, add one field to `Listing` after `closed_at`:

```python
class Listing(BaseModel):
    id: str
    company: str
    title: str
    category: Category
    locations: list[str]
    url: str
    ats: str
    source: str
    first_seen: datetime
    active: bool = True
    closed_at: datetime | None = None
    dead_checks: int = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: all PASS (new test plus existing ones — the default keeps old `listings.json` entries deserializing).

- [ ] **Step 5: Commit**

```bash
ruff format scraper/models.py tests/test_models.py && ruff check scraper tests
git add scraper/models.py tests/test_models.py
git commit -m "feat: add dead_checks counter to Listing model"
```

---

### Task 2: URL classifier with Workday special case

**Files:**
- Create: `scraper/liveness.py`
- Test: `tests/test_liveness.py` (new file)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `Verdict = Literal["alive", "dead", "unknown"]`
  - `DEAD_THRESHOLD: int = 2`
  - `check_url(url: str, timeout: float = 10.0) -> Verdict`
  - `workday_cxs_url(url: str) -> str | None` (None for non-Workday URLs)
  - `classify_response(status: int, body: str) -> Verdict`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_liveness.py`:

```python
import pytest
import requests

from scraper import liveness
from scraper.liveness import check_url, classify_response, workday_cxs_url


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
    monkeypatch.setattr(
        liveness.requests, "get", lambda url, **kwargs: FakeResponse(404)
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_liveness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.liveness'`.

- [ ] **Step 3: Write the implementation**

Create `scraper/liveness.py`:

```python
import re
from typing import Literal
from urllib.parse import urlsplit

import requests

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_liveness.py -v`
Expected: all PASS.

Note: the 301 row in `test_classify_response` documents that a non-followed redirect is inconclusive — `check_url` follows redirects, so `classify_response` only ever sees a 3xx if redirects were exhausted.

- [ ] **Step 5: Commit**

```bash
ruff format scraper/liveness.py tests/test_liveness.py && ruff check scraper tests
git add scraper/liveness.py tests/test_liveness.py
git commit -m "feat: add url liveness classifier with workday cxs translation"
```

---

### Task 3: Liveness step — apply verdicts to merged listings

**Files:**
- Modify: `scraper/liveness.py` (append to the file from Task 2)
- Test: `tests/test_liveness.py` (append)

**Interfaces:**
- Consumes: `Listing` (with `dead_checks` from Task 1), `check_url`, `DEAD_THRESHOLD`, `Verdict` from Task 2.
- Produces:
  - `LivenessStats(NamedTuple)` with `checked: int, dead: int, archived: int`
  - `run_liveness(listings: list[Listing], previous_ids: set[str], now: datetime, check: Callable[[str], Verdict] = check_url) -> tuple[list[Listing], LivenessStats]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_liveness.py`:

```python
from datetime import datetime, timezone

from scraper.liveness import DEAD_THRESHOLD, LivenessStats, run_liveness
from scraper.models import Listing

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_liveness.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'LivenessStats'`.

- [ ] **Step 3: Write the implementation**

In `scraper/liveness.py`, extend the imports at the top of the file to:

```python
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal, NamedTuple
from urllib.parse import urlsplit

import requests

from scraper.models import Listing
```

Append after `check_url`:

```python
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
        return listing.model_copy(
            update={"dead_checks": checks, "active": False, "closed_at": now}
        )
    return listing.model_copy(update={"dead_checks": checks})


def run_liveness(
    listings: list[Listing],
    previous_ids: set[str],
    now: datetime,
    check: Callable[[str], Verdict] = check_url,
) -> tuple[list[Listing], LivenessStats]:
    targets = [
        item for item in listings if item.active and item.source.startswith("community:")
    ]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_liveness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
ruff format scraper/liveness.py tests/test_liveness.py && ruff check scraper tests
git add scraper/liveness.py tests/test_liveness.py
git commit -m "feat: add liveness step with two-strike archival and ingest gate"
```

---

### Task 4: merge() preserves dead_checks and never resurrects dead-linked listings

**Files:**
- Modify: `scraper/merge.py`
- Test: `tests/test_merge.py` (append)

**Interfaces:**
- Consumes: `Listing.dead_checks` (Task 1), `DEAD_THRESHOLD` from `scraper.liveness` (Task 2).
- Produces: unchanged signature `merge(previous, fetched, now, sources_ok) -> list[Listing]` with the two new rules. This is the primary regression guard against archived listings flapping back onto the README.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_merge.py` (the `make` helper at the top of the file already exists — do not redefine it):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merge.py -v`
Expected: the two new tests FAIL (`active` is `True` in the first, `dead_checks == 0` in the second). All existing tests still PASS.

- [ ] **Step 3: Write the implementation**

In `scraper/merge.py`, update the imports and replace the `merge` function:

```python
from datetime import datetime

from scraper.liveness import DEAD_THRESHOLD
from scraper.models import Listing
```

```python
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
```

(`dedupe` stays exactly as it is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merge.py tests/test_liveness.py -v`
Expected: all PASS — including the pre-existing `test_reappearing_listing_is_revived`, which still holds because its previous record has `dead_checks=0` (an ATS closure, not a dead link).

- [ ] **Step 5: Commit**

```bash
ruff format scraper/merge.py tests/test_merge.py && ruff check scraper tests
git add scraper/merge.py tests/test_merge.py
git commit -m "feat: never resurrect dead-linked listings in merge"
```

---

### Task 5: Wire liveness into scraper.main with failure containment and reporting

**Files:**
- Modify: `scraper/main.py` (imports; `report` ~line 43; tail of `run` ~line 85-88)
- Test: `tests/test_main.py` (append)

**Interfaces:**
- Consumes: `run_liveness`, `LivenessStats`, `check_url` from Task 3.
- Produces: `report(merged, previous_ids, failures, liveness_stats: LivenessStats)` — new fourth parameter; summary line `- liveness: checked N, dead M, archived K`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py` (module already imports `json`, `scraper.main as main`, `Listing`, and defines `NOW`, `LISTING`, `setup_repo`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: new tests FAIL with `AttributeError: module 'scraper.main' has no attribute 'liveness'` (first) / `'run_liveness'` (second).

- [ ] **Step 3: Write the implementation**

In `scraper/main.py`:

Add imports (keep existing ones):

```python
from scraper import liveness
from scraper.liveness import LivenessStats, run_liveness
```

Replace `report` with:

```python
def report(
    merged: list[Listing],
    previous_ids: set[str],
    failures: list[str],
    liveness_stats: LivenessStats,
) -> None:
    new = sum(1 for item in merged if item.active and item.id not in previous_ids)
    open_count = sum(1 for item in merged if item.active)
    lines = [
        "## Listings update",
        f"- open: {open_count}, new this run: {new}",
        (
            f"- liveness: checked {liveness_stats.checked}, "
            f"dead {liveness_stats.dead}, archived {liveness_stats.archived}"
        ),
        f"- failed sources: {len(failures)}",
    ] + [f"  - {failure}" for failure in failures]
    text = "\n".join(lines)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as handle:
            handle.write(text + "\n")
```

In `run`, replace the last four lines (`merged = ...` through `return 0`) with:

```python
    merged = merge(previous, fetched, now, sources_ok)
    previous_ids = {item.id for item in previous}
    try:
        merged, liveness_stats = run_liveness(
            merged, previous_ids, now, check=liveness.check_url
        )
    except Exception as error:  # a broken checker must never block the publish
        print(f"liveness step failed, skipping: {error}", file=sys.stderr)
        liveness_stats = LivenessStats(checked=0, dead=0, archived=0)
    write_outputs(root, merged, now)
    report(merged, previous_ids, failures, liveness_stats)
    return 0
```

Note: `check=liveness.check_url` (attribute lookup at call time, not a from-import binding) is what lets the test monkeypatch `main.liveness.check_url`.

- [ ] **Step 4: Run the full suite**

Run: `pytest`
Expected: all PASS, including the two pre-existing `test_main.py` tests (their runs have zero community targets, so `run_liveness` no-ops).

- [ ] **Step 5: Commit**

```bash
ruff format scraper/main.py tests/test_main.py && ruff check scraper tests
git add scraper/main.py tests/test_main.py
git commit -m "feat: run liveness checks in scrape pipeline with failure containment"
```

---

### Task 6: One-shot live smoke test (manual verification, no code committed)

**Files:**
- None created — manual verification only.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Run the classifier against a handful of real URLs**

```bash
python -c "
from scraper.liveness import check_url
for url in [
    'https://job-boards.greenhouse.io/andurilindustries/jobs/5148079007',
    'https://boards.greenhouse.io/nonexistent-board/jobs/1',
    'https://leidos.wd5.myworkdayjobs.com/External/job/Chantilly-VA/Software-Engineer-Intern_R-00183714',
]:
    print(check_url(url), url)
"
```

Expected: first prints `alive` (or `unknown` if bot-blocked — acceptable), second prints `dead`, third prints `alive` or `dead` via the CxS endpoint and must NOT crash. If the Workday URL prints `unknown`, inspect the CxS response manually before shipping — the translation may need a locale-segment fix.

- [ ] **Step 2: Run the full pipeline locally and inspect the diff**

```bash
python -m scraper.main && git diff --stat data/listings.json README.md ARCHIVED.md
```

Expected: exits 0; the printed summary includes the `liveness:` line; any listings newly moved to ARCHIVED.md have genuinely dead URLs (spot-check 2-3 in a browser). Revert the data diff with `git checkout -- data/listings.json README.md ARCHIVED.md` if you don't want to commit it (the hourly workflow will regenerate it anyway).

- [ ] **Step 3: Final green check**

```bash
ruff check scraper tests && pytest
git status  # clean except intentional data changes
```

---

## Self-Review Notes

- Spec coverage: classifier table (Task 2), Workday CxS (Task 2), `dead_checks` model field (Task 1), two-strike + ingest gate + reset-on-unknown (Task 3), merge no-resurrect + preserve (Task 4), failure containment + `GITHUB_STEP_SUMMARY` line (Task 5), rollout sanity (Task 6). No gaps.
- `DEAD_THRESHOLD` is imported by `merge.py` from `scraper.liveness` — no circular import (`liveness` imports only `models`).
- Ingest-gate archived listings get `closed_at=now` and land in ARCHIVED.md via the existing `render_archived`, matching the approved design choice.
