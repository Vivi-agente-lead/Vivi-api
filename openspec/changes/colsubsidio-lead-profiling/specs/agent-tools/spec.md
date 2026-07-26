# Delta for agent-tools

## ADDED Requirements

### Requirement: Lead-Profiling Tool Surface

The system MUST expose exactly five tools to the agent runtime: `lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead`. Each tool MUST obtain its `conversation_id` from the `ToolContext` (RunnableConfig `configurable`) rather than from LLM-supplied args. Tools MUST NOT directly import `langgraph` (stateless service layer).

#### Scenario: lookup_afiliado by composite key

- GIVEN an `afiliados_colsubsidio` table seeded with a row (tipo='CC', numero='12345678', categoria_afiliado='A', score_credito=820)
- WHEN `lookup_afiliado(tipo_documento='CC', numero_documento='12345678')` is called
- THEN the tool returns `{afiliado: {…}}`, and that nested `afiliado` object contains `categoria_afiliado`, `edad` (derived from `fecha_nacimiento`), `score_credito`, `score_rating` (band label of `score_credito`), and `ha_recibido_subsidio`
- GIVEN an unknown cedula
- WHEN `lookup_afiliado` is called with that cedula
- THEN the tool returns `{afiliado: null}` (no exception)
- AND both branches share the same envelope: the payload is always under the `afiliado` key, never flattened to the top level

#### Scenario: lookup_afiliado accepts every source document type

- GIVEN the source offers five document types (Cédula de ciudadanía, Cédula de extranjería, Pasaporte, Permiso Especial de Permanencia, Permiso por Protección Temporal)
- WHEN `lookup_afiliado` is called with any of the canonical slugs `CC`, `CE`, `PA`, `PEP`, `PPT`
- THEN the lookup proceeds
- AND the tool MUST NOT reject `PA`, `PEP` or `PPT`, and MUST NOT accept `TI`, which appears nowhere in the source domain

#### Scenario: save_lead upserts by conversation_id

- GIVEN a conversation with an existing `leads` row at `status='profiling'` carrying `{estado_civil='soltero'}`
- WHEN `save_lead({total_ingresos_mensuales: 3500000})` runs for the same `conversation_id`
- THEN the existing row is updated to include `total_ingresos_mensuales=3500000`
- AND previously-set fields (`estado_civil='soltero'`) remain unchanged
- AND `status` remains `profiling` (the tool MUST NOT promote status unless called via `classify_lead`)

#### Scenario: save_lead normalizes enumerated fields

- GIVEN `save_lead` is called with a verbatim source label for an enumerated field (e.g. `ahorros_o_cesantias='Menos de $3 millones'`)
- WHEN the tool persists the row
- THEN the value is normalized to its canonical slug (`menos_3m`) before the write
- GIVEN a value that matches no verbatim label and no canonical slug
- WHEN the tool persists the row
- THEN the field is written as NULL and the raw value is appended to the row's normalization notes

#### Scenario: get_lead returns current lead context

- GIVEN a conversation has persisted a partial lead row
- WHEN `get_lead()` is called for that conversation
- THEN the tool returns the current row as a dict matching the `leads` schema
- GIVEN no `leads` row exists yet for the conversation
- WHEN `get_lead()` is called
- THEN the tool returns `null` (no exception) — defensive against LLM asking for context before any save

#### Scenario: get_projects filtered for Calificado recommendation

- GIVEN a `calificado`-classified lead whose `lugar_eleccion_vivir` is `'Bogotá norte'` and whose `municipio_normalizado` is therefore `'Bogota'`
- AND `proyectos_colsubsidio` holds rows where `municipio='Bogota'`
- WHEN `get_projects(municipio='Bogota', tipo=None)` is called
- THEN the tool returns up to 5 matching projects ordered deterministically (by `proyecto`, then `modelo`)
- AND the tool MUST be called with `municipio_normalizado`, never with the raw `lugar_eleccion_vivir`, because the source municipio values are unaccented (`Bogota`, `Ubate`) and would not match the accented lead-facing options
- GIVEN a `nutrible` or `no_calificado` lead
- WHEN the handoff node runs
- THEN it MUST NOT invoke `get_projects` from `handoff` (no recommendation path for a lead that is not `calificado`)

**Amended by the graph-topology migration, Block B (`docs/v2-impact-analysis.md` §1, §8)**: `get_projects` is no longer READY/Calificado-only overall — it is also called from the entry-menu welcome message (`app/graph/nodes/browsing.py::menu_proyecto`, unfiltered, to source a real default project deterministically) and from the catalogue-browsing loop (`app/graph/nodes/browsing.py::mostrar_catalogo`, filtered by `municipio_normalizado` and a `tipo` derived from the lead's stated `preferencia_vis`), for **any** lead browsing the catalogue, before qualification and before a `status` exists at all. The MUST above narrows to: `handoff` itself MUST NOT call `get_projects` for a `nutrible` or `no_calificado` lead. It no longer means "only a `calificado` lead may trigger `get_projects` anywhere in the graph."

#### Scenario: get_projects is called before qualification from the entry menu and the browsing loop

- GIVEN a new conversation with no `leads` row yet
- WHEN `menu_proyecto` renders the welcome message
- THEN it calls `get_projects()` with no filters to source a real, deterministically-ordered default project (first row by `proyecto`, then `modelo`) — never a hardcoded project name
- GIVEN a lead who chose `Quiero ver otro proyecto.` and answered `preferencia_vis` and a municipio
- WHEN `mostrar_catalogo` renders the catalogue
- THEN it calls `get_projects(municipio=municipio_normalizado, tipo=<VIS|NO VIS|None>)`, `tipo` derived from `preferencia_vis` (`vis`→`VIS`, `no_vis`→`NO VIS`, `ambas`→ no `tipo` filter)
- AND this happens regardless of `status`, because no `status` has been computed yet at this point in the conversation

#### Scenario: get_projects tolerates the corrupt municipio value

- GIVEN the `VIBO ONCE` row whose `modelo` is `B2` carries the corrupt value `municipio='VIS'`
- WHEN `get_projects(municipio='Bogota')` is called
- THEN that row is included in the candidate set, because `'VIS'` is repaired to `'Bogota'` at lookup time
- AND the stored row still reads `'VIS'`, preserving the source verbatim

#### Scenario: classify_lead persists verdict

- GIVEN a `leads` row with collected fields (scoreable)
- WHEN `classify_lead()` is called
- THEN the tool invokes `lead_scorer.score_lead`, persists `status`, `score`, `score_rating`, `classification_reasoning` onto the row
- AND returns a verdict dict `{status, score, score_rating, classification, reasoning}` to the caller
- AND `classification` equals `status` and is one of {`calificado`, `nutrible`, `no_calificado`} — a single domain shared with `lead-scoring` and `lead-data-model` (v2 rename, `docs/v2-impact-analysis.md` §7: `ready`/`nurture`/`nurture_social` → `calificado`/`nutrible`/`no_calificado`)

#### Scenario: Tool wiring uses ToolContext, not LLM args

- GIVEN the 5 tools are registered and the graph executes a node that calls `save_lead`
- WHEN the call resolves `conversation_id`
- THEN the resolution MUST come from `RunnableConfig.configurable["tool_context"].conversation_id`
- AND if the LLM passes a `conversation_id` argument, the tool MUST ignore it (LLM cannot forge cross-conversation writes)
