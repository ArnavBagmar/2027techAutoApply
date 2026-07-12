import json
from contextlib import contextmanager
from datetime import datetime, timezone

from autoapply.cli import cmd_init, cmd_run, cmd_status
from autoapply.state import Record, load_state, save_state, select_pending
from scraper.models import Listing

NOW = datetime(2026, 7, 12, 17, 0, tzinfo=timezone.utc)

VALID_PROFILE = """
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
resume_path: "{resume}"
default_answers:
  how_did_you_hear: GitHub
"""


def make_listing(id_: str, url: str = "https://boards.greenhouse.io/acme/jobs/1") -> Listing:
    return Listing(
        id=id_,
        company="Acme",
        title="SWE Intern, Summer 2027",
        category="swe",
        locations=["San Francisco, CA"],
        url=url,
        ats="greenhouse",
        source="greenhouse:acme",
        first_seen=NOW,
    )


def write_profile(tmp_path) -> None:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "profile.yaml").write_text(VALID_PROFILE.format(resume=resume))


def write_listings(tmp_path, listings) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "listings.json").write_text(
        json.dumps([listing.model_dump(mode="json") for listing in listings])
    )


class FakeLocator:
    def __init__(self, page, target):
        self.page = page
        self.target = target

    @property
    def first(self):
        return self

    def fill(self, value, timeout=None):
        self.page.filled.append((self.target, value))


class FakePage:
    """Records fill/goto calls; exposes `url`."""

    def __init__(self, landing_url: str | None = None, goto_error: Exception | None = None):
        self.url = ""
        self._landing_url = landing_url
        self._goto_error = goto_error
        self.filled: list[tuple[str, str]] = []
        self.goto_calls: list[str] = []

    def goto(self, url: str):
        self.goto_calls.append(url)
        if self._goto_error is not None:
            raise self._goto_error
        self.url = self._landing_url if self._landing_url is not None else url

    def fill(self, target, value, timeout=None):
        self.filled.append((target, value))

    def get_by_label(self, target):
        return FakeLocator(self, target)

    def set_input_files(self, target, value, timeout=None):
        self.filled.append((target, value))


class FakeContext:
    def __init__(self, page: FakePage):
        self._page = page

    def new_page(self):
        return self._page


def patch_session(monkeypatch, page: FakePage):
    @contextmanager
    def fake_session(user_data_dir):
        yield FakeContext(page)

    import autoapply.browser as browser_module

    monkeypatch.setattr(browser_module, "session", fake_session)


def setup_run_env(monkeypatch, tmp_path, listings, page: FakePage):
    monkeypatch.chdir(tmp_path)
    write_profile(tmp_path)
    write_listings(tmp_path, listings)
    patch_session(monkeypatch, page)


# --- Fix 1: re-prompt on unrecognized input ---


def test_reprompt_then_submit(monkeypatch, tmp_path, capsys):
    listing = make_listing("a" * 40)
    page = FakePage()
    setup_run_env(monkeypatch, tmp_path, [listing], page)

    answers = iter(["bogus", "s"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = cmd_run()

    assert result == 0
    captured = capsys.readouterr()
    assert "Please answer s, k, or q." in captured.out
    state = load_state(tmp_path / "applied.json")
    assert state[listing.id].status == "submitted"


# --- Fix 2: filled status wiring ---


def test_quit_after_fill_records_filled(monkeypatch, tmp_path):
    listing = make_listing("a" * 40)
    page = FakePage()
    setup_run_env(monkeypatch, tmp_path, [listing], page)

    monkeypatch.setattr("builtins.input", lambda prompt="": "q")

    result = cmd_run()

    assert result == 0
    state = load_state(tmp_path / "applied.json")
    assert state[listing.id].status == "filled"


def test_quit_on_unsupported_ats_leaves_pending(monkeypatch, tmp_path):
    listing = make_listing("a" * 40, url="https://example.com/careers/1")
    page = FakePage()
    setup_run_env(monkeypatch, tmp_path, [listing], page)

    monkeypatch.setattr("builtins.input", lambda prompt="": "q")

    result = cmd_run()

    assert result == 0
    state = load_state(tmp_path / "applied.json")
    assert listing.id not in state


def test_select_pending_represents_filled():
    listing = make_listing("a" * 40)
    state = {"a" * 40: Record(listing_id="a" * 40, status="filled", updated_at=NOW)}
    assert [item.id for item in select_pending([listing], state)] == ["a" * 40]


# --- Fix 3: guard page.goto ---


def test_goto_failure_then_skip_continues_loop(monkeypatch, tmp_path, capsys):
    listing_bad = make_listing("a" * 40, url="https://boards.greenhouse.io/acme/jobs/1")
    listing_good = make_listing("b" * 40, url="https://boards.greenhouse.io/acme/jobs/2")

    class FlakyPage(FakePage):
        def __init__(self):
            super().__init__()
            self._calls = 0

        def goto(self, url):
            self._calls += 1
            self.goto_calls.append(url)
            if self._calls == 1:
                raise RuntimeError("net::ERR_CONNECTION_RESET")
            self.url = url

    page = FlakyPage()
    setup_run_env(monkeypatch, tmp_path, [listing_bad, listing_good], page)

    prompts: list[str] = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        answers = {1: "k", 2: "s"}
        return answers[len(prompts)]

    monkeypatch.setattr("builtins.input", fake_input)

    result = cmd_run()

    assert result == 0
    assert any("Could not load" in prompt for prompt in prompts)
    state = load_state(tmp_path / "applied.json")
    assert state[listing_bad.id].status == "skipped"
    assert state[listing_good.id].status == "submitted"


def test_goto_failure_reprompts_on_bad_input(monkeypatch, tmp_path, capsys):
    listing = make_listing("a" * 40)
    page = FakePage(goto_error=RuntimeError("boom"))
    setup_run_env(monkeypatch, tmp_path, [listing], page)

    answers = iter(["nonsense", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = cmd_run()

    assert result == 0
    captured = capsys.readouterr()
    assert "Please answer k or q." in captured.out
    state = load_state(tmp_path / "applied.json")
    assert listing.id not in state


def test_goto_failure_prompt_contains_url_and_error(monkeypatch, tmp_path):
    listing = make_listing("a" * 40)
    page = FakePage(goto_error=RuntimeError("boom"))
    setup_run_env(monkeypatch, tmp_path, [listing], page)

    prompts: list[str] = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return "q"

    monkeypatch.setattr("builtins.input", fake_input)

    cmd_run()

    assert any("Could not load" in prompt and listing.url in prompt for prompt in prompts)


# --- Fix 4: adapter matched on landed URL ---


def test_adapter_matched_on_landed_url_downgrades_to_manual(monkeypatch, tmp_path, capsys):
    listing = make_listing("a" * 40, url="https://boards.greenhouse.io/acme/jobs/1")
    # Redirects off the ATS domain.
    page = FakePage(landing_url="https://acme.com/careers/thanks")
    setup_run_env(monkeypatch, tmp_path, [listing], page)

    monkeypatch.setattr("builtins.input", lambda prompt="": "k")

    result = cmd_run()

    assert result == 0
    captured = capsys.readouterr()
    assert "Unsupported ATS — fill manually" in captured.out
    assert page.filled == []


# --- Fix 5: friendly file errors + CWD guard ---


def test_cmd_run_missing_listings_returns_1(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    write_profile(tmp_path)

    result = cmd_run()

    assert result == 1
    captured = capsys.readouterr()
    assert "data/listings.json not found" in captured.err
    assert "root of the cloned repo" in captured.err


def test_cmd_status_missing_listings_returns_1(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)

    result = cmd_status()

    assert result == 1
    captured = capsys.readouterr()
    assert "data/listings.json not found" in captured.err


def test_cmd_status_corrupt_applied_json_friendly_error(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    write_listings(tmp_path, [make_listing("a" * 40)])
    (tmp_path / "applied.json").write_text("{not valid json")

    result = cmd_status()

    assert result == 1
    captured = capsys.readouterr()
    assert "applied.json" in captured.err
    assert "corrupted" in captured.err


def test_cmd_run_corrupt_applied_json_friendly_error(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    write_profile(tmp_path)
    write_listings(tmp_path, [make_listing("a" * 40)])
    (tmp_path / "applied.json").write_text("{not valid json")

    result = cmd_run()

    assert result == 1
    captured = capsys.readouterr()
    assert "applied.json" in captured.err
    assert "corrupted" in captured.err


# --- Fix 6: atomic state writes ---


def test_atomic_save_leaves_valid_state_file(tmp_path):
    path = tmp_path / "applied.json"
    state = {"a" * 40: Record(listing_id="a" * 40, status="submitted", updated_at=NOW)}

    save_state(path, state)

    assert path.exists()
    loaded = load_state(path)
    assert loaded["a" * 40].status == "submitted"
    # no leftover temp files
    leftovers = [p for p in tmp_path.iterdir() if p.name != "applied.json"]
    assert leftovers == []


# --- Fix 7: cmd_init hardening ---


def test_init_overwrite_decline_leaves_file_untouched(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("original: content\n")

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    result = cmd_init()

    assert result == 0
    assert profile_path.read_text() == "original: content\n"


def test_init_reprompts_on_bad_year(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    answers = iter(
        [
            "Ada",  # first name
            "Lovelace",  # last name
            "ada@example.com",  # email
            "555-0100",  # phone
            "",  # linkedin
            "",  # github
            str(tmp_path / "resume.pdf"),  # resume path
            "MIT",  # school
            "BS",  # degree
            "Computer Science",  # major
            "not-a-year",  # grad year (bad)
            "2028",  # grad year (retry)
            "y",  # work authorized
            "n",  # needs sponsorship
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = cmd_init()

    assert result == 0
    profile_path = tmp_path / "profile.yaml"
    assert profile_path.exists()
    content = profile_path.read_text()
    assert "grad_year: 2028" in content
