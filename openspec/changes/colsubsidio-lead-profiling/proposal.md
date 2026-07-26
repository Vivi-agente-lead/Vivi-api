# Colsubsidio Lead Profiling — Proposal

Status: proposed

## 1. Intent

Today every inbound WhatsApp lead lands the same way: a single `create_react_agent` chat that answers questions and forwards the contact. No qualification happens, so Colsubsidio asesores spend valuable cycles on leads that will never qualify for a housing subsidy, while genuinely high-purchasing-power leads wait in the same FIFO queue and churn. The non-affiliate path is worse: it carries a regulatory bottleneck (credit-bureau + caja-compensación constraints) that the current bot doesn't even surface. This change turns Vivi into a deterministic-where-it-matters, conversational-where-it-helps lead profiler that (a) gates on Colsubsidio's real eligibility rules, (b) scores purchasing power against a transparent 6-bucket matrix, and (c) hands READY leads to a human asesor and NURTURE leads to nutrición — so scarce advisor time goes only to leads that can actually close.

## 2. Scope

### In Scope
- New LangGraph **StateGraph (hybrid)** replacing the cached `create_react_agent`; 15 explicit nodes: `start`, `autorizacion_datos`, `pedir_cedula`, `afiliado_check`, `recoger_identidad`, `recoger_estado_civil`, `recoger_otra_caja`, `recoger_empleo`, 4 capacity-bundle nodes, `recoger_intencion`, `scoring` (deterministic), `handoff`.
- Conditional edges modelling the afiliado / edad / estado-civil / empleo branches from `docs/Flujo asesor…json`, including the underage gate on **both** the afiliado and no-afiliado paths.
- `AgentState.lead_profile` dict checkpointer-persisted across 10-min user gaps; **mirror** to the `leads` DB row keyed by `conversation_id` (auditable artifact).
- Three DB entities: replace `LeadEntity` with the Colsubsidio `lead` schema; **NEW** `AfiliadoColsubsidioEntity` + `ProyectoColsubsidioEntity`.
- Bootstrap + seed scripts: `scripts/bootstrap_db.py`, `scripts/seed_colsubsidio.py` (**44** projects verbatim + 15 mock afiliados), `scripts/reset_db.py` for explicit destructive resets.
- `app/services/domain_normalizer.py` — verbatim source option labels → canonical slugs, so the scorer never string-matches LLM output.
- `app/services/credit_bands.py` — hardcoded 6-band credit-score → label mapping.
- `app/services/lead_scorer.py` — pure-Python scorer with a 6-bucket point matrix summing to 100 + **absolute disqualifier** for `subsidio_vivienda_anterior=True`.
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
- `lead-scoring`: deterministic 6-bucket point matrix (Credito 25 · Afiliacion 15 · Ingreso 20 · Ahorro 15 · Tiempo 10 · Estabilidad 15 = 100) with prior-subsidy disqualifier → emits `(score, rating_label, classification, reasoning)`.
- `colsubsidio-data`: afiliados, proyectos, and credit-band reference data + seed script.

### Modified Capabilities
None — `openspec/specs/` is currently empty; this is the first spec.

## 4. Key Decisions

- **Hybrid architecture** — LangGraph `StateGraph` + per-node micro-dialogue LLM (explore fork #1, confirmed).
- **Subsidio previo = absolute disqualifier** — `subsidio_vivienda_anterior=True` forces `status="nurture"` regardless of numeric score; score still computed for analytics (explore fork #2, confirmed). Collected on **every** branch, including leads without a partner.
- **Deploy Fly.io US region** for the juror demo (explore fork #3, confirmed).
- **No-afiliado credit bureau = cedula-mod deterministic simulation** (reproducible for demo; documented as "simulated bureau").
- **Scoring threshold READY ≥ 60 for afiliados, ≥ 75 for no-afiliados** (NURTURE from 30 to below the applicable threshold; NURTURE+asesor_social <30).
- **90/10 rule encoded as a distribution target, not a hard gate** — affiliation is a strictly positive scoring signal (no-afiliado scores 0 on the Afiliacion bucket) plus the differentiated READY threshold. A hard gate would contradict the required "Happy path no-afiliado reaches READY" scenario.
- **Source vocabularies are authoritative** — every enumerated field uses the option list from `docs/Preguntas y modelo tabla de datos.xlsx`, normalized to canonical slugs at collection time. The scorer never substring-matches free text.
- **Dual persistence** — `lead_profile` in `AgentState` (checkpointer) **AND** mirrored to the `leads` DB row (auditable artifact for the juror).

## 5. Initial Approach

1. Pin the dependency manifest and commit a lockfile; re-verify the LangGraph API against the installed package.
2. Replace data model — 3 entities + `scripts/bootstrap_db.py` + `scripts/seed_colsubsidio.py`.
3. Write `domain_normalizer.py` from the source option lists — it is the input contract for everything downstream.
4. Build StateGraph skeleton: `autorizacion_datos → pedir_cedula → afiliado_check → handoff`.
5. Add branch nodes: identity (no-af only) / edad gates / estado_civil / otra_caja / empleo / 4 capacity bundles / intención.
6. Write `credit_bands.py` + `lead_scorer.py` (matrix + disqualifier + differentiated threshold).
7. Rewrite `app/prompts/system.py` — persona + per-node prompt slices in neutral Colombian Spanish.
8. Replace tools (`lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead`).
9. Tests under `tests/`: normalizer, scorer matrix, graph traversal, seed idempotency.
10. Close the pre-existing code defects: `external_id` persistence, `/simulate` env gate, webhook signature, duplicated settings field.
11. README + ARCHITECTURE.md as tail-end artifacts.

## 6. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| OpenAI geo-block (VE) kills demo | High | Fly.io US region deploy; README documents fallback OpenAI account. |
| Scoring matrix is our own design (no domain data) — juror freedom vs. defensibility | Med | Document the 6 buckets verbatim in spec; cite the Colsubsidio flow JSON and workbook as sources. The 700-point mortgage threshold named in the source backs the Bucket 1 bands. |
| LLM micro-dialogue conditional drift (asks for fields out of order) | Med | Conditional edges gate node entry; per-node prompt slices forbid off-scope questions and present the source option lists verbatim. |
| LLM answers outside the source option lists | Med | Normalizer fails closed to NULL; the bucket contributes 0 and the raw value is recorded for audit. |
| LangGraph API drift in conditional edges / checkpointer | High | Pin exact versions in `pyproject.toml` **and commit a lockfile** before apply; re-verify the API against the installed package as the first apply task. |
| Public deploy exposes the dev simulator and an unsigned webhook | High | Gate `/simulate` on `app_env == "development"`; verify `X-Hub-Signature-256` on the webhook POST. |
| Multi-channel scope creep (web adapter) | Low | Explicit non-goal; channel-agnostic core stays, adapter deferred. |

## 7. Stakeholders

- **Colsubsidio** — housing entity whose eligibility rules govern gating.
- **Leads** — afiliados and no-afiliados interacting on WhatsApp.
- **Asesores humanos** — receive READY leads only.
- **Nutrición** — receives NURTURE leads.
- **Jurado del hackathon** — demo audience for the auditable `leads` artifact.

## 8. Open Questions / Explicit Assumptions

- Assume judges have access to a shared OpenAI handle if local keys fail (or use the Fly.io US deployment).
- Assume the 15 mock afiliados are sufficient for the juror demo — we'll publish 3 "demo star" cedulas in the README. The source workbook's afiliados sheet is empty, so all 15 are fabricated by the seed script.
- Assume the 6-bucket scoring matrix is acceptable to the juror — it is documented verbatim with its source.
- Assume cedula-mod simulation for the no-afiliado credit bureau is satisfactory for the demo; it is labeled "simulated bureau" in spec and README.
- Assume the READY thresholds (60 afiliado / 75 no-afiliado) are reasonable — there is no historical conversion data to calibrate against, and the no-afiliado threshold is the single tunable if the demo's 90/10 distribution misses.
- Assume the flow diagram outranks the spreadsheet on *who is asked* and the spreadsheet outranks the diagram on *field domains* — see design §13.2.
- Assume Spanish (Colombia) neutral/professional register with `tú` for in-dialogue copy; warm but not regional-slang-heavy, and specifically not Rioplatense voseo.

## 9. Next Phase

Recommended: **`spec`** — write OpenSpec requirement deltas (Given/When/Then scenarios, RFC 2119 keywords) for `lead-profiling`, `lead-scoring`, `colsubsidio-data`.

## Rollback Plan

- Schema-affecting change: keep `LeadEntity` removal in a separate commit; revert restores the old single-entity model.
- `create_react_agent` path is preserved behind a feature flag (`LEAD_PROFILER_ENABLED=false`) until graph traversal tests pass.
- Seed script is idempotent; rollback = `python -m scripts.reset_db --yes` followed by re-bootstrap. No automatic DROP runs at server startup.
- Scorer is a pure module — revert removes `lead_scorer.py` and the `scoring` node without touching the dialogue skeleton.

## Success Criteria

- [ ] A no-afiliado conversation traverses the correct branch sequence end-to-end on WhatsApp.
- [ ] A lead with `subsidio_vivienda_anterior=True` is classified `nurture` even if its numeric score clears its threshold — including a lead with no partner.
- [ ] Every enumerated field persists a canonical slug; no bucket falls to a default because the LLM used the source wording.
- [ ] A lead choosing "Bogotá norte" receives project recommendations.
- [ ] `leads` row mirrors `AgentState.lead_profile` after every scoring node run.
- [ ] READY lead triggers `handoff` → asesor; NURTURE lead triggers `handoff` → nutrición.
- [ ] The affiliate share of READY leads is queryable in one statement and reported in the README.
- [ ] Fly.io US deploy serves the demo without OpenAI 403, with `/simulate` unreachable and the webhook signature-verified.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/graph/` | Modified | StateGraph replaces `create_react_agent`; `nodes/`, `router.py`. |
| `app/services/lead_scorer.py` | New | 6-bucket scorer + disqualifier. |
| `app/services/domain_normalizer.py` | New | Source option labels → canonical slugs; municipio mapping. |
| `app/services/credit_bands.py` | New | Hardcoded credit-band labels. |
| `app/models/` | Modified/New | Replace `LeadEntity`; add `AfiliadoColsubsidioEntity`, `ProyectoColsubsidioEntity`, `constants.py`. |
| `app/prompts/system.py` | Modified | Colsubsidio persona + per-node slices. |
| `scripts/` | New | `bootstrap_db.py`, `seed_colsubsidio.py` (44 projects + 15 afiliados), `reset_db.py`. |
| `app/tools/` | Modified | 5 tools added/replaced. |
| `app/routers/whatsapp.py` | Modified | `/simulate` env gate; webhook signature verification. |
| `app/services/agent_service.py` | Modified | Per-node prompts; forward `external_id` so wamid idempotency works. |
| `tests/` | New | Normalizer, scorer, traversal, seed idempotency. |
| `pyproject.toml` | Modified | Exact pins + committed lockfile. |

## Dependencies

- An exact, pinned langgraph + langchain-openai version with a committed lockfile. The manifest currently declares open lower bounds (`langgraph>=0.5`), which is not a pin.
- Fly.io account + US region allocation for demo deploy.
- Existing WhatsApp webhook (hardened, not replaced).