# Listings Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the hourly pipeline that discovers Summer 2027 internships from public ATS APIs + community lists, maintains `data/listings.json`, and regenerates README/ARCHIVED tables via GitHub Actions.

**Architecture:** Pure-function core (parse → filter → merge → render) with I/O at the edges (`fetch` per source, `main.py` orchestrator). Every source is isolated; one failure never kills a run. GitHub Actions cron commits only when output changed.

**Tech Stack:** Python 3.12, pydantic v2, requests, PyYAML, pytest + pytest-cov, ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-12-internship-list-autoapply-design.md`

## Global Constraints

- Python `>=3.11` locally; GitHub Actions uses 3.12.
- Runtime deps (this plan): `requests>=2.31`, `pydantic>=2.5`, `PyYAML>=6.0`. Dev: `pytest>=8`, `pytest-cov>=5`, `ruff>=0.4`.
- All timestamps are timezone-aware UTC; serialized as ISO-8601.
- `listings.json` is written sorted by `(company.lower(), title.lower(), id)` with `indent=2, sort_keys=True` and a trailing newline so a no-change run is byte-identical (no empty commits).
- Never mutate: merge/filter/render build new objects (`model_copy`, new lists).
- CI coverage gate: 80%. Conventional commit messages (`feat:`, `test:`, `chore:`…), no attribution lines.
- README generated block lives between `<!-- LISTINGS:START -->` and `<!-- LISTINGS:END -->`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `scraper/__init__.py`, `scraper/sources/__init__.py`, `tests/__init__.py`, `tests/test_sanity.py`, `.gitignore`

**Interfaces:**
- Produces: installable `internships-2027` project; `pytest` and `ruff` runnable. Later tasks add modules under `scraper/`.

- [ ] **Step 1: Write the failing test**

`tests/test_sanity.py`:
```python
def test_scraper_package_imports():
    import scraper  # noqa: F401
    import scraper.sources  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sanity.py -v`
Expected: FAIL / error with `ModuleNotFoundError: No module named 'scraper'`

- [ ] **Step 3: Create the project files**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "internships-2027"
version = "0.1.0"
description = "Summer 2027 tech internship list + semi-automated apply tool"
requires-python = ">=3.11"
dependencies = [
  "requests>=2.31",
  "pydantic>=2.5",
  "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "ruff>=0.4"]

[tool.setuptools]
packages = ["scraper", "scraper.sources"]

[tool.pytest.ini_options]
addopts = "-q"
markers = ["live: hits real external APIs (excluded from CI)"]

[tool.ruff]
line-length = 100
```

Create empty `scraper/__init__.py`, `scraper/sources/__init__.py`, `tests/__init__.py`.

`.gitignore`:
```
__pycache__/
*.egg-info/
.coverage
.venv/
profile.yaml
applied.json
.browser-profile/
```

Then install: `pip install -e ".[dev]"`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sanity.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml scraper tests .gitignore
git commit -m "chore: scaffold python project"
```

---

### Task 2: Models and listing identity

**Files:**
- Create: `scraper/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Category = Literal["swe", "data-ml", "quant", "hardware"]`; `Company(name, ats, board, category_hint="swe", season_agnostic=False)`; `Listing(id, company, title, category, locations, url, ats, source, first_seen, active=True, closed_at=None)`; `canonical_url(url: str) -> str`; `listing_id(url: str) -> str` (sha1 hex of canonical URL).

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.models'`

- [ ] **Step 3: Write minimal implementation**

`scraper/models.py`:
```python
import hashlib
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel

Category = Literal["swe", "data-ml", "quant", "hardware"]
ATSName = Literal["greenhouse", "lever", "ashby", "smartrecruiters"]


class Company(BaseModel):
    name: str
    ats: ATSName
    board: str
    category_hint: Category = "swe"
    season_agnostic: bool = False


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


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path}".rstrip("/")


def listing_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scraper/models.py tests/test_models.py
git commit -m "feat: add Listing/Company models and canonical listing id"
```

---

### Task 3: Filters and categorization

**Files:**
- Create: `scraper/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `Category` from `scraper.models`.
- Produces: `is_internship(title: str) -> bool`; `matches_summer_2027(text: str, season_agnostic: bool = False) -> bool`; `categorize(title: str, hint: Category = "swe") -> Category`; `is_us(locations: list[str]) -> bool` (empty/"Unknown" lists count as US so unknown-location postings are kept).

- [ ] **Step 1: Write the failing test**

`tests/test_filters.py`:
```python
import pytest

from scraper.filters import categorize, is_internship, is_us, matches_summer_2027


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineering Intern", True),
        ("Software Engineering Internship - Summer 2027", True),
        ("Software Engineer Co-op", True),
        ("Internal Tools Engineer", False),
        ("International Sales Manager", False),
        ("Senior Software Engineer", False),
    ],
)
def test_is_internship(title, expected):
    assert is_internship(title) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SWE Intern (Summer 2027)", True),
        ("2027 Summer Software Intern", True),
        ("Summer 2026 Intern", False),
        ("SWE Intern", False),
    ],
)
def test_matches_summer_2027(text, expected):
    assert matches_summer_2027(text) is expected


def test_season_agnostic_bypasses_year_check():
    assert matches_summer_2027("SWE Intern", season_agnostic=True) is True


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Quantitative Trading Intern", "quant"),
        ("Machine Learning Intern", "data-ml"),
        ("Embedded Software Intern", "hardware"),
        ("Software Engineering Intern", "swe"),
    ],
)
def test_categorize(title, expected):
    assert categorize(title) == expected


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        (["San Francisco, CA"], True),
        (["New York, NY", "London, UK"], True),
        (["London, UK"], False),
        (["Remote - US"], True),
        (["Unknown"], True),
        ([], True),
    ],
)
def test_is_us(locations, expected):
    assert is_us(locations) is expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.filters'`

- [ ] **Step 3: Write minimal implementation**

`scraper/filters.py`:
```python
import re

from scraper.models import Category

INTERN_RE = re.compile(r"\b(intern|internship|co[- ]?op)\b", re.IGNORECASE)
EXCLUDE_RE = re.compile(r"\b(internal|international)\b", re.IGNORECASE)
SUMMER_2027_RE = re.compile(r"(summer.{0,40}2027|2027.{0,40}summer)", re.IGNORECASE | re.DOTALL)
US_STATE_RE = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|"
    r"NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
)
US_HINT_RE = re.compile(r"\b(united states|usa|u\.s\.|remote)\b", re.IGNORECASE)

CATEGORY_RULES: tuple[tuple[Category, "re.Pattern[str]"], ...] = (
    ("quant", re.compile(r"\b(quant\w*|trading|trader)\b", re.IGNORECASE)),
    ("hardware", re.compile(r"\b(hardware|embedded|fpga|asic|silicon|firmware)\b", re.IGNORECASE)),
    ("data-ml", re.compile(r"\b(data|machine learning|ml|ai|analytics)\b", re.IGNORECASE)),
)


def is_internship(title: str) -> bool:
    return bool(INTERN_RE.search(EXCLUDE_RE.sub(" ", title)))


def matches_summer_2027(text: str, season_agnostic: bool = False) -> bool:
    return season_agnostic or bool(SUMMER_2027_RE.search(text))


def categorize(title: str, hint: Category = "swe") -> Category:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(title):
            return category
    return hint


def is_us(locations: list[str]) -> bool:
    known = [loc for loc in locations if loc and loc.lower() != "unknown"]
    if not known:
        return True
    return any(US_STATE_RE.search(loc) or US_HINT_RE.search(loc) for loc in known)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filters.py -v`
Expected: PASS (all parametrized cases)

- [ ] **Step 5: Commit**

```bash
git add scraper/filters.py tests/test_filters.py
git commit -m "feat: add internship/season/region filters and categorization"
```

---

### Task 4: Source helpers + Greenhouse source

**Files:**
- Create: `scraper/sources/base.py`, `scraper/sources/greenhouse.py`, `tests/fixtures/greenhouse_jobs.json`
- Test: `tests/test_source_greenhouse.py`

**Interfaces:**
- Consumes: models (Task 2), filters (Task 3).
- Produces: `base.build_listing(company: Company, title: str, locations: list[str], url: str, now: datetime) -> Listing`; `base.keep(company, title, locations, url) -> bool`; `greenhouse.API` (str template with `{board}`); `greenhouse.parse(payload: dict, company: Company, now: datetime) -> list[Listing]`; `greenhouse.fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]`. Every later source module exposes the same `API`/`parse`/`fetch` trio.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/greenhouse_jobs.json` (shape of the real boards API response):
```json
{
  "jobs": [
    {
      "title": "Software Engineering Intern, Summer 2027",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/111?gh_src=x",
      "location": {"name": "San Francisco, CA"}
    },
    {
      "title": "Senior Software Engineer",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/222",
      "location": {"name": "New York, NY"}
    },
    {
      "title": "Software Engineering Intern, Summer 2027",
      "absolute_url": "https://boards.greenhouse.io/acme/jobs/333",
      "location": {"name": "London, UK"}
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_source_greenhouse.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scraper.models import Company
from scraper.sources import greenhouse

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="greenhouse", board="acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_keeps_only_matching_us_internships():
    listings = greenhouse.parse(load_fixture("greenhouse_jobs.json"), ACME, NOW)
    assert [item.url for item in listings] == [
        "https://boards.greenhouse.io/acme/jobs/111?gh_src=x"
    ]


def test_parse_maps_fields():
    listing = greenhouse.parse(load_fixture("greenhouse_jobs.json"), ACME, NOW)[0]
    assert listing.company == "Acme"
    assert listing.category == "swe"
    assert listing.locations == ["San Francisco, CA"]
    assert listing.ats == "greenhouse"
    assert listing.source == "greenhouse:acme"
    assert listing.first_seen == NOW


@pytest.mark.live
def test_fetch_live_smoke():
    listings = greenhouse.fetch(Company(name="Stripe", ats="greenhouse", board="stripe"), NOW)
    assert isinstance(listings, list)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_source_greenhouse.py -v -m "not live"`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.sources.greenhouse'`

- [ ] **Step 4: Write minimal implementation**

`scraper/sources/base.py`:
```python
from datetime import datetime

from scraper.filters import categorize, is_internship, is_us, matches_summer_2027
from scraper.models import Company, Listing, listing_id


def build_listing(
    company: Company, title: str, locations: list[str], url: str, now: datetime
) -> Listing:
    return Listing(
        id=listing_id(url),
        company=company.name,
        title=title,
        category=categorize(title, company.category_hint),
        locations=locations,
        url=url,
        ats=company.ats,
        source=f"{company.ats}:{company.board}",
        first_seen=now,
    )


def keep(company: Company, title: str, locations: list[str], url: str) -> bool:
    return bool(
        url
        and is_internship(title)
        and matches_summer_2027(title, company.season_agnostic)
        and is_us(locations)
    )
```

`scraper/sources/greenhouse.py`:
```python
from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


def parse(payload: dict[str, Any], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for job in payload.get("jobs", []):
        title = job.get("title") or ""
        url = job.get("absolute_url") or ""
        location = ((job.get("location") or {}).get("name")) or "Unknown"
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_source_greenhouse.py -v -m "not live"`
Expected: PASS (2 passed, 1 deselected)

- [ ] **Step 6: Commit**

```bash
git add scraper/sources tests/fixtures/greenhouse_jobs.json tests/test_source_greenhouse.py
git commit -m "feat: add source helpers and greenhouse source"
```

---

### Task 5: Lever source

**Files:**
- Create: `scraper/sources/lever.py`, `tests/fixtures/lever_postings.json`
- Test: `tests/test_source_lever.py`

**Interfaces:**
- Consumes: `build_listing`/`keep` from `scraper.sources.base`.
- Produces: `lever.API`, `lever.parse(payload: list, company, now) -> list[Listing]`, `lever.fetch(company, now, timeout=20.0) -> list[Listing]`. Note: Lever's payload is a JSON **list**, not a dict.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/lever_postings.json`:
```json
[
  {
    "text": "Software Engineering Intern (Summer 2027)",
    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
    "categories": {"location": "New York, NY"}
  },
  {
    "text": "Staff Software Engineer",
    "hostedUrl": "https://jobs.lever.co/acme/def-456",
    "categories": {"location": "Remote - US"}
  }
]
```

- [ ] **Step 2: Write the failing test**

`tests/test_source_lever.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Company
from scraper.sources import lever

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="lever", board="acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_keeps_only_internships():
    listings = lever.parse(load_fixture("lever_postings.json"), ACME, NOW)
    assert [item.url for item in listings] == ["https://jobs.lever.co/acme/abc-123"]


def test_parse_maps_fields():
    listing = lever.parse(load_fixture("lever_postings.json"), ACME, NOW)[0]
    assert listing.title == "Software Engineering Intern (Summer 2027)"
    assert listing.locations == ["New York, NY"]
    assert listing.source == "lever:acme"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_source_lever.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.sources.lever'`

- [ ] **Step 4: Write minimal implementation**

`scraper/sources/lever.py`:
```python
from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://api.lever.co/v0/postings/{board}?mode=json"


def parse(payload: list[dict[str, Any]], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for posting in payload:
        title = posting.get("text") or ""
        url = posting.get("hostedUrl") or ""
        location = (posting.get("categories") or {}).get("location") or "Unknown"
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_source_lever.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add scraper/sources/lever.py tests/fixtures/lever_postings.json tests/test_source_lever.py
git commit -m "feat: add lever source"
```

---

### Task 6: Ashby source

**Files:**
- Create: `scraper/sources/ashby.py`, `tests/fixtures/ashby_jobs.json`
- Test: `tests/test_source_ashby.py`

**Interfaces:**
- Produces: `ashby.API`, `ashby.parse(payload: dict, company, now)`, `ashby.fetch(company, now, timeout=20.0)`. Skips jobs with `isListed: false`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/ashby_jobs.json`:
```json
{
  "jobs": [
    {
      "title": "Software Engineer Intern - Summer 2027",
      "jobUrl": "https://jobs.ashbyhq.com/acme/1111",
      "location": "San Francisco, CA",
      "isListed": true
    },
    {
      "title": "Software Engineer Intern - Summer 2027",
      "jobUrl": "https://jobs.ashbyhq.com/acme/2222",
      "location": "San Francisco, CA",
      "isListed": false
    },
    {
      "title": "Engineering Manager",
      "jobUrl": "https://jobs.ashbyhq.com/acme/3333",
      "location": "San Francisco, CA",
      "isListed": true
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_source_ashby.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Company
from scraper.sources import ashby

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="ashby", board="acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_skips_unlisted_and_non_intern():
    listings = ashby.parse(load_fixture("ashby_jobs.json"), ACME, NOW)
    assert [item.url for item in listings] == ["https://jobs.ashbyhq.com/acme/1111"]
    assert listings[0].source == "ashby:acme"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_source_ashby.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.sources.ashby'`

- [ ] **Step 4: Write minimal implementation**

`scraper/sources/ashby.py`:
```python
from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def parse(payload: dict[str, Any], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for job in payload.get("jobs", []):
        if not job.get("isListed", True):
            continue
        title = job.get("title") or ""
        url = job.get("jobUrl") or ""
        location = job.get("location") or "Unknown"
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_source_ashby.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add scraper/sources/ashby.py tests/fixtures/ashby_jobs.json tests/test_source_ashby.py
git commit -m "feat: add ashby source"
```

---

### Task 7: SmartRecruiters source

**Files:**
- Create: `scraper/sources/smartrecruiters.py`, `tests/fixtures/smartrecruiters_postings.json`
- Test: `tests/test_source_smartrecruiters.py`

**Interfaces:**
- Produces: `smartrecruiters.API`, `parse(payload: dict, company, now)`, `fetch(company, now, timeout=20.0)`. Apply URL is built as `https://jobs.smartrecruiters.com/{board}/{posting_id}`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/smartrecruiters_postings.json`:
```json
{
  "content": [
    {
      "id": "744000012345",
      "name": "Software Engineer Intern (Summer 2027)",
      "location": {"city": "Santa Clara", "region": "CA", "country": "us"}
    },
    {
      "id": "744000067890",
      "name": "Principal Engineer",
      "location": {"city": "Santa Clara", "region": "CA", "country": "us"}
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_source_smartrecruiters.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import Company
from scraper.sources import smartrecruiters

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)
ACME = Company(name="Acme", ats="smartrecruiters", board="Acme")


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_builds_apply_url_and_location():
    listings = smartrecruiters.parse(
        load_fixture("smartrecruiters_postings.json"), ACME, NOW
    )
    assert [item.url for item in listings] == [
        "https://jobs.smartrecruiters.com/Acme/744000012345"
    ]
    assert listings[0].locations == ["Santa Clara, CA"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_source_smartrecruiters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.sources.smartrecruiters'`

- [ ] **Step 4: Write minimal implementation**

`scraper/sources/smartrecruiters.py`:
```python
from datetime import datetime
from typing import Any

import requests

from scraper.models import Company, Listing
from scraper.sources.base import build_listing, keep

API = "https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=100"
APPLY_URL = "https://jobs.smartrecruiters.com/{board}/{posting_id}"


def _location(raw: dict[str, Any]) -> str:
    parts = [raw.get("city"), raw.get("region")]
    return ", ".join(part for part in parts if part) or "Unknown"


def parse(payload: dict[str, Any], company: Company, now: datetime) -> list[Listing]:
    listings = []
    for posting in payload.get("content", []):
        title = posting.get("name") or ""
        posting_id = posting.get("id") or ""
        url = APPLY_URL.format(board=company.board, posting_id=posting_id) if posting_id else ""
        location = _location(posting.get("location") or {})
        if keep(company, title, [location], url):
            listings.append(build_listing(company, title, [location], url, now))
    return listings


def fetch(company: Company, now: datetime, timeout: float = 20.0) -> list[Listing]:
    response = requests.get(API.format(board=company.board), timeout=timeout)
    response.raise_for_status()
    return parse(response.json(), company, now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_source_smartrecruiters.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add scraper/sources/smartrecruiters.py tests/fixtures/smartrecruiters_postings.json tests/test_source_smartrecruiters.py
git commit -m "feat: add smartrecruiters source"
```

---

### Task 8: Community list source

**Files:**
- Create: `scraper/sources/community.py`, `tests/fixtures/community_listings.json`
- Test: `tests/test_source_community.py`

**Interfaces:**
- Produces: `community.COMMUNITY_SOURCES: dict[str, str]` (repo → raw JSON URL); `community.parse(payload: list, repo: str, now) -> list[Listing]`; `community.fetch_all(now, timeout=20.0) -> tuple[list[Listing], set[str]]` where the set contains `f"community:{repo}"` for each repo fetched successfully.
- ⚠️ Before implementing: verify the exact community repo names and raw-file paths with `curl -sI <raw url>` (they follow the SimplifyJobs `.github/scripts/listings.json` layout; the 2027 repo name must be confirmed on github.com at implementation time and put in `COMMUNITY_SOURCES`).

- [ ] **Step 1: Create the fixture**

`tests/fixtures/community_listings.json` (SimplifyJobs-style entries):
```json
[
  {
    "company_name": "Acme",
    "title": "Software Engineering Intern",
    "locations": ["Austin, TX"],
    "url": "https://boards.greenhouse.io/acme/jobs/999",
    "terms": ["Summer 2027"],
    "active": true
  },
  {
    "company_name": "Acme",
    "title": "Software Engineering Intern",
    "locations": ["Austin, TX"],
    "url": "https://boards.greenhouse.io/acme/jobs/888",
    "terms": ["Summer 2026"],
    "active": true
  },
  {
    "company_name": "Acme",
    "title": "Software Engineering Intern",
    "locations": ["Austin, TX"],
    "url": "https://boards.greenhouse.io/acme/jobs/777",
    "terms": ["Summer 2027"],
    "active": false
  }
]
```

- [ ] **Step 2: Write the failing test**

`tests/test_source_community.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

from scraper.sources import community

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)


def load_fixture(name: str):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_parse_keeps_active_summer_2027_only():
    listings = community.parse(load_fixture("community_listings.json"), "org/repo", NOW)
    assert [item.url for item in listings] == ["https://boards.greenhouse.io/acme/jobs/999"]


def test_parse_tags_source_and_ats():
    listing = community.parse(load_fixture("community_listings.json"), "org/repo", NOW)[0]
    assert listing.source == "community:org/repo"
    assert listing.ats == "community"
    assert listing.company == "Acme"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_source_community.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.sources.community'`

- [ ] **Step 4: Write minimal implementation**

`scraper/sources/community.py`:
```python
from datetime import datetime
from typing import Any

import requests

from scraper.filters import categorize, is_internship, is_us
from scraper.models import Listing, listing_id

# Verified at implementation time; must point at a machine-readable listings
# file in a community-maintained Summer 2027 internship repo.
COMMUNITY_SOURCES: dict[str, str] = {
    "SimplifyJobs/Summer2027-Internships": (
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships"
        "/dev/.github/scripts/listings.json"
    ),
}


def parse(payload: list[dict[str, Any]], repo: str, now: datetime) -> list[Listing]:
    listings = []
    for entry in payload:
        title = entry.get("title") or ""
        url = entry.get("url") or ""
        locations = entry.get("locations") or []
        terms = entry.get("terms") or []
        if not entry.get("active", True):
            continue
        if "Summer 2027" not in terms:
            continue
        if not (url and is_internship(title) and is_us(locations)):
            continue
        listings.append(
            Listing(
                id=listing_id(url),
                company=entry.get("company_name") or "Unknown",
                title=title,
                category=categorize(title),
                locations=locations,
                url=url,
                ats="community",
                source=f"community:{repo}",
                first_seen=now,
            )
        )
    return listings


def fetch_all(now: datetime, timeout: float = 20.0) -> tuple[list[Listing], set[str]]:
    listings: list[Listing] = []
    ok: set[str] = set()
    for repo, raw_url in COMMUNITY_SOURCES.items():
        try:
            response = requests.get(raw_url, timeout=timeout)
            response.raise_for_status()
            listings.extend(parse(response.json(), repo, now))
            ok.add(f"community:{repo}")
        except Exception as error:
            print(f"community source {repo} failed: {error}")
    return listings, ok
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_source_community.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add scraper/sources/community.py tests/fixtures/community_listings.json tests/test_source_community.py
git commit -m "feat: add community list source"
```

---

### Task 9: Merge and diff

**Files:**
- Create: `scraper/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `Listing`.
- Produces: `dedupe(fetched: list[Listing]) -> list[Listing]` (keeps first occurrence per id — callers put ATS sources before community so direct links win); `merge(previous: list[Listing], fetched: list[Listing], now: datetime, sources_ok: set[str]) -> list[Listing]` sorted by `(company.lower(), title.lower(), id)`.

- [ ] **Step 1: Write the failing test**

`tests/test_merge.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.merge'`

- [ ] **Step 3: Write minimal implementation**

`scraper/merge.py`:
```python
from datetime import datetime

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
        if new is not None:
            merged.append(
                new.model_copy(
                    update={"first_seen": old.first_seen, "active": True, "closed_at": None}
                )
            )
        elif old.active and old.source in sources_ok:
            merged.append(old.model_copy(update={"active": False, "closed_at": now}))
        else:
            merged.append(old)
    merged.extend(fetched_by_id.values())
    return sorted(merged, key=lambda item: (item.company.lower(), item.title.lower(), item.id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_merge.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add scraper/merge.py tests/test_merge.py
git commit -m "feat: add merge/diff with close-and-revive semantics"
```

---

### Task 10: Renderer + README/ARCHIVED skeletons

**Files:**
- Create: `scraper/render.py`, `README.md`, `ARCHIVED.md`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `render_listings(listings: list[Listing], now: datetime) -> str` (active only, grouped by category, newest first, 🆕 when `first_seen` < 24h); `render_archived(listings: list[Listing]) -> str` (inactive only); `inject_section(text: str, section: str) -> str` (replaces content between `<!-- LISTINGS:START -->` / `<!-- LISTINGS:END -->`).

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.render'`

- [ ] **Step 3: Write minimal implementation**

`scraper/render.py`:
```python
from datetime import datetime, timedelta

from scraper.models import Category, Listing

CATEGORY_TITLES: dict[Category, str] = {
    "swe": "💻 Software Engineering",
    "data-ml": "📊 Data Science & ML",
    "quant": "📈 Quant & Trading",
    "hardware": "🔧 Hardware & Embedded",
}
START = "<!-- LISTINGS:START -->"
END = "<!-- LISTINGS:END -->"
NEW_WINDOW = timedelta(hours=24)
TABLE_HEADER = [
    "| Company | Role | Location | Posted | Apply |",
    "| --- | --- | --- | --- | --- |",
]


def _row(listing: Listing, marker: str) -> str:
    locations = "; ".join(listing.locations) or "Unknown"
    posted = listing.first_seen.strftime("%b %d")
    return (
        f"| {marker}{listing.company} | {listing.title} | {locations} "
        f"| {posted} | [Apply]({listing.url}) |"
    )


def render_listings(listings: list[Listing], now: datetime) -> str:
    active = [item for item in listings if item.active]
    lines = [
        f"_Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')} — "
        f"{len(active)} open positions_"
    ]
    for category, title in CATEGORY_TITLES.items():
        rows = sorted(
            (item for item in active if item.category == category),
            key=lambda item: item.first_seen,
            reverse=True,
        )
        if not rows:
            continue
        lines += ["", f"## {title}", ""] + TABLE_HEADER
        lines += [
            _row(item, "🆕 " if now - item.first_seen < NEW_WINDOW else "") for item in rows
        ]
    return "\n".join(lines)


def render_archived(listings: list[Listing]) -> str:
    closed = sorted(
        (item for item in listings if not item.active),
        key=lambda item: item.closed_at or item.first_seen,
        reverse=True,
    )
    lines = ["# Archived listings", "", "Roles that are no longer accepting applications.", ""]
    lines += TABLE_HEADER
    lines += [_row(item, "") for item in closed]
    return "\n".join(lines) + "\n"


def inject_section(text: str, section: str) -> str:
    before, _, rest = text.partition(START)
    _, _, after = rest.partition(END)
    return f"{before}{START}\n{section}\n{END}{after}"
```

`README.md` (static skeleton; the generated block gets replaced hourly):
```markdown
# Summer 2027 Tech Internships ☀️

Auto-updated **every hour** with new Summer 2027 internship postings — SWE,
Data/ML, Quant, and Hardware, US-focused. Star ⭐ the repo to keep it handy.

**Want to apply faster?** Clone this repo and use the included semi-automated
apply tool — it fills applications from your profile and lets **you** review and
submit each one. See [docs/SETUP.md](docs/SETUP.md) and the
[DISCLAIMER](DISCLAIMER.md).

Closed roles move to [ARCHIVED.md](ARCHIVED.md).
Want a company added? See [CONTRIBUTING.md](CONTRIBUTING.md).

<!-- LISTINGS:START -->
_First scrape pending…_
<!-- LISTINGS:END -->
```

`ARCHIVED.md`:
```markdown
# Archived listings

Roles that are no longer accepting applications.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scraper/render.py tests/test_render.py README.md ARCHIVED.md
git commit -m "feat: add markdown renderer and README skeleton"
```

---

### Task 11: Orchestrator + seed company list

**Files:**
- Create: `scraper/main.py`, `data/companies.yaml`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: every prior module.
- Produces: `main.FETCHERS: dict[str, Callable]`; `main.run(root: Path, now: datetime) -> int` (0 = success, 1 = aborted); `python -m scraper.main` entry point. Writes `data/listings.json`, `README.md`, `ARCHIVED.md`; appends a summary to `$GITHUB_STEP_SUMMARY` when set. Aborts without writing when >50% of sources fail.

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.main'`

- [ ] **Step 3: Write minimal implementation**

`scraper/main.py`:
```python
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
```

`data/companies.yaml` — seed list. ⚠️ Verify every board token before committing, e.g.:
`curl -s "https://boards-api.greenhouse.io/v1/boards/stripe/jobs" | head -c 300` (expect JSON, not 404). Drop or fix any token that 404s.
```yaml
- name: Stripe
  ats: greenhouse
  board: stripe
- name: Databricks
  ats: greenhouse
  board: databricks
- name: Figma
  ats: greenhouse
  board: figma
- name: Duolingo
  ats: greenhouse
  board: duolingo
- name: Anthropic
  ats: greenhouse
  board: anthropic
- name: Palantir
  ats: lever
  board: palantir
- name: Plaid
  ats: lever
  board: plaid
- name: Ramp
  ats: ashby
  board: ramp
- name: Notion
  ats: ashby
  board: notion
- name: OpenAI
  ats: ashby
  board: openai
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite + a real end-to-end scrape**

Run: `pytest -m "not live" --cov=scraper --cov-fail-under=80`
Expected: PASS with coverage ≥ 80%

Run: `python -m scraper.main && git diff --stat`
Expected: `data/listings.json` created with real listings; README tables populated. Inspect README rendering locally before committing.

- [ ] **Step 6: Commit**

```bash
git add scraper/main.py data/companies.yaml tests/test_main.py data/listings.json README.md ARCHIVED.md
git commit -m "feat: add scrape orchestrator and seed company list"
```

---

### Task 12: GitHub Actions workflows + repo docs

**Files:**
- Create: `.github/workflows/update-listings.yml`, `.github/workflows/ci.yml`, `CONTRIBUTING.md`

**Interfaces:**
- Consumes: `python -m scraper.main` (Task 11), pytest/ruff config (Task 1).

- [ ] **Step 1: Create the update workflow**

`.github/workflows/update-listings.yml`:
```yaml
name: Update listings
on:
  schedule:
    - cron: "0 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: update-listings
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e .
      - run: python -m scraper.main
      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/listings.json README.md ARCHIVED.md
          if ! git diff --cached --quiet; then
            git commit -m "chore: update listings $(date -u +'%Y-%m-%d %H:%M UTC')"
            git push
          fi
```

- [ ] **Step 2: Create the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check . && ruff format --check .
      - run: pytest -m "not live" --cov=scraper --cov-fail-under=80
```

- [ ] **Step 3: Create CONTRIBUTING.md**

````markdown
# Contributing

## Add a company

1. Find the company's job board: Greenhouse (`boards.greenhouse.io/<board>`),
   Lever (`jobs.lever.co/<board>`), Ashby (`jobs.ashbyhq.com/<board>`), or
   SmartRecruiters.
2. Add an entry to `data/companies.yaml`:
   ```yaml
   - name: Company Name
     ats: greenhouse
     board: boardtoken
   ```
3. Verify the token resolves, e.g.
   `curl -s "https://boards-api.greenhouse.io/v1/boards/<board>/jobs" | head -c 300`
   should return JSON, not a 404. Open a PR; CI must pass.

## Report a bad listing

Open an issue with the listing URL and what's wrong (dead link, not an
internship, wrong season/region).
````

- [ ] **Step 4: Verify end-to-end on GitHub**

1. `git push -u origin main`
2. On github.com → Actions → "Update listings" → **Run workflow** (manual dispatch).
3. Expected: run goes green, a `chore: update listings …` commit appears, README shows populated tables, job summary lists sources OK/failed.
4. Wait for the next top-of-hour cron run and confirm it triggers (may lag 10–30 min).
5. Confirm CI ran green on the push.

- [ ] **Step 5: Commit**

```bash
git add .github CONTRIBUTING.md
git commit -m "ci: add hourly update workflow and CI"
git push
```
