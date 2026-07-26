# Architecture — Vivi / Colsubsidio Lead Profiler

This document mirrors the load-bearing decisions of
`openspec/changes/colsubsidio-lead-profiling/design.md` (§3, §7, §13) so they
survive independently of the OpenSpec change history. Where this document and
`design.md` disagree, the code (cited by file path below) is the tiebreaker —
this file describes what was actually built, not what was planned.

## 1. The channel-agnostic seam

The single non-negotiable boundary in this codebase is that **nothing in the
graph, the tools, or the scorer knows it is talking to WhatsApp**. Everything
channel-specific lives above `AgentService`; everything below it is a pure
conversational-state machine plus a Postgres session.

```
Meta Cloud API ──▶ app/routers/whatsapp.py ──▶ InboundMessageHandler
                                                        │
                                                        ▼
                                              AgentService.send_message
                                                        │
                              ┌─────────────────────────┼─────────────────────────┐
                              ▼                         ▼                         ▼
                    ConversationService        build_graph(role).ainvoke   MessageService
                    (get-or-create thread)      (the 15-node StateGraph)    (persist turn)
                                                        │
                                                        ▼
                                              ToolContext (session, conversation_id)
                                                        │
                                                        ▼
                                          app/tools/lead_tools.py (5 tools)
```

`AgentService.send_message(conversation_id, payload)` (`app/services/agent_service.py`)
is the seam. It:

1. Validates the payload and persists the inbound message.
2. Builds a `ToolContext(session, conversation_id)` (`app/services/tool_context.py`)
   and injects it into `RunnableConfig.configurable["tool_context"]`.
3. Invokes the compiled graph for one turn.
4. Persists whatever assistant/tool messages the turn produced.

A second channel (web chat, a contact-center adapter, anything) only needs to
call `AgentService.send_message` with its own `conversation_id`; it never
touches the graph, the tools, or the scorer directly. This is why the tools in
`app/tools/lead_tools.py` accept a hidden `config: RunnableConfig` instead of a
`session`/`conversation_id` argument the LLM could supply directly — an LLM
that could forge `conversation_id` could read or write another lead's row. The
tool extracts its context with `get_tool_context(config)`
(`app/services/tool_context.py`), which raises loudly if the orchestrator
forgot to inject it — a missing `ToolContext` is a wiring bug, not a
user-facing error.

`AgentService.stream_message` exists in the same file for a future SSE-driven
web channel and reuses the identical seam, but **no router mounts it** — see
README.md "What works" for why that matters to a juror reading the code.

## 2. The 15-node graph topology

`app/graph/builder.py::build_lead_profiler()` assembles a LangGraph
`StateGraph(AgentState)` with exactly the 15 nodes named in `design.md` §3:

```
START
  │
  ▼
start ──▶ autorizacion_datos ──(no)──▶ END
                │ (sí)
                ▼
          pedir_cedula ──▶ afiliado_check
                                 │
              ┌──────────────────┼───────────────────────┐
              ▼ (no afiliado)    ▼ (afiliado, edad≥18)    ▼ (afiliado, edad<18)
        recoger_identidad        │                       END
              │                  │
         ┌────┴────┐             │
         ▼(<18)    ▼(≥18)        │
        END         └────────────┴──▶ recoger_estado_civil
                                            │
                            ┌───────────────┴───────────────┐
                            ▼ (no afiliado)                  ▼ (afiliado)
                     recoger_otra_caja                        │
                            └───────────────┬─────────────────┘
                                            ▼
                                     recoger_empleo
                                            │
        ┌───────────────────┬──────────────┴──────┬───────────────────┐
        ▼                   ▼                     ▼                   ▼
cap_emp_con_pareja  cap_emp_sin_pareja   cap_ind_con_pareja   cap_ind_sin_pareja
        └───────────────────┴──────────────┬───────┴───────────────────┘
                                            ▼
                                    recoger_intencion
                                            ▼
                                        scoring   (pure — no LLM)
                                            ▼
                                        handoff
                                            ▼
                                           END
```

Source: `app/graph/builder.py::NODES` (the dict literally is this list) and
`app/graph/router.py` for the five conditional-edge predicates
(`_route_autorizacion`, `_route_afiliado`, `_route_edad`, `_route_otra_caja`,
`_route_capacity`). Every predicate returns the `END` sentinel imported from
`langgraph.graph` — never the literal string `"END"` — because an earlier
design revision shipped exactly that defect and it is silent: a router
returning `"END"` looks like a valid (if wrong) node id to LangGraph.

### 2.1 One turn = one node's question — `turn_gated`

LangGraph's `interrupt_before` is an explicit non-goal (`design.md` §3), so the
graph needs its own way to hand control back to the user mid-conversation.
`app/graph/turn_gate.py::turn_gated` wraps **every** outgoing edge — static and
conditional — so that once any node has asked a question in the current
invocation (`state["asked_this_turn"]`), the turn ends at `END` regardless of
what the wrapped destination would otherwise have been. The next inbound
WhatsApp message is a fresh graph invocation against the same checkpointer
thread; `awaiting_field` (part of `AgentState`, `app/graph/state.py`) tells
that invocation which node's question the new message answers, so the replay
is a pass-through until it reaches the node still waiting.

This means **one graph invocation is one conversational turn**, not one full
conversation — a detail `design.md` leaves implicit and the code had to make
explicit to be testable without a live LLM (see `tests/test_graph_traversal.py`,
which drives a conversation by calling `graph.ainvoke` once per user reply).

### 2.2 Capacity bundles collapse two predicates, not the source labels

The four `cap_*` nodes are selected by `_route_capacity` from two **derived**
booleans — `es_empleado` (from `contrato_laboral`) and `tiene_pareja` (from
`estado_civil`) — never from a raw source label. `subsidio_vivienda_anterior`,
`numero_pac` and `condicion_discapacidad_familiar` are collected on **all
four** bundles (`app/graph/nodes/capacity.py`), even though the source
spreadsheet's condition for the prior-subsidy question reads "Preguntar si es
casado o UL". `design.md` §13.2 resolves this explicitly: the spreadsheet
governs field *domains* (what values are valid, how the question is phrased —
"su pareja" only parses with a partner), the flow diagram governs *who is
asked*. Gating the field to casado/union_libre would leave the absolute
disqualifier inert for every soltero, divorciado, separado and viudo lead.

## 3. The normalizer boundary

`app/services/domain_normalizer.py` is the **only** place the two vocabularies
in this system meet: the verbatim option labels a lead sees in WhatsApp
(`"Menos de $3 millones"`, `"Cédula de ciudadanía"`, `"Bogotá norte"`) and the
canonical slugs everything downstream — the scorer, the repositories, the
`leads` table columns — actually stores and compares (`menos_3m`, `CC`,
`Bogota`).

Why this boundary exists at all: an earlier design revision let the scorer
read LLM output directly and matched it by substring (`"no" not in ahorro`).
That test scored `"Menos de $3 millones"` as zero, because the string `"menos"`
contains `"no"`. `normalize(field, raw)` (`app/services/domain_normalizer.py`)
replaces every such comparison with one rule, applied everywhere:

- **Exact match only**, after case-folding, accent-stripping and whitespace
  collapsing (`_fold`). Never a substring probe.
- **Fails closed.** A value matching no verbatim label and no canonical slug
  returns `None` — never a mid-range guess. The caller
  (`app/graph/nodes/_validators.py::validate_enumerated`) re-asks the question
  and appends an audit line to `lead_profile["normalization_notes"]`
  (`note_rejected`), so the raw thing the lead actually typed survives for
  audit even though it never reaches the scorer.
- **Idempotent.** A value that is already a canonical slug normalizes to
  itself, so a node that re-reads a previously-normalized field never breaks.

A second normalizer inside the same module, `normalize_municipio`, exists
because the lead-facing location options and the project catalogue disagree:
of the nine `lugar_eleccion_vivir` options, four (all three Bogotá variants,
plus `Ubaté` vs. the catalogue's unaccented `Ubate`) do not equality-match the
`proyectos_colsubsidio.municipio` column. `recoger_intencion`
(`app/graph/nodes/closing.py`) persists **both**: `lugar_eleccion_vivir`
verbatim (the audit trail — what the lead actually chose) and
`municipio_normalizado` (the join key `get_projects` and the VIS-recommended
lookup use). A third helper, `repair_catalogo_municipio`, patches the single
corrupt catalogue row (`VIBO ONCE` modelo `B2` has `municipio='VIS'`, a
transcription error) **at lookup time only** — the stored row is left
untouched so the source data stays verbatim.

## 4. The scorer — six buckets, additive red flags, one absolute override

`app/services/lead_scorer.py::score_lead(lead, afiliado) -> (score, rating_label,
classification, reasoning)` is pure Python: no LLM call, no network, no DB
session. It is invoked once, from `app/graph/nodes/closing.py::scoring`, which
is the only node in the graph with no LLM step at all — the design's stated
reason is that a score has to be reproducible across two process invocations
of the same inputs, which an LLM cannot guarantee.

| Bucket | Max pts | Source | Notes |
|---|---|---|---|
| 1. Crédito | 25 | `app/services/credit_bands.py::band_from_score_credito` | Afiliado: real `score_credito` (150-950). No-afiliado: `simulate_bureau_cedula` — a deterministic cedula-mod, labeled "simulado bureau" in the reasoning string. |
| 2. Afiliación | 15 | `categoria_afiliado` (`A`=15, `B`=11, `C`=7) | No-afiliado scores **0** here — the first of the two 90/10 structural levers (§5). |
| 3. Ingreso | 20 | `rango_salarial` | For an afiliado this is *derived* from `salario_base_cotizacion` (`app/graph/nodes/_validators.py::derive_rango_salarial`), never asked — an affiliate is never asked `rango_salarial` at all. |
| 4. Ahorro | 15 | `ahorros_o_cesantias` | Exact slug lookup; the substring regression this replaces is documented above. |
| 5. Tiempo de compra | 10 | `tiempo_compra_deseado` | |
| 6. Estabilidad laboral | 15 | `contrato_laboral` × `antiguedad_laboral` | Independientes (`prestacion_servicios`) get a flat 6 pts regardless of tenure — there is no `antiguedad_laboral` question on that branch. |

Red flags, applied additively to the six-bucket sum, then clamped to `[0, 100]`:

- **VIS + owns a home already (`−15`)**: only when the `scoring` node's own
  project lookup found VIS-typed matches for the lead's
  `municipio_normalizado` **and** `tiene_vivienda_propia` is `True`. This is
  why `scoring` queries `ProyectoColsubsidioEntity` before calling
  `classify_lead` — the flag needs a live catalogue lookup, not a stored flag.
- **Active credit (`−5`)**: `tiene_creditos_activos is True`.
- **PAC / discapacidad (`+8`)**: `condicion_discapacidad_familiar is True` OR
  `numero_pac > 0`. This is additive with the flags above, not exclusive.

**Absolute override — prior subsidy.** If `subsidio_vivienda_anterior is
True`, the classification can never be `ready`, regardless of the numeric
score: `nurture` if the score is ≥ 30, `nurture_social` otherwise. The score
itself is **never decremented** for this — it stays the real number for
analytics, and only the classification is overridden. This rule is collected
on **all four** capacity bundles (§2.2), including every lead without a
partner, closing a regression an earlier design revision had (gating the
question to casado/union_libre made the disqualifier inert for solteros).

### 4.1 The 90/10 rule is two structural levers, not a hard gate

The proposal's "90% of qualified leads should be affiliates" is encoded as a
*distribution target*, deliberately not a hard `if not afiliado: reject`. Two
levers push the distribution there without making it impossible for a
no-afiliado to reach READY (a required scenario):

1. Bucket 2 (Afiliación) contributes 0 for every no-afiliado — a strictly
   positive signal for affiliation, never negative for its absence.
2. The READY threshold is **differentiated**: 60 for an afiliado, 75 for a
   no-afiliado (`READY_THRESHOLD_AFILIADO`, `READY_THRESHOLD_NO_AFILIADO` in
   `app/services/lead_scorer.py`). The no-afiliado threshold is the one
   tunable knob if a live demo's distribution misses the target — see
   `design.md` §7.4.

The one-statement affiliate-share query this target is checked against is in
README.md's "Affiliate share (90/10) query" section, backed by the
`ix_leads_status_afiliado` index (`app/models/lead_model.py`).

## 5. Persistence — dual, not just cached

`lead_profile` lives in `AgentState`, checkpointer-persisted per conversation
thread. It mirrors to the `leads` table row (`LeadColsubsidioEntity`,
`app/models/lead_model.py`) keyed by `conversation_id`, at three points:
end of `afiliado_check` (row created, `status='profiling'`), after every
`save_lead` tool call (opportunistic upsert), and after `classify_lead` inside
`scoring` (terminal write of `status`/`score`/`score_rating`/
`classification_reasoning`). The **terminal-status guard** — a lead already at
`ready`/`nurture`/`nurture_social` cannot have its status changed — lives in
`LeadRepository.upsert_by_conversation_id`
(`app/models/repositories/lead_repository.py`), not in any of the three
callers, precisely so none of them can bypass it by construction.

If the in-memory checkpointer loses the thread (a process restart with
`LLM_CHECKPOINTER=memory`), `AgentService._build_graph_input` calls
`app/services/lead_state_rebuilder.py::rebuild_lead_profile(session, conv_id)`
to reconstruct `lead_profile` from the persisted `leads` row before the next
graph invocation, so a crash mid-conversation does not re-ask everything.

## 6. Known architectural gaps at the end of Phase 6

Recorded here rather than glossed over, because this document is what survives
independently of the OpenSpec change history:

- **Phase 5 (channel hardening) has not landed on this branch.** The wamid
  idempotency guard, the `/simulate` production gate, the webhook signature
  check, and the `/health` readiness probe are all still open — see
  README.md "Known limitations" for the concrete, code-cited consequences of
  each.
- **The web/SSE channel is unmounted, not unbuilt.** `AgentService.stream_message`
  and the SSE schemas in `app/schemas/chat_schema.py` exist and share the same
  seam described in §1, but no router in `app/main.py` exposes them over HTTP.
  Wiring a second channel is exactly the exercise this seam was built for; it
  is simply not done.
