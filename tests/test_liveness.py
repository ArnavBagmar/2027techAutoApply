import pytest
import requests

from scraper import liveness
from scraper.liveness import check_url, classify_response, workday_cxs_url


class FakeResponse:
    def __init__(self, status_code: int, text: str = "job page"):
        self.status_code = status_code
        self.text = text


@pytest.mark.parametrize(
    ("status", "body", "verdict"),
    [
        (404, "", "dead"),
        (410, "", "dead"),
        (200, "Apply now to this role", "alive"),
        (200, "Sorry, Job Not Found", "dead"),
        (200, "This posting is no longer available.", "dead"),
        (200, "We are no longer accepting applications", "dead"),
        (200, "This position has been filled", "dead"),
        (200, "this job is no longer active", "dead"),
        (403, "", "unknown"),
        (429, "", "unknown"),
        (500, "", "unknown"),
        (503, "", "unknown"),
        (301, "", "unknown"),
    ],
)
def test_classify_response(status, body, verdict):
    assert classify_response(status, body) == verdict


def test_check_url_returns_verdict(monkeypatch):
    monkeypatch.setattr(liveness.requests, "get", lambda url, **kwargs: FakeResponse(404))
    assert check_url("https://example.com/job/1") == "dead"


def test_check_url_timeout_is_unknown(monkeypatch):
    def boom(url, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(liveness.requests, "get", boom)
    assert check_url("https://example.com/job/1") == "unknown"


def test_check_url_any_exception_is_unknown(monkeypatch):
    def boom(url, **kwargs):
        raise ValueError("weird")

    monkeypatch.setattr(liveness.requests, "get", boom)
    assert check_url("https://example.com/job/1") == "unknown"


def test_check_url_sends_browser_user_agent(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse(200)

    monkeypatch.setattr(liveness.requests, "get", fake_get)
    check_url("https://example.com/job/1")
    assert "Mozilla" in captured["headers"]["User-Agent"]
    assert captured["timeout"] == 10.0


def test_workday_url_is_translated_to_cxs(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse(200, "{}")

    monkeypatch.setattr(liveness.requests, "get", fake_get)
    check_url(
        "https://leidos.wd5.myworkdayjobs.com/External/job/Chantilly-VA/Software-Engineer-Intern_R-00183714"
    )
    assert captured["url"] == (
        "https://leidos.wd5.myworkdayjobs.com/wday/cxs/leidos/External"
        "/job/Chantilly-VA/Software-Engineer-Intern_R-00183714"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/McLean-VA/Program_R246020-1",
            "https://capitalone.wd12.myworkdayjobs.com/wday/cxs/capitalone/Capital_One"
            "/job/McLean-VA/Program_R246020-1",
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/en-US/External/job/Boston-MA/SWE-Intern_R1",
            "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/job/Boston-MA/SWE-Intern_R1",
        ),
        ("https://boards.greenhouse.io/acme/jobs/1", None),
        ("https://acme.wd1.myworkdayjobs.com/External", None),
    ],
)
def test_workday_cxs_url(url, expected):
    assert workday_cxs_url(url) == expected
