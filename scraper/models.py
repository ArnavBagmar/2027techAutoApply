import hashlib
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import BaseModel

Category = Literal["swe", "data-ml", "quant", "hardware"]
ATSName = Literal["greenhouse", "lever", "ashby", "smartrecruiters"]


class Company(BaseModel):
    name: str
    ats: ATSName
    board: str
    category_hint: Category = "swe"
    season_agnostic: bool = False


class Listing(BaseModel):
    id: str
    company: str
    title: str
    category: Category
    locations: list[str]
    url: str
    ats: str
    source: str
    first_seen: datetime
    active: bool = True
    closed_at: datetime | None = None


TRACKING_PARAMS = frozenset(
    {"gh_src", "ref", "src", "source", "lever-origin", "lever-source", "utm"}
)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    base = f"{parts.scheme}://{parts.netloc.lower()}{parts.path}".rstrip("/")
    query = urlencode(sorted(kept))
    return f"{base}?{query}" if query else base


def listing_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()
