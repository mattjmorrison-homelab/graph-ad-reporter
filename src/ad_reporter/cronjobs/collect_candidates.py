import datetime
import os
import re

import requests

from ad_reporter.cronjobs._shared import graphql

BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://graphql.morrisons.site/",
)
PIHOLE_URL = os.environ.get("PIHOLE_URL", "http://pihole.pihole.svc.cluster.local:8080")
WINDOW_SECONDS = 180

_FORWARDED_STATUSES = ("FORWARDED", "CACHE", "CACHE_STALE")

_UNRESOLVED_REPORTS_QUERY = """
{ ad { unresolved { id timestamp candidateDomains } } }
"""

_RECORD_CANDIDATE_DOMAINS_MUTATION = """
mutation($id: ID!, $domains: [String!]!) {
  ad {
    recordCandidateDomains(id: $id, domains: $domains) {
      id
    }
  }
}
"""


def _report_epoch_seconds(timestamp: str) -> float:
    without_fraction = re.sub(r"\.[0-9]+", "", timestamp, count=1)
    normalized = re.sub(r"\+00:00$", "Z", without_fraction)
    return datetime.datetime.fromisoformat(normalized).timestamp()


def _candidate_domains(pihole_queries: list[dict], report_epoch: float) -> list[str]:
    domains = set()
    for pihole_query in pihole_queries:
        if pihole_query["status"] not in _FORWARDED_STATUSES:
            continue
        if abs(pihole_query["time"] - report_epoch) > WINDOW_SECONDS:
            continue
        domains.add(pihole_query["domain"])
    return sorted(domains)


def main() -> None:
    reports = graphql(BACKEND_URL, _UNRESOLVED_REPORTS_QUERY)["data"]["ad"][
        "unresolved"
    ]

    if not reports:
        print("no unresolved reports")
        return

    response = requests.get(f"{PIHOLE_URL}/api/queries?length=500")
    response.raise_for_status()
    pihole_queries = response.json()["queries"]

    for report in reports:
        report_id = report["id"]

        if report["candidateDomains"] is not None:
            print(f"report {report_id}: already collected, skipping")
            continue

        report_epoch = _report_epoch_seconds(report["timestamp"])
        domains = _candidate_domains(pihole_queries, report_epoch)

        print(f"report {report_id}: found domains {domains}")

        graphql(
            BACKEND_URL,
            _RECORD_CANDIDATE_DOMAINS_MUTATION,
            {"id": report_id, "domains": domains},
        )
