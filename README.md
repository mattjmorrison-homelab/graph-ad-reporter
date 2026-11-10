# graph-ad-reporter

GraphQL API + SQLite storage for the "I just saw an ad" reporter. A
`uv`-managed Python project serving a `strawberry.federation.Schema`
subgraph over plain WSGI (`gunicorn`), same structural pattern as
`graph-hdmi-switch`. Deploys to `k8s-ad-reporter`.

## Schema

```graphql
type Report {
  id: ID!
  timestamp: DateTime!
  clientIp: String!
  resolved: Boolean!
  resolutionNote: String
}

type Query {
  unresolvedReports(since: DateTime): [Report!]!
}

type Mutation {
  reportAd: Report!
  resolveReport(id: ID!, resolutionNote: String): Report!
}
```

- `reportAd` reads the caller's `client_ip` server-side from the
  `X-Forwarded-For` header (Traefik forwards the real LAN IP in front of
  this service), falling back to the WSGI `REMOTE_ADDR` if absent. It is
  never a client-supplied argument, so it can't be spoofed by whoever
  calls the mutation.
- `unresolvedReports` filters to `resolved = false`, and to
  `timestamp >= since` when `since` is given.

## Storage

One SQLite file, path set by `AD_REPORTER_DB_PATH` (default
`/data/ad-reporter.db`, matching where `k8s-ad-reporter`'s PVC is
mounted):

```sql
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,      -- ISO 8601 UTC
    client_ip TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution_note TEXT
);
```

## Files

- `src/ad_reporter/db.py` — SQLite access (schema creation, CRUD).
- `src/ad_reporter/schema.py` — the federation schema (`Report`,
  `Query`, `Mutation`) and `client_ip` capture.
- `src/ad_reporter/wsgi.py` — the WSGI app: `/graphql` (POST), `/version`.
- `scripts/verify-deploy.sh` — polls `/version` post-publish until it
  matches the just-built commit SHA.

## Local setup

```sh
nix-shell -p uv python312
uv sync
uv run pytest
```

## `/version`

Returns `{"commit_sha": ...}`, baked in at image build time via the
`COMMIT_SHA` build arg (see `Dockerfile`). `k8s-ad-reporter`'s `PostSync`
verify Job polls this to confirm the live pod is running the
just-deployed commit.
