# Delta for leads-conversational-flow

## ADDED Requirements

### Requirement: Hybrid Conversation Flow

The system MUST drive Colsubsidio lead profiling through a structured state graph with explicit ordered nodes (autorizacion_datos → pedir_cedula → afiliado_check → edad gate → recoger_estado_civil → [recoger_otra_caja] → recoger_empleo → capacity bundle (4 paths) → recoger_intencion → scoring → handoff). The graph MUST replace the cached `create_react_agent`. Deterministic nodes (afiliado_check, scoring, handoff) MUST execute without LLM discretion. Collection nodes MUST delegate only question phrasing to a per-node LLM slice. The system SHALL persist `lead_profile` in checkpointer state AND mirror it to the `leads` DB row keyed by `conversation_id`.

Capacity bundles are selected by two derived predicates — `es_empleado` and
`tiene_pareja` — not by raw source labels:
`cap_emp_con_pareja` · `cap_emp_sin_pareja` · `cap_ind_con_pareja` · `cap_ind_sin_pareja`.

#### Scenario: Happy path afiliado reaches READY

- GIVEN an inbound WhatsApp message starts a new conversation and a mock afiliado exists with the cedula the user will provide
- WHEN the user answers autorizacion (yes) → cedula (matches afiliado) → estado_civil → empleo → capacity bundle → intencion (3 meses)
- THEN the conversation traverses autorizacion_datos → pedir_cedula → afiliado_check → recoger_estado_civil → recoger_empleo → capacity bundle → recoger_intencion → scoring → handoff
- AND the `leads` row ends with `status='ready'`, `score >= 60`, and handoff routes to a human asesor

#### Scenario: Happy path no-afiliado reaches READY

- GIVEN a new conversation from a cedula not present in `afiliados_colsubsidio`
- WHEN the user provides autorizacion, cedula, nombre_apellido, fecha_nacimiento (≥18y), estado_civil, otra caja, empleo, capacity fields, intencion
- THEN the graph traverses the no-afiliado branch (recoger_identidad, recoger_otra_caja) and reaches scoring
- AND `status='ready'` requires `score >= 75` for a no-afiliado lead (the affiliation-dependent threshold in `lead-scoring`)
- AND the `leads` row has `afiliado_colsubsidio=false` and `categoria` NULL

#### Scenario: Menor de edad ends conversation without lead — no-afiliado path

- GIVEN a no-afiliado user provides a fecha_nacimiento that yields edad < 18
- WHEN the recoger_identidad node computes edad
- THEN the graph sends a single cordial farewell message and terminates
- AND no `leads` row with a terminal status is persisted for this conversation (a `profiling` row MAY exist with the collected identity fields)

#### Scenario: Menor de edad ends conversation without lead — afiliado path

- GIVEN a cedula that matches an afiliado whose `fecha_nacimiento` yields edad < 18
- WHEN the afiliado_check node derives edad from the afiliado record
- THEN the graph sends a single cordial farewell message and terminates, exactly as on the no-afiliado path
- AND the underage gate MUST be reachable from both branches — the source flow diagram carries a `Consultar edad en BD → ¿Es mayor de edad?` decision on the afiliado side

#### Scenario: Terminal routing uses the LangGraph END sentinel

- GIVEN a conditional-edge predicate that terminates the conversation (consent opt-out or underage gate)
- WHEN the predicate returns
- THEN it returns the `END` sentinel imported from `langgraph.graph`, whose value is `"__end__"`
- AND it MUST NOT return the literal string `"END"`, which resolves to no registered node

#### Scenario: Subsidio previo forces nurture regardless of score

- GIVEN a lead whose computed score is 75 but `subsidio_vivienda_anterior=true`
- WHEN the scoring node runs
- THEN `lead.status` is forced to `'nurture'` (NOT `'ready'`)
- AND `classification_reasoning` contains the literal phrase "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"

#### Scenario: Subsidio previo is collected on every path

- GIVEN a lead with any `estado_civil`, including `soltero`, `divorciado`, `separado` and `viudo`
- WHEN the capacity bundle runs
- THEN `subsidio_vivienda_anterior` is collected
- AND the field MUST NOT be gated to `casado`/`union_libre` only

> **Recorded decision (source conflict).** The spreadsheet's `Condicion` cell reads
> "Preguntar si es casado o UL"; the flow diagram asks the question in all four
> capacity bundles, using `¿Has recibido…?` for leads without a partner and
> `¿Usted o su pareja han recibido…?` for leads with one. **The flow diagram is
> authoritative for *who* is asked; the spreadsheet is authoritative for *field
> domains*.** The spreadsheet condition governs phrasing, not eligibility — a lead
> without a partner can hold a prior subsidy, and gating the field would leave the
> absolute disqualifier inert for that entire population.

#### Scenario: PAC and discapacidad are collected on every path

- GIVEN a lead on any branch, including `soltero` + afiliado
- WHEN the capacity bundle runs
- THEN `numero_pac` and `condicion_discapacidad_familiar` are collected
- AND the `+8` scoring bonus is therefore reachable from every branch

#### Scenario: Nurture mid-score outcome

- GIVEN a lead whose computed score is at or above 30 but below its applicable READY threshold, and `subsidio_vivienda_anterior=false`
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
- THEN the graph MUST NOT ask the user for `nombre_apellido`, `otra_caja_compensacion`, `fecha_nacimiento` or `edad`
- AND `lead.edad` is derived from the afiliado's `fecha_nacimiento`, `lead.categoria` is set from the afiliado row, `lead.otra_caja_compensacion` stays NULL

#### Scenario: Rango salarial is asked only where the source permits

- GIVEN an afiliado lead, whose `salario_base_cotizacion` is already known from the afiliado record
- WHEN the capacity bundle runs
- THEN the graph MUST NOT ask for `rango_salarial`; it is derived from `salario_base_cotizacion`
- GIVEN a no-afiliado lead with `es_empleado=false`
- WHEN the capacity bundle runs
- THEN the graph MUST NOT ask for `rango_salarial`
- GIVEN a no-afiliado lead with `es_empleado=true`
- WHEN the capacity bundle runs
- THEN the graph asks for `rango_salarial`, per the source condition "Preguntar solo si es empleado y NO es afiliado Colsubsidio"

#### Scenario: Pareja vs sin-pareja income fields

- GIVEN a lead with `tiene_pareja=false` (soltero, divorciado, separado or viudo)
- WHEN the capacity bundle runs
- THEN the graph MUST collect `total_ingresos_mensuales` and MUST NOT collect `total_ingresos_familiares_mensuales`
- GIVEN a lead with `tiene_pareja=true` (casado or union_libre)
- WHEN the capacity bundle runs
- THEN the graph MUST collect `total_ingresos_familiares_mensuales` and MUST NOT collect `total_ingresos_mensuales`

#### Scenario: Empleado vs independiente antiguedad

- GIVEN a lead with `es_empleado=true` (`contrato_laboral` in {`termino_fijo`, `termino_indefinido`})
- WHEN the capacity bundle runs
- THEN the graph MUST collect `antiguedad_laboral`
- GIVEN a lead with `contrato_laboral='prestacion_servicios'`
- WHEN the capacity bundle runs
- THEN the graph MUST NOT ask for `antiguedad_laboral`

#### Scenario: Contract type is captured verbatim, not collapsed at collection time

- GIVEN the source offers exactly three answers to "¿Cuentas con contrato de trabajo o eres independiente?": `Termino fijo`, `Termino indefinido`, `Prestacion de servicios`
- WHEN `recoger_empleo` records the answer
- THEN `contrato_laboral` stores the canonical slug for the specific contract type
- AND `es_empleado` is derived from it for routing
- AND the graph MUST NOT compare the field against the literal value `"empleado"`, which appears nowhere in the source domain

#### Scenario: cabeza_de_hogar auto-derivation

- GIVEN a lead with `tiene_pareja=false`
- WHEN the node that persists `cabeza_de_hogar` runs
- THEN `lead.cabeza_de_hogar=true`
- GIVEN a lead with `tiene_pareja=true` and `numero_pac > 0`
- WHEN the same node runs
- THEN `lead.cabeza_de_hogar=true`
- GIVEN a lead with `tiene_pareja=true` and `numero_pac=0`
- WHEN the same node runs
- THEN `lead.cabeza_de_hogar=false`
- AND the derivation runs in the capacity bundle, which every branch reaches

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

### Requirement: Documented Deviations From the Source Flow Diagram

`docs/Flujo asesor de venta de vivienda Colsubsidio.json` contains nodes this change
deliberately does not implement. Each omission MUST be recorded as a decision rather
than left as an implicit gap, and the design MUST NOT claim a one-to-one mapping.

#### Scenario: Omitted flow nodes are enumerated

- GIVEN the source flow diagram
- WHEN the design is compared against it
- THEN the following nodes are recorded as out of scope for this iteration, with a reason: the `QUIERO COMPRAR` / `QUIERO ASESORIA` entry split, `¿Ya sabes en cual proyecto de vivienda estas interesado?`, `¿Cuál de los siguientes proyectos te interesa?`, `Mostrar una descripción del proyecto seleccionado`, `¿Te interesaría revisar tus opciones de compra con un asesor?`, `Selecciona una de las ubicaciones disponibles`, `Setear variable pos_subsidio = 0`, and the intermediate reassurance message `Ya voy conociendote mejor, vamos con unas preguntas mas`
- AND the relocation of the municipio question (asked early in the diagram, collected in `recoger_intencion` here) is recorded with its reason: `vis_recommended` and the −15 red flag depend on it being known at scoring time

#### Scenario: Reassurance message before the capacity bundle

- GIVEN the source flow sends `Ya voy conociendote mejor, vamos con unas preguntas mas` before the capacity questions
- WHEN a lead reaches the capacity bundle
- THEN an equivalent short reassurance precedes the bundle's first question
- AND it is emitted by the bundle's prompt slice, not by a dedicated node
