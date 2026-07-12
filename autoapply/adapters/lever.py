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
