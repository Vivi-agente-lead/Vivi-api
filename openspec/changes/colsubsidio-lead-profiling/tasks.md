# Tasks: Colsubsidio Lead Profiling

Derived from `proposal.md`, the 7 spec deltas, and `design.md` (revision 2).
Each task is sized for one working session. The `closes` column traces back to
`review-ledger.md` finding ids so the audit can be re-run against the result.

**Sequencing.** Phase 0 gates everything — the change's top risk is LangGraph API
drift against an unpinned manifest, and the previous design revision shipped a
`return "END"` defect precisely because nobody had the package installed. Phases 1
and 5 are independent of each other and of Phase 2; Phase 4 needs 1, 2 and 3.

```
0 ──► 1 ──► 3 ──► 4 ──► 6
      │     ▲     ▲
      └► 2 ─┘     │
   5 ───────────► ┘   (5 is independent; land it whenever)
```

**Definition of done for every task**: `pytest -q` green, no new `print()`, type
hints present, `logging.getLogger(__name__)` for output.

---

## Phase 0 — De-risk the toolchain

Nothing else starts until 0.1 and 0.2 are done. Both exist because the audit found
the change's stated risk mitigation did not exist.

- [x] **0.1 Pin dependencies and commit a lockfile**
  `pyproject.toml` currently declares open lower bounds (`langgraph>=0.5` spans a
  major version). Resolve, pin exact versions, commit the lockfile, and record the
  resolved versions in `openspec/config.yaml` replacing the `KNOWN GAP` note.
  *Files*: `pyproject.toml`, lockfile, `openspec/config.yaml` · *closes*: SDD-005

- [x] **0.2 Verify the LangGraph API against the installed package**
  With the pinned version installed, confirm in a throwaway script: `StateGraph`
  constructor, `add_conditional_edges` signature, the value of `END`, async node
  return shape, and `compile(checkpointer=...)`. Correct `design.md` §3 if anything
  differs. Confirm whether `langgraph.prebuilt.create_react_agent` still resolves —
  the current `app/graph/builder.py:27` depends on it until Phase 4 lands.
  *Files*: `design.md` §3 · *closes*: LOGIC-002 (verification), SDD-005

- [x] **0.3 Remove the duplicated settings field**
  `app/core/config.py:56-57` declares `whatsapp_api_version` twice; fix the stray
  de-indentation of the `# ── WhatsApp ──` comment at line 52 while you are there.
  *Files*: `app/core/config.py` · *closes*: CODE-002

---

## Phase 1 — Data layer

- [x] **1.1 Canonical slug constants**
  `app/models/constants.py` — the seven enumerated domains from the
  `Source Domain Normalization` requirement, plus `ESTADO_CIVIL_CON_PAREJA` and
  `CONTRATO_EMPLEADO` as the predicate source sets, and the `status` domain
  `{profiling, ready, nurture, nurture_social}`.
  *Files*: `app/models/constants.py`

- [x] **1.2 Normalizer tests (write first)**
  `tests/test_domain_normalizer.py` — every verbatim label from the workbook maps to
  its slug, with and without accents and casing; unknown values return `None`; the
  municipio table maps all nine lead-facing options; `'VIS'` repairs to `'Bogota'`.
  *Files*: `tests/test_domain_normalizer.py` · *spec*: `lead-scoring` §Source Domain Normalization

- [x] **1.3 Domain normalizer**
  `app/services/domain_normalizer.py` — exact lookup after case-folding and
  accent-stripping. Never substring-matches. `normalize(field, raw) -> str | None`
  plus `normalize_municipio` and `repair_catalogo_municipio`.
  *Files*: `app/services/domain_normalizer.py` · *closes*: DATA-001, DATA-002, DATA-004, DATA-005, DATA-006, DATA-009, DATA-010

- [x] **1.4 Replace `LeadEntity` with `LeadColsubsidioEntity`**
  Per `design.md` §6. Enumerated columns hold slugs; `municipio_normalizado` indexed;
  `ix_leads_status_afiliado` for the 90/10 query; `normalization_notes` JSONB.
  *Files*: `app/models/lead_model.py`, `app/models/__init__.py` · *closes*: SDD-004

- [x] **1.5 Afiliado and proyecto entities**
  `AfiliadoColsubsidioEntity` (`fecha_nacimiento` as a real `Date`) and
  `ProyectoColsubsidioEntity` (12 columns; **`modelo` is `NOT NULL DEFAULT ''`** so
  the `(proyecto, modelo)` key matches the two blank-modelo rows).
  *Files*: `app/models/afiliado_model.py`, `app/models/proyecto_model.py`, `app/models/__init__.py` · *closes*: DATA-008

- [x] **1.6 Repositories**
  `lead_repository`: `find_by_conversation_id`, `upsert_by_conversation_id` with
  field-merge semantics **and the terminal-status guard** (a terminal status may not
  change — the guard lives here so all three writers inherit it).
  `afiliado_repository.find_by_doc`, `proyecto_repository.find_filtered` ordered by
  `(proyecto, modelo)`.
  *Files*: `app/models/repositories/{lead,afiliado,proyecto}_repository.py` · *closes*: LOGIC-008

- [x] **1.7 Bootstrap and reset scripts**
  `scripts/bootstrap_db.py` — `create_all(checkfirst=True)`, real exit code, **no
  DROP under any environment**. `scripts/reset_db.py` — destructive, requires `--yes`,
  never invoked by the server.
  *Files*: `scripts/bootstrap_db.py`, `scripts/reset_db.py` · *closes*: SDD-003, RES-001

- [x] **1.8 Seed — 44 proyectos**
  Transcribe sheet `Proyectos` verbatim. Parse comma decimals (`56,29` → `56.29`);
  blank numeric cells → NULL, not `0`; blank `modelo` → `''`. Preserve the
  `VIBO ONCE` `B2` (`tipo`=`municipio`=`'VIS'`), `VERSALLES` `E`
  (privada 60,60 > construida 56,29), `ABETO` and `LA ARBOLEDA` rows unchanged.
  `INSERT … ON CONFLICT (proyecto, modelo) DO NOTHING`.
  *Files*: `scripts/seed_colsubsidio.py` · *closes*: DATA-007, DATA-011

- [x] **1.9 Seed — 15 afiliados**
  The source sheet has **zero** afiliado rows; all 15 are fabricated here. Cover all
  three `categoria_afiliado` values and every one of the six credit bands; at least
  one with `ha_recibido_subsidio=true`. Demo stars: `1010101010` Andrea Marín (A, 880),
  `2020202020` Beto Salazar (B, 720), `3030303030` Camila Ríos (C, 580).
  `DELETE WHERE is_seed=true` then re-INSERT.
  *Files*: `scripts/seed_colsubsidio.py` · *closes*: DATA-012

- [x] **1.10 Seed idempotency test**
  `tests/test_seed_idempotency.py` — run twice; assert `count(proyectos)==44`,
  `count(afiliados WHERE is_seed)==15`, and that `ABETO` and `LA ARBOLEDA` each appear
  exactly once. Skip cleanly when no Postgres is reachable.
  *Files*: `tests/test_seed_idempotency.py` · *closes*: RES-003 (location)

- [x] **1.11 Caja de compensación vocabulary**
  The 30+ enumerated cajas from the workbook as a constant; `otra_caja_compensacion`
  accepts a member, `ninguna`, or NULL.
  *Files*: `app/models/constants.py` · *closes*: DATA-013

---

## Phase 2 — Scoring (pure; parallel with Phase 1 after 1.1)

- [x] **2.1 Credit bands**
  `app/services/credit_bands.py` — the six bands verbatim from the workbook legend,
  `band_from_score_credito(score) -> (pts, label)` returning `(0, "Malo")` for NULL,
  and `simulate_bureau_cedula`.
  *Files*: `app/services/credit_bands.py`

- [x] **2.2 Scorer tests (write first)**
  `tests/test_lead_scorer.py` — the 12 cases in `design.md` §11. The two that guard
  regressions the audit found: **case 5** (`estado_civil='soltero'` with
  `subsidio_vivienda_anterior=True` still yields `nurture`) and **case 8**
  (`ahorros_o_cesantias='menos_3m'` scores 5, not 0). Plus case 12 (afiliado strictly
  outscores an otherwise-identical no-afiliado).
  *Files*: `tests/test_lead_scorer.py` · *spec*: `lead-scoring`

- [x] **2.3 Scorer**
  `app/services/lead_scorer.py` per `design.md` §7.3. Six buckets summing to 100,
  exact slug lookup everywhere, `0` for unknown, additive red flags then clamp,
  affiliation-dependent READY threshold, subsidio-previo override that never touches
  the numeric score. `classification == status`.
  *Files*: `app/services/lead_scorer.py` · *closes*: DATA-003, LOGIC-005, LOGIC-006, SDD-007

---

## Phase 3 — Tools

- [ ] **3.1 Replace the tool module**
  Five tools per `design.md` §5: `lookup_afiliado`, `save_lead`, `get_lead`,
  `get_projects`, `classify_lead`. Delete the `search_leads` and `score_lead` stubs.
  `save_lead` normalizes every enumerated field before writing and records rejects in
  `normalization_notes`. `get_projects` takes `municipio_normalizado` and applies the
  `'VIS'` repair. No `langgraph` import.
  *Files*: `app/tools/lead_tools.py` · *spec*: `agent-tools`

- [ ] **3.2 Tool registry**
  Wire the five tools to role `"agent"`.
  *Files*: `app/tools/tool_registry.py`

- [ ] **3.3 Tool tests**
  `tests/test_lead_tools.py` — `save_lead` upsert preserves prior fields and never
  promotes `status`; `get_lead` returns `null` with no row; `lookup_afiliado` accepts
  all five document slugs and rejects `TI`; `get_projects` returns rows for `'Bogota'`;
  an LLM-supplied `conversation_id` is ignored.
  *Files*: `tests/test_lead_tools.py`

---

## Phase 4 — Graph

Land 4.4 (the smallest end-to-end machine) before adding branches — that was the
design's own risk mitigation for API drift and it still applies.

- [ ] **4.1 Agent state**
  `lead_profile`, `current_node`, `pending_user_reply`. Retire `lead_profile_draft`.
  *Files*: `app/graph/state.py`

- [ ] **4.2 Routers**
  `app/graph/router.py` — the five predicates from `design.md` §3. All terminal
  returns use the **`END` sentinel imported from `langgraph.graph`**, never the string
  `"END"`. `edad is None` routes to `END` in both age gates.
  *Files*: `app/graph/router.py` · *closes*: LOGIC-002, LOGIC-003

- [ ] **4.3 Router tests**
  `tests/test_router.py` — table-driven over every branch, including
  `divorciado`/`separado`/`viudo` reaching the `sin_pareja` bundles, and both underage
  gates returning `END`.
  *Files*: `tests/test_router.py` · *closes*: DATA-010

- [ ] **4.4 Spine: `start` → `autorizacion_datos` → `pedir_cedula` → `afiliado_check` → `handoff`**
  Four nodes plus a stub handoff, compiled and traversable end to end. `afiliado_check`
  is tool-dispatch only (no LLM): calls `lookup_afiliado`, derives `edad` server-side,
  creates the `leads` row at `status='profiling'`.
  *Files*: `app/graph/nodes/`, `app/graph/builder.py`

- [ ] **4.5 Prompt slices**
  `app/prompts/slices.py` + `render_system_prompt(node, …)`. Neutral professional
  Colombian Spanish with `tú` — **no voseo, no German or Portuguese fragments** (the
  previous design revision carried `Gespräch`, `atualizá`, `pregunts`, `laconfirmation`).
  Every slice that collects an enumerated field prints the source option list verbatim.
  *Files*: `app/prompts/slices.py`, `app/prompts/system.py` · *closes*: DOC-001

- [ ] **4.6 Identity, estado civil, otra caja**
  `recoger_identidad` (no-afiliado; `edad` computed server-side from
  `fecha_nacimiento`, never trusted from the LLM), `recoger_estado_civil` (6-value
  domain, derives `tiene_pareja`), `recoger_otra_caja` (no-afiliado only).
  *Files*: `app/graph/nodes/`

- [ ] **4.7 Empleo and the four capacity bundles**
  `recoger_empleo` stores the specific `contrato_laboral` slug and derives
  `es_empleado`. Each bundle collects `subsidio_vivienda_anterior`, `numero_pac`,
  `condicion_discapacidad_familiar`, `tiene_vivienda_propia`, `ahorros_o_cesantias`,
  `tiene_creditos_activos`, the correct income field, `antiguedad_laboral` (empleado
  only), `rango_salarial` (no-afiliado **and** empleado only), then derives
  `cabeza_de_hogar` and calls `save_lead`.
  *Files*: `app/graph/nodes/` · *closes*: LOGIC-001, LOGIC-004, LOGIC-007

- [ ] **4.8 Intención, scoring, handoff**
  `recoger_intencion` persists both `lugar_eleccion_vivir` and `municipio_normalizado`.
  `scoring` is pure: project lookup to set `vis_recommended`, then `score_lead`, then
  `classify_lead`. `handoff` calls `get_projects` **only** when `status=='ready'` and
  renders the matching sub-slice.
  *Files*: `app/graph/nodes/`

- [ ] **4.9 Post-LLM validators**
  `app/graph/nodes/_validators.py` — strip out-of-schema answers before merging into
  `lead_profile`; route every enumerated value through the normalizer; append rejects
  to `normalization_notes`.
  *Files*: `app/graph/nodes/_validators.py`

- [ ] **4.10 Crash recovery**
  `app/services/lead_state_rebuilder.py::rebuild_lead_profile(conv_id)`; call it from
  `AgentService.send_message` on the first turn when the checkpointer has no state.
  *Files*: `app/services/lead_state_rebuilder.py`, `app/services/agent_service.py`

- [ ] **4.11 Traversal tests**
  `tests/test_graph_traversal.py` — READY afiliado end to end; a no-afiliado scoring
  in [60, 74] classified `nurture` (proving the 75 threshold); an afiliado aged 17
  terminating at the afiliado-side gate.
  *Files*: `tests/test_graph_traversal.py`

- [ ] **4.12 Wire the graph and retire the ReAct path**
  `builder.py` compiles the 15-node graph behind `LEAD_PROFILER_ENABLED`; remove
  `create_react_agent` once 4.11 is green.
  *Files*: `app/graph/builder.py`, `app/core/config.py`

---

## Phase 5 — Channel hardening (independent; land any time)

- [ ] **5.1 Make wamid idempotency real**
  Thread `external_id` from `InboundMessageHandler.handle` through
  `AgentService.send_message` into `MessageService.persist_user_message` (which
  already accepts it). Today the column is never written, so the duplicate guard never
  fires and a Meta retry re-runs the agent and sends a second reply.
  *Files*: `app/services/inbound_handler.py`, `app/services/agent_service.py` · *closes*: CODE-001

- [ ] **5.2 Idempotency test**
  `tests/test_inbound_idempotency.py` — deliver the same `external_id` twice; assert
  `AgentService.send_message` runs once.
  *Files*: `tests/test_inbound_idempotency.py`

- [ ] **5.3 Gate the dev simulator**
  Register `POST /whatsapp/simulate` only when `settings.app_env == "development"`.
  With `dry_run=false` on a public URL it is an open relay able to send arbitrary
  WhatsApp messages to arbitrary recipients through the project's Meta credentials.
  *Files*: `app/routers/whatsapp.py` · *closes*: SEC-001

- [ ] **5.4 Verify the webhook signature**
  Validate `X-Hub-Signature-256` on `POST /whatsapp/webhook`; 403 on mismatch, with no
  conversation created and no LLM call. Add `WHATSAPP_APP_SECRET` to settings and
  `.env.example`. The `hub.verify_token` guards only the `GET` handshake.
  *Files*: `app/routers/whatsapp.py`, `app/core/config.py`, `.env.example` · *closes*: SEC-002

- [ ] **5.5 Health reports readiness**
  `GET /health` returns 503 when the database is unreachable, naming the dependency.
  Stop swallowing `init_db()` failures silently in the lifespan. Without this the
  deployment spec's health scenario passes against a demo with no tables.
  *Files*: `app/routers/health.py`, `app/main.py` · *closes*: RES-002

---

## Phase 6 — Delivery

- [ ] **6.1 Dockerfile**
  Copy `scripts/` (and any source data the seed reads) into the image; install from
  the lockfile. The current image copies only `pyproject.toml`, `README.md` and
  `app/`, so the seed cannot run on Fly.
  *Files*: `Dockerfile` · *closes*: RES-004

- [ ] **6.2 Fly.io deploy**
  `fly.toml` for a US region; set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, Postgres DSN,
  `WHATSAPP_APP_SECRET`, and `APP_ENV=production` (which also closes `/simulate`).
  Run bootstrap + seed once against the deployed database.
  *Files*: `fly.toml`

- [ ] **6.3 Reconcile Postgres credentials**
  `.env.example` (`postgres`/`123456789`), `app/core/config.py` defaults
  (`vivi`/`vivi`) and `docker-compose.yml` (`vivi`/`vivi`) disagree three ways.
  *Files*: `.env.example`, `app/core/config.py`, `docker-compose.yml` · *closes*: DOC-003

- [ ] **6.4 README rewrite**
  Remove the SSE endpoint claim and the "WhatsApp stubbed at `app/routers/webhook.py`"
  claim — both are false, in opposite directions. Add the juror walkthrough: Fly URL,
  the 3 demo-star cedulas with expected outcomes, simulator commands, webhook verify
  token placeholder, the affiliate-share query, and the Meta sandbox caveat. Under 5
  minutes end to end.
  *Files*: `README.md` · *closes*: DOC-002

- [ ] **6.5 ARCHITECTURE.md**
  Channel-agnostic seam (`AgentService.send_message` + `ToolContext`), the 15-node
  topology, and the normalizer boundary. Mirror the §13 recorded decisions here so
  they survive without Engram.
  *Files*: `ARCHITECTURE.md` · *closes*: SDD-008, SDD-010

- [ ] **6.6 Demo rehearsal**
  Drive all three demo-star cedulas plus one no-afiliado and one prior-subsidy lead
  against the Fly URL. Confirm the READY lead sees projects, the affiliate share query
  returns a sane figure, and `/simulate` 404s in production.
  *Verifies*: proposal §Success Criteria

---

## Notes

**Parallel lanes.** After Phase 0, one person can take Phase 1 while another takes
Phase 5 — they share no files. Phase 2 only needs `constants.py` from 1.1.

**TDD.** `openspec/config.yaml` sets `strict_tdd: false` and `apply.tdd: false` for the
hackathon, but the current session harness reports Strict TDD Mode enabled. The task
order above writes tests first for the two pure modules (1.2 before 1.3, 2.2 before
2.3), where it costs nothing and the audit found real defects. The graph and channel
phases are test-after. **Confirm which setting governs before starting Phase 1** — if
strict TDD wins, 3.3, 4.3, 4.11 and 5.2 move ahead of their implementation tasks.

**Still open at the end of the planning pass.** Every finding in `review-ledger.md` with
status `open` is assigned above: SDD-001 closes when this file is approved; CODE-001,
CODE-002, SEC-001, SEC-002, RES-002, RES-004, DOC-002, DOC-003 and SDD-010 map to tasks
0.3, 5.1, 5.3, 5.4, 5.5, 6.1, 6.3, 6.4 and 6.5.
