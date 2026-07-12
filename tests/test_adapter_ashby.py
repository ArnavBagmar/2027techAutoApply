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
