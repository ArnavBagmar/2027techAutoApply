# Auto-Apply CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `autoapply` CLI that cloners run to semi-automatically apply: it reads `data/listings.json`, opens each pending posting in a real browser, fills the form from a local profile, and pauses for the human to review and submit.

**Architecture:** Pure logic (profile validation, state transitions, fill planning) is separated from Playwright I/O so everything except the browser layer is unit-testable in CI. Each ATS gets an adapter that produces a list of `FillAction`s; a thin browser runner executes them.

**Tech Stack:** Python 3.12, pydantic v2, Playwright (sync API), argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-07-12-internship-list-autoapply-design.md`
**Prerequisite:** Listings pipeline plan completed (`Listing` model in `scraper/models.py`, `data/listings.json` exists).

## Global Constraints

- New runtime dep: `playwright>=1.44`. Console script: `autoapply = autoapply.cli:main`.
- The tool NEVER clicks submit, NEVER interacts with CAPTCHAs or anti-bot checks, applies one listing at a time. These are hard product rules — any step that would violate them is a bug.
- `profile.yaml`, `applied.json`, `.browser-profile/` are gitignored (done in pipeline Task 1) and must never be committed.
- All timestamps timezone-aware UTC. State updates return new dicts (no mutation).
- CI coverage gate stays at 80% across `scraper` + `autoapply` (browser layer excluded via the `live` marker convention: browser code paths are exercised in manual E2E only).
- Conventional commits, no attribution lines.

---

### Task 1: Package scaffolding + pyproject update

**Files:**
- Create: `autoapply/__init__.py`, `autoapply/adapters/__init__.py`
- Modify: `pyproject.toml` (packages list, dependencies, console script, coverage command)

**Interfaces:**
- Produces: importable `autoapply` package; `autoapply` console command (fails until Task 8 adds `cli.main`, which is expected at this stage).

- [ ] **Step 1: Write the failing test**

`tests/test_autoapply_sanity.py`:
```python
def test_autoapply_package_imports():
    import autoapply  # noqa: F401
    import autoapply.adapters  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_autoapply_sanity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply'`

- [ ] **Step 3: Create packages and update pyproject**

Create empty `autoapply/__init__.py` and `autoapply/adapters/__init__.py`.

In `pyproject.toml`, change these sections (leave the rest untouched):
```toml
[project]
# ...existing fields...
dependencies = [
  "requests>=2.31",
  "pydantic>=2.5",
  "PyYAML>=6.0",
  "playwright>=1.44",
]

[project.scripts]
autoapply = "autoapply.cli:main"

[tool.setuptools]
packages = ["scraper", "scraper.sources", "autoapply", "autoapply.adapters"]
```

Reinstall: `pip install -e ".[dev]"`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_autoapply_sanity.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply pyproject.toml tests/test_autoapply_sanity.py
git commit -m "chore: scaffold autoapply package"
```

---

### Task 2: Profile model and loader

**Files:**
- Create: `autoapply/profile.py`, `profile.example.yaml`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `Education(school, degree, major, grad_year)`; `Profile(first_name, last_name, email, phone, education, work_authorized_us, needs_sponsorship, linkedin="", github="", website="", resume_path, default_answers={})` with computed property `full_name`; `ProfileError(Exception)` with a user-friendly message; `load_profile(path: Path) -> Profile` (raises `ProfileError` for missing file, invalid YAML, failed validation, or missing resume file).

- [ ] **Step 1: Write the failing test**

`tests/test_profile.py`:
```python
from pathlib import Path

import pytest

from autoapply.profile import Profile, ProfileError, load_profile

VALID = """
first_name: Ada
last_name: Lovelace
email: ada@example.com
phone: "555-0100"
education:
  school: MIT
  degree: BS
  major: Computer Science
  grad_year: 2028
work_authorized_us: true
needs_sponsorship: false
linkedin: https://linkedin.com/in/ada
resume_path: "{resume}"
default_answers:
  how_did_you_hear: GitHub
"""


def write_profile(tmp_path: Path, content: str) -> Path:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    path = tmp_path / "profile.yaml"
    path.write_text(content.format(resume=resume))
    return path


def test_load_valid_profile(tmp_path):
    profile = load_profile(write_profile(tmp_path, VALID))
    assert profile.full_name == "Ada Lovelace"
    assert profile.education.grad_year == 2028
    assert profile.default_answers["how_did_you_hear"] == "GitHub"


def test_missing_file_raises_friendly_error(tmp_path):
    with pytest.raises(ProfileError, match="autoapply init"):
        load_profile(tmp_path / "nope.yaml")


def test_missing_resume_raises(tmp_path):
    path = write_profile(tmp_path, VALID)
    (tmp_path / "resume.pdf").unlink()
    with pytest.raises(ProfileError, match="resume"):
        load_profile(path)


def test_invalid_email_raises(tmp_path):
    bad = VALID.replace("ada@example.com", "not-an-email")
    with pytest.raises(ProfileError, match="email"):
        load_profile(write_profile(tmp_path, bad))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.profile'`

- [ ] **Step 3: Write minimal implementation**

`autoapply/profile.py`:
```python
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator


class ProfileError(Exception):
    """User-facing profile problem with a plain-English message."""


class Education(BaseModel):
    school: str
    degree: str
    major: str
    grad_year: int


class Profile(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str
    education: Education
    work_authorized_us: bool
    needs_sponsorship: bool
    linkedin: str = ""
    github: str = ""
    website: str = ""
    resume_path: Path
    default_answers: dict[str, str] = {}

    @field_validator("email")
    @classmethod
    def email_must_have_at(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("email must contain '@'")
        return value

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def load_profile(path: Path) -> Profile:
    if not path.exists():
        raise ProfileError(
            f"No profile found at {path}. Run 'autoapply init' to create one."
        )
    try:
        raw = yaml.safe_load(path.read_text())
        profile = Profile.model_validate(raw)
    except yaml.YAMLError as error:
        raise ProfileError(f"{path} is not valid YAML: {error}") from error
    except ValidationError as error:
        raise ProfileError(f"{path} is invalid: {error}") from error
    if not profile.resume_path.exists():
        raise ProfileError(
            f"resume not found at {profile.resume_path}. Fix resume_path in {path}."
        )
    return profile
```

`profile.example.yaml` (committed template; users copy to gitignored `profile.yaml`):
```yaml
first_name: Ada
last_name: Lovelace
email: ada@example.com
phone: "555-0100"
education:
  school: Your University
  degree: BS
  major: Computer Science
  grad_year: 2028
work_authorized_us: true
needs_sponsorship: false
linkedin: https://linkedin.com/in/yourhandle
github: https://github.com/yourhandle
website: ""
resume_path: /absolute/path/to/resume.pdf
default_answers:
  how_did_you_hear: GitHub
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_profile.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply/profile.py profile.example.yaml tests/test_profile.py
git commit -m "feat: add profile model and loader"
```

---

### Task 3: Application state store

**Files:**
- Create: `autoapply/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `Status = Literal["pending", "filled", "submitted", "skipped"]`; `Record(listing_id, status, updated_at)`; `load_state(path: Path) -> dict[str, Record]` (empty dict when file missing); `with_status(state, listing_id, status, now) -> dict[str, Record]` (returns a NEW dict); `save_state(path, state) -> None`; `select_pending(listings, state) -> list[Listing]` (active listings whose id is absent or `pending`).

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.state'`

- [ ] **Step 3: Write minimal implementation**

`autoapply/state.py`:
```python
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from scraper.models import Listing

Status = Literal["pending", "filled", "submitted", "skipped"]


class Record(BaseModel):
    listing_id: str
    status: Status
    updated_at: datetime


def load_state(path: Path) -> dict[str, Record]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {key: Record.model_validate(value) for key, value in raw.items()}


def save_state(path: Path, state: dict[str, Record]) -> None:
    payload = {key: record.model_dump(mode="json") for key, record in state.items()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def with_status(
    state: dict[str, Record], listing_id: str, status: Status, now: datetime
) -> dict[str, Record]:
    record = Record(listing_id=listing_id, status=status, updated_at=now)
    return {**state, listing_id: record}


def select_pending(listings: list[Listing], state: dict[str, Record]) -> list[Listing]:
    def is_pending(listing: Listing) -> bool:
        record = state.get(listing.id)
        return record is None or record.status == "pending"

    return [item for item in listings if item.active and is_pending(item)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply/state.py tests/test_state.py
git commit -m "feat: add immutable application state store"
```

---

### Task 4: FillAction + adapter registry

**Files:**
- Create: `autoapply/adapters/base.py`
- Test: `tests/test_adapters_base.py`

**Interfaces:**
- Produces: `FillAction(kind: Literal["css", "label", "file_css"], target: str, value: str)` (frozen dataclass); `Adapter` protocol with `name: str`, `matches(url: str) -> bool`, `plan(profile: Profile) -> list[FillAction]`; `ADAPTERS: list[Adapter]` (populated by Tasks 5–7); `adapter_for(url: str) -> Adapter | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_adapters_base.py`:
```python
from autoapply.adapters.base import ADAPTERS, FillAction, adapter_for


def test_fill_action_is_frozen():
    action = FillAction(kind="css", target="#email", value="a@b.com")
    try:
        action.value = "other"
        raised = False
    except AttributeError:
        raised = True
    assert raised


def test_adapter_for_unknown_url_returns_none():
    assert adapter_for("https://careers.example.com/apply/1") is None


def test_registry_is_a_list():
    assert isinstance(ADAPTERS, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapters_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.adapters.base'`

- [ ] **Step 3: Write minimal implementation**

`autoapply/adapters/base.py`:
```python
from dataclasses import dataclass
from typing import Literal, Protocol

from autoapply.profile import Profile


@dataclass(frozen=True)
class FillAction:
    kind: Literal["css", "label", "file_css"]
    target: str
    value: str


class Adapter(Protocol):
    name: str

    def matches(self, url: str) -> bool: ...

    def plan(self, profile: Profile) -> list["FillAction"]: ...


ADAPTERS: list[Adapter] = []


def adapter_for(url: str) -> Adapter | None:
    for adapter in ADAPTERS:
        if adapter.matches(url):
            return adapter
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapters_base.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply/adapters/base.py tests/test_adapters_base.py
git commit -m "feat: add FillAction and adapter registry"
```

---

### Task 5: Greenhouse adapter

**Files:**
- Create: `autoapply/adapters/greenhouse.py`
- Modify: `autoapply/adapters/__init__.py` (register adapter)
- Test: `tests/test_adapter_greenhouse.py`

**Interfaces:**
- Consumes: `FillAction`, `ADAPTERS` from base; `Profile` from Task 2.
- Produces: `GreenhouseAdapter` with `name = "greenhouse"`, matching any `*.greenhouse.io` URL, planning fills for first/last name, email, phone, LinkedIn, and resume upload.
- ⚠️ Greenhouse has two board generations (`boards.greenhouse.io` classic and `job-boards.greenhouse.io`). The selectors below are for the classic form; the manual E2E step in Task 9 verifies and adjusts against a live posting.

- [ ] **Step 1: Write the failing test**

`tests/test_adapter_greenhouse.py`:
```python
from pathlib import Path

from autoapply.adapters.base import adapter_for
from autoapply.adapters.greenhouse import GreenhouseAdapter
from autoapply.profile import Education, Profile

PROFILE = Profile(
    first_name="Ada",
    last_name="Lovelace",
    email="ada@example.com",
    phone="555-0100",
    education=Education(school="MIT", degree="BS", major="CS", grad_year=2028),
    work_authorized_us=True,
    needs_sponsorship=False,
    linkedin="https://linkedin.com/in/ada",
    resume_path=Path("/tmp/resume.pdf"),
)


def test_matches_greenhouse_urls():
    adapter = GreenhouseAdapter()
    assert adapter.matches("https://boards.greenhouse.io/acme/jobs/1")
    assert adapter.matches("https://job-boards.greenhouse.io/acme/jobs/1")
    assert not adapter.matches("https://jobs.lever.co/acme/1")


def test_registered_in_registry():
    assert isinstance(adapter_for("https://boards.greenhouse.io/acme/jobs/1"), GreenhouseAdapter)


def test_plan_covers_core_fields_and_resume():
    actions = GreenhouseAdapter().plan(PROFILE)
    by_target = {action.target: action for action in actions}
    assert by_target["#first_name"].value == "Ada"
    assert by_target["#last_name"].value == "Lovelace"
    assert by_target["#email"].value == "ada@example.com"
    assert by_target["#phone"].value == "555-0100"
    file_actions = [action for action in actions if action.kind == "file_css"]
    assert file_actions and file_actions[0].value == "/tmp/resume.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_greenhouse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.adapters.greenhouse'`

- [ ] **Step 3: Write minimal implementation**

`autoapply/adapters/greenhouse.py`:
```python
from urllib.parse import urlsplit

from autoapply.adapters.base import FillAction
from autoapply.profile import Profile


class GreenhouseAdapter:
    name = "greenhouse"

    def matches(self, url: str) -> bool:
        host = urlsplit(url).netloc.lower()
        return host.endswith("greenhouse.io")

    def plan(self, profile: Profile) -> list[FillAction]:
        actions = [
            FillAction("css", "#first_name", profile.first_name),
            FillAction("css", "#last_name", profile.last_name),
            FillAction("css", "#email", profile.email),
            FillAction("css", "#phone", profile.phone),
            FillAction("file_css", "input[type='file']", str(profile.resume_path)),
        ]
        if profile.linkedin:
            actions.append(FillAction("label", "LinkedIn Profile", profile.linkedin))
        return actions
```

`autoapply/adapters/__init__.py`:
```python
from autoapply.adapters.base import ADAPTERS
from autoapply.adapters.greenhouse import GreenhouseAdapter

ADAPTERS.append(GreenhouseAdapter())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_greenhouse.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply/adapters/greenhouse.py autoapply/adapters/__init__.py tests/test_adapter_greenhouse.py
git commit -m "feat: add greenhouse fill adapter"
```

---

### Task 6: Lever adapter

**Files:**
- Create: `autoapply/adapters/lever.py`
- Modify: `autoapply/adapters/__init__.py`
- Test: `tests/test_adapter_lever.py`

**Interfaces:**
- Produces: `LeverAdapter` with `name = "lever"`, matching `jobs.lever.co` URLs. Lever forms use `name` attributes, and the name field is a single full-name input.

- [ ] **Step 1: Write the failing test**

`tests/test_adapter_lever.py`:
```python
from pathlib import Path

from autoapply.adapters.base import adapter_for
from autoapply.adapters.lever import LeverAdapter
from autoapply.profile import Education, Profile

PROFILE = Profile(
    first_name="Ada",
    last_name="Lovelace",
    email="ada@example.com",
    phone="555-0100",
    education=Education(school="MIT", degree="BS", major="CS", grad_year=2028),
    work_authorized_us=True,
    needs_sponsorship=False,
    github="https://github.com/ada",
    resume_path=Path("/tmp/resume.pdf"),
)


def test_matches_lever_urls_only():
    adapter = LeverAdapter()
    assert adapter.matches("https://jobs.lever.co/acme/abc-123")
    assert not adapter.matches("https://boards.greenhouse.io/acme/jobs/1")


def test_registered_in_registry():
    assert isinstance(adapter_for("https://jobs.lever.co/acme/abc-123"), LeverAdapter)


def test_plan_uses_full_name_and_name_attributes():
    actions = LeverAdapter().plan(PROFILE)
    by_target = {action.target: action for action in actions}
    assert by_target["input[name='name']"].value == "Ada Lovelace"
    assert by_target["input[name='email']"].value == "ada@example.com"
    assert by_target["input[name='urls[GitHub]']"].value == "https://github.com/ada"
    assert by_target["input[name='resume']"].kind == "file_css"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_lever.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.adapters.lever'`

- [ ] **Step 3: Write minimal implementation**

`autoapply/adapters/lever.py`:
```python
from urllib.parse import urlsplit

from autoapply.adapters.base import FillAction
from autoapply.profile import Profile


class LeverAdapter:
    name = "lever"

    def matches(self, url: str) -> bool:
        return urlsplit(url).netloc.lower() == "jobs.lever.co"

    def plan(self, profile: Profile) -> list[FillAction]:
        actions = [
            FillAction("css", "input[name='name']", profile.full_name),
            FillAction("css", "input[name='email']", profile.email),
            FillAction("css", "input[name='phone']", profile.phone),
            FillAction("file_css", "input[name='resume']", str(profile.resume_path)),
        ]
        if profile.linkedin:
            actions.append(FillAction("css", "input[name='urls[LinkedIn]']", profile.linkedin))
        if profile.github:
            actions.append(FillAction("css", "input[name='urls[GitHub]']", profile.github))
        return actions
```

Update `autoapply/adapters/__init__.py`:
```python
from autoapply.adapters.base import ADAPTERS
from autoapply.adapters.greenhouse import GreenhouseAdapter
from autoapply.adapters.lever import LeverAdapter

ADAPTERS.append(GreenhouseAdapter())
ADAPTERS.append(LeverAdapter())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_lever.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply/adapters/lever.py autoapply/adapters/__init__.py tests/test_adapter_lever.py
git commit -m "feat: add lever fill adapter"
```

---

### Task 7: Ashby adapter

**Files:**
- Create: `autoapply/adapters/ashby.py`
- Modify: `autoapply/adapters/__init__.py`
- Test: `tests/test_adapter_ashby.py`

**Interfaces:**
- Produces: `AshbyAdapter` with `name = "ashby"`, matching `jobs.ashbyhq.com`. Ashby forms are React-rendered without stable ids, so fills are planned by **label** (Playwright `get_by_label`), plus a CSS file upload.

- [ ] **Step 1: Write the failing test**

`tests/test_adapter_ashby.py`:
```python
from pathlib import Path

from autoapply.adapters.ashby import AshbyAdapter
from autoapply.profile import Education, Profile

PROFILE = Profile(
    first_name="Ada",
    last_name="Lovelace",
    email="ada@example.com",
    phone="555-0100",
    education=Education(school="MIT", degree="BS", major="CS", grad_year=2028),
    work_authorized_us=True,
    needs_sponsorship=False,
    resume_path=Path("/tmp/resume.pdf"),
)


def test_matches_ashby_urls_only():
    adapter = AshbyAdapter()
    assert adapter.matches("https://jobs.ashbyhq.com/acme/1111")
    assert not adapter.matches("https://jobs.lever.co/acme/1")


def test_plan_uses_labels():
    actions = AshbyAdapter().plan(PROFILE)
    labels = {action.target: action.value for action in actions if action.kind == "label"}
    assert labels["Name"] == "Ada Lovelace"
    assert labels["Email"] == "ada@example.com"
    assert any(action.kind == "file_css" for action in actions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_ashby.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.adapters.ashby'`

- [ ] **Step 3: Write minimal implementation**

`autoapply/adapters/ashby.py`:
```python
from urllib.parse import urlsplit

from autoapply.adapters.base import FillAction
from autoapply.profile import Profile


class AshbyAdapter:
    name = "ashby"

    def matches(self, url: str) -> bool:
        return urlsplit(url).netloc.lower() == "jobs.ashbyhq.com"

    def plan(self, profile: Profile) -> list[FillAction]:
        actions = [
            FillAction("label", "Name", profile.full_name),
            FillAction("label", "Email", profile.email),
            FillAction("label", "Phone", profile.phone),
            FillAction("file_css", "input[type='file']", str(profile.resume_path)),
        ]
        if profile.linkedin:
            actions.append(FillAction("label", "LinkedIn", profile.linkedin))
        return actions
```

Update `autoapply/adapters/__init__.py`:
```python
from autoapply.adapters.ashby import AshbyAdapter
from autoapply.adapters.base import ADAPTERS
from autoapply.adapters.greenhouse import GreenhouseAdapter
from autoapply.adapters.lever import LeverAdapter

ADAPTERS.append(GreenhouseAdapter())
ADAPTERS.append(LeverAdapter())
ADAPTERS.append(AshbyAdapter())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_ashby.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add autoapply/adapters/ashby.py autoapply/adapters/__init__.py tests/test_adapter_ashby.py
git commit -m "feat: add ashby fill adapter"
```

---

### Task 8: Browser runner + CLI

**Files:**
- Create: `autoapply/browser.py`, `autoapply/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `browser.session(user_data_dir: Path)` context manager yielding a Playwright persistent context (headed Chromium); `browser.apply_actions(page, actions: list[FillAction]) -> list[FillAction]` returning the actions that failed (never raises for a single bad selector); `cli.main(argv: list[str] | None = None) -> int` with subcommands `init`, `run`, `status`; `cli.load_listings(path: Path) -> list[Listing]`.
- The `run` loop per listing: goto URL → plan via `adapter_for` → `apply_actions` → print unmapped/failed actions → prompt `[s]ubmitted / s[k]ip / [q]uit` → update state via `with_status` + `save_state`. NO code path clicks a submit button.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py` (pure helpers only; browser paths are manual-E2E):
```python
import json
from datetime import datetime, timezone

from autoapply.cli import build_parser, format_status, load_listings
from autoapply.state import with_status
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


def test_parser_has_three_subcommands():
    parser = build_parser()
    for command in ("init", "run", "status"):
        args = parser.parse_args([command])
        assert args.command == command


def test_load_listings(tmp_path):
    path = tmp_path / "listings.json"
    path.write_text(json.dumps([LISTING.model_dump(mode="json")]))
    listings = load_listings(path)
    assert listings[0].company == "Acme"


def test_format_status_counts():
    state = with_status({}, "a" * 40, "submitted", NOW)
    output = format_status([LISTING], state)
    assert "submitted: 1" in output
    assert "pending: 0" in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoapply.cli'`

- [ ] **Step 3: Write the browser runner**

`autoapply/browser.py`:
```python
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from autoapply.adapters.base import FillAction

ACTION_TIMEOUT_MS = 3000


def apply_actions(page: Page, actions: list[FillAction]) -> list[FillAction]:
    """Apply fill actions; return the ones that failed so the human can do them."""
    failed: list[FillAction] = []
    for action in actions:
        try:
            if action.kind == "css":
                page.fill(action.target, action.value, timeout=ACTION_TIMEOUT_MS)
            elif action.kind == "label":
                page.get_by_label(action.target).first.fill(
                    action.value, timeout=ACTION_TIMEOUT_MS
                )
            elif action.kind == "file_css":
                page.set_input_files(action.target, action.value, timeout=ACTION_TIMEOUT_MS)
        except Exception:
            failed.append(action)
    return failed


@contextmanager
def session(user_data_dir: Path):
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir), headless=False
        )
        try:
            yield context
        finally:
            context.close()
```

- [ ] **Step 4: Write the CLI**

`autoapply/cli.py`:
```python
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from autoapply.adapters.base import adapter_for
from autoapply.profile import ProfileError, load_profile
from autoapply.state import load_state, save_state, select_pending, with_status
from scraper.models import Listing

LISTINGS_PATH = Path("data/listings.json")
PROFILE_PATH = Path("profile.yaml")
STATE_PATH = Path("applied.json")
BROWSER_DIR = Path(".browser-profile")

INIT_FIELDS = [
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("linkedin", "LinkedIn URL (optional)"),
    ("github", "GitHub URL (optional)"),
    ("resume_path", "Absolute path to resume PDF"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoapply",
        description="Semi-automated internship applications. YOU review and submit each one.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create profile.yaml interactively")
    sub.add_parser("run", help="fill pending applications, one at a time")
    sub.add_parser("status", help="show application counts")
    return parser


def load_listings(path: Path) -> list[Listing]:
    return [Listing.model_validate(entry) for entry in json.loads(path.read_text())]


def format_status(listings: list[Listing], state) -> str:
    counts = {"pending": 0, "filled": 0, "submitted": 0, "skipped": 0}
    for listing in listings:
        record = state.get(listing.id)
        status = record.status if record else "pending"
        if not listing.active and status == "pending":
            continue
        counts[status] += 1
    return "\n".join(f"{status}: {count}" for status, count in counts.items())


def cmd_init() -> int:
    answers = {}
    print("Setting up your profile (saved to gitignored profile.yaml):")
    for key, prompt in INIT_FIELDS:
        answers[key] = input(f"  {prompt}: ").strip()
    answers["education"] = {
        "school": input("  School: ").strip(),
        "degree": input("  Degree (e.g. BS): ").strip(),
        "major": input("  Major: ").strip(),
        "grad_year": int(input("  Graduation year: ").strip()),
    }
    answers["work_authorized_us"] = input("  US work authorized? [y/n]: ").lower() == "y"
    answers["needs_sponsorship"] = input("  Need sponsorship? [y/n]: ").lower() == "y"
    answers["default_answers"] = {"how_did_you_hear": "GitHub"}
    PROFILE_PATH.write_text(yaml.safe_dump(answers, sort_keys=False))
    print(f"Wrote {PROFILE_PATH}. Verify it, then run: autoapply run")
    return 0


def cmd_run() -> int:
    from autoapply.browser import apply_actions, session  # import here: needs playwright

    try:
        profile = load_profile(PROFILE_PATH)
    except ProfileError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    listings = load_listings(LISTINGS_PATH)
    state = load_state(STATE_PATH)
    todo = select_pending(listings, state)
    print(f"{len(todo)} pending applications. One at a time; YOU click submit.")

    with session(BROWSER_DIR) as context:
        page = context.new_page()
        for listing in todo:
            print(f"\n→ {listing.company}: {listing.title}\n  {listing.url}")
            page.goto(listing.url)
            adapter = adapter_for(listing.url)
            if adapter is None:
                print("  Unsupported ATS — fill manually in the browser window.")
            else:
                failed = apply_actions(page, adapter.plan(profile))
                for action in failed:
                    print(f"  Could not fill: {action.target} — do this one by hand.")
                print("  Review EVERYTHING, answer custom questions, then submit yourself.")
            choice = input("  [s]ubmitted / s[k]ip / [q]uit: ").strip().lower()
            now = datetime.now(timezone.utc)
            if choice == "s":
                state = with_status(state, listing.id, "submitted", now)
            elif choice == "k":
                state = with_status(state, listing.id, "skipped", now)
            else:
                break
            save_state(STATE_PATH, state)
    save_state(STATE_PATH, state)
    return 0


def cmd_status() -> int:
    listings = load_listings(LISTINGS_PATH)
    print(format_status(listings, load_state(STATE_PATH)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {"init": cmd_init, "run": cmd_run, "status": cmd_status}
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

Run: `pip install -e ".[dev]" && autoapply --help`
Expected: usage text listing init/run/status.

- [ ] **Step 6: Commit**

```bash
git add autoapply/browser.py autoapply/cli.py tests/test_cli.py
git commit -m "feat: add browser runner and autoapply CLI"
```

---

### Task 9: User docs + disclaimer + manual E2E

**Files:**
- Create: `DISCLAIMER.md`, `docs/SETUP.md`

**Interfaces:**
- Consumes: the working CLI (Task 8).

- [ ] **Step 1: Create DISCLAIMER.md**

```markdown
# Disclaimer

The `autoapply` tool is a **form-filling assistant**, not a bot:

- It never clicks submit — you review and submit every application yourself.
- It never solves, bypasses, or automates around CAPTCHAs or anti-bot checks.
- It processes one application at a time, at human pace.
- Your profile and resume stay on your machine; nothing is uploaded anywhere
  except into the application form you are looking at.

You are responsible for the accuracy of every application you submit and for
complying with each site's terms of service. Listings data is aggregated from
public APIs and community sources with no guarantee of accuracy — always verify
details on the company's official posting.
```

- [ ] **Step 2: Create docs/SETUP.md**

````markdown
# Auto-apply setup

## Requirements
- Python 3.11+
- Chromium (installed by the playwright step below)

## Install

```bash
git clone https://github.com/ArnavBagmar/2027techAutoApply.git
cd 2027techAutoApply
pip install -e .
playwright install chromium
```

## Configure

```bash
autoapply init          # answers are saved to gitignored profile.yaml
```

Or copy `profile.example.yaml` to `profile.yaml` and edit it. Set
`resume_path` to an absolute path to your resume PDF.

## Apply

```bash
git pull                # grab the freshest listings
autoapply run
```

For each pending listing the tool opens the posting in a visible browser,
fills what it can from your profile, and lists anything it could not fill.
Answer the custom questions, review every field, click submit yourself, then
tell the CLI: `s` (submitted), `k` (skip), or `q` (quit).

```bash
autoapply status        # pending / filled / submitted / skipped counts
```

Supported ATS for auto-fill: Greenhouse, Lever, Ashby. Anything else opens
for manual completion. Read [DISCLAIMER.md](../DISCLAIMER.md) before using.
````

- [ ] **Step 3: Manual E2E checklist (run locally, once per ATS)**

1. `autoapply init` with your real info (or copy the example and edit).
2. Pick one active Greenhouse listing from README → `autoapply run` → confirm:
   fields filled, resume attached, unfilled fields reported, no submit clicked.
   Choose `k` (skip) unless you actually want to apply.
3. Repeat for one Lever and one Ashby listing.
4. If selectors miss on a modern Greenhouse board (`job-boards.greenhouse.io`),
   adjust `GreenhouseAdapter.plan` selectors and re-run the adapter tests.
5. `autoapply status` shows the updated counts; `applied.json` exists and is
   NOT tracked by git (`git status` must not list it).

- [ ] **Step 4: Full suite + commit**

Run: `pytest -m "not live" --cov=scraper --cov=autoapply --cov-fail-under=80`
Expected: PASS with coverage ≥ 80%

```bash
git add DISCLAIMER.md docs/SETUP.md
git commit -m "docs: add disclaimer and auto-apply setup guide"
git push
```
