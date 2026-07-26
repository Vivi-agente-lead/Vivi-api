# Delta for demo-deployment

## ADDED Requirements

### Requirement: Fly.io US Region Demo Deployment

The system MUST be deployable to Fly.io in a US region for the juror demo, exposing `uvicorn app.main:app` at a public HTTPS URL reachable by the Meta webhook verifier.

#### Scenario: API reachable at public Fly URL

- GIVEN the app is deployed to Fly.io US region
- WHEN `curl -i https://<fly-app>.fly.dev/health` (or equivalent health route) is invoked
- THEN the response status is 200 and the body confirms the app is running

#### Scenario: Health reflects readiness, not just liveness

- GIVEN the app is running but schema creation failed (unreachable database, wrong DSN)
- WHEN `GET /health` is invoked
- THEN the response status is 503 and the body names the failed dependency
- AND `GET /health` MUST NOT return 200 while the database is unusable — the FastAPI lifespan currently swallows `init_db()` failures with a warning, which would let this deployment scenario pass against a completely non-functional demo

#### Scenario: WhatsApp webhook verifies at Fly URL

- GIVEN the Fly app is running and the operator has copied the Fly public URL into the Meta WhatsApp dashboard's webhook config
- WHEN Meta issues the `GET /whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>` verification request
- THEN the Fly app echoes the `hub.challenge` and Meta marks the webhook as verified

#### Scenario: OpenAI call succeeds from Fly US (no 403)

- GIVEN the Fly deploy is configured with `OPENAI_API_KEY` and `OPENAI_BASE_URL` points to the standard OpenAI endpoint
- WHEN any agent graph node invokes the LLM during a webhook-driven conversation
- THEN the LLM call returns 200 (no 403 geo-block from Venezuela) and produces an assistant message

### Requirement: Public Deployment Hardening

Exposing the app at a public HTTPS URL turns two development affordances into
externally reachable surfaces. Both MUST be closed before the Fly deploy.

#### Scenario: Dev simulator is unreachable in a deployed environment

- GIVEN the app is deployed with `APP_ENV` set to anything other than `development`
- WHEN `POST /whatsapp/simulate` is requested
- THEN the response is 404 — the route is not registered
- AND the route MUST NOT be publicly reachable with `dry_run=false`, which would make the deployment an open relay capable of sending arbitrary WhatsApp messages to arbitrary recipients through the project's Meta credentials

#### Scenario: Webhook rejects unsigned payloads

- GIVEN Meta signs every webhook POST with an `X-Hub-Signature-256` header derived from the app secret
- WHEN `POST /whatsapp/webhook` receives a request whose signature is absent or does not verify
- THEN the response is 403 and no conversation is created and no LLM call is made
- AND the `hub.verify_token` check MUST NOT be treated as covering the POST route — it guards only the `GET` handshake

### Requirement: Juror Demo Walkthrough

The README MUST contain a juror demo walkthrough under 5 minutes that includes: the Fly URL, the 3 demo-star afiliado cedulas (one per categoria × band), the expected branch each cedula triggers, and the dry_run simulator commands for local rehearsal.

#### Scenario: README contains the four mandatory pieces

- GIVEN the repository README is read end-to-end
- WHEN a juror scans it
- THEN the README contains (a) the Fly URL placeholder, (b) the 3 demo-star cedulas with their categoria/band and expected outcome, (c) the `curl` or `http` commands to drive the simulator, (d) the Meta webhook verify token placeholder
- AND a reader following the walkthrough verbatim can run a full READY classification against the Fly URL within 5 minutes

#### Scenario: README describes the application that exists

- GIVEN the README's "What works" and "What is not done yet" sections
- WHEN each claim is checked against the mounted routers in `app/main.py`
- THEN every claimed endpoint exists and every endpoint that exists is claimed
- AND the README MUST NOT advertise the SSE route `GET /conversations/{id}/messages/stream`, which is not mounted, nor describe the WhatsApp channel as "stubbed at `app/routers/webhook.py`" — WhatsApp is the only implemented channel and no such file exists