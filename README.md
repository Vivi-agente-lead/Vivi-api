# vivi-api

Backend for **Vivi**, a conversational agent that profiles real-estate leads.

This repository is the **initial architecture skeleton** built during a hackathon
(~20h). It is a minimal-but-clean, production-style scaffold of a LangGraph +
FastAPI conversational agent. It is intentionally **not** a finished product.

## What works

- FastAPI app with async SQLAlchemy 2.x + PostgreSQL.
- LangGraph `create_react_agent` with a cached graph per role.
- OpenAI `ChatOpenAI` (direct, no Azure) as the LLM.
- Checkpointer selectable between `MemorySaver` (dev) and `AsyncPostgresSaver` (prod).
- SSE streaming endpoint (`GET /conversations/{id}/messages/stream`).
- Tool registry with `@safe_tool` decorator and `ToolContext` DI via `RunnableConfig`.
- Lead persistence model (`LeadEntity`) and a `save_lead` write tool that executes directly.
- Auto-created schema via `Base.metadata.create_all` at startup (no Alembic).

## What is explicitly NOT done yet (next iterations)

- **No human-in-the-loop (HITL)** approval flow. The `save_lead` tool writes
  directly. See `# TODO: HITL via LangGraph interrupts in next iteration`.
- **No channel adapters.** Only HTTP/SSE is exposed; a WhatsApp webhook router
  is stubbed at `app/routers/webhook.py`.
- **No business intelligence.** Lead tools return placeholder JSON shapes.
  Prompts are persona-only; the rules of business (scoring heuristics,
  qualification gates, budget normalization) will be defined in the next
  iteration.
- **No auth.** Endpoints are unauthenticated for the hackathon.
- **No Alembic.** Schema is auto-created. Replace with Alembic when the lead
  schema stabilizes.

## Stack

Python 3.12 · FastAPI · LangGraph 0.5 · LangChain 0.3 · SQLAlchemy 2.x async ·
psycopg 3 · PostgreSQL 16 · pydantic-settings.

## Layout

See the `app/` directory; each module has a docstring describing its role.

## Running locally

```bash
cp .env.example .env
pip install -e .[dev]
uvicorn app.main:app --reload
# or: docker compose up --build
```

## Verification

```bash
python3 -m compileall app
pytest
curl http://localhost:8000/health
```