# Delta for leads-conversational-flow

## ADDED Requirements

### Requirement: Hybrid Conversation Flow

The system MUST drive Colsubsidio lead profiling through a structured state graph with explicit ordered nodes (autorizacion_datos → pedir_cedula → afiliado_check → branch on afiliado → recoger_estado_civil → recoger_empleo → capacity bundle (4 paths) → recoger_intencion → scoring → handoff). The graph MUST replace the cached `create_react_agent`. Deterministic nodes (afiliado_check, scoring, handoff) MUST execute without LLM discretion. Collection nodes MUST delegate only question phrasing to a per-node LLM slice. The system SHALL persist `lead_profile` in checkpointer state AND mirror it to the `leads` DB row keyed by `conversation_id`.

#### Scenario: Happy path afiliado reaches READY

- GIVEN an inbound WhatsApp message starts a new conversation and a mock afiliado exists with the cedula the user will provide
- WHEN the user answers autorizacion (yes) → cedula (matches afiliado) → estado_civil → empleo → capacity bundle → intencion (3_meses)
- THEN the conversation traverses autorizacion_datos → pedir_cedula → afiliado_check → recoger_estado_civil → recoger_empleo → capacity bundle → recoger_intencion → scoring → handoff
- AND the `leads` row ends with `status='ready'`, `score >= 60`, and handoff routes to a human asesor

#### Scenario: Happy path no-afiliado reaches READY

- GIVEN a new conversation from a cedula not present in `afiliados_colsubsidio`
- WHEN the user provides autorizacion, cedula, nombre_apellido, fecha_nacimiento (≥18y), estado_civil, empleo, capacity fields, intencion
- THEN the graph traverses the no-afiliado branch (recoger_identidad, no categoria/otra_caja asked from DB) and reaches scoring → READY when score >= 60
- AND the `leads` row has `afiliado_colsubsidio=false` and `categoria` NULL

#### Scenario: Menor de edad ends conversation without lead

- GIVEN a no-afiliado user provides a fecha_nacimiento that yields edad < 18
- WHEN the recoger_identidad node computes edad
- THEN the graph sends a single cordial farewell message and terminates (FIN)
- AND no `leads` row with `status='ready'` or `'nurture'` is persisted for this conversation (a `profiling` row MAY exist with the collected identity fields)

#### Scenario: Subsidio previo forces nurture regardless of score

- GIVEN a lead whose computed score is 75 but `subsidio_vivienda_anterior=true`
- WHEN the scoring node runs
- THEN `lead.status` is forced to `'nurture'` (NOT `'ready'`)
- AND `classification_reasoning` contains the literal phrase "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"

#### Scenario: Nurture mid-score outcome

- GIVEN a lead whose computed score is in [30, 59] and `subsidio_vivienda_anterior=false`
- WHEN the scoring node runs
- THEN `lead.status='nurture'`
- AND the handoff message instructs "te vamos a contactar más adelante" (or equivalent nurture phrasing)

#### Scenario: Nurture+social low-score outcome

- GIVEN a lead whose computed score is < 30 and `subsidio_vivienda_anterior=false`
- WHEN the scoring node runs
- THEN `lead.status='nurture_social'`
- AND the handoff message references an asistente social contact path

#### Scenario: Afiliado branch skips identidad, otra_caja, edad

- GIVEN the afiliado_check node found a record for the cedula
- WHEN subsequent collection nodes execute
- THEN the graph MUST NOT ask the user for `nombre_apellido`, `otra_caja_compensacion`, or `edad`
- AND `lead.edad` is derived from the afiliado's `fecha_nacimiento`, `lead.categoria` is set from the afiliado row, `lead.otra_caja_compensacion` stays NULL

#### Scenario: Soltero vs casado income fields

- GIVEN a lead with `estado_civil='soltero'`
- WHEN the capacity bundle runs
- THEN the graph MUST collect `total_ingresos_mensuales` and MUST NOT collect `total_ingresos_familiares_mensuales`
- GIVEN a lead with `estado_civil in ('casado', 'union_libre')`
- WHEN the capacity bundle runs
- THEN the graph MUST collect `total_ingresos_familiares_mensuales` and MUST NOT collect `total_ingresos_mensuales`

#### Scenario: Empleado vs independiente antiguedad

- GIVEN a lead with `empleado_o_independiente='empleado'`
- WHEN the recoger_empleo node runs
- THEN the graph MUST collect `antiguedad_laboral`
- GIVEN a lead with `empleado_o_independiente='independiente'`
- WHEN the capacity bundle runs
- THEN the graph MUST NOT ask for `antiguedad_laboral`

#### Scenario: cabeza_de_hogar auto-derivation

- GIVEN a lead with `estado_civil='soltero'`
- WHEN any node that persists `cabeza_de_hogar` runs
- THEN `lead.cabeza_de_hogar=true`
- GIVEN a lead with `estado_civil in ('casado','union_libre')` and `numero_pac > 0`
- WHEN the same node runs
- THEN `lead.cabeza_de_hogar=true`
- GIVEN a lead with `estado_civil in ('casado','union_libre')` and `numero_pac=0`
- WHEN the same node runs
- THEN `lead.cabeza_de_hogar=false`

#### Scenario: Conversational resume across 10-minute gap

- GIVEN a conversation that paused at the recoger_empleo node and the checkpointer holds the graph state
- WHEN the same `wa_id` user sends a WhatsApp message 10 minutes later
- THEN the graph resumes from recoger_empleo with `lead_profile` intact (no restart from autorizacion_datos)
- AND the user is not re-asked fields already collected

#### Scenario: Channel-agnostic graph core

- GIVEN the StateGraph, the 5 tools, and the scorer module
- WHEN a code search is performed for WhatsApp/Meta specific tokens
- THEN zero references appear in the graph, tools (excluding tool wiring that fetches conversation_id from ToolContext), and scorer modules
- AND only `InboundMessageHandler` and `WhatsAppClient` modules reference Meta/WhatsApp