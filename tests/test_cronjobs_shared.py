from unittest.mock import MagicMock, patch

import pytest

from ad_reporter.cronjobs import _shared


def _mock_response(json_body: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_body
    return response


def test_graphql_posts_query_and_variables_and_returns_parsed_body() -> None:
    response = _mock_response({"data": {"ok": True}})

    with patch.object(_shared.requests, "post", return_value=response) as post:
        result = _shared.graphql("http://backend.test/graphql", "{ ping }", {"a": 1})

    post.assert_called_once_with(
        "http://backend.test/graphql",
        json={"query": "{ ping }", "variables": {"a": 1}},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status.assert_called_once()
    assert result == {"data": {"ok": True}}


def test_graphql_raises_for_non_2xx_response() -> None:
    response = _mock_response({})
    response.raise_for_status.side_effect = _shared.requests.HTTPError("boom")

    with (
        patch.object(_shared.requests, "post", return_value=response),
        pytest.raises(_shared.requests.HTTPError),
    ):
        _shared.graphql("http://backend.test/graphql", "{ ping }")


def test_resolve_report_calls_resolve_report_mutation() -> None:
    response = _mock_response({"data": {"resolveReport": {"id": "1"}}})

    with patch.object(_shared.requests, "post", return_value=response) as post:
        _shared.resolve_report("http://backend.test/graphql", "1", "handled")

    _, kwargs = post.call_args
    assert kwargs["json"]["variables"] == {"id": "1", "note": "handled"}
    assert "resolveReport" in kwargs["json"]["query"]


def test_pihole_auth_returns_session_sid() -> None:
    response = _mock_response({"session": {"sid": "abc123"}})

    with patch.object(_shared.requests, "post", return_value=response) as post:
        sid = _shared.pihole_auth("http://pihole.test")

    post.assert_called_once_with(
        "http://pihole.test/api/auth",
        json={"password": ""},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status.assert_called_once()
    assert sid == "abc123"
