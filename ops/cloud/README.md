# Configuration preflight container

## Scope

This is an optional, one-shot operations image. It runs the existing
`transcript_app/config.py` loader without changing application configuration,
credentials, or authentication behavior. It is not a FastAPI server, a React
build, a transcription worker, or a deployable replacement for the application.
Only the configuration module was available when this slice was proposed.

No cloud provider, registry, runtime, or deployment environment is selected.
There are no cloud resources, publishing steps, deployment actions, or CI secrets
in this slice. Existing application workflows and security controls are untouched.

## Local build and smoke check

Run from the repository root with a Docker builder supporting Dockerfile-specific
ignore files:

```sh
docker build --pull -f ops/cloud/Dockerfile -t transcript-config-preflight:local .
docker run --rm --read-only --network none \
  --cap-drop ALL --security-opt no-new-privileges=true \
  --pids-limit 64 --memory 128m --cpus 1 \
  --env AZURE_SPEECH_KEY=non-secret-preflight-placeholder \
  --env AZURE_SPEECH_REGION=westeurope \
  transcript-config-preflight:local
```

The placeholder is intentionally not an Azure credential. This command does not
contact Azure. To check existing runtime configuration, pass the corresponding
exported variables with `--env AZURE_SPEECH_KEY`, `--env AZURE_SPEECH_REGION`,
`--env AZURE_SPEECH_ENDPOINT`, and optionally `--env AZURE_SPEECH_LANGUAGE`.
Do not place credential values in image build arguments, Dockerfiles, committed
files, command-line literals, or CI logs. Real credentials are unnecessary for
all proposed CI checks.

The image contains no `.env` file. The existing loader retains dotenv support;
its application behavior is not changed by this operations image. Docker access
is privileged: runtime environment injection does not hide credentials from
host administrators or Docker daemon operators.

## Contract and observability

The process writes one JSON event to stdout on each handled execution path:

- `event`: `transcript.configuration_preflight`
- `scope`: `configuration_only`
- `timestamp`: UTC ISO 8601 timestamp
- `outcome`: `ready`, `not_ready`, or `error`
- `reason`: a fixed, non-sensitive classification
- `duration_ms`: local elapsed time

Exit codes are:

| Code | Meaning |
| --- | --- |
| 0 | Existing configuration loader accepted the supplied configuration. |
| 1 | Loader raised a configuration RuntimeError. |
| 2 | An unexpected dependency, import, or loader error occurred. |

Settings, key values, regions, endpoints, languages, exception messages, and
tracebacks are not included in these events. Infrastructure failures before
Python starts remain Docker or runner failures, not preflight events.

Acceptance only means that the current loader accepted a key and a region or
endpoint. It does not establish credential validity, endpoint reachability,
Azure authorization, transcription correctness, service readiness, or service
liveness. The probe intentionally preserves the loader's existing validation
rather than adding new restrictions. Do not wire this batch image to HTTP
readiness checks or use it as the application health check.

No telemetry exporter is configured because no telemetry destination was
selected. Application metrics, traces, request correlation, and privacy-safe
request logging require the backend owner's implementation and review.

## Identity and isolation

The image runs as numeric UID/GID `10001:10001`. Application and dependency files
are not owned by that runtime user. CI additionally enforces a read-only root
filesystem, no network, dropped Linux capabilities, no-new-privileges, and
resource limits. The Dockerfile does not itself enforce every runtime flag;
future runtime configuration must preserve these restrictions where applicable.

The GitHub workflow uses `contents: read`, a commit-pinned checkout action, and
`persist-credentials: false`. It uses ordinary pull-request events, not
`pull_request_target`, and does not request an OIDC token. It builds only a local
runner image and publishes nothing. Keep untrusted builds off privileged
self-hosted runners.

The current loader requires `AZURE_SPEECH_KEY`. Container identity is not Azure
managed identity and does not remove that requirement. A backend adapter must
first establish SDK support and preserve key-based behavior before managed
Speech identity can be offered as an alternative.

If deployment is later approved, add a separate reviewed workflow with an
explicit target. Scope OIDC trust to the exact repository and approved
branch/environment, request `id-token: write` only in the job needing it, and
grant only the required registry/runtime permissions. Require protected
environments and approval for production. Do not introduce long-lived cloud
credentials or subscription-wide contributor access as a shortcut.

## Dependencies and supply chain

`requirements.txt` is exclusively for this operations image; it is not an
application dependency manifest. Its dotenv pin needs compatibility and
vulnerability review against the application's authoritative dependencies.

The base-image tag receives upstream changes and is not an immutable supply-chain
pin. Before production adoption, resolve and review an actual supported image
digest, scan the image and dependency, and define a refresh process. Do not invent
a digest or claim this proposal provides reproducible builds. No generated scan
reports, lock files, or binary artifacts are committed by this slice.

The Dockerfile-specific allowlist excludes repository history, credentials,
`.env` files, and unrelated source from this build context. It does not replace
secret scanning or the ignore rules of other Dockerfiles.

## Required verification and handoffs

No commands or tests were executed as part of this proposal. The workflow defines
build and operational smoke checks; it does not replace the existing test suite.

The Testing Agent should own automated coverage for:

1. Key plus region, key plus endpoint, both location settings, and missing or empty
   required settings, preserving the authoritative loader's semantics.
2. Language default `ro-RO`, explicit overrides, and unchanged dotenv behavior.
3. Exact exit codes and structured event fields, including unexpected failures.
4. Secret redaction from stdout and stderr using sentinel keys, endpoints, and
   exception messages.
5. Successful restricted-runtime execution and exclusion of a sentinel `.env`
   and unrelated files from the image/build context.

Platform verification must include workflow linting, effective permission review,
image/dependency scanning, and validation on the chosen Docker builder.

Backend ownership is required for the actual FastAPI entrypoint, complete service
dependencies, authentication integration, graceful shutdown, and distinct
liveness/readiness behavior. Frontend ownership is required for the React 19 and
TypeScript build contract. Once those contracts and a cloud target are supplied,
platform can add application containers, runtime secret injection, telemetry
routing, narrowly scoped cloud federation, and reviewed delivery configuration.
