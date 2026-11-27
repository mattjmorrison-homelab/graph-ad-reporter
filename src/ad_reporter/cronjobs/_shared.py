import requests

_RESOLVE_REPORT_MUTATION = """
mutation($id: ID!, $note: String!) {
  resolveReport(id: $id, resolutionNote: $note) {
    id
  }
}
"""


def graphql(url: str, query: str, variables: dict | None = None) -> dict:
    response = requests.post(
        url,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def resolve_report(backend_url: str, report_id: str, resolution_note: str) -> None:
    graphql(
        backend_url,
        _RESOLVE_REPORT_MUTATION,
        {"id": report_id, "note": resolution_note},
    )


def pihole_auth(pihole_url: str) -> str:
    response = requests.post(
        f"{pihole_url}/api/auth",
        json={"password": ""},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    return response.json()["session"]["sid"]
