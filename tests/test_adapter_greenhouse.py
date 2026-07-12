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
