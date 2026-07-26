# Pending — parked to resume after the jury delivery

Everything here was found, verified, and deliberately deferred. Nothing on this
list blocks the demo. Ordered by what I would pick up first.

Provenance: `openspec/changes/colsubsidio-lead-profiling/review-ledger.md`
(finding ids in brackets) and `logs/conversation-trace.md`.

---

## 1. Not merged, not pushed

**`feat/whatsapp-interactive`** — 11 files, +675/−22, `327 passed / 3 skipped`.
Local branch inside a worktree; it exists nowhere on the remote, which is why the
work is invisible on GitHub. Adds tactile buttons/lists for nine enumerated
fields, fixes the webhook silently dropping every tap, and keeps a text fallback.

> **Caveat now that v2 has landed**: its largest single piece is the 5-section
> list menu for the 43 cajas de compensación, and v2 deletes that vocabulary
> entirely. Re-scope before merging — see `docs/v2-impact-analysis.md`.

Also unpushed and already merged into `main` by hand: `fix/scorer-critical-defects`,
`sdd/colsubsidio-lead-profiling-phase3`, `phase5`, `phase6`. Three junk branches
`worktree-agent-*` are leftovers from subagents and can be deleted.

## 2. Quick-select buttons never reached the boolean fields

`autorizacion_datos`, `tiene_vivienda_propia`, `tiene_creditos_activos`,
`condicion_discapacidad_familiar`, `subsidio_vivienda_anterior` still render as
plain text: they declare no `FIELD_OPTIONS` entry, so the interactive renderer
skips them.

Five questions per conversation, two options each, three characters per label —
the cheapest tactile win available. One of them is `subsidio_vivienda_anterior`,
the absolute disqualifier, where a tap removes the last place an interpretation
can change the classification.

## 3. The seed contract is verified by nothing

[P12-005] All three tests in `tests/test_seed_idempotency.py` gate on a reachable
Postgres and skip, and the repo has no CI config at all. Drop one dict from
`PROYECTOS_RAW` and `pytest -q` still passes with 43 rows shipping.

A Postgres **is** listening on `localhost:5432` in the dev environment — pointing
the tests at it confirms the 44 rows and that `ABETO` / `LA ARBOLEDA` do not
duplicate on re-seed. `len(PROYECTOS_RAW) == 44` and the sparse/decimal row
mapping are pure functions that need no database at all and should be unit tests.

## 4. Tests that mutate whatever the environment points at

[P12-006] `seed_colsubsidio._run()` executes
`DELETE FROM afiliados_colsubsidio WHERE is_seed=true` **and commits**, three
times per suite run, against `settings.database_url`. No fixture, no isolation,
no rollback. Tolerable with the current workflow (the DB is dropped by hand), but
a developer whose `.env` points at the Fly demo loses rows by running `pytest`.

## 5. Untested invariants

- [P12-001] The terminal-status guard in `LeadRepository.upsert_by_conversation_id`
  has zero tests. Delete the guard and the suite stays green; a `ready` lead can
  then be silently demoted to `profiling`.
- [P12-008] Two documented Estabilidad values are unasserted — mutating
  `termino_indefinido["1_2a"]` to 999 leaves the suite green.
- [P12-019] The constants ↔ normalizer ↔ scorer domain agreement — the cheapest
  guard against the defect class this whole change was audited for — is correct
  today and asserted by nothing.

## 6. Latent correctness

- [P12-011] `find_by_conversation_id` filters `deleted_at IS NULL` but
  `uq_leads_conversation` does not. After a soft delete the next `save_lead`
  takes the INSERT branch and raises `IntegrityError` instead of resurrecting.
- [P12-017] An unrecognised `categoria_afiliado` scores 0 on Bucket 2 but still
  selects the *easier* READY threshold (60 rather than 75).
- [P12-014] Estabilidad, all three red flags and the credit-band selection are
  computed twice in independent copies; changing one is not caught by the other.
- [P12-012] `tests/test_seed_idempotency.py` uses `importlib.util` with only
  `import importlib`. It works today because pytest imports the submodule first.
- [P12-018] `scripts/reset_db.py` drops every table, not the three the spec calls
  "affected", and does not recreate them.

## 7. Interpretation: only the deterministic half was built

`app/graph/nodes/_tolerance.py` resolves money and durations numerically and
covers categorical fields with a synonym table. The LLM fallback — constrained to
pick an existing slug or return `NONE`, never to produce a value — was not built.
An answer outside the synonym table still triggers a re-ask.

## 8. Documentation debt

- [P0-3] `pyproject.toml` and `openspec/config.yaml` both state the pins were
  resolved "against the committed `.venv`". `.venv/` is gitignored and absent, so
  the lockfile cannot be reproduced or regenerated from what is committed.
- [P0-4] `scripts/_verify_langgraph_api.py` verifies
  `add_conditional_edges(src, fn, path_map)`; `design.md` §3 and the shipped
  routers use the two-argument form. The form actually in production was never
  covered by that script (it is covered by `tests/test_router.py`).
- [P0-5] Its `assert END != "END"` compares a constant to a literal and proves
  nothing about routing. Materially closed by `tests/test_router.py`, where
  mutating the sentinel fails 12 tests — the assertion in the script is still
  theatre and should be deleted or replaced.
- [P0-7] `design.md:112` still says the pin "MUST" be added and the API "is to be
  re-verified as the first task of the apply phase". Both are done.
- [P0-8] `requirements.lock` records no interpreter. It was built on Python 3.14
  while the Dockerfile is `python:3.12-slim`.

## 9. Owner-only

- **6.2** Fly.io deploy — needs the Fly account. `fly.toml` and the commands are
  in the README.
- **6.6** Demo rehearsal against the deployed URL and a live Meta sandbox.

## 10. v2 migration — Blocks B and C

Block A landed (`feat/v2-graph-topology`): the qualification flow is v2-correct and
the suite was green at 325 passed / 3 skipped.

**Block B — entry inversion and the catalogue loop. DONE** (`feat/v2-blocks-bc`).
`app/graph/nodes/browsing.py` adds `menu_proyecto` (catalogue-first welcome,
sourced from a real `proyectos_colsubsidio` row via `get_projects`, never
hardcoded), `salir_menu`, `elegir_preferencia_vis`, `elegir_municipio_catalogo`
and `mostrar_catalogo` (the back-navigation loop). `lugar_eleccion_vivir` and
`preferencia_vis` move to the front for a lead who browses the catalogue;
`recoger_intencion`'s existing "already answered" skip means neither is asked
twice. `get_projects` is no longer READY/Calificado-only —
`specs/agent-tools/spec.md`'s scenario was amended (not contradicted) to
narrow the MUST to "`handoff` itself must not call it for a non-Calificado
lead". New router predicates `_route_menu` / `_route_volver_menu`
(`app/graph/router.py`) hold the stateful menu + back-navigation, entirely in
the graph — no WhatsApp/Meta reference. Suite: 344 passed / 3 skipped.

**Block C — two capabilities with no code behind them.**
`¿Te conecto con un asesor de crédito?` (a second hand-off, distinct from the
asesor comercial one) and `Enviar notificación por correo` (no mail transport
exists in the project; a logged no-op behind a clean seam is the honest first
step — do not fake a send).

## 11. Housekeeping

`.atl/` is untracked (agent tooling cache — gitignore it or commit it, but decide).
