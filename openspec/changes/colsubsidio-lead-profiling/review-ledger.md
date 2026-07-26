# Review Ledger — colsubsidio-lead-profiling

Audit of the OpenSpec artifacts (`proposal.md`, `design.md`, 7 spec deltas) against
the actual codebase and against the two source-of-truth documents in `docs/`.

- **Date**: 2026-07-26
- **Scope**: `openspec/changes/colsubsidio-lead-profiling/**`, `openspec/config.yaml`, `app/**`, `README.md`, `pyproject.toml`, `docs/**`
- **Change status**: `proposed` — spec + design written, `tasks.md` absent, zero implementation
- **Repo state**: `main` @ `15392c6`, clean
- **Method**: every claim below was verified against a file or against the source
  spreadsheet/flow diagram. Reproduction steps are in [Appendix A](#appendix-a--verification-method).
  Unverifiable claims are explicitly marked `UNVERIFIED`.

---

## 1. Summary

| Severity | Count |
|---|---|
| BLOCKER | 6 |
| CRITICAL | 12 |
| WARNING | 14 |
| SUGGESTION | 3 |

The headline result is not the volume — it is **where** the defects are. The design
states in §1 that "the graph node list maps one-to-one onto the Colsubsidio flow
JSON". It does not. Eleven nodes present in the flow diagram have no counterpart in
the design, and the field domains the design hardcodes (`empleado`/`independiente`,
`<1SMMLV`…`>4SMMLV`, `3_meses`…`no_se`) do not match a single option offered by the
source spreadsheet. Because the scorer keys off those exact string literals, four of
its six buckets would silently collapse to their default branch in production.

The second structural problem: the design repeatedly *resolves* spec defects in prose
instead of amending the spec (see `SDD-004`, `SDD-003`). Verify reads the spec. Apply
reads the design. They will disagree.

---

## 2. Findings ledger

| id | lens | location | severity | status | evidence |
|---|---|---|---|---|---|
| SDD-001 | reliability | `openspec/changes/colsubsidio-lead-profiling/` | BLOCKER | open | `tasks.md` absent; SDD chain broken before apply |
| SDD-002 | reliability | `app/**` | BLOCKER | open | Zero implementation; every spec delta describes code that does not exist |
| SDD-003 | reliability | `specs/seed-and-bootstrap/spec.md` ↔ `design.md:570` | BLOCKER | open | Spec MUSTs `scripts/bootstrap_db.py`; design says "no separate bootstrap script" |
| SDD-004 | reliability | `specs/lead-data-model/spec.md:47` ↔ `specs/lead-scoring/spec.md:14` | BLOCKER | open | `score_rating` derived from `score` (0–100) via 150–950 bands — impossible |
| DATA-001 | reliability | `design.md:164` ↔ `docs/…xlsx` Leads!N5:N7 | BLOCKER | open | `empleado_o_independiente` domain is `Termino fijo/indefinido/Prestacion de servicios`, never `"empleado"` → all leads route to `ind_*` bundle |
| LOGIC-001 | reliability | `design.md:181` ↔ `docs/Flujo….json` | BLOCKER | open | `subsidio_vivienda_anterior` never collected for `soltero` → the absolute disqualifier never fires for single leads |
| DATA-002 | reliability | `design.md:405` ↔ `docs/…xlsx` Leads!Q5:Q9 | CRITICAL | open | `rango_salarial` domain is pesos (5 buckets), design uses SMMLV (4) → Bucket 3 always defaults to 10/20 |
| DATA-003 | reliability | `design.md:408-414` ↔ `docs/…xlsx` Leads!Z5:Z10 | CRITICAL | open | Ahorro substring match: 15-pt tier unreachable; `"Menos de $3 millones"` scores 0 because `"menos"` contains `"no"` |
| DATA-004 | reliability | `design.md:422-427` ↔ `docs/…xlsx` Leads!U5:U7 | CRITICAL | open | `antiguedad_laboral` domain is `Menos de 1 año/1 a 2 años/Mas de dos años`, design uses `<1y/1-3y/>3y` |
| DATA-005 | reliability | `design.md:417` ↔ `docs/…xlsx` Leads!AI5:AI9 | CRITICAL | open | `tiempo_compra_deseado` source has 5 options incl. `2 años`; design has 4 → silent 0 pts |
| DATA-006 | reliability | `specs/agent-tools/spec.md:44` ↔ `docs/…xlsx` | CRITICAL | open | `get_projects(municipio='Bogotá')` returns 0 rows: source municipio is `Bogota` (unaccented) |
| DATA-007 | reliability | `specs/seed-and-bootstrap/spec.md:16` ↔ `docs/…xlsx` Proyectos | CRITICAL | open | Sheet has **44** data rows, not 43 (asserted 4× across spec + design) |
| DATA-008 | reliability | `design.md:340` ↔ `docs/…xlsx` Proyectos | CRITICAL | open | `ON CONFLICT (proyecto, modelo)` cannot dedupe `ABETO`/`LA ARBOLEDA` — `modelo` is NULL |
| LOGIC-002 | reliability | `design.md:141,149` | CRITICAL | open | Router predicates return the literal string `"END"`; the LangGraph sentinel is `END` (`"__end__"`) |
| LOGIC-003 | reliability | `design.md:178-179` ↔ `docs/Flujo….json` | CRITICAL | open | No underage gate on the afiliado path; flow diagram has `Consultar edad en BD → ¿Es mayor de edad?` |
| LOGIC-004 | reliability | `design.md:159` | CRITICAL | open | `soltero + afiliado` skips both PAC nodes → `numero_pac`/`condicion_discapacidad_familiar` never collected, +8 bonus unreachable |
| CODE-001 | reliability | `app/services/inbound_handler.py:58` | CRITICAL | open | Wamid idempotency is dead code — `external_id` is never persisted |
| SEC-001 | risk | `app/routers/whatsapp.py:107` | CRITICAL | open | `POST /whatsapp/simulate` has no env gate; with `dry_run=false` it is an open outbound-WhatsApp relay |
| SEC-002 | risk | `app/routers/whatsapp.py:84` | CRITICAL | open | No `X-Hub-Signature-256` verification on the webhook |
| SDD-005 | reliability | `openspec/config.yaml:6-13` ↔ `pyproject.toml:13-33` | CRITICAL | open | Declared versions contradict the manifest; the langgraph pin cited as a risk mitigation does not exist |
| DOC-001 | readability | `design.md:493-529` | CRITICAL | open | Persona/slice prompt text contaminated with German + Portuguese + broken Spanish |
| SDD-006 | reliability | `design.md:5` ↔ `docs/Flujo….json` | CRITICAL | open | "maps one-to-one onto the flow JSON" is false — 11 flow nodes have no design counterpart |
| SDD-007 | reliability | `docs/Reto_de_vivienda_Descripcion.md:41` | CRITICAL | open | The brief's non-negotiable **90/10 rule** appears in no artifact; the scorer actively works against it |
| DOC-002 | readability | `README.md:14-25` | CRITICAL | open | Claims an SSE endpoint that does not exist; claims WhatsApp is "stubbed" when it is the only channel built |
| DATA-009 | reliability | `docs/…xlsx` Leads!C5:C10 | WARNING | open | `tipo_documento` domain is 5 values incl. PEP/PPT; design validator is `(CC\|CE\|TI)` — `TI` is not in the source |
| DATA-010 | reliability | `docs/…xlsx` Leads!L5:L10 | WARNING | open | `estado_civil` has 6 values (adds Divorciado/Separado/Viudo); design handles 3 |
| DATA-011 | reliability | `docs/…xlsx` Proyectos | WARNING | open | Areas use comma decimals (`56,29`); no parsing strategy specified for `Numeric(10,2)` |
| DATA-012 | reliability | `docs/…xlsx` Afiliados Colsubsidio | WARNING | open | Sheet has **0** data rows — all 15 afiliados are invented; spec's distribution requirement is unconstrained |
| DATA-013 | reliability | `docs/…xlsx` Leads!AM5:AM38 | WARNING | open | `Caja de Compensación` is an enumerated list of 30+; design models it as free-text `String(150)` |
| LOGIC-005 | reliability | `design.md:424` | WARNING | open | `min(est_pts, 15)` makes the `+3` empleado bonus dead code for `>3y` |
| LOGIC-006 | reliability | `specs/agent-tools/spec.md:52` ↔ `specs/lead-scoring/spec.md:44` | WARNING | open | `classification` domain contradiction: `{ready,nurture}` vs `{ready,nurture,nurture_social}` |
| LOGIC-007 | reliability | `design.md:184-187` ↔ `docs/…xlsx` Leads!P2 | WARNING | open | Source says ask `rango_salarial` only if empleado AND not afiliado; design asks in all 4 bundles |
| LOGIC-008 | reliability | `specs/lead-data-model/spec.md:38` | WARNING | open | "no terminal→profiling transition" has no named enforcement point in the design |
| RES-001 | resilience | `design.md:582` + `.env.example:1` + `docker-compose.yml:22` | WARNING | open | `DROP TABLE leads CASCADE` gated on `app_env=="development"`, which is the shipped default everywhere |
| RES-002 | resilience | `app/main.py:38` | WARNING | open | `init_db()` failure is swallowed; `/health` returns 200 with no tables, satisfying the demo spec while broken |
| RES-003 | resilience | `design.md:590` ↔ `pyproject.toml:40` | WARNING | open | Smoke tests live in `scripts/tests/`, outside `testpaths=["tests"]` — verify's `pytest -q` never runs them |
| RES-004 | resilience | `Dockerfile:17-18` | WARNING | open | Image copies only `pyproject.toml`, `README.md`, `app/` — `scripts/` and `docs/` are absent, so the seed cannot run on Fly |
| CODE-002 | readability | `app/core/config.py:56-57` | WARNING | open | `whatsapp_api_version` declared twice |
| SDD-008 | reliability | `design.md:71,303,480` | WARNING | open | Locked decisions cite "Engram #258" — unauditable from the repo alone |
| SDD-009 | reliability | `design.md:633` | SUGGESTION | open | Open question (full proyecto column list) still unchecked; blocks the table definition |
| DOC-003 | readability | `.env.example` / `app/core/config.py` / `docker-compose.yml` | SUGGESTION | open | Three different Postgres credential sets |
| SDD-010 | reliability | `openspec/config.yaml:3` | SUGGESTION | open | `artifact_store: both` but no in-repo Engram trace |

---

## 3. Blockers

### SDD-001 — `tasks.md` is missing

`openspec/changes/colsubsidio-lead-profiling/` contains `proposal.md`, `design.md`
and `specs/*/spec.md` (7 files). There is no `tasks.md`. The SDD chain is
`proposal → spec → design → **(gap)** → apply`.

The design itself depends on it. `design.md:623`:

> Ship smallest end-to-end machine first (`autorizacion_datos → pedir_cedula →
> afiliado_check → handoff`) before adding the 4 capacity bundles (**tasks phase must
> sequence this**).

and `design.md:354`:

> the full proyecto column list is finalized at the tasks/apply phase

Nothing is implementable until this exists.

### SDD-002 — Zero implementation

Every spec delta describes code that is not present. Verified file by file:

| Spec requires | Actual code |
|---|---|
| Custom `StateGraph`, 16 nodes | `create_react_agent` — `app/graph/builder.py:33` |
| `lead_profile` first-class state field | `lead_profile_draft`, "unused in this iteration" — `app/graph/state.py:21` |
| Colsubsidio `leads` schema (27 columns) | `LeadEntity` with `name/phone/email/budget_min/budget_max/preferred_locations` — `app/models/lead_model.py:34-47` |
| 5 tools: `lookup_afiliado`, `save_lead`, `get_lead`, `get_projects`, `classify_lead` | 4 stubs: `search_leads`, `get_lead`, `save_lead`, `score_lead` — `app/tools/tool_registry.py:17` |
| Deterministic scorer | `score_lead` returns `{"score": None, "note": "scoring heuristic not yet defined"}` — `app/tools/lead_tools.py:143` |
| `afiliados_colsubsidio`, `proyectos_colsubsidio` | do not exist |
| `app/services/lead_scorer.py`, `credit_bands.py`, `lead_state_rebuilder.py` | do not exist |
| `app/graph/nodes/`, `app/graph/router.py`, `app/prompts/slices.py` | do not exist |
| `scripts/seed_colsubsidio.py`, `scripts/bootstrap_db.py` | `scripts/` does not exist |
| `fly.toml` | does not exist |

`openspec/specs/` is empty — nothing has been archived. This is expected for a change
at `proposed`, but it sets the scale: 632 lines of design against a 3,266-line
skeleton with 4 smoke tests.

### SDD-003 — Spec and design contradict each other on bootstrap

`specs/seed-and-bootstrap/spec.md` opens with a MUST:

> The system MUST provide `scripts/bootstrap_db.py` (runnable as
> `python -m scripts.bootstrap_db`) that recreates the schema idempotently

and a scenario `bootstrap then seed runs in order` asserting
`python -m scripts.bootstrap_db && python -m scripts.seed_colsubsidio` exits 0.

`design.md:570` opens §10 with the opposite:

> **TL;DR — `init_db` runs in the FastAPI lifespan (`app/main.py`) via
> `Base.metadata.create_all(checkfirst=True)`; no separate bootstrap script.**

Apply will implement one. Verify will test the other.

### SDD-004 — `score_rating` is mathematically impossible as specified

`specs/lead-data-model/spec.md`, scenario *Score rating band labels*:

> THEN it MUST be one of the literal labels {Malo, Regular, Aceptable, Bueno, Muy
> Bueno, Excelente} AND it MUST be derived from **the lead's `score` band** per the
> credit-band mapping (150-499 Malo · 500-649 Regular · … · 800-950 Excelente).

`specs/lead-scoring/spec.md`, scenario *Score range invariant*:

> THEN the returned `score` is an integer in the closed interval **[0, 100]**

A value in `[0,100]` never falls in `[150,950]`. Every lead would be unmapped.

The design detects this and patches it in prose (`design.md:303`):

> This resolves an ambiguity in spec scenario "Score rating band labels" (which lists
> the credit-band ranges 150-950 that bind to `score_credito`, not to the 0-100 `score`).

That is the right resolution and the wrong mechanism. The spec still ships the broken
statement. **Fix: amend `lead-data-model/spec.md` to bind the band to `score_credito`.**

### DATA-001 — `empleado_o_independiente` never matches the source domain

`design.md:164`, the capacity router:

```python
bundle = f"cap_{'emp' if p.get('empleado_o_independiente') == 'empleado' else 'ind'}_"
```

The source spreadsheet's option list for that field (Leads sheet, column N, the
`Columna5` slot adjacent to `Empleado o independiente`) is:

```
Termino fijo · Termino indefinido · Prestacion de servicios
```

There is no `"empleado"` value. The equality test can never be true, so **every lead
routes to `cap_ind_*`**, and Bucket 6 (Estabilidad) always returns the independiente
neutral `7` — `antiguedad_laboral` is collected by no bundle and contributes nothing.

Note the flow diagram asks the question in the same terms as the sheet
(`¿Cuentas con contrato de trabajo o eres independiente?`), so the mismatch is in the
design's assumed *answer* vocabulary, not in the question.

**Fix:** either normalize the three contract types into a two-value enum in a
validator, or key the router off the contract type directly.

### LOGIC-001 — the absolute disqualifier never fires for `soltero` leads

`subsidio_vivienda_anterior=True` forcing `status='nurture'` is the single
user-locked business rule of this change (`proposal.md` §4, `design.md:480`, and its
own spec scenario in both `lead-scoring` and `leads-conversational-flow`).

Per `design.md:181-188`, the field is written by exactly one node:

| Node | Applies to | Writes `subsidio_vivienda_anterior`? |
|---|---|---|
| `recoger_subsidio_pareja` | casado / union_libre | **yes** |
| `recoger_otra_caja_y_pac` | soltero + no-afiliado | no |
| `cap_*` bundles (×4) | all | no |
| `recoger_intencion` | all | no |

A `soltero` lead — of either affiliation — never has the field collected. It stays
`None`, `lead.get("subsidio_vivienda_anterior") is True` evaluates `False`, and the
override is skipped.

The two source documents disagree here, which is how it slipped through:

- The **spreadsheet** (Leads sheet, `Condicion` row) says `Preguntar si es casado o UL`.
- The **flow diagram** asks it in all four capacity bundles, including both soltero
  paths: `¿Has recibido anteriormente un subsidio de vivienda?`

The design followed the spreadsheet silently. The result is that the headline rule has
a hole covering every single applicant. **This needs a decision recorded, not an
implicit pick.**

---

## 4. Critical

### DATA-002 · DATA-003 · DATA-004 · DATA-005 — the scorer's string keys do not match the source domains

`design.md` §7 keys four buckets off exact string literals. None of the four
vocabularies exists in the source spreadsheet.

| Bucket | Design keys | Source options (Leads sheet) | Effect |
|---|---|---|---|
| 3 · Ingreso (20) | `>4SMMLV`, `2-4SMMLV`, `1-2SMMLV`, `<1SMMLV` | `2 millones o menos` · `2 a 4 millones` · `4 a 8 millones` · `8 a 10 millones` · `mas de 10 millones` | always default `10` |
| 4 · Ahorro (15) | substring `≥10` / `>=10` / `10%` | `No tengo ahorros.` · `Menos de $3 millones` · `Entre $3 y $10 millones` · `Entre $10 y $20 millones` · `Entre $20 y $40 millones` · `Más de $40 millones` | 15-pt tier **unreachable** |
| 5 · Tiempo (10) | `3_meses`, `6_meses`, `1_ano`, `no_se` | `3 meses` · `6 meses` · `1 año` · `2 años` · `No sé` | always `0` |
| 6 · Estabilidad (15) | `>3y`, `1-3y`, `<1y` | `Menos de 1 año` · `1 a 2 años` · `Mas de dos años` | always default |

Different units (SMMLV vs pesos), different bucket boundaries (3 years vs 2 years),
different cardinality (4 vs 5, 4 vs 5). A change whose stated purpose is that "the
score be a pure function of the inputs, not a function of LLM mood" (`design.md:5`)
currently makes the score a function of whether the LLM happens to reformat the user's
answer into a vocabulary that appears nowhere in the domain.

**DATA-003 deserves separate attention** — it is a live bug, not just a mismatch:

```python
ahorro = (lead.get("ahorros_o_cesantias") or "").lower()
if "≥10" in ahorro or ">=10" in ahorro or "10%" in ahorro:
    ahorro_pts = 15
elif ahorro and "no" not in ahorro:
    ahorro_pts = 8
else:
    ahorro_pts = 0
```

Applied to the six real options:

| Option | lowercased contains `"no"`? | Points |
|---|---|---|
| `No tengo ahorros.` | yes (`no`) | 0 ✓ intended |
| `Menos de $3 millones` | **yes — `me`·`no`·`s`** | **0** ✗ |
| `Entre $3 y $10 millones` | no | 8 |
| `Entre $10 y $20 millones` | no | 8 |
| `Entre $20 y $40 millones` | no | 8 |
| `Más de $40 millones` | no | 8 |

The `"menos"` substring collision silently zeroes a legitimate saver, and no input can
ever reach 15. Bucket 4 is effectively a binary 0-or-8.

### DATA-006 — `get_projects` returns nothing for Bogotá

`specs/agent-tools/spec.md`, scenario *get_projects filtered for READY recommendation*:

> GIVEN a READY-classified lead with `lugar_eleccion_vivir='Bogotá'` and the
> `proyectos_colsubsidio` table has rows where `municipio='Bogotá'`

Verified against the source. The Proyectos sheet's distinct `Municipio` values are:

```
Bogota · Chía · Girardot · Ricaurte · Soacha · Tocancipá · Ubate · VIS
```

`Bogota` and `Ubate` are **unaccented**. The Leads sheet's option list for
`Lugar de elección para vivir` is:

```
Bogotá norte · Bogotá centro · Bogotásur · Soacha · Chía · Tocancipá · Girardot · Ricaurte · Ubaté
```

Cross-referencing the two lists:

| Lead option | Matches a `municipio`? |
|---|---|
| `Bogotá norte` | **no** |
| `Bogotá centro` | **no** |
| `Bogotásur` (sic — no space) | **no** |
| `Ubaté` | **no** (source has `Ubate`) |
| Soacha · Chía · Tocancipá · Girardot · Ricaurte | yes |

Four of nine options — including all three Bogotá variants — join to zero rows. Two
consequences beyond the empty recommendation:

1. The READY handoff for a Bogotá lead shows no projects, which is the juror-facing
   moment.
2. `vis_recommended` stays `False`, so the **−15 VIS red flag never applies** to those
   leads (`design.md:481`).

**Fix:** the sheet's municipio values are a *catalog*, the lead options are a
*sub-municipal preference*. They need an explicit normalization/mapping table, not an
equality join.

### DATA-007 — the spreadsheet has 44 proyectos, not 43

The count `43` is asserted four times: `proposal.md` §2 and §7,
`specs/seed-and-bootstrap/spec.md` (as a MUST and as an assertion
`SELECT count(*) … returns 43`), `specs/lead-data-model/spec.md`, and
`design.md:9`, `:334`, `:617`.

Verified: the `Proyectos` sheet has 45 rows — 1 header + **44** data rows, all
non-empty. See [Appendix A](#appendix-a--verification-method).

The other three source-quirk claims in the same spec **do hold**:

| Claim | Verdict | Evidence |
|---|---|---|
| A row where `area_privada_m2 > area_construida_m2` | ✅ exactly one | `VERSALLES` modelo `E` — construida `56,29`, privada `60,6` |
| `VIBO ONCE` row with `tipo == municipio == 'VIS'` | ✅ (1 of its 2 rows) | modelo `B2` is `(VIS, VIS)`; modelo `A` is `(VIS, Bogota)` |
| Sparse `ABETO` row with NULLs | ✅ | empty `Dirección`, `Modelo`, `area_privada_m2` |

`LA ARBOLEDA` is **sparser than `ABETO`** (empty `Modelo`, `area_privada_m2`,
`cantidad_habitaciones`, `cantidad_baños`) and is named in no artifact.
`LOS NOGALES` has an empty `Valor viviendas VIS en SMMLV`.

### DATA-008 — the idempotent re-seed cannot dedupe two rows

`design.md:340` and the seed spec rely on:

```python
UniqueConstraint("proyecto", "modelo", name="uq_proyecto_modelo")  # idempotent re-seed
```
> proyectos use an ON CONFLICT-by-composite-key … so the table still holds exactly 43
> rows, not 86

`ABETO` and `LA ARBOLEDA` have an empty `Modelo`. `specs/lead-data-model/spec.md`
explicitly requires those to be stored as NULL ("the sparse `ABETO` row (with NULLs on
sparse columns)"). In PostgreSQL, **NULL values never conflict in a UNIQUE
constraint**, and `ON CONFLICT (proyecto, modelo)` will not match them.

Running the seed twice yields 46 rows, not 44. Two scenarios in the same spec file
contradict each other: *Proyectos table preserves source quirks* (NULLs) versus
*Re-running the seed is idempotent* (requires non-NULL keys).

**Fix:** store `modelo` as `''` with a `NOT NULL DEFAULT ''`, or add a surrogate
natural key, or use `DELETE`-then-`INSERT` for proyectos as the afiliados path already
does.

### LOGIC-002 — router predicates return the wrong END sentinel

`design.md:85-87` correctly states:

> `START` and `END` are sentinel constants imported from `langgraph.graph`.

`design.md:141` and `:149` then return the *string literal*:

```python
def _route_autorizacion(state) -> str:
    return "pedir_cedula" if state["lead_profile"].get("autorizacion_datos") else "END"

def _route_edad(state) -> str:
    return "END" if state["lead_profile"].get("edad", 0) < 18 else "recoger_estado_civil"
```

`END` is `"__end__"`, not `"END"`. Returning `"END"` resolves to a node that was never
added. Both terminal paths of the graph — the consent opt-out and the underage gate —
are the ones affected, and both are spec'd scenarios.

### LOGIC-003 — no underage gate on the afiliado path

The flow diagram has **two** `¿Es mayor de edad?` decision nodes:

- no-afiliado: `¿Cual es tu fecha de nacimiento? → ¿Es mayor de edad? → FIN / Mensaje cordial de despedida`
- afiliado: `Consultar edad en BD → ¿Es mayor de edad? → FIN / Mensaje cordial de despedida`

The design has one. `_route_edad` is attached only to `recoger_identidad`
(`design.md:179`), which per its own table is "no-afiliado only". `_route_afiliado`
sends afiliados straight to `recoger_estado_civil` with no age check, even though
`afiliado_check` derives `edad` from the afiliado record and could gate on it.

The spec scenario *Menor de edad ends conversation without lead* only covers the
no-afiliado case, so verify would not catch this either.

### LOGIC-004 — `soltero` + afiliado skips both PAC-collecting nodes

`design.md:156-159`:

```python
if ec in ("casado", "union_libre"):
    return "recoger_subsidio_pareja"
if ec == "soltero" and not p.get("afiliado_colsubsidio"):
    return "recoger_otra_caja_y_pac"
return "recoger_empleo"  # soltero + afiliado → straight to empleo
```

`numero_pac` and `condicion_discapacidad_familiar` are written only by
`recoger_subsidio_pareja` and `recoger_otra_caja_y_pac`. A `soltero` afiliado reaches
neither, so both stay unset and the `+8` bonus
(`condicion_discapacidad_familiar OR numero_pac > 0`) is unreachable for that
population.

This also breaks `specs/leads-conversational-flow/spec.md` scenario
*cabeza_de_hogar auto-derivation*, which requires `cabeza_de_hogar=true` for every
`soltero`: the derivation is documented as running "at end of whichever node last
writes `numero_pac`/`estado_civil`" (`design.md:205`), and for this branch that node
does not execute.

The flow diagram asks `¿Cuantas personas tienes a cargo?` and
`¿algún miembro de tu hogar se encuentra en situacion de discapacidad?` in **all four**
capacity bundles — i.e. for everyone. Moving both fields into the bundles resolves
LOGIC-004 and LOGIC-001 together.

### CODE-001 — Wamid idempotency is dead code *(confirmed bug in shipped code)*

`app/services/inbound_handler.py:58`:

```python
existing = await self.message_repo.find_by_external_id(external_id)
if existing is not None:
    logger.info("inbound.duplicate", extra={"external_id": external_id})
    return
```

The write path never populates that column. `MessageService.persist_user_message`
accepts it as a keyword-only argument defaulting to `None`
(`app/services/message_service.py:31-37`), but the only caller is
`app/services/agent_service.py:66`:

```python
await self.message_service.persist_user_message(conv.id, content)
```

No `external_id`. `MessageEntity.external_id` is therefore always NULL, the lookup
always returns `None`, and the guard never fires. Meta retries on slow 200s re-run the
full agent turn and send a second reply.

This directly violates `specs/whatsapp-channel-pipeline/spec.md` scenario
*Wamid idempotency* ("the system MUST NOT invoke `AgentService.send_message` a second
time").

**Fix:** thread `external_id` from `InboundMessageHandler.handle` through
`AgentService.send_message` into `persist_user_message`. The column already has
`unique=True` (`app/models/message_model.py:23`), so it will also enforce at the DB
level once populated.

### SEC-001 — `/whatsapp/simulate` is an unauthenticated outbound relay

`app/routers/whatsapp.py:107-126` exposes `POST /whatsapp/simulate` with no
authentication and no environment gate. Its `from` query parameter is the destination
phone number, and `dry_run` defaults to `True` but is caller-controlled:

```
POST /whatsapp/simulate?text=<arbitrary>&from=<any number>&dry_run=false
```

sends an arbitrary WhatsApp message to an arbitrary recipient through the project's
Meta credentials. `specs/demo-deployment/spec.md` requires this app to be deployed at a
public HTTPS URL. Neither the spec nor the design mentions gating the endpoint.

Mitigating factor: `specs/whatsapp-channel-pipeline/spec.md` notes the demo only
reaches Meta sandbox-approved recipients, which limits blast radius during the
hackathon but not after.

**Fix:** gate registration on `settings.app_env == "development"`, or require a shared
secret header.

### SEC-002 — no webhook signature verification

`app/routers/whatsapp.py:7-8` states it plainly:

> Verify-token guards the GET; signature verification is a TODO (Meta signs the
> `X-Hub-Signature-256` header). For hackathon, token check suffices.

`POST /whatsapp/webhook` accepts any JSON body from any source. On a public Fly URL
that is unauthenticated conversation injection and unmetered OpenAI spend. Note the
verify token only protects the `GET` handshake — it is not checked on `POST`.

### SDD-005 — declared versions contradict the manifest, and the cited pin does not exist

`openspec/config.yaml:6-13` declares a precise stack:

> Stack: Python 3.12, FastAPI 0.140, langchain 1.3.14, langgraph 1.2.9,
> langchain-openai 1.4.1, SQLAlchemy 2.0.51 async (psycopg 3.3.4), pydantic v2 +
> pydantic-settings, sse-starlette 3.4.6, langgraph-checkpoint-postgres 3.1.0.
> Tests: pytest 9.1.1 + pytest-asyncio 1.4.0

`pyproject.toml:13-33` declares open lower bounds:

| Package | config.yaml | pyproject.toml |
|---|---|---|
| fastapi | 0.140 | `>=0.115` |
| langchain | 1.3.14 | `>=0.3` |
| **langgraph** | **1.2.9** | **`>=0.5`** |
| langchain-openai | 1.4.1 | `>=0.2` |
| sqlalchemy | 2.0.51 | `>=2.0` |
| psycopg | 3.3.4 | `>=3.2` |
| sse-starlette | 3.4.6 | `>=2.1` |
| langgraph-checkpoint-postgres | 3.1.0 | `>=2.0` |
| pytest | 9.1.1 | `>=8.3` |
| pytest-asyncio | 1.4.0 | `>=0.24` |

`UNVERIFIED`: whether those exact versions exist upstream could not be checked — there
is no `.venv`, no lockfile, and no network access during this audit. What *is* verified
is that the manifest does not pin them.

This matters because `design.md:623` lists the pin as the mitigation for the change's
top-ranked technical risk:

> **LangGraph 1.x API drift in conditional edges** … Mitigation: **Pin langgraph
> 1.2.9**

That pin does not exist. `langgraph>=0.5` spans a major-version boundary, so a fresh
`pip install -e .` resolves to whatever is current. And `design.md:83` concedes the API
surface was never checked:

> introspection not runnable here because the env has no langgraph install, so
> signatures are taken from the package's public 1.x docs

So the top technical risk is mitigated by a pin that isn't there, against an API that
wasn't verified. `LOGIC-002` is one instance of what that produces.

Separately, `UNVERIFIED` and worth checking before apply: whether
`langgraph.prebuilt.create_react_agent` — used at `app/graph/builder.py:27` — is still
available under the intended major version. This change deletes that call path anyway,
but the existing code's ability to boot depends on it.

**Fix:** create a lockfile, pin the manifest to whatever actually resolves, and record
the real installed versions in `config.yaml`.

### DOC-001 — prompt text is contaminated across four languages

`design.md` §8 supplies the persona preamble and an example slice that
`design.md:557` schedules for verbatim copy into `app/prompts/slices.py`.

Shared preamble (`design.md:493-499`):

> con calidez humana, paso a paso, sin tecnicismos. Hago una pregunta a la vez,
> escucho tu respuesta, y **laconfirmation** antes de avanzar.

Example slice `recoger_estado_civil` (`design.md:513-529`):

> - No **pregunts** nombre ni apellido (ya tengo: {nombre_apellido}).
> - No **pregunts** otra caja, subsidio previo, PAC o discapacidad (van en otro paso).
> - No **pregunts** empleo, ingresos, vivienda propia, **Gespräch** de compra.
> …
> Si la persona corrige, **atualizá**.
> …
> Si ya tengo {estado_civil_known}, **confirmationá**: …

- `laconfirmation`, `confirmationá` — English token spliced into Spanish
- `pregunts` ×3 — should be `preguntés`
- `Gespräch` — German (should be `tiempo`/`intención`)
- `atualizá` — Portuguese (should be `actualizá`)

`design.md:488` also mentions "Each node's **Happy** prompt", which reads as another
stray token.

This is the persona the juror sees. It is also 14 slices' worth of text that the same
generation pass produced, so the two shown here are a sample, not the full extent.

### SDD-006 — "maps one-to-one onto the flow JSON" is false

`design.md:5-7`:

> The graph node list maps one-to-one onto the Colsubsidio flow JSON:
> `autorizacion_datos → pedir_cedula → afiliado_check → …`

Extracted all 61 labelled cells from `docs/Flujo asesor de venta de vivienda
Colsubsidio.json`. Flow nodes with **no design counterpart**:

| Flow node | Design |
|---|---|
| `QUIERO COMPRAR` / `QUIERO ASESORIA` (two entry intents) | absent — single entry |
| `¿Ya sabes en cual proyecto de vivienda estas interesado?` | absent |
| `¿Cuál de los siguientes proyectos te interesa?` | absent |
| `Mostrar una descripción del proyecto seleccionado` | absent |
| `¿Te interesaría revisar tus opciones de compra con un asesor?` | absent |
| `¡Genial! Aquí empieza el camino…` (greeting) | partially — `start` node |
| `Tenemos proyectos disponibles en los siguientes municipios, ¿Dónde te gustaría vivir?` | **misplaced** — design puts it last, in `recoger_intencion` |
| `Selecciona una de las ubicaciones disponibles` | absent |
| `Setear variable pos_subsidio = 0` | absent — no such state field |
| `Consultar edad en BD → ¿Es mayor de edad?` (afiliado branch) | absent — see LOGIC-003 |
| `Mensaje: Ya voy conociendote mejor, vamos con unas preguntas mas` | absent |

The ordering difference matters beyond completeness: the flow collects the municipio
**early**, before the afiliado check. The design collects it **last**, in
`recoger_intencion` immediately before `scoring`. Since `vis_recommended` (and the −15
red flag) depends on it, the design's ordering is defensible — but it is a deviation,
and deviations from the cited source should be recorded as decisions.

What the design **does** get right, verified: the four capacity bundles map exactly
onto `Es empleado y casado o en union libre` / `Es empleado y soltero` /
`Es independiente y casado o UL` / `Es independiente y soltero`, and only the empleado
bundles ask antigüedad. The credit-band table in `design.md:365-369` matches the
spreadsheet legend **exactly** (150-499 Malo · 500-649 Regular · 650-699 Aceptable ·
700-749 Bueno · 750-799 Muy Bueno · 800-950 Excelente).

### SDD-007 — the brief's 90/10 rule appears in no artifact

`docs/Reto_de_vivienda_Descripcion.md`, under *Cómo se ve un buen resultado*:

> Distingue quién es afiliado y quién no desde el inicio. **Regla del 90/10: 90% de
> los leads calificados deben ser afiliados.**

and under *Lo NO Negociable*:

> Distingue afiliados desde el inicio

Searched `proposal.md`, `design.md`, and all 7 spec deltas: the 90/10 rule appears
nowhere. Worse, the scorer works against it (`design.md:396-401`):

```python
if afiliado:
    cat_pts = {"A": 15, "B": 10, "C": 5}.get(cat, 0)
else:
    cat_pts = 8     # no-afiliado neutral
```

A **no-afiliado scores 8, a categoria C afiliado scores 5**. All else equal, the
non-affiliate is ranked above the affiliate — the inverse of the stated rule. Nothing
anywhere caps the affiliate share of READY leads.

Two further brief requirements with no artifact coverage:

- *"Sea capaz de brindar asesoría"* (one of three stated objectives) — the design's
  `handoff` node routes and closes; there is no advisory capability.
- *"Manejo del lead nutrible: 15%"* of the evaluation weighting — the nurture path is a
  single farewell message. `proposal.md` lists "Marketing / nurturing content strategy"
  as out of scope.

Rubric weighting from the brief, for prioritization:
Calidad del perfilamiento 30% · Reducción del ruido comercial 20% · Innovación y
escalabilidad 20% · Manejo del lead nutrible 15% · Experiencia de usuario 15%.

### DOC-002 — README describes a different application

`README.md:14-25` under *What works*:

> - SSE streaming endpoint (`GET /conversations/{id}/messages/stream`).

and under *What is explicitly NOT done yet*:

> - **No channel adapters.** Only HTTP/SSE is exposed; a WhatsApp webhook router is
>   stubbed at `app/routers/webhook.py`.

Verified against `app/main.py:53-54`:

```python
app.include_router(health.router)
app.include_router(whatsapp.router)
```

There is no conversations router and no SSE route — `AgentService.stream_message`
exists (`app/services/agent_service.py:89`) but nothing mounts it. There is no
`app/routers/webhook.py`. WhatsApp is fully implemented and is the *only* channel.

Both claims are wrong, in opposite directions. This is not cosmetic:
`specs/demo-deployment/spec.md` makes the README a MUST-carrying artifact
("The README MUST contain a juror demo walkthrough under 5 minutes") and the brief
lists `README < 5min` as a deliverable.

---

## 5. Warnings

**DATA-009 — `tipo_documento` domain.** Source offers five distinct values:
`Cédula de ciudadanía`, `Cédula de extranjería`, `Pasaporte`, `Permiso Especial de
Permanencia`, `Permiso por Protección Temporal`. The design's validator is
`(CC|CE|TI)` (`design.md:177`) — `TI` is not in the source at all, and PEP/PPT/Pasaporte
are unrepresented. PPT holders are a significant Colsubsidio housing population.

**DATA-010 — `estado_civil` domain.** Source offers six: `Soltero`, `Casado`,
`Divorciado`, `Union libre`, `Separado`, `Viudo`. Design handles three. A `Divorciado`,
`Separado` or `Viudo` lead falls through `_route_estado_civil`'s final `return
"recoger_empleo"`, skipping PAC/discapacidad/otra_caja collection entirely, and
`_derive_cabeza_de_hogar` returns `False` for them — arguably the exact population most
likely to be cabeza de hogar.

**DATA-011 — decimal format.** Areas are stored with comma decimals (`56,29`, `60,6`).
`Numeric(10,2)` ingestion needs an explicit parse step; no artifact mentions it.

**DATA-012 — the afiliados sheet is empty.** `Afiliados Colsubsidio` has a header row
plus the credit-band legend and **zero data rows**. All 15 mock afiliados are invented,
which the proposal does say ("15 mock afiliados") — but it means
`specs/seed-and-bootstrap/spec.md`'s "the distribution covers all three categoria
values and a sample of credit bands" is unconstrained by any source. Also note the
header contains draft artifacts: `numero_documento2`, `Columna14`.

**DATA-013 — `Caja de Compensación` is enumerated.** The sheet lists 30+ named cajas
(Cafam, Compensar, Colsubsidio, Comfacundi, Comfaboy, Comfama, …). The design models
`otra_caja_compensacion` as free-text `String(150)`. Free text makes the
"already has another caja" regulatory branch unanalyzable.

**LOGIC-005 — dead bonus in Bucket 6.**
```python
est_pts = {">3y": 15, "1-3y": 10, "<1y": 5}.get(ant, 5) + 3   # +3 empleado bonus
est_pts = min(est_pts, 15)
```
`>3y` → `15+3 → min → 15`. The bonus is swallowed for the top tier; it only affects
`1-3y` (13) and `<1y` (8). Either the cap or the bonus is wrong.

**LOGIC-006 — `classification` domain contradiction.**
`specs/agent-tools/spec.md` (*classify_lead persists verdict*): "`classification` is
one of {`ready`, `nurture`} (with `nurture_social` reflected via
`status='nurture_social'`)". `specs/lead-scoring/spec.md` (*NURTURE_SOCIAL threshold*):
"THEN `classification='nurture_social'`". Two spec files, same field, different domains.

**LOGIC-007 — `rango_salarial` gating ignored.** The spreadsheet's `Condicion` row for
that field reads `Preguntar solo si es empleado y NO es afiliado Colsubsidio`. The
design collects it in all four capacity bundles (`design.md:184-187`), including for
afiliados whose salary is already known from `salario_base_cotizacion`. Redundant
questions cost UX (15% of the rubric).

**LOGIC-008 — status transition rule unenforced.** `specs/lead-data-model/spec.md`
requires that terminal statuses never revert. No design element owns this;
`save_lead`'s "MUST NOT promote status" is a different guarantee.

**RES-001 — destructive default.** `design.md:582`:
> `init_db` in lifespan MAY unconditionally drop the `leads` table … via a best-effort
> `DROP TABLE IF EXISTS leads CASCADE` before `create_all`, but only when running in
> development mode, controlled by `settings.app_env == "development"`.

`app_env` defaults to `development` in `app/core/config.py:28`, in `.env.example:1`,
and in `docker-compose.yml`. Every restart destroys the auditable artifact the change
exists to produce. It also contradicts `specs/seed-and-bootstrap/spec.md`
("no destructive DROP unless the script opts in").

The same section is internally inconsistent: "No env flag, no opt-in" followed by
"The Design does NOT add the `DROP TABLE` to runtime code here — only the policy",
with the whole thing hedged as `MAY`. Apply has no decision to implement.

**RES-002 — `/health` is not a readiness check.** `app/main.py:33-39` swallows
`init_db()` failures with a warning. The app boots with no tables and answers
`GET /health` with 200 — which is exactly what `specs/demo-deployment/spec.md` scenario
*API reachable at public Fly URL* asserts. The deployment spec can pass against a
completely non-functional database.

**RES-003 — the design's own tests are unreachable.** `design.md:590` puts all three
smoke harnesses under `scripts/tests/`. `pyproject.toml:40` sets
`testpaths = ["tests"]`, and `openspec/config.yaml` sets both apply and verify
`test_command: "pytest -q"`. Verify will run 4 pre-existing smoke tests and report
green without executing the scorer matrix, the graph traversal, or the seed
idempotency check.

**RES-004 — the Docker image cannot seed.** `Dockerfile:17-18` copies only
`pyproject.toml`, `README.md`, and `app/`. `scripts/` (the seed) and `docs/` (the
source spreadsheet) are excluded. The Fly deploy required by `demo-deployment` would
ship an app that cannot populate its own reference data.

**CODE-002 — duplicate settings field.** `app/core/config.py:56-57` declares
`whatsapp_api_version` twice; the second silently wins. Symptomatic —
`openspec/config.yaml` sets `linter: false`, `type_checker: false`, `formatter: false`.
Also note the stray de-indentation of the `# ── WhatsApp ──` comment at line 52.

**SDD-008 — unauditable decision provenance.** `design.md:71`, `:303` and `:480` cite
"Engram #258" as the source of locked decisions ("fork B, locked", "Engram #258 Bucket
6 said −20; the user overrode that"). None of it is readable from the repository. If
Engram is lost, the rationale for the change's central rules is lost with it.

---

## 6. Suggestions

**SDD-009** — `design.md:633` leaves an unchecked open question: the full
`ProyectoColsubsidioEntity` column list, deferred to apply. The sheet's 12 columns are
now known (see Appendix A) — close it in the design so tasks can be estimated.

**DOC-003** — three Postgres credential sets: `.env.example` (`postgres`/`123456789`),
`app/core/config.py` defaults (`vivi`/`vivi`), `docker-compose.yml` (`vivi`/`vivi`).

**SDD-010** — `openspec/config.yaml:3` sets `artifact_store: both`, but the repository
carries no Engram trace, which is the mechanical cause of SDD-008.

---

## 7. Recommended order of work

1. **Reconcile sources before touching the design.** The spreadsheet and the flow
   diagram disagree on who gets asked about `subsidio_vivienda_anterior`,
   `numero_pac` and `condicion_discapacidad_familiar`. Pick one, record why.
   Resolves LOGIC-001 and LOGIC-004.
2. **Rewrite the field domains from the spreadsheet**, not from invention. Every value
   list in §7 of the design should be a copy of a source option list, or an explicitly
   documented normalization of one. Resolves DATA-001 through DATA-005, DATA-009,
   DATA-010.
3. **Amend the specs** for SDD-003, SDD-004, DATA-007, DATA-008 and LOGIC-006. Do not
   leave these as design-prose resolutions.
4. **Add a municipio normalization table.** Resolves DATA-006.
5. **Decide the 90/10 rule.** It is non-negotiable in the brief and absent from every
   artifact. Resolves SDD-007.
6. **Pin the dependency manifest** and generate a lockfile. Resolves SDD-005; makes
   LOGIC-002 verifiable.
7. **Write `tasks.md`.** Resolves SDD-001, unblocks apply.
8. Fix CODE-001, SEC-001, SEC-002, CODE-002 — these are in shipped code and independent
   of the change.
9. Rewrite the prompt text (DOC-001) and the README (DOC-002).

---

## Appendix A — verification method

No `openpyxl`/`pandas` in the environment, so the workbook was read with stdlib
`zipfile` + `xml.etree` (an `.xlsx` is a zip of XML parts). Scripts used:

- `xlsx_dump.py` — resolves `xl/workbook.xml` → `xl/_rels/workbook.xml.rels` to get
  sheet order and targets, loads `xl/sharedStrings.xml`, and expands each `<c r="B7">`
  into a dense row via column-letter arithmetic (so blank cells keep their position —
  essential here, since the Leads sheet stores each field's option list in the
  placeholder column adjacent to its `Campo BD` label).
- `verify_claims.py` — asserts each falsifiable claim and prints the actual value.

Both live in the session scratchpad:
`/tmp/claude-1000/-home-frank-Documentos-vivi-Vivi-api/449d541d-ed96-4b22-888d-53692dc8f1d5/scratchpad/`

Key output:

```
[proyectos] DATA ROWS = 44   (spec claims 43)
[proyectos] columns = ['Proyecto', 'Tipo', 'Municipio', 'Ubicación', 'Dirección',
            'Descripción', 'Modelo', 'area_construida_m2', 'area_privada_m2',
            'cantidad_ habitaciones', 'cantidad_baños', 'Valor viviendas VIS en SMMLV']
[proyectos] rows where privada > construida = 1 -> [(4, 'VERSALLES', 'E', '56,29', '60,6')]
[proyectos] VIBO ONCE rows = [('VIS', 'Bogota', 'A'), ('VIS', 'VIS', 'B2')]
[proyectos] rows with EMPTY Modelo = ['ABETO', 'LA ARBOLEDA']
[proyectos] duplicate (proyecto, modelo) pairs = {}
[proyectos] DISTINCT municipio = ['Bogota', 'Chía', 'Girardot', 'Ricaurte', 'Soacha',
                                  'Tocancipá', 'Ubate', 'VIS']
[proyectos] DISTINCT tipo = ['NO VIS', 'VIS']
[afiliados] DATA ROWS (cols 0-13 non-empty) = 0
```

The flow diagram is a draw.io export (`{"version": "31.0.2", "pages": [...]}`);
61 cells of `type: "node"` carry a `label`. Cells whose `parent` is an edge id are edge
labels (`SI`/`NO`), not nodes — both were extracted and separated.

### Source field domains (Leads sheet), verbatim

| Field | Options |
|---|---|
| Tipo de documento | Cédula de ciudadanía · Cédula de extranjería · Pasaporte · Permiso Especial de Permanencia · Permiso por Protección Temporal |
| Afiliado Colsubsidio | SI · NO |
| Categoria | A · B · C |
| Estado civil | Soltero · Casado · Divorciado · Union libre · Separado · Viudo |
| Empleado o independiente | Termino fijo · Termino indefinido · Prestacion de servicios |
| Rango salarial | 2 millones o menos · 2 a 4 millones · 4 a 8 millones · 8 a 10 millones · mas de 10 millones |
| Antigüedad laboral | Menos de 1 año · 1 a 2 años · Mas de dos años |
| Tiene vivienda propia | SI · NO *(an adjacent orphan column offers Arrendada · Propia)* |
| Ahorros o cesantias | No tengo ahorros. · Menos de $3 millones · Entre $3 y $10 millones · Entre $10 y $20 millones · Entre $20 y $40 millones · Más de $40 millones |
| ¿Usted o su pareja han recibido…subsidio? | SI · NO |
| Lugar de elección para vivir | Bogotá norte · Bogotá centro · Bogotásur · Soacha · Chía · Tocancipá · Girardot · Ricaurte · Ubaté |
| ¿En cuánto tiempo deseas comprar…? | 3 meses · 6 meses · 1 año · 2 años · No sé |
| Caja de Compensación | Cafam · Compensar · Colsubsidio · Comfacundi · Comfaboy · Comfama · … (30+) |

### Source gating rules (Leads sheet, `Condicion` row), verbatim

| Field | Condicion |
|---|---|
| Nombre y apellido | Solo si NO es afiliado Colsubsidio |
| Categoria | Solo si es afiliado Colsubsidio |
| Otra caja de compensación | Solo si NO es afiliado Colsubsidio |
| Edad | Solo si NO es afiliado Colsubsidio |
| Rango salarial | Preguntar solo si es empleado y NO es afiliado Colsubsidio |
| Total ingresos mensuales | Preguntar solo si es soltero |
| Total ingresos familiares mensuales | Preguntar sólo si esta casado o en unión libre |
| ¿Usted o su pareja han recibido…subsidio? | Preguntar si es casado o UL |
| Cabeza de hogar | Si es casado o UL *(question note: "Si es soltero o casado y tiene PAC entonces SI")* |

### Credit bands (Afiliados sheet legend) — matches `design.md:365` exactly

```
150 a 499 pts: Malo / Riesgo Alto        500 a 649 pts: Regular / En construcción
650 a 699 pts: Aceptable / Riesgo Medio  700 a 749 pts: Bueno
750 a 799 pts: Muy Bueno                 800 a 950 pts: Excelente / Premium
```

`700 a 749 puntos — Bueno — Alta. Perfil confiable. **Umbral mínimo recomendado para
créditos hipotecarios.**` — the source names 700 as the mortgage threshold. No artifact
uses it; it is a stronger, domain-sourced gate than the team-invented `score >= 60`
(flagged in `proposal.md` §6 as "our own design (no domain data)").
