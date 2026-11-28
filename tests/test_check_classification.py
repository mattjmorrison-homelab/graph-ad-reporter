from unittest.mock import MagicMock, patch

from ad_reporter.cronjobs import check_classification


def _mock_graphql_responses(*bodies: dict) -> MagicMock:
    return MagicMock(side_effect=list(bodies))


def _job_response(body: dict) -> dict:
    return {"data": {"claude": {"promptJob": body}}}


def test_main_does_nothing_when_no_reports_awaiting_classification() -> None:
    graphql_mock = _mock_graphql_responses({"data": {"ad": {"unresolved": []}}})

    with patch.object(check_classification, "graphql", graphql_mock):
        check_classification.main()

    assert graphql_mock.call_count == 1


def test_main_ignores_reports_without_classification_prompt_id() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": None},
                    ]
                }
            }
        }
    )

    with patch.object(check_classification, "graphql", graphql_mock):
        check_classification.main()

    assert graphql_mock.call_count == 1


def test_main_leaves_pending_report_untouched() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response({"status": "PENDING", "response": None, "error": None}),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_not_called()


def test_main_resolves_failed_report_with_error_message() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response(
            {"status": "FAILED", "response": None, "error": "model unavailable"}
        ),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL,
        "1",
        "classification failed: model unavailable",
    )


def test_main_resolves_failed_report_with_unknown_error_fallback() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response({"status": "FAILED", "response": None, "error": None}),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL,
        "1",
        "classification failed: unknown error",
    )


def test_main_resolves_report_when_response_cannot_be_parsed() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response(
            {"status": "COMPLETED", "response": "not json at all", "error": None}
        ),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL,
        "1",
        "could not parse classification response",
    )


def test_main_resolves_report_when_extracted_array_is_still_invalid() -> None:
    raw_response = "here you go: [this is not valid json] thanks"
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response({"status": "COMPLETED", "response": raw_response, "error": None}),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL,
        "1",
        "could not parse classification response",
    )


def test_main_parses_response_with_stray_text_around_json_array() -> None:
    raw_response = (
        "Sure, here is the result:\n"
        '[{"domain": "legit.example.com", "classification": "legit", '
        '"reason": "cdn"}]\n'
        "Hope that helps!"
    )
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response({"status": "COMPLETED", "response": raw_response, "error": None}),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL, "1", "no domains blocked"
    )


def test_main_handles_block_questionable_and_legit_entries() -> None:
    response_body = (
        '[{"domain": "ads.example.com", "classification": "block", '
        '"reason": "known tracker"},'
        '{"domain": "weird.example.com", "classification": "questionable", '
        '"reason": "unclear"},'
        '{"domain": "cdn.example.com", "classification": "legit", '
        '"reason": "major cdn"}]'
    )
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response(
            {"status": "COMPLETED", "response": response_body, "error": None}
        ),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "pihole_auth", return_value="sid-123"),
        patch.object(check_classification.requests, "post") as post,
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    post_urls = [call.args[0] for call in post.call_args_list]
    assert f"{check_classification.PIHOLE_URL}/api/domains/deny/regex" in post_urls
    assert check_classification.CONFIRMED_WEBHOOK_URL in post_urls
    assert check_classification.SUSPICIOUS_WEBHOOK_URL in post_urls

    deny_call = next(
        call
        for call in post.call_args_list
        if call.args[0] == f"{check_classification.PIHOLE_URL}/api/domains/deny/regex"
    )
    assert deny_call.kwargs["json"]["domain"] == [r"(\.|^)ads\.example\.com$"]
    assert deny_call.kwargs["headers"] == {"sid": "sid-123"}

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL,
        "1",
        "blocked ads.example.com, 1 questionable",
    )


def test_main_reports_no_domains_blocked_with_no_questionable_suffix() -> None:
    response_body = (
        '[{"domain": "cdn.example.com", "classification": "legit", '
        '"reason": "major cdn"}]'
    )
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {"id": "1", "classificationPromptId": "job-1"},
                    ]
                }
            }
        },
        _job_response(
            {"status": "COMPLETED", "response": response_body, "error": None}
        ),
    )

    with (
        patch.object(check_classification, "graphql", graphql_mock),
        patch.object(check_classification, "resolve_report") as resolve_report,
    ):
        check_classification.main()

    resolve_report.assert_called_once_with(
        check_classification.BACKEND_URL, "1", "no domains blocked"
    )
