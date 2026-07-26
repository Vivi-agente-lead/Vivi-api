# Delta for whatsapp-channel-pipeline

## ADDED Requirements

> The WhatsApp pipeline already exists in code; this delta captures the contract the pipeline MUST uphold as the StateGraph lands. Main `openspec/specs/whatsapp-channel-pipeline/spec.md` does not yet exist, so these are added as new requirements.

### Requirement: Inbound Webhook Processing

The system MUST accept WhatsApp Cloud API webhooks at `POST /whatsapp/webhook` and verify at `GET /whatsapp/webhook`. The handler MUST persist the inbound user message to the conversation history BEFORE invoking the agent, so a crash mid-agent does not lose the inbound. The handler MUST support a `dry_run` mode for the dev simulator.

#### Scenario: Inbound message persists before agent invocation

- GIVEN a valid webhook POST delivers a user message to `wa_id='+57300...`
- WHEN the handler processes the webhook
- THEN the user `HumanMessage` is persisted to the conversation row FIRST
- AND only then `AgentService.send_message` is invoked
- AND a process crash between persistence and agent invocation does NOT lose the inbound message

#### Scenario: Wamid idempotency

- GIVEN a webhook whose `wamid` matches a previously processed webhook for this conversation
- WHEN the handler receives the duplicate webhook
- THEN the system MUST NOT invoke `AgentService.send_message` a second time
- AND the handler returns 200 OK without side effects

#### Scenario: The wamid is actually persisted

- GIVEN `InboundMessageHandler.handle` receives an `external_id`
- WHEN the inbound user message is written
- THEN that `external_id` is stored on the `messages` row
- AND `AgentService.send_message` MUST accept and forward it to `MessageService.persist_user_message`
- AND the duplicate check `MessageRepository.find_by_external_id` MUST be able to match a real value — today the column is never written, so the guard never fires and a Meta retry re-runs the whole agent turn and sends a second reply

### Requirement: Dev Simulator Endpoint

The system MUST expose `POST /whatsapp/simulate?text=&from=&dry_run=` for local development that bypasses Meta verification and drives the full agent + persistence pipeline. With `dry_run=true`, the simulator MUST execute the agent and capture the would-be outbound reply without sending it to Meta.

The route MUST be registered only when `settings.app_env == "development"` — see the
`Public Deployment Hardening` requirement in `demo-deployment`.

#### Scenario: dry_run logs the would-be reply

- GIVEN a running local server and `dry_run=true`
- WHEN `POST /whatsapp/simulate?text=Hola&from=%2B57300...&dry_run=true` is sent
- THEN the agent graph executes end to end
- AND the response body includes the would-be reply text
- AND no outbound request is sent to the Meta Graph API (asserted: zero HTTP calls to `graph.facebook.com`)

#### Scenario: dry_run=false sends to Meta

- GIVEN a running server with valid Meta credentials and `dry_run=false`
- WHEN `POST /whatsapp/simulate?...` is sent
- THEN `WhatsAppClient.send_text` issues an HTTP POST to the Meta send endpoint
- AND the simulator response includes the Meta API response

### Requirement: Channel-Agnostic Boundary

The WhatsApp adapter MUST be the ONLY layer that knows about Meta. The agent service, graph, tools, and scorer MUST be reachable from a non-WhatsApp channel adapter without modification.

#### Scenario: Removing WhatsApp does not break the graph core

- GIVEN the codebase compiles with `app/services/inbound_handler.py` and `app/services/whatsapp_client.py` removed (mocked or deleted)
- WHEN the StateGraph, tools, and scorer are imported and unit-tested directly
- THEN imports succeed and tests pass
- AND the StateGraph + tools contain no references to WhatsApp, Meta, or `whatsapp_client`

#### Scenario: Webhook verify at GET

- GIVEN Meta sends `GET /whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<configured>&hub.challenge=<challenge>`
- WHEN the handler receives the request
- THEN the response body is the literal `hub.challenge` value with status 200
- GIVEN the `hub.verify_token` mismatches the configured token
- WHEN the same GET is received
- THEN the response is 403

### Requirement: Operational Sandbox Caveat

The README MUST note that the demo only sends messages to Meta sandbox-approved test recipients; production recipients require a separate Meta template-message approval outside this change's scope.