# Delta for agent-tools

## ADDED Requirements

### Requirement: Lead-Profiling Tool Surface

The system MUST expose exactly five tools to the agent runtime: `lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead`. Each tool MUST obtain its `conversation_id` from the `ToolContext` (RunnableConfig `configurable`) rather than from LLM-supplied args. Tools MUST NOT directly import `langgraph` (stateless service layer).

#### Scenario: lookup_afiliado by composite key

- GIVEN an `afiliados_colsubsidio` table seeded with a row (tipo='CC', numero='12345678', categoria='A', score_credito=820)
- WHEN `lookup_afiliado(tipo_documento='CC', numero_documento='12345678')` is called
- THEN the tool returns a dict containing `categoria`, `edad` (derived from `fecha_nacimiento`), `score_credito`, `score_rating` (band label), and `ha_recibido_subsidio`
- GIVEN an unknown cedula
- WHEN `lookup_afiliado` is called with that cedula
- THEN the tool returns `{afiliado: null}` (no exception)

#### Scenario: save_lead upserts by conversation_id

- GIVEN a conversation with an existing `leads` row at `status='profiling'` carrying `{estado_civil='soltero'}`
- WHEN `save_lead({total_ingresos_mensuales: 3500000})` runs for the same `conversation_id`
- THEN the existing row is updated to include `total_ingresos_mensuales=3500000`
- AND previously-set fields (`estado_civil='soltero'`) remain unchanged
- AND `status` remains `profiling` (the tool MUST NOT promote status unless called via `classify_lead`)

#### Scenario: get_lead returns current lead context

- GIVEN a conversation has persisted a partial lead row
- WHEN `get_lead()` is called for that conversation
- THEN the tool returns the current row as a dict matching the `leads` schema
- GIVEN no `leads` row exists yet for the conversation
- WHEN `get_lead()` is called
- THEN the tool returns `null` (no exception) — defensive against LLM asking for context before any save

#### Scenario: get_projects filtered for READY recommendation

- GIVEN a READY-classified lead with `lugar_eleccion_vivir='Bogotá'` and the `proyectos_colsubsidio` table has rows where `municipio='Bogotá'`
- WHEN `get_projects(municipio='Bogotá', tipo=None)` is called
- THEN the tool returns up to 5 matching projects ordered deterministically (e.g., by `proyecto` name)
- GIVEN a NURTURE or `nurture_social` lead
- WHEN `get_projects` is called from a handoff node
- THEN the handoff node MUST NOT invoke `get_projects` (no recommendation path for non-READY)

#### Scenario: classify_lead persists verdict

- GIVEN a `leads` row with collected fields (scoreable)
- WHEN `classify_lead()` is called
- THEN the tool invokes `lead_scorer.score_lead`, persists `status`, `score`, `score_rating`, `classification_reasoning` onto the row
- AND returns a verdict dict `{status, score, score_rating, classification, reasoning}` to the caller
- AND `classification` is one of {`ready`, `nurture`} (with `nurture_social` reflected via `status='nurture_social'`)

#### Scenario: Tool wiring uses ToolContext, not LLM args

- GIVEN the 5 tools are registered and the graph executes a node that calls `save_lead`
- WHEN the call resolves `conversation_id`
- THEN the resolution MUST come from `RunnableConfig.configurable["tool_context"].conversation_id`
- AND if the LLM passes a `conversation_id` argument, the tool MUST ignore it (LLM cannot forge cross-conversation writes)