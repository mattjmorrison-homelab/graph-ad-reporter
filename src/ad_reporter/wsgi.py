import json
import os
from wsgiref.types import StartResponse, WSGIEnvironment

from ad_reporter.schema import schema


def _handle_graphql_request(environ: WSGIEnvironment) -> bytes:
    """Execute a GraphQL query from a JSON request body.
    Reads query and optional variables per GraphQL-over-HTTP spec, executes against
    the federation schema, and returns {"data": ...} or {"data": ..., "errors": ...}.
    Malformed JSON is caught and reported gracefully; errors are always returned in
    the response body with 200 OK status per GraphQL convention. The raw WSGI
    environ is passed through as context_value so resolvers (report_ad) can read
    the caller's IP from request headers.
    """
    content_length = int(environ.get("CONTENT_LENGTH", 0))
    request_body = environ["wsgi.input"].read(content_length)
    try:
        payload = json.loads(request_body)
    except json.JSONDecodeError:
        return json.dumps({"errors": [{"message": "invalid JSON body"}]}).encode(
            "utf-8"
        )

    result = schema.execute_sync(
        payload["query"],
        variable_values=payload.get("variables"),
        context_value=environ,
    )
    response_data: dict[str, object] = {"data": result.data}
    if result.errors:
        # GraphQL-over-HTTP requires each entry in `errors` to be an object
        # with a `message` key, not a bare string — Apollo Router rejects
        # subgraph responses that don't conform to this.
        response_data["errors"] = [{"message": str(error)} for error in result.errors]
    return json.dumps(response_data).encode("utf-8")


def app(environ: WSGIEnvironment, start_response: StartResponse) -> list[bytes]:
    if (
        environ.get("PATH_INFO") == "/graphql"
        and environ.get("REQUEST_METHOD") == "POST"
    ):
        body = _handle_graphql_request(environ)
        headers = [("Content-Type", "application/json")]
        start_response("200 OK", headers)
        return [body]

    if environ.get("PATH_INFO") == "/version":
        # k8s-ad-reporter's PostSync verify Job polls this endpoint post-deploy
        # to confirm the live pod is running the just-deployed commit.
        commit_sha = os.environ.get("COMMIT_SHA", "unknown")
        body = json.dumps({"commit_sha": commit_sha}).encode("utf-8")
        headers = [("Content-Type", "application/json")]
        start_response("200 OK", headers)
        return [body]

    body = json.dumps({"error": "not found"}).encode("utf-8")
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    start_response("404 Not Found", headers)
    return [body]
