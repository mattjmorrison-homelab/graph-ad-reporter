from unittest.mock import MagicMock, patch

from ad_reporter.cronjobs import collect_candidates


def _mock_graphql_responses(*bodies: dict) -> MagicMock:
    mock = MagicMock(side_effect=list(bodies))
    return mock


def _mock_pihole_queries_response(queries: list[dict]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"queries": queries}
    return response


def test_main_does_nothing_when_no_unresolved_reports() -> None:
    graphql_mock = _mock_graphql_responses({"data": {"unresolvedReports": []}})

    with (
        patch.object(collect_candidates, "graphql", graphql_mock),
        patch.object(collect_candidates.requests, "get") as get,
    ):
        collect_candidates.main()

    get.assert_not_called()


def test_main_skips_report_with_candidate_domains_already_set() -> None:
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "unresolvedReports": [
                    {
                        "id": "1",
                        "timestamp": "2026-11-10T00:00:00+00:00",
                        "candidateDomains": ["already.example.com"],
                    }
                ]
            }
        }
    )
    pihole_response = _mock_pihole_queries_response([])

    with (
        patch.object(collect_candidates, "graphql", graphql_mock),
        patch.object(collect_candidates.requests, "get", return_value=pihole_response),
    ):
        collect_candidates.main()

    assert graphql_mock.call_count == 1


def test_main_collects_matching_domains_within_window() -> None:
    report_epoch = collect_candidates._report_epoch_seconds(
        "2026-11-10T00:00:00.123456+00:00"
    )
    graphql_mock = _mock_graphql_responses(
        {
            "data": {
                "unresolvedReports": [
                    {
                        "id": "1",
                        "timestamp": "2026-11-10T00:00:00.123456+00:00",
                        "candidateDomains": None,
                    }
                ]
            }
        },
        {"data": {"recordCandidateDomains": {"id": "1"}}},
    )
    pihole_response = _mock_pihole_queries_response(
        [
            {
                "status": "FORWARDED",
                "time": report_epoch + 10,
                "domain": "ads.example.com",
            },
            {
                "status": "CACHE",
                "time": report_epoch - 10,
                "domain": "tracker.example.com",
            },
            {
                "status": "CACHE_STALE",
                "time": report_epoch + collect_candidates.WINDOW_SECONDS + 100,
                "domain": "too-late.example.com",
            },
            {
                "status": "GRAVITY",
                "time": report_epoch,
                "domain": "blocked-already.example.com",
            },
        ]
    )

    with (
        patch.object(collect_candidates, "graphql", graphql_mock),
        patch.object(collect_candidates.requests, "get", return_value=pihole_response),
    ):
        collect_candidates.main()

    assert graphql_mock.call_count == 2
    second_call_args = graphql_mock.call_args_list[1][0]
    variables = second_call_args[2]
    assert variables["id"] == "1"
    assert variables["domains"] == ["ads.example.com", "tracker.example.com"]


def test_report_epoch_seconds_strips_fraction_and_normalizes_offset() -> None:
    with_fraction = collect_candidates._report_epoch_seconds(
        "2026-11-10T00:00:00.123456+00:00"
    )
    without_fraction = collect_candidates._report_epoch_seconds(
        "2026-11-10T00:00:00+00:00"
    )

    assert with_fraction == without_fraction
