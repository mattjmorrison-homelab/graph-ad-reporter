import io
import json
import os
from collections.abc import Callable
from unittest.mock import patch
from wsgiref.types import StartResponse, WSGIEnvironment

from ad_reporter.wsgi import app


class _CapturedResponse:
    """Records the status and headers passed to a start_response call."""

    def __init__(self) -> None:
        self.status = ""
        self.headers: list[tuple[str, str]] = []


def _capturing_start_response() -> tuple[StartResponse, _CapturedResponse]:
    """Build a start_response callable that records its status and headers."""
    captured = _CapturedResponse()

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object = None,
    ) -> Callable[[bytes], object]:
        captured.status = status
        captured.headers = headers
        return lambda data: None

    return start_response, captured


def _graphql_environ(request_body: bytes, **extra: str) -> WSGIEnvironment:
    environ: WSGIEnvironment = {
        "PATH_INFO": "/graphql",
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(request_body)),
        "wsgi.input": io.BytesIO(request_body),
    }
    environ.update(extra)
    return environ


def _run_query(query: str, remote_addr: str, **extra: str) -> dict:
    start_response, _ = _capturing_start_response()
    body = json.dumps({"query": query}).encode("utf-8")
    result = app(
        _graphql_environ(body, REMOTE_ADDR=remote_addr, **extra), start_response
    )
    return json.loads(b"".join(result))


def test_report_ad_mutation_captures_client_ip_from_forwarded_header() -> None:
    start_response, captured = _capturing_start_response()
    request_body = json.dumps(
        {"query": "mutation { reportAd { id resolved clientIp resolutionNote } }"}
    ).encode("utf-8")

    body = app(
        _graphql_environ(
            request_body,
            HTTP_X_FORWARDED_FOR="192.168.1.50, 10.0.0.1",
            REMOTE_ADDR="10.0.0.1",
        ),
        start_response,
    )

    assert captured.status == "200 OK"
    parsed = json.loads(b"".join(body))
    report = parsed["data"]["reportAd"]
    assert report["clientIp"] == "192.168.1.50"
    assert report["resolved"] is False
    assert report["resolutionNote"] is None


def test_report_ad_mutation_falls_back_to_remote_addr_without_forwarded_header() -> (
    None
):
    parsed = _run_query(
        "mutation { reportAd { clientIp } }", remote_addr="192.168.1.77"
    )

    assert parsed["data"]["reportAd"]["clientIp"] == "192.168.1.77"


def test_unresolved_reports_query_excludes_resolved_reports() -> None:
    first = _run_query("mutation { reportAd { id } }", remote_addr="192.168.1.1")
    first_id = first["data"]["reportAd"]["id"]
    second = _run_query("mutation { reportAd { id } }", remote_addr="192.168.1.2")
    second_id = second["data"]["reportAd"]["id"]

    _run_query(
        f'mutation {{ resolveReport(id: "{first_id}", resolutionNote: "handled") '
        "{ id } }",
        remote_addr="192.168.1.1",
    )

    result = _run_query(
        "{ unresolvedReports { id resolved } }", remote_addr="192.168.1.1"
    )
    ids = [report["id"] for report in result["data"]["unresolvedReports"]]

    assert ids == [second_id]


def test_unresolved_reports_query_filters_by_since() -> None:
    created = _run_query("mutation { reportAd { id } }", remote_addr="192.168.1.9")
    report_id = created["data"]["reportAd"]["id"]

    future_result = _run_query(
        '{ unresolvedReports(since: "2999-01-01T00:00:00+00:00") { id } }',
        remote_addr="192.168.1.9",
    )
    assert future_result["data"]["unresolvedReports"] == []

    past_result = _run_query(
        '{ unresolvedReports(since: "2000-01-01T00:00:00+00:00") { id } }',
        remote_addr="192.168.1.9",
    )
    ids = [report["id"] for report in past_result["data"]["unresolvedReports"]]
    assert report_id in ids


def test_resolve_report_mutation_updates_resolved_and_note() -> None:
    created = _run_query("mutation { reportAd { id } }", remote_addr="192.168.1.3")
    report_id = created["data"]["reportAd"]["id"]

    result = _run_query(
        f'mutation {{ resolveReport(id: "{report_id}", '
        'resolutionNote: "example.com blocked") '
        "{ id resolved resolutionNote } }",
        remote_addr="192.168.1.3",
    )
    report = result["data"]["resolveReport"]

    assert report["resolved"] is True
    assert report["resolutionNote"] == "example.com blocked"


def test_resolve_report_mutation_errors_for_unknown_id() -> None:
    result = _run_query(
        'mutation { resolveReport(id: "999999") { id } }', remote_addr="192.168.1.4"
    )

    assert result["data"] is None
    assert any("not found" in error["message"] for error in result["errors"])


def test_candidate_domains_is_null_before_collection() -> None:
    created = _run_query(
        "mutation { reportAd { id candidateDomains } }", remote_addr="192.168.1.10"
    )

    assert created["data"]["reportAd"]["candidateDomains"] is None


def test_record_candidate_domains_mutation_sets_decoded_list() -> None:
    created = _run_query("mutation { reportAd { id } }", remote_addr="192.168.1.11")
    report_id = created["data"]["reportAd"]["id"]

    result = _run_query(
        f'mutation {{ recordCandidateDomains(id: "{report_id}", '
        'domains: ["a.example.com", "b.example.com"]) '
        "{ id candidateDomains } }",
        remote_addr="192.168.1.11",
    )

    assert result["data"]["recordCandidateDomains"]["candidateDomains"] == [
        "a.example.com",
        "b.example.com",
    ]


def test_record_candidate_domains_mutation_errors_for_unknown_id() -> None:
    result = _run_query(
        'mutation { recordCandidateDomains(id: "999999", domains: []) { id } }',
        remote_addr="192.168.1.12",
    )

    assert result["data"] is None
    assert any("not found" in error["message"] for error in result["errors"])


def test_graphql_service_sdl_query_returns_federation_sdl() -> None:
    result = _run_query("{ _service { sdl } }", remote_addr="192.168.1.6")

    sdl = result["data"]["_service"]["sdl"]
    assert isinstance(sdl, str) and len(sdl) > 0


def test_graphql_route_returns_errors_for_invalid_json_body() -> None:
    start_response, captured = _capturing_start_response()

    request_body = b"not valid json {{{"
    body = app(_graphql_environ(request_body), start_response)

    assert captured.status == "200 OK"
    assert json.loads(b"".join(body)) == {"errors": [{"message": "invalid JSON body"}]}


def test_version_route_returns_commit_sha_from_env() -> None:
    start_response, captured = _capturing_start_response()

    environ = {"PATH_INFO": "/version", "REQUEST_METHOD": "GET"}
    with patch.dict(os.environ, {"COMMIT_SHA": "abc1234"}):
        body = app(environ, start_response)

    assert captured.status == "200 OK"
    assert json.loads(b"".join(body)) == {"commit_sha": "abc1234"}
    assert ("Content-Type", "application/json") in captured.headers


def test_unknown_route_returns_404() -> None:
    start_response, captured = _capturing_start_response()

    environ = {"PATH_INFO": "/nope", "REQUEST_METHOD": "GET"}
    body = app(environ, start_response)

    assert captured.status == "404 Not Found"
    assert json.loads(b"".join(body)) == {"error": "not found"}


def test_graphql_get_request_returns_404() -> None:
    start_response, captured = _capturing_start_response()

    environ = {"PATH_INFO": "/graphql", "REQUEST_METHOD": "GET"}
    body = app(environ, start_response)

    assert captured.status == "404 Not Found"
    assert json.loads(b"".join(body)) == {"error": "not found"}
