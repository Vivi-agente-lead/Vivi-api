# Delta for leads-conversational-flow

## ADDED Requirements

### Requirement: Hybrid Conversation Flow

The system MUST drive Colsubsidio lead profiling through a structured state graph with explicit ordered nodes (autorizacion_datos → pedir_cedula → afiliado_check → edad gate → [recoger_identidad → recoger_interes_afiliacion] → recoger_estado_civil → recoger_empleo → recoger_capacidad → recoger_intencion → scoring → handoff). The graph MUST replace the cached `create_react_agent`. Deterministic nodes (afiliado_check, scoring, handoff) MUST execute without LLM discretion. Collection nodes MUST delegate only question phrasing to a per-node LLM slice. The system SHALL persist `lead_profile` in checkpointer state AND mirror it to the `leads` DB row keyed by `conversation_id`.

**v2 graph-topology migration (`docs/v2-impact-analysis.md`)**: the four v1 capacity bundles (`cap_emp_con_pareja` · `cap_emp_sin_pareja` · `cap_ind_con_pareja` · `cap_ind_sin_pareja`) and the `_route_capacity` predicate that selected among them by two derived predicates (`es_empleado`, `tiene_pareja`) are DELETED. v2 asks one household capacity block of every lead — employed or not, partnered or not — so `tiene_pareja` and `es_empleado` stop being routing predicates (both are still derived, bookkeeping only). `recoger_otra_caja` (the v1 caja-name prompt) is likewise deleted; `recoger_interes_afiliacion` replaces it, reachable only from the no-afiliado age gate.

#### Scenario: Happy path afiliado reaches Calificado

- GIVEN an inbound WhatsApp message starts a new conversation and a mock afiliado exists with the cedula the user will provide
- WHEN the user answers autorizacion (yes) → cedula (matches afiliado) → estado_civil → empleo → capacidad → intencion (3 meses)
- THEN the conversation traverses autorizacion_datos → pedir_cedula → afiliado_check → recoger_estado_civil → recoger_empleo → recoger_capacidad → recoger_intencion → scoring → handoff
- AND the `leads` row ends with `status='calificado'`, `score >= 60`, and handoff routes to a human asesor

#### Scenario: Happy path no-afiliado reaches Nutrible or Calificado

- GIVEN a new conversation from a cedula not present in `afiliados_colsubsidio`
- WHEN the user provides autorizacion, cedula, nombre_apellido, edad (≥18y, stated directly), interes_afiliacion, estado_civil, empleo, the household capacidad fields, intencion
- THEN the graph traverses the no-afiliado branch (recoger_identidad, recoger_interes_afiliacion) and reaches scoring
- AND `status='calificado'` requires `score >= 75` for a no-afiliado lead (the affiliation-dependent threshold in `lead-scoring`)
- AND the `leads` row has `afiliado_colsubsidio=false` and `categoria` NULL

#### Scenario: Menor de edad ends conversation without lead — no-afiliado path

- GIVEN a no-afiliado user states an `edad` below 18 directly, in answer to `¿Que edad tienes?`
- WHEN the `recoger_identidad` node records the answer
- THEN the graph sends a single cordial farewell message and terminates
- AND no `leads` row with a terminal status is persisted for this conversation (a `profiling` row MAY exist with the collected identity fields)
- AND `edad` is the lead's own stated answer here, NOT derived from a birth date — v2 has no `fecha_nacimiento` node on this branch at all (a recorded regression in trustworthiness vs. v1's server-side derivation; `docs/v2-impact-analysis.md` §6 — followed as the JSON authority states it)

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

#### Scenario: Subsidio previo forces nutrible regardless of score

- GIVEN a lead whose computed score is 75 but `subsidio_vivienda_anterior=true`
- WHEN the scoring node runs
- THEN `lead.status` is forced to `'nutrible'` (NOT `'calificado'`)
- AND `classification_reasoning` contains the literal phrase "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"

#### Scenario: Subsidio previo is collected on every path

- GIVEN a lead with any `estado_civil`, including `soltero`, `divorciado`, `separado` and `viudo`
- WHEN `recoger_capacidad` runs
- THEN `subsidio_vivienda_anterior` is collected
- AND the field MUST NOT be gated by `estado_civil` or `tiene_pareja` — the single household block asks it of every lead

#### Scenario: PAC is collected on every path

- GIVEN a lead on any branch, including `soltero` + afiliado
- WHEN `recoger_capacidad` runs
- THEN `numero_pac` is collected
- AND the `+8` scoring bonus is therefore reachable from every branch
- AND `condicion_discapacidad_familiar` is NOT collected — v2 removes the field outright (absent from the v2 sheet's capacity question); the `+8` bonus keeps only its `numero_pac > 0` trigger

#### Scenario: Nutrible mid-score outcome

- GIVEN a lead whose computed score is at or above 30 but below its applicable threshold, and `subsidio_vivienda_anterior=false`
- WHEN the scoring node runs
- THEN `lead.status='nutrible'`
- AND the handoff message instructs "te vamos a contactar más adelante" (or equivalent nurture phrasing)

#### Scenario: No calificado low-score outcome

- GIVEN a lead whose computed score is < 30 and `subsidio_vivienda_anterior=false`
- WHEN the scoring node runs
- THEN `lead.status='no_calificado'`
- AND the handoff message references an asistente social contact path
- AND `no_calificado` is terminal, with no follow-up drawn — only `Calificado` continues, to "Me ha encantado tu entusiasmo…" (`docs/v2-impact-analysis.md` §7)

#### Scenario: Afiliado branch skips identidad, interes_afiliacion, edad

- GIVEN the afiliado_check node found a record for the cedula
- WHEN subsequent collection nodes execute
- THEN the graph MUST NOT ask the user for `nombre_apellido`, `edad` or `interes_afiliacion`
- AND `lead.edad` is derived from the afiliado's `fecha_nacimiento`, `lead.categoria` is set from the afiliado row, `lead.otra_caja_compensacion` and `lead.interes_afiliacion` stay NULL
- AND the affiliation question is gated to non-affiliates by topology alone — `recoger_interes_afiliacion` is reachable only from the no-afiliado age gate, so no separate routing predicate is needed to keep an affiliate away from it

#### Scenario: Rango salarial is always derived, never asked directly

- GIVEN an afiliado lead, whose `salario_base_cotizacion` is already known from the afiliado record
- WHEN `afiliado_check` runs
- THEN the graph MUST NOT ask for `rango_salarial`; it is derived from `salario_base_cotizacion`
- GIVEN a no-afiliado lead
- WHEN `recoger_capacidad` runs
- THEN the graph MUST NOT ask for `rango_salarial` either — neither the v2 flow diagram's household node nor the v2 workbook carries a distinct rango_salarial prompt
- AND `rango_salarial` is instead derived from the collected `total_ingresos_mensuales`, using the same band boundaries the afiliado derivation applies, so Bucket 3 ("Ingreso") of the scorer is not silently zeroed for the entire no-afiliado population — a deliberate interpretation call by this change, not a literal JSON requirement

#### Scenario: The household capacity block is asked of every lead, once

- GIVEN a lead with any `estado_civil` and any `contrato_laboral`
- WHEN the lead reaches `recoger_capacidad`
- THEN the graph collects, in this order: `total_ingresos_mensuales`, `gastos_mensuales`, `tiene_vivienda_propia`, `numero_pac`, `subsidio_vivienda_anterior`, `ahorros_o_cesantias`
- AND there is no per-partner or per-employment variant of this block — the four v1 bundles collapse into this one node
- AND `total_ingresos_familiares_mensuales` no longer exists as a separate field; `total_ingresos_mensuales` is the single household-income column every branch writes

#### Scenario: Contract type is captured verbatim, not collapsed at collection time

- GIVEN the source offers exactly four answers to "¿Cuentas con contrato de trabajo o eres independiente?": `Termino fijo`, `Termino indefinido`, `Prestacion de servicios`, `Independiente`
- WHEN `recoger_empleo` records the answer
- THEN `contrato_laboral` stores the canonical slug for the specific contract type, including the v2-only `independiente` slug, distinct from `prestacion_servicios`
- AND `es_empleado` is derived from it for bookkeeping (no longer for routing)
- AND the graph MUST NOT compare the field against the literal value `"empleado"`, which appears nowhere in the source domain

#### Scenario: cabeza_de_hogar is removed

- GIVEN any lead, on any branch
- WHEN the graph runs to completion
- THEN `lead.cabeza_de_hogar` is never derived, collected or persisted — the v2 sheet has no column and no question for it, and its former input (`condicion_discapacidad_familiar`) is also gone

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

`docs/Flujo asesor de venta de vivienda Colsubsidio-v2.json` contains nodes this change deliberately does not implement in Block A of the graph-topology migration. Each omission MUST be recorded as a decision rather than left as an implicit gap, and the design MUST NOT claim a one-to-one mapping.

#### Scenario: Omitted v2 flow nodes are enumerated

- GIVEN the v2 source flow diagram
- WHEN the implementation is compared against it
- THEN the following v2 surface is recorded as out of scope for Block A, with a reason: the catalogue-first entry inversion (`Bienvenido(a)…` → `Para continuar elige una opcion:` → `Quiero saber más de este proyecto` / `Quiero ver otro proyecto.` / `Salir`), the project-browsing loop with back-navigation (`Preguntar: ¿Te interesan vivienda VIS, NO VIS o ambas?` → municipio → `Mostrar menu de proyectos disponibles…` → `El usuario selecciona volver al menu anterior`), `¿Te conecto con un asesor de crédito?`, and `Enviar notificación por correo` — all deferred to a later work unit (Block B / Block C) because they are new stateful surface, not a field-level correction
- AND `lugar_eleccion_vivir` stays collected in `recoger_intencion`, at the end of the flow, rather than moving to the front as the v2 diagram's entry inversion implies — a deliberate interim placement for Block A, since the linear flow this change ships has no project-selection front-end yet
- AND `preferencia_vis` is a real, normalized domain (`app/models/constants.py`, `app/services/domain_normalizer.py`) and its scorer wiring is live (`lead-scoring`), but no node in Block A's linear flow collects it — the v2 diagram places that question only inside the project-browsing loop, which Block A does not build; a lead's `preferencia_vis` is therefore always NULL until that loop ships, and the `-15` red flag falls back to the derived `vis_recommended`

#### Scenario: Reassurance message before the capacity block

- GIVEN the source flow sends `Ya voy conociendote mejor, vamos con unas preguntas mas` before the capacity questions
- WHEN a lead reaches `recoger_capacidad`
- THEN an equivalent short reassurance precedes the block's first question
- AND it is emitted by the block's prompt slice, not by a dedicated node

#### Scenario: tiene_creditos_activos is dormant, not removed

- GIVEN the `leads.tiene_creditos_activos` column and the scorer's `-5` red-flag rule, both of which predate this change
- WHEN the v2 flow diagram and the v2 workbook are checked for a matching question
- THEN neither carries one — a fourth field removal `docs/v2-impact-analysis.md` did not enumerate
- AND this change stops asking the question rather than inventing a v2 node or prompt for it; the column stays on the model (out of scope — `app/models/**`) and the `-5` rule stays in the scorer, both permanently dormant: an always-NULL field already fails the rule's `is True` check closed, exactly like every other uncollected boolean
