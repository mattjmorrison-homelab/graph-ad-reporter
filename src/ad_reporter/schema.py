# Apollo Federation subgraph schema for the ad-reporter service.
# Uses strawberry.federation.Schema to enable the _service { sdl } introspection
# field that Apollo Gateway/Router needs for subgraph composition.
import datetime
import json

import strawberry

from ad_reporter import db


@strawberry.federation.type
class Report:
    id: strawberry.ID
    timestamp: datetime.datetime
    client_ip: str
    resolved: bool
    resolution_note: str | None
    candidate_domains: list[str] | None


def _report_from_row(row: db.ReportRow) -> Report:
    return Report(
        id=strawberry.ID(str(row.id)),
        timestamp=datetime.datetime.fromisoformat(row.timestamp),
        client_ip=row.client_ip,
        resolved=row.resolved,
        resolution_note=row.resolution_note,
        candidate_domains=(
            json.loads(row.candidate_domains)
            if row.candidate_domains is not None
            else None
        ),
    )


def _client_ip(info: strawberry.types.Info) -> str:
    """Read the caller's LAN IP from WSGI environ, which is passed as the
    GraphQL context_value (see wsgi.py). Traefik forwards the real client
    address via X-Forwarded-For; REMOTE_ADDR is the fallback for direct
    (non-proxied) requests. Never a client-supplied argument -- this must
    not be spoofable by whoever is calling the mutation.
    """
    environ = info.context
    forwarded = environ.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return environ.get("REMOTE_ADDR", "")


@strawberry.type
class AdQuery:
    @strawberry.field
    def unresolved(
        self, since: datetime.datetime | None = None
    ) -> list[Report]:
        since_str = since.isoformat() if since is not None else None
        rows = db.unresolved_reports(since=since_str)
        return [_report_from_row(row) for row in rows]


@strawberry.type
class AdMutation:
    @strawberry.field
    def report_ad(self, info: strawberry.types.Info) -> Report:
        client_ip = _client_ip(info)
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()
        row = db.insert_report(timestamp=timestamp, client_ip=client_ip)
        return _report_from_row(row)

    @strawberry.field
    def resolve(
        self, id: strawberry.ID, resolution_note: str | None = None
    ) -> Report:
        row = db.resolve_report(int(id), resolution_note)
        if row is None:
            raise ValueError(f"report {id} not found")
        return _report_from_row(row)

    @strawberry.field
    def record_candidate_domains(self, id: strawberry.ID, domains: list[str]) -> Report:
        row = db.record_candidate_domains(int(id), domains)
        if row is None:
            raise ValueError(f"report {id} not found")
        return _report_from_row(row)


@strawberry.type
class Query:
    @strawberry.field
    def ad(self) -> AdQuery:
        return AdQuery()


@strawberry.type
class Mutation:
    @strawberry.field
    def ad(self) -> AdMutation:
        return AdMutation()


schema = strawberry.federation.Schema(query=Query, mutation=Mutation)
