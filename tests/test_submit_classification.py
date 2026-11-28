from unittest.mock import MagicMock, patch

from ad_reporter.cronjobs import submit_classification


def _mock_graphql_responses(*bodies: dict) -> MagicMock:
    return MagicMock(side_effect=list(bodies))


def _mock_search_response(gravity: int, exact: int, regex: int) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "results": {
            "gravity": [object()] * gravity,
            "domains": {"exact": [object()] * exact, "regex": [object()] * regex},
        }
    }
    return response


def test_main_does_nothing_when_no_reports_ready() -> None:
    graphql_mock = _mock_graphql_responses({"data": {"ad": {"unresolved": []}}})

    with (
        patch.object(submit_classification, "graphql", graphql_mock),
        patch.object(submit_classification, "pihole_auth") as pihole_auth,
    ):
        submit_classification.main()

    pihole_auth.assert_not_called()


def test_main_excludes_reports_without_candidates_or_already_submitted() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {
                            "id": "1",
                            "candidateDomains": None,
                            "classificationPromptId": None,
                        },
                        {
                            "id": "2",
                            "candidateDomains": [],
                            "classificationPromptId": None,
                        },
                        {
                            "id": "3",
                            "candidateDomains": ["a.example.com"],
                            "classificationPromptId": "already-submitted",
                        },
                    ]
                }
            }
        }
    )

    with (
        patch.object(submit_classification, "graphql", graphql_mock),
        patch.object(submit_classification, "pihole_auth") as pihole_auth,
    ):
        submit_classification.main()

    pihole_auth.assert_not_called()


def test_main_resolves_report_when_all_candidates_already_covered() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {
                            "id": "1",
                            "candidateDomains": ["covered.example.com"],
                            "classificationPromptId": None,
                        }
                    ]
                }
            }
        }
    )
    search_response = _mock_search_response(gravity=1, exact=0, regex=0)

    with (
        patch.object(submit_classification, "graphql", graphql_mock),
        patch.object(submit_classification, "pihole_auth", return_value="sid-123"),
        patch.object(
            submit_classification.requests, "get", return_value=search_response
        ) as get,
        patch.object(submit_classification, "resolve_report") as resolve_report,
    ):
        submit_classification.main()

    get.assert_called_once()
    assert "sid-123" == get.call_args.kwargs["headers"]["sid"]
    resolve_report.assert_called_once_with(
        submit_classification.BACKEND_URL,
        "1",
        "no ad domain found; candidates already covered",
    )


def test_main_submits_prompt_for_uncovered_domains_only() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "ad": {
                    "unresolved": [
                        {
                            "id": "1",
                            "candidateDomains": [
                                "covered.example.com",
                                "new.example.com",
                            ],
                            "classificationPromptId": None,
                        }
                    ]
                }
            }
        },
        {"data": {"claude": {"submitPrompt": {"id": "prompt-1"}}}},
        {"data": {"ad": {"recordClassificationPromptId": {"id": "1"}}}},
    )
    covered_response = _mock_search_response(gravity=1, exact=0, regex=0)
    uncovered_response = _mock_search_response(gravity=0, exact=0, regex=0)

    with (
        patch.object(submit_classification, "graphql", graphql_mock),
        patch.object(submit_classification, "pihole_auth", return_value="sid-123"),
        patch.object(
            submit_classification.requests,
            "get",
            side_effect=[covered_response, uncovered_response],
        ),
        patch.object(submit_classification, "resolve_report") as resolve_report,
    ):
        submit_classification.main()

    resolve_report.assert_not_called()
    assert graphql_mock.call_count == 3

    submit_call_args = graphql_mock.call_args_list[1][0]
    prompt = submit_call_args[2]["prompt"]
    assert "new.example.com" in prompt
    assert "covered.example.com" not in prompt

    record_call_args = graphql_mock.call_args_list[2][0]
    assert record_call_args[2] == {"id": "1", "promptId": "prompt-1"}
