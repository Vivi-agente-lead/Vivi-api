# Colsubsidio Lead Profiling — Proposal

Status: proposed

## 1. Intent

Today every inbound WhatsApp lead lands the same way: a single `create_react_agent` chat that answers questions and forwards the contact. No qualification happens, so Colsubsidio asesores spend valuable cycles on leads that will never qualify for a housing subsidy, while genuinely high-purchasing-power leads wait in the same FIFO queue and churn. The non-affiliate path is worse: it carries a regulatory bottleneck (credit-bureau + caja-compensación constraints) that the current bot doesn't even surface. This change turns Vivi into a deterministic-where-it-matters, conversational-where-it-helps lead profiler that (a) gates on Colsubsidio's real eligibility rules, (b) scores purchasing power against a transparent 7-bucket matrix, and (c) hands READY leads to a human asesor and NURTURE leads to nutrición — so scarce advisor time goes only to leads that can actually close.

## 2. Scope

### In Scope
- New LangGraph **StateGraph (hybrid)** replacing the cached `create_react_agent`; explicit nodes `autorizacion_datos`, `pedir_cedula`, `afiliado_check`, `recoger_identidad`, `recoger_estado_civil`, `recoger_empleo`, 4 capacity-bundle nodes, `recoger_intencion`, `scoring` (deterministic), `handoff`.
- Conditional edges modelling the afiliado / estado-civil / empleo branches from `docs/Flujo asesor…json`.
- `AgentState.lead_profile` dict checkpointer-persisted across 10-min user gaps; **mirror** to the `leads` DB row keyed by `conversation_id` (auditable artifact).
- Three DB entities: replace `LeadEntity` with the Colsubsidio `lead` schema; **NEW** `AfiliadoColsubsidioEntity` + `ProyectoColsubsidioEntity`.
- Seed script `scripts/seed_colsubsidio.py`: 43 projects (verbatim) + 15 mock afiliados.
- `app/services/credit_bands.py` — hardcoded 6-band credit-score → label mapping.
- `app/services/lead_scorer.py` — pure-Python scorer with the 7-bucket point matrix + **absolute disqualifier** for `subsidio_vivienda_anterior=True`.
- Tools: `lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead`.
- Rewrite `app/prompts/system.py` — warm, human Spanish (Colombia) persona + per-node focused prompt slices.
- Channel: WhatsApp only (existing webhook + simulator unchanged); core stays channel-agnostic.
- Deploy: Fly.io US region for the juror demo (bypasses OpenAI 403 geo-block on Venezuela).

### Out of Scope / Non-Goals
- Real integration with Colsubsidio DB or DataCrédito (simulated via mock table + cedula-mod).
- Web/HTTP channel adapter (README mention only; not built this iteration).
- Multi-turn HITL / human-approval confirmation flow.
- Alembic migrations (still on `Base.metadata.create_all`).
- Real CRM integration, credit approval, contract signing.
- Marketing / nurturing content strategy.

## 3. Capabilities

### New Capabilities
- `lead-profiling`: end-to-end StateGraph dialogue that collects, gates, scores, and routes Colsubsidio leads (afiliado + no-afiliado paths).
- `lead-scoring`: deterministic 7-bucket point matrix with prior-subsidy disqualifier → emits `(score, rating_label, classification, reasoning)`.
- `colsubsidio-data`: afiliados, proyectos, and credit-band reference data + seed script.

### Modified Capabilities
None — `openspec/specs/` is currently empty; this is the first spec.

## 4. Key Decisions

- **Hybrid architecture** — LangGraph `StateGraph` + per-node micro-dialogue LLM (explore fork #1, confirmed).
- **Subsidio previo = absolute disqualifier** — `subsidio_vivienda_anterior=True` forces `status="nurture"` regardless of numeric score; score still computed for analytics (explore fork #2, confirmed).
- **Deploy Fly.io US region** for the juror demo (explore fork #3, confirmed).
- **No-afiliado credit bureau = cedula-mod deterministic simulation** (reproducible for demo; documented as "simulated bureau").
- **Scoring threshold READY ≥ 60** (NURTURE 30–59; NURTURE+asesor_social <30).
- **Dual persistence** — `lead_profile` in `AgentState` (checkpointer) **AND** mirrored to the `leads` DB row (auditable artifact for the juror).

## 5. Initial Approach

1. Replace data model — 3 entities + `scripts/seed_colsubsidio.py`.
2. Build StateGraph skeleton: `autorizacion_datos → pedir_cedula → afiliado_check`.
3. Add branch nodes: identity (no-af only) / estado_civil / empleo / 4 capacity bundles / intención.
4. Write `credit_bands.py` + `lead_scorer.py` (matrix + disqualifier).
5. Rewrite `app/prompts/system.py` — persona + per-node prompt slices.
6. Replace tools (`lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead`).
7. Smoke tests: graph traversal + scorer matrix + disqualifier path.
8. README + ARCHITECTURE.md as tail-end artifacts.

## 6. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| OpenAI geo-block (VE) kills demo | High | Fly.io US region deploy; README documents fallback OpenAI account. |
| Scoring matrix is our own design (no domain data) — juror freedom vs. defensibility | Med | Document the 7 buckets verbatim in spec; cite Colsubsidio flow JSON as source. |
| LLM micro-dialogue conditional drift (asks for fields out of order) | Med | Conditional edges gate node entry; per-node prompt slices forbid off-scope questions. |
| LangGraph 1.x API drift in conditional edges / checkpointer | Med | Pin langgraph 1.2.9; smoke-test graph traversal before each node add. |
| Multi-channel scope creep (web adapter) | Low | Explicit non-goal; channel-agnostic core stays, adapter deferred. |

## 7. Stakeholders

- **Colsubsidio** — housing entity whose eligibility rules govern gating.
- **Leads** — afiliados and no-afiliados interacting on WhatsApp.
- **Asesores humanos** — receive READY leads only.
- **Nutrición** — receives NURTURE leads.
- **Jurado del hackathon** — demo audience for the auditable `leads` artifact.

## 8. Open Questions / Explicit Assumptions

- Assume judges have access to a shared OpenAI handle if local keys fail (or use the Fly.io US deployment).
- Assume the 15 mock afiliados are sufficient for the juror demo — we'll publish 3 "demo star" cedulas in the README.
- Assume the 7-bucket scoring matrix is acceptable to the juror — it is documented verbatim with its source.
- Assume cedula-mod simulation for the no-afiliado credit bureau is satisfactory for the demo; it is labeled "simulated bureau" in spec and README.
- Assume the READY ≥ 60 threshold is reasonable — there is no historical conversion data to calibrate against.
- Assume Spanish (Colombia) neutral/professional register for in-dialogue copy is the right voice; warm but not regional-slang-heavy.

## 9. Next Phase

Recommended: **`spec`** — write OpenSpec requirement deltas (Given/When/Then scenarios, RFC 2119 keywords) for `lead-profiling`, `lead-scoring`, `colsubsidio-data`.

## Rollback Plan

- Schema-affecting change: keep `LeadEntity` removal in a separate commit; revert restores the old single-entity model.
- `create_react_agent` path is preserved behind a feature flag (`LEAD_PROFILER_ENABLED=false`) until graph smoke tests pass.
- Seed script is idempotent (DROP + INSERT inside a transaction); rollback = `TRUNCATE afiliados, proyectos, leads`.
- Scorer is a pure module — revert removes `lead_scorer.py` and the `scoring` node without touching the dialogue skeleton.

## Success Criteria

- [ ] A no-afiliado conversation traverses the correct branch sequence end-to-end on WhatsApp.
- [ ] A lead with `subsidio_vivienda_anterior=True` is classified `nurture` even if its numeric score is ≥ 60.
- [ ] `leads` row mirrors `AgentState.lead_profile` after every scoring node run.
- [ ] READY lead triggers `handoff` → asesor; NURTURE lead triggers `handoff` → nutrición.
- [ ] Fly.io US deploy serves the demo without OpenAI 403.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/agents/` | Modified | StateGraph replaces `create_react_agent`; per-node prompts. |
| `app/services/lead_scorer.py` | New | 7-bucket scorer + disqualifier. |
| `app/services/credit_bands.py` | New | Hardcoded credit-band labels. |
| `app/entities/` | Modified/New | Replace `LeadEntity`; add `AfiliadoColsubsidioEntity`, `ProyectoColsubsidioEntity`. |
| `app/prompts/system.py` | Modified | Colsubsidio persona + per-node slices. |
| `scripts/seed_colsubsidio.py` | New | 43 projects + 15 afiliados. |
| `app/tools/` | Modified | 5 tools added/replaced. |

## Dependencies

- langgraph 1.2.9 (pinned), langchain-openai 1.4.1.
- Fly.io account + US region allocation for demo deploy.
- Existing WhatsApp webhook (unchanged).