from pathlib import Path

import pytest

from autoapply.profile import ProfileError, load_profile

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
