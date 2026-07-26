# vivi-api

Backend for **Vivi**, a conversational agent that profiles Colsubsidio housing
leads on WhatsApp: it gates on real eligibility rules, scores purchasing power
against a transparent 6-bucket matrix, and routes each lead to a human asesor
(`ready`), a nurture pipeline (`nurture`), or social support
(`nurture_social`) — so scarce advisor time only goes to leads that can
actually close. See `docs/Reto_de_vivienda_Descripcion.md` for the original
brief and `ARCHITECTURE.md` for how the pieces fit together.

This is a hackathon build. Read "Known limitations" before treating any claim
here as production-ready.

## Juror walkthrough (under 5 minutes)

1. **Open the deployed API.** Fly URL: `https://<your-fly-app-name>.fly.dev`
   (placeholder — see "Deploy to Fly.io"; not yet deployed by this change, see
   "What is explicitly not done").
2. **Drive a conversation with the dev simulator** (no real WhatsApp number
   needed — `dry_run=true` skips the outbound Meta call and only returns the
   agent's reply in the response body):

   ```bash
   curl -X POST "https://<your-fly-app-name>.fly.dev/whatsapp/simulate" \
     --get \
     --data-urlencode "from=573001234567" \
     --data-urlencode "text=Hola" \
     --data-urlencode "dry_run=true"
   ```

   Repeat with the next reply each time, reusing the same `from` number so the
   conversation continues on the same thread. The three scripts below are
   copy-pasteable end-to-end conversations against the three seeded demo-star
   afiliados (`scripts/seed_colsubsidio.py`); the exact question order is
   enforced by `app/graph/nodes/capacity.py` and verified by
   `tests/test_graph_traversal.py`, so it will not drift if the prompts are
   reworded.

3. **Verify the Meta webhook handshake locally** (no real Meta account
   needed — this is the same check Meta itself runs against the deployed URL):

   ```bash
   curl -i "https://<your-fly-app-name>.fly.dev/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<your-verify-token>&hub.challenge=12345"
   # expect: 200 and a body of exactly "12345"
   ```

   `<your-verify-token>` is whatever you set `WHATSAPP_WEBHOOK_VERIFY_TOKEN` to
   at deploy time (see `.env.example`); it is not a secret Meta computes, it is
   a shared string you both configure.

### Demo-star cedulas (`scripts/seed_colsubsidio.py`)

All three are afiliados (`categoria_afiliado` × credit band), so the READY
threshold that applies is 60, not 75 (`app/services/lead_scorer.py`,
`READY_THRESHOLD_AFILIADO`). Scores below are computed by hand against the
pinned scorer/normalizer logic for the exact answer sequence given — they were
not captured from a live run against a deployed OpenAI key (none was available
in the environment this change was built in). Re-running the script is the way
to confirm them; `app/services/credit_bands.py::DEMO_CEDULA_SCORES` is the
single source these three cedulas are drawn from.

#### 1. `1010101010` — Andrea Marín — categoría **A**, score_credito **880 (Excelente)** → expect **READY**

Send these messages in order (each a separate `/whatsapp/simulate` call, or
paste them one at a time into a WhatsApp thread once deployed):

```
Hola
Sí
Cédula de ciudadanía
1010101010
Casado
Termino indefinido
9.000.000
Mas de dos años
No
Más de $40 millones
No
2
No
No
Bogotá norte
3 meses
Un apartamento con dos habitaciones y balcón.
```

Expected: `status=ready`, score 100/100 (25 crédito + 15 afiliación A + 14
ingreso [4_8m, derived from her salario_base_cotizacion] + 15 ahorro + 10
tiempo + 15 estabilidad + 8 PAC bonus, clamped at 100). The closing message
names the READY asesor hand-off and lists matching projects near Bogotá if any
are catalogued there (`scripts/seed_colsubsidio.py` seeds several).

#### 2. `2020202020` — Beto Salazar — categoría **B**, score_credito **720 (Bueno)** → expect **NURTURE**

```
Hola
Sí
Cédula de ciudadanía
2020202020
Casado
Termino fijo
3.500.000
Menos de 1 año
No
No tengo ahorros.
Sí
0
No
No
Chía
No sé
Un apartamento cómodo cerca del trabajo.
```

Expected: `status=nurture`, score 39/100 (18 crédito + 11 afiliación B + 10
ingreso + 0 ahorro + 0 tiempo + 5 estabilidad − 5 active-credit flag). This
script deliberately picks weak capacity answers to show that a mid-tier
affiliate does **not** get a free pass to READY — the score is a function of
the whole profile, not just the affiliation category.

#### 3. `3030303030` — Camila Ríos — categoría **C**, score_credito **580 (Regular)** → expect **NURTURE_SOCIAL**

```
Hola
Sí
Cédula de ciudadanía
3030303030
Union libre
Prestacion de servicios
3.000.000
No
No tengo ahorros.
No
0
No
No
Ricaurte
No sé
Una vivienda sencilla para mi familia.
```

Expected: `status=nurture_social`, score 24/100 (6 crédito + 7 afiliación C +
5 ingreso + 0 ahorro + 0 tiempo + 6 independiente estabilidad, no red flags).
The closing message routes to social support and never mentions the numeric
score (`app/prompts/slices.py::handoff_nurture_social`).

### Affiliate share (90/10) query

Run this against the deployed Postgres (`psql $DATABASE_URL -c "..."` or via
Fly's `fly postgres connect`) to check the affiliate share of READY leads the
proposal's 90/10 target is about:

```sql
SELECT
  count(*) FILTER (WHERE afiliado_colsubsidio)                                   AS ready_afiliados,
  count(*) FILTER (WHERE NOT afiliado_colsubsidio)                               AS ready_no_afiliados,
  round(100.0 * count(*) FILTER (WHERE afiliado_colsubsidio) / NULLIF(count(*), 0), 1) AS pct_afiliado
FROM leads
WHERE status = 'ready';
```

Backed by `ix_leads_status_afiliado` (`app/models/lead_model.py`) so the scan
stays cheap even as the `leads` table grows during the demo.

### Meta sandbox caveat

A Meta WhatsApp Business app in development mode only delivers messages to
phone numbers explicitly added as test recipients in the Meta dashboard. The
`/whatsapp/simulate` endpoint above sidesteps this entirely (it never calls
Meta when `dry_run=true`), which is exactly why it exists for rehearsal. If you
drive the demo through the **real** WhatsApp number (`dry_run=false` or an
actual inbound message), it will only reach numbers your Meta app has
whitelisted as sandbox testers — it will silently fail to reach anyone else.

## What works

- FastAPI app (`app/main.py`) mounting exactly two routers:
  `app/routers/health.py` (`GET /health`) and `app/routers/whatsapp.py`
  (`GET`/`POST /whatsapp/webhook`, `POST /whatsapp/simulate`). **WhatsApp is
  the only implemented, mounted channel.**
- A custom LangGraph `StateGraph` — 15 explicit nodes
  (`app/graph/builder.py`, `app/graph/nodes/`) — replacing the earlier
  `create_react_agent` loop, so Colsubsidio's eligibility gates (age, document
  domain, affiliate status) are enforced in Python, not by LLM discretion. See
  `ARCHITECTURE.md` §2 for the full topology.
- A pure, deterministic scorer (`app/services/lead_scorer.py`) — six buckets
  summing to 100, additive red flags, an absolute prior-subsidy disqualifier —
  reproducible across two process invocations of the same inputs.
- A verbatim-label → canonical-slug normalizer
  (`app/services/domain_normalizer.py`) so the scorer never substring-matches
  free text (`ARCHITECTURE.md` §3).
- Async SQLAlchemy 2.x + PostgreSQL persistence: `leads`,
  `afiliados_colsubsidio`, `proyectos_colsubsidio`, `conversations`,
  `messages`. Schema via `scripts/bootstrap_db.py`
  (`Base.metadata.create_all(checkfirst=True)`, no Alembic yet).
  `scripts/seed_colsubsidio.py` seeds 44 real projects (verbatim transcription
  of the source workbook) and 15 mock afiliados, idempotently.
- Checkpointer selectable between `MemorySaver` (dev) and `AsyncPostgresSaver`
  (prod) via `LLM_CHECKPOINTER`.
- Crash recovery: if the checkpointer loses a thread, the next turn rebuilds
  `lead_profile` from the persisted `leads` row
  (`app/services/lead_state_rebuilder.py`) instead of re-asking everything.
- Tool registry with a `@safe_tool` decorator and `ToolContext` DI via
  `RunnableConfig` (`app/tools/lead_tools.py`, `app/tools/tool_registry.py`):
  `lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead`.
  No tool accepts `conversation_id` as an LLM argument — see
  `ARCHITECTURE.md` §1.
- A channel-agnostic core (`AgentService.send_message` +
  `ToolContext` — `ARCHITECTURE.md` §1): a second channel adapter is a router
  + a call to `send_message`, nothing in the graph or tools changes.
- 279 passing tests, 3 skipped (see "Running the tests").

## What is explicitly not done yet

- **Not deployed to Fly.io.** `fly.toml` is authored (task 6.2 in
  `openspec/changes/colsubsidio-lead-profiling/tasks.md` is explicitly out of
  scope for this change — it needs a Fly.io account this agent does not have).
  The "Deploy to Fly.io" section below documents the exact commands; nobody
  has run them yet.
- **No demo rehearsal against a live Fly URL** (task 6.6) — same reason.
- **Phase 5 channel hardening has not landed on this branch.** Concretely,
  as of this branch:
  - `POST /whatsapp/webhook` does **not** verify `X-Hub-Signature-256`
    (`app/routers/whatsapp.py`) — anyone who can reach the URL can post a
    forged Meta payload and trigger a real agent turn (and, without
    `dry_run`, a real outbound WhatsApp send).
  - `POST /whatsapp/simulate` is **not** gated on `APP_ENV` — it is reachable
    in a production deployment exactly as it is in dev. With `dry_run=false`
    it can send an arbitrary WhatsApp message to an arbitrary recipient
    through this project's Meta credentials. **Do not point a real,
    production Meta app at this branch's Fly deploy without first landing
    Phase 5** (`sdd/colsubsidio-lead-profiling-phase5` branch, or task 5.3 in
    `tasks.md`).
  - `GET /health` (`app/routers/health.py`) is a pure liveness probe — it
    returns `200` even when the database is unreachable and schema creation
    failed. The `demo-deployment` spec's readiness scenario (503 naming the
    failed dependency) is **not** satisfied by this branch's `/health`.
  - Meta's retry-on-slow-200 is **not** deduplicated: `external_id` is never
    threaded from `InboundMessageHandler` through `AgentService.send_message`
    into the persisted message row, so
    `MessageRepository.find_by_external_id` never finds a match and a Meta
    retry re-runs the agent and can send a second reply.
- **No HTTP/SSE web channel is mounted.** `AgentService.stream_message` and
  the SSE payload schemas (`app/schemas/chat_schema.py`) exist in code and
  share the channel-agnostic seam, but **no router exposes them** — there is
  no `GET /conversations/{id}/messages/stream` endpoint in this build. If you
  find that route in an older draft of this README, it was aspirational; it
  never existed as a mounted route.
- **No human-in-the-loop approval flow.** `save_lead` writes directly.
- **No auth** on any endpoint.
- **No Alembic** — schema is auto-created; `scripts/reset_db.py --yes` is the
  only destructive path, and it is never invoked automatically.
- **Real Colsubsidio/DataCrédito integration** does not exist — afiliado
  lookups hit a seeded mock table, and a no-afiliado's credit score is a
  deterministic cedula-mod simulation (`app/services/credit_bands.py::simulate_bureau_cedula`),
  labeled "simulado bureau" in every reasoning string it produces.
- **The 6-bucket scoring matrix is this team's own design**, not a
  Colsubsidio-published rubric — it is documented verbatim in
  `openspec/changes/colsubsidio-lead-profiling/design.md` §7.3 and in
  `ARCHITECTURE.md` §4, citing the one number the source brief does name (700
  points as the recommended mortgage-credit threshold).

## Stack

Python 3.12 · FastAPI 0.140 · LangGraph 1.2.9 (custom `StateGraph`, not
`create_react_agent`) · LangChain 1.3 · SQLAlchemy 2.x async · psycopg 3 ·
PostgreSQL 16 · pydantic-settings. Exact pins: `pyproject.toml`; full
transitive graph: `requirements.lock` (a `pip freeze --exclude-editable`
snapshot — the editable self-reference `pip freeze` would otherwise emit for
this very package is stripped, because installing it clones this repo over
SSH at a stale commit and a Docker build has no SSH key).

## Layout

See the `app/` directory; each module has a docstring describing its role.
`ARCHITECTURE.md` covers the graph topology, the normalizer boundary, the
scorer, and the channel-agnostic seam in depth.

## Running locally

```bash
cp .env.example .env
# Edit .env: set OPENAI_API_KEY, and make sure POSTGRES_* matches a Postgres
# you actually have running (the shipped .env.example, app/core/config.py's
# defaults, and docker-compose.yml disagree on the Postgres user/password —
# a known gap tracked as task 6.3, owned by a separate change and not touched
# here; pick one consistently rather than assuming .env.example is correct).
pip install -e .[dev]

# Option A — Postgres via Docker, app run locally:
docker compose up -d db
uvicorn app.main:app --reload &   # the lifespan calls init_db(), which
                                   # creates tables for local dev convenience
python -m scripts.seed_colsubsidio

# Option B — everything via Docker:
docker compose up --build
# then, once the api container is healthy:
docker compose exec api python -m scripts.bootstrap_db
docker compose exec api python -m scripts.seed_colsubsidio
```

The FastAPI lifespan's own `init_db()` call is a **convenience**, not the
migration contract: it swallows `create_all` failures with a warning
(`app/main.py`), so a broken schema can still answer `GET /health` with `200`
today (see "Known limitations"). `scripts/bootstrap_db.py` is the real,
loudly-failing contract; run it explicitly against a fresh database before
`seed_colsubsidio.py`.

## Deploy to Fly.io (not yet run — see "What is explicitly not done yet")

```bash
fly launch --no-deploy --copy-config --name <your-fly-app-name>
fly postgres create --name <your-fly-app-name>-db --region iad
fly postgres attach <your-fly-app-name>-db --app <your-fly-app-name>
fly secrets set \
  OPENAI_API_KEY=sk-... \
  WHATSAPP_API_TOKEN=... \
  WHATSAPP_WEBHOOK_VERIFY_TOKEN=... \
  WHATSAPP_PHONE_NUMBER_ID=... \
  --app <your-fly-app-name>
fly deploy --app <your-fly-app-name>
fly ssh console --app <your-fly-app-name> -C "python -m scripts.bootstrap_db"
fly ssh console --app <your-fly-app-name> -C "python -m scripts.seed_colsubsidio"
```

`fly.toml` sets the US region (`iad`) specifically to avoid the OpenAI 403
geo-block this team hit testing from Venezuela. Read `fly.toml`'s header
comment before running this — it names the Phase 5 gaps that apply verbatim to
a live deploy of this branch.

## Running the tests

```bash
pytest -q
# 279 passed, 3 skipped (the 3 skips are Postgres-integration tests that skip
# cleanly with no reachable database, e.g. tests/test_seed_idempotency.py)
```

```bash
python3 -m compileall app
curl http://localhost:8000/health
```
