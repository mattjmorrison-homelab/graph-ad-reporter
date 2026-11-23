import json
import os
import re

import requests

from ad_reporter.cronjobs._shared import graphql, pihole_auth, resolve_report

BACKEND_URL = os.environ.get(
    "BACKEND_URL", "http://ad-reporter-backend.ad-reporter.svc.cluster.local:8000/graphql"
)
PIHOLE_URL = os.environ.get("PIHOLE_URL", "https://pihole.morrisons.site")
CLAUDE_URL = os.environ.get("CLAUDE_URL", "https://graphql.morrisons.site/")
CONFIRMED_WEBHOOK_URL = os.environ["CONFIRMED_WEBHOOK_URL"]
SUSPICIOUS_WEBHOOK_URL = os.environ["SUSPICIOUS_WEBHOOK_URL"]

_UNRESOLVED_REPORTS_QUERY = """
{ unresolvedReports { id classificationPromptId } }
"""

_PROMPT_JOB_QUERY = """
query($id: ID!) {
  claude {
    promptJob(id: $id) {
      status
      response
      error
    }
  }
}
"""

_JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)


def _reports_awaiting_classification(reports: list[dict]) -> list[dict]:
    return [report for report in reports if report["classificationPromptId"] is not None]


def _parse_classification_entries(raw_response: str) -> list[dict] | None:
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        pass

    match = _JSON_ARRAY_PATTERN.search(raw_response)
    if match is None:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _block_domain(pihole_url: str, domain: str, report_id: str) -> None:
    sid = pihole_auth(pihole_url)
    pattern = r"(\.|^)" + domain.replace(".", r"\.") + r"$"
    response = requests.post(
        f"{pihole_url}/api/domains/deny/regex",
        headers={"sid": sid},
        json={
            "domain": [pattern],
            "comment": f"ad-reporter: report {report_id}",
            "enabled": True,
        },
    )
    response.raise_for_status()


def _notify_discord(webhook_url: str, message: str) -> None:
    response = requests.post(webhook_url, json={"content": message})
    response.raise_for_status()


def _handle_pending(report_id: str, prompt_job_id: str) -> None:
    print(f"report {report_id}: classification prompt {prompt_job_id} still pending")


def _handle_failed(report_id: str, prompt_job_id: str, job: dict) -> None:
    job_error = job["error"] or "unknown error"
    print(f"report {report_id}: classification prompt {prompt_job_id} failed: {job_error}")
    resolve_report(BACKEND_URL, report_id, f"classification failed: {job_error}")


def _handle_completed(report_id: str, job: dict) -> None:
    entries = _parse_classification_entries(job["response"])
    if entries is None:
        print(f"report {report_id}: could not parse classification response")
        resolve_report(BACKEND_URL, report_id, "could not parse classification response")
        return

    blocked_domains = []
    questionable_count = 0

    for entry in entries:
        domain = entry["domain"]
        classification = entry["classification"]
        reason = entry["reason"]

        if classification == "block":
            _block_domain(PIHOLE_URL, domain, report_id)
            _notify_discord(
                CONFIRMED_WEBHOOK_URL,
                f"Blocked ad domain `{domain}` for report {report_id}: {reason}",
            )
            blocked_domains.append(domain)
        elif classification == "questionable":
            _notify_discord(
                SUSPICIOUS_WEBHOOK_URL,
                f"Questionable domain `{domain}` for report {report_id}: {reason}",
            )
            questionable_count += 1

    if blocked_domains:
        summary = f"blocked {', '.join(blocked_domains)}"
    else:
        summary = "no domains blocked"
    if questionable_count > 0:
        summary = f"{summary}, {questionable_count} questionable"

    resolve_report(BACKEND_URL, report_id, summary)


def main() -> None:
    reports = graphql(BACKEND_URL, _UNRESOLVED_REPORTS_QUERY)["data"]["unresolvedReports"]
    reports = _reports_awaiting_classification(reports)

    if not reports:
        print("no reports awaiting classification results")
        return

    for report in reports:
        report_id = report["id"]
        prompt_job_id = report["classificationPromptId"]

        job = graphql(CLAUDE_URL, _PROMPT_JOB_QUERY, {"id": prompt_job_id})["data"]["claude"][
            "promptJob"
        ]
        status = job["status"]

        if status == "PENDING":
            _handle_pending(report_id, prompt_job_id)
        elif status == "FAILED":
            _handle_failed(report_id, prompt_job_id, job)
        elif status == "COMPLETED":
            _handle_completed(report_id, job)
