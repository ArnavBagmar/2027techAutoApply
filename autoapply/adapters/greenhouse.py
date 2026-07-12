from urllib.parse import urlsplit

from autoapply.adapters.base import FillAction
from autoapply.profile import Profile


class GreenhouseAdapter:
    name = "greenhouse"

    def matches(self, url: str) -> bool:
        host = urlsplit(url).netloc.lower()
        return host == "greenhouse.io" or host.endswith(".greenhouse.io")

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
