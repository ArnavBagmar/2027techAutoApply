import re

from scraper.models import Category

INTERN_RE = re.compile(r"\b(intern|internship|co[- ]?op)\b", re.IGNORECASE)
EXCLUDE_RE = re.compile(r"\b(internal|international)\b", re.IGNORECASE)
SUMMER_2027_RE = re.compile(r"(summer.{0,40}2027|2027.{0,40}summer)", re.IGNORECASE | re.DOTALL)
US_STATE_RE = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|"
    r"NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
)
US_HINT_RE = re.compile(r"\b(united states|usa|u\.s\.|remote)\b", re.IGNORECASE)

CATEGORY_RULES: tuple[tuple[Category, "re.Pattern[str]"], ...] = (
    ("quant", re.compile(r"\b(quant\w*|trading|trader)\b", re.IGNORECASE)),
    ("hardware", re.compile(r"\b(hardware|embedded|fpga|asic|silicon|firmware)\b", re.IGNORECASE)),
    ("data-ml", re.compile(r"\b(data|machine learning|ml|ai|analytics)\b", re.IGNORECASE)),
)


def is_internship(title: str) -> bool:
    return bool(INTERN_RE.search(EXCLUDE_RE.sub(" ", title)))


def matches_summer_2027(text: str, season_agnostic: bool = False) -> bool:
    return season_agnostic or bool(SUMMER_2027_RE.search(text))


def categorize(title: str, hint: Category = "swe") -> Category:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(title):
            return category
    return hint


def is_us(locations: list[str]) -> bool:
    known = [loc for loc in locations if loc and loc.lower() != "unknown"]
    if not known:
        return True
    return any(US_STATE_RE.search(loc) or US_HINT_RE.search(loc) for loc in known)
