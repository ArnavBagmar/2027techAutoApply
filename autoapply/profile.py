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
        raise ProfileError(f"No profile found at {path}. Run 'autoapply init' to create one.")
    try:
        raw = yaml.safe_load(path.read_text())
        profile = Profile.model_validate(raw)
    except yaml.YAMLError as error:
        raise ProfileError(f"{path} is not valid YAML: {error}") from error
    except ValidationError as error:
        raise ProfileError(f"{path} is invalid: {error}") from error
    if not profile.resume_path.exists():
        raise ProfileError(f"resume not found at {profile.resume_path}. Fix resume_path in {path}.")
    return profile
