import pytest

from scraper.filters import categorize, is_internship, is_us, matches_summer_2027


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineering Intern", True),
        ("Software Engineering Internship - Summer 2027", True),
        ("Software Engineer Co-op", True),
        ("Internal Tools Engineer", False),
        ("International Sales Manager", False),
        ("Senior Software Engineer", False),
    ],
)
def test_is_internship(title, expected):
    assert is_internship(title) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SWE Intern (Summer 2027)", True),
        ("2027 Summer Software Intern", True),
        ("Summer 2026 Intern", False),
        ("SWE Intern", False),
    ],
)
def test_matches_summer_2027(text, expected):
    assert matches_summer_2027(text) is expected


def test_season_agnostic_bypasses_year_check():
    assert matches_summer_2027("SWE Intern", season_agnostic=True) is True


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Quantitative Trading Intern", "quant"),
        ("Machine Learning Intern", "data-ml"),
        ("Embedded Software Intern", "hardware"),
        ("Software Engineering Intern", "swe"),
    ],
)
def test_categorize(title, expected):
    assert categorize(title) == expected


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        (["San Francisco, CA"], True),
        (["New York, NY", "London, UK"], True),
        (["London, UK"], False),
        (["Remote - US"], True),
        (["Unknown"], True),
        ([], True),
    ],
)
def test_is_us(locations, expected):
    assert is_us(locations) is expected
