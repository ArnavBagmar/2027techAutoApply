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
