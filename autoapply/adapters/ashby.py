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
