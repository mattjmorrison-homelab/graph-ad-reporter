# release and test each have their own external FROM instead of extending
# a shared base stage: kaniko pushes a Docker-v2-schema manifest (which
# zot rejects with 415/MANIFEST_INVALID) when a pushed --target stage's
# own FROM references another Dockerfile stage rather than an external
# image, confirmed by reproducing locally against a throwaway registry
# (see graph-hdmi-switch, the precedent this repo mirrors).
#
# amd64 digests (unlike graph-hdmi-switch, which pins arm64 for physical
# serial access on pi5-8) -- this service has no hardware dependency, so
# it builds/runs on the k8s-amd64 runner/nodes like graph-router.

FROM python:3.12-slim-bookworm@sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4 AS release
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:c7db1d63057f268a8b6da8af9077850a60461f98d23db23c676a82089a050c91 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
ARG COMMIT_SHA
ENV COMMIT_SHA=$COMMIT_SHA
RUN uv sync --frozen --no-dev
EXPOSE 8000
ENTRYPOINT ["uv", "run", "gunicorn", "ad_reporter.wsgi:app", "--bind", "0.0.0.0:8000"]

FROM python:3.12-slim-bookworm@sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4 AS test
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:c7db1d63057f268a8b6da8af9077850a60461f98d23db23c676a82089a050c91 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen
COPY tests ./tests
ENTRYPOINT ["uv", "run"]
