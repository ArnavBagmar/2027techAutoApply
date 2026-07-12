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
