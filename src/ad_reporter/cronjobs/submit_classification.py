import os

import requests

from ad_reporter.cronjobs._shared import graphql, pihole_auth, resolve_report

BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://graphql.morrisons.site/",
)
PIHOLE_URL = os.environ.get("PIHOLE_URL", "https://pihole.morrisons.site")
CLAUDE_URL = os.environ.get("CLAUDE_URL", "https://graphql.morrisons.site/")

_UNRESOLVED_REPORTS_QUERY = """
{ unresolvedReports { id candidateDomains classificationPromptId } }
"""

_SUBMIT_PROMPT_MUTATION = """
mutation($prompt: String!) {
  claude {
    submitPrompt(prompt: $prompt) {
      id
    }
  }
}
"""

_RECORD_CLASSIFICATION_PROMPT_ID_MUTATION = """
mutation($id: ID!, $promptId: String!) {
  recordClassificationPromptId(id: $id, promptId: $promptId) {
    id
  }
}
"""

_PROMPT_HEADER = (
    "For each of the following domains observed in a user's network traffic "
    "shortly after they reported seeing an ad, classify it as one of: "
    '"block" (confirmed ad/tracker/CMP vendor), "legit" (confirmed non-ad '
    "infrastructure, e.g. a major cloud/CDN provider or the core domain of a "
    'known software publisher), or "questionable" (not confidently '
    "classifiable either way — search the web if needed). Respond with ONLY "
    "a JSON array, no other text, in this exact shape: "
    '[{"domain": "...", "classification": "block"|"legit"|"questionable", '
    '"reason": "..."}].'
)


def _reports_ready_for_submission(reports: list[dict]) -> list[dict]:
    return [
        report
        for report in reports
        if report["candidateDomains"] and report["classificationPromptId"] is None
    ]


def _domain_already_covered(pihole_url: str, sid: str, domain: str) -> bool:
    response = requests.get(
        f"{pihole_url}/api/search/{domain}?n=3&partial=false",
        headers={"sid": sid},
    )
    response.raise_for_status()
    results = response.json()["results"]
    return (
        len(results["gravity"])
        + len(results["domains"]["exact"])
        + len(results["domains"]["regex"])
        > 0
    )


def main() -> None:
    reports = graphql(BACKEND_URL, _UNRESOLVED_REPORTS_QUERY)["data"][
        "unresolvedReports"
    ]
    reports = _reports_ready_for_submission(reports)

    if not reports:
        print("no reports ready for classification submission")
        return

    sid = pihole_auth(PIHOLE_URL)

    for report in reports:
        report_id = report["id"]

        uncovered_domains = [
            domain
            for domain in report["candidateDomains"]
            if not _domain_already_covered(PIHOLE_URL, sid, domain)
        ]

        if not uncovered_domains:
            print(f"report {report_id}: all candidate domains already covered")
            resolve_report(
                BACKEND_URL, report_id, "no ad domain found; candidates already covered"
            )
            continue

        prompt = f"{_PROMPT_HEADER}\n\nDomains:\n" + "\n".join(uncovered_domains) + "\n"

        submission = graphql(CLAUDE_URL, _SUBMIT_PROMPT_MUTATION, {"prompt": prompt})
        prompt_job_id = submission["data"]["claude"]["submitPrompt"]["id"]

        print(f"report {report_id}: submitted classification prompt {prompt_job_id}")

        graphql(
            BACKEND_URL,
            _RECORD_CLASSIFICATION_PROMPT_ID_MUTATION,
            {"id": report_id, "promptId": prompt_job_id},
        )
