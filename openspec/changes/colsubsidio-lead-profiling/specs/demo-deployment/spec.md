# Delta for demo-deployment

## ADDED Requirements

### Requirement: Fly.io US Region Demo Deployment

The system MUST be deployable to Fly.io in a US region for the juror demo, exposing `uvicorn app.main:app` at a public HTTPS URL reachable by the Meta webhook verifier.

#### Scenario: API reachable at public Fly URL

- GIVEN the app is deployed to Fly.io US region
- WHEN `curl -i https://<fly-app>.fly.dev/health` (or equivalent health route) is invoked
- THEN the response status is 200 and the body confirms the app is running

#### Scenario: WhatsApp webhook verifies at Fly URL

- GIVEN the Fly app is running and the operator has copied the Fly public URL into the Meta WhatsApp dashboard's webhook config
- WHEN Meta issues the `GET /whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>` verification request
- THEN the Fly app echoes the `hub.challenge` and Meta marks the webhook as verified

#### Scenario: OpenAI call succeeds from Fly US (no 403)

- GIVEN the Fly deploy is configured with `OPENAI_API_KEY` and `OPENAI_BASE_URL` points to the standard OpenAI endpoint
- WHEN any agent graph node invokes the LLM during a webhook-driven conversation
- THEN the LLM call returns 200 (no 403 geo-block from Venezuela) and produces an assistant message

### Requirement: Juror Demo Walkthrough

The README MUST contain a juror demo walkthrough under 5 minutes that includes: the Fly URL, the 3 demo-star afiliado cedulas (one per categoria × band), the expected branch each cedula triggers, and the dry_run simulator commands for local rehearsal.

#### Scenario: README contains the four mandatory pieces

- GIVEN the repository README is read end-to-end
- WHEN a juror scans it
- THEN the README contains (a) the Fly URL placeholder, (b) the 3 demo-star cedulas with their categoria/band and expected outcome, (c) the `curl` or `http` commands to drive the simulator, (d) the Meta webhook verify token placeholder
- AND a reader following the walkthrough verbatim can run a full READY classification against the Fly URL within 5 minutes